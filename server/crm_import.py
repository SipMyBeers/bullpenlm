"""CRM CSV import wizard.

Drop a CSV (HubSpot export, Salesforce report, Google Sheet, Notion DB,
hand-built list — anything) → auto-detect columns → preview → confirm
→ batch-create organizations + contacts + (optionally) deals.

Lowest-common-denominator format chosen deliberately: every CRM exports
CSV; no per-vendor API integration to maintain.

Column detection
================

  We try a long list of canonical field names matched case-insensitively
  + whitespace-normalized:

    person_name:   name, full name, contact, person, contact name
    first_name:    first name, given name, first
    last_name:     last name, surname, family name, last
    email:         email, email address, e-mail, work email, primary email
    phone:         phone, phone number, mobile, work phone, direct
    company:       company, organization, account, employer, account name
    title:         title, job title, role, position
    stage:         stage, status, pipeline stage, deal stage
    amount:        amount, deal value, mrr, arr, value, opportunity amount
    linkedin:      linkedin, linkedin url
    notes:         notes, note, comments, description

  Operator can also manually override any mapping on the preview screen.

Pipeline stage normalization
============================

  We snap incoming stage strings to BullpenLM's default pipeline
  stages (lead/contacted/qualified/demo/pilot/won/lost) by fuzzy match
  against substrings. Anything unrecognized lands in `lead`.

Idempotence
===========

  Org slug = kebab-case(company name). Contact slug = kebab-case(person
  name). If `organizations/<org-slug>/people/<contact-slug>/person.json`
  exists, the import preserves the existing record and counts it as
  "duplicate". Operator can choose force-update mode to overwrite.

Audit
=====

  Per-row: `crm_imported` event with payload {contact_slug, org_slug, ...}
  Per-import-run: `crm_import_run` summary event with totals.
"""
from __future__ import annotations
import csv
import datetime
import io
import json
import re
from pathlib import Path
from typing import Optional, Iterable

REPO = Path(__file__).parent.parent
ORGS_ROOT = REPO / "organizations"
BULLPENS_ROOT = REPO / "bullpens"


# ── Column heuristics ────────────────────────────────────────────────────

# Each canonical field maps to a list of header-fragment substrings.
# Order matters: more specific matches first.
FIELD_HEURISTICS: dict[str, list[str]] = {
    "first_name": ["first name", "given name", "first_name", "fname", "first"],
    "last_name": ["last name", "surname", "family name", "last_name", "lname", "last"],
    "person_name": ["full name", "person name", "contact name", "full_name", "name", "contact", "person"],
    "email": ["email address", "email_address", "work email", "primary email", "e-mail", "email"],
    "phone": ["mobile phone", "work phone", "phone number", "phone_number", "mobile", "phone", "tel", "direct"],
    "linkedin": ["linkedin url", "linkedin_url", "linkedin"],
    "company": ["company name", "account name", "company_name", "organization", "company", "account", "employer"],
    "title": ["job title", "job_title", "title", "position", "role"],
    "stage": ["pipeline stage", "deal stage", "deal_stage", "stage", "status"],
    "amount": ["opportunity amount", "deal value", "deal_value", "amount", "mrr", "arr", "value", "size"],
    "notes": ["notes", "note", "comment", "comments", "description"],
}


# Default pipeline stage names → canonical IDs (match the pipeline.py defaults)
STAGE_NORMALIZATIONS = [
    (["closed won", "won", "close-won", "closed-won"], "won"),
    (["closed lost", "lost", "close-lost", "closed-lost"], "lost"),
    (["pilot", "trial", "evaluation", "poc"], "pilot"),
    (["demo", "presentation", "preso"], "demo"),
    (["qualified", "discovery", "scoping"], "qualified"),
    (["contacted", "outreach", "connected", "engaged"], "contacted"),
    (["new", "lead", "open", "prospecting", "raw"], "lead"),
]


def normalize_stage(s: str) -> str:
    s = (s or "").strip().lower()
    if not s:
        return "lead"
    for fragments, canonical in STAGE_NORMALIZATIONS:
        for f in fragments:
            if f in s:
                return canonical
    return "lead"


def detect_columns(headers: list[str]) -> dict[str, Optional[str]]:
    """Map canonical field → header name (or None). First match wins per
    canonical field; one header can only be claimed by one field."""
    headers = [h or "" for h in headers]
    normalized = [(i, h, h.strip().lower()) for i, h in enumerate(headers)]
    out: dict[str, Optional[str]] = {f: None for f in FIELD_HEURISTICS}
    claimed: set[int] = set()
    for field, fragments in FIELD_HEURISTICS.items():
        for frag in fragments:
            for i, h, low in normalized:
                if i in claimed:
                    continue
                if frag in low:
                    out[field] = h
                    claimed.add(i)
                    break
            if out[field]:
                break
    return out


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:64]


