"""Live-work eligibility gate + prospect-claim allocation firewall.

This module is the structural enforcement of Phase 0.5's two big
guarantees:

  1. A closer cannot be assigned a real prospect (live work) until they
     have:
       (a) signed Closer Agreement on file with both-party hash
       (b) W-9 on file
       (c) drill certification cleared (proof of competence)
       (d) jurisdiction compliance check passed
       (e) accepted the Closer Disclosure

  2. The prospect-claim priority function accepts ONLY money-XP,
     drill-cert score, and historical close-rate. The function
     signature does not accept clout-XP — passing it is a TypeError.
     This is the allocation firewall the other AI flagged as the leak
     path Koscot would catch.

Both guarantees are enforced HERE, not in the UI. The UI may surface
the same checks for ergonomics, but the server-side gate is the truth.

═══════════════════════════════════════════════════════════════════════
The allocation firewall in code
═══════════════════════════════════════════════════════════════════════

`prospect_claim_priority` accepts a precisely-typed Earning Inputs
record. There is no field on that record for clout-XP. A future
contributor cannot "just add clout-XP" to influence priority without
changing the dataclass definition — and that change would be caught in
code review as a Phase 0.5 firewall regression.

The dataclass is intentionally constructed where money-XP is read, not
passed across many call sites — so a programmer who wants to introduce
"priority by leaderboard rank" has to either (a) plumb a new path
through the dataclass (visible diff) or (b) bypass this module
entirely (visible diff). Either way, the leak is not subtle.
"""
from __future__ import annotations
import dataclasses
import datetime
from pathlib import Path
from typing import Optional

from audit import append as audit_append

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"


# ── Live-work gate ───────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class GateCheck:
    """Result of can_claim_live_prospect(). A single bool ("ok") plus a
    list of which sub-checks failed, so the UI can show the closer
    exactly what's missing."""
    ok: bool
    missing: list[str]
    details: dict


def can_claim_live_prospect(bullpen: str, closer: str, prospect_slug: Optional[str] = None) -> GateCheck:
    """The single source of truth for "can this closer claim a real
    prospect right now."

    Returns ok=False with a `missing` list naming each unsatisfied
    requirement. The caller (team.claim, server.py route, etc.) MUST
    treat a False ok as a refusal and surface `missing` to the closer.

    Side-effect-free; safe to call repeatedly to power UI status.
    """
    missing: list[str] = []
    details: dict = {}

    # 1. Operator entity is set up
    try:
        from entity import is_setup as entity_is_setup, get_entity
        if not entity_is_setup(bullpen):
            missing.append("operator_entity_not_set_up")
            details["operator_entity"] = "Operator must complete entity setup before any closer can claim live work."
        else:
            details["operator_entity"] = get_entity(bullpen).get("legal_name")
    except Exception as e:
        missing.append("entity_check_failed")
        details["operator_entity_error"] = str(e)

    # 2. Closer has signed the Closer Agreement
    try:
        from legal import get_member_signatures
        sigs = get_member_signatures(bullpen, closer) or {}
        ca = sigs.get("closer-agreement")
        if not ca:
            missing.append("closer_agreement_not_signed")
        elif not ca.get("current"):
            missing.append("closer_agreement_out_of_date")
        details["closer_agreement"] = ca
    except Exception:
        # legal.get_member_signatures may not exist in older builds — be
        # defensive and treat as missing.
        missing.append("closer_agreement_not_signed")

    # 3. W-9 on file
    try:
        from disclosures import has_w9
        if not has_w9(bullpen, closer):
            missing.append("w9_not_on_file")
    except Exception:
        missing.append("w9_not_on_file")

    # 4. Closer Disclosure accepted
    try:
        from disclosures import has_accepted_closer_disclosure
        if not has_accepted_closer_disclosure(bullpen, closer):
            missing.append("closer_disclosure_not_accepted")
    except Exception:
        missing.append("closer_disclosure_not_accepted")

    # 5. Drill certification cleared
    try:
        from xp import get_money_xp
        # Phase 0.5 minimum: any positive money-XP from drill
        # certifications (drill_passed at phase_tier ≥ 3). A future
        # tightening can require a specific cert tier per role.
        mxp = get_money_xp(bullpen, closer)
        details["money_xp"] = mxp
        if mxp < 100:   # one cert-tier drill_passed = 100 base
            missing.append("drill_certification_not_cleared")
    except Exception:
        missing.append("drill_certification_check_failed")

    # 6. Jurisdiction compliance (closer + operator location compatible)
    try:
        from classification import jurisdiction_ok_for_closer
        ok_jur, why = jurisdiction_ok_for_closer(bullpen, closer)
        if not ok_jur:
            missing.append("jurisdiction_check_failed")
            details["jurisdiction_reason"] = why
    except Exception:
        # If the classification module isn't loaded, FAIL CLOSED — never
        # allow live work without a jurisdiction check.
        missing.append("jurisdiction_check_unavailable")

    # 7. DNC scrub on the specific prospect (only when a prospect is
    #    named — the gate is also used for "can this closer claim ANY
    #    real prospect" checks where prospect_slug is None).
    if prospect_slug:
        try:
            from dnc import is_clear_to_dial
            ok_dnc, why = is_clear_to_dial(bullpen, prospect_slug)
            if not ok_dnc:
                missing.append("dnc_scrub_failed")
                details["dnc_reason"] = why
        except Exception:
            missing.append("dnc_check_unavailable")

    return GateCheck(ok=(len(missing) == 0), missing=missing, details=details)


