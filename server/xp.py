"""XP rules + level curve + projection from the audit log.

═══════════════════════════════════════════════════════════════════════
TWO-LEDGER FIREWALL (Phase 0.5)
═══════════════════════════════════════════════════════════════════════

Every XP event lands in exactly one of three buckets:

    money — awarded only when value is actually created for a real
            external customer (closed deals, signed pilots) OR when
            outcome-tagged drill certifications prove competence to
            handle real customers. Drives commission tier eligibility
            and prospect claim priority.

    clout — awarded for social / volume / housekeeping activity (calls
            attempted, drills practiced, emails sent, meetings logged,
            achievements unlocked). Drives rank, leaderboard position,
            cosmetics. Vanity only. Never routes prospects, never
            raises commission %.

    none  — recorded in the audit chain for attribution, but credits
            no XP of any kind. Specifically: inviting another closer,
            recruiting another operator, sharing the bullpen, posting
            about the opportunity to recruit reps. Marketing the
            product (NOT the opportunity) is `clout`, not `none`.

The buckets are SEPARATE LEDGERS. They never merge. The allocation
firewall in `server/team.py` + `server/gates.py` accepts ONLY money_xp
as an earning-opportunity input — never clout_xp.

Why: the FTC's Koscot pyramid test asks whether earnings trace to real
product sold to real external customers, or to recruitment/promotion of
the opportunity itself. Two ledgers + zero-XP-for-recruitment + an
allocation firewall that can't accept clout-XP make the platform
structurally incapable of taking the bad shape.

If you're adding a rule and you're not sure which bucket it belongs in:
    - Does this event represent revenue created for a real external
      customer, or proof of competence to do so? → money
    - Is this event a recruit/promote-the-opportunity action? → none
    - Everything else → clout

═══════════════════════════════════════════════════════════════════════

Design contract: **XP is a derivation of the audit log, not a separate
store.** Every audit event has a corresponding XP delta (from `RULES`).
We compute totals on demand by streaming through
`audit.iter_all(bullpen)`. A small in-process cache (`_xp_cache`) avoids
re-scanning on every request.

If the audit log changes (`audit.append`), call `invalidate(bullpen)`
so the next read recomputes.

Level curve: triangular progression — Lvl N requires ~250·N(N+1)/2
cumulative XP. Levels are computed against the SUM of money_xp +
clout_xp (vanity rank), but eligibility/allocation always queries
money_xp directly.

  Lvl 2:    750 XP
  Lvl 5:  3,750 XP
  Lvl 10: 13,750 XP
  Lvl 20: 52,500 XP
  Lvl 50: 318,750 XP  (soft cap; past 50 = "prestige")
"""
from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Literal, Optional

from audit import iter_all as audit_iter_all


Bucket = Literal["money", "clout", "none"]


# ── XP rules table — single source of truth ──────────────────────────────
#
# Each rule is matched against (event.kind, optional payload predicate).
# Order matters only for events that match multiple rules — we apply ALL
# matching rules (an event can earn multiple XP types).
#
# `bucket` is REQUIRED on every rule. The validator at module import
# refuses to load a rule that's missing it or has an invalid value —
# this is the structural guarantee that no future contributor
# accidentally introduces a third path.

def _xp_close_won(payload: dict) -> int:
    amount = float(payload.get("amount") or 0)
    return int(100 + amount / 100)   # $15K deal = 250 XP, $50K = 600 XP

def _xp_stage_moved(payload: dict) -> int:
    delta = float(payload.get("prob_delta") or 0)
    return int(max(0, round(delta * 100)))   # +30% prob = 30 XP

def _xp_achievement_unlocked(payload: dict) -> int:
    rarity = payload.get("rarity") or "common"
    return {"common": 50, "rare": 200, "epic": 750, "legendary": 2000}.get(rarity, 50)


