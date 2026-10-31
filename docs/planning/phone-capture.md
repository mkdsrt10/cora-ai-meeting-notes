# Phone Capture over Tailscale (Mac Studio always-on): Design (rev 2)

Track: phone-capture. Branch: `production`. Date: 2026-10-17. Status: revised after three adversarial reviews; ready for owner decisions (§21).
Inputs: `remote_headless.json`, `remote_tailscale_ios.json`, plus reads of `python/api/{http,auth,router}.py`, `python/{server,policy,paths,db,voice_memo_pipeline}.py`, `src/main/{api-client,paths}.js`, `src/main.js`, `package.json`. Spot-checked in this revision: `voice_memo_pipeline.py` (`discover()` is `rglob` over `voice_memos_source` and INBOX and accepts dot-files; baseline loop at 516-539 matches anything under `voice_memos_source`, which defaults to INBOX; `main()` flock is `LOCK_NB` and exits 0), `db.get_unprocessed_recording` (newest NULL-model row, `LIMIT 1`), `db.log_notification` (inserts a row only), `index.html` (18 `<script>` tags, not 17), `recordings.py` (no `recording_progress()` helper exists; enhanced-notes provider can be non-local).

---

## 0. TL;DR

* **Shape.** A second tiny loopback listener (the "mobile gateway", `127.0.0.1:8767`, same Python process as `server.py`) is published with `tailscale serve` on a **non-Funnel HTTPS port (default 9443)**, so a mistyped `tailscale funnel` cannot publish it (Funnel only exists on 443/8443/10000; verified in WP0). The main API on 8765 is untouched: `authorize()` in `http.py` gets zero edits.
* **v1 is a deliberately small "Week-1 slice"** that gives the daily loop: Voice Memos, Share, Shortcut "Send to Cora", Mac, notes, and a second Shortcut "Latest Note". Gateway has 5 routes, one token type (upload plus optional read-own), no static serving, no cookies, no pairing, no PWA, no `read-all`, no Settings UI (CLI instead), no Electron changes. Everything else is v1.1 after launch, gated on WP0 device evidence (§20). The cut line removes attack surface, not only effort.
* **Upload returns 202 as soon as the bytes are staged, hashed and fsynced** in `DATA_DIR/mobile_staging/` (outside INBOX). Probing, normalising and archiving happen in the worker (`received`, `normalizing`, `queued`, ...). ffmpeg/ffprobe only ever see magic-byte-sniffed files with a forced format whitelist, `-protocol_whitelist file,pipe`, `file:` inputs, no stdin, an empty cwd, rlimits and timeouts.
* **PipelineWorker runs each job as a subprocess** (`python/pipeline_job.py <folder>`) with a wall-clock timeout and an attempts cap, defers while a live Mac recording is pending, yields to UI-initiated work, and forces local ASR/notes for phone audio (decision made: force-local in v1).
* **Lockdown: mobile is always blocked under `enterprise_lockdown` in v1.** No env override. Tailscale's own control-plane/DERP traffic is not Cora-originated, so the claim is "adds no Cora-originated outbound path".
* **Audit:** SQLite `mobile_audit` row written in the same transaction as the state change; fail-closed; plain JSONL mirror. No hash chain in v1 (an unkeyed chain proves nothing against a same-user writer; HMAC chain with Keychain key is v1.1 if an auditor asks).
* **Mac runtime in week 1:** run the existing Electron app as a macOS Login Item on the Mac Studio (auto-login, no sleep). No headless LaunchAgent, no attach refactor in v1; the secure attach handshake is specified for v1.1 (§11.2).
* **Effort:** about 7.75 agent-days (critical path about 6), plus owner hands for WP0, Tailscale/Mac Studio setup and a one-week dogfood. Previous draft: 19.75 days.

---

## 1. Goals, non-goals, constraints

Goals (owner (e)): run Cora on an always-on Mac Studio; send voice notes from iPhone over Tailscale; read the resulting notes on the phone; keep transcription local.

Non-goals (v1): PWA recorder and reader; pairing codes/QR; cookie sessions; `read-all`; speaker-separated "conversation" notes from a phone (single-track audio labels everyone "You"; cut rather than ship wrong attribution); push notifications (APNs/Web Push are outbound dependencies); Android; multi-user sharing; plugins or the main UI on the phone; Apple Watch; headless LaunchAgent and Electron attach (v1.1).

| Constraint | How |
|---|---|
| Never weaken main API loopback/token/Host/Origin | Separate listener and handler; zero edits to `authorize()`; behavioural regression tests (ts.net Host/Origin still 403, token still required). No hash pin of `http.py` (brittle, bypassed by rebase) |
| `enterprise_lockdown` blocks every outbound path incl. plugins | Mobile is hard-blocked under lockdown (no override). When enabled, Cora originates no outbound connection from this feature; job subprocess forced local; ffmpeg protocol whitelist keeps media tooling from opening sockets; plugins have no gateway access. `tailscaled` itself talks to Tailscale infrastructure; that is outside Cora and listed as a gap (§15) |
| Local default | Feature off by default; phone audio always processed locally in v1 |
| No real meeting data in launch assets | Launch screenshots/video use `tools/seed_demo_data.py` data and a fictional hostname; smoke tool has a `--demo` fixture |
| SOC 2 Type 2 in progress | Scoped revocable tokens with expiry, audited events, fail-closed audit, change-managed flag, honest control mapping (§15) |
| HIPAA / DoD | Default-restrictive: upload-only tokens by default, read-own opt-in per token, no filenames stored, `no-store`, generic errors, lockdown (DoD segment) blocks the feature, docs on passcode/MDM and iCloud Voice Memos |
| Solo founder, 4-5 weeks | Week-1 slice about 7.75 agent-days; stdlib only; no new Python deps; no new JS |

---

## 2. Scope tiers and cut line

**v1 (Week-1 slice, launch-gated; this is what ships):**

1. Policy gate (`mobile_ingress_allowed`), config/store/audit tables, device tokens.
2. Gateway with exactly 5 routes (§8), layered network checks, per-device rate/quota limits.
3. Streaming upload to staging, sha256, fsync, 202; dedupe with explicit failed-to-requeue.
4. Worker: hardened probe/normalise, archive via `run_once`, subprocess processing, single-flight, priority, backoff.
5. Mac runs Electron as Login Item; owner admin through `tools/cora_mobile.py` (talks to new owner routes `/api/mobile/*` on 8765 with the owner token).
6. Shortcut "Send to Cora" and "Cora: Latest Note" recipes; doctor with 4 failing checks plus 2 warn-only.

