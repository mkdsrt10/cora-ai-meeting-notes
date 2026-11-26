# Cora Plugin SDK — Proposal: MCP-native

Angle: every plugin is an MCP server. Cora hosts it (MCP client), brokers everything it can touch, and re-exports it (MCP server) to Claude Desktop, Cursor and ChatGPT. Date: 2026-10-16/17. Branch: `production`. Status: design only, nothing in the repo modified.

---

## 0. Verdict in one page

**What we build.** A plugin is a directory with a `cora-plugin.json` manifest and one or both of:
- declarative assets: prompts, personas, analyzers, note templates, rule sets, connector specs. Cora's host runs these, with no third-party code;
- an optional local **stdio MCP server** that Cora spawns in a macOS sandbox with **no network, no DB, no Keychain and no `DATA_DIR` access**.

The plugin reaches Cora data only through a per-plugin, scope-checked **`cora-host` MCP server** that Cora exposes on a private Unix socket. It reaches an LLM only through Cora (MCP `sampling` or `cora.llm.*`). Any user-visible UI is an MCP-Apps-style `ui://` HTML resource rendered in a sandboxed, no-network frame, or a host-rendered contribution (tab, action, chat persona, settings form).

**Why this angle is strong.**
1. Lockdown has one chokepoint. The plugin process cannot make outbound connections, so `policy.py` only has to be enforced in a handful of host broker functions. That is a far easier SOC 2 control story than auditing third-party code.
2. Portability is real. The same plugin server runs under Claude Desktop, Cursor or MCP Inspector. A declarative persona becomes an MCP *prompt* in Claude Desktop with no extra work.
3. It dogfoods the surface that agents already speak, and it turns the existing `python/mcp_server.py` from "parity feature" into "the plugin runtime export".

**What MCP does not give us, and what we add** (§17 is the honest list):
- permissions and consent: Cora-defined scopes;
- server-to-host data calls: the `cora-host` MCP server on a second channel;
- event subscription: manifest-declared event-to-tool bindings, which are ordinary `tools/call`s;
- long jobs: `plugin_jobs` plus MCP progress notifications;
- UI: MCP Apps conventions, spec revision pinned.

**Hard scope cut for a 4-5 week solo+agents launch** (the rest is designed but deferred):
- Launch: Tier 0 (declarative) for everyone; Tier 1 (stdio server) for **first-party signed plugins plus a Developer Mode sideload** for third-party authors; host-rendered UI contributions; the chat slot; the MCP export gateway; the audit log; the lockdown conformance test.
- Post-launch (week 6+): sandboxed `ui://` frames for third parties, signed registry and one-click install, connector marketplace, TypeScript SDK, shared team todos.

A third-party author can ship a *useful* plugin at launch with zero code (Tier 0), or with about 30 lines of Python in Developer Mode. No third party's unsigned code can run on a locked-down or default-install machine.

---

## 1. Verified starting point

I verified the discovery files against the tree on `production`. All the key claims hold. Items I confirmed or sharpened:

- `python/plugin_registry.py` (59 lines): config-flag lookup plus a hard import of `plugins.coaching.engine`, cached forever. `PLUGINS_DIR` (`paths.py:28`) is unused. Confirmed.
- **Chat slot**: `src/ui/web/index.html:337-340` is the disabled `notepad-ask-row` ("Ask anything about this meeting…", Coming soon). The tabs are at `:305-336`. Confirmed.
- **CSP** (`index.html:6`) is meta-only: `default-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; form-action 'none'`. There is no `frame-src`, so it falls back to `default-src 'self'`.
- **HTTP** (`python/api/http.py:24-53`): every response sends `X-Frame-Options: DENY` and `CORP: same-origin`. `authorize()` pins Host and Origin to loopback and requires the token (cookie or `X-VC-Token`). `Origin: null` is rejected because `"null"` is not in the allowed-hosts set. **Consequence: sandboxed or custom-scheme frames can never call `/api` directly.** That is a feature for us: all plugin UI I/O flows through the host bridge.
- `src/main/security.js:13-43`: `isTrustedUrl` prefix-matches the whole dashboard origin. `will-navigate` is guarded for main frames only. `setWindowOpenHandler` calls `shell.openExternal` for any https URL from any frame. There is no `will-frame-navigate` guard. These are prerequisites for any iframe (WP0).
- `main.js:1005-1011`: the `vc_token` cookie is set host-only for `127.0.0.1`, not port-scoped. Anything the renderer loads from another loopback port receives it. A plugin must therefore never run a server the renderer loads.
- `credentials.py:403-441`: `call_configured_llm(prompt, system_prompt, provider, model, max_tokens, trace_name)` is **single-turn and non-streaming**. The policy gate `policy.provider_allowed(...)` sits in `_call_configured_llm` (`:427-441`). It is wrapped in `ai_trace.span`, which stores inputs and outputs locally, so retention of traces matters for HIPAA.
- `python/mcp_server.py`: `from mcp.server.mcpserver import MCPServer`; `pyproject.toml:18` has `mcp>=2.2`. **Cora already depends on the Python MCP SDK, both server and client sides.** There is no `policy` import, so it is not covered by lockdown.
- `settings.py:44-75` `/api/mcp/config`: generates configs with only `command` and `args`. It does not pass `VOICECOACH_DATA_DIR`, so a non-default data dir points external MCP clients at the wrong DB.
- `runner.py`: `db.update_recording_data(... "diarization"/"call_summary")` then `log_resource_usage` (~`:339-343`); the `retain_audio` unlink is at ~`:372-378`; the continuation merge follows. There is no hook anywhere in the default pipeline.
- `db.py`: ten tables. `todo_state` is keyed `(recording_id, item_index)` and has no writer. There are no plugin tables.
- `package.json`: `python-runtime` is shipped via `extraResources`; `plugins/**` is bundled and asar-unpacked. **We can launch plugin servers with the bundled Python, with no user-installed toolchain.**
- **Policy-source subtlety**: `policy.lockdown_enabled()` reads the env var (MDM-enforceable) **or** `config.json`, which is user-writable. Per the `policy.py` docstring, only the env var is truly enforceable. Plugin admin policy must follow the same pattern (§6).
- `python/api/auth.py`: the token is minted per launch and written 0600 to `API_TOKEN_FILE` for same-user CLI tools. This already defines the trust boundary "same OS user may call the API". The MCP gateway (§11) uses exactly this mechanism and adds nothing.

---

## 2. Architecture

```
 Claude Desktop / Cursor / ChatGPT / Claude Code
        |  stdio (spawns `cora mcp`)                          [MCP client -> Cora]
        v
 +-----------------+  X-VC-Token (existing 0600 file)   +--------------------------------------------------+
 | cora mcp (proxy)| ---------------------------------> | Python API  (existing ThreadingHTTPServer)       |
 +-----------------+      POST /api/mcp/rpc             |  api/routes/plugins.py  (new, same authorize())  |
                                                        |  python/plugins/  (new package)                  |
 Electron renderer (sandboxed, strict CSP)              |    manager.py    discover/install/state/consent  |
   plugin-host.js  --fetch /api/plugins/*  ------------>|    runtime.py    spawn+sandbox+MCP client loop   |
   <iframe sandbox cora-plugin://id/...>                |    hostsrv.py    per-plugin `cora-host` MCP srv  |
        ^  MessageChannel (typed verbs only)            |    events.py     event->tool bindings, job queue |
        |                                               |    broker.py     llm / connectors / audio / notes|
 Electron main: protocol.handle('cora-plugin')          |    gateway.py    export plugin+core tools as MCP |
   forces CSP header, serves ui:// bytes from memory    |    audit.py     hash-chained plugin_audit        |
                                                        +-----------+--------------------+-------------+
                                                                    |                    |
                              stdio (MCP: Cora is client)           |                    | unix socket (MCP: plugin is client)
                                                                    v                    v
                                          +-----------------------------------------------------+
                                          |  Plugin process (sandbox-exec: deny network*,       |
                                          |  deny reads outside plugin dir + scratch)           |
                                          |  = MCP server (tools/prompts/resources, ui://)      |
                                          |  + MCP client of `cora-host` (scoped cora.* tools)  |
                                          +-----------------------------------------------------+
```

### 2.1 The four MCP relationships

1. **Cora is an MCP *client* of each plugin server.** It uses stdio as the transport and the spec's `tools/*`, `prompts/*`, `resources/*` (including `ui://`), and progress notifications. Cora is also the *sampling* and *elicitation* provider: plugins call `sampling/createMessage` for LLM text, and the host routes it through the policy-gated broker. `elicitation` is rendered as a host-owned dialog.
2. **Cora is an MCP *server* to each plugin** (`cora-host`). It is a separate MCP server instance per plugin, on a per-spawn Unix socket. The plugin SDK opens it as a second MCP client session. The tool surface is scope-filtered at `tools/list`, so a plugin literally cannot see tools it was not granted. See §9.
3. **Cora is an MCP *server* to external agents** (`cora mcp`, §11). It exports a scoped subset of the built-in tools plus plugin-contributed tools, prompts and resources.
4. **Cora does not connect plugins to arbitrary remote MCP servers.** That would be an egress path. A "remote" tier (Streamable HTTP) is designed as post-launch and is a hard-blocked class under lockdown (§3).

### 2.2 Why two channels per plugin

MCP is bidirectional on one transport only for *client-feature* requests (sampling, elicitation, roots). It has no server-to-client "call a tool" primitive. Rather than invent a private JSON-RPC method that no SDK routes, plugins get a second, completely standard MCP client session to `cora-host`. Result: plugin authors use only stock MCP SDK concepts, and the Cora-specific part is a *tool catalogue*, not a protocol.

