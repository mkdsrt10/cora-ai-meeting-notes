"""To-dos: a View over core Action items (python/action_items.py, ADR 0004).

The store that used to live here (todo_items) moved to core; its rows migrate
once, keeping ids and done marks. This module keeps the names the plugin's
routes use.
"""
from __future__ import annotations

from typing import Any

import action_items
import db

sync = action_items.sync
find = action_items.find
set_done = action_items.set_done
backfill = action_items.backfill
eligible = action_items.eligible


def listed() -> list[dict[str, Any]]:
    """Current To-dos of processed Recordings, in Recording order then each
    Recording's Action item order."""
    items = action_items.current()
    recordings = {r["id"]: r for r in db.get_all_recordings() if eligible(r)}
    order = {rid: i for i, rid in enumerate(recordings)}
    result = []
    for item in items:
        rec = recordings.get(item["recording_id"])
        if rec is None:
            continue
        result.append({
            "id": item["id"],
            "recording_id": item["recording_id"],
            "recording_title": rec.get("title") or rec["id"],
            "recorded_at": rec.get("recorded_at"),
            "index": item["position"],
            "text": item["text"],
            "owner": item["owner"],
            "due": item["due"],
            "done": item["done"],
            "done_at": item["done_at"],
        })
    result.sort(key=lambda item: (order[item["recording_id"]], item["index"]))
    return result
