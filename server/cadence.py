"""Follow-up cadence engine.

When a deal moves into a pipeline stage, automatically start a cadence
template: a sequence of touches (call / email / note / meeting / DNC-check)
scheduled across N days. Each touch is auditable and XP-eligible per
the rules in xp.py.

Cadence templates are stage-triggered: when audit emits
`deal_stage_moved` with `payload.to == <stage>`, a matching cadence
starts for that deal. Multiple cadences can be active per deal; same
template doesn't double-start (idempotent).

Templates ship with sane defaults but operators can override per-bullpen
by dropping JSON files into `bullpens/<slug>/cadence-templates/`.

Storage
=======

  bullpens/<slug>/cadences/<cadence_id>.json
    {
      "id": "cad-YYYYMMDD-HHMMSS-XX",
      "deal_id": "deal-...",
      "rep": "kelly",
      "template": "qualified_to_demo",
      "started_at": ISO8601,
      "status": "active" | "completed" | "abandoned",
      "completed_at": ISO8601 | null,
      "steps": [
        {
          "idx": 0, "day": 0, "channel": "email",
          "template": "qualified-intro", "due_at": ISO8601,
          "status": "pending" | "done" | "skipped",
          "completed_at": ISO8601 | null, "note": ""
        },
        ...
      ]
    }

Audit events
============

  cadence_started     payload {cadence_id, deal_id, template, rep}
  followup_scheduled  payload {cadence_id, step_idx, channel, due_at}     (per step at start)
  followup_executed   payload {cadence_id, step_idx, channel, executed_at} (per mark-done)
  cadence_completed   payload {cadence_id, deal_id, template, rep}
  cadence_abandoned   payload {cadence_id, deal_id, reason}

XP credit per the rules in xp.py:
  followup_scheduled  +2 clout (per step at start)
  followup_executed   +8 clout (per step marked done)
  cadence_completed  +30 clout (when last step done)
"""
from __future__ import annotations
import datetime
import json
import secrets
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"


# ── Template definitions ──────────────────────────────────────────────────

# Built-in defaults. Operators can override by writing JSON to
# bullpens/<slug>/cadence-templates/<template-id>.json with the same shape.

DEFAULT_TEMPLATES = {
    # Most common: prospect just moved into a stage that requires
    # active outreach. The cadence keeps them warm without nagging.
    "qualified_to_demo": {
        "name": "Qualified → Demo",
        "description": "Move them from qualified to demo within 14 days.",
        "trigger_stage": "qualified",
        "steps": [
            {"day": 0, "channel": "email", "template": "qualified-intro",
             "note": "Confirm pain you've already established + 2 demo slots"},
            {"day": 1, "channel": "linkedin",
             "note": "Connect / DM if not connected"},
            {"day": 3, "channel": "call",
             "note": "Voicemail OK — reference the email subject"},
            {"day": 7, "channel": "email", "template": "qualified-followup",
             "note": "Send the peer-firm case study"},
            {"day": 12, "channel": "call",
             "note": "Last attempt before abandoning to nurture"},
        ],
    },
    "demo_to_pilot": {
        "name": "Demo → Pilot",
        "description": "Convert post-demo interest into a paid pilot.",
        "trigger_stage": "demo",
        "steps": [
            {"day": 0, "channel": "email", "template": "demo-recap",
             "note": "Send the recap with concrete next ask"},
            {"day": 2, "channel": "call",
             "note": "Pricing + procurement intro call"},
            {"day": 5, "channel": "email", "template": "pilot-proposal",
             "note": "Send the pilot SOW"},
            {"day": 9, "channel": "linkedin",
             "note": "Engage with their content / share something relevant"},
            {"day": 14, "channel": "call",
             "note": "Decision push — schedule the kickoff"},
        ],
    },
    "pilot_to_close": {
        "name": "Pilot → Close",
        "description": "Convert pilot success into full purchase.",
        "trigger_stage": "pilot",
        "steps": [
            {"day": 0, "channel": "email", "template": "pilot-kickoff",
             "note": "Kickoff agenda + success criteria"},
            {"day": 7, "channel": "call",
             "note": "Week 1 check-in"},
            {"day": 14, "channel": "email", "template": "pilot-midpoint",
             "note": "Halfway results + expansion options"},
            {"day": 21, "channel": "meeting",
             "note": "Stakeholder review — bring procurement"},
            {"day": 28, "channel": "email", "template": "pilot-close",
             "note": "Final terms + signature request"},
        ],
    },
    "pilot_stalled_recovery": {
        "name": "Pilot stalled — recovery",
        "description": "When a pilot hasn't progressed in 14 days, run a recovery sequence.",
        "trigger_stage": None,  # manual trigger only
        "steps": [
            {"day": 0, "channel": "call",
             "note": "Diagnostic call — what changed?"},
            {"day": 3, "channel": "email", "template": "executive-summary",
             "note": "Forward to the exec sponsor"},
            {"day": 7, "channel": "meeting",
             "note": "All-hands recovery meeting"},
        ],
    },
    "lead_nurture": {
        "name": "Lead nurture (post-rejection)",
        "description": "Slow drip for leads that weren't ready.",
        "trigger_stage": "lost",
        "steps": [
            {"day": 30, "channel": "email", "template": "industry-update",
             "note": "Send relevant industry move"},
            {"day": 90, "channel": "email", "template": "case-study-share",
             "note": "Peer-firm case study"},
            {"day": 180, "channel": "linkedin",
             "note": "Engage with their content"},
            {"day": 270, "channel": "email", "template": "reopen",
             "note": "Direct ask: \"anything changed?\""},
        ],
    },
}


