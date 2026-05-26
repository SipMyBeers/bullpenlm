"""Monthly invoice generation per closer per bullpen.

Beers's architectural call: BullpenLM is not a payment processor. Operators
pay closers themselves through whatever method they accept (Stripe, PayPal,
Wise, USDC, etc. — picked at wizard time). What BullpenLM does:

  • At month-end (or on demand), looks at every `deal_closed_won` event
    in the bullpen's audit log for the period.
  • Groups by closer (the `actor` field on the audit entry).
  • Computes commission per the bullpen's commission_rate (parses "30%",
    "30 %", "0.30", "30 percent of MRR" etc. — best-effort numeric
    extraction; falls back to surfacing the rule string verbatim if
    nothing parseable is found).
  • Writes a Markdown invoice to bullpens/<slug>/invoices/<rep>-<YYYY-MM>.md
    with the operator's entity, closer's payout method, deal breakdown,
    total commission due, and due date (issue + grace days).
  • Audit-logs an `invoice_generated` event so the activity timeline
    captures it.

Closers can also request an early-payout invoice (off-cycle). Founders mark
invoices paid via `mark_paid()`.

Zero hardcoding: every operator/closer detail pulled from bullpen.json +
member files. No "Beers Labs LLC" anywhere — the renderer reads
`company_entity` / `company_entity_type` etc. from the config the wizard
already collects.

  generate_invoice(bullpen, rep, period=YYYY-MM)  → {ok, id, path, total}
  generate_all_for_period(bullpen, period)        → [{rep, id, total}, ...]
  list_invoices(bullpen, rep=None, status=None)   → [...]
  get_invoice(bullpen, invoice_id)                → {id, content, ...} or None
  mark_paid(bullpen, invoice_id, paid_via)        → {ok}
  request_early_payout(bullpen, rep)              → invoice now through today

CLI for sanity-checking from the terminal:
  python3 server/invoices.py generate-all killsesh 2026-05
  python3 server/invoices.py list killsesh
"""
from __future__ import annotations
import calendar
import datetime
import json
import re
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"
INVOICE_GRACE_DAYS = 15  # operator has this long from issue to pay


# ── Storage helpers ────────────────────────────────────────────────────────

def _bullpen_dir(slug: str) -> Path:
    return BULLPENS_ROOT / slug


def _invoices_dir(slug: str) -> Path:
    d = _bullpen_dir(slug) / "invoices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(slug: str) -> Path:
    return _invoices_dir(slug) / "_index.json"


def _load_index(slug: str) -> list[dict]:
    p = _index_path(slug)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def _save_index(slug: str, idx: list[dict]) -> None:
    _index_path(slug).write_text(json.dumps(idx, indent=2) + "\n")


# ── Bullpen + member lookups ───────────────────────────────────────────────

def _bullpen_cfg(slug: str) -> dict:
    p = _bullpen_dir(slug) / "bullpen.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _member(slug: str, rep: str) -> dict:
    p = _bullpen_dir(slug) / "members" / f"{rep}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


# ── Commission math ────────────────────────────────────────────────────────

_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_DEC_RE = re.compile(r"^\s*0?\.\d+\s*$")


def _parse_rate(rate_str: str) -> Optional[float]:
    """Best-effort: pull a rate (as decimal, e.g. 0.30 for 30%) out of a
    free-text commission rule like "50% of revenue" or "0.30" or
    "thirty percent". Returns None if nothing parseable was found —
    caller surfaces the rule string verbatim instead of inventing a number.
    """
    if not rate_str:
        return None
    s = rate_str.strip()
    m = _PCT_RE.search(s)
    if m:
        try:
            return float(m.group(1)) / 100.0
        except ValueError:
            return None
    if _DEC_RE.match(s):
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _money(n) -> str:
    try:
        return "$" + format(float(n), ",.2f")
    except Exception:
        return str(n)


def _period_bounds(period: str) -> tuple[datetime.date, datetime.date]:
    """'2026-05' → (2026-05-01, 2026-05-31)."""
    try:
        y, m = period.split("-")
        y, m = int(y), int(m)
    except Exception:
        raise ValueError(f"period must be YYYY-MM, got {period!r}")
    last = calendar.monthrange(y, m)[1]
    return (datetime.date(y, m, 1), datetime.date(y, m, last))


