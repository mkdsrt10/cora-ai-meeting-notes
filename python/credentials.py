#!/usr/bin/env python3
"""Secure credentials management for Cora.

Supports:
1. Google Cloud Vertex AI (via ADC, Service Account JSON, or Vertex API key).
2. Google AI Studio (via API key).

Security model:
- Primary storage: macOS Keychain via `/usr/bin/security` (encrypted by Apple Secure Enclave / user login keychain).
- Persistence fallback: `~/.config/cora/credentials.json` with restricted filesystem permissions (directory 0700, file 0600).
- Automatic detection: Discovers existing `gcloud` Application Default Credentials (ADC) and active gcloud projects.
- Database sanitization: Never stores API keys or service account private keys in SQLite plaintext.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import policy

KEYCHAIN_SERVICE = "ai.cora.desktop"
CONFIG_DIR = Path.home() / ".config" / "cora"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
DEFAULT_LOCATION = "global"
DEFAULT_VERTEX_MODEL = "gemini-3.8-flash"
DEFAULT_AI_STUDIO_MODEL = "gemini-3.7-flash"


def get_default_model() -> str:
    """Return the optimal model for the current provider."""
    status = get_public_status()
    if status.get("provider") == "vertex":
        return DEFAULT_VERTEX_MODEL
    return DEFAULT_AI_STUDIO_MODEL


DEFAULT_MODEL = DEFAULT_VERTEX_MODEL


def _keychain_available() -> bool:
    """Check if macOS security CLI is available."""
    return sys.platform == "darwin" and Path("/usr/bin/security").exists()


def _security_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _keychain_set(account: str, secret: str, service: str = KEYCHAIN_SERVICE) -> bool:
    """Save a secret to macOS Keychain.

    The command goes to `security -i` over stdin so the secret never appears
    in argv (visible to every local user via `ps`). Piping just the password
    to `add-generic-password -w` is not an option: it silently truncates at
    128 bytes, which corrupts service-account JSON.
    """
    if not _keychain_available() or not secret:
        return False
    if "\n" in secret or "\r" in secret:
        try:
            secret = json.dumps(json.loads(secret), separators=(",", ":"))
        except ValueError:
            return False
    command = (
        f"add-generic-password -U -s {_security_quote(service)} "
        f"-a {_security_quote(account)} -w {_security_quote(secret)}\n"
    )
    try:
        result = subprocess.run(
            ["/usr/bin/security", "-i"],
            input=command,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except Exception:
        return False


def _keychain_get(account: str, service: str = KEYCHAIN_SERVICE) -> Optional[str]:
    """Retrieve a secret from macOS Keychain."""
    if not _keychain_available():
        return None
    try:
        output = subprocess.check_output(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
            ],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return output if output else None
    except Exception:
        return None


def _keychain_delete(account: str, service: str = KEYCHAIN_SERVICE) -> bool:
    """Remove a secret from macOS Keychain."""
    if not _keychain_available():
        return False
    try:
        subprocess.run(
            [
                "/usr/bin/security",
                "delete-generic-password",
                "-s",
                service,
                "-a",
                account,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _read_secure_file() -> dict[str, Any]:
    """Read the restricted credentials file (~/.config/cora/credentials.json)."""
    if not CREDENTIALS_FILE.exists():
        return {}
    try:
        return json.loads(CREDENTIALS_FILE.read_text())
    except Exception:
        return {}


def _write_secure_file(data: dict[str, Any]) -> bool:
    """Write credentials to file with 0700 dir and 0600 file permissions."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(CONFIG_DIR, 0o700)

        tmp_file = CONFIG_DIR / f"credentials.{os.getpid()}.tmp"
        # Create with 0600 up front — write_text() then chmod leaves a window
        # where the secrets sit in a world-readable file.
        fd = os.open(tmp_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(data, indent=2) + "\n")
        tmp_file.replace(CREDENTIALS_FILE)
        os.chmod(CREDENTIALS_FILE, 0o600)
        return True
    except Exception as exc:
        print(f"[credentials] Failed to write secure credentials file: {exc}", file=sys.stderr)
        return False


