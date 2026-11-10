"""Typed processing failures, so callers (the /api/process-recording route,
via api.processing_errors) can tell permanent from transient without reading
exception text. Messages are fixed, user-facing and safe: never a transcript,
notes, prompt or a provider's response body (the original exception, when
any, is only chained as __cause__ for local debugging)."""
from __future__ import annotations

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "groq": "Groq",
    "ollama": "Ollama",
    "lmstudio": "LM Studio",
    "custom": "Your custom model endpoint",
    "openai_compatible": "Your OpenAI-compatible endpoint",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "vertex": "Google Gemini",
    "ai_studio": "Google Gemini",
    "local_mlx": "The local model",
}


def provider_label(provider: str | None) -> str:
    return PROVIDER_LABELS.get(provider or "", "The AI provider")


class ProcessingError(Exception):
    """Base: `code` and `retryable` are the contract with the Processing queue."""
    code = "internal"
    retryable = True
    default_message = "Processing failed unexpectedly. Details are in the logs."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class NoAudioError(ProcessingError, FileNotFoundError):
    code, retryable = "no_audio", False
    default_message = "No archived audio was found for this recording."


class CorruptedAudioError(ProcessingError):
    code, retryable = "corrupted_audio", False
    default_message = "This recording's audio could not be read; the file may be corrupted."


class MissingDependencyError(ProcessingError):
    code, retryable = "missing_dependency", False

    def __init__(self, component: str = "") -> None:
        self.component = component
        what = f" ({component} is missing)" if component else ""
        super().__init__(f"Processing isn't set up on this Mac{what}. Run setup again, "
                         "or choose a cloud provider in Settings.")


class ProviderError(ProcessingError, RuntimeError):
    def __init__(self, provider: str | None = None, message: str | None = None) -> None:
        self.provider = provider
        super().__init__(message or self.message_for(provider_label(provider)))

    def message_for(self, label: str) -> str:
        raise NotImplementedError


class ProviderAuthError(ProviderError):
    """The provider rejected the credentials (401/403), or none are set."""
    code, retryable = "provider_auth", False

    def message_for(self, label: str) -> str:
        return f"{label} rejected the request: the API key is missing or invalid. Check the key in Settings."


class ProviderNotConfiguredError(ProviderError):
    code, retryable = "provider_not_configured", False

    def message_for(self, label: str) -> str:
        return f"{label} is not set up. Configure it in Settings, or choose another provider."


class ProviderUnavailableError(ProviderError):
    """Network error, timeout, 429 or 5xx, after the adapter's own retries."""
    code, retryable = "provider_unavailable", True

    def message_for(self, label: str) -> str:
        return f"{label} is unavailable right now (network error, rate limit or server error). It will be retried."


class WindowedTranscriptionError(ProviderError):
    """A cloud Window was rejected and could be neither transcribed locally
    nor kept as a gap. Retrying sends the same audio for the same result."""
    code, retryable = "cloud_transcription_rejected", False

    def message_for(self, label: str) -> str:
        return ("The cloud transcription engine rejected part of this recording "
                "and no local model was available to fill in.")


AUTH_STATUS = frozenset({401, 403})


def status_of(exc: BaseException) -> int | None:
    """HTTP status of a requests / google-genai style error, if it has one."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    return status if isinstance(status, int) else None


def is_unavailable(exc: BaseException) -> bool:
    """Network failure, timeout, 408/409/429 or 5xx."""
    try:
        import requests
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
    except ImportError:  # pragma: no cover
        pass
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    status = status_of(exc)
    return status is not None and (status in {408, 409, 429} or 500 <= status < 600)


def from_provider(exc: BaseException, provider: str | None) -> ProviderError | None:
    """The typed error for a provider-call failure, or None when it is
    neither an auth failure nor a transient one."""
    if isinstance(exc, ProviderError):
        return exc
    if status_of(exc) in AUTH_STATUS:
        return ProviderAuthError(provider)
    if is_unavailable(exc):
        return ProviderUnavailableError(provider)
    return None
