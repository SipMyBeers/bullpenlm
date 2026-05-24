"""
Org-graph loader. Reads organizations/<slug>/ → returns a JSON-serializable
graph with every org, its known people, its calls, and its deals.

The trainer server uses this for /api/organizations. The post-call debrief
also uses it to find the right org folder to update.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent
ORGS_ROOT = REPO / "organizations"


def _safe_read_json(p: Path) -> Optional[dict]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def _safe_read_text(p: Path) -> str:
    return p.read_text() if p.exists() else ""


def _load_people(org_dir: Path) -> list[dict]:
    out = []
    people_dir = org_dir / "people"
    if not people_dir.exists():
        return out
    for pdir in sorted(people_dir.iterdir()):
        if not pdir.is_dir():
            continue
        person = _safe_read_json(pdir / "person.json")
        if not person:
            continue
        person.setdefault("slug", pdir.name)
        person["personality"] = _safe_read_text(pdir / "personality.md").strip()
        person["speech_profile"] = _safe_read_text(pdir / "speech_profile.md").strip()
        person["has_voice_clone"] = (pdir / "voice" / "clone_config.json").exists()
        out.append(person)
    return out


def _load_calls(org_dir: Path) -> list[dict]:
    out = []
    calls_dir = org_dir / "calls"
    if not calls_dir.exists():
        return out
    for cdir in sorted(calls_dir.iterdir(), reverse=True):
        if not cdir.is_dir():
            continue
        meta = _safe_read_json(cdir / "metadata.json") or {}
        meta["slug"] = cdir.name
        meta["has_recording"] = (cdir / "recording.wav").exists()
        meta["has_transcript"] = (cdir / "transcript.txt").exists()
        meta["summary_preview"] = _safe_read_text(cdir / "summary.md")[:240]
        out.append(meta)
    return out


def _load_deals(org_dir: Path) -> list[dict]:
    out = []
    deals_dir = org_dir / "deals"
    if not deals_dir.exists():
        return out
    for ddir in sorted(deals_dir.iterdir()):
        if not ddir.is_dir():
            continue
        deal = _safe_read_json(ddir / "deal.json")
        if not deal:
            continue
        deal.setdefault("slug", ddir.name)
        out.append(deal)
    return out


def _parse_digital(md: str) -> list[str]:
    out = []
    for ln in md.splitlines():
        ln = ln.strip()
        if ln.startswith(("- ", "* ")):
            out.append(ln[2:].strip())
    return out


def load_org(slug: str) -> Optional[dict]:
    d = ORGS_ROOT / slug
    if not d.is_dir():
        return None
    base = _safe_read_json(d / "org.json")
    if not base:
        return None
    base["slug"] = slug
    base["digital"] = _parse_digital(_safe_read_text(d / "digital.md"))
    base["pushbacks"] = [
        ln.strip() for ln in _safe_read_text(d / "pushbacks.txt").splitlines() if ln.strip()
    ]
    base["abc_md"] = _safe_read_text(d / "abc.md")
    base["signals"] = _safe_read_text(d / "signals.md")
    base["people"] = _load_people(d)
    base["calls"] = _load_calls(d)
    base["deals"] = _load_deals(d)
    return base


def load_all() -> list[dict]:
    """Compact summary for the floor — full per-org detail loaded on demand."""
    out = []
    if not ORGS_ROOT.exists():
        return out
    for d in sorted(ORGS_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
            continue
        base = _safe_read_json(d / "org.json")
        if not base:
            continue
        base["slug"] = d.name
        people_count = len(list((d / "people").iterdir())) if (d / "people").exists() else 0
        calls_count = len(list((d / "calls").iterdir())) if (d / "calls").exists() else 0
        deals_count = len(list((d / "deals").iterdir())) if (d / "deals").exists() else 0
        base["counts"] = {"people": people_count, "calls": calls_count, "deals": deals_count}
        # Surface enrichment + signal availability so the floor can rank by depth
        base["enriched"] = (d / "enriched_personality.md").exists()
        base["has_signals"] = (d / "signals.md").exists()
        out.append(base)
    return out


if __name__ == "__main__":
    import sys
    orgs = load_all()
    print(f"Loaded {len(orgs)} organizations")
    for o in orgs[:5]:
        print(f"  {o['slug']:<22} {o.get('company','?'):<28} {o.get('zone','?'):<18} people={o['counts']['people']} calls={o['counts']['calls']}")
    if len(sys.argv) > 1:
        d = load_org(sys.argv[1])
        print(json.dumps(d, indent=2)[:2000])
