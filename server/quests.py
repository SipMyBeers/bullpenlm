"""Quests — daily, weekly, and raid objectives that give reps bite-sized
targets between long sales cycles.

Storage layout (per bullpen):
  bullpens/<slug>/quests/active.json        — current daily + weekly set
  bullpens/<slug>/quests/raids/<id>.json    — founder-authored raid quests
  bullpens/<slug>/quests/progress/<rep>/<quest_id>.json  — per-rep progress

Quest predicate DSL — a small, safe allow-list of audit-log filters:
  {
    "kind": "call",                    # required: audit event kind
    "match": {"call_kind": "real"},    # optional: payload key/value match
    "count": 10                        # required: number of matching events
  }

A quest is "completed" when the rep has `count` audit events matching the
predicate (counted since `quest.starts_at`).
"""
from __future__ import annotations
import datetime
import json
import random
from pathlib import Path
from typing import Optional

from audit import iter_all as audit_iter_all
from audit import append as audit_append

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


# ── Daily quest templates ──
DAILY_TEMPLATES = [
    {"id_prefix": "10dials",   "name": "10 dials today",
     "predicate": {"kind": "call", "match": {"call_kind": "real"}, "count": 10},
     "xp_reward": 100},
    {"id_prefix": "3drills",   "name": "Pass 3 drills",
     "predicate": {"kind": "drill_passed", "count": 3},
     "xp_reward": 75},
    {"id_prefix": "1stage",    "name": "Advance 1 deal",
     "predicate": {"kind": "deal_stage_moved", "count": 1},
     "xp_reward": 50},
    {"id_prefix": "1claim",    "name": "Claim a fresh prospect",
     "predicate": {"kind": "claim", "count": 1},
     "xp_reward": 30},
    {"id_prefix": "1extract",  "name": "Extract a new contact from a call",
     "predicate": {"kind": "debrief_extracted", "count": 1},
     "xp_reward": 60},
    {"id_prefix": "5drills",   "name": "5 practice drills",
     "predicate": {"kind": "call", "match": {"call_kind": "practice"}, "count": 5},
     "xp_reward": 80},
]

# ── Weekly quest templates (higher bar, bigger XP) ──
WEEKLY_TEMPLATES = [
    {"id_prefix": "w-50dials",  "name": "50 real calls this week",
     "predicate": {"kind": "call", "match": {"call_kind": "real"}, "count": 50},
     "xp_reward": 500},
    {"id_prefix": "w-5deals",   "name": "Create 5 new deals",
     "predicate": {"kind": "deal_created", "count": 5},
     "xp_reward": 400},
    {"id_prefix": "w-3closes",  "name": "Close 3 deals",
     "predicate": {"kind": "deal_closed_won", "count": 3},
     "xp_reward": 1000},
    {"id_prefix": "w-allgauntlet", "name": "Pass all 7 Gauntlet phases this week",
     "predicate": {"kind": "drill_passed", "count": 7, "distinct_phase": True},
     "xp_reward": 800},
]


def _quests_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "quests"
    d.mkdir(parents=True, exist_ok=True)
    (d / "progress").mkdir(exist_ok=True)
    (d / "raids").mkdir(exist_ok=True)
    return d


def _active_path(bullpen: str) -> Path:
    return _quests_dir(bullpen) / "active.json"


def _today_key() -> str:
    return datetime.date.today().isoformat()


def _week_key() -> str:
    """ISO week key, e.g. 2026-W21."""
    d = datetime.date.today()
    return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"


def ensure_active(bullpen: str) -> dict:
    """Make sure today's daily + this week's weekly quests exist. If they
    don't, generate them. Returns the active manifest."""
    p = _active_path(bullpen)
    if p.exists():
        try:
            active = json.loads(p.read_text())
        except Exception:
            active = {}
    else:
        active = {}

    today = _today_key()
    week = _week_key()
    changed = False

    # Daily — pick 3 random templates per day
    if active.get("daily_date") != today:
        chosen = random.sample(DAILY_TEMPLATES, k=min(3, len(DAILY_TEMPLATES)))
        active["daily_date"] = today
        active["daily"] = [
            {**t, "id": f"daily-{today}-{t['id_prefix']}",
             "starts_at": today + "T00:00:00",
             "expires_at": today + "T23:59:59",
             "scope": "daily"}
            for t in chosen
        ]
        changed = True

    # Weekly — pick 2 random templates per week
    if active.get("weekly_id") != week:
        chosen = random.sample(WEEKLY_TEMPLATES, k=min(2, len(WEEKLY_TEMPLATES)))
        active["weekly_id"] = week
        # Week starts Monday, expires Sunday
        d = datetime.date.today()
        monday = d - datetime.timedelta(days=d.weekday())
        sunday = monday + datetime.timedelta(days=6)
        active["weekly"] = [
            {**t, "id": f"weekly-{week}-{t['id_prefix']}",
             "starts_at": monday.isoformat() + "T00:00:00",
             "expires_at": sunday.isoformat() + "T23:59:59",
             "scope": "weekly"}
            for t in chosen
        ]
        changed = True

    if changed:
        p.write_text(json.dumps(active, indent=2) + "\n")
    return active


