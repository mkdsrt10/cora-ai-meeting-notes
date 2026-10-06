# Benchmarking speech-to-text models on your own meetings

Goal: find out whether anything beats Tara on *your* Hinglish meetings, on a
bigger machine (Mac Studio, or a CUDA VM). Public benchmarks cover Hindi, not
code-switching, and none of them tested Tara — so measure it.

Tool: [`tools/asr_bench.py`](../tools/asr_bench.py). Standalone (needs only
ffmpeg + whichever model libraries you use). It prints WER/CER/speed only —
no transcript text — unless you pass `--dump-hyp`.

## 1. Pick the test meeting (on the Mac that recorded it)

Choose a 10–30 min meeting, ideally with heavy Hindi-English switching and
a few names/jargon. Open it in Cora and fix the transcript in the editor so
the text is a trustworthy reference. Use a non-sensitive meeting if the bundle
will leave your Mac (it is real audio of real people).

```bash
python tools/asr_bench.py prepare <recording-id> --out bench-bundle
scp -r bench-bundle  user@vm:~/        # or copy to the Mac Studio
```

## 2. Run the candidates

Smoke-test first (`--limit-seconds 120`), then the full clip. Every model sees
identical ≤25 s chunks, like Cora's pipeline.

```bash
# Baseline: what you run today
python tools/asr_bench.py run bench-bundle --model mlx-whisper:$HOME/tara-mlx            # Mac
python tools/asr_bench.py run bench-bundle --model hf-whisper:Trelis/tara                # VM (CUDA)

# Candidates
--model indic-conformer:ai4bharat/indic-conformer-600m-multilingual   # top of the Hindi benchmark; non-generative
--model "cmd:python qwen_asr.py {wav}"                                # Qwen3-ASR 0.6B / 1.7B (has a community MLX port)
--model "cmd:python voxtral.py {wav}"                                 # Voxtral Mini 3B / Small 24B (Apache 2.0)
--model hf-whisper:openai/whisper-large-v3                            # un-tuned reference point
--model gemini:<model-id>                                             # hosted baseline (needs Cora's Google creds)
```

For models without a built-in backend, write a ~10-line script that takes a wav
path and prints the transcript, and use `cmd:`.

## 3. Read the result

| Look at | Why |
|---|---|
| **WER** | Overall accuracy vs your corrected reference. A 1–2 point gap is noise on one meeting; run 2–3 meetings. |
| **CER** | Less sensitive to Hinglish spelling variants (`kyunki` vs `kyonki`). Trust it when WER and CER disagree. |
| **words out** vs reference | Far more words than the reference = hallucination/looping; far fewer = dropped speech. |
| **x realtime** | Whether the model is usable for 60–90 min meetings on that hardware. |

Also open `--dump-hyp` output for the winner and spot-check names, numbers, and
code-switch points — WER doesn't capture whether *Rahul* became *Rahool*.

## Already known (from a literature check, not from our audio)

- IndicConformer-600M: 8.2% Hindi WER in the Voice of India benchmark; Whisper wasn't in that benchmark.
- Hosted: Sarvam and Gemini 3 Pro led on Hindi (≈5–6%); OpenAI gpt-4o-transcribe was far behind (≈34%).
- Nothing there measured Hinglish code-switching specifically. That's what this run is for.

If a model wins clearly, send the numbers back and we'll add it as a one-click
option (and convert it to MLX if it's a PyTorch/NeMo model).