def _current_period() -> str:
    today = datetime.date.today()
    return f"{today.year:04d}-{today.month:02d}"


# ── Core: pull won deals for a closer over a period ────────────────────────

def _closed_deals_for(slug: str, rep: str,
                       since: datetime.date, until: datetime.date) -> list[dict]:
    """Walk the audit log, return every deal_closed_won attributed to `rep`
    with close-date in [since, until]."""
    try:
        from audit import iter_all
    except Exception:
        return []
    out = []
    for ev in iter_all(slug):
        if ev.get("kind") != "deal_closed_won":
            continue
        if (ev.get("actor") or "") != rep:
            continue
        # When date — prefer payload.closed_at, fall back to top-level ts.
        when_str = (ev.get("payload") or {}).get("closed_at") or ev.get("ts") or ""
        try:
            when = datetime.date.fromisoformat(when_str[:10])
        except Exception:
            continue
        if since <= when <= until:
            out.append({
                "deal_id": ev.get("target_id") or "",
                "prospect": (ev.get("payload") or {}).get("prospect") or "",
                "amount": float((ev.get("payload") or {}).get("amount") or 0),
                "closed_at": when.isoformat(),
                "raw_event_ts": ev.get("ts") or "",
            })
    return out


# ── Invoice rendering ──────────────────────────────────────────────────────

def _operator_block(cfg: dict) -> str:
    """Render the 'Bill TO' (operator) details from bullpen config."""
    founder_name = cfg.get("founder_display_name") or cfg.get("founder_rep") or "—"
    entity = cfg.get("company_entity") or ""
    if entity:
        primary = entity
        sub = founder_name
    else:
        primary = f"{founder_name} (sole proprietor)"
        sub = ""
    parts = [f"**{primary}**"]
    if sub:
        parts.append(sub)
    if cfg.get("brand_sending_email"):
        parts.append(cfg["brand_sending_email"])
    if cfg.get("brand_domain"):
        parts.append(cfg["brand_domain"])
    return "\n".join(parts)


def _closer_block(member: dict, rep: str) -> str:
    """Render the 'Bill FROM' (closer) details from member record."""
    name = member.get("display_name") or rep
    parts = [f"**{name}**", f"@{rep}"]
    if member.get("payout_method"):
        parts.append(f"Preferred payout: {member['payout_method']}")
    if member.get("payout_handle"):
        parts.append(f"Send to: `{member['payout_handle']}`")
    return "\n".join(parts)


def _render_invoice_md(slug: str, rep: str, period: str,
                        deals: list[dict],
                        rate: Optional[float], rate_str: str,
                        commission_total: float,
                        rev_total: float) -> str:
    cfg = _bullpen_cfg(slug)
    member = _member(slug, rep)
    issued = datetime.date.today()
    due = issued + datetime.timedelta(days=INVOICE_GRACE_DAYS)

    inv_id = f"{slug}-{rep}-{period}"
    rate_line = (
        f"{rate*100:g}%" if rate is not None else (rate_str or "per agreement")
    )

    # Deals table
    if deals:
        rows = ["| Deal | Prospect | Closed | Revenue | Commission |",
                "|------|----------|--------|---------|------------|"]
        for d in deals:
            comm = d["amount"] * rate if rate is not None else 0.0
            rows.append(
                f"| `{d['deal_id'] or '—'}` | {d['prospect'] or '—'} | "
                f"{d['closed_at']} | {_money(d['amount'])} | "
                f"{_money(comm) if rate is not None else '—'} |"
            )
        deals_block = "\n".join(rows)
    else:
        deals_block = "_No closed-won deals in this period._"

    payout_methods = (cfg.get("payout_methods") or "").replace(",", ", ")
    payout_methods_block = (
        f"This operator accepts: **{payout_methods}**. "
        f"Confirm with the operator which method they'll use for this invoice."
        if payout_methods else
        "Confirm payout method with the operator before they pay."
    )

    commission_note = (
        f"Rate applied: **{rate_line}** on collected revenue."
        if rate is not None else
        f"Rate per agreement: _{rate_str or 'see signed commission agreement'}_.\n"
        f"This invoice surfaces gross revenue only — the operator must "
        f"compute commission per the agreement's terms before paying."
    )

    md = f"""# Invoice — {inv_id}

**Period:** {period} ({_period_bounds(period)[0]} → {_period_bounds(period)[1]})
**Issued:** {issued.isoformat()}
**Due by:** {due.isoformat()} (operator has {INVOICE_GRACE_DAYS} days)
**Status:** unpaid

---

## Bill from (closer)

{_closer_block(member, rep)}

## Bill to (operator)

{_operator_block(cfg)}

---

## Closed-won deals this period

{deals_block}

**Period revenue closed:** {_money(rev_total)}
**Commission due:** {_money(commission_total) if rate is not None else '— (manual calc per agreement)'}

{commission_note}

---

## Payment

{payout_methods_block}

This invoice was auto-generated by **BullpenLM** based on the bullpen's
audit log. BullpenLM does not custody funds — the operator pays the
closer directly through whichever payout method they agreed on.

If something looks wrong, reply to the operator before the due date so
they can correct the invoice (or generate a revised one) before paying.
"""
    return md


