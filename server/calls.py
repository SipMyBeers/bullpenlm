"""Live call sessions — closers stream mic audio to whisper, coaches subscribe
to the live transcript and type advice that pops up on the closer's screen.

Architecture:
  * `start_call(bullpen, rep, prospect)` — opens a session, returns call_id.
  * `add_transcript_chunk(...)` — closer's MediaRecorder posts audio every
    ~5s, server transcodes opus→wav via ffmpeg and pipes through whisper-cli;
    the text snippet gets appended to the session log and published to the
    bullpen's SSE channel as kind=call_transcript.
  * `add_coach_message(...)` — coaches POST short messages, server appends
    them to the session log and broadcasts as kind=call_coach so the
    closer's page shows a toast.
  * `end_call(call_id)` — marks complete; the closer's record button toggles.
  * `list_active_calls(bullpen)` — index page for coaches who want to drop in.

Storage: each call is an append-only JSONL at
  bullpens/<slug>/calls/<call_id>.jsonl
Active sessions tracked in-memory; reconstructed on restart by scanning
the calls/ folder for files without an `ended_at` marker.

Whisper hallucinates on silence, so we skip chunks that ffmpeg reports as
< 0.8 seconds of audio. ffmpeg + whisper run synchronously per chunk on a
worker thread so the request returns fast.
"""
from __future__ import annotations
import datetime
import json
import secrets
import subprocess
import threading
from pathlib import Path
from typing import Optional

from events import publish

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"


def _calls_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "calls"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_path(bullpen: str, call_id: str) -> Path:
    return _calls_dir(bullpen) / f"{call_id}.jsonl"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _append(bullpen: str, call_id: str, record: dict) -> None:
    """Append a JSONL record to the call's log."""
    path = _session_path(bullpen, call_id)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _read_all(bullpen: str, call_id: str) -> list[dict]:
    path = _session_path(bullpen, call_id)
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try: out.append(json.loads(line))
        except Exception: continue
    return out


def _meta(bullpen: str, call_id: str) -> Optional[dict]:
    """Return the first record (call_started) for this session."""
    records = _read_all(bullpen, call_id)
    for r in records:
        if r.get("kind") == "call_started":
            return r
    return None


def _is_active(bullpen: str, call_id: str) -> bool:
    for r in _read_all(bullpen, call_id):
        if r.get("kind") == "call_ended":
            return False
    return True


def start_call(bullpen: str, rep: str, prospect: str = "",
                deal_id: str = "") -> dict:
    call_id = "call-" + secrets.token_urlsafe(7)[:10].replace("_", "z").replace("-", "y")
    rec = {
        "kind": "call_started",
        "call_id": call_id,
        "bullpen": bullpen,
        "rep": (rep or "").strip(),
        "prospect": (prospect or "").strip(),
        "deal_id": (deal_id or "").strip(),
        "started_at": _now(),
    }
    _append(bullpen, call_id, rec)
    publish(bullpen, {**rec, "kind": "call_started"})
    return rec


def add_transcript_chunk(bullpen: str, call_id: str, text: str,
                          chunk_seconds: float = 0.0) -> dict:
    text = (text or "").strip()
    if not text:
        return {"ok": True, "skipped": "empty"}
    rec = {
        "kind": "call_transcript",
        "call_id": call_id,
        "text": text,
        "chunk_seconds": chunk_seconds,
        "at": _now(),
    }
    _append(bullpen, call_id, rec)
    publish(bullpen, rec)
    return {"ok": True}


def add_coach_message(bullpen: str, call_id: str, coach: str, message: str) -> dict:
    message = (message or "").strip()[:600]
    if not message:
        return {"ok": False, "error": "empty_message"}
    if not _is_active(bullpen, call_id):
        return {"ok": False, "error": "call_ended"}
    rec = {
        "kind": "call_coach",
        "call_id": call_id,
        "coach": (coach or "anon").strip(),
        "message": message,
        "at": _now(),
    }
    _append(bullpen, call_id, rec)
    publish(bullpen, rec)
    return {"ok": True}


def end_call(bullpen: str, call_id: str) -> dict:
    if not _is_active(bullpen, call_id):
        return {"ok": True, "already_ended": True}
    rec = {
        "kind": "call_ended",
        "call_id": call_id,
        "ended_at": _now(),
    }
    _append(bullpen, call_id, rec)
    publish(bullpen, rec)
    return {"ok": True}


def get_call(bullpen: str, call_id: str) -> Optional[dict]:
    meta = _meta(bullpen, call_id)
    if not meta:
        return None
    records = _read_all(bullpen, call_id)
    transcript = [r for r in records if r.get("kind") == "call_transcript"]
    coach_msgs = [r for r in records if r.get("kind") == "call_coach"]
    ended = next((r for r in records if r.get("kind") == "call_ended"), None)
    return {
        **meta,
        "active": ended is None,
        "ended_at": ended.get("ended_at") if ended else None,
        "transcript": transcript,
        "coach_messages": coach_msgs,
    }


def list_active_calls(bullpen: str) -> list[dict]:
    d = _calls_dir(bullpen)
    out = []
    for p in sorted(d.glob("call-*.jsonl"), reverse=True):
        call_id = p.stem
        if not _is_active(bullpen, call_id):
            continue
        m = _meta(bullpen, call_id)
        if m:
            out.append({
                "call_id": call_id,
                "rep": m.get("rep"),
                "prospect": m.get("prospect"),
                "deal_id": m.get("deal_id"),
                "started_at": m.get("started_at"),
            })
    return out


# ── Audio pipeline: opus chunk → 16kHz mono WAV → whisper ──────────────────
# Imported lazily to avoid pulling the whisper bits into modules that
# never need them.

def transcribe_chunk(opus_bytes: bytes, min_seconds: float = 0.8) -> dict:
    """Run an opus/webm audio chunk through ffmpeg + whisper.cpp.

    Returns {ok, text, chunk_seconds, skipped?}.
    Skips chunks shorter than `min_seconds` (whisper hallucinates worst
    on near-silent or sub-second audio).
    """
    if not opus_bytes:
        return {"ok": True, "text": "", "skipped": "empty"}
    # Probe duration
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", "-i", "pipe:0"],
            input=opus_bytes, capture_output=True, timeout=8,
        )
        dur = float(probe.stdout.decode().strip() or 0)
    except Exception:
        dur = 0.0
    if dur and dur < min_seconds:
        return {"ok": True, "text": "", "chunk_seconds": dur, "skipped": "too_short"}

    # Transcode to 16kHz mono WAV
    try:
        ff = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", "pipe:0",
             "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1"],
            input=opus_bytes, capture_output=True, timeout=15,
        )
        if ff.returncode != 0:
            return {"ok": False, "error": "ffmpeg_failed",
                    "stderr": ff.stderr.decode(errors="ignore")[:200]}
        wav = ff.stdout
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ffmpeg_timeout"}
    except FileNotFoundError:
        return {"ok": False, "error": "ffmpeg_not_installed"}

    # Defer transcribe_wav import to avoid loading the heavy server module
    # before it's fully initialised.
    from server import transcribe_wav
    try:
        text = transcribe_wav(wav)
    except Exception as e:
        return {"ok": False, "error": "whisper_failed", "detail": str(e)}
    return {"ok": True, "text": text, "chunk_seconds": dur}