def _ensure_org(org_slug: str, company_name: str, *, vertical: str = "",
                hq: str = "") -> dict:
    """Idempotent org creation. Writes organizations/<slug>/org.json."""
    d = ORGS_ROOT / org_slug
    d.mkdir(parents=True, exist_ok=True)
    org_file = d / "org.json"
    if org_file.exists():
        try:
            return json.loads(org_file.read_text())
        except Exception:
            pass
    rec = {
        "slug": org_slug,
        "name": company_name.strip(),
        "vertical": vertical.strip(),
        "hq": hq.strip(),
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "created_via": "crm_import",
    }
    org_file.write_text(json.dumps(rec, indent=2))
    return rec


def _combine_name(row: dict, cols: dict[str, str]) -> str:
    if cols.get("person_name") and row.get(cols["person_name"]):
        return row[cols["person_name"]].strip()
    parts = []
    if cols.get("first_name"):
        parts.append((row.get(cols["first_name"]) or "").strip())
    if cols.get("last_name"):
        parts.append((row.get(cols["last_name"]) or "").strip())
    return " ".join(p for p in parts if p).strip()


# ── Public API ────────────────────────────────────────────────────────────

def parse_csv(text: str) -> tuple[list[str], list[dict]]:
    """Parse CSV text → (headers, rows-as-dicts). Tolerant of BOMs,
    quote variations, encoding artifacts."""
    text = text.lstrip("﻿")  # BOM
    reader = csv.DictReader(io.StringIO(text))
    headers = list(reader.fieldnames or [])
    rows = []
    for row in reader:
        # Strip whitespace from every value, skip empty rows
        clean = {k: (v or "").strip() for k, v in row.items() if k}
        if any(v for v in clean.values()):
            rows.append(clean)
    return headers, rows


def preview(
    text: str,
    *,
    column_override: Optional[dict[str, str]] = None,
    n: int = 10,
) -> dict:
    """Parse CSV + show the first N rows mapped through detected columns.
    No writes. Caller shows this then asks confirmation."""
    headers, rows = parse_csv(text)
    detected = detect_columns(headers)
    cols = {**detected, **(column_override or {})}
    sample = []
    for row in rows[:n]:
        name = _combine_name(row, cols)
        company = row.get(cols.get("company") or "", "").strip()
        sample.append({
            "person_name": name,
            "company": company,
            "title":   row.get(cols.get("title") or "", "").strip(),
            "email":   row.get(cols.get("email") or "", "").strip(),
            "phone":   row.get(cols.get("phone") or "", "").strip(),
            "linkedin": row.get(cols.get("linkedin") or "", "").strip(),
            "stage_raw": row.get(cols.get("stage") or "", "").strip(),
            "stage":   normalize_stage(row.get(cols.get("stage") or "", "")),
            "amount":  row.get(cols.get("amount") or "", "").strip(),
            "notes":   (row.get(cols.get("notes") or "", "") or "").strip(),
        })
    return {
        "headers": headers,
        "detected_columns": detected,
        "active_columns": cols,
        "row_count_total": len(rows),
        "sample": sample,
    }


