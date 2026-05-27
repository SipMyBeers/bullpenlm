"""Team layer — multi-rep coordination for a hosted BullpenLM instance.

One Mac (or VPS) hosts the trainer server. Anyone with network access (e.g.
Tailscale into the host) can join by typing their REP name in the floor UI;
their calls, claims, and drill progress get attributed under that name. This
module is the file-based backend for:

  * Claims         — who currently owns which prospect (territory locks)
  * Roster         — every rep who has ever shown up on this instance
  * Leaderboard    — per-rep totals: calls, badges, current rank
  * Activity feed  — append-only log of team events for the live ticker

No database. Just JSON files in `team/`. Lockless reads, single-writer assumed
(the host server is the only writer); good enough for a 2-10 rep team.
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent
TEAM_DIR = REPO / "team"
CLAIMS_DIR = TEAM_DIR / "claims"
ACTIVITY_LOG = TEAM_DIR / "activity.jsonl"
TRAINING_DIR = REPO / "training-runs"
ORGS_DIR = REPO / "organizations"

TEAM_DIR.mkdir(exist_ok=True)
CLAIMS_DIR.mkdir(exist_ok=True)

# ── Claims ────────────────────────────────────────────────────────────────

# Strict mode: a claim locks a prospect to one rep until they release it,
# OR until CLAIM_AUTO_RELEASE_DAYS pass with no activity from the owner.
CLAIM_AUTO_RELEASE_DAYS = 14


def _claim_path(prospect_slug: str) -> Path:
    return CLAIMS_DIR / f"{prospect_slug}.json"


def get_claim(prospect_slug: str) -> Optional[dict]:
    """Return current claim dict, or None if unclaimed (or auto-released)."""
    p = _claim_path(prospect_slug)
    if not p.exists():
        return None
    try:
        c = json.loads(p.read_text())
    except Exception:
        return None
    last = c.get("last_activity") or c.get("claimed_at")
    if last:
        age_days = (datetime.datetime.now() -
                    datetime.datetime.fromisoformat(last)).days
        if age_days >= CLAIM_AUTO_RELEASE_DAYS:
            # Auto-release stale claims. Record the release as a tombstone
            # so the activity feed picks it up.
            release_claim(prospect_slug, by="system-auto-release")
            return None
    return c


def claim(prospect_slug: str, rep: str, *, bullpen: Optional[str] = None) -> dict:
    """Claim a prospect for a rep. If already claimed by someone else, this
    is rejected (caller should surface the existing owner).

    Phase 0.5 firewall: when `bullpen` is supplied, the live-work gate
    fires first. If the gate refuses (closer missing signed agreement,
    W-9, drill cert, jurisdiction OK, or DNC scrub), the claim is
    blocked and the missing requirements are returned so the UI can
    show the closer exactly what to complete.

    Backward compat: legacy callers that pass no `bullpen` continue to
    claim without the gate (used by the global team layer of the
    self-hosted host, which predates bullpens). The audit chain records
    these as `gate_bypassed_legacy` so we can grep for callers still on
    the old path.
    """
    if bullpen:
        try:
            from gates import can_claim_live_prospect
            from audit import append as audit_append
            check = can_claim_live_prospect(bullpen, rep, prospect_slug)
            if not check.ok:
                audit_append(bullpen, kind="gate_refused", actor=rep, payload={
                    "prospect": prospect_slug,
                    "missing": check.missing,
                })
                return {
                    "ok": False,
                    "error": "live_work_gate_refused",
                    "missing": check.missing,
                    "details": check.details,
                }
        except Exception as e:
            # Fail-closed: if the gate module can't be loaded, refuse
            # the live claim rather than silently bypassing it.
            return {"ok": False, "error": "gate_unavailable", "detail": str(e)}
    else:
        # Audit-flag the bypass so we can find legacy code paths.
        try:
            from audit import append as audit_append
            audit_append("_global", kind="gate_bypassed_legacy", actor=rep,
                         payload={"prospect": prospect_slug})
        except Exception:
            pass

    existing = get_claim(prospect_slug)
    if existing and existing.get("rep") != rep:
        return {"ok": False, "error": "already_claimed",
                "claim": existing}
    now = datetime.datetime.now().isoformat(timespec="seconds")
    data = {
        "prospect_slug": prospect_slug,
        "rep": rep,
        "claimed_at": existing.get("claimed_at") if existing else now,
        "last_activity": now,
        "bullpen": bullpen,
    }
    _claim_path(prospect_slug).write_text(json.dumps(data, indent=2) + "\n")
    _log_event("claim", rep=rep, prospect=prospect_slug)
    return {"ok": True, "claim": data}


def release_claim(prospect_slug: str, by: str) -> dict:
    """Release a claim. The owner can release at any time; the system can
    auto-release stale claims."""
    p = _claim_path(prospect_slug)
    if not p.exists():
        return {"ok": True, "released": False}
    try:
        prev = json.loads(p.read_text())
    except Exception:
        prev = {}
    p.unlink()
    _log_event("release", rep=by, prospect=prospect_slug,
               note=f"previously held by {prev.get('rep', '?')}")
    return {"ok": True, "released": True, "previous": prev}


def touch_claim(prospect_slug: str, rep: str) -> None:
    """Bump the last_activity timestamp on a claim. Called from /api/upload-call
    and other rep-activity endpoints so active claims don't auto-release."""
    p = _claim_path(prospect_slug)
    if not p.exists():
        return
    try:
        c = json.loads(p.read_text())
    except Exception:
        return
    if c.get("rep") != rep:
        return
    c["last_activity"] = datetime.datetime.now().isoformat(timespec="seconds")
    p.write_text(json.dumps(c, indent=2) + "\n")


