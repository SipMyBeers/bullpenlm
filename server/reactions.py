"""Reactions — emoji reactions on audit events.

Teammates react to events as they fly by in the ticker. Reactions are
themselves audit events (kind="reaction"), so they show up in the same
SSE stream and contribute to a "people who hyped each other" view later.

Storage: a single jsonl per bullpen at bullpens/<slug>/reactions.jsonl —
small, append-only, easy to fold into the audit log.
"""
from __future__ import annotations
import json
from pathlib import Path

from audit import append as audit_append

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"

# Hard-coded allow-list — keeps reactions playful but bounded.
ALLOWED_EMOJI = {"🔥", "👏", "💰", "💀", "🏆", "🙏", "🎯", "📈", "🥶", "🚀"}


def _reactions_path(bullpen: str) -> Path:
    return BULLPENS_ROOT / bullpen / "reactions.jsonl"


def react(bullpen: str, event_id: str, rep: str, emoji: str) -> dict:
    if emoji not in ALLOWED_EMOJI:
        raise ValueError("emoji_not_allowed")
    if not event_id or not rep:
        raise ValueError("missing_event_or_rep")

    # Don't double-react with the same emoji from the same rep on the same event.
    p = _reactions_path(bullpen)
    if p.exists():
        for line in p.read_text().splitlines():
            try: r = json.loads(line)
            except Exception: continue
            if (r.get("event_id") == event_id and r.get("rep") == rep
                    and r.get("emoji") == emoji):
                return r   # idempotent

    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {"event_id": event_id, "rep": rep, "emoji": emoji}
    with p.open("a") as f:
        f.write(json.dumps(entry) + "\n")

    audit_append(bullpen, rep, "reaction",
                 target_type="event", target_id=event_id,
                 payload={"emoji": emoji})
    return entry


def counts_for_events(bullpen: str, event_ids: list[str]) -> dict[str, dict]:
    """Return {event_id: {emoji: [reps...]}} aggregating reactions for a
    set of event IDs. The caller passes the IDs it wants to overlay."""
    wanted = set(event_ids)
    out: dict[str, dict[str, list[str]]] = {}
    p = _reactions_path(bullpen)
    if not p.exists():
        return {}
    for line in p.read_text().splitlines():
        try: r = json.loads(line)
        except Exception: continue
        eid = r.get("event_id")
        if eid not in wanted: continue
        slot = out.setdefault(eid, {})
        reps = slot.setdefault(r["emoji"], [])
        if r["rep"] not in reps:
            reps.append(r["rep"])
    return out
