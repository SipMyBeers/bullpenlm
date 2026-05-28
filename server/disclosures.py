"""Disclosure acceptance + W-9 collection.

Required click-through screens for closers and operators before any
live work happens. Acceptances hash-chain into the audit log; the
acceptance record is the proof the platform held up its disclosure
obligations.

Two disclosure surfaces:

  closer-disclosure   — Closer reads + clicks before signing the
                        Closer Agreement. Acknowledges that BullpenLM
                        is software, not an employer; commission comes
                        from the operator; remedy for non-payment is
                        against the operator, not the platform.

  operator-tos        — Operator reads + clicks before they can invite
                        any closer. Acknowledges they are the
                        counterparty, they carry the legal/tax/
                        compliance burden, and the platform is on no
                        contracts between them and their closers.

Storage:
  bullpens/<slug>/disclosures/<closer>/closer-disclosure.json
  bullpens/<slug>/disclosures/operator-tos.json
  bullpens/<slug>/w9/<closer>.json   (or .pdf — we accept either; the
                                      raw TIN is hashed, not stored)
"""
from __future__ import annotations
import datetime
import hashlib
import json
from pathlib import Path
from typing import Optional

from audit import append as audit_append

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


def _disclosure_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "disclosures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _w9_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "w9"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_template(name: str) -> str:
    p = REPO / "templates" / "legal" / f"{name}.md"
    if not p.exists():
        return ""
    return p.read_text()


# ── Closer Disclosure ────────────────────────────────────────────────────

def accept_closer_disclosure(
    bullpen: str,
    closer: str,
    *,
    closer_legal_name: str,
    typed_signature: str,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """Record a closer's acceptance of the Closer Disclosure.

    The acceptance bundles the SHA of the disclosure version they saw,
    so if the disclosure text changes, the old acceptance no longer
    matches and the closer re-accepts the new text.

    `typed_signature` is a hard-typed name match against
    `closer_legal_name` — same string, no caret marks, no scribble. The
    UI should require an exact match before submitting.
    """
    if typed_signature.strip().lower() != closer_legal_name.strip().lower():
        raise ValueError("typed signature does not match legal name")

    text = _read_template("closer-disclosure")
    if not text:
        raise RuntimeError("closer-disclosure template missing")
    text_sha = _sha256(text)

    record = {
        "closer": closer,
        "closer_legal_name": closer_legal_name.strip(),
        "typed_signature": typed_signature.strip(),
        "disclosure_sha256": text_sha,
        "accepted_at": _now(),
        "user_agent": user_agent,
        "ip": ip,
    }

    p = _disclosure_dir(bullpen) / closer / "closer-disclosure.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=2) + "\n")

    audit_append(bullpen, kind="closer_disclosure_accepted", actor=closer, payload={
        "disclosure_sha256": text_sha,
    })

    return record


def has_accepted_closer_disclosure(bullpen: str, closer: str) -> bool:
    """True iff the closer has accepted the CURRENT version of the
    Closer Disclosure (SHA matches)."""
    p = _disclosure_dir(bullpen) / closer / "closer-disclosure.json"
    if not p.exists():
        return False
    try:
        record = json.loads(p.read_text())
    except Exception:
        return False
    current_sha = _sha256(_read_template("closer-disclosure"))
    return record.get("disclosure_sha256") == current_sha


# ── Operator TOS ─────────────────────────────────────────────────────────

def accept_operator_tos(
    bullpen: str,
    operator_actor: str,
    *,
    operator_legal_name: str,
    typed_signature: str,
    counsel_consulted: bool,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """Record the operator's acceptance of the Operator TOS.

    `counsel_consulted` is a hard checkbox: the operator certifies they
    have either consulted counsel or expressly waive the right to. The
    audit log records which.
    """
    if typed_signature.strip().lower() != operator_legal_name.strip().lower():
        raise ValueError("typed signature does not match operator legal name")

    text = _read_template("operator-tos")
    if not text:
        raise RuntimeError("operator-tos template missing")
    text_sha = _sha256(text)

    record = {
        "operator_actor": operator_actor,
        "operator_legal_name": operator_legal_name.strip(),
        "typed_signature": typed_signature.strip(),
        "tos_sha256": text_sha,
        "counsel_consulted": bool(counsel_consulted),
        "accepted_at": _now(),
        "user_agent": user_agent,
        "ip": ip,
    }

    p = _disclosure_dir(bullpen) / "operator-tos.json"
    p.write_text(json.dumps(record, indent=2) + "\n")

    audit_append(bullpen, kind="operator_tos_accepted", actor=operator_actor, payload={
        "tos_sha256": text_sha,
        "counsel_consulted": bool(counsel_consulted),
    })

    return record


def has_accepted_operator_tos(bullpen: str) -> bool:
    """True iff the operator has accepted the CURRENT version of the TOS."""
    p = _disclosure_dir(bullpen) / "operator-tos.json"
    if not p.exists():
        return False
    try:
        record = json.loads(p.read_text())
    except Exception:
        return False
    current_sha = _sha256(_read_template("operator-tos"))
    return record.get("tos_sha256") == current_sha


# ── W-9 collection ───────────────────────────────────────────────────────

def submit_w9(
    bullpen: str,
    closer: str,
    *,
    legal_name: str,
    business_name: Optional[str],
    federal_tax_classification: str,
    address: dict,
    raw_tin: str,
    actor: Optional[str] = None,
) -> dict:
    """Record W-9 submission. The raw TIN (SSN or EIN) is hashed, never
    persisted — the operator collects the raw value separately for
    their own 1099-NEC filing (the platform is bookkeeping, not the
    operator's tax filer).

    federal_tax_classification: one of "individual", "c_corp", "s_corp",
    "partnership", "trust", "llc_c", "llc_s", "llc_p", "other"
    """
    valid = {"individual", "c_corp", "s_corp", "partnership", "trust",
             "llc_c", "llc_s", "llc_p", "other"}
    if federal_tax_classification not in valid:
        raise ValueError(f"invalid federal_tax_classification: {federal_tax_classification!r}")
    if not raw_tin or len(raw_tin.replace("-", "").replace(" ", "")) < 9:
        raise ValueError("TIN must be at least 9 digits")

    tin_sha = hashlib.sha256(raw_tin.encode("utf-8")).hexdigest()
    record = {
        "closer": closer,
        "legal_name": legal_name.strip(),
        "business_name": (business_name or "").strip() or None,
        "federal_tax_classification": federal_tax_classification,
        "address": {
            "street": address.get("street", "").strip(),
            "city": address.get("city", "").strip(),
            "state": address.get("state", "").strip().upper(),
            "postal_code": address.get("postal_code", "").strip(),
            "country": address.get("country", "US"),
        },
        "tin_sha256": tin_sha,
        "submitted_at": _now(),
    }

    p = _w9_dir(bullpen) / f"{closer}.json"
    p.write_text(json.dumps(record, indent=2) + "\n")

    audit_append(bullpen, kind="w9_submitted", actor=(actor or closer), payload={
        "closer": closer,
        "tin_sha256": tin_sha,
        "federal_tax_classification": federal_tax_classification,
    })

    return record


def has_w9(bullpen: str, closer: str) -> bool:
    return (_w9_dir(bullpen) / f"{closer}.json").exists()


def get_w9(bullpen: str, closer: str) -> Optional[dict]:
    p = _w9_dir(bullpen) / f"{closer}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None
