"""Bumblebee — Beers Bot's voice. Stitches short clips from movies, radio,
and hype tracks into messages, the way Bumblebee uses radio snippets.

Inspired by the Transformers character who can't speak so he communicates
via clips of songs and ads. Our reason is different (the cleanest legal +
brand path away from voice cloning) but the result is the same — every
announcement is a curated collage of the salesfloor canon.

  python3 server/bumblebee.py list
  python3 server/bumblebee.py stitch --tags hype,close,close --out /tmp/out.mp3
  python3 server/bumblebee.py post-welcome
  python3 server/bumblebee.py event close-won
  python3 server/bumblebee.py event new-bullpen

Tag → folder map lives in TAG_DIRS. Clips are picked randomly within a tag;
optionally pin a specific filename via the explicit `clips/<tag>/<file>`
form when stitching.

The stitcher uses ffmpeg's concat filter with explicit volume normalization
(loudnorm) so wildly different sources don't clip when chained. Output is
MP3 at 192kbps — small enough to attach to Discord messages, sounds fine.
"""
from __future__ import annotations
import json
import os
import random
import secrets
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

REPO = Path(__file__).parent.parent
CLIPS_ROOT = REPO / "clips"
DEFAULT_OUT = REPO / "clips" / ".out"
DEFAULT_OUT.mkdir(exist_ok=True)

TAG_DIRS = {
    "hype": "hype",
    "greeting": "greeting",
    "close": "close",
    "hard-truth": "hard-truth",
    "objection": "objection",
    "raid": "raid",
    "taunt": "taunt",
    "taps": "taps",
}

AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".ogg", ".aiff", ".aac")

# Curated stitch recipes per event. Each is a list of tag tokens — they're
# stitched in order. Use the same tag twice for emphasis.
EVENT_RECIPES = {
    "welcome":     ["greeting", "hype", "hard-truth", "taps"],
    "new-bullpen": ["hype", "hype", "close", "taps"],
    "close-won":   ["close", "close", "hype"],
    "raid-start":  ["raid", "hype", "taunt"],
    "duel":        ["taunt", "taps"],
    "sprint":      ["hype", "hype", "raid"],
}


def list_library() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for tag, sub in TAG_DIRS.items():
        d = CLIPS_ROOT / sub
        if not d.exists():
            out[tag] = []
            continue
        out[tag] = sorted(
            str(p.name) for p in d.iterdir()
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS
        )
    return out


def _resolve_clip(spec: str) -> Optional[Path]:
    """Resolve a stitch token. Accepts:
      - 'hype'                    → random clip from clips/hype/
      - 'clips/hype/foo.mp3'      → exact path
      - 'hype/foo.mp3'            → exact path
    """
    spec = spec.strip()
    if not spec:
        return None
    # Tag-only
    if spec in TAG_DIRS:
        d = CLIPS_ROOT / TAG_DIRS[spec]
        candidates = [p for p in d.iterdir()
                       if p.is_file() and p.suffix.lower() in AUDIO_EXTS] if d.exists() else []
        return random.choice(candidates) if candidates else None
    # Explicit path
    p = Path(spec)
    if not p.is_absolute():
        if not str(p).startswith("clips/"):
            p = Path("clips") / p
        p = REPO / p
    return p if p.exists() else None


