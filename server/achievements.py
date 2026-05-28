"""Achievements — 60+ unlocks evaluated against the audit log.

Each achievement has a `trigger` function that takes (rep, audit_iterator)
and returns True the first time the rep qualifies. We persist awards
per-rep at `bullpens/<slug>/achievements/<rep>.jsonl` so an unlock fires
exactly once per rep per bullpen.

The catalog defines RARITY tiers; xp.py reads payload['rarity'] to award
the right XP (common=50, rare=200, epic=750, legendary=2000).
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Callable, Optional

from audit import iter_all as audit_iter_all
from audit import append as audit_append

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


# ── Trigger helpers ──────────────────────────────────────────────────────

def _count(kind: str, predicate: Optional[Callable[[dict], bool]] = None):
    def trig(rep: str, events: list[dict]) -> int:
        n = 0
        for e in events:
            if e.get("actor") != rep:
                continue
            if e.get("kind") != kind:
                continue
            if predicate and not predicate(e.get("payload") or {}):
                continue
            n += 1
        return n
    return trig


def _at_least(trigger: Callable, n: int) -> Callable:
    def trig(rep: str, events: list[dict]) -> bool:
        return trigger(rep, events) >= n
    return trig


def _ever(kind: str, predicate: Optional[Callable[[dict], bool]] = None):
    return _at_least(_count(kind, predicate), 1)


def _sum(kind: str, field: str, predicate: Optional[Callable] = None):
    """Sum a numeric field across matching events."""
    def trig(rep: str, events: list[dict]) -> float:
        total = 0.0
        for e in events:
            if e.get("actor") != rep or e.get("kind") != kind:
                continue
            payload = e.get("payload") or {}
            if predicate and not predicate(payload):
                continue
            try:
                total += float(payload.get(field) or 0)
            except Exception:
                continue
        return total
    return trig


def _sum_at_least(kind: str, field: str, threshold: float):
    s = _sum(kind, field)
    return lambda rep, events: s(rep, events) >= threshold


# ── Catalog ─────────────────────────────────────────────────────────────

CATALOG: list[dict] = [
    # ════════════════════════ COMMON (30) ═══════════════════════════════
    {"id": "first-claim",     "name": "First Claim",     "rarity": "common",
     "icon": "🚩", "desc": "Claim your first prospect.",
     "trigger": _ever("claim")},
    {"id": "first-call",      "name": "First Call",      "rarity": "common",
     "icon": "📞", "desc": "Upload your first call.",
     "trigger": _ever("call")},
    {"id": "first-deal",      "name": "First Deal",      "rarity": "common",
     "icon": "💼", "desc": "Create your first deal.",
     "trigger": _ever("deal_created")},
    {"id": "first-close",     "name": "First Close",     "rarity": "common",
     "icon": "✓", "desc": "Close your first deal.",
     "trigger": _ever("deal_closed_won")},
    {"id": "first-drill",     "name": "Welcome to the Bullpen", "rarity": "common",
     "icon": "🎯", "desc": "Complete your first practice drill.",
     "trigger": _ever("call", lambda p: p.get("call_kind") == "practice")},
    {"id": "first-signature", "name": "Paper Signed",    "rarity": "common",
     "icon": "✍", "desc": "Sign your first legal doc.",
     "trigger": _ever("doc_signed")},
    {"id": "first-vm",        "name": "Left a Mark",     "rarity": "common",
     "icon": "🎙", "desc": "Leave your first voicemail (Phase II).",
     "trigger": _ever("drill_passed", lambda p: p.get("phase") == 2)},
    {"id": "first-gatekeeper", "name": "Through the Gate", "rarity": "common",
     "icon": "🚪", "desc": "Pass Phase I — Get past the gatekeeper.",
     "trigger": _ever("drill_passed", lambda p: p.get("phase") == 1)},
    {"id": "first-pitch",     "name": "Earned the Room", "rarity": "common",
     "icon": "🎤", "desc": "Pass Phase III — 60-sec pitch.",
     "trigger": _ever("drill_passed", lambda p: p.get("phase") == 3)},
    {"id": "first-pricing",   "name": "Held the Line",   "rarity": "common",
     "icon": "🛡", "desc": "Pass Phase IV — defend your pricing.",
     "trigger": _ever("drill_passed", lambda p: p.get("phase") == 4)},
    {"id": "first-cio",       "name": "Cornered the Office", "rarity": "common",
     "icon": "🏢", "desc": "Pass Phase V — CIO elevator.",
     "trigger": _ever("drill_passed", lambda p: p.get("phase") == 5)},
    {"id": "first-clarity",   "name": "Civilian-Tested", "rarity": "common",
     "icon": "👋", "desc": "Pass Phase VI — explain it without jargon.",
     "trigger": _ever("drill_passed", lambda p: p.get("phase") == 6)},
    {"id": "first-handoff",   "name": "Passed the Torch", "rarity": "common",
     "icon": "🔥", "desc": "Pass Phase VII — recap to your teammate.",
     "trigger": _ever("drill_passed", lambda p: p.get("phase") == 7)},
    {"id": "ten-dials",       "name": "Ten Dials",       "rarity": "common",
     "icon": "📞", "desc": "Log 10 real calls.",
     "trigger": _at_least(_count("call", lambda p: p.get("call_kind") == "real"), 10)},
    {"id": "ten-drills",      "name": "Drilled",         "rarity": "common",
     "icon": "🥊", "desc": "Complete 10 practice drills.",
     "trigger": _at_least(_count("call", lambda p: p.get("call_kind") == "practice"), 10)},
    {"id": "ten-claims",      "name": "Land Grab",       "rarity": "common",
     "icon": "🗺", "desc": "Claim 10 prospects.",
     "trigger": _at_least(_count("claim"), 10)},
    {"id": "three-deals",     "name": "Pipeline Builder", "rarity": "common",
     "icon": "📊", "desc": "Have 3 deals in the pipeline.",
     "trigger": _at_least(_count("deal_created"), 3)},
    {"id": "demo-day",        "name": "Demo Day",        "rarity": "common",
     "icon": "🎬", "desc": "Move a deal into Demo stage.",
     "trigger": _ever("deal_stage_moved", lambda p: p.get("to") == "demo")},
    {"id": "pilot-stage",     "name": "On the Tarmac",   "rarity": "common",
     "icon": "✈", "desc": "Move a deal into Pilot stage.",
     "trigger": _ever("deal_stage_moved", lambda p: p.get("to") == "pilot")},
    {"id": "five-drills",     "name": "Bullpen Regular", "rarity": "common",
     "icon": "🎯", "desc": "Complete 5 practice drills.",
     "trigger": _at_least(_count("call", lambda p: p.get("call_kind") == "practice"), 5)},
    {"id": "fifty-claims",    "name": "Empire Builder",  "rarity": "common",
     "icon": "🏰", "desc": "Claim 50 prospects.",
     "trigger": _at_least(_count("claim"), 50)},
    {"id": "first-quest",     "name": "On Quest",        "rarity": "common",
     "icon": "📜", "desc": "Complete your first daily quest.",
     "trigger": _ever("quest_completed")},
    {"id": "first-mentor",    "name": "Helping Hand",    "rarity": "common",
     "icon": "🤝", "desc": "Mentor a teammate on a call.",
     "trigger": _ever("mentor_flag")},
    {"id": "first-extract",   "name": "Memory Bank",     "rarity": "common",
     "icon": "🧠", "desc": "Extract a new contact from a real call.",
     "trigger": _ever("debrief_extracted")},
    {"id": "speaking-five",   "name": "Voice Lessons",   "rarity": "common",
     "icon": "🗣", "desc": "Complete 5 speaking drills.",
     "trigger": _at_least(_count("call", lambda p: p.get("call_kind") == "speaking"), 5)},
    {"id": "ten-stage-moves", "name": "Pipeline Mover",  "rarity": "common",
     "icon": "➡", "desc": "Advance deals 10 times.",
     "trigger": _at_least(_count("deal_stage_moved"), 10)},
    {"id": "first-release",   "name": "Generous",        "rarity": "common",
     "icon": "🔓", "desc": "Voluntarily release a claim for a teammate.",
     "trigger": _ever("release", lambda p: not p.get("auto_release"))},
    {"id": "morning-warrior", "name": "Morning Warrior", "rarity": "common",
     "icon": "🌅", "desc": "Make a call before 9 AM local.",
     "trigger": _ever("call", lambda p: p.get("hour_local") is not None and p["hour_local"] < 9)},
    {"id": "late-shift",      "name": "Late Shift",      "rarity": "common",
     "icon": "🌙", "desc": "Make a call after 6 PM local.",
     "trigger": _ever("call", lambda p: p.get("hour_local") is not None and p["hour_local"] >= 18)},
    {"id": "founders-token",  "name": "Founder's Token", "rarity": "common",
     "icon": "👑", "desc": "Founded a bullpen.",
     "trigger": _ever("bullpen_created")},

    # ════════════════════════ RARE (20) ════════════════════════════════
    {"id": "all-seven-phases", "name": "The Gauntlet",   "rarity": "rare",
     "icon": "🏆", "desc": "Pass all 7 Gauntlet phases.",
     "trigger": lambda rep, events: len({(e.get("payload") or {}).get("phase")
                                          for e in events
                                          if e.get("actor") == rep
                                          and e.get("kind") == "drill_passed"
                                          and (e.get("payload") or {}).get("phase") in {1,2,3,4,5,6,7}}) >= 7},
    {"id": "five-meetings",   "name": "Pipeline on Fire", "rarity": "rare",
     "icon": "📅", "desc": "Book 5 briefings (deal → demo).",
     "trigger": _at_least(_count("deal_stage_moved", lambda p: p.get("to") == "demo"), 5)},
    {"id": "five-closes",     "name": "Closer Mode",     "rarity": "rare",
     "icon": "💰", "desc": "Close 5 deals.",
     "trigger": _at_least(_count("deal_closed_won"), 5)},
    {"id": "twenty-five-dials", "name": "Iron Lungs",    "rarity": "rare",
     "icon": "🫁", "desc": "Log 25 real calls.",
     "trigger": _at_least(_count("call", lambda p: p.get("call_kind") == "real"), 25)},
    {"id": "fifty-drills",    "name": "The Cage",        "rarity": "rare",
     "icon": "💪", "desc": "Complete 50 practice drills.",
     "trigger": _at_least(_count("call", lambda p: p.get("call_kind") == "practice"), 50)},
    {"id": "hundred-claims",  "name": "Conqueror",       "rarity": "rare",
     "icon": "⚔", "desc": "Claim 100 prospects.",
     "trigger": _at_least(_count("claim"), 100)},
    {"id": "first-25k",       "name": "$25K Closed",     "rarity": "rare",
     "icon": "💸", "desc": "Close $25,000 in cumulative deals.",
     "trigger": _sum_at_least("deal_closed_won", "amount", 25_000)},
    {"id": "first-50k",       "name": "$50K Closed",     "rarity": "rare",
     "icon": "💵", "desc": "Close $50,000 in cumulative deals.",
     "trigger": _sum_at_least("deal_closed_won", "amount", 50_000)},
    {"id": "two-pilot-signs", "name": "Signature Streak", "rarity": "rare",
     "icon": "📝", "desc": "Sign 2 pilot contracts.",
     "trigger": _at_least(_count("pilot_signed"), 2)},
    {"id": "ten-stage-advances", "name": "Velocity",     "rarity": "rare",
     "icon": "🚀", "desc": "Advance 10 deals through stages.",
     "trigger": _at_least(_count("deal_stage_moved"), 10)},
    {"id": "five-mentors",    "name": "Building the Bench", "rarity": "rare",
     "icon": "👥", "desc": "Mentor on 5 calls.",
     "trigger": _at_least(_count("mentor_flag"), 5)},
    {"id": "raid-leader",     "name": "Raid Leader",     "rarity": "rare",
     "icon": "⚔", "desc": "Lead a raid your party completes.",
     "trigger": _ever("raid_completed", lambda p: p.get("leader_was_me"))},
    {"id": "twenty-drills-week", "name": "Grinder",      "rarity": "rare",
     "icon": "🔁", "desc": "Complete 20 drills in 7 days.",
     "trigger": lambda rep, events: _drills_in_window(rep, events, days=7) >= 20},
    {"id": "ten-extracts",    "name": "Memory Palace",   "rarity": "rare",
     "icon": "🏛", "desc": "Extract 10 new contacts from real calls.",
     "trigger": _at_least(_count("debrief_extracted"), 10)},
    {"id": "five-quests",     "name": "Quest Hunter",    "rarity": "rare",
     "icon": "🗡", "desc": "Complete 5 quests.",
     "trigger": _at_least(_count("quest_completed"), 5)},
    {"id": "ten-vm-returned", "name": "VM Master",       "rarity": "rare",
     "icon": "📨", "desc": "Get 10 voicemails returned.",
     "trigger": _at_least(_count("vm_returned"), 10)},
    {"id": "first-cosign",    "name": "Co-Sign Cash",    "rarity": "rare",
     "icon": "🤝", "desc": "Co-sign a deal that closes.",
     "trigger": _ever("cosign_paid")},
    {"id": "week-streak",     "name": "7-Day Streak",    "rarity": "rare",
     "icon": "🔥", "desc": "7 consecutive days with XP gain.",
     "trigger": lambda rep, events: _max_streak(rep, events) >= 7},
    {"id": "first-100k",      "name": "Six Figures",     "rarity": "rare",
     "icon": "💎", "desc": "Close $100,000 in cumulative deals.",
     "trigger": _sum_at_least("deal_closed_won", "amount", 100_000)},
    {"id": "perfect-drill",   "name": "No Fillers",      "rarity": "rare",
     "icon": "🎯", "desc": "Pass a drill with 0 filler words.",
     "trigger": _ever("drill_passed", lambda p: (p.get("filler_count") or 0) == 0)},

    # ════════════════════════ EPIC (8) ══════════════════════════════════
    {"id": "month-streak",    "name": "30-Day Streak",   "rarity": "epic",
     "icon": "🔥🔥", "desc": "30 consecutive days with XP gain.",
     "trigger": lambda rep, events: _max_streak(rep, events) >= 30},
    {"id": "all-7-week",      "name": "Speed Run",       "rarity": "epic",
     "icon": "⚡", "desc": "Pass all 7 Gauntlet phases inside 7 days.",
     "trigger": lambda rep, events: _all_phases_within(rep, events, days=7)},
    {"id": "first-250k",      "name": "Quarter-Mil",     "rarity": "epic",
     "icon": "🏛", "desc": "Close $250,000 in cumulative deals.",
     "trigger": _sum_at_least("deal_closed_won", "amount", 250_000)},
    {"id": "ten-closes",      "name": "The Hot Hand",    "rarity": "epic",
     "icon": "✨", "desc": "Close 10 deals.",
     "trigger": _at_least(_count("deal_closed_won"), 10)},
    {"id": "ten-pilots-signed", "name": "Pilot Pipeline", "rarity": "epic",
     "icon": "📋", "desc": "Sign 10 pilot contracts.",
     "trigger": _at_least(_count("pilot_signed"), 10)},
    {"id": "ten-mentor-graduates", "name": "Coach Of The Year", "rarity": "epic",
     "icon": "🎓", "desc": "Have 10 mentored sessions logged.",
     "trigger": _at_least(_count("mentor_flag"), 10)},
    {"id": "comeback",        "name": "The Comeback",    "rarity": "epic",
     "icon": "🔄", "desc": "Close a deal that stalled >60 days.",
     "trigger": _ever("deal_closed_won", lambda p: (p.get("days_in_pipeline") or 0) > 60)},
    {"id": "iron-throat",     "name": "Iron Throat",     "rarity": "epic",
     "icon": "🗣🔥", "desc": "10 calls in one day, all <3 fillers.",
     "trigger": lambda rep, events: _iron_throat(rep, events)},

    # ════════════════════════ LEGENDARY (4) ═════════════════════════════
    {"id": "first-million",   "name": "The Whale",       "rarity": "legendary",
     "icon": "🐋", "desc": "Close $1,000,000 cumulative.",
     "trigger": _sum_at_least("deal_closed_won", "amount", 1_000_000)},
    {"id": "hundred-streak",  "name": "100-Day Streak",  "rarity": "legendary",
     "icon": "💯🔥", "desc": "100 consecutive days with XP gain.",
     "trigger": lambda rep, events: _max_streak(rep, events) >= 100},
    {"id": "the-architect",   "name": "The Architect",   "rarity": "legendary",
     "icon": "🏗", "desc": "Build your own bullpen (be a founder).",
     "trigger": _ever("bullpen_created")},
    {"id": "perfect-quarter", "name": "Perfect Quarter", "rarity": "legendary",
     "icon": "💎🔥", "desc": "Close every deal in your pipeline in a calendar quarter.",
     "trigger": lambda rep, events: _perfect_quarter(rep, events)},
]


# ── Trigger helpers that need richer event walks ─────────────────────────

def _drills_in_window(rep: str, events: list[dict], days: int) -> int:
    import datetime as dt
    now = dt.datetime.now()
    window_start = now - dt.timedelta(days=days)
    n = 0
    for e in events:
        if e.get("actor") != rep or e.get("kind") != "call":
            continue
        if (e.get("payload") or {}).get("call_kind") != "practice":
            continue
        try:
            t = dt.datetime.fromisoformat(e.get("ts", ""))
        except Exception:
            continue
        if t >= window_start:
            n += 1
    return n


def _all_phases_within(rep: str, events: list[dict], days: int) -> bool:
    import datetime as dt
    passes = {}   # phase → ts
    for e in events:
        if e.get("actor") != rep or e.get("kind") != "drill_passed":
            continue
        phase = (e.get("payload") or {}).get("phase")
        if phase not in {1,2,3,4,5,6,7}:
            continue
        try:
            t = dt.datetime.fromisoformat(e.get("ts", ""))
        except Exception:
            continue
        if phase not in passes or t < passes[phase]:
            passes[phase] = t
    if len(passes) < 7:
        return False
    span = max(passes.values()) - min(passes.values())
    return span.days <= days


def _max_streak(rep: str, events: list[dict]) -> int:
    """Longest run of consecutive days with at least one XP-earning event."""
    import datetime as dt
    days = set()
    for e in events:
        if e.get("actor") != rep:
            continue
        try:
            d = dt.datetime.fromisoformat(e.get("ts", "")).date()
        except Exception:
            continue
        days.add(d)
    if not days:
        return 0
    sorted_days = sorted(days)
    best = current = 1
    for i in range(1, len(sorted_days)):
        if (sorted_days[i] - sorted_days[i-1]).days == 1:
            current += 1
            best = max(best, current)
        else:
            current = 1
    return best


def _iron_throat(rep: str, events: list[dict]) -> bool:
    """≥10 calls in a single day, all with <3 filler_count."""
    import datetime as dt
    by_day: dict = {}
    for e in events:
        if e.get("actor") != rep or e.get("kind") != "call":
            continue
        try:
            d = dt.datetime.fromisoformat(e.get("ts", "")).date()
        except Exception:
            continue
        fillers = (e.get("payload") or {}).get("filler_count")
        slot = by_day.setdefault(d, {"total": 0, "good": 0})
        slot["total"] += 1
        if fillers is not None and fillers < 3:
            slot["good"] += 1
    return any(s["total"] >= 10 and s["good"] == s["total"] for s in by_day.values())


def _perfect_quarter(rep: str, events: list[dict]) -> bool:
    """Every closed deal in a calendar quarter was closed-won. Need ≥3 deals."""
    import datetime as dt
    by_q: dict = {}
    for e in events:
        if e.get("actor") != rep:
            continue
        if e.get("kind") not in ("deal_closed_won", "deal_closed_lost"):
            continue
        try:
            d = dt.datetime.fromisoformat(e.get("ts", "")).date()
        except Exception:
            continue
        q = (d.year, (d.month - 1) // 3 + 1)
        slot = by_q.setdefault(q, {"won": 0, "lost": 0})
        if e.get("kind") == "deal_closed_won":
            slot["won"] += 1
        else:
            slot["lost"] += 1
    return any(s["won"] >= 3 and s["lost"] == 0 for s in by_q.values())


# ── Award persistence + evaluation ───────────────────────────────────────

def _awards_path(bullpen: str, rep: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "achievements"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{rep}.jsonl"


def awards_for(bullpen: str, rep: str) -> list[dict]:
    p = _awards_path(bullpen, rep)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if not line.strip(): continue
        try: out.append(json.loads(line))
        except Exception: continue
    return out


def _already_awarded(bullpen: str, rep: str, achievement_id: str) -> bool:
    return any(a.get("id") == achievement_id for a in awards_for(bullpen, rep))


def evaluate(bullpen: str, rep: Optional[str] = None) -> list[dict]:
    """Walk the audit log, fire any newly-qualified achievements for the
    given rep (or for all reps if None). Returns the list of newly-awarded
    achievements. Idempotent — already-awarded ones don't fire again."""
    events = list(audit_iter_all(bullpen))
    reps = {rep} if rep else {e.get("actor") for e in events if e.get("actor")}
    reps.discard(None); reps.discard("system")

    newly_awarded = []
    for r in reps:
        for ach in CATALOG:
            if _already_awarded(bullpen, r, ach["id"]):
                continue
            try:
                if ach["trigger"](r, events):
                    award = {
                        "id": ach["id"],
                        "name": ach["name"],
                        "rarity": ach["rarity"],
                        "icon": ach["icon"],
                        "desc": ach["desc"],
                        "awarded_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    }
                    with _awards_path(bullpen, r).open("a") as f:
                        f.write(json.dumps(award) + "\n")
                    # Also emit an audit event so XP picks it up
                    audit_append(bullpen, r, "achievement_unlocked",
                                 target_type="achievement", target_id=ach["id"],
                                 payload={"name": ach["name"], "rarity": ach["rarity"]})
                    newly_awarded.append({**award, "rep": r})
            except Exception:
                continue
    return newly_awarded


def catalog() -> list[dict]:
    """Return the public catalog (without the trigger callables)."""
    return [{k: v for k, v in a.items() if k != "trigger"} for a in CATALOG]


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 server/achievements.py evaluate <bullpen> [rep]")
        print("       python3 server/achievements.py list <bullpen> <rep>")
        print("       python3 server/achievements.py catalog")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "evaluate":
        bullpen = sys.argv[2]
        rep = sys.argv[3] if len(sys.argv) > 3 else None
        new = evaluate(bullpen, rep)
        if not new:
            print(f"No new achievements for {rep or 'anyone'} in {bullpen}.")
        else:
            print(f"✓ Awarded {len(new)} new achievement(s):")
            for a in new:
                print(f"  {a['icon']}  {a['name']:30}  {a['rarity']:10}  → {a['rep']}")
    elif cmd == "list":
        bullpen, rep = sys.argv[2], sys.argv[3]
        for a in awards_for(bullpen, rep):
            print(f"  {a['icon']}  {a['name']:30}  {a['rarity']:10}  {a['awarded_at']}")
    elif cmd == "catalog":
        for a in catalog():
            print(f"  {a['icon']}  {a['name']:30}  {a['rarity']:10}  {a['desc']}")