def assert_can_claim_live(bullpen: str, closer: str, prospect_slug: Optional[str] = None) -> None:
    """Convenience wrapper that raises if the gate fails. Records the
    refusal in the audit log so we have evidence the firewall held."""
    g = can_claim_live_prospect(bullpen, closer, prospect_slug)
    if g.ok:
        return
    audit_append(bullpen, kind="gate_refused", actor=closer, payload={
        "prospect": prospect_slug,
        "missing": g.missing,
    })
    raise GateError(missing=g.missing, details=g.details)


class GateError(Exception):
    def __init__(self, missing: list[str], details: dict):
        self.missing = missing
        self.details = details
        super().__init__(f"live-work gate refused: missing={missing}")


# ── Allocation firewall ──────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class EarningInputs:
    """The ONLY inputs the prospect-claim priority function accepts.

    There is no `clout_xp` field here. There is no `invite_count`,
    `post_count`, `rank`, or `social_score`. Adding any of those would
    require modifying this dataclass — a visible code-review event.

    If you find yourself wanting to add a field to make priority
    influenced by social/recruitment behavior: DON'T. That's the
    Koscot leak the firewall exists to prevent. The leaderboard is a
    vanity surface, not an allocation surface.

    Allowed inputs:
        money_xp:            cumulative money-XP (closed deals + cert drills)
        drill_cert_score:    proof-of-competence summary (0.0 - 1.0)
        close_rate:          historical close rate on real prospects (0.0 - 1.0)
        tenure_days:         how long the closer has been a member of this bullpen
    """
    money_xp: int
    drill_cert_score: float
    close_rate: float
    tenure_days: int


def earning_inputs_for(bullpen: str, closer: str) -> EarningInputs:
    """Build the EarningInputs for a given closer. Pulls only from
    money-XP (xp.py) + cert summary + commissions history. Does NOT
    touch clout-XP, leaderboard rank, or any social signal."""
    money_xp = 0
    try:
        from xp import get_money_xp
        money_xp = get_money_xp(bullpen, closer)
    except Exception:
        pass

    # Drill cert score: ratio of cert-tier passes to attempts. Pulls
    # from the audit log directly so it can't be inflated by clout
    # activity. Cheap to compute; ok to do per-call for now.
    drill_cert_score = _drill_cert_score(bullpen, closer)
    close_rate = _close_rate(bullpen, closer)
    tenure_days = _tenure_days(bullpen, closer)

    return EarningInputs(
        money_xp=money_xp,
        drill_cert_score=drill_cert_score,
        close_rate=close_rate,
        tenure_days=tenure_days,
    )


