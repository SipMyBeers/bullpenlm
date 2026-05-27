"""Marketing post tracker + outcome attribution.

The Phase 0.5 firewall says: closers earn money from CLOSED DEALS with
real external customers, never from recruitment activity. Marketing is
the *good* opposite of recruitment — closers promoting the product to
strangers, who become real customers.

Mechanism
=========

  1. Closer publishes a marketing post on Twitter / LinkedIn / Discord /
     blog. They register it here with the post URL + channel + topic.
  2. We mint a per-post tracking token. The closer pastes a tracked
     link (https://app.bullpenlm.com/m/<token>?dest=<landing>) into their
     post.
  3. Visitors click the link → server bumps the click counter + audits
     a `marketing_post_clicked` event → redirects to the destination.
  4. If a visitor then signs up / converts (separate POST from the
     landing or onboard flow with ?ref=<token>), we attribute it back
     to the originating post → audit `marketing_lead_signed` → that
     post's closer earns MONEY-XP.
  5. If a deal is later closed traceable to that lead, audit
     `marketing_deal_closed` → more money-XP.

Storage
=======

  bullpens/<slug>/marketing/posts/<post_id>.json
    {
      "id":           "post-YYYYMMDD-HHMMSS-XX",
      "rep":          "kelly",
      "channel":      "twitter|linkedin|discord|blog|other",
      "url":          "https://twitter.com/kelly/status/...",   (where the post lives)
      "topic":        "killsesh|bullpenlm|general",
      "dest":         "landing"|"signup"|"demo"|...,            (where the tracked link should point)
      "tracking_token": "MKT-<8-chars>",
      "outbound_url": "https://bullpenlm.com/?ref=...",
      "created_at":   ISO8601,
      "metrics": {
        "clicks":            0,
        "unique_clicks":     0,
        "leads_attributed":  0,
        "deals_attributed":  0,
      }
    }
  bullpens/<slug>/marketing/tokens.json          { token: post_id, ... } (index)
  bullpens/<slug>/marketing/clicks.jsonl         append-only per-click log

Marketing destinations (where the tracked link can route to). All are
on the *product* side — the bullpenlm.com landing, the bullpen's own
public roster page, or a specific demo URL. NONE of them point at a
closer-recruitment surface. The firewall enforces this.
"""
from __future__ import annotations
import datetime
import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"

# Whitelist of destinations a tracked link can route to. Anything not in
# this list is rejected at registration time. This is the structural
# guarantee against using marketing-XP-credited links to drive recruitment.
ALLOWED_DESTS = {
    "landing": "https://bullpenlm.com/",
    "signup": "https://bullpenlm.com/signup",      # future: product signup page
    "demo": "https://bullpenlm.com/demo",          # future: product demo
    "github": "https://github.com/SipMyBeers/bullpenlm",
}


def _mk_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "marketing"
    (d / "posts").mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _audit(bullpen: str, actor: str, kind: str, payload: dict) -> None:
    try:
        from audit import append as audit_append
        audit_append(bullpen, actor, kind, target_type="marketing",
                     target_id=payload.get("post_id", ""), payload=payload)
    except Exception:
        pass


def _tokens_index_path(bullpen: str) -> Path:
    return _mk_dir(bullpen) / "tokens.json"


def _load_tokens(bullpen: str) -> dict:
    p = _tokens_index_path(bullpen)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_tokens(bullpen: str, index: dict) -> None:
    _tokens_index_path(bullpen).write_text(json.dumps(index, indent=2))


def _post_path(bullpen: str, post_id: str) -> Path:
    return _mk_dir(bullpen) / "posts" / f"{post_id}.json"


# ── Registration ──────────────────────────────────────────────────────────

def register_post(
    bullpen: str,
    *,
    rep: str,
    url: str,
    channel: str,
    topic: str = "general",
    dest: str = "landing",
) -> dict:
    """Register a new marketing post. Returns the post record + the
    tracked URL the closer should embed."""
    if channel not in ("twitter", "linkedin", "discord", "blog", "youtube", "other"):
        raise ValueError(f"invalid channel: {channel}")
    if dest not in ALLOWED_DESTS:
        raise ValueError(f"invalid dest (allowed: {list(ALLOWED_DESTS)}): {dest}")
    if not url or not url.startswith(("http://", "https://")):
        raise ValueError("url must be a valid http(s) URL")
    if not rep:
        raise ValueError("rep required")

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    post_id = f"post-{ts}-{secrets.token_hex(3)}"
    token = f"MKT-{secrets.token_urlsafe(6).upper().replace('-','').replace('_','')[:8]}"

    base = ALLOWED_DESTS[dest]
    separator = "&" if "?" in base else "?"
    outbound_url = f"{base}{separator}ref={token}"

    record = {
        "id": post_id,
        "rep": rep,
        "channel": channel,
        "url": url,
        "topic": topic,
        "dest": dest,
        "tracking_token": token,
        "outbound_url": outbound_url,
        "created_at": _now(),
        "metrics": {"clicks": 0, "unique_clicks": 0, "leads_attributed": 0, "deals_attributed": 0},
    }
    _post_path(bullpen, post_id).write_text(json.dumps(record, indent=2))

    index = _load_tokens(bullpen)
    index[token] = post_id
    _save_tokens(bullpen, index)

    _audit(bullpen, rep, "marketing_post_published", {
        "post_id": post_id, "channel": channel, "topic": topic, "url": url,
        "tracking_token": token, "dest": dest,
    })
    return record


