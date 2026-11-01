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


def get_default_model() -> str:
    """Default Gemini model for the configured Gemini backend (see pipeline.text_model)."""
    from pipeline.text_model import gemini_default
    return gemini_default()


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
    from pipeline import text_model
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
        "gemini_model": file_cfg.get("gemini_model") or text_model.gemini_default(provider),
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
        "anthropic_model": file_cfg.get("anthropic_model") or text_model.ANTHROPIC_DEFAULT,
        "openai_model": file_cfg.get("openai_model") or text_model.default_model("openai"),
        "openai_base_url": file_cfg.get("openai_base_url") or text_model.OPENAI_COMPATIBLE["openai"][0],
        "custom_llm_model": file_cfg.get("custom_llm_model") or text_model.default_model("custom"),
        # Other OpenAI-compatible presets: which ones have a saved base URL.
        "openai_compatible_presets": {p: bool(file_cfg.get(f"{p}_base_url")) for p in ("openrouter", "groq", "ollama", "lmstudio")},
        "detected_gcloud_project": detected_project,
        "is_configured": is_configured,
        "storage_mode": "macOS Keychain (Secure Enclave) + 0600 file",
        "keychain_active": _keychain_available(),
    }


# Saved fields per text-model provider: (api key account, model field, base URL field, key env var).
# `custom` keeps its original field names; other OpenAI-compatible presets use <preset>_*.
_PROVIDER_FIELDS = {
    "anthropic": ("anthropic_api_key", "anthropic_model", None, "ANTHROPIC_API_KEY"),
    "openai": ("openai_api_key", "openai_model", "openai_base_url", "OPENAI_API_KEY"),
    "custom": ("custom_llm_key", "custom_llm_model", "custom_llm_url", None),
    "openrouter": ("openrouter_api_key", "openrouter_model", "openrouter_base_url", "OPENROUTER_API_KEY"),
    "groq": ("groq_api_key", "groq_model", "groq_base_url", "GROQ_API_KEY"),
    "ollama": ("ollama_api_key", "ollama_model", "ollama_base_url", None),
    "lmstudio": ("lmstudio_api_key", "lmstudio_model", "lmstudio_base_url", None),
    "gemini": (None, "gemini_model", None, None),
}
OPENAI_COMPATIBLE_PRESETS = tuple(p for p in _PROVIDER_FIELDS if p not in {"anthropic", "gemini"})


def provider_settings(provider: str) -> dict[str, Any]:
    """Saved api_key / model / base_url for one text-model provider ("" when unset).
    Keys come from the Keychain first, then the 0600 file, then the environment."""
    key_field, model_field, url_field, env = _PROVIDER_FIELDS[provider]
    file_cfg = _read_secure_file()
    api_key = ""
    if key_field:
        api_key = _keychain_get(key_field) or file_cfg.get(key_field) or (os.environ.get(env) if env else "") or ""
    base_url = ""
    if url_field:
        base_url = file_cfg.get(url_field) or ""
        if provider == "custom":
            base_url = _keychain_get("custom_llm_url") or base_url or os.environ.get("CUSTOM_LLM_URL", "")
    return {"api_key": api_key, "model": file_cfg.get(model_field) or "", "base_url": base_url}


def save_anthropic_credentials(api_key: str, model: str = "") -> None:
    from pipeline.text_model import ANTHROPIC_DEFAULT
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("Anthropic API key cannot be empty.")
    _keychain_set("anthropic_api_key", api_key)
    file_cfg = _read_secure_file()
    file_cfg["anthropic_api_key"] = api_key
    file_cfg["anthropic_model"] = model.strip() or ANTHROPIC_DEFAULT
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


def save_openai_compatible_credentials(preset: str, base_url: str = "", api_key: str = "", model: str = "") -> None:
    """Save an OpenAI-compatible preset (openai, openrouter, groq, ollama,
    lmstudio, custom). The key goes to the Keychain like every other key."""
    from pipeline.text_model import OPENAI_COMPATIBLE
    if preset not in OPENAI_COMPATIBLE_PRESETS:
        raise ValueError(f"Unknown OpenAI-compatible preset: {preset}")
    default_url, default_model = OPENAI_COMPATIBLE[preset]
    base_url = (base_url or default_url).strip()
    if not base_url:
        raise ValueError("Base URL cannot be empty.")
    base_url = validate_llm_base_url(base_url)
    api_key = api_key.strip()
    if preset in {"openai", "openrouter", "groq"} and not api_key:
        raise ValueError(f"{preset} API key cannot be empty.")
    key_field, model_field, url_field, _ = _PROVIDER_FIELDS[preset]
    file_cfg = _read_secure_file()
    if api_key:
        _keychain_set(key_field, api_key)
        file_cfg[key_field] = api_key
    else:
        _keychain_delete(key_field)
        file_cfg.pop(key_field, None)
    file_cfg[model_field] = model.strip() or default_model
    file_cfg[url_field] = base_url
    file_cfg["notes_llm_provider"] = preset
    _write_secure_file(file_cfg)
    _invalidate_public_status_cache()