# ── Public API ─────────────────────────────────────────────────────────────

def generate_invoice(slug: str, rep: str,
                      period: Optional[str] = None,
                      early_payout: bool = False) -> dict:
    """Generate (or regenerate) an invoice for one closer for the given
    period. If `early_payout`, the "period" runs from the 1st of the
    current month through today and the file name marks it as a partial
    invoice (e.g. `<rep>-2026-05-mid.md`)."""
    cfg = _bullpen_cfg(slug)
    if not cfg:
        return {"ok": False, "error": "bullpen_not_found"}

    if early_payout:
        today = datetime.date.today()
        since = datetime.date(today.year, today.month, 1)
        until = today
        period = period or f"{today.year:04d}-{today.month:02d}-mid"
    else:
        period = period or _current_period()
        try:
            since, until = _period_bounds(period)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    deals = _closed_deals_for(slug, rep, since, until)
    rev_total = sum(d["amount"] for d in deals)
    rate_str = (cfg.get("commission_rate") or "").strip()
    rate = _parse_rate(rate_str)
    commission_total = rev_total * rate if rate is not None else 0.0

    md = _render_invoice_md(slug, rep, period, deals, rate, rate_str,
                              commission_total, rev_total)
    fname = f"{rep}-{period}.md"
    path = _invoices_dir(slug) / fname
    path.write_text(md)

    inv_id = f"{slug}-{rep}-{period}"
    issued = datetime.date.today().isoformat()
    due = (datetime.date.today() + datetime.timedelta(days=INVOICE_GRACE_DAYS)).isoformat()

    # Update index
    idx = _load_index(slug)
    existing = next((i for i in idx if i.get("id") == inv_id), None)
    entry = {
        "id": inv_id,
        "rep": rep,
        "period": period,
        "file": fname,
        "rev_total": rev_total,
        "commission_total": commission_total if rate is not None else None,
        "rate": rate,
        "rate_str": rate_str,
        "deal_count": len(deals),
        "issued_at": issued,
        "due_at": due,
        "status": (existing.get("status") if existing else None) or "unpaid",
        "early_payout": bool(early_payout),
    }
    if existing:
        # Preserve paid-at if it was already paid
        if existing.get("status") == "paid":
            entry["status"] = "paid"
            entry["paid_at"] = existing.get("paid_at")
            entry["paid_via"] = existing.get("paid_via")
        idx.remove(existing)
    idx.append(entry)
    idx.sort(key=lambda d: (d.get("period", ""), d.get("rep", "")), reverse=True)
    _save_index(slug, idx)

    # Audit-log
    try:
        from audit import append as audit_append
        audit_append(slug, rep, "invoice_generated",
                     target_type="invoice", target_id=inv_id,
                     payload={"period": period, "deal_count": len(deals),
                              "rev_total": rev_total,
                              "commission_total": commission_total,
                              "rate": rate, "rate_str": rate_str,
                              "early_payout": bool(early_payout)})
    except Exception:
        pass

    return {"ok": True, "id": inv_id, "rep": rep, "period": period,
            "path": str(path.relative_to(REPO)),
            "rev_total": rev_total,
            "commission_total": commission_total if rate is not None else None,
            "deal_count": len(deals)}