def _raids(bullpen: str) -> list[dict]:
    d = _quests_dir(bullpen) / "raids"
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            r = json.loads(f.read_text())
        except Exception:
            continue
        # Filter to active raids only
        if r.get("expires_at"):
            try:
                exp = datetime.datetime.fromisoformat(r["expires_at"])
                if exp < datetime.datetime.now():
                    continue
            except Exception:
                pass
        out.append(r)
    return out


def list_active(bullpen: str) -> dict:
    """Return all currently-active quests (daily + weekly + raids)."""
    a = ensure_active(bullpen)
    return {
        "daily": a.get("daily", []),
        "weekly": a.get("weekly", []),
        "raids": _raids(bullpen),
    }


def progress(bullpen: str, rep: str) -> dict:
    """Compute progress for each active quest for one rep."""
    active = list_active(bullpen)
    events = list(audit_iter_all(bullpen))

    def _matches(event: dict, pred: dict, started_after: Optional[str]) -> bool:
        if event.get("actor") != rep:
            return False
        if event.get("kind") != pred.get("kind"):
            return False
        if started_after and event.get("ts", "") < started_after:
            return False
        match = pred.get("match") or {}
        payload = event.get("payload") or {}
        return all(payload.get(k) == v for k, v in match.items())

    claimed_path = _quests_dir(bullpen) / "progress" / rep
    def _quest_progress(quest: dict) -> dict:
        pred = quest.get("predicate") or {}
        target = int(pred.get("count") or 1)
        matching = [e for e in events
                    if _matches(e, pred, quest.get("starts_at"))]
        if pred.get("distinct_phase"):
            phases = {(e.get("payload") or {}).get("phase") for e in matching}
            current = len(phases - {None})
        else:
            current = len(matching)
        completed = current >= target
        # Has this quest already been claimed? Marker is written by
        # claim_rewards() below — we surface the flag so the UI can
        # show "✓ done" vs "✓ READY · CLAIM" distinctly.
        claimed = (claimed_path / f"{quest['id']}.json").exists() if claimed_path.exists() else False
        return {
            "id": quest["id"],
            "name": quest["name"],
            "scope": quest.get("scope"),
            "current": current,
            "target": target,
            "pct": min(1.0, round(current / max(1, target), 3)),
            "completed": completed,
            "claimed": claimed,
            "xp_reward": quest.get("xp_reward", 0),
            "expires_at": quest.get("expires_at"),
        }

    out = {"daily": [], "weekly": [], "raids": []}
    for q in active["daily"]:  out["daily"].append(_quest_progress(q))
    for q in active["weekly"]: out["weekly"].append(_quest_progress(q))
    for q in active["raids"]:  out["raids"].append(_quest_progress(q))
    return out


def claim_rewards(bullpen: str, rep: str) -> list[dict]:
    """Walk progress + emit a quest_completed audit event for any newly
    completed quest the rep hasn't yet claimed. Returns the list claimed."""
    prog = progress(bullpen, rep)
    claimed_path = _quests_dir(bullpen) / "progress" / rep
    claimed_path.mkdir(parents=True, exist_ok=True)

    claimed = []
    for scope in ("daily", "weekly", "raids"):
        for q in prog[scope]:
            if not q["completed"]:
                continue
            marker = claimed_path / f"{q['id']}.json"
            if marker.exists():
                continue
            marker.write_text(json.dumps({"completed_at": datetime.datetime.now().isoformat(timespec="seconds")}) + "\n")
            audit_append(bullpen, rep, "quest_completed",
                         target_type="quest", target_id=q["id"],
                         payload={"quest_name": q["name"], "scope": scope,
                                  "xp_reward": q["xp_reward"]})
            claimed.append(q)
    return claimed


def create_raid(bullpen: str, authored_by: str, name: str,
                predicate: dict, xp_reward: int = 200,
                expires_in_days: int = 7,
                party_size: int = 2) -> dict:
    """Founder/Strategist authors a raid quest."""
    raid_id = f"raid-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    now = datetime.datetime.now()
    raid = {
        "id": raid_id,
        "name": name,
        "scope": "raid",
        "authored_by": authored_by,
        "starts_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + datetime.timedelta(days=expires_in_days)).isoformat(timespec="seconds"),
        "predicate": predicate,
        "xp_reward": xp_reward,
        "party_size": party_size,
    }
    (_quests_dir(bullpen) / "raids" / f"{raid_id}.json").write_text(
        json.dumps(raid, indent=2) + "\n")
    audit_append(bullpen, authored_by, "raid_authored",
                 target_type="raid", target_id=raid_id,
                 payload={"name": name, "predicate": predicate})
    return raid
