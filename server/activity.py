"""Activity — the lived history of every prospect / contact / deal.

A unified timeline log: every call, email, meeting, sms, note attached
to a (deal_id | contact "<org>/<slug>" | org_slug) target. Append-only
to bullpens/<slug>/activity/<target_key>.jsonl AND mirrored to the
audit log so it flows over SSE in real time.

Schema:
  { id, ts, kind, actor, target_type, target_id,
    outcome,  -- for calls: booked | no_answer | voicemail | gatekeeper | not_interested | bad_number
    direction,-- inbound | outbound
    summary,  -- one-line headline
    notes,    -- free markdown
    duration_sec,
    contact_slug, deal_id, org_slug -- whichever apply
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

VALID_KINDS = {"call", "email", "meeting", "sms", "note", "task_done"}
CALL_OUTCOMES = {"booked", "no_answer", "voicemail", "gatekeeper",
                 "not_interested", "bad_number", "callback", "other"}


def _activity_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "activity"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_target_key(target_type: str, target_id: str) -> str:
    """File-safe key per target. Contacts use 'contact__<org>__<slug>'."""
    if target_type == "contact":
        return "contact__" + (target_id or "").replace("/", "__")
    return f"{target_type}__{target_id or 'misc'}".replace("/", "__").replace(" ", "_")


def _activity_path(bullpen: str, target_type: str, target_id: str) -> Path:
    return _activity_dir(bullpen) / f"{_safe_target_key(target_type, target_id)}.jsonl"


def log(bullpen: str, actor: str, kind: str,
        target_type: str, target_id: str,
        summary: str = "", notes: str = "",
        outcome: Optional[str] = None,
        direction: str = "outbound",
        duration_sec: Optional[int] = None,
        contact_slug: Optional[str] = None,
        deal_id: Optional[str] = None,
        org_slug: Optional[str] = None) -> dict:
    if kind not in VALID_KINDS:
        raise ValueError("invalid_kind")
    if target_type not in ("deal", "contact", "org"):
        raise ValueError("invalid_target_type")
    if outcome and outcome not in CALL_OUTCOMES:
        raise ValueError("invalid_outcome")

    now = datetime.datetime.now()
    entry = {
        "id": f"act-{now.strftime('%Y%m%d-%H%M%S-%f')}",
        "ts": now.isoformat(timespec="seconds"),
        "actor": actor,
        "kind": kind,
        "target_type": target_type,
        "target_id": target_id,
        "summary": (summary or "").strip(),
        "notes": (notes or "").strip(),
        "outcome": outcome,
        "direction": direction,
        "duration_sec": duration_sec,
        "contact_slug": contact_slug,
        "deal_id": deal_id,
        "org_slug": org_slug,
    }

    # Append to the per-target log
    with _activity_path(bullpen, target_type, target_id).open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Mirror to audit so SSE delivers + XP fires
    # For calls, also use the existing "call" event kind so the call XP
    # rule + leaderboard count picks it up.
    if kind == "call":
        audit_append(bullpen, actor, "call",
                     target_type=target_type, target_id=target_id,
                     payload={"summary": entry["summary"],
                              "outcome": outcome, "direction": direction,
                              "call_kind": "real" if outcome != "voicemail" else "voicemail",
                              "duration_sec": duration_sec,
                              "contact_slug": contact_slug,
                              "deal_id": deal_id, "org_slug": org_slug,
                              "activity_id": entry["id"]})
    else:
        audit_append(bullpen, actor, "activity_" + kind,
                     target_type=target_type, target_id=target_id,
                     payload={"summary": entry["summary"], "outcome": outcome,
                              "direction": direction,
                              "contact_slug": contact_slug,
                              "deal_id": deal_id, "org_slug": org_slug,
                              "activity_id": entry["id"]})
    return entry


def for_target(bullpen: str, target_type: str, target_id: str,
               limit: int = 200) -> list[dict]:
    p = _activity_path(bullpen, target_type, target_id)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try: out.append(json.loads(line))
        except Exception: continue
    out.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return out[:limit]


def for_org(bullpen: str, org_slug: str, limit: int = 100) -> list[dict]:
    """Roll up all activity across the org (deal-targeted + contact-targeted
    + org-targeted) into one timeline."""
    out: list[dict] = []
    root = _activity_dir(bullpen)
    if not root.exists():
        return []
    for f in root.glob("*.jsonl"):
        for line in f.read_text().splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("org_slug") == org_slug:
                out.append(e)
                continue
            if e.get("target_type") == "org" and e.get("target_id") == org_slug:
                out.append(e); continue
    out.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return out[:limit]


def for_deal(bullpen: str, deal_id: str, limit: int = 100) -> list[dict]:
    """All activity that names this deal, anywhere."""
    out: list[dict] = []
    root = _activity_dir(bullpen)
    if not root.exists():
        return []
    for f in root.glob("*.jsonl"):
        for line in f.read_text().splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("deal_id") == deal_id or (e.get("target_type") == "deal" and e.get("target_id") == deal_id):
                out.append(e)
    out.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return out[:limit]


def for_contact(bullpen: str, org_slug: str, contact_slug: str,
                limit: int = 100) -> list[dict]:
    out: list[dict] = []
    root = _activity_dir(bullpen)
    if not root.exists():
        return []
    cs = contact_slug
    for f in root.glob("*.jsonl"):
        for line in f.read_text().splitlines():
            try: e = json.loads(line)
            except Exception: continue
            if e.get("contact_slug") == cs and e.get("org_slug") == org_slug:
                out.append(e); continue
            if e.get("target_type") == "contact" and e.get("target_id") == f"{org_slug}/{cs}":
                out.append(e)
    out.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return out[:limit]
