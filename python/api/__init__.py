"""Cora's local HTTP API (stdlib http.server, loopback only).

    router.py   route registry: @route("GET", "/api/x") / prefix routes
    auth.py     per-launch token, Host/Origin pinning (see authorize())
    http.py     Handler: security headers, JSON/file responses, dispatch
    core.py     shared paths/constants and payload builders
    routes/     endpoints grouped by area (recordings, capture, people, ...)

To add an endpoint: write a function in the right routes/ module and
decorate it; handlers get (req, path, query|body) and respond via
req.send_json(...) / req.serve_file(...).
"""
