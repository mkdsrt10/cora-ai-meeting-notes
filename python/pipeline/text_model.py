"""Text model: the one way Cora calls a text-generation model.

    with text_model(profile) as model:
        reply = model.complete(prompt, system=..., json=True, max_tokens=..., trace="notes.chunk.0")

The Processing profile's provider picks the adapter (one rule, whatever the
mode says), so one run never splits work across providers. Behind the
interface this module owns: lockdown (policy.provider_allowed), the local AI
trace span, model defaults, JSON repair, and retries with backoff for remote
adapters. A local MLX model loads on first use and is released when the
context exits, so several passes share one load.

Providers (see GLOSSARY.md): local_mlx, openai_compatible (OpenAI-compatible
presets: openai, openrouter, groq, ollama, lmstudio, custom), anthropic, gemini.
"""
from __future__ import annotations

import json as _json
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

import ai_trace
import policy

LOCAL_DEFAULT = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
ANTHROPIC_DEFAULT = "claude-sonnet-5-5"
GEMINI_DEFAULTS = {"vertex": "gemini-3.8-flash", "ai_studio": "gemini-3.7-flash"}
# OpenAI-compatible preset -> (default base URL, default model). Every one is
# served by the same adapter: POST {base_url}/chat/completions.
OPENAI_COMPATIBLE = {
    "openai": ("https://api.openai.com/v1", "gpt-4o"),
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "ollama": ("http://localhost:11434/v1", "llama3"),
    "lmstudio": ("http://localhost:1234/v1", "default"),
    "custom": ("", "llama3"),
}
PRESETS = ("local_mlx", "gemini", "anthropic", *OPENAI_COMPATIBLE)
REMOTE_CHAR_BUDGET = 48000  # conservative portable prompt budget for hosted models

ATTEMPTS = 3
BACKOFF_S = (2.0, 6.0)
RETRY_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
_sleep: Callable[[float], None] = time.sleep


def provider_of(preset: str) -> str:
    """Provider (adapter family) for a profile's provider value."""
    if preset in OPENAI_COMPATIBLE:
        return "openai_compatible"
    if preset in {"gemini", "vertex", "ai_studio"}:
        return "gemini"
    if preset in {"local_mlx", "anthropic"}:
        return preset
    raise ValueError(f"Unknown text model provider: {preset}")


def resolve_base_url(preset: str, url: Optional[str] = None) -> str:
    """The one base-URL rule for an OpenAI-compatible preset: the given
    (saved or entered) URL, else the preset's default, without a trailing
    slash. "" for `custom` with nothing entered."""
    return ((url or "").strip() or OPENAI_COMPATIBLE[preset][0]).rstrip("/")


def gemini_default(backend: Optional[str] = None) -> str:
    """Default Gemini model for a Gemini backend (vertex or ai_studio)."""
    if backend is None:
        import credentials
        backend = credentials.get_public_status().get("provider")
    return GEMINI_DEFAULTS["vertex" if backend == "vertex" else "ai_studio"]


def default_model(preset: str) -> str:
    """The one model-defaults table."""
    if preset in OPENAI_COMPATIBLE:
        return OPENAI_COMPATIBLE[preset][1]
    kind = provider_of(preset)
    if kind == "gemini":
        return gemini_default()
    return LOCAL_DEFAULT if kind == "local_mlx" else ANTHROPIC_DEFAULT


_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_json(text: str) -> Any:
    """A model's JSON reply as a dict or list. Tolerates thinking blocks,
    code fences and output cut off at the token limit (json_repair).
    Raises ValueError when there is no JSON object or list to recover."""
    clean = _FENCE.sub("", _THINK.sub("", text or "").strip()).strip()
    try:
        value = _json.loads(clean)
    except ValueError:
        import json_repair
        value = json_repair.loads(clean) if clean else None
    if not isinstance(value, (dict, list)):
        raise ValueError("Model reply is not a JSON object or list")
    return value


