"""Discord webhook — post bullpen highlights to the team Discord channel.

Subscribes to audit events. When a deal closes, a raid completes, or an
achievement unlocks at epic/legendary, posts a formatted message via the
bullpen's configured webhook.

Voice and emoji usage are dictated by BEERS_BOT_SOUL.md at the repo root.
Allowed emojis: ✅ 🚀 💯 ❗ — nothing else.

Setup: in bullpens/<slug>/bullpen.json, set:
  "discord_webhook": "https://discord.com/api/webhooks/..."

No webhook configured = no-op (safe).

Posts run on a background thread so the audit/SSE path isn't blocked
by Discord latency.
"""
from __future__ import annotations
import json
import ssl
import threading
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"

BOT_NAME = "Beers Bot"


def _webhook_for(bullpen: str) -> Optional[str]:
    f = BULLPENS_ROOT / bullpen / "bullpen.json"
    if not f.exists(): return None
    try: cfg = json.loads(f.read_text())
    except Exception: return None
    return (cfg.get("discord_webhook") or "").strip() or None


def _post(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "BullpenLM (https://bullpenlm.com, 0.1)",
    })
    try:
        with urllib.request.urlopen(req, timeout=5, context=_SSL_CTX) as _:
            pass
    except urllib.error.HTTPError as e:
        if e.code not in (200, 204):
            print(f"[discord] webhook error {e.code}: {e.read()[:200]!r}")
    except Exception as e:
        print(f"[discord] webhook failed: {e}")


def _post_async(url: str, payload: dict) -> None:
    threading.Thread(target=_post, args=(url, payload), daemon=True).start()


def _money(n) -> str:
    try: return "$" + format(float(n), ",.0f")
    except Exception: return str(n)


def _send(url: str, content: str) -> None:
    _post_async(url, {"username": BOT_NAME, "content": content})


SHOWCASE_WEBHOOK_PATH = Path.home() / ".bullpenlm" / "showcase-webhook.txt"


def _fire_bumblebee_event(event: str, channel: Optional[str] = None,
                            webhook_url: Optional[str] = None,
                            caption: str = "") -> None:
    """Best-effort Bumblebee stitch+post. Silently no-ops if the clip
    library is empty, the webhook isn't configured, or ffmpeg trips.
    Runs on a background thread so the caller doesn't block on audio
    rendering. Either `channel` (master-server webhook lookup) or
    `webhook_url` (per-bullpen webhook from bullpen.json) wins."""
    def _go():
        try:
            from bumblebee import stitch_event, post_audio_to_discord
            try:
                audio_path = stitch_event(event)
            except Exception as e:
                print(f"[bumblebee] skipping {event}: {e}")
                return
            r = post_audio_to_discord(audio_path, channel=channel,
                                       webhook_url=webhook_url, caption=caption)
            if not r.get("ok"):
                print(f"[bumblebee] post {event} failed: {r}")
        except Exception as e:
            print(f"[bumblebee] {event} crashed: {e}")
    threading.Thread(target=_go, daemon=True).start()


def _showcase_webhook() -> Optional[str]:
    """The master BullpenLM Discord #showcase webhook. Set per-host so the
    secret URL doesn't leak in the public repo."""
    if not SHOWCASE_WEBHOOK_PATH.exists():
        return None
    try:
        return SHOWCASE_WEBHOOK_PATH.read_text().strip() or None
    except Exception:
        return None


def announce_new_bullpen(bullpen_cfg: dict, public_url: Optional[str] = None) -> None:
    """Auto-post to the master #showcase when a new bullpen is created via
    the wizard. No-op if the per-host webhook isn't configured. Follows
    the BEERS_BOT_SOUL voice + emoji palette."""
    hook = _showcase_webhook()
    if not hook:
        return
    cfg = bullpen_cfg or {}
    slug = cfg.get("slug") or "?"
    name = cfg.get("name") or slug
    founder = cfg.get("founder_display_name") or cfg.get("founder_rep") or "an operator"
    product = cfg.get("product") or ""
    commission = cfg.get("commission_rate") or ""
    seats = cfg.get("seats_open")
    access_mode = cfg.get("access_mode") or "invite_only"
    price = cfg.get("price_usd")

    access_line = {
        "public": "**Access:** open floor — anyone joins",
        "invite_only": "**Access:** invite-only — operator vets you",
        "paid": f"**Access:** paid — ${price} to enter" if price else "**Access:** paid",
    }.get(access_mode, "**Access:** invite-only")

    lines = [
        f"🚀 **{name.upper()}** is open.",
        "",
        f"**Operator:** {founder}",
    ]
    if product:
        lines.append(f"**Selling:** {product}")
    if commission:
        lines.append(f"**Commission:** {commission}")
    if seats:
        lines.append(f"**Seats open:** {seats}")
    lines.append(access_line)

    if public_url:
        lines.append("")
        lines.append(f"**See the floor:** {public_url}/b/{slug}")

    lines.append("")
    lines.append("Closers — reply with your numbers if you want a seat. ✅")

    _post_async(hook, {
        "username": BOT_NAME,
        "content": "\n".join(lines),
    })

    # Beers Bot also speaks (Bumblebee-style) if the clip library has
    # enough material to render the recipe. No-op when clips are missing.
    _fire_bumblebee_event("new-bullpen", channel="showcase",
                            caption=f"🚀 **{name.upper()}** just opened.")


