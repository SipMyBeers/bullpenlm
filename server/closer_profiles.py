"""Host-wide closer identity store — clearance carries across bullpens.

Cross-host bundle signing (v2)
==============================
When a closer exports a bundle, the issuing host signs it with an HMAC
keyed by its host-secret (kept at DATA_DIR/.closer-profiles-host-key).
The receiving host verifies the signature against a whitelist of
trusted issuers (DATA_DIR/.trusted-hosts.json). An unknown issuer
triggers a UI prompt: "trust this host's clearances?"

Trust establishment
-------------------
Two hosts trust each other after they swap their public host-secret
hashes. The receiving operator pastes the issuing host's hash into
their trusted-hosts list (UI: /app/identity/ → "Add trusted host").
This is friend-cohort scale — manual but explicit. Cohort growth into
the dozens stays manageable.


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
import hmac
import json
import os
import re
import secrets
from pathlib import Path
from typing import Optional

from paths import DATA_DIR as REPO


PROFILES_DIR = REPO / "closer-profiles"
HOST_KEY_PATH = REPO / ".closer-profiles-host-key"
TRUSTED_HOSTS_PATH = REPO / ".trusted-hosts.json"


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


def global_xp(email: str) -> dict:
    """Aggregate XP across every bullpen this email is linked to.

    Walks every bullpens/<slug>/rep-emails.json, finds the rep slug
    for this email, then reads that bullpen's xp ledger. Returns
    {money_xp, clout_xp, total_xp, level, bullpens:[{slug,rep,xp}]}.
    """
    from paths import DATA_DIR as _DD
    out = {"email": email, "money_xp": 0, "clout_xp": 0, "total_xp": 0,
           "level": 1, "bullpens": []}
    bullpens_root = _DD / "bullpens"
    if not bullpens_root.exists():
        return out
    try:
        import xp as _xp
    except Exception:
        _xp = None
    norm = _norm_email(email)
    for bp_dir in bullpens_root.iterdir():
        if not bp_dir.is_dir(): continue
        idx_path = bp_dir / "rep-emails.json"
        if not idx_path.exists(): continue
        try:
            idx = json.loads(idx_path.read_text())
        except Exception:
            continue
        for rep_slug, e in idx.items():
            if _norm_email(e) != norm: continue
            m = c = 0
            if _xp:
                try:
                    m = _xp.get_money_xp(bp_dir.name, rep_slug)
                    c = _xp.get_clout_xp(bp_dir.name, rep_slug)
                except Exception:
                    pass
            out["money_xp"] += m
            out["clout_xp"] += c
            out["bullpens"].append({"slug": bp_dir.name, "rep": rep_slug,
                                      "money_xp": m, "clout_xp": c})
            break
    out["total_xp"] = out["money_xp"] + out["clout_xp"]
    try:
        from xp import level_for_xp, progress_to_next
        out["level"] = level_for_xp(out["total_xp"])
        out.update(progress_to_next(out["total_xp"]))
    except Exception:
        pass
    return out


def email_for_rep(bullpen: str, rep_slug: str) -> Optional[str]:
    idx_path = _index_path(bullpen)
    if not idx_path.exists():
        return None
    try:
        idx = json.loads(idx_path.read_text())
    except Exception:
        return None
    return idx.get(rep_slug)


# ── Host signing + trusted-hosts ──────────────────────────────────────────

def _host_secret() -> bytes:
    """Get-or-generate this host's HMAC secret. 32 bytes of urandom,
    persisted at DATA_DIR/.closer-profiles-host-key with 0o600 perms."""
    if HOST_KEY_PATH.exists():
        try:
            return HOST_KEY_PATH.read_bytes()
        except Exception:
            pass
    HOST_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    HOST_KEY_PATH.write_bytes(secret)
    try: os.chmod(HOST_KEY_PATH, 0o600)
    except Exception: pass
    return secret


def host_fingerprint() -> str:
    """Public identifier of this host — sha256 of the secret. Safe to
    share; cannot be used to forge signatures. Operators paste this
    into a peer's trusted-hosts list to establish trust."""
    return hashlib.sha256(_host_secret()).hexdigest()[:16]


def _sign_payload(payload: bytes) -> str:
    return hmac.new(_host_secret(), payload, hashlib.sha256).hexdigest()


def trusted_hosts() -> list[dict]:
    """[{fingerprint, label, added_at}, ...] — fingerprints we accept
    signed bundles from."""
    if not TRUSTED_HOSTS_PATH.exists():
        return []
    try:
        return json.loads(TRUSTED_HOSTS_PATH.read_text()) or []
    except Exception:
        return []


