"""Briefing — the single composer for "what we're selling" + "what's working".

A new friend joins, opens /app/briefing.html, and ramps up in ten minutes.
The composer pulls together what we already have:

  • bullpen.json                                  — product, founder
  • legal/cheat-card.md, playbook.md, the-gauntlet.md, house-accounts.md
  • legal/referral-agreement.md (rate table)      — commission economics
  • organizations/*/org.json                       — verticals + reps' coverage
  • audit log — recent close-wons (proof + reference customers)
              — top openers / closers (what's working RIGHT NOW)

No new on-disk state.
"""
from __future__ import annotations
import json
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"
ORGS_ROOT = REPO / "organizations"


def _read(p: Path) -> str:
    if not p.exists(): return ""
    try: return p.read_text(encoding="utf-8")
    except Exception: return ""


def _section(md: str, header_re: str) -> str:
    """Pull a single section out of a markdown file by header regex.
    Returns the body up to the next H1/H2."""
    if not md: return ""
    m = re.search(header_re + r"\s*\n+(.*?)(?=\n#{1,2}\s|\Z)", md, re.S | re.I)
    return (m.group(1).strip() if m else "")


def for_bullpen(bullpen: str) -> dict:
    bdir = BULLPENS_ROOT / bullpen
    legal = bdir / "legal"

    bp = {}
    try: bp = json.loads((bdir / "bullpen.json").read_text())
    except Exception: pass

    cheat    = _read(legal / "cheat-card.md")
    playbook = _read(legal / "playbook.md")
    gauntlet = _read(legal / "the-gauntlet.md")
    house    = _read(legal / "house-accounts.md")
    referral = _read(legal / "referral-agreement.md")

    # ── Verticals covered ──
    verticals: Counter = Counter()
    org_count = 0
    for f in ORGS_ROOT.glob("*/org.json"):
        try: org = json.loads(f.read_text())
        except Exception: continue
        org_count += 1
        v = (org.get("vertical") or org.get("industry") or "Other").strip()
        if v: verticals[v] += 1

    # ── Commission economics ──
    try:
        from legal import parse_rate_table
        rates = parse_rate_table(referral) if referral else []
    except Exception:
        rates = []

    # ── Recent close-wons + win signal ──
    closes: list[dict] = []
    booking_outcomes: Counter = Counter()
    try:
        from audit import iter_all
        for e in iter_all(bullpen):
            k = e.get("kind")
            if k == "deal_closed_won":
                p = e.get("payload") or {}
                closes.append({
                    "ts": e.get("ts"),
                    "rep": e.get("actor"),
                    "prospect": p.get("prospect") or e.get("target_id"),
                    "amount": p.get("amount") or 0,
                })
            elif k == "call":
                p = e.get("payload") or {}
                if p.get("outcome"):
                    booking_outcomes[p["outcome"]] += 1
    except Exception:
        pass
    closes.sort(key=lambda c: c["ts"] or "", reverse=True)

    # ── Most-claimed prospects (signal of "where the team is fishing") ──
    most_active: Counter = Counter()
    try:
        from audit import iter_all
        for e in iter_all(bullpen):
            if e.get("kind") in ("call", "claim", "deal_created"):
                pros = ((e.get("payload") or {}).get("prospect")
                        or (e.get("payload") or {}).get("prospect_slug"))
                if pros: most_active[pros] += 1
    except Exception:
        pass

    # ── House accounts (extract the bullets) ──
    house_accounts = []
    if house:
        for line in house.splitlines():
            m = re.match(r"^\s*[-*]\s+(.+)$", line)
            if m:
                house_accounts.append(m.group(1).strip())

    # ── Pull the OPENER block out of the cheat-card (the script reps memorize) ──
    opener = ""
    if cheat:
        # Find content under "## OPENER" or "OPENER (memorize)" header
        m = re.search(r"^#{1,3}\s+(?:THE\s+)?OPENER[^\n]*\n+(.*?)(?=\n#{1,3}\s|\Z)",
                      cheat, re.S | re.I | re.M)
        if m:
            opener = m.group(1).strip()
            # Strip leading "> " quote prefixes that are common in these docs
            opener = "\n".join(re.sub(r"^>\s?", "", l) for l in opener.splitlines()).strip()

    return {
        "bullpen": bp,
        "product": bp.get("product") or bp.get("name") or bullpen,
        "founder": bp.get("founder_rep"),
        "opener": opener,
        "verticals_top": [{"name": v, "count": n}
                          for v, n in verticals.most_common(10)],
        "verticals_total_orgs": org_count,
        "commission_rates": rates,
        "recent_closes": closes[:6],
        "booking_outcomes": dict(booking_outcomes),
        "most_active_prospects": [{"slug": s, "count": n}
                                  for s, n in most_active.most_common(8)],
        "house_accounts": house_accounts[:20],
        "docs": {
            "cheat_card": cheat,
            "playbook":   playbook,
            "gauntlet":   gauntlet,
            "house":      house,
        },
    }
