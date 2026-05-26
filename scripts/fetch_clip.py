#!/usr/bin/env python3
"""Fetch a Bumblebee clip from a URL (typically YouTube) + trim it to the
specified time range, normalize loudness, and save into the right mood
folder.

Usage:
  fetch_clip.py URL --start 12.4 --end 15.2 --mood hard-truth --name wolf-pick-up-phone
  fetch_clip.py URL --start 1:24 --end 1:28 --mood close --name wolf-cash-register

  # Process a manifest of multiple clips
  fetch_clip.py --manifest clips/SOURCING.yaml

Behind the scenes: yt-dlp downloads bestaudio → ffmpeg -ss/-to → loudnorm
→ MP3 192k → clips/<mood>/<name>.mp3.

The clip files stay local (gitignored). What you're doing is your problem
under fair use — short, transformative, non-substitutive use of copyrighted
audio for collage commentary. Use accordingly.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent
CLIPS_ROOT = REPO / "clips"
VALID_MOODS = {"hype", "greeting", "close", "hard-truth",
                "objection", "raid", "taunt", "taps"}


def _parse_ts(spec: str) -> float:
    if spec.strip().upper() == "REVIEW":
        raise ValueError("timestamp is REVIEW — scrub the video and replace with seconds")
    """Accepts '12.4', '12.4s', '1:24', '1:24.5', '1:01:24'. Returns seconds."""
    spec = spec.strip().rstrip("s")
    if not spec:
        raise ValueError("empty timestamp")
    if ":" in spec:
        parts = spec.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        raise ValueError(f"bad timestamp: {spec!r}")
    return float(spec)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "clip"


def fetch_one(url: str, start: float, end: float, mood: str, name: str,
               crossfade_pad_ms: int = 100) -> Path:
    if mood not in VALID_MOODS:
        raise ValueError(f"mood must be one of {VALID_MOODS}")
    if end <= start:
        raise ValueError("end must be > start")
    dest_dir = CLIPS_ROOT / mood
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{_slug(name)}.mp3"

    with tempfile.TemporaryDirectory() as td:
        tmp_audio = Path(td) / "src.m4a"
        # 1. yt-dlp → bestaudio (m4a usually, ffmpeg can read whatever)
        print(f"  ↓ yt-dlp {url}")
        r = subprocess.run([
            "yt-dlp", "-f", "bestaudio", "-q",
            "-o", str(tmp_audio.with_suffix(".%(ext)s")),
            url,
        ], capture_output=True, timeout=180)
        if r.returncode != 0:
            raise RuntimeError(f"yt-dlp failed: {r.stderr.decode(errors='ignore')[:300]}")
        # Find the actual downloaded file (extension varies)
        candidates = list(Path(td).iterdir())
        src = next((c for c in candidates if c.is_file()), None)
        if not src:
            raise RuntimeError("yt-dlp produced no file")

        # 2. ffmpeg: trim + loudnorm + transcode to MP3
        duration = end - start
        print(f"  ✂ trim {start}→{end} ({duration:.2f}s) + loudnorm")
        ff = subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{start:.3f}",
            "-to", f"{end:.3f}",
            "-i", str(src),
            "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(dest),
        ], capture_output=True, timeout=60)
        if ff.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {ff.stderr.decode(errors='ignore')[:300]}")

    print(f"  ✓ wrote {dest.relative_to(REPO)}")
    return dest


def fetch_manifest(path: Path) -> list[Path]:
    """Process a YAML/JSON manifest of {url, start, end, mood, name}.

    YAML format (preferred — comments allowed for sourcing notes):

      - url: https://youtu.be/...
        start: 1:24
        end:   1:28
        mood:  hard-truth
        name:  wolf-pick-up-phone
        # Belfort training scene, boiler room pump-up

    JSON is also accepted (same field names, array of objects).
    """
    text = path.read_text()
    items: list[dict]
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            raise RuntimeError("install PyYAML for YAML manifests: pip install pyyaml")
        items = yaml.safe_load(text) or []
    else:
        items = json.loads(text) or []

    out: list[Path] = []
    for i, it in enumerate(items, 1):
        try:
            print(f"[{i}/{len(items)}] {it.get('mood')}/{it.get('name')}")
            p = fetch_one(
                it["url"],
                _parse_ts(str(it["start"])),
                _parse_ts(str(it["end"])),
                it["mood"],
                it["name"],
            )
            out.append(p)
        except Exception as e:
            print(f"  × {e}")
    return out


def main():
    ap = argparse.ArgumentParser(description="Fetch a Bumblebee clip")
    ap.add_argument("url", nargs="?", help="YouTube (or any yt-dlp-supported) URL")
    ap.add_argument("--start", help="Start timestamp (e.g. 12.4 or 1:24)")
    ap.add_argument("--end", help="End timestamp")
    ap.add_argument("--mood", help=f"One of: {sorted(VALID_MOODS)}")
    ap.add_argument("--name", help="Filename slug (no extension)")
    ap.add_argument("--manifest", help="Path to YAML/JSON list of clips to fetch")
    args = ap.parse_args()

    if args.manifest:
        fetch_manifest(Path(args.manifest))
        return

    if not all([args.url, args.start, args.end, args.mood, args.name]):
        ap.print_help()
        sys.exit(1)
    fetch_one(args.url, _parse_ts(args.start), _parse_ts(args.end),
               args.mood, args.name)


if __name__ == "__main__":
    main()