RULES: list[dict] = [
    # ── Practice / drills ──
    # Practice attempts are CLOUT — volume reward, no proof of outcome.
    {"kind": "drill_attempt", "bucket": "clout", "xp": 10,
     "reason": "Practice drill completed"},
    # Drill passed at certification tier (phase_tier ≥ 3) is MONEY —
    # proof of competence to handle real customers. Lower-tier passes
    # are CLOUT (improvement, but not certification).
    {"kind": "drill_passed", "bucket": "money", "xp": 100,
     "reason": "Drill CERTIFIED (cert tier)",
     "bonus": lambda p: 50 * max(0, int(p.get("phase_tier") or 0) - 3),
     "match": lambda p: int(p.get("phase_tier") or 0) >= 3},
    {"kind": "drill_passed", "bucket": "clout", "xp": 50,
     "reason": "Drill passed",
     "bonus": lambda p: 25 * int(p.get("phase_tier") or 0),
     "match": lambda p: int(p.get("phase_tier") or 0) < 3},

    # ── Real calls ──
    # Calls are activity, not outcome. CLOUT.
    # (deal_closed_won is what credits real-customer revenue.)
    {"kind": "call", "bucket": "clout", "xp": 25, "reason": "Real call uploaded",
     "match": lambda p: p.get("call_kind") == "real"},
    {"kind": "call", "bucket": "clout", "xp": 10, "reason": "Practice call uploaded",
     "match": lambda p: p.get("call_kind") == "practice"},
    {"kind": "call", "bucket": "clout", "xp": 5, "reason": "Speaking drill",
     "match": lambda p: p.get("call_kind") == "speaking"},

    # ── Debrief extraction ──
    # Housekeeping. CLOUT.
    {"kind": "debrief_extracted", "bucket": "clout", "xp": 40,
     "reason": "New contact extracted from call"},

    # ── Claims (territory) ──
    # Claiming a prospect is an action, not an outcome. CLOUT.
    {"kind": "claim", "bucket": "clout", "xp": 5,
     "reason": "Prospect claimed"},

    # ── Deal pipeline ──
    # Creating a deal is activity (CLOUT). Moving a real deal forward
    # in prob is an outcome signal against a real customer (MONEY).
    # Closing won is THE outcome (MONEY).
    {"kind": "deal_created", "bucket": "clout", "xp": 20,
     "reason": "Deal created"},
    {"kind": "deal_stage_moved", "bucket": "money", "xp": _xp_stage_moved,
     "reason": "Deal advanced"},
    {"kind": "deal_closed_won", "bucket": "money", "xp": _xp_close_won,
     "reason": "DEAL CLOSED-WON"},

    # ── Legal / signatures ──
    # Signing internal docs = housekeeping (CLOUT). Signing a real
    # pilot contract with a real customer = revenue event (MONEY).
    {"kind": "doc_signed", "bucket": "clout", "xp": 50,
     "reason": "Legal doc signed"},
    # Gate steps used to emit audit events with NO matching rule = 0 XP on
    # the highest-friction part of onboarding. Reward them so clearing the
    # gate feels like leveling up, not filling out a form.
    {"kind": "closer_disclosure_accepted", "bucket": "clout", "xp": 25,
     "reason": "Disclosure reviewed"},
    {"kind": "w9_submitted", "bucket": "clout", "xp": 50,
     "reason": "W-9 on file — cleared to earn"},
    {"kind": "pilot_signed", "bucket": "money", "xp": 500,
     "reason": "PILOT CONTRACT SIGNED"},

    # ── Mentor / teamwork ──
    # Helping a teammate is good behavior but not customer outcome. CLOUT.
    {"kind": "mentor_flag", "bucket": "clout", "xp": 75,
     "reason": "Helped a teammate"},

    # ── Achievement unlocks ──
    # Vanity. CLOUT.
    {"kind": "achievement_unlocked", "bucket": "clout",
     "xp": _xp_achievement_unlocked, "reason": "Achievement"},

    # ── Quest completions ──
    # Vanity / engagement. CLOUT.
    {"kind": "quest_completed", "bucket": "clout",
     "xp": lambda p: int(p.get("xp_reward") or 0),
     "reason": "Quest completed"},

    # ── Follow-up discipline ──
    # Activity (CLOUT). The downstream close credits MONEY.
    {"kind": "followup_done", "bucket": "clout", "xp": 8,
     "reason": "Follow-up done"},

    # ── Activity types beyond raw 'call' ──
    {"kind": "activity_email", "bucket": "clout", "xp": 6,
     "reason": "Email sent"},
    {"kind": "activity_meeting", "bucket": "clout", "xp": 40,
     "reason": "Meeting logged"},
    {"kind": "activity_note", "bucket": "clout", "xp": 2,
     "reason": "Note added"},
    {"kind": "contact_created", "bucket": "clout", "xp": 10,
     "reason": "New contact added"},

    # ── STUDY / RAG ingestion (Phase B Studio) ─────────────────────────
    # Dropping a source = volume (clout). Cap per-event so dumping a 200-chunk
    # PDF doesn't out-credit a thoughtful targeted ingestion.
    {"kind": "source_ingested", "bucket": "clout", "xp": 5,
     "reason": "Source added to dossier",
     "bonus": lambda p: min(20, int(p.get("chunks") or 0))},
    {"kind": "source_removed", "bucket": "clout", "xp": 0,
     "reason": "Source removed (no XP)"},

    # ── Flashcards / SRS practice ──
    # Each card pass = clout (study volume). Easy rating gets a small bump
    # because the rep self-reports they've internalized it.
    {"kind": "flashcard_passed", "bucket": "clout", "xp": 3,
     "reason": "Flashcard passed",
     "match": lambda p: (p.get("rating") or "good") != "easy"},
    {"kind": "flashcard_passed", "bucket": "clout", "xp": 5,
     "reason": "Flashcard passed (easy)",
     "match": lambda p: (p.get("rating") or "") == "easy"},

    # ── Quiz ──
    # Completing a quiz = clout. A PERFECT score on a cert-tier quiz
    # (corpus has 3+ sources for the buyer, proving real study material
    # was used) = money. Otherwise still clout.
    {"kind": "quiz_completed", "bucket": "clout", "xp": 20,
     "reason": "Pop quiz completed",
     "match": lambda p: not (p.get("perfect") and int(p.get("source_count") or 0) >= 3)},
    {"kind": "quiz_completed", "bucket": "money", "xp": 100,
     "reason": "PERFECT quiz on cert-tier dossier (3+ sources)",
     "match": lambda p: p.get("perfect") and int(p.get("source_count") or 0) >= 3},

    # ── Briefing / one-sheeter / account map / data table — viewing ──
    {"kind": "briefing_read", "bucket": "clout", "xp": 8,
     "reason": "Briefing read"},
    {"kind": "one_sheeter_viewed", "bucket": "clout", "xp": 6,
     "reason": "One-sheeter viewed"},
    {"kind": "account_map_viewed", "bucket": "clout", "xp": 6,
     "reason": "Account map viewed"},
    {"kind": "data_table_viewed", "bucket": "clout", "xp": 4,
     "reason": "Data table viewed"},

    # ── Research chat ──
    # Asking is clout (effort + volume). A question that LANDS — i.e., the
    # closer closes the same buyer's deal within 7 days of asking — credits
    # money via outcome attribution (research_question_landed event fired
    # by the deal-close watcher, NOT directly by the user).
    {"kind": "research_question_asked", "bucket": "clout", "xp": 4,
     "reason": "Pre-call research question asked"},
    {"kind": "research_question_landed", "bucket": "money", "xp": 50,
     "reason": "Research landed (closed within 7 days)"},

    # ── Marketing (outcome-attributed) ─────────────────────────────────
    # Publishing a marketing post: clout (you did the work).
    # A click on your tracked link: clout (someone saw it).
    # A SIGNUP attributed to your post: money (real outcome — someone
    # entered the funnel because of you).
    #
    # CRITICAL — these are MARKETING (product / outreach), not RECRUITMENT
    # (closer-to-closer invites). Marketing posts about the PRODUCT / the
    # PROSPECT-FACING brand earn XP. Posts about "join my bullpen to earn
    # commission" earn ZERO and would be flagged.
    {"kind": "marketing_post_published", "bucket": "clout", "xp": 10,
     "reason": "Marketing post published"},
    {"kind": "marketing_post_clicked", "bucket": "clout", "xp": 2,
     "reason": "Marketing post got a click",
     "bonus": lambda p: 0},  # capped per event; tracker can rate-limit
    {"kind": "marketing_lead_signed", "bucket": "money", "xp": 200,
     "reason": "Marketing-attributed signup"},
    {"kind": "marketing_deal_closed", "bucket": "money", "xp": 500,
     "reason": "Marketing-attributed deal closed"},

    # ── Follow-up cadence (Phase C) ───────────────────────────────────
    # Cadence = the deal-stage-triggered touch sequence. Discipline credits
    # clout; the underlying close still credits money via deal_closed_won.
    {"kind": "followup_scheduled", "bucket": "clout", "xp": 2,
     "reason": "Follow-up scheduled"},
    {"kind": "followup_executed", "bucket": "clout", "xp": 8,
     "reason": "Follow-up executed"},
    {"kind": "cadence_completed", "bucket": "clout", "xp": 30,
     "reason": "Cadence completed (all steps)"},

    # ── RECRUITMENT — explicitly NONE ──────────────────────────────────
    # Inviting a closer or operator credits ZERO XP of either kind. The
    # event is still audit-logged for attribution; the audit log shows
    # "Jordan invited Ramos" without awarding Jordan anything earnable.
    # This is the structural guarantee against the Koscot pyramid shape.
    {"kind": "invite_closer", "bucket": "none", "xp": 0,
     "reason": "Closer invited (no XP — recruitment doesn't pay)"},
    {"kind": "invite_operator", "bucket": "none", "xp": 0,
     "reason": "Operator invited (no XP — recruitment doesn't pay)"},
    {"kind": "closer_joined", "bucket": "none", "xp": 0,
     "reason": "Closer accepted invite (no XP — recruitment doesn't pay)"},
    {"kind": "operator_joined", "bucket": "none", "xp": 0,
     "reason": "Operator accepted invite (no XP — recruitment doesn't pay)"},
]


