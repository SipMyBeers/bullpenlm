#!/bin/bash
# Local notarized .app build for BullpenLM.
#
# Wraps `cargo tauri build` with the Apple notarization env vars Tauri's
# bundler looks for. When all four are set, tauri-bundler invokes
# `xcrun notarytool submit --wait` and then `xcrun stapler staple` on the
# .app and .dmg automatically. Without them, the build skips notarization
# and prints "no APPLE_ID & APPLE_PASSWORD & APPLE_TEAM_ID … found".
#
# Beers's setup:
#   - The "Developer ID Application: Dylan Beers (NV5993W4T4)" signing
#     identity lives in his login keychain; tauri.conf.json points at it
#     by name so codesigning works without env vars.
#   - Notarization needs separate creds (an app-specific password for
#     his Apple ID), which this wrapper sources from desktop/.env.notarize.
#
# Usage:
#   1. Copy desktop/.env.notarize.example -> desktop/.env.notarize
#   2. Fill in the three values (see comments inside the file)
#   3. Run: bash desktop/scripts/build-notarized.sh
#
# The .env.notarize file is gitignored (.env.* covers it).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="$ROOT/desktop/.env.notarize"

if [ ! -f "$ENV_FILE" ]; then
  echo "✗ Missing $ENV_FILE"
  echo ""
  echo "  Copy the example and fill in your Apple ID + app-specific password:"
  echo "    cp desktop/.env.notarize.example desktop/.env.notarize"
  echo "    \$EDITOR desktop/.env.notarize"
  echo ""
  echo "  Then re-run this script."
  exit 1
fi

# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

missing=()
[ -z "${APPLE_ID:-}" ]       && missing+=("APPLE_ID")
[ -z "${APPLE_PASSWORD:-}" ] && missing+=("APPLE_PASSWORD")
[ -z "${APPLE_TEAM_ID:-}" ]  && missing+=("APPLE_TEAM_ID")
if [ ${#missing[@]} -gt 0 ]; then
  echo "✗ Missing env vars in $ENV_FILE: ${missing[*]}"
  exit 1
fi

echo "→ Notarization creds present"
echo "  APPLE_ID:      ${APPLE_ID}"
echo "  APPLE_TEAM_ID: ${APPLE_TEAM_ID}"
echo "  APPLE_PASSWORD: ********"
echo ""

# Rebuild the PyInstaller sidecar so the bundled .app has the latest
# server.py routes. cargo tauri build alone won't recompile it.
echo "→ Rebuilding PyInstaller sidecar"
cd "$ROOT/desktop/src-tauri/binaries"
if [ -d "$ROOT/.venv-build" ]; then
  # shellcheck disable=SC1091
  . "$ROOT/.venv-build/bin/activate"
fi
pyinstaller --clean --noconfirm bullpenlm-server.spec

echo ""
echo "→ Running cargo tauri build (this will sign, notarize, and staple)"
echo "  Expect this to take 2–5 min: most of the wall-clock time is"
echo "  waiting for Apple's notarization service to respond."
cd "$ROOT/desktop/src-tauri"
/Users/beers/.cargo/bin/cargo tauri build

APP_PATH="$ROOT/desktop/src-tauri/target/release/bundle/macos/BullpenLM.app"
DMG_PATH="$ROOT/desktop/src-tauri/target/release/bundle/dmg/BullpenLM_0.1.0_aarch64.dmg"

echo ""
echo "→ Verifying notarization staple"
if [ -d "$APP_PATH" ]; then
  /usr/bin/xcrun stapler validate "$APP_PATH" && echo "  ✓ .app stapled" || echo "  ✗ .app NOT stapled — check tauri build output"
fi
if [ -f "$DMG_PATH" ]; then
  /usr/bin/xcrun stapler validate "$DMG_PATH" && echo "  ✓ .dmg stapled" || echo "  ✗ .dmg NOT stapled"
fi

echo ""
echo "→ Gatekeeper assessment (what a fresh Mac will see)"
if [ -d "$APP_PATH" ]; then
  /usr/sbin/spctl -a -vv "$APP_PATH" 2>&1 || true
fi

echo ""
echo "Done. The .app + .dmg are now safe to hand to anyone on macOS."
