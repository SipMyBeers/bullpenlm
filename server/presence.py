"""Presence — who's online in a bullpen right now and what they're doing.

In-memory only (no disk). A rep is "online" if they posted a heartbeat
within the last PRESENCE_TTL seconds. Every heartbeat also records the
current page slug ("floor", "deals", "pvp", "legal", …) and an optional
status string ("dialing allstate", "writing notes").

We don't need persistence — when the server restarts, presence resets
and the next page load re-establishes it within 20s.
"""
from __future__ import annotations
import datetime
import threading
from typing import Optional

PRESENCE_TTL = 60   # seconds — must exceed the client heartbeat interval (20s)

_lock = threading.Lock()
# (bullpen, rep) → {ts, page, status, color}
_presence: dict[tuple[str, str], dict] = {}


def beat(bullpen: str, rep: str, page: Optional[str] = None,
         status: Optional[str] = None, color: Optional[str] = None) -> dict:
    """Record a heartbeat. Returns the freshly stored record."""
    with _lock:
        now = datetime.datetime.now()
        prior = _presence.get((bullpen, rep), {})
        rec = {
            "rep": rep,
            "bullpen": bullpen,
            "ts": now.isoformat(timespec="seconds"),
            "ts_epoch": int(now.timestamp()),
            "page": page or prior.get("page") or "floor",
            "status": status if status is not None else prior.get("status") or "",
            "color": color or prior.get("color"),
        }
        _presence[(bullpen, rep)] = rec
        return rec


def roster(bullpen: str) -> list[dict]:
    """Return everyone currently online in `bullpen`, sorted by recency."""
    now = int(datetime.datetime.now().timestamp())
    with _lock:
        live = [r for (b, _r), r in _presence.items()
                if b == bullpen and (now - r["ts_epoch"]) <= PRESENCE_TTL]
    live.sort(key=lambda r: -r["ts_epoch"])
    return live


def get(bullpen: str, rep: str) -> Optional[dict]:
    """One-off lookup. Returns None if not currently online."""
    now = int(datetime.datetime.now().timestamp())
    with _lock:
        rec = _presence.get((bullpen, rep))
        if not rec:
            return None
        if (now - rec["ts_epoch"]) > PRESENCE_TTL:
            return None
        return dict(rec)


def clear(bullpen: str, rep: str) -> None:
    """Explicit sign-out (user closed tab and clicked logout)."""
    with _lock:
        _presence.pop((bullpen, rep), None)
