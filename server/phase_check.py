"""Phase-readiness check.

Surfaces whether the platform — and any given bullpen — is ready to
move from Phase 0.5 (alpha, friends-only, awaiting counsel) to Phase 1
(signed-binary distribution to non-friends).

The gates are intentionally narrow: a single missing item blocks
Phase 1. The point isn't to gatekeep; it's to make the readiness
state self-evident so nobody has to remember "what was the last thing
counsel said?"

Two scopes:

  platform_ready()  — platform-level (does COUNSEL_REVIEW.md exist,
                       do all firewall tests pass, etc.) Returns a
                       structured readiness report.

  bullpen_ready()   — one operator's bullpen is ready to invite
                       non-friend operators / non-friend closers. Each
                       operator checks their own bullpen separately;
                       platform readiness is necessary but not
                       sufficient.

Both are read-only; calling them never mutates state.
"""
from __future__ import annotations
import datetime
import subprocess
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent


# ── Platform readiness ───────────────────────────────────────────────────

def platform_ready() -> dict:
    """Aggregate platform-level Phase-1 readiness checks.

    Checks:
      * Counsel-review file present (`docs/legal/COUNSEL_REVIEW.md`)
      * All firewall test files exist
      * Firewall tests pass (best-effort — only if pytest is available)
      * Legal templates exist
      * Server module loads without errors

    Returns:
      {
        "ready": bool,
        "blockers": list[str],
        "checks": {check_name: {"ok": bool, "detail": str}}
      }
    """
    checks: dict[str, dict] = {}

    # 1. Counsel review
    counsel_path = REPO / "docs" / "legal" / "COUNSEL_REVIEW.md"
    counsel_template = REPO / "docs" / "legal" / "COUNSEL_REVIEW.template.md"
    checks["counsel_review_filed"] = {
        "ok": counsel_path.exists(),
        "detail": (
            f"Counsel review at {counsel_path.relative_to(REPO)}"
            if counsel_path.exists()
            else f"Missing. Fill out {counsel_template.relative_to(REPO)} and save as COUNSEL_REVIEW.md."
        ),
    }

    # 2. Required firewall modules exist
    required_modules = [
        "server/xp.py", "server/gates.py", "server/entity.py",
        "server/classification.py", "server/disclosures.py", "server/dnc.py",
        "server/legal.py", "server/payouts.py",
    ]
    missing_modules = [m for m in required_modules if not (REPO / m).exists()]
    checks["firewall_modules_present"] = {
        "ok": not missing_modules,
        "detail": "All present" if not missing_modules else f"Missing: {missing_modules}",
    }

    # 3. Legal templates exist
    required_templates = [
        "closer-agreement.md", "closer-disclosure.md", "operator-tos.md",
        "code-of-conduct.md", "mutual-nda.md", "dnc-acknowledgement.md",
    ]
    tdir = REPO / "templates" / "legal"
    missing_templates = [t for t in required_templates if not (tdir / t).exists()]
    checks["legal_templates_present"] = {
        "ok": not missing_templates,
        "detail": "All present" if not missing_templates else f"Missing: {missing_templates}",
    }

    # 4. Tests pass (best-effort — skips if pytest isn't installed)
    test_dir = REPO / "tests"
    test_files = [
        "test_xp_firewall.py", "test_gates.py",
        "test_classification.py", "test_disclosures.py",
    ]
    missing_tests = [t for t in test_files if not (test_dir / t).exists()]
    if missing_tests:
        checks["firewall_tests_present"] = {
            "ok": False,
            "detail": f"Missing test files: {missing_tests}",
        }
    else:
        checks["firewall_tests_present"] = {"ok": True, "detail": "All present"}
        # Run them if pytest is available
        try:
            r = subprocess.run(
                ["python3", "-m", "pytest", str(test_dir), "-q", "--no-header"],
                cwd=str(REPO), capture_output=True, text=True, timeout=120,
            )
            checks["firewall_tests_pass"] = {
                "ok": r.returncode == 0,
                "detail": r.stdout.strip().split("\n")[-1] if r.stdout else r.stderr.strip()[:200],
            }
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
            checks["firewall_tests_pass"] = {
                "ok": None,
                "detail": f"Could not run tests automatically: {e}",
            }

    # 5. Xp.py bucket validator + bucket coverage
    try:
        import sys
        sys.path.insert(0, str(REPO / "server"))
        import xp
        buckets = {r["bucket"] for r in xp.RULES}
        checks["xp_bucket_validator"] = {
            "ok": buckets == {"money", "clout", "none"},
            "detail": f"Buckets present: {sorted(buckets)}",
        }
    except Exception as e:
        checks["xp_bucket_validator"] = {"ok": False, "detail": f"Could not load xp.py: {e}"}

    # 6. EarningInputs has no clout_xp leak
    try:
        import dataclasses, gates as _gates
        fields = [f.name for f in dataclasses.fields(_gates.EarningInputs)]
        leak = "clout_xp" in fields or any(f in fields for f in
            ("invite_count", "post_count", "rank", "social_score"))
        checks["allocation_firewall_intact"] = {
            "ok": not leak,
            "detail": (
                f"EarningInputs fields: {fields}"
                if not leak
                else f"LEAK: forbidden field in EarningInputs: {fields}"
            ),
        }
    except Exception as e:
        checks["allocation_firewall_intact"] = {"ok": False, "detail": str(e)}

    blockers = [name for name, c in checks.items() if c.get("ok") is False]
    return {
        "ready": not blockers,
        "blockers": blockers,
        "checks": checks,
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


# ── Per-bullpen readiness ────────────────────────────────────────────────

def bullpen_ready(bullpen: str) -> dict:
    """Is a specific bullpen ready to onboard non-friend closers / scale
    beyond 5 closers?

    Checks platform readiness AND bullpen-specific readiness (operator
    entity set up, TOS accepted, classification = contractor, DNC list
    loaded, at least one closer fully gated, operator's own counsel
    reviewed if scaling >5 closers).
    """
    pr = platform_ready()
    checks: dict[str, dict] = {}

    try:
        from entity import is_setup, get_entity
        checks["entity_setup"] = {
            "ok": is_setup(bullpen),
            "detail": (get_entity(bullpen) or {}).get("legal_name") or "Not set up",
        }
    except Exception as e:
        checks["entity_setup"] = {"ok": False, "detail": str(e)}

    try:
        from classification import get_answers
        ans = get_answers(bullpen, None)
        verdict = (ans or {}).get("score", {}).get("verdict")
        checks["classification_contractor"] = {
            "ok": verdict == "contractor",
            "detail": f"Verdict: {verdict or 'not-run'}",
        }
    except Exception as e:
        checks["classification_contractor"] = {"ok": False, "detail": str(e)}

    try:
        from disclosures import has_accepted_operator_tos
        checks["operator_tos_accepted"] = {
            "ok": has_accepted_operator_tos(bullpen),
            "detail": "Accepted" if has_accepted_operator_tos(bullpen) else "Not accepted",
        }
    except Exception as e:
        checks["operator_tos_accepted"] = {"ok": False, "detail": str(e)}

    try:
        from dnc import dnc_status
        s = dnc_status(bullpen)
        checks["dnc_list_loaded"] = {
            "ok": s.get("any_loaded", False),
            "detail": f"{len(s.get('lists') or {})} list(s)",
        }
    except Exception as e:
        checks["dnc_list_loaded"] = {"ok": False, "detail": str(e)}

    try:
        from audit import verify
        ok, broken_at = verify(bullpen)
        checks["audit_chain_intact"] = {
            "ok": ok,
            "detail": "OK" if ok else f"broken at {broken_at}",
        }
    except Exception as e:
        checks["audit_chain_intact"] = {"ok": False, "detail": str(e)}

    blockers = [name for name, c in checks.items() if not c.get("ok")]
    return {
        "ready": pr["ready"] and not blockers,
        "platform_ready": pr["ready"],
        "platform_blockers": pr["blockers"],
        "bullpen_blockers": blockers,
        "checks": checks,
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    import json, sys
    if len(sys.argv) > 1 and sys.argv[1] != "platform":
        print(json.dumps(bullpen_ready(sys.argv[1]), indent=2))
    else:
        print(json.dumps(platform_ready(), indent=2))
