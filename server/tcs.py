"""TCS — Task, Conditions, Standards.

Borrowed from Army training-evaluation outlines: every soldier task is
documented as TASK (what you do) + CONDITIONS (what's given/scenario) +
STANDARDS (pass/fail criteria) + PERFORMANCE STEPS (numbered sequence).
A spot check fires the task against a soldier on the spot; pass = GO,
fail = NO-GO, retrain.

We use the same structure for sales plays. Each TCS lives at
bullpens/<slug>/tcs/<id>.json:

  {
    "id", "name", "phase_tier" (1-7 mapping to the Gauntlet),
    "task":        "What you're doing",
    "conditions":  "What you're working with",
    "standards":   "What counts as a win",
    "performance_steps": ["1. …", "2. …", …],
    "auto_grade_keywords": ["audit", "trail", "20 min"],   # OR-of-words
    "auto_grade_min_hits": 3,
    "spot_check_prompt": "What you say to the rep when firing a check",
    "spot_check_seconds": 90,
  }

Per-rep qualifications:
  bullpens/<slug>/qualifications/<rep>.jsonl    — append-only attempt log
    each line: {ts, tcs_id, result: GO|NO_GO, source: spot_check|self|peer,
                checker: <rep_or_founder>, response: <text>, score: int}

is_qualified(rep, tcs_id) = any GO in the last 90 days.
"""
from __future__ import annotations
import datetime
import json
import re
from pathlib import Path
from typing import Optional

from audit import append as audit_append

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"

QUAL_TTL_DAYS = 90


def _tcs_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "tcs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _quals_path(bullpen: str, rep: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "qualifications"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{rep}.jsonl"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# ── TCS CRUD ─────────────────────────────────────────────────────────────

def list_all(bullpen: str) -> list[dict]:
    out = []
    for f in sorted(_tcs_dir(bullpen).glob("*.json")):
        try: out.append(json.loads(f.read_text()))
        except Exception: continue
    out.sort(key=lambda t: (t.get("phase_tier") or 99, t.get("id") or ""))
    return out


def get(bullpen: str, tcs_id: str) -> Optional[dict]:
    p = _tcs_dir(bullpen) / f"{tcs_id}.json"
    if not p.exists(): return None
    try: return json.loads(p.read_text())
    except Exception: return None


def write(bullpen: str, tcs: dict) -> dict:
    if not tcs.get("id"):
        raise ValueError("missing_id")
    tcs.setdefault("created_at", _now())
    tcs["updated_at"] = _now()
    (_tcs_dir(bullpen) / f"{tcs['id']}.json").write_text(
        json.dumps(tcs, indent=2, ensure_ascii=False) + "\n")
    return tcs


# ── Qualifications ledger ───────────────────────────────────────────────

def _read_attempts(bullpen: str, rep: str) -> list[dict]:
    p = _quals_path(bullpen, rep)
    if not p.exists(): return []
    out = []
    for line in p.read_text().splitlines():
        try: out.append(json.loads(line))
        except Exception: continue
    return out


def is_qualified(bullpen: str, rep: str, tcs_id: str) -> Optional[dict]:
    """Returns the most recent GO attempt within QUAL_TTL_DAYS, or None."""
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=QUAL_TTL_DAYS)
              ).isoformat(timespec="seconds")
    for att in reversed(_read_attempts(bullpen, rep)):
        if att.get("tcs_id") != tcs_id:
            continue
        if att.get("result") != "GO":
            continue
        if (att.get("ts") or "") < cutoff:
            return None
        return att
    return None


def attempts_for_rep(bullpen: str, rep: str,
                     tcs_id: Optional[str] = None) -> list[dict]:
    """Newest first."""
    out = _read_attempts(bullpen, rep)
    if tcs_id:
        out = [a for a in out if a.get("tcs_id") == tcs_id]
    out.sort(key=lambda a: a.get("ts", ""), reverse=True)
    return out


def top_pack(bullpen: str, rep: str) -> dict:
    """Per-rep summary: which plays the rep is cleared on, and which need
    retraining."""
    library = list_all(bullpen)
    cleared = []
    not_cleared = []
    for tcs in library:
        q = is_qualified(bullpen, rep, tcs["id"])
        item = {
            "id": tcs["id"], "name": tcs["name"],
            "phase_tier": tcs.get("phase_tier"),
            "qualified": bool(q),
            "qualified_at": q.get("ts") if q else None,
            "qualified_by": q.get("checker") if q else None,
        }
        (cleared if q else not_cleared).append(item)
    pct = round(100 * len(cleared) / max(1, len(library)))
    return {
        "rep": rep, "total": len(library), "cleared_count": len(cleared),
        "pct_cleared": pct,
        "cleared": cleared, "not_cleared": not_cleared,
    }


