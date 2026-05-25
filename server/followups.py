"""Follow-ups — personal reminder tasks each rep keeps for themselves.

"Call Marcus Thursday at 2." Lives at:
  bullpens/<slug>/followups/<rep>/<id>.json

Each followup has:
  id, created_at, owner_rep, title, notes, due_at (iso),
  target_type ('deal'|'contact'|'org'|'none'), target_id,
  status ('open'|'done'|'snoozed'), completed_at

Lifecycle:
  open → done       (complete)
  open → open       (snooze; due_at advances; status stays open with a count)
  open → archived   (delete; soft delete only when status=='done')

Listing is fast: walk one folder. The "Today" view filters by
due_at ≤ end-of-day AND status == 'open'.
"""
from __future__ import annotations
import datetime
import json
import re
from pathlib import Path
from typing import Optional

from audit import append as audit_append

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"


def _fu_dir(bullpen: str, rep: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "followups" / rep
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _parse_due(due_at: Optional[str]) -> str:
    """Accept iso, 'today', 'tomorrow', '+Nd', '+Nh', or a date keyword."""
    if not due_at:
        return (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat(timespec="seconds")
    s = due_at.strip().lower()
    now = datetime.datetime.now()
    if s == "today":
        end = now.replace(hour=17, minute=0, second=0, microsecond=0)
        if end < now: end = end + datetime.timedelta(days=1)
        return end.isoformat(timespec="seconds")
    if s == "tomorrow":
        d = (now + datetime.timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        return d.isoformat(timespec="seconds")
    m = re.match(r"^\+(\d+)([dhm])$", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"d": datetime.timedelta(days=n),
                 "h": datetime.timedelta(hours=n),
                 "m": datetime.timedelta(minutes=n)}[unit]
        return (now + delta).isoformat(timespec="seconds")
    # Assume already an iso string — pass through
    return due_at


def create(bullpen: str, owner_rep: str, title: str,
           due_at: Optional[str] = None, notes: str = "",
           target_type: str = "none", target_id: str = "") -> dict:
    if not title.strip():
        raise ValueError("missing_title")
    if target_type not in ("none", "deal", "contact", "org"):
        raise ValueError("invalid_target_type")
    now = datetime.datetime.now()
    fu_id = f"fu-{now.strftime('%Y%m%d-%H%M%S-%f')}"
    rec = {
        "id": fu_id,
        "created_at": now.isoformat(timespec="seconds"),
        "owner_rep": owner_rep,
        "title": title.strip(),
        "notes": (notes or "").strip(),
        "due_at": _parse_due(due_at),
        "target_type": target_type,
        "target_id": target_id,
        "status": "open",
        "snooze_count": 0,
        "completed_at": None,
    }
    (_fu_dir(bullpen, owner_rep) / f"{fu_id}.json").write_text(
        json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    audit_append(bullpen, owner_rep, "followup_created",
                 target_type="followup", target_id=fu_id,
                 payload={"title": rec["title"], "due_at": rec["due_at"],
                          "for_target": f"{target_type}:{target_id}"})
    return rec


def list_for_rep(bullpen: str, rep: str,
                 status: Optional[str] = None,
                 due_before: Optional[str] = None) -> list[dict]:
    out = []
    for f in sorted(_fu_dir(bullpen, rep).glob("*.json")):
        try: r = json.loads(f.read_text())
        except Exception: continue
        if status and r.get("status") != status:
            continue
        if due_before and r.get("due_at", "") > due_before:
            continue
        out.append(r)
    # Newest first by due_at among open, then by completed_at desc among done
    out.sort(key=lambda r: (r.get("due_at") or r.get("completed_at") or ""))
    return out


def get(bullpen: str, rep: str, fu_id: str) -> Optional[dict]:
    p = _fu_dir(bullpen, rep) / f"{fu_id}.json"
    if not p.exists(): return None
    try: return json.loads(p.read_text())
    except Exception: return None


def complete(bullpen: str, rep: str, fu_id: str) -> Optional[dict]:
    p = _fu_dir(bullpen, rep) / f"{fu_id}.json"
    if not p.exists(): return None
    rec = json.loads(p.read_text())
    if rec.get("status") == "done":
        return rec
    rec["status"] = "done"
    rec["completed_at"] = _now_iso()
    p.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    audit_append(bullpen, rep, "followup_done",
                 target_type="followup", target_id=fu_id,
                 payload={"title": rec.get("title"),
                          "for_target": f"{rec.get('target_type')}:{rec.get('target_id')}"})
    return rec


def snooze(bullpen: str, rep: str, fu_id: str, snooze_to: str) -> Optional[dict]:
    p = _fu_dir(bullpen, rep) / f"{fu_id}.json"
    if not p.exists(): return None
    rec = json.loads(p.read_text())
    if rec.get("status") == "done":
        raise ValueError("already_done")
    rec["due_at"] = _parse_due(snooze_to)
    rec["snooze_count"] = int(rec.get("snooze_count", 0)) + 1
    p.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    audit_append(bullpen, rep, "followup_snoozed",
                 target_type="followup", target_id=fu_id,
                 payload={"title": rec.get("title"), "new_due_at": rec["due_at"],
                          "snooze_count": rec["snooze_count"]})
    return rec


def for_target(bullpen: str, target_type: str, target_id: str) -> list[dict]:
    """All open follow-ups across all reps for a given (type, id) — used by
    the deal/contact pages to show 'X has a follow-up Thursday'."""
    root = BULLPENS_ROOT / bullpen / "followups"
    if not root.exists(): return []
    out = []
    for rep_dir in root.iterdir():
        if not rep_dir.is_dir(): continue
        for f in rep_dir.glob("*.json"):
            try: r = json.loads(f.read_text())
            except Exception: continue
            if r.get("status") != "open": continue
            if r.get("target_type") == target_type and r.get("target_id") == target_id:
                out.append(r)
    out.sort(key=lambda r: r.get("due_at", ""))
    return out
