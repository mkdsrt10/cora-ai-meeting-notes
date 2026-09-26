#!/usr/bin/env bash
# Build a self-contained Cora AI Meeting Notes.app + .dmg for Apple Silicon.
#
# The app ships its own relocatable CPython (uv-managed python-build-standalone)
# with the locked dependencies, so users need neither a clone nor a venv.
# Models are downloaded from Hugging Face on first use; ffmpeg comes from
# Homebrew (onboarding checks for it).
#
# Signing: ad-hoc (no Apple Developer ID). The DMG is not notarized, so on
# first launch macOS asks users to confirm — see docs/INSTALL.md.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="$(node -p "require('./package.json').version")"
PRODUCT="Cora AI Meeting Notes"
RUNTIME="build/python-runtime"
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }

say "Building native helpers"
make build-native

say "Preparing bundled Python runtime"
mkdir -p build
uv export --frozen --no-dev --no-hashes --no-emit-project --extra cloud -o build/requirements.next.txt >/dev/null
if [[ -x "$RUNTIME/bin/python3" ]] && cmp -s build/requirements.next.txt build/requirements.txt; then
  echo "dependencies unchanged — reusing $RUNTIME"
  rm build/requirements.next.txt
else
  mv build/requirements.next.txt build/requirements.txt
  uv python install 3.11 >/dev/null
  PY="$(uv python find --python-preference only-managed 3.11)"
  PYROOT="$(cd "$(dirname "$PY")/.." && pwd -P)"
  rm -rf "$RUNTIME"
  cp -R "$PYROOT" "$RUNTIME"
  uv pip install --python "$RUNTIME/bin/python3" --break-system-packages --no-cache --quiet -r build/requirements.txt
  find "$RUNTIME" -name "__pycache__" -type d -prune -exec rm -rf {} +
  rm -rf "$RUNTIME"/lib/python3.11/{test,idlelib,tkinter,turtledemo} "$RUNTIME"/lib/python3.11/site-packages/*/tests
fi
"$RUNTIME/bin/python3" -c "import mlx.core, mlx_whisper, mlx_lm, numpy, requests, mcp; print('runtime imports OK')"

say "Packaging the app"
rm -rf dist
CSC_IDENTITY_AUTO_DISCOVERY=false npx --no-install electron-builder --mac dir --arm64 -c.mac.identity=null >/dev/null
APP="dist/mac-arm64/$PRODUCT.app"
[[ -d "$APP" ]] || { echo "electron-builder did not produce $APP"; exit 1; }

say "Ad-hoc signing"
# Sign nested Mach-O files first (bundled Python and helpers), then the app.
find "$APP/Contents/Resources" -type f \( -name "*.so" -o -name "*.dylib" -o -perm -u+x \) -print0 \
  | xargs -0 -n 50 sh -c 'for f; do file -b "$f" | grep -q "Mach-O" && codesign --force --sign - "$f" 2>/dev/null; done; true' sh
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

say "Creating DMG"
DMG="dist/Cora-AI-Meeting-Notes-$VERSION-arm64.dmg"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "$PRODUCT" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
shasum -a 256 "$DMG" | tee "$DMG.sha256"
du -sh "$APP" "$DMG"