class TextModel:
    """See the module docstring. `fits(text)` says whether one prompt fits
    this model's context; `stats` accumulates usage across calls."""

    def __init__(self, adapter: Any, *, provider: str, model: str) -> None:
        self._adapter = adapter
        self.provider = provider
        self.model = model
        self.local = provider == "local_mlx"
        self.stats: dict[str, Any] = {"calls": 0, "output_tokens": 0, "finish_reason": None}

    def __enter__(self) -> "TextModel":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._adapter.close()

    def complete(self, prompt: str, *, system: str = "", json: bool = False, max_tokens: int = 1500,
                 trace: str = "llm", template: Optional[str] = None) -> Any:
        with ai_trace.span("llm", trace, provider=self._adapter.trace_provider, model=self.model,
                           input={"system": system, "prompt": prompt}, params={"max_tokens": max_tokens},
                           prompt_template=template or system or None) as span:
            text, metrics = self._adapter.complete(prompt, system=system, max_tokens=max_tokens, trace=trace)
            span.set_output(text, **{k: v for k, v in metrics.items() if v is not None})
        self.stats["calls"] += 1
        self.stats["output_tokens"] += metrics.get("output_tokens") or 0
        self.stats["finish_reason"] = metrics.get("finish_reason")
        text = _THINK.sub("", text or "").replace("<|im_end|>", "").strip()
        return parse_json(text) if json else text

    def fits(self, text: str, *, reserve: int = 2000) -> bool:
        return self._adapter.fits(text, reserve)


def text_model(profile: dict[str, Any], *, connection: Optional[dict[str, Any]] = None) -> TextModel:
    """The Text model for a Processing profile (needs only `provider` and
    `model`). `connection` replaces the saved credentials, for Settings'
    connection tests (api_key, base_url, or a Gemini `client`).
    Raises policy.LockdownError for a remote provider under lockdown."""
    preset = profile.get("provider") or "local_mlx"
    preset = "gemini" if preset in {"vertex", "ai_studio"} else preset
    kind = provider_of(preset)
    settings = dict(connection) if connection is not None else _saved(preset)
    model = profile.get("model") or settings.get("model") or default_model(preset)
    if kind == "openai_compatible":
        settings["base_url"] = resolve_base_url(preset, settings.get("base_url"))
    if not policy.provider_allowed(preset, settings.get("base_url")):
        raise policy.LockdownError(f"Text model provider '{preset}' is disabled by enterprise lockdown.")
    return TextModel(_adapter(preset, model, settings), provider=preset, model=model)


def _saved(preset: str) -> dict[str, Any]:
    if preset == "local_mlx":
        import db
        return {"model": db.get_setting("liquid_model", "")}
    import credentials
    return credentials.provider_settings(preset)


def _adapter(preset: str, model: str, settings: dict[str, Any]) -> Any:
    kind = provider_of(preset)
    if kind == "local_mlx":
        return MlxText(model)
    if kind == "anthropic":
        return AnthropicText(model, settings.get("api_key") or "")
    if kind == "gemini":
        return GeminiText(model, settings.get("client"))
    return OpenAICompatibleText(preset, settings["base_url"], settings.get("api_key") or "", model)


# ---- listing a provider's models (Settings -> "Load models") -------------------

MODELS_TIMEOUT_S = 10


class ModelListError(RuntimeError):
    """A provider's model list could not be read. The message is safe to show:
    it never carries the provider's response body or the key."""


ANTHROPIC_API = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


def candidate_connection(preset: str, *, base_url: Optional[str] = None,
                         api_key: Optional[str] = None) -> dict[str, str]:
    """What Settings entered, completed from what is saved: {base_url, api_key}
    for an OpenAI-compatible preset or Anthropic. A blank key means "keep the
    saved key", but only for the saved base URL, so a saved key is never sent
    to a newly typed host. Raises ValueError for an unsafe base URL."""
    saved = _saved(preset)
    key = (api_key or "").strip()
    if preset == "anthropic":
        return {"base_url": ANTHROPIC_API, "api_key": key or saved.get("api_key") or ""}
    if preset not in OPENAI_COMPATIBLE:
        raise ValueError(f"Unknown OpenAI-compatible preset: {preset}")
    saved_url = resolve_base_url(preset, saved.get("base_url"))
    url = resolve_base_url(preset, base_url) if (base_url or "").strip() else saved_url
    if not url:
        raise ValueError("Base URL cannot be empty.")
    import credentials
    url = credentials.validate_llm_base_url(url)
    if not key and url == saved_url:
        key = saved.get("api_key") or ""
    return {"base_url": url, "api_key": key}


