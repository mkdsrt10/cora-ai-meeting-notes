# Research notes: why local meeting intelligence breaks, and what fixes it

This is a write-up of empirical findings from building Cora — diagnosing *why* running
transcription and note-taking entirely on a 16 GB Apple Silicon Mac kept failing, and what
actually fixed it. It's distilled from build logs and benchmarks run against real meeting
recordings on the author's own machines, evaluated with an LLM-as-judge pattern (a larger
cloud model grading transcripts and notes against the recording). These are internal,
self-reported numbers from one team's usage — not a third-party audited benchmark — so treat
the figures as directional evidence, not a certified result. All example quotes below are
synthetic, written to illustrate the linguistic pattern being described, not transcript excerpts.

See the main [README](../README.md#why-this-exists) for the project's broader thesis. This doc
is the technical detail behind one claim in it: that the ceiling on local models is usually the
software around them, not the models themselves.

## Central finding

Small on-device models (4B parameters and under) don't fail on real meetings because they lack
capacity. They fail because the surrounding pipeline routinely breaks four assumptions that
hold for typical NLP benchmarks but not for spoken, multi-track, code-mixed conversation:

1. **Multi-track audio gets silently collapsed to one channel** before the model ever hears it.
2. **Shallow ASR decoders loop on silence** rather than staying quiet.
3. **English-centric extraction misses commitments spoken in a pro-drop language** (Hindi verb
   inflections encode the subject; the pronoun is often just not there).
4. **A long-lived process leaks GPU memory** until the machine starts swapping.

Below is each finding, how it was diagnosed, the fix, and — since this repo is the actual
pipeline these findings feed — whether it's shipped in Cora today or still a research direction.

## 1. The multi-track audio drop

**Symptom:** long stretches of a transcript degenerating into a repeated word or phrase —
hundreds of instances of `"the the the..."` or a single word repeated across dozens of segments
with inverted timestamps.

**Diagnosis:** Cora's capture writes the microphone and system audio (the other participants) as
two separate streams in one container. Every `ffmpeg` command used for silence detection and
clipping picked a single stream by default when called without an explicit `-map`. Whenever the
*other side* of the call was talking, the local microphone was picking up near-silence — so the
pipeline handed Whisper long stretches of dead air on exactly the turns where someone else was
speaking, and a shallow decoder loops on dead air (see the next finding).

**Fix:** mix both tracks (`[0:a:0][0:a:1]amix=inputs=2:duration=longest`) before any silence
detection or clipping happens, not after.

**Shipped in Cora:** yes — [`pipeline/audio.py:ensure_mixed_audio`](../python/pipeline/audio.py).

## 2. The shallow-decoder silence trap

**Symptom:** Whisper models with a 4-layer decoder (e.g. `whisper-large-v3-turbo`, built for
speed) occasionally lock into repeating a single token or short phrase for the rest of a segment.

**Diagnosis:** on low-signal audio (room hum, a thinking pause), the acoustic encoder gives the
decoder almost no gradient to work with. Under greedy decoding, if the decoder emits a
high-prior filler token, self-attention conditions on that token in the next step — and with
only 4 layers, cross-attention isn't deep enough to override that self-reinforcing loop. It
settles into token → same token → same token until the max sequence length.

The standard fix in the literature — a temperature fallback ladder (retry at 0.2, 0.4, 0.6...) —
makes it *worse* past a point. At temperature ≥ 0.6, the decoder samples from the vocabulary's
long tail: non-repeating, high-entropy nonsense ("Flexarb 91ksi jalizon..."). Because it doesn't
repeat, it passes Whisper's own repetition safeguard (a gzip-compression-ratio check), so the
hallucination gets accepted as valid speech and inserted into the transcript.

A deeper decoder doesn't have this problem: a full 32-layer `whisper-large-v3` (we used
[Trelis Tara](https://huggingface.co/Trelis/tara), a 32-layer Hindi-English fine-tune) held
acoustic grounding through the same low-volume audio with zero loops, at roughly 6x the word
accuracy of the 4-layer model on the same clip. A transducer architecture (NeMo FastConformer)
sidesteps the problem differently — it can emit a blank symbol instead of a token, so it's not
structurally capable of this kind of loop at all.

**Fix:** cap the temperature ladder low (`0.0, 0.2, 0.4` — never let it reach the word-salad
range), tune `compression_ratio_threshold` / `no_speech_threshold` explicitly rather than
trusting library defaults, and add a deterministic regex backstop that collapses any residual
repeated word/phrase down to one occurrence.

**Shipped in Cora:** yes — the decode parameters and
[`pipeline/transcribe.py:collapse_repetition_loops`](../python/pipeline/transcribe.py). The
32-layer alternative is a one-click downloadable option in Settings
([`mayank-dubey-ai/tara-mlx`](https://huggingface.co/mayank-dubey-ai/tara-mlx), an MLX conversion
of Trelis Tara) rather than the bundled default, since it's a much larger download.

## 3. The pro-drop gap in code-mixed speech

**Symptom:** on Hinglish (English-Hindi code-mixed) meetings, action-item extraction that looked
for the standard English pattern — an explicit subject pronoun plus a modal ("I will...", "I'll
need to...") — recalled as few as 1 in 10 real commitments.

**Diagnosis:** English requires an explicit subject. Hindi doesn't — it's a
[pro-drop language](https://en.wikipedia.org/wiki/Pro-drop_language): person, tense and gender
are encoded in the verb's own inflection, so the pronoun is routinely omitted entirely.
*"Bhej dungi"* ("[I] will send it," feminine), *"kar dunga"* ("[I] will do it," masculine),
*"dekh leta hun"* ("let me take a look"), *"baat karni padegi"* ("[I'll] need to talk to...") —
none of these have a surface subject for an English-pattern extractor to anchor on. A speaker
saying, for example, *"iske alawa mujhe ek baar Rahul se baat karni padegi"* ("besides that,
I'll need to talk to Rahul about this once") gets read as passing conversation rather than a
commitment, because there's no "I will" to match.

**Fix:** a deterministic pre-filter that recognizes freestanding pro-drop verb inflections
(`bhej dungi`, `kar dunga`, `dekh leta`, `baat karni padegi`, and their variants) alongside the
English promissory patterns, before handing the model a much smaller, denser slice of the
transcript to extract from.

**Shipped in Cora:** yes —
[`pipeline/notes.py:_mine_commitment_turns`](../python/pipeline/notes.py) and its
`_COMMITMENT_PATTERN` regex.

## 4. Metal memory retention in a long-lived process

**Symptom:** a Mac running Cora's local pipeline continuously across several meetings became
sluggish, with the Python process's resident memory climbing past 10 GB and the system starting
to swap — generation throughput dropping by an order of magnitude once that happened.

**Diagnosis:** on Apple Silicon, `mlx`'s Metal backend caches GPU buffer allocations for reuse.
That's the right default for a short-lived script, but in a persistent server process, standard
Python garbage collection (`del model; gc.collect()`) drops the Python object, not the
underlying Metal allocation — so every meeting processed added its model's buffers on top of the
last, unbounded, for as long as the process stayed alive.

**Fix:** an explicit teardown after generation — `gc.collect()` **and** `mx.clear_cache()`
— returning the Metal buffer pool to the OS rather than assuming reuse. Measured across
recordings from under 2 minutes to 105 minutes, peak resident memory stayed in a roughly
4.8–6.8 GB band with no swap, regardless of how many meetings had already run in that process.

**Shipped in Cora:** yes — [`pipeline/config.py`](../python/pipeline/config.py) (`_cap_mlx_memory`,
`_release_mlx_model`), applied after every local-LLM call.

## Local model shootout (notes quality vs. size)

Eight open-weight local models were run through note extraction on the same real meetings, each
graded by an LLM judge on decision recall, action-item recall and owner-attribution accuracy:

| Model | Params | RAM (4-bit) | Grade | Characteristic failure |
|---|---|---|---|---|
| LiquidAI LFM-1.2B | 1.2B | 0.7 GB | F (5/100) | Attention collapse — zero action items, leaked its own system prompt, repeated a single keyword 8 times in a row |
| LiquidAI LFM-2.6B | 2.6B | 1.5 GB | D (45/100) | Better syntax, still drops debate reversals and complex owner assignments |
| Microsoft Phi-4-mini | 3.8B | 2.4 GB | F (25/100) | Format regression without an explicit chat-template wrapper |
| Qwen2.5-Coder-7B | 7.0B | 4.8 GB | F (24/100) | Fails without ChatML formatting; larger footprint risks swap on 16 GB |
| Qwen3-8B | 8.0B | 5.5 GB | D (52/100) | Reasoning tokens eat the output budget, truncating structured output |
| **Qwen3-4B-Instruct** | 4.0B | 2.1 GB | **B+ (87/100)** | Sweet spot — 100% decision recall, 90% owner accuracy, when paired with the decoupled extraction approach below |
| Qwen3-Coder-Next (80B MoE, reference only) | 80B (3B active) | ~45 GB | B (85/100) | Frontier baseline; not practical on a consumer Mac |

**The 4B inflection point:** below roughly 3.5B parameters, small models don't just get less
accurate — they qualitatively break (empty outputs, system-prompt leakage, degenerate keyword
repetition). At 4B, with the right extraction architecture, quality jumps to matching an 80B
model on this task. That's the parameter range Cora already defaults to
(`Qwen3-4B-Instruct-2507-4bit`).

**The extraction architecture matters as much as the model.** A single monolithic prompt over a
whole transcript, or the "many small sequential chunk calls merged together" pattern, both
under-perform a **decoupled** pipeline: separate, narrow passes for decisions, for reversals
(catching when an earlier decision gets explicitly superseded later in the same meeting), and
for commitment-mining (finding #3 above) feeding a focused action-item pass — each pass getting
only the slice of the transcript it actually needs, rather than the whole thing. In our
benchmark this cut wall-clock notes generation from several minutes to under 10 seconds and
roughly 6x'd the overall grade on the same recording and model.

**Status in Cora:** partially shipped. Cora's current
[`pipeline/notes.py:generate_enhanced_notes`](../python/pipeline/notes.py) already runs narrow,
single-purpose calls per section (not one giant structured-JSON ask) and applies the pro-drop
commitment miner from finding #3 as a pre-filter. It doesn't yet have the fully decoupled
reversal-tracking pass described above — that's an open direction, not yet merged.

## The preference-alignment flywheel (early, not shipped)

To let a local model improve without hand-tuning prompts, we've been running an automated
[DPO](https://arxiv.org/abs/2305.18290) data pipeline: for each meeting, generate two candidate
outputs (a naive baseline and the decoupled pipeline above), have a larger model grade both, and
export the (chosen, rejected) pair for fine-tuning. This is still a research pipeline running
against private data — none of the resulting training data is public — but the resulting model
weights are: a Hinglish-tuned Whisper fine-tune is public on Hugging Face at
[`mayank-dubey-ai/whisper-large-v3-turbo-hinglish`](https://huggingface.co/mayank-dubey-ai/whisper-large-v3-turbo-hinglish)
(and an [MLX build](https://huggingface.co/mayank-dubey-ai/whisper-large-v3-turbo-hinglish-mlx)
for Apple Silicon).

## Local vs. Gemini on a week of real calls (November 2026)

An accidental A/B: from 2026-10-20 to 2026-11-01 the app ran from source with Gemini for both
transcription and notes; from 2026-11-02 to 2026-11-05 the installed 0.2.1 bundle (built
2026-10-05) ran instead, fully local. Same Mac, same user, same kinds of meetings. The pipeline
traces (`traces.db`) and the per-run resource log name the engine for every recording, so the
two weeks can be compared, and five of the local-week recordings were then rerun through Gemini
on the same audio for a paired comparison.

**Where things are.**

| Item | Location |
|---|---|
| Original recordings (both weeks) | `~/Library/Application Support/Cora AI Meeting Notes/recordings/` |
| Gemini reruns of 5 local-week meetings (audio copies deleted, traces kept) | `~/Library/Application Support/Cora AI Meeting Notes/research/gemini-rerun-2026-11-06/` |
| Engine per run | `traces.db` tables `runs` (app_version, git_commit) and `spans` (provider, model, tokens) |
| Stage timings, CPU, peak memory per recording | `logs/local_pipeline_resource_usage.jsonl` |
| Paired comparison tool (counts only, prints no transcript text) | [`tools/compare_engine_reruns.py`](../tools/compare_engine_reruns.py) `<rerun-data-dir>` |

**Models.** Gemini week: transcription `gemini-3.7-flash` in ~4-minute windows (1152 calls over
the week), notes `gemini-3.8-flash`, template selection, speaker naming and romanization also on
Gemini. Local week: transcription `mayank-dubey-ai/tara-mlx` (MLX Whisper), notes
`mlx-community/Qwen3-4B-Instruct-2507-4bit`, romanization and speaker naming on the same Qwen.
The local week ran the 2026-10-05 notes code (no templates, 1600-token section budget); the
rerun used the current code with the stored Gemini preference.

**Week-level numbers** (recordings over 2 minutes; medians):

| | Gemini week (n=46) | Local week (n=22–28) |
|---|---|---|
| Transcription wall-clock, as a fraction of audio length | 0.064 | 0.068 |
| Notes generation, seconds per audio minute | 1.7 | 1.0 |
| Peak process memory | 412 MB | 5.0 GB |
| Transcript density, words per audio minute | 162 | 124 |
| Notes length, characters per audio minute | 170 | 607 |
| Bullets per audio minute / words per bullet | 1.55 / 12 | 3.49 / 23 |
| Median bullets: actions / discussion / timeline / open questions | 3 / 3 / 5 / 2 | 5 / 15 / 10 / 10 |
| Gemini tokens for the week | transcription 4.9M in, 0.85M out; notes 0.47M in, 45k out | — |

Windowed Gemini transcription is not faster in wall-clock than local Whisper on this Mac: each
window is a ~10 s network round trip and windows run sequentially, so both land near 0.065x
real time. What Gemini buys is memory (the local path peaks at 5 GB) and density.

**Paired rerun, same audio** (local original vs. Gemini rerun):

| Meeting length | Words, local → Gemini | Segments | Speaker turns | Notes chars | Decisions | Open questions |
|---|---|---|---|---|---|---|
| 3.7 min | 582 → 802 | 9 → 42 | 1 → 23 | 5.7k → 1.6k | 8 → 3 | 6 → 0 |
| 12.5 min | 1602 → 1651 | 29 → 54 | 9 → 22 | 9.4k → 2.1k | 18 → 3 | 16 → 0 |
| 20.8 min | 2602 → 2962 | 47 → 139 | 19 → 55 | 7.2k → 2.5k | 16 → 3 | 1 → 2 |
| 24.6 min | 3897 → 4700 | 63 → 270 | 22 → 127 | 15.8k → 2.6k | 22 → 2 | 36 → 2 |
| 58.9 min | — | — | — | — | — | — (Gemini run failed, see below) |

Findings:

1. **Local Whisper under-transcribes by 3–38% of words** on the same audio, and the gap grows
   with crosstalk. Its segments average 23–25 s against Gemini's 5–6 s, so turn-taking is
   flattened: 1 speaker turn where Gemini finds 23. Both transcripts are Romanized Hinglish, but
   the local romanizer spells differently ("kareke", "abhee"), so a naive word diff between the
   two reads 57–85% and is not a WER. A true WER needs a corrected reference
   (`tools/asr_bench.py`); that is the next measurement to run.
2. **The local notes are 3–6x longer and the extra length is inventory, not insight.** Qwen3-4B
   with a 1600-token budget per section fills it: 16–22 "decisions" and up to 36 "open
   questions" for a 25-minute call where Gemini returns 2–3 of each. Bullets are twice as long.
   This is the "summaries got very long" complaint, and it is a prompt-budget and model-size
   effect, not a transcript effect: the rerun on the same audio with Gemini produced 2.1–2.6k
   character notes every time. The earlier shootout grade (B+ for Qwen3-4B) was on decision and
   action recall, which a long list also scores well on; precision was not graded. It should be.
3. **Templates only exist on the current code.** Gemini runs select a template (technical
   review, standup) before extraction; the 0.2.1 build had none, which is a second reason its
   notes read as undifferentiated lists.
4. **Gemini can refuse a window and the whole meeting fails.** On the 59-minute meeting the last
   window (3240–3534 s) came back empty with `BlockedReason.OTHER` through 3 retries and 2
   splits, so the pipeline raised `WindowedASRError` and the recording was reported as an
   internal, retryable failure. Local transcription has no such mode. The windowed engine needs a
   per-window fallback to local Whisper (or to skip the window with a marker) rather than failing
   the recording, and a blocked window must be classified as permanent, not retryable.
5. **The Accessibility speaker timeline was empty in both weeks.** 0 of 61 recordings had a
   non-empty `speakers_timeline.json` or `participants.json`, even though the watcher log
   recorded speaker changes. Diarization therefore came from the two-track mic/system audio
   alone, and remote participants were named only when Gemini diarization ran (7 of 54 Gemini
   week recordings, 4 of 25 local week). This is independent of engine and is the biggest open
   quality gap on the diarization side.

**Judge-graded accuracy (the four paired meetings).** An LLM judge read both transcripts of
each meeting, wrote its own strict reference list of real decisions, action items and open
questions, then graded every item each engine produced as supported, distorted, fabricated or
duplicate, and scored recall against its reference. Reference totals across the four meetings:
14 decisions, 17 action items, 5 open questions.

| | Local (tara-mlx + Qwen3-4B, 0.2.1 code) | Gemini (3.7-flash ASR + 3.8-flash notes) |
|---|---|---|
| Decisions produced / supported → precision | 64 / 20 → **31%** | 11 / 11 → **100%** |
| Decisions recall | 10 of 14 → 71% | 7 of 14 → 50% |
| Action items produced / supported → precision | 30 / 7 → **23%** | 11 / 9 → **82%** |
| Action items recall | 10 of 17 → 59% | 11 of 17 → 65% |
| Action-item owner given and correct | 0 of 30 (no owners at all) | 9 of 11 (1 flipped by diarization) |
| Open questions produced / supported → precision | 59 / 2 → **3%** (32 duplicates) | 4 / 4 → 100% |
| Open questions recall | 2 of 5 | 4 of 5 |
| Fabricated items (not in either transcript) | 3 | 0 |
| Overview accuracy / usefulness (1–5, mean) | 2.3 / 2.3 | 4.8 / 4.0 |
| Transcript stretches clearly missing (judge count, all meetings) | 15 | 6 |
| More coherent transcript | — | 4 of 4 |

How to read it: the local stack's recall is respectable (it mentions most real decisions
somewhere in its long list), but two of every three "decisions" and three of every four "action
items" it prints are distorted, inverted or restated, no action item has an owner, and the
open-questions section is noise. Characteristic local failures, consistent across all four
judges: topics and process descriptions relabelled as decisions; the direction of a design
choice inverted; status items and illustrative examples turned into action items; misheard
tokens becoming wrong dates and numbers; the same open-question text looped dozens of times.
Most of this traces to the transcript: the judges counted 15 stretches absent from the local
transcript against 6 from Gemini, and the local diarizer collapsed nearly every turn onto one
speaker, which is why the 4B model cannot assign owners.

Gemini is precise and conservative, and under-generates: it tends to list a tentatively agreed
item as a proposal and to drop a minor hand-off. Its one bad meeting (B) was a transcript
failure, not a notes failure: the windowed engine dropped the stretch where the commitments were
made, so decision recall there was 0 of 4. Windowed Gemini transcription can lose stretches too,
and when it does the notes are silently incomplete.

**Takeaways for the local tier.** Keep Qwen3-4B as the notes model, but cap the per-section
budget (the Gemini run's 2–3 items per section is the right shape), add the template step to the
local path, and grade precision in the next shootout. For transcription, the density gap means
the local tier needs either the larger Tara checkpoint with silence-aware chunking tuned for
crosstalk, or a reference-scored WER before it is offered as the default to anyone.

## Known limitations

- **Cold start:** loading weights from disk into unified memory takes roughly 18–25 seconds on
  first use in a session; a cloud API has no equivalent cost, since it never unloads.
- **Co-located overlap:** the Accessibility-tree active-speaker signal Cora uses works well for
  separate video tiles in a call, but can't separate two people speaking into the same physical
  microphone at once.
- **Script mismatch:** a model trained on Romanized Hinglish outputs Latin-script transcripts
  even for Hindi speech; comparing that against Devanagari reference text produces artificial
  character-level mismatches unless a transliteration layer sits in between. (Cora's own
  `transcript_script` setting and [`pipeline/romanize.py`](../python/pipeline/romanize.py)
  address this for the app's own transcripts.)

## The conceptual claim

None of the four fixes above required a bigger model. Each one was a place where the pipeline
was quietly discarding information the model needed — a dropped audio channel, a decoder given
no way to signal "I don't know," an English assumption baked into a regex, a memory allocator
assuming a short-lived process. Fix the interface, and a 4B model running on a laptop's own GPU
does the job a cloud model would otherwise be rented for.
