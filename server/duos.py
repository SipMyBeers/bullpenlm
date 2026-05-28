"""Duos — 1v1 cold-call practice sessions.

Two reps; one plays the SELLER (sees just the prospect name + the open
playbook), one plays the BUYER (sees the full buyer card with objections,
red flags, hot buttons — and must roleplay against the seller).

Lifecycle:
  pending   — challenger created; opponent hasn't accepted yet
  active    — both in; transcript open; timer ticking
  ended     — timer expired OR either rep ended early; scorecard frozen

The transcript is a list of {ts, rep, role, text} entries. Every msg
appends to the transcript AND emits an audit event (kind="duo_msg")
so SSE delivers it to both players in real time.

On end:
  • SELLER earns a duo_call XP event with base 30 XP + bonus for hitting
    each hot-button word + bonus for surviving each objection.
  • BUYER earns a flat 20 XP for participating.
  • Both get a small drill_attempt XP hit too (this counts as practice).

Storage:
  bullpens/<slug>/duos/<id>.json   — full session including transcript
"""
from __future__ import annotations
import datetime
import json
import re
from pathlib import Path
from typing import Optional

from audit import append as audit_append
from audit import iter_all as audit_iter_all
from buyer_cards import generate as buyer_card_generate

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"

DEFAULT_DURATION_MIN = 10


def _duos_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "duos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _duo_path(bullpen: str, duo_id: str) -> Path:
    return _duos_dir(bullpen) / f"{duo_id}.json"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def create(bullpen: str, challenger_rep: str, opponent_rep: str,
           prospect_slug: str, challenger_role: str = "seller",
           duration_minutes: int = DEFAULT_DURATION_MIN) -> dict:
    """Challenger picks the prospect AND the role they want to play.
    Opponent gets the other role on accept."""
    if challenger_rep == opponent_rep:
        raise ValueError("self_duo_not_allowed")
    if challenger_role not in ("seller", "buyer"):
        raise ValueError("invalid_role")

    card = buyer_card_generate(prospect_slug, bullpen=bullpen)
    if not card:
        raise ValueError("prospect_not_found")

    now = datetime.datetime.now()
    duo_id = f"duo-{now.strftime('%Y%m%d-%H%M%S')}-{prospect_slug}"
    opponent_role = "buyer" if challenger_role == "seller" else "seller"
    duo = {
        "id": duo_id,
        "bullpen": bullpen,
        "status": "pending",
        "prospect_slug": prospect_slug,
        "card_persona_name": card["persona"]["name"],
        "duration_minutes": int(duration_minutes),
        "created_at": _now(),
        "accept_by": (now + datetime.timedelta(hours=1)).isoformat(timespec="seconds"),
        "starts_at": None,
        "ends_at": None,
        "ended_at": None,
        "roles": {
            "seller": challenger_rep if challenger_role == "seller" else opponent_rep,
            "buyer":  challenger_rep if challenger_role == "buyer"  else opponent_rep,
        },
        "challenger": challenger_rep,
        "opponent": opponent_rep,
        "transcript": [],
        "scorecard": None,
    }
    _duo_path(bullpen, duo_id).write_text(json.dumps(duo, indent=2) + "\n")
    audit_append(bullpen, challenger_rep, "duo_challenged",
                 target_type="duo", target_id=duo_id,
                 payload={"opponent": opponent_rep, "prospect": prospect_slug,
                          "challenger_role": challenger_role,
                          "duration_minutes": int(duration_minutes)})
    return duo


def accept(bullpen: str, duo_id: str, accepting_rep: str) -> dict:
    p = _duo_path(bullpen, duo_id)
    if not p.exists():
        raise ValueError("duo_not_found")
    duo = json.loads(p.read_text())
    if duo["status"] != "pending":
        raise ValueError(f"duo_status_{duo['status']}")
    if accepting_rep != duo["opponent"]:
        raise ValueError("not_your_duo")
    now = datetime.datetime.now()
    duo["status"] = "active"
    duo["starts_at"] = now.isoformat(timespec="seconds")
    duo["ends_at"] = (now + datetime.timedelta(minutes=int(duo["duration_minutes"]))).isoformat(timespec="seconds")
    p.write_text(json.dumps(duo, indent=2) + "\n")
    audit_append(bullpen, accepting_rep, "duo_accepted",
                 target_type="duo", target_id=duo_id,
                 payload={"challenger": duo["challenger"], "prospect": duo["prospect_slug"]})
    return duo