def list_all_claims() -> list[dict]:
    """Return every active claim (with auto-released ones already filtered)."""
    out = []
    for p in sorted(CLAIMS_DIR.glob("*.json")):
        slug = p.stem
        c = get_claim(slug)  # via get_claim so auto-release fires
        if c:
            out.append(c)
    return out


# ── Roster ─────────────────────────────────────────────────────────────────

def get_roster() -> list[str]:
    """Every rep name that has ever shown up in metrics. Sorted, unique."""
    reps = {"self"}
    if TRAINING_DIR.exists():
        for mf in TRAINING_DIR.glob("*.metrics.json"):
            try:
                r = json.loads(mf.read_text()).get("rep")
                if r:
                    reps.add(r)
            except Exception:
                pass
    if ORGS_DIR.exists():
        for cm in ORGS_DIR.glob("*/calls/*/metadata.json"):
            try:
                r = json.loads(cm.read_text()).get("rep")
                if r:
                    reps.add(r)
            except Exception:
                pass
    return sorted(reps)


# ── Leaderboard ────────────────────────────────────────────────────────────

# Gauntlet phase definitions — must match the landing/floor app.
# `match` is a substring searched in the persona slug used during the drill.
PHASES = [
    {"id": 1, "name": "Through the gate",      "badge": "THE GATEKEEPER'S NOD", "match": "warm-gatekeeper"},
    {"id": 2, "name": "Leave a mark",          "badge": "VOICE MEMO",           "match": "voicemail"},
    {"id": 3, "name": "Earn the room",         "badge": "THE FLOOR",            "match": "skeptical-cto"},
    {"id": 4, "name": "Hold the line",         "badge": "THE LINE",             "match": "pe-pressured-cfo"},
    {"id": 5, "name": "Win the corner office", "badge": "THE CORNER OFFICE",    "match": "time-poor-ceo"},
    {"id": 6, "name": "The clarity test",      "badge": "THE CIVILIAN",         "match": "curious-champion"},
    {"id": 7, "name": "Pass the torch",        "badge": "THE BATON",            "match": "mentor-coach"},
]

# Rank thresholds — must match landing copy.
RANKS = [
    (0,  "ROOKIE"),
    (1,  "WALK-ON"),
    (3,  "STARTER"),
    (5,  "CLOSER"),
    (7,  "ALL-STAR"),
]


