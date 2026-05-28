"""Applications — public-facing membership applications for invite_only
and paid bullpens.

Anyone (no auth required) POSTs to /api/b/<slug>/apply with their info.
The founder reviews each application in-app and either approves (auto-
generates a single-use invite code and copies the share URL) or
rejects with a reason.

Storage:
  bullpens/<slug>/applications/<id>.json

Lifecycle:
  pending → approved → invited (when the invite code is consumed)
  pending → rejected
"""
from __future__ import annotations
import datetime
import json
import re
import secrets
from pathlib import Path
from typing import Optional

from audit import append as audit_append

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


def _dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "applications"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(bullpen: str, app_id: str) -> Path:
    return _dir(bullpen) / f"{app_id}.json"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _validate_email(e: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (e or "").strip()))


def submit(bullpen: str, name: str, email: str,
           discord_handle: str = "", sales_experience: str = "",
           why: str = "", referred_by: str = "") -> dict:
    if not _validate_email(email):
        raise ValueError("invalid_email")
    if not (name or "").strip():
        raise ValueError("missing_name")
    sales_experience = sales_experience.strip().lower()
    if sales_experience and sales_experience not in ("none", "some", "pro"):
        raise ValueError("invalid_sales_experience")

    now = datetime.datetime.now()
    app_id = f"app-{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    rec = {
        "id": app_id,
        "bullpen": bullpen,
        "name": name.strip()[:80],
        "email": email.strip()[:120],
        "discord_handle": (discord_handle or "").strip()[:40],
        "sales_experience": sales_experience or "none",
        "why": (why or "").strip()[:1200],
        "referred_by": (referred_by or "").strip()[:48],
        "status": "pending",
        "submitted_at": now.isoformat(timespec="seconds"),
        "reviewed_by": None, "reviewed_at": None,
        "rejection_reason": None,
        "invite_code": None,
    }
    _path(bullpen, app_id).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    audit_append(bullpen, "system", "application_submitted",
                 target_type="application", target_id=app_id,
                 payload={"name": rec["name"], "email": rec["email"],
                          "sales_experience": rec["sales_experience"]})
    return rec


def get(bullpen: str, app_id: str) -> Optional[dict]:
    p = _path(bullpen, app_id)
    if not p.exists(): return None
    try: return json.loads(p.read_text())
    except Exception: return None


def list_all(bullpen: str, status: Optional[str] = None) -> list[dict]:
    out = []
    for f in sorted(_dir(bullpen).glob("*.json"), reverse=True):
        try: r = json.loads(f.read_text())
        except Exception: continue
        if status and r.get("status") != status:
            continue
        out.append(r)
    return out


def approve(bullpen: str, app_id: str, founder: str,
            rep_slug: Optional[str] = None) -> dict:
    """Approve + generate an invite code. The applicant gets a single-use
    code they can redeem at /join.html?code=<code>."""
    rec = get(bullpen, app_id)
    if not rec: raise ValueError("application_not_found")
    if rec["status"] != "pending":
        raise ValueError(f"already_{rec['status']}")

    # Derive a slug from the application name unless overridden
    if not rep_slug:
        rep_slug = re.sub(r"[^a-z0-9\-]", "-",
                          rec["name"].lower().strip())[:24].strip("-")
    if not rep_slug:
        rep_slug = "rep-" + secrets.token_hex(3)

    try:
        from invites import create_invite
        code_obj = create_invite(rep_slug)
        # create_invite returns a dict — extract just the code string
        code = code_obj.get("code") if isinstance(code_obj, dict) else code_obj
    except Exception as e:
        raise RuntimeError(f"invite_create_failed: {e}")

    rec["status"] = "approved"
    rec["reviewed_by"] = founder
    rec["reviewed_at"] = _now()
    rec["invite_code"] = code
    rec["rep_slug"] = rep_slug
    _path(bullpen, app_id).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")

    audit_append(bullpen, founder, "application_approved",
                 target_type="application", target_id=app_id,
                 payload={"name": rec["name"], "rep_slug": rep_slug,
                          "invite_code": code})
    return rec


def reject(bullpen: str, app_id: str, founder: str, reason: str = "") -> dict:
    rec = get(bullpen, app_id)
    if not rec: raise ValueError("application_not_found")
    if rec["status"] != "pending":
        return rec
    rec["status"] = "rejected"
    rec["reviewed_by"] = founder
    rec["reviewed_at"] = _now()
    rec["rejection_reason"] = (reason or "").strip()[:300]
    _path(bullpen, app_id).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    audit_append(bullpen, founder, "application_rejected",
                 target_type="application", target_id=app_id,
                 payload={"name": rec["name"], "reason": rec["rejection_reason"]})
    return rec


def count_pending(bullpen: str) -> int:
    return len(list_all(bullpen, status="pending"))
