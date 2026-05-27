"""DNC scrub + telemarketing compliance tooling.

What this module does:
  * Maintains a local Do-Not-Call list (donotcall.gov national DNC +
    state DNC + per-bullpen internal opt-outs).
  * Checks a phone number against the list before it can be claimed
    or dialed.
  * Records two-party-consent prompts wired by closer + prospect
    jurisdiction.
  * Enforces hours-of-day rules (no 9pm dials in CA, etc.).

What this module does NOT do:
  * It does not auto-download the donotcall.gov list — that file is
    behind an operator-specific subscription (TPS Connect / DNC.gov
    organization account). The operator imports it manually on a
    schedule appropriate to their telemarketing license.
  * It does not adjudicate compliance — the platform's role is to
    make compliance trivial; the operator certifies they have a
    valid telemarketing license and DNC subscription. The Operator
    TOS makes this explicit.

Storage:
  bullpens/<slug>/dnc/national.txt         — donotcall.gov export (numbers, one per line)
  bullpens/<slug>/dnc/state-XX.txt         — state DNC list per state
  bullpens/<slug>/dnc/internal-optouts.txt — per-bullpen opt-out list
  bullpens/<slug>/dnc/last-import.json     — metadata about freshness
  bullpens/<slug>/dnc/consent/<prospect>.json — per-prospect consent records
"""
from __future__ import annotations
import datetime
import json
import re
from pathlib import Path
from typing import Optional

from audit import append as audit_append

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"


def _dnc_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "dnc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _normalize(phone: str) -> str:
    """Normalize to digits-only. US numbers come back as 10 or 11 digits."""
    return re.sub(r"\D", "", phone or "")


# ── DNC list management ──────────────────────────────────────────────────

def _list_path(bullpen: str, name: str) -> Path:
    return _dnc_dir(bullpen) / f"{name}.txt"