def _rank_for(badges: int) -> str:
    rank = "ROOKIE"
    for threshold, name in RANKS:
        if badges >= threshold:
            rank = name
    return rank


def get_leaderboard() -> list[dict]:
    """Per-rep totals + rank. Reads all metrics files once and aggregates."""
    by_rep: dict[str, dict] = {}
    real_calls_by_rep: dict[str, int] = {}

    # Practice + speaking sessions
    if TRAINING_DIR.exists():
        for mf in sorted(TRAINING_DIR.glob("*.metrics.json")):
            try:
                rec = json.loads(mf.read_text())
            except Exception:
                continue
            rep = rec.get("rep", "self")
            slot = by_rep.setdefault(rep, {
                "rep": rep, "calls": 0, "phases_passed": set(),
                "filler_total": 0, "filler_calls": 0,
                "last_seen": None,
            })
            slot["calls"] += 1
            slot["filler_total"] += rec.get("filler_count", 0) or 0
            slot["filler_calls"] += 1
            ts = rec.get("timestamp")
            if ts and (slot["last_seen"] is None or ts > slot["last_seen"]):
                slot["last_seen"] = ts
            # Did the persona slug match a phase?
            persona = rec.get("slug", "") or ""
            for phase in PHASES:
                if phase["match"] in persona:
                    slot["phases_passed"].add(phase["id"])

    # Real recorded calls
    if ORGS_DIR.exists():
        for cm in ORGS_DIR.glob("*/calls/*/metadata.json"):
            try:
                rec = json.loads(cm.read_text())
            except Exception:
                continue
            rep = rec.get("rep", "self")
            slot = by_rep.setdefault(rep, {
                "rep": rep, "calls": 0, "phases_passed": set(),
                "filler_total": 0, "filler_calls": 0, "last_seen": None,
            })
            real_calls_by_rep[rep] = real_calls_by_rep.get(rep, 0) + 1
            ts = rec.get("call_id") or rec.get("date")
            if ts and (slot["last_seen"] is None or ts > slot["last_seen"]):
                slot["last_seen"] = ts

    out = []
    for rep, slot in by_rep.items():
        passed = sorted(slot["phases_passed"])
        out.append({
            "rep": rep,
            "rank": _rank_for(len(passed)),
            "phases_passed": passed,
            "badges": [p["badge"] for p in PHASES if p["id"] in slot["phases_passed"]],
            "total_calls": slot["calls"] + real_calls_by_rep.get(rep, 0),
            "practice_calls": slot["calls"],
            "real_calls": real_calls_by_rep.get(rep, 0),
            "avg_fillers": round(slot["filler_total"] / slot["filler_calls"], 1) if slot["filler_calls"] else None,
            "last_seen": slot["last_seen"],
        })
    # Sort by (badges desc, calls desc, rep name)
    out.sort(key=lambda x: (-len(x["phases_passed"]), -x["total_calls"], x["rep"]))
    return out


# ── Activity feed ──────────────────────────────────────────────────────────

def _log_event(kind: str, rep: str, **fields) -> None:
    """Append-only JSON-lines log. Each line is a single event."""
    entry = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "rep": rep,
        **fields,
    }
    with ACTIVITY_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def log_call(rep: str, prospect_slug: str, kind: str = "practice",
             phase_passed: Optional[int] = None, metrics: Optional[dict] = None) -> None:
    """External callers use this to write a 'call' event. `kind` is
    'practice' | 'real' | 'speaking'."""
    fields = {"prospect": prospect_slug, "call_kind": kind}
    if phase_passed:
        fields["phase_passed"] = phase_passed
    if metrics:
        fields["filler_count"] = metrics.get("filler_count")
        fields["talk_ratio"] = metrics.get("talk_ratio")
    _log_event("call", rep=rep, **fields)


def get_activity_feed(limit: int = 30) -> list[dict]:
    """Last N events. Newest first."""
    if not ACTIVITY_LOG.exists():
        return []
    lines = ACTIVITY_LOG.read_text().splitlines()
    out = []
    for ln in lines[-limit*2:]:  # Read 2x then trim — handles malformed lines
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    out.reverse()
    return out[:limit]
