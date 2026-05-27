"""IRS 20-factor + state-aware worker-classification coach.

Purpose: catch the obvious-employee pattern before an operator papers a
1099 they shouldn't. NOT a substitute for legal advice — explicitly so.

The operator answers a small questionnaire when they set up commission
terms; this module scores it. If the score crosses an "employee" line,
the coach refuses to render the 1099 Closer Agreement and shows the
operator which factors flipped.

State overlays:
  * CA — AB5 / ABC test (strictest)
  * NJ — 75-IIIA ABC test
  * NY, IL, LA — Freelance Isn't Free Act (different angle: it requires
    written contract + payment timeline for 1099 work, doesn't change
    classification per se)

The questionnaire stays small (~12 questions). The IRS publishes 20
factors but they cluster into three categories — Behavioral Control,
Financial Control, Type of Relationship. We ask 4 in each cluster.

Storage:
  bullpens/<slug>/classification/<closer>.json   — per-closer answer set
  bullpens/<slug>/classification/operator.json   — operator's default answers
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

from audit import append as audit_append

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"


def _class_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "classification"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# ── The questionnaire ────────────────────────────────────────────────────
#
# Each question's answer is keyed to either CONTRACTOR-LEANING (+1) or
# EMPLOYEE-LEANING (-1). Some questions are veto-style: a single answer
# can flip the verdict regardless of total score (the AB5 (B) factor in
# particular).
#
# `id`           — stable key, do not rename
# `cluster`      — irs cluster: "behavioral" | "financial" | "relationship"
# `prompt`       — plain-English question for the operator
# `contractor`   — text shown next to "yes" if "yes" leans contractor
# `employee`     — text shown next to "yes" if "yes" leans employee
# `score_yes`    — +1 (contractor) | -1 (employee)
# `veto`         — None | "ab5_b" | other named veto

QUESTIONS: list[dict] = [
    # ── Behavioral control ────────────────────────────────────────────
    {
        "id": "set_own_hours",
        "cluster": "behavioral",
        "prompt": "Does the closer set their own hours (no required start/end times, no fixed shifts)?",
        "score_yes": 1,
        "veto": None,
    },
    {
        "id": "required_training",
        "cluster": "behavioral",
        "prompt": "Will you require the closer to attend training sessions you create (beyond optional drills)?",
        "score_yes": -1,
        "veto": None,
    },
    {
        "id": "manages_other_clients",
        "cluster": "behavioral",
        "prompt": "Is the closer free to work for other operators / other businesses at the same time?",
        "score_yes": 1,
        "veto": None,
    },
    {
        "id": "directed_methods",
        "cluster": "behavioral",
        "prompt": "Will you direct HOW the closer does their work (specific scripts, required call cadence, mandated tools)?",
        "score_yes": -1,
        "veto": None,
    },

    # ── Financial control ─────────────────────────────────────────────
    {
        "id": "own_equipment",
        "cluster": "financial",
        "prompt": "Does the closer supply their own laptop, phone, and workspace?",
        "score_yes": 1,
        "veto": None,
    },
    {
        "id": "commission_only",
        "cluster": "financial",
        "prompt": "Is compensation commission-only (no salary, no hourly wage, no guaranteed minimum)?",
        "score_yes": 1,
        "veto": None,
    },
    {
        "id": "operator_reimburses_expenses",
        "cluster": "financial",
        "prompt": "Will you reimburse the closer for ordinary business expenses (mileage, phone bill, internet)?",
        "score_yes": -1,
        "veto": None,
    },
    {
        "id": "can_realize_profit_or_loss",
        "cluster": "financial",
        "prompt": "Can the closer realize a profit or loss based on their business decisions (e.g. buying their own ad spend)?",
        "score_yes": 1,
        "veto": None,
    },

    # ── Type of relationship ──────────────────────────────────────────
    {
        "id": "written_independent_contractor_agreement",
        "cluster": "relationship",
        "prompt": "Will there be a written agreement explicitly designating the closer as an independent contractor?",
        "score_yes": 1,
        "veto": None,
    },
    {
        "id": "no_employee_benefits",
        "cluster": "relationship",
        "prompt": "Will the closer receive ZERO employee benefits (no PTO, no health insurance, no 401k match)?",
        "score_yes": 1,
        "veto": None,
    },
    {
        "id": "project_based_relationship",
        "cluster": "relationship",
        "prompt": "Is the relationship limited to specific projects or sales engagements (not open-ended indefinite employment)?",
        "score_yes": 1,
        "veto": None,
    },
    {
        "id": "core_business_function",
        "cluster": "relationship",
        "prompt": "Is the closer's work OUTSIDE the operator's usual course of business?",
        "score_yes": 1,
        "veto": "ab5_b",
    },
]


# ── Scoring ──────────────────────────────────────────────────────────────

def score(answers: dict[str, bool], operator_state: Optional[str] = None) -> dict:
    """Score a set of answers. Returns:
        {
            "verdict": "contractor" | "borderline" | "employee",
            "total_score": int,
            "veto_failures": list[str],   # named vetoes that fired
            "by_cluster": {behavioral, financial, relationship: int},
            "warnings": list[str],         # state-specific notes
        }
    """
    by_cluster: dict[str, int] = {"behavioral": 0, "financial": 0, "relationship": 0}
    total = 0
    vetoes: list[str] = []

    for q in QUESTIONS:
        ans = answers.get(q["id"])
        if ans is None:
            continue
        delta = q["score_yes"] if ans else -q["score_yes"]
        total += delta
        by_cluster[q["cluster"]] += delta

        # AB5 (B) veto: if operator is in CA, the work being OUTSIDE the
        # operator's usual course of business is REQUIRED. If
        # core_business_function == False (yes-answer flipped),
        # classification fails in CA regardless of total score.
        if q["veto"] == "ab5_b" and (operator_state or "").upper() == "CA" and not ans:
            vetoes.append("ab5_b_in_california")

    state = (operator_state or "").upper()
    warnings: list[str] = []

    if state == "CA":
        warnings.append(
            "California uses the ABC test (AB5). A worker is presumed employee "
            "unless (A) free from control, (B) work is outside the operator's "
            "usual business, AND (C) independently established. (B) is the "
            "hardest to satisfy for a sales closer dialing for the operator's "
            "own product."
        )
    elif state == "NJ":
        warnings.append(
            "New Jersey uses a similar ABC test under N.J.S.A. 43:21-19(i)(6). "
            "Confirm the closer is genuinely engaged in an independent trade."
        )
    elif state in {"NY", "IL", "LA"}:
        warnings.append(
            f"{state} has a Freelance Isn't Free Act (or equivalent). 1099 work "
            f">$800 in 120 days requires a written contract specifying "
            "payment timeline. The Closer Agreement template covers this."
        )

    # Verdict
    if vetoes:
        verdict = "employee"
    elif total >= 6:
        verdict = "contractor"
    elif total >= 2:
        verdict = "borderline"
    else:
        verdict = "employee"

    return {
        "verdict": verdict,
        "total_score": total,
        "veto_failures": vetoes,
        "by_cluster": by_cluster,
        "warnings": warnings,
    }


def can_render_1099(answers: dict[str, bool], operator_state: Optional[str] = None) -> tuple[bool, dict]:
    """Returns (allowed, score_result). The Closer Agreement renderer
    MUST call this and refuse to render if allowed=False."""
    result = score(answers, operator_state)
    return (result["verdict"] in ("contractor", "borderline")
            and not result["veto_failures"]), result


# ── Persist + retrieve ───────────────────────────────────────────────────

def save_answers(
    bullpen: str,
    *,
    answers: dict[str, bool],
    operator_state: Optional[str] = None,
    closer: Optional[str] = None,
    actor: str = "operator",
) -> dict:
    """Save a classification answer set. If `closer` is None, this is
    the operator's default for the whole bullpen.
    """
    result = score(answers, operator_state)
    record = {
        "answers": answers,
        "operator_state": operator_state,
        "score": result,
        "saved_at": _now(),
        "saved_by": actor,
    }
    if closer:
        p = _class_dir(bullpen) / f"{closer}.json"
    else:
        p = _class_dir(bullpen) / "operator.json"
    p.write_text(json.dumps(record, indent=2) + "\n")

    audit_append(bullpen, kind="classification_saved", actor=actor, payload={
        "closer": closer,
        "verdict": result["verdict"],
        "veto_failures": result["veto_failures"],
    })

    return record


def get_answers(bullpen: str, closer: Optional[str] = None) -> Optional[dict]:
    if closer:
        p = _class_dir(bullpen) / f"{closer}.json"
    else:
        p = _class_dir(bullpen) / "operator.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


# ── Gate integration ─────────────────────────────────────────────────────

def jurisdiction_ok_for_closer(bullpen: str, closer: str) -> tuple[bool, Optional[str]]:
    """Check whether the bullpen's classification setup permits this
    closer to do live work.

    Called by `gates.can_claim_live_prospect`. Returns (ok, reason).

    Phase 0.5 logic: the operator's saved answers must score contractor
    (not borderline, not employee). If no answers are saved, fail closed.
    """
    record = get_answers(bullpen, closer) or get_answers(bullpen, None)
    if not record:
        return False, "classification questionnaire not completed"

    verdict = (record.get("score") or {}).get("verdict")
    veto_failures = (record.get("score") or {}).get("veto_failures") or []

    if veto_failures:
        return False, f"classification veto fired: {', '.join(veto_failures)}"

    if verdict == "contractor":
        return True, None

    if verdict == "borderline":
        # Phase 0.5: borderline blocks live work. Operators can revisit
        # the questionnaire or consult counsel.
        return False, "classification is borderline — review the questionnaire or consult counsel"

    return False, "classification is employee-leaning — cannot render a 1099 Closer Agreement"
