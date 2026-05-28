"""Today — the single composer for "what's actionable for me right now".

Pulled from primitives that already exist:
  • open follow-ups due (overdue first; followups.py)
  • claims I currently hold (team.py)
  • my open deals stalled in early stages for >7d (deals.py)
  • pending duels addressed to me (duos.py)
  • raids I joined that I haven't claimed yet (parties.py)
  • squad I'm in (parties.py — informational)
  • recent close-wons across the bullpen (audit log)

This module composes, doesn't store.
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"

STALL_THRESHOLD_DAYS = 7
EARLY_STAGES = {"lead", "contacted", "qualified"}


def _today_end_iso() -> str:
    eod = datetime.datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    return eod.isoformat(timespec="seconds")


def for_rep(bullpen: str, rep: str) -> dict:
    out = {
        "rep": rep,
        "bullpen": bullpen,
        "as_of": datetime.datetime.now().isoformat(timespec="seconds"),
        "followups_due": [],
        "followups_overdue": [],
        "open_claims": [],
        "stalling_deals": [],
        "pending_duels": [],
        "open_raids": [],
        "squad": None,
        "recent_closes": [],
        "open_spotchecks": [],
        "top_pack_pct": None,
    }

    # ── Follow-ups ──
    try:
        from followups import list_for_rep as fu_list
        open_fus = fu_list(bullpen, rep, status="open")
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        eod = _today_end_iso()
        for fu in open_fus:
            d = fu.get("due_at") or ""
            if d < now_iso:
                out["followups_overdue"].append(fu)
            elif d <= eod:
                out["followups_due"].append(fu)
    except Exception: pass

    # ── Open claims ──
    try:
        from team import get_roster
        roster = get_roster()
        # roster format: list of {rep, ..., claims:[...]} OR per-rep dicts
        for r in roster:
            if (r.get("rep") or r.get("name")) == rep:
                out["open_claims"] = r.get("claims") or []
                break
    except Exception:
        # Fallback: scan claims directory directly
        try:
            cdir = BULLPENS_ROOT / bullpen / "claims"
            if cdir.exists():
                for f in cdir.glob("*.json"):
                    try: c = json.loads(f.read_text())
                    except Exception: continue
                    if c.get("rep") == rep:
                        out["open_claims"].append(c)
        except Exception: pass

    # ── Stalling deals ──
    try:
        from deals import list_all as deals_list
        cutoff = (datetime.datetime.now() -
                  datetime.timedelta(days=STALL_THRESHOLD_DAYS)).isoformat(timespec="seconds")
        my_deals = deals_list(bullpen, owner_rep=rep, include_terminal=False)
        for d in my_deals:
            if d.get("stage") not in EARLY_STAGES:
                continue
            # Last touch = last stage_history entry OR opened_at
            history = d.get("stage_history") or []
            last_touch = (history[-1].get("at") if history else d.get("opened_at")) or ""
            if last_touch < cutoff:
                out["stalling_deals"].append({
                    "id": d["id"],
                    "prospect": d.get("prospect_slug"),
                    "stage": d.get("stage"),
                    "amount": d.get("amount", 0),
                    "last_touch": last_touch,
                    "days_stalled": (datetime.datetime.now() -
                                     datetime.datetime.fromisoformat(last_touch)).days
                                    if last_touch else None,
                })
    except Exception: pass

    # ── Pending duels addressed to me ──
    try:
        from duos import list_for_rep as duos_list
        my = duos_list(bullpen, rep, status="pending")
        for d in my:
            if d.get("opponent") == rep:
                out["pending_duels"].append({
                    "id": d["id"], "challenger": d.get("challenger"),
                    "prospect": d.get("prospect_slug"),
                    "duration_minutes": d.get("duration_minutes"),
                })
    except Exception: pass

    # ── Open raids I joined but haven't claimed ──
    try:
        from parties import raid_party_progress
        rd = BULLPENS_ROOT / bullpen / "quests" / "raids"
        if rd.exists():
            for f in rd.glob("*.json"):
                try: raid = json.loads(f.read_text())
                except Exception: continue
                prog = raid_party_progress(bullpen, raid["id"], raid)
                if rep not in (prog.get("members") or []):
                    continue
                if rep in (prog.get("completed_members") or []):
                    continue
                out["open_raids"].append({
                    "id": raid["id"], "name": raid.get("name"),
                    "pct": prog.get("pct"), "count": prog.get("count"),
                    "target": prog.get("target"),
                    "claimable": bool(prog.get("completed")),
                    "xp_share": prog.get("xp_per_member"),
                })
    except Exception: pass

    # ── Squad ──
    try:
        from parties import squad_for_rep
        out["squad"] = squad_for_rep(bullpen, rep)
    except Exception: pass

    # ── Open spot-checks waiting on me ──
    try:
        from spotcheck import list_open_for_target
        scs = list_open_for_target(bullpen, rep)
        for sc in scs:
            out["open_spotchecks"].append({
                "id": sc["id"], "tcs_name": sc.get("tcs_name"),
                "phase_tier": sc.get("phase_tier"),
                "checker": sc.get("checker"),
                "fired_at": sc.get("fired_at"),
                "seconds": sc.get("seconds"),
            })
    except Exception: pass

    # ── Top Pack snapshot ──
    try:
        from tcs import top_pack
        tp = top_pack(bullpen, rep)
        out["top_pack_pct"] = tp.get("pct_cleared")
        out["top_pack_cleared"] = tp.get("cleared_count")
        out["top_pack_total"]   = tp.get("total")
    except Exception: pass

    # ── Recent close-wons across the bullpen ──
    try:
        from audit import tail
        for e in tail(bullpen, n=200):
            if e.get("kind") == "deal_closed_won":
                out["recent_closes"].append({
                    "ts": e.get("ts"), "actor": e.get("actor"),
                    "deal_id": e.get("target_id"),
                    "amount": (e.get("payload") or {}).get("amount"),
                    "prospect": (e.get("payload") or {}).get("prospect"),
                })
                if len(out["recent_closes"]) >= 8:
                    break
    except Exception: pass

    return out
