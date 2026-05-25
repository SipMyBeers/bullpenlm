"""Minimal Stripe client for BullpenLM paid invite codes.

Uses urllib + form-encoding so we don't add a runtime dep. Reads the API
key from ~/.bullpenlm/stripe.json (mode + sk_live or sk_test). Falls back
to $BULLPENLM_STRIPE_KEY env var.

Surface:
  create_checkout_session(code, price_usd, ...) → {id, url}
  retrieve_checkout_session(session_id) → full session dict
  is_configured() → bool

v0.1 uses platform-direct charges (all money goes to BullpenLM platform
account). v0.2 will migrate to Connect destination charges so founders get
their own connected accounts and direct payouts. See references/connect.md
in the stripe skill.
"""
from __future__ import annotations
import json
import os
import ssl
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path.home() / ".bullpenlm" / "stripe.json"
API_BASE = "https://api.stripe.com/v1"

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()


def _config() -> dict:
    """Load Stripe config from disk. Format:
       {"key": "sk_live_...", "mode": "live"}  or  test."""
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            return {}
    env_key = os.environ.get("BULLPENLM_STRIPE_KEY")
    if env_key:
        mode = "live" if env_key.startswith("sk_live_") else "test"
        return {"key": env_key, "mode": mode}
    return {}


def _api_key() -> Optional[str]:
    return (_config().get("key") or "").strip() or None


def is_configured() -> bool:
    return _api_key() is not None


def mode() -> str:
    return _config().get("mode") or "unknown"


def save_config(key: str) -> dict:
    """Persist the API key to ~/.bullpenlm/stripe.json (0600)."""
    key = (key or "").strip()
    if not key:
        raise ValueError("api_key_required")
    if not (key.startswith("sk_live_") or key.startswith("sk_test_")):
        raise ValueError("not_a_secret_key")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    m = "live" if key.startswith("sk_live_") else "test"
    body = json.dumps({"key": key, "mode": m}, indent=2) + "\n"
    CONFIG_PATH.write_text(body)
    CONFIG_PATH.chmod(0o600)
    return {"ok": True, "mode": m}


def _request(method: str, path: str, form: Optional[dict] = None) -> dict:
    key = _api_key()
    if not key:
        return {"ok": False, "error": "stripe_not_configured"}
    url = f"{API_BASE}{path}"
    data = None
    headers = {"Authorization": f"Bearer {key}"}
    if form is not None:
        # Stripe accepts repeated keys & nested via urlencode with flat keys.
        flat = []
        for k, v in form.items():
            if v is None:
                continue
            flat.append((k, str(v)))
        data = urllib.parse.urlencode(flat, doseq=True).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
            body = r.read()
            return {"ok": True, "data": json.loads(body.decode("utf-8"))}
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_body = {"raw": "<unparseable>"}
        return {"ok": False, "error": "stripe_http_error",
                "status": e.code, "stripe": err_body}
    except Exception as e:
        return {"ok": False, "error": "stripe_network_error",
                "detail": str(e)}


def create_checkout_session(code: str, price_usd: float,
                             product_name: str,
                             success_url: str,
                             cancel_url: str,
                             customer_email: Optional[str] = None) -> dict:
    """Create a Checkout Session for a paid invite code.

    On success returns {ok: True, id, url}. The URL is what the closer
    visits to pay. After payment Stripe redirects to success_url with
    {CHECKOUT_SESSION_ID} substituted, where our /api/invite/redeem
    can verify before unlocking the code.
    """
    cents = int(round(float(price_usd) * 100))
    if cents < 50:
        return {"ok": False, "error": "stripe_min_charge_is_50_cents"}
    form = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][product_data][name]": product_name,
        "line_items[0][price_data][unit_amount]": cents,
        "line_items[0][quantity]": 1,
        "metadata[bullpen_code]": code,
        "client_reference_id": code,
        "payment_intent_data[metadata][bullpen_code]": code,
    }
    if customer_email:
        form["customer_email"] = customer_email
    r = _request("POST", "/checkout/sessions", form=form)
    if not r.get("ok"):
        return r
    d = r["data"]
    return {"ok": True, "id": d.get("id"), "url": d.get("url"),
            "expires_at": d.get("expires_at")}


def retrieve_checkout_session(session_id: str) -> dict:
    """Look up a Checkout Session by ID. Returns full session payload."""
    if not session_id or not session_id.startswith("cs_"):
        return {"ok": False, "error": "invalid_session_id"}
    r = _request("GET", f"/checkout/sessions/{session_id}")
    if not r.get("ok"):
        return r
    d = r["data"]
    return {
        "ok": True,
        "id": d.get("id"),
        "payment_status": d.get("payment_status"),
        "status": d.get("status"),
        "amount_total": d.get("amount_total"),
        "currency": d.get("currency"),
        "client_reference_id": d.get("client_reference_id"),
        "metadata": d.get("metadata") or {},
    }