def record_attempt(bullpen: str, rep: str, tcs_id: str, result: str,
                   checker: str, source: str = "spot_check",
                   response: str = "", score: int = 0,
                   feedback: str = "") -> dict:
    if result not in ("GO", "NO_GO"):
        raise ValueError("invalid_result")
    tcs = get(bullpen, tcs_id)
    if not tcs:
        raise ValueError("tcs_not_found")
    entry = {
        "ts": _now(), "rep": rep, "tcs_id": tcs_id, "tcs_name": tcs.get("name"),
        "result": result, "source": source, "checker": checker,
        "response": (response or "")[:4000],
        "score": int(score), "feedback": (feedback or "")[:1000],
    }
    with _quals_path(bullpen, rep).open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Emit existing drill kinds so xp.py picks them up.
    if result == "GO":
        audit_append(bullpen, rep, "drill_passed",
                     target_type="tcs", target_id=tcs_id,
                     payload={"tcs_name": tcs.get("name"),
                              "phase_tier": tcs.get("phase_tier") or 0,
                              "source": source, "checker": checker,
                              "score": int(score)})
        # Mirror cert-tier passes (phase_tier ≥ 3) into the host-wide
        # closer profile so the drill cert carries to other bullpens.
        try:
            phase_tier = int(tcs.get("phase_tier") or 0)
            if phase_tier >= 3:
                from closer_profiles import email_for_rep, record_cert
                _email = email_for_rep(bullpen, rep)
                if _email:
                    record_cert(_email, "drill_cert_tier3", bullpen=bullpen,
                                tcs=tcs_id, phase_tier=phase_tier, score=int(score))
        except Exception:
            pass
        # Phase D loop extension: cert-tier drill passes ALSO ingest the
        # response transcript into a synthetic "drills" buyer in the
        # bullpen's RAG corpus. The compounding-practice loop: rare,
        # high-signal moments where a closer actually nailed an
        # objection or open feed back into future drill grading + into
        # the "what good looks like" reference material for newer reps.
        # Buyer slug for drill content is `_drill_bank` (underscore
        # prefix prevents collision with real buyers).
        if (tcs.get("phase_tier") or 0) >= 3 and (response or "").strip():
            try:
                from rag import ingest_text as _rag_ingest
                _rag_ingest(
                    bullpen, "_drill_bank",
                    f"# Cert-tier pass · {tcs.get('name', tcs_id)} · {rep}\n"
                    f"_TCS: {tcs_id} · phase_tier {tcs.get('phase_tier')}_\n\n"
                    f"## What the closer said\n\n{response}\n\n"
                    f"## Auto-grade\n\n{feedback or '(no feedback)'}\n",
                    source_name=f"drill-{tcs_id}-{rep}-{_now()}.md",
                    actor=rep,
                )
            except Exception:
                pass
    else:
        audit_append(bullpen, rep, "drill_attempt",
                     target_type="tcs", target_id=tcs_id,
                     payload={"tcs_name": tcs.get("name"),
                              "phase_tier": tcs.get("phase_tier") or 0,
                              "source": source, "checker": checker,
                              "score": int(score)})
    return entry


# ── Auto-grader ──────────────────────────────────────────────────────────
#
# Cheap deterministic grader: count distinct keyword hits in the rep's
# response. result = GO if hits >= tcs.auto_grade_min_hits.
# Founders can always override via /spotcheck/<id>/grade.

_WORD = re.compile(r"[a-z0-9]+")


def auto_grade(tcs: dict, response: str) -> tuple[str, int, str]:
    """Returns (GO|NO_GO, score, feedback).

    Score = % of ALL target beats covered (not just the pass threshold) so a
    bare pass and a great answer don't both read 100 — there's a real ceiling
    to chase. Feedback COACHES without naming the target phrases (no
    answer-key leak; the keywords never reach the client)."""
    text = (response or "").lower()
    keywords = tcs.get("auto_grade_keywords") or []
    hits = set()
    for kw in keywords:
        terms = [t for t in _WORD.findall(kw.lower()) if len(t) > 2]
        if not terms: continue
        if all(t in text for t in terms):
            hits.add(kw)
    threshold = int(tcs.get("auto_grade_min_hits") or 2)
    # Score relative to the pass bar, not the full keyword list: a bare pass
    # (threshold hits) = ~50, hitting 2x the bar = 100. This avoids unfair
    # ceilings on plays whose keyword list holds mutually-exclusive
    # alternatives (e.g. "thursday" OR "tomorrow", "20 seconds" OR "30
    # seconds") that no single good answer could ever all contain.
    score = min(100, int(round(100 * len(hits) / max(1, 2 * threshold))))
    if len(hits) >= threshold:
        if score >= 85:
            tail = "Sharp — you hit nearly every beat."
        elif score >= 60:
            tail = "Solid pass. Tighten it and you're in elite territory."
        else:
            tail = "Passed, but thin — work in more of the buyer's real pain next rep."
        return ("GO", score, f"GO · {score}/100. {tail}")
    return ("NO_GO", score,
            f"NO-GO · {score}/100. Name the buyer's specific pain in their own "
            f"words and make one crisp ask — then run it back.")


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 server/tcs.py <bullpen> [rep]")
        sys.exit(0)
    if len(sys.argv) == 2:
        for t in list_all(sys.argv[1]):
            print(f"  P{t.get('phase_tier','?')}  {t['id']:25} {t['name']}")
    else:
        tp = top_pack(sys.argv[1], sys.argv[2])
        print(f"  {tp['rep']}: {tp['cleared_count']}/{tp['total']} cleared ({tp['pct_cleared']}%)")
        for c in tp["cleared"]:
            print(f"    ✓ {c['id']:25} {c['name']} ({c['qualified_at']})")
        for n in tp["not_cleared"]:
            print(f"    – {n['id']:25} {n['name']}")
