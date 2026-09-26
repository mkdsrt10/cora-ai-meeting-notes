"""Settings, credentials, onboarding, models, vocabulary memory, MCP config."""
from __future__ import annotations
import datetime as dt
import shutil

from api.router import route
import credentials
import datetime as dt
import db
import meeting_types
import shutil
from api.core import PYTHON, ROOT, available_models, local_usage_stats


@route("GET", '/api/settings')
def get_api_settings(req, path: str, query: dict) -> None:
    return req.send_json({"value": db.get_setting(query.get("key", [""])[0])})


@route("GET", '/api/onboarding/status')
def get_api_onboarding_status(req, path: str, query: dict) -> None:
    return req.send_json({
        "complete": bool(db.get_setting("onboarding_complete", False)),
        "has_api_key": credentials.is_available(),
        "credentials": credentials.get_public_status(),
        "self_name": db.get_setting("pending_self_name") or (db.get_person(db.get_self_person_id() or "") or {}).get("name"),
        "profession": db.get_setting("profession"),
        "ffmpeg_ok": shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None,
    })


@route("GET", '/api/credentials/status')
def get_api_credentials_status(req, path: str, query: dict) -> None:
    return req.send_json({"ok": True, "credentials": credentials.get_public_status()})


@route("GET", '/api/local-stats')
def get_api_local_stats(req, path: str, query: dict) -> None:
    return req.send_json(local_usage_stats())


@route("GET", '/api/memory/terms')
def get_api_memory_terms(req, path: str, query: dict) -> None:
    return req.send_json({"terms": db.get_vocabulary_terms(200)})


@route("GET", '/api/mcp/config')
def get_api_mcp_config(req, path: str, query: dict) -> None:
    py_bin = str(PYTHON)
    mcp_script = str(ROOT / "python/mcp_server.py")
    claude_config = {
        "mcpServers": {
            "cora": {
                "command": py_bin,
                "args": [mcp_script]
            }
        }
    }
    cursor_config = {
        "mcpServers": {
            "cora": {
                "command": py_bin,
                "args": [mcp_script]
            }
        }
    }
    return req.send_json({
        "claude_desktop_config": claude_config,
        "cursor_config": cursor_config,
        "claude_code_command": f"claude mcp add cora {py_bin} {mcp_script}",
        "mcp_script_path": mcp_script,
        "python_bin": py_bin,
    })


@route("GET", '/api/onboarding/meeting-types')
def get_api_onboarding_meeting_types(req, path: str, query: dict) -> None:
    return req.send_json({
        "meeting_types": meeting_types.MEETING_TYPES,
        "selected": db.get_setting("meeting_types", []),
    })


@route("GET", '/api/onboarding/models')
def get_api_onboarding_models(req, path: str, query: dict) -> None:
    return req.send_json(available_models())


@route("POST", '/api/memory/terms')
def post_api_memory_terms(req, path: str, body: dict) -> None:
    term = str(body.get("term", "")).strip()
    if not term:
        raise ValueError("Term is empty")
    db.upsert_vocabulary_term(term, "manual", dt.datetime.now().astimezone().isoformat())
    return req.send_json({"ok": True}, 201)


@route("POST", '/api/memory/terms/delete')
def post_api_memory_terms_delete(req, path: str, body: dict) -> None:
    term = str(body.get("term", "")).strip()
    if not term:
        raise ValueError("Term is empty")
    db.delete_vocabulary_term(term)
    return req.send_json({"ok": True})


@route("POST", '/api/memory/terms/merge')
def post_api_memory_terms_merge(req, path: str, body: dict) -> None:
    primary = str(body.get("primary", "")).strip()
    duplicate = str(body.get("duplicate", "")).strip()
    if not primary or not duplicate or primary == duplicate:
        raise ValueError("primary and duplicate must be distinct, non-empty terms")
    db.merge_vocabulary_terms(primary, duplicate)
    return req.send_json({"ok": True})


