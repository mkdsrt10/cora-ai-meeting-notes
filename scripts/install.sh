#!/usr/bin/env bash
# Install Cora AI Meeting Notes from a GitHub release.
#
#   curl -fsSL https://raw.githubusercontent.com/mkdsrt10/cora-ai-meeting-notes/main/scripts/install.sh | bash
#
# Why this exists: the app is ad-hoc signed, not notarized (no paid Apple
# Developer ID yet). A DMG downloaded in a browser carries macOS's quarantine
# flag, so Gatekeeper refuses to open it. Files fetched with curl are not
# quarantined, and this script clears the flag anyway, so the app just opens.
#
# What it does, and nothing else: downloads the release DMG over HTTPS,
# checks it against the release's published SHA-256, copies the .app into
# Applications, and (optionally) opens it. It never runs anything from the DMG
# and never uses sudo. Read it first if you like: it is short.
#
# Options:  --version vX.Y.Z   install a specific release (default: latest)
#           --dir PATH         install location (default: /Applications, else ~/Applications)
#           --open             launch the app when done
#           --dry-run          show what would happen, change nothing
#           -h, --help
set -euo pipefail

REPO="${CORA_REPO:-mkdsrt10/cora-ai-meeting-notes}"
APP_NAME="Cora AI Meeting Notes"
VERSION=""
DEST=""
OPEN=0
DRY=0

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
run()  { if [[ $DRY -eq 1 ]]; then echo "  (dry-run) $*"; else "$@"; fi; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="${2:-}"; shift 2 ;;
    --dir)     DEST="${2:-}"; shift 2 ;;
    --open)    OPEN=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

# --- preflight ---------------------------------------------------------
[[ "$(uname -s)" == "Darwin" ]] || die "Cora is a macOS app."
[[ "$(uname -m)" == "arm64" ]]  || die "Cora needs Apple Silicon (M1 or later); this Mac is $(uname -m)."
major="$(sw_vers -productVersion | cut -d. -f1)"
[[ "$major" -ge 14 ]] || die "Cora needs macOS 14 (Sonoma) or newer; this is $(sw_vers -productVersion)."
for tool in curl shasum hdiutil ditto xattr; do
  command -v "$tool" >/dev/null || die "missing required tool: $tool"
done

# --- resolve the release ----------------------------------------------
if [[ -z "$VERSION" ]]; then
  say "Finding the latest release"
  final="$(curl -fsSLI --proto '=https' --tlsv1.2 -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest")" \
    || die "could not reach github.com/$REPO"
  VERSION="${final##*/}"
fi
[[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.]+)?$ ]] || die "unexpected version string: $VERSION"
NUM="${VERSION#v}"
DMG="Cora-AI-Meeting-Notes-${NUM}-arm64.dmg"
BASE="https://github.com/$REPO/releases/download/$VERSION"

if [[ -z "$DEST" ]]; then
  if [[ -w /Applications ]]; then DEST="/Applications"; else DEST="$HOME/Applications"; fi
fi
TARGET="$DEST/$APP_NAME.app"

say "Plan"
echo "  release : $VERSION ($DMG)"
echo "  from    : $BASE/"
echo "  install : $TARGET"
[[ $DRY -eq 1 ]] && { echo "  dry run : nothing will be downloaded or changed"; exit 0; }

if pgrep -f "$TARGET/Contents/MacOS/" >/dev/null 2>&1; then
  die "$APP_NAME is running. Quit it first (a recording may be in progress), then run this again."
fi

# --- download + verify --------------------------------------------------
work="$(mktemp -d)"
mnt="$work/mnt"
cleanup() { hdiutil detach "$mnt" -quiet 2>/dev/null || true; rm -rf "$work"; }
trap cleanup EXIT

say "Downloading $DMG (about 650 MB)"
progress="-sS"; [[ -t 1 ]] && progress="--progress-bar"   # a bar only in a real terminal; it floods logs otherwise
curl -fL --proto '=https' --tlsv1.2 "$progress" -o "$work/$DMG" "$BASE/$DMG" || die "download failed: $BASE/$DMG"
curl -fsSL --proto '=https' --tlsv1.2 -o "$work/$DMG.sha256" "$BASE/$DMG.sha256" \
  || die "this release has no published checksum ($DMG.sha256), so I won't install it"

say "Verifying checksum"
expected="$(awk '{print $1}' "$work/$DMG.sha256" | head -n1)"
actual="$(shasum -a 256 "$work/$DMG" | awk '{print $1}')"
[[ -n "$expected" && "$expected" == "$actual" ]] || die "checksum mismatch (expected $expected, got $actual). Not installing."
echo "  sha256 $actual"

# --- install ------------------------------------------------------------
say "Installing to $DEST"
mkdir -p "$DEST" 2>/dev/null || die "cannot create $DEST (try --dir \"\$HOME/Applications\")"
mkdir -p "$mnt"
hdiutil attach "$work/$DMG" -nobrowse -readonly -noautoopen -mountpoint "$mnt" -quiet || die "could not mount the DMG"
[[ -d "$mnt/$APP_NAME.app" ]] || die "the DMG does not contain $APP_NAME.app"
if [[ -d "$TARGET" ]]; then
  echo "  replacing existing install (your recordings and settings are kept: they live in ~/Library/Application Support)"
  rm -rf "$TARGET" || die "could not remove the old app at $TARGET"
fi
ditto "$mnt/$APP_NAME.app" "$TARGET" || die "copy failed (disk full?)"
xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null || true

say "Installed $APP_NAME $VERSION"
if ! command -v ffmpeg >/dev/null 2>&1 && [[ ! -x /opt/homebrew/bin/ffmpeg ]]; then
  warn "ffmpeg is not installed (Cora needs it). Install it with:  brew install ffmpeg"
fi
cat <<EOF

Next:
  1. Open the app (it will not show the "can't verify" warning).
  2. Allow Microphone, Screen Recording (to hear the other side of calls; no video is recorded)
     and Accessibility (live speaker names) when asked.
  3. After an update, macOS may ask for those permissions again: this build is ad-hoc signed.

EOF
if [[ $OPEN -eq 1 ]]; then open "$TARGET"; fi
