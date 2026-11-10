# Transcription engines

Cora transcribes on your Mac by default (MLX Whisper, e.g. Tara). For Hindi-English meetings where you want
the best accuracy, you can switch one setting to use Google Gemini instead.

## Using Gemini

1. **Settings > Where models run > Gemini**: add an AI Studio API key, or use Google Cloud (Vertex AI).
   Use a **paid / billing-enabled** key or Vertex: on the AI Studio free tier Google may use your audio
   to improve its products.
2. **Settings > On-Device Models > Transcription engine**: choose *Google Gemini*.
3. Record as usual. Re-run an old meeting with **Retranscribe & Re-summarize**.

Each recording's privacy note says which engine transcribed it ("Speech audio was sent to Google Gemini
for transcription..." or "No audio or text left this device"). Notes are still written by the local model
unless you chose a cloud notes provider.

## What is sent

Only speech, as lossless FLAC, in windows of about four minutes (silence is skipped), plus the meeting
title, attendee names, your name, and a glossary of names/terms from this meeting's notes, screenshots and
vocabulary. That is about 15-17 requests per hour of meeting. Audio is about 32 tokens per second, so roughly
115k input tokens per hour; check Google's current pricing for the model you picked.

Nothing is sent when `enterprise_lockdown` is on: the engine is forced back to local, whatever Settings says.

## How it works

`pipeline/windows.py` cuts the speech into windows at the longest pauses. `pipeline/gemini_asr.py` asks the
model for structured turns (`start`, `end`, `text` relative to the window) with no speaker labels; speaker
attribution is unchanged (Accessibility timeline, then mic/system loudness). `pipeline/asr_validate.py` rejects
answers that drop speech, run away, echo the prompt or have broken timestamps, and snaps times to the local
speech detector. A rejected window is retried, then split at a balanced pause or at the midpoint for continuous speech. Up to two levels of smaller-clip retries are allowed (at most 21 requests per original window); if it still fails the
transcription **fails with an error** (the previous transcript is kept). It never silently falls back to
another engine.

The speech detector (`pipeline/audio.py` `find_speech_segments`, shared by local Whisper chunking and cloud
windows) works relative to each recording's own noise floor: the 10th percentile of RMS over 100 ms frames of
the audio it is given. Speech is anything at least 10 dB above that floor; the strict detector used for the
coverage check needs 18 dB. A measured floor above -45 dBFS is clamped to -45 before the margin is added:
such a recording has no quiet frames (speech end to end), so its "floor" is speech and would otherwise cut out
the quieter half of it. Neither threshold ever goes above -20 dBFS. Both overrides are optional and absent from config.example.json: setting
`silence_threshold_db` (main) or `strict_silence_threshold_db` (strict) in config.json, e.g. `"-45dB"`, pins a
fixed threshold instead. An empty string counts as unset, and so does `"-50dB"` for `silence_threshold_db`:
older builds copied that value from the example into every data dir, so it is ignored (with a log line) to let
existing installs use the relative detector. Pin a different value, e.g. `"-51dB"`, to keep a fixed threshold.

The model defaults to your configured Gemini model; set the `cloud_asr_model` setting to pin one.

## Not for regulated data yet

This is the dogfooding version. Before a HIPAA or DoD customer enables it, the hardening in
[planning/transcription-gemini.md](planning/transcription-gemini.md) (`TX:T-G1`) has to land: a Vertex-only
client with a pinned region, audited consent, and a lockdown guard on every call site. Until then keep those
meetings on *On this Mac*.

## Compare engines on your own meetings

`python tools/asr_bench.py` scores engines against a corrected transcript; see
[ASR_BENCHMARK.md](ASR_BENCHMARK.md).
