"""Opt-in cloud/dev features: VM sync, dataset export, legacy analysis endpoints."""
from __future__ import annotations
import json
import time

from api.router import route
import db
import json
import paths
import time


@route("GET", '/api/cloud/sync-status')
def get_api_cloud_sync_status(req, path: str, query: dict) -> None:
    import vm_sync
    return req.send_json({**vm_sync.get_sync_status(), "configured": vm_sync.configured_target() is not None})


@route("GET", '/api/dataset/stats')
def get_api_dataset_stats(req, path: str, query: dict) -> None:
    return req.send_json({
        "total_pairs": db.get_training_pairs_count(),
        "datasets": ["whisper-hinglish-v2", "cora-dpo-flywheel-v1"],
    })


@route("POST", '/api/analyze', '/api/analyze-all', '/api/gemini-analyze', '/api/hermes-session', '/api/hermes-chat', '/api/hermes-weekly')
def post_api_analyze(req, path: str, body: dict) -> None:
    return req.send_json({"error": "Legacy analysis is disabled. Use neural speaker diarization, confirm identity, then run coaching."}, 410)


@route("POST", '/api/cloud/sync-vm')
def post_api_cloud_sync_vm(req, path: str, body: dict) -> None:
    import vm_sync
    res = vm_sync.sync_to_vm(include_audio=body.get("include_audio") is True)
    return req.send_json(res)


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