def list_models(preset: str, *, base_url: Optional[str] = None, api_key: Optional[str] = None) -> list[str]:
    """Model ids a provider offers (GET {base_url}/models), using the entered
    key/base URL completed from the saved ones (candidate_connection).
    Raises policy.LockdownError, ValueError (bad URL) or ModelListError."""
    import requests
    from urllib.parse import urlparse
    conn = candidate_connection(preset, base_url=base_url, api_key=api_key)
    url, key = conn["base_url"], conn["api_key"]
    if not policy.provider_allowed(preset, url):
        raise policy.LockdownError(f"Provider '{preset}' is disabled by enterprise lockdown.")
    host = urlparse(url).hostname or "the endpoint"
    if preset == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION} if key else {}
    else:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        res = requests.get(f"{url}/models", headers=headers, timeout=MODELS_TIMEOUT_S)
    except requests.Timeout:
        raise ModelListError(f"{host} did not answer in {MODELS_TIMEOUT_S}s.") from None
    except requests.RequestException:
        raise ModelListError(f"Could not reach {host}. Is it running?") from None
    if res.status_code in (401, 403):
        raise ModelListError("The provider rejected the API key.")
    if res.status_code == 404:
        raise ModelListError("This endpoint has no model list; type the model name.")
    if res.status_code >= 400:
        raise ModelListError(f"The provider returned HTTP {res.status_code}.")
    try:
        data = res.json()
    except ValueError:
        raise ModelListError("The provider's model list was not JSON.") from None
    items = data.get("data") if isinstance(data, dict) else None
    return sorted({str(m["id"]) for m in items or [] if isinstance(m, dict) and m.get("id")})


# ---- retries --------------------------------------------------------------------

def _transient(exc: Exception) -> bool:
    import requests
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    status = getattr(getattr(exc, "response", None), "status_code", None) or getattr(exc, "code", None)
    return status in RETRY_STATUS


def _retrying(call: Callable[[], Any]) -> Any:
    for attempt in range(ATTEMPTS):
        try:
            return call()
        except Exception as exc:
            if attempt == ATTEMPTS - 1 or not _transient(exc):
                raise
            print(f"[Text model] transient error, retrying ({attempt + 1}/{ATTEMPTS - 1}): {type(exc).__name__}",
                  flush=True)
            _sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
    raise AssertionError("unreachable")


def _post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    import requests

    def call() -> dict[str, Any]:
        res = requests.post(url, headers=headers, json=payload, timeout=90)
        res.raise_for_status()
        return res.json()
    return _retrying(call)


# ---- adapters ---------------------------------------------------------------------
# Each adapter: complete(prompt, *, system, max_tokens, trace) -> (text, metrics),
# fits(text, reserve) -> bool, close(), and trace_provider.

class _Remote:
    def fits(self, text: str, reserve: int) -> bool:
        return len(text) <= REMOTE_CHAR_BUDGET

    def close(self) -> None:
        pass


class OpenAICompatibleText(_Remote):
    """OpenAI, OpenRouter, Groq, Ollama, LM Studio, LiteLLM, any /chat/completions."""

    def __init__(self, preset: str, base_url: str, api_key: str, model: str) -> None:
        if not base_url:
            raise RuntimeError("Custom model endpoint has no base URL. Set it in Settings -> Models.")
        self.trace_provider, self.base_url, self.api_key, self.model = preset, base_url, api_key, model

    def complete(self, prompt: str, *, system: str, max_tokens: int, trace: str) -> tuple[str, dict[str, Any]]:
        if self.trace_provider in {"openai", "openrouter", "groq"} and not self.api_key:
            raise RuntimeError(f"{self.trace_provider} API key is not configured. Set it in Settings -> Models.")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        data = _post(f"{self.base_url}/chat/completions", headers,
                     {"model": self.model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens})
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        return ((choice.get("message") or {}).get("content") or "",
                {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                 "finish_reason": choice.get("finish_reason")})


