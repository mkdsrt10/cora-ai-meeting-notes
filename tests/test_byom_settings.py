"""Bring-your-own-model Settings: base-URL resolution, listing a provider's
models through the backend, and the credentials routes Settings calls.

Transport is stubbed at requests.get/post; keys and provider bodies must
never appear in what the renderer receives."""
from types import SimpleNamespace

import pytest

import credentials
import policy
from pipeline import text_model as tm


def test_base_url_is_the_entered_url_else_the_preset_default():
    assert tm.resolve_base_url("groq") == "https://api.groq.com/openai/v1"
    assert tm.resolve_base_url("ollama", "") == "http://localhost:11434/v1"
    assert tm.resolve_base_url("custom", " http://localhost:4000/v1/ ") == "http://localhost:4000/v1"
    assert tm.resolve_base_url("custom") == ""


class Response:
    def __init__(self, payload, status=200, text=""):
        self._payload, self.status_code, self.text = payload, status, text

    def json(self):
        return self._payload


@pytest.fixture
def saved(monkeypatch):
    """Saved provider settings, as credentials would return them."""
    values = {}
    monkeypatch.setattr(credentials, "provider_settings", lambda name: dict(values.get(name, {})))
    return values


@pytest.fixture
def gets(monkeypatch):
    import requests
    calls, replies = [], []

    def get(url, headers=None, timeout=None, **kwargs):
        calls.append(dict(url=url, headers=headers or {}, timeout=timeout))
        reply = replies.pop(0) if replies else Response({"data": []})
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(requests, "get", get)
    return SimpleNamespace(calls=calls, replies=replies)


