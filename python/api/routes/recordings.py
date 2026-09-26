"""Recordings: dashboard, detail, notes, titles, folders, (re)processing, transcript edits."""
from __future__ import annotations
import datetime as dt
import json
import re
import time

from api.router import route
from diarization import LATEST_AUDIO_MODEL
from diarization import atomic_json
from diarization import diarize as gemini_diarize
from diarization import speaker_profiles
import datetime as dt
import db
import json
import re
import time
from api.core import ARCHETYPES, RECORDINGS, current_self_name, safe_folder
from api.views import PENDING_TITLES, dashboard_payload, key_phrases_payload, live_transcript_payload, participants_payload, pending_recording_item, recording_item


@route("GET", '/api/recording/summary-formats')
def get_api_recording_summary_formats(req, path: str, query: dict) -> None:
    import local_meeting_pipeline
    return req.send_json({
        "formats": [{"id": key, "label": val["label"]} for key, val in local_meeting_pipeline.SUMMARY_FORMATS.items()],
    })


@route("GET", '/api/folders')
def get_api_folders(req, path: str, query: dict) -> None:
    return req.send_json({"folders": db.get_folders()})


@route("GET", '/api/dashboard')
def get_api_dashboard(req, path: str, query: dict) -> None:
    return req.send_json(dashboard_payload())


@route("GET", '/api/recording')
def get_api_recording(req, path: str, query: dict) -> None:
    rec_id = query.get("id", [""])[0]
    rec_data = db.get_recording(rec_id)
    if not rec_data:
        # rec_id may be a live recording id (main.js's
        # meeting_<timestamp>) whose pending row was already
        # retired once archiving replaced it with a real
        # date-prefixed, hash-suffixed folder id — without this,
        # a client still polling the old id 404s forever with no
        # indication anything changed (see live_recording_id in
        # voice_memo_pipeline.py's archive step).
        fallback = db.get_recording_by_live_id(rec_id)
        if fallback:
            rec_id = fallback["id"]
            rec_data = fallback
    if rec_data and rec_data.get("status") in PENDING_TITLES:
        item = pending_recording_item(rec_data)
        item["notes"] = db.get_notes(rec_id)
        item["available_summary_formats"] = []
        item["live_transcript"] = live_transcript_payload(rec_id)
        item["participants"] = participants_payload(rec_id, None)
        item["key_phrases"] = key_phrases_payload(rec_id)
        return req.send_json(item)
    folder = safe_folder(rec_id)
    detailed_item = recording_item(folder, detailed=True)
    detailed_item["live_transcript"] = live_transcript_payload(rec_id)
    detailed_item["participants"] = participants_payload(rec_id, folder)
    detailed_item["key_phrases"] = key_phrases_payload(rec_id)
    return req.send_json(detailed_item)


@route("GET", '/api/recording/version')
def get_api_recording_version(req, path: str, query: dict) -> None:
    rec_id = query.get("id", [""])[0]
    stamp = query.get("stamp", [""])[0]
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}", stamp):
        raise ValueError("Invalid version stamp")
    version_dir = (safe_folder(rec_id) / "versions" / stamp).resolve()
    version_dir.relative_to(RECORDINGS.resolve())
    if not version_dir.is_dir():
        raise FileNotFoundError(stamp)
    transcript_path = version_dir / "transcript_diarized.md"
    notes_path = version_dir / "enhanced_notes.md"
    return req.send_json({
        "stamp": stamp,
        "transcript": transcript_path.read_text(errors="replace") if transcript_path.exists() else "",
        "enhanced_notes": notes_path.read_text(errors="replace") if notes_path.exists() else "",
    })


@route("GET", '/api/recording/progress')
def get_api_recording_progress(req, path: str, query: dict) -> None:
    rec_id = query.get("id", [""])[0]
    if not db.get_recording(rec_id):
        fallback = db.get_recording_by_live_id(rec_id)
        if fallback:
            rec_id = fallback["id"]
    progress_path = (RECORDINGS / rec_id / ".pipeline_progress.json").resolve()
    if not progress_path.is_relative_to(RECORDINGS.resolve()) or not progress_path.is_file():
        return req.send_json({"id": rec_id, "active": False})
    try:
        progress = json.loads(progress_path.read_text())
    except Exception:
        return req.send_json({"id": rec_id, "active": False})
    ts = progress.get("timestamp")
    if ts and (time.time() - float(ts)) > 900:
        return req.send_json({"id": rec_id, "active": False, "stale": True})
    return req.send_json({"id": rec_id, "active": True, **progress})


