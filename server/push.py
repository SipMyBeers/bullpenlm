"""Mobile push (APNs) for the BullpenLM iOS team-tracking app.

Two halves:
  - a device-token registry (which iOS devices track which bullpen)
  - a sender that fires an APNs alert when a notify-worthy audit event
    lands, so an operator gets pinged when a rep closes / certifies /
    clears the gate / joins.

Graceful degradation: if no devices are registered, or the APNs key /
deps (pyjwt[crypto], httpx[http2]/h2) are absent, every entry point is a
logged no-op — nothing here can break audit.append. Activate by setting
the APNS_* env vars + dropping the .p8 key on the host, then
`pip install "pyjwt[crypto]" "httpx[http2]"` into the build venv and
rebuilding the sidecar. See ios/TESTFLIGHT_RUNBOOK.md.
"""
import json
import os
import time
import threading
import datetime
from pathlib import Path

try:
    from paths import DATA_DIR
except Exception:
    DATA_DIR = Path(os.environ.get("BULLPENLM_HOME",
                                   str(Path.home() / "Library/Application Support/BullpenLM")))

_LOCK = threading.Lock()


def _store() -> Path:
    return Path(DATA_DIR) / "push_tokens.json"


def _load() -> dict:
    try:
        return json.loads(_store().read_text())
    except Exception:
        return {}


def _save(d: dict) -> None:
    tmp = _store().with_suffix(".tmp")
    tmp.write_text(json.dumps(d))
    tmp.replace(_store())


def register(bullpen: str, operator: str, token: str,
             platform: str = "ios", env: str = "prod") -> dict:
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "no token"}
    with _LOCK:
        d = _load()
        pen = d.setdefault(bullpen, {})
        pen[token] = {"operator": operator or "self", "platform": platform, "env": env,
                      "ts": datetime.datetime.now().isoformat(timespec="seconds")}
        _save(d)
        n = len(d.get(bullpen, {}))
    return {"ok": True, "devices": n}


def unregister(bullpen: str, token: str) -> dict:
    with _LOCK:
        d = _load()
        if bullpen in d and token in d[bullpen]:
            del d[bullpen][token]
            _save(d)
    return {"ok": True}


def _tokens_for(bullpen: str):
    return list(_load().get(bullpen, {}).items())


# Notify-worthy audit kinds → (title, body template). Body gets {actor}.
# Kinds that don't exist simply never fire — safe to keep a generous set.
NOTIFY = {
    "deal_closed_won":      ("Deal closed",      "{actor} closed a deal"),
    "drill_passed_cert":    ("Drill certified",  "{actor} certified a Tier-3 drill"),
    "gate_cleared":         ("Gate cleared",     "{actor} can dial real prospects now"),
    "joined":               ("New rep",          "{actor} joined the bullpen"),
    "achievement_unlocked": ("Achievement",      "{actor} unlocked an achievement"),
    "w9_submitted":         ("Gate progress",    "{actor} submitted their W-9"),
}


def on_audit_event(bullpen: str, entry: dict) -> None:
    """Called from audit.append for every event. Fires a push for the
    notify-worthy kinds to every device tracking this bullpen."""
    spec = NOTIFY.get(entry.get("kind"))
    if not spec:
        return
    toks = _tokens_for(bullpen)
    if not toks:
        return
    actor = entry.get("actor") or "Someone"
    title, body_t = spec
    body = body_t.format(actor=actor)
    data = {"bullpen": bullpen, "rep": actor, "kind": entry.get("kind")}
    for tok, meta in toks:
        try:
            _send(tok, meta, title, body, data)
        except Exception:
            pass


# ── APNs send (lazy deps; logged no-op when unconfigured) ──────────────
_JWT = {"tok": None, "exp": 0}


def _cfg():
    kp, kid, team = (os.environ.get("APNS_KEY_PATH"), os.environ.get("APNS_KEY_ID"),
                     os.environ.get("APNS_TEAM_ID"))
    if not (kp and kid and team and Path(kp).exists()):
        return None
    return {"key_path": kp, "key_id": kid, "team_id": team,
            "topic": os.environ.get("APNS_TOPIC", "com.beerslabs.bullpenlm")}


def _provider_jwt(cfg) -> str:
    now = int(time.time())
    if _JWT["tok"] and _JWT["exp"] > now + 60:
        return _JWT["tok"]
    import jwt  # pyjwt[crypto]
    tok = jwt.encode({"iss": cfg["team_id"], "iat": now},
                     Path(cfg["key_path"]).read_text(),
                     algorithm="ES256", headers={"kid": cfg["key_id"]})
    _JWT["tok"], _JWT["exp"] = tok, now + 3000
    return tok


def _send(token: str, meta: dict, title: str, body: str, data: dict) -> None:
    cfg = _cfg()
    if cfg is None:
        print(f"[push] (no APNs key) would notify {token[:8]}...: {title} - {body}")
        return
    try:
        import httpx
        bearer = _provider_jwt(cfg)
    except Exception as e:
        print(f"[push] APNs deps/key not ready ({e}); skipped")
        return
    env = meta.get("env", "prod")
    host = "https://api.push.apple.com" if env == "prod" else "https://api.sandbox.push.apple.com"
    payload = {"aps": {"alert": {"title": title, "body": body}, "sound": "default"}}
    payload.update(data)
    headers = {"authorization": f"bearer {bearer}", "apns-topic": cfg["topic"],
               "apns-push-type": "alert", "apns-priority": "10"}
    try:
        with httpx.Client(http2=True, timeout=8) as c:
            r = c.post(f"{host}/3/device/{token}", headers=headers, json=payload)
            if r.status_code == 410:                       # token retired
                unregister(data.get("bullpen", ""), token)
            elif r.status_code >= 300:
                print(f"[push] APNs {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"[push] send failed: {e}")
