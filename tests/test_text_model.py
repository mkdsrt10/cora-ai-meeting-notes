"""Text model: one interface for every text-generation call.

Adapter tests stub the transport (requests.post / the Gemini client) and
check the request each provider receives; everything else goes through
text_model(profile).complete(...)."""
import json
from types import SimpleNamespace

import pytest

import credentials
import policy
from pipeline import text_model as tm


class Response:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} error", response=self)


@pytest.fixture
def saved(monkeypatch):
    """Saved provider settings, as credentials would return them."""
    values = {}
    monkeypatch.setattr(credentials, "provider_settings", lambda name: dict(values.get(name, {})))
    return values


@pytest.fixture
def posts(monkeypatch):
    import requests
    calls = []
    replies = []

    def post(url, headers=None, json=None, timeout=None, **kwargs):
        calls.append(dict(url=url, headers=headers, json=json, **kwargs))
        reply = replies.pop(0) if replies else Response({})
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(tm, "_sleep", lambda s: None)
    return SimpleNamespace(calls=calls, replies=replies)


def chat_reply(text, finish="stop"):
    return Response({"choices": [{"message": {"content": text}, "finish_reason": finish}],
                     "usage": {"prompt_tokens": 12, "completion_tokens": 3}})


def test_openai_compatible_request_shape(saved, posts):
    saved["openrouter"] = {"api_key": "or-key", "model": "", "base_url": ""}
    posts.replies.append(chat_reply("hello"))
    with tm.text_model({"provider": "openrouter", "model": "meta/llama"}) as model:
        assert model.complete("Say hi", system="Be brief", max_tokens=50, trace="t") == "hello"
    call = posts.calls[0]
    assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer or-key"
    assert call["json"]["model"] == "meta/llama"
    assert call["json"]["max_tokens"] == 50
    assert call["json"]["messages"] == [{"role": "system", "content": "Be brief"}, {"role": "user", "content": "Say hi"}]


def test_custom_endpoint_without_key_sends_no_auth_header(saved, posts):
    saved["custom"] = {"api_key": "", "model": "qwen", "base_url": "http://localhost:11434/v1/"}
    posts.replies.append(chat_reply("ok"))
    model = tm.text_model({"provider": "custom", "model": ""})
    assert model.model == "qwen"
    model.complete("x")
    assert posts.calls[0]["url"] == "http://localhost:11434/v1/chat/completions"
    assert "Authorization" not in posts.calls[0]["headers"]
    assert posts.calls[0]["json"]["messages"] == [{"role": "user", "content": "x"}]


def test_anthropic_request_shape_and_current_default_model(saved, posts):
    saved["anthropic"] = {"api_key": "sk-ant"}
    posts.replies.append(Response({"content": [{"type": "text", "text": "Hi "}, {"type": "text", "text": "there"}],
                                   "usage": {"input_tokens": 5, "output_tokens": 2}}))
    model = tm.text_model({"provider": "anthropic", "model": ""})
    assert model.model == "claude-sonnet-5-5"
    assert model.complete("Hello", system="Sys", max_tokens=99) == "Hi there"
    call = posts.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"]["x-api-key"] == "sk-ant" and call["headers"]["anthropic-version"] == "2023-06-01"
    assert call["json"] == {"model": "claude-sonnet-5-5", "max_tokens": 99, "system": "Sys",
                            "messages": [{"role": "user", "content": "Hello"}]}


def test_missing_key_is_a_clear_error(saved, posts):
    with pytest.raises(RuntimeError, match="Anthropic API key is not configured"):
        tm.text_model({"provider": "anthropic", "model": ""}).complete("x")
    assert not posts.calls


