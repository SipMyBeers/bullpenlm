"""Rank ladders + the shared promotion contract.

See docs/RANK_STUDY_CONTRACT.md for the canonical shape. Ranks are CONFIG ROWS,
not hardcoded — each org/bullpen defines its own ladder in
bullpens/<slug>/ranks.json; absent that, the BullpenLM default ladder
(Rookie -> Legend) is used.

This module is BullpenLM's concrete ADAPTER of the contract: promotion_check()
fills the canonical payload from BullpenLM's own data —
  knowledge  <- Gauntlet tiers cleared        (tcs.top_pack)
  quiz       <- Tier-3 drill cert             (gates.can_claim_live_prospect)
  production <- deal_closed_won this month     (audit)
Swap this adapter for another spine later without touching any consumer.

KOSCOT FIREWALL: production.metric is always personal sales — never recruiting.
"""
import json
import datetime
from pathlib import Path

try:
    from paths import DATA_DIR
except Exception:
    import os
    DATA_DIR = Path(os.environ.get("BULLPENLM_HOME",
                    str(Path.home() / "Library/Application Support/BullpenLM")))


def _g(source_kind, sources_total, quiz, sales):
    return {"knowledge": {"source_kind": source_kind, "sources_total": sources_total,
                          "quiz_required": quiz},
            "production": {"metric": "sales", "threshold": sales, "window": "month"}}


# BullpenLM's default ladder. `xp_hint` is an OPTIONAL display-only hint for the
# lightweight roster chip; the authoritative promotion gate is always gate_rule.
DEFAULT_RANKS = [
    {"id": "rookie",   "name": "Rookie",   "order": 0, "comp_label": "Lvl 1", "xp_hint": 0,     "gate_rule": _g("gauntlet", 0, False, 0)},
    {"id": "walk-on",  "name": "Walk-On",  "order": 1, "comp_label": "Lvl 2", "xp_hint": 250,   "gate_rule": _g("gauntlet", 2, False, 1)},
    {"id": "starter",  "name": "Starter",  "order": 2, "comp_label": "Lvl 3", "xp_hint": 1000,  "gate_rule": _g("gauntlet", 3, False, 3)},
    {"id": "closer",   "name": "Closer",   "order": 3, "comp_label": "Lvl 4", "xp_hint": 2500,  "gate_rule": _g("gauntlet", 5, True,  5)},
    {"id": "all-star", "name": "All-Star", "order": 4, "comp_label": "Lvl 5", "xp_hint": 5000,  "gate_rule": _g("gauntlet", 6, True,  10)},
    {"id": "legend",   "name": "Legend",   "order": 5, "comp_label": "Lvl 6", "xp_hint": 10000, "gate_rule": _g("gauntlet", 7, True,  20)},
]


def _ranks_path(bullpen: str) -> Path:
    return Path(DATA_DIR) / "bullpens" / bullpen / "ranks.json"


def ranks(bullpen: str):
    """The org's rank ladder (config rows), ordered. Falls back to the default."""
    try:
        rows = json.loads(_ranks_path(bullpen).read_text())
        if isinstance(rows, list) and rows:
            rows = sorted(rows, key=lambda r: r.get("order", 0))
            return [dict(r, org_id=bullpen) for r in rows]
    except Exception:
        pass
    return [dict(r, org_id=bullpen) for r in DEFAULT_RANKS]


# ── adapter: fill the contract from BullpenLM data ────────────────────
def _sales_this_month(bullpen: str, agent: str) -> int:
    try:
        from audit import iter_all
    except Exception:
        return 0
    ym = datetime.datetime.now().strftime("%Y-%m")
    return sum(1 for e in iter_all(bullpen)
               if e.get("actor") == agent and e.get("kind") == "deal_closed_won"
               and str(e.get("ts", "")).startswith(ym))


def _tiers_cleared(bullpen: str, agent: str) -> int:
    try:
        from tcs import top_pack
        tp = top_pack(bullpen, agent)
        return len({c.get("phase_tier") for c in tp.get("cleared", []) if c.get("phase_tier")})
    except Exception:
        return 0


def _cert_passed(bullpen: str, agent: str) -> bool:
    try:
        from gates import can_claim_live_prospect
        chk = can_claim_live_prospect(bullpen, agent)
        return "drill_certification_not_cleared" not in (getattr(chk, "missing", None) or [])
    except Exception:
        return False


def promotion_check(bullpen: str, agent: str, rank_id: str):
    """Canonical promotion_check payload (docs/RANK_STUDY_CONTRACT.md §3)."""
    row = next((r for r in ranks(bullpen) if r["id"] == rank_id), None)
    if row is None:
        return None
    kn = row.get("gate_rule", {}).get("knowledge", {})
    pr = row.get("gate_rule", {}).get("production", {})
    total = int(kn.get("sources_total", 0))
    studied = _tiers_cleared(bullpen, agent) if kn.get("source_kind") == "gauntlet" else 0
    if total:
        studied = min(studied, total)
    quiz_passed = (not kn.get("quiz_required")) or _cert_passed(bullpen, agent)
    threshold = int(pr.get("threshold", 0))
    sales = _sales_this_month(bullpen, agent)
    eligible = studied >= total and bool(quiz_passed) and sales >= threshold
    return {
        "rank": {"id": row["id"], "name": row["name"], "order": row["order"],
                 "comp_label": row["comp_label"]},
        "knowledge": {"sources_studied": studied, "sources_total": total,
                      "quiz_passed": bool(quiz_passed)},
        "production": {"sales_this_month": sales, "threshold": threshold},
        "eligible": bool(eligible),
    }


def current_order(bullpen: str, agent: str) -> int:
    """Highest rank order the agent is eligible for = their current rank."""
    cur = 0
    for r in ranks(bullpen):
        chk = promotion_check(bullpen, agent, r["id"])
        if chk and chk["eligible"]:
            cur = max(cur, r["order"])
    return cur


def ladder(bullpen: str, agent: str):
    """The full read a scorecard needs: ladder rows + current rank + next gate."""
    rows = ranks(bullpen)
    cur = current_order(bullpen, agent)
    nxt = next((r for r in rows if r["order"] > cur), None)
    return {
        "org_id": bullpen,
        "ranks": [{"id": r["id"], "name": r["name"], "order": r["order"],
                   "comp_label": r["comp_label"], "xp_hint": r.get("xp_hint")} for r in rows],
        "current_order": cur,
        "next_check": promotion_check(bullpen, agent, nxt["id"]) if nxt else None,
    }
