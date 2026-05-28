"""Live-audio bridge — teammates listen in while a closer is on a call.

The product moment: Marcus is drilling Cigna at his desk. The rest of
the floor sees a 🔴 LIVE badge on the office iso-view next to his
avatar. Click → audio player opens and they hear the call as it
happens, about 4-6 seconds behind real-time.

Architecture (zero new infra)
=============================

  Closer's browser:
    Continuous MediaRecorder loop. Every ~3s it stops the current
    recording (which flushes a self-contained WebM/Opus file),
    starts a new one, and POSTs the just-finished blob to
    /api/b/<slug>/live/<call_id>/chunk?seq=N.

  Server (this module):
    Writes each chunk to
        bullpens/<slug>/live_calls/<call_id>/chunks/seq_<n>.webm
    Updates
        bullpens/<slug>/live_calls/<call_id>/meta.json
    so the active-calls index stays current.

  Listener's browser:
    Polls /api/b/<slug>/live/<call_id>/chunks?since=N every ~1.5s,
    appends new chunks to a play queue, and chains them through an
    <audio> element via the 'ended' event. ~4-6s end-to-end latency.

Why not HLS / WebRTC?
=====================
HLS would require server-side ffmpeg transcoding from Opus → AAC and a
fragmented-mp4 init segment dance for sub-10s latency. WebRTC would
require an SFU and STUN/TURN infra. For the friends-cohort bullpen size
(≤20 listeners per call) the dumb chunk-queue pattern is sufficient and
adds zero deps.

Privacy / consent (v1 scope = drills only)
==========================================
Drills are between a closer and an AI buyer. No external party, no
TCPA. Listen-in is always-on for drill mode. Real-call broadcast is
deferred to v4 of the listen-in roadmap (requires both-party consent
UI + a recording-disclosure overlay).

State on disk
=============
  bullpens/<slug>/live_calls/<call_id>/
    meta.json              ← {call_id, rep, kind, buyer, started_at,
                              ended_at, latest_seq}
    chunks/seq_<n>.webm    ← self-contained Opus chunks (~3s each,
                              ~30 KB at 64 kbps stereo)
"""
from __future__ import annotations
import datetime
import json
import re
from pathlib import Path
from typing import Optional

from paths import DATA_DIR as REPO


_VALID_ID = re.compile(r"^[a-zA-Z0-9_\-]{1,80}$")
_VALID_EMOJI = {"🔥", "💯", "❗", "👀", "🥶", "🤝"}


def _root(bullpen: str) -> Path:
    return REPO / "bullpens" / bullpen / "live_calls"


def _call_dir(bullpen: str, call_id: str) -> Path:
    if not _VALID_ID.match(call_id or ""):
        raise ValueError(f"invalid call_id: {call_id!r}")
    return _root(bullpen) / call_id


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# ── Lifecycle ─────────────────────────────────────────────────────────────

def start_call(bullpen: str, *, call_id: str, rep: str, kind: str,
               buyer: Optional[str] = None,
               title: Optional[str] = None) -> dict:
    """Begin a broadcastable call. Returns the meta record.

    kind: 'drill' | 'real' (only 'drill' wired for listeners in v1)
    """
    d = _call_dir(bullpen, call_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "chunks").mkdir(exist_ok=True)
    meta_path = d / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
    else:
        meta = {
            "call_id": call_id,
            "rep": rep,
            "kind": kind,
            "buyer": buyer,
            "title": title or buyer or "Live call",
            "started_at": _now_iso(),
            "ended_at": None,
            "latest_seq": -1,
        }
    meta_path.write_text(json.dumps(meta, indent=2))
    return meta


def save_chunk(bullpen: str, call_id: str, seq: int, blob: bytes) -> dict:
    """Store one audio chunk. Returns the updated meta."""
    if not isinstance(seq, int) or seq < 0 or seq > 99999:
        raise ValueError(f"bad seq: {seq!r}")
    if not blob or len(blob) > 5_000_000:
        # 5MB cap per chunk — anything bigger is misuse.
        raise ValueError(f"bad blob size: {len(blob) if blob else 0}")
    d = _call_dir(bullpen, call_id)
    meta_path = d / "meta.json"
    if not meta_path.exists():
        raise ValueError(f"call not started: {call_id!r}")
    meta = json.loads(meta_path.read_text())
    if meta.get("ended_at"):
        raise ValueError(f"call already ended: {call_id!r}")
    chunk_path = d / "chunks" / f"seq_{seq}.webm"
    chunk_path.write_bytes(blob)
    if seq > meta["latest_seq"]:
        meta["latest_seq"] = seq
    meta["last_chunk_at"] = _now_iso()
    meta_path.write_text(json.dumps(meta, indent=2))
    return meta


