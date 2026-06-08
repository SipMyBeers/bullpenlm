#!/usr/bin/env python3
"""Reproducible seed for the BullpenLM team-tracking DEMO floor.

The demo floor (bullpen `demo`) is what a cold-open / App Store reviewer sees.
This recreates it from scratch so it survives a host reseed — no dependency on
any throwaway sandbox. Self-contained: it copies the Gauntlet play library from
the `default` bullpen (which every host seeds from the bundle on first run),
then defines its own reps and gives each a profile of cleared tiers + closes +
activity so the roster is lively, varied, and internally consistent (the
roster's gate-based rank matches each scorecard).

Run on the host:
  BULLPENLM_HOME="$HOME/Library/Application Support/BullpenLM" \
    python3 scripts/seed-demo.py

Idempotent — recreates `demo` each run. Knowledge = Gauntlet tiers cleared;
production = personal closes this month (Koscot firewall: never recruiting);
the drill cert clears once money_xp >= 100 (i.e. a few closes).
"""
import os
import sys
import json
import shutil
from pathlib import Path

HOME = Path(os.environ.get("BULLPENLM_HOME",
            str(Path.home() / "Library/Application Support/BullpenLM")))
os.environ["BULLPENLM_HOME"] = str(HOME)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

BULLPENS = HOME / "bullpens"
DEMO = BULLPENS / "demo"
DEFAULT = BULLPENS / "default"

# (rep, tiers_to_clear, closes_this_month, extra_recent_drills) -> a nice ladder
PROFILES = [
    ("priya-nair",     7, 22, 8),   # Legend
    ("marcus-cole",    6, 11, 14),  # All-Star
    ("dana-kim",       6, 10, 4),   # All-Star
    ("tyler-bryce",    5, 6,  6),   # Closer
    ("omar-haddad",    5, 5,  5),   # Closer
    ("bella-fontaine", 4, 4,  4),   # Starter
    ("jake-rollins",   3, 3,  3),   # Starter
    ("mia-santos",     2, 2,  2),   # Walk-On
    ("sofia-marin",    2, 1,  2),   # Walk-On
    ("chris-webb",     1, 0,  1),   # Rookie
]


def main():
    if not (DEFAULT / "tcs").exists():
        sys.exit("default/tcs not found — run the server once so it seeds the play library, then retry.")

    # 1. fresh demo dir with the play library (and buyers, for scorecard depth)
    if DEMO.exists():
        shutil.rmtree(DEMO)
    DEMO.mkdir(parents=True)
    shutil.copytree(DEFAULT / "tcs", DEMO / "tcs")
    if (DEFAULT / "buyer_cards").exists():
        shutil.copytree(DEFAULT / "buyer_cards", DEMO / "buyer_cards")
    (DEMO / "bullpen.json").write_text(json.dumps(
        {"slug": "demo", "name": "Demo Floor", "demo": True}))

    import tcs
    import audit

    # plays grouped by tier (from the copied library)
    plays = []
    for f in sorted((DEMO / "tcs").glob("*.json")):
        p = json.loads(f.read_text())
        plays.append((p["id"], int(p.get("phase_tier") or 0)))
    by_tier = {}
    for pid, tier in plays:
        by_tier.setdefault(tier, []).append(pid)
    all_ids = [pid for pid, _ in plays] or ["cold-open-bfsi"]

    for rep, tiers, closes, extra in PROFILES:
        # clear the plays for tiers 1..N -> qualifications + drill_passed + clout xp
        for tier in range(1, tiers + 1):
            for pid in by_tier.get(tier, []):
                try:
                    tcs.record_attempt("demo", rep, pid, "GO",
                                       checker="coach", source="spot_check", score=85)
                except Exception:
                    pass
        # extra recent drills for a lively roster
        for i in range(extra):
            audit.append("demo", actor_rep=rep, kind="drill_passed",
                         target_type="tcs", target_id=all_ids[i % len(all_ids)],
                         payload={"phase_tier": 1, "score": 82, "source": "self"})
        # closes this month -> production + money_xp (clears the drill cert at >=100)
        for c in range(closes):
            audit.append("demo", actor_rep=rep, kind="deal_closed_won",
                         target_type="deal", target_id=f"c-{rep}-{c}",
                         payload={"amount": 1200 + c * 150, "product": "KillSesh pilot"})
        audit.append("demo", actor_rep=rep, kind="activity_meeting",
                     target_type="org", target_id="demo", payload={})
        print(f"  seeded {rep}: {tiers} tiers, {closes} closes, +{extra} drills")

    print(f"demo seeded with {len(PROFILES)} reps at {DEMO}")


if __name__ == "__main__":
    main()
