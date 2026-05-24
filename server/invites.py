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


def create_invite(rep: str, note: str = "") -> dict:
    """Create a single-use invite code for a named rep."""
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
    }
    (INVITES_DIR / f"{code}.json").write_text(json.dumps(data, indent=2) + "\n")
    return data


def redeem_invite(code: str) -> dict:
    """Mark an invite as used. Returns {ok, rep, error}."""
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
    data["used_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    # Move to /used/ so the active dir only contains live codes
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