@route("POST", '/api/credentials/test')
def post_api_credentials_test(req, path: str, body: dict) -> None:
    provider = body.get("provider", "vertex")
    ok, msg = credentials.test_credentials(
        provider=provider,
        project=body.get("project"),
        location=body.get("location", "us-central1"),
        auth_type=body.get("auth_type", "adc"),
        service_account_json=body.get("service_account_json"),
        api_key=body.get("api_key"),
        model=body.get("model"),
    )
    if not ok:
        return req.send_json({"ok": False, "error": msg}, 400)
    return req.send_json({"ok": True, "message": msg})


@route("POST", '/api/credentials/save', '/api/onboarding/api-key')
def post_api_credentials_save(req, path: str, body: dict) -> None:
    provider = body.get("provider")
    raw_key = str(body.get("api_key", "")).strip()
    model = str(body.get("model", "")).strip()
    project = str(body.get("project", "")).strip() or credentials.detect_gcloud_project()
    location = str(body.get("location", "us-central1")).strip()
    auth_type = str(body.get("auth_type", "adc")).strip()
    sa_json = body.get("service_account_json")
    base_url = str(body.get("base_url", "")).strip()

    if provider == "anthropic":
        ok, msg = credentials.test_credentials(provider="anthropic", api_key=raw_key, model=model or None)
        if not ok:
            return req.send_json({"ok": False, "error": f"Anthropic key rejected: {msg}"}, 400)
        credentials.save_anthropic_credentials(raw_key, model=model or "claude-3-7-sonnet-20250219")

    elif provider == "openai":
        ok, msg = credentials.test_credentials(provider="openai", api_key=raw_key, model=model or None, location=base_url or None)
        if not ok:
            return req.send_json({"ok": False, "error": f"OpenAI key rejected: {msg}"}, 400)
        credentials.save_openai_credentials(raw_key, model=model or "gpt-4o", base_url=base_url or "https://api.openai.com/v1")

    elif provider == "custom":
        ok, msg = credentials.test_credentials(provider="custom", api_key=raw_key, model=model or None, location=base_url)
        if not ok:
            return req.send_json({"ok": False, "error": f"Custom endpoint rejected: {msg}"}, 400)
        credentials.save_custom_llm_credentials(base_url=base_url, api_key=raw_key, model=model or "default")

    elif provider == "vertex":
        ok, msg = credentials.test_credentials(
            provider="vertex",
            project=project,
            location=location,
            auth_type=auth_type,
            service_account_json=sa_json,
            api_key=raw_key if auth_type == "api_key" else None,
        )
        if not ok:
            return req.send_json({"ok": False, "error": f"Vertex verification failed: {msg}"}, 400)
        credentials.save_vertex_credentials(
            project=project,
            location=location,
            auth_type=auth_type,
            service_account_json=sa_json,
            api_key=raw_key if auth_type == "api_key" else None,
        )
    elif provider in {"ai_studio", "gemini"}:
        if not raw_key:
            raise ValueError("Gemini API key is required.")
        ok, msg = credentials.test_credentials(provider="ai_studio", api_key=raw_key, model=model or None)
        if not ok:
            return req.send_json({"ok": False, "error": f"Gemini key was rejected: {msg}"}, 400)
        credentials.save_ai_studio_credentials(raw_key)
        if model:
            file_cfg = credentials._read_secure_file()
            file_cfg["gemini_model"] = model
            file_cfg["notes_llm_provider"] = "gemini"
            credentials._write_secure_file(file_cfg)
            credentials._invalidate_public_status_cache()

    return req.send_json({"ok": True, "credentials": credentials.get_public_status()})


@route("POST", '/api/onboarding/name')
def post_api_onboarding_name(req, path: str, body: dict) -> None:
    name = str(body.get("name", "")).strip()
    if not name:
        raise ValueError("Name is empty")
    db.set_setting("pending_self_name", name)
    return req.send_json({"ok": True})


@route("POST", '/api/onboarding/complete')
def post_api_onboarding_complete(req, path: str, body: dict) -> None:
    db.set_setting("onboarding_complete", True)
    return req.send_json({"ok": True})


@route("POST", '/api/settings')
def post_api_settings(req, path: str, body: dict) -> None:
    key = str(body.get("key", ""))
    value = body.get("value")
    if value is not None:
        db.set_setting(key, value)
        return req.send_json({"ok": True})
    else:
        return req.send_json({"value": db.get_setting(key)})