# ── Click tracking ────────────────────────────────────────────────────────

def record_click(bullpen: str, token: str, *, ip: Optional[str] = None,
                 user_agent: Optional[str] = None) -> Optional[dict]:
    """Bump click counter for the post with this token. Returns the post
    record (so the caller can know where to redirect). None if token unknown."""
    index = _load_tokens(bullpen)
    post_id = index.get(token)
    if not post_id:
        return None
    p = _post_path(bullpen, post_id)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text())
    except Exception:
        return None

    # Append to clicks log (for uniqueness analysis later)
    clicks_log = _mk_dir(bullpen) / "clicks.jsonl"
    ip_hash = hashlib.sha256((ip or "").encode()).hexdigest()[:12] if ip else ""
    line = json.dumps({
        "ts": _now(),
        "token": token,
        "post_id": post_id,
        "ip_sha": ip_hash,
        "ua": (user_agent or "")[:200],
    })
    with clicks_log.open("a") as f:
        f.write(line + "\n")

    # Update counters — read previous clicks log for uniqueness
    rec["metrics"]["clicks"] = rec["metrics"].get("clicks", 0) + 1
    if ip_hash:
        seen = set()
        try:
            for ln in clicks_log.read_text().splitlines():
                try:
                    entry = json.loads(ln)
                    if entry.get("post_id") == post_id and entry.get("ip_sha"):
                        seen.add(entry["ip_sha"])
                except Exception:
                    pass
        except Exception:
            seen = {ip_hash}
        rec["metrics"]["unique_clicks"] = len(seen)
    p.write_text(json.dumps(rec, indent=2))

    _audit(bullpen, rec["rep"], "marketing_post_clicked", {
        "post_id": post_id, "tracking_token": token,
    })
    return rec


# ── Attribution (outcome) ─────────────────────────────────────────────────

def attribute_signup(bullpen: str, token: str, *, who: str = "anonymous") -> Optional[dict]:
    """Called when a signup happens with ?ref=<token>. Credits money-XP
    to the originating closer."""
    rec = _post_by_token(bullpen, token)
    if not rec:
        return None
    rec["metrics"]["leads_attributed"] = rec["metrics"].get("leads_attributed", 0) + 1
    _post_path(bullpen, rec["id"]).write_text(json.dumps(rec, indent=2))
    _audit(bullpen, rec["rep"], "marketing_lead_signed", {
        "post_id": rec["id"], "tracking_token": token, "signed_who": who,
    })
    return rec


def attribute_deal_closed(bullpen: str, token: str, *, deal_id: str, amount: float = 0) -> Optional[dict]:
    """Called when a closed-won deal traces back to a marketing token."""
    rec = _post_by_token(bullpen, token)
    if not rec:
        return None
    rec["metrics"]["deals_attributed"] = rec["metrics"].get("deals_attributed", 0) + 1
    _post_path(bullpen, rec["id"]).write_text(json.dumps(rec, indent=2))
    _audit(bullpen, rec["rep"], "marketing_deal_closed", {
        "post_id": rec["id"], "tracking_token": token, "deal_id": deal_id, "amount": amount,
    })
    return rec


# ── Listing / management ──────────────────────────────────────────────────

def list_posts(bullpen: str, *, rep: Optional[str] = None) -> list[dict]:
    out = []
    p = _mk_dir(bullpen) / "posts"
    if not p.exists():
        return out
    for f in sorted(p.glob("*.json"), reverse=True):
        try:
            rec = json.loads(f.read_text())
        except Exception:
            continue
        if rep and rec.get("rep") != rep:
            continue
        out.append(rec)
    return out


def get_post(bullpen: str, post_id: str) -> Optional[dict]:
    p = _post_path(bullpen, post_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _post_by_token(bullpen: str, token: str) -> Optional[dict]:
    index = _load_tokens(bullpen)
    pid = index.get(token)
    if not pid:
        return None
    return get_post(bullpen, pid)


def aggregate_stats(bullpen: str) -> dict:
    """Aggregate marketing metrics across all posts in the bullpen."""
    posts = list_posts(bullpen)
    by_rep: dict[str, dict] = {}
    total = {"posts": 0, "clicks": 0, "unique_clicks": 0,
             "leads": 0, "deals": 0}
    for rec in posts:
        total["posts"] += 1
        m = rec.get("metrics") or {}
        total["clicks"] += m.get("clicks", 0)
        total["unique_clicks"] += m.get("unique_clicks", 0)
        total["leads"] += m.get("leads_attributed", 0)
        total["deals"] += m.get("deals_attributed", 0)
        rep = rec.get("rep", "?")
        slot = by_rep.setdefault(rep, {"posts": 0, "clicks": 0, "leads": 0, "deals": 0})
        slot["posts"] += 1
        slot["clicks"] += m.get("clicks", 0)
        slot["leads"] += m.get("leads_attributed", 0)
        slot["deals"] += m.get("deals_attributed", 0)
    return {"total": total, "by_rep": by_rep, "post_count": len(posts)}
