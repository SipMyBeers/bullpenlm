#!/usr/bin/env bash
# BullpenLM — one-shot Mac Mini installer.
#
# This is the script you paste into a Mac Mini's terminal to get from
# "fresh macOS" to "BullpenLM running, tunnel up, wizard ready" in one
# command. Run as the user who'll own the floor (don't sudo it — the
# Python server should run as a normal user).
#
# Usage from any Mac that can reach the Mini (SSH in first):
#   curl -fsSL https://raw.githubusercontent.com/SipMyBeers/bullpenlm/main/scripts/install_macmini.sh | bash
#
# Or after cloning:
#   bash scripts/install_macmini.sh
#
# What it does:
#   1. Verifies macOS + Homebrew (installs Homebrew if absent — interactive
#      because Apple requires sudo confirmation for that one).
#   2. brew installs: python3, git, cloudflared, ffmpeg, ollama,
#      whisper-cpp, yt-dlp.
#   3. Clones SipMyBeers/bullpenlm to ~/bullpenlm (pulls latest if exists).
#   4. pip3 installs: pyyaml, certifi.
#   5. Downloads the whisper small.en model (~466MB) into server/models/.
#   6. Pulls the Ollama Gemma 9B model (~5GB) so cold-call roleplay works.
#   7. Starts the Python server in the background (nohup → /tmp/bullpen-server.log).
#   8. Spawns caffeinate so the Mac Mini doesn't sleep.
#   9. Hits /api/host/publish to spin up the Cloudflare Quick Tunnel.
#  10. Prints the wizard URL + the tunnel URL.
#
# Resumable: re-runs are idempotent. Already-installed brew packages skip,
# already-downloaded models skip, already-running server is reused.

set -euo pipefail

# ── Output helpers ──
GREEN='\033[0;32m'
GOLD='\033[1;33m'
RED='\033[0;31m'
DIM='\033[2m'
RESET='\033[0m'
log()  { echo -e "${DIM}▸${RESET} $*"; }
ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${GOLD}!${RESET} $*"; }
err()  { echo -e "${RED}×${RESET} $*" >&2; }
hr()   { echo -e "${DIM}────────────────────────────────────────────────────────────${RESET}"; }

hr
echo "  BullpenLM · Mac Mini one-shot installer"
hr

# ── 1. macOS check ──
if [[ "$(uname)" != "Darwin" ]]; then
  err "This installer only runs on macOS. You're on $(uname)."
  exit 1
fi
ok "macOS confirmed ($(sw_vers -productName) $(sw_vers -productVersion))"

# ── 2. Homebrew ──
if ! command -v brew >/dev/null 2>&1; then
  warn "Homebrew not found — installing now (will prompt for sudo password)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Add brew to PATH for the rest of this script + future shells
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
    grep -q 'brew shellenv' ~/.zprofile 2>/dev/null || \
      echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
  fi
fi
ok "Homebrew ready ($(brew --version | head -1))"

# ── 3. brew packages ──
PACKAGES=(python3 git cloudflared ffmpeg ollama whisper-cpp yt-dlp)
for pkg in "${PACKAGES[@]}"; do
  if brew list "$pkg" >/dev/null 2>&1; then
    log "$pkg already installed"
  else
    log "installing $pkg"
    brew install "$pkg"
  fi
done
ok "All brew dependencies installed"

# ── 4. Clone or pull bullpenlm ──
REPO_DIR="$HOME/bullpenlm"
if [[ -d "$REPO_DIR/.git" ]]; then
  log "bullpenlm already cloned at $REPO_DIR — pulling latest"
  git -C "$REPO_DIR" pull --ff-only origin main
else
  log "cloning bullpenlm to $REPO_DIR"
  git clone https://github.com/SipMyBeers/bullpenlm.git "$REPO_DIR"
fi
cd "$REPO_DIR"
ok "Repo at $REPO_DIR (commit $(git rev-parse --short HEAD))"

# ── 5. Python user deps ──
log "ensuring python3 user packages (pyyaml, certifi)"
python3 -m pip install --user --quiet --upgrade pyyaml certifi 2>&1 | grep -v "already satisfied" || true
ok "Python user deps ready"

