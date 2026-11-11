#!/usr/bin/env bash
# One-time setup of the beta receiver on this Mac (see receiver/README.md):
# copies receiver.py to a dedicated folder, generates a token, installs a
# launchd agent that keeps it running on 127.0.0.1:8787, and exposes it with
# Tailscale Funnel. Prints the URL and the two env vars the team build needs.
#
#   scripts/setup-receiver.sh            # install or refresh, then show the build env
#   scripts/setup-receiver.sh --env      # only print the build env (export lines)
set -euo pipefail

RX="$HOME/cora-receiver"
ROOT="$HOME/cora-beta"
PORT=8787
LABEL=com.cora.beta-receiver
PL="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

print_env() {
  local url
  url="$(tailscale funnel status 2>/dev/null | grep -oE 'https://[^ ]+' | head -1 || true)"
  echo "export CORA_BETA_RECEIVER_URL=${url:-<funnel not active>}"
  echo "export CORA_BETA_TOKEN=\$(cat $ROOT/.token)"
}

if [[ "${1:-}" == "--env" ]]; then print_env; exit 0; fi

mkdir -p "$RX/receiver" "$ROOT/logs"
chmod 700 "$ROOT"
cp "$REPO/receiver/receiver.py" "$RX/receiver/receiver.py"
[[ -s "$ROOT/config.json" ]] || cp "$REPO/receiver/config.example.json" "$ROOT/config.json"
if [[ ! -s "$ROOT/.token" ]]; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$ROOT/.token"
  chmod 600 "$ROOT/.token"
fi
TOKEN="$(cat "$ROOT/.token")"

cat > "$PL" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$RX/receiver/receiver.py</string>
    <string>--root</string><string>$ROOT</string>
    <string>--port</string><string>$PORT</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CORA_RECEIVER_TOKEN</key><string>$TOKEN</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$ROOT/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/launchd.err.log</string>
</dict>
</plist>
EOF
chmod 600 "$PL"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PL"
sleep 1
echo "local:  $(curl -s "http://127.0.0.1:$PORT/v1/config")"
echo "auth:   HTTP $(curl -s -o /dev/null -w '%{http_code}' -X POST -d '{}' "http://127.0.0.1:$PORT/v1/events") for a POST without the token (401 expected)"

# Funnel: needs to be enabled once for the tailnet; the command prints the
# admin-console link if it is not.
tailscale funnel --bg "$PORT"
tailscale funnel status
URL="$(tailscale funnel status 2>/dev/null | grep -oE 'https://[^ ]+' | head -1 || true)"
if [[ -n "$URL" ]]; then
  echo "public: $(curl -s --max-time 15 "$URL/v1/config")"
fi
echo
echo "Build the team dmg with:"
print_env
echo "  scripts/build-app.sh --team"
