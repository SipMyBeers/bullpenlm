"""Trophies — deterministic loot drops on closed-won deals.

A trophy roll is keyed off (deal_id, amount) so the same deal always
yields the same drop — no double-claims, no race conditions. Rarity
weights skew with deal size: a $50K close is much more likely to roll
legendary than a $1K close.

Storage layout (per bullpen):
  bullpens/<slug>/trophies/<rep>.jsonl    — append-only awarded trophies

Trophy schema:
  {id, deal_id, rep, awarded_at, rarity, name, icon, sub}
"""
from __future__ import annotations
import datetime
import hashlib
import json
import random
from pathlib import Path
from typing import Optional

from audit import append as audit_append
from audit import iter_all as audit_iter_all

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


# Trophy library — keep small. Each entry is a (rarity, name, icon, sub).
TROPHIES = {
    "common": [
        {"name": "Logo Sticker",      "icon": "🪧", "sub": "Slap it on your laptop."},
        {"name": "Door Knock",        "icon": "🚪", "sub": "You opened it."},
        {"name": "Coffee Mug",        "icon": "☕", "sub": "Earned, not given."},
        {"name": "Tally Mark",        "icon": "✓",  "sub": "Another one on the board."},
        {"name": "Cigar Band",        "icon": "🟫", "sub": "Smelled, not lit."},
    ],
    "rare": [
        {"name": "Brass Bell",        "icon": "🔔", "sub": "Ring it. The bullpen hears."},
        {"name": "Animated Banner",   "icon": "🎌", "sub": "Lights up over your name."},
        {"name": "Silver Cufflinks",  "icon": "💎", "sub": "Costume upgrade."},
        {"name": "Trophy Pen",        "icon": "🖊️", "sub": "Sign the next one with this."},
    ],
    "epic": [
        {"name": "Custom Title",      "icon": "👑", "sub": "A line under your name only you control."},
        {"name": "Marble Plaque",     "icon": "🏛", "sub": "Etched into the bullpen wall."},
        {"name": "Golden Microphone", "icon": "🎙", "sub": "Lead the morning huddle next week."},
    ],
    "legendary": [
        {"name": "Rolex Drop",        "icon": "⌚", "sub": "Bullpen-wide announcement. Glass case."},
        {"name": "The Glengarry",     "icon": "🏆", "sub": "ABC. Always. Be. Closing."},
        {"name": "Bullpen Hall of Fame","icon": "🌟", "sub": "Permanent fixture on the home page."},
    ],
}


def _trophies_path(bullpen: str, rep: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "trophies"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{rep}.jsonl"


def _rarity_weights_for(amount: float) -> list[tuple[str, float]]:
    """Return weighted rarity distribution scaled by deal size.

    A trivial deal (<$1K) is almost always common; a whale (>$100K) is
    weighted toward legendary."""
    if amount >= 100000:
        return [("common", 0.10), ("rare", 0.30), ("epic", 0.35), ("legendary", 0.25)]
    if amount >= 50000:
        return [("common", 0.20), ("rare", 0.40), ("epic", 0.30), ("legendary", 0.10)]
    if amount >= 15000:
        return [("common", 0.40), ("rare", 0.40), ("epic", 0.18), ("legendary", 0.02)]
    if amount >= 5000:
        return [("common", 0.60), ("rare", 0.32), ("epic", 0.08), ("legendary", 0.00)]
    return [("common", 0.80), ("rare", 0.18), ("epic", 0.02), ("legendary", 0.00)]


def _deterministic_pick(deal_id: str, amount: float) -> dict:
    """Roll a trophy deterministically from the deal_id+amount seed."""
    seed = int(hashlib.sha256(f"{deal_id}|{amount}".encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    weights = _rarity_weights_for(amount)
    r = rng.random()
    acc = 0.0
    rarity = weights[0][0]
    for name, w in weights:
        acc += w
        if r <= acc:
            rarity = name
            break
    pool = TROPHIES[rarity]
    pick = pool[rng.randrange(len(pool))]
    return {
        "deal_id": deal_id,
        "rarity": rarity,
        "name": pick["name"],
        "icon": pick["icon"],
        "sub": pick["sub"],
    }


def existing_for_deal(bullpen: str, deal_id: str) -> Optional[dict]:
    """Find a trophy already awarded for `deal_id`, across all reps."""
    root = BULLPENS_ROOT / bullpen / "trophies"
    if not root.exists():
        return None
    for f in root.glob("*.jsonl"):
        for line in f.read_text().splitlines():
            try:
                t = json.loads(line)
            except Exception:
                continue
            if t.get("deal_id") == deal_id:
                return t
    return None


def award(bullpen: str, deal_id: str, rep: str, amount: float) -> dict:
    """Award (or return existing) trophy for one closed-won deal."""
    prior = existing_for_deal(bullpen, deal_id)
    if prior:
        return prior
    trophy = _deterministic_pick(deal_id, amount)
    trophy["id"] = f"trophy-{deal_id}"
    trophy["rep"] = rep
    trophy["awarded_at"] = datetime.datetime.now().isoformat(timespec="seconds")

    with _trophies_path(bullpen, rep).open("a") as f:
        f.write(json.dumps(trophy) + "\n")

    audit_append(bullpen, rep, "trophy_awarded",
                 target_type="trophy", target_id=trophy["id"],
                 payload={"deal_id": deal_id, "rarity": trophy["rarity"],
                          "name": trophy["name"], "icon": trophy["icon"]})
    return trophy


def for_rep(bullpen: str, rep: str) -> list[dict]:
    p = _trophies_path(bullpen, rep)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try: out.append(json.loads(line))
        except Exception: continue
    out.sort(key=lambda t: t.get("awarded_at", ""), reverse=True)
    return out


def backfill(bullpen: str) -> list[dict]:
    """Walk the audit log; award a trophy for every deal_closed_won
    that doesn't already have one. Idempotent."""
    new = []
    for e in audit_iter_all(bullpen):
        if e.get("kind") != "deal_closed_won":
            continue
        deal_id = e.get("target_id")
        rep = e.get("actor")
        amount = float((e.get("payload") or {}).get("amount") or 0)
        if not deal_id or not rep:
            continue
        if existing_for_deal(bullpen, deal_id):
            continue
        new.append(award(bullpen, deal_id, rep, amount))
    return new


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 server/trophies.py <bullpen> [backfill|<rep>]")
        sys.exit(0)
    bullpen = sys.argv[1]
    arg = sys.argv[2] if len(sys.argv) > 2 else "backfill"
    if arg == "backfill":
        new = backfill(bullpen)
        print(f"  Backfilled {len(new)} trophies.")
        for t in new:
            print(f"    {t['icon']} {t['name']} ({t['rarity']}) → {t['rep']} from {t['deal_id']}")
    else:
        for t in for_rep(bullpen, arg):
            print(f"  {t['icon']} {t['name']} ({t['rarity']})  {t['awarded_at']}  {t['deal_id']}")
