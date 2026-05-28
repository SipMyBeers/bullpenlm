#!/bin/bash
# Bundle whisper-cli + its dylib graph for the Mac app build.
#
# Tauri's externalBin gives us per-target-triple binaries, but those binaries
# can still depend on system dylibs from /opt/homebrew/... that won't exist
# on a friend's clean Mac. This script:
#
#   1. Copies the homebrew whisper-cli into binaries/whisper-cli-<triple>
#   2. Copies the dylib transitive closure into binaries/whisper-deps/
#   3. Rewrites the binary's load commands to use @loader_path so the
#      bundled dylibs are found relative to the binary at runtime
#
# Run this BEFORE `tauri build`. Idempotent — safe to re-run.
#
# Output:
#   desktop/src-tauri/binaries/
#     whisper-cli-<triple>            ← rpath-rewritten executable
#     whisper-deps/
#       libwhisper.1.dylib
#       libggml.0.dylib
#       libggml-base.0.dylib
#       (and any second-order deps)
#
# server/server.py looks for whisper next to itself first; in a bundled app
# the Tauri runtime sets PATH so sidecars resolve via Tauri's path API.

set -euo pipefail

BIN_DIR="$(cd "$(dirname "$0")/../src-tauri/binaries" && pwd)"
DEPS_DIR="$BIN_DIR/whisper-deps"
TRIPLE="${1:-aarch64-apple-darwin}"
SRC="${WHISPER_BIN:-/opt/homebrew/bin/whisper-cli}"

if [ ! -x "$SRC" ]; then
  echo "✗ No whisper-cli at $SRC. Install: brew install whisper-cpp" >&2
  exit 1
fi

OUT_BIN="$BIN_DIR/whisper-cli-$TRIPLE"
mkdir -p "$DEPS_DIR"
cp "$SRC" "$OUT_BIN"
chmod +w "$OUT_BIN"

echo "→ Bundling whisper-cli → $OUT_BIN"

# Walk the dylib graph. Whisper depends on libwhisper + libggml + libggml-base;
# libggml depends on libggml-base; everything else is system (/usr/lib) which
# we don't bundle.
collect_deps() {
  local f="$1"
  otool -L "$f" 2>/dev/null | awk 'NR>1 {print $1}' | while read -r dep; do
    case "$dep" in
      /opt/homebrew/*|/usr/local/*|@rpath/*)
        local base; base="$(basename "$dep")"
        local resolved="$dep"
        # @rpath/foo.dylib resolves through whisper-cli's rpath list. Most
        # common case on this Mac: @rpath/libwhisper.1.dylib lives under
        # /opt/homebrew/opt/whisper-cpp/lib/.
        if [[ "$dep" == @rpath/* ]]; then
          for guess in \
            "/opt/homebrew/opt/whisper-cpp/lib/$base" \
            "/opt/homebrew/lib/$base" \
            "/opt/homebrew/opt/ggml/lib/$base" ; do
            [ -f "$guess" ] && { resolved="$guess"; break; }
          done
        fi
        if [ -f "$resolved" ] && [ ! -f "$DEPS_DIR/$base" ]; then
          echo "  + $base"
          cp "$resolved" "$DEPS_DIR/$base"
          chmod +w "$DEPS_DIR/$base"
          collect_deps "$DEPS_DIR/$base"  # recurse
        fi
        ;;
    esac
  done
}

collect_deps "$OUT_BIN"

# Rewrite the binary + each dylib to use @loader_path. This makes them
# findable when the .app is installed anywhere, including a friend's
# Downloads folder.
rewrite() {
  local f="$1" relative_deps_dir="$2"
  # Re-point each non-system dependency to @loader_path/<deps-dir>/<basename>
  otool -L "$f" 2>/dev/null | awk 'NR>1 {print $1}' | while read -r dep; do
    case "$dep" in
      /opt/homebrew/*|/usr/local/*|@rpath/*)
        local base; base="$(basename "$dep")"
        install_name_tool -change "$dep" "@loader_path/$relative_deps_dir/$base" "$f" 2>/dev/null || true
        ;;
    esac
  done
  # Strip the @rpath entries so nothing leaks back to /opt/homebrew
  otool -l "$f" 2>/dev/null | awk '/LC_RPATH/{getline;getline;print $2}' | while read -r rp; do
    [ -n "$rp" ] && install_name_tool -delete_rpath "$rp" "$f" 2>/dev/null || true
  done
}

# Binary's deps live in ./whisper-deps relative to itself
rewrite "$OUT_BIN" "whisper-deps"
# Dylib-to-dylib deps live in same dir, so use @loader_path/. (no subdir)
for dylib in "$DEPS_DIR"/*.dylib; do
  [ -f "$dylib" ] || continue
  rewrite "$dylib" "."
  # Set the dylib's own install_name to a self-referential @rpath so it
  # doesn't try to re-resolve via the homebrew prefix.
  install_name_tool -id "@rpath/$(basename "$dylib")" "$dylib" 2>/dev/null || true
done

# Re-sign — install_name_tool invalidates the signature on Apple Silicon.
# Ad-hoc signing is enough for local dev. CI / release re-signs with the
# Developer ID Application cert.
codesign --force --sign - "$OUT_BIN" 2>/dev/null || true
for dylib in "$DEPS_DIR"/*.dylib; do
  [ -f "$dylib" ] && codesign --force --sign - "$dylib" 2>/dev/null || true
done

echo "→ Done."
echo
echo "→ Verify ($OUT_BIN no longer references /opt/homebrew):"
otool -L "$OUT_BIN" | tail -n +2

echo
echo "→ Smoke test:"
"$OUT_BIN" --version 2>&1 | head -3 || echo "  (version flag may not be supported — try --help)"
