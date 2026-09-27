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
32-layer alternative is supported as an optional `local_whisper_models` entry (see the README's
Configuration section) rather than the bundled default, since it's a much larger download.

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
