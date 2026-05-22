#!/usr/bin/env bash
# Pull the default Ollama model. ~5GB, one-time.
set -euo pipefail
echo "▸ starting ollama daemon if not already running"
if ! pgrep -x ollama >/dev/null 2>&1; then
  ollama serve &
  sleep 2
fi
echo "▸ pulling gemma2:9b (~5GB)"
ollama pull gemma2:9b
echo "✓ model ready"
