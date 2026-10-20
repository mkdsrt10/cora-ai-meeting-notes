# Cora Plugin SDK v1 — Proposal: Pragmatic In-Process Python SDK

Angle: manifest + Python package with lifecycle hooks, routes under `/api/plugins/<id>/`, host-owned storage and LLM broker, permissions enforced at the API boundary, UI from same-server static files mounted as tabs. Trust model: review + signed registry. Optimized for time-to-build (solo founder + AI agents, 4-5 weeks to launch, today 2026-10-16).

Status: design only. Nothing in the repo was modified. All `file:line` references were checked against the working tree on branch `production` unless marked "(discovery)".

---

## 0. Position in one page

1. **One SDK, three tiers.** Tier 0 is declarative (manifest + prompt templates + schemas + rules; zero third-party code). Tier 1 adds a sandboxed UI frame. Tier 2 adds in-process Python hooks/routes. About 80% of the owner's plugin ideas (roleplay, storytelling, communication-lite, roadmap, todo export rules, KB extraction) are Tier 0 or Tier 0 + a little first-party Python. That is what keeps the build fast and the HIPAA/DoD story defensible.
2. **In-process Python is trusted code, not sandboxed code.** CPython cannot sandbox a plugin. This proposal does not pretend otherwise. Third-party Python (Tier 2) is installable only when it carries a Cora registry signature (human review + CI) or an org-signed allowlist entry; unsigned code runs only in an explicit dev mode that is unavailable under lockdown or managed mode. Permissions are enforced at the host API (`ctx`, routes, broker), backed by an import guard and an audit-hook tripwire. These are guardrails against accidents and naive abuse, not a boundary against a determined attacker. §7 states this plainly.
3. **The SDK surface is RPC-shaped** (JSON-serializable args/returns, no live DB handles, no core imports). That is the one design rule that costs almost nothing now and lets v2 move Tier 2 out-of-process under `sandbox-exec` without changing a single plugin.
4. **Lockdown is enforced in five places, not one**: load-time gating, the LLM broker, host connectors, a Python-level egress tripwire, and the Electron main/renderer (frame sandbox + CSP + `will-frame-navigate`/webRequest). Plugins have no network permission at all in v1; outbound is only through host-implemented connectors and the policy-checked broker.
5. **Same-server UI, but not same-origin.** The discovery notes correctly warn that a same-origin iframe on `127.0.0.1:8765` gets the token cookie, parent DOM and `parent.electronAPI`. This proposal serves plugin UI from `/plugins/<id>/` on the existing server (fastest: no protocol handler) but only into an iframe with `sandbox="allow-scripts"` (no `allow-same-origin`) plus a response CSP `sandbox` directive, so the document has an opaque origin: no cookie, no parent access, `Origin: null` rejected by `authorize()`, all data via a host `postMessage` bridge. Tier 0 plugins need no frame at all; they render host-side.
6. **MCP is a sibling surface, not the plugin runtime.** `python/mcp_server.py` stays a separate read-only process. Plugins contribute read-only MCP tools declaratively over their own outputs and the shared KB tables. The server gets the lockdown gate it lacks today.
7. **Core fixes that are prerequisites, not plugin work** (WP0/WP2): `POST /api/settings` key allowlist, MCP lockdown gate, frame/navigation hardening in `src/main/security.js`, and stable action-item IDs (today `todo_state` is keyed by list index and has no writer).

---

## 1. Verified ground truth (and corrections to discovery)

| Fact | Evidence |
|---|---|
| Only plugin mechanism is a hard-wired importer with process-lifetime cache and silent `ImportError` -> `None`. | `python/plugin_registry.py:19-59` |
| `PLUGINS_DIR` exists, unused. Bundle already ships `plugins/**/*` unpacked. | `python/paths.py:28`; `package.json` `files` + `asarUnpack` |
| Router: exact routes win, then prefix routes in registration order; exact duplicates raise. A single `/api/plugins/` prefix route is safe, and management routes can live under a different exact prefix. | `python/api/router.py:16-36` |
| Route modules are a static import list. | `python/api/routes/__init__.py:2` |
| `authorize()` checks Host and Origin for **every** path (including static), then requires token only for `/api/*` and `/media*`. Static files are public. `Origin: null` is rejected (`"null"` is not in the allowed set). | `python/api/http.py:35-53` |
| Every response gets `X-Frame-Options: DENY`, `CORP: same-origin` in `end_headers()`; there is no CSP header. A per-route override needs a small refactor of `end_headers`. | `python/api/http.py:24-29` |
| `serve_static` serves `STATIC` with a traversal check; a sibling `serve_plugin_static` is trivial. | `python/api/routes/media.py:79-84` |
| `POST /api/settings` writes **any** key. | `python/api/routes/settings.py:243-251` |
| `call_configured_llm` is single-turn, policy-checked per call, traced via `ai_trace.span`. It is the right base for a broker but needs a messages variant. | `python/credentials.py:403-441` |
| Policy: `lockdown_enabled()` reads env then config.json on each call; `provider_allowed()` blocks cloud providers and non-loopback custom endpoints. Env var "cannot be switched off from inside the app" is the existing enforcement precedent. | `python/policy.py:15-49` |
| Local pipeline runs in **two** processes: in the API server (`/api/process-recording` -> `process_recording_local`) and in a spawned `cron_runner.py` (Electron `PIPELINE_SCRIPT`). Hook dispatch must therefore go through the DB, not an in-memory registry. | `python/api/routes/recordings.py:222-232`; `src/main/paths.js:49`; `src/main.js:682` |
| Persistence points for the processed event: `db.update_recording_data(... diarization / call_summary)` at `runner.py:339-343`; audio deleted at `:376-378`; continuation merge at `:410-428`. | `python/pipeline/runner.py` |
| Identity: `confirm_speaker` writes `identity` and calls `clear_coaching_artifacts` (hard-coded filenames); cloud auto-pilot auto-confirms identity and calls coaching inline. | `python/diarization.py:287-337`, `:663-691` |
| Action items: `todo_state(recording_id, item_index)` has a getter only; no writer. | `python/db.py:87-94`, `:571-573` |
| Detail UI: chip row `:259-267`; four fixed tabs `:305-310`; disabled "Ask anything... Coming soon" row `:337-340`; settings nav `:369-378`. Tab/settings handlers are bound once with `$$()` (`notepad.js:21-24`, `settings.js:5-8`, `search.js:153`) and `search.js:17-27` hard-codes panel ids. `core.js:9-16` titles map. | files as listed |
| `isTrustedUrl` prefix-trusts the whole dashboard origin; `will-navigate` is main-frame only; `setWindowOpenHandler` opens any https URL from any frame. | `src/main/security.js:13-43` |
| `cryptography` is already in the bundled runtime (transitively via `google-auth`, `--extra cloud`). It provides Ed25519. Make it an explicit dependency of the core extra. | `build/requirements.txt` |

Corrections / refinements to discovery:
- Discovery recommends custom-scheme frames for Tier 1. That is stronger but needs `protocol.registerSchemesAsPrivileged` and handler code in main. The opaque-origin loopback frame described in §8.4 gives equivalent isolation for the properties that matter here (no token, no parent, no `electronAPI`, no fetch) with fewer moving parts. It does rely on browser behavior that must be spiked on day 1 (risk R1) with the custom scheme as the fallback.
- Discovery says third-party code should be out-of-process only. That is the right v2 destination; it is not the fastest path and is explicitly not this proposal's scope. It is preserved as an upgrade path (§7.6).
- `mcp_server.py` is the only extension surface today that is outside the token gate. Treated as a control gap and fixed in WP0.

---

## 2. Plugin types and tiers

| Tier | Name | Contains | Runs where | Who can install | Typical plugins |
|---|---|---|---|---|---|
| 0 | **Pack** | `plugin.json`, prompt templates (`.md`), output JSON schemas, rules (`.json`), note templates, personas | Host interprets it. No third-party code executes. | Anyone, with consent sheet. Registry-signed or sideloaded. | Storytelling coach, roleplay personas, roadmap tracker, todo-export rule sets, note templates, comm-coach-lite |
| 1 | **Pack + UI** | Tier 0 + static `ui/` (HTML/JS/CSS) | Sandboxed opaque-origin iframe; host bridge only | Registry-signed or sideloaded | Knowledge-base browser, roadmap board, custom dashboards |
| 2 | **Code** | Tier 0/1 + Python package with hooks, routes, MCP tools | In-process in the API server, behind `ctx` | **Registry-signed (reviewed) or org-allowlisted only.** Unsigned only in dev mode, never under lockdown/managed. | Coaching (delivery metrics need numpy + audio), KB extraction/dedupe, future team-sync |
| host connector (not a plugin tier) | **Connector** | Host-implemented export targets (`file`, `reminders`, later `todoist`/`linear`/`notion`) | Core code; policy-checked | Part of the app | Used by todo-export rules |