# ── Bucket validation at module load ─────────────────────────────────────
# Refuses to import the module if any rule is missing a bucket or has an
# invalid value. This is the structural guarantee.

_VALID_BUCKETS: tuple[str, ...] = ("money", "clout", "none")

def _validate_rules() -> None:
    for i, r in enumerate(RULES):
        b = r.get("bucket")
        if b not in _VALID_BUCKETS:
            raise RuntimeError(
                f"server/xp.py RULES[{i}] (kind={r.get('kind')!r}) "
                f"has invalid bucket {b!r}. "
                f"Must be one of {_VALID_BUCKETS}. "
                f"This is the two-ledger firewall — no rule may bypass it."
            )

_validate_rules()


# ── Level curve ──────────────────────────────────────────────────────────

def xp_for_level(n: int) -> int:
    """Cumulative XP required to reach level n. Lvl 1 = 0 XP."""
    if n <= 1:
        return 0
    return 250 * n * (n - 1) // 2   # triangular: 0, 250, 750, 1500, 2500...


def level_for_xp(xp: int) -> int:
    """Given total XP, return the highest level reached. Soft cap at Lvl 50."""
    if xp <= 0:
        return 1
    n = int((1 + math.sqrt(1 + 8 * xp / 250)) / 2)
    return min(max(n, 1), 50)