def stitch(tokens: list[str], out_path: Optional[Path] = None,
            crossfade_ms: int = 80) -> Path:
    """Concatenate a sequence of clips (resolved from tokens) into a single
    MP3. Applies a brief crossfade between segments so cuts don't pop.

    Returns the path of the written MP3. Raises if nothing resolved.
    """
    clips = [c for c in (_resolve_clip(t) for t in tokens) if c]
    if not clips:
        raise RuntimeError("no clips resolved — library empty? Run `bumblebee list`.")
    out_path = out_path or (DEFAULT_OUT / f"stitch-{secrets.token_hex(4)}.mp3")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ffmpeg concat filter with light loudness normalization. Crossfade between
    # adjacent inputs to avoid pops on hard cuts.
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for c in clips:
        cmd += ["-i", str(c)]

    n = len(clips)
    if n == 1:
        # Single clip — just normalize and transcode.
        filter_complex = "[0:a]loudnorm=I=-16:LRA=11:TP=-1.5[out]"
    else:
        # Build a chain: clip0 → normalized [a0], clip1 → [a1], … then
        # acrossfade pairwise.
        norm_parts = []
        for i in range(n):
            norm_parts.append(f"[{i}:a]loudnorm=I=-16:LRA=11:TP=-1.5[a{i}]")
        fade_parts = []
        if n == 2:
            fade_parts.append(f"[a0][a1]acrossfade=d={crossfade_ms/1000}[out]")
        else:
            # First crossfade → tmp1, then chain.
            fade_parts.append(f"[a0][a1]acrossfade=d={crossfade_ms/1000}[t1]")
            for i in range(2, n):
                next_label = "out" if i == n - 1 else f"t{i}"
                fade_parts.append(f"[t{i-1}][a{i}]acrossfade=d={crossfade_ms/1000}[{next_label}]")
        filter_complex = ";".join(norm_parts + fade_parts)
    cmd += ["-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(out_path)]

    r = subprocess.run(cmd, capture_output=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.decode(errors='ignore')[:600]}")
    return out_path


def stitch_event(event: str, out_path: Optional[Path] = None) -> Path:
    """Render the canned recipe for a known event ('welcome', 'new-bullpen',
    'close-won', etc.)."""
    if event not in EVENT_RECIPES:
        raise ValueError(f"unknown event '{event}'. Try: {list(EVENT_RECIPES)}")
    return stitch(EVENT_RECIPES[event], out_path=out_path)


# ── Discord webhook upload (multipart file attachment) ─────────────────────

DISCORD_WEBHOOK_PATHS = {
    "showcase": Path.home() / ".bullpenlm" / "showcase-webhook.txt",
    "start-here": Path.home() / ".bullpenlm" / "start-here-webhook.txt",
}


def _webhook(channel: str) -> Optional[str]:
    p = DISCORD_WEBHOOK_PATHS.get(channel)
    if not p or not p.exists():
        return None
    try:
        return p.read_text().strip() or None
    except Exception:
        return None


def post_audio_to_discord(audio_path: Path, channel: str,
                           caption: str = "") -> dict:
    """POST a stitched audio file to a Discord webhook as a multipart upload.
    Discord renders MP3 attachments with an inline audio player."""
    hook = _webhook(channel)
    if not hook:
        return {"ok": False, "error": f"no_webhook_for_{channel}",
                "hint": f"Put the webhook URL in {DISCORD_WEBHOOK_PATHS.get(channel)}"}
    if not audio_path.exists():
        return {"ok": False, "error": "audio_missing", "path": str(audio_path)}

    boundary = "----bullpenlm-" + secrets.token_hex(8)
    body_parts: list[bytes] = []
    payload = {"username": "Beers Bot"}
    if caption:
        payload["content"] = caption
    body_parts.append(
        (f'--{boundary}\r\n'
         'Content-Disposition: form-data; name="payload_json"\r\n'
         'Content-Type: application/json\r\n\r\n').encode()
    )
    body_parts.append(json.dumps(payload).encode())
    body_parts.append(b"\r\n")
    body_parts.append(
        (f'--{boundary}\r\n'
         f'Content-Disposition: form-data; name="files[0]"; filename="{audio_path.name}"\r\n'
         'Content-Type: audio/mpeg\r\n\r\n').encode()
    )
    body_parts.append(audio_path.read_bytes())
    body_parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(body_parts)

    req = urllib.request.Request(hook, data=body, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "BullpenLM (https://bullpenlm.com, 0.1)",
    })
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
            return {"ok": True, "status": r.status, "channel": channel}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "body": e.read().decode(errors="ignore")[:300]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── CLI ────────────────────────────────────────────────────────────────────

def _cli():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  bumblebee.py list")
        print("  bumblebee.py stitch --tags hype,close,close [--out /tmp/x.mp3]")
        print("  bumblebee.py event <welcome|new-bullpen|close-won|raid-start|duel|sprint>")
        print("  bumblebee.py post-welcome      # stitch the welcome recipe + post to #start-here")
        print("  bumblebee.py post --channel showcase --event new-bullpen [--caption '...']")
        sys.exit(0)
    cmd = sys.argv[1]

    if cmd == "list":
        lib = list_library()
        total = sum(len(v) for v in lib.values())
        print(f"Library at {CLIPS_ROOT} — {total} clip(s) across {len(lib)} tags:")
        for tag in TAG_DIRS:
            files = lib.get(tag) or []
            print(f"  {tag:12} {len(files):3}  {', '.join(files[:5])}{'…' if len(files) > 5 else ''}")
        return

    if cmd == "stitch":
        args = dict(zip(sys.argv[2::2], sys.argv[3::2]))
        tokens = (args.get("--tags") or "hype,close").split(",")
        out = Path(args["--out"]) if "--out" in args else None
        p = stitch(tokens, out_path=out)
        print(f"✓ Wrote {p}")
        return

    if cmd == "event":
        if len(sys.argv) < 3:
            print("× need event name"); sys.exit(1)
        event = sys.argv[2]
        p = stitch_event(event)
        print(f"✓ Wrote {p}")
        return

    if cmd == "post-welcome":
        try:
            p = stitch_event("welcome")
        except Exception as e:
            print(f"× stitch failed: {e}"); sys.exit(1)
        r = post_audio_to_discord(p, channel="start-here",
                                    caption="🔊 The floor speaks. Listen first.")
        print(json.dumps(r, indent=2))
        return

    if cmd == "post":
        args = dict(zip(sys.argv[2::2], sys.argv[3::2]))
        event = args.get("--event") or "new-bullpen"
        channel = args.get("--channel") or "showcase"
        caption = args.get("--caption") or ""
        try:
            p = stitch_event(event)
        except Exception as e:
            print(f"× stitch failed: {e}"); sys.exit(1)
        r = post_audio_to_discord(p, channel=channel, caption=caption)
        print(json.dumps(r, indent=2))
        return

    print(f"× unknown command: {cmd}"); sys.exit(1)


if __name__ == "__main__":
    _cli()
