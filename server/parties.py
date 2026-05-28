"""Parties — squads + party-raid mechanics.

Two distinct concepts:

  Squad — a permanent named group of reps inside a bullpen. Squads can
          be 2-5 reps. Each member of a squad with N members gets a
          small XP multiplier (5% per teammate, capped at +20%) on
          *every* event for the duration of squad membership.

  Raid party — short-lived. Multiple reps join a raid quest. Their
          progress is summed against the raid's target. When the raid
          completes, every member of the party gets `xp_reward / N` XP
          via a quest_completed event, where N is the party size.

Storage:
  bullpens/<slug>/parties/squads/<id>.json
  bullpens/<slug>/parties/raid_parties/<raid_id>.json
"""
from __future__ import annotations
import datetime
import json
import re
from pathlib import Path
from typing import Optional

from audit import append as audit_append
from audit import iter_all as audit_iter_all

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"

SQUAD_COLORS = ["#34d399", "#fbbf24", "#a78bfa", "#f87171", "#22d3ee", "#fb923c"]


def _squads_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "parties" / "squads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _raid_parties_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "parties" / "raid_parties"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9\-]", "-", name.lower().strip())[:32].strip("-") or "squad"


# ── Squads ───────────────────────────────────────────────────────────────

def create_squad(bullpen: str, name: str, founder: str,
                 members: Optional[list[str]] = None,
                 color: Optional[str] = None) -> dict:
    if not name.strip():
        raise ValueError("missing_name")
    members = list(dict.fromkeys((members or []) + [founder]))
    if len(members) > 5:
        raise ValueError("squad_capped_at_5")
    sid = _slug(name)
    # Append a suffix if collision
    p = _squads_dir(bullpen) / f"{sid}.json"
    if p.exists():
        sid = f"{sid}-{datetime.datetime.now().strftime('%H%M%S')}"
        p = _squads_dir(bullpen) / f"{sid}.json"
    color = color or SQUAD_COLORS[hash(sid) % len(SQUAD_COLORS)]
    squad = {
        "id": sid, "name": name.strip(), "founder": founder,
        "members": members, "color": color,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    p.write_text(json.dumps(squad, indent=2) + "\n")
    audit_append(bullpen, founder, "squad_formed",
                 target_type="squad", target_id=sid,
                 payload={"name": squad["name"], "members": members, "color": color})
    return squad


def list_squads(bullpen: str) -> list[dict]:
    out = []
    for f in sorted(_squads_dir(bullpen).glob("*.json")):
        try: out.append(json.loads(f.read_text()))
        except Exception: continue
    return out


def squad_for_rep(bullpen: str, rep: str) -> Optional[dict]:
    """A rep belongs to at most one squad. First squad found wins."""
    for s in list_squads(bullpen):
        if rep in (s.get("members") or []):
            return s
    return None


def join_squad(bullpen: str, squad_id: str, rep: str) -> dict:
    p = _squads_dir(bullpen) / f"{squad_id}.json"
    if not p.exists():
        raise ValueError("squad_not_found")
    s = json.loads(p.read_text())
    if rep in s["members"]:
        return s
    if len(s["members"]) >= 5:
        raise ValueError("squad_full")
    s["members"].append(rep)
    p.write_text(json.dumps(s, indent=2) + "\n")
    audit_append(bullpen, rep, "squad_joined",
                 target_type="squad", target_id=squad_id,
                 payload={"name": s["name"]})
    return s


def leave_squad(bullpen: str, squad_id: str, rep: str) -> dict:
    p = _squads_dir(bullpen) / f"{squad_id}.json"
    if not p.exists():
        raise ValueError("squad_not_found")
    s = json.loads(p.read_text())
    if rep not in s["members"]:
        return s
    s["members"] = [m for m in s["members"] if m != rep]
    p.write_text(json.dumps(s, indent=2) + "\n")
    audit_append(bullpen, rep, "squad_left",
                 target_type="squad", target_id=squad_id,
                 payload={"name": s["name"]})
    return s


def squad_xp_bonus(bullpen: str, rep: str) -> float:
    """+5% XP per teammate, capped at +20%."""
    s = squad_for_rep(bullpen, rep)
    if not s:
        return 1.0
    teammates = max(0, len(s.get("members") or []) - 1)
    return 1.0 + min(0.20, 0.05 * teammates)


# ── Raid parties ─────────────────────────────────────────────────────────
#
# A raid party is keyed off (bullpen, raid_id). Each rep that joins a raid
# is added to that raid's party file. Progress evaluation (see quests.py)
# can use this list to know the full member set + the per-member share.

def _raid_party_path(bullpen: str, raid_id: str) -> Path:
    return _raid_parties_dir(bullpen) / f"{raid_id}.json"


def party_for_raid(bullpen: str, raid_id: str) -> dict:
    p = _raid_party_path(bullpen, raid_id)
    if not p.exists():
        return {"raid_id": raid_id, "members": [], "completed_at": None,
                "completed_members": []}
    try: return json.loads(p.read_text())
    except Exception: return {"raid_id": raid_id, "members": [], "completed_at": None,
                              "completed_members": []}


def join_raid(bullpen: str, raid_id: str, rep: str) -> dict:
    party = party_for_raid(bullpen, raid_id)
    if rep in party["members"]:
        return party
    party["members"].append(rep)
    _raid_party_path(bullpen, raid_id).write_text(json.dumps(party, indent=2) + "\n")
    audit_append(bullpen, rep, "raid_joined",
                 target_type="raid", target_id=raid_id,
                 payload={"party_size": len(party["members"])})
    return party


def leave_raid(bullpen: str, raid_id: str, rep: str) -> dict:
    party = party_for_raid(bullpen, raid_id)
    if rep not in party["members"]:
        return party
    party["members"] = [m for m in party["members"] if m != rep]
    _raid_party_path(bullpen, raid_id).write_text(json.dumps(party, indent=2) + "\n")
    audit_append(bullpen, rep, "raid_left",
                 target_type="raid", target_id=raid_id,
                 payload={"party_size": len(party["members"])})
    return party


def raid_party_progress(bullpen: str, raid_id: str, raid: dict) -> dict:
    """Sum progress across every party member against the raid predicate.
    Returns {members, count, target, completed, pct, per_member_share}."""
    party = party_for_raid(bullpen, raid_id)
    members = party.get("members") or []
    pred = raid.get("predicate") or {}
    target = int(pred.get("count") or 1)
    starts_at = raid.get("starts_at")

    def matches(e):
        if e.get("actor") not in members:
            return False
        if e.get("kind") != pred.get("kind"):
            return False
        if starts_at and (e.get("ts") or "") < starts_at:
            return False
        match = pred.get("match") or {}
        payload = e.get("payload") or {}
        return all(payload.get(k) == v for k, v in match.items())

    matching = [e for e in audit_iter_all(bullpen) if matches(e)]
    if pred.get("distinct_phase"):
        phases = {(e.get("payload") or {}).get("phase") for e in matching}
        count = len(phases - {None})
    else:
        count = len(matching)

    party_size = max(1, len(members))
    xp_reward = int(raid.get("xp_reward") or 0)
    per_share = xp_reward // party_size

    return {
        "raid_id": raid_id, "members": members, "party_size": party_size,
        "count": count, "target": target,
        "pct": min(1.0, round(count / max(1, target), 3)),
        "completed": count >= target,
        "completed_at": party.get("completed_at"),
        "completed_members": party.get("completed_members") or [],
        "xp_reward_total": xp_reward,
        "xp_per_member": per_share,
    }


def claim_raid_rewards(bullpen: str, raid_id: str, raid: dict, rep: str) -> Optional[dict]:
    """If the raid is complete AND `rep` is in the party AND hasn't claimed
    yet, emit a quest_completed event for their share. Returns the claim
    record or None."""
    prog = raid_party_progress(bullpen, raid_id, raid)
    if not prog["completed"]:
        return None
    if rep not in prog["members"]:
        return None
    party = party_for_raid(bullpen, raid_id)
    if rep in (party.get("completed_members") or []):
        return None

    party.setdefault("completed_members", []).append(rep)
    if not party.get("completed_at"):
        party["completed_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    _raid_party_path(bullpen, raid_id).write_text(json.dumps(party, indent=2) + "\n")

    audit_append(bullpen, rep, "quest_completed",
                 target_type="raid", target_id=raid_id,
                 payload={"quest_name": raid.get("name") or raid_id,
                          "scope": "raid",
                          "xp_reward": prog["xp_per_member"],
                          "party_size": prog["party_size"]})
    return {"rep": rep, "xp": prog["xp_per_member"], "party_size": prog["party_size"]}