Rules:
- A higher tier may use everything below it. Tier is a property of what code the plugin ships, and it drives install policy and the consent wording ("This plugin includes code that runs on your Mac with the app's access").
- Tier 2 first-party plugins live in `APP_ROOT/plugins/` inside the signed app bundle and need no separate signature (the app signature covers them).
- A plugin may not change tier between versions without a fresh consent.

---

## 3. Manifest schema (`plugin.json`, API v1)

JSON Schema is shipped as `cora_sdk/plugin.schema.json` and enforced by the loader and `cora-plugin lint`. Unknown top-level keys are an error (forward compatibility via `api_version`, not via silent ignore).

```jsonc
{
  "$schema": "https://cora.example/schemas/plugin-v1.json",
  "api_version": "1",                       // plugin API major; host supports a window (v1 only at launch)
  "id": "acme.storyteller",                 // ^[a-z0-9][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)+$ ; first-party = "cora.*" (reserved)
  "name": "Storytelling Coach",
  "version": "1.2.0",                       // semver
  "description": "Finds the stories in your meetings and coaches your structure.",
  "publisher": { "name": "Acme", "url": "https://github.com/acme" },
  "license": "MIT",
  "tier": 0,                                // 0 | 1 | 2 ; must match the files actually present
  "requires": {
    "cora": ">=1.4.0",
    "host_packages": ["numpy"],             // must already be in the bundle; no pip at runtime
    "platforms": ["darwin-arm64", "darwin-x86_64"]
  },

  // --- Data & egress declaration (drives consent text and lockdown behavior) ---
  "permissions": {
    "required": ["transcript:read", "llm:call", "notes:write"],
    "optional": ["transcript:read:all", "kb:write"]
  },
  "llm": {
    "cloud": "optional",                    // "never" | "optional" | "required"
    "min_context_tokens": 16000,
    "audio": false                          // true => also needs permission llm:audio
  },
  "lockdown": {
    "works_offline": true,                  // loads under lockdown, with cloud paths refused by the broker
    "disabled_features": []                 // features that self-disable under lockdown (shown in UI)
  },

  // --- Lifecycle (Tier 2; Tier 0 uses `pipelines` below) ---
  "entry": "plugin.py",                     // Tier 2 only; relative, inside the package
  "events": ["recording.processed", "notes.generated", "identity.changed"],
  "timeouts": { "event_seconds": 300 },

  // --- Routes (Tier 2): each declares the scopes it needs; host checks before dispatch ---
  "routes": [
    { "method": "POST", "path": "/analyze", "scopes": ["transcript:read", "llm:call"], "stream": false }
  ],

  // --- Declarative pipelines (Tier 0): host runs them on events ---
  "pipelines": [
    {
      "id": "story-scan",
      "on": "recording.processed",
      "when": { "min_duration_seconds": 300, "min_speakers": 1 },
      "steps": [
        { "llm": { "template": "prompts/story_scan.md", "schema": "schemas/story_scan.json", "max_tokens": 2500 } }
      ],
      "sinks": [
        { "output": { "kind": "story_scan", "title": "Story scan", "render": "markdown", "from": "$.report_md" } }
      ]
    }
  ],

  // --- UI contribution points (see §8) ---
  "contributes": {
    "recording_tabs": [
      { "id": "story", "label": "Stories", "icon": "book-open", "render": "output", "kind": "story_scan" }
    ],
    "actions": [
      { "id": "rescan", "label": "Re-scan stories", "icon": "refresh", "where": "recording.chips",
        "visible_when": { "has_notes": true }, "invoke": { "pipeline": "story-scan" }, "confirm": false }
    ],
    "chat_personas": [
      { "id": "mentor", "label": "Story mentor", "system_template": "prompts/mentor.md",
        "context": ["transcript", "notes"], "inputs_schema": "schemas/mentor_inputs.json" }
    ],
    "settings": { "schema": "schemas/settings.json" },             // host-rendered form (JSON-schema subset)
    "views": [],                                                   // sidebar pages: { id, label, icon, render: "frame"|"schema", entry }
    "templates": [ { "id": "story-notes", "kind": "notes", "label": "Story-first notes", "file": "templates/story-notes.md" } ],
    "mcp_tools": [ { "name": "story_scan", "description": "Latest story scan for a recording.",
                     "source": { "output": "story_scan" }, "args": { "recording_id": "string" } } ]
  },

  // --- Declared secrets (stored in Keychain as plugin.<id>.<name>; never sent to frames) ---
  "secrets": [],

  // --- Integrity (filled by `cora-plugin pack`, verified at install and every load) ---
  "integrity": { "tree_sha256": "..." }
}
```

Validation rules enforced by the loader (each failure becomes `plugins.state = load_error` with a human-readable `last_error`; never silent):
- `tier` consistent with files (no `entry` => tier 0/1; `ui/` present => tier >= 1; `entry` => tier 2).
- Every scope in `routes[].scopes`, `pipelines`, `contributes` must be a subset of `permissions.required ∪ optional`.
- `llm.cloud: "required"` is incompatible with `lockdown.works_offline: true`.
- Paths are relative, normalized, no `..`, no symlinks, size caps (package <= 25 MB; UI <= 5 MB).
- `id` prefixes: `cora.` is reserved for bundled plugins; `_`-prefixed ids reserved for the host.
- `requires.host_packages` must be importable at load time; failure surfaces the missing package name in UI (fixes the silent-vanish bug at `plugin_registry.py:54-57`).

### 3.1 Python entry contract (Tier 2)

```python
# plugin.py
from cora_sdk import Plugin

plugin = Plugin()

@plugin.on("recording.processed")          # or define module-level on_recording_processed(ctx, ev)
def processed(ctx, ev):
    nb = ctx.notes()                        # event-scoped: ev.recording_id
    ...
    ctx.outputs.put("story_scan", content_md=..., content_json=...)

@plugin.on("identity.changed")
def identity_changed(ctx, ev):
    ctx.outputs.mark_stale(recording_id=ev.recording_id)   # replaces clear_coaching_artifacts

@plugin.route("POST", "/analyze")
def analyze(ctx, req):                      # req: PluginRequest(json, recording_id, query); no raw handler
    return {"ok": True}

@plugin.mcp_tool("story_scan")
def story_scan(ctx, recording_id: str) -> dict: ...
```

Both styles work: decorators, or module functions named `on_recording_processed`, `on_notes_generated`, `on_identity_changed`, etc. The host only calls hooks that appear in the manifest `events`; undeclared hooks are ignored with a lint warning.

---

## 4. Lifecycle and events

### 4.1 Event catalogue (v1)

| Event | Emitted from | Payload (JSON) | Audio available? |
|---|---|---|---|
| `recording.processed` | end of `_process_recording_local_inner` after `db.update_recording_data(...)` (`runner.py:339-343`, before `:376`); also the cloud `diarize()` completion (replaces auto-pilot block `diarization.py:663-688`) | `recording_id`, `kind: initial\|reprocess`, `engine`, `duration_s`, `has_audio` | Yes, via audio lease |
| `notes.generated` | after enhanced notes persist (initial), after re-summarize (`recordings.py:324-396`), after a note-template re-apply | `recording_id`, `template_id`, `kind: initial\|regenerate\|variant` | Lease continues |
| `identity.changed` | `confirm_speaker`, `reset_speaker`, `label_speaker(is_self)` (`diarization.py:287-329`), cloud auto-confirm | `recording_id`, `old_speaker_id`, `new_speaker_id`, `person_id`, `source: manual\|auto` | n/a |
| `recording.merged` | continuation merge (`runner.py:410-428`) | `parent_id`, `child_id` | n/a |
| `transcript.edited` | `transcript_edit.py` save | `recording_id` | n/a |
| `recording.deleted` | `db.delete_recording` | `recording_id` (plugin must purge its derived data; host also cascades) | n/a |
| `plugin.enabled` / `plugin.disabled` / `plugin.uninstalling` | host | `plugin_id`, `purge: bool` | n/a |
| `schedule.daily` / `schedule.weekly` | host timer (v1.1; not launch) | `date` | n/a |

Plugins may not emit host events. Plugin-to-plugin events are out of scope for v1 (a documented non-goal; cross-plugin composition happens through the shared KB tables).

### 4.2 Delivery semantics

- **Durable queue.** `plugin_events` + `plugin_event_deliveries` tables (§5). Emitting is a single function `plugin_host.events.emit(type, recording_id, payload)` that only inserts rows. It never imports plugins, so it is safe from `cron_runner.py` and from the server process alike. A worker pool inside the API server (2 threads; one in-flight delivery per plugin) drains the queue. On server start it replays `queued`/`running` rows (at-least-once). If the server is down, events wait.
- **Idempotency.** Each delivery carries `event_id`; hooks must be idempotent. `ctx.outputs.put` is upsert-by-`(plugin_id, recording_id, kind)`.
- **Timeouts and failure.** Default 300 s wall clock per delivery (manifest-overridable up to 1800 s). Cooperative cancel via `ctx.cancelled`; a stuck thread is abandoned and the plugin is marked `degraded` after 3 consecutive timeouts. 3 attempts with backoff, then `failed` with the error visible in the Plugins pane and `plugin_runs`. Exceptions are never swallowed with `print` (the auto-pilot bug at `diarization.py:690-691`).
- **Progress.** `ctx.progress(fraction, message)` writes `plugin_runs`; the UI polls `GET /api/plugin-host/runs?recording_id=...` and shows a per-recording "Plugins working..." chip, modeled on `.pipeline_progress.json` (`pipeline/common._write_progress`). Long work never runs in a request thread (today `routes/coaching.py:20-35` blocks a Gemini audio call in the handler).
- **Ordering.** Per recording: `recording.processed` is delivered before `notes.generated`; no ordering across plugins. Deliveries for the same `(plugin, recording)` are serialized.
- **Per-recording opt-out.** Metadata flag `plugins_excluded: true` (toggle in the detail overflow menu; default settable in Settings > Data & privacy). Excluded recordings generate no deliveries, and `ctx` raises for them. This is a HIPAA/DoD-relevant control that costs one `if`.