class AnthropicText(_Remote):
    trace_provider = "anthropic"
    URL = f"{ANTHROPIC_API}/messages"

    def __init__(self, model: str, api_key: str) -> None:
        self.model, self.api_key = model, api_key

    def complete(self, prompt: str, *, system: str, max_tokens: int, trace: str) -> tuple[str, dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("Anthropic API key is not configured. Set it in Settings -> Models.")
        headers = {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
        payload: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens}
        if system:
            payload["system"] = system
        payload["messages"] = [{"role": "user", "content": prompt}]
        data = _post(self.URL, headers, payload)
        usage = data.get("usage") or {}
        return ("".join(c.get("text", "") for c in data.get("content", [])),
                {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                 "finish_reason": data.get("stop_reason")})


class GeminiText(_Remote):
    trace_provider = "gemini"

    def __init__(self, model: str, client: Any = None) -> None:
        self.model, self._client = model, client

    def complete(self, prompt: str, *, system: str, max_tokens: int, trace: str) -> tuple[str, dict[str, Any]]:
        if self._client is None:
            import credentials
            self._client = credentials.build_gemini_client()
        res = _retrying(lambda: self._client.models.generate_content(
            model=self.model, contents=prompt,
            config={"system_instruction": system or None, "max_output_tokens": max_tokens}))
        return (res.text.strip() if res and res.text else ""), gemini_usage(res)


class MlxText:
    """Local MLX chat model: loaded on first use, released by close()."""
    trace_provider = "mlx"

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self._model = self._tokenizer = None

    def _load(self) -> None:
        if self._model is None:
            import mlx_lm
            with ai_trace.span("model_load", "model.load", provider="mlx", model=self.model_id):
                self._model, self._tokenizer = mlx_lm.load(self.model_id)

    def _chat(self, prompt: str, system: str) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        try:
            return self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            return "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages) + "<|im_start|>assistant\n"

    def complete(self, prompt: str, *, system: str, max_tokens: int, trace: str) -> tuple[str, dict[str, Any]]:
        """Uses stream_generate (what mlx_lm.generate does internally) so the
        final response's token counts, throughput and peak Metal memory can
        be traced for benchmarking."""
        import mlx_lm
        from .config import _clear_mlx_cache
        self._load()
        text, last = "", None
        for last in mlx_lm.stream_generate(self._model, self._tokenizer, self._chat(prompt, system), max_tokens=max_tokens):
            text += last.text
        metrics: dict[str, Any] = {}
        if last is not None:
            metrics = dict(input_tokens=last.prompt_tokens, output_tokens=last.generation_tokens,
                           prompt_tps=round(last.prompt_tps, 2), generation_tps=round(last.generation_tps, 2),
                           peak_memory_mb=round(last.peak_memory * 1000, 1), finish_reason=last.finish_reason)
        _clear_mlx_cache()  # reclaim cached Metal buffers between calls (see config._clear_mlx_cache)
        return text, metrics

    def fits(self, text: str, reserve: int) -> bool:
        self._load()
        configured = getattr(getattr(self._model, "args", None), "max_position_embeddings", None) or 4096
        return len(self._tokenizer.encode(self._chat(text, ""))) + reserve <= min(8192, int(configured))

    def close(self) -> None:
        if self._model is not None:
            from .config import _release_mlx_model
            _release_mlx_model(self._model, self._tokenizer)
            self._model = self._tokenizer = None


class FakeText:
    """Test adapter: `reply` is a string, a list of strings (one per call) or
    a callable(prompt, system=, max_tokens=, trace=) -> str. `fit(text)` stands
    in for the context-window check. Records calls."""
    trace_provider = "fake"

    def __init__(self, reply: Any = "", *, fit: Callable[[str], bool] = lambda text: True) -> None:
        self._reply, self.fit = reply, fit
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def complete(self, prompt: str, *, system: str, max_tokens: int, trace: str) -> tuple[str, dict[str, Any]]:
        self.calls.append(dict(prompt=prompt, system=system, max_tokens=max_tokens, trace=trace))
        if callable(self._reply):
            return self._reply(prompt, system=system, max_tokens=max_tokens, trace=trace), {}
        if isinstance(self._reply, list):
            return self._reply.pop(0), {}
        return self._reply, {}

    def fits(self, text: str, reserve: int) -> bool:
        return self.fit(text)

    def close(self) -> None:
        self.closed = True


# ---- Gemini client for Gemini-only audio features ------------------------------------

def gemini_usage(response: Any) -> dict[str, Any]:
    meta = getattr(response, "usage_metadata", None)
    return {"input_tokens": getattr(meta, "prompt_token_count", None),
            "output_tokens": getattr(meta, "candidates_token_count", None)}


class _TracedModels:
    def __init__(self, models: Any, trace: str) -> None:
        self._models, self._trace = models, trace

    def __getattr__(self, name: str) -> Any:
        return getattr(self._models, name)

    def generate_content(self, *, model: str, contents: Any, config: Any = None, **kwargs: Any) -> Any:
        # Audio/image bytes are fingerprinted by ai_trace, never stored.
        with ai_trace.span("llm", self._trace, provider="gemini", model=model,
                           input={"contents": contents}, params={"config": config}) as span:
            response = self._models.generate_content(model=model, contents=contents, config=config, **kwargs)
            span.set_output(getattr(response, "text", None), **gemini_usage(response))
        return response


class _TracedClient:
    def __init__(self, client: Any, trace: str) -> None:
        self._client = client
        self.models = _TracedModels(client.models, trace)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def gemini_client(trace: str) -> Any:
    """Authenticated google-genai client for the Gemini-only audio features
    (whole-file diarization, voice matching). Every generate_content call is
    traced under `trace`. Raises policy.LockdownError under lockdown."""
    import credentials
    return _TracedClient(credentials.build_gemini_client(), trace)


def caller_trace_name() -> str:
    """gemini.<module>.<function> of whoever called the caller (legacy get_client)."""
    import inspect
    frame = inspect.stack()[2]
    return f"gemini.{Path(frame.filename).stem}.{frame.function}"
