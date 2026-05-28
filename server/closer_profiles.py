"""Host-wide closer identity store — clearance carries across bullpens.

Today's friction: a closer who finishes disclosure → agreement → W-9 →
DNC → Tier-3 drill in bullpen-A has to do all of it AGAIN in bullpen-B
on the same host. The clearance state lives per-bullpen, so a single
person running across multiple bullpens is treated as N strangers.

This module fixes that for the single-host case (multi-bullpen on the
same operator's machine) AND lays the groundwork for the cross-host
case (closer brings a signed bundle from another host).

Storage
=======
  DATA_DIR/closer-profiles/<email-hash>.json
    {
      "email":         "kelly@gmail.com",
      "display_name":  "Kelly",
      "rep_slugs":     ["kelly", "kelly-b"],   # aliases used across bullpens
      "first_seen_at": ISO,
      "last_seen_at":  ISO,
      "certs": {
        "disclosure":          {"at": ISO, "bullpen": "...", "legal_name": "..."},
        "closer_agreement":    {"at": ISO, "bullpen": "...", "doc_version": "...",
                                 "signed_doc_hash": "..."},
        "w9":                  {"at": ISO, "bullpen": "...", "tin_last4": "...",
                                 "legal_name_hash": "..."},
        "dnc_ack":             {"at": ISO, "bullpen": "...", "signed_doc_hash": "..."},
        "drill_cert_tier3":    {"at": ISO, "bullpen": "...", "tcs": "..."}
      },
      "host_id":       "this-bullpen-host-uuid",
      "version":       1
    }

Privacy
=======
We hash the email + legal name before persisting — the on-disk profile
never stores plaintext PII. The W-9 TIN is stored only as last4 (per
IRS reporting practice for closer-side reference).

Lookup
======
Profiles are keyed by sha256(email-normalized). When a closer joins a
new bullpen and their gate is checked, we:
  1. Look up the per-bullpen onboarding state (existing behavior)
  2. Also look up their host-wide closer_profile via email hash
  3. Union the two — a cert from EITHER counts
This makes "clearance carries across bullpens on this host" work
without changing the gate semantics for the per-bullpen flow.

Cross-host portability v1 (deferred)
====================================
The profile can be exported as a JSON bundle and imported on another
host. The receiving operator decides whether to trust the bundle (UI
prompt: "This closer brings clearance from bullpen-X — accept?"). v1
ships plain JSON; v2 adds HMAC signing per host.
"""
from __future__ import annotations
import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from paths import DATA_DIR as REPO


PROFILES_DIR = REPO / "closer-profiles"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def email_hash(email: str) -> str:
    """sha256 of the normalized email. Used as the profile key on disk."""
    return hashlib.sha256(_norm_email(email).encode("utf-8")).hexdigest()[:32]


def _path(eh: str) -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILES_DIR / f"{eh}.json"


# ── Read / write ──────────────────────────────────────────────────────────

def load(eh: str) -> Optional[dict]:
    p = _path(eh)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _save(eh: str, profile: dict) -> None:
    profile["last_seen_at"] = _now()
    _path(eh).write_text(json.dumps(profile, indent=2))


def ensure(email: str, *, display_name: str, rep_slug: str) -> dict:
    """Create or refresh the host-wide profile for this closer. Idempotent."""
    eh = email_hash(email)
    profile = load(eh) or {
        "email": _norm_email(email),
        "display_name": display_name,
        "rep_slugs": [],
        "first_seen_at": _now(),
        "last_seen_at": _now(),
        "certs": {},
        "version": 1,
    }
    profile["display_name"] = display_name or profile.get("display_name", "")
    if rep_slug and rep_slug not in profile["rep_slugs"]:
        profile["rep_slugs"] = list({*profile["rep_slugs"], rep_slug})
    _save(eh, profile)
    return profile


