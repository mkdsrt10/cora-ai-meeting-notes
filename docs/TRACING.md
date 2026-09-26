# Local AI tracing

Every AI call Cora makes is recorded on your Mac in `traces.db` inside the data directory
(owner-only, `0600`). Nothing is uploaded; Langfuse is a separate opt-in mirror.

## What is recorded

| Kind | Where | Captured |
|---|---|---|
| `transcription` | local pipeline Whisper, voice-memo Whisper | audio fingerprint (size, head/tail SHA-256, duration), initial prompt, decode params, raw output with per-segment `avg_logprob` / `no_speech_prob` / `compression_ratio` / temperature, real-time factor |
| `llm` (local) | enhanced notes (one span per section and merge), summary variants, speaker naming | prompt, instruction, output, prompt/generation tokens, prompt & generation tokens/s, peak Metal memory, finish reason |
| `llm` (cloud) | `call_configured_llm` (Anthropic/OpenAI/custom/Gemini) and every Gemini `generate_content` call | request, response text, provider-reported token usage, latency |
| `ocr` | screenshot OCR (Apple Vision) | image fingerprint, text |

Spans are grouped into **runs** (one pipeline execution over one recording). Each run stores the
app version, git commit (and whether the tree was dirty), `PIPELINE_VERSION`, hardware (chip, RAM,
macOS) and the model-affecting settings. Each span stores the model id plus the exact weights
revision (Hugging Face snapshot commit, or a fingerprint of a local checkpoint) and a hash of the
prompt template — so a change in quality or speed can be traced to the model, prompt, code or
machine that caused it.

Audio and image bytes are never stored — only fingerprints that point back at the recording's
own files.

**Human corrections** made in the transcript editor (who spoke a turn, fixed wording) are logged to
a `corrections` table with the turn's timestamps — the best retraining labels there are.

## Using it

```bash
python tools/traces.py stats --days 30          # benchmark table per model / weights / prompt version
python tools/traces.py runs                     # recent pipeline runs with versions
python tools/traces.py show <run-id-prefix>     # every call in one run
python tools/traces.py export llm.jsonl --kind llm --name 'enhanced_notes.%'
python tools/traces.py export fixes.jsonl --corrections
```

Exports contain meeting content: keep them as private as the recordings.

## Configuration (`config.json`)

```json
"local_tracing": {"enabled": true, "store_payloads": true, "retention_days": 180}
```

- `store_payloads: false` keeps only metrics and versions (no prompts, transcripts or outputs).
- Traces for a recording can be removed with `ai_trace.purge_recording(id)`.
- Bump `PIPELINE_VERSION` in `python/ai_trace.py` whenever pipeline structure changes.
