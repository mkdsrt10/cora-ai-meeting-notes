"""Settings, credentials, onboarding, models, vocabulary memory, MCP config."""
from __future__ import annotations
import datetime as dt
import shutil
from pathlib import Path

from api.router import route
import credentials
import datetime as dt
import db
import meeting_types
import shutil
from api.core import PYTHON, ROOT, available_models, local_usage_stats


@route("GET", '/api/settings')
def get_api_settings(req, path: str, query: dict) -> None:
    return req.send_json({"value": read_setting(query.get("key", [""])[0])})


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


@route("GET", '/api/models/status')
def get_api_models_status(req, path: str, query: dict) -> None:
    """Whether the currently selected transcription/notes models actually
    have weights on disk right now — checked at startup (and can be
    re-checked any time) so a broken or never-downloaded model surfaces as
    a clear "pick or download one" prompt instead of failing deep inside a
    recording with an opaque mlx error."""
    import pipeline.config as pcfg
    return req.send_json({"whisper": pcfg.whisper_model_status(), "liquid": pcfg.llm_model_status()})


@route("POST", '/api/models/download')
def post_api_models_download(req, path: str, body: dict) -> None:
    model_id = str(body.get("id", "")).strip()
    if not model_id or "/" not in model_id or Path(model_id).expanduser().is_absolute():
        raise ValueError("id must be a Hugging Face repo id (e.g. 'org/model') — a local path can't be downloaded")
    import download_manager
    return req.send_json(download_manager.start(model_id))


@route("GET", '/api/models/download-status')
def get_api_models_download_status(req, path: str, query: dict) -> None:
    model_id = query.get("id", [""])[0]
    if not model_id:
        raise ValueError("id is required")
    import download_manager
    return req.send_json(download_manager.status(model_id))


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


def _candidate(provider: str, body: dict) -> dict:
    """Entered api_key/base_url completed from the saved ones, for the
    OpenAI-compatible presets and Anthropic (blank key = keep the saved key)."""
    from pipeline import text_model
    if provider == "anthropic" or provider in credentials.OPENAI_COMPATIBLE_PRESETS:
        conn = text_model.candidate_connection(provider, base_url=body.get("base_url"), api_key=body.get("api_key"))
        return {"api_key": conn["api_key"], "base_url": None if provider == "anthropic" else conn["base_url"]}
    return {"api_key": body.get("api_key"), "base_url": body.get("base_url")}


@route("POST", '/api/credentials/test')
def post_api_credentials_test(req, path: str, body: dict) -> None:
    provider = body.get("provider", "vertex")
    if provider in credentials.OPENAI_COMPATIBLE_PRESETS or provider == "anthropic":
        ok, msg = credentials.test_credentials(provider=provider, model=body.get("model"), **_candidate(provider, body))
    else:
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


@route("POST", '/api/credentials/models')
def post_api_credentials_models(req, path: str, body: dict) -> None:
    """Settings' "Load models": the provider's model ids, fetched here so the
    saved key never reaches the renderer. Errors never echo the provider body."""
    import policy
    from pipeline import text_model
    preset = str(body.get("provider") or body.get("preset") or "")
    try:
        models = text_model.list_models(preset, base_url=body.get("base_url"), api_key=body.get("api_key"))
    except policy.LockdownError as exc:
        return req.send_json({"ok": False, "error": str(exc)}, 403)
    except (text_model.ModelListError, ValueError) as exc:
        return req.send_json({"ok": False, "error": str(exc)}, 400)
    return req.send_json({"ok": True, "models": models})


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

    if provider == "anthropic" or provider in credentials.OPENAI_COMPATIBLE_PRESETS:
        candidate = _candidate(provider, body)
        raw_key, base_url = candidate["api_key"], candidate["base_url"] or ""

    if provider == "anthropic":
        ok, msg = credentials.test_credentials(provider="anthropic", api_key=raw_key, model=model or None)
        if not ok:
            return req.send_json({"ok": False, "error": f"Anthropic key rejected: {msg}"}, 400)
        credentials.save_anthropic_credentials(raw_key, model=model)

    elif provider in credentials.OPENAI_COMPATIBLE_PRESETS:
        # openai, openrouter, groq, ollama, lmstudio, custom: one OpenAI-compatible adapter.
        if provider == "custom" and not base_url:
            raise ValueError("Base URL cannot be empty.")
        ok, msg = credentials.test_credentials(provider=provider, api_key=raw_key, model=model or None, base_url=base_url or None)
        if not ok:
            label = {"openai": "OpenAI key", "custom": "Custom endpoint"}.get(provider, f"{provider} endpoint")
            return req.send_json({"ok": False, "error": f"{label} rejected: {msg}"}, 400)
        credentials.save_openai_compatible_credentials(provider, base_url=base_url, api_key=raw_key,
                                                       model=model or ("default" if provider == "custom" else ""))

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

    asr_model = str(body.get("asr_model") or "").strip()
    if asr_model and provider in credentials.OPENAI_COMPATIBLE_PRESETS:
        db.set_setting("openai_asr_model", asr_model)

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


