"""Wallboard — TV-mode data for Discord screenshare.

Aggregates today's per-rep counts (dials / demos / closes / XP earned),
plus today's bullpen totals, plus the active sprint (if any). All from
the existing audit log — pure projection.
"""
from __future__ import annotations
import datetime
from collections import defaultdict
from pathlib import Path

from audit import iter_all

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


def _today_iso_bounds() -> tuple[str, str]:
    """[start, end_exclusive) for today in local time."""
    d = datetime.date.today()
    start = datetime.datetime.combine(d, datetime.time.min).isoformat(timespec="seconds")
    end   = datetime.datetime.combine(d + datetime.timedelta(days=1), datetime.time.min).isoformat(timespec="seconds")
    return start, end


def today_stats(bullpen: str) -> dict:
    start, end = _today_iso_bounds()

    per_rep: dict = defaultdict(lambda: {
        "rep": "", "dials": 0, "demos": 0, "closes": 0,
        "revenue": 0.0, "xp_today": 0, "drills": 0, "followups_done": 0,
    })

    totals = {"dials": 0, "demos": 0, "closes": 0, "revenue": 0.0,
              "xp_today": 0, "followups_done": 0}

    # Lazily import xp.xp_for_event so the same rule table drives today's XP
    try:
        from xp import xp_for_event
    except Exception:
        xp_for_event = lambda _e: []

    for e in iter_all(bullpen):
        ts = e.get("ts") or ""
        if ts < start or ts >= end:
            continue
        rep = e.get("actor") or ""
        if not rep: continue
        slot = per_rep[rep]
        slot["rep"] = rep
        kind = e.get("kind"); p = e.get("payload") or {}

        if kind == "call" and p.get("call_kind") == "real":
            slot["dials"] += 1; totals["dials"] += 1
        if kind == "deal_stage_moved" and p.get("to") == "demo":
            slot["demos"] += 1; totals["demos"] += 1
        if kind == "deal_closed_won":
            slot["closes"] += 1; totals["closes"] += 1
            slot["revenue"] += float(p.get("amount") or 0)
            totals["revenue"] += float(p.get("amount") or 0)
        if kind == "drill_passed":
            slot["drills"] += 1
        if kind == "followup_done":
            slot["followups_done"] += 1; totals["followups_done"] += 1

        for hit in xp_for_event(e):
            slot["xp_today"] += hit["xp"]
            totals["xp_today"] += hit["xp"]

    rows = sorted(per_rep.values(), key=lambda r: (-r["xp_today"], -r["closes"]))

    # Active sprints (top 1)
    sprint = None
    try:
        from pvp import list_sprints, sprint_leaderboard
        live = list_sprints(bullpen, include_expired=False)
        if live:
            sprint = sprint_leaderboard(bullpen, live[0]["id"])
    except Exception: pass

    # Online roster
    online = []
    try:
        from presence import roster
        online = roster(bullpen)
    except Exception: pass

    # Recent close-wons (for the bell + ticker tail)
    recent_closes = []
    try:
        from audit import tail
        for e in tail(bullpen, n=120):
            if e.get("kind") == "deal_closed_won":
                p = e.get("payload") or {}
                recent_closes.append({
                    "ts": e.get("ts"), "rep": e.get("actor"),
                    "amount": p.get("amount"),
                    "prospect": p.get("prospect") or e.get("target_id"),
                })
                if len(recent_closes) >= 8: break
    except Exception: pass

    return {
        "bullpen": bullpen,
        "as_of": datetime.datetime.now().isoformat(timespec="seconds"),
        "day_start": start,
        "totals_today": totals,
        "per_rep": rows,
        "active_sprint": sprint,
        "online": online,
        "recent_closes": recent_closes,
    }