def import_list(bullpen: str, list_name: str, numbers: list[str], actor: str = "operator") -> dict:
    """Replace a DNC list with a fresh import.

    list_name: 'national' | 'state-CA' | 'internal-optouts' | ...
    numbers:   list of phone strings (we normalize)
    """
    if not re.match(r"^(national|state-[A-Z]{2}|internal-optouts)$", list_name):
        raise ValueError(f"invalid DNC list name: {list_name!r}")

    normalized = sorted({_normalize(n) for n in numbers if _normalize(n)})
    p = _list_path(bullpen, list_name)
    p.write_text("\n".join(normalized) + "\n")

    meta_path = _dnc_dir(bullpen) / "last-import.json"
    meta = {}
    if meta_path.exists():
        try: meta = json.loads(meta_path.read_text())
        except Exception: meta = {}
    meta[list_name] = {
        "imported_at": _now(),
        "count": len(normalized),
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    audit_append(bullpen, kind="dnc_list_imported", actor=actor, payload={
        "list_name": list_name,
        "count": len(normalized),
    })

    return {"list_name": list_name, "count": len(normalized)}


def _load_list(bullpen: str, list_name: str) -> set[str]:
    p = _list_path(bullpen, list_name)
    if not p.exists():
        return set()
    return {ln.strip() for ln in p.read_text().splitlines() if ln.strip()}


def is_clear_to_dial(bullpen: str, prospect_slug: str) -> tuple[bool, Optional[str]]:
    """Returns (ok, reason). ok=True means no DNC hit AND we have a
    valid phone we can dial. ok=False means either a DNC hit or no
    phone on file.

    The prospect lookup goes through contacts.* — we resolve the
    prospect_slug to a phone number, normalize, and check against all
    applicable lists.
    """
    try:
        from contacts import get_contact
        contact = get_contact(bullpen, prospect_slug)
    except Exception:
        return False, "contacts module unavailable"

    if not contact:
        return False, "prospect not found"

    phone = contact.get("phone") or contact.get("primary_phone")
    if not phone:
        return False, "no phone number on file"

    normalized = _normalize(phone)
    if len(normalized) < 10:
        return False, "phone number is malformed"

    # Check internal opt-outs first (highest priority — closer-specific
    # opt-outs always win)
    internal = _load_list(bullpen, "internal-optouts")
    if normalized in internal or normalized[-10:] in internal:
        return False, "internal opt-out (this prospect asked to be removed)"

    # National DNC
    national = _load_list(bullpen, "national")
    if national and (normalized in national or normalized[-10:] in national):
        return False, "national DNC list"

    # State DNC (look up by prospect's state if known)
    state = (contact.get("state") or "").upper()
    if state and len(state) == 2:
        state_list = _load_list(bullpen, f"state-{state}")
        if state_list and (normalized in state_list or normalized[-10:] in state_list):
            return False, f"state DNC list ({state})"

    return True, None


def add_internal_optout(bullpen: str, phone: str, *, reason: str = "", actor: str = "system") -> None:
    """Add a number to the bullpen's internal opt-out list. Called when
    a prospect explicitly asks not to be called."""
    p = _list_path(bullpen, "internal-optouts")
    existing = _load_list(bullpen, "internal-optouts")
    normalized = _normalize(phone)
    existing.add(normalized)
    p.write_text("\n".join(sorted(existing)) + "\n")
    audit_append(bullpen, kind="dnc_internal_optout", actor=actor, payload={
        "phone_last4": normalized[-4:] if normalized else "",
        "reason": reason,
    })


# ── Hours-of-day rules ───────────────────────────────────────────────────
# FTC TSR: 8am-9pm local time to the called party.
# State variations apply; we hold to the federal floor unless a state
# is stricter.

STATE_HOUR_RULES: dict[str, tuple[int, int]] = {
    # (open_hour_24h, close_hour_24h) in the called party's local time.
    # Defaults to (8, 21) per federal TSR. Listed only when state differs.
    "AL": (8, 20),   # Alabama: 8am-8pm
    "AR": (8, 20),   # Arkansas: 8am-9pm but no Sundays — handled below
    "FL": (8, 20),   # Florida: 8am-8pm M-Sat, no Sundays/holidays
    "LA": (8, 20),   # Louisiana: 8am-8pm
    "MS": (8, 20),   # Mississippi: 8am-8pm
}

NO_SUNDAY_STATES = {"AR", "FL", "AL"}


def is_allowed_hour(now: Optional[datetime.datetime] = None, state: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """Returns (ok, reason). State is the called party's state."""
    now = now or datetime.datetime.now()
    state = (state or "").upper()
    open_h, close_h = STATE_HOUR_RULES.get(state, (8, 21))

    if state in NO_SUNDAY_STATES and now.weekday() == 6:   # Sunday
        return False, f"{state} prohibits Sunday cold calls"

    if now.hour < open_h:
        return False, f"too early for {state or 'TSR floor'} (opens {open_h}:00)"
    if now.hour >= close_h:
        return False, f"too late for {state or 'TSR floor'} (closes {close_h}:00)"

    return True, None


# ── Two-party-consent (call recording) ───────────────────────────────────
# Two-party-consent states: CA, FL, IL, MD, MA, MT, NV, NH, OR (some
# variations), PA, WA. Federal default is one-party.

TWO_PARTY_STATES: set[str] = {
    "CA", "FL", "IL", "MD", "MA", "MT", "NV", "NH", "OR", "PA", "WA",
    # Connecticut: one-party for phone, two for in-person — treated as
    # two-party for our purposes since calls span that boundary
    "CT",
    # Delaware, Hawaii: nuanced; default to two-party for safety
    "DE", "HI",
}


def recording_consent_required(closer_state: Optional[str], prospect_state: Optional[str]) -> bool:
    """Return True if call recording requires explicit two-party consent
    (either party's state requires it)."""
    cs = (closer_state or "").upper()
    ps = (prospect_state or "").upper()
    return (cs in TWO_PARTY_STATES) or (ps in TWO_PARTY_STATES)


def record_consent(bullpen: str, prospect_slug: str, *, granted: bool, by: str, actor: str) -> dict:
    """Log a recording-consent grant or refusal for a prospect.

    by:    "prospect" | "closer" | "operator"
    actor: who recorded it in the system
    """
    p = _dnc_dir(bullpen) / "consent" / f"{prospect_slug}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "prospect": prospect_slug,
        "granted": bool(granted),
        "by": by,
        "recorded_at": _now(),
    }
    p.write_text(json.dumps(record, indent=2) + "\n")
    audit_append(bullpen, kind="recording_consent_recorded", actor=actor, payload={
        "prospect": prospect_slug,
        "granted": bool(granted),
        "by": by,
    })
    return record


# ── Status snapshot for UI ───────────────────────────────────────────────

def dnc_status(bullpen: str) -> dict:
    """Status snapshot — what lists are loaded, how stale, how many entries."""
    meta_path = _dnc_dir(bullpen) / "last-import.json"
    meta = {}
    if meta_path.exists():
        try: meta = json.loads(meta_path.read_text())
        except Exception: meta = {}
    return {
        "lists": meta,
        "any_loaded": bool(meta),
    }