def save_openai_credentials(api_key: str, model: str = "", base_url: str = "") -> None:
    save_openai_compatible_credentials("openai", base_url=base_url, api_key=api_key, model=model)


def save_custom_llm_credentials(base_url: str, api_key: str = "", model: str = "") -> None:
    if not base_url.strip():
        raise ValueError("Base URL cannot be empty.")
    save_openai_compatible_credentials("custom", base_url=base_url, api_key=api_key, model=model or "default")


def save_notes_provider(provider: str) -> None:
    file_cfg = _read_secure_file()
    file_cfg["notes_llm_provider"] = provider
    _write_secure_file(file_cfg)
    _invalidate_public_status_cache()


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
    """Gemini client for callers outside python/ core (plugins, tools).
    Core code uses pipeline.text_model.gemini_client(trace=...) instead."""
    from pipeline import text_model
    if not traced:
        return build_gemini_client()
    return text_model.gemini_client(text_model.caller_trace_name())


def build_gemini_client() -> Any:
    """Untraced google-genai client for the configured Gemini backend. Callers
    go through pipeline.text_model (text) or text_model.gemini_client (audio)."""
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
    base_url: Optional[str] = None,
) -> tuple[bool, str]:
    """Test candidate credentials without saving them: one tiny call through
    the Text model with these credentials in place of the saved ones.
    `location` is the Vertex region; `base_url` the OpenAI-compatible endpoint.

    Returns (success, message).
    """
    import requests

    from pipeline import text_model
    k = (api_key or "").strip()
    if provider in OPENAI_COMPATIBLE_PRESETS:
        base_url = (base_url or "").strip() or text_model.OPENAI_COMPATIBLE[provider][0]
        if not base_url:
            return False, "Custom API Base URL cannot be empty (e.g. http://localhost:11434/v1)."
        try:
            base_url = validate_llm_base_url(base_url)
        except ValueError as exc:
            return False, str(exc)
    if not policy.provider_allowed(provider, base_url):
        return False, f"Provider '{provider}' is disabled by enterprise lockdown."

    labels = {"anthropic": "Anthropic Claude", "openai": "OpenAI", "openrouter": "OpenRouter", "groq": "Groq",
              "ollama": "Ollama", "lmstudio": "LM Studio"}
    try:
        if provider == "vertex":
            from google import genai
            from google.oauth2 import service_account
            import google.auth
            proj = (project or "").strip() or detect_gcloud_project()
            loc = (location or DEFAULT_LOCATION).strip()
            atype = (auth_type or "adc").strip().lower()
            if not proj:
                return False, "Project ID is required for Vertex AI."
            if atype == "service_account":
                raw = (service_account_json or "").strip()
                if not raw:
                    return False, "Service account JSON is required."
                if Path(raw).exists():
                    raw = Path(raw).read_text()
                credentials = service_account.Credentials.from_service_account_info(
                    json.loads(raw), scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                client = genai.Client(vertexai=True, project=proj, location=loc, credentials=credentials)
            elif atype == "api_key":
                if not k:
                    return False, "Vertex API key is required."
                client = genai.Client(vertexai=True, project=proj, location=loc, api_key=k)
            else:
                credentials, detected_proj = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                proj = proj or detected_proj
                client = genai.Client(vertexai=True, project=proj, location=loc, credentials=credentials)
            profile, connection = {"provider": "gemini", "model": text_model.gemini_default("vertex")}, {"client": client}
            success = f"Connected to Vertex AI ({proj} / {loc}) successfully."
        elif provider in {"ai_studio", "gemini"}:
            from google import genai
            if not k:
                return False, "Gemini API key cannot be empty."
            m = model or text_model.gemini_default("ai_studio")
            profile, connection = {"provider": "gemini", "model": m}, {"client": genai.Client(api_key=k)}
            success = f"Connected to Gemini AI Studio ({m}) successfully."
        elif provider == "anthropic" or provider in OPENAI_COMPATIBLE_PRESETS:
            if not k and provider in {"anthropic", "openai", "openrouter", "groq"}:
                return False, f"{labels[provider]} API key cannot be empty."
            m = model or text_model.default_model(provider)
            profile, connection = {"provider": provider, "model": m}, {"api_key": k, "base_url": base_url}
            success = (f"Connected to custom LLM endpoint ({base_url}) successfully." if provider == "custom"
                       else f"Connected to {labels[provider]} ({m}) successfully.")
        else:
            return False, f"Unknown provider: {provider}"

        reply = text_model.text_model(profile, connection=connection).complete(
            "Ping. Respond with 'pong'.", max_tokens=10, trace="credentials.test")
        if provider == "vertex" and not reply:
            return False, "Model did not return a response."
        return True, success

    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 401:
            return False, f"Invalid {labels.get(provider, provider)} API key."
        return False, str(exc)
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
