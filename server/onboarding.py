"""Onboarding — minimal per-rep state for the welcome wizard.

A rep is onboarded once they've finished all REQUIRED_STEPS. Until
then, the welcome wizard surfaces what's missing.

Stored at bullpens/<slug>/onboarding/<rep>.json:
  {
    "rep": "...",
    "started_at": "iso",
    "completed_at": "iso" | null,
    "steps_done": ["identity", "briefing", "agreement"]
  }
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

from audit import append as audit_append

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"

REQUIRED_STEPS = ["identity", "briefing", "agreement"]


def _dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "onboarding"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(bullpen: str, rep: str) -> Path:
    return _dir(bullpen) / f"{rep}.json"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _infer_completed_steps(bullpen: str, rep: str) -> list[str]:
    """Backfill: if a rep already has the artifact of a step (display_name
    + avatar set, signed referral agreement, etc.), credit the step.
    Lets pre-existing reps + founders skip the banner."""
    done: list[str] = []
    try:
        from bullpens import get_member, get_bullpen
        member = get_member(bullpen, rep) or {}
        cfg = get_bullpen(bullpen) or {}
        # identity = has display_name + avatar (or is the founder)
        if (member.get("display_name") and member.get("avatar")) \
                or cfg.get("founder_rep") == rep:
            done.append("identity")
        # agreement = has a signed_doc on referral-agreement
        signed = member.get("signed_docs") or []
        if any(((d.get("doc") if isinstance(d, dict) else d) == "referral-agreement")
               for d in signed):
            done.append("agreement")
        # briefing is hard to detect from state — but if the rep is the
        # founder, they wrote the briefing.
        if cfg.get("founder_rep") == rep:
            done.append("briefing")
    except Exception:
        pass
    return done


def get_state(bullpen: str, rep: str) -> dict:
    """Return the rep's onboarding state. Initializes a fresh record if
    none exists — never raises."""
    p = _path(bullpen, rep)
    if not p.exists():
        # Synthesize an initial record from any existing artifacts so
        # pre-existing reps don't get nagged into re-doing onboarding.
        inferred = _infer_completed_steps(bullpen, rep)
        rec = {"rep": rep, "started_at": _now(), "completed_at": None,
               "steps_done": list(inferred)}
        if inferred:
            # Persist so audit doesn't re-fire on every page load
            try: p.write_text(json.dumps(rec, indent=2) + "\n")
            except Exception: pass
    else:
        try:
            rec = json.loads(p.read_text())
        except Exception:
            rec = {"rep": rep, "started_at": _now(), "completed_at": None,
                   "steps_done": []}
        # If the user has since picked up artifacts that satisfy steps,
        # merge them in (without re-emitting audit events).
        inferred = _infer_completed_steps(bullpen, rep)
        existing = set(rec.get("steps_done") or [])
        merged = list(existing | set(inferred))
        if set(merged) != existing:
            rec["steps_done"] = merged
            try: p.write_text(json.dumps(rec, indent=2) + "\n")
            except Exception: pass

    rec["steps_required"] = list(REQUIRED_STEPS)
    rec["is_complete"] = all(s in (rec.get("steps_done") or [])
                             for s in REQUIRED_STEPS)
    if rec["is_complete"] and not rec.get("completed_at"):
        rec["completed_at"] = _now()
        try: p.write_text(json.dumps(rec, indent=2) + "\n")
        except Exception: pass
    if rec["is_complete"]:
        rec["next_step"] = None
    else:
        rec["next_step"] = next(
            (s for s in REQUIRED_STEPS if s not in (rec.get("steps_done") or [])),
            None)
    return rec


def mark_step_done(bullpen: str, rep: str, step: str) -> dict:
    if step not in REQUIRED_STEPS:
        raise ValueError("unknown_step")
    rec = get_state(bullpen, rep)
    if step in (rec.get("steps_done") or []):
        return rec
    rec.setdefault("steps_done", []).append(step)
    if not rec.get("started_at"):
        rec["started_at"] = _now()
    # Recompute completion
    all_done = all(s in rec["steps_done"] for s in REQUIRED_STEPS)
    if all_done:
        rec["completed_at"] = _now()
    _path(bullpen, rep).write_text(json.dumps(rec, indent=2) + "\n")
    audit_append(bullpen, rep, "onboarding_step_done",
                 target_type="onboarding", target_id=rep,
                 payload={"step": step,
                          "remaining": [s for s in REQUIRED_STEPS
                                         if s not in rec["steps_done"]]})
    if all_done:
        audit_append(bullpen, rep, "onboarding_complete",
                     target_type="onboarding", target_id=rep,
                     payload={"steps_done": rec["steps_done"]})
    return get_state(bullpen, rep)


def is_complete(bullpen: str, rep: str) -> bool:
    return get_state(bullpen, rep).get("is_complete", False)