def progress_to_next(xp: int) -> dict:
    """Returns {level, xp, xp_into_level, xp_for_next, pct}."""
    lvl = level_for_xp(xp)
    cur_base = xp_for_level(lvl)
    next_base = xp_for_level(lvl + 1)
    span = max(1, next_base - cur_base)
    into = xp - cur_base
    return {
        "level": lvl,
        "xp": xp,
        "xp_into_level": into,
        "xp_for_next_level": span,
        "pct_to_next": round(min(1.0, into / span), 3),
    }


# ── Rule matching ────────────────────────────────────────────────────────

def _matches(rule: dict, event: dict) -> bool:
    if rule.get("kind") and event.get("kind") != rule["kind"]:
        return False
    pred = rule.get("match")
    if callable(pred):
        try:
            return bool(pred(event.get("payload") or {}))
        except Exception:
            return False
    return True


def _xp_from_rule(rule: dict, event: dict) -> int:
    payload = event.get("payload") or {}
    base = rule["xp"]
    val = base(payload) if callable(base) else int(base)
    bonus = rule.get("bonus")
    if callable(bonus):
        try: val += int(bonus(payload) or 0)
        except Exception: pass
    return max(0, val)


def xp_for_event(event: dict) -> list[dict]:
    """Return the list of {xp, reason, bucket} rule hits for one event."""
    hits = []
    for r in RULES:
        if _matches(r, event):
            hits.append({
                "xp": _xp_from_rule(r, event),
                "reason": r.get("reason", r["kind"]),
                "bucket": r["bucket"],
            })
    return hits


# ── Per-rep XP projection ────────────────────────────────────────────────

_xp_cache: dict[str, dict] = {}


def invalidate(bullpen: str) -> None:
    _xp_cache.pop(bullpen, None)