@route("POST", '/api/recording/archetype')
def post_api_recording_archetype(req, path: str, body: dict) -> None:
    rec_id = str(body.get("id", ""))
    archetype_id = body.get("archetype_id")
    archetype_key = str(body.get("mode") or (archetype_id if archetype_id is not None else "")).strip()

    arch_data = None
    if archetype_key.lower() not in ["auto", "none", ""]:
        try:
            aid = int(archetype_key)
            arch_data = ARCHETYPES.get(aid)
        except (ValueError, TypeError):
            for a in ARCHETYPES.values():
                if a["archetype_name"].lower() == archetype_key.lower():
                    arch_data = a
                    break

    # Check if it's an active pending recording
    pending_rec = db.get_pending_recording(rec_id)
    if pending_rec:
        curr_meta = pending_rec.get("metadata") or {}
        if arch_data:
            curr_meta["archetype"] = arch_data
        else:
            curr_meta.pop("archetype", None)
        db.update_recording_data(rec_id, "metadata", curr_meta)
        return req.send_json({"ok": True, "archetype": arch_data})

    folder = safe_folder(rec_id)
    curr_meta = db.get_recording_data(folder.name, "metadata") or {}
    if arch_data:
        curr_meta["archetype"] = arch_data
        atomic_json(folder / "archetype_classification.json", arch_data)
    else:
        curr_meta.pop("archetype", None)
        (folder / "archetype_classification.json").unlink(missing_ok=True)
    db.update_recording_data(folder.name, "metadata", curr_meta)
    return req.send_json({"ok": True, "archetype": arch_data})


@route("POST", '/api/folders')
def post_api_folders(req, path: str, body: dict) -> None:
    name = str(body.get("name", "")).strip()
    if not name:
        raise ValueError("Folder name is empty")
    folder_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or dt.datetime.now().strftime("f%Y%m%d%H%M%S%f")
    db.create_folder(folder_id, name, dt.datetime.now().astimezone().isoformat())
    return req.send_json({"ok": True, "folder": {"id": folder_id, "name": name}}, 201)


@route("POST", '/api/folders/delete')
def post_api_folders_delete(req, path: str, body: dict) -> None:
    folder_id = str(body.get("id", "")).strip()
    if not folder_id:
        raise ValueError("Folder id is empty")
    db.delete_folder(folder_id)
    return req.send_json({"ok": True})


@route("POST", '/api/recording/title')
def post_api_recording_title(req, path: str, body: dict) -> None:
    rec_id = str(body.get("id", "")).strip()
    new_title = str(body.get("title", "")).strip()
    if not rec_id:
        raise ValueError("Recording ID is required")
    if not new_title:
        raise ValueError("Title cannot be empty")
    db.update_recording_title(rec_id, new_title)
    try:
        folder = safe_folder(rec_id)
        metadata_path = folder / "metadata.json"
        if metadata_path.is_file():
            meta = json.loads(metadata_path.read_text())
            meta["recording_name"] = new_title
            meta["recording_name_source"] = "user"
            atomic_json(metadata_path, meta)
    except Exception:
        pass
    return req.send_json({"ok": True, "title": new_title})


@route("POST", '/api/recording/folder')
def post_api_recording_folder(req, path: str, body: dict) -> None:
    rec_id = str(body.get("id", ""))
    rec_data = db.get_recording(rec_id)
    if not rec_data:
        raise FileNotFoundError(rec_id)
    folder_id = body.get("folder_id") or None
    meta = rec_data.get("metadata") or {}
    if folder_id:
        meta["folder_id"] = folder_id
    else:
        meta.pop("folder_id", None)
    db.update_recording_data(rec_id, "metadata", meta)
    return req.send_json({"ok": True})


