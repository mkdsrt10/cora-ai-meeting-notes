# Architecture

Cora is three cooperating processes on one Mac, with user data in a single private directory.

```mermaid
flowchart LR
  subgraph Electron["Electron app (src/)"]
    M[main.js<br/>tray · windows · capture state machine]
    UI[Dashboard UI<br/>src/ui/web/js/*]
    F[Floater window]
  end
  subgraph Native["Swift helpers (capture/, bin/)"]
    DC[dual-capture<br/>mic + system audio]
    MW[mic-watch<br/>meeting start/stop]
    SW[speaker-watch<br/>active speaker via Accessibility]
    OCR[mac-ocr<br/>Apple Vision]
  end
  subgraph Py["Python (python/)"]
    API[api/<br/>loopback HTTP API]
    PIPE[pipeline/<br/>runner]
    DB[(SQLite + files<br/>data dir)]
    TR[(traces.db)]
  end
  M -- spawn --> DC & MW & SW & OCR
  M -- spawn + token --> API
  UI -- fetch (cookie token) --> API
  F -- IPC (trusted pages only) --> M
  API --> DB
  API -- process-recording --> PIPE
  PIPE --> DB
  PIPE --> TR
  MCP[mcp_server.py<br/>stdio, read-only] --> DB
```

## Recording → notes

1. **Capture.** `mic-watch` notices a meeting app using the mic; `main.js` starts `dual-capture`
   (mic and system audio as two tracks in one `.mov`) and `speaker-watch` (who's speaking, from the
   meeting app's Accessibility tree). Screenshots are OCR'd by `mac-ocr`.
2. **Archive** (`voice_memo_pipeline.py`): the recording moves from `inbox/` into
   `recordings/<id>/` — the two-track `audio.mov` plus a mixed `playback.m4a` for the player.
3. **Pipeline** (`pipeline/runner.py`):
   - `audio`: mix tracks for ASR, detect silence;
   - `context` + `transcribe`: pause-bounded chunks, each with a Whisper prompt built from
     attendees, nearby screenshot text, title, notes and vocabulary;
   - `speakers`: Accessibility timeline, then mic-vs-system loudness (you vs. them);
   - `romanize`: Devanagari → Romanized Hinglish (local LLM, validated, rule-based fallback);
   - `speaker_guess`: the local LLM names remote turns, validated against roster and evidence;
   - `notes`: enhanced notes and summaries with a local LLM (or an opt-in cloud model).
4. **Serve.** The UI and MCP read the results; the transcript editor writes corrections back and
   logs them as training data.

## Boundaries worth knowing

- **Security:** the API only answers loopback requests carrying the per-launch token (`api/auth.py`);
  renderers are sandboxed with a strict CSP and only trusted pages may use IPC (`src/main/security.js`).
- **Privacy:** outbound features (cloud LLMs, tracing, VM sync, contribution) are opt-in and all
  pass through `python/policy.py`, which enterprise lockdown turns off entirely.
- **Paths:** `python/paths.py` (and `src/main/paths.js`) decide where code and data live; nothing
  else hardcodes a path.
- **Observability:** every model call goes through `ai_trace.span(...)` — see [TRACING.md](TRACING.md).
