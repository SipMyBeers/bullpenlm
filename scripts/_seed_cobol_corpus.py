#!/usr/bin/env python3
"""
Seeder: write the 30-org COBOL-modernization corpus into organizations/.
Augments (does not overwrite) the existing 24 KillSesh-prospect orgs.

Adds new industry-taxonomy fields to every org:
    industry, vertical, mainframe_systems, modernization_state,
    known_systems, regulatory_context

Re-running is idempotent — existing files are preserved, new fields are
merged into org.json without clobbering hand-edits.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
ORGS = REPO / "organizations"
CORPUS = REPO / "scripts" / "_cobol_corpus.json"


def _zone_code(label: str) -> str:
    l = label.lower()
    if "end" in l: return "end"
    if "channel" in l: return "channel"
    if "tool" in l: return "tool"
    if "boutique" in l: return "boutique"
    return "end"

if not CORPUS.exists():
    sys.exit(f"× corpus missing: {CORPUS}")

corpus = json.loads(CORPUS.read_text())
print(f"▸ loaded {len(corpus)} orgs from {CORPUS.name}")

written = 0
for entry in corpus:
    slug = entry["slug"]
    d = ORGS / slug
    d.mkdir(parents=True, exist_ok=True)
    for sub in ("people", "calls", "deals"):
        (d / sub).mkdir(exist_ok=True)

    org_path = d / "org.json"
    if org_path.exists():
        existing = json.loads(org_path.read_text())
        # Only ADD missing keys from the corpus — never overwrite
        for k, v in entry.items():
            if k not in existing or existing[k] in ("", None, "(unknown)"):
                existing[k] = v
        existing["source"] = existing.get("source") or "cobol-corpus-v1"
        org_path.write_text(json.dumps(existing, indent=2) + "\n")
    else:
        entry["source"] = "cobol-corpus-v1"
        # Ensure standard fields exist for the loader
        entry.setdefault("zoneCode", _zone_code(entry.get("zone", "End Customer")))
        org_path.write_text(json.dumps(entry, indent=2) + "\n")

    # ── digital.md ──
    digital_path = d / "digital.md"
    if not digital_path.exists() and entry.get("digital"):
        lines = ["# Digital footprint", ""] + [f"- {b}" for b in entry["digital"]]
        digital_path.write_text("\n".join(lines) + "\n")

    # ── pushbacks.txt ──
    pb_path = d / "pushbacks.txt"
    if not pb_path.exists() and entry.get("pushbacks"):
        pb_path.write_text("\n".join(entry["pushbacks"]) + "\n")

    # ── abc.md ──
    abc_path = d / "abc.md"
    if not abc_path.exists() and entry.get("abc"):
        abc = entry["abc"]
        abc_md = (
            "# ABCs of the call\n\n"
            f"## A — Attention hook\n\n{abc.get('a', '')}\n\n"
            f"## B — Buy-in trigger\n\n{abc.get('b', '')}\n\n"
            f"## C — Close (the exact ask)\n\n{abc.get('c', '')}\n"
        )
        abc_path.write_text(abc_md)

    written += 1


# Now backfill the industry taxonomy into the existing 24 orgs
print(f"\n▸ backfilling industry taxonomy into existing orgs…")

# Inference heuristics for existing orgs based on what we already know
INDUSTRY_INFERENCE = {
    # KillSesh seed slugs → industry guesses
    "rocket-software":      ("Software", "Mainframe Modernization · Tools"),
    "profound-logic":       ("Software", "IBM i / AS400 Modernization"),
    "informatik":           ("Software", "Data Migration Tools"),
    "syntax":               ("Services", "Managed IT · BFSI Outsourcing"),
    "ensono":               ("Services", "Mainframe-to-Cloud Managed"),
    "softserve":            ("Services", "Global IT Services · Modernization"),
    "epam":                 ("Services", "Engineering Services · BFSI"),
    "hexaware":             ("Services", "IT Services · BFSI"),
    "lti-mindtree":         ("Services", "IT Services · Legacy App Mod"),
    "encore":               ("Services", "Boutique · TBD"),
    "katalyst":             ("Services", "Boutique IT Consultancy"),
    "fpt-software":         ("Services", "IT Services · US-growth"),
    "enhance-it":           ("Services", "IT Staffing · Mainframe"),
    "ptg":                  ("Services", "Mainframe Consulting · Boutique"),
    "bluebird-it":          ("Services", "IT Staffing · TBD"),
    "cobol-cowboys":        ("Services", "COBOL Specialists · Famous"),
    "keyhole":              ("Services", "Custom Software · Midwest"),
    "integrative-systems":  ("Services", "AS400 / IBM i Specialists"),
    "hexaview":             ("Services", "Custom Dev · Modernization"),
    "nw-natural":           ("Utility", "Natural Gas · PUC-regulated"),
    "pacificsource":        ("Insurance", "Health · Regional"),
    "premera":              ("Insurance", "Health · BCBS Regional"),
    "symetra":              ("Insurance", "Life + Retirement"),
    "the-standard":         ("Insurance", "Group Disability + Life"),
}

MAINFRAME_INFERENCE = {
    "Software": "Customer-side z/OS / IBM i",
    "Services": "Customer-side z/OS / IBM i",
    "Insurance": "IBM z/OS",
    "Utility":   "IBM z/OS / mainframe billing",
    "Government": "IBM z/OS · MUMPS · multi-decade",
}

for d in sorted(ORGS.iterdir()):
    if not d.is_dir(): continue
    org_path = d / "org.json"
    if not org_path.exists(): continue
    org = json.loads(org_path.read_text())
    slug = d.name
    changed = False

    if "industry" not in org:
        inf = INDUSTRY_INFERENCE.get(slug)
        if inf:
            org["industry"], org["vertical"] = inf
            changed = True
    if "mainframe_systems" not in org and org.get("industry"):
        org["mainframe_systems"] = MAINFRAME_INFERENCE.get(org["industry"], "(unknown)")
        changed = True
    if "modernization_state" not in org:
        # Default — most existing orgs were KillSesh prospects = in-progress
        org["modernization_state"] = "in-progress"
        changed = True
    if changed:
        org_path.write_text(json.dumps(org, indent=2) + "\n")

print(f"✓ wrote/updated {written} new orgs · backfilled taxonomy on existing orgs")
print(f"  Total orgs in store: {len([d for d in ORGS.iterdir() if d.is_dir()])}")
