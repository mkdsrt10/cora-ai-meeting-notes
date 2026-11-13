#!/usr/bin/env bash
# Build a self-contained Cora AI Meeting Notes.app + .dmg for Apple Silicon.
#
# The app ships its own relocatable CPython (uv-managed python-build-standalone)
# with the locked dependencies, so users need neither a clone nor a venv.
# Models are downloaded from Hugging Face on first use; ffmpeg comes from
# Homebrew (onboarding checks for it).
#
# Signing: the persistent self-signed identity from scripts/signing-setup.sh,
# so macOS permission grants survive updates; ad-hoc (with a warning) if it
# hasn't been set up. Not notarized (no Apple Developer ID) — see docs/INSTALL.md.
#
# Options:  --team   new installs default to Gemini for transcription and notes
#                    (no local models to download; each user pastes the team's key)
set -euo pipefail
cd "$(dirname "$0")/.."

TEAM=0
for arg in "$@"; do
  case "$arg" in
    --team) TEAM=1 ;;
    *) echo "unknown option: $arg" >&2; exit 1 ;;
  esac
done

VERSION="$(node -p "require('./package.json').version")"
PRODUCT="Cora AI Meeting Notes"
RUNTIME="build/python-runtime"
SIGN_KC="$HOME/.cora-signing/cora-signing.keychain-db"
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }

SIGN_ARGS=(--sign -)
if [[ -f "$SIGN_KC" ]]; then
  security unlock-keychain -p "$(cat "$HOME/.cora-signing/keychain-password")" "$SIGN_KC"
  SIGN_HASH="$(security find-identity -p codesigning "$SIGN_KC" | awk '$1 == "1)" {print $2; exit}')"
  [[ -n "$SIGN_HASH" ]] || { echo "no code-signing identity in $SIGN_KC" >&2; exit 1; }
  SIGN_ARGS=(--keychain "$SIGN_KC" --sign "$SIGN_HASH")
else
  printf '\033[33mwarning:\033[0m no signing identity (run scripts/signing-setup.sh); ad-hoc signing,\n' >&2
  printf '         so users will have to re-grant macOS permissions after this update.\n' >&2
fi

say "Building native helpers"
make build-native
# Each helper must load on the oldest macOS the app claims (LSMinimumSystemVersion):
# a helper linked without a deployment target aborts at load on an older macOS
# with dyld "Symbol not found" (0.4.0 on the first teammate's Mac).
MIN_OS="$(node -p "require('./package.json').build.mac.extendInfo.LSMinimumSystemVersion")"
for helper in capture/dual-capture capture/mic-watch capture/speaker-watch bin/mac-ocr; do
  minos="$(otool -l "$helper" | awk '/LC_BUILD_VERSION/{f=1} f && /minos/{print $2; exit}')"
  [[ "$minos" == "$MIN_OS" ]] || { echo "$helper is built for macOS $minos, not $MIN_OS (see Makefile MACOS_MIN)" >&2; exit 1; }
done

say "Building bundled ffmpeg"
./scripts/build-ffmpeg.sh

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

if [[ $TEAM -eq 1 ]]; then
  say "Team build: new installs default to Gemini"
  CFG="$PWD/$APP/Contents/Resources/app.asar.unpacked/config.example.json"
  [[ -f "$CFG" ]] || { echo "missing $CFG (asarUnpack config.example.json?)"; exit 1; }
  node -e 'const f=process.argv[1],c=require(f);c.default_processing_mode="cloud";require("fs").writeFileSync(f,JSON.stringify(c,null,2)+"\n")' "$CFG"
fi

say "Stamping build-info.json"
# Version, commit and variant for the Python server (src/build-info.js reads it
# at launch). Receiver URL and token come from CORA_BETA_RECEIVER_URL and
# CORA_BETA_TOKEN in this shell; unset means the build never sends telemetry.
# Written into the bundle only, never into the repo.
VARIANT=public; [[ $TEAM -eq 1 ]] && VARIANT=team
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || true)"
node src/build-info.js "$PWD/$APP/Contents/Resources" "$VERSION" "$COMMIT" "$VARIANT"
[[ -n "${CORA_BETA_RECEIVER_URL:-}" && -n "${CORA_BETA_TOKEN:-}" ]] \
  || printf '\033[33mwarning:\033[0m CORA_BETA_RECEIVER_URL/CORA_BETA_TOKEN not set; this build will not send beta telemetry\n' >&2

say "Signing"
# Sign nested Mach-O files first (bundled Python, ffmpeg and helpers), then the app.
find "$APP/Contents/Resources" -type f \( -name "*.so" -o -name "*.dylib" -o -perm -u+x \) -print0 \
  | while IFS= read -r -d '' f; do
      if file -b "$f" | grep -q "Mach-O"; then codesign --force "${SIGN_ARGS[@]}" "$f" 2>/dev/null || true; fi
    done
codesign --force --deep "${SIGN_ARGS[@]}" "$APP"
codesign --verify --deep --strict "$APP"
codesign -dr - "$APP" 2>&1 | grep designated

say "Creating DMG"
DMG="dist/Cora-AI-Meeting-Notes-$VERSION-arm64.dmg"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "$PRODUCT" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
shasum -a 256 "$DMG" | tee "$DMG.sha256"
du -sh "$APP" "$DMG"
