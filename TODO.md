# Cora TODO: launch plan and work packages

Generated 2026-10-20 from the design docs in [docs/planning/](docs/planning/). Branch: `production`. Each item below is a self-contained work package an agent can take: read the linked design doc section first, then do **only** the listed files, then run `uv run pytest -m "not mlx" -q`, `uv run ruff check python tests tools`, and `node scripts/lint-ui.js`.

## Status

- [x] One-line installer + unsigned-app explanation in README/INSTALL (`scripts/install.sh`)
- [x] Privacy hotfix: "On this Mac" no longer uploads; honest provenance labels (e80bf9e)
- [x] Demo-data seeder `tools/seed_demo_data.py` (PR #15)
- [x] Gemini transcription core (windows, structured call, validation, retry/split ladder): `TX:T-G2`, `TX:T-G3` and the orchestrator part of `TX:T-G4`, verified against the real API on synthetic audio. See [docs/transcription.md](docs/transcription.md)
- [ ] **Next: security prerequisites (`SDK:WP-0`), look-and-feel P0 (`UI:*`), then the rest of `TX:*` (compliance guard T-G1, UI-lite T-G6, bench T-G5) before any regulated customer uses Gemini**
- [ ] Plugin catalog design is a draft only: [plugin-catalog.draft.md](docs/planning/plugin-catalog.draft.md) (reviews not run)

## Ground rules for parallel agents

- One work package per agent, one branch per package (`wp/<id>`), PR into `production`. Do not edit files outside the package's list; if you must, stop and note it in the PR.
- Shared hot files (below) are the merge-conflict risk. Packages touching the same hot file must be sequenced or land in separate PRs rebased in order.
- Never weaken `python/policy.py` lockdown, the loopback token/Host/Origin checks in `python/api/`, or add outbound calls without a `policy.require_outbound_allowed` guard.
- No real meeting data in tests, fixtures, screenshots or docs. Use `tools/seed_demo_data.py`.
- Cross-track dependencies are not encoded in the lists below (only dependencies within a track). Check the design docs' "depends on" notes before starting.

## Owner decisions that block work

Answer these (a line each is enough) and the dependent packages unblock. Recommended defaults are in each design doc.

### Plugin SDK ([doc](docs/planning/plugin-sdk.md))
- [ ] Tier 1 UI frames: run the 1-day spike in week 3 only if slack (recommended), or defer entirely to post-launch?
- [ ] Under lockdown, keep export.file/export.clipboard allowed? Recommended yes (local), but files may land in synced folders; confirm with DoD customer expectations
- [ ] ai_trace.store_payloads: plugin default off (recommended) vs follow the global setting; should lockdown force the global default off too?
- [ ] MCP server under lockdown: refuse by default with admin mcp_export allow_local override (recommended); breaks local-only MCP use for lockdown users unless the admin opts in
- [ ] Honor enterprise_lockdown from the root-owned admin policy file in policy.lockdown_enabled() (recommended; closes the user-writable config.json gap)
- [ ] Third-party installs at launch: local sideload of Tier 0 only (recommended) vs also hiding sideload behind Developer Mode
- [ ] Ship cora.rehearse with prefer_local or require a configured cloud model for acceptable demo quality?
- [ ] Post-launch signing/registry: who signs Verified, whether an explicit-click Browse plugins network call is acceptable for the brand, and Ed25519 verification in Electron main vs bundled cryptography
- [ ] Include plugin tables, chat sessions and outputs in export-my-data and delete-my-data flows at launch (recommended yes)
- [ ] Licensing and naming: SDK under MIT in sdk/, cora.* id prefix reserved, .coraplugin extension

### Gemini transcription ([doc](docs/planning/transcription-gemini.md))
- [ ] GCP project/region for the daily driver and whether a BAA/ZDR posture exists; until confirmed, dogfood only non-customer meetings and mark customer meetings local_only
- [ ] If T-G0 finds the best model global-only: take the documented env-var residency override on production only, use an older regional GA model, or shelve the engine
- [ ] Default cloud_asr_context on production: none (shipped) vs meeting (names help recall but are personal data)
- [ ] Keep local as the first-run default everywhere and flip gemini only in the owner's production config
- [ ] Accept deleting the legacy whole-file Gemini path after G2
- [ ] Record and publish the scripted mock meeting plus reference, and commit 6-8 hours of blind labelling in week 1
- [ ] Confirm in writing that Tara was not trained on the gold-set meetings
- [ ] Prerequisites before any regulated customer enables Gemini: keychain-only SA keys (P-5), reduced notes-span payload retention, confirmation of Google data-handling terms
- [ ] Confirm or adjust the proposed pass-bar numbers before the Tara baseline run, after which they are frozen

### Notes templates ([doc](docs/planning/notes-templates.md))
- [ ] A1. Confirm the consent model: auto_notes_cloud default off, separate from notes_llm_provider, existing values ignored until the user opts in via the dialog. The design recommends this and implements it as the default posture.
- [ ] A2. Vertex vs AI Studio wording and defaults in the consent dialog for regulated customers (data-use terms), and whether a 'regulated' setting should hide AI Studio.
- [ ] A3. one_on_one is cloud-eligible (not local_only) because cloud is already an explicit opt-in. Flip it if HR content should stay local by default.
- [ ] A4. Ship the executive one-pager in v1 as the third PH demo moment (recommended, about 0.2 d), or hold it with the post-launch templates.
- [ ] A6. After the WP1 spike: pin the Gemini model and the notes_thinking setting, and confirm leaving temperature at the provider default.

### Look and feel ([doc](docs/planning/look-and-feel.md))
- [ ] Teal reserved for privacy state with neutral-ink primary actions (recommended) versus keeping blue actions
- [ ] hiddenInset opaque window for launch (recommended) versus standard title bar; confirm vibrancy is out of P0
- [ ] Approve the Ring mark or commission a final mark
- [ ] Rehearse launch dependency: name the fallback shot and video beat if the streaming endpoint (GATE-4) slips
- [ ] Approve Tier A (9.75 days) as the minimum and 20.75 days as the target given competing tracks
- [ ] Stage semantics: hide the ready state; Coached badge only when the coaching plugin is on
- [ ] Drop meeting types and people from mandatory onboarding
- [ ] Keep Memory or rename to Vocabulary
- [ ] System font in P0 versus self-hosted Inter in P1
- [ ] Opt-in global record shortcut in P1 (default unset) versus none
- [ ] Hinglish caption only if the ASR benchmark supports it

### Phone capture over Tailscale ([doc](docs/planning/phone-capture.md))
- [ ] Confirm Week-1 slice as v1 and PWA/pairing/read-all/Settings UI/headless/attach as post-launch
- [ ] Mac Studio runs Electron as Login Item in v1 (recommended) vs waiting for headless plus attach
- [ ] Allow opt-in read-own for the Latest Note Shortcut in v1 (recommended) vs upload-only
- [ ] Serve port 9443 (WP0-confirmed) vs 443 with a funnel nodeAttr policy audit
- [ ] Delete the INBOX copy after verified archive
- [ ] Gateway in-process now with defined split trigger vs split into a sibling process now
- [ ] Beta label and the single Product Hunt sentence, with go/no-go on 2026-11-06 tied to the exit gate
- [ ] Confirm tentative dates and that the owner can supply an iPhone and Mac Studio time for WP0 and the dogfood week

### Positioning and launch ([doc](docs/planning/pmf-and-launch.md))
- [ ] Approve the hero (Rehearse vs platform vs Hinglish accuracy); final read-out on Oct 30
- [ ] Confirm owner time zone and whether a co-maker can cover launch-day shifts (the plan assumes IST)
- [ ] Enroll in the Apple Developer Program today, individual vs organization (D-U-N-S delay), and budget $99/yr
- [ ] Approve no voice cloning and no voiceprints of other participants for roleplay and coaching
- [ ] Accept an explicit labelled cloud-model opt-in as the default Rehearse path if the local model fails T2
- [ ] Confirm releases are cut from the public lineage, never from the production working tree, and confirm third-party and model licences (Tara weights) before any 'local model' claim
- [ ] Accept deferring phone capture/Tailscale and the windowed-Gemini rewrite until after launch
- [ ] Pricing: park Pro until after day 90, or run a no-payment supporter page at launch
- [ ] Approve a short legal review of privacy policy, terms, BIPA and India DPDP consent notice
- [ ] Decide whether to run the Hinglish benchmark (T7) and publish it, losses included

## Work packages by track

### Plugin SDK: `SDK:*`  ([design doc](docs/planning/plugin-sdk.md), 26.0 agent-days)

The final Plugin SDK v1 design is written. It starts from the declarative-first proposal and cuts it to about 3 weeks. Launch is Tier 0 "recipe" plugins: a manifest, prompt files, JSON schemas and rule files, rendered by host UI, with no third-party code running. The only in-process Python is the bundled, hash-pinned `cora.coaching` migration (Tier 3). Tier 1 UI frames and Tier 2 sandboxed sidecars are marked roadmap. The schema reserves their fields, and a 1-day Electron spike for Tier 1 is optional in week 3. The doc contains the full manifest JSON Schema, worked examples (`cora.rehearse`, a

- [ ] **SDK:WP-0** Security prerequisites (settings allowlist, policy_lockdown error code, MCP lockdown gate + data-dir passthrough, Electron navigation/open-external hardening, webRequest loopback filter, coaching privacy copy fix, admin policy loader)  _(2.5d)_
  - files: `plugins/coaching/README.md`, `plugins/coaching/engine.py`, `python/api/http.py`, `python/api/routes/settings.py`, `python/mcp_server.py`, `python/pluginhost/policy_admin.py`, `python/policy.py`, `src/main.js`, `src/main/security.js`
  - done when: POST /api/settings rejects unknown keys; LockdownError returns 403 with code policy_lockdown; MCP server refuses start under lockdown unless admin allows; open-external denied under lockdown; will-frame-navigate and window-open denied for untrusted frames; untrusted/group-writable policy file ignored and audited; coaching copy matches inline-bytes behavior
- [ ] **SDK:WP-1** pluginhost core: schema-subset validator, manifest, registry with plugin_registry shim, grants, hash-chained audit + verify, DB tables, /api/plugins routes, install preview/commit, verb registry + egress guard  _(3.5d)_
  - depends on: SDK:WP-0
  - files: `python/api/routes/__init__.py`, `python/api/routes/plugins.py`, `python/db.py`, `python/plugin_registry.py`, `python/pluginhost/audit.py`, `python/pluginhost/egress.py`, `python/pluginhost/grants.py`, `python/pluginhost/manifest.py`, `python/pluginhost/packaging.py`, `python/pluginhost/registry.py`, `python/pluginhost/schema.py`, `python/pluginhost/verbs.py`, `sdk/schema/plugin.v1.schema.json`
  - done when: Example manifests validate; install preview returns consent model; grants persisted with bundle hash; audit chain verifies and detects tampering; all routes behind authorize with no new public paths; state/reason persisted, no silent errors
- [ ] **SDK:WP-2** Events/jobs/scheduler (emit-only + server worker), recipe executor, templating, call_configured_chat, ai_trace payload control, audio lease + runner hooks, plugins_excluded  _(4d)_
  - depends on: SDK:WP-1
  - files: `python/ai_trace.py`, `python/api/routes/recordings.py`, `python/credentials.py`, `python/cron_runner.py`, `python/diarization.py`, `python/pipeline/runner.py`, `python/pluginhost/audio_lease.py`, `python/pluginhost/chat.py`, `python/pluginhost/events.py`, `python/pluginhost/jobs.py`, `python/pluginhost/recipes.py`, `python/pluginhost/scheduler.py`, `python/pluginhost/templating.py`, `python/server.py`
  - done when: meeting.processed emitted at runner.py:343 from both server and cron_runner processes, jobs drained by server worker with dedupe; recipe runs produce validated outputs with one repair; plugin calls store no ai_trace payloads by default; audio deletion deferred under lease and swept; excluded recordings queue nothing
- [ ] **SDK:WP-3** Renderer: plugin-host.js, delegated binding refactor, registerView, notes sections/tabs/chips/pages, settings form renderer, install sheet, chat dock  _(4d)_
  - depends on: SDK:WP-1
  - files: `scripts/lint-ui.js`, `src/ui/web/index.html`, `src/ui/web/js/core.js`, `src/ui/web/js/detail.js`, `src/ui/web/js/init.js`, `src/ui/web/js/notepad.js`, `src/ui/web/js/plugin-host.js`, `src/ui/web/js/search.js`, `src/ui/web/js/settings.js`, `src/ui/web/styles.css`
  - done when: Plugin surfaces render from /api/plugins/contrib with no plugin JS in the renderer; install sheet shows resolved data destination and lockdown state; chat dock works with single-chunk fallback; lint-ui passes with no unescaped innerHTML; dynamic tabs/settings/pages bind correctly
- [ ] **SDK:WP-4** Items/decisions tables with stable UUIDs, todo_state migration, FTS, rule engine, export formats and preview  _(2.5d)_
  - depends on: SDK:WP-1
  - files: `python/api/routes/items.py`, `python/api/views.py`, `python/db.py`, `python/pipeline/notes.py`, `python/pipeline/runner.py`, `python/pluginhost/exports.py`, `python/pluginhost/rules.py`
  - done when: Re-summarize preserves item status via text_hash reconcile; legacy todo_state migrated; export preview shows matched rule per item; catastrophic-regex fixture times out safely; re-export dedupes via item_events
- [ ] **SDK:WP-5** Coaching migration to Tier 3 via ctx facade with dual-write outputs and deprecated aliases  _(2.5d)_
  - depends on: SDK:WP-2
  - files: `plugins/coaching/engine.py`, `plugins/coaching/plugin.json`, `python/api/routes/coaching.py`, `python/api/views.py`, `python/mcp_server.py`, `python/plugin_registry.py`, `python/pluginhost/tier3_ctx.py`
  - done when: Existing coaching output unchanged via shim; no network or private-helper imports in plugins/coaching; lockdown skips cloud pass with skipped:disabled_by_policy while local metrics still run; /api/confirm-and-coach and /api/gemini-coach enqueue jobs
- [ ] **SDK:WP-6** First-party plugins (rehearse, kb, comm-coach, todo-export, templates contract) with fictional fixtures and conformance/hostile suites  _(3d)_
  - depends on: SDK:WP-2, SDK:WP-3, SDK:WP-4
  - files: `plugins/cora.comm-coach/`, `plugins/cora.kb/`, `plugins/cora.rehearse/`, `plugins/cora.templates/`, `plugins/cora.todo-export/`, `sdk/fixtures/`, `tests/test_egress_static.py`, `tests/test_hostile_plugin.py`, `tests/test_lockdown_plugins.py`
  - done when: Each plugin installs through the consent sheet and runs on a fictional demo meeting; conformance suite proves every egress verb denied under lockdown; hostile-plugin suite passes; no real data in fixtures
- [ ] **SDK:WP-7** CLI (create/validate/run/dev/pack), generated SDK types, docs, hello-world scaffold  _(2d)_
  - depends on: SDK:WP-1, SDK:WP-6
  - files: `docs/plugins/`, `sdk/cli/cora-plugin.js`, `sdk/cora-plugin.d.ts`, `sdk/templates/`, `sdk/verbs.v1.json`, `tools/gen_sdk_types.py`
  - done when: Ten-minute hello-world works end to end with dry-run, dev hot reload and pack; manifest and verb reference generated from schema/registry; dev link refuses under lockdown or without developer mode
- [ ] **SDK:WP-8** MCP plugin-output views and mcp.expose grant UI (off by default)  _(1d)_
  - depends on: SDK:WP-1
  - files: `python/api/routes/settings.py`, `python/db.py`, `python/mcp_server.py`, `src/ui/web/js/plugin-host.js`
  - done when: Granted plugins expose only mcp_visible outputs via v_mcp_* views; excluded recordings omitted; MCP refuses under lockdown without admin allow_local
- [ ] **SDK:WP-9** Optional Tier 1 frame spike (go/no-go doc only)  _(1d)_
  - depends on: SDK:WP-0, SDK:WP-3
  - files: `src/main.js`, `src/main/security.js`, `src/ui/web/index.html`
  - done when: Written verdict on cora-plugin:// protocol.handle, sandboxed iframe with allow-same-origin, and webRequest frame attribution; no production code merged

### Gemini transcription: `TX:*`  ([design doc](docs/planning/transcription-gemini.md), 16.5 agent-days)

Rev 2 replaces per-clip Gemini with windowed structured transcription: about 240 s FLAC windows cut at pauses, a small adaptive worker pool, and JSON turns {start,end,text} under a response_schema. About 15-17 calls per meeting-hour. Gemini no longer labels speakers, so attribution stays AX, then mic/system loudness, then default, and the tracks path keeps the literal "You". All cloud audio goes through one guard (asr_engines.guard), and the engine value set is only local and gemini. Per-clip dispatch is deleted, transcribe.py becomes local-only, and transcribe_windows refuses to run without a

- [ ] **TX:T-G0** Go/no-go spike: model x region x quota, schema+thinking+tokens combo, SDK facts, Google data-handling docs  _(1d)_
  - files: `docs/transcription.md`, `python/pipeline/asr_models.json`, `tools/asr_smoke.py`
  - done when: Decision-tree outcome recorded (compliant regional model, owner override, or shelve); 429 table at 1-4 concurrent calls; probe passes from the owner's project; existing audit store checked
- [ ] **TX:T-G1** Compliance guard, ASR Vertex client, audit-log consent, settings-route rejection, rewire all dispatch sites, legacy 410  _(2.5d)_
  - depends on: TX:T-G0
  - files: `python/api/routes/recordings.py`, `python/api/routes/settings.py`, `python/api/routes/transcription.py`, `python/credentials.py`, `python/pipeline/asr_engines.py`, `python/pipeline/cloud_asr.py`, `python/pipeline/transcribe.py`, `tests/test_asr_guard.py`, `tests/test_lockdown_asr.py`
  - done when: Socket-blocked lockdown and guard tests green for every call site; no cloud branch remains in transcribe.py; forged settings ack has no effect; local_only honoured
- [x] **TX:T-G2** Window planner, FLAC extraction, strict VAD, temp-file sweep  _(1.5d)_
  - files: `python/pipeline/audio.py`, `python/pipeline/windows.py`, `tests/test_asr_temp_files.py`, `tests/test_windows.py`
  - _built without the strict-VAD false-fail measurement and temp-dir sweep (still open)._
  - done when: Planner tests pass; FLAC under 12 MB per window; strict-VAD false-fail rate measured on a noisy excerpt; temp dirs 0700 and swept at startup
- [x] **TX:T-G3** Gemini window call, meeting-only context, parse, validate, snap, asr_span  _(2d)_
  - depends on: TX:T-G0
  - files: `python/pipeline/asr_validate.py`, `python/pipeline/context.py`, `python/pipeline/gemini_asr.py`, `tests/test_asr_trace_minimization.py`, `tests/test_asr_validate.py`, `tests/test_gemini_asr.py`
  - _built; differences from the design: uses the configured Gemini client (not Vertex-only), full glossary kept, trace stores sizes/counts only._
  - done when: Fake-client tests green; no temperature key; one real window validates; sentinel trace-minimization test green; Langfuse bridge exclusion verified
- [~] **TX:T-G4** (orchestrator, retry/split ladder, runner wiring and honest provenance done; windows report, cleanup ordering and soak test open) Orchestrator, minimal ladder, runner integration, provenance, windows report, cleanup order  _(2d)_
  - depends on: TX:T-G1, TX:T-G2, TX:T-G3
  - files: `python/pipeline/runner.py`, `python/pipeline/windowed.py`, `tests/test_provenance.py`, `tests/test_windowed_ladder.py`
  - done when: 60-min recording end-to-end; failed run leaves previous transcript intact; provenance honest in all outcomes (location from resolved client); soak test passes
- [ ] **TX:T-G5** Minimal bench, blind gold set, Tara baselines (private and public default), pre-registration  _(2d)_
  - depends on: TX:T-G2
  - files: `.gitignore`, `tests/test_asr_metrics.py`, `tools/asr_bench.py`, `tools/asr_metrics.py`, `tools/asr_prereg.json`
  - done when: Baselines produced and prereg hash committed before any gemini scoring; no DB mutation; metrics unit-tested; 6-8 owner hours of blind labelling started week 1
- [ ] **TX:T-G6** UI-lite: engine select with data-flow text, configuration checks, test button, consent modal, chip, retranscribe confirm with edit-discard, local-only toggle  _(2d)_
  - depends on: TX:T-G1, TX:T-G4
  - files: `src/ui/web/index.html`, `src/ui/web/js/detail-actions.js`, `src/ui/web/js/detail.js`, `src/ui/web/js/settings.js`, `src/ui/web/js/transcript.js`, `src/ui/web/styles.css`
  - done when: Matches doc section 11; light/dark; lockdown state; CSP unchanged; screenshots from seeded fictional data only
- [ ] **TX:T-G7** Compliance suite completion and docs (data flow, egress hosts, retention, consent, not-verified list)  _(1d)_
  - depends on: TX:T-G4
  - files: `docs/transcription.md`, `tests/test_transcription_routes.py`
  - done when: All section-13 compliance tests green; docs list hosts and exactly what is sent
- [ ] **TX:P-1-P-5** Independent PRs: per-part loudness fix with AX time-base verification, dedupe key, float timestamps, provenance notes-provider sentence, keychain-only SA key  _(2.5d)_
  - files: `python/credentials.py`, `python/pipeline/runner.py`, `python/pipeline/speakers.py`, `python/pipeline/transcribe.py`
  - done when: Each PR has its own tests and merges independently; none is gated on Gemini results

### Notes templates: `TPL:*`  ([design doc](docs/planning/notes-templates.md), 15.5 agent-days)

Revision 2 of the notes-templates design rewrites the draft against all three adversarial reviews. User templates now live in DATA_DIR/user_templates/notes, a different directory from the built-ins. This fixes the collision on the owner's machine, where DATA_DIR equals APP_ROOT. The new dir is added to _PRIVATE_ENTRIES, and the writer refuses any path that resolves under APP_ROOT/templates. Automatic cloud notes now require a separate auto_notes_cloud setting. It defaults to off, is set only by a confirm dialog that names the provider, and is timestamped and audit-logged. It is not derived fro

- [ ] **TPL:WP0** Consent, egress and error plumbing (auto_notes_cloud, stop save_* writing notes_llm_provider, protected setting key, audit events, trace payload control, implicit-upload caller audit, @notes_errors)  _(1.5d)_
  - files: `python/api/routes/settings.py`, `python/api/routes/templates.py`, `python/credentials.py`, `src/ui/web/index.html`, `src/ui/web/js/settings.js`, `tests/test_notes_consent.py`
  - done when: Regression test passes: a user with notes_llm_provider='gemini' and no auto_notes_cloud still gets local notes. The consent route requires confirm and is lockdown-gated. The generic settings setter cannot write auto_notes_cloud. An audit list of callers of call_configured_llm with provider=None is in the PR.
- [ ] **TPL:WP1** Gemini structured call, spike and coerce_note (system_instruction, model resolution, thinking, finish reasons, status keys, SDK pin, section cap)  _(1.5d)_
  - depends on: TPL:WP0
  - files: `python/credentials.py`, `python/pipeline/notes_coerce.py`, `tests/test_cloud_llm_structured.py`, `tests/test_notes_coerce.py`
  - done when: Spike results recorded and the exact google-genai version pinned. An 8-section schema is accepted and the 9-section rejection case is documented. The golden GenerateContentConfig test is green. Finish-reason classes are tested. coerce_note passes the dict/str-cite/bool-cite/repair cases. The opt-in live smoke test passes locally.
- [ ] **TPL:WP2** Template registry, validator, resolver, 6 built-ins, paths and packaging  _(2d)_
  - files: `package.json`, `python/note_templates.py`, `python/paths.py`, `templates/notes/customer_call.json`, `templates/notes/default.json`, `templates/notes/executive.json`, `templates/notes/one_on_one.json`, `templates/notes/solo_voice_memo.json`, `templates/notes/standup.json`, `tests/test_note_templates.py`, `tests/test_packaging.py`
  - done when: The save/override/reset/delete suite leaves the built-in dir byte-identical with DATA_DIR equal to APP_ROOT and with a temp DATA_DIR. All built-ins validate. Unknown keys are dropped. The confidence-gated resolver matches the tests. Packaged build contains templates/notes.
- [ ] **TPL:WP3** Render engine: cloud render, quote-anchored citation resolution, injection-hardened prompt, legacy adapter, generic local renderer with 7-call cap, legacy/notes markdown, to_legacy  _(2.5d)_
  - depends on: TPL:WP1, TPL:WP2
  - files: `python/pipeline/notes.py`, `python/pipeline/notes_render.py`, `tests/test_notes_local_budget.py`, `tests/test_notes_render.py`
  - done when: Injection fixtures pass on downstream artifacts (tasks, recording_name, vocabulary, legacy markdown). Quote resolution handles verified, corrected, unverified and unchecked, including Hinglish. The max-size local template makes <=7 calls. An unmodified default uses the legacy generator and an edited default uses the generic renderer. to_legacy core fields are never empty. 2.5 h local timing is recorded.
- [ ] **TPL:WP4** Runner integration: file locks, continuation-to-parent write, archive scopes and manifests, provenance, DB-based staleness, kill switch, pending-pick merge  _(2d)_
  - depends on: TPL:WP3
  - files: `python/api/routes/recordings.py`, `python/api/views.py`, `python/db.py`, `python/pipeline/runner.py`, `tests/test_archive_scopes.py`, `tests/test_notes_runner.py`, `tests/test_notes_staleness.py`
  - done when: With notes_templates_enabled=false, enhanced_notes.md and call_summary.json (schema 2.0) are byte-identical to the pre-change runner. Continuation writes notes into the parent and archives them first. The pipeline takes .notes.lock and a concurrent manual render gets 409. A pending template pick survives to the final folder. Retranscribe still versions the WAV and notes scope never does. Staleness comes from the DB copy and chips are disabled only on a structure change.
- [ ] **TPL:WP5** API, views, MCP envelope and summary fallback, re-summarize alias  _(1.5d)_
  - depends on: TPL:WP4
  - files: `python/api/routes/__init__.py`, `python/api/routes/templates.py`, `python/api/views.py`, `python/mcp_server.py`, `tests/test_mcp_notes.py`, `tests/test_notes_api.py`
  - done when: Every route is tested for auth, caps and id validation. Error mapping gives 403, 409 and a sanitized 502. Preview writes nothing and render writes notes/* and mirrors the main note. no_transcript returns 400 with no provider call. Structured log lines are emitted, including on local renders. MCP responses carry the untrusted envelope and the summary fallback works.
- [ ] **TPL:WP6** UI: regenerate modal, template chip and popover, suggestion chip, Add output, structured renderer with citation chips, loading state, banners, consent flow  _(2d)_
  - depends on: TPL:WP5
  - files: `src/ui/web/index.html`, `src/ui/web/js/detail-actions.js`, `src/ui/web/js/detail.js`, `src/ui/web/js/notes-render.js`, `src/ui/web/js/settings.js`, `src/ui/web/styles.css`
  - done when: lint-ui passes and the manual checklist passes (380 px and 1280 px, keyboard, light and dark, lockdown). The three demo moments (one recording in three lenses, chip seeks audio and transcript, edit-and-preview) work on synthetic fixtures. The loading strip and empty state exist.
- [ ] **TPL:WP7** Templates settings panel: list, JSON editor with validate, preview on a meeting, duplicate, reset, delete, copy, import with sha and full text  _(1d)_
  - depends on: TPL:WP5, TPL:WP6
  - files: `src/ui/web/index.html`, `src/ui/web/js/settings.js`, `src/ui/web/styles.css`
  - done when: Validate shows path errors, preview renders via renderStructuredNotes with the egress notice, and import shows sha256 plus full prompt text and marks imported templates unreviewed and non-auto-selectable. A bad file never breaks the app. Droppable if the schedule slips.
- [ ] **TPL:WP8** Gold-labelled eval with automatic scoring, synthetic fixtures, 30-meeting suggestion set, packaged-build smoke, docs, demo script and screenshots  _(1.5d)_
  - depends on: TPL:WP3
  - files: `docs/templates.md`, `tests/fixtures/transcripts/`, `tools/eval_notes_templates.py`
  - done when: The committed baseline JSON records task recall and precision, owner/due accuracy, citation hit rate and injection pass/fail for local and Gemini. Suggestion accuracy is measured and decides whether SHOW_MODEL_SUGGESTION is on (>=85%). The packaged smoke test passes. Launch screenshots come only from synthetic data.

### Look and feel: `UI:*`  ([design doc](docs/planning/look-and-feel.md), 21.0 agent-days)

Revision 2 of the look-and-feel design resolves every must_fix from the three reviews. The privacy chip and Settings cards now derive from a server-computed state. That state covers resolved ASR, notes provider, sync and log upload, MCP use (via a heartbeat), and plugin egress (null until the plugin track defines scopes), plus lockdown. A lockdown_partial state shows when MCP is used but lockdown does not cover it. The chip copy is narrowed and is not a compliance claim. The brand signature is the Ring: the mark's ring colour is the live privacy state, in three places only (sidebar chip, engin

- [ ] **UI:LF-0** Standalone fixes: transcript gap (verify cause first), task checkbox rows, item_key keying, stage-badge UI fix, remove disabled Ask row  _(1d)_
  - files: `python/db.py`, `src/ui/web/index.html`, `src/ui/web/js/core.js`, `src/ui/web/js/detail.js`, `src/ui/web/js/transcript.js`
  - done when: Transcript speaker and text have no stray gap; '- [ ]' renders as checkboxes whose state survives regenerate when item text is unchanged; finished meetings show no badge; no disabled Ask row remains; node tests pass
- [ ] **UI:LF-1** Tokens (light and both dark blocks), complete compat aliases, system font, token lint, contrast script  _(1d)_
  - depends on: UI:LF-0
  - files: `scripts/check-contrast.js`, `scripts/lint-ui.js`, `src/ui/web/index.html`, `src/ui/web/styles.css`, `src/ui/web/tokens.css`
  - done when: Every var(--x) is defined; the dark blocks are identical per lint; contrast script passes all listed pairs in light and dark; before/after screenshots reviewed by the owner; no teal outside privacy selectors
- [ ] **UI:LF-2** About 22 Lucide icons via icons.js, delete pixel-icons.js, notices file, advisory emoji lint  _(0.75d)_
  - depends on: UI:LF-1
  - files: `THIRD_PARTY_NOTICES.md`, `scripts/lint-ui.js`, `src/ui/web/icons.js`, `src/ui/web/index.html`, `src/ui/web/pixel-icons.js`
  - done when: [data-icon] API still works; P0 screens contain no emoji or pixel icons; Lucide ISC notice ships in repo and Settings
- [ ] **UI:LF-3** UI kit on platform primitives: dialog, popover menu, toast, badge, emptyState, skeleton  _(1d)_
  - depends on: UI:LF-1
  - files: `src/ui/web/components.css`, `src/ui/web/js/ui-kit.js`
  - done when: prompt()/confirm() replaced by dialog; menus are keyboard operable; kit emits no style attributes; policy-disabled controls use aria-disabled with visible reason text
- [ ] **UI:LF-4** Shell: hiddenInset opaque window, drag audit, window state, application menu, boot.js, nativeTheme IPC, sidebar, topbar removal, privacy summary route and chip, MCP heartbeat  _(2d)_
  - depends on: UI:LF-3
  - files: `python/api/routes/system.py`, `python/mcp_server.py`, `src/main.js`, `src/main/menu.js`, `src/preload.js`, `src/ui/web/index.html`, `src/ui/web/js/boot.js`, `src/ui/web/js/core.js`, `src/ui/web/js/folders.js`, `src/ui/web/js/privacy-chip.js`
  - done when: No Force Reload shortcut in packaged build; every control in top 52px is clickable; window size and position restore; /api/privacy/summary enforces token/Host/Origin and returns no secrets; chip state matches the matrix including lockdown_partial; theme follows nativeTheme with no flash
- [ ] **UI:LF-5** Home: day grouping, badge language, skeleton, empty state, live row  _(0.75d)_
  - depends on: UI:LF-3
  - files: `src/ui/web/index.html`, `src/ui/web/js/core.js`, `src/ui/web/js/sessions.js`
  - done when: Rows grouped by day, 12px minimum text, badges only when attention is needed, skeleton rows and empty state present
- [ ] **UI:LF-6** Meeting detail: header, action menus, three tabs, notes typography, processing steps, People restyle, title editor restyle  _(2d)_
  - depends on: UI:LF-3
  - files: `src/ui/web/index.html`, `src/ui/web/js/detail-actions.js`, `src/ui/web/js/detail.js`, `src/ui/web/js/notepad.js`, `src/ui/web/js/search.js`, `src/ui/web/js/title-editor.js`
  - done when: Header, tabs and actions under 120px; notes start above the fold at 800px height; menus replace five emoji buttons; processing shows named steps with a static reduced-motion equivalent
- [ ] **UI:LF-7a** Settings: sans titles, engine cards with confirm dialog, Data & privacy panel  _(1.25d)_
  - depends on: UI:LF-3, UI:LF-4
  - files: `src/ui/web/index.html`, `src/ui/web/js/settings.js`
  - done when: Selecting Gemini always opens a dialog naming what leaves the Mac; cancel leaves the setting unchanged; under lockdown the card is aria-disabled with visible reason; Data & privacy table matches /api/privacy/summary including lockdown_covers
- [ ] **UI:LF-8** Trimmed onboarding, sample meeting endpoints and bundle, sample exclusion from MCP, export, sync, retention and People  _(1.5d)_
  - depends on: UI:LF-3
  - files: `python/api/routes/cloud.py`, `python/api/routes/recordings.py`, `python/api/views.py`, `python/mcp_server.py`, `python/samples/q4-roadmap-review/`, `src/ui/web/index.html`, `src/ui/web/js/onboarding.js`
  - done when: Three-screen onboarding with no orphaned Vertex step; samples/load and samples/remove are idempotent with no parameters or network; sample absent from MCP, export, sync and retention (tests); no real names in bundle
- [ ] **UI:LF-A11Y** Accessibility package: landmarks, skip link, tablist pattern, focus-visible reveals, reduced-motion equivalents, toast and floater timers  _(1.5d)_
  - depends on: UI:LF-6, UI:LF-7a
  - files: `src/ui/web/index.html`, `src/ui/web/js/ui-kit.js`, `src/ui/web/styles.css`
  - done when: Keyboard-only and VoiceOver passes complete on first run, Home, Notes, Settings > Transcription and Rehearse; no hover-only affordance; floater actions verified via tray menu
- [ ] **UI:LF-10** ChatPanel with scripted fixture stream, Rehearse view, honesty banner, debrief  _(2d)_
  - depends on: UI:LF-3
  - files: `src/ui/web/components.css`, `src/ui/web/js/chat-panel.js`
  - done when: Transcript-style turns with AI tag; no live region on the message list, finished message announced once via role=status; works against the fixture; first-token latency measured; launch requires the real streaming endpoint (GATE-4)
- [ ] **UI:LF-11** Ring mark, app icon (src/icon.png and src/icon.icns), tray template images, small-size legibility checks  _(1.5d)_
  - files: `src/icon.icns`, `src/icon.png`, `src/main.js`, `src/trayTemplate.png`, `src/trayTemplate@2x.png`
  - done when: Packaged app uses the new icns; tray is a template image visible in light and dark menu bars; thumbnail legible at 48px and 24px (ring-only fallback if not); current icns inspected before claiming the margin bug
- [ ] **UI:LF-12** Floater: icon swap, toast folded into pill, width prototype around 360, opaque capsule, Ring  _(0.75d)_
  - depends on: UI:LF-11
  - files: `src/main.js`, `src/ui/floater.html`, `src/ui/floater.js`
  - done when: All controls fit without clipping at the chosen width; Saved state visible inside the pill; meters carry a non-colour cue; no backdrop-filter; auto-hide pauses on hover and focus
- [ ] **UI:LF-14** CORA_DEMO guard, 4 gallery shots, thumbnail, 45-50s video with README loop, local counts-only OCR checker  _(3d)_
  - depends on: UI:LF-4, UI:LF-5, UI:LF-6, UI:LF-7a, UI:LF-8, UI:LF-10, UI:LF-11, UI:LF-12
  - files: `src/main.js`, `tools/check_demo_assets.py`
  - done when: CORA_DEMO refuses to start on the real data dir; check_demo_assets prints only counts and is not run in CI; all assets use fictional seed data and synthesized audio; captions respect the claims gate
- [ ] **UI:LF-16** Node unit tests, contrast script in CI, lint-ui additions, privacy route and sample tests  _(1d)_
  - depends on: UI:LF-1
  - files: `.github/workflows/ci.yml`, `scripts/lint-ui.js`, `tests/test_privacy_summary.py`, `tests/test_server_auth.py`, `tests/ui/`
  - done when: CI runs node --test tests/ui and the contrast script; /api/privacy/summary is in the auth route inventory; the state matrix test passes

### Phone capture over Tailscale: `MOB:*`  ([design doc](docs/planning/phone-capture.md), 7.8 agent-days)

The revised design cuts v1 to a Week-1 slice. An iOS Shortcut ("Send to Cora") uploads to a tiny 5-route mobile gateway. The gateway is a second loopback listener in the same Python process, published via tailscale serve on non-Funnel port 9443, and the main API on 8765 is untouched. Upload now returns 202 right after the body is streamed to a staging directory outside INBOX, sha256-hashed and fsynced. Probing, normalising and archiving moved into the worker, with new states received, normalizing and queued. The worker runs each job as a subprocess with a timeout and an attempts cap. It defers

- [ ] **MOB:WP0** Real-device and real-proxy spike (owner hands): Shortcut size/timeout, serve port 9443 and unix target, Host with port, early-reject/chunked through serve, fixtures  _(0.5d)_
  - files: `tools/mobile_spike/*`
  - done when: Documented answers on 9443 acceptance, Host form, Shortcut 30/60/100 MB over cellular, early-reject and chunked behaviour through real tailscale serve, share-sheet listing; real serve status --json fixtures captured
- [ ] **MOB:WP1** Policy gate, config/store tables, tokens, fail-closed audit  _(1d)_
  - files: `python/mobile/audit.py`, `python/mobile/config.py`, `python/mobile/store.py`, `python/mobile/tokens.py`, `python/policy.py`, `python/server.py`
  - done when: Tokens hashed, bound to login, rotate/expire/revoke work; audit write failure aborts the action; mobile_* not writable via settings/MCP/import; lockdown makes mobile_ingress_allowed false; files 0600
- [ ] **MOB:WP2** Gateway, netcheck, 5 routes, owner routes, CLI  _(1.25d)_
  - depends on: MOB:WP1
  - files: `python/api/routes/__init__.py`, `python/api/routes/mobile.py`, `python/mobile/gateway.py`, `python/mobile/netcheck.py`, `python/mobile/runtime.py`, `tools/cora_mobile.py`
  - done when: Route table exactly 5 routes, everything else 404; table-driven header/token/scope tests pass; main API ts.net Host/Origin still 403; reject ring visible; slow-loris timeout honoured
- [ ] **MOB:WP3** Streaming upload, staging, quotas, early-reply drain, idempotency/requeue  _(1d)_
  - depends on: MOB:WP2
  - files: `python/mobile/upload.py`, `tests/test_mobile_upload.py`
  - done when: 202 before any ffmpeg runs; failed rows requeue by client id and sha; per-device daily byte quota, hourly cap, global byte cap, queue-depth 503 enforced incl. rejected attempts; early rejects delivered without RST; no orphan files after kill -9
- [ ] **MOB:WP4** Hardened media handling  _(0.5d)_
  - depends on: MOB:WP3
  - files: `python/mobile/media.py`, `tests/test_mobile_media.py`
  - done when: m3u8/ffconcat pointing at a loopback listener cause no connection and fail unreadable_audio; sniff, whitelists, empty cwd, rlimits, timeouts verified; pass-through for Voice Memos m4a, single-stream normalise otherwise
- [ ] **MOB:WP5** PipelineWorker, priority gate, job subprocess, force-local, db/flock/baseline/exclusive edits  _(1.5d)_
  - depends on: MOB:WP3, MOB:WP4
  - files: `python/api/routes/recordings.py`, `python/db.py`, `python/pipeline/cloud_asr.py`, `python/pipeline_job.py`, `python/pipeline_worker.py`, `python/voice_memo_pipeline.py`, `tests/test_pipeline_worker.py`
  - done when: Single-flight with UI priority; defers during live recording; job timeout kills process group; attempts and crash-loop caps; pending row before os.replace; get_unprocessed_recording excludes m_ rows; main() waits 60 s for flock; real baseline test with old Voice Memos files; no-outbound test with non-local engine configured
- [ ] **MOB:WP6** Notes views (latest/by id) and doctor (4 fail-capable plus 2 warn-only)  _(0.75d)_
  - depends on: MOB:WP5
  - files: `python/mobile/tailscale.py`, `python/mobile/views.py`, `tests/test_mobile_views.py`, `tests/test_tailscale_doctor.py`
  - done when: Notes text only, own-only, relative_to guarded, forbidden strings absent on real fixture; doctor fails on Funnel and on any handler targeting 8765
- [ ] **MOB:WP7** Docs, Shortcut recipes, smoke tool, evidence note, tailnet policy sample  _(0.5d)_
  - depends on: MOB:WP6
  - files: `docs/PHONE_CAPTURE.md`, `docs/shortcuts/SEND_TO_CORA.md`, `tools/mobile_smoke.py`
  - done when: Owner can set up Tailscale, mint token and build both Shortcuts from docs alone; honest PHI-on-phone, availability and SOC 2 mapping text present
- [ ] **MOB:WP8** Exit-gate run, real-model soak, dogfood fixes  _(0.75d)_
  - depends on: MOB:WP1, MOB:WP2, MOB:WP3, MOB:WP4, MOB:WP5, MOB:WP6, MOB:WP7
  - files: `tests/*`
  - done when: All exit-gate items pass: real-tailnet 60 MB cellular upload, dedupe no-op, revoked/other-login 401, Funnel header 403, lockdown zero sockets, hostile playlist 422, rejected 150 MB clean failure, 48 h soak with flat memory, Mac meeting plus phone note correctly processed

### Positioning and launch: `LAUNCH:*`  ([design doc](docs/planning/pmf-and-launch.md), 85.5 agent-days)

The document picks proposal 2's hero. Cora is for people with many hard conversations (engineering managers, founders, product leads on Mac). The headline is "Rehearse your next hard conversation, from real meetings", where an AI plays the other person and every persona line links back to the transcript segment it came from. Plugins are the "how", described as "files you can read, edit and share", with no ecosystem claim at launch. Grafts from the other proposals are folded in: proposal 1's permission scopes, cut list, slip rule and day-90 go/pivot criteria; proposal 3's honesty rules, benchma

- [ ] **LAUNCH:PL-1** Apple Developer enrollment, Developer ID, notarized and stapled DMG pipeline (signs every Mach-O)  _(5d)_
  - files: `.github/workflows/release.yml`, `build/entitlements.mac.plist`, `capture/ (Swift helpers)`, `package.json`, `python/ (bundled .so/.dylib signing)`, `scripts/notarize.js`
  - done when: Stapled DMG and zip pass notarytool and stapler validate; clean macOS 15 and 26 browser-download install reaches first recording; update keeps mic and screen-recording permissions; credentials only in CI secrets or Keychain; logs archived as SOC 2 evidence
- [ ] **LAUNCH:PL-2** Lockdown CI suite covering cloud ASR, notes, plugins, MCP server, updater and any usage ping, plus network-capture red-team (T6)  _(3d)_
  - files: `README.md`, `docs/DATA_FLOW.md`, `python/policy.py`, `tests/test_lockdown_*.py`
  - done when: Socket-blocking CI test fails on any connection under lockdown; a plugin without a network scope cannot connect; network capture shows zero unexplained connections with default settings and with lockdown on; main API authorize() unchanged
- [ ] **LAUNCH:PL-3** Validation tests T1-T8 and R11 voiceprint and consent review, with the Oct 30 hero decision readout  _(6d)_
  - files: `docs/launch/tests-readout.md (outside repo or scratchpad until approved)`, `tools/asr_bench.py`
  - done when: Each test recorded against its pass and kill bar; speakers.py and people matcher confirmed free of stored voiceprints; participant-notice template drafted; owner picks hero A or B by Oct 30
- [ ] **LAUNCH:PL-4** Rehearse plugin (text) with provenance links, coach panel, debrief and before/after metrics  _(6d)_
  - depends on: LAUNCH:PL-5
  - files: `plugins/rehearse/`, `python/api/routes/plugins.py`, `src/ui/web/js/chat-panel.js`
  - done when: End-to-end text rehearsal on seed data; T2 bar met or labelled cloud opt-in showing the exact outbound payload; 'AI simulation' label; persona deleted with person; no voice cloning
- [ ] **LAUNCH:PL-5** Plugin API v0 (declarative tier, scoped permissions, audit log), 3 first-party plugins, quickstart and template repo  _(31d)_
  - files: `docs/PLUGINS.md`, `plugins/`, `python/api/routes/plugins.py`, `python/plugin_registry.py`
  - done when: Manifest frozen Oct 30; default-deny scopes with consent; Rehearse, comm-coach and todo-export plugins work; 10-minute hello-world verified by an outside developer; plugins exposed as MCP tools; lockdown blocks plugin egress
- [ ] **LAUNCH:PL-6** Look-and-feel P0 and UI freeze Nov 12; gallery assets captured on the notarized RC tag  _(15d)_
  - depends on: LAUNCH:PL-1
  - files: `docs/launch/assets/`, `src/main.js`, `src/ui/floater.html`, `src/ui/web/index.html`, `src/ui/web/styles.css`
  - done when: P0 list from look-and-feel draft done; 6 gallery images at 1270x760, 240x240 thumbnail and 45s YouTube video with captions, seed data only; frame audit finds no real names or paths
- [ ] **LAUNCH:PL-7** README rewrite, website, privacy policy, terms, FAQ, CONTRIBUTING and good-first-plugin issues, license and model notices  _(4d)_
  - depends on: LAUNCH:PL-2
  - files: `CONTRIBUTING.md`, `README.md`, `SECURITY.md`, `docs/`
  - done when: README has GIF, DMG link, data-flow table and plugin quickstart; legal review of policy, terms and consent notice done; Tara and bundled-model licences confirmed; no HIPAA, DoD or SOC 2 claims
- [ ] **LAUNCH:PL-8** Repo and artifact hygiene: secret and PII scan, build from clean public-lineage tag, exclude data dirs from DMG files list  _(1.5d)_
  - files: `.gitignore`, `package.json`, `tools/seed_demo_data.py`
  - done when: Scan of tag and DMG contents finds no transcripts, recordings, people, db, config or recording files; release built from a clean tag, not the production working tree
- [ ] **LAUNCH:PL-9** PH draft listing, Show HN and community drafts, pre-launch community building, beta and interview recruiting (founder-led, agents draft)  _(6d)_
  - depends on: LAUNCH:PL-3
  - files: `docs/launch/ph-listing.md`, `docs/launch/show-hn.md`, `docs/launch/social.md`
  - done when: PH listing scheduled by Nov 6 with all fields filled; first comment and FAQ answers ready; no vote-asking language anywhere; 20-50 beta users and 15 interview candidates recruited
- [ ] **LAUNCH:PL-10** Launch execution and post-launch: runbooks, launch days, claim PH page and badge, changelog, post-mortem, slip plan on standby  _(8d)_
  - depends on: LAUNCH:PL-1, LAUNCH:PL-2, LAUNCH:PL-4, LAUNCH:PL-5, LAUNCH:PL-6, LAUNCH:PL-7, LAUNCH:PL-8, LAUNCH:PL-9
  - files: `CHANGELOG.md`, `docs/launch/runbook.md`
  - done when: Show HN posted Nov 17, PH live Nov 19 12:01am PT, every comment answered by the founder, post-mortem with numbers published by Nov 27; if a never-cut gate fails on Nov 6 or Nov 13, launch moves to Dec 1/3

## Merge-conflict hot files (touched by more than one track)

| file | tracks |
|---|---|
| `python/api/routes/recordings.py` | MOB, SDK, TPL, TX, UI |
| `src/ui/web/index.html` | LAUNCH, SDK, TPL, TX, UI |
| `src/ui/web/styles.css` | LAUNCH, SDK, TPL, TX, UI |
| `python/db.py` | MOB, SDK, TPL, UI |
| `src/ui/web/js/detail.js` | SDK, TPL, TX, UI |
| `src/ui/web/js/settings.js` | SDK, TPL, TX, UI |
| `python/api/routes/settings.py` | SDK, TPL, TX |
| `python/mcp_server.py` | SDK, TPL, UI |
| `python/policy.py` | LAUNCH, MOB, SDK |
| `src/main.js` | LAUNCH, SDK, UI |
| `python/api/routes/__init__.py` | MOB, SDK, TPL |
| `python/credentials.py` | SDK, TPL, TX |
| `python/pipeline/runner.py` | SDK, TPL, TX |
| `python/api/views.py` | SDK, TPL, UI |
| `src/ui/web/js/detail-actions.js` | TPL, TX, UI |
| `python/api/routes/plugins.py` | LAUNCH, SDK |
| `python/plugin_registry.py` | LAUNCH, SDK |
| `python/server.py` | MOB, SDK |
| `scripts/lint-ui.js` | SDK, UI |
| `src/ui/web/js/core.js` | SDK, UI |
| `src/ui/web/js/notepad.js` | SDK, UI |
| `src/ui/web/js/search.js` | SDK, UI |
| `python/pipeline/notes.py` | SDK, TPL |
| `python/pipeline/cloud_asr.py` | MOB, TX |
| `.gitignore` | LAUNCH, TX |

## Suggested parallel waves (starting point; review before launching agents)

Computed greedily: within a wave, packages have no unmet in-track dependency and touch disjoint files. It does not know cross-track dependencies or priorities, so reorder using the status list above.

**Wave 1** (51.0d): LAUNCH:PL-1, LAUNCH:PL-2, LAUNCH:PL-3, LAUNCH:PL-5, MOB:WP0, TPL:WP0, TX:T-G0, TX:T-G2, UI:LF-11

**Wave 2** (37.0d): LAUNCH:PL-4, LAUNCH:PL-6, LAUNCH:PL-7, LAUNCH:PL-8, LAUNCH:PL-9, MOB:WP1, TPL:WP1, TX:T-G3

**Wave 3** (19.2d): LAUNCH:PL-10, MOB:WP2, SDK:WP-0, TPL:WP2, TX:P-1-P-5, TX:T-G5, UI:LF-0

**Wave 4** (11.2d): MOB:WP3, SDK:WP-1, TPL:WP3, TX:T-G1, UI:LF-1, UI:LF-12

**Wave 5** (11.0d): MOB:WP4, SDK:WP-2, SDK:WP-3, TPL:WP8, UI:LF-3

**Wave 6** (10.0d): MOB:WP5, SDK:WP-5, SDK:WP-9, TX:T-G4, UI:LF-10, UI:LF-16

**Wave 7** (6.2d): MOB:WP6, SDK:WP-4, TX:T-G6, TX:T-G7

**Wave 8** (5.2d): MOB:WP7, SDK:WP-6, SDK:WP-8, UI:LF-2

**Wave 9** (6.8d): MOB:WP8, SDK:WP-7, TPL:WP4, UI:LF-4

**Wave 10** (2.2d): TPL:WP5, UI:LF-5

**Wave 11** (2.0d): TPL:WP6

**Wave 12** (1.0d): TPL:WP7

**Wave 13** (2.0d): UI:LF-6

**Wave 14** (1.2d): UI:LF-7a

**Wave 15** (1.5d): UI:LF-8

**Wave 16** (4.5d): UI:LF-14, UI:LF-A11Y

## Reference

- Research (code maps, competitor/PMF/Product Hunt findings): [docs/planning/research/](docs/planning/research/)
- Rejected/alternative designs: [docs/planning/alternatives/](docs/planning/alternatives/)
- Positioning, dated launch plan and PH listing draft: [docs/planning/pmf-and-launch.md](docs/planning/pmf-and-launch.md)
