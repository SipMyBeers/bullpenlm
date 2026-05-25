"""Discord webhook — post bullpen highlights to the team Discord channel.

Subscribes to audit events. When a deal closes, a raid completes, or an
achievement unlocks at epic/legendary, posts a formatted message via the
bullpen's configured webhook.

Setup: in bullpens/<slug>/bullpen.json, set:
  "discord_webhook": "https://discord.com/api/webhooks/..."

No webhook configured = no-op (safe).

Posts run on a background thread so the audit/SSE path isn't blocked
by Discord latency.
"""
from __future__ import annotations
import json
import threading
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"


def _webhook_for(bullpen: str) -> Optional[str]:
    f = BULLPENS_ROOT / bullpen / "bullpen.json"
    if not f.exists(): return None
    try: cfg = json.loads(f.read_text())
    except Exception: return None
    return (cfg.get("discord_webhook") or "").strip() or None


def _post(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as _:
            pass
    except urllib.error.HTTPError as e:
        # Discord returns 204 No Content on success; anything else is logged.
        if e.code not in (200, 204):
            print(f"[discord] webhook error {e.code}: {e.read()[:200]!r}")
    except Exception as e:
        print(f"[discord] webhook failed: {e}")


def _post_async(url: str, payload: dict) -> None:
    threading.Thread(target=_post, args=(url, payload), daemon=True).start()


def _money(n) -> str:
    try: return "$" + format(float(n), ",.0f")
    except Exception: return str(n)


def notify(bullpen: str, event: dict) -> None:
    """Called from audit.append's fan-out. Inspect `event`, decide if it's
    notable, and fire."""
    url = _webhook_for(bullpen)
    if not url:
        return

    kind = event.get("kind")
    p = event.get("payload") or {}
    actor = event.get("actor") or "?"

    if kind == "deal_closed_won":
        prospect = p.get("prospect") or event.get("target_id") or "a deal"
        amount = _money(p.get("amount") or 0)
        _post_async(url, {
            "username": "BullpenLM 🔔",
            "content": f"🔔 **{actor}** just closed **{prospect}** for **{amount}** in {bullpen}",
            "embeds": [{
                "color": 0x34d399,
                "fields": [
                    {"name": "Rep",      "value": actor,    "inline": True},
                    {"name": "Prospect", "value": prospect, "inline": True},
                    {"name": "Amount",   "value": amount,   "inline": True},
                ],
            }],
        })
        return

    if kind == "achievement_unlocked" and (p.get("rarity") in ("epic", "legendary")):
        rarity = p.get("rarity")
        name = p.get("name") or event.get("target_id") or "an achievement"
        emoji = "🌟" if rarity == "legendary" else "💜"
        _post_async(url, {
            "username": "BullpenLM",
            "content": f"{emoji} **{actor}** unlocked **{name}** ({rarity.upper()}) in {bullpen}",
        })
        return

    if kind == "quest_completed" and (p.get("scope") in ("raid",)):
        name = p.get("quest_name") or event.get("target_id") or "a raid"
        xp = p.get("xp_reward") or 0
        size = p.get("party_size") or 0
        _post_async(url, {
            "username": "BullpenLM",
            "content": f"🐉 **{actor}** finished raid **{name}** with party of {size} — +{xp} XP",
        })
        return

    if kind == "sprint_started":
        name = p.get("name") or event.get("target_id") or "a sprint"
        _post_async(url, {
            "username": "BullpenLM",
            "content": f"⚔ **{actor}** kicked off **{name}** — get on the phones",
        })
        return

    if kind == "duo_challenged":
        opp = p.get("opponent") or "?"
        prospect = p.get("prospect") or ""
        _post_async(url, {
            "username": "BullpenLM",
            "content": f"🥊 **{actor}** challenged **{opp}** to a 1v1 on {prospect}",
        })
        return
