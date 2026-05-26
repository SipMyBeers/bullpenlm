"""Business docs per bullpen — pitch decks, comp plans, founder financials,
contracts, anything else that lives next to the CRM.

Each doc has a visibility level:
  - public        — anyone with the bullpen URL can read (rare; brand assets)
  - members       — any active member of this bullpen (default)
  - founder-only  — just the founder + Beers

Storage:
  bullpens/<slug>/docs/_index.json   metadata array, source of truth for
                                      visibility + display name
  bullpens/<slug>/docs/<filename>    the file itself (any extension)

API surface (called from server.py):
  list_docs(bullpen, viewer_rep)         → docs visible to viewer
  get_doc(bullpen, filename, viewer_rep) → (bytes, content_type) or None
  put_doc(bullpen, filename, body, ...)  → metadata (founder-only)
  delete_doc(bullpen, filename, viewer)  → bool (founder-only)
  set_visibility(...)                    → metadata

Visibility check uses bullpens.get_member(slug, rep) — founder-rep flag set
by bullpens.create_bullpen marks the founder. Beers (the platform owner)
isn't currently special-cased; for v0.1 he sees what the founder sees of
his own bullpens.
"""
from __future__ import annotations
import datetime
import json
import mimetypes
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"

VISIBILITIES = {"public", "members", "founder-only"}


def _docs_dir(slug: str) -> Path:
    d = BULLPENS_ROOT / slug / "docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(slug: str) -> Path:
    return _docs_dir(slug) / "_index.json"


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


def _safe_filename(name: str) -> str:
    name = (name or "").strip()
    if not name or "/" in name or ".." in name or name.startswith("."):
        raise ValueError("invalid filename")
    return name


def _viewer_role(slug: str, viewer_rep: Optional[str]) -> str:
    """Return one of 'founder', 'member', 'guest'."""
    if not viewer_rep:
        return "guest"
    try:
        from bullpens import get_bullpen, get_member
    except Exception:
        return "guest"
    bp = get_bullpen(slug) or {}
    if bp.get("founder_rep") == viewer_rep:
        return "founder"
    m = get_member(slug, viewer_rep)
    if m and m.get("status") != "removed":
        return "member"
    return "guest"


def _can_see(visibility: str, role: str) -> bool:
    if visibility == "public":
        return True
    if visibility == "members":
        return role in ("founder", "member")
    if visibility == "founder-only":
        return role == "founder"
    return False


def list_docs(bullpen: str, viewer_rep: Optional[str] = None) -> list[dict]:
    role = _viewer_role(bullpen, viewer_rep)
    idx = _load_index(bullpen)
    return [d for d in idx if _can_see(d.get("visibility", "members"), role)]


def get_doc(bullpen: str, filename: str, viewer_rep: Optional[str] = None
             ) -> Optional[tuple[bytes, str, dict]]:
    fn = _safe_filename(filename)
    role = _viewer_role(bullpen, viewer_rep)
    idx = _load_index(bullpen)
    entry = next((d for d in idx if d.get("file") == fn), None)
    if not entry:
        return None
    if not _can_see(entry.get("visibility", "members"), role):
        return None
    p = _docs_dir(bullpen) / fn
    if not p.exists():
        return None
    ctype, _ = mimetypes.guess_type(fn)
    return (p.read_bytes(), ctype or "application/octet-stream", entry)


def put_doc(bullpen: str, filename: str, body: bytes,
             title: str = "", visibility: str = "members",
             uploaded_by: str = "",
             viewer_rep: Optional[str] = None) -> dict:
    """Add or replace a doc. Founder-only. `body` is raw bytes."""
    if visibility not in VISIBILITIES:
        raise ValueError(f"visibility must be one of {VISIBILITIES}")
    role = _viewer_role(bullpen, viewer_rep or uploaded_by)
    if role != "founder":
        raise PermissionError("docs:put requires founder role")
    fn = _safe_filename(filename)
    p = _docs_dir(bullpen) / fn
    p.write_bytes(body)
    idx = _load_index(bullpen)
    existing = next((d for d in idx if d.get("file") == fn), None)
    entry = {
        "file": fn,
        "title": title or fn,
        "visibility": visibility,
        "size": len(body),
        "uploaded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "uploaded_by": uploaded_by,
    }
    if existing:
        idx.remove(existing)
    idx.append(entry)
    idx.sort(key=lambda d: d.get("uploaded_at", ""), reverse=True)
    _save_index(bullpen, idx)
    return entry


def delete_doc(bullpen: str, filename: str, viewer_rep: str) -> bool:
    role = _viewer_role(bullpen, viewer_rep)
    if role != "founder":
        raise PermissionError("docs:delete requires founder role")
    fn = _safe_filename(filename)
    idx = _load_index(bullpen)
    before = len(idx)
    idx = [d for d in idx if d.get("file") != fn]
    _save_index(bullpen, idx)
    p = _docs_dir(bullpen) / fn
    if p.exists():
        p.unlink()
    return len(idx) < before


def set_visibility(bullpen: str, filename: str, visibility: str,
                    viewer_rep: str) -> Optional[dict]:
    if visibility not in VISIBILITIES:
        raise ValueError(f"visibility must be one of {VISIBILITIES}")
    role = _viewer_role(bullpen, viewer_rep)
    if role != "founder":
        raise PermissionError("docs:set-visibility requires founder role")
    fn = _safe_filename(filename)
    idx = _load_index(bullpen)
    entry = next((d for d in idx if d.get("file") == fn), None)
    if not entry:
        return None
    entry["visibility"] = visibility
    _save_index(bullpen, idx)
    return entry