def test_list_models_calls_the_presets_models_endpoint_with_the_entered_key(saved, gets):
    gets.replies.append(Response({"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "whisper-large-v3"}]}))
    models = tm.list_models("groq", api_key="gsk-entered")
    assert models == ["llama-3.3-70b-versatile", "whisper-large-v3"]
    call = gets.calls[0]
    assert call["url"] == "https://api.groq.com/openai/v1/models"
    assert call["headers"]["Authorization"] == "Bearer gsk-entered"
    assert call["timeout"] and call["timeout"] <= 15


@pytest.mark.parametrize("status, expected", [(401, "rejected the API key"), (403, "rejected the API key"),
                                              (404, "type the model name"), (500, "HTTP 500")])
def test_list_models_errors_are_plain_and_never_echo_the_provider_body(saved, gets, status, expected):
    gets.replies.append(Response({"error": {"message": "bad key sk-secret-123"}}, status,
                                 text='{"error": "bad key sk-secret-123"}'))
    with pytest.raises(tm.ModelListError) as err:
        tm.list_models("openai", api_key="sk-secret-123")
    assert expected in str(err.value)
    assert "sk-secret" not in str(err.value)


def test_list_models_unreachable_or_slow_endpoint_is_a_clear_error(saved, gets):
    import requests
    gets.replies.append(requests.ConnectionError("conn refused http://localhost:1234 secret"))
    with pytest.raises(tm.ModelListError, match="Could not reach localhost"):
        tm.list_models("lmstudio")
    gets.replies.append(requests.Timeout("read timed out"))
    with pytest.raises(tm.ModelListError, match="did not answer"):
        tm.list_models("lmstudio")


def test_lockdown_blocks_listing_a_remote_provider_but_allows_localhost(saved, gets, monkeypatch):
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    for preset, url in (("openrouter", None), ("custom", "https://litellm.example.com/v1"), ("anthropic", None)):
        with pytest.raises(policy.LockdownError):
            tm.list_models(preset, base_url=url, api_key="k")
    assert gets.calls == []
    gets.replies.append(Response({"data": [{"id": "llama3"}]}))
    assert tm.list_models("ollama") == ["llama3"]
    assert gets.calls[0]["url"] == "http://localhost:11434/v1/models"


def test_list_models_refuses_plain_http_to_a_remote_host(saved, gets):
    with pytest.raises(ValueError, match="https"):
        tm.list_models("custom", base_url="http://evil.example.com/v1", api_key="k")
    assert gets.calls == []


def test_saved_key_is_reused_only_for_the_saved_base_url(saved, gets):
    saved["custom"] = {"api_key": "saved-key", "base_url": "https://proxy.example.com/v1"}
    tm.list_models("custom")
    assert gets.calls[-1]["url"] == "https://proxy.example.com/v1/models"
    assert gets.calls[-1]["headers"]["Authorization"] == "Bearer saved-key"
    tm.list_models("custom", base_url="https://other.example.com/v1")
    assert "Authorization" not in gets.calls[-1]["headers"]


def test_anthropic_models_use_its_own_header(saved, gets):
    saved["anthropic"] = {"api_key": "sk-ant-saved"}
    gets.replies.append(Response({"data": [{"id": "claude-sonnet-5-5"}]}))
    assert tm.list_models("anthropic") == ["claude-sonnet-5-5"]
    call = gets.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/models"
    assert call["headers"]["x-api-key"] == "sk-ant-saved" and "Authorization" not in call["headers"]


# ---- routes Settings calls ------------------------------------------------------

def call_route(fn, body):
    out = {}
    req = SimpleNamespace(send_json=lambda payload, status=200: out.update(payload=payload, status=status))
    fn(req, "", body)
    return out["status"], out["payload"]


def test_models_route_returns_the_list(saved, gets):
    from api.routes import settings
    gets.replies.append(Response({"data": [{"id": "b"}, {"id": "a"}]}))
    status, payload = call_route(settings.post_api_credentials_models,
                                 {"provider": "openrouter", "api_key": "or-key"})
    assert (status, payload) == (200, {"ok": True, "models": ["a", "b"]})


def test_models_route_errors_carry_no_key_or_body(saved, gets, monkeypatch):
    from api.routes import settings
    gets.replies.append(Response({}, 401, text="invalid key or-secret"))
    status, payload = call_route(settings.post_api_credentials_models,
                                 {"provider": "openrouter", "api_key": "or-secret"})
    assert status == 400 and payload["ok"] is False and "rejected the API key" in payload["error"]
    assert "or-secret" not in str(payload)
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    status, payload = call_route(settings.post_api_credentials_models, {"provider": "groq", "api_key": "g"})
    assert status == 403 and "lockdown" in payload["error"]


@pytest.fixture
def store(monkeypatch):
    """In-memory Keychain + 0600 file; connection tests always pass and are recorded."""
    keychain, files, tests = {}, {}, []
    monkeypatch.setattr(credentials, "_keychain_set", lambda account, secret: keychain.__setitem__(account, secret) or True)
    monkeypatch.setattr(credentials, "_keychain_get", lambda account, *a: keychain.get(account))
    monkeypatch.setattr(credentials, "_keychain_delete", lambda account, *a: keychain.pop(account, None) or True)
    monkeypatch.setattr(credentials, "_read_secure_file", lambda: dict(files))
    monkeypatch.setattr(credentials, "_write_secure_file", lambda data: files.clear() or files.update(data) or True)
    monkeypatch.setattr(credentials, "_sanitize_db", lambda: None)
    monkeypatch.setattr(credentials, "detect_gcloud_project", lambda: "")
    monkeypatch.setattr(credentials, "has_gcloud_adc", lambda: False)
    credentials._invalidate_public_status_cache()
    monkeypatch.setattr(credentials, "test_credentials", lambda **kw: tests.append(kw) or (True, "ok"))
    return SimpleNamespace(keychain=keychain, files=files, tests=tests)


@pytest.mark.parametrize("preset, body, expected_url", [
    ("openai", {"api_key": "sk-1", "model": "gpt-4o-mini"}, "https://api.openai.com/v1"),
    ("openrouter", {"api_key": "or-1", "model": "anthropic/claude"}, "https://openrouter.ai/api/v1"),
    ("groq", {"api_key": "gsk-1", "model": "llama-3.3-70b-versatile"}, "https://api.groq.com/openai/v1"),
    ("ollama", {"model": "qwen3"}, "http://localhost:11434/v1"),
    ("lmstudio", {"model": "local", "base_url": "http://127.0.0.1:1235/v1/"}, "http://127.0.0.1:1235/v1"),
    ("custom", {"api_key": "lite-1", "model": "proxy", "base_url": "https://litellm.example.com/v1"},
     "https://litellm.example.com/v1"),
])
def test_save_route_stores_each_openai_compatible_preset(store, preset, body, expected_url):
    from api.routes import settings
    status, payload = call_route(settings.post_api_credentials_save, {"provider": preset, **body})
    assert status == 200 and payload["ok"]
    assert store.tests[-1]["base_url"] == expected_url and "location" not in store.tests[-1]
    assert credentials.provider_settings(preset) == {"api_key": body.get("api_key", ""), "model": body["model"],
                                                     "base_url": expected_url}
    assert payload["credentials"]["presets"][preset]["configured"] is True
    assert "sk-1" not in str(payload) and "lite-1" not in str(payload)


def test_save_route_keeps_the_saved_key_when_the_field_is_left_blank(store):
    from api.routes import settings
    call_route(settings.post_api_credentials_save, {"provider": "groq", "api_key": "gsk-1", "model": "a"})
    status, _ = call_route(settings.post_api_credentials_save, {"provider": "groq", "api_key": "", "model": "b"})
    assert status == 200 and store.tests[-1]["api_key"] == "gsk-1"
    assert credentials.provider_settings("groq")["model"] == "b" and store.keychain["groq_api_key"] == "gsk-1"


def test_save_route_stores_anthropic_and_gemini(store):
    from api.routes import settings
    assert call_route(settings.post_api_credentials_save,
                      {"provider": "anthropic", "api_key": "sk-ant-1", "model": "claude-opus-5-5"})[0] == 200
    assert credentials.provider_settings("anthropic")["api_key"] == "sk-ant-1"
    assert call_route(settings.post_api_credentials_save,
                      {"provider": "ai_studio", "api_key": "AIza-1", "model": "gemini-3.7-flash"})[0] == 200
    assert store.keychain["gemini_api_key"] == "AIza-1" and store.files["gemini_model"] == "gemini-3.7-flash"


def test_save_route_stores_the_transcription_model(store, monkeypatch):
    from api.routes import settings
    import db
    saved = {}
    monkeypatch.setattr(db, "set_setting", lambda key, value: saved.update({key: value}))
    call_route(settings.post_api_credentials_save,
               {"provider": "groq", "api_key": "gsk-1", "model": "m", "asr_model": "whisper-large-v3"})
    assert saved == {"openai_asr_model": "whisper-large-v3"}


def test_test_route_sends_the_entered_base_url_and_falls_back_to_the_saved_key(store):
    from api.routes import settings
    call_route(settings.post_api_credentials_save,
               {"provider": "custom", "api_key": "lite-1", "model": "m", "base_url": "https://proxy.example.com/v1"})
    call_route(settings.post_api_credentials_test,
               {"provider": "custom", "base_url": "https://proxy.example.com/v1", "location": "us-central1"})
    assert store.tests[-1]["base_url"] == "https://proxy.example.com/v1" and store.tests[-1]["api_key"] == "lite-1"
    call_route(settings.post_api_credentials_test, {"provider": "custom", "base_url": "https://other.example.com/v1"})
    assert store.tests[-1]["api_key"] == ""