@route("POST", '/api/process-recording', '/api/gemini-diarize', '/api/local-process')
def post_api_process_recording(req, path: str, body: dict) -> None:
    # /api/process-recording is the current name — local-first
    # by default, same as this whole endpoint always was.
    # /api/gemini-diarize is kept only as a back-compat alias
    # (it's what this endpoint used to be called, even though
    # it runs local processing by default, not Gemini — the
    # confusing name is exactly why /api/process-recording
    # exists now).
    folder = safe_folder(body.get("id", ""))
    engine = str(body.get("engine", "")).lower()
    # Local-first by default: an explicit request for the cloud path
    # (either endpoint or engine param) is the only way to opt into
    # sending audio to Gemini. transcription_engine unset == local.
    wants_cloud = path in {"/api/process-recording", "/api/gemini-diarize"} and engine in {"cloud", "gemini", "vertex"}
    is_local = not wants_cloud and (
        path == "/api/local-process"
        or engine in {"local", "local_mlx", "mlx"}
        or db.get_setting("transcription_engine", "local_mlx") == "local_mlx"
    )
    if is_local:
        try:
            import local_meeting_pipeline
            res = local_meeting_pipeline.process_recording_local(folder)
        except ImportError as exc:
            return req.send_json({
                "error": (
                    "Local transcription isn't set up on this machine "
                    f"(missing dependency: {exc}). Install it with "
                    "`pip install mlx-whisper mlx-lm`, or set "
                    "transcription_engine to \"gemini\" via /api/settings "
                    "to use cloud diarization instead."
                )
            }, 503)
        return req.send_json({
            "ok": True,
            "diarization": res["diarization"],
            "speaker_profiles": res["speaker_profiles"],
            "call_summary": res["call_summary"],
            "engine": "local_mlx_hinglish"
        })
    else:
        result = gemini_diarize(folder, model=LATEST_AUDIO_MODEL)
        return req.send_json({"ok": True, "diarization": result, "speaker_profiles": speaker_profiles(result)})


@route("POST", '/api/recording/key-phrase')
def post_api_recording_key_phrase(req, path: str, body: dict) -> None:
    rec_id = str(body.get("id", ""))
    term = str(body.get("term", "")).strip()
    action = str(body.get("action", ""))
    if not db.get_recording(rec_id):
        raise FileNotFoundError(rec_id)
    if not term:
        raise ValueError("term is required")
    metadata = db.get_recording_data(rec_id, "metadata") or {}
    manual = metadata.get("key_phrases_manual") or []
    removed = metadata.get("key_phrases_removed") or []
    term_key = term.lower()
    if action == "add":
        if term_key not in {t.lower() for t in manual}:
            manual.append(term)
        removed = [t for t in removed if t.lower() != term_key]
    elif action == "remove":
        manual = [t for t in manual if t.lower() != term_key]
        if term_key not in {t.lower() for t in removed}:
            removed.append(term)
    else:
        raise ValueError(f"Unknown action: {action}")
    metadata["key_phrases_manual"] = manual
    metadata["key_phrases_removed"] = removed
    db.update_recording_data(rec_id, "metadata", metadata)
    return req.send_json({"ok": True})


@route("POST", '/api/recording/notes/append')
def post_api_recording_notes_append(req, path: str, body: dict) -> None:
    rec_id = str(body.get("id", "")).strip()
    note_line = str(body.get("text", "")).strip()
    if not rec_id:
        raise ValueError("Recording ID is required")
    if not note_line:
        raise ValueError("Text is required")
    existing = db.get_notes(rec_id) or ""
    formatted_line = f"- {note_line}" if not note_line.startswith("-") else note_line
    new_text = (existing + "\n" + formatted_line).strip() if existing else formatted_line
    db.update_notes(rec_id, new_text)
    return req.send_json({"ok": True, "notes": new_text})


@route("POST", '/api/recording/notes')
def post_api_recording_notes(req, path: str, body: dict) -> None:
    rec_id = str(body.get("id", ""))
    if not db.get_recording(rec_id):
        raise FileNotFoundError(rec_id)
    text = str(body.get("text", ""))
    db.update_notes(rec_id, text)
    if text.strip():
        import local_meeting_pipeline
        local_meeting_pipeline.learn_from_transcript(text, source="notes")
    return req.send_json({"ok": True})