### 2.3 Process model and runtime

- A new Python package `python/plugins/` runs inside the existing API process. MCP client sessions are asyncio-based, so we run **one dedicated asyncio loop thread**; the stdlib `ThreadingHTTPServer` handlers call into it with `asyncio.run_coroutine_threadsafe`. (Keep the HTTP server stdlib; do not rewrite it.)
- **Lazy spawn**: a plugin process starts on first need (an event job, a tool call, or opening its tab). It is stopped after 5 min idle. Maximum 4 concurrent plugin processes. Crash backoff is 1s, 5s, 30s, then `failed` with the visible stderr tail.
- **Runtime command resolution.** Manifest `runtime.kind` is `python` (bundled `python-runtime` plus plugin-vendored deps) or `node` (Electron binary with `ELECTRON_RUN_AS_NODE=1` — no Node install required) or `binary` (first-party/signed only).
- **Resource guard**: RSS watchdog (macOS does not enforce `RLIMIT_AS` reliably), default cap 512 MB, `nice` +10, and a per-call timeout (tools 30 s default; jobs up to 15 min while progress heartbeats arrive).
- **Where it runs.** Plugins run wherever the Cora Python server runs. On the Mac Studio headless setup, plugins run there and the iPhone voice-note path simply produces `meeting.processed` events on the server. v1 UI is Electron-only (`cora-plugin://` is an Electron protocol); a web/iOS client would later render `ui://` HTML via `srcdoc` in a sandboxed iframe, with the same bridge.

### 2.4 Sandbox

Spawn with `/usr/bin/sandbox-exec -f <generated.sb> <cmd>`. The profile is generated per plugin from its manifest:
- `(deny default)` and import only the system pieces the interpreter needs;
- read: the plugin dir, the Python/Node runtime, and `$CORA_PLUGIN_SCRATCH`;
- write: `$CORA_PLUGIN_SCRATCH` only (`DATA_DIR/plugin-scratch/<id>/`, 0700, purged on uninstall);
- `(deny network*)`, with a single `(allow network-outbound (remote unix-socket (path-literal "<run>/<nonce>.sock")))` for `cora-host`;
- no `DATA_DIR`, no `API_TOKEN_FILE`, no `~/Library/Keychains`, no `mach-lookup` to securityd/keychain agents;
- env is rebuilt from scratch (`PATH` minimal, `CORA_*` only); no API keys, no `VOICECOACH_API_TOKEN`, no cloud-credential variables.
- The `cora-host` identity is the socket (random 128-bit nonce per spawn, 0700 run dir) **plus** `LOCAL_PEERPID` checked against the child pid. It does not use the loopback token at all.

Honest caveats: `sandbox-exec` is deprecated by Apple (still functional; Chromium and Bazel-class tools rely on the same underlying Seatbelt). Writing a tight `deny default` profile for Python is a 1-2 day spike (WP2); fail-closed means we iterate until it passes. **Startup canary**: at first spawn per app launch, Cora runs a tiny probe under the same profile that tries `connect(127.0.0.1:8765)`, `connect(1.1.1.1:443)`, `open(DATA_DIR/voicecoach.db)` and `open(API_TOKEN_FILE)`. If any succeeds, Cora refuses to enable any Tier 1 plugin (fail closed) and shows why. The canary's result is written to `plugin_audit`, which is cheap, strong SOC 2 evidence.

---

## 3. Plugin types and tiers

| Tier | Name | Code that runs | Who | Where it can run | Lockdown behavior |
|---|---|---|---|---|---|
| **0** | Declarative | none (host interprets) | anyone | all installs, no Developer Mode | works if every LLM use resolves to a local provider; otherwise "disabled by policy" |
| **1** | Local MCP server | third-party/first-party process in sandbox, no network | first-party signed; third-party via signed registry (post-launch) or Developer Mode (launch) | signed or Developer Mode | works, since it has no egress; its LLM calls go through the broker |
| **1+** | Local server + `ui://` views | as Tier 1, plus HTML in sandboxed no-network frame | same | same | same |
| **2** | Connector spec | none; declarative HTTP described in JSON, **executed by host** | anyone can contribute; user grants hosts | not in lockdown | **blocked** (needs `require_outbound_allowed`) |
| **3** | Remote MCP server (designed, not built) | none locally; HTTPS to team-run MCP server | team admins | not in lockdown (loopback-only exception possible) | **blocked** |

Tier 0 contribution kinds (all declared under `contributes`, §4):
- `analyzers`: prompt, input selector, JSON output schema, markdown render template. Host executes the LLM call and stores a `plugin_outputs` row. Triggers: action button, event, or schedule.
- `personas`: system prompt and context binders for the chat slot (roleplay, coach).
- `templates`: note/summary formats (replaces the hard-coded `SUMMARY_FORMATS`, `pipeline/notes.py:14-33`).
- `rulesets`: todo-routing rules (§15) with local sinks.
- `connectors`: Tier 2 specs.

Every Tier 0 contribution is **automatically re-exported** as MCP surface: analyzers become tools (`analyze_<id>`), personas become prompts, templates become resources. A user who writes a persona in Markdown gets it in Cora's chat panel and in Claude Desktop's prompt picker.

Tier 0 is the Product Hunt story ("write a Markdown file, get a plugin") and the compliance story ("no third-party code ran").

---

## 4. Manifest schema (`cora-plugin.json`)

JSON (not YAML, which has parsing edge cases). It has a published JSON Schema at `https://…/cora-plugin.schema.json`, validated by `cora-plugin validate` and by the host at install. Unknown top-level keys are rejected; unknown `x-` keys are allowed.

| Field | Type | Req | Notes |
|---|---|---|---|
| `manifest_version` | int | y | `1` |
| `id` | string | y | reverse-DNS, `^[a-z0-9]+(\.[a-z0-9-]+)+$`. Immutable. Prefix `dev.cora.` reserved for first-party (checked against signature) |
| `slug` | string | y | `^[a-z][a-z0-9_]{1,23}$`, used as the MCP export namespace. Unique per installation |
| `name`, `description`, `version` (semver), `author` {name,url}, `license` (SPDX), `repository`, `icon` | | y/o | icon must be a Cora fixed-set glyph id or a bundled 64x64 PNG/SVG (sanitised) |
| `engines` | {cora: semver-range, mcp: spec-revision} | y | e.g. `{"cora": ">=1.1 <2", "mcp": "2025-06-18"}`. Host refuses mismatched `mcp` majors |
| `tier` | `0 \| 1 \| 2` | y | derived and cross-checked by the validator |
| `runtime` | {kind, entry, args[], deps_vendored:true, platforms[], inherit_site_packages?} | Tier 1 | `inherit_site_packages` honored for first-party signed only |
| `permissions` | {scopes: [{scope, reason, optional?, constraint?}], llm: {...}, audio?: {...}} | y | each scope needs a human-readable `reason` (shown in the consent sheet). See §5 |
| `llm` | {min: `"local"\|"any"`, cloud: `"never"\|"allowed"\|"required"`, audio: bool, multi_turn: bool, stream: bool} | if any `llm:*` | `cloud:"never"` pins the plugin to local models even if the user's global provider is cloud |
| `egress` | `"none"` (only valid value for Tier 0/1) | y | Tier 2 connectors declare hosts under `connectors[]` instead |
| `events` | [{on, tool, mode: `"async"\|"sync-ui"`, timeout_s, requires_audio?: bool, debounce_s?}] | o | host calls `tool` via `tools/call` with `{event_id, event, recording_id, ...}` |
| `contributes.tabs` | [{id, title, icon, when, view: {kind: `"markdown"\|"records"\|"ui"`, tool?, resource?}}] | o | detail-page tabs. `when` is a restricted predicate DSL: `has_transcript`, `meeting_type in [...]`, `participants>=2` |
| `contributes.actions` | [{id, label, icon, when, tool\|analyzer, confirm?, result: `"tab"\|"toast"\|"artifact"\|"chat"`}] | o | chip row at `index.html:259-267` |
| `contributes.views` | [{id, title, icon, resource}] | o | full-page sidebar views (knowledge base, team todos, roadmap) |
| `contributes.personas` | [{id, title, prompt_file, context: [...], tools: [...], opening, end_event}] | o | chat slot |
| `contributes.analyzers` | [{id, title, trigger: `"manual"\|"event:..."\|"cron:..."`, prompt_file, input: [...], output_schema_file, render_file}] | o | Tier 0 |
| `contributes.templates` | [{id, label, file, meeting_types?: [...]}] | o | notes formats |
| `contributes.rulesets` | [{id, file, sinks: [...]}] | o | §15 |
| `contributes.settings` | {schema_file} | o | JSON-Schema subset (string/number/bool/enum/array of those, `format: "folder"` picked via host dialog); host renders the form |
| `contributes.badges` | [{id, label_tool, when}] | o | per-meeting status chips (replaces the hard-coded `ready_for_coaching`/`coached` stage names) |
| `connectors` | [{id, base_url_hosts[], auth: {kind: `"bearer\|header\|none"`, keychain_name}, operations: [...], confirm: `"always\|first\|never"`}] | Tier 2 | host-executed; see §9.5 |
| `export` | {mcp: bool, tools: [names], prompts: [...], resources: [...]} | o | opt-in to re-export (§11); default `false` for write tools |
| `portable` | {standalone: bool, needs: [scopes]} | o | whether the server runs unmodified in Claude Desktop/Cursor |
| `integrity` | {files: {path: sha256}, bundle_sha256} | y at pack | generated by `cora-plugin pack` |
| `signature` | external file `SIGNATURE` (Ed25519, minisign format) | y except sideload | covers `cora-plugin.json` + integrity map |

