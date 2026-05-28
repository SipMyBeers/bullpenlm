"""1099-NEC prep CSV exporter.

Scans the audit chain for commission-paid events per closer for a given
calendar year, and emits a CSV the operator hands to their CPA for IRS
1099-NEC filing.

This module does NOT custody funds, route payments, or file forms with
the IRS. It is read-only over the audit chain. The platform's role:
make the operator's year-end tax prep trivial — not be the tax filer.

Payment recording lives in server/commissions.py (existing). This module
projects from the audit chain so it can't drift from the canonical
record.

Event kinds consumed (commissions.py emits these on actual payout):
    commission_paid    — operator marked commission as settled
    pilot_paid         — pilot contract payment received

CSV columns:
    closer_rep          — internal rep name
    closer_legal_name   — from W-9
    closer_address      — from W-9
    tin_sha256          — hashed TIN (operator looks up raw value out-of-band)
    federal_tax_class   — from W-9
    total_paid_usd      — sum of commission + pilot payments in the year
    payments_count      — number of payouts
    first_payment_date  — earliest payment in the year
    last_payment_date   — latest payment in the year
    rails_used          — semicolon-separated list of payment rails

Only closers paid $600+ in the year need a 1099-NEC, but the CSV
includes everyone for transparency. The CPA filters.
"""
from __future__ import annotations
import csv
import datetime
import io
from pathlib import Path
from typing import Optional

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


def _year_bounds(year: int) -> tuple[datetime.datetime, datetime.datetime]:
    return (datetime.datetime(year, 1, 1),
            datetime.datetime(year + 1, 1, 1))


def collect_payments(bullpen: str, year: int) -> dict[str, dict]:
    """Walk the audit chain and return per-rep payment aggregates."""
    try:
        from audit import iter_all
    except Exception:
        return {}

    start, end = _year_bounds(year)
    by_rep: dict[str, dict] = {}

    for ev in iter_all(bullpen):
        if ev.get("kind") not in ("commission_paid", "pilot_paid"):
            continue
        ts = ev.get("ts")
        if not ts:
            continue
        try:
            dt = datetime.datetime.fromisoformat(ts)
        except Exception:
            continue
        if not (start <= dt < end):
            continue
        payload = ev.get("payload") or {}
        rep = payload.get("closer") or payload.get("rep") or ev.get("actor")
        if not rep:
            continue
        amount = float(payload.get("amount") or payload.get("amount_usd") or 0)
        rail = payload.get("rail") or payload.get("payment_rail") or "unspecified"

        slot = by_rep.setdefault(rep, {
            "total_paid_usd": 0.0,
            "payments_count": 0,
            "first_payment_date": None,
            "last_payment_date": None,
            "rails": set(),
        })
        slot["total_paid_usd"] += amount
        slot["payments_count"] += 1
        if slot["first_payment_date"] is None or ts < slot["first_payment_date"]:
            slot["first_payment_date"] = ts
        if slot["last_payment_date"] is None or ts > slot["last_payment_date"]:
            slot["last_payment_date"] = ts
        slot["rails"].add(rail)

    return by_rep


def generate_1099_csv(bullpen: str, year: int) -> str:
    """Build the CSV body. Returns a string ready to ship as text/csv."""
    payments = collect_payments(bullpen, year)
    # Pull W-9 info for each rep so legal_name + tin_sha256 are on the export
    w9_info: dict[str, dict] = {}
    try:
        from disclosures import get_w9
        for rep in payments:
            w9 = get_w9(bullpen, rep)
            if w9:
                w9_info[rep] = w9
    except Exception:
        pass

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "closer_rep",
        "closer_legal_name",
        "closer_business_name",
        "closer_address",
        "tin_sha256",
        "federal_tax_class",
        "total_paid_usd",
        "payments_count",
        "first_payment_date",
        "last_payment_date",
        "rails_used",
        "1099_required",
    ])
    for rep, slot in sorted(payments.items(), key=lambda kv: -kv[1]["total_paid_usd"]):
        w9 = w9_info.get(rep, {})
        addr = w9.get("address") or {}
        addr_line = ", ".join(filter(None, [
            addr.get("street"),
            addr.get("city"),
            f"{addr.get('state', '')} {addr.get('postal_code', '')}".strip(),
            addr.get("country"),
        ]))
        writer.writerow([
            rep,
            w9.get("legal_name") or "",
            w9.get("business_name") or "",
            addr_line,
            w9.get("tin_sha256") or "",
            w9.get("federal_tax_classification") or "",
            f"{slot['total_paid_usd']:.2f}",
            slot["payments_count"],
            slot["first_payment_date"] or "",
            slot["last_payment_date"] or "",
            "; ".join(sorted(slot["rails"])),
            "yes" if slot["total_paid_usd"] >= 600 else "no",
        ])

    return buf.getvalue()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 server/payouts.py <bullpen> <year>")
        sys.exit(0)
    body = generate_1099_csv(sys.argv[1], int(sys.argv[2]))
    print(body)
