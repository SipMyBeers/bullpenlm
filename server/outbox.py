"""Outbox — email drafts queued for the founder to send from the official inbox.

Reps write the email body in-app, attached to a deal/contact. Founder
sees the queue, reviews, copies the text into their actual email
client, and marks "sent" — which auto-logs an activity_email so it
shows on the timeline + earns +6 XP for the original rep.

Lifecycle:
  draft     → rep is still editing
  ready     → rep submitted for founder review
  approved  → founder edited/approved, will send manually from inbox
  sent      → founder marked sent; activity_email fires for original rep
  rejected  → founder rejected with optional feedback

Storage:
  bullpens/<slug>/outbox/<id>.json    — one file per draft

Why not just send via SMTP? Per Beers's call: outbound email reputation
belongs to the founder's domain. Reps draft; founder sends. Keeps
deliverability tight and one human reading every email before it goes out.
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

from audit import append as audit_append

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"

VALID_STATUS = {"draft", "ready", "approved", "sent", "rejected"}


def _outbox_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "outbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(bullpen: str, draft_id: str) -> Path:
    return _outbox_dir(bullpen) / f"{draft_id}.json"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def create(bullpen: str, author_rep: str,
           to: str, subject: str, body: str,
           target_type: str = "none", target_id: str = "",
           contact_slug: Optional[str] = None,
           deal_id: Optional[str] = None,
           org_slug: Optional[str] = None,
           submit: bool = False) -> dict:
    if not to.strip() or not subject.strip() or not body.strip():
        raise ValueError("missing_fields")
    if target_type not in ("none", "deal", "contact", "org"):
        raise ValueError("invalid_target_type")
    now = datetime.datetime.now()
    did = f"draft-{now.strftime('%Y%m%d-%H%M%S-%f')}"
    rec = {
        "id": did,
        "created_at": now.isoformat(timespec="seconds"),
        "updated_at": now.isoformat(timespec="seconds"),
        "author_rep": author_rep,
        "to": to.strip(),
        "subject": subject.strip(),
        "body": body,
        "status": "ready" if submit else "draft",
        "target_type": target_type, "target_id": target_id,
        "contact_slug": contact_slug, "deal_id": deal_id, "org_slug": org_slug,
        "reviewed_by": None, "reviewed_at": None,
        "sent_at": None, "rejection_reason": None,
    }
    _path(bullpen, did).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    audit_append(bullpen, author_rep, "email_draft_created",
                 target_type="email_draft", target_id=did,
                 payload={"to": rec["to"], "subject": rec["subject"],
                          "status": rec["status"],
                          "for_target": f"{target_type}:{target_id}"})
    return rec


def get(bullpen: str, draft_id: str) -> Optional[dict]:
    p = _path(bullpen, draft_id)
    if not p.exists(): return None
    try: return json.loads(p.read_text())
    except Exception: return None


def update(bullpen: str, draft_id: str, updates: dict, actor: str) -> Optional[dict]:
    """Patch a draft. Only the author may edit a draft. Status-only
    transitions are allowed for the founder."""
    rec = get(bullpen, draft_id)
    if not rec: return None
    ALLOWED_BODY = {"to", "subject", "body"}
    is_author = rec.get("author_rep") == actor
    if is_author and rec.get("status") in ("draft", "ready"):
        for k in ALLOWED_BODY:
            if k in updates: rec[k] = updates[k]
    rec["updated_at"] = _now()
    _path(bullpen, draft_id).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    return rec


def submit(bullpen: str, draft_id: str, rep: str) -> dict:
    rec = get(bullpen, draft_id)
    if not rec: raise ValueError("draft_not_found")
    if rec.get("author_rep") != rep:
        raise ValueError("only_author_can_submit")
    if rec.get("status") not in ("draft", "rejected"):
        raise ValueError(f"cannot_submit_from_{rec['status']}")
    rec["status"] = "ready"
    rec["updated_at"] = _now()
    _path(bullpen, draft_id).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    audit_append(bullpen, rep, "email_draft_ready",
                 target_type="email_draft", target_id=draft_id,
                 payload={"to": rec["to"], "subject": rec["subject"],
                          "for_target": f"{rec.get('target_type')}:{rec.get('target_id')}"})
    return rec


def mark_sent(bullpen: str, draft_id: str, founder: str) -> dict:
    """Founder copied the email into their inbox + sent it. Log the
    activity against the deal/contact so the timeline + XP picks it up."""
    rec = get(bullpen, draft_id)
    if not rec: raise ValueError("draft_not_found")
    if rec.get("status") in ("sent",): return rec
    rec["status"] = "sent"
    rec["sent_at"] = _now()
    rec["reviewed_by"] = founder
    rec["reviewed_at"] = _now()
    _path(bullpen, draft_id).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")

    # Log activity against the original target so timeline + XP fire for
    # the rep who wrote it (not the founder who clicked Send).
    try:
        from activity import log as activity_log
        author = rec.get("author_rep") or founder
        tt = rec.get("target_type") or "none"
        if tt in ("deal", "contact", "org"):
            activity_log(
                bullpen, actor=author, kind="email",
                target_type=tt, target_id=rec.get("target_id") or "",
                summary="Email sent: " + (rec.get("subject") or "").strip(),
                notes=rec.get("body") or "", direction="outbound",
                contact_slug=rec.get("contact_slug"),
                deal_id=rec.get("deal_id"), org_slug=rec.get("org_slug"),
            )
    except Exception: pass

    audit_append(bullpen, founder, "email_sent",
                 target_type="email_draft", target_id=draft_id,
                 payload={"to": rec["to"], "subject": rec["subject"],
                          "author": rec.get("author_rep"),
                          "for_target": f"{rec.get('target_type')}:{rec.get('target_id')}"})
    return rec


def reject(bullpen: str, draft_id: str, founder: str, reason: str = "") -> dict:
    rec = get(bullpen, draft_id)
    if not rec: raise ValueError("draft_not_found")
    rec["status"] = "rejected"
    rec["reviewed_by"] = founder
    rec["reviewed_at"] = _now()
    rec["rejection_reason"] = reason.strip()
    rec["updated_at"] = _now()
    _path(bullpen, draft_id).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    audit_append(bullpen, founder, "email_draft_rejected",
                 target_type="email_draft", target_id=draft_id,
                 payload={"author": rec.get("author_rep"), "reason": reason.strip()})
    return rec


def list_all(bullpen: str, status: Optional[str] = None,
             author_rep: Optional[str] = None) -> list[dict]:
    out = []
    for f in sorted(_outbox_dir(bullpen).glob("*.json"), reverse=True):
        try: r = json.loads(f.read_text())
        except Exception: continue
        if status and r.get("status") != status: continue
        if author_rep and r.get("author_rep") != author_rep: continue
        out.append(r)
    return out


def queue_for_founder(bullpen: str) -> list[dict]:
    """Drafts that need founder action (ready + approved-not-yet-sent)."""
    return [d for d in list_all(bullpen) if d.get("status") in ("ready", "approved")]