### 4.1 Example: roleplay (Tier 0, no code)

```json
{
  "manifest_version": 1,
  "id": "dev.cora.roleplay",
  "slug": "roleplay",
  "name": "1:1 Roleplay",
  "version": "0.1.0",
  "license": "MIT",
  "engines": { "cora": ">=1.1 <2", "mcp": "2025-06-18" },
  "tier": 0,
  "egress": "none",
  "permissions": {
    "scopes": [
      { "scope": "meeting:current:summary", "reason": "Ground the practice conversation in the meeting you have open." },
      { "scope": "people:read:profile",      "reason": "Use the other person's role and communication notes." },
      { "scope": "llm:text",                 "reason": "Generate the other person's replies." },
      { "scope": "plugin:storage",           "reason": "Save your practice sessions." }
    ],
    "llm": { "min": "local", "cloud": "allowed", "multi_turn": true, "stream": true }
  },
  "contributes": {
    "personas": [{
      "id": "other-person",
      "title": "Practice with {{person.name}}",
      "prompt_file": "prompts/other-person.md",
      "context": ["meeting.summary", "person.profile", "person.recent_quotes(5)"],
      "opening": "ask_scenario",
      "end_event": "chat.session_ended"
    }],
    "analyzers": [{
      "id": "debrief", "title": "Practice debrief", "trigger": "event:chat.session_ended",
      "prompt_file": "prompts/debrief.md", "input": ["chat.transcript"],
      "output_schema_file": "schemas/debrief.json", "render_file": "render/debrief.md"
    }],
    "actions": [{
      "id": "practice", "label": "Practice this conversation", "icon": "message",
      "when": "has_transcript && participants>=2", "result": "chat"
    }]
  },
  "export": { "mcp": true }
}
```

### 4.2 Example: todo exporter (Tier 0 + user rule set)

```json
{
  "manifest_version": 1, "id": "dev.cora.todo-export", "slug": "todo_export",
  "name": "Send todos to my app", "version": "0.1.0", "tier": 0, "egress": "none",
  "engines": { "cora": ">=1.1 <2", "mcp": "2025-06-18" },
  "permissions": { "scopes": [
    { "scope": "todos:read",  "reason": "Read action items to route them." },
    { "scope": "todos:write", "reason": "Record where each item was sent." },
    { "scope": "llm:text",    "reason": "Classify items into your projects when rules say so.", "optional": true },
    { "scope": "sink:local:markdown-folder", "reason": "Write a checklist file into a folder you pick.", "constraint": {"folder": "user-picked"} },
    { "scope": "sink:local:apple-reminders", "reason": "Create Reminders on this Mac.", "optional": true },
    { "scope": "sink:connector:todoist",     "reason": "Create tasks in Todoist.", "optional": true }
  ]},
  "contributes": {
    "rulesets": [{ "id": "default", "file": "rules/default.rules.yml", "sinks": ["markdown-folder", "apple-reminders", "todoist"] }],
    "settings": { "schema_file": "settings.schema.json" },
    "actions": [{ "id": "send", "label": "Send todos", "icon": "check", "when": "todos.open>0", "confirm": true, "result": "toast" }],
    "views": [{ "id": "log", "title": "Todo export log", "icon": "list", "resource": "builtin:records?collection=sync_log" }]
  },
  "connectors": [{ "id": "todoist", "base_url_hosts": ["api.todoist.com"], "auth": {"kind": "bearer", "keychain_name": "token"}, "confirm": "first", "operations": ["connectors/todoist.create_task.json"] }]
}
```

### 4.3 Example: Tier 1 hello (what a third party writes)

```json
{ "manifest_version": 1, "id": "com.example.wordcount", "slug": "wordcount", "name": "Word Count",
  "version": "0.1.0", "tier": 1, "egress": "none",
  "engines": { "cora": ">=1.1 <2", "mcp": "2025-06-18" },
  "runtime": { "kind": "python", "entry": "server.py", "deps_vendored": true },
  "permissions": { "scopes": [ { "scope": "meeting:current:transcript", "reason": "Count words in the open meeting." } ] },
  "contributes": { "tabs": [ { "id": "wc", "title": "Word count", "icon": "chart",
                               "view": { "kind": "markdown", "tool": "wordcount_report" } } ] },
  "portable": { "standalone": true, "needs": ["meeting:read:transcript"] } }
```

---

## 5. Permission scopes and consent UX

### 5.1 Scope grammar

`<domain>:<qualifier>:<resource>`. Scopes are **additive, default-deny, stored in DB** (`plugin_grants`, not `config.json`). Each scope carries a fixed `risk` and an `egress` class used by the UI.

| Scope | What it allows | Risk | Egress class |
|---|---|---|---|
| `meeting:current:{metadata,summary,notes,transcript}` | Only the meeting open in the UI, and only while the user has the plugin surface open or has just invoked an action on it. Server-enforced: tool calls carry a `ctx_token` bound to a recording id | low | none |
| `meeting:read:{metadata,summary,notes,transcript}` | Read any meeting, filtered by constraint (folder, meeting type, date window) | high | none (but see `llm:*`) |
| `meeting:read:audio` | `cora.audio.stage(id)` clones audio into the plugin scratch dir for one job; auto-deleted | high | none |
| `meetings:search` | Cross-meeting FTS (`cora.meetings.search`) returning snippets, not full transcripts | medium | none |
| `people:read:{profile,quotes}` / `people:write:notes` | Read people; add plugin-attributed notes to a person | medium | none |
| `notes:append` | Add a versioned, attributed section to the meeting notes (never overwrites user text) | medium | none |
| `todos:read` / `todos:write` | Read/write `action_items` with stable ids | medium | none |
| `decisions:read` / `decisions:write` | Same for `decisions` | medium | none |
| `plugin:storage` | Own namespace in `plugin_kv` / `plugin_records` / `plugin_outputs` (implicitly granted to every installed plugin) | low | none |
| `llm:text` | Call the user's configured LLM through the broker | **depends on provider** | none if local; **cloud-llm** if the active provider is cloud |
| `llm:audio` | Send an audio ref to an audio-capable provider (currently Gemini) | high | **cloud-llm** only |
| `ui:notify` / `ui:view` | Toasts / contribute views | low | none |
| `jobs:background` | Run event/cron jobs when no UI is open | medium | none |
| `sink:local:markdown-folder` | Host writes files into a folder the user picked; the plugin never sees the path | medium | none |
| `sink:local:apple-reminders` | Host creates Reminders via an EventKit helper | medium | none |
| `sink:connector:<id>` | Execute operations of a declared connector (Tier 2). Needs the connector's per-host grant | high | **connector** |
| `mcp:export` | Allow plugin tools/prompts to be exposed to external MCP clients | high | external-agent |

No scope exists for: network, filesystem paths, Keychain, settings, credentials, other plugins' data, or the raw DB. A plugin that needs those cannot be expressed. That is deliberate.

### 5.2 Consent UX (all host-rendered, never plugin-drawn)

**Install sheet** (one screen, plain English, grouped):
```
 Roleplay  v0.1.0  · Cora (first-party, signed)          [Tier 0: no code runs]
 ────────────────────────────────────────────────────────────────────────────
 Reads        the meeting you have open (summary) · people profiles
 Writes       your practice sessions (inside this plugin only)
 Uses AI      Your notes model: Local (MLX). Nothing leaves this Mac.   [live-computed]
 Never        has no network access · cannot read other meetings · cannot change settings
 Optional     [ ] Allow Todo… (toggle each optional scope)
 Fingerprint  sha256 3fa9…  signed by key cora-2026a
                                              [Cancel]   [Install & enable]
```
- The "Uses AI" row is **computed from the live provider config and `policy.provider_allowed`**. If the user's provider is Gemini: "Transcript text will be sent to Google Gemini (your configured provider)". Under lockdown with a cloud provider, the row reads "Blocked by your organisation's policy" and Install-and-enable is replaced by "Install (disabled)".
- A **Tier 1** badge says "Runs a local program in a sandbox with no network access". Sideload/Developer Mode shows a red "Unsigned, developer mode" banner and cannot be installed without the toggle in Settings → Developer.

**Runtime confirmations** (cannot be pre-approved by a plugin):
- First `meeting:read:*` cross-meeting read per app session: "Knowledge Base wants to read 214 meetings to build its index. Allow once / for this session / always."
- Every `sink:connector:*` write: a diff card ("Create 3 tasks in Todoist: …"). Modes `always | first | never` are bounded by the user's choice; `never` is disabled under policy when `require_confirm_outbound` is set.
- Every tool call annotated `destructiveHint:true` through the chat loop.
- `elicitation` requests are displayed as host dialogs with the plugin name and are rate-limited (3 per minute per plugin).

**Re-consent triggers:** manifest hash change that adds any scope or changes a constraint; publisher key change; tier change. Patch updates with no scope change can auto-apply only if the user ticked "auto-update safe patches" and policy allows.

**Plugins pane (Settings → Plugins):** per plugin: state, version, trust badge, scopes with revoke toggles, "Activity" (reads `plugin_audit` filtered to that plugin: "Read transcript of *Weekly sync* 14:02 — 12 KB"), "Data" (size of collections, Export, Delete data), `stderr` tail for Tier 1, and "Pin to local models". There is also a global "Plugin activity" log with Export CSV for auditors.