### 4.3 Audio lease (fixes the `retain_audio` ordering bug)

`runner.py:376-378` deletes audio immediately when `retain_audio` is off, so an audio-dependent hook could never run. New behavior:
1. At emit time, `events.emit(...)` returns `audio_lease=True` if any enabled, consented subscriber holds `audio:read`.
2. If true, the runner skips `unlink`, writes `audio_deletion_pending: <iso>` into recording metadata, and the host performs the deletion after the last delivery for that recording reaches a terminal state, or after a hard 30-minute lease expiry, whichever is first. A startup sweep deletes any `audio_deletion_pending` older than the lease (crash safety).
3. The privacy promise stays true ("audio is deleted when processing finishes") with the lease window disclosed in the consent sheet for any plugin requesting `audio:read`.

---

## 5. Data model (SQLite, added in `db.init_db()`; all `CREATE TABLE IF NOT EXISTS`)

All plugin data lives in the existing `voicecoach.db` (one backup/erase story). Nothing goes in `settings` or the `summaries` blob (`db.py:412-430` has a read-modify-write race and `/api/settings` exposes every `settings` key).

```sql
-- Registry of installed plugins (source of truth for state; config.json is NOT trusted for grants)
CREATE TABLE plugins (
  id TEXT PRIMARY KEY, version TEXT NOT NULL, tier INTEGER NOT NULL,
  source TEXT NOT NULL,                 -- bundled | registry | sideload | dev
  manifest_json TEXT NOT NULL, tree_sha256 TEXT NOT NULL, registry_sig TEXT,
  enabled INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'installed',  -- installed|ok|load_error|blocked_policy|needs_consent|degraded
  last_error TEXT, installed_at TEXT, updated_at TEXT, installed_by TEXT   -- 'user' | 'admin' | 'bundled'
);

CREATE TABLE plugin_grants (
  plugin_id TEXT NOT NULL REFERENCES plugins(id) ON DELETE CASCADE,
  scope TEXT NOT NULL, granted INTEGER NOT NULL,
  manifest_version TEXT NOT NULL, granted_at TEXT NOT NULL,
  PRIMARY KEY (plugin_id, scope)
);

-- Namespaced KV. recording_id '' = global. namespace: settings | state | cache
CREATE TABLE plugin_kv (
  plugin_id TEXT NOT NULL REFERENCES plugins(id) ON DELETE CASCADE,
  namespace TEXT NOT NULL, recording_id TEXT NOT NULL DEFAULT '', key TEXT NOT NULL,
  value TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (plugin_id, namespace, recording_id, key)
);  -- value <= 256 KB; per-plugin quota 50 MB

-- Latest derived artifact per (plugin, recording, kind); rendered host-side
CREATE TABLE plugin_outputs (
  id TEXT PRIMARY KEY,                       -- uuid
  plugin_id TEXT NOT NULL REFERENCES plugins(id) ON DELETE CASCADE,
  recording_id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT,
  content_md TEXT, content_json TEXT, schema_version INTEGER DEFAULT 1,
  inputs_hash TEXT,                          -- hash of transcript+identity+template at compute time
  stale INTEGER NOT NULL DEFAULT 0,          -- set by identity.changed / transcript.edited / recording.merged
  run_id TEXT, version INTEGER NOT NULL DEFAULT 1, created_at TEXT, updated_at TEXT,
  UNIQUE (plugin_id, recording_id, kind)
);

-- Durable event queue (written from any process; drained by the server worker)
CREATE TABLE plugin_events (
  event_id TEXT PRIMARY KEY, type TEXT NOT NULL, recording_id TEXT, payload_json TEXT,
  audio_lease INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE plugin_event_deliveries (
  event_id TEXT NOT NULL REFERENCES plugin_events(event_id) ON DELETE CASCADE,
  plugin_id TEXT NOT NULL, status TEXT NOT NULL,   -- queued|running|done|failed|skipped
  attempts INTEGER DEFAULT 0, run_id TEXT, started_at TEXT, finished_at TEXT, error TEXT,
  PRIMARY KEY (event_id, plugin_id)
);
CREATE TABLE plugin_runs (
  run_id TEXT PRIMARY KEY, plugin_id TEXT NOT NULL, trigger TEXT NOT NULL,  -- event|route|action|chat
  recording_id TEXT, status TEXT NOT NULL, progress REAL, message TEXT,
  started_at TEXT, finished_at TEXT, error TEXT, llm_tokens_in INTEGER, llm_tokens_out INTEGER
);

-- Append-only, hash-chained audit (SOC 2 evidence). Never stores content.
CREATE TABLE plugin_audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, plugin_id TEXT,
  actor TEXT NOT NULL,                       -- plugin | user | admin | system
  action TEXT NOT NULL,                      -- install|enable|grant|revoke|scope_use|llm_call|export|deny|load_error|purge
  scope TEXT, recording_id TEXT, detail_json TEXT,  -- ids, counts, bytes, provider, model; no transcript text
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL       -- sha256(prev_hash || canonical row)
);

-- Host-owned chat (roleplay, coaching chat, "ask this meeting")
CREATE TABLE chat_sessions (
  id TEXT PRIMARY KEY, recording_id TEXT, plugin_id TEXT NOT NULL, persona_id TEXT NOT NULL,
  title TEXT, params_json TEXT, provider TEXT, model TEXT, created_at TEXT, ended_at TEXT
);
CREATE TABLE chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, tokens INTEGER, created_at TEXT NOT NULL
);

-- Shared KB tables (core-owned; plugins write with kb:write). Stable UUIDs fix todo_state.
CREATE TABLE action_items (
  id TEXT PRIMARY KEY,                       -- uuid, stable across re-summarize
  recording_id TEXT NOT NULL, text TEXT NOT NULL, text_norm_hash TEXT NOT NULL,
  owner_person_id TEXT, owner_name TEXT, due_date TEXT,
  status TEXT NOT NULL DEFAULT 'open',       -- open|done|dismissed
  done_at TEXT, source TEXT NOT NULL,        -- notes | plugin:<id> | manual
  span_json TEXT,                            -- transcript provenance {start_s,end_s,speaker_id}
  version INTEGER NOT NULL DEFAULT 1,        -- bump on change (future sync / conflict detection)
  created_at TEXT, updated_at TEXT, superseded_by TEXT
);
CREATE INDEX action_items_rec ON action_items(recording_id);
CREATE TABLE decisions (
  id TEXT PRIMARY KEY, recording_id TEXT NOT NULL, text TEXT NOT NULL, rationale TEXT,
  decided_by_person_id TEXT, span_json TEXT, source TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active', created_at TEXT, updated_at TEXT, superseded_by TEXT
);
CREATE TABLE task_exports (                 -- idempotent export ledger for the todo-export plugin
  item_id TEXT NOT NULL, plugin_id TEXT NOT NULL, connector TEXT NOT NULL,
  external_ref TEXT, content_hash TEXT NOT NULL, exported_at TEXT NOT NULL,
  PRIMARY KEY (item_id, plugin_id, connector)
);
```

Notes:
- **`action_items` backfill**: one idempotent job parses `call_summary.action_items` bullets (`runner.py:293`) into rows with `text_norm_hash = sha256(normalize(text))`. Re-summarize reconciles by hash then token-set fuzzy match (>= 0.85) so IDs and `done` state survive. Existing `todo_state` rows are migrated by index at backfill time (best effort, once), then the table is retired. This is core WP2, because it also unblocks MCP `is_done` (`mcp_server.py:614-625`).
- **Cascade on recording delete**: `db.delete_recording` is extended to delete `plugin_outputs`, `plugin_kv` (recording-scoped), `chat_sessions`, `action_items`, `decisions` for that id, and emits `recording.deleted`. Uninstall offers "Delete this plugin's data" (default on).
- **Concurrency**: all plugin-table writes use short `with db.get_db()` transactions. No plugin writes into `summaries`.
- Recording payloads given to plugins are redacted: no `folder_path`, `folder_uri`, `audio_url` (these leak the home dir; `views.py:365-373`).

---

## 6. Host services: `PluginContext` (what plugins may call)