# ── Storage helpers ──────────────────────────────────────────────────────

def _cadence_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "cadences"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cadence_path(bullpen: str, cad_id: str) -> Path:
    return _cadence_dir(bullpen) / f"{cad_id}.json"


def _templates_dir(bullpen: str) -> Path:
    return BULLPENS_ROOT / bullpen / "cadence-templates"


def get_templates(bullpen: str) -> dict:
    """Default templates + any operator overrides."""
    out = dict(DEFAULT_TEMPLATES)
    over_dir = _templates_dir(bullpen)
    if over_dir.exists():
        for f in over_dir.glob("*.json"):
            try:
                custom = json.loads(f.read_text())
                tid = f.stem
                out[tid] = custom
            except Exception:
                continue
    return out


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _audit(bullpen: str, actor: str, kind: str, payload: dict) -> None:
    try:
        from audit import append as audit_append
        audit_append(bullpen, actor, kind, target_type="cadence",
                     target_id=payload.get("cadence_id", ""), payload=payload)
    except Exception:
        pass


# ── Lifecycle ─────────────────────────────────────────────────────────────

def start_for_deal(
    bullpen: str, deal_id: str, *, template: str,
    rep: str, now: Optional[datetime.datetime] = None,
) -> dict:
    """Start a cadence for a deal. Idempotent on (deal_id, template) —
    if an active cadence already exists for that pair, returns the
    existing one."""
    templates = get_templates(bullpen)
    if template not in templates:
        raise ValueError(f"unknown cadence template: {template}")

    # De-dupe: any ACTIVE cadence on this deal+template?
    existing = next((c for c in list_for_deal(bullpen, deal_id)
                     if c["template"] == template and c["status"] == "active"), None)
    if existing:
        return existing

    t = templates[template]
    now = now or _now()
    cad_id = f"cad-{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
    steps = []
    for i, st in enumerate(t["steps"]):
        due = now + datetime.timedelta(days=int(st.get("day", 0)))
        steps.append({
            "idx": i,
            "day": int(st.get("day", 0)),
            "channel": st.get("channel", "email"),
            "template": st.get("template"),
            "note": st.get("note", ""),
            "due_at": due.isoformat(timespec="seconds"),
            "status": "pending",
            "completed_at": None,
        })
    rec = {
        "id": cad_id,
        "deal_id": deal_id,
        "rep": rep,
        "template": template,
        "template_name": t.get("name", template),
        "started_at": now.isoformat(timespec="seconds"),
        "status": "active",
        "completed_at": None,
        "steps": steps,
    }
    _cadence_path(bullpen, cad_id).write_text(json.dumps(rec, indent=2))
    _audit(bullpen, rep, "cadence_started", {
        "cadence_id": cad_id, "deal_id": deal_id, "template": template, "rep": rep,
    })
    # Audit each scheduled step so XP credits at start
    for s in steps:
        _audit(bullpen, rep, "followup_scheduled", {
            "cadence_id": cad_id, "step_idx": s["idx"],
            "channel": s["channel"], "due_at": s["due_at"],
        })
    return rec