def test_gemini_honors_configured_model_and_output_budget(saved, monkeypatch):
    saved["gemini"] = {"model": "configured-model"}
    captured = {}

    def generate(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text=" general \n", usage_metadata=None)
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    monkeypatch.setattr(credentials, "build_gemini_client", lambda: client)
    model = tm.text_model({"provider": "gemini", "model": ""})
    assert model.model == "configured-model"
    assert model.complete("meeting data", system="static instructions", max_tokens=256) == "general"
    assert captured == {"model": "configured-model", "contents": "meeting data",
                        "config": {"system_instruction": "static instructions", "max_output_tokens": 256}}


def test_json_replies_are_repaired_once_for_every_provider(saved, posts):
    saved["openai"] = {"api_key": "k"}
    posts.replies.append(chat_reply('<think>hmm</think>```json\n{"title": "Plan", "items": ["a", "b"\n```'))
    reply = tm.text_model({"provider": "openai", "model": ""}).complete("x", json=True)
    assert reply == {"title": "Plan", "items": ["a", "b"]}


@pytest.mark.parametrize("raw", ["", "no json here at all", "42"])
def test_parse_json_rejects_non_json(raw):
    with pytest.raises(ValueError):
        tm.parse_json(raw)


def test_parse_json_recovers_truncated_list():
    assert tm.parse_json('[{"turn": 1}, {"turn": 2}') == [{"turn": 1}, {"turn": 2}]


def test_transient_errors_are_retried_with_backoff(saved, posts):
    import requests
    saved["groq"] = {"api_key": "g"}
    posts.replies.extend([Response({}, 429), requests.ConnectionError("reset"), chat_reply("finally")])
    assert tm.text_model({"provider": "groq", "model": ""}).complete("x") == "finally"
    assert len(posts.calls) == 3


def test_client_errors_are_not_retried(saved, posts):
    import requests
    saved["openai"] = {"api_key": "bad"}
    posts.replies.extend([Response({}, 401), chat_reply("never")])
    with pytest.raises(requests.HTTPError):
        tm.text_model({"provider": "openai", "model": ""}).complete("x")
    assert len(posts.calls) == 1


def test_lockdown_blocks_remote_adapters_but_allows_localhost(saved, posts, monkeypatch):
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    saved["custom"] = {"base_url": "http://127.0.0.1:4000/v1"}
    saved["openai"] = {"api_key": "k"}
    for provider in ("anthropic", "gemini", "openai", "openrouter"):
        with pytest.raises(policy.LockdownError):
            tm.text_model({"provider": provider, "model": ""})
    posts.replies.append(chat_reply("local answer"))
    assert tm.text_model({"provider": "custom", "model": ""}).complete("x") == "local answer"
    assert tm.text_model({"provider": "ollama", "model": ""}).provider == "ollama"


def test_one_profile_resolves_one_provider_and_model(saved, monkeypatch):
    """Every caller with the same profile gets the same adapter and model,
    whatever the mode says; nothing falls back to another provider."""
    saved["openai"] = {"api_key": "k", "model": "gpt-saved"}
    for mode in ("local_light", "local_thorough", "cloud"):
        model = tm.text_model({"mode": mode, "provider": "openai", "model": ""})
        assert (model.provider, model.model, model.local) == ("openai", "gpt-saved", False)
    local = tm.text_model({"mode": "cloud", "provider": "local_mlx", "model": "my/mlx"})
    assert (local.provider, local.model, local.local) == ("local_mlx", "my/mlx", True)


def test_local_model_defaults_to_the_onboarding_choice(saved, monkeypatch):
    import db
    monkeypatch.setattr(db, "get_setting", lambda key, default=None: "chosen/model" if key == "liquid_model" else default)
    assert tm.text_model({"provider": "local_mlx", "model": ""}).model == "chosen/model"
    assert tm.text_model({"provider": "local_mlx", "model": "explicit"}).model == "explicit"