# ── Reactions ─────────────────────────────────────────────────────────────
#
# Listeners on /app/tunein.html tap an emoji button to broadcast a
# reaction to the closer. The closer's voice.html polls /reactions and
# pops a transient overlay. Kept tiny on disk — appended to a JSONL file,
# never grows past the call's lifetime. Each event:
#   {seq, ts, emoji, from_rep}

def add_reaction(bullpen: str, call_id: str, *, emoji: str,
                  from_rep: str) -> dict:
    if emoji not in _VALID_EMOJI:
        raise ValueError(f"unknown emoji: {emoji!r}")
    d = _call_dir(bullpen, call_id)
    meta_path = d / "meta.json"
    if not meta_path.exists():
        raise ValueError(f"call not started: {call_id!r}")
    rxn_path = d / "reactions.jsonl"
    seq = 0
    if rxn_path.exists():
        # Cheap: count lines. Reactions per call are bounded (~dozens) so
        # this is fine vs. maintaining a counter file.
        seq = sum(1 for _ in rxn_path.open())
    event = {
        "seq": seq,
        "ts": _now_iso(),
        "emoji": emoji,
        "from_rep": (from_rep or "").strip()[:80] or "anon",
    }
    with rxn_path.open("a") as f:
        f.write(json.dumps(event) + "\n")
    return event


def list_reactions(bullpen: str, call_id: str, *, since: int = -1) -> list[dict]:
    d = _call_dir(bullpen, call_id)
    rxn_path = d / "reactions.jsonl"
    if not rxn_path.exists():
        return []
    out = []
    with rxn_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("seq", -1) > since:
                out.append(ev)
    return out


def end_call(bullpen: str, call_id: str) -> dict:
    d = _call_dir(bullpen, call_id)
    meta_path = d / "meta.json"
    if not meta_path.exists():
        raise ValueError(f"call not found: {call_id!r}")
    meta = json.loads(meta_path.read_text())
    if not meta.get("ended_at"):
        meta["ended_at"] = _now_iso()
        meta_path.write_text(json.dumps(meta, indent=2))
    return meta


# ── Read paths (for listeners) ────────────────────────────────────────────

def get_meta(bullpen: str, call_id: str) -> Optional[dict]:
    d = _call_dir(bullpen, call_id)
    meta_path = d / "meta.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


def list_chunks(bullpen: str, call_id: str, *, since: int = -1) -> list[dict]:
    """Return chunks with seq > since, oldest first."""
    d = _call_dir(bullpen, call_id) / "chunks"
    if not d.exists():
        return []
    out = []
    for p in d.glob("seq_*.webm"):
        m = re.match(r"seq_(\d+)\.webm$", p.name)
        if not m:
            continue
        seq = int(m.group(1))
        if seq <= since:
            continue
        st = p.stat()
        out.append({
            "seq": seq,
            "size_bytes": st.st_size,
            "mtime": st.st_mtime,
        })
    out.sort(key=lambda c: c["seq"])
    return out


def read_chunk(bullpen: str, call_id: str, seq: int) -> Optional[bytes]:
    d = _call_dir(bullpen, call_id) / "chunks"
    p = d / f"seq_{seq}.webm"
    if not p.exists() or not p.is_file():
        return None
    return p.read_bytes()


# ── Active-calls index ────────────────────────────────────────────────────

# A call counts as "active" if its meta has no ended_at AND it received
# a chunk within the last STALE_AFTER_SEC seconds (so closers who close
# their tab without calling end_call get auto-cleaned out of the UI).
STALE_AFTER_SEC = 20


def list_active(bullpen: str) -> list[dict]:
    root = _root(bullpen)
    if not root.exists():
        return []
    now = datetime.datetime.now()
    out = []
    for call_dir in root.iterdir():
        if not call_dir.is_dir():
            continue
        meta_path = call_dir / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            continue
        if meta.get("ended_at"):
            continue
        # Stale check
        last = meta.get("last_chunk_at") or meta.get("started_at")
        try:
            last_dt = datetime.datetime.fromisoformat(last)
        except Exception:
            continue
        if (now - last_dt).total_seconds() > STALE_AFTER_SEC:
            continue  # silently dropped; doesn't auto-end the call
        out.append({
            "call_id":     meta["call_id"],
            "rep":         meta.get("rep"),
            "kind":        meta.get("kind"),
            "buyer":       meta.get("buyer"),
            "title":       meta.get("title"),
            "started_at":  meta.get("started_at"),
            "latest_seq":  meta.get("latest_seq", -1),
            "seconds_in":  int((now - last_dt).total_seconds()),
        })
    out.sort(key=lambda c: c.get("started_at") or "", reverse=True)
    return out