def msg(bullpen: str, duo_id: str, rep: str, text: str) -> dict:
    p = _duo_path(bullpen, duo_id)
    if not p.exists():
        raise ValueError("duo_not_found")
    duo = json.loads(p.read_text())
    if duo["status"] != "active":
        raise ValueError(f"duo_status_{duo['status']}")
    role = None
    for r, owner in (duo["roles"] or {}).items():
        if owner == rep:
            role = r; break
    if not role:
        raise ValueError("not_in_this_duo")
    text = (text or "").strip()
    if not text:
        raise ValueError("empty_message")
    if len(text) > 2000:
        text = text[:2000]

    entry = {"ts": _now(), "rep": rep, "role": role, "text": text}
    duo["transcript"].append(entry)
    # Auto-end if past the deadline
    if duo.get("ends_at") and _now() > duo["ends_at"]:
        duo = _finalize(bullpen, duo)
    p.write_text(json.dumps(duo, indent=2) + "\n")

    # Push as audit event so SSE delivers to both browsers immediately
    audit_append(bullpen, rep, "duo_msg",
                 target_type="duo", target_id=duo_id,
                 payload={"role": role, "text": text,
                          "transcript_index": len(duo["transcript"]) - 1})
    return entry


def end(bullpen: str, duo_id: str, ending_rep: str) -> dict:
    p = _duo_path(bullpen, duo_id)
    if not p.exists():
        raise ValueError("duo_not_found")
    duo = json.loads(p.read_text())
    if duo["status"] == "ended":
        return duo
    if ending_rep not in (duo["roles"].get("seller"), duo["roles"].get("buyer")):
        raise ValueError("not_in_this_duo")
    duo = _finalize(bullpen, duo)
    p.write_text(json.dumps(duo, indent=2) + "\n")
    return duo


# ── Scoring ──────────────────────────────────────────────────────────────

def _score(duo: dict) -> dict:
    """Compute a simple scorecard from the transcript + buyer card.

    Seller score components (target ~100):
      + 30 base for completing the call
      + 8 per hot-button word landed (capped 40)
      + 6 per pushback the seller addressed (capped 30)
      − 4 per red-flag phrase the seller said (capped −20)
      + 12 if the seller explicitly asked for the next step
    """
    from buyer_cards import generate as bc_generate
    card = bc_generate(duo["prospect_slug"], bullpen=duo["bullpen"]) or {}
    seller = duo["roles"].get("seller")
    seller_lines = [m["text"].lower() for m in duo["transcript"] if m["rep"] == seller]
    buyer_lines  = [m["text"].lower() for m in duo["transcript"] if m["rep"] != seller]
    full_seller = " ".join(seller_lines)

    def hits(phrases):
        total = 0
        for p in (phrases or []):
            words = [w for w in re.findall(r"[a-z0-9]+", p.lower()) if len(w) > 3]
            if not words: continue
            # A "hit" = at least 2 of the distinctive words appear together
            if sum(1 for w in words if w in full_seller) >= min(2, len(words)):
                total += 1
        return total

    hot_hits   = hits(card.get("their_hot_buttons"))
    red_hits   = hits(card.get("their_red_flags"))

    # Pushback addressed = seller said something AFTER a buyer line that
    # contained pushback words.
    addressed = 0
    pushbacks = card.get("their_objections") or []
    for i, line in enumerate(duo["transcript"]):
        if line["rep"] == seller: continue
        text = line["text"].lower()
        for pb in pushbacks:
            words = [w for w in re.findall(r"[a-z0-9]+", pb.lower()) if len(w) > 3]
            if words and sum(1 for w in words if w in text) >= 2:
                # Did seller respond to this?
                if i + 1 < len(duo["transcript"]) and duo["transcript"][i + 1]["rep"] == seller:
                    addressed += 1; break

    asked_for_next_step = any(re.search(r"\b(book|schedule|set up|grab|invite|pencil|calendar|next step|follow.?up)\b", l)
                              for l in seller_lines)

    seller_score = (30
                    + min(40, hot_hits * 8)
                    + min(30, addressed * 6)
                    - min(20, red_hits * 4)
                    + (12 if asked_for_next_step else 0))
    seller_score = max(0, min(120, seller_score))

    return {
        "seller_rep": seller,
        "seller_score": seller_score,
        "hot_buttons_landed": hot_hits,
        "objections_addressed": addressed,
        "red_flags_said": red_hits,
        "asked_for_next_step": asked_for_next_step,
        "seller_lines": len(seller_lines),
        "buyer_lines": len(buyer_lines),
    }


