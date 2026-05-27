"""Invite codes + session cookies — the "click a link, type a code, you're in"
flow for joining a hosted BullpenLM without needing Tailscale.

Architecture:
  * Host generates a single-use invite code from the team panel (or CLI).
  * Host shares the public tunnel URL + the code with a friend.
  * Friend visits /join, types the code, server validates + sets a signed
    session cookie identifying them by their REP name.
  * Subsequent API requests carry the cookie; non-localhost requests without
    a valid cookie get 401.

Storage: JSON files under team/invites/ + team/sessions.json (NDJSON-style).
No database. Single-host writer assumed.

Security: cookies are HMAC-signed with a per-host secret kept in
~/.bullpenlm/host-secret. Codes are random 8-char (URL-safe). Sessions
expire after SESSION_TTL_DAYS.

═══════════════════════════════════════════════════════════════════════
PHASE 0.5 FIREWALL — INVITES AWARD NO XP
═══════════════════════════════════════════════════════════════════════

This module does NOT import or call `xp.py`. Creating, sharing, or
redeeming an invite is structurally incapable of awarding XP to the
inviter or invitee.

The XP rules table (server/xp.py) defines `invite_closer`,
`invite_operator`, `closer_joined`, and `operator_joined` events with
`bucket: "none"` — meaning: if a future caller were to dispatch one of
those events into the audit log via `xp.xp_for_event(...)`, the XP
total would still be zero. The audit chain records the attribution
("Jordan invited Ramos") for social visibility, but never credits
earnable XP.

This is one of the three structural guarantees against the FTC
Koscot/Omnitrition pyramid shape:

  1. Money-XP and Clout-XP are separate ledgers (server/xp.py)
  2. Clout-XP cannot route prospects (server/gates.py:EarningInputs)
  3. Recruitment events award no XP at all (this module + xp.py)

Removing or weakening any of these three guarantees is a Phase 0.5
firewall regression. Don't.
"""
from __future__ import annotations
import datetime
import hmac
import hashlib
import json
import secrets
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent
TEAM_DIR = REPO / "team"
INVITES_DIR = TEAM_DIR / "invites"
USED_DIR = TEAM_DIR / "invites" / "used"
SECRET_PATH = Path.home() / ".bullpenlm" / "host-secret"

INVITES_DIR.mkdir(parents=True, exist_ok=True)
USED_DIR.mkdir(parents=True, exist_ok=True)

SESSION_TTL_DAYS = 30
CODE_PREFIX = "BULL-"
CODE_LEN = 8   # excluding prefix


def _host_secret() -> bytes:
    """Get-or-create the per-host HMAC secret. 32 bytes, written 0600."""
    if SECRET_PATH.exists():
        return SECRET_PATH.read_bytes()
    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    s = secrets.token_bytes(32)
    SECRET_PATH.write_bytes(s)
    SECRET_PATH.chmod(0o600)
    return s


# ── Invite codes ──────────────────────────────────────────────────────────

def _gen_code() -> str:
    """8 char URL-safe code, prefixed BULL- for legibility."""
    return CODE_PREFIX + secrets.token_urlsafe(8)[:CODE_LEN].upper().replace("_", "X").replace("-", "Y")


def create_invite(rep: str, note: str = "", price_usd: float = 0,
                  stripe_session_id: str = "") -> dict:
    """Create a single-use invite code for a named rep.

    price_usd > 0 marks the invite as requiring Stripe checkout before redeem.
    stripe_session_id is set later (by the server) once a checkout session is
    created and attached to this code.
    """
    rep = (rep or "").strip()
    if not rep:
        raise ValueError("rep name required")
    code = _gen_code()
    data = {
        "code": code,
        "rep": rep,
        "note": note,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "used_at": None,
        "price_usd": float(price_usd or 0),
        "payment_status": "paid" if not price_usd else "pending",
        "stripe_session_id": stripe_session_id or "",
    }
    (INVITES_DIR / f"{code}.json").write_text(json.dumps(data, indent=2) + "\n")
    return data


def attach_stripe_session(code: str, session_id: str, checkout_url: str = "") -> dict:
    """Attach a Stripe Checkout Session to a pending paid invite."""
    code = (code or "").strip().upper()
    p = INVITES_DIR / f"{code}.json"
    if not p.exists():
        return {"ok": False, "error": "invalid_code"}
    try:
        data = json.loads(p.read_text())
    except Exception:
        return {"ok": False, "error": "corrupt_code"}
    data["stripe_session_id"] = session_id
    if checkout_url:
        data["checkout_url"] = checkout_url
    p.write_text(json.dumps(data, indent=2) + "\n")
    return {"ok": True, "invite": data}


