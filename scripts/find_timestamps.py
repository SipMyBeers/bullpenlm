#!/usr/bin/env python3
"""Auto-locate exact timestamps for each clip in clips/SOURCING.yaml by
downloading YouTube auto-captions and searching for the target line.

For each entry with `line:` set and start/end == REVIEW, this:
  1. Downloads English auto-captions via yt-dlp (no video data).
  2. Parses the VTT timestamps.
  3. Finds the cue that best matches the target line (case-insensitive,
     normalized whitespace).
  4. Prints the proposed start/end (with a small pre-roll and post-roll
     so the line isn't clipped).
  5. With --apply, writes the new timestamps back into SOURCING.yaml.

Usage:
  python3 scripts/find_timestamps.py                 # dry-run, prints proposals
  python3 scripts/find_timestamps.py --apply         # rewrite YAML in place
"""
from __future__ import annotations
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

try:
    import yaml  # type: ignore
except ImportError:
    print("× install PyYAML: pip install pyyaml"); sys.exit(1)

REPO = Path(__file__).parent.parent
MANIFEST = REPO / "clips" / "SOURCING.yaml"

PRE_ROLL = 0.30   # seconds of context before the matched cue
POST_ROLL = 0.50  # seconds of tail after the cue


def _ts_to_seconds(ts: str) -> float:
    # VTT timestamp: HH:MM:SS.mmm or MM:SS.mmm
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    raise ValueError(f"bad timestamp: {ts!r}")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def fetch_captions(url: str) -> list[tuple[float, float, str]]:
    """Return list of (start_s, end_s, text) from English auto-captions."""
    with tempfile.TemporaryDirectory() as td:
        outpat = str(Path(td) / "cap.%(ext)s")
        cmd = [
            "yt-dlp", "-q",
            "--skip-download",
            "--write-auto-subs",
            "--sub-langs", "en.*",
            "--convert-subs", "vtt",
            "-o", outpat,
            url,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        if r.returncode != 0:
            # Some videos don't have auto-captions; try regular subs as a fallback
            cmd[3] = "--write-subs"
            r = subprocess.run(cmd, capture_output=True, timeout=60)
            if r.returncode != 0:
                return []
        vtts = list(Path(td).glob("*.vtt"))
        if not vtts:
            return []
        return _parse_vtt(vtts[0].read_text())


_CUE_RE = re.compile(
    r"(\d{1,2}:\d{2}(?::\d{2})?\.\d{3})\s+-->\s+(\d{1,2}:\d{2}(?::\d{2})?\.\d{3})"
)


def _parse_vtt(text: str) -> list[tuple[float, float, str]]:
    out: list[tuple[float, float, str]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _CUE_RE.search(lines[i])
        if m:
            start = _ts_to_seconds(m.group(1))
            end = _ts_to_seconds(m.group(2))
            i += 1
            body: list[str] = []
            while i < len(lines) and lines[i].strip():
                body.append(re.sub(r"</?[^>]+>", "", lines[i]))  # strip <c> tags
                i += 1
            out.append((start, end, " ".join(body).strip()))
        i += 1
    return out


def find_line(cues: list[tuple[float, float, str]], needle: str) -> Optional[tuple[float, float, str]]:
    """Best-effort cue match. Searches for the needle string across the
    transcript. Returns the (start_s, end_s, matched_text) of the best
    cue, expanding to neighbors if the needle spans cues."""
    if not cues or not needle:
        return None
    needle_n = _norm(needle)
    # Try exact substring across each cue and across pairs.
    for idx in range(len(cues)):
        if needle_n in _norm(cues[idx][2]):
            return cues[idx]
    for idx in range(len(cues) - 1):
        combined = cues[idx][2] + " " + cues[idx + 1][2]
        if needle_n in _norm(combined):
            return (cues[idx][0], cues[idx + 1][1], combined.strip())
    for idx in range(len(cues) - 2):
        combined = " ".join(c[2] for c in cues[idx:idx + 3])
        if needle_n in _norm(combined):
            return (cues[idx][0], cues[idx + 2][1], combined.strip())
    # Fall back to fuzzy: longest common word-sequence
    needle_words = needle_n.split()
    if len(needle_words) >= 3:
        head = " ".join(needle_words[:3])
        for idx in range(len(cues)):
            if head in _norm(cues[idx][2]):
                # Expand forward a couple cues for safety
                end = cues[min(idx + 2, len(cues) - 1)][1]
                return (cues[idx][0], end, cues[idx][2])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Write proposed timestamps back into SOURCING.yaml")
    args = ap.parse_args()

    text = MANIFEST.read_text()
    items = yaml.safe_load(text) or []

    # Cache fetched captions per URL (multiple entries can share one source video)
    cap_cache: dict[str, list[tuple[float, float, str]]] = {}

    changes: list[tuple[int, float, float]] = []  # (index, start, end)
    for i, it in enumerate(items):
        line = it.get("line")
        if not line:
            continue
        if str(it.get("start", "")).strip().upper() != "REVIEW":
            continue  # already set
        url = it["url"]
        if url not in cap_cache:
            print(f"[{i+1}] ↓ captions for {it.get('name')}  ({url})")
            cap_cache[url] = fetch_captions(url)
        cues = cap_cache[url]
        if not cues:
            print(f"  × no captions available — leave as REVIEW")
            continue
        hit = find_line(cues, line)
        if not hit:
            print(f"  × didn't find: {line!r}")
            continue
        start, end, matched = hit
        start_p = max(0.0, start - PRE_ROLL)
        end_p = end + POST_ROLL
        print(f"  ✓ {it['name']}  →  start={start_p:.2f}  end={end_p:.2f}")
        print(f"     matched: {matched[:120]}")
        changes.append((i, start_p, end_p))

    if not args.apply:
        print(f"\n[dry-run] {len(changes)} entries would be updated.")
        print("Re-run with --apply to write them.")
        return

    # Patch the YAML — preserve comments by doing string-level surgery
    # on the original text. For each changed item, find its YAML block by
    # `name:` and replace the start/end values.
    new_text = text
    for idx, start, end in changes:
        name = items[idx]["name"]
        # Match the block: a `- url:` line followed by `start: REVIEW` … `name: <name>`
        # Replace `start: REVIEW` and `end:   REVIEW` lines *within* the block.
        # We anchor on the `name: <name>` line and search backward for the
        # closest preceding `start:` / `end:`.
        # Simpler: use the YAML emitter; we'll lose comments but the file
        # still works. Save the original as .bak for safety.
        pass

    # Comment-preserving approach: textual replace per name marker.
    new_text = _patch_yaml_inplace(text, items, changes)
    Path(str(MANIFEST) + ".bak").write_text(text)
    MANIFEST.write_text(new_text)
    print(f"\n✓ Wrote {len(changes)} timestamp pairs to {MANIFEST}")
    print(f"  (backup at {MANIFEST}.bak)")


def _patch_yaml_inplace(text: str, items: list[dict],
                          changes: list[tuple[int, float, float]]) -> str:
    """Surgical text-level patch — replaces `start: REVIEW` and `end: REVIEW`
    lines within the block that owns `name: <name>`. Keeps comments intact."""
    lines = text.splitlines(keepends=True)
    # Find the line index of each `name: <name>` entry.
    name_to_line: dict[str, int] = {}
    name_re = re.compile(r"^\s*name:\s*([a-z0-9\-]+)")
    for li, ln in enumerate(lines):
        m = name_re.search(ln)
        if m:
            name_to_line[m.group(1)] = li

    for idx, start, end in changes:
        name = items[idx]["name"]
        ln = name_to_line.get(name)
        if ln is None:
            continue
        # Walk upward to find `start: REVIEW` and `end: REVIEW` in this block.
        for back in range(ln - 1, max(0, ln - 12), -1):
            stripped = lines[back].lstrip()
            if stripped.startswith("- url:"):
                break
            if "start:" in stripped:
                lines[back] = re.sub(r"start:\s*REVIEW",
                                     f"start: {start:.2f}", lines[back])
            elif "end:" in stripped:
                lines[back] = re.sub(r"end:\s*REVIEW",
                                     f"end:   {end:.2f}", lines[back])
    return "".join(lines)


if __name__ == "__main__":
    main()