**Admin policy** (MDM): read from env `VOICECOACH_PLUGIN_POLICY=/path/to/policy.json` **or** `/Library/Application Support/Cora/policy.json`. The file is honored only if owned by root and not group/world-writable; otherwise ignored with an audit row. `config.json` can add stricter user settings but can never relax an admin setting.
```json
{ "plugins": { "allow": ["dev.cora.*"], "block": [], "max_tier": 1, "require_signed": true,
               "deny_scopes": ["sink:connector:*", "mcp:export", "llm:audio"],
               "developer_mode": false, "registry": "disabled" } }
```

---

## 6. Enforcing `enterprise_lockdown` and the LLM provider policy

### 6.1 Principle
Plugins cannot egress by construction (sandbox + no scope for it). Therefore lockdown is enforced **at every host broker function**, re-evaluated per call (`policy.lockdown_enabled()` already reads env/config each time; no caching), and again at the process-spawn and UI boundaries. Defence in depth, five layers:

| # | Layer | Mechanism | Fails closed? |
|---|---|---|---|
| 1 | **Enable-time gate** | `manager.enable(id)` computes `needs_egress = scopes ∩ {llm:* if provider is cloud, sink:connector:*, mcp:export, audio→cloud}` or `tier in (2,3)`. If lockdown or admin policy forbids, state becomes `blocked_policy` with the reason shown. Not an error, a clean UI state | yes |
| 2 | **Process sandbox** | `(deny network*)`; startup canary (§2.4). Spawn itself calls `policy.lockdown_enabled()`; if lockdown flips on at runtime a listener kills Tier 1 processes with in-flight cloud jobs | yes |
| 3 | **Broker chokepoints** | `broker.llm_complete/chat` → `credentials._call_configured_llm` (**already** enforces `policy.provider_allowed`). `broker.connector_invoke` and `broker.registry_fetch` begin with `policy.require_outbound_allowed(...)`. `gateway` (MCP export) begins with a lockdown check. Audio-to-cloud is a distinct `llm:audio` path that checks both | yes |
| 4 | **UI frame** | `cora-plugin://` responses carry `connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'`. Main process adds `will-frame-navigate` deny for non-trusted frames and a `session.webRequest.onBeforeRequest` filter that cancels any non-loopback http(s) request from any frame. `setWindowOpenHandler` becomes deny-all; external links go through a new `handleTrusted('open-external')` that checks lockdown. Main reads `VOICECOACH_ENTERPRISE_LOCKDOWN`/`config.json` itself | yes |
| 5 | **Evidence** | Every denied/allowed outbound-capable broker call writes `plugin_audit` (hash-chained). A conformance test enumerates broker functions (§6.3) | n/a |

