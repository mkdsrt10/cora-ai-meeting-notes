# Cora beta receiver

The backend for the internal beta (spec: `docs/specs/beta-telemetry-and-updates.md`): one Python
process and one directory, run on the Mac Studio by launchd and exposed with Tailscale Funnel.
Python standard library only; no `uv sync` needed on the host.

```sh
CORA_RECEIVER_TOKEN=... python3 receiver/receiver.py --root ~/cora-beta --port 8787
```

Flags: `--root DIR` (created if missing), `--port N`, `--host` (default `127.0.0.1`; Funnel proxies
to localhost, so do not bind publicly), `--token-env NAME` (default `CORA_RECEIVER_TOKEN`). It
refuses to start without a token.

## Endpoints

| Route | Auth | Result |
|---|---|---|
| `POST /v1/events` | bearer | JSON batch (`install_id`, `display_name`, `app_version`, `git_commit`, `build_variant`, `events: [{id, name, ts, payload}]`) → `202 {"accepted": n}` |
| `POST /v1/recordings` | bearer | tar.gz body (max 2 GB) with headers `X-Cora-Install`, `X-Cora-Recording`, `X-Cora-Reason` (`feedback`\|`sample`), `X-Cora-Version`, `X-Cora-Display-Name` → `201 {"stored": "<install>/<recording>"}`; `409` if already stored |
| `GET /v1/config` | none | `config.json` merged over the defaults, re-read on every request; `500` if the file does not parse (clients then keep their cached copy) |

`401` bad or missing token, `413` body over the limit (events 16 MB, recordings 2 GB, judged from
`Content-Length` before any byte is read), `400` malformed batch, missing or unsafe ids (charset
`[A-Za-z0-9._-]`), or an unknown reason. A client that sends `Expect: 100-continue` (curl does for
large bodies) is refused before it uploads anything.

## Disk layout

```
<root>/
  config.json                      remote config, hand-edited (start from receiver/config.example.json)
  events/YYYY-MM-DD.jsonl          one line per event, UTC day of receipt; each line is the event plus
                                   install_id, display_name, app_version, git_commit, build_variant, received_at
  recordings/<install_id>/<recording_id>/
    archive.tar.gz                 the Captured Recording, exactly as uploaded
    meta.json                      headers + size + sha256 + received_at
  logs/receiver.jsonl              one line per request: ts, method, path, status, ms, ids, error (never the token)
```

Uploads stream to disk in 1 MiB pieces as `archive.tar.gz.part`; `archive.tar.gz` appears only once
the whole body has arrived. A cut-off upload leaves no folder behind, so the app's retry succeeds.

**The receiver never opens, extracts or inspects the archives it stores.** They hold meeting audio,
transcripts and notes: keep `<root>` on a FileVault-encrypted disk, `chmod 700` it, and delete
recordings once reviewed. The receiver itself prunes nothing; the report script
(`tools/usage_report.py <root>`) only reads `events/` and `meta.json` files.

## Run it under launchd

Use a dedicated checkout (not a working tree whose branch you switch) and a root outside
`~/Documents`/`~/Desktop`, which launchd agents cannot read without Full Disk Access.

Generate a token:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

`~/Library/LaunchAgents/com.cora.beta-receiver.plist` (absolute paths only; launchd does not expand `~`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.cora.beta-receiver</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/YOU/cora-receiver/receiver/receiver.py</string>
    <string>--root</string><string>/Users/YOU/cora-beta</string>
    <string>--port</string><string>8787</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CORA_RECEIVER_TOKEN</key><string>PASTE-TOKEN-HERE</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/YOU/cora-beta/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>/Users/YOU/cora-beta/logs/launchd.err.log</string>
</dict>
</plist>
```

The plist holds the token in plain text: `chmod 600` it. Load and check:

```sh
mkdir -p ~/cora-beta/logs && chmod 700 ~/cora-beta
chmod 600 ~/Library/LaunchAgents/com.cora.beta-receiver.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cora.beta-receiver.plist
launchctl print gui/$(id -u)/com.cora.beta-receiver | grep -E 'state|pid'
curl -s http://127.0.0.1:8787/v1/config
```

## Expose it with Tailscale Funnel

```sh
tailscale funnel --bg 8787        # https://<machine>.<tailnet>.ts.net -> http://127.0.0.1:8787
tailscale funnel status
curl -s https://<machine>.<tailnet>.ts.net/v1/config
```

`tailscale funnel --https=443 off` stops it. The `https://<machine>.<tailnet>.ts.net` URL is what
the build script embeds as `CORA_BETA_RECEIVER_URL`.

## Rotate the token

The token is a beta convenience, not a security boundary: every team build carries it. Rotate when
a build leaves the team or on suspicion of misuse.

1. Generate a new token and put it in the plist.
2. Restart: `launchctl bootout gui/$(id -u)/com.cora.beta-receiver` then the `bootstrap` command above.
3. Rebuild the team app with `CORA_BETA_TOKEN=<new>` (`scripts/build-app.sh --team`) and ship it.

The receiver accepts one token at a time. Installs on the old build get `401` and keep their events
queued locally for up to 7 days, so ship the new build within that window or their events are dropped
(each drop is recorded as an `events_dropped` event once they reconnect).

## Remote config

Copy `receiver/config.example.json` to `<root>/config.json` and edit it in place; it is read on
every request, no restart needed. Keys: `telemetry_enabled`, `capture_sample_rate` (0 stops sampled
captures), `capture_max_minutes`, `min_app_version` (string or null). Missing keys take the defaults.
Validate after editing: `python3 -m json.tool <root>/config.json`.
