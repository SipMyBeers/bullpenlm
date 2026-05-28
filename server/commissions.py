"""Commissions — auto-generated monthly statements per rep.

A statement is produced from:
  • all deals owned by `rep` that closed-won within the period
  • the rate table parsed from the currently-signed referral agreement
  • a default classification of every deal as "pilot" revenue (the system
    has no notion of expansion / renewal yet — those tag onto the deal
    record when we add subscription tracking)

Statements live at:
  bullpens/<slug>/commissions/<rep>/<YYYY-MM>.json

A statement is idempotent: rebuilding for the same (rep, period) yields
the same numbers, plus a new `generated_at` timestamp.
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

from audit import iter_all as audit_iter_all
from legal import get_doc as legal_get_doc, is_current_signature

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"

REFERRAL_DOC_ID = "referral-agreement"


def _commissions_dir(bullpen: str, rep: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "commissions" / rep
    d.mkdir(parents=True, exist_ok=True)
    return d


def _deals_dir(bullpen: str) -> Path:
    return BULLPENS_ROOT / bullpen / "deals"


def _load_deal(bullpen: str, deal_id: str) -> Optional[dict]:
    f = _deals_dir(bullpen) / f"{deal_id}.json"
    if not f.exists():
        return None
    try: return json.loads(f.read_text())
    except Exception: return None


def _period_bounds(yyyy_mm: str) -> tuple[str, str]:
    """Return ISO-string [start, end_exclusive) for a YYYY-MM period."""
    year, month = (int(p) for p in yyyy_mm.split("-"))
    start = datetime.date(year, month, 1)
    end   = datetime.date(year + (month // 12), (month % 12) + 1, 1)
    return (start.isoformat() + "T00:00:00", end.isoformat() + "T00:00:00")


def _pick_pilot_rate(rates: list[dict]) -> float:
    """The rate table parser returns multiple rows (pilot/expansion/renewal).
    The MVP commission engine treats every closed-won deal as pilot revenue
    until we add expansion/renewal classifications to the deal record."""
    for r in rates:
        if "pilot" in (r.get("label") or "").lower():
            return float(r.get("percent") or 0)
    # Fallback: highest declared rate
    if rates:
        return max(float(r.get("percent") or 0) for r in rates)
    return 0.0


def generate(bullpen: str, rep: str, period: str) -> dict:
    """Build (and persist) one monthly statement for one rep.

    Returns the statement dict. Idempotent across re-runs for the same period."""
    start_ts, end_ts = _period_bounds(period)
    doc = legal_get_doc(bullpen, REFERRAL_DOC_ID)
    rates = (doc or {}).get("rates") or []
    rate_pct = _pick_pilot_rate(rates)
    sig = is_current_signature(bullpen, rep, REFERRAL_DOC_ID)

    line_items: list[dict] = []
    gross_amount = 0.0
    commission_amount = 0.0

    # Walk audit events for close-won events in the period belonging to this rep.
    for evt in audit_iter_all(bullpen):
        if evt.get("kind") != "deal_closed_won":
            continue
        if evt.get("actor") != rep:
            continue
        ts = evt.get("ts") or ""
        if not (start_ts <= ts < end_ts):
            continue

        deal_id = evt.get("target_id")
        deal = _load_deal(bullpen, deal_id) or {}
        amount = float((evt.get("payload") or {}).get("amount")
                       or deal.get("amount") or 0)
        commission = round(amount * rate_pct / 100, 2)
        line_items.append({
            "deal_id": deal_id,
            "prospect": deal.get("prospect") or (evt.get("payload") or {}).get("prospect"),
            "closed_at": ts,
            "amount": amount,
            "revenue_type": "pilot",
            "rate_pct": rate_pct,
            "commission": commission,
        })
        gross_amount += amount
        commission_amount += commission

    statement = {
        "bullpen": bullpen,
        "rep": rep,
        "period": period,
        "rate_pct_applied": rate_pct,
        "rate_source_doc": REFERRAL_DOC_ID,
        "rate_source_sha256": (doc or {}).get("sha256"),
        "signature_status": "current" if sig else (
            "missing" if not any(s for s in []) else "out_of_date"
        ),
        "signed_at": sig.get("signed_at") if sig else None,
        "deals_closed": len(line_items),
        "gross_amount": round(gross_amount, 2),
        "commission_amount": round(commission_amount, 2),
        "line_items": line_items,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "warnings": _warnings(rep, sig, rate_pct, line_items),
    }
    path = _commissions_dir(bullpen, rep) / f"{period}.json"
    path.write_text(json.dumps(statement, indent=2) + "\n")
    return statement


def _warnings(rep: str, sig: Optional[dict], rate_pct: float, items: list[dict]) -> list[str]:
    w = []
    if not sig:
        w.append("no_current_signature_on_referral_agreement")
    if rate_pct <= 0:
        w.append("rate_table_not_parseable_from_referral_agreement")
    if not items:
        w.append("no_closed_won_deals_in_period")
    return w


def get(bullpen: str, rep: str, period: str) -> Optional[dict]:
    p = _commissions_dir(bullpen, rep) / f"{period}.json"
    if not p.exists():
        return None
    try: return json.loads(p.read_text())
    except Exception: return None


def list_for_rep(bullpen: str, rep: str) -> list[dict]:
    d = _commissions_dir(bullpen, rep)
    out = []
    for f in sorted(d.glob("*.json"), reverse=True):
        try:
            s = json.loads(f.read_text())
            out.append({k: s.get(k) for k in
                        ("period", "deals_closed", "gross_amount",
                         "commission_amount", "signature_status", "generated_at")})
        except Exception:
            continue
    return out


def list_all(bullpen: str) -> dict[str, list[dict]]:
    """Map rep → statement summaries (for the bullpen-wide commissions view)."""
    root = BULLPENS_ROOT / bullpen / "commissions"
    if not root.exists():
        return {}
    out: dict[str, list[dict]] = {}
    for rep_dir in sorted(root.iterdir()):
        if not rep_dir.is_dir():
            continue
        out[rep_dir.name] = list_for_rep(bullpen, rep_dir.name)
    return out


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python3 server/commissions.py <bullpen> <rep> <YYYY-MM>")
        sys.exit(0)
    s = generate(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"  Period: {s['period']}")
    print(f"  Rate applied: {s['rate_pct_applied']}% (signature: {s['signature_status']})")
    print(f"  Deals: {s['deals_closed']}  Gross: ${s['gross_amount']:,.2f}  Commission: ${s['commission_amount']:,.2f}")
    if s["warnings"]:
        print(f"  Warnings: {', '.join(s['warnings'])}")