def _compute(bullpen: str) -> dict[str, dict]:
    try:
        from parties import squad_xp_bonus
    except Exception:
        def squad_xp_bonus(_b, _r): return 1.0
    bonus_cache: dict[str, float] = {}

    by_rep: dict[str, dict] = {}
    for event in audit_iter_all(bullpen):
        actor = event.get("actor") or "self"
        slot = by_rep.setdefault(actor, {
            "money_xp": 0,
            "clout_xp": 0,
            "ledger": [],
        })
        if actor not in bonus_cache:
            try: bonus_cache[actor] = squad_xp_bonus(bullpen, actor)
            except Exception: bonus_cache[actor] = 1.0
        mult = bonus_cache[actor]
        for hit in xp_for_event(event):
            if hit["bucket"] == "none":
                # Recorded for attribution, awards no XP.
                slot["ledger"].append({
                    "ts": event.get("ts"),
                    "kind": event.get("kind"),
                    "target_id": event.get("target_id"),
                    "xp": 0,
                    "bucket": "none",
                    "reason": hit["reason"],
                })
                continue
            # Squad multiplier applies only to money-XP — clout shouldn't
            # bonus-stack from squad membership (that creates a recruit-
            # adjacent incentive).
            scored = int(round(hit["xp"] * mult)) if hit["bucket"] == "money" else int(hit["xp"])
            if hit["bucket"] == "money":
                slot["money_xp"] += scored
            else:
                slot["clout_xp"] += scored
            slot["ledger"].append({
                "ts": event.get("ts"),
                "kind": event.get("kind"),
                "target_id": event.get("target_id"),
                "xp": scored,
                "bucket": hit["bucket"],
                "reason": hit["reason"] + (
                    f" (squad ×{mult:.2f})"
                    if (mult > 1.0 and hit["bucket"] == "money")
                    else ""
                ),
            })
    return by_rep


# ── Public read API ──────────────────────────────────────────────────────

def get_money_xp(bullpen: str, rep: str) -> int:
    """Money-XP for one rep. THIS is the input the allocation firewall
    uses; clout-XP is forbidden from the firewall."""
    if bullpen not in _xp_cache:
        _xp_cache[bullpen] = _compute(bullpen)
    slot = _xp_cache[bullpen].get(rep)
    return int(slot["money_xp"]) if slot else 0


def get_clout_xp(bullpen: str, rep: str) -> int:
    """Clout-XP for one rep. Use ONLY for vanity surfaces (leaderboards,
    rank, cosmetics). MUST NOT be passed to allocation/priority/
    commission-tier logic. The firewall in team.py / gates.py refuses
    to accept it."""
    if bullpen not in _xp_cache:
        _xp_cache[bullpen] = _compute(bullpen)
    slot = _xp_cache[bullpen].get(rep)
    return int(slot["clout_xp"]) if slot else 0


def get(bullpen: str, rep: Optional[str] = None) -> dict:
    """Return XP totals + level for one rep (or all reps if rep is None).

    Both buckets are surfaced. Callers that need allocation/commission
    decisions MUST use get_money_xp() — calling get()['xp'] (combined)
    for those decisions defeats the firewall.
    """
    if bullpen not in _xp_cache:
        _xp_cache[bullpen] = _compute(bullpen)
    by_rep = _xp_cache[bullpen]

    def _rep_summary(r: str, slot: dict) -> dict:
        combined = slot["money_xp"] + slot["clout_xp"]
        prog = progress_to_next(combined)
        return {
            "rep": r,
            "money_xp": slot["money_xp"],
            "clout_xp": slot["clout_xp"],
            "xp": combined,
            **{k: v for k, v in prog.items() if k != "xp"},
            "events": len(slot["ledger"]),
        }

    if rep is None:
        out = [_rep_summary(r, s) for r, s in by_rep.items()]
        # Vanity leaderboard sorts by combined XP (rank-ish).
        out.sort(key=lambda x: -x["xp"])
        return {"reps": out}

    slot = by_rep.get(rep, {"money_xp": 0, "clout_xp": 0, "ledger": []})
    summary = _rep_summary(rep, slot)
    summary["ledger"] = list(reversed(slot["ledger"]))[:50]
    return summary


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 server/xp.py <bullpen> [rep]")
        sys.exit(0)
    bullpen = sys.argv[1]
    rep = sys.argv[2] if len(sys.argv) > 2 else None
    r = get(bullpen, rep)
    if rep:
        print(f"  {r['rep']:12} Lvl {r['level']:3}  "
              f"$={r['money_xp']:>6}  clout={r['clout_xp']:>6}  "
              f"({r['xp_into_level']}/{r['xp_for_next_level']} to Lvl {r['level']+1})")
        for e in r["ledger"][:10]:
            tag = e.get("bucket", "?")[0].upper()  # M / C / N
            print(f"    [{tag}] +{e['xp']:>4} XP  {e['kind']:20}  {e['reason']}")
    else:
        for x in r["reps"]:
            print(f"  {x['rep']:12} Lvl {x['level']:3}  "
                  f"$={x['money_xp']:>6}  clout={x['clout_xp']:>6}  "
                  f"events={x['events']}")