def mark_done(bullpen: str, cad_id: str, step_idx: int,
              *, rep: str, note: str = "") -> dict:
    """Mark a step done. If all steps done, mark cadence completed."""
    p = _cadence_path(bullpen, cad_id)
    if not p.exists():
        raise ValueError(f"cadence not found: {cad_id}")
    rec = json.loads(p.read_text())
    if step_idx < 0 or step_idx >= len(rec["steps"]):
        raise ValueError(f"step_idx out of range: {step_idx}")
    step = rec["steps"][step_idx]
    if step["status"] == "done":
        return rec  # idempotent
    step["status"] = "done"
    step["completed_at"] = _now().isoformat(timespec="seconds")
    if note:
        step["note"] = (step.get("note", "") + " · " + note).strip(" ·")
    p.write_text(json.dumps(rec, indent=2))
    _audit(bullpen, rep, "followup_executed", {
        "cadence_id": cad_id, "step_idx": step_idx,
        "channel": step["channel"], "executed_at": step["completed_at"],
    })

    # All done?
    if all(s["status"] in ("done", "skipped") for s in rec["steps"]):
        rec["status"] = "completed"
        rec["completed_at"] = _now().isoformat(timespec="seconds")
        p.write_text(json.dumps(rec, indent=2))
        _audit(bullpen, rep, "cadence_completed", {
            "cadence_id": cad_id, "deal_id": rec["deal_id"],
            "template": rec["template"], "rep": rep,
        })
    return rec


def skip_step(bullpen: str, cad_id: str, step_idx: int,
              *, rep: str, reason: str = "") -> dict:
    p = _cadence_path(bullpen, cad_id)
    if not p.exists():
        raise ValueError(f"cadence not found: {cad_id}")
    rec = json.loads(p.read_text())
    if step_idx < 0 or step_idx >= len(rec["steps"]):
        raise ValueError(f"step_idx out of range: {step_idx}")
    rec["steps"][step_idx]["status"] = "skipped"
    rec["steps"][step_idx]["completed_at"] = _now().isoformat(timespec="seconds")
    if reason:
        rec["steps"][step_idx]["note"] = (rec["steps"][step_idx].get("note", "") + " · skipped: " + reason).strip(" ·")
    p.write_text(json.dumps(rec, indent=2))
    if all(s["status"] in ("done", "skipped") for s in rec["steps"]):
        rec["status"] = "completed"
        rec["completed_at"] = _now().isoformat(timespec="seconds")
        p.write_text(json.dumps(rec, indent=2))
        _audit(bullpen, rep, "cadence_completed", {
            "cadence_id": cad_id, "deal_id": rec["deal_id"],
            "template": rec["template"], "rep": rep,
        })
    return rec


def abandon(bullpen: str, cad_id: str, *, rep: str, reason: str = "") -> dict:
    p = _cadence_path(bullpen, cad_id)
    if not p.exists():
        raise ValueError(f"cadence not found: {cad_id}")
    rec = json.loads(p.read_text())
    rec["status"] = "abandoned"
    rec["completed_at"] = _now().isoformat(timespec="seconds")
    p.write_text(json.dumps(rec, indent=2))
    _audit(bullpen, rep, "cadence_abandoned", {
        "cadence_id": cad_id, "deal_id": rec["deal_id"], "reason": reason,
    })
    return rec


# ── Listing ──────────────────────────────────────────────────────────────

