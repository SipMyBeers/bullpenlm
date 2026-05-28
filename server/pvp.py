"""PvP — short-window sprints + opt-in 1v1 head-to-head matches.

A sprint is an open competition over a fixed window (1 hour, 1 day, or
1 week). All bullpen members are automatically entered. The leaderboard
ranks by `score_kind` (dials / demos / closes / xp). The winner gets
a transient achievement and the right to name the next daily quest.

A duel is an opt-in 1v1 — two reps with a 7-day window competing on
the same metric. The challenger creates it; the opponent must accept
within 24h or it expires.

Storage layout:
  bullpens/<slug>/pvp/sprints/<id>.json
  bullpens/<slug>/pvp/duels/<id>.json
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

from audit import append as audit_append
from audit import iter_all as audit_iter_all

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


SCORE_KINDS = {
    "dials":  {"label": "Most real calls",  "kind": "call",             "match": {"call_kind": "real"}},
    "demos":  {"label": "Most demos booked", "kind": "deal_stage_moved", "match": {"to": "demo"}},
    "closes": {"label": "Most closed-won",  "kind": "deal_closed_won",  "match": {}},
    "revenue":{"label": "Highest gross",    "kind": "deal_closed_won",  "match": {}, "sum_field": "amount"},
    "xp":     {"label": "Most XP earned",   "kind": "*",                "match": {}, "xp_mode": True},
}


def _sprint_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "pvp" / "sprints"
    d.mkdir(parents=True, exist_ok=True); return d


def _duel_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "pvp" / "duels"
    d.mkdir(parents=True, exist_ok=True); return d


def _matches(event: dict, kind_spec: dict) -> bool:
    if kind_spec.get("kind") != "*" and event.get("kind") != kind_spec.get("kind"):
        return False
    match = kind_spec.get("match") or {}
    payload = event.get("payload") or {}
    return all(payload.get(k) == v for k, v in match.items())


def _score_one_rep(bullpen: str, rep: str, kind_spec: dict,
                   start_ts: str, end_ts: str) -> float:
    total = 0.0
    sum_field = kind_spec.get("sum_field")
    xp_mode = kind_spec.get("xp_mode")
    for e in audit_iter_all(bullpen):
        if e.get("actor") != rep:
            continue
        ts = e.get("ts") or ""
        if not (start_ts <= ts <= end_ts):
            continue
        if xp_mode:
            try:
                from xp import xp_for_event
                for hit in xp_for_event(e):
                    total += hit.get("xp", 0)
            except Exception: pass
            continue
        if not _matches(e, kind_spec):
            continue
        if sum_field:
            total += float((e.get("payload") or {}).get(sum_field) or 0)
        else:
            total += 1
    return total


# ── Sprints ──────────────────────────────────────────────────────────────

def create_sprint(bullpen: str, authored_by: str, score_kind: str,
                  duration_hours: int = 1, name: Optional[str] = None) -> dict:
    if score_kind not in SCORE_KINDS:
        raise ValueError("unknown_score_kind")
    now = datetime.datetime.now()
    sprint_id = f"sprint-{now.strftime('%Y%m%d-%H%M%S')}-{score_kind}"
    end = now + datetime.timedelta(hours=duration_hours)
    sprint = {
        "id": sprint_id,
        "type": "sprint",
        "name": name or f"{score_kind.title()} sprint · {duration_hours}h",
        "authored_by": authored_by,
        "score_kind": score_kind,
        "score_label": SCORE_KINDS[score_kind]["label"],
        "starts_at": now.isoformat(timespec="seconds"),
        "expires_at": end.isoformat(timespec="seconds"),
        "duration_hours": duration_hours,
    }
    (_sprint_dir(bullpen) / f"{sprint_id}.json").write_text(json.dumps(sprint, indent=2) + "\n")
    audit_append(bullpen, authored_by, "sprint_started",
                 target_type="sprint", target_id=sprint_id,
                 payload={"name": sprint["name"], "score_kind": score_kind,
                          "duration_hours": duration_hours})
    return sprint


def _participating_reps(bullpen: str) -> list[str]:
    d = BULLPENS_ROOT / bullpen / "members"
    if not d.exists(): return []
    return sorted(f.stem for f in d.glob("*.json"))


def sprint_leaderboard(bullpen: str, sprint_id: str) -> dict:
    p = _sprint_dir(bullpen) / f"{sprint_id}.json"
    if not p.exists():
        return {"error": "sprint_not_found"}
    sprint = json.loads(p.read_text())
    spec = SCORE_KINDS[sprint["score_kind"]]
    reps = _participating_reps(bullpen)
    rows = []
    for rep in reps:
        score = _score_one_rep(bullpen, rep, spec,
                               sprint["starts_at"], sprint["expires_at"])
        rows.append({"rep": rep, "score": score})
    rows.sort(key=lambda r: -r["score"])
    return {"sprint": sprint, "leaderboard": rows,
            "now": datetime.datetime.now().isoformat(timespec="seconds")}


def list_sprints(bullpen: str, include_expired: bool = False) -> list[dict]:
    out = []
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for f in sorted(_sprint_dir(bullpen).glob("*.json"), reverse=True):
        try: sp = json.loads(f.read_text())
        except Exception: continue
        if not include_expired and sp.get("expires_at", "") < now:
            continue
        out.append(sp)
    return out


# ── Duels ────────────────────────────────────────────────────────────────

def create_duel(bullpen: str, challenger: str, opponent: str,
                score_kind: str, duration_days: int = 7) -> dict:
    if score_kind not in SCORE_KINDS:
        raise ValueError("unknown_score_kind")
    if challenger == opponent:
        raise ValueError("self_duel_not_allowed")
    now = datetime.datetime.now()
    duel_id = f"duel-{now.strftime('%Y%m%d-%H%M%S')}-{challenger}-vs-{opponent}"
    duel = {
        "id": duel_id,
        "type": "duel",
        "challenger": challenger,
        "opponent": opponent,
        "score_kind": score_kind,
        "score_label": SCORE_KINDS[score_kind]["label"],
        "status": "pending",   # pending → active → resolved | declined | expired
        "created_at": now.isoformat(timespec="seconds"),
        "accept_by": (now + datetime.timedelta(hours=24)).isoformat(timespec="seconds"),
        "starts_at": None,
        "expires_at": None,
        "duration_days": duration_days,
        "winner": None,
    }
    (_duel_dir(bullpen) / f"{duel_id}.json").write_text(json.dumps(duel, indent=2) + "\n")
    audit_append(bullpen, challenger, "duel_challenged",
                 target_type="duel", target_id=duel_id,
                 payload={"opponent": opponent, "score_kind": score_kind})
    return duel


def accept_duel(bullpen: str, duel_id: str, accepting_rep: str) -> dict:
    p = _duel_dir(bullpen) / f"{duel_id}.json"
    if not p.exists():
        raise ValueError("duel_not_found")
    duel = json.loads(p.read_text())
    if duel.get("status") != "pending":
        raise ValueError(f"duel_status_{duel['status']}")
    if accepting_rep != duel["opponent"]:
        raise ValueError("not_your_duel")
    now = datetime.datetime.now()
    duel["status"] = "active"
    duel["starts_at"] = now.isoformat(timespec="seconds")
    duel["expires_at"] = (now + datetime.timedelta(days=int(duel["duration_days"]))).isoformat(timespec="seconds")
    p.write_text(json.dumps(duel, indent=2) + "\n")
    audit_append(bullpen, accepting_rep, "duel_accepted",
                 target_type="duel", target_id=duel_id,
                 payload={"challenger": duel["challenger"]})
    return duel


def duel_scores(bullpen: str, duel_id: str) -> dict:
    p = _duel_dir(bullpen) / f"{duel_id}.json"
    if not p.exists():
        return {"error": "duel_not_found"}
    duel = json.loads(p.read_text())
    if duel["status"] not in ("active", "resolved"):
        return {"duel": duel, "scores": None}
    spec = SCORE_KINDS[duel["score_kind"]]
    return {
        "duel": duel,
        "scores": {
            duel["challenger"]: _score_one_rep(bullpen, duel["challenger"], spec, duel["starts_at"], duel["expires_at"]),
            duel["opponent"]:   _score_one_rep(bullpen, duel["opponent"],   spec, duel["starts_at"], duel["expires_at"]),
        },
    }


def list_duels(bullpen: str, rep: Optional[str] = None) -> list[dict]:
    out = []
    for f in sorted(_duel_dir(bullpen).glob("*.json"), reverse=True):
        try: d = json.loads(f.read_text())
        except Exception: continue
        if rep and rep not in (d.get("challenger"), d.get("opponent")):
            continue
        out.append(d)
    return out


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 server/pvp.py <bullpen> sprints|duels [<rep>]")
        sys.exit(0)
    bullpen, sub = sys.argv[1], sys.argv[2]
    if sub == "sprints":
        for s in list_sprints(bullpen, include_expired=True):
            print(f"  {s['id']:55} {s['name']} (expires {s['expires_at']})")
    elif sub == "duels":
        rep = sys.argv[3] if len(sys.argv) > 3 else None
        for d in list_duels(bullpen, rep):
            print(f"  {d['id']:55} [{d['status']:8}] {d['challenger']} vs {d['opponent']}")
