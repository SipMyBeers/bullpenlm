"""
adapters/csv_import.py — bulk-import from any CRM export.

Drop a CSV from HubSpot, Salesforce, Pipedrive, Airtable, or hand-rolled
research. Maps columns to org folders. Idempotent — re-running merges
without clobbering hand-edits to org.json.

Default column mapping (case-insensitive, partial-match):
    name | company | account            → company
    title | role | job_title             → default_role
    industry | sector                    → (used to suggest zone)
    city + state | location | hq         → hq
    website | url | domain               → web
    phone | direct_dial                  → phone
    email                                → (creates person stub under org)
    employees | size | company_size      → size
    notes | description                  → bio
    linkedin | linkedin_url              → linkedin

Override with --map "csv_col=org_field" pairs.

Example:
    python3 -m adapters.csv_import prospects.csv
    python3 -m adapters.csv_import prospects.csv --zone "End Customer"
    python3 -m adapters.csv_import hubspot_export.csv --map "Company name=company" --map "Job Title=default_role"
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from adapters._common import slugify, write_org


# Heuristic column matchers — substring matches against lower-cased CSV headers
DEFAULT_MAP = {
    "company":         ["company", "account", "organization", "org"],
    "default_role":    ["role", "title", "job"],
    "industry":        ["industry", "sector", "vertical"],
    "hq":              ["hq", "headquarters", "location", "city", "address"],
    "web":             ["website", "url", "domain", "homepage"],
    "phone":           ["phone", "direct_dial", "direct dial", "telephone", "tel"],
    "email":           ["email", "e-mail"],
    "size":            ["employees", "size", "company size", "headcount"],
    "bio":             ["notes", "description", "about", "summary"],
    "linkedin":        ["linkedin"],
    "personName":      ["name", "contact", "first_name", "lead name"],
}


def auto_map(headers: list[str]) -> dict[str, str]:
    """Returns {target_field: csv_column}."""
    lower = {h: h.lower() for h in headers}
    out = {}
    for target, hints in DEFAULT_MAP.items():
        for h in headers:
            l = lower[h]
            if any(hint in l for hint in hints):
                out[target] = h
                break
    return out


def detect_zone(industry: str, role: str = "") -> str:
    """Best guess at zone from CSV signals."""
    text = (industry + " " + role).lower()
    if any(w in text for w in ("software", "saas", "platform", "tools")):
        return "Tool Partner"
    if any(w in text for w in ("consult", "services", "agency", "delivery")):
        return "Channel Partner"
    if any(w in text for w in ("staffing", "boutique", "freelance")):
        return "Boutique Partner"
    return "End Customer"


def import_csv(path: str, *, zone_override: str = None, map_overrides: dict = None, slug_prefix: str = "", verbose: bool = True) -> dict:
    """Import rows from a CSV → org graph.

    Returns {"count": int, "created": [slug, ...], "warnings": [str, ...]}.
    Raises ValueError on unreadable input — callers in HTTP context should catch.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"CSV not found: {p}")

    with p.open(newline="") as f:
        sample = f.read(4096); f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        rows = list(reader)
        headers = reader.fieldnames or []

    if not rows:
        raise ValueError("CSV has no rows")

    field_map = auto_map(headers)
    if map_overrides:
        field_map.update(map_overrides)

    if verbose:
        print(f"▸ loaded {len(rows)} rows from {p.name}")
        print(f"▸ column mapping detected:")
        for target, col in sorted(field_map.items()):
            print(f"    {target:<14} ← {col!r}")
        print()

    created: list[str] = []
    warnings: list[str] = []
    for row in rows:
        # Pull mapped values
        company = row.get(field_map.get("company", ""), "").strip()
        if not company:
            # Fall back to person name if no company column
            company = row.get(field_map.get("personName", ""), "").strip()
        if not company:
            continue
        slug = slug_prefix + slugify(company)
        industry = row.get(field_map.get("industry", ""), "").strip()
        role = row.get(field_map.get("default_role", ""), "").strip()
        zone = zone_override or detect_zone(industry, role)

        org = {
            "slug": slug,
            "company": company,
            "hq": row.get(field_map.get("hq", ""), "").strip() or "(unknown)",
            "size": row.get(field_map.get("size", ""), "").strip() or "(unknown)",
            "zone": zone,
            "what": row.get(field_map.get("bio", ""), "").strip() or f"{industry} company" if industry else "(unknown)",
            "phone": row.get(field_map.get("phone", ""), "").strip() or "(unknown)",
            "web": row.get(field_map.get("web", ""), "").strip() or "(unknown)",
            "linkedin": row.get(field_map.get("linkedin", ""), "").strip() or None,
            "default_role": role or "(unknown — pending discovery)",
            "industry": industry,
            "source": "csv-import",
        }
        bio = row.get(field_map.get("bio", ""), "").strip()
        digital_lines = []
        if industry: digital_lines.append(f"Industry: {industry}")
        if bio:      digital_lines.append(bio[:240])

        d = write_org(slug, org, digital=digital_lines)

        # If the row names a specific person + has email/role, scaffold them
        person_name = row.get(field_map.get("personName", ""), "").strip()
        email = row.get(field_map.get("email", ""), "").strip()
        if person_name and person_name.lower() != company.lower():
            pslug = slugify(person_name)
            pdir = d / "people" / pslug
            if not pdir.exists():
                pdir.mkdir(parents=True, exist_ok=True)
                (pdir / "person.json").write_text(json.dumps({
                    "slug": pslug,
                    "personName": person_name,
                    "role": role or "(unknown)",
                    "email": email or None,
                    "relationship": "primary_contact",
                    "discovered_from": "csv-import",
                }, indent=2) + "\n")

        created.append(slug)

    if verbose:
        print(f"✓ imported {len(created)} organizations")
    return {"count": len(created), "created": created, "warnings": warnings}


def parse_map_overrides(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            sys.exit(f"× bad --map: {pair} (expected 'col_name=target_field')")
        col, tgt = pair.split("=", 1)
        out[tgt.strip()] = col.strip()
    return out


def main():
    ap = argparse.ArgumentParser(description="Bulk import a CSV → organizations/")
    ap.add_argument("path", help="Path to the CSV file")
    ap.add_argument("--zone", help="Override the auto-detected zone for all rows")
    ap.add_argument("--map", dest="map_pairs", action="append",
                    help="Override column mapping: --map 'Company name=company' (repeatable)")
    ap.add_argument("--slug-prefix", default="", help="Prefix every slug (useful for namespacing imports)")
    args = ap.parse_args()
    import_csv(args.path,
               zone_override=args.zone,
               map_overrides=parse_map_overrides(args.map_pairs),
               slug_prefix=args.slug_prefix)


if __name__ == "__main__":
    main()
