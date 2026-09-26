#!/usr/bin/env bash
# Refresh the code inside an installed Cora.app (a launcher for this
# checkout — see src/main/paths.js) without rebuilding the bundle. Replacing
# only app.asar keeps the app's executable and ad-hoc signature, so macOS
# keeps its Microphone / Screen Recording / Accessibility grants.
set -euo pipefail
cd "$(dirname "$0")/.."
APP="${1:-/Applications/Cora.app}"
ASAR="$APP/Contents/Resources/app.asar"
[[ -f "$ASAR" ]] || { echo "No app.asar at $ASAR (pass the .app path as an argument)"; exit 1; }
if pgrep -f "$APP/Contents/MacOS/" >/dev/null; then
  echo "Quit $(basename "$APP") first (a recording may be in progress)."; exit 1
fi
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
cp -R package.json config.example.json src "$stage/"
cp "$ASAR" "$ASAR.bak"
node -e "require('@electron/asar').createPackage(process.argv[1], process.argv[2])" "$stage" "$ASAR"
echo "Updated $ASAR (previous copy: app.asar.bak). Open the app to use the new code."