def prospect_claim_priority(inputs: EarningInputs) -> float:
    """Priority score for a single closer's claim on a contested
    prospect. Higher = better priority.

    Weights are intentionally simple:
        - money_xp: log-scaled so a 10× difference is ~1 point, not 10×
        - drill_cert_score: 0-1, weighted 2x
        - close_rate: 0-1, weighted 3x (real outcomes weigh most)
        - tenure_days: capped log scale, weighted 0.5x (slight stability bias)

    NB: the function signature is EarningInputs — there is no
    `clout_xp` parameter. If you need to tune priority, tune the
    weights here; do NOT plumb a new social signal in.
    """
    import math
    money_component = math.log10(max(1, inputs.money_xp)) * 1.0
    cert_component = max(0.0, min(1.0, inputs.drill_cert_score)) * 2.0
    close_component = max(0.0, min(1.0, inputs.close_rate)) * 3.0
    tenure_component = math.log10(max(1, inputs.tenure_days)) * 0.5
    return money_component + cert_component + close_component + tenure_component


def rank_claim_candidates(bullpen: str, candidates: list[str]) -> list[tuple[str, float]]:
    """Order candidates by claim priority (highest first). Used when
    multiple closers race for the same prospect, or for round-robin
    assignment of unclaimed leads.

    Returns [(closer, priority_score), ...] sorted desc by score.
    """
    scored = []
    for c in candidates:
        try:
            inputs = earning_inputs_for(bullpen, c)
            scored.append((c, prospect_claim_priority(inputs)))
        except Exception:
            scored.append((c, 0.0))
    scored.sort(key=lambda x: -x[1])
    return scored


# ── Internal helpers ─────────────────────────────────────────────────────

def _drill_cert_score(bullpen: str, closer: str) -> float:
    """Ratio of cert-tier drill passes to attempts. Returns 0.0 if no attempts."""
    try:
        from audit import iter_all
    except Exception:
        return 0.0
    attempts = 0
    cert_passes = 0
    for ev in iter_all(bullpen):
        if ev.get("actor") != closer:
            continue
        k = ev.get("kind")
        p = ev.get("payload") or {}
        if k == "drill_attempt":
            attempts += 1
        elif k == "drill_passed" and int(p.get("phase_tier") or 0) >= 3:
            cert_passes += 1
            attempts += 1
    if attempts == 0:
        return 0.0
    return min(1.0, cert_passes / max(1, attempts))


def _close_rate(bullpen: str, closer: str) -> float:
    """Closed-won / (closed-won + closed-lost). Returns 0.0 if no deals."""
    try:
        from audit import iter_all
    except Exception:
        return 0.0
    won = 0
    lost = 0
    for ev in iter_all(bullpen):
        if ev.get("actor") != closer:
            continue
        k = ev.get("kind")
        if k == "deal_closed_won":
            won += 1
        elif k == "deal_closed_lost":
            lost += 1
    total = won + lost
    if total == 0:
        return 0.0
    return won / total


def _tenure_days(bullpen: str, closer: str) -> int:
    """Days since first event by this closer."""
    try:
        from audit import iter_all
    except Exception:
        return 0
    earliest = None
    for ev in iter_all(bullpen):
        if ev.get("actor") != closer:
            continue
        ts = ev.get("ts")
        if not ts:
            continue
        if earliest is None or ts < earliest:
            earliest = ts
    if not earliest:
        return 0
    try:
        dt = datetime.datetime.fromisoformat(earliest)
        return max(0, (datetime.datetime.now() - dt).days)
    except Exception:
        return 0
