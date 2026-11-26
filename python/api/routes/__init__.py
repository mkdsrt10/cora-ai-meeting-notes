"""Route modules; importing this package registers every endpoint with api.router.
Plugin routes are served through api/routes/plugins.py (see plugin_host)."""
from api.routes import action_items, beta, capture, cloud, logs, media, outbox, people, plugins, pulse, recordings, settings, surfaces, system  # noqa: F401