def _finalize(bullpen: str, duo: dict) -> dict:
    duo["status"] = "ended"
    duo["ended_at"] = _now()
    sc = _score(duo)
    duo["scorecard"] = sc

    seller = duo["roles"]["seller"]
    buyer  = duo["roles"]["buyer"]

    # Seller XP scales with score; 30 XP base, +1 per score point above 30.
    seller_xp = 30 + max(0, sc["seller_score"] - 30)
    # XP rules can't reference dynamic deltas without a custom kind, so
    # we use quest_completed (which lets us pass xp_reward in payload).
    audit_append(bullpen, seller, "quest_completed",
                 target_type="duo", target_id=duo["id"],
                 payload={"quest_name": "Duo · " + duo["prospect_slug"],
                          "scope": "duo", "xp_reward": seller_xp,
                          "score": sc["seller_score"]})

    # Buyer gets a flat reward for showing up + playing the part
    audit_append(bullpen, buyer, "quest_completed",
                 target_type="duo", target_id=duo["id"],
                 payload={"quest_name": "Duo (buyer) · " + duo["prospect_slug"],
                          "scope": "duo", "xp_reward": 20})

    # And both get a drill_attempt for the practice-call count
    audit_append(bullpen, seller, "drill_attempt",
                 target_type="duo", target_id=duo["id"],
                 payload={"role": "seller", "score": sc["seller_score"]})
    audit_append(bullpen, buyer, "drill_attempt",
                 target_type="duo", target_id=duo["id"],
                 payload={"role": "buyer"})

    try:
        from xp import invalidate as xp_invalidate
        xp_invalidate(bullpen)
    except Exception: pass

    return duo


# ── Listing / lookup ─────────────────────────────────────────────────────

def get(bullpen: str, duo_id: str) -> Optional[dict]:
    p = _duo_path(bullpen, duo_id)
    if not p.exists(): return None
    try: return json.loads(p.read_text())
    except Exception: return None


def list_for_rep(bullpen: str, rep: Optional[str] = None,
                 status: Optional[str] = None) -> list[dict]:
    out = []
    for f in sorted(_duos_dir(bullpen).glob("*.json"), reverse=True):
        try: d = json.loads(f.read_text())
        except Exception: continue
        if rep and rep not in (d.get("roles") or {}).values():
            continue
        if status and d.get("status") != status:
            continue
        out.append(d)
    return out


# ── Lobby / matchmaking ──────────────────────────────────────────────────
#
# In-memory queue: reps waiting for a quick-match opponent. A new request
# pairs with the first waiter on the OTHER role (seller looking → match
# with first buyer waiter) AND the same prospect_slug if specified.

import threading as _threading
_lobby_lock = _threading.Lock()
_lobby: dict[str, list[dict]] = {}   # bullpen → [{rep, role, prospect_slug, ts}]


def lobby_join(bullpen: str, rep: str, role: str,
               prospect_slug: Optional[str] = None) -> dict:
    """Returns either {'matched': True, 'duo': <duo>} or {'matched': False}."""
    if role not in ("seller", "buyer"):
        raise ValueError("invalid_role")
    other = "buyer" if role == "seller" else "seller"
    now = datetime.datetime.now().isoformat(timespec="seconds")

    with _lobby_lock:
        waiters = _lobby.setdefault(bullpen, [])
        # Match against any waiter of the opposite role; if prospect_slug
        # is set, prefer a match on the same prospect.
        match = None
        for w in waiters:
            if w["rep"] == rep: continue
            if w["role"] != other: continue
            if prospect_slug and w.get("prospect_slug") and w["prospect_slug"] != prospect_slug:
                continue
            match = w; break
        if match:
            waiters.remove(match)
            # Use challenger=match.rep so the OTHER side accepts.
            challenger_role = match["role"]
            duo = create(
                bullpen,
                challenger_rep=match["rep"],
                opponent_rep=rep,
                prospect_slug=prospect_slug or match.get("prospect_slug") or "accenture-mainframe",
                challenger_role=challenger_role,
            )
            # Auto-accept since both reps were in the lobby (consenting)
            duo = accept(bullpen, duo["id"], rep)
            return {"matched": True, "duo": duo}

        # Drop any prior queue entry for this rep, then add fresh
        waiters[:] = [w for w in waiters if w["rep"] != rep]
        waiters.append({"rep": rep, "role": role,
                        "prospect_slug": prospect_slug, "ts": now})
        return {"matched": False, "waiting": len(waiters)}


def lobby_leave(bullpen: str, rep: str) -> dict:
    with _lobby_lock:
        waiters = _lobby.get(bullpen) or []
        waiters[:] = [w for w in waiters if w["rep"] != rep]
        return {"waiting": len(waiters)}


def lobby_state(bullpen: str) -> dict:
    with _lobby_lock:
        return {"waiters": list(_lobby.get(bullpen) or [])}