def notify(bullpen: str, event: dict) -> None:
    """Called from audit.append's fan-out. Inspect `event`, decide if it's
    notable, and fire. All copy follows BEERS_BOT_SOUL.md."""
    url = _webhook_for(bullpen)
    if not url:
        return

    kind = event.get("kind")
    p = event.get("payload") or {}
    actor = event.get("actor") or "?"

    if kind == "deal_closed_won":
        prospect = p.get("prospect") or event.get("target_id") or "a deal"
        amount = _money(p.get("amount") or 0)
        _send(url,
              f"🚀 **{actor}** just closed **{prospect}** — **{amount}**. "
              f"That's how it's done. ✅")
        _fire_bumblebee_event("close-won", webhook_url=url,
                                caption=f"🚀 **{actor}** just closed **{prospect}**.")
        # Auto-send the branded close-won-thanks email if a client email is
        # attached to the deal AND the Cloudflare Email Worker is configured.
        # No-op cleanly when either piece is missing.
        client_email = p.get("client_email") or p.get("prospect_email")
        if client_email:
            try:
                from email_send import send_template
                threading.Thread(target=send_template, args=(bullpen, "close-won-thanks", client_email),
                                  kwargs={"vars": {"first_name": p.get("client_first_name", ""),
                                                    "deal_name": prospect,
                                                    "deal_amount": amount},
                                          "actor": actor},
                                  daemon=True).start()
            except Exception as e:
                print(f"[email] close-won-thanks send failed: {e}")
        return

    if kind == "achievement_unlocked" and (p.get("rarity") in ("epic", "legendary")):
        rarity = p.get("rarity")
        name = p.get("name") or event.get("target_id") or "an achievement"
        marker = "🚀" if rarity == "legendary" else "💯"
        _send(url,
              f"{marker} **{actor}** just hit **{name}**. "
              f"That's **{rarity.upper()}**. Tip of the cap.")
        if rarity == "legendary":
            _fire_bumblebee_event("close-won", webhook_url=url,
                                    caption=f"{marker} **{actor}** unlocked **{name}**.")
        return

    if kind == "quest_completed" and (p.get("scope") in ("raid",)):
        name = p.get("quest_name") or event.get("target_id") or "a raid"
        xp = p.get("xp_reward") or 0
        size = p.get("party_size") or 0
        _send(url,
              f"✅ **{actor}** dragged a party of **{size}** over the line on "
              f"**{name}**. **+{xp} XP**. Crew's eating tonight.")
        _fire_bumblebee_event("raid-start", webhook_url=url,
                                caption=f"✅ Raid down — **{name}**.")
        return

    if kind == "sprint_started":
        name = p.get("name") or event.get("target_id") or "a sprint"
        _send(url,
              f"❗ Sprint live — **{name}**. Started by **{actor}**. "
              f"Pick up the phone. Pick up the phone. Pick up the phone.")
        _fire_bumblebee_event("sprint", webhook_url=url,
                                caption=f"❗ Sprint live — **{name}**.")
        return

    if kind == "duo_challenged":
        opp = p.get("opponent") or "?"
        prospect = p.get("prospect") or ""
        tail = f" on **{prospect}**" if prospect else ""
        _send(url,
              f"❗ **{actor}** just called out **{opp}**{tail}. "
              f"Step up or step off.")
        _fire_bumblebee_event("duel", webhook_url=url,
                                caption=f"❗ **{actor}** → **{opp}**.")
        return
