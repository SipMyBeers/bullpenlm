#!/usr/bin/env bash
# Set up a durable named Cloudflare Tunnel for BullpenLM.
#
# Why this exists: free Quick Tunnels (trycloudflare.com) have no uptime
# guarantee and frequently 404 at the Cloudflare edge. Named tunnels are
# Cloudflare's production-tier offering — stable URL, no expiration, no
# warning pages. You already have 3 named tunnels running on this Mac;
# this adds one more, side-by-side, without touching the others.
#
# Prerequisites:
#   - `cloudflared` installed (brew install cloudflared)
#   - You own a domain on Cloudflare (e.g. bullpenlm.com, ranger-beers.com)
#   - You're authed: `cloudflared tunnel login` (browser opens once)
#
# Usage:
#   bash scripts/setup-named-tunnel.sh [hostname]
#
# Default hostname: floor.bullpenlm.com
#
# After this finishes, the tunnel runs in the background and persists
# across reboots. The URL in the magic-link generator updates
# automatically (we write to ~/.bullpenlm/tunnel-url + tunnel.json).

set -euo pipefail

GREEN='\033[0;32m'
GOLD='\033[1;33m'
RED='\033[0;31m'
DIM='\033[2m'
RESET='\033[0m'
ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${GOLD}!${RESET} $*"; }
err()  { echo -e "${RED}×${RESET} $*" >&2; }
log()  { echo -e "${DIM}▸${RESET} $*"; }
hr()   { echo -e "${DIM}────────────────────────────────────────────────────────────${RESET}"; }

HOSTNAME="${1:-floor.bullpenlm.com}"
TUNNEL_NAME="bullpenlm"
CONFIG_FILE="$HOME/.cloudflared/$TUNNEL_NAME.yml"

hr
echo "  Named Cloudflare Tunnel setup — hostname=$HOSTNAME"
hr

# 1. cloudflared installed?
if ! command -v cloudflared >/dev/null 2>&1; then
  err "cloudflared not installed. Run: brew install cloudflared"
  exit 1
fi
ok "cloudflared installed: $(cloudflared --version | head -1)"

# 2. Auth check
if ! cloudflared tunnel list >/dev/null 2>&1; then
  warn "Not authed with Cloudflare. Browser will open for login."
  cloudflared tunnel login
fi
ok "Cloudflare auth working"

# 3. Tunnel exists?
TUNNEL_UUID=$(cloudflared tunnel list 2>/dev/null | awk -v n="$TUNNEL_NAME" '$2==n {print $1}' | head -1)
if [ -n "$TUNNEL_UUID" ]; then
  log "tunnel '$TUNNEL_NAME' already exists (UUID $TUNNEL_UUID)"
else
  log "creating tunnel '$TUNNEL_NAME'"
  cloudflared tunnel create "$TUNNEL_NAME"
  TUNNEL_UUID=$(cloudflared tunnel list 2>/dev/null | awk -v n="$TUNNEL_NAME" '$2==n {print $1}' | head -1)
  if [ -z "$TUNNEL_UUID" ]; then
    err "tunnel creation failed — UUID not returned"
    exit 1
  fi
fi
ok "Tunnel UUID: $TUNNEL_UUID"

# 4. Write the dedicated config file (side-by-side with dittobot/etc.)
log "writing $CONFIG_FILE"
cat > "$CONFIG_FILE" <<EOF
# BullpenLM tunnel — added by scripts/setup-named-tunnel.sh
# Stays separate from the main config.yml (dittobot/api.dittomethis.com)
# so neither config interferes with the other.

tunnel: $TUNNEL_UUID
credentials-file: $HOME/.cloudflared/$TUNNEL_UUID.json

ingress:
  - hostname: $HOSTNAME
    service: http://127.0.0.1:7878
    originRequest:
      connectTimeout: 30s
      tcpKeepAlive: 30s
      # SSE (audit-chain live feed) needs long-lived connections
      noHappyEyeballs: true

  - service: http_status:404
