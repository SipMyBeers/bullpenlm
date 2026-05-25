"""XP rules + level curve + projection from the audit log.

Design contract: **XP is a derivation of the audit log, not a separate store.**
Every audit event has a corresponding XP delta (from `RULES`). We compute
totals on demand by streaming through `audit.iter_all(bullpen)`. A small
in-process cache (`_xp_cache`) avoids re-scanning on every request.

If the audit log changes (`audit.append`), call `invalidate(bullpen)` so
the next read recomputes.

Level curve: triangular progression — Lvl N requires ~250·N(N+1)/2 cumulative XP.
  Lvl 2:    750 XP
  Lvl 5:  3,750 XP
  Lvl 10: 13,750 XP
  Lvl 20: 52,500 XP
  Lvl 50: 318,750 XP  (soft cap; past 50 = "prestige")
"""
from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Optional

from audit import iter_all as audit_iter_all


# ── XP rules table — single source of truth ──────────────────────────────
#
# Each rule is matched against (event.kind, optional payload predicate).
# Order matters only for events that match multiple rules — we apply ALL
# matching rules (an event can earn multiple XP types).
#
# Some rules pull dynamic XP from the event payload (e.g. deal close-won
# scales with amount). Those use a callable instead of an int.

def _xp_close_won(payload: dict) -> int:
    amount = float(payload.get("amount") or 0)
    return int(100 + amount / 100)   # $15K deal = 250 XP, $50K = 600 XP

def _xp_stage_moved(payload: dict) -> int:
    delta = float(payload.get("prob_delta") or 0)
    return int(max(0, round(delta * 100)))   # +30% prob = 30 XP

def _xp_achievement_unlocked(payload: dict) -> int:
    rarity = payload.get("rarity") or "common"
    return {"common": 50, "rare": 200, "epic": 750, "legendary": 2000}.get(rarity, 50)


RULES: list[dict] = [
    # ── Practice / drills ──
    {"kind": "drill_attempt",     "xp": 10,  "reason": "Practice drill completed"},
    {"kind": "drill_passed",      "xp": 50,  "reason": "Drill passed",
     "bonus": lambda p: 25 * int(p.get("phase_tier") or 0)},  # +25 per phase tier

    # ── Real calls ──
    {"kind": "call",              "xp": 25,  "reason": "Real call uploaded",
     "match": lambda p: p.get("call_kind") == "real"},
    {"kind": "call",              "xp": 10,  "reason": "Practice call uploaded",
     "match": lambda p: p.get("call_kind") == "practice"},
    {"kind": "call",              "xp": 5,   "reason": "Speaking drill",
     "match": lambda p: p.get("call_kind") == "speaking"},

    # ── Debrief extraction ──
    {"kind": "debrief_extracted", "xp": 40,  "reason": "New contact extracted from call"},

    # ── Claims (territory) ──
    {"kind": "claim",             "xp": 5,   "reason": "Prospect claimed"},

    # ── Deal pipeline ──
    {"kind": "deal_created",      "xp": 20,  "reason": "Deal created"},
    {"kind": "deal_stage_moved",  "xp": _xp_stage_moved, "reason": "Deal advanced"},
    {"kind": "deal_closed_won",   "xp": _xp_close_won,   "reason": "DEAL CLOSED-WON"},

    # ── Legal / signatures ──
    {"kind": "doc_signed",        "xp": 50,  "reason": "Legal doc signed"},
    {"kind": "pilot_signed",      "xp": 500, "reason": "PILOT CONTRACT SIGNED"},

    # ── Mentor / teamwork ──
    {"kind": "mentor_flag",       "xp": 75,  "reason": "Helped a teammate"},

    # ── Achievement unlocks ──
    {"kind": "achievement_unlocked", "xp": _xp_achievement_unlocked, "reason": "Achievement"},

    # ── Quest completions ──
    {"kind": "quest_completed",   "xp": lambda p: int(p.get("xp_reward") or 0),
     "reason": "Quest completed"},

    # ── Follow-up discipline ──
    {"kind": "followup_done",     "xp": 8,   "reason": "Follow-up done"},

    # ── Activity types beyond raw 'call' ──
    {"kind": "activity_email",    "xp": 6,   "reason": "Email sent"},
    {"kind": "activity_meeting",  "xp": 40,  "reason": "Meeting logged"},
    {"kind": "activity_note",     "xp": 2,   "reason": "Note added"},
    {"kind": "contact_created",   "xp": 10,  "reason": "New contact added"},
]


# ── Level curve ──────────────────────────────────────────────────────────

def xp_for_level(n: int) -> int:
    """Cumulative XP required to reach level n. Lvl 1 = 0 XP."""
    if n <= 1:
        return 0
    return 250 * n * (n - 1) // 2   # triangular: 0, 250, 750, 1500, 2500...


