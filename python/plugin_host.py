"""Plugin host: the one seam where a bundled Plugin plugs into Cora.

A Plugin declares, in one place (its package's ``PLUGIN``):
  - ``view``: an optional page in the Cora window (title, subtitle, icon).
    The host adds the nav entry and the page section; the renderer script
    ``src/ui/web/plugins/<id>.js`` calls ``registerView('<id>', ...)``.
  - ``payload(recording)``: its data for one Recording (the DB row dict),
    shown in the recording view model under ``plugins[<id>]``.
  - ``stage(recording)``: optional; the Recording's stage once the core
    stages are cleared (see recording_stage.py), plus ``stage_labels``.
  - ``routes``: ``(method, subpath, handler)``, served under
    ``/api/plugins/<id>/<subpath>``. Handlers have the api.router signature.
  - ``hooks``: ``{"after_meeting": fn(recording_id), "daily": fn()}``.

Bundled plugins are discovered under ``plugins/`` at the app root. Whether
one is enabled is ``plugins.<id>.enabled`` in config.json, falling back to
the plugin's ``enabled_by_default``; it is read on every call, so a disabled
plugin vanishes from views, payloads, routes and hooks without a restart.

Every call into a plugin is isolated: an exception is logged with the plugin
id and the exception type only (never its message, which may quote meeting
content) and the host carries on.
"""
from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

import paths

HOOKS = ("after_meeting", "daily")
Handler = Callable[[Any, str, dict], None]


@dataclass(frozen=True)
class View:
    title: str
    subtitle: str = ""
    icon: str = "dot"


@dataclass(frozen=True)
class Plugin:
    id: str
    name: str
    view: View | None = None
    payload: Callable[[dict], dict | None] | None = None
    stage: Callable[[dict], str | None] | None = None
    stage_labels: dict[str, str] = field(default_factory=dict)
    routes: tuple[tuple[str, str, Handler], ...] = ()
    hooks: dict[str, Callable[..., Any]] = field(default_factory=dict)
    enabled_by_default: bool = False


_plugins: dict[str, Plugin] = {}
_discovered = False


def _log(plugin_id: str, where: str, exc: BaseException) -> None:
    print(f"[plugins] {plugin_id}: {where} failed ({type(exc).__name__})", flush=True)


def register(plugin: Plugin) -> None:
    if plugin.id in _plugins:
        raise ValueError(f"duplicate plugin id {plugin.id}")
    unknown = set(plugin.hooks) - set(HOOKS)
    if unknown:
        raise ValueError(f"plugin {plugin.id} declares unknown hooks {sorted(unknown)}")
    _plugins[plugin.id] = plugin


def unregister(plugin_id: str) -> None:
    _plugins.pop(plugin_id, None)


def discover() -> None:
    """Import every bundled plugin package under plugins/ that exports PLUGIN."""
    global _discovered
    if _discovered:
        return
    _discovered = True
    root = str(paths.APP_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    if not paths.PLUGINS_DIR.is_dir():
        return
    for package in sorted(paths.PLUGINS_DIR.iterdir()):
        if not (package / "__init__.py").is_file():
            continue
        try:
            module = importlib.import_module(f"plugins.{package.name}")
        except Exception as exc:  # a broken plugin must not take the app down
            _log(package.name, "import", exc)
            continue
        plugin = getattr(module, "PLUGIN", None)
        if isinstance(plugin, Plugin) and plugin.id not in _plugins:
            register(plugin)


def plugins() -> list[Plugin]:
    """Every known plugin, enabled or not."""
    discover()
    return list(_plugins.values())


def _config() -> dict[str, Any]:
    try:
        value = json.loads(paths.CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value.get("plugins") or {} if isinstance(value, dict) else {}


def is_enabled(plugin_id: str) -> bool:
    return any(p.id == plugin_id for p in enabled_plugins())


def enabled_plugins() -> list[Plugin]:
    flags = _config()
    return [p for p in plugins() if bool((flags.get(p.id) or {}).get("enabled", p.enabled_by_default))]


def views() -> list[dict[str, Any]]:
    """Enabled plugins and their Views, for GET /api/plugins."""
    return [{
        "id": p.id,
        "name": p.name,
        "view": {"id": p.id, "title": p.view.title, "subtitle": p.view.subtitle, "icon": p.view.icon} if p.view else None,
    } for p in enabled_plugins()]


def payloads(recording: dict[str, Any]) -> dict[str, Any]:
    """{plugin_id: payload} for one Recording; plugins returning None are left out."""
    result: dict[str, Any] = {}
    for p in enabled_plugins():
        if p.payload is None:
            continue
        try:
            value = p.payload(recording)
        except Exception as exc:
            _log(p.id, "payload", exc)
            continue
        if value is not None:
            result[p.id] = value
    return result


def plugin_stage(recording: dict[str, Any], enabled: list[Plugin] | None = None) -> str | None:
    """The first stage an enabled plugin claims for a Recording, if any."""
    for p in enabled if enabled is not None else enabled_plugins():
        if p.stage is None:
            continue
        try:
            value = p.stage(recording)
        except Exception as exc:
            _log(p.id, "stage", exc)
            continue
        if value:
            return value
    return None


def stage_labels() -> dict[str, str]:
    labels: dict[str, str] = {}
    for p in enabled_plugins():
        labels.update(p.stage_labels)
    return labels


def run_hook(name: str, recording_id: str | None = None) -> dict[str, bool]:
    """Call one Hook on every enabled plugin that declares it.
    Returns {plugin_id: succeeded}; one plugin failing never stops the rest."""
    if name not in HOOKS:
        raise ValueError(f"unknown hook {name}")
    results: dict[str, bool] = {}
    for p in enabled_plugins():
        fn = p.hooks.get(name)
        if fn is None:
            continue
        try:
            fn(recording_id) if name == "after_meeting" else fn()
            results[p.id] = True
        except Exception as exc:
            _log(p.id, f"hook {name}", exc)
            results[p.id] = False
    return results


def route_for(method: str, path: str) -> Handler | None:
    """Resolve /api/plugins/<id>/<subpath> to an enabled plugin's handler."""
    rest = path[len("/api/plugins/"):] if path.startswith("/api/plugins/") else ""
    plugin_id, _, subpath = rest.partition("/")
    for p in enabled_plugins():
        if p.id != plugin_id:
            continue
        for m, sub, handler in p.routes:
            if m == method and sub.strip("/") == subpath.strip("/"):
                return handler
    return None