### 6.2 LLM provider policy for plugins
- Plugins never name a provider. They call `cora.llm.complete/chat` or MCP `sampling`; the broker uses the user's `notes_llm_provider` (or the per-plugin override in `plugin_kv('_host','llm_override')`).
- Manifest `llm.cloud: "never"` pins a plugin to local models. If the active provider is cloud, the broker substitutes the local model, or fails with a *clean, typed* `policy_local_only` error. The UI shows "Needs a local model". Under HIPAA workflows the user can also set the per-plugin pin in the Plugins pane.
- `llm.cloud: "required"` (e.g., Gemini-audio coaching) is `blocked_policy` under lockdown and visibly labelled "sends audio to Google" in the consent sheet.
- The consent sheet and the audit rows both carry `provider`, `model`, `bytes_out` (counts only). Prompt/response bodies stay in the existing local `ai_trace` under `trace_name = "plugin:<id>:<call>"`. Open item: trace retention for HIPAA users (owner decision #8).
- The single-turn `call_configured_llm` gains a sibling `call_configured_chat(messages, system, stream, ...)` (WP5). It must reuse the same `_call_configured_llm` provider gate. The new function must **not** duplicate the policy check; extract a shared `_gate(provider)`.

### 6.3 Conformance tests (SOC 2 evidence)
- `tests/test_plugin_lockdown.py`: with `VOICECOACH_ENTERPRISE_LOCKDOWN=1`, iterate a registry of broker functions (decorated `@outbound_capable`) and assert each raises `LockdownError` or returns `blocked_policy`. A decorator-registry test also fails the build if a new broker function lacks the decorator or a lockdown test.
- Static lint: `python/plugins/**` may not import `requests`, `urllib.request`, `http.client`, `socket` or `httpx` outside `broker.py`/`registry_fetch.py`.
- Sandbox canary test (macOS CI only) and a "cloud provider configured + lockdown" matrix test for LLM brokering.
- `tests/test_plugin_policy_file.py`: ignores user-writable policy files; env var wins; config can only tighten.

### 6.4 Pre-existing gaps this design depends on (fix first, WP0)
- `mcp_server.py` has no lockdown check, so it serves everything to whatever client, typically a cloud LLM. Add the check now, independent of plugins.
- `POST /api/settings` writes arbitrary keys (`settings.py:243-251`). A key allowlist is required before any plugin UI (or even the new bridge) exists.
- Subframe navigation and `window.open` guards (`security.js:30-43`); `isTrustedUrl` made exact-match for the dashboard page.

---

## 7. Lifecycle and events

### 7.1 Plugin state machine
`discovered → installed(verified) → [blocked_policy | needs_consent] → enabled → (running ⇄ idle) → failed(backoff) → disabled → uninstalled(keep|purge data)`

- Discovery sources: `APP_ROOT/plugins/` (first-party, in signed bundle), `DATA_DIR/plugins/<id>/<version>/` (installed), `DATA_DIR/plugins-dev/<id>` (symlinks from `cora-plugin dev`, only when Developer Mode is on).
- Load errors are **recorded, not swallowed** (fixes `plugin_registry.py:54-57`): `plugins.state_reason` plus stderr tail are visible in the UI.
- Enable/disable is live (no server restart). Nothing is cached at import time; routes are fixed (`/api/plugins/...`) and contributions are data, so no restart is needed to toggle.

### 7.2 Events (host → plugin)
Events are delivered as ordinary `tools/call`s to the tool named in the manifest's `events[]` binding. Payload: `{event_id, event, recording_id?, person_id?, ts, ctx_token}`. Return value is the job result (optional `structuredContent`). Progress arrives as MCP `notifications/progress` and lands in `plugin_jobs.progress_json`; the UI shows it like the existing `.pipeline_progress.json`.

| Event | Fired from | Notes |
|---|---|---|
| `meeting.started` / `meeting.ended` | capture routes / `main.js` | Live-meeting hooks: v1 has no per-utterance streaming |
| `meeting.processed` | **new hook in `pipeline/runner.py` after the DB writes at ~:339-343** | Audio and transcript and notes and call_summary all exist. Replaces the cloud-only auto-pilot (`diarization.py:663-688`) |
| `meeting.updated` | re-summarize (`recordings.py:324-396`), transcript edit | Marks dependent `plugin_outputs` stale via `inputs_hash` |
| `meeting.identity_changed` | `diarization.confirm_speaker/reset_speaker` | Replaces the hard-coded `clear_coaching_artifacts` |
| `meeting.merged` | continuation merge (`runner.py:~383-428`) | Fixes the stale-coaching bug |
| `person.updated` | `people` routes | |
| `chat.session_started/ended` | host chat panel | Debrief analyzers hang here |
| `schedule.cron` | host scheduler (in the API process, minute tick) | Weekly digests; never fires under `jobs:background` revoked |
| `plugin.enabled/disabled/upgraded` | manager | Lets plugins run migrations of their own data |

**Delivery semantics:** at-least-once, idempotent by `(plugin_id, event_id)` UNIQUE; per-plugin ordered queue, concurrency 1; 3 retries with backoff; timeout; dead-letter visible in the Plugins pane. **Never blocking** for the pipeline: no pre-notes hooks in v1 (a blocking hook would let a plugin stall recording processing).

**Audio lease** (fixes `runner.py:376-378`): the `meeting.processed` dispatcher takes an audio lease for each enabled plugin whose binding has `requires_audio:true` and whose grant includes `meeting:read:audio` (and `llm:audio` if it needs a cloud call). The `retain_audio=false` deletion becomes `retention.delete_audio_when_unleased(folder)`, which runs when the last lease releases (job done/failed/timeout 30 min). No plugin → no change in behavior. Audio-needing plugins degrade to transcript-only if the lease is absent.

---

## 8. Data model

New tables (all in `db.init_db()` with a migration version). Everything is namespaced by `plugin_id` and cascades on purge. Plugins never see these tables; they use `cora.*` tools.

```sql
CREATE TABLE plugins (
  id TEXT PRIMARY KEY, slug TEXT UNIQUE NOT NULL, version TEXT NOT NULL, tier INTEGER NOT NULL,
  trust TEXT NOT NULL,                  -- first_party | verified | community | sideload
  manifest_json TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, bundle_sha256 TEXT,
  publisher_key_id TEXT, install_path TEXT NOT NULL,
  state TEXT NOT NULL,                  -- installed|enabled|disabled|blocked_policy|failed|needs_consent
  state_reason TEXT, installed_at TEXT, updated_at TEXT, installed_by TEXT);

CREATE TABLE plugin_grants (
  plugin_id TEXT, scope TEXT, constraint_json TEXT, granted INTEGER NOT NULL,
  granted_by TEXT NOT NULL,             -- user | admin | default
  granted_at TEXT, manifest_sha256_at_grant TEXT, PRIMARY KEY (plugin_id, scope));

CREATE TABLE plugin_kv (                -- settings + small state; also host-private rows under plugin_id='_host'
  plugin_id TEXT, namespace TEXT, key TEXT, value_json TEXT, updated_at TEXT,
  PRIMARY KEY (plugin_id, namespace, key));

CREATE TABLE plugin_records (           -- document store for plugin-owned collections
  plugin_id TEXT, collection TEXT, id TEXT, recording_id TEXT, person_id TEXT,
  data_json TEXT NOT NULL, created_at TEXT, updated_at TEXT, deleted_at TEXT,
  PRIMARY KEY (plugin_id, collection, id));
CREATE INDEX plugin_records_rec ON plugin_records(plugin_id, collection, recording_id);

CREATE TABLE plugin_outputs (           -- versioned artifacts: tab content, notes sections, reports
  id TEXT PRIMARY KEY, plugin_id TEXT NOT NULL, recording_id TEXT, key TEXT NOT NULL,
  version INTEGER NOT NULL, kind TEXT NOT NULL, content TEXT, content_type TEXT,
  inputs_hash TEXT,                     -- hash(transcript, identity, template); staleness detection
  produced_by_job TEXT, created_at TEXT, UNIQUE(plugin_id, recording_id, key, version));

CREATE TABLE plugin_jobs (
  id TEXT PRIMARY KEY, plugin_id TEXT NOT NULL, event TEXT NOT NULL, event_id TEXT NOT NULL,
  recording_id TEXT, payload_json TEXT, status TEXT NOT NULL,   -- queued|running|done|failed|dead
  attempts INTEGER DEFAULT 0, run_after TEXT, started_at TEXT, finished_at TEXT,
  error TEXT, progress_json TEXT, audio_lease INTEGER DEFAULT 0, UNIQUE(plugin_id, event_id));

CREATE TABLE plugin_audit (             -- append-only, hash-chained for tamper evidence
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, plugin_id TEXT, actor TEXT NOT NULL,
  action TEXT NOT NULL, scope TEXT, recording_id TEXT, bytes_out INTEGER, provider TEXT,
  outcome TEXT NOT NULL,                -- ok|denied|error|blocked_policy
  detail_json TEXT, prev_hash TEXT, hash TEXT NOT NULL);

-- Core-owned, because multiple plugins, the UI and the MCP export all need them:
CREATE TABLE action_items (
  id TEXT PRIMARY KEY,                  -- uuid, stable across re-summarize
  recording_id TEXT NOT NULL, text TEXT NOT NULL, norm_hash TEXT NOT NULL,
  owner_person_id TEXT, owner_name TEXT, due TEXT,
  status TEXT NOT NULL DEFAULT 'open',  -- open|done|dropped
  status_at TEXT, source TEXT NOT NULL, -- 'notes' | 'plugin:<id>'
  span_json TEXT, confidence REAL, superseded_by TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE decisions (
  id TEXT PRIMARY KEY, recording_id TEXT NOT NULL, text TEXT NOT NULL, rationale TEXT,
  decided_by TEXT, span_json TEXT, status TEXT DEFAULT 'active', supersedes_id TEXT,
  source TEXT NOT NULL, created_at TEXT);
CREATE TABLE chat_sessions (
  id TEXT PRIMARY KEY, plugin_id TEXT NOT NULL, persona_id TEXT, recording_id TEXT, person_id TEXT,
  scenario_json TEXT, created_at TEXT, ended_at TEXT);
CREATE TABLE chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL,
  content TEXT NOT NULL, created_at TEXT);
```

Design points:
- **`action_items`** replaces `todo_state` (index-keyed, writer-less). Migration: map each existing `call_summary` action-item list into rows, then carry any `todo_state` done flags by index. A `reconcile_action_items(recording_id)` runs after every re-summarize: match by `norm_hash` first, then fuzzy text, keeping ids and statuses (this unblocks todo-app export, knowledge base and, later, team todos).
- **`chat_*` are host-owned** so retention, export and "delete my data" are uniform (HIPAA right-to-delete cascades). Plugins read them only through `chat.*` events and `cora.chat.*` tools if granted.
- **Recording columns `coaching`, `delivery_metrics`** are not dropped. A one-time migration copies them into `plugin_records('dev.cora.coaching','reports')`; the columns remain, read-only, for one release.
- `plugin_audit.hash = sha256(prev_hash || canonical_row)`; a startup self-check verifies the chain and shows "Audit log verified" in Settings. Rows never contain transcript text, only ids and byte counts.
- Plugin data purge on uninstall is `DELETE … WHERE plugin_id=?` across the plugin tables plus the scratch dir, offered as "Keep my data / Delete my data".
- Encryption at rest is out of scope here (FileVault is the assumed control; flagged as a SOC 2 note).

---

## 9. The `cora-host` tool surface (what plugins can call)

Exposed per plugin on the Unix socket as standard MCP tools; `tools/list` returns only granted tools. Every call: (1) authenticate connection (nonce+PID), (2) resolve scope+constraint, (3) check `ctx_token` binding for `:current` scopes, (4) execute with a **redacting serializer**, (5) write `plugin_audit`. Redaction removes `folder_path`, `folder_uri`, `audio_url` and any absolute path (`views.py:365-373` currently exposes them) and maps speaker ids to `speaker_N` plus display names only when `people:read:profile` is also granted.

| Tool | Scope | Notes |
|---|---|---|
| `cora.meeting.get` `{id?}` | `meeting:*:metadata` | `id` omitted = current meeting |
| `cora.meeting.transcript` `{id?, range?}` | `meeting:*:transcript` | paged, with `{start_s,end_s,speaker,text}` |
| `cora.meeting.notes` / `.summary` | `meeting:*:notes/summary` | |
| `cora.meetings.list` / `.search` | `meeting:read:*` / `meetings:search` | cursor-paged; filter by constraint |
| `cora.people.list/get` | `people:read:*` | |
| `cora.todos.list/upsert/set_status` | `todos:*` | upserts attach `source='plugin:<id>'`, provenance span |
| `cora.decisions.list/upsert` | `decisions:*` | |
| `cora.notes.append_section` `{recording_id,key,markdown}` | `notes:append` | versioned; user text never overwritten; sanitized by `renderMarkdownSubset` on display |
| `cora.store.get/put/query/delete` | `plugin:storage` | → `plugin_records`; quotas (100 MB/plugin, 10k docs/collection) |
| `cora.outputs.put` `{recording_id,key,content}` | `plugin:storage` | → `plugin_outputs` with `inputs_hash` |
| `cora.audio.stage` `{id}` | `meeting:read:audio` | APFS `clonefile` into scratch; returns `{path}`; deleted at job end |
| `cora.llm.complete/chat` | `llm:text` | also reachable via MCP `sampling/createMessage`; see §9.2 |
| `cora.llm.audio` `{audio_path,prompt,schema}` | `llm:audio` | only if provider supports audio; typed `provider_unsupported` otherwise |
| `cora.connector.invoke` `{connector,op,args}` | `sink:connector:<id>` | §9.5 |
| `cora.sink.local` `{sink,items}` | `sink:local:*` | host writes the file/Reminder; plugin never learns the path |
| `cora.ui.notify`, `cora.job.progress` | `ui:notify` / `jobs:background` | |

Also exposed as MCP **resources**: `cora://meeting/{id}/{transcript|notes|summary}` (scope-filtered), enabling portable servers that use `resources/read` semantics.

### 9.2 LLM brokering
Two entry points, one implementation (`broker.llm_*`): MCP `sampling/createMessage` (stock-SDK path, works for any MCP server library) and `cora.llm.*` (richer: structured output schema, streaming into a chat session). The broker enforces `llm:*` grant, `llm.cloud` pin, `policy.provider_allowed`, per-plugin token budget per day (default 200k tokens; visible), max prompt size, and writes `ai_trace` + `plugin_audit`. Multi-turn and streaming require `credentials.call_configured_chat` (WP5); local MLX streaming follows `pipeline/llm.py` conventions.

### 9.3 Audio
Audio never crosses a pipe; it is a cloned file in the scratch dir that the sandbox can read. Cloud audio goes only through `cora.llm.audio`, never by plugin code. The coaching plugin's current inline-bytes upload (`diarization.py:428-429`) becomes this path, and its privacy note is regenerated from the broker's real behavior (fixing the incorrect "Files API copy was deleted" claim at `engine.py:642` / `plugins/coaching/README.md:17-19`).

### 9.4 Rate limits and quotas
Per plugin: 20 tool calls/s, 50 MB/min read volume from meeting content, 1 concurrent LLM call per job. Exceeding returns a typed `rate_limited` error and an audit row.

### 9.5 Connectors (Tier 2, host-executed)
A connector is JSON, not code: allowed hosts, auth kind (token read by the host from Keychain under `plugin.<id>.<name>`; the plugin never sees it), and operation templates with parameter schema and response mapping. The host: https-only; host pinned; redirects only within pinned hosts; 1 MB body, 10 s timeout; per-op rate limit; user confirm per §5.2; `require_outbound_allowed` first. A connector is reviewable by reading a JSON file, which makes it a better third-party contribution than "network permission".

---

## 10. UI contribution points

All contributions are declared in the manifest and returned to the renderer inside `dashboard_payload().plugins` (`views.py:522-524`, generalised). Labels pass through `esc()` or `textContent`. Icons come from the fixed `data-icon` set (or a sanitized bundled SVG rendered as `<img>`, never inline).

| Point | Where in the renderer | Rendering | Notes |
|---|---|---|---|
| **Detail tab** | tabs `index.html:305-310`, panels `:311-336` | `view.kind=markdown` → host-rendered via `renderMarkdownSubset` (`detail.js:316-339`, escape-first); `records` → host table/list; `ui` → sandboxed frame | Needs delegated listeners (`notepad.js:21-24`, `search.js:153`) and `search.js:17-27` to skip plugin panels |
| **Action chips** | `.notepad-chip-row` `index.html:259-267`, visibility computed in `detail.js loadNotepad():139-273` | Host-rendered button; click calls the bound tool/analyzer; `result` decides tab/toast/artifact/chat | `when` is a restricted DSL evaluated in the host |
| **Chat slot** | replace `notepad-ask-row` at `index.html:337-340` | **Host-rendered** chat panel: persona picker, scenario chips, streaming message list, "end & debrief". Built-in persona `ask` ("Ask anything about this meeting") ships first-party, so the slot works on day one | Transcripts never touch plugin JS. `POST /api/plugins/chat/send` returns chunked SSE (manual chunking on the stdlib server; one thread per live stream, fine for a single user) |
| **Settings** | nav `index.html:369-378`, panels `:379-557`; `settings.js:5-8` delegated | Host-rendered form from the JSON-Schema subset; saved to `plugin_kv` namespace `settings` | A plugin can never write core settings. It sees only its own keys |
| **Full-page view** | sidebar `index.html:196-200`; `core.js showView :9-21, :49-62` (dynamic titles; today a missing title shows `undefined`) | `ui://` frame or `records` | Knowledge Base, Roadmap, Team todos |
| **Badges** | recording list / detail header | host renders a label from `badge.label_tool` output (cached) | Replaces the coaching-specific stage names (`views.py:346-353`, `core.js:25`, `index.html:234`) with a core `ready` stage + per-plugin badges |
| **Templates** | notes format picker via `/api/recording/summary-formats` (`recordings.py:22-27`) | merged list: built-in + `DATA_DIR/templates/*.md` + plugin `templates` | |

### 10.1 `ui://` frames (post-launch for third parties; first-party can use at launch)
- The host calls `resources/read` on the plugin server for the `ui://` URI and **serves the bytes from memory** at `cora-plugin://<plugin-id>/<content-hash>` through `protocol.handle` in the Electron main process. The frame is cross-origin to the dashboard, and the bytes cannot be swapped on disk after consent.
- Response CSP forced by main: `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'`. (Inline script is acceptable *only* because the frame has no network and no access to the parent.) `<iframe sandbox="allow-scripts">` — **opaque origin, no `allow-same-origin`, no popups, no modals, no top-navigation.** Single-file bundle required (the SDK's build step inlines everything); no subresource loads.
- Main CSP gains `frame-src cora-plugin:`. `registerSchemesAsPrivileged` is called before `app.ready`. `isTrustedUrl` is changed to exact match so the privileged IPC (`preload.js` `electronAPI`, 18 calls) is unreachable from plugin frames; `nodeIntegrationInSubFrames:false` is set explicitly.
- **Bridge** (`plugin-host.js`, a first-party classic script added before `init.js`, `index.html:682-700`; `scripts/lint-ui.js` order list updated): one `MessageChannel` per frame; checks `event.source === iframe.contentWindow`; protocol is MCP-Apps-style JSON-RPC (`ui/initialize`, `tools/call`, `ui/message`, `ui/update-model-context`) restricted to: *tools of that plugin's own server* (proxied through `/api/plugins/rpc`), `storage.*`, `ui.toast`, `ui.confirm`, `ui.resize`, `theme`. It is **not** a generic API proxy; there is no `fetch` verb and no settings verb. Server re-checks scopes and audits. MCP Apps rendering requires the pinned spec revision (§19 decision #3).
- Plugin frames cannot use the mic (`main.js:1000-1003` denies all but clipboard). Voice roleplay is host-mediated capture and out of scope for v1.

---

## 11. Cora as MCP server (the export)

### 11.1 Shape
`cora mcp` stays what external clients launch (`/api/mcp/config` hands out the command), but it becomes a thin **stdio-to-HTTP proxy** to the running app:
- reads the token from `API_TOKEN_FILE` (0600, same-user: exactly how existing CLI tools authenticate); calls `POST /api/mcp/rpc` over loopback with `X-VC-Token` and the correct `Host`. **No change to the token/Host/Origin model.** The new route sits behind the same `authorize()`.
- if the app is not running: serve **only** the built-in read tools in the legacy read-only SQLite mode with the same grants and lockdown check; plugin tools are absent with a clear message.
- fixes the config generator to include `VOICECOACH_DATA_DIR`.

### 11.2 What is exported
- Built-in tool groups (`meetings.read`, `people.read`, `todos.read`, `todos.write`, `coaching.read`), each with a user toggle in Settings → Connect AI tools (all groups default **off** until the user enables the export once, with a consent sheet naming the client from `clientInfo`).
- Plugin tools only if the manifest sets `export.mcp:true` **and** the user granted `mcp:export`. Names are `<slug>_<tool>`. Tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`) are mandatory in manifests (validator-enforced) and mapped to confirmations: destructive tools exported require the client's own confirmation plus a host confirm card when the app is frontmost, otherwise they are not exported.
- Tier 0 contributions are auto-exported as described in §3 (analyzer→tool, persona→prompt, template→resource).
- A plugin's tool called by an external client still runs *inside Cora's sandbox* with the plugin's own grants. The external client gets no more than the plugin could do. `mcp:export` only exposes the plugin's tools, not the plugin's scopes.

### 11.3 Lockdown
Under lockdown `cora mcp` and `/api/mcp/rpc` **refuse by default**, because the client identity (`clientInfo`) is self-reported and the typical client is a cloud model. An admin can set `"mcp_export": "allow"` in the root-owned policy for local-only clients; that is a deliberate admin act, audited. This closes the gap in `mcp_server.py` and `policy.py:5-8` ("every outbound path refuses to run").

### 11.4 Prompt-injection and exfiltration notes
Transcripts are attacker-influenced text (a meeting participant can say anything). Exported write tools (`todos.write`, `notes.append`) could be driven by an injected instruction in a transcript the *client* LLM reads. Mitigations: write tools are off by default, annotated, and rate-limited; the host audit log records `clientInfo`; `notes:append` writes are attributed and versioned (visible, revertable); no tool deletes meetings or settings.

---

## 12. Packaging, install, update, signing

- **Format:** `*.cora-plugin` = deterministic zip: `cora-plugin.json`, assets, `integrity` map inside the manifest, `SIGNATURE`. Vendored dependencies for Tier 1 (wheels unpacked / bundled JS). Max 50 MB (first-party may exceed).
- **Install sources:** (1) in-app Plugins → Browse (registry index, post-launch); (2) drag a `.cora-plugin` file in (offline: the only path under lockdown/air-gap); (3) `cora-plugin install <dir|file>`; (4) Developer Mode symlink. All paths run the same `manager.install()`: unzip to a temp dir, verify the zip is traversal-safe (no absolute paths, no symlinks, no `..`), validate the manifest, verify signature and integrity, compute the scope diff, then show the consent sheet.
- **Signing:** Ed25519 (minisign format; verification via the `PyNaCl`/`cryptography` lib already in the runtime or a ~100-line verifier). The Cora first-party public key is embedded in the app. Third-party publishers register a public key in the registry. Trust levels: `first_party` (embedded key), `verified` (registry-attested key plus automated lint plus human review if scopes exceed the tier's norm), `community` (valid signature, unreviewed; red-ish warning and key fingerprint confirmation), `sideload` (unsigned; Developer Mode only; never under `require_signed`).
- **Registry (post-launch, week 6+):** a public git repo `cora-plugin-registry` with `index.json` (id, versions, sha256, signature URL, publisher key id, scope summary, review status). Hosted on GitHub Pages; the app fetches **only on user action**, and the fetch is `broker.registry_fetch` (lockdown-blocked). Publishing is a PR whose CI runs `cora-plugin validate --strict`. At launch a README-listed "awesome-cora-plugins" with GitHub release links is enough (1 hour).
- **Updates:** never silent by default. "Check for updates" compares index versions, downloads, shows the **scope diff**; any added scope/constraint or key change forces re-consent; the previous version stays on disk for one-click rollback. Opt-in "auto-update patch releases with no scope change". Enterprise: `registry: disabled` blocks all of it.
- **Integrity at runtime:** `manifest_sha256` and `bundle_sha256` are pinned at consent and re-verified at every spawn (cheap hash of the integrity map plus stat check); mismatch → `failed: integrity` and an audit row. This addresses the "code-plant in DATA_DIR/plugins" concern.
- **Uninstall:** stop process, remove version dirs, revoke grants, ask keep/delete data, purge scratch.
- **Electron bundle:** first-party plugins live in `plugins/` (already in `package.json build.files` and `asarUnpack`) and are covered by the app's code signature; the first-party key signature is still checked so the same code path is exercised.

---

## 13. Developer experience

### 13.1 Tools
- **Python SDK `cora-plugin-sdk`** (import name `cora_plugin`): a thin layer over the official `mcp` package (already `mcp>=2.2` in `pyproject.toml`). **Bundled inside the app** (no install needed for in-app scaffolding) and published on PyPI for outside use. TypeScript SDK `@cora/plugin-sdk` is post-launch (the sandbox supports Node via `ELECTRON_RUN_AS_NODE`).
- **CLI `cora-plugin`**: `new`, `dev`, `validate`, `test`, `pack`, `sign`, `install`, `mcp-config`, `publish` (opens a registry PR). Shipped as `bin/cora-plugin` inside the app using the bundled runtime, and `pipx install cora-plugin-sdk` outside it.
- **Fake host** (`cora_plugin.testing.FakeHost`): serves `cora.*` from fixture meetings (generated from `tools/seed_demo_data.py` fictional data, so no real meeting data in examples, docs or launch assets); pytest fixture; asserts scopes (a tool call outside the declared scopes fails the test).
- **MCP Inspector works unmodified** against any plugin server (the portability dividend), with `cora-plugin dev --inspector`.

### 13.2 Hot reload
`cora-plugin dev` (1) symlinks the dir into `DATA_DIR/plugins-dev/` and calls `POST /api/plugins/dev/attach` with the token from `API_TOKEN_FILE` (same-user, same mechanism as existing CLI tools); (2) host file-watches the dir: manifest change → re-validate and diff scopes (dev: prompt once, remembered by manifest hash); code change → restart that plugin process only (< 1 s); `ui://` change → push `plugin.reload` to the open frame; (3) stderr and `cora-host` call log stream into Plugins → Developer pane (and to the terminal). Developer Mode must be on (off by default; hidden and refused under admin `developer_mode:false`).

### 13.3 The 10-minute hello-world
```
0:00  Settings → Developer → "Create plugin"   (or: cora-plugin new wordcount)
0:30  Generated:  wordcount/ cora-plugin.json  server.py  README.md  tests/test_server.py
0:30  server.py (the entire plugin):
```
```python
from cora_plugin import Plugin
plugin = Plugin("wordcount")

@plugin.tool(scopes=["meeting:current:transcript"], read_only=True)
async def wordcount_report(ctx) -> str:
    segs = await ctx.meeting.transcript()          # = cora.meeting.transcript (scoped to the open meeting)
    n = sum(len(s["text"].split()) for s in segs)
    by = {}
    for s in segs: by[s["speaker"]] = by.get(s["speaker"], 0) + len(s["text"].split())
    return f"**{n} words**\n\n" + "\n".join(f"- {k}: {v}" for k, v in sorted(by.items(), key=lambda x: -x[1]))

if __name__ == "__main__": plugin.run()
```
```
3:00  cora-plugin dev   → Cora shows "wordcount (dev)"; consent sheet appears once; Enable.
4:00  Open any (demo) meeting → a "Word count" tab appears (manifest tab bound to wordcount_report).
5:00  Edit the function; save → tab refreshes in < 1 s.
6:00  cora-plugin test  → pytest with FakeHost passes; scope-violation test included.
7:00  cora-plugin mcp-config → prints a Claude Desktop/Cursor snippet; ask "word count of my last meeting" there.
9:00  cora-plugin pack && cora-plugin validate --strict  → wordcount-0.1.0.cora-plugin
10:00 Drag the file onto Plugins → install sheet. Done.
```
An even shorter Tier 0 path: `cora-plugin new --declarative persona` produces `prompts/*.md` and a manifest. No Python needed.

**Docs** shipped with launch: a 1-page quickstart, scope reference, manifest reference (generated from the JSON Schema), 4 worked examples (persona, analyzer, rule set, Tier 1 tracker), a "porting an existing MCP server" page, and a threat-model page for reviewers.

---

## 14. Migration

### 14.1 Coaching onto the platform (`dev.cora.coaching`, first-party Tier 1)
1. `plugins/coaching/` becomes `plugins/dev.cora.coaching/` with a manifest, `server.py` (stdio MCP server) and the engine code. It **stops importing `diarization.py` private helpers and `db`** (the nine imports at `engine.py:18-29`). It gets transcript, call_summary and identity from `cora.meeting.*`/`cora.people.*`, and audio from `cora.audio.stage`.
2. LLM: `classify_meeting` and the coaching pass go through `cora.llm.complete` / `cora.llm.audio`. The Gemini-only coupling disappears; under lockdown the plugin shows "disabled by policy" instead of a deep `LockdownError` 500. Local delivery metrics (numpy) stay local; `inherit_site_packages` is allowed for this first-party plugin to avoid vendoring numpy.
3. Events: `meeting.processed` (opt-in "auto-coach" setting, default off), `meeting.identity_changed` (invalidate output by `inputs_hash`), `meeting.merged`. The cloud-only auto-pilot block (`diarization.py:663-688`) is deleted; both pipelines emit the same event. Long work runs as a job with progress, not inside an HTTP request thread.
4. Routes: `api/routes/coaching.py` is deleted. `/api/confirm-and-coach` and `/api/gemini-coach` remain for one release as thin shims that enqueue the job and return `202 {job_id}`.
5. Core cleanup: remove the hard-coded coaching bits in `views.py:160-190, 336-412, 522-524`, `api/core.py` ARCHETYPE_OPTIONS, `diarization.clear_coaching_artifacts`, and the `ready_for_coaching`/`coached` stages (core `ready` + plugin badges). `meeting_types.py` becomes the single taxonomy source; `main.js MEETING_ARCHETYPES` (`:331-368`), the picker (`:370-425`), the "Processing coaching report..." notification (`:750-753`) and the tray submenu (`:819-875`) are driven by the plugins payload and appear only when a plugin that declares `meeting_types` is enabled.
6. Data: columns `coaching`, `delivery_metrics` → `plugin_records` one-time copy; legacy columns read-only for one release. Fix the privacy note to describe inline-bytes upload (`engine.py:642`, README `:17-19`), `ffmpeg` via `shutil.which` (`engine.py:265`).
7. Delete dead code: `python/gemini_coach.py`, `plugins/coaching/coach_engine.py` (or move to examples), the orphan delivery-dashboard handler (`navigation.js:7-14`) and CSS (`styles.css:872-924`), `MODE_LABELS`/`DEFAULT_DATA` in `api/core.py`. Fix `backfill_delivery_metrics.py` paths or delete.
8. `plugin_registry.py` becomes a ~20-line compat shim over `plugins.manager` (so `coaching_enabled()` callers keep working during the transition), then is removed.

### 14.2 Notes templates
`SUMMARY_FORMATS` (`notes.py:14-33`) and the frontier notes prompt become template files (`DATA_DIR/templates/*.md` with front-matter: label, sections, output schema, `meeting_types`, preferred provider). Plugins contribute templates through the manifest. The existing `/api/recording/summary-formats` route (`recordings.py:22-27`) lists the merged set. This is the lowest tier of the platform and is documented first.

### 14.3 `mcp_server.py`
Becomes the proxy plus the legacy fallback; its stale coaching reads (`:87-107, :307-320, :433-465`) are replaced by `plugin_records`-backed tools exported by the coaching plugin.

---

## 15. First-party plugins mapped to the owner's ideas

| Idea | Tier | How (MCP-native) | Scopes | Works under lockdown? |
|---|---|---|---|---|
| **1:1 roleplay** | 0 | Persona prompt + context binders; chat slot runs the loop; debrief analyzer on `chat.session_ended`; sessions in `chat_*` | `meeting:current:summary`, `people:read:profile`, `llm:text` | yes with a local model (quality caveat for small MLX models) |
| **Communication coaching** | 0 analyzer (+ existing delivery metrics from the coaching plugin) | Analyzer over transcript → scorecard markdown tab + records; trend view reads `plugin_records` | `meeting:current:transcript`, `llm:text` | yes (local) |
| **Storytelling coaching** | 0 | Analyzer "story structure/hook/arc" + a persona "story coach" for rewrites | same | yes (local) |
| **Todo / decision knowledge base** | 1 first-party | Event `meeting.processed` → extract decisions/todos (writes core `action_items`, `decisions` via `todos:write`/`decisions:write`) → dedupe and "open loops" across meetings; `kb_search` tool; full-page view; exported to MCP for Claude | `meeting:read:*` (constraint), `todos:*`, `decisions:*`, `meetings:search`, `llm:text`, `jobs:background` | yes (local) |
| **Roadmap tracker** | 1 (reference third-party example) | User points to a roadmap file via folder picker (host reads it; `files:read:user-file` constraint-scoped); each processed meeting → compare vs roadmap items → `plugin_records('signals')`; "drift" tab and weekly digest via `schedule.cron` | `meeting:read:transcript`, `llm:text`, `jobs:background` | yes (local) |
| **Todo-app export with a user rule set** | 0 + 2 | `rules/*.rules.yml` (YAML: `match`, `transform` incl. optional `llm: classify`, `sink`), local sinks (Markdown folder, Apple Reminders) work offline; Todoist/Linear/Notion via connector specs; idempotent via `sync_log` collection keyed by `action_items.id` | `todos:*`, `sink:*` | local sinks yes; connectors **no** |
| **Shared team todos (later)** | 1 + file-sync ledger or Tier 3 | Append-only JSONL ledger per device in a user-chosen synced folder (iCloud/Dropbox/Syncthing/git) merged by UUID, so Cora runs no server and stays local-first. Or Tier 3 remote MCP server run by the team (including on a tailnet). **Deferred**: needs `action_items` identity and ownership fields to prove out first | `todos:*`, folder picker | ledger yes (local folder); remote no |

Rule-set DSL sketch (user-editable file in `DATA_DIR/plugins-data/dev.cora.todo-export/rules/`):
```yaml
- name: eng-bugs
  match: { text_regex: "(?i)\\b(bug|fix|regress)", owner: me, confidence_gte: 0.6 }
  transform: { title: "{{text}}", priority: 2, project: "Engineering", due: "{{due or +3d}}" }
  sink: todoist
- name: everything-else
  match: { owner: me }
  sink: markdown-folder
```

---

## 16. Threat model and SOC 2 mapping

| Threat | Control |
|---|---|
| Malicious/buggy plugin exfiltrates data | No network in sandbox; no scope for network; brokers enforce lockdown; connector hosts pinned and confirmed; audit chain |
| Plugin reads other data / credentials / token | Sandbox denies `DATA_DIR`, token file, Keychain; scoped `cora-host`; redacting serializer |
| Plugin UI steals token or drives privileged IPC | Cross-origin opaque-origin frame; no cookie; `isTrustedUrl` exact; no `/api` access from frames; bridge has typed verbs only |
| Frame navigates away or `window.open` exfil | `will-frame-navigate` deny, deny-all window open, `webRequest` loopback-only filter |
| Supply chain (tampered update) | Ed25519 signature, integrity pins at consent and at each spawn, scope-diff re-consent, rollback |
| Prompt injection via transcript driving plugin/exported tools | Write tools off by default; destructive annotation confirms; versioned attributed writes; client name audited |
| User weakens lockdown | Env/root-owned policy wins; config.json can only tighten |
| Plugin DoS (CPU/memory/disk) | RSS watchdog, call timeouts, storage quotas, concurrency caps |
| Tamper with audit log | Hash chain + startup verification (note: a local admin can still rewrite the DB; ship periodic export) |

SOC 2 control artifacts this produces: change management (plugin install/enable are audited admin-or-user actions with approver and hash), access control (least-privilege scopes, revocation), logical access monitoring (`plugin_audit` export), vendor/third-party management (registry review status, signature), confidentiality (lockdown tests, sandbox canary evidence), availability (watchdogs). Gaps remaining (honest): no encryption at rest in the app, local DB is user-writable, `sandbox-exec` is deprecated API.

---

## 17. Honest trade-offs of the MCP-native angle

**What it costs**
- A process per Tier 1 plugin (30-80 MB for Python), 200-600 ms cold start, plus asyncio inside a threaded stdlib server. Mitigated by Tier 0 doing most plugin ideas with no process.
- MCP gaps filled with our own conventions: permission/consent model, server-to-host data calls (second channel), event subscriptions (bindings), long jobs (jobs table). We are using MCP as the *interface and portability layer*, not as a security model.
- `sampling` support in third-party MCP clients (Claude Desktop, Cursor) is not guaranteed. Standalone mode therefore uses the *prompt-return pattern*: a tool that would call the LLM returns its instructions/structured context to the invoking model instead. SDK helper `ctx.llm.complete()` auto-selects (host broker → sampling → prompt-return) so the same server works in all three.
- **MCP Apps / `ui://` spec churn.** The convention (resource URI scheme, MIME profile, `postMessage` JSON-RPC) is young. Pin a spec revision in `engines.mcp`, keep the bridge in one file, and keep third-party frames post-launch.
- `sandbox-exec` deprecation risk; a tight profile takes iteration.
- Portability is real for *tools/prompts/resources* and weaker for *UI and scopes*: in Claude Desktop the plugin's data reads go through the Cora gateway grants but not through Cora's consent sheet, and the UI is simply absent.

**Where a non-MCP design would be simpler:** pure-declarative plugins (Tier 0) don't need MCP internally at all; we only synthesize the MCP surface for export. If schedule slips, Tier 0 + first-party Python-in-process (the current model, but behind manifest, scopes and events) is a viable fallback, and the manifest and scope vocabulary carry over unchanged to the later sandboxed runtime. That is the recommended fallback and the reason WP1/WP3 are written runtime-agnostic.

**Competitive reality check** (from `research_competitors.json`): MCP access is table stakes (Granola, Otter, Read.ai, Circleback, Fireflies, Zoom), so the MCP *export* alone is parity. The differentiators are (a) plugins that run inside Cora with write access, local models and UI, (b) the same plugin working in Claude Desktop, and (c) a security story Anarlog (renderer-injected JS) and Screenpipe (broad agent permissions) cannot tell. Screenpipe owns the "pipes store" narrative and Anarlog has a plugin SDK, so launch copy must not claim "the only extensible meeting tool" (the discovery file's recommendation). Position: "plugins for your meetings that run on your Mac, work in Claude and Cursor, and can't phone home."

---

## 18. Work packages (see structured output for effort and dependencies)

Launch cut (target ≈ 22 agent-assisted working days of platform work, inside the 4-5 week window alongside transcription/templates/launch assets) is marked **[L]**; post-launch **[P]**.

1. **WP0 [L] Hardening prerequisites**: key allowlist for `/api/settings`; Electron `will-frame-navigate`, deny-all window open + `open-external` handler with lockdown check, `webRequest` loopback filter, exact `isTrustedUrl`; lockdown gate in `mcp_server.py`; MCP config includes `VOICECOACH_DATA_DIR`; stable `action_items`/`decisions` tables + migration from `todo_state` + reconcile.
2. **WP1 [L] Manifest, registry, consent store, policy**: schema, validator, manager state machine, `plugin_grants`/`plugins`/`plugin_kv`/`plugin_records`/`plugin_outputs`/`plugin_jobs`/`plugin_audit`, admin policy file, compat shim for `plugin_registry.py`.
3. **WP2 [L] Sandboxed runtime**: SBPL profile spike, spawn, asyncio MCP client loop, canary, lifecycle, watchdog, hot reload, Developer Mode.
4. **WP3 [L] `cora-host` server and brokers**: scoped tools, redaction, audit chain, quotas, audio staging, sampling handler.
5. **WP4 [L] Events and jobs plus pipeline hooks**: dispatcher, queue, runner/diarization hooks, audio lease and retention change.
6. **WP5 [L] LLM broker upgrades**: multi-turn + streaming in `credentials.py`, shared policy gate, per-plugin pins and budgets.
7. **WP6 [L] HTTP routes**: `/api/plugins/*`, rpc, chat SSE, dev attach, `dashboard_payload` plugins block.
8. **WP7a [L] Renderer contributions**: `plugin-host.js`, delegated tabs/settings/views, chat slot, install and runtime consent sheets, Plugins pane, badges, dynamic `showView`.
9. **WP7b [P] Sandboxed `ui://` frames**: protocol handler, CSP header, bridge, frame lifecycle.
10. **WP8 [L] Tier 0 engines**: analyzers, personas, templates, rule sets with local sinks; Tier 2 connector executor is **[P]**.
11. **WP9 [L] MCP export gateway**: proxy, `/api/mcp/rpc`, grants UI, plugin tool re-export, lockdown.
12. **WP10 [L-min] SDK and CLI**: Python SDK, `new/dev/test/validate/pack`, FakeHost, docs, hello-world.
13. **WP11 [P] Signing, registry and updates**: `sign`, signature verify (verification itself is **[L]** because first-party plugins use it), registry index, update flow with scope diff.
14. **WP12 [L] First-party plugins and migration**: coaching migration, roleplay, communication, storytelling, todo-export (local sinks), knowledge-base (minimal); roadmap tracker as the reference example **[P]**.
15. **WP13 [L] Tests and SOC 2 evidence**: lockdown conformance, policy-file tests, sandbox canary, threat-model doc, audit export.

---

## 19. Owner decisions needed

1. **`sandbox-exec` acceptable?** It is deprecated but functional. Alternative: ship Tier 1 *first-party only* at launch and treat third-party Tier 1 as Developer-Mode-only until a signed-helper sandbox is built. Recommended default: yes, with the canary and fail-closed.
2. **Third-party code at launch.** Recommend: third-party Tier 1 only through Developer Mode; marketplace post-launch. Confirm.
3. **MCP Apps spec revision to pin** (`ui://`, MIME profile, bridge methods) and `engines.mcp` revision (2025-06-18 assumed; verify current stable revision and the Python SDK `mcp>=2.2` client features, including `sampling` and `elicitation` callbacks, before WP2).
4. **Python-only SDK at launch** (TypeScript post-launch)?
5. **MCP export default.** Recommend off until explicitly enabled; refused under lockdown unless an admin policy allows it. Confirm.
6. **Plugin ID namespace and registry host** (GitHub Pages repo name, publisher key issuance).
7. **Cloud connectors for todo apps** at launch (Todoist/Linear) or local sinks only until after launch. Recommend local sinks only at launch.
8. **`ai_trace` retention** for plugin LLM calls on HIPAA/DoD machines (content is stored locally today): add a retention/off switch?
9. **Shared team todos approach:** file-synced ledger vs remote MCP (Tier 3). Recommend ledger, after launch.
10. **Voice roleplay** (host-mediated mic): defer past launch. Confirm.

## 20. Risks

- Schedule: the full plan is larger than the launch window; the cut line in §0/§18 is the mitigation, and the Tier-0-plus-first-party fallback preserves the manifest/scope contract.
- Sandbox profile iteration (Python under `deny default`) could consume the WP2 budget; keep a 2-day timebox and the fallback of first-party-in-process.
- MCP client feature gaps (`sampling`/`elicitation` in the Python SDK, in external clients) are version-dependent and must be verified early.
- Local-model quality limits roleplay and coaching under lockdown; set expectations in the UI.
- Cold start (0 stars): first-party plugins double as the examples and the PH demo; the 10-minute hello-world must be tested by someone who didn't write it.
- Electron main-process hardening (WP0) touches security-critical code; it needs tests and should land before any frame ships, even if frames are post-launch, because it independently closes real gaps.
