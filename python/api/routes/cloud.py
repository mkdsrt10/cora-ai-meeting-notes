"""Developer feature: training-dataset stats and export (used by tools/curate_training_data.py)."""
from __future__ import annotations
import json
import time

from api.router import route
import db
import paths


@route("GET", '/api/dataset/stats')
def get_api_dataset_stats(req, path: str, query: dict) -> None:
    return req.send_json({
        "total_pairs": db.get_training_pairs_count(),
        "datasets": ["whisper-hinglish-v2", "cora-dpo-flywheel-v1"],
    })


@route("POST", '/api/dataset/export')
def post_api_dataset_export(req, path: str, body: dict) -> None:
    dataset_name = str(body.get("dataset_name", "whisper-hinglish-v2")).strip()
    pairs = db.get_all_training_pairs(dataset_name)
    export_path = paths.LOGS_DIR / f"dataset_{dataset_name}_{int(time.time())}.jsonl"
    with export_path.open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    return req.send_json({
        "ok": True,
        "count": len(pairs),
        "file_path": str(export_path),
    })
