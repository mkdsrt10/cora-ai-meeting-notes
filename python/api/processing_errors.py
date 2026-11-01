"""The one mapping from a processing failure to the response the Electron
Processing queue acts on: {"error", "code", "retryable"} plus an HTTP status.

  code                     retryable  status
  no_audio                 false      404
  corrupted_audio          false      422
  provider_auth            false      502
  provider_not_configured  false      412
  lockdown                 false      403
  missing_dependency       false      501
  provider_unavailable     true       503
  busy                     true       409
  internal                 true       500

`error` is a fixed, plain message per code (naming the provider where known);
it never carries exception text, so no transcript, notes, prompt or provider
response body can reach the queue or the UI.
"""
from __future__ import annotations

from typing import Any

from pipeline import errors

STATUS = {
    "no_audio": 404,
    "corrupted_audio": 422,
    "provider_auth": 502,
    "provider_not_configured": 412,
    "lockdown": 403,
    "missing_dependency": 501,
    "provider_unavailable": 503,
    "busy": 409,
    "internal": 500,
}


def _chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _typed(exc: BaseException) -> errors.ProcessingError | None:
    import policy
    import processing
    if isinstance(exc, errors.ProcessingError):
        return exc
    if isinstance(exc, policy.LockdownError):
        err = errors.ProcessingError("Cloud processing is disabled by enterprise lockdown. Use an on-device model.")
        err.code, err.retryable = "lockdown", False
        return err
    if isinstance(exc, processing.ProcessingBusyError):
        err = errors.ProcessingError("Another processing job is running; this one will be retried when it finishes.")
        err.code, err.retryable = "busy", True
        return err
    if isinstance(exc, ImportError):
        return errors.MissingDependencyError(getattr(exc, "name", None) or "")
    if type(exc).__name__ == "DefaultCredentialsError":  # google.auth: no Gemini credentials
        return errors.ProviderNotConfiguredError("gemini")
    return errors.from_provider(exc, None)


def classify(exc: BaseException) -> tuple[int, dict[str, Any]]:
    """(status, body) for any exception raised while processing a Recording."""
    for link in _chain(exc):
        typed = _typed(link)
        if typed is not None:
            return STATUS[typed.code], {"error": str(typed), "code": typed.code, "retryable": typed.retryable}
    internal = errors.ProcessingError()
    return STATUS["internal"], {"error": str(internal), "code": "internal", "retryable": True}
