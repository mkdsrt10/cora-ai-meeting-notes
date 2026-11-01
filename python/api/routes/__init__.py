"""Route modules; importing this package registers every endpoint with api.router.
Plugin routes are served through api/routes/plugins.py (see plugin_host)."""
from api.routes import capture, cloud, logs, media, people, plugins, recordings, settings, system  # noqa: F401