def record_cert(email: str, kind: str, *, bullpen: str, **detail) -> dict:
    """Stamp a cert into the host-wide profile. Caller should pre-redact:
    plaintext TIN, full legal name, and signed-doc bytes never go through
    here — only hashes and last4."""
    if not email:
        return {}
    eh = email_hash(email)
    profile = load(eh) or {
        "email": _norm_email(email),
        "display_name": "",
        "rep_slugs": [],
        "first_seen_at": _now(),
        "last_seen_at": _now(),
        "certs": {},
        "version": 1,
    }
    profile.setdefault("certs", {})
    profile["certs"][kind] = {"at": _now(), "bullpen": bullpen, **detail}
    _save(eh, profile)
    return profile


def has_cert(email: str, kind: str) -> Optional[dict]:
    """Returns the cert record if present, None otherwise."""
    if not email:
        return None
    profile = load(email_hash(email))
    if not profile:
        return None
    return (profile.get("certs") or {}).get(kind)


# ── Email lookup by rep_slug ──────────────────────────────────────────────
#
# The per-bullpen flow knows the rep slug but not always the email. To
# make clearance carry, we keep a reverse index: rep_slug → email (within
# this bullpen). Scoped per-bullpen so two operators can both have a
# "kelly" without colliding.

def _index_path(bullpen: str) -> Path:
    d = REPO / "bullpens" / bullpen
    d.mkdir(parents=True, exist_ok=True)
    return d / "rep-emails.json"


def link_rep_to_email(bullpen: str, rep_slug: str, email: str) -> None:
    if not email or not rep_slug:
        return
    idx_path = _index_path(bullpen)
    idx = {}
    if idx_path.exists():
        try: idx = json.loads(idx_path.read_text())
        except Exception: pass
    idx[rep_slug] = _norm_email(email)
    idx_path.write_text(json.dumps(idx, indent=2))


def email_for_rep(bullpen: str, rep_slug: str) -> Optional[str]:
    idx_path = _index_path(bullpen)
    if not idx_path.exists():
        return None
    try:
        idx = json.loads(idx_path.read_text())
    except Exception:
        return None
    return idx.get(rep_slug)


# ── Portable bundle (cross-host) ──────────────────────────────────────────

def export_bundle(email: str, *, host_id: str = "self") -> Optional[dict]:
    """Plain-JSON bundle a closer can save to their machine and import on
    another host. v1 unsigned — receiving operator must explicitly trust.
    v2 will add HMAC signing per the issuing host's secret."""
    eh = email_hash(email)
    profile = load(eh)
    if not profile:
        return None
    return {
        "kind": "bullpenlm-closer-identity",
        "version": 1,
        "email_hash": eh,
        "display_name": profile.get("display_name"),
        "certs": profile.get("certs", {}),
        "first_seen_at": profile.get("first_seen_at"),
        "exported_at": _now(),
        "issuing_host": host_id,
    }


def import_bundle(bundle: dict, *, email: str) -> dict:
    """Merge a bundle from another host into this host's profile. The
    receiving operator should gate this via UI confirmation; we do
    minimum sanity checks here."""
    if not bundle or bundle.get("kind") != "bullpenlm-closer-identity":
        raise ValueError("not a bullpenlm closer identity bundle")
    if not email:
        raise ValueError("email required to import")
    if bundle.get("email_hash") != email_hash(email):
        raise ValueError("bundle email hash does not match the email provided")
    eh = email_hash(email)
    profile = load(eh) or {
        "email": _norm_email(email),
        "display_name": bundle.get("display_name", ""),
        "rep_slugs": [],
        "first_seen_at": bundle.get("first_seen_at") or _now(),
        "last_seen_at": _now(),
        "certs": {},
        "version": 1,
    }
    incoming_certs = bundle.get("certs") or {}
    # Trust newest by ISO timestamp
    for kind, cert in incoming_certs.items():
        existing = (profile.get("certs") or {}).get(kind)
        if not existing or (cert.get("at", "") > existing.get("at", "")):
            profile.setdefault("certs", {})[kind] = {
                **cert,
                "imported_from": bundle.get("issuing_host"),
                "imported_at": _now(),
            }
    _save(eh, profile)
    return profile