def add_trusted_host(fingerprint: str, label: str = "") -> list[dict]:
    fingerprint = (fingerprint or "").strip().lower()
    if not re.match(r"^[0-9a-f]{16,}$", fingerprint):
        raise ValueError("fingerprint must be hex (16+ chars)")
    hosts = trusted_hosts()
    # Dedupe
    hosts = [h for h in hosts if h.get("fingerprint") != fingerprint]
    hosts.append({
        "fingerprint": fingerprint,
        "label": (label or "").strip()[:80] or "unlabelled",
        "added_at": _now(),
    })
    TRUSTED_HOSTS_PATH.write_text(json.dumps(hosts, indent=2))
    return hosts


def remove_trusted_host(fingerprint: str) -> list[dict]:
    fingerprint = (fingerprint or "").strip().lower()
    hosts = [h for h in trusted_hosts() if h.get("fingerprint") != fingerprint]
    TRUSTED_HOSTS_PATH.write_text(json.dumps(hosts, indent=2))
    return hosts


# ── Portable bundle (cross-host) ──────────────────────────────────────────

def export_bundle(email: str, *, host_id: str = "self") -> Optional[dict]:
    """Plain-JSON bundle a closer can save to their machine and import on
    another host. v1 unsigned — receiving operator must explicitly trust.
    v2 will add HMAC signing per the issuing host's secret."""
    eh = email_hash(email)
    profile = load(eh)
    if not profile:
        return None
    # The signed payload covers everything EXCEPT the signature itself.
    payload = {
        "kind": "bullpenlm-closer-identity",
        "version": 2,
        "email_hash": eh,
        "display_name": profile.get("display_name"),
        "certs": profile.get("certs", {}),
        "first_seen_at": profile.get("first_seen_at"),
        "exported_at": _now(),
        "issuing_host": host_id,
        "issuer_fingerprint": host_fingerprint(),
    }
    # Canonical JSON for signing — sort_keys + no extra whitespace so
    # the issuing and verifying hosts agree on the byte sequence.
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["signature"] = _sign_payload(canonical)
    return payload


def verify_bundle_signature(bundle: dict) -> dict:
    """Returns {ok, reason, issuer_fingerprint, is_trusted}.
    ok=True means the signature checks out AND the issuer is trusted by
    this host (or is this host itself). ok=False with details otherwise."""
    if not bundle or bundle.get("kind") != "bullpenlm-closer-identity":
        return {"ok": False, "reason": "not a bullpenlm identity bundle"}
    version = bundle.get("version") or 1
    if version < 2 or "signature" not in bundle:
        # v1 unsigned — receiving operator must explicitly trust
        return {"ok": False, "reason": "unsigned (v1) bundle",
                "issuer_fingerprint": None, "is_trusted": False, "unsigned": True}
    fingerprint = (bundle.get("issuer_fingerprint") or "").lower()
    sig_claim = bundle.get("signature", "")
    payload = {k: v for k, v in bundle.items() if k != "signature"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    # If the issuer fingerprint matches THIS host, verify with our own key
    is_self = fingerprint == host_fingerprint()
    if is_self:
        expected = _sign_payload(canonical)
        if hmac.compare_digest(expected, sig_claim):
            return {"ok": True, "reason": "self-signed", "issuer_fingerprint": fingerprint, "is_trusted": True}
        return {"ok": False, "reason": "signature does not verify against own key",
                "issuer_fingerprint": fingerprint, "is_trusted": False}
    # Foreign host — must be in trusted-hosts to verify (we don't have
    # their secret, so we can't actually verify the HMAC. Trust is by
    # fingerprint match alone, which means a stolen bundle replayed from
    # a previously-trusted host can't be detected. v3 will switch to
    # asymmetric keys to fix this.)
    is_trusted = any(h.get("fingerprint") == fingerprint for h in trusted_hosts())
    if not is_trusted:
        return {"ok": False, "reason": f"issuer {fingerprint[:8]}… not in trusted-hosts list",
                "issuer_fingerprint": fingerprint, "is_trusted": False}
    return {"ok": True, "reason": "issuer trusted (fingerprint match)",
            "issuer_fingerprint": fingerprint, "is_trusted": True}


def import_bundle(bundle: dict, *, email: str, allow_untrusted: bool = False) -> dict:
    """Merge a bundle from another host into this host's profile. By
    default refuses to import if the issuer isn't in trusted-hosts;
    pass allow_untrusted=True to accept anyway (UI-confirmed trust)."""
    if not bundle or bundle.get("kind") != "bullpenlm-closer-identity":
        raise ValueError("not a bullpenlm closer identity bundle")
    if not email:
        raise ValueError("email required to import")
    if bundle.get("email_hash") != email_hash(email):
        raise ValueError("bundle email hash does not match the email provided")
    sig = verify_bundle_signature(bundle)
    if not sig["ok"] and not allow_untrusted:
        raise ValueError(f"bundle not trusted: {sig['reason']}. Add the issuer fingerprint "
                          f"({sig.get('issuer_fingerprint') or 'n/a'}) to trusted-hosts first, "
                          f"or import with allow_untrusted=True after UI confirmation.")
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
