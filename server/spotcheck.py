"""Spot checks — surprise drills against a TCS.

An NCO in the Army can walk up to any soldier and say "show me how you'd
treat a tension pneumothorax right now." Same here: the founder (or any
mentor-class rep) fires a spot check at a teammate on a specific TCS.

Lifecycle:
  open       — rep has been pinged, hasn't responded
  responded  — rep submitted their answer, awaiting grade
  graded     — checker (or auto-grader) marked GO|NO_GO; logged to the
               qualifications ledger via tcs.record_attempt

Storage:
  bullpens/<slug>/spot_checks/<id>.json
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

from audit import append as audit_append
import tcs as _tcs

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"


def _dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "spot_checks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(bullpen: str, sc_id: str) -> Path:
    return _dir(bullpen) / f"{sc_id}.json"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def fire(bullpen: str, checker_rep: str, target_rep: str, tcs_id: str,
         seconds: Optional[int] = None,
         prompt_override: Optional[str] = None) -> dict:
    """Fire a spot check from `checker_rep` at `target_rep` on TCS `tcs_id`."""
    tcs = _tcs.get(bullpen, tcs_id)
    if not tcs:
        raise ValueError("tcs_not_found")
    if checker_rep == target_rep and prompt_override is None:
        # Self-drill is allowed but not auto-rewarded as heavily — see grade.
        pass

    now = datetime.datetime.now()
    sc_id = f"sc-{now.strftime('%Y%m%d-%H%M%S-%f')}"
    rec = {
        "id": sc_id,
        "bullpen": bullpen,
        "tcs_id": tcs_id,
        "tcs_name": tcs.get("name"),
        "phase_tier": tcs.get("phase_tier"),
        "checker": checker_rep,
        "target": target_rep,
        "prompt": prompt_override or tcs.get("spot_check_prompt")
                  or f"Demonstrate {tcs.get('name')} as if the prospect is live on the phone.",
        "seconds": int(seconds or tcs.get("spot_check_seconds") or 90),
        "fired_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + datetime.timedelta(minutes=15)).isoformat(timespec="seconds"),
        "status": "open",
        "responded_at": None, "response": None,
        "graded_at": None, "graded_by": None,
        "result": None, "score": None, "feedback": None,
        "self_drill": (checker_rep == target_rep),
    }
    _path(bullpen, sc_id).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    audit_append(bullpen, checker_rep, "spotcheck_fired",
                 target_type="spotcheck", target_id=sc_id,
                 payload={"target": target_rep, "tcs_id": tcs_id,
                          "tcs_name": tcs.get("name"),
                          "self_drill": rec["self_drill"]})
    return rec


def respond(bullpen: str, sc_id: str, rep: str, response: str) -> dict:
    rec = get(bullpen, sc_id)
    if not rec: raise ValueError("spotcheck_not_found")
    if rec["target"] != rep:
        raise ValueError("not_your_spotcheck")
    if rec["status"] != "open":
        raise ValueError(f"spotcheck_already_{rec['status']}")
    if not (response or "").strip():
        raise ValueError("empty_response")

    rec["response"] = response.strip()[:4000]
    rec["responded_at"] = _now()
    rec["status"] = "responded"
    _path(bullpen, sc_id).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    audit_append(bullpen, rep, "spotcheck_responded",
                 target_type="spotcheck", target_id=sc_id,
                 payload={"tcs_id": rec["tcs_id"]})

    # Auto-grade unless the checker is a different human (then they grade)
    if rec["self_drill"] or rec["checker"] == "auto":
        _apply_grade(bullpen, rec, grader="auto")
        # Re-read so the API caller sees the final (graded) record
        rec = get(bullpen, sc_id) or rec
    return rec


def grade(bullpen: str, sc_id: str, grader_rep: str,
          result: Optional[str] = None, score: Optional[int] = None,
          feedback: str = "") -> dict:
    """Manual grade by the checker. If result is None, run auto_grade first."""
    rec = get(bullpen, sc_id)
    if not rec: raise ValueError("spotcheck_not_found")
    if rec["status"] not in ("responded", "open"):
        raise ValueError(f"spotcheck_already_{rec['status']}")
    if rec["status"] == "open":
        raise ValueError("response_missing")
    if grader_rep != rec["checker"] and grader_rep != "auto":
        # Allow the founder to override anyone; cheap check by looking at
        # the bullpen.json founder_rep
        try:
            cfg = json.loads((BULLPENS_ROOT / bullpen / "bullpen.json").read_text())
            if cfg.get("founder_rep") != grader_rep:
                raise ValueError("only_checker_or_founder_can_grade")
        except Exception:
            raise ValueError("only_checker_or_founder_can_grade")
    if result and result not in ("GO", "NO_GO"):
        raise ValueError("invalid_result")

    if result is None:
        tcs = _tcs.get(bullpen, rec["tcs_id"])
        if not tcs: raise ValueError("tcs_not_found")
        result, auto_score, auto_fb = _tcs.auto_grade(tcs, rec["response"])
        if score is None: score = auto_score
        if not feedback: feedback = auto_fb

    rec["status"] = "graded"
    rec["graded_at"] = _now()
    rec["graded_by"] = grader_rep
    rec["result"] = result
    rec["score"] = int(score or 0)
    rec["feedback"] = (feedback or "")[:1000]
    _path(bullpen, rec["id"]).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")

    _tcs.record_attempt(bullpen, rec["target"], rec["tcs_id"],
                        result=result, checker=grader_rep,
                        source=("self" if rec["self_drill"]
                                else "spot_check" if grader_rep != "auto"
                                else "spot_check_auto"),
                        response=rec["response"] or "",
                        score=rec["score"],
                        feedback=rec["feedback"] or "")
    return rec


def _apply_grade(bullpen: str, rec: dict, grader: str = "auto") -> dict:
    tcs = _tcs.get(bullpen, rec["tcs_id"])
    if not tcs:
        return rec
    result, score, fb = _tcs.auto_grade(tcs, rec["response"] or "")
    return grade(bullpen, rec["id"], grader_rep=grader,
                 result=result, score=score, feedback=fb)


def get(bullpen: str, sc_id: str) -> Optional[dict]:
    p = _path(bullpen, sc_id)
    if not p.exists(): return None
    try: return json.loads(p.read_text())
    except Exception: return None


def list_for_rep(bullpen: str, rep: str,
                 status: Optional[str] = None,
                 as_role: str = "any") -> list[dict]:
    """as_role = 'target' | 'checker' | 'any'. status optional."""
    out = []
    for f in sorted(_dir(bullpen).glob("*.json"), reverse=True):
        try: rec = json.loads(f.read_text())
        except Exception: continue
        if as_role == "target" and rec.get("target") != rep: continue
        if as_role == "checker" and rec.get("checker") != rep: continue
        if as_role == "any" and rep not in (rec.get("target"), rec.get("checker")): continue
        if status and rec.get("status") != status: continue
        out.append(rec)
    return out


def list_open_for_target(bullpen: str, rep: str) -> list[dict]:
    return list_for_rep(bullpen, rep, status="open", as_role="target")