def detect_gcloud_project() -> Optional[str]:
    """Detect active Google Cloud project from env, gcloud CLI, or config files."""
    for var in ("GOOGLE_CLOUD_PROJECT", "CLOUDSDK_CORE_PROJECT", "GCLOUD_PROJECT"):
        val = os.environ.get(var)
        if val:
            return val.strip()

    gcloud_bin = shutil.which("gcloud") or "/opt/homebrew/bin/gcloud"
    if Path(gcloud_bin).exists():
        try:
            output = subprocess.check_output(
                [gcloud_bin, "config", "get-value", "project"],
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).decode().strip()
            if output and output != "(unset)":
                return output
        except Exception:
            pass

    # Check default config file directly
    active_config_path = Path.home() / ".config/gcloud/active_config"
    if active_config_path.exists():
        cfg_name = active_config_path.read_text().strip() or "default"
        cfg_file = Path.home() / f".config/gcloud/configurations/config_{cfg_name}"
        if cfg_file.exists():
            for line in cfg_file.read_text().splitlines():
                if line.strip().startswith("project"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        return parts[1].strip()

    return None


def has_gcloud_adc() -> bool:
    """Check if Application Default Credentials exist."""
    env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if env_path and Path(env_path).exists():
        return True
    adc_standard = Path.home() / ".config/gcloud/application_default_credentials.json"
    return adc_standard.exists()


_PUBLIC_STATUS_CACHE_SECONDS = 30
_public_status_cache: tuple[float, dict[str, Any]] | None = None


def get_public_status() -> dict[str, Any]:
    """Cached wrapper around _compute_public_status() — that function shells
    out to the macOS Keychain and gcloud several times over (a few hundred
    ms to ~1s total), and this is called on every /api/dashboard poll
    (every 4s while a recording is processing). Credential configuration
    essentially never changes mid-session, so a short cache avoids paying
    that cost repeatedly."""
    global _public_status_cache
    now = time.time()
    if _public_status_cache and (now - _public_status_cache[0]) < _PUBLIC_STATUS_CACHE_SECONDS:
        return _public_status_cache[1]
    status = _compute_public_status()
    _public_status_cache = (now, status)
    return status


def _invalidate_public_status_cache() -> None:
    global _public_status_cache
    _public_status_cache = None


def _compute_public_status() -> dict[str, Any]:
    """Return a safe status dictionary suitable for UI and logs (no secrets exposed)."""
    file_cfg = _read_secure_file()
    keychain_provider = _keychain_get("auth_provider")
    keychain_project = _keychain_get("vertex_project")
    keychain_location = _keychain_get("vertex_location")
    keychain_auth_type = _keychain_get("vertex_auth_type")

    detected_project = detect_gcloud_project()
    has_adc = has_gcloud_adc()

    provider = (
        keychain_provider
        or file_cfg.get("provider")
        or ("vertex" if (has_adc or detected_project) else "ai_studio")
    )

    vertex_project = (
        keychain_project
        or file_cfg.get("vertex_project")
        or detected_project
        or ""
    )

    vertex_location = (
        keychain_location
        or file_cfg.get("vertex_location")
        or os.environ.get("GOOGLE_CLOUD_LOCATION")
        or DEFAULT_LOCATION
    )

    vertex_auth_type = (
        keychain_auth_type
        or file_cfg.get("vertex_auth_type")
        or ("adc" if has_adc else "service_account")
    )

    has_sa = bool(
        _keychain_get("vertex_service_account_json")
        or file_cfg.get("vertex_service_account_json")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    )

    has_vertex_api_key = bool(
        _keychain_get("vertex_api_key")
        or file_cfg.get("vertex_api_key")
    )

    has_ai_studio_key = bool(
        _keychain_get("gemini_api_key")
        or file_cfg.get("gemini_api_key")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )

    has_anthropic_key = bool(
        _keychain_get("anthropic_api_key")
        or file_cfg.get("anthropic_api_key")
        or os.environ.get("ANTHROPIC_API_KEY")
    )

    has_openai_key = bool(
        _keychain_get("openai_api_key")
        or file_cfg.get("openai_api_key")
        or os.environ.get("OPENAI_API_KEY")
    )

    custom_url = _keychain_get("custom_llm_url") or file_cfg.get("custom_llm_url") or os.environ.get("CUSTOM_LLM_URL") or ""
    has_custom_llm = bool(custom_url)

    notes_provider = file_cfg.get("notes_llm_provider") or "local_mlx"

    is_configured = False
    if provider == "vertex":
        is_configured = bool(vertex_project and (has_adc or has_sa or has_vertex_api_key))
    elif provider == "ai_studio":
        is_configured = has_ai_studio_key
    elif provider == "anthropic":
        is_configured = has_anthropic_key
    elif provider == "openai":
        is_configured = has_openai_key
    elif provider == "custom":
        is_configured = has_custom_llm

    return {
        "provider": provider,
        "notes_llm_provider": notes_provider,
        "vertex_project": vertex_project,
        "vertex_location": vertex_location,
        "vertex_auth_type": vertex_auth_type,
        "has_adc": has_adc,
        "has_service_account": has_sa,
        "has_vertex_api_key": has_vertex_api_key,
        "has_ai_studio_key": has_ai_studio_key,
        "has_anthropic_key": has_anthropic_key,
        "has_openai_key": has_openai_key,
        "has_custom_llm": has_custom_llm,
        "custom_llm_url": custom_url,
        "anthropic_model": file_cfg.get("anthropic_model", "claude-3-7-sonnet-20250219"),
        "openai_model": file_cfg.get("openai_model", "gpt-4o"),
        "custom_llm_model": file_cfg.get("custom_llm_model", "llama3"),
        "detected_gcloud_project": detected_project,
        "is_configured": is_configured,
        "storage_mode": "macOS Keychain (Secure Enclave) + 0600 file",
        "keychain_active": _keychain_available(),
    }


def save_anthropic_credentials(api_key: str, model: str = "claude-3-7-sonnet-20250219") -> None:
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("Anthropic API key cannot be empty.")
    _keychain_set("anthropic_api_key", api_key)
    file_cfg = _read_secure_file()
    file_cfg["anthropic_api_key"] = api_key
    file_cfg["anthropic_model"] = model.strip() or "claude-3-7-sonnet-20250219"
    file_cfg["notes_llm_provider"] = "anthropic"
    _write_secure_file(file_cfg)
    _invalidate_public_status_cache()


def validate_llm_base_url(base_url: str) -> str:
    """Allow only https endpoints, or plain http to this machine (Ollama etc.).

    API keys are sent to this URL, so a plaintext or attacker-chosen remote
    host would leak them.
    """
    from urllib.parse import urlparse
    parsed = urlparse(base_url.strip())
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid base URL.")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError("Base URL must use https (plain http is allowed only for localhost).")
    return base_url.strip().rstrip("/")


def save_openai_credentials(api_key: str, model: str = "gpt-4o", base_url: str = "https://api.openai.com/v1") -> None:
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("OpenAI API key cannot be empty.")
    _keychain_set("openai_api_key", api_key)
    file_cfg = _read_secure_file()
    file_cfg["openai_api_key"] = api_key
    file_cfg["openai_model"] = model.strip() or "gpt-4o"
    file_cfg["openai_base_url"] = validate_llm_base_url(base_url or "https://api.openai.com/v1")
    file_cfg["notes_llm_provider"] = "openai"
    _write_secure_file(file_cfg)
    _invalidate_public_status_cache()


def save_custom_llm_credentials(base_url: str, api_key: str = "", model: str = "") -> None:
    if not base_url.strip():
        raise ValueError("Base URL cannot be empty.")
    base_url = validate_llm_base_url(base_url)
    file_cfg = _read_secure_file()
    file_cfg["custom_llm_url"] = base_url
    file_cfg["custom_llm_key"] = api_key.strip()
    file_cfg["custom_llm_model"] = model.strip() or "default"
    file_cfg["notes_llm_provider"] = "custom"
    _write_secure_file(file_cfg)
    _invalidate_public_status_cache()


def save_notes_provider(provider: str) -> None:
    file_cfg = _read_secure_file()
    file_cfg["notes_llm_provider"] = provider
    _write_secure_file(file_cfg)
    _invalidate_public_status_cache()


def call_configured_llm(
    prompt: str,
    system_prompt: str = "",
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 4096,
    trace_name: str = "configured_llm",
) -> str:
    """Universal caller for user-configured frontier or custom LLMs.

    Every call is recorded in the local AI trace (inputs, output, token
    usage, latency) under `trace_name`.
    """
    import ai_trace

    p = (provider or get_public_status().get("notes_llm_provider") or "local_mlx").lower()
    with ai_trace.span("llm", trace_name, provider=p, model=model,
                       input={"system": system_prompt, "prompt": prompt},
                       params={"max_tokens": max_tokens}, prompt_template=system_prompt or None) as trace:
        text, usage, used_model = _call_configured_llm(prompt, system_prompt, provider, model, max_tokens)
        trace.set_output(text, model=used_model, **usage)
    return text


def _call_configured_llm(
    prompt: str,
    system_prompt: str,
    provider: Optional[str],
    model: Optional[str],
    max_tokens: int,
) -> tuple[str, dict[str, Any], str]:
    """Returns (text, usage, model actually used)."""
    import requests
    status = get_public_status()
    file_cfg = _read_secure_file()
    p = (provider or status.get("notes_llm_provider") or "local_mlx").lower()
    if not policy.provider_allowed(p, file_cfg.get("custom_llm_url")):
        raise policy.LockdownError(f"LLM provider '{p}' is disabled by enterprise lockdown.")

    if p == "anthropic":
        key = _keychain_get("anthropic_api_key") or file_cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("Anthropic API key is not configured. Set it in Settings -> Models.")
        m = model or file_cfg.get("anthropic_model") or "claude-3-7-sonnet-20250219"
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": m,
            "max_tokens": max_tokens,
            "system": system_prompt or "You are an executive chief of staff. Produce clear, structured, and factual meeting notes.",
            "messages": [{"role": "user", "content": prompt}],
        }
        res = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=90)
        res.raise_for_status()
        data = res.json()
        usage = data.get("usage") or {}
        return ("".join(c.get("text", "") for c in data.get("content", [])),
                {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}, m)

    elif p == "openai":
        key = _keychain_get("openai_api_key") or file_cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OpenAI API key is not configured. Set it in Settings -> Models.")
        m = model or file_cfg.get("openai_model") or "gpt-4o"
        base_url = file_cfg.get("openai_base_url") or "https://api.openai.com/v1"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": m,
            "messages": [
                {"role": "system", "content": system_prompt or "You are an executive chief of staff. Produce clear, structured, and factual meeting notes."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        res = requests.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload, timeout=90)
        res.raise_for_status()
        data = res.json()
        return data["choices"][0]["message"]["content"], _openai_usage(data), m

    elif p == "custom":
        base_url = file_cfg.get("custom_llm_url") or "http://localhost:11434/v1"
        key = file_cfg.get("custom_llm_key", "")
        m = model or file_cfg.get("custom_llm_model") or "llama3"
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        payload = {
            "model": m,
            "messages": [
                {"role": "system", "content": system_prompt or "You are an executive chief of staff. Produce clear, structured, and factual meeting notes."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        res = requests.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload, timeout=90)
        res.raise_for_status()
        data = res.json()
        return data["choices"][0]["message"]["content"], _openai_usage(data), m

    elif p in {"vertex", "ai_studio", "gemini"}:
        client = get_client(traced=False)  # traced once, by call_configured_llm
        m = model or DEFAULT_MODEL
        full_content = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        res = client.models.generate_content(model=m, contents=full_content)
        return (res.text.strip() if res and res.text else ""), _gemini_usage(res), m

    else:
        raise ValueError(f"Unknown or local provider: {p}")


def _openai_usage(data: dict[str, Any]) -> dict[str, Any]:
    usage = data.get("usage") or {}
    return {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")}


def _gemini_usage(response: Any) -> dict[str, Any]:
    meta = getattr(response, "usage_metadata", None)
    return {
        "input_tokens": getattr(meta, "prompt_token_count", None),
        "output_tokens": getattr(meta, "candidates_token_count", None),
    }


class _TracedModels:
    """Wraps `client.models` so every generate_content call — diarization,
    voice matching, coaching, dataset tools — lands in the local AI trace
    without touching each caller. Audio/image bytes are fingerprinted,
    never stored."""

    def __init__(self, models: Any) -> None:
        self._models = models

    def __getattr__(self, name: str) -> Any:
        return getattr(self._models, name)

    def generate_content(self, *, model: str, contents: Any, config: Any = None, **kwargs: Any) -> Any:
        import inspect

        import ai_trace
        caller = inspect.stack()[1]
        name = f"gemini.{Path(caller.filename).stem}.{caller.function}"
        with ai_trace.span("llm", name, provider="gemini", model=model,
                           input={"contents": contents}, params={"config": config}) as trace:
            response = self._models.generate_content(model=model, contents=contents, config=config, **kwargs)
            trace.set_output(getattr(response, "text", None), **_gemini_usage(response))
        return response


class _TracedClient:
    def __init__(self, client: Any) -> None:
        self._client = client
        self.models = _TracedModels(client.models)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def save_vertex_credentials(
    project: str,
    location: str = DEFAULT_LOCATION,
    auth_type: str = "adc",
    service_account_json: Optional[str] = None,
    api_key: Optional[str] = None,
) -> None:
    """Save Vertex AI credentials securely into macOS Keychain and 0600 file."""
    project = (project or "").strip()
    location = (location or DEFAULT_LOCATION).strip()
    auth_type = (auth_type or "adc").strip().lower()

    if not project:
        raise ValueError("Google Cloud Project ID is required for Vertex AI.")

    # Validate service account JSON if provided
    sa_content = None
    if auth_type == "service_account":
        raw = (service_account_json or "").strip()
        if raw:
            # Could be a file path or direct JSON
            if Path(raw).exists():
                sa_content = Path(raw).read_text()
            else:
                sa_content = raw
            try:
                parsed = json.loads(sa_content)
                if not isinstance(parsed, dict) or "type" not in parsed:
                    raise ValueError("Service account JSON must be a valid GCP service account credential object.")
                sa_content = json.dumps(parsed)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid service account JSON: {exc}")

    # Save non-sensitive metadata in Keychain & file
    _keychain_set("auth_provider", "vertex")
    _keychain_set("vertex_project", project)
    _keychain_set("vertex_location", location)
    _keychain_set("vertex_auth_type", auth_type)

    if sa_content:
        _keychain_set("vertex_service_account_json", sa_content)
    if api_key:
        _keychain_set("vertex_api_key", api_key.strip())

    file_data = _read_secure_file()
    file_data.update({
        "provider": "vertex",
        "vertex_project": project,
        "vertex_location": location,
        "vertex_auth_type": auth_type,
    })
    if sa_content:
        file_data["vertex_service_account_json"] = sa_content
    elif "vertex_service_account_json" in file_data and auth_type != "service_account":
        del file_data["vertex_service_account_json"]

    if api_key:
        file_data["vertex_api_key"] = api_key.strip()

    _write_secure_file(file_data)
    _sanitize_db()
    _invalidate_public_status_cache()


def save_ai_studio_credentials(api_key: str) -> None:
    """Save Google AI Studio API key securely into macOS Keychain and 0600 file."""
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Gemini API key cannot be empty.")

    _keychain_set("auth_provider", "ai_studio")
    _keychain_set("gemini_api_key", key)

    file_data = _read_secure_file()
    file_data.update({
        "provider": "ai_studio",
        "gemini_api_key": key,
    })
    _write_secure_file(file_data)
    _sanitize_db()
    _invalidate_public_status_cache()


def _sanitize_db() -> None:
    """Remove any plaintext API keys from SQLite settings table."""
    try:
        import db
        with db.get_db() as conn:
            conn.execute("DELETE FROM settings WHERE key = 'gemini_api_key'")
            conn.commit()
    except Exception:
        pass


def get_client(traced: bool = True) -> Any:
    """Construct and return an authenticated google.genai.Client instance.

    By default the client's generate_content calls are recorded in the
    local AI trace (see _TracedClient).
    """
    client = _build_client()
    return _TracedClient(client) if traced else client


def _build_client() -> Any:
    policy.require_outbound_allowed("Google Gemini")
    from google import genai
    from google.oauth2 import service_account
    import google.auth

    status = get_public_status()
    provider = status.get("provider", "vertex")

    if provider == "vertex":
        project = (
            _keychain_get("vertex_project")
            or _read_secure_file().get("vertex_project")
            or status.get("vertex_project")
            or detect_gcloud_project()
        )
        location = (
            _keychain_get("vertex_location")
            or _read_secure_file().get("vertex_location")
            or status.get("vertex_location")
            or DEFAULT_LOCATION
        )
        auth_type = (
            _keychain_get("vertex_auth_type")
            or _read_secure_file().get("vertex_auth_type")
            or status.get("vertex_auth_type")
            or "adc"
        )

        sa_json = (
            _keychain_get("vertex_service_account_json")
            or _read_secure_file().get("vertex_service_account_json")
        )
        api_key = (
            _keychain_get("vertex_api_key")
            or _read_secure_file().get("vertex_api_key")
        )

        credentials = None
        if auth_type == "service_account" and sa_json:
            try:
                info = json.loads(sa_json)
                credentials = service_account.Credentials.from_service_account_info(
                    info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                if not project and "project_id" in info:
                    project = info["project_id"]
            except Exception as e:
                raise RuntimeError(f"Failed to load service account credentials: {e}")
        elif auth_type == "api_key" and api_key:
            return genai.Client(
                vertexai=True,
                project=project,
                location=location,
                api_key=api_key,
            )
        else:
            # ADC (Application Default Credentials)
            try:
                credentials, detected_proj = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                if not project and detected_proj:
                    project = detected_proj
            except Exception as e:
                raise RuntimeError(
                    f"Vertex AI requires Google Cloud credentials (ADC or service account): {e}"
                )

        if not project:
            raise RuntimeError("Google Cloud Project ID is not configured for Vertex AI.")

        from google.genai import types
        http_options = types.HttpOptions(timeout=600000)

        return genai.Client(
            vertexai=True,
            project=project,
            location=location,
            credentials=credentials,
            http_options=http_options,
        )

    else:
        # AI Studio
        key = (
            _keychain_get("gemini_api_key")
            or _read_secure_file().get("gemini_api_key")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        if not key:
            raise RuntimeError("Gemini API key is not configured.")
        from google.genai import types
        http_options = types.HttpOptions(timeout=600000)
        return genai.Client(api_key=key, http_options=http_options)


def test_credentials(
    provider: str,
    project: Optional[str] = None,
    location: Optional[str] = DEFAULT_LOCATION,
    auth_type: Optional[str] = "adc",
    service_account_json: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> tuple[bool, str]:
    """Test candidate credentials without saving them.

    Returns (success, message).
    """
    if not policy.provider_allowed(provider, location if provider == "custom" else None):
        return False, f"Provider '{provider}' is disabled by enterprise lockdown."
    if provider in {"openai", "custom"} and location:
        try:
            validate_llm_base_url(location)
        except ValueError as exc:
            return False, str(exc)
    from google import genai
    from google.oauth2 import service_account
    import google.auth

    try:
        if provider == "vertex":
            proj = (project or "").strip() or detect_gcloud_project()
            loc = (location or DEFAULT_LOCATION).strip()
            atype = (auth_type or "adc").strip().lower()

            if not proj:
                return False, "Project ID is required for Vertex AI."

            credentials = None
            if atype == "service_account":
                raw = (service_account_json or "").strip()
                if not raw:
                    return False, "Service account JSON is required."
                if Path(raw).exists():
                    raw = Path(raw).read_text()
                info = json.loads(raw)
                credentials = service_account.Credentials.from_service_account_info(
                    info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
            elif atype == "api_key":
                if not api_key:
                    return False, "Vertex API key is required."
                client = genai.Client(vertexai=True, project=proj, location=loc, api_key=api_key.strip())
            else:
                credentials, detected_proj = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                if not proj and detected_proj:
                    proj = detected_proj

            if atype != "api_key":
                client = genai.Client(vertexai=True, project=proj, location=loc, credentials=credentials)

            # Verification ping
            res = client.models.generate_content(
                model=DEFAULT_VERTEX_MODEL,
                contents="Ping. Respond with 'pong'.",
            )
            if not res or not res.text:
                return False, "Model did not return a response."
            return True, f"Connected to Vertex AI ({proj} / {loc}) successfully."

        elif provider in {"ai_studio", "gemini"}:
            k = (api_key or "").strip()
            if not k:
                return False, "Gemini API key cannot be empty."
            client = genai.Client(api_key=k)
            # Lightweight verification
            m = model or DEFAULT_AI_STUDIO_MODEL
            res = client.models.generate_content(
                model=m,
                contents="Ping. Respond with 'pong'.",
            )
            return True, f"Connected to Gemini AI Studio ({m}) successfully."

        elif provider == "anthropic":
            import requests
            k = (api_key or "").strip()
            if not k:
                return False, "Anthropic API key cannot be empty."
            headers = {
                "x-api-key": k,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            m = model or "claude-3-5-haiku-20241022"
            payload = {
                "model": m,
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Ping"}],
            }
            res = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=15)
            if res.status_code == 401:
                return False, "Invalid Anthropic API key."
            res.raise_for_status()
            return True, f"Connected to Anthropic Claude ({m}) successfully."

        elif provider == "openai":
            import requests
            k = (api_key or "").strip()
            if not k:
                return False, "OpenAI API key cannot be empty."
            burl = (location or "https://api.openai.com/v1").rstrip("/")
            headers = {
                "Authorization": f"Bearer {k}",
                "Content-Type": "application/json",
            }
            m = model or "gpt-4o-mini"
            payload = {
                "model": m,
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Ping"}],
            }
            res = requests.post(f"{burl}/chat/completions", headers=headers, json=payload, timeout=15)
            if res.status_code == 401:
                return False, "Invalid OpenAI API key."
            res.raise_for_status()
            return True, f"Connected to OpenAI ({m}) successfully."

        elif provider == "custom":
            import requests
            burl = (location or "").strip().rstrip("/")
            if not burl:
                return False, "Custom API Base URL cannot be empty (e.g. http://localhost:11434/v1)."
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key.strip()}"
            m = model or "default"
            payload = {
                "model": m,
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Ping"}],
            }
            res = requests.post(f"{burl}/chat/completions", headers=headers, json=payload, timeout=15)
            res.raise_for_status()
            return True, f"Connected to custom LLM endpoint ({burl}) successfully."

        else:
            return False, f"Unknown provider: {provider}"

    except Exception as exc:
        msg = getattr(exc, "message", None) or str(exc)
        return False, msg


def is_available() -> bool:
    """Check if AI is configured and credentials are functional."""
    try:
        client = get_client()
        return bool(client)
    except Exception:
        return False


if __name__ == "__main__":
    print(json.dumps(get_public_status(), indent=2))