EOF
ok "Config file written"

# 5. DNS route — only run if the hostname isn't already routed.
log "ensuring DNS for $HOSTNAME"
if cloudflared tunnel route dns "$TUNNEL_NAME" "$HOSTNAME" 2>&1 | tee /tmp/cf-dns-out.log | grep -qi "already exists\|already configured"; then
  log "DNS record already exists for $HOSTNAME — reusing"
elif grep -qi "added CNAME" /tmp/cf-dns-out.log; then
  ok "DNS record added: $HOSTNAME → $TUNNEL_UUID.cfargotunnel.com"
fi

# 6. Stop any old cloudflared instance for the same name
PREV=$(pgrep -f "cloudflared.*$TUNNEL_NAME" || true)
if [ -n "$PREV" ]; then
  log "stopping previous '$TUNNEL_NAME' cloudflared (pid $PREV)"
  echo "$PREV" | xargs -r kill 2>/dev/null
  sleep 2
fi

# 7. Run the tunnel in the background
mkdir -p "$HOME/.bullpenlm"
log "starting tunnel '$TUNNEL_NAME' in background"
nohup cloudflared --no-autoupdate --config "$CONFIG_FILE" tunnel run "$TUNNEL_NAME" \
  > "$HOME/.bullpenlm/tunnel-named.log" 2>&1 &
TUNNEL_PID=$!
sleep 5

if ! ps -p "$TUNNEL_PID" >/dev/null 2>&1; then
  err "tunnel didn't stay up. log tail:"
  tail -20 "$HOME/.bullpenlm/tunnel-named.log"
  exit 1
fi
ok "Tunnel running (pid $TUNNEL_PID, log $HOME/.bullpenlm/tunnel-named.log)"

# 8. Update ~/.bullpenlm/tunnel.json + tunnel-url so the magic-link generator
#    + invite-ready diagnostic + host panel all pick up the new URL.
python3 - <<PY
import json, datetime
from pathlib import Path
url = "https://$HOSTNAME"
state = {
    "running": True,
    "url": url,
    "pid": $TUNNEL_PID,
    "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "port": 7878,
    "named": True,
    "tunnel_name": "$TUNNEL_NAME",
}
(Path.home() / ".bullpenlm" / "tunnel.json").write_text(json.dumps(state, indent=2) + "\n")
(Path.home() / ".bullpenlm" / "tunnel-url").write_text(url + "\n")
print("  ✓ ~/.bullpenlm/tunnel.json + tunnel-url updated")
PY

# 9. Wait for DNS to propagate, then verify reachability
log "waiting up to 60s for DNS + tunnel connection to come up..."
for i in $(seq 1 12); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "https://$HOSTNAME/api/team/roster" 2>/dev/null || echo "000")
  if [ "$CODE" = "200" ]; then
    ok "tunnel reachable: https://$HOSTNAME (attempt $i)"
    break
  fi
  log "  attempt $i (${i}*5s): HTTP $CODE"
  sleep 5
done

if [ "$CODE" != "200" ]; then
  warn "tunnel didn't reach 200 within 60s. Check ~/.bullpenlm/tunnel-named.log"
  warn "  cloudflared often needs a minute to register; retry: curl https://$HOSTNAME/api/team/roster"
fi

# 10. Final hint
hr
echo
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}  NAMED TUNNEL LIVE: https://$HOSTNAME${RESET}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${RESET}"
echo
echo "  Magic link generator now uses this URL:"
echo "    python3 server/invites.py magic-link <friend-name> --bullpen ghengis"
echo
echo "  Or via the host control panel:"
echo "    https://$HOSTNAME/app/host.html"
echo
echo "  To make this tunnel run on boot (background daemon):"
echo "    sudo cloudflared --config $CONFIG_FILE service install"
echo "    sudo launchctl start com.cloudflare.cloudflared"
echo
echo "  To stop:  pkill -f 'cloudflared.*$TUNNEL_NAME'"
echo
hr