@route("POST", '/api/recording/summary')
def post_api_recording_summary(req, path: str, body: dict) -> None:
    import local_meeting_pipeline
    folder = safe_folder(body.get("id", ""))
    format_name = str(body.get("format", ""))
    transcript_text = (folder / "transcript_diarized.md").read_text(errors="replace") if (folder / "transcript_diarized.md").exists() else ""
    notes_text = db.get_notes(folder.name)
    slides_data = local_meeting_pipeline.load_slides_ocr(folder)
    result = local_meeting_pipeline.generate_summary_variant(transcript_text, notes_text, slides_data, format_name)
    db.update_summary(folder.name, format_name, result)
    return req.send_json({"ok": True, "summary": result})


@route("POST", '/api/recording/re-summarize')
def post_api_recording_re_summarize(req, path: str, body: dict) -> None:
    folder = safe_folder(body.get("id", ""))
    provider = str(body.get("provider", "")).strip().lower() or None
    model = str(body.get("model", "")).strip() or None

    import local_meeting_pipeline
    t_path = folder / "transcript_diarized.md"
    if not t_path.exists():
        raise FileNotFoundError("Transcript not found for this recording")
    transcript_text = t_path.read_text(encoding="utf-8")
    user_notes = db.get_notes(folder.name) or ""
    slides_data = local_meeting_pipeline.load_slides_ocr(folder)
    diar_data = db.get_recording_data(folder.name, "diarization") or {}
    aligned_segments = diar_data.get("segments", [])

    if provider and provider != "local_mlx":
        notes = local_meeting_pipeline.generate_enhanced_notes_frontier(
            transcript_text=transcript_text,
            slides_data=slides_data,
            aligned_segments=aligned_segments,
            user_notes=user_notes,
            provider=provider,
            model=model,
        )
        used_model = f"{provider}:{model or 'default'}"
    else:
        notes = local_meeting_pipeline.generate_enhanced_notes(
            transcript_text=transcript_text,
            slides_data=slides_data,
            aligned_segments=aligned_segments,
            folder=folder,
        )
        used_model = db.get_setting("liquid_model", local_meeting_pipeline.LOCAL_LLM_MODEL_DEFAULT)

    now_iso = dt.datetime.now().astimezone().isoformat()
    call_summary_payload = {
        "overview": notes["overview"],
        "decisions": local_meeting_pipeline._markdown_bullets(notes["decisions_md"]),
        "action_items": local_meeting_pipeline._markdown_bullets(notes["action_items_md"]),
        "unresolved_questions": local_meeting_pipeline._markdown_bullets(notes["open_questions_md"]),
        "keywords": notes["keywords"],
        "model": used_model,
        "generated_at": now_iso,
        "schema_version": "2.0",
        "source_recording": "audio.mov",
    }

    enhanced_notes_md = "\n\n".join([
        "## Overview", notes["overview"],
        "## Action Items", notes["action_items_md"],
        "## Key Discussion & Decisions", notes["decisions_md"],
        "## Timeline", notes["timeline_md"],
        "## Open Questions", notes["open_questions_md"],
        "## Key Entities", notes["key_entities_md"],
    ])

    local_meeting_pipeline._archive_previous_outputs(folder)
    (folder / "enhanced_notes.md").write_text(enhanced_notes_md + "\n", encoding="utf-8")
    (folder / "call_summary.json").write_text(json.dumps(call_summary_payload, indent=2, ensure_ascii=False) + "\n")
    if diar_data:
        diar_data["summary"] = notes["overview"]
        (folder / "gemini_diarization.json").write_text(json.dumps(diar_data, indent=2, ensure_ascii=False) + "\n")
        db.update_recording_data(folder.name, "diarization", diar_data)

    db.update_recording_data(folder.name, "call_summary", call_summary_payload)

    return req.send_json({
        "ok": True,
        "enhanced_notes": enhanced_notes_md,
        "call_summary": call_summary_payload,
        "model": used_model,
    })


@route("POST", '/api/recording/transcript/edit')
def post_api_recording_transcript_edit(req, path: str, body: dict) -> None:
    import transcript_edit
    rec_id = str(body.get("id", ""))
    folder = safe_folder(rec_id)
    edits = body.get("edits")
    if not isinstance(edits, list) or not edits or len(edits) > 2000:
        raise ValueError("edits must be a non-empty list")
    return req.send_json(transcript_edit.apply_edits(folder.name, folder, edits, self_name=current_self_name()))
