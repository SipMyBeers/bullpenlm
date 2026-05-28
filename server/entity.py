"""Operator entity profile.

Every bullpen has ONE operator entity — the legal party that contracts
with closers. Could be an LLC, sole prop, or individual person. Every
generated legal doc renders with this entity, never with "Beers Labs LLC"
by default.

Storage:
    bullpens/<slug>/entity.json

Schema:
    {
        "kind": "llc" | "sole_prop" | "individual",
        "legal_name": "KillSesh Industries LLC",
        "ein_or_ssn_sha256": "...",   # one-way hash; raw value NEVER stored
        "address": {
            "street": "...",
            "city": "...",
            "state": "OR",           # 2-letter for US, country code otherwise
            "postal_code": "...",
            "country": "US"
        },
        "jurisdiction": "US-OR",     # governing law for closer agreements
        "contact_email": "...",
        "contact_phone": "...",
        "counsel_reviewed_at": "2026-05-26" | null,
        "counsel_name": "..." | null,
        "created_at": "...",
        "updated_at": "..."
    }

Critical design choice: we hash the EIN/SSN with a per-bullpen salt and
NEVER store the raw value. The raw value belongs on the signed PDF
(operator types it once at render time) and in the operator's own
accounting system. The platform doesn't custody it.
"""
from __future__ import annotations
import datetime
import hashlib
import hmac
import json
import secrets
from pathlib import Path
from typing import Optional

from audit import append as audit_append

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


def _entity_path(bullpen: str) -> Path:
    return BULLPENS_ROOT / bullpen / "entity.json"


def _salt_path(bullpen: str) -> Path:
    """Per-bullpen salt for EIN/SSN hashing. Stored separately from
    entity.json so a leak of one file doesn't enable a rainbow lookup."""
    return BULLPENS_ROOT / bullpen / ".entity-salt"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _ensure_salt(bullpen: str) -> bytes:
    p = _salt_path(bullpen)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(secrets.token_bytes(32))
        try:
            p.chmod(0o600)
        except Exception:
            pass
    return p.read_bytes()


def _hash_tin(bullpen: str, raw_ein_or_ssn: str) -> str:
    """One-way hash of EIN/SSN. Raw value never persisted."""
    salt = _ensure_salt(bullpen)
    return hmac.new(salt, raw_ein_or_ssn.encode("utf-8"), hashlib.sha256).hexdigest()


# ── Read / write ─────────────────────────────────────────────────────────

def get_entity(bullpen: str) -> Optional[dict]:
    """Return the operator entity profile, or None if not set up."""
    p = _entity_path(bullpen)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def set_entity(
    bullpen: str,
    *,
    kind: str,
    legal_name: str,
    raw_ein_or_ssn: Optional[str],
    address: dict,
    jurisdiction: str,
    contact_email: str,
    contact_phone: Optional[str] = None,
    actor: str = "operator",
) -> dict:
    """Set or update the operator entity profile. Validates required
    fields; rejects non-US jurisdictions (Phase 0.5 scope is US-only).

    raw_ein_or_ssn is hashed immediately and discarded. Caller must not
    log it, persist it, or pass it onward.
    """
    if kind not in ("llc", "sole_prop", "individual"):
        raise ValueError(f"invalid entity kind: {kind!r}")
    if not legal_name or not legal_name.strip():
        raise ValueError("legal_name is required")
    if address.get("country") != "US":
        raise ValueError("Phase 0.5: US-only entities supported")
    if not jurisdiction or not jurisdiction.startswith("US-"):
        raise ValueError("jurisdiction must be US-XX (e.g. US-OR)")
    if not contact_email or "@" not in contact_email:
        raise ValueError("contact_email is required")

    existing = get_entity(bullpen) or {}
    now = _now()

    entity = {
        "kind": kind,
        "legal_name": legal_name.strip(),
        "ein_or_ssn_sha256": (
            _hash_tin(bullpen, raw_ein_or_ssn)
            if raw_ein_or_ssn
            else existing.get("ein_or_ssn_sha256")
        ),
        "address": {
            "street": address.get("street", "").strip(),
            "city": address.get("city", "").strip(),
            "state": address.get("state", "").strip().upper(),
            "postal_code": address.get("postal_code", "").strip(),
            "country": "US",
        },
        "jurisdiction": jurisdiction,
        "contact_email": contact_email.strip(),
        "contact_phone": (contact_phone or "").strip() or None,
        "counsel_reviewed_at": existing.get("counsel_reviewed_at"),
        "counsel_name": existing.get("counsel_name"),
        "created_at": existing.get("created_at", now),
        "updated_at": now,
    }

    p = _entity_path(bullpen)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entity, indent=2) + "\n")

    audit_append(bullpen, kind="entity_set", actor=actor, payload={
        "entity_kind": entity["kind"],
        "legal_name": entity["legal_name"],
        "jurisdiction": entity["jurisdiction"],
        "had_tin": bool(raw_ein_or_ssn),
    })

    return entity


def record_counsel_review(
    bullpen: str,
    *,
    counsel_name: str,
    reviewed_at: Optional[str] = None,
    actor: str = "operator",
) -> dict:
    """Mark the operator's entity as counsel-reviewed.

    This is the operator's own counsel reviewing the operator's own
    legal posture — distinct from `docs/legal/COUNSEL_REVIEW.md` which
    is BullpenLM's platform-wide review.
    """
    entity = get_entity(bullpen)
    if not entity:
        raise ValueError(f"no entity profile yet for {bullpen}")
    entity["counsel_reviewed_at"] = reviewed_at or datetime.date.today().isoformat()
    entity["counsel_name"] = counsel_name.strip()
    entity["updated_at"] = _now()
    _entity_path(bullpen).write_text(json.dumps(entity, indent=2) + "\n")
    audit_append(bullpen, kind="entity_counsel_reviewed", actor=actor, payload={
        "counsel_name": counsel_name,
        "reviewed_at": entity["counsel_reviewed_at"],
    })
    return entity


# ── Template substitution ────────────────────────────────────────────────

def template_vars(bullpen: str) -> dict:
    """Return the {{var}} substitution dict for legal templates.

    These are the canonical operator-side substitutions. If a template
    references {{operator_entity}}, {{operator_jurisdiction}}, etc.,
    those resolve here. If the entity isn't set up, returns an empty
    dict — the template renderer should refuse to render in that case.
    """
    e = get_entity(bullpen)
    if not e:
        return {}
    addr = e.get("address") or {}
    addr_line = ", ".join(filter(None, [
        addr.get("street"),
        addr.get("city"),
        f"{addr.get('state', '')} {addr.get('postal_code', '')}".strip(),
        addr.get("country"),
    ]))
    return {
        "operator_entity": e["legal_name"],
        "operator_entity_kind": {
            "llc": "limited liability company",
            "sole_prop": "sole proprietorship",
            "individual": "individual",
        }.get(e["kind"], e["kind"]),
        "operator_address": addr_line,
        "operator_state": addr.get("state", ""),
        "operator_jurisdiction": e["jurisdiction"],
        "operator_email": e["contact_email"],
        "operator_phone": e.get("contact_phone") or "",
    }


def is_setup(bullpen: str) -> bool:
    """True if the entity profile is sufficient to render legal docs."""
    e = get_entity(bullpen)
    if not e:
        return False
    required = ["legal_name", "address", "jurisdiction", "contact_email"]
    if not all(e.get(k) for k in required):
        return False
    addr = e.get("address") or {}
    return all(addr.get(k) for k in ["street", "city", "state", "postal_code"])
