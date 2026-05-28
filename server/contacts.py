"""Contacts — the people you actually call inside each prospect org.

Reads existing data from organizations/<slug>/people/<contact_slug>/person.json
(the format the trainer already produces) AND lets reps add new contacts
during the call without leaving the app.

Contact schema:
  slug, personName, role, email, phone, linkedin, bio, relationship,
  notes (free text — markdown), tags, created_at, created_by

A contact belongs to ONE org. A deal belongs to ONE org. So the bridge
is org_slug. We don't carry deal_id on contacts — instead the Deal page
shows every contact under the same org_slug.
"""
from __future__ import annotations
import datetime
import json
import re
from pathlib import Path
from typing import Optional

from audit import append as audit_append

from paths import DATA_DIR as REPO
ORGS_ROOT = REPO / "organizations"


def _org_dir(org_slug: str) -> Path:
    return ORGS_ROOT / org_slug


def _people_dir(org_slug: str) -> Path:
    d = _org_dir(org_slug) / "people"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _contact_dir(org_slug: str, contact_slug: str) -> Path:
    d = _people_dir(org_slug) / contact_slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(name: str) -> str:
    return (re.sub(r"[^a-z0-9\-]", "-", name.lower().strip())[:48].strip("-")
            or "contact-" + datetime.datetime.now().strftime("%H%M%S"))


# ── Read ─────────────────────────────────────────────────────────────────

def list_for_org(org_slug: str) -> list[dict]:
    """All contacts under an org. Includes both seeded (person.json) and
    newly-created ones."""
    pdir = _people_dir(org_slug)
    if not pdir.exists():
        return []
    out = []
    for child in sorted(pdir.iterdir()):
        if not child.is_dir():
            continue
        f = child / "person.json"
        if not f.exists():
            continue
        try:
            c = json.loads(f.read_text())
        except Exception:
            continue
        c["slug"] = c.get("slug") or child.name
        c["org_slug"] = org_slug
        out.append(c)
    return out


def get(org_slug: str, contact_slug: str) -> Optional[dict]:
    f = _contact_dir(org_slug, contact_slug) / "person.json"
    if not f.exists():
        return None
    try:
        c = json.loads(f.read_text())
        c["slug"] = c.get("slug") or contact_slug
        c["org_slug"] = org_slug
        return c
    except Exception:
        return None


# ── Write ────────────────────────────────────────────────────────────────

def create(bullpen: str, org_slug: str, person_name: str,
           role: str = "", email: str = "", phone: str = "",
           linkedin: str = "", bio: str = "", notes: str = "",
           tags: Optional[list] = None, relationship: str = "contact",
           created_by: str = "self") -> dict:
    """Create a contact under an org. Idempotent on slug collisions
    (returns the existing record)."""
    if not person_name.strip():
        raise ValueError("missing_person_name")
    if not _org_dir(org_slug).exists():
        raise ValueError("org_not_found")
    contact_slug = _slug(person_name)
    f = _contact_dir(org_slug, contact_slug) / "person.json"
    if f.exists():
        return get(org_slug, contact_slug) or {}
    rec = {
        "slug": contact_slug,
        "personName": person_name.strip(),
        "role": role.strip(),
        "email": email.strip(),
        "phone": phone.strip(),
        "linkedin": linkedin.strip(),
        "bio": bio.strip(),
        "notes": notes.strip(),
        "tags": list(tags or []),
        "relationship": relationship,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "created_by": created_by,
        "discovered_from": "in_app",
    }
    f.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    audit_append(bullpen, created_by, "contact_created",
                 target_type="contact", target_id=f"{org_slug}/{contact_slug}",
                 payload={"name": person_name.strip(), "org": org_slug})
    rec["org_slug"] = org_slug
    return rec


def update(bullpen: str, org_slug: str, contact_slug: str,
           updates: dict, actor: str = "self") -> Optional[dict]:
    """Patch a contact. Only allow-listed fields are writable."""
    ALLOWED = {"role", "email", "phone", "linkedin", "bio", "notes", "tags",
               "relationship", "personName"}
    rec = get(org_slug, contact_slug)
    if not rec:
        return None
    changed = {}
    for k, v in (updates or {}).items():
        if k not in ALLOWED:
            continue
        if rec.get(k) != v:
            rec[k] = v
            changed[k] = v
    if not changed:
        return rec
    rec["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    (_contact_dir(org_slug, contact_slug) / "person.json").write_text(
        json.dumps({k: v for k, v in rec.items() if k != "org_slug"}, indent=2,
                   ensure_ascii=False) + "\n")
    audit_append(bullpen, actor, "contact_updated",
                 target_type="contact", target_id=f"{org_slug}/{contact_slug}",
                 payload={"changed": list(changed.keys())})
    rec["org_slug"] = org_slug
    return rec


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 server/contacts.py <org-slug>")
        sys.exit(0)
    for c in list_for_org(sys.argv[1]):
        print(f"  {c['slug']:30}  {c.get('personName',''):30}  {c.get('role','')[:50]}")