def level_for_xp(xp: int) -> int:
    """Given total XP, return the highest level reached. Soft cap at Lvl 50."""
    if xp <= 0:
        return 1
    # Solve 250·n(n-1)/2 ≤ xp  →  n ≤ (1 + sqrt(1 + 8·xp/250)) / 2
    n = int((1 + math.sqrt(1 + 8 * xp / 250)) / 2)
    return min(max(n, 1), 50)


def progress_to_next(xp: int) -> dict:
    """Returns {level, xp, xp_into_level, xp_for_next, pct}."""
    lvl = level_for_xp(xp)
    cur_base = xp_for_level(lvl)
    next_base = xp_for_level(lvl + 1)
    span = max(1, next_base - cur_base)
    into = xp - cur_base
    return {
        "level": lvl,
        "xp": xp,
        "xp_into_level": into,
        "xp_for_next_level": span,
        "pct_to_next": round(min(1.0, into / span), 3),
    }


# ── Rule matching ────────────────────────────────────────────────────────

def _matches(rule: dict, event: dict) -> bool:
    if rule.get("kind") and event.get("kind") != rule["kind"]:
        return False
    pred = rule.get("match")
    if callable(pred):
        try:
            return bool(pred(event.get("payload") or {}))
        except Exception:
            return False
    return True


def _xp_from_rule(rule: dict, event: dict) -> int:
    payload = event.get("payload") or {}
    base = rule["xp"]
    val = base(payload) if callable(base) else int(base)
    bonus = rule.get("bonus")
    if callable(bonus):
        try: val += int(bonus(payload) or 0)
        except Exception: pass
    return max(0, val)


def xp_for_event(event: dict) -> list[dict]:
    """Return the list of {xp, reason} rule hits for one event."""
    hits = []
    for r in RULES:
        if _matches(r, event):
            hits.append({"xp": _xp_from_rule(r, event), "reason": r.get("reason", r["kind"])})
    return hits


# ── Per-rep XP projection ────────────────────────────────────────────────
#
# We cache (bullpen → {rep → totals}) until `invalidate(bullpen)` is called.
# Recompute is cheap (a few thousand events scans in milliseconds).

_xp_cache: dict[str, dict] = {}


def invalidate(bullpen: str) -> None:
    _xp_cache.pop(bullpen, None)


def _compute(bullpen: str) -> dict[str, dict]:
    # Cache squad bonus per actor — squad membership doesn't change inside
    # a single projection pass, and looking it up per-event is a file read.
    try:
        from parties import squad_xp_bonus
    except Exception:
        def squad_xp_bonus(_b, _r): return 1.0
    bonus_cache: dict[str, float] = {}

    by_rep: dict[str, dict] = {}
    for event in audit_iter_all(bullpen):
        actor = event.get("actor") or "self"
        slot = by_rep.setdefault(actor, {"xp": 0, "ledger": []})
        if actor not in bonus_cache:
            try: bonus_cache[actor] = squad_xp_bonus(bullpen, actor)
            except Exception: bonus_cache[actor] = 1.0
        mult = bonus_cache[actor]
        for hit in xp_for_event(event):
            scored = int(round(hit["xp"] * mult))
            slot["xp"] += scored
            slot["ledger"].append({
                "ts": event.get("ts"),
                "kind": event.get("kind"),
                "target_id": event.get("target_id"),
                "xp": scored,
                "reason": hit["reason"] + (f" (squad ×{mult:.2f})" if mult > 1.0 else ""),
            })
    return by_rep


def get(bullpen: str, rep: Optional[str] = None) -> dict:
    """Return XP totals + level for one rep (or all reps if rep is None)."""
    if bullpen not in _xp_cache:
        _xp_cache[bullpen] = _compute(bullpen)
    by_rep = _xp_cache[bullpen]

    if rep is None:
        out = []
        for r, slot in by_rep.items():
            p = progress_to_next(slot["xp"])
            out.append({"rep": r, **p, "events": len(slot["ledger"])})
        out.sort(key=lambda x: -x["xp"])
        return {"reps": out}

    slot = by_rep.get(rep, {"xp": 0, "ledger": []})
    return {"rep": rep, **progress_to_next(slot["xp"]),
            "events": len(slot["ledger"]),
            "ledger": list(reversed(slot["ledger"]))[:50]}  # newest 50


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 server/xp.py <bullpen> [rep]")
        sys.exit(0)
    bullpen = sys.argv[1]
    rep = sys.argv[2] if len(sys.argv) > 2 else None
    r = get(bullpen, rep)
    if rep:
        print(f"  {r['rep']:12} Lvl {r['level']:3}  xp={r['xp']:>6}  ({r['xp_into_level']}/{r['xp_for_next_level']} to Lvl {r['level']+1})")
        for e in r["ledger"][:10]:
            print(f"    +{e['xp']:>4} XP  {e['kind']:20}  {e['reason']}")
    else:
        for x in r["reps"]:
            print(f"  {x['rep']:12} Lvl {x['level']:3}  xp={x['xp']:>6}  events={x['events']}")