def run_import(
    bullpen: str,
    text: str,
    *,
    column_override: Optional[dict[str, str]] = None,
    create_deals: bool = True,
    default_owner: str = "self",
    actor: str = "operator",
    force_update: bool = False,
) -> dict:
    """Actually ingest the CSV. Returns counts + per-row outcomes."""
    headers, rows = parse_csv(text)
    detected = detect_columns(headers)
    cols = {**detected, **(column_override or {})}

    from contacts import create as create_contact, get as get_contact
    from deals import create as create_deal

    try:
        from audit import append as audit_append
    except Exception:
        audit_append = lambda *a, **k: None

    stats = {
        "rows": len(rows),
        "orgs_created": 0,
        "orgs_existing": 0,
        "contacts_created": 0,
        "contacts_existing": 0,
        "deals_created": 0,
        "rows_skipped": 0,
    }
    outcomes: list[dict] = []

    for i, row in enumerate(rows):
        person_name = _combine_name(row, cols)
        company = (row.get(cols.get("company") or "", "") or "").strip()
        # Skip rows with no person_name AND no company — nothing to anchor on
        if not person_name and not company:
            stats["rows_skipped"] += 1
            outcomes.append({"row": i, "status": "skipped", "reason": "no name or company"})
            continue
        # If no company, anchor the org slug on the person's name
        org_label = company or person_name
        org_slug = _slugify(org_label)
        if not org_slug:
            stats["rows_skipped"] += 1
            outcomes.append({"row": i, "status": "skipped", "reason": "no usable slug"})
            continue

        # Org
        existed_org = (ORGS_ROOT / org_slug / "org.json").exists()
        _ensure_org(org_slug, org_label)
        if existed_org:
            stats["orgs_existing"] += 1
        else:
            stats["orgs_created"] += 1

        # Contact (only if we have a person_name)
        contact_slug = None
        if person_name:
            existing = get_contact(org_slug, _slugify(person_name))
            if existing and not force_update:
                stats["contacts_existing"] += 1
                contact_slug = existing.get("slug")
            else:
                try:
                    rec = create_contact(
                        bullpen, org_slug, person_name,
                        role=row.get(cols.get("title") or "", "").strip(),
                        email=row.get(cols.get("email") or "", "").strip(),
                        phone=row.get(cols.get("phone") or "", "").strip(),
                        linkedin=row.get(cols.get("linkedin") or "", "").strip(),
                        notes=row.get(cols.get("notes") or "", "").strip(),
                        relationship="contact",
                        created_by=actor,
                    )
                    contact_slug = rec.get("slug")
                    stats["contacts_created"] += 1
                except Exception as e:
                    outcomes.append({"row": i, "status": "contact_failed", "reason": str(e)})
                    continue

        # Deal — only if create_deals is on AND we have a stage column OR amount
        deal_id = None
        if create_deals and (cols.get("stage") or cols.get("amount")):
            stage = normalize_stage(row.get(cols.get("stage") or "", ""))
            amount_str = (row.get(cols.get("amount") or "", "") or "").strip()
            # Parse amount — strip $, comma, currency suffixes
            amount = 0.0
            try:
                cleaned = re.sub(r"[^0-9.\-]", "", amount_str)
                if cleaned:
                    amount = float(cleaned)
            except Exception:
                amount = 0.0
            if stage and (stage != "lead" or amount > 0):
                try:
                    deal = create_deal(
                        bullpen, org_slug, default_owner,
                        amount=amount, stage_id=stage,
                        notes=f"CRM-imported: {row.get(cols.get('notes') or '', '')[:200]}",
                    )
                    deal_id = deal.get("id")
                    stats["deals_created"] += 1
                except Exception as e:
                    outcomes.append({"row": i, "status": "deal_failed", "reason": str(e)})

        outcomes.append({
            "row": i, "status": "ok",
            "org_slug": org_slug, "contact_slug": contact_slug, "deal_id": deal_id,
        })

    # Audit summary
    audit_append(bullpen, actor, "crm_import_run",
                 target_type="crm", target_id="csv",
                 payload={"stats": stats, "headers": headers, "active_columns": cols})

    return {"stats": stats, "outcomes": outcomes, "active_columns": cols}


# ── Quick CRM aggregate (for cockpit tile) ───────────────────────────────

def aggregate(bullpen: str) -> dict:
    """Quick rollup of CRM state across the whole platform / this bullpen."""
    # Orgs live globally
    org_count = 0
    contact_count = 0
    if ORGS_ROOT.exists():
        for od in ORGS_ROOT.iterdir():
            if not od.is_dir(): continue
            if (od / "org.json").exists():
                org_count += 1
            people_dir = od / "people"
            if people_dir.exists():
                contact_count += sum(1 for p in people_dir.iterdir()
                                      if p.is_dir() and (p / "person.json").exists())
    # Deals are bullpen-scoped
    deal_count = 0
    try:
        from deals import list_all as deals_list_all
        deal_count = len(deals_list_all(bullpen) or [])
    except Exception:
        pass
    return {
        "orgs": org_count,
        "contacts": contact_count,
        "deals": deal_count,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python3 server/crm_import.py preview <bullpen> < input.csv")
        print("  python3 server/crm_import.py run <bullpen> [--no-deals] < input.csv")
        print("  python3 server/crm_import.py stats <bullpen>")
        sys.exit(0)
    cmd = sys.argv[1]
    bp = sys.argv[2]
    if cmd == "stats":
        print(json.dumps(aggregate(bp), indent=2)); sys.exit(0)
    text = sys.stdin.read()
    if cmd == "preview":
        print(json.dumps(preview(text), indent=2))
    elif cmd == "run":
        create_deals = "--no-deals" not in sys.argv
        print(json.dumps(run_import(bp, text, create_deals=create_deals, actor="cli"), indent=2))
    else:
        print(f"× unknown: {cmd}"); sys.exit(1)
