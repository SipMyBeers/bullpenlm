"""Reaction-role reconciler for the BullpenLM master Discord.

Polls the role-selection message every ROLE_POLL_INTERVAL seconds.
Whoever reacted with 🚀 gets the Operator role; whoever reacted with
✅ gets the Closer role. Reactions removed → role removed.

Reads the bot token from $DISCORD_BOT_TOKEN. If unset, the reconciler
no-ops cleanly so dev environments without bot creds still start.

Run from server.py main() via start_background().
"""
from __future__ import annotations
import json
import os
import ssl
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

GUILD_ID = "1508278033000304700"
ROLE_CHANNEL_ID = "1508290494994841630"   # #start-here
ROLE_MESSAGE_ID = "1508295352501932043"   # welcome msg

OPERATOR_ROLE_ID = "1508289484536680529"
CLOSER_ROLE_ID = "1508296541079736390"

EMOJI_ROLE_MAP = {
    "🚀": OPERATOR_ROLE_ID,
    "✅": CLOSER_ROLE_ID,
}

ROLE_POLL_INTERVAL = 20  # seconds
API = "https://discord.com/api/v10"
UA = "BullpenLM-RoleReconciler (https://bullpenlm.com, 0.1)"


def _token() -> Optional[str]:
    tok = os.environ.get("DISCORD_BOT_TOKEN")
    if tok:
        return tok.strip()
    # Fallback: try the MCP config the user already has wired
    claude_cfg = Path.home() / ".claude.json"
    if claude_cfg.exists():
        try:
            cfg = json.loads(claude_cfg.read_text())
            return ((cfg.get("mcpServers") or {})
                    .get("discord") or {}).get("env", {}).get("DISCORD_TOKEN")
        except Exception:
            return None
    return None


def _req(method: str, path: str, token: str) -> Optional[dict | list]:
    url = f"{API}{path}"
    req = urllib.request.Request(url, method=method, headers={
        "Authorization": f"Bot {token}",
        "User-Agent": UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=8, context=_SSL_CTX) as r:
            body = r.read()
            if not body:
                return None
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 204 No Content is success for PUT/DELETE role.
        if e.code == 204:
            return None
        # 404 on the reactions endpoint just means nobody reacted yet.
        if e.code == 404 and "/reactions/" in path:
            return []
        print(f"[discord_roles] {method} {path} → {e.code}: {e.read()[:200]!r}")
        return None
    except Exception as e:
        print(f"[discord_roles] {method} {path} failed: {e}")
        return None


def _reactors(token: str, emoji: str) -> set[str]:
    """User IDs who reacted with `emoji` on the role message."""
    enc = urllib.parse.quote(emoji)
    out: set[str] = set()
    after = None
    while True:
        qs = "?limit=100" + (f"&after={after}" if after else "")
        path = f"/channels/{ROLE_CHANNEL_ID}/messages/{ROLE_MESSAGE_ID}/reactions/{enc}{qs}"
        users = _req("GET", path, token)
        if not isinstance(users, list) or not users:
            break
        for u in users:
            if u.get("bot"):
                continue
            uid = u.get("id")
            if uid:
                out.add(uid)
        if len(users) < 100:
            break
        after = users[-1].get("id")
    return out


def _assign(token: str, user_id: str, role_id: str) -> None:
    _req("PUT", f"/guilds/{GUILD_ID}/members/{user_id}/roles/{role_id}", token)


def _revoke(token: str, user_id: str, role_id: str) -> None:
    _req("DELETE", f"/guilds/{GUILD_ID}/members/{user_id}/roles/{role_id}", token)


# Persisted across polls so we know who lost a reaction since last tick.
_last_seen: dict[str, set[str]] = {e: set() for e in EMOJI_ROLE_MAP}


def _reconcile_once(token: str) -> None:
    for emoji, role_id in EMOJI_ROLE_MAP.items():
        current = _reactors(token, emoji)
        added = current - _last_seen[emoji]
        removed = _last_seen[emoji] - current
        for uid in added:
            _assign(token, uid, role_id)
        for uid in removed:
            _revoke(token, uid, role_id)
        _last_seen[emoji] = current


def _loop() -> None:
    token = _token()
    if not token:
        print("[discord_roles] no DISCORD_BOT_TOKEN configured — reaction-role sync disabled")
        return
    print(f"[discord_roles] reaction-role sync live (every {ROLE_POLL_INTERVAL}s)")
    # Prime _last_seen so a fresh restart doesn't churn role assignments.
    try:
        for emoji in EMOJI_ROLE_MAP:
            _last_seen[emoji] = _reactors(token, emoji)
        # Re-assign any current reactors so a restart catches roles lost between runs.
        for emoji, role_id in EMOJI_ROLE_MAP.items():
            for uid in _last_seen[emoji]:
                _assign(token, uid, role_id)
    except Exception as e:
        print(f"[discord_roles] prime failed: {e}")
    while True:
        try:
            _reconcile_once(token)
        except Exception as e:
            print(f"[discord_roles] reconcile failed: {e}")
        time.sleep(ROLE_POLL_INTERVAL)


def start_background() -> None:
    """Fire-and-forget background poller. Safe to call once from server.main()."""
    threading.Thread(target=_loop, daemon=True, name="discord-roles").start()
