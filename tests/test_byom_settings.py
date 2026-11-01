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
