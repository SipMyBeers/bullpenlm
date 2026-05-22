#!/usr/bin/env python3
"""
One-shot seeder: read the pre-extracted KillSesh prospects snapshot and
write each as an organizations/<slug>/ folder.

The snapshot lives at scripts/_killsesh_prospects.json (committed to the
repo). The original source was the PROSPECTS array in SALES_FLOOR.html;
we ran a one-time Node extraction to turn the JS literal into clean JSON.

Re-running this script merges with existing org.json so user edits aren't
clobbered.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
ORGS = REPO / "organizations"
SNAPSHOT = REPO / "scripts" / "_killsesh_prospects.json"

ORGS.mkdir(parents=True, exist_ok=True)
if not SNAPSHOT.exists():
    sys.exit(f"× snapshot missing at {SNAPSHOT}")

prospects = json.loads(SNAPSHOT.read_text())
print(f"▸ loaded {len(prospects)} prospects from {SNAPSHOT.name}")

ZONE_LABEL = {
    "end": "End Customer",
    "channel": "Channel Partner",
    "tool": "Tool Partner",
    "boutique": "Boutique Partner",
}

written = 0
for p in prospects:
    slug = p["slug"]
    d = ORGS / slug
    d.mkdir(parents=True, exist_ok=True)
    for sub in ("people", "calls", "deals"):
        (d / sub).mkdir(exist_ok=True)

    org = {
        "slug": slug,
        "company": p["company"],
        "hq": p["hq"],
        "zone": ZONE_LABEL.get(p["zone"], "End Customer"),
        "zoneCode": p["zone"],
        "what": p.get("what", ""),
        "techStack": p.get("techStack", "(unknown)"),
        "phone": p.get("phone", ""),
        "web": p.get("web", ""),
        "linkedin": p.get("linkedin"),
        "dealsInFlight": p.get("dealsInFlight", ""),
        "decisionMakers": p.get("decisionMakers", ""),
        "alreadyUsing": p.get("alreadyUsing", ""),
        "competition": p.get("competition", ""),
        "source": "killsesh-seed",
        "default_role": p.get("role", "(unknown — pending discovery)"),
        "bio": p.get("bio", ""),
        "abc": p.get("abc", {}),
    }
    org_path = d / "org.json"
    if org_path.exists():
        existing = json.loads(org_path.read_text())
        for k, v in org.items():
            existing.setdefault(k, v)
        org = existing
    org_path.write_text(json.dumps(org, indent=2) + "\n")

    # digital.md (intel bullets)
    digital_path = d / "digital.md"
    if not digital_path.exists():
        bullets = p.get("digital") or []
        lines = ["# Digital footprint", ""] + [f"- {b}" for b in bullets]
        digital_path.write_text("\n".join(lines) + "\n")

    # pushbacks.txt
    pb_path = d / "pushbacks.txt"
    if not pb_path.exists():
        pb_path.write_text("\n".join(p.get("pushbacks") or []) + "\n")

    # abc.md (call structure)
    abc_path = d / "abc.md"
    if not abc_path.exists() and p.get("abc"):
        abc = p["abc"]
        abc_md = (
            "# ABCs of the call\n\n"
            f"## A — Attention hook\n\n{abc.get('a', '')}\n\n"
            f"## B — Buy-in trigger\n\n{abc.get('b', '')}\n\n"
            f"## C — Close (the exact ask)\n\n{abc.get('c', '')}\n"
        )
        abc_path.write_text(abc_md)

    # If the seed names a specific person, scaffold them as a contact
    person_name = p.get("personName")
    if person_name:
        person_slug = re.sub(r"[^a-z0-9]+", "-", person_name.lower()).strip("-")
        pdir = d / "people" / person_slug
        pdir.mkdir(parents=True, exist_ok=True)
        person_json = pdir / "person.json"
        if not person_json.exists():
            person_json.write_text(json.dumps({
                "slug": person_slug,
                "personName": person_name,
                "role": p.get("role", ""),
                "relationship": "primary_contact",
                "bio": p.get("bio", ""),
                "say_voice": "Fred" if "Hinshaw" in person_name else "Daniel",
                "say_rate": 165,
                "discovered_from": "killsesh-seed",
                "discovered_at": "2026-05-22",
            }, indent=2) + "\n")

    written += 1

print(f"✓ wrote {written} organizations to {ORGS.relative_to(REPO)}/")
