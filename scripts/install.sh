#!/usr/bin/env bash
# BullpenLM — one-shot install on macOS.
# Pulls everything you need for Tier-1 and Tier-2. Tier-3 (XTTS voice cloning)
# stays optional — install separately via pip when you want it.
set -euo pipefail

echo "─────────────────────────────────────────────────"
echo "  BullpenLM · local install"
echo "─────────────────────────────────────────────────"

if ! command -v brew >/dev/null 2>&1; then
  echo "× Homebrew not found. Install from https://brew.sh first."
  exit 1
fi

needs_install() { ! command -v "$1" >/dev/null 2>&1; }

# Core deps
if needs_install ollama;       then echo "▸ installing ollama";       brew install ollama;       fi
if needs_install whisper-cli;  then echo "▸ installing whisper-cpp";  brew install whisper-cpp;  fi
if needs_install yt-dlp;       then echo "▸ installing yt-dlp";       brew install yt-dlp;       fi

# Whisper model
MODEL="$(dirname "$0")/../server/models/ggml-base.en.bin"
mkdir -p "$(dirname "$MODEL")"
if [ ! -f "$MODEL" ]; then
  echo "▸ downloading whisper base.en model (~150MB)"
  curl -sL -o "$MODEL" \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
fi

echo ""
echo "✓ Install complete."
echo ""
echo "Next:"
echo "  ./scripts/pull-model.sh         # download the LLM (~5GB, one-time)"
echo "  python3 server/server.py        # start the trainer at :7878"
echo "  open floor/index.html           # open the walking sales floor"
echo ""
echo "Optional (Tier 3 voice cloning):"
echo "  pip install 'TTS>=0.22.0'"
echo "  python3 personas/manage.py clone-voice <slug>"