**v1.1 (after launch, each gated on WP0 evidence and dogfood):** PWA recorder (needs mic persistence and cookie/partitioning answers; the draft's own research says iOS web capture can silently lose audio), PWA notes reader, pairing codes/QR, cookie mode, `read-all`, Settings UI (renderer), headless LaunchAgent plus Electron attach plus SIGTERM fix, HMAC audit chain with verify/CSV UI, unix-socket serve target, process-split gateway, per-device opt-in cloud engine, speaker handling for conversation notes. Designs for these (with the review fixes folded in) are in §20 so nothing is lost, but none is on the critical path.

**Attack-surface effect of the cut:** no static file serving, no cookie/CSRF logic, no token in IndexedDB, no pairing endpoint to brute-force, no `read-all` PHI path, no new renderer UI (so no new stored-XSS sink in the Electron renderer that holds the owner cookie), no change to `src/main.js` (the Product Hunt build path).

---

## 3. Architecture

```
iPhone (Tailscale app, untagged)       Shortcut "Send to Cora" / "Cora: Latest Note"
        |  HTTPS over WireGuard tailnet (cert from tailscaled)
        v
Mac Studio: tailscaled --serve--> https://studio-x.tailNNNN.ts.net:9443
                                   | (Host/Origin preserved; Serve sets Tailscale-User-*, X-Forwarded-*)
                                   v
              127.0.0.1:8767  MOBILE GATEWAY (GatewayHandler, own route table)
                                   |
  +--------------------------------+---------------------------------------------+
  | python/server.py (Electron-spawned, Login Item)                              |
  |   127.0.0.1:8765  MAIN API (unchanged; owner token; Electron/CLI only)       |
  |   mobile.store / upload / views / audit                                      |
  |   PipelineWorker thread --> run_once() (flock) --> pipeline_job.py subprocess |
  +------------------------------------------------------------------------------+
        ^ owner token only: tools/cora_mobile.py (v1), Settings UI (v1.1)
```

**Process boundary decision.** v1 keeps the gateway in-process: it shares `db`, `policy`, the lock and the worker without IPC. This is a weaker boundary than the draft claimed: the handler class and route table separate routes, not memory. A logic or parsing bug in upload handling runs in a process that holds the owner API token, DB access and Keychain access. This is acceptable in v1 because (a) the only parser of untrusted bytes is a length-delimited copy loop (media parsing is in hardened subprocesses), (b) lockdown (the DoD/regulated posture) blocks the feature entirely. **Trigger to split:** before mobile is ever permitted under lockdown, before any `read-all`/PWA surface ships, or when any regulated customer is onboarded onto it. Split design: gateway as a sibling process owned by the same LaunchAgent, with ingest via a 0600 unix-socket "ingest" interface (stage path in, row id out). The `mobile/` package therefore imports only `db`, `paths`, `policy` and neutral helpers, never `api.*`. No `db` import of `mobile` either (circular): `server.py` calls `mobile.store.init_tables()` after `db.init_db()`.

Why not 8765: `tailscale serve` preserves client `Host`, so `authorize()` correctly 403s it; loosening it re-opens DNS rebinding on credentials/settings/capture routes. Rejected.

Why 9443, not 8443: 443/8443/10000 are the only Funnel-capable ports. Serving on 9443 makes Funnel structurally impossible for this service, instead of relying on a 5-minute watchdog. **WP0 gate:** confirm `tailscale serve --https=9443` is accepted and Safari/Shortcuts send `Host: fqdn:9443` consistently. If not accepted, fallback is 443 with a tailnet policy that removes `funnel` nodeAttr, with the request-time header check as the primary control (§12.3).

Doctor must also **fail** if any serve/funnel handler on any port targets `127.0.0.1:8765` (the main API), not only the gateway port. `authorize()` would 403 it, but it is a misconfiguration to flag.

---

## 4. Module and file map

New package `python/mobile/` (imports `db`, `paths`, `policy` only):

| File | Responsibility |
|---|---|
| `config.py` | `load()/save(patch)`, validation; stored in dedicated table (§6), not the `settings` table |
| `store.py` | `init_tables()`, devices/uploads/quota/audit CRUD |
| `tokens.py` | mint/verify/rotate device tokens, hashing, constant-time compare |
| `audit.py` | `record(event, **fields)` in the caller's transaction + JSONL mirror (0600); fail-closed |
| `netcheck.py` | layered header/host/origin/login checks (§7) |
| `gateway.py` | `GatewayHandler`, `GatewayServer`, `GATEWAY_ROUTES` |
| `upload.py` | streaming receive to staging, caps, quotas, dedupe/requeue |
| `media.py` | magic sniff, hardened `probe()` and `normalize()`; the only module that spawns ffmpeg/ffprobe |
| `views.py` | `latest_note()`, `get_note()`, `upload_status()` (verbatim `enhanced_notes.md`, no structured projection in v1) |
| `tailscale.py` | read-only CLI wrapper, `doctor()` |
| `runtime.py` | `start/reload/stop/status`, lockdown gate, baseline, worker + watchdog lifecycle, GC |
| `python/pipeline_worker.py` | generic `PipelineWorker`, `PROCESS_LOCK`/`exclusive()`, priority gate |
| `python/pipeline_job.py` | thin subprocess entry: `process_recording_local(Path(folder))` with forced-local env |
| `python/api/routes/mobile.py` | owner-only management routes on 8765 (§8.2) |
| `tools/cora_mobile.py` | owner CLI (status, enable, mint-token, rotate, revoke, devices, uploads, doctor, audit [--csv]); reads `.api_token`; stdlib only |
| `tools/mobile_smoke.py` | simulates a phone with forged Tailscale headers (by design; documents that headers are hygiene only) |
| `docs/PHONE_CAPTURE.md`, `docs/shortcuts/SEND_TO_CORA.md` | setup, tailnet policy sample, availability (sleep/auto-login/Login Item) in one place, regulated-use notes, evidence note |

Edits to existing files (bounded list):

| File | Edit |
|---|---|
| `python/policy.py` | `mobile_ingress_allowed()` (§14) |
| `python/server.py` | call `mobile.store.init_tables()` and `mobile.runtime.start()`; stop on exit |
| `python/api/routes/__init__.py` | import `mobile` routes module |
| `python/api/routes/recordings.py` | wrap **every** local MLX/LLM entry in `pipeline_worker.exclusive(ui=True, wait=...)`: `/api/process-recording` local branch, summary variant, enhanced notes, re-enhance (all call `generate_*`/load `mlx_lm` today without a lock); on `Busy` return 503 `busy` |
| `python/db.py` | `get_unprocessed_recording` excludes phone rows: `AND COALESCE(json_extract(metadata,'$.live_recording_id'),'') NOT LIKE 'm\_%' ESCAPE '\'` (keyed on the server-generated stem set at archive time, race-free; fixes Electron's `diarizeLatestRecording` picking a phone note ahead of the Mac meeting that just ended and double-processing it) |
| `python/voice_memo_pipeline.py` | (1) extract the baseline loop (516-539) into `ensure_baseline(config, state, files)` called by `run_once` (behaviour-preserving); (2) `main()` waits for the flock up to 60 s (poll `LOCK_NB` every 2 s) instead of exiting 0, so Electron's post-stop archive pass is not silently skipped while the worker holds the lock |
| `python/pipeline/cloud_asr.py` (+ the notes-provider selection in `local_meeting_pipeline`) | honour `VOICECOACH_FORCE_LOCAL=1` (set only by `pipeline_job.py`): skip Gemini ASR and frontier notes providers. WP5 enumerates every outbound call in the `process_recording_local` chain and tests it with a non-local engine configured |

No edits to: `src/main.js`, `src/main/api-client.js`, `http.py`, `settings.py`, `package.json`, renderer files (v1).

---

## 5. Configuration

Dedicated table `mobile_config(key TEXT PRIMARY KEY, value TEXT)`, one row `config` (JSON), written only by `mobile.store.save_config()` via `POST /api/mobile/config`. It is deliberately not in the `settings` table: the generic `POST /api/settings` (`settings.py:243`) writes any key, a prefix denylist is fragile, and the MCP server or dataset import must not be able to flip `enabled` or `allowed_logins`. Tests: generic settings POST with key `mobile_config`/`mobile_*` cannot change mobile behaviour; `python/mcp_server.py` has no tool that writes this table; dataset import/restore do not touch `mobile_*` tables.

```json
{
  "enabled": false,
  "tailscale_fqdn": "studio-x.tailNNNN.ts.net",
  "serve_port": 9443,
  "listen_port": 8767,
  "allowed_logins": ["owner@example.com"],
  "max_upload_mb": 200,
  "max_duration_h": 4,
  "max_device_daily_mb": 1024,
  "max_uploads_per_device_hour": 20,
  "inbox_cap_gb": 5,
  "max_queue_depth": 20,
  "delete_inbox_after_archive": true,
  "token_ttl_days": 90,
  "audit_retention_days": 400,
  "keep_awake": true
}
```

Validation in `save()`: `tailscale_fqdn` matches `^[a-z0-9-]+(\.[a-z0-9-]+)*\.ts\.net$` (lowercased, trailing dot stripped); `allowed_logins` non-empty to enable; `listen_port` loopback only; `serve_port` not in `{443, 8443, 10000}` unless the owner passes `acknowledge_funnel_capable_port` (warn); `max_upload_mb <= 512`; `max_duration_h <= 6`; `token_ttl_days <= 365`. Caps are sized for **Compressed** Voice Memos (a 60 min AAC memo is 30-60 MB); Lossless runs 5-10 MB/min and exceeds the cap, so the recipe says to use Compressed.
`enabled=true` is refused 403 `lockdown` when `policy.mobile_ingress_allowed()` is false. Admin hard-off: `config.json` `"mobile_disabled": true`.
When `allowed_logins` shrinks, every device whose `bound_login` is no longer allowed is revoked immediately (`revoked_by='allowlist'`, audited).

---

## 6. Data model (SQLite `voicecoach.db`, `CREATE TABLE IF NOT EXISTS`; DB and JSONL files `chmod 0600` explicitly by the code that creates them)

```sql
CREATE TABLE IF NOT EXISTS mobile_devices (
  id            TEXT PRIMARY KEY,            -- 8 hex, token prefix
  name          TEXT NOT NULL,               -- server-sanitised printable allowlist [A-Za-z0-9 ._'()-], max 60
  kind          TEXT NOT NULL,               -- 'shortcut' (v1) | 'pwa' (v1.1)
  token_hash    TEXT NOT NULL,               -- sha256 hex of secret part
  scopes        TEXT NOT NULL,               -- JSON: upload | read-own   (read-all is v1.1)
  bound_login   TEXT NOT NULL,               -- Tailscale login chosen at mint; mismatch => rejected
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL,
  last_seen_at  TEXT,                        -- written at most once/minute per device
  last_ip       TEXT,                        -- validated tailnet address only
  last_login    TEXT,                        -- sanitised, validated email-ish
  revoked_at    TEXT,
  revoked_by    TEXT,                        -- owner | device | expiry | allowlist | rotation
  rotated_from  TEXT
);

CREATE TABLE IF NOT EXISTS mobile_uploads (
  id            TEXT PRIMARY KEY,            -- m_<UTC yyyymmddThhmmss>_<8hex>; staging/inbox stem; metadata.live_recording_id
  device_id     TEXT NOT NULL REFERENCES mobile_devices(id),
  client_id     TEXT,                        -- X-Cora-Client-Id (optional for Shortcut)
  sha256        TEXT NOT NULL,
  bytes         INTEGER NOT NULL,
  source        TEXT NOT NULL DEFAULT 'shortcut',
  received_at   TEXT NOT NULL,
  recorded_at   TEXT NOT NULL,               -- client-supplied (Shortcut Creation Date), clamped to [now-90d, now+5min]
  duration_s    REAL,
  status        TEXT NOT NULL,               -- received|normalizing|queued|archiving|archived|processing|done|failed
  recording_id  TEXT,
  error_code    TEXT,                        -- e.g. unreadable_audio, archive_failed, processing_timeout, lost, stalled
  attempts      INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT,
  updated_at    TEXT NOT NULL,
  UNIQUE(device_id, client_id),
  UNIQUE(device_id, sha256)
);
CREATE INDEX IF NOT EXISTS mobile_uploads_status ON mobile_uploads(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS mobile_quota (        -- counts attempts including rejected ones
  device_id TEXT NOT NULL, day TEXT NOT NULL, bytes_declared INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (device_id, day)
);

CREATE TABLE IF NOT EXISTS mobile_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, event TEXT NOT NULL,
  device_id TEXT, login TEXT, ip TEXT, method TEXT, path TEXT /* template, no query */,
  status INTEGER, recording_id TEXT, bytes INTEGER, detail TEXT /* short enum, never content */
);
CREATE INDEX IF NOT EXISTS mobile_audit_ts ON mobile_audit(ts);

CREATE TABLE IF NOT EXISTS mobile_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

Token: `cora_dev_<id8>_<secret>`, `secret = secrets.token_urlsafe(32)`; only `sha256(secret)` stored; verify with `hmac.compare_digest`, then `revoked_at IS NULL`, `expires_at > now`, `bound_login == Tailscale-User-Login`. Token read is per request (revocation immediate); only the `last_seen_*` write is throttled to once a minute to avoid contending with worker writes (`get_db()` opens a new connection per call).

Lifecycle: mint returns the token once (CLI stdout). **Rotate**: `rotate` mints a replacement and sets the old token's `expires_at = now + 24 h` (`revoked_by='rotation'` at expiry) so the Shortcut can be edited without a dead window. Expiry warning: `status`/doctor list tokens expiring within 14 days, and upload/latest responses include `token_days_left` so the recipe can notify the user under 14 days. No sliding renewal for Shortcut tokens (plaintext in an iCloud-synced Shortcut; rotation is the control).

Retention: audit 400 days (config; note to HIPAA customers that device IP/login in SQLite and JSONL is personal data with that retention); `mobile_uploads` rows kept while the recording exists; GC in §10.5.

---

## 7. Gateway request pipeline (`netcheck.py`, first thing for every request)

On any failure respond 403 `{"error":"forbidden"}` (uniform body; reason goes to audit `detail` and to an in-memory ring of the last 20 reject reasons exposed to the owner at `/api/mobile/status.last_rejects`, so a Safari/Shortcut `Host` mismatch is debuggable without weakening the response). Order:

| # | Check | Real control or hygiene |
|---|---|---|
| 1 | `client_address[0] == "127.0.0.1"`; server binds 127.0.0.1 only, `GatewayServer.__init__` raises otherwise | hygiene (any local process satisfies it) |
| 2 | No `Tailscale-Funnel-Request`; `Tailscale-User-Login` present | **primary Funnel guard** (§12.3); header set by Serve, not forgeable from the tailnet |
| 3 | `Host` equals `fqdn:<serve_port>` exactly (`fqdn` alone only if port 443) | hygiene vs local forger; real vs DNS rebinding from a browser |
| 4 | `X-Forwarded-Proto == https`; `X-Forwarded-For` single tailnet address (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`) | hygiene |
| 5 | `Origin` absent or exactly `https://fqdn:<serve_port>` | hygiene/real vs browsers |
| 6 | `Tailscale-User-Login` (RFC 2047 decoded, lowercased) in `allowed_logins` | real against other tailnet users; forgeable by a local process |
| 7 | Method `GET`/`POST` only | real |
| 8 | Failed-auth throttle keyed on **(login, ip)** with exponential backoff (429 only for the throttled key, never a global lock); in-memory (restart resets; acceptable because tokens are 256-bit) | hygiene |
| 9 | Route lookup (404 after 1-7) then `Authorization: Bearer cora_dev_...` verify; reject if `bound_login != login` | **the only real control against a local attacker** |
| 10 | Scope check | real |
| 11 | Per-device limits: 120 req/min; uploads per §9 | real |
| 12 | Audit | n/a |

Honest statement for the evidence binder: steps 1-6 are all forgeable by any process on the Mac (`tools/mobile_smoke.py` forges them by design); they defend against the tailnet, browsers and mistakes. Against a local attacker the device token is the control; same-user malware is out of model (it can read the DB). **WP0 probes** whether `tailscale serve` accepts a `unix:/path` target; if so, an optional mode binds the gateway to a 0600 unix socket (`DATA_DIR/mobile.sock`) and step 1 becomes a peer-uid check, removing other-local-user forgery. Default stays loopback TCP.

Responses: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `Strict-Transport-Security`. No HTML in v1, so no CSP is needed (v1.1 PWA CSP in §20). `GatewayHandler.timeout = 60` (idle), `protocol_version = "HTTP/1.0"`, `daemon_threads`, `request_queue_size = 16`. `log_message` logs method, path template and status only. Errors are fixed codes, never `str(exc)` (main API leaks paths this way at `http.py:120-139`). Slow-loris test uses a 1 s timeout to prove `Handler.timeout` is honoured by `ThreadingHTTPServer` (the main API sets none, so no existing pattern is reused).

---

## 8. Routes

### 8.1 Gateway (phone-facing; complete list; all else 404, including `/`, `/m/` and any `/api/*`)

| Method | Path | Auth | Scope | Notes |
|---|---|---|---|---|
| GET | `/m/api/ping` | net only | - | `{"ok":true}` |
| POST | `/m/api/upload` | token | `upload` | §9 |
| GET | `/m/api/uploads/<id>` | token | `upload` | status of an upload id (own only): `{status, error_code?, token_days_left}`; no PHI |
| GET | `/m/api/notes/latest` | token | `read-own` | newest **own** upload that is `done`: `200 text/plain` markdown of `enhanced_notes.md`; if newest own upload is not done: `202 {"status":...}`; none: `404` |
| GET | `/m/api/notes/<id>` | token | `read-own` | same, by upload id; maps `mobile_uploads.id` to `recording_id` to folder; ownership by `device_id` |

Every file read resolves with `resolve().relative_to(RECORDINGS_DIR)` and is rejected otherwise. Responses carry markdown text only: no titles, `recording_name`, `source_file`, `archived_file`, folder paths or Apple Voice Memos titles. The forbidden-key/string test runs against the real fixture output (including those names). Note reads are audited with the recording id; `uploads/<id>` polls return no PHI and are counted by rate limits but not individually audited.

Never exposed: anything under `/api/*`, `/media*`, settings, credentials, recording control, logs, models, cloud, dataset, people, plugin routes. Plugins cannot register gateway routes.

### 8.2 Owner routes on the main API (`python/api/routes/mobile.py`; owner token only; the gateway cannot reach them)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/mobile/status` | `{allowed, enabled, state, fqdn, listen_port, worker:{alive,queue_depth,current}, devices, last_upload_at, last_rejects[]}`; states: `off, running, blocked_lockdown, blocked_funnel, port_in_use, error` |
| POST | `/api/mobile/config` | validated patch; reloads runtime; audit `config_enabled`/`config_disabled`/`config_change` (changed keys) |
| GET | `/api/mobile/doctor` | §12.2 |
| POST | `/api/mobile/shortcut-token` | `{"name","scopes","login"?}` returns token once; audit `shortcut_token_minted` |
| POST | `/api/mobile/devices/rotate` | `{"id"}` returns new token once; audit `device_rotated` |
| GET | `/api/mobile/devices` | no hashes |
| POST | `/api/mobile/devices/update` | `{"id","name"?,"scopes"?}`; audit `device_updated` |
| POST | `/api/mobile/devices/revoke` / `revoke-all` | immediate; audit `device_revoked` / `revoke_all` |
| GET | `/api/mobile/uploads?limit=` | status/error_code |
| POST | `/api/mobile/uploads/retry` | explicit failed-to-requeue (§9.3) |
| GET | `/api/mobile/audit?limit=&event=&format=csv` | CSV cells starting `=`,`+`,`-`,`@` get a leading `'`; audit `audit_exported` |

All owner mobile routes audit their own use (`runtime_started`, `runtime_stopped`, lockdown denials as `lockdown_denied`). Every string field from a phone or Tailscale header (name, login, ip) is sanitised server-side at write time and, in any renderer UI (v1.1), rendered with `textContent` or `esc()` only.

---

## 9. Upload (`upload.py`)

`POST /m/api/upload`, raw body.

| Header | Required | Meaning |
|---|---|---|
| `Content-Length` | yes | else 411; `Transfer-Encoding` present: 411 (Go's proxy can re-frame length-less bodies as chunked; `BaseHTTPRequestHandler` does not decode them) |
| `Content-Type` | yes | advisory allowlist (`audio/*`, `application/octet-stream`) else 415; truth comes from the magic sniff and probe |
| `X-Cora-Client-Id` | optional | UUID idempotency key |
| `X-Cora-Content-SHA256` | optional | if present, compared with the server hash; mismatch 422 `checksum_mismatch` (transmission integrity, 164.312(c)) |
| `X-Cora-Recorded-At` | optional | ISO-8601 (Shortcut can send the file's Creation Date), clamped to `[now-90d, now+5min]`, else server time |
| `X-Cora-Kind`, `X-Cora-Source`, `X-Cora-Template` | ignored/reserved | `kind` is always `note` in v1 |
| `X-Filename` | ignored | never stored or logged (can contain PHI) |

### 9.1 Algorithm (everything before the 202 is bounded I/O; no ffmpeg in the request thread)

```python
def handle_upload(h, principal):
    length = parse_length(h)                         # 411/400/413 (> max_upload_mb)
    ctype  = check_ctype(h)                          # 415
    admit  = admission(principal, length)            # quotas, caps, queue depth, disk; reserves declared bytes; 429/503/507
    # admission: per-device uploads/hour and per-device daily byte quota (mobile_quota, counts REJECTED attempts too),
    #   global staging+INBOX byte cap (inbox_cap_gb), queue depth <= max_queue_depth (503 + Retry-After),
    #   free space >= 2*length + 5 GiB reserve (507), global semaphore(2) + per-device 1 (503 busy, Retry-After 30)
    try:                                              # semaphore + reservation released in finally on every path
        cid = h.headers.get("X-Cora-Client-Id")
        if cid and (dup := store.find_upload(dev, client_id=cid)) and dup.status != "failed":
            return early_reply(h, 200, {"id": dup.id, "status": dup.status, "duplicate": True})
        part = STAGING / f".{uuid4().hex}.part"       # DATA_DIR/mobile_staging, same filesystem as INBOX (asserted at start), 0600, O_EXCL
        sha = hashlib.sha256(); got = 0
        deadline = time.monotonic() + max(120, min(7200, length / 65536))   # >= 64 KB/s floor, relative to length
        with open(part, "xb", opener=...0o600) as out:
            while got < length:
                chunk = h.rfile.read(min(1 << 20, length - got))
                if not chunk or time.monotonic() > deadline: raise Abort("incomplete_body", 400)
                out.write(chunk); sha.update(chunk); got += len(chunk)
            out.flush(); os.fsync(out.fileno())
        digest = sha.hexdigest()
        check_client_sha(h, digest)                   # 422 checksum_mismatch
        stem = new_stem(); staged = STAGING / f"{stem}.upload"; os.replace(part, staged)
        row, kind = store.accept_upload(dev, cid, digest, got, recorded_at, stem)   # ONE transaction incl. audit row (fail-closed); see 9.3
        return json(202, {"id": row.id, "status": "received", "duplicate": kind == "duplicate", "token_days_left": days_left})
    finally: release()
```

The 202 means "stored, hashed, fsynced; processing will happen". Shortcuts' reported ~30 s timeout and iOS dropping backgrounded fetches no longer interact with ffprobe/ffmpeg time or the semaphore. Probing, normalising and archiving are worker states.

Early responses with an unread body (`early_reply`, also 411/413/415/429/503/507 before any read): send the response with `Connection: close`, `shutdown(SHUT_WR)`, then drain at most 2 MiB for at most 5 s, then close, so the client sees the status instead of a TCP RST. Because Shortcuts cannot probe first, a client that still sees a network error retries; the retry hits the same cheap rejection. **WP0 must run this through the real `tailscale serve`** with a 150 MB rejected upload and with chunked/length-less bodies: tailscaled's Go proxy may mask or change the behaviour either way.

### 9.2 Hardened media handling (worker, `media.py`)

* Magic sniff first (Python, 64 bytes): accept only `ftyp` at offset 4 (mp4/m4a/mov), `RIFF....WAVE`, `ID3`/MPEG sync, `caff`, `OggS`, EBML (webm/mkv). Anything else (HLS `#EXTM3U`, `ffconcat`, text playlists, SDP) fails `unreadable_audio` (422 in status) before any tool starts.
* Every ffprobe/ffmpeg call: argv list (never a shell), `-nostdin -v error -protocol_whitelist file,pipe -format_whitelist mov,mp4,m4a,3gp,mp3,wav,caf,ogg,matroska,webm`, input addressed as `file:<abs path>`, cwd = fresh empty temp dir, minimal env, `preexec_fn` setting `RLIMIT_CPU`, `RLIMIT_FSIZE` (2 x max upload) and a new process group, wall-clock timeout (probe 30 s; normalise `max(120 s, 2 x duration)`, capped at 20 min), kill the group on timeout. Output goes to `STAGING/.<stem>.norm.part`, forced `-f mp4` (never an audio suffix inside INBOX; dot-prefixed `.part` so no scanner can discover it).
* Policy: reject no audio stream, duration under 1 s or over `max_duration_h`. Voice Memos m4a (single AAC/ALAC stream with moov) passes through with no transcode; anything else (mp3/wav/caf/multi-stream) is transcoded `-vn -map 0:a:0 -c:a aac -b:a 96k -ac 1 -movflags +faststart`. Single audio stream is mandatory because the pipeline reads 2+ streams as track0=mic/track1=system. Missing ffmpeg: upload still succeeds (202), row goes `failed: server_misconfigured`, doctor row warns; no data loss.
* Tests (§16): an `.m3u8` and an `ffconcat` file whose entries point at a loopback listener, uploaded and also fed straight to `media.probe` with the sniff bypassed: assert no connection is ever made and the row ends `failed: unreadable_audio`.

### 9.3 Idempotency and failed-to-requeue (explicit transitions, never reliance on `IntegrityError`)

`store.accept_upload` runs in `BEGIN IMMEDIATE`:

1. Find existing row by `(device, client_id)` then by `(device, sha256)`.
2. None: insert `received` (+ audit `upload_ok`), return `new`.
3. Existing and `status != 'failed'`: delete the staged file, return `duplicate` (HTTP 200, `duplicate:true`).
4. Existing and `status == 'failed'`: **reuse the row**: replace the staged file, `status='received'`, `attempts=0`, `error_code=NULL`, `next_attempt_at=NULL`, audit `upload_requeued`; return 202. The phone can therefore always retry a failed upload and its audio is not stranded.
5. `IntegrityError` (race between two threads): re-read and apply 3/4.

The owner can force the same transition with `POST /api/mobile/uploads/retry` (also resets `attempts`). A permanent processing failure is visible to the phone through `GET /m/api/uploads/<id>` (`failed`, `error_code`); the recipe's "Latest Note" shortcut shows it.

Client semantics: 2xx = done; 4xx other than 408/429 = permanent (keep the memo in Voice Memos); 5xx/network = retry.

### 9.4 Ordering vs the other archivers (INBOX is touched by three actors)

Actors that may touch INBOX: the gateway (never; stages elsewhere), the worker (the only writer), and `cron_runner`/`voice_memo_pipeline.run_once` (separate process spawned by Electron outside attach mode, which does not share `PROCESS_LOCK`; it shares the `LOCK_PATH` flock only). Therefore:

1. Staging lives in `DATA_DIR/mobile_staging/`, outside INBOX, so `discover()` (`rglob`, dot-files included) cannot see partial files.
2. The worker moves a normalised file into INBOX last, in this order: (a) `db.create_pending_recording(stem, stem, recorded_iso, "processing")` **before** the move, so `process()`'s `get_pending_recording(path.stem)` always finds it (no orphan `processing` row, no lost tags); (b) `os.utime` to `recorded_at`; (c) `os.replace` to `INBOX/<stem>.m4a` (atomic, same filesystem).
3. Because `recorded_at` for a fresh memo is "about now", `minimum_age_seconds` (30 s) still applies: eligibility is roughly 30-35 s after the move (the worker schedules a wake at +31 s), not "immediate". Latency budget: upload, then up to about 40 s to archive, then processing time.
4. Tagging (`source=mobile`, `audio_stream_count=1`) after archive is cosmetic; correctness never depends on it (the `db.py` exclusion keys on the stem prefix set at insert).
5. Baseline: see §10.3.

---

## 10. PipelineWorker (`python/pipeline_worker.py`)

### 10.1 Locking and priority

```python
class Gate:                                # process-wide single-flight with priority
    def acquire(self, ui: bool, wait): ... # UI callers increment ui_waiting; the worker never STARTS a job while ui_waiting > 0
    def release(self): ...
@contextmanager
def exclusive(ui=False, wait=None): ...    # raises Busy on timeout
```

UI-initiated jobs (`/api/process-recording`, summary variants, enhanced notes) take the gate with `ui=True` and are preferred; a running worker job is not preempted, so the worst-case UI wait is one job timeout (§10.4); UI requests wait up to 1200 s then return 503 `busy`. The previous plain `threading.Lock` is replaced (it was unfair and could hold a handler thread behind a phone backlog while Electron's `postJson` has no timeout). The worker also **defers while any pending row has `status IN ('recording','paused')`** (live Mac capture), so a phone backlog never runs Whisper during a live meeting.

### 10.2 State machine

`received -> normalizing -> queued -> archiving -> archived -> processing -> done`; any state to `failed:<code>`; `failed -> received` only via §9.3. `tick()` interval 30 s plus `wake()`:

```python
def tick(self):
    if live_recording_pending(): return
    for up in due(status="received"): self._normalize(up)            # media.py, hardened; may fail unreadable_audio
    self._place_and_archive()                                        # pending row, utime, os.replace, then run_once under flock (nonblocking)
    for up in due(status="archived"):                                # oldest first, BY ID (not LIMIT 1)
        if gate_ui_waiting() or live_recording_pending(): break
        self._process(up)
```

`_process(up)`: acquire gate; **re-read the recording after the lock**: if `diarization.model` is already set, mark `done` without reprocessing (the lock serialises runs, it does not deduplicate them; this covers Electron's `diarizeLatestRecording` racing the worker); else `status=processing, attempts+1` and run the job subprocess.

### 10.3 Archive and baseline

`_place_and_archive()` takes the `LOCK_PATH` flock non-blocking (skip this tick if held), runs `voice_memo_pipeline.run_once()`, releases the flock (held only for `run_once`, short), then maps uploads to recordings by `db.get_recording_by_live_id(stem)`, sets `archived`, tags metadata, and (if `delete_inbox_after_archive`) deletes the INBOX copy only after verifying the archived file exists and its size matches (test).

**Baseline hazard (corrected).** The baseline loop (516-539) marks every file under `voice_memos_source` as `baseline_existing` on first scan, which protects an existing Apple Voice Memos library from mass import; the default `voice_memos_source` is INBOX, so it would also swallow first uploads. The draft's `ensure_baselined()` that merely set `voice_memos_baselined=True` would have switched that protection off and mass-archived a historical library on installs where `voice_memos_source` is the Apple library. Fix: extract the real routine (`ensure_baseline`) and call it from `runtime.start` before first enable, under the flock, so the first scan never happens with live uploads and the Apple library is baselined correctly. Test: `voice_memos_source` holds old files, first enable plus an upload: old files `baseline_existing`, upload processed.

### 10.4 Job subprocess, timeouts, attempts

Each job runs `python pipeline_job.py <folder>` (`VOICECOACH_FORCE_LOCAL=1`, `process_recording_local(Path(folder))`), so MLX/Metal memory is released after every job, a Metal abort or OOM kills only the child, and models are not resident in the API process for worker jobs. Wall-clock timeout `clamp(10 min + 2 x duration, 3 h)`, process-group kill on timeout (`failed: processing_timeout` counts as an attempt). Attempts cap 3 enforced in `_recover()` (crash recovery resets `archiving/processing` to the prior queued state only if `attempts < 3`, else `failed: crash_loop`) and before every `_process`, so a poison or oversized file cannot crash-loop under launchd/Electron restarts. Backoff 2 min, 10 min, 30 min.
UI-path jobs still run in-process in handler threads (pre-existing); the test plan adds a real-model soak (MLX streams are thread-local, a known source of "no Stream in current thread").

### 10.5 GC and backpressure

Startup and hourly: delete staging files older than 24 h with no row; `received/normalizing` rows with a missing file become `failed: lost`; any non-terminal row older than 24 h becomes `failed: stalled`; staged files of `failed` rows deleted after 7 days; queue depth above `max_queue_depth` makes new uploads 503 `busy` with `Retry-After: 300`; global byte cap counts staging plus INBOX bytes. Rejected attempts count toward per-device quotas (§9.1).

### 10.6 Engine: force local

Phone audio is processed local-only in v1 (decision, previously open decision 6): the job subprocess sets `VOICECOACH_FORCE_LOCAL=1`, covering both ASR and the enhanced-notes provider (the notes path can use a frontier provider when the provider setting is not `local_mlx`). `/api/mobile/status` and the Shortcut reply say `"engine":"local"`. Revisit per device opt-in (`allow_cloud_engine`) only after Gemini transcription is dogfooded on desktop and the BAA posture is documented per account type.

---

## 11. Mac runtime

### 11.1 v1: Electron as a Login Item (no new Mac-side code paths)

The Mac Studio runs the existing app (which spawns `server.py` with gateway and worker in-process) as a macOS Login Item with auto-login enabled and sleep disabled (`keep_awake` spawns `caffeinate -i -s -w <server pid>` while the server lives). One place documents availability (docs/PHONE_CAPTURE.md): auto-login, no system sleep, restart-after-power-failure, Tailscale Standalone build with key expiry disabled. The doctor rows `no_sleep` and `auto_login` are **warn-only**. If Electron is not running, the gateway is down: the Shortcut shows failure, the memo stays in Voice Memos. Because Login Items do not auto-restart a crashed app, the owner checks `tools/cora_mobile.py status` during dogfood; an unattended-crash alert is out of scope (no outbound channel exists by design; the phone-side Shortcut failure notification is the alert, stated honestly in docs). Note: Electron's own post-stop flow (`cron_runner`, `diarizeLatestRecording`) keeps working on the Studio and is made safe by the `db.py`, flock-wait and post-lock "already done" fixes above.

Admin: `tools/cora_mobile.py` (stdlib) reads `DATA_DIR/.api_token` (0600) and calls `/api/mobile/*` on 127.0.0.1:8765. Minting prints the token once on stdout.

Notifications: `db.log_notification` only inserts a row (`db.py:160`); native notifications come from Electron's `notify()` in `main.js`. The earlier claim that the Mac shows a macOS notification is withdrawn. v1 surfaces events through `status`/doctor output and the audit log only; there is no "Funnel blocked" critical notification.

### 11.2 v1.1: headless LaunchAgent and secure Electron attach (specified, not built in v1)

* `server.py --headless` under a LaunchAgent in `gui/<uid>` (Aqua needed for Keychain and Metal/MLX); `RunAtLoad`, `KeepAlive{SuccessfulExit=false}`, `ThrottleInterval 10`, log rotation at startup, no tokens in the plist, `@ROOT@` pinned to the app path with a **version-mismatch check** against `/api/health.version` and re-render on app update (a long-lived server otherwise keeps running old code); a checkout/bundle under `~/Documents` or `~/Desktop` hits TCC when launchd-spawned, so the installer refuses those paths.
* SIGTERM: the handler must not call `server.shutdown()` from the main thread (it is inside `serve_forever()`, so `shutdown()` deadlocks until launchd SIGKILLs). Raise `KeyboardInterrupt` (already caught at `server.py:56`) or call `shutdown()` from a helper thread.
* Electron attach, with the squatter fix the review required (`api-client.js:84-103 verifyOwnServer` exists because a hostile local process may hold 8765): never trust `/api/health {mode:"headless"}`. Before reading `.api_token` or sending `X-VC-Token`: (1) the `.api_token` file is mode 0600 and owned by the current uid; (2) `lsof -nP -iTCP:8765 -sTCP:LISTEN` shows a single listener whose uid equals ours and whose PID equals the PID of `launchctl print gui/<uid>/ai.cora.server`; only then read the token, `GET /api/auth/check`, set the cookie. Any mismatch falls through to today's `verifyOwnServer` error dialog. `API_TOKEN` is an exported `const` destructured at `main.js:11` and baked into `PYTHON_ENV` and header builders, so the getter/setter refactor touches every consumer and the 30 s re-sync loop must cover the window where the headless server restarts and rotates its token. Attach keeps spawning `cron_runner` after Mac recording stops (the worker's `tick()` returns early when no phone upload is due, so removing it would leave a Mac meeting unarchived). This is rated a launch-risk change to `src/main.js` and does not ship before the Product Hunt launch unless the owner decides otherwise.

---

## 12. Tailscale integration

### 12.1 Owner setup (documented, not automated)

1. Tailscale **Standalone** macOS build; MagicDNS and HTTPS certificates on (publishes machine/tailnet names to public CT logs: rename the Mac to something non-identifying and randomise the tailnet DNS name first).
2. `tailscale serve --bg --https=9443 http://127.0.0.1:8767`; `tailscale serve status` must say "Available within your tailnet".
3. Tailnet policy (shared/work tailnet): remove allow-all; owner group plus `tag:cora`; `tcp:9443` only; audit/remove any `funnel` nodeAttr. Keep the **phone untagged** (identity headers are not sent for tagged sources). If the Mac itself is tagged, `Self.UserID` is not the owner: the CLI prefill of `allowed_logins` must come from the owner typing it, not from `status()` when `Self.Tags` is non-empty.
4. iPhone: Tailscale VPN On Demand or "Always".

Cora never runs a mutating `tailscale` command; the CLI prints "setup commands" to copy.

### 12.2 Doctor (read-only subprocess calls to the local socket; not run when mobile is disabled or blocked)

Rows (`[{id,label,state,detail,fix}]`): fail-capable: `tailscale_running`, `serve_configured` (handler on `fqdn:9443` proxies to `127.0.0.1:8767`), `serve_safe` (**fail** if Funnel is on for any port of this node, or if any serve/funnel handler targets `127.0.0.1:8765`), `lockdown_state`; warn-only: `no_sleep`, `auto_login`. Heuristic rows (machine-name hints, untagged-phone hint) are cut: no reliable signal. The `AllowFunnel` JSON shape has no fixture yet; WP0 captures real `serve status --json` output as the test fixture.

### 12.3 Funnel posture

Control order: (1) non-Funnel port (structural), (2) request-time `Tailscale-Funnel-Request` rejection (the primary live control), (3) best-effort watchdog every 5 min and on reload that sets `state="blocked_funnel"` (gateway answers 503, tokens stay valid), audit `funnel_blocked`, visible in `status`/doctor. The watchdog is detective and best-effort; it is not presented as the control. Resume only after the owner fixes it and runs `doctor`.

---

## 13. Phone UX (v1: Shortcuts only)

Honest positioning: record in **Voice Memos** (works with the screen locked; the file stays on the phone until upload succeeds; set Audio Quality to Compressed), then Share, "Send to Cora". Mint an upload-only token with `tools/cora_mobile.py mint-token`.

**Send to Cora** (`docs/shortcuts/SEND_TO_CORA.md`): Show in Share Sheet (Audio, Files); optional `Tailscale: Connect` + wait; `Get Contents of URL` `POST https://studio-x.tailNNNN.ts.net:9443/m/api/upload`, headers `Authorization: Bearer <token>`, `Content-Type: audio/mp4`, `X-Cora-Recorded-At: <Creation Date, ISO 8601>`, optional `X-Cora-Client-Id`, request body **File** = Shortcut Input; read `status`; `received`/`queued`/`done` or `duplicate` shows "Sent to Cora" (and, if `token_days_left < 14`, "Cora token expires soon, rotate it"), otherwise "Cora upload failed. Check Tailscale and try again." Import Questions for URL and token so an exported `.shortcut` carries neither. Re-running is safe (dedupe). The token sits in plaintext inside a Shortcut that iCloud syncs: upload-only by default, 90-day expiry, bound to the owner's Tailscale login (a leaked token is useless from another tailnet identity), revocable, rotatable; docs: never share the Shortcut.

**Cora: Latest Note** (requires a token minted with `read-own`, off by default): `GET /m/api/notes/latest`, then `Show Result`/`Copy to Clipboard`. PHI-at-rest on the phone, stated honestly: notification and Show Result surfaces, Universal Clipboard sync, and the iOS app-switcher snapshot can hold note text; revoking a token is server-side only and does not wipe the phone. Mitigation is device passcode/MDM and not granting `read-own` to tokens on phones that are not trusted. Notes only (no transcript) are returned. "Record & Send" (Action Button) variant is unverified with the screen locked; WP0 tests it.

Recipe notes for large files: Apple publishes no size/timeout limits (one report: ~30 s intent timeout). The server replies right after staging; WP0 tests 30-60 MB over cellular. Cellular reliability limit: whole-file POST has no resume; hence the 200 MB cap and Compressed advice. Offset-based resumable upload is a v1.1 PWA item.

---

## 14. Policy and lockdown

```python
def mobile_ingress_allowed() -> bool:
    """Mobile capture is inbound exposure of meeting data to a second device and depends on tailscaled
    (third-party control plane/DERP). It is always off under enterprise_lockdown and when config.json sets mobile_disabled."""
    return (not lockdown_enabled()) and not _admin_flag("mobile_disabled")
```

`VOICECOACH_MOBILE_UNDER_LOCKDOWN` and open decision 7 are removed: a documented exception would read as a lockdown bypass (an env var in a user-owned LaunchAgent plist is not admin-only anyway). `runtime.start/reload` and every gateway request re-check it (403 `lockdown`, audit `lockdown_denied`); a runtime flip of lockdown stops the listener on the next reload tick. When the feature is enabled (non-lockdown), Cora originates no outbound connection from it (test blocks non-loopback sockets in the gateway process and in the job subprocess, with a non-local engine configured).

---

## 15. Security analysis and control mapping

| Threat | Mitigation |
|---|---|
| Other tailnet member or shared device hits the gateway | Tailnet grants (docs), login allowlist, device token bound to `bound_login`, allowlist shrink revokes immediately |
| Local process forges `Tailscale-*`/`X-Forwarded-*` | Documented: steps 1-6 are hygiene; token is the only real local control; same-user malware out of model; optional unix-socket target (v1.1/WP0) |
| Funnel enabled by mistake | Non-Funnel port, request-time header rejection (primary), best-effort watchdog, doctor |
| DNS rebinding / cross-site | Exact Host/Origin, no CORS/OPTIONS, bearer-only (no cookies in v1, so no CSRF surface) |
| Stolen/lost phone | Server-side revoke, expiry, upload-only default, login binding. **Not** a phone wipe: PHI on phone is passcode/MDM dependent (notification/Show Result/clipboard/app-switcher, Voice Memos audio, iCloud). Phone wipe flag is v1.1 PWA design only |
| Shortcut token leakage | Upload-only default, login binding, 90 d expiry, rotate/revoke, expiry warning |
| Slow-loris / disk fill / cost | 60 s idle timeout; length-relative deadline; global semaphore(2), per-device 1; per-device hourly count and **daily byte quota** (rejected attempts counted); **global staging+INBOX byte cap**; queue-depth backpressure; disk reserve; cap 200 MB / 4 h; reservation released in `finally`; GC (§10.5) |
| Malicious media (SSRF/LFI/lockdown bypass via ffmpeg demuxers) | Magic sniff, `-format_whitelist`, `-protocol_whitelist file,pipe`, `file:` inputs, `-nostdin`, empty cwd, rlimits, timeouts, subprocess, tests with m3u8/concat to a loopback listener (§9.2). A subprocess socket would not be caught by an in-process socket patch, so the test uses a real listener |
| MLX crash/OOM/poison file | Subprocess jobs, timeout, attempts cap, crash-loop cap |
| Stored XSS in owner UI via device name/login/ip | v1 has no renderer UI; fields sanitised server-side (printable allowlist, validated IP); v1.1 renderer requires `textContent`/`esc()` and a render test with `<img onerror>` names; CSV formula guard |
| Path/PHI leakage | Server-generated stem, filenames never stored, generic errors, `relative_to(RECORDINGS_DIR)` on every read, notes text only, forbidden-string test on real fixture |
| Audit tampering | Honest: audit is an append-only record in SQLite with JSONL mirror, **not** tamper-evident against a same-user writer. HMAC chain (Keychain key, rotation continuity, lock, off-box checkpoints) is v1.1 if required |
| Audit logs leaving the Mac | `mobile_audit.jsonl` not in `DEFAULT_BUNDLE_FILES` (`logs.py:35`), test asserts it is excluded from any bundle; files 0600 |
| CT logs leak hostname | Doc: non-identifying machine/tailnet names |

Audit events (each tested): `pairing_*` (v1.1), `shortcut_token_minted`, `device_rotated`, `device_updated` (name/scope), `device_revoked`, `revoke_all`, `auth_fail` (reason enum), `lockdown_denied`, `upload_ok`, `upload_requeued`, `upload_rejected` (reason, declared bytes), `note_read` (id), `runtime_started`, `runtime_stopped`, `config_enabled`, `config_disabled`, `config_change`, `audit_exported`, `funnel_blocked`. **Fail-closed:** state-changing actions write their audit row in the same SQLite transaction; if it cannot be written (disk full) the action does not happen (503). Audit reads of PHI: v1 has no list endpoints; every note read is audited with its id (a v1.1 list endpoint must audit with a count; `/notes/status` style polls must be audited or return no PHI).

SOC 2 / HIPAA mapping (evidence binder):

| Control | Mechanism |
|---|---|
| CC6.1 / 164.312(a)(1),(d) | Per-device scoped tokens, login binding, expiry, least-privilege default, rotation |
| CC6.2-6.3 | Mint/revoke/rotate/revoke-all flows audited; allowlist-shrink revocation; expiry |
| CC6.6 / 164.312(e) | Loopback-only listeners, tailnet-only serve on a non-Funnel port, WireGuard + TLS |
| CC7.2 / 164.312(b) | `mobile_audit` (fail-closed) with the event list above, CLI/CSV export, retention (config). Not tamper-evident in v1 (stated) |
| CC7.3-7.4 | Throttles and reject ring visible to owner; revoke-all runbook; no push alerting (stated gap) |
| CC8.1 | Off by default; flagged; design and tests are the change record; admin hard-off; lockdown gate |
| 164.312(c) | Server sha256 plus optional client `X-Cora-Content-SHA256` comparison, `Content-Length` match, magic/probe validation, atomic rename, archive size verified before inbox delete |
| PHI on phone | Upload-only default; `read-own` opt-in; honest passcode/MDM dependence; iCloud Voice Memos guidance |

Gaps to flag to the owner: (1) Tailscale control plane and DERP are third-party infrastructure (payload E2E encrypted, metadata visible); "no Cora-originated outbound path" is the precise claim; DoD/HIPAA customers may need Headscale or risk acceptance, and that is why lockdown blocks the feature. (2) iCloud Voice Memos sync is a separate residency path. (3) The phone is outside Cora's control. (4) Audit is not tamper-evident in v1. (5) In-process gateway (§3) with defined split trigger. (6) Audit/device IP+login retention is personal data.

---

## 16. Test plan and exit gate

Python (pytest, throwaway `VOICECOACH_DATA_DIR`, in-process `ThreadingHTTPServer` port 0, raw sockets; ffmpeg tests generate a 2 s sine and `skipif(no ffmpeg)`):

| File | Cases |
|---|---|
| `test_mobile_gateway_auth.py` | table-driven Host/Origin/Funnel/login/forwarded/peer variants incl. `fqdn` vs `fqdn:9443`; token missing/wrong/revoked/expired/wrong scope/**bound_login mismatch**; allowlist shrink revokes; OPTIONS/PUT rejected; uniform 403; throttle keyed on (login, ip) does not lock others; reject ring populated; slow-loris with 1 s timeout; semaphore released on exception |
| `test_mobile_routes.py` | gateway route table equals the 5-route list exactly; `/`, `/m/`, `/api/settings`, `/api/mobile/config` on the gateway are 404; **behavioural main-API regression**: ts.net Host/Origin still 403 on 8765, token still required (no hash pin, no registry enumeration) |
| `test_mobile_upload.py` | 411 chunked/no length; 413; 415; truncated body leaves nothing in INBOX/staging/rows; **202 returns before any ffprobe/ffmpeg runs** (probe patched to block); fsync before 202; duplicate by client id and sha (200); **failed row retried by same client id and same sha is requeued, not duplicate or stranded** (attempts reset, file replaced); race of two identical uploads; client SHA header mismatch 422; per-device daily byte quota and hourly count (rejected attempts counted); global byte cap; queue-depth 503; early-reject delivers the status to a raw-socket client (drain then close, no RST); semaphore/reservation freed on abort |
| `test_mobile_media.py` | m3u8/ffconcat with loopback-listener entries: no connection, `failed: unreadable_audio`; magic-sniff rejects non-audio; whitelist flags present in argv; empty cwd, timeouts, rlimit; Voice Memos-like m4a passes through, mp3/wav/caf/multi-stream normalised to one stream; garbage fails |
| `test_pipeline_worker.py` | concurrency max 1; by-id oldest first; **UI job preferred over queued phone jobs**; worker defers during pending `recording`/`paused` row; post-lock already-done check (no reprocess); subprocess timeout kills group; attempts cap and crash-loop cap in `_recover`; backoff 2/10/30; flock held then skipped; `main()` waits up to 60 s for flock; pending row exists before `os.replace` and no orphan `processing` row; `get_unprocessed_recording` excludes `m_` rows; baseline test with old files in `voice_memos_source`; inbox delete only if size matches; GC cases |
| `test_mobile_policy.py` | lockdown: `runtime.start` no-op, enable 403, per-request 403 and audit; no env override exists; **no-outbound** test with a non-local engine configured covering gateway process and job subprocess (real loopback listener plus socket patch); `mobile_disabled`; `mobile_*` cannot be written through generic settings, MCP or dataset import |
| `test_mobile_audit.py` | every event in the list emitted; fail-closed (audit write failure aborts the action, upload not accepted); no tokens/codes/filenames/transcript text; sanitised names/logins; CSV formula guard; retention; JSONL/DB mode 0600; not in logs bundle |
| `test_mobile_views.py` | own-only ownership; text only; path escape attempts rejected via `relative_to`; forbidden keys/strings (`folder_path`, `source_file`, `archived_file`, `recording_name`, `/Users/`, data-dir) absent from real fixture output; `no-store`; generic 404/500 |
| `test_tailscale_doctor.py` | fixture JSONs (real capture from WP0): ok, Funnel on, handler targeting 8765 (fail), missing serve, logged out, CLI missing |

**Exit gate for the Week-1 slice (all must pass before any launch claim):** real-tailnet 60 MB Compressed memo over cellular completes or fails cleanly with a visible message; re-run is a no-op (dedupe); failed row is retryable from the phone; revoked token 401; other-login token 401; `Tailscale-Funnel-Request` 403; lockdown yields no listener and zero outbound sockets; m3u8/concat upload 422 with no connection; 150 MB rejected upload through real `tailscale serve` shows a clean failure (no retry loop); kill -9 server mid-upload leaves no orphan; Mac meeting stopped while a phone note is pending is archived and processed correctly; 3 concurrent uploads plus one UI reprocess with a **real model** soak; 48 h run with restarts and flat memory.

WP0 device matrix (needs the owner's physical iPhone, not parallelisable): iOS current and N-1; Shortcut listed in Voice Memos share sheet; Shortcut with 30/60/100 MB over cellular; Shortcut timeout behaviour; VPN On Demand; Mac asleep/unplugged; "Record & Send" with screen locked; `tailscale serve --https=9443` accepted; `unix:` target accepted; Safari/Shortcuts `Host` includes `:9443`; early-reject, chunked and length-less through the real proxy; real `serve status --json` fixtures.

---

## 17. Rollout and launch gate

Dates are tentative, assuming the Product Hunt launch lands about mid-November; owner confirms.

1. **Week of 2026-10-19:** WP0 (owner hands), then WP1-WP7. Dark-launch on `production` with `enabled=false` (no listener; zero behaviour change except `get_unprocessed_recording` exclusion, flock wait, `exclusive()` wrappers, new tables).
2. **2026-10-26 to 2026-11-01:** owner dogfood on Mac Studio plus own iPhone (Login Item, Tailscale policy, Shortcuts daily), nightly `mobile_smoke.py` via the existing scheduler.
3. **Go/no-go 2026-11-06 (tied to the exit gate in §16, not to the full plan):** go only if every gate item passes and the dogfood week has zero stranded or lost memos. Go means one Product Hunt line, labelled beta: "Send voice memos from your iPhone to your own Mac over Tailscale. Your audio never goes to our cloud." (true because the feature is local-only and blocked under lockdown; the engine is forced local). No-go means ship the code dark and omit the claim; this does not delay launch.
4. Launch assets use seeded fictional data and a fictional hostname.
5. Regulated customers: off (lockdown blocks it); doc explains data-residency caveats.
6. Rollback: `enabled=false` (listener stops, API unaffected), `tailscale serve --https=9443 off`, tables additive.

Never cut: separate listener and route isolation, token/scope/login binding, lockdown gate, staged atomic upload, hardened media handling, worker lock/priority/attempts cap, fail-closed audit, tests.

---

## 18. Work packages (v1 slice)

| ID | Title | Files | Depends | Days |
|---|---|---|---|---|
| WP0 | Real-device and real-proxy spike (owner hands): Shortcut sizes/timeouts, 9443 and unix targets, Host with port, early-reject/chunked through serve, fixtures | `tools/mobile_spike/*` | - | 0.5 |
| WP1 | Policy gate, config/store tables, tokens, fail-closed audit | `python/mobile/{config,store,tokens,audit}.py`, `python/policy.py`, `python/server.py` | - | 1.0 |
| WP2 | Gateway, netcheck, 5 routes, owner routes, CLI | `python/mobile/{gateway,netcheck,runtime}.py`, `python/api/routes/{mobile,__init__}.py`, `tools/cora_mobile.py` | WP1 | 1.25 |
| WP3 | Streaming upload, staging, quotas, early-reply drain, idempotency/requeue | `python/mobile/upload.py`, `tests/test_mobile_upload.py` | WP2 | 1.0 |
| WP4 | Hardened media (sniff, whitelists, rlimits) | `python/mobile/media.py`, `tests/test_mobile_media.py` | WP3 | 0.5 |
| WP5 | PipelineWorker, priority gate, job subprocess, force-local, db/flock/baseline/exclusive edits | `python/pipeline_worker.py`, `python/pipeline_job.py`, `python/db.py`, `python/voice_memo_pipeline.py`, `python/pipeline/cloud_asr.py`, `python/api/routes/recordings.py`, `tests/test_pipeline_worker.py` | WP3, WP4 | 1.5 |
| WP6 | Notes views (latest/by id) and doctor (4+2) | `python/mobile/{views,tailscale}.py`, tests | WP5 | 0.75 |
| WP7 | Docs, recipes, smoke tool, evidence note, tailnet policy sample | `docs/*`, `tools/mobile_smoke.py` | WP6 | 0.5 |
| WP8 | Exit-gate run, real-model soak, dogfood fixes | tests | all | 0.75 |

Total about 7.75 agent-days; critical path WP1, WP2, WP3, WP4, WP5, WP6, WP8 about 6.5 days. Owner-time dependencies (not agent-parallelisable): iPhone for WP0 and the device matrix, Tailscale HTTPS/policy changes, Mac Studio power/auto-login/sleep settings, the 1-week dogfood. Previous plan (19.75 days) and its inconsistent "about 18 / critical 11" figures are withdrawn.

v1.1 backlog with estimates: PWA recorder 4, PWA reader plus pairing/cookie 2, Settings UI 2, headless plus attach plus SIGTERM 2, HMAC audit chain 1, read-all 0.5, unix socket 0.5, process split 2, speaker handling 0.5.

---

## 19. Failure modes

| Failure | Behaviour |
|---|---|
| Mac asleep / Tailscale down / Electron not running | Shortcut notification says check Tailscale; memo remains in Voice Memos; doctor warns on sleep/auto-login; no push alerting (stated) |
| Upload cut mid-way | Staging `.part` only; no row; GC removes; retry is safe |
| Duplicate/retry | 200 `duplicate:true`; never two recordings |
| Failed upload retried | Same row requeued (§9.3) |
| ffmpeg missing / corrupt audio / hostile media | 202 already returned; row `failed` with `error_code`; visible via `uploads/<id>`; audio remains on phone |
| Worker crash / server restart | `_recover` requeues if attempts < 3 else `failed: crash_loop`; job subprocess isolates MLX crashes |
| Job hangs | Timeout kills process group; attempt counted |
| Processing error | Backoff 2/10/30 min then `failed`; owner `retry` |
| Live Mac meeting in progress | Worker defers phone jobs |
| Electron post-stop archive while worker holds flock | `main()` waits up to 60 s instead of exiting |
| Phone note unprocessed when Mac meeting stops | `get_unprocessed_recording` excludes `m_` rows; post-lock check prevents double work |
| Port 8767 in use | `state: port_in_use`; main API unaffected |
| Funnel enabled | Structurally unavailable on 9443; header rejection; watchdog 503 (best effort) |
| Token revoked/expired | 401; memo stays on phone; re-mint token |
| Audit write fails (disk full) | State-changing requests fail closed (503) |
| Disk filling | 507 before body, global byte cap, GC |
| Lockdown flipped on while running | Listener stops next reload tick; requests 403 |
| Headless token rotation, attach | v1.1 only (§11.2) |

---

## 20. v1.1 deferred designs (revised per review; build only after WP0 evidence and launch)

* **PWA** (`src/ui/mobile/`, gateway static serving): precondition is a WP0 answer on mic persistence, cookie visibility between Safari and the Home Screen app, and silent-audio-loss behaviour. Require Home Screen install before recording (Safari tabs get the 7-day script-writable storage purge, so the IndexedDB journal is not durable there). CSP `default-src 'none'; script-src 'self'; style-src 'self'; ...` blocks inline `style` attributes and `setAttribute('style')`, so lint for them. Cookie vs token mode is server config only (default cookie, `__Host-`, HttpOnly, SameSite=Strict, `X-Cora-Client` on POST); token-in-IndexedDB fallback only if WP0 proves cookies fail, with 30-day TTL and login binding. Resumable offset-based append uploads (reusing the IndexedDB chunks) instead of whole-file retries; the client pre-checks size against `max_upload_mb` from `/me` and probes `GET /m/api/uploads/<client_id>` before sending. Phone-side PHI: remote-wipe flag returned on the next 401 (clears IndexedDB and cached note text) and a short TTL for `done` items; honest copy that revocation does not touch unsent audio unless the app opens again.
* **Pairing:** 10-char Crockford code, 300 s TTL, QR in URL fragment, lock keyed per (login, ip) with exponential backoff (not global), code bound to the first requester IP, the lockout never in the generic 403; `pairing_code_issued` audited.
* **`read-all` and list endpoints:** off by default, requires an explicit decision and the process split (§3); list calls are audited with a count; `/notes/status` audited or PHI-free; neutral `recording_status.py` module extracted from the inline progress code in `recordings.py:91-108` (no `recording_progress()` helper exists today) so `mobile/` still imports nothing from `api.*`.
* **Settings UI:** renderer section with `textContent`/`esc()` for every device/login/ip field and a render test with `<img onerror>` names; QR via a vendored MIT lib; new script is the 19th `<script>` tag.
* **HMAC audit chain:** Keychain-held key, continuity across monthly rotation and the 400-day prune, a lock for concurrent writers, signed checkpoints exported off-box, verify endpoint and CSV UI. Until then the SOC 2 row says "not tamper-evident".
* **Conversation kind:** needs diarization on single-track audio; cut until it works, rather than label everyone "You".
* **Cloud engine for phone audio:** per-device opt-in (`allow_cloud_engine`), shown in every reply; only after BAA posture per Google account type is documented.

---

## 21. Open owner decisions (recommendations)

1. Confirm the Week-1 slice as v1 and PWA/pairing/`read-all`/Settings UI/headless/attach as post-launch (recommended: yes; supersedes the old "build both PWA and Shortcut").
2. Mac Studio runs Electron as a Login Item in v1 (recommended) vs waiting for headless plus attach (not recommended before launch).
3. Allow `read-own` for Latest Note in v1 (recommended: yes, opt-in per token, off by default, with the PHI-on-phone warning) vs shipping upload-only. Reviewers split here; default retained because it is the minimum lovable read path and regulated customers are excluded by lockdown.
4. Serve port 9443 (recommended; WP0 confirms) vs 443 plus policy audit.
5. Delete the INBOX copy after verified archive (recommended: yes).
6. Gateway in-process now (recommended) with the §3 split trigger vs split now.
7. Beta label and the single PH sentence in §17 (recommended) vs omit.
(Withdrawn: Gemini-vs-force-local for phone audio, decided force-local; lockdown override, decided always blocked; identity mode, decided login allowlist plus bound login.)

---

## Appendix: review disposition

Adopted (all must_fix): worker-side probe/normalise with 202 after fsync and new `normalizing` state (§9.1, §10.2); ffmpeg/ffprobe hardening plus loopback-listener test (§9.2); explicit failed-to-requeue (§9.3); pending row before `os.replace`, staging outside INBOX with dot-prefixed `.part` and forced `-f mp4` (§9.4); real baseline routine instead of flag-setting (§10.3); stored-XSS/name sanitisation/CSV guard (§6, §8.2, §15); audit honesty (no unkeyed chain; fail-closed; events list; read auditing) (§15); per-device daily byte quota, global cap, 200 MB/4 h, rejected-attempt counting, length-relative deadline, timeout/semaphore tests (§9.1, §16); phone-PHI honesty and v1 read scope opt-in (§13, §15); non-Funnel port and doctor flags 8765 handlers (§3, §12.2); attach squatter fix (PID/uid/file checks, §11.2); cron_runner not skipped; `get_unprocessed_recording` exclusion; flock wait; subprocess jobs with timeout and attempts cap; `exclusive()` on all MLX entry points and live-capture deferral and UI priority; SIGTERM fix; early-response drain; lockdown override removed; shared-helper/circular-import fix (§3); Week-1 slice, single effort figure, PWA post-launch, conversation kind cut; false notification claim withdrawn; Funnel watchdog demoted; config moved off the `settings` table.

Adopted should_fix: hygiene-vs-control table; per-(login, ip) throttling; cookie mode server-config only (v1.1); token rotation, expiry warning, login binding, allowlist-shrink revoke; force-local default; "no Cora-originated outbound path" wording; `relative_to` on reads and forbidden-key tests on real fixtures; 0600 files and bundle exclusion; process-split trigger; no `http.py` hash pin; claim corrections (18 scripts, no `recording_progress()`, `Handler.timeout` unset on the main API); WP0 checks for serve port and Host form plus `last_rejects` ring; Shortcut `recorded_at` floor 90 days and Creation Date header; throttled `last_seen` writes; real-model soak; client-sent SHA header; audit retention note; version-mismatch check and TCC note for the LaunchAgent (v1.1); `package.json` correction (only `asarUnpack` would be needed, and only for the v1.1 PWA).

Adopted with modification: Latest Note stays in v1 (reviewer 3 core, reviewer 1 exclude) as opt-in `read-own`, notes text only; doctor is 4 fail-capable plus 2 warn-only rows (between reviewers' "reduce to 4" and "warn-only"); unix-socket target is a WP0 probe and optional mode, not default; Electron attach challenge replaced by PID/uid/file-owner checks (no new unauthenticated endpoint on the main API); audit JSONL kept as a plain mirror.

Rejected: sliding renewal of Shortcut tokens (rotation plus warning instead; plaintext token in an iCloud Shortcut should not silently extend); client-supplied SHA as mandatory (optional only; Shortcuts cannot compute it cheaply); making the gateway a separate process in v1 (trigger defined instead; lockdown excludes the DoD segment, and the only untrusted parser is a length-delimited copy); a persisted failed-auth lockout (tokens are 256-bit; in-memory throttle suffices).