# ── 6. Whisper small.en model ──
MODEL="$REPO_DIR/server/models/ggml-small.en.bin"
mkdir -p "$(dirname "$MODEL")"
if [[ -f "$MODEL" ]]; then
  log "whisper small.en model already present"
else
  log "downloading whisper small.en model (~466MB, one-time)"
  curl -fL --progress-bar -o "$MODEL" \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin"
fi
ok "Whisper model ready"

# ── 7. Ollama model (gemma2:9b) ──
log "starting Ollama daemon (background)"
if ! pgrep -f "ollama serve" >/dev/null; then
  nohup ollama serve > /tmp/ollama.log 2>&1 &
  sleep 3
fi
if ollama list 2>/dev/null | grep -q "gemma2:9b"; then
  log "gemma2:9b already pulled"
else
  log "pulling gemma2:9b (~5.4GB, one-time, takes a few minutes)"
  ollama pull gemma2:9b
fi
ok "Gemma 9B ready for AI buyer roleplay"

# ── 8. Free port 7878, start the Python server ──
if lsof -ti :7878 >/dev/null 2>&1; then
  log "port 7878 in use — killing stale process"
  lsof -ti :7878 | xargs -r kill -9 2>/dev/null
  sleep 1
fi
log "starting BullpenLM server in background"
nohup python3 -u server/server.py > /tmp/bullpen-server.log 2>&1 &
SERVER_PID=$!

# Wait up to 20s for the server to bind to 7878
for i in $(seq 1 20); do
  if curl -s -o /dev/null http://127.0.0.1:7878/api/health 2>/dev/null \
     || curl -s -o /dev/null http://127.0.0.1:7878/ 2>/dev/null; then
    break
  fi
  sleep 1
done
if ! curl -s -o /dev/null http://127.0.0.1:7878/ 2>/dev/null; then
  err "Server didn't come up on :7878. Check /tmp/bullpen-server.log"
  tail -20 /tmp/bullpen-server.log
  exit 1
fi
ok "Server up at http://localhost:7878 (pid $SERVER_PID, log: /tmp/bullpen-server.log)"

# ── 9. Caffeinate (keep Mac Mini awake forever) ──
if pgrep -fl 'caffeinate.*-dimsu' >/dev/null 2>&1; then
  log "caffeinate already running"
else
  log "spawning caffeinate (keeps Mac Mini awake indefinitely)"
  nohup caffeinate -dimsu > /dev/null 2>&1 &
fi
ok "Caffeinate armed — Mac Mini will not sleep"

# ── 10. Publish the Cloudflare tunnel ──
log "spinning up Cloudflare Quick Tunnel"
TUNNEL_JSON=$(curl -s -X POST http://127.0.0.1:7878/api/host/publish || echo '{}')
TUNNEL_URL=$(echo "$TUNNEL_JSON" | python3 -c "import json,sys
try:
    d = json.load(sys.stdin)
    print(d.get('url') or '')
except Exception:
    print('')" 2>/dev/null)

if [[ -z "$TUNNEL_URL" ]]; then
  warn "Tunnel didn't auto-start. Try manually: curl -X POST http://127.0.0.1:7878/api/host/publish"
else
  ok "Tunnel live: $TUNNEL_URL"
fi

# ── Done ──
hr
echo
ok "Install complete. Mac Mini is the host."
echo
echo -e "${GOLD}On the Mac Mini (or via SSH from your laptop):${RESET}"
echo "  open http://localhost:7878/app/start-bullpen.html"
echo "  → walk through the 5-step wizard"
echo
if [[ -n "$TUNNEL_URL" ]]; then
  echo -e "${GOLD}From any other device (laptop, phone):${RESET}"
  echo "  $TUNNEL_URL/app/start-bullpen.html"
  echo "  (use this to run the wizard from your couch)"
  echo
fi
echo -e "${GOLD}After the wizard finishes:${RESET}"
echo "  cd ~/bullpenlm && python3 scripts/_seed_killsesh_prospects.py"
echo "  → seeds 24 BFSI prospects so closers have someone to claim"
echo
echo -e "${GOLD}Tail server logs:${RESET}"
echo "  tail -f /tmp/bullpen-server.log"
echo
echo -e "${GOLD}To stop the server later:${RESET}"
echo "  lsof -ti :7878 | xargs kill -9"
echo "  pkill -f 'caffeinate -dimsu'"
echo
hr