def list_all(bullpen: str, *, status: Optional[str] = None,
             rep: Optional[str] = None) -> list[dict]:
    out = []
    d = _cadence_dir(bullpen)
    for f in sorted(d.glob("*.json"), reverse=True):
        try:
            rec = json.loads(f.read_text())
        except Exception:
            continue
        if status and rec.get("status") != status:
            continue
        if rep and rec.get("rep") != rep:
            continue
        out.append(rec)
    return out


def list_for_deal(bullpen: str, deal_id: str) -> list[dict]:
    return [c for c in list_all(bullpen) if c.get("deal_id") == deal_id]


def get(bullpen: str, cad_id: str) -> Optional[dict]:
    p = _cadence_path(bullpen, cad_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def due_steps(bullpen: str, *, rep: Optional[str] = None,
              within_hours: Optional[int] = None) -> list[dict]:
    """Steps that are pending and either past-due or due within
    `within_hours`. Used by the operator daily check / UI badge."""
    out = []
    cutoff = None
    if within_hours is not None:
        cutoff = _now() + datetime.timedelta(hours=within_hours)
    for c in list_all(bullpen, status="active", rep=rep):
        for s in c["steps"]:
            if s["status"] != "pending":
                continue
            try:
                due_dt = datetime.datetime.fromisoformat(s["due_at"])
            except Exception:
                continue
            if cutoff is None or due_dt <= cutoff:
                out.append({
                    "cadence_id": c["id"], "deal_id": c["deal_id"],
                    "rep": c["rep"], "template": c["template"],
                    "step": s,
                })
    return out


# ── SSE-driven auto-start ────────────────────────────────────────────────

# Maps trigger_stage → template_id. Built from get_templates() once on
# first call so operator overrides are respected.
def _stage_to_templates(bullpen: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for tid, t in get_templates(bullpen).items():
        stage = t.get("trigger_stage")
        if stage:
            out.setdefault(stage, []).append(tid)
    return out


def handle_audit_event(bullpen: str, event: dict) -> list[dict]:
    """Called by the auto-start watcher. If the event is a
    deal_stage_moved with a stage that has a template, start the
    cadence (idempotent)."""
    if event.get("kind") != "deal_stage_moved":
        return []
    payload = event.get("payload") or {}
    to_stage = payload.get("to") or payload.get("stage")
    deal_id = payload.get("deal_id") or event.get("target_id")
    rep = event.get("actor") or "self"
    if not to_stage or not deal_id:
        return []
    started: list[dict] = []
    for tid in _stage_to_templates(bullpen).get(to_stage, []):
        try:
            rec = start_for_deal(bullpen, deal_id, template=tid, rep=rep)
            started.append(rec)
        except Exception:
            continue
    return started


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 server/cadence.py templates <bullpen>")
        print("  python3 server/cadence.py start <bullpen> <deal_id> <template> <rep>")
        print("  python3 server/cadence.py list <bullpen> [--rep R] [--status S]")
        print("  python3 server/cadence.py done <bullpen> <cad_id> <step_idx> <rep> [note]")
        print("  python3 server/cadence.py due <bullpen> [--within HOURS]")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "templates":
        print(json.dumps(get_templates(sys.argv[2]), indent=2))
    elif cmd == "start":
        print(json.dumps(start_for_deal(sys.argv[2], sys.argv[3], template=sys.argv[4], rep=sys.argv[5]), indent=2))
    elif cmd == "list":
        rep = None; status = None
        if "--rep" in sys.argv: rep = sys.argv[sys.argv.index("--rep")+1]
        if "--status" in sys.argv: status = sys.argv[sys.argv.index("--status")+1]
        print(json.dumps(list_all(sys.argv[2], rep=rep, status=status), indent=2))
    elif cmd == "done":
        note = sys.argv[6] if len(sys.argv) > 6 else ""
        print(json.dumps(mark_done(sys.argv[2], sys.argv[3], int(sys.argv[4]), rep=sys.argv[5], note=note), indent=2))
    elif cmd == "due":
        within = None
        if "--within" in sys.argv: within = int(sys.argv[sys.argv.index("--within")+1])
        print(json.dumps(due_steps(sys.argv[2], within_hours=within), indent=2))
    else:
        print(f"× unknown command: {cmd}", file=sys.stderr); sys.exit(1)
