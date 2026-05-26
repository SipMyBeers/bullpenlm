"""Send branded outreach emails through the BullpenLM Cloudflare Worker.

The Worker URL + shared secret live at ~/.bullpenlm/email-worker.json
(0600, gitignored). The Worker handles the actual Email Service binding
call — we just render templates locally and POST the rendered HTML/text.

  send_template(bullpen, template_name, to, vars=...) → {ok, ...}
  send_raw(bullpen, to, subject, html, text) → {ok, ...}

Both functions audit-log the send via audit.append(kind='email_sent') so
the activity timeline picks it up.

No-op safely if ~/.bullpenlm/email-worker.json is missing — the call still
audit-logs as `email_intent_unsent` so the founder can manually send via
/app/outbox.html (the existing draft flow) without losing the intent.
"""
from __future__ import annotations
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

CONFIG_PATH = Path.home() / ".bullpenlm" / "email-worker.json"
UA = "BullpenLM (https://bullpenlm.com, 0.1)"


def _worker_config() -> Optional[dict]:
    if not CONFIG_PATH.exists():
        return None
    try:
        d = json.loads(CONFIG_PATH.read_text())
    except Exception:
        return None
    if not d.get("url") or not d.get("secret"):
        return None
    return d


def is_configured() -> bool:
    return _worker_config() is not None


def _resolve_from(bullpen: str) -> Optional[dict]:
    """Pull {email, name} for the From: header out of the bullpen config."""
    from bullpens import get_bullpen
    cfg = get_bullpen(bullpen) or {}
    email = (cfg.get("brand_sending_email") or "").strip()
    if not email:
        return None
    name = (cfg.get("founder_display_name")
             or cfg.get("name")
             or bullpen).strip()
    return {"email": email, "name": name}


def _audit(bullpen: str, kind: str, actor: str, payload: dict) -> None:
    try:
        from audit import append as audit_append
        audit_append(bullpen, actor or "system", kind,
                     target_type="email",
                     target_id=payload.get("to") if isinstance(payload.get("to"), str) else "many",
                     payload=payload)
    except Exception:
        pass


def send_raw(bullpen: str, to, subject: str, html: str, text: str,
              from_override: Optional[dict] = None,
              actor: str = "system") -> dict:
    """POST a rendered email to the Worker. Returns {ok, ...}.

    `to` may be a str or list[str]. `from_override` lets you override the
    bullpen's default `brand_sending_email` (rare — usually leave None)."""
    sender = from_override or _resolve_from(bullpen)
    if not sender:
        _audit(bullpen, "email_intent_unsent", actor,
               {"to": to, "subject": subject, "reason": "no_brand_sending_email"})
        return {"ok": False, "error": "brand_sending_email_not_set",
                "hint": "Set brand_sending_email on the bullpen config."}

    cfg = _worker_config()
    if not cfg:
        _audit(bullpen, "email_intent_unsent", actor,
               {"to": to, "subject": subject, "from": sender,
                "html_len": len(html or ""), "text_len": len(text or ""),
                "reason": "email_worker_not_configured"})
        return {"ok": False, "error": "email_worker_not_configured",
                "hint": "Deploy email-worker/ and write ~/.bullpenlm/email-worker.json"}

    body = {
        "from": sender,
        "to": to,
        "subject": subject,
        "html": html,
        "text": text,
    }
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + "/send",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg['secret']}",
            "Content-Type": "application/json",
            "User-Agent": UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
            resp = json.loads(r.read().decode("utf-8") or "{}")
        result = {"ok": True, "worker_response": resp}
    except urllib.error.HTTPError as e:
        result = {"ok": False, "error": "worker_http_error",
                  "status": e.code,
                  "body": e.read().decode(errors="ignore")[:400]}
    except Exception as e:
        result = {"ok": False, "error": "network", "detail": str(e)}

    _audit(bullpen, "email_sent" if result.get("ok") else "email_failed",
           actor, {"to": to, "subject": subject, "from": sender,
                    "result": result})
    return result


def send_template(bullpen: str, template_name: str, to,
                   vars: Optional[dict] = None,
                   actor: str = "system") -> dict:
    """Render the named template against the bullpen + supplied vars, then
    send via the Worker."""
    try:
        from email_templates import render
        rendered = render(template_name, vars=vars or {}, bullpen=bullpen)
    except FileNotFoundError as e:
        return {"ok": False, "error": "template_not_found", "detail": str(e)}
    return send_raw(
        bullpen=bullpen,
        to=to,
        subject=rendered["subject"],
        html=rendered["html"],
        text=rendered["text"],
        actor=actor,
    )
