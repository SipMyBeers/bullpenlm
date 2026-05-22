#!/usr/bin/env python3
"""
clone_voice.py — Tier 3 voice cloning.

Reads personas/<slug>/voice/sample.wav (a 30+ second sample of the target
person's actual voice from a public talk / podcast) and produces a clone
config at voice/clone_config.json that the training server will use for TTS
instead of the macOS `say` command.

ENGINE: Coqui XTTS v2 — runs 100% locally, no API key, supports 30s-sample
voice cloning with great quality. Installs via:

    pip install "TTS>=0.22.0"
    # First run will download the XTTS-v2 model (~1.8GB) from HuggingFace.

If TTS isn't installed, this script fails politely with copy-paste install
instructions and the trainer falls back to macOS `say`. No silent failures.

ETHICAL NOTE: voice cloning a real person without consent is sketchy.
This tool is for INTERNAL training — your AI roleplay partner sounds like
the real buyer so YOU practice better. Do NOT use cloned voices for any
external-facing output (recordings, marketing, deepfake content).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent

INSTALL_INSTRUCTIONS = """
✗ Coqui TTS isn't installed yet. To enable Tier 3 voice cloning:

  pip install "TTS>=0.22.0"

That will pull ~1.5GB of dependencies (PyTorch, transformers, etc.) and
download the XTTS-v2 model (~1.8GB) on first run.

If you'd rather skip this for now, no problem — the trainer will keep
using the macOS `say` voice configured in persona.json. Tier 2 quote
injection still works great without it.

After install, re-run:
  python3 personas/manage.py clone-voice <slug>
"""


def main(slug: str):
    pdir = ROOT / slug
    if not pdir.exists():
        sys.exit(f"× persona '{slug}' not found at {pdir}")
    sample = pdir / "voice" / "sample.wav"
    if not sample.exists():
        sys.exit(f"× no voice sample at {sample}")

    # Lazy import so the rest of the system doesn't need TTS installed.
    try:
        from TTS.api import TTS  # type: ignore
    except ImportError:
        print(INSTALL_INSTRUCTIONS)
        sys.exit(1)

    print(f"▸ Cloning voice for {slug}")
    print(f"  reference sample: {sample}")
    print(f"  this may take a minute (first run downloads XTTS-v2)…")

    # XTTS-v2: best open-source voice-cloning model that runs locally.
    # gpu=False forces CPU which works on M-series macs; XTTS will run on
    # MPS / CUDA automatically if available in the runtime.
    tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False, gpu=False)

    # Sanity-check the voice with a short synthesis to a verification file.
    verify_out = pdir / "voice" / "verify.wav"
    print(f"  synthesizing verification clip → {verify_out.name}")
    tts.tts_to_file(
        text="Hello. This is a verification clip. If you hear this in the target voice, the clone is working.",
        speaker_wav=str(sample),
        language="en",
        file_path=str(verify_out),
    )

    # Save the clone config. The server reads this and uses XTTS at runtime.
    config = {
        "engine": "xtts_v2",
        "model_name": "tts_models/multilingual/multi-dataset/xtts_v2",
        "speaker_wav": str(sample.resolve()),
        "language": "en",
        "verify_clip": str(verify_out.resolve()),
    }
    out = pdir / "voice" / "clone_config.json"
    out.write_text(json.dumps(config, indent=2) + "\n")

    print(f"✓ Clone config written to {out}")
    print(f"  Listen to {verify_out} to confirm voice quality.")
    print(f"  Restart the training server — persona '{slug}' is now Tier 3.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 clone_voice.py <slug>")
    main(sys.argv[1])