def generate_all_for_period(slug: str, period: Optional[str] = None) -> list[dict]:
    """Generate an invoice for every closer in the bullpen who had at least
    one closed-won deal in the period. Returns a list of result dicts."""
    period = period or _current_period()
    since, until = _period_bounds(period)
    try:
        from audit import iter_all
    except Exception:
        return []
    # Collect distinct closers with deal_closed_won in window.
    closers: set[str] = set()
    for ev in iter_all(slug):
        if ev.get("kind") != "deal_closed_won":
            continue
        actor = ev.get("actor") or ""
        if not actor:
            continue
        when_str = (ev.get("payload") or {}).get("closed_at") or ev.get("ts") or ""
        try:
            when = datetime.date.fromisoformat(when_str[:10])
        except Exception:
            continue
        if since <= when <= until:
            closers.add(actor)
    return [generate_invoice(slug, rep, period=period) for rep in sorted(closers)]


def list_invoices(slug: str, rep: Optional[str] = None,
                   status: Optional[str] = None) -> list[dict]:
    idx = _load_index(slug)
    out = idx
    if rep:
        out = [i for i in out if i.get("rep") == rep]
    if status:
        out = [i for i in out if i.get("status") == status]
    return out


def get_invoice(slug: str, invoice_id: str) -> Optional[dict]:
    idx = _load_index(slug)
    entry = next((i for i in idx if i.get("id") == invoice_id), None)
    if not entry:
        return None
    path = _invoices_dir(slug) / entry["file"]
    if not path.exists():
        return entry
    return {**entry, "content": path.read_text()}


def mark_paid(slug: str, invoice_id: str, paid_via: str = "",
               founder_rep: str = "") -> dict:
    idx = _load_index(slug)
    entry = next((i for i in idx if i.get("id") == invoice_id), None)
    if not entry:
        return {"ok": False, "error": "invoice_not_found"}
    entry["status"] = "paid"
    entry["paid_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    entry["paid_via"] = paid_via
    _save_index(slug, idx)
    try:
        from audit import append as audit_append
        audit_append(slug, founder_rep or "founder", "invoice_paid",
                     target_type="invoice", target_id=invoice_id,
                     payload={"paid_via": paid_via, "rep": entry.get("rep")})
    except Exception:
        pass
    return {"ok": True, "invoice": entry}


def request_early_payout(slug: str, rep: str) -> dict:
    """Closer-side request — generates a partial-period invoice through today."""
    return generate_invoice(slug, rep, early_payout=True)


# ── Monthly auto-fire (called by a background thread in server.py) ─────────

def maybe_generate_monthly(slug: str) -> dict:
    """Generate the previous month's invoices if we haven't yet. Idempotent —
    re-run safe. Returns {generated_count, period}."""
    today = datetime.date.today()
    # Previous month
    if today.month == 1:
        period = f"{today.year - 1:04d}-12"
    else:
        period = f"{today.year:04d}-{today.month - 1:02d}"
    idx = _load_index(slug)
    # If we already have any non-early invoices for that period, skip.
    has = any(i for i in idx
              if i.get("period") == period and not i.get("early_payout"))
    if has:
        return {"generated_count": 0, "period": period, "skipped": "already_done"}
    results = generate_all_for_period(slug, period=period)
    return {"generated_count": sum(1 for r in results if r.get("ok")),
            "period": period}


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 server/invoices.py generate <bullpen> <rep> [period]")
        print("  python3 server/invoices.py generate-all <bullpen> [period]")
        print("  python3 server/invoices.py list <bullpen> [rep]")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "generate":
        r = generate_invoice(sys.argv[2], sys.argv[3],
                              period=sys.argv[4] if len(sys.argv) > 4 else None)
        print(json.dumps(r, indent=2))
    elif cmd == "generate-all":
        rs = generate_all_for_period(sys.argv[2],
                                       period=sys.argv[3] if len(sys.argv) > 3 else None)
        for r in rs:
            print(json.dumps(r, indent=2))
    elif cmd == "list":
        rep = sys.argv[3] if len(sys.argv) > 3 else None
        for inv in list_invoices(sys.argv[2], rep=rep):
            print(f"  {inv['id']:50}  {inv['status']:6}  {inv.get('rev_total', 0):>10}  {inv.get('commission_total') or '—'}")
    else:
        print(f"unknown: {cmd}"); sys.exit(1)