def mark_paid(code: str) -> dict:
    """Mark a paid invite as payment-confirmed (called after Stripe verification)."""
    code = (code or "").strip().upper()
    p = INVITES_DIR / f"{code}.json"
    if not p.exists():
        return {"ok": False, "error": "invalid_code"}
    try:
        data = json.loads(p.read_text())
    except Exception:
        return {"ok": False, "error": "corrupt_code"}
    data["payment_status"] = "paid"
    data["paid_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    p.write_text(json.dumps(data, indent=2) + "\n")
    return {"ok": True, "invite": data}


def get_invite(code: str) -> Optional[dict]:
    """Return an invite by code (active dir only)."""
    code = (code or "").strip().upper()
    if not code.startswith(CODE_PREFIX):
        code = CODE_PREFIX + code
    p = INVITES_DIR / f"{code}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def redeem_invite(code: str) -> dict:
    """Mark an invite as used. Returns {ok, rep, error}.

    Paid invites whose payment hasn't been confirmed return
    {ok: False, error: 'payment_required', checkout_url, price_usd}.
    """
    code = (code or "").strip().upper()
    if not code.startswith(CODE_PREFIX):
        code = CODE_PREFIX + code
    p = INVITES_DIR / f"{code}.json"
    if not p.exists():
        return {"ok": False, "error": "invalid_code"}
    try:
        data = json.loads(p.read_text())
    except Exception:
        return {"ok": False, "error": "corrupt_code"}
    if data.get("used_at"):
        return {"ok": False, "error": "already_used", "used_at": data["used_at"]}
    if data.get("price_usd", 0) > 0 and data.get("payment_status") != "paid":
        return {
            "ok": False,
            "error": "payment_required",
            "price_usd": data["price_usd"],
            "checkout_url": data.get("checkout_url", ""),
            "code": code,
        }
    data["used_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    (USED_DIR / f"{code}.json").write_text(json.dumps(data, indent=2) + "\n")
    p.unlink()
    return {"ok": True, "rep": data["rep"]}


def list_invites(include_used: bool = False) -> list[dict]:
    """List active (and optionally used) invites."""
    out = []
    for p in sorted(INVITES_DIR.glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            continue
    if include_used:
        for p in sorted(USED_DIR.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except Exception:
                continue
    return out


# ── Session cookies ───────────────────────────────────────────────────────

def make_session_cookie(rep: str) -> str:
    """Build a signed session cookie value for the given rep."""
    secret = _host_secret()
    issued = int(datetime.datetime.now().timestamp())
    payload = f"{rep}.{issued}"
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}.{sig}"


def validate_session_cookie(cookie_value: str) -> Optional[str]:
    """Return the rep name if the cookie is valid + not expired, else None."""
    if not cookie_value:
        return None
    parts = cookie_value.rsplit(".", 1)
    if len(parts) != 2:
        return None
    payload, sig = parts
    expected = hmac.new(_host_secret(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        rep, issued = payload.rsplit(".", 1)
        issued_at = datetime.datetime.fromtimestamp(int(issued))
    except Exception:
        return None
    if (datetime.datetime.now() - issued_at).days > SESSION_TTL_DAYS:
        return None
    return rep


# ── CLI for the host to create an invite from the terminal ────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("Usage:")
        print("  python3 server/invites.py create <rep-name> [note]")
        print("  python3 server/invites.py list")
        print("  python3 server/invites.py list --all")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "create":
        if len(sys.argv) < 3:
            print("× rep name required"); sys.exit(1)
        rep = sys.argv[2]
        note = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
        inv = create_invite(rep, note)
        print(f"✓ Created invite for {inv['rep']}")
        print(f"  Code: {inv['code']}")
        print(f"  Share: <YOUR-HOST-URL>/join?code={inv['code']}")
    elif cmd == "list":
        include_used = "--all" in sys.argv
        invs = list_invites(include_used=include_used)
        if not invs:
            print("No invites."); sys.exit(0)
        for i in invs:
            status = ("USED " + i["used_at"]) if i.get("used_at") else "ACTIVE"
            print(f"  {i['code']}  rep={i['rep']:14}  {status}  {i.get('note', '')}")
    else:
        print(f"× unknown command: {cmd}"); sys.exit(1)