# Keys where a stored null means something (microphone: System default;
# beta_display_name: no name), so {key, value: null} clears them. For every
# other key null stays a read.
NULLABLE_SETTINGS = frozenset({"microphone", "beta_display_name"})

# Defaults for keys whose unset value is not null (beta audio retention).
SETTING_DEFAULTS = {"audio_retention_days": 30, "audio_cap_mb": 500}
READ_ONLY_SETTINGS = frozenset({"install_id"})
DISPLAY_NAME_MAX = 100


def read_setting(key: str):
    """A setting as the app should see it: the Install id (created on first
    read), the share toggle's effective value (build-variant default, off
    under lockdown), and the audio retention defaults."""
    import usage_events
    if key == "install_id":
        return usage_events.install_id()
    if key == "share_usage":
        return usage_events.share_usage()
    return db.get_setting(key, SETTING_DEFAULTS.get(key))


@route("POST", '/api/settings')
def post_api_settings(req, path: str, body: dict) -> None:
    """{key, value} writes; {key} alone, or {key, value: null}, reads; for a
    key in NULLABLE_SETTINGS, {key, value: null} clears it instead."""
    key = str(body.get("key", ""))
    value = body.get("value")
    if value is None and not ("value" in body and key in NULLABLE_SETTINGS):
        return req.send_json({"value": read_setting(key)})
    if key in READ_ONLY_SETTINGS:
        raise ValueError(f"{key} is read-only")
    validate = _VALIDATORS.get(key)
    if validate and value is not None:
        value = validate(value)
    db.set_setting(key, value)
    return req.send_json({"ok": True})


def _validate_microphone(value):
    """The Microphone setting is {unique_id, name} (null = System default)."""
    if not (isinstance(value, dict) and set(value) == {"unique_id", "name"}
            and all(isinstance(v, str) and v.strip() for v in value.values())):
        raise ValueError("microphone must be {unique_id, name} or null")
    return value


def _validate_display_name(value):
    """Your name for the Cora team: trimmed text; blank means no name."""
    if not isinstance(value, str) or len(value.strip()) > DISPLAY_NAME_MAX:
        raise ValueError(f"beta_display_name must be text of at most {DISPLAY_NAME_MAX} characters, or null")
    return value.strip() or None


def _validate_share_usage(value):
    if not isinstance(value, bool):
        raise ValueError("share_usage must be true or false")
    return value


def _whole_number_at_least(key: str, minimum: int):
    def validate(value):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{key} must be a whole number of at least {minimum}")
        return value
    return validate


_VALIDATORS = {
    "microphone": _validate_microphone,
    "beta_display_name": _validate_display_name,
    "share_usage": _validate_share_usage,
    "audio_retention_days": _whole_number_at_least("audio_retention_days", 1),
    "audio_cap_mb": _whole_number_at_least("audio_cap_mb", 50),
}


@route("GET", '/api/audio-devices')
def get_api_audio_devices(req, path: str, query: dict) -> None:
    """Microphone picker's device list, from the capture helper. Local-only:
    not gated by enterprise lockdown."""
    import capture_devices
    return req.send_json({"devices": capture_devices.list_devices()})


@route('GET', '/api/processing')
def get_api_processing(req, path: str, query: dict) -> None:
    import processing
    return req.send_json(dict(preferences=processing.preferences(), hardware=processing.hardware(),
                              templates=[dict(id=k, name=v[0], description=v[1]) for k, v in processing.TEMPLATES.items()]))


@route('POST', '/api/processing')
def post_api_processing(req, path: str, body: dict) -> None:
    import processing
    selected = processing.validate(body)
    # Saving this explicit profile is consent to automatic use, unlike saving an API key.
    processing.resolve(selected)
    db.set_setting('processing_preferences', selected)
    return req.send_json(dict(ok=True, preferences=selected))
