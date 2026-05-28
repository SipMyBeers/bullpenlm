"""Streaks — consecutive days with at least one XP-earning event.

Pure projection from the audit log; no separate write path. Multiplier
returned by `multiplier(bullpen, rep)` is applied by xp.py when an event
fires. Freeze tokens: one per rep per month, consumed automatically when
a streak would otherwise break (i.e. the rep missed exactly one day).

Storage layout:
  bullpens/<slug>/streaks/<rep>.json    — { freeze_tokens_used: {"2026-05": ["2026-05-12"]} }
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

from audit import iter_all as audit_iter_all

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"

# Event kinds that count as "the rep showed up today"
ACTIVE_KINDS = {
    "call", "claim", "deal_created", "deal_stage_moved", "deal_closed_won",
    "doc_signed", "quest_completed", "drill_passed", "drill_attempt",
    "debrief_extracted", "mentor_flag",
}

# Streak tier multipliers
TIERS = [
    {"min": 100, "mult": 1.20, "label": "+20% XP"},
    {"min":  30, "mult": 1.10, "label": "+10% XP"},
    {"min":   7, "mult": 1.05, "label": "+5% XP"},
    {"min":   0, "mult": 1.00, "label": ""},
]


def _streak_path(bullpen: str, rep: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "streaks"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{rep}.json"


def _read_freeze_state(bullpen: str, rep: str) -> dict:
    p = _streak_path(bullpen, rep)
    if not p.exists():
        return {"freeze_tokens_used": {}}
    try: return json.loads(p.read_text())
    except Exception: return {"freeze_tokens_used": {}}


def _write_freeze_state(bullpen: str, rep: str, state: dict) -> None:
    _streak_path(bullpen, rep).write_text(json.dumps(state, indent=2) + "\n")


def _active_days(bullpen: str, rep: str) -> set[str]:
    """Return the set of YYYY-MM-DD dates on which `rep` had ≥1 active event."""
    days = set()
    for e in audit_iter_all(bullpen):
        if e.get("actor") != rep:
            continue
        if e.get("kind") not in ACTIVE_KINDS:
            continue
        ts = e.get("ts") or ""
        if ts:
            days.add(ts[:10])
    return days


def compute(bullpen: str, rep: str) -> dict:
    """Walk backward from today, counting consecutive active days.
    Allow up to one freeze-token consumption per calendar month."""
    days = _active_days(bullpen, rep)
    if not days:
        return {"streak": 0, "tier": TIERS[-1], "freeze_tokens_remaining_this_month": 1,
                "freeze_used_dates": []}

    state = _read_freeze_state(bullpen, rep)
    used = dict(state.get("freeze_tokens_used") or {})

    today = datetime.date.today()
    cur = today
    streak = 0
    pending_freeze: list[tuple[str, str]] = []   # (month_key, date_key)
    streak_at_pending: list[int] = []            # streak count when each freeze was tentatively spent

    while True:
        key = cur.isoformat()
        if key in days:
            streak += 1
            cur -= datetime.timedelta(days=1)
            continue
        month_key = key[:7]
        used_this_month = (used.get(month_key) or []) + [d for (m, d) in pending_freeze if m == month_key]
        if key not in used_this_month and len(used_this_month) < 1 and cur != today:
            pending_freeze.append((month_key, key))
            streak_at_pending.append(streak)
            cur -= datetime.timedelta(days=1)
            continue
        break

    # Commit only the freeze spends that produced *more* active days past them.
    # A spend at streak=N is effective if final streak > N.
    effective = [(m, d) for (m, d), s_when in zip(pending_freeze, streak_at_pending) if streak > s_when]
    if effective:
        for m, d in effective:
            used.setdefault(m, [])
            if d not in used[m]:
                used[m].append(d)
        state["freeze_tokens_used"] = used
        _write_freeze_state(bullpen, rep, state)

    tier = next(t for t in TIERS if streak >= t["min"])
    cur_month = today.isoformat()[:7]
    tokens_used_this_month = len(used.get(cur_month) or [])
    return {
        "streak": streak,
        "tier": tier,
        "freeze_tokens_remaining_this_month": max(0, 1 - tokens_used_this_month),
        "freeze_used_dates": list((used.get(cur_month) or [])),
    }


def multiplier(bullpen: str, rep: str) -> float:
    return compute(bullpen, rep)["tier"]["mult"]


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 server/streaks.py <bullpen> <rep>")
        sys.exit(0)
    s = compute(sys.argv[1], sys.argv[2])
    print(f"  {sys.argv[2]} streak: {s['streak']} days  ({s['tier']['label'] or '—'})")
    print(f"  Freeze tokens left this month: {s['freeze_tokens_remaining_this_month']}")
