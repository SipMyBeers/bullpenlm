#!/usr/bin/env python3
"""Bundle BullpenLM into a zip you can send your friend via Discord, AirDrop,
or anything else. Excludes your personal coaching history and whisper models
(too big for Discord free tier). Includes a SETUP.md that walks them through
first-run setup in ~5 minutes.

Usage:
  python3 scripts/package_for_friend.py
  python3 scripts/package_for_friend.py --include-models   # heavier but no setup
"""
from __future__ import annotations
import argparse
import datetime
import os
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).parent.parent

# Always exclude these — personal data, caches, OS files, and oversized binaries
EXCLUDE_DIRS = {
    "training-runs",                # your coaching history is yours
    "__pycache__",
    ".git",
    ".pytest_cache",
    "node_modules",
    "landing",                      # marketing site — friend doesn't need it
}
EXCLUDE_PATTERNS = [
    ".DS_Store",
    ".pyc",
    ".log",
    ".env",
    ".env.local",
]

SETUP_MD = """\
# BullpenLM — first-run setup

Your buddy sent you a sales-training tool. Here's how to get it running in 5 minutes.

## Prereqs (one-time)

1. **Python 3.11+** — `python3 --version` should say 3.11 or higher
2. **Ollama** — local LLM runner: https://ollama.com/download
3. **Homebrew** (Mac) — for whisper.cpp: https://brew.sh

## Install dependencies

```bash
# Pull the local LLM model (~5 GB, one-time)
ollama pull gemma2:9b

# Install whisper.cpp (local speech-to-text)
brew install whisper-cpp

# Install Python deps
pip3 install pypdf certifi

# Download the whisper model (~141 MB)
mkdir -p server/models
curl -L -o server/models/ggml-base.en.bin \\
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
```

## Run it

```bash
# Start the trainer server (keep this terminal open)
python3 server/server.py
```

Then open `floor/index.html` in Chrome or Safari. You'll see the sales floor.

## What you have

- **57 COBOL-modernization prospects** loaded — these are real companies your friend's
  selling to (Allstate, BoA, Cigna, etc.). Each has a roleplay persona built in.
- **8 library personas** for skill practice — Skeptical CTO, Hostile Buyer,
  Time-Poor CEO, Mentor Coach, and 4 more.
- **Live recording** — click 🔴 Record on any prospect card, talk for 5 minutes,
  and the system auto-transcribes + scores you on talk ratio, filler words, etc.
- **Speaking drill** (🎤 FAB) — solo speech practice with rotating prompts.
- **Practice Lab** (⌁ FAB) — pick a persona by tier (Beginner → Advanced).
- **Trend view** (📈 FAB) — your fillers + talk ratio over time.

## First call to make

Once it's running, click **⌁ Practice** → **Skeptical CTO** → take the call. That's
your training environment for KillSesh outreach. The mentor-coach persona can
help you debrief afterward.

## Set your name

In the top-right of the floor, set the **REP** field to your name. All your
metrics save under that name so you and your friend's stats stay separate.

## Questions

Ping your friend. He built this.
"""


def should_include(path: Path) -> bool:
    parts = path.parts
    if any(d in parts for d in EXCLUDE_DIRS):
        return False
    name = path.name
    if any(name.endswith(p) for p in EXCLUDE_PATTERNS):
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--include-models", action="store_true",
                    help="Include whisper models in the zip (adds ~600MB, requires Discord Nitro to send)")
    ap.add_argument("--out", default=None, help="Output zip path")
    args = ap.parse_args()

    today = datetime.date.today().isoformat()
    out = Path(args.out) if args.out else REPO.parent / f"bullpenlm-share-{today}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)

    excluded_extra = set() if args.include_models else {".bin"}

    print(f"Packaging {REPO.name} → {out}")
    print(f"  excluding: {sorted(EXCLUDE_DIRS)}{' + .bin models' if not args.include_models else ''}")

    files_added = 0
    bytes_total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        # Add a top-level SETUP.md
        z.writestr(f"{REPO.name}/SETUP.md", SETUP_MD)

        for root, dirs, files in os.walk(REPO):
            # Filter directories in-place so os.walk skips them
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
            for fname in files:
                src = Path(root) / fname
                if not should_include(src):
                    continue
                if src.suffix in excluded_extra:
                    continue
                rel = src.relative_to(REPO.parent)
                z.write(src, arcname=str(rel))
                files_added += 1
                bytes_total += src.stat().st_size

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"\n✓ Created {out.name}")
    print(f"  {files_added} files, {size_mb:.1f} MB")
    if size_mb > 25:
        print(f"  ⚠ Over Discord free-tier 25MB limit. Options:")
        print(f"     · Discord Nitro (500MB) · Dropbox · Google Drive · AirDrop · USB")
    else:
        print(f"  ✓ Under Discord 25MB free limit — drag it into any DM")


if __name__ == "__main__":
    main()
