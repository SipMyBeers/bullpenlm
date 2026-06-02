"""Leaderboard — multi-axis stats per closer.

Reads the bullpen's audit log and tallies discipline-specific stats so
the BRIDGE can surface "top performer per lane" instead of one giant
revenue ranking that punishes everyone doing the unsexy work.

Lanes:
  🎯 cold_open   — connect-rate proxy: deal_stage_moved 'contacted' OR
                     dial events with connect=true
  🗡 discovery   — qualified-rate: deal_stage_moved 'qualified'
  💰 closer      — close-won count + revenue
  🪤 hunter      — net-new prospects added (buyer-card creates this user
                     authored, plus deal_created with new prospect_slug)
  📣 marketer    — marketing.post_published + tracked_link events
  🧠 researcher  — studio source ingests + dossier_enriched events
  🏆 overall     — total XP (money + clout)

Returns a dict keyed by lane, with per-rep counts + totals. Designed to
be read-time; reads through the same audit_iter_all the XP engine uses,
so there's no separate store to keep in sync.
"""
from __future__ import annotations

from typing import Dict, Any
from collections import defaultdict


def _empty_stats() -> dict:
    return {
        "cold_open": 0,
        "discovery": 0,
        "closer_wins": 0,
        "closer_revenue": 0.0,
        "hunter": 0,
        "marketer": 0,
        "researcher": 0,
        "total_xp": 0,
    }


def compute(bullpen: str) -> Dict[str, Any]:
    """Return per-lane leaderboard for a bullpen."""
    try:
        from audit import iter_all as audit_iter_all
    except Exception:
        return {"reps": [], "lanes": {}}

    per_rep: Dict[str, dict] = defaultdict(_empty_stats)
    seen_prospects_per_rep: Dict[str, set] = defaultdict(set)

    for ev in audit_iter_all(bullpen):
        rep = ev.get("actor") or "self"
        stats = per_rep[rep]
        kind = ev.get("kind") or ""
        payload = ev.get("payload") or {}

        if kind == "deal_stage_moved":
            to_stage = payload.get("to")
            if to_stage == "contacted":
                stats["cold_open"] += 1
            elif to_stage == "qualified":
                stats["discovery"] += 1

        elif kind == "deal_closed_won":
            stats["closer_wins"] += 1
            try: stats["closer_revenue"] += float(payload.get("amount") or 0)
            except Exception: pass

        elif kind == "deal_created":
            # Hunter credit only if this rep hadn't claimed this prospect
            # in this bullpen before (don't pay twice for the same target)
            prospect = payload.get("prospect_slug") or payload.get("prospect")
            if prospect and prospect not in seen_prospects_per_rep[rep]:
                seen_prospects_per_rep[rep].add(prospect)
                stats["hunter"] += 1

        elif kind in ("buyer_card_created", "prospect_seeded"):
            stats["hunter"] += 1

        elif kind in ("marketing_post_published", "tracked_link_minted",
                       "outbound_email_sent"):
            stats["marketer"] += 1

        elif kind in ("rag_source_ingested", "dossier_enriched",
                       "studio_asset_generated"):
            stats["researcher"] += 1

    # XP roll-up (read from xp module so the curve stays canonical)
    try:
        import xp as _xp
        for rep in list(per_rep.keys()):
            try:
                per_rep[rep]["total_xp"] = (_xp.get_money_xp(bullpen, rep)
                                              + _xp.get_clout_xp(bullpen, rep))
            except Exception:
                pass
    except Exception:
        pass

    # Build per-lane ranked lists
    reps = sorted(per_rep.keys())
    def _ranked(lane_key: str):
        return sorted(
            [{"rep": r, "score": per_rep[r][lane_key]} for r in reps
              if per_rep[r][lane_key] > 0],
            key=lambda x: -x["score"],
        )

    return {
        "reps": [{"rep": r, **per_rep[r]} for r in reps],
        "lanes": {
            "cold_open":  _ranked("cold_open"),
            "discovery":  _ranked("discovery"),
            "closer":     sorted(
                [{"rep": r, "wins": per_rep[r]["closer_wins"],
                  "revenue": per_rep[r]["closer_revenue"]}
                 for r in reps if per_rep[r]["closer_wins"] > 0],
                key=lambda x: -x["revenue"]),
            "hunter":     _ranked("hunter"),
            "marketer":   _ranked("marketer"),
            "researcher": _ranked("researcher"),
            "overall":    _ranked("total_xp"),
        },
    }