`ctx` is constructed per delivery/route/chat turn and bound to `plugin_id`, `run_id`, and (when applicable) one `recording_id`. Every method calls `grants.require(plugin_id, scope, recording_id)` and writes an audit row on deny and on first use per run. Plugin code never imports `db`, `credentials`, `diarization`, `paths`, `policy`.

| API | Scope required | Notes |
|---|---|---|
| `ctx.recording(id=None)` | `recordings:read` | metadata: id, title, date, duration, participants (names), folder tags. Redacted. Default id = bound event/open recording. |
| `ctx.transcript(id=None, format="labeled")` | `transcript:read` (`:all` for other ids) | speaker-labeled, timestamped segments |
| `ctx.notes(id=None)` | `notes:read` (`:all`) | enhanced notes + summary variants |
| `ctx.speakers(id=None)` | `transcript:read` | speaker profiles (no embeddings/clips) |
| `ctx.identity(id=None)` | `identity:read` | which speaker is "me" |
| `ctx.people.list()/get()` | `people:read` | name, role, org, tags |
| `ctx.audio(id=None)` -> context manager yielding a read-only path | `audio:read` (event-scoped only; no `:all` in v1) | requires the audio lease; deleted afterwards |
| `ctx.llm.chat(messages, system=, schema=, max_tokens=, temperature=, prefer="user")` | `llm:call` | broker, §7.3 |
| `ctx.llm.stream(...)` | `llm:call` | generator of text deltas |
| `ctx.llm.audio(prompt, audio_path, schema=)` | `llm:audio` | Gemini audio route; egress-flagged |
| `ctx.outputs.put/get/list/mark_stale` | implicit (own rows) | `put` is upsert |
| `ctx.kv.get/set/delete(namespace, key, recording_id=None)` | implicit (own rows) | quotas |
| `ctx.settings` | implicit | values of this plugin's settings form |
| `ctx.secret(name)` | declared in `secrets` | Keychain `plugin.<id>.<name>` |
| `ctx.kb.items(...)/add_decision(...)/set_status(...)` | `kb:read` / `kb:write` | shared tables, §5 |
| `ctx.notes_section(title, md)` | `notes:write` | stores as `plugin_outputs(kind="notes_section")`; rendered under the notes with attribution; **never mutates user notes** |
| `ctx.export(connector, payload, confirm_token)` | `export:<connector>` | host connector, §7.4 |
| `ctx.progress`, `ctx.log`, `ctx.cancelled`, `ctx.host.supports("llm.stream")` | implicit | capability probing |
| `ctx.policy.cloud_allowed` | implicit | read-only; lets plugins degrade gracefully under lockdown |

Never available: raw DB, arbitrary filesystem, sockets/HTTP, subprocess, Keychain beyond declared secrets, core settings write, other plugins' rows.

---

## 7. Permissions, consent, lockdown, LLM policy

### 7.1 Scope catalogue (v1)

Each scope carries a data class used by the consent UI and by lockdown logic.

| Scope | Meaning | Class |
|---|---|---|
| `recordings:read` | metadata of the bound/open meeting | local |
| `transcript:read` / `transcript:read:all` | transcript + speakers of the bound meeting / of every meeting | local (:all = **history**) |
| `notes:read` / `notes:read:all` | notes of bound / all meetings | local |
| `audio:read` | raw audio of the bound meeting, during processing only | local (sensitive) |
| `people:read`, `identity:read` | names/roles/orgs; which speaker is the user | local |
| `notes:write` | append an attributed section under the notes | local |
| `kb:read`, `kb:write` | shared action items/decisions across meetings | local |
| `llm:call` | send text you (or the host) assembled to the user's configured model | **egress iff provider is cloud (decided per call)** |
| `llm:audio` | send audio to a cloud transcription/analysis model | **egress always** |
| `export:file` | write files to a folder the user picks | local |
| `export:reminders` | create Apple Reminders via the host | local |
| `export:<cloud connector>` (post-launch: `todoist`, `linear`, `notion`) | host-implemented outbound writes | **egress always** |
| `mcp:expose` | surface this plugin's read-only tools to MCP clients | **egress-adjacent** (MCP clients are usually cloud LLMs) |

There is intentionally no `net:*` scope. A plugin cannot ask for the network. Third-party Python that wants one is rejected at review.

### 7.2 Consent UX

Install/enable sheet (`plugin-host.js`, host-rendered, text from the manifest only via `textContent`):
1. Header: name, publisher, verified badge (registry-signed / bundled / "unsigned, developer mode"), tier line ("Declarative: no third-party code" vs "Includes code that runs on your Mac").
2. Permissions grouped by data class, plain language and computed, not static:
   - "Reads the transcript of the meeting you have open." vs "Reads transcripts of **all** your meetings."
   - "Sends text to your AI provider: **Anthropic (cloud)**" or "Uses your local model; nothing leaves this Mac" (computed from the current provider via `policy.provider_allowed`).
   - Red callout for anything egress-capable, with the "what" and "where".
   - `audio:read` shows the lease window.
3. Required scopes are all-or-nothing. Optional scopes are individual toggles; plugins must work without them.
4. Runtime confirmations: the first `export:*` action per rule set shows a payload preview; "Always allow for this rule set" is stored per rule set. `llm:audio` shows the exact data sent.
5. Updates that add scopes, change tier, or change `tree_sha256` for Tier 2 re-prompt with a diff. Tier 0 updates that keep scopes can auto-apply (opt-in toggle).
6. Settings > Plugins: list with state, last error, permissions with revoke, **activity** (last N audit rows: calls per scope, LLM tokens, export count), "Delete data", "Export data".

Grants live in `plugin_grants` (DB), not `config.json`, so every grant/revoke is auditable. For managed deployments the enforceable source is the env policy in §7.5, because anything in the user's data dir is user-editable.

### 7.3 LLM broker (`plugin_host/llm.py`)

- New core function `credentials.call_llm_messages(messages, system, provider, model, max_tokens, schema, stream, trace_name)` generalizes `_call_configured_llm` (`credentials.py:427-441`) to multi-turn across the existing providers (anthropic/openai/custom/local MLX) and keeps the same `policy.provider_allowed` check on every call. The existing single-turn function becomes a one-message wrapper.
- Broker rules, applied to every plugin call in this order:
  1. Plugin enabled and `llm:call` granted; `plugins_excluded` recording check.
  2. `policy.lockdown_enabled()` and provider cloud => raise `LockdownError` (surfaced as a clean "Disabled by your organization's policy" state, not a 500).
  3. `manifest.llm.cloud == "never"` and provider is cloud => refuse with "This plugin only works with a local model; switch provider in Settings".
  4. Per-plugin budget: default 200k input tokens/day and 20 calls/min (user-adjustable in the Plugins pane), to stop runaway loops and surprise bills.
  5. `ai_trace.span(... trace_name="plugin:<id>:<purpose>")` so every plugin call is in the local trace (inputs/outputs stay local, and `ai_trace.prune()` already bounds retention).
  6. Structured output: host validates against the plugin's JSON schema (`jsonschema` is already in the lockfile) with one repair retry.
