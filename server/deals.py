"""Deal — a tracked opportunity inside a bullpen. Lives at
`bullpens/<slug>/deals/<deal_id>.json`. Every mutation (create, stage
move, close, delete) emits an AuditEvent so the chain is the source of
truth for everything that affects commission + XP.

Deal JSON shape:
  {
    "id": "20260524-142503-allstate",
    "prospect_slug": "allstate",
    "owner_rep": "beers",
    "pipeline": "default",
    "stage": "qualified",
    "amount": 15000,
    "currency": "USD",
    "opened_at": "2026-05-24T14:25:03",
    "closed_at": null,
    "closed_won": null,
    "source_call_id": null,
    "signature_ids": [],
    "custom": {},
    "notes": "",
    "stage_history": [
      {"stage": "lead",      "by": "beers", "at": "2026-05-24T14:25:03"},
      {"stage": "qualified", "by": "beers", "at": "2026-05-24T14:30:00"}
    ]
  }

Weighted forecast = sum(amount × stage.probability) across non-terminal deals.
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"


def _deals_dir(bullpen: str) -> Path:
    return BULLPENS_ROOT / bullpen / "deals"


def _deal_path(bullpen: str, deal_id: str) -> Path:
    return _deals_dir(bullpen) / f"{deal_id}.json"


def _new_id(prospect_slug: str) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{ts}-{prospect_slug}"


def create(bullpen: str, prospect_slug: str, owner_rep: str,
           amount: float = 0, pipeline_name: str = "default",
           stage_id: str = "lead", source_call_id: Optional[str] = None,
           notes: str = "") -> dict:
    """Create a new deal. Emits AuditEvent."""
    from audit import append as audit_append
    from pipeline import ensure_default, stage as get_stage

    ensure_default(bullpen)  # make sure default pipeline exists
    deal_id = _new_id(prospect_slug)
    now = datetime.datetime.now().isoformat(timespec="seconds")

    deal = {
        "id": deal_id,
        "prospect_slug": prospect_slug,
        "owner_rep": owner_rep,
        "pipeline": pipeline_name,
        "stage": stage_id,
        "amount": float(amount or 0),
        "currency": "USD",
        "opened_at": now,
        "closed_at": None,
        "closed_won": None,
        "source_call_id": source_call_id,
        "signature_ids": [],
        "custom": {},
        "notes": notes,
        "stage_history": [{"stage": stage_id, "by": owner_rep, "at": now}],
    }
    _deals_dir(bullpen).mkdir(parents=True, exist_ok=True)
    _deal_path(bullpen, deal_id).write_text(json.dumps(deal, indent=2) + "\n")

    audit_append(bullpen, owner_rep, "deal_created",
                 target_type="deal", target_id=deal_id,
                 payload={"prospect": prospect_slug, "amount": amount,
                          "stage": stage_id, "pipeline": pipeline_name})
    return deal


def get(bullpen: str, deal_id: str) -> Optional[dict]:
    p = _deal_path(bullpen, deal_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def list_all(bullpen: str, owner_rep: Optional[str] = None,
             include_terminal: bool = True) -> list[dict]:
    from pipeline import get as get_pipeline, is_terminal
    d = _deals_dir(bullpen)
    if not d.exists():
        return []
    out = []
    pipelines = {}  # cache per-pipeline lookups
    for p in sorted(d.glob("*.json")):
        try:
            deal = json.loads(p.read_text())
        except Exception:
            continue
        if owner_rep and deal.get("owner_rep") != owner_rep:
            continue
        if not include_terminal:
            pn = deal.get("pipeline", "default")
            if pn not in pipelines:
                pipelines[pn] = get_pipeline(bullpen, pn) or {}
            if is_terminal(pipelines[pn], deal.get("stage")):
                continue
        out.append(deal)
    # Sort by opened_at descending (newest first)
    out.sort(key=lambda x: x.get("opened_at", ""), reverse=True)
    return out


def move_stage(bullpen: str, deal_id: str, new_stage_id: str,
               actor_rep: str) -> dict:
    """Move a deal to a new stage. Emits AuditEvent with stage probability
    delta in the payload (drives XP)."""
    from audit import append as audit_append
    from pipeline import get as get_pipeline, stage_probability, is_terminal

    deal = get(bullpen, deal_id)
    if not deal:
        return {"ok": False, "error": "deal_not_found"}
    if deal["stage"] == new_stage_id:
        return {"ok": True, "deal": deal, "noop": True}

    p = get_pipeline(bullpen, deal.get("pipeline", "default"))
    if not p:
        return {"ok": False, "error": "pipeline_not_found"}
    if not any(s.get("id") == new_stage_id for s in p.get("stages", [])):
        return {"ok": False, "error": "invalid_stage", "stage": new_stage_id}

    old_stage = deal["stage"]
    old_prob = stage_probability(p, old_stage)
    new_prob = stage_probability(p, new_stage_id)
    now = datetime.datetime.now().isoformat(timespec="seconds")

    deal["stage"] = new_stage_id
    deal["stage_history"].append(
        {"stage": new_stage_id, "by": actor_rep, "at": now})

    # If we landed in a terminal stage, set closed_at + closed_won
    if is_terminal(p, new_stage_id):
        deal["closed_at"] = now
        deal["closed_won"] = (new_stage_id == "won")

    _deal_path(bullpen, deal_id).write_text(json.dumps(deal, indent=2) + "\n")

    audit_append(bullpen, actor_rep, "deal_stage_moved",
                 target_type="deal", target_id=deal_id,
                 payload={"from": old_stage, "to": new_stage_id,
                          "prob_delta": round(new_prob - old_prob, 4),
                          "amount": deal.get("amount", 0)})

    # Special close events get their own kind for XP rules to match easily
    if is_terminal(p, new_stage_id):
        audit_append(bullpen, actor_rep,
                     "deal_closed_won" if deal["closed_won"] else "deal_closed_lost",
                     target_type="deal", target_id=deal_id,
                     payload={"amount": deal.get("amount", 0),
                              "prospect": deal.get("prospect_slug")})

    return {"ok": True, "deal": deal}


def update_amount(bullpen: str, deal_id: str, new_amount: float,
                  actor_rep: str) -> dict:
    from audit import append as audit_append
    deal = get(bullpen, deal_id)
    if not deal:
        return {"ok": False, "error": "deal_not_found"}
    old = deal.get("amount", 0)
    deal["amount"] = float(new_amount or 0)
    _deal_path(bullpen, deal_id).write_text(json.dumps(deal, indent=2) + "\n")
    audit_append(bullpen, actor_rep, "deal_amount_changed",
                 target_type="deal", target_id=deal_id,
                 payload={"from": old, "to": deal["amount"]})
    return {"ok": True, "deal": deal}


def forecast(bullpen: str, owner_rep: Optional[str] = None) -> dict:
    """Weighted forecast = sum(amount × stage.probability) over non-terminal
    deals. Returns totals per stage + grand totals."""
    from pipeline import get as get_pipeline, stage_probability, is_terminal
    p = get_pipeline(bullpen, "default") or {"stages": []}

    by_stage = {}
    total_pipeline = 0.0
    total_weighted = 0.0
    closed_won = 0.0
    closed_lost_count = 0

    for deal in list_all(bullpen, owner_rep=owner_rep, include_terminal=True):
        stage_id = deal.get("stage", "lead")
        amount = float(deal.get("amount", 0))
        if is_terminal(p, stage_id):
            if deal.get("closed_won"):
                closed_won += amount
            else:
                closed_lost_count += 1
            continue
        prob = stage_probability(p, stage_id)
        weighted = amount * prob
        slot = by_stage.setdefault(stage_id, {"count": 0, "amount": 0.0, "weighted": 0.0,
                                              "probability": prob})
        slot["count"] += 1
        slot["amount"] += amount
        slot["weighted"] += weighted
        total_pipeline += amount
        total_weighted += weighted

    return {
        "owner_rep": owner_rep,
        "total_pipeline": round(total_pipeline, 2),
        "total_weighted": round(total_weighted, 2),
        "closed_won": round(closed_won, 2),
        "closed_lost_count": closed_lost_count,
        "by_stage": {k: {**v,
                         "amount": round(v["amount"], 2),
                         "weighted": round(v["weighted"], 2)}
                     for k, v in by_stage.items()},
    }