def test_complete_is_traced_once_with_usage(saved, posts, monkeypatch):
    import ai_trace
    spans = []

    class Span:
        def set_output(self, output, **metrics):
            spans[-1].update(output=output, **metrics)

    from contextlib import contextmanager

    @contextmanager
    def span(kind, name, **kwargs):
        spans.append(dict(kind=kind, name=name, **kwargs))
        yield Span()
    monkeypatch.setattr(ai_trace, "span", span)
    saved["openai"] = {"api_key": "k"}
    posts.replies.append(chat_reply("traced"))
    tm.text_model({"provider": "openai", "model": ""}).complete("p", system="s", trace="notes.chunk.0")
    assert len(spans) == 1
    assert spans[0]["name"] == "notes.chunk.0" and spans[0]["provider"] == "openai"
    assert spans[0]["input"] == {"system": "s", "prompt": "p"}
    assert spans[0]["output"] == "traced" and spans[0]["output_tokens"] == 3


def test_fake_text_records_calls_and_close():
    fake = tm.FakeText(lambda prompt, **kw: json.dumps({"echo": prompt}))
    with tm.TextModel(fake, provider="local_mlx", model="fake") as model:
        assert model.complete("hi", json=True, trace="x") == {"echo": "hi"}
    assert fake.calls[0]["trace"] == "x" and fake.closed


def test_custom_endpoint_key_is_stored_in_keychain(monkeypatch, tmp_path):
    keychain, files = {}, {}
    monkeypatch.setattr(credentials, "_keychain_set", lambda account, secret: keychain.__setitem__(account, secret) or True)
    monkeypatch.setattr(credentials, "_keychain_get", lambda account: keychain.get(account))
    monkeypatch.setattr(credentials, "_read_secure_file", lambda: dict(files))
    monkeypatch.setattr(credentials, "_write_secure_file", lambda data: files.update(data) or True)
    credentials.save_custom_llm_credentials("http://localhost:4000/v1", api_key="litellm-key", model="proxy-model")
    assert keychain["custom_llm_key"] == "litellm-key"
    assert credentials.provider_settings("custom") == {"api_key": "litellm-key", "model": "proxy-model",
                                                       "base_url": "http://localhost:4000/v1"}


def test_connection_test_uses_candidate_base_url_through_text_model(saved, posts):
    posts.replies.append(chat_reply("pong"))
    ok, msg = credentials.test_credentials("custom", api_key="", model="m", base_url="http://localhost:9999/v1")
    assert ok, msg
    assert posts.calls[0]["url"] == "http://localhost:9999/v1/chat/completions"
    posts.replies.append(Response({}, 401))
    ok, msg = credentials.test_credentials("openai", api_key="bad", base_url="https://api.openai.com/v1")
    assert not ok and "Invalid OpenAI API key" in msg


def test_settings_test_route_forwards_base_url(monkeypatch):
    from api.routes import settings
    seen = {}
    monkeypatch.setattr(credentials, "test_credentials", lambda **kw: seen.update(kw) or (True, "ok"))
    req = SimpleNamespace(send_json=lambda payload, status=200: payload)
    settings.post_api_credentials_test(req, "", {"provider": "custom", "base_url": "http://localhost:11434/v1"})
    assert seen["base_url"] == "http://localhost:11434/v1"


def test_gemini_audio_client_traces_under_its_name_and_respects_lockdown(monkeypatch):
    import ai_trace
    from contextlib import contextmanager
    names = []

    @contextmanager
    def span(kind, name, **kwargs):
        names.append(name)
        yield SimpleNamespace(set_output=lambda *a, **k: None)
    monkeypatch.setattr(ai_trace, "span", span)
    raw = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw: SimpleNamespace(text="{}")))
    monkeypatch.setattr(credentials, "build_gemini_client", lambda: raw)
    tm.gemini_client("gemini.people_matcher.run_voice_match").models.generate_content(model="m", contents=["clip"])
    assert names == ["gemini.people_matcher.run_voice_match"]
    monkeypatch.undo()  # restore the real client builder, which checks lockdown first
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    with pytest.raises(policy.LockdownError):
        tm.gemini_client("x")
