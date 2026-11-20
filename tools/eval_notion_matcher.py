#!/usr/bin/env python3
"""Notion matcher eval (spec gate: link precision >= 0.8 on the fixture).

Runs plugins/notion/matcher.py over tests/fixtures/notion_matcher/fixture.json
(fictional Tasks, hand-labelled links). Prints counts only.

    python tools/eval_notion_matcher.py                 # lexical only
    python tools/eval_notion_matcher.py --model local_mlx [--model-name ...]
    python tools/eval_notion_matcher.py --instructions "Chunky tasks" --json

link precision = correct links / links proposed; link recall = correct links /
items that should link; false creates = should-link items proposed as create
(they still offer the right Task under "link instead" when it is among the 3
nearest, counted as rescued).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "python"), str(ROOT)]

FIXTURE = ROOT / "tests" / "fixtures" / "notion_matcher" / "fixture.json"


def run(model=None, instructions: str = "") -> dict:
    from plugins.notion import matcher
    data = json.loads(FIXTURE.read_text())
    tasks = [{**t, "assignee_ids": []} for t in data["tasks"]]
    items = [{"id": f"I{n:02d}", "text": c["text"]} for n, c in enumerate(data["cases"], 1)]
    expect = {f"I{n:02d}": c["expect"] for n, c in enumerate(data["cases"], 1)}
    decisions = matcher.decide(items, tasks, model=model, instructions=instructions)
    links = [d for d in decisions if d.decision == "link"]
    correct = [d for d in links if d.task_id == expect[d.action_item_id]]
    should = [i for i, e in expect.items() if e]
    false_creates = [d for d in decisions if d.decision != "link" and expect[d.action_item_id]]
    rescued = [d for d in false_creates if expect[d.action_item_id] in {t["id"] for t in d.nearest}]
    return {"items": len(items), "should_link": len(should), "links": len(links), "correct_links": len(correct),
            "link_precision": round(len(correct) / len(links), 3) if links else None,
            "link_recall": round(len(correct) / len(should), 3) if should else None,
            "false_creates": len(false_creates), "rescued_by_link_instead": len(rescued),
            "skips": sum(d.decision == "skip" for d in decisions)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", help="Text model provider (e.g. local_mlx, gemini); omit for lexical only")
    ap.add_argument("--model-name", default="")
    ap.add_argument("--instructions", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.model:
        from pipeline.text_model import text_model
        with text_model({"provider": args.model, "model": args.model_name}) as model:
            result = run(model, args.instructions)
        result["model"] = model.model
    else:
        result = run(None, args.instructions)
        result["model"] = "lexical"
    if args.json:
        print(json.dumps(result))
    else:
        for key, value in result.items():
            print(f"{key:>24}: {value}")
        p = result["link_precision"]
        print(f"{'gate (precision>=0.8)':>24}: {'PASS' if p is not None and p >= 0.8 else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
