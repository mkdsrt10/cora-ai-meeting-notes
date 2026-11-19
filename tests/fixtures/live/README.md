Fictional speech for the Live transcript tests (docs/specs/live-transcript.md), made with macOS `say`;
no real meeting audio or text.

- `you.wav`: `say -v Samantha -o you.wav --data-format=LEI16@16000 "Good morning. Let us review the garden plan for the spring festival. The tulips arrive on Tuesday."`
- `them.wav`: `say -v Daniel -o them.wav --data-format=LEI16@16000 "Thanks. I will order seven blue lanterns and check the weather report tomorrow."`
- `hypotheses.jsonl`: scripted engine hypotheses for `live-engine --replay` (half words, a final that disagrees with stable words, a start that goes backwards).
