#!/usr/bin/env bash
# Build ffmpeg + ffprobe for bundling inside Cora.app, so users don't need Homebrew.
#
# Built from the official source tarball (SHA-256 pinned; it matches Homebrew's
# ffmpeg 7.1.1 formula) with every external library disabled: the binaries link
# only macOS system libraries, so they run on any Apple Silicon Mac on macOS 14+.
# Output: build/ffmpeg/bin/{ffmpeg,ffprobe}. Re-running is a no-op once built.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="7.1.1"
SHA256="733984395e0dbbe5c046abda2dc49a5544e7e0e1e2366bba849222ae9e3a03b1"
SRC_DIR="build/ffmpeg-src"
OUT="build/ffmpeg"
TARBALL="$SRC_DIR/ffmpeg-$VERSION.tar.xz"
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }

if [[ -x "$OUT/bin/ffmpeg" && -x "$OUT/bin/ffprobe" && "$(cat "$OUT/VERSION" 2>/dev/null)" == "$VERSION" ]]; then
  echo "ffmpeg $VERSION already built in $OUT"
  exit 0
fi

mkdir -p "$SRC_DIR"
if [[ ! -f "$TARBALL" ]]; then
  say "Downloading ffmpeg $VERSION source"
  curl -fsSL --proto '=https' --tlsv1.2 -o "$TARBALL" "https://ffmpeg.org/releases/ffmpeg-$VERSION.tar.xz"
fi
actual="$(shasum -a 256 "$TARBALL" | awk '{print $1}')"
[[ "$actual" == "$SHA256" ]] || { echo "checksum mismatch for $TARBALL: $actual" >&2; rm -f "$TARBALL"; exit 1; }

say "Building ffmpeg $VERSION (a few minutes)"
work="$SRC_DIR/ffmpeg-$VERSION"
rm -rf "$work"
tar -xJf "$TARBALL" -C "$SRC_DIR"
(
  cd "$work"
  ./configure \
    --prefix="$PWD/../../ffmpeg" \
    --arch=arm64 --cc=clang \
    --extra-cflags="-mmacosx-version-min=14.0" --extra-ldflags="-mmacosx-version-min=14.0" \
    --disable-autodetect --enable-zlib --enable-audiotoolbox \
    --disable-network --disable-ffplay --disable-doc --disable-debug \
    --disable-shared --enable-static >/dev/null
  make -j"$(sysctl -n hw.ncpu)" >/dev/null
  rm -rf ../../ffmpeg
  make install >/dev/null
)
rm -rf "$OUT/include" "$OUT/lib" "$OUT/share" "$work"
echo "$VERSION" > "$OUT/VERSION"

# Fail the build if anything links outside the OS (e.g. a stray Homebrew dylib).
for bin in ffmpeg ffprobe; do
  if otool -L "$OUT/bin/$bin" | tail -n +2 | awk '{print $1}' | grep -vqE '^/(usr/lib|System/Library)/'; then
    echo "$bin links a non-system library:" >&2; otool -L "$OUT/bin/$bin" >&2; exit 1
  fi
done
"$OUT/bin/ffmpeg" -hide_banner -version | head -n1
