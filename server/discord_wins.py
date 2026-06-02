"""Discord wins webhook — pings the bullpen's celebration channel when
a deal closes won. Lives outside the chat loop so a flaky network
doesn't block the deal-stage move itself.

Configuration lives in the bullpen's config under
`webhooks.discord_wins_url` (a full Discord webhook URL). When unset,
this module is a no-op — the bell still rings, XP still credits, the
trophy still drops. Only the cross-network celebration is skipped.

The post is a single embed with the closer's display name, amount,
prospect, and a link to the deal inside the app. Discord rate-limits
to ~30/minute on a webhook so we don't queue or retry — wins are
sparse enough that a single best-effort POST is fine.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Optional


def _bullpen_webhook_url(bullpen: str) -> Optional[str]:
    """Read the per-bullpen Discord wins webhook URL, if set."""
    try:
        from bullpens import get_bullpen
        cfg = get_bullpen(bullpen) or {}
    except Exception:
        return None
    return ((cfg.get("webhooks") or {}).get("discord_wins_url") or "").strip() or None


def _format_amount(n: float) -> str:
    if not n: return "$0"
    if n >= 1_000_000: return f"${n/1_000_000:.1f}M"
    if n >= 1_000: return f"${round(n/1_000)}k"
    return f"${int(n)}"


def maybe_post_close_won(bullpen: str, rep: str, deal: dict) -> bool:
    """POST a close-won celebration if a webhook is configured.

    Returns True on success / False on no-op / any error. Never raises.
    """
    url = _bullpen_webhook_url(bullpen)
    if not url:
        return False
    amount = float(deal.get("amount") or 0)
    prospect = deal.get("prospect_slug") or "—"
    deal_id = deal.get("id") or ""
    payload = {
        "username": "BullpenLM",
        "embeds": [{
            "title": f"🔔 {rep} closed {prospect}",
            "description": f"**{_format_amount(amount)}** booked.",
            "color": 0x34D399,  # accent-mint to match in-app brand
            "fields": [
                {"name": "Closer", "value": rep, "inline": True},
                {"name": "Amount", "value": _format_amount(amount), "inline": True},
                {"name": "Deal", "value": f"`{deal_id}`", "inline": False},
            ],
        }],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False
