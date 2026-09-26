#!/usr/bin/env bash
# One-shot setup for a fresh Apple Silicon Mac. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31mError:\033[0m %s\n' "$*" >&2; exit 1; }

say "Checking platform"
[[ "$(uname -s)" == "Darwin" ]] || die "Cora runs on macOS only."
[[ "$(uname -m)" == "arm64" ]] || die "Cora needs Apple Silicon (MLX requires Metal)."
major=$(sw_vers -productVersion | cut -d. -f1)
(( major >= 14 )) || die "macOS 14 (Sonoma) or newer is required (found $(sw_vers -productVersion))."
xcode-select -p >/dev/null 2>&1 || die "Install the Xcode Command Line Tools first: xcode-select --install"

say "Checking Homebrew tools"
command -v brew >/dev/null || die "Homebrew is required: https://brew.sh"
for tool in ffmpeg node uv; do
  if ! command -v "$tool" >/dev/null; then
    say "Installing $tool"
    brew install "$tool"
  fi
done

say "Installing Python dependencies (uv, from uv.lock)"
uv sync --frozen --all-extras

say "Installing Node dependencies (from package-lock.json)"
npm ci

say "Building native helpers"
make build-native

say "Installing git hooks"
if command -v pre-commit >/dev/null || uv run --with pre-commit pre-commit --version >/dev/null 2>&1; then
  uv run --with pre-commit pre-commit install || true
fi

cat <<'MSG'

Setup complete. Start Cora with:

    make dev

On first launch macOS will ask for Microphone, Screen Recording (needed to
capture the other side of the call) and Accessibility (live speaker names)
permissions. See docs/SETUP.md if a permission prompt doesn't appear.
MSG