- Provider choice: the user's `notes_llm_provider` by default. Plugins can say `prefer: "local"` and the broker honors it if a local model is configured; they cannot select a cloud provider the user has not configured and cannot read keys.
- Streaming: NDJSON over the existing `ThreadingHTTPServer` (manual chunked writes; a handler helper `req.stream_ndjson(iterable)`). Each live stream holds a thread; cap concurrent streams at 4.
- `ctx.llm.audio` goes through the existing Gemini client path (`credentials.get_client`, which already checks lockdown at `:671`). Its privacy copy must state "audio bytes are sent inline" (the coaching README's "Files API copy deleted" claim is false per `diarization.py:428-429`; fix in WP12).

### 7.4 Connectors (the only outbound path besides the broker)

Core module `plugin_host/connectors/` with `file`, `reminders` (osascript/EventKit, local) at launch; cloud connectors later. Each calls `policy.require_outbound_allowed("export:<name>")` before any I/O when egress-class, requires the per-action confirm token, writes a `plugin_audit` row, and is idempotent through `task_exports`. Credentials for cloud connectors are host-held in Keychain (`plugin.<id>.<connector>`); the plugin never sees them.

### 7.5 `enterprise_lockdown` enforcement: five layers

| Layer | Mechanism | Fails closed? |
|---|---|---|
| L1 Load-time | `registry.refresh()` evaluates `policy.lockdown_enabled()` and managed env policy on each request path (cheap: cached by env + config mtime). Plugins with `llm.cloud: "required"` or any `export:<cloud>`-only function -> `state=blocked_policy`, not loaded, UI shows "Blocked by your organization". Plugins with `works_offline: true` load, with `ctx.policy.cloud_allowed == False`. | Yes |
| L2 Broker | `provider_allowed()` on every call, see §7.3; `LockdownError` mapped to a clean API error `{"error": "...", "code": "policy_lockdown"}` (fixes the generic-500 behavior from `http.py:138-139`) | Yes |
| L3 Connectors | `require_outbound_allowed` first line of every egress connector | Yes |
| L4 Python tripwire | `sys.addaudithook` installed at server start (`plugin_host/guard.py`): (a) from any frame attributed to a plugin module (`__name__` starts with `cora_plugin_`, walked via `sys._getframe`): deny `socket.connect`/`socket.getaddrinfo` to non-loopback, `subprocess.Popen`, `os.system`, `os.exec*`, `os.posix_spawn`, `ctypes.dlopen`, `open` of the DB, credentials file, or anything outside the plugin's own data dir and granted recording dirs; (b) when lockdown is on, additionally deny `socket.connect` to non-loopback for **any** frame in the server process (defense in depth for the existing paths, e.g. a dependency attempting a model download). | Yes for Python-level calls; see limits |
| L5 Electron | frame sandbox + CSP (`connect-src 'none'`, `frame-src 'none'`, `form-action 'none'`), `will-frame-navigate` deny, `setWindowOpenHandler` deny-by-default with `open-external` behind an allowlist **and** a lockdown check, `session.webRequest.onBeforeRequest` blocking non-loopback http(s). Main reads `VOICECOACH_ENTERPRISE_LOCKDOWN` and config.json itself. | Yes |

Plus:
- **MCP gate** (WP0): `mcp_server.py` refuses to start under lockdown unless an admin sets `VOICECOACH_MCP_LOCAL_CLIENT=1` (attesting the MCP client is a local model). Without this, transcripts leave via Claude Desktop/ChatGPT regardless of plugins, contradicting `policy.py:5-8`.
- **Managed plugin policy (env, MDM-settable, user cannot change from inside the app):**
  `VOICECOACH_PLUGINS=off | allowlist | open` (default `open` for consumers; `allowlist` implied under lockdown), `VOICECOACH_PLUGIN_ALLOWLIST=id@sha256,...`, `VOICECOACH_PLUGIN_TRUSTED_KEYS=<org Ed25519 pubkeys>`. Under `allowlist`, install of anything not matching id+hash is refused and Tier 2 requires a match. Install/enable/disable are audited as `actor=admin|user`.
- **Conformance test** (`tests/test_plugin_lockdown.py`, runs in CI and is SOC 2 evidence): loads a hostile sample plugin and asserts that under lockdown every one of {plugin socket, subprocess, broker cloud call, cloud connector, MCP start, frame fetch} is denied and audited.

Honest limits of L4: audit hooks do not see native-extension sockets or syscalls that bypass Python, so a malicious C extension or a vendored native wheel can evade it. Mitigations: registry review rejects native code in plugin packages (pure-Python only, scanned in CI), `requires.host_packages` limits dependencies to those already in the bundle, and §7.6.

### 7.6 Trust model and the upgrade path

- Tier 0/1 carry no third-party Python. Their risk is prompt content and UI, both host-mediated.
- Tier 2 trust = review + signature (§10). Reviewers check: AST lint (no `socket`, `requests`, `urllib`, `http.client`, `subprocess`, `ctypes`, `sqlite3`, `importlib` of core, `os.system`), import guard compliance, scope minimality vs actual `ctx` use, license, size, no native code.
- **Import guard** (`sys.meta_path` finder): imports of `db`, `credentials`, `diarization`, `paths`, `policy`, `plugin_host.*` internals, `sqlite3`, `socket`, `requests`, `urllib3`, `httpx`, `subprocess` from a module named `cora_plugin_*` raise `ImportError("not available to plugins; use ctx.*")`. This catches accidental coupling (the nine private helpers `engine.py:18-29` imports today) and naive abuse.
- **Upgrade path**: because `ctx` is RPC-shaped, v2 can run Tier 2 in a child process under `sandbox-exec` (network denied, filesystem limited to the plugin dir) speaking JSON-RPC over stdio, reusing the loader and consent model. Third-party unsigned Python becomes installable at that point. Not in this proposal's schedule.

---

## 8. UI contribution points

All plugin-provided strings go through `esc()`/`textContent`. Icons come only from the fixed `data-icon` set. Markdown goes only through `renderMarkdownSubset` (`detail.js:316-339`, escape-first).

### 8.0 Prerequisite renderer refactor (WP8, blocking everything below)

- New first-party classic script `src/ui/web/js/plugin-host.js`, inserted before `init.js` in the ordered list (`index.html:683-700`; update `scripts/lint-ui.js` order check). It fetches `GET /api/plugin-host/contributions`, renders contributions, owns consent sheets and the frame bridge. No plugin JS is ever loaded into the main document.
- Convert static handlers to delegation: `notepad.js:21-24` and `search.js:153` (tab clicks) -> one delegated listener on `.notepad-tabs`; `settings.js:5-8` -> delegated on `.settings-nav`; `search.js:17-27 getActivePanel` -> skip plugin panels (`data-notepad-tab^="plugin:"`); `core.js:9-21,49-62` `showView` -> dynamic `titles`/load hooks map (also fixes `undefined` title for unknown views).

### 8.1 Recording detail tabs (`index.html:305-310` buttons, `:311-336` panels)

`contributes.recording_tabs[]`, buttons appended with `data-notepad-tab="plugin:<id>:<tab>"`. `render` modes:
- `output`: host renders `plugin_outputs` of a `kind` (markdown via `renderMarkdownSubset`, or JSON through a small table/list/score-card renderer keyed by `content_json.type`). Shows a stale banner ("Speaker identity changed; Re-run") when `stale=1`, with the plugin's declared rerun action. **Tier 0 uses only this mode.**
- `schema`: host-rendered widgets from `content_json` (key-value, checklist, timeline).
- `frame`: sandboxed frame (§8.4).
Tab visibility respects grants and `plugins_excluded`. Errors from a plugin tab render a bounded error card, never break the page.

### 8.2 Actions (`.notepad-chip-row`, `index.html:259-267`)

`contributes.actions[]` with `where`: `recording.chips` | `recording.menu` | `person.menu`. Visibility is evaluated in `loadNotepad()` next to the reprocess/summarize toggles (`detail.js:139-273`) from a declarative `visible_when` (`has_notes`, `has_transcript`, `min_duration_seconds`, `min_speakers`, `identity_confirmed`). `invoke` is `{pipeline}` (Tier 0), `{route}` (Tier 2, POST to the plugin's own prefix), or `{chat_persona}` (opens the chat dock). `confirm` shows a host dialog.

### 8.3 Chat slot (`index.html:337-340`)

Replace the disabled "Ask anything... Coming soon" row with a host chat dock: persona dropdown (core persona "Ask this meeting" ships first and delivers the long-promised feature with zero plugin code; plugins add personas), a provider badge ("Local model" / "Anthropic (cloud)") so egress is always visible, a setup form rendered from `inputs_schema` (e.g. roleplay: choose the counterpart speaker and moment), streaming transcript, "End session" -> optional debrief pipeline -> `plugin_outputs`. Persistence in `chat_sessions/chat_messages`. Context attached **server-side** per grants; the renderer never receives the transcript for chat. Voice is out of scope (renderer denies media except clipboard, `main.js:1000-1003`).

### 8.4 Settings (`index.html:369-378` nav, `:379-557` panels)

- Core "Plugins" panel (list, consent, activity, budgets, delete data).
- Per-plugin settings: `contributes.settings.schema` rendered by the host from a JSON-Schema subset (string, number, boolean, enum, textarea, array-of-objects for rule sets, `secret`, `code` with JSON validation and **dry-run preview**). Stored in `plugin_kv(namespace='settings')`; secrets to Keychain.

### 8.5 Full-page views and Tier 1 frames

- `contributes.views[]` add a sidebar item (`index.html:196-200`) under a collapsible "Plugins" group (cap 5 visible).
- Frame mechanics:
  - Served by a new `GET /plugins/<id>/<path>` handler (sibling of `serve_static`, `media.py:79-84`) from `DATA_DIR/plugins/<id>/<ver>/ui/` or bundled `plugins/<id>/ui/`. Strict traversal check (`resolve().relative_to(root)`), no directory listing, no symlinks, only declared `ui/` tree. Public like other static files (code only; data comes via bridge).
  - `Handler.end_headers` is refactored to allow per-response overrides. For `/plugins/` responses: drop `X-Frame-Options`, set `Content-Security-Policy: sandbox allow-scripts; default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'none'; frame-src 'none'; frame-ancestors 'self'; form-action 'none'; base-uri 'none'`, and `Cross-Origin-Resource-Policy: cross-origin` (an opaque-origin document's own subresource loads count as cross-origin).
  - `authorize()` change: permit `Origin: null` for `GET /plugins/**` only (needed for CORS-mode fonts/modules from an opaque origin); add `Access-Control-Allow-Origin: *` on those responses. Still rejected for every `/api` and `/media` path.
  - Embedding: `<iframe sandbox="allow-scripts" src="/plugins/<id>/index.html" referrerpolicy="no-referrer">`. Never `allow-same-origin`, `allow-popups`, `allow-top-navigation`, `allow-modals`. Main CSP gets explicit `frame-src 'self'` (`index.html:6`). Use a relative `src`, never a hard-coded `127.0.0.1` (the remote/Tailscale design must be able to change the public origin).
  - Result: opaque origin => no `vc_token` cookie (HttpOnly + SameSite=Strict + cross-site), no `document.cookie`, no `parent`/`top` access, no `electronAPI`, `fetch` blocked by CSP and by `Origin: null` rejection.
- **Bridge**: `plugin-host.js` creates a `MessageChannel` per frame on load, transfers `port2`, validates `event.source === iframe.contentWindow`, and speaks typed verbs only: `meeting.current`, `meeting.transcript`, `notes.get`, `kb.list`, `kb.setStatus`, `outputs.get`, `kv.get/set`, `llm.chat` (streamed), `route.call(path, body)` (only the plugin's **own** `/api/plugins/<id>/` prefix), `ui.toast`, `ui.confirm`, `ui.resize`. Renderer checks scopes, then calls `POST /api/plugin-host/rpc {plugin_id, method, args}`; the server re-checks grants from the DB (authoritative) and audits. No generic API proxy, ever (`/api/settings` write -> VM sync/log upload exfil, see §9.2).
- `cora_sdk/ui/cora-plugin.js` (classic UMD, no build step) wraps the bridge: `Cora.meeting.current()`, etc.

---

## 9. Server integration

### 9.1 Routes

- One prefix route `@route("GET"|"POST", "/api/plugins/", prefix=True)` in a new `api/routes/plugins.py` (added to the import list at `routes/__init__.py:2`). It runs behind the unchanged `Handler.authorize` (loopback Host/Origin + token; no change to the main API's security model), then: parse `<id>` and subpath; require plugin `enabled` and `state in (ok, degraded)`; look up the manifest-declared route (method + path); check `granted ⊇ route.scopes`; check lockdown mapping; apply a per-plugin rate limit; build `PluginRequest` (JSON body <= 1 MB inherited from `http.py:64-71`, plus `recording_id` validated via `safe_folder`-style check); call the plugin handler with a bound `ctx`; serialize only JSON (or NDJSON stream via the host helper). Plugins never receive the raw `req` (cannot `serve_file` or set headers).
- Management API (exact routes): `/api/plugin-host/{list, contributions, install, enable, disable, uninstall, grants, runs, audit, rpc, chat/send, dev-events}`. Install/enable/uninstall/grant are state-changing and audited; they require the normal token and a JSON `confirm` field the UI only sets after the consent sheet.
- `POST /api/settings` gets a core-key allowlist plus a hard deny for anything beginning `plugin:`; the plugin settings route is separate. This is a prerequisite because `vm_sync_host`/`log_upload_url`/`transcription_engine` are writable today.

### 9.2 Pipeline and views

- `runner.py:343`: add `events.emit("recording.processed", ...)` then `events.emit("notes.generated", ...)`; gate the `:376-378` unlink on the audio lease; `:410-428`: emit `recording.merged` and mark parent outputs stale. `diarization.py:663-688`: replace the coaching call with the same emit. `diarization.py:287-337`: emit `identity.changed`; delete `clear_coaching_artifacts` once coaching migrates.
- `api/views.py:522-524` `plugins` payload becomes the generic list (id, name, enabled, state, tier, load_error, contributions summary). `recording_item(detailed=True)` gains `plugins: {<id>: {outputs summary, stale}}` instead of hard-coded `gemini_coaching/delivery_metrics` keys. The stage machine drops `ready_for_coaching/coached` for a core `ready` stage plus plugin badges (`views.py:346-353`, `index.html:234`, `core.js:25`, `mcp_server.py:166-177`).

### 9.3 Remote deployment (Mac Studio + iPhone over Tailscale)

The SDK stays remote-agnostic: plugin frames use relative URLs; the bridge goes through the same token-gated API; `_allowed_hosts` is the single place a remote design widens Host/Origin pinning and it applies to `/plugins/` automatically. Plugin routes inherit whatever authentication the remote layer adds. The consent sheet and Plugins pane are rendered by the host UI, so they work on any front end that runs the same renderer. No plugin API assumes the user is physically at the machine except `export:reminders` (reports "unavailable on headless host").

---

## 10. MCP relationship

- `python/mcp_server.py` stays a separate, read-only stdio process; it is **not** the plugin runtime and plugin Python never runs inside it (that would bypass `ctx` enforcement).
- It gains: (1) the lockdown gate (§7.5), (2) `VOICECOACH_DATA_DIR` passthrough in the generated config (`api/routes/settings.py:48-74`), (3) stale-coaching-field fixes, (4) declarative plugin contributions: for each enabled plugin with `mcp:expose` granted, `contributes.mcp_tools[]` become tools that read `plugin_outputs` of a `kind` (or `kb.action_items`/`kb.decisions`) read-only, with `source.output` / `source.kb` descriptors. A few generic tools (`cora_kb_search`, `cora_action_items`) are core.
- Phase B (post-launch): MCP server becomes a client of the local API using a second, read-only MCP token, so Tier 2 Python tool handlers can run under `ctx` in the server process, and write tools can exist behind explicit opt-in.
- Portability and positioning: Tier 0 packs are plain markdown + JSON, deliberately close to Claude Skills and Screenpipe's `pipe.md`, so `cora-plugin export-skill` can emit a Claude-Skill-shaped folder from a pack. Cora plugins are exposed over MCP, so Cora is the meeting runtime that agents call, not another silo. Competitor research (Screenpipe's pipe store, Anarlog's `plugin.json` SDK, Granola Recipes, Fireflies AI Skills) means launch copy must not claim "no one has plugins"; the defensible claim is "the open, local-first plugin platform built around structured meeting data: speakers, people, transcript, notes, action items; plugins can write back and run on your own model".

---

## 11. Packaging, install, update, signing

### 11.1 Package format

`<id>-<version>.coraplugin` = zip containing `plugin.json`, files, `SHA256SUMS` (every file), and `integrity.tree_sha256` (hash of sorted `path:sha256` list excluding `__pycache__`). Limits: 25 MB, no symlinks, no absolute paths, pure-Python only for Tier 2. Plugin imports run with bytecode writing disabled so `__pycache__` never pollutes the tree hash.

### 11.2 Locations and loading

- Bundled first-party: `APP_ROOT/plugins/<id>/` (unpacked, inside the signed app; `paths.PLUGINS_DIR` finally used).
- Installed: `DATA_DIR/plugins/<id>/<version>/` plus a `current` pointer file; the previous version is kept for one-click rollback.
- Dev: `DATA_DIR/plugins-dev/<id>` (symlink or copy), enabled only by `VOICECOACH_PLUGIN_DEV=1` or Settings > Developer, hidden when lockdown/managed policy is on.
- Loader: `importlib.util.spec_from_file_location("cora_plugin_<id_sanitized>", entry, submodule_search_locations=[plugin_dir])` so relative imports work and module names are attributable by the guard; load errors are recorded into `plugins.last_error`; no process-lifetime import cache (replaces `_cache`, `plugin_registry.py:45-59`); enable/disable takes effect without restart (also removes the import-time `ARCHETYPES` capture at `api/core.py:27,32`).
- Tree hash recomputed and compared to `plugins.tree_sha256` at every load; mismatch => `state=load_error("modified on disk")`, never silently loaded. (This detects tampering by anything that cannot also edit the DB; for managed fleets the env allowlist is the enforceable pin.)

### 11.3 Signing and registry (review + signed registry)

- Registry = a public GitHub repo `cora-plugins` with `index.json`: for each plugin `id`, versions, `sha256`, `url` (GitHub Release asset), tier, publisher, scopes, review date, and a detached Ed25519 signature over the canonical entry. Signing key is held offline by the owner; the app embeds the public key list (rotation: `keys[]` with `not_after`; `revoked.json` lists revoked `id@sha256`, checked at startup and at every enable).
- **Submission flow**: third party opens a PR adding `submissions/<id>/` (source, not binary). CI builds the package deterministically, runs `cora-plugin lint --strict` (manifest, scope-vs-AST usage, import deny list, no native code, size), the lockdown conformance harness against the package, and license check. A maintainer reviews the diff, merges, and CI signs the resulting `sha256` with the registry key. Authors do not hold signing keys in v1; optional author signatures for provenance are v1.1.
- **Client verify**: `cryptography`'s Ed25519 (made an explicit dependency). Verify signature over `index.json` entry, verify package hash equals entry hash, verify `tree_sha256`, then show consent. Sideload (`.coraplugin` file drop) verifies the same signature if present; unsigned sideload is allowed for Tier 0/1 with a loud "unsigned" badge and never for Tier 2 outside dev mode.
- **Network disclosure**: "Browse plugins" and update checks fetch static JSON/assets from GitHub: no identifiers sent, user-initiated, update check opt-in (default off), and **blocked entirely under lockdown**. Enterprise: `VOICECOACH_PLUGIN_REGISTRY=file:///...` or an internal URL with `VOICECOACH_PLUGIN_TRUSTED_KEYS`; under lockdown only file-based registries/sideload with org-signed packages.
- **Updates**: never auto-apply when scopes expand, tier changes, or Tier 2 code changes; show diff and re-consent. Tier 0 same-scope updates may auto-apply (opt-in). Rollback keeps the previous directory and grants.
- **Launch registry** can be just the signed `index.json` plus a "Plugins" section in the README; the in-app browse UI can follow in week 5/post-launch.

---

## 12. Developer experience

`cora-plugin` CLI (Python module `cora_sdk`, shipped in the app and as a pip package; no Node needed):

| Command | Does |
|---|---|
| `cora-plugin new <name> --kind pack\|ui\|python` | scaffold with a working example, schema `$schema` links, README, tests |
| `cora-plugin dev` | link into `plugins-dev/`, validate, watch files: manifest/prompt edits reload instantly; Python reloads by re-executing a fresh module namespace (old in-flight deliveries finish on the old module); UI frames reload via SSE `/api/plugin-host/dev-events`; shows load errors inline in the Plugins pane |
| `cora-plugin test` | `cora_sdk.testing.FakeHost`: fixture recordings (synthetic/fictional only), event replay, scripted fake LLM, scope-denial assertions |
| `cora-plugin lint [--strict]` | manifest schema, scopes declared vs actually used (AST), forbidden imports, size |
| `cora-plugin pack` / `sign --dev-key` | produce `.coraplugin`, dev signature for local testing |
| `cora-plugin publish` | opens the registry PR |
| `cora-plugin export-skill` | emit a Claude-Skill-shaped folder from a Tier 0 pack |

**10-minute hello-world (Tier 2, ~15 lines):**
1. `cora-plugin new hello --kind python` (30 s).
2. `plugin.json` already declares `events: ["notes.generated"]`, `permissions.required: ["notes:read","notes:write"]`.
3. `plugin.py`:
```python
from cora_sdk import Plugin
plugin = Plugin()

@plugin.on("notes.generated")
def on_notes(ctx, ev):
    notes = ctx.notes()
    words = len(notes.markdown.split())
    ctx.notes_section("Hello from my plugin", f"These notes are {words} words long.")
```
4. `cora-plugin dev`; open Cora; Plugins pane shows "hello (developer mode)"; click Enable and the consent sheet; re-summarize any recording; the section appears under the notes within seconds. Edit and save; it hot-reloads.
5. `cora-plugin test` runs the same hook against a fictional fixture. `cora-plugin pack` yields a `.coraplugin`.
A Tier 0 hello-world is the same minus `plugin.py`: one prompt file and one pipeline entry (about 5 minutes).

Docs deliverables: `docs/PLUGINS.md` (concepts, manifest reference generated from the JSON Schema, scope reference, security model, review checklist), `docs/PLUGIN_COOKBOOK.md` (the six first-party plugins as annotated examples), CONTRIBUTING pointer.

---

## 13. Declarative engine (Tier 0) in brief

- **Template renderer**: `{{path}}` substitution and `{{json path}}` only; no loops or logic (so templates cannot become a code-execution surface). Host-built context keys: `transcript.text`, `transcript.self_only`, `transcript.speaker[<id>]`, `notes.markdown`, `people`, `recording.title/date`, `settings.*`, `kb.open_items`, `roadmap` (a plugin setting). Context size is budgeted against `llm.min_context_tokens`, truncated with explicit "[truncated]" markers.
- **Pipeline steps**: `llm` (template + schema + max_tokens), `rules` (apply a rule set to structured items), `export` (to a connector). Sinks: `output`, `notes_section`, `kb.action_items`, `kb.decisions`, `chat_context`.
- **Rule sets** (todo export): JSON `{ "rules": [ { "when": {"owner":"self","status":"open","text_matches":"(?i)send|draft"}, "then": {"export":"reminders","list":"Cora","title":"{{item.text}}","due":"{{item.due}}"} } ] }`. Evaluated by the host over `action_items`; regex is `re2`-style restricted (length-capped, no backrefs) to avoid ReDoS; dry-run preview in settings shows "3 items would be exported" before anything is sent.
- **Note templates**: `contributes.templates[]` feed a core template registry (`DATA_DIR/templates/` for user-edited files + plugin-contributed). That replaces the hard-coded `SUMMARY_FORMATS` (`pipeline/notes.py:16-33`) and the frontier system prompt (`:378-397`), and the existing `/api/recording/summary-formats` route (`recordings.py:22-27`) lists both. Front-matter: `label`, `sections`, `output_schema?`, `match: {meeting_types}`. This is the owner's "user-editable templates" goal delivered as the simplest plugin type.

---

## 14. How the owner's plugin ideas map onto the SDK

| Idea | Tier | Mechanism | Scopes | Notes |
|---|---|---|---|---|
| 1:1 AI roleplay (AI plays the other person) | 0 | `chat_personas` with `inputs_schema` (pick counterpart + moment) and a `prepare` pipeline step that builds a cached speaking-style profile from that speaker's turns; host chat dock; end-of-session debrief pipeline | `transcript:read`, `people:read`, `llm:call` | Flagship demo. Clear egress badge in the dock. Local-model-capable (`llm.cloud: optional`). Voice later. |
| Communication coaching | 2 (first-party, migrated `cora.coaching`) + 0 lite pack | Delivery metrics need numpy + audio (Tier 2 hook, local, works under lockdown); Gemini coaching via `llm.audio` (cloud, disabled under lockdown); a transcript-only pack variant covers the no-audio case | `audio:read`, `transcript:read`, `identity:read`, `llm:call`, `llm:audio` (optional) | §15 |
| Storytelling coaching | 0 | pipeline on `recording.processed` -> markdown tab `Stories` | `transcript:read`, `llm:call` | Smallest possible plugin; used as the documentation example |
| Company knowledge base: todos/decisions across meetings | 2 first-party `cora.kb` + core tables | `notes.generated` -> structured extraction -> `action_items`/`decisions` with dedupe against open items; KB view (Tier 1 frame or host `schema` view); MCP tools `kb.search`; user-initiated backfill job with token estimate | `notes:read`, `transcript:read`, `kb:read`, `kb:write`, `llm:call`, `transcript:read:all` (optional for backfill) | Core owns tables and stable IDs; plugin owns extraction and UI |
| Keep-on-track-with-roadmap | 0 | roadmap is a plugin setting (`textarea`/file); pipeline compares each processed meeting to roadmap and writes a drift/alignment output + KB decisions; weekly digest when `schedule.weekly` lands | `transcript:read`, `kb:read`, `llm:call` | Reads KB via host context, not own code |
| Convert outputs to a todo app via user rule set | 0 + host connectors | rule set JSON + dry-run + connector `reminders`/`file` at launch; cloud connectors post-launch with per-action confirm | `kb:read`, `export:reminders`, `export:file` | Idempotent through `task_exports` |
| Shared team todos | later (post-launch) | `action_items.version` + `origin` fields shipped now; a future Tier 2 `cora.team-sync` needs an egress connector and sync infra (peer-to-peer over Tailscale or a shared git/folder backend) | `kb:*`, `export:team-sync` | Pulls against local-first; blocked under lockdown; not in the 4-5 week scope |
| Third parties | 0/1 via registry; 2 only after review | `cora-plugin new/dev/test/pack/publish` | per manifest | Cold start: ship 5-6 first-party plugins as the examples, because the repo has 0 stars and a marketplace will not fill itself |

---

## 15. Migrating `plugins/coaching` onto the SDK

Goal: coaching becomes `cora.coaching`, the reference Tier 2 plugin, with no core knowledge of coaching.

1. **Layout**: add `plugins/coaching/plugin.json` (`id: cora.coaching`, tier 2, events `recording.processed`, `identity.changed`, `recording.merged`; scopes `audio:read`, `transcript:read`, `identity:read`, `people:read`, `llm:call`, `llm:audio` optional; `lockdown.works_offline: true`, `llm.cloud: optional`). `plugin.py` wraps the existing functions behind hooks. Default **disabled**, as today.
2. **Stop importing core privates** (`engine.py:18-29`): host services replace them: `ctx.speakers()`, `ctx.audio()`, `ctx.transcript()`, `ctx.llm.audio()`, `ctx.llm.chat()` (so archetype classification is no longer Gemini-only; `engine.py:547-577` currently bypasses `call_configured_llm`).
3. **Routes**: move `api/routes/coaching.py` into the plugin as `/api/plugins/cora.coaching/{coach,confirm-and-coach}`; keep `/api/gemini-coach` and `/api/confirm-and-coach` as thin aliases (a core alias table) for one release; both now enqueue a run and return `{run_id}` instead of blocking a request thread for minutes.
4. **Hooks**: replace the auto-pilot block (`diarization.py:663-688`) and `clear_coaching_artifacts` (`:332-337`) with `recording.processed`/`identity.changed` handlers (`outputs.mark_stale`). Fixes: coaching now runs on the default local pipeline when enabled, stale-after-merge, and audio-before-deletion (lease).
5. **Data**: write results to `plugin_outputs(kind="coaching" | "delivery_metrics")`. One idempotent migration copies existing `recordings.coaching/delivery_metrics` and on-disk JSON; the DB columns and `db.py:367,375` allowlist entries stay for one release as a read-through shim, then are dropped. `views.py:160-190,336-412,440-442` read via `plugin.view()` outputs.
6. **Taxonomy**: `meeting_types.py` becomes the only source; delete the copies in `api/core.py:34-107`, `engine.py:285-294` (keep only per-id rubric text in the plugin), and `src/main.js:331-368`. Drive the archetype picker and tray submenu (`main.js:370-425,819-875`) from `/api/plugin-host/contributions` so they appear only when a plugin that declares `contributes.meeting_types` is enabled.
7. **Stage machine**: core `ready` + plugin badge; remove `ready_for_coaching/coached` (`views.py:346-353`).
8. **Honesty and hygiene fixes**: correct the "Files API copy deleted" claim (`engine.py:642`, README `:17-19`) to "audio is sent inline"; `shutil.which("ffmpeg")` instead of `/opt/homebrew/bin/ffmpeg` (`engine.py:265`); point `backfill_delivery_metrics.py` at `paths.*`; delete `python/gemini_coach.py`, `coach_engine.py` references, the orphan `.delivery-*` handler (`navigation.js:7-14`) and CSS (`styles.css:872-924`); fix MCP's stale coaching fields.
9. **Lockdown behavior**: delivery metrics (local numpy) still run; the Gemini pass is refused by the broker with a clean message and the tab shows "Cloud coaching disabled by policy."
10. **Tests**: `tests/test_plugin_loader.py` (discovery, manifest errors, hash mismatch), `test_plugin_events.py` (emit from a second process, lease, retries), `test_plugin_permissions.py`, `test_plugin_lockdown.py`, a coaching hook test against fictional fixtures.

---

## 16. Schedule, critical path, cut list

Effort unit = one focused founder+agent day. Critical path: WP1 -> WP2 -> WP3 -> WP4 -> WP7 -> WP8 -> WP13. WP0, WP5, WP6, WP10, WP11 parallelize across agents.

| Week | Outcome |
|---|---|
| 1 | WP0 (hardening), WP1 (loader/registry), WP2 (tables, stable action items), day-1 spike on the opaque-origin frame (R1) |
| 2 | WP3 (events, worker, audio lease), WP4 (ctx, routes, permissions, audit), WP5 (broker) |
| 3 | WP6 (lockdown layers + conformance), WP7 (Tier 0 engine + templates), start WP8 |
| 4 | WP8 (host UI: tabs, actions, chat dock, settings, consent), WP12 (coaching migration), WP13 first-party plugins |
| 5 | WP11 (CLI, docs, hello-world), launch assets, buffer |

Cut list if behind (in order): (1) Tier 1 frames and `/plugins/` serving (WP9) move post-launch; launch plugins are Tier 0/2 and need no frames; (2) in-app registry browse (keep signed `index.json` + sideload); (3) coaching data migration (keep column shim, ship hooks/routes only); (4) `schedule.*` events and weekly digest; (5) `export:reminders` (keep `export:file`). Not cuttable: WP0, lockdown conformance, consent sheet, audit table, the audio lease, stable action-item IDs.

Work packages (effort in agent-assisted days; "L" = launch-minimum):

| ID | Title | Depends | Days | L |
|---|---|---|---|---|
| WP0 | Core hardening prerequisites: `/api/settings` allowlist, MCP lockdown gate + data-dir fix, `end_headers` overrides, `will-frame-navigate`/window-open/webRequest/`isTrustedUrl` in `security.js` | none | 2.5 | yes |
| WP1 | Manifest schema, validator, `plugin_host` loader/registry, import guard, state machine, replace `plugin_registry.py` | none | 3 | yes |
| WP2 | DB tables, KV/outputs/grants/audit APIs, stable `action_items` + `todo_state` migration | WP1 | 3 | yes |
| WP3 | Event bus, worker, audio lease, emit points in runner/diarization/recordings/transcript_edit | WP1, WP2 | 3 | yes |
| WP4 | `PluginContext`, permission enforcement, `/api/plugins/<id>/` + `/api/plugin-host/*`, audit, rate limits | WP2, WP3 | 3 | yes |
| WP5 | LLM broker: `call_llm_messages`, structured output, NDJSON streaming, budgets | WP4 | 3 | yes |
| WP6 | Lockdown layers L1-L4, managed env policy, conformance test | WP4, WP5 | 2.5 | yes |
| WP7 | Tier 0 engine: renderer, pipeline steps, sinks, rule sets, note-template registry | WP4, WP5 | 4 | yes |
| WP8 | Host UI: `plugin-host.js`, delegation refactor, tabs/actions/settings/chat dock, consent sheet, Plugins pane | WP4, WP7 | 5 | yes |
| WP9 | Tier 1 frames: `/plugins/<id>/`, headers, bridge, SDK js | WP0, WP8 | 3 | no |
| WP10 | Package/sign/verify/install/update/rollback, registry index, sideload | WP1, WP4 | 3 | partial (pack+verify+sideload 1.5) |
| WP11 | `cora-plugin` CLI, hot reload, FakeHost testing, docs, hello-world | WP4, WP7 | 3 | partial (1.5) |
| WP12 | Migrate coaching to `cora.coaching`; delete dead code; MCP plugin tools | WP3, WP4, WP5 | 3 (lite) + 1.5 | lite |
| WP13 | First-party plugins: roleplay, storytelling, KB, roadmap, todo-export, comm-lite | WP7, WP8 | 5 | yes |

Launch-minimum effort is about 38 agent-assisted days on the table above. That fits 4-5 weeks only with two agents working in parallel plus the cuts above available. The plan has no slack for a second large feature (e.g., Gemini transcription work from the other proposals shares the founder's review time).

---

## 17. Risks

| ID | Risk | Mitigation |
|---|---|---|
| R1 | Opaque-origin loopback frame behaves differently than assumed (XFO/CSP `frame-ancestors`, CORP, `Origin: null` handling). | Day-1 spike in Electron 44 with a stub plugin; fallback is `protocol.handle('cora-plugin')` per discovery. Tier 0 launch plugins do not depend on it. |
| R2 | In-process Python is not a sandbox; L4 tripwire is bypassable by native code or determined authors. | Tier 2 limited to signed/reviewed or org-allowlisted; pure-Python only; honest copy in docs and consent; v2 out-of-process path (§7.6). Never claim "sandboxed" for Tier 2. |
| R3 | Registry signing key compromise or a reviewed plugin turns malicious in an update. | Offline key, rotation + `revoked.json`, no auto-update for Tier 2 or scope growth, tree-hash pinning, audit trail, per-plugin kill switch. |
| R4 | Audio lease extends audio retention beyond what `retain_audio=false` users expect. | 30-minute hard cap, startup sweep, consent text, only for plugins holding `audio:read`. |
| R5 | Event worker contention with the pipeline and local MLX on the same machine (memory/CPU). | 2 workers, one in-flight per plugin, LLM budgets, defer local-model plugin work while a pipeline run is active. |
| R6 | Renderer refactor (delegated handlers, dynamic views) regresses existing UI (17 order-dependent scripts). | Land delegation first behind no feature change, extend `scripts/lint-ui.js`, manual pass of every tab/settings/search path. |
| R7 | Prompt injection through transcripts into plugin LLM calls could make a plugin act on attacker text (e.g., export rule triggers). | Exports never fire from raw model text without the rule engine and confirm; rule `when` only uses structured fields; dry-run preview; per-action confirm for cloud connectors. |
| R8 | Cold start: 0 stars, no third-party authors before launch. | Five to six first-party plugins as cookbook, 10-minute hello-world, GitHub registry index; do not market a "store" at launch. |
| R9 | Competitor claim risk (Screenpipe, Anarlog already ship plugin systems). | Positioning per §10; keep launch copy about meeting-structured data + local-first + consent/audit, not "first". |
| R10 | Scope creep in the declarative engine into a programming language. | Frozen v1 surface: templates without logic, three step types, rule sets as data. Anything else is Tier 2. |

---

## 18. Open decisions for the owner

1. Under lockdown, should MCP be refused outright (recommended) or allowed behind the admin attestation `VOICECOACH_MCP_LOCAL_CLIENT=1`?
2. Is a public registry signed by an offline owner key acceptable operationally (you are the reviewer and single point of failure), or should signing be delegated to a second maintainer before launch?
3. Should plugins be on by default for new installs (all disabled except `cora.kb`?) or opt-in only? Recommendation: all opt-in; `cora.kb` offered at onboarding.
4. Is the consent-sheet copy that names the provider ("Anthropic (cloud)") acceptable for HIPAA/DoD sales, or does legal want a stricter default (e.g., plugins refuse cloud providers unless the user explicitly enables cloud per plugin)?
5. Are you willing to ship launch with Tier 1 frames cut and `cora.kb` using host-rendered views, to protect the schedule?
6. Do you want `cryptography` promoted to a hard dependency of the base (non-`cloud`) install for signature verification, or a pure-Python Ed25519 fallback to keep the base install slim?
