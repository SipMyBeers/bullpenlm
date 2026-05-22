#!/usr/bin/env python3
"""
personas/manage.py — reproducible persona management CLI.

Usage:
  python3 manage.py list
      Show all personas and their current tier (1/2/3).

  python3 manage.py new <slug>
      Scaffold a new persona at personas/<slug>/ with template files.
      Edit them by hand, then re-run `list` to confirm.

  python3 manage.py ingest-talk <slug> <url-or-file> [--name <label>]
      TIER 2 enrichment. Download the audio (via yt-dlp) or read a local file,
      transcribe with whisper.cpp, save to personas/<slug>/transcripts/<label>.txt.
      Works for YouTube, podcast RSS .mp3 URLs, or any local audio file.

  python3 manage.py clone-voice <slug>
      TIER 3 enrichment. Reads personas/<slug>/voice/sample.wav and produces
      a clone config at personas/<slug>/voice/clone_config.json. Requires the
      OpenVoice TTS package — prints install instructions if missing.

  python3 manage.py show <slug>
      Dump the full assembled system prompt the LLM sees for this persona.
      Useful for verifying tier-2/3 content is making it into the prompt.

External deps (auto-detected, optional):
  yt-dlp           — for ingest-talk URL mode      brew install yt-dlp
  whisper-cli      — for transcription             brew install whisper-cpp
  openvoice-cli    — for voice cloning             pip install MyShell-OpenVoice
                                                   (see clone_voice.py for details)
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
TRAINING = ROOT.parent / "training"
WHISPER_MODEL = TRAINING / "models" / "ggml-base.en.bin"

sys.path.insert(0, str(ROOT))
from loader import load_all, load_persona, build_persona_prompt

# ───────────────────────────── helpers ─────────────────────────────

def fail(msg: str, code: int = 1):
    print(f"× {msg}", file=sys.stderr)
    sys.exit(code)


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


# ───────────────────────────── commands ─────────────────────────────

def cmd_list(_):
    personas = load_all()
    print(f"\n{len(personas)} personas\n")
    print(f"  {'TIER':<6}{'SLUG':<24}{'COMPANY':<28}{'ZONE':<22}{'ENRICHMENT'}")
    print(f"  {'-'*6}{'-'*24}{'-'*28}{'-'*22}{'-'*30}")
    for slug, p in personas.items():
        tier_str = "★" * p.tier + "·" * (3 - p.tier)
        enrich = []
        if p.examples: enrich.append(f"{len(p.examples)}q")
        if p.transcripts: enrich.append(f"{len(p.transcripts)}t")
        if p.cloned_voice_path: enrich.append("voice-cloned")
        print(f"  {tier_str:<6}{slug:<24}{p.company:<28}{p.zone:<22}{', '.join(enrich) or '—'}")
    print()


def cmd_new(args):
    slug = args.slug
    d = ROOT / slug
    if d.exists():
        fail(f"persona '{slug}' already exists at {d}")
    d.mkdir(parents=True)
    (d / "persona.json").write_text(json.dumps({
        "slug": slug,
        "company": "TODO Company Name",
        "role": "TODO Role Title",
        "hq": "TODO City, ST",
        "size": "TODO size",
        "zone": "End Customer",  # or Channel Partner / Tool Partner / Boutique Partner
        "what": "TODO 1-sentence company description",
        "say_voice": "Samantha",  # one of: Daniel Karen Samantha Fred Ralph
        "say_rate": 175,
    }, indent=2) + "\n")
    (d / "personality.md").write_text("TODO 2-3 sentences on this person's internal state. Skeptical? Warm? Procurement-armored?\n")
    (d / "speech_profile.md").write_text("TODO linguistic fingerprint — region/dialect, sentence length, characteristic phrases, words they'd NEVER use.\n")
    (d / "pushbacks.txt").write_text(
        "TODO objection 1 — verbatim, in their voice\n"
        "TODO objection 2\n"
        "TODO objection 3\n"
    )
    (d / "examples.md").write_text(
        f"# Verbatim quotes for {slug}\n\n"
        "## (source: example)\n"
        "> Paste a real quote here. Keep them short and characteristic.\n"
    )
    (d / "transcripts").mkdir()
    (d / "transcripts" / "README.txt").write_text(
        "Drop transcripts of this person's public talks here as .txt files.\n"
    )
    (d / "voice").mkdir()
    (d / "voice" / "README.txt").write_text(
        f"Drop a 30+ second audio sample as sample.wav, then run:\n  python3 manage.py clone-voice {slug}\n"
    )
    print(f"✓ Scaffolded {d}")
    print(f"  Now edit persona.json, personality.md, speech_profile.md, pushbacks.txt.")
    print(f"  Optional enrichment:")
    print(f"    python3 manage.py ingest-talk {slug} <youtube-url>")
    print(f"    python3 manage.py clone-voice {slug}")


def cmd_ingest_talk(args):
    """Download or read audio → transcribe → save to transcripts/<label>.txt."""
    slug = args.slug
    pdir = ROOT / slug
    if not pdir.exists():
        fail(f"persona '{slug}' not found — run `manage.py new {slug}` first")
    if not WHISPER_MODEL.exists():
        fail(f"whisper model missing at {WHISPER_MODEL} — re-run training setup")

    source = args.source
    label = args.name or _label_from_source(source)
    out_path = pdir / "transcripts" / f"{label}.txt"
    if out_path.exists() and not args.force:
        fail(f"{out_path} already exists — pass --force to overwrite")

    print(f"▸ Ingesting talk for {slug}")
    print(f"  source: {source}")
    print(f"  saving to: {out_path}")

    # Resolve source to a local audio file
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        if source.startswith(("http://", "https://")):
            if not have("yt-dlp"):
                fail(
                    "yt-dlp not installed — install with:\n"
                    "  brew install yt-dlp\n"
                    "Then re-run this command. Or convert the audio yourself to .wav and pass the local file path."
                )
            print("  ▸ downloading + extracting audio via yt-dlp…")
            wav_path = tmp_path / "audio.wav"
            r = subprocess.run([
                "yt-dlp",
                "-x", "--audio-format", "wav",
                "--postprocessor-args", "-ar 16000 -ac 1",
                "-o", str(tmp_path / "audio.%(ext)s"),
                "--quiet",
                source,
            ])
            if r.returncode != 0:
                fail(f"yt-dlp failed (exit {r.returncode})")
            if not wav_path.exists():
                # yt-dlp sometimes leaves a differently-named .wav
                wavs = list(tmp_path.glob("*.wav"))
                if not wavs:
                    fail("yt-dlp completed but produced no .wav output")
                wav_path = wavs[0]
        else:
            src_file = Path(source).expanduser().resolve()
            if not src_file.exists():
                fail(f"local file not found: {src_file}")
            wav_path = tmp_path / "audio.wav"
            # Convert to whisper-friendly format if needed
            if src_file.suffix.lower() == ".wav":
                shutil.copy(src_file, wav_path)
            else:
                if not have("afconvert"):
                    fail("non-WAV input requires macOS `afconvert` (built-in)")
                print("  ▸ converting to 16kHz mono WAV…")
                r = subprocess.run([
                    "afconvert", str(src_file), "-f", "WAVE",
                    "-d", "LEI16@16000", "-c", "1", str(wav_path),
                ])
                if r.returncode != 0:
                    fail(f"afconvert failed (exit {r.returncode})")

        print(f"  ▸ transcribing with whisper.cpp (this can take a minute)…")
        out_base = str(wav_path)[:-4]  # strip .wav for -of
        r = subprocess.run([
            "whisper-cli", "-m", str(WHISPER_MODEL),
            str(wav_path), "-nt", "-otxt", "-of", out_base,
            "-l", "en", "-t", "4",
        ], capture_output=True)
        if r.returncode != 0:
            fail(f"whisper-cli failed: {r.stderr.decode(errors='ignore')[:400]}")
        txt = Path(out_base + ".txt").read_text().strip()
        if not txt:
            fail("whisper produced empty output")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(txt + "\n")

    word_count = len(txt.split())
    print(f"✓ Saved {word_count:,} words to {out_path}")
    print(f"  Persona '{slug}' is now Tier 2 — re-launch the trainer to pick up the change.")


def cmd_clone_voice(args):
    """Tier-3 voice clone. Delegates to clone_voice.py for the heavy lifting."""
    slug = args.slug
    pdir = ROOT / slug
    if not pdir.exists():
        fail(f"persona '{slug}' not found")
    sample = pdir / "voice" / "sample.wav"
    if not sample.exists():
        fail(
            f"no voice sample at {sample}\n"
            f"  Drop a 30+ second .wav of the person speaking at:\n"
            f"  {sample}\n"
            f"  Then re-run this command."
        )
    # Delegate to clone_voice.py — keeps the heavy TTS deps off the main path.
    script = ROOT / "clone_voice.py"
    if not script.exists():
        fail(f"clone_voice.py missing at {script}")
    r = subprocess.run([sys.executable, str(script), slug])
    sys.exit(r.returncode)


def cmd_show(args):
    """Dump the system prompt that the LLM sees for this persona."""
    slug = args.slug
    try:
        p = load_persona(slug)
    except FileNotFoundError:
        fail(f"persona '{slug}' not found")
    print(f"# Persona: {p.company} — Tier {p.tier}\n")
    print(build_persona_prompt(p))


# ───────────────────────────── utils ─────────────────────────────

def _label_from_source(source: str) -> str:
    """Build a filename-safe label from a URL or path."""
    import re, datetime
    base = Path(source).stem if "://" not in source else source.rstrip("/").split("/")[-1]
    base = re.sub(r"[^a-zA-Z0-9-]+", "-", base).strip("-")[:48].lower() or "talk"
    return f"{datetime.date.today().isoformat()}-{base}"


# ───────────────────────────── main ─────────────────────────────

def main():
    ap = argparse.ArgumentParser(prog="manage.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show all personas and their tier")

    p_new = sub.add_parser("new", help="scaffold a new persona directory")
    p_new.add_argument("slug")

    p_ing = sub.add_parser("ingest-talk", help="Tier 2: transcribe a public talk via yt-dlp + whisper")
    p_ing.add_argument("slug")
    p_ing.add_argument("source", help="URL (youtube/podcast) or local audio file path")
    p_ing.add_argument("--name", help="filename label (default: date + slugified source)")
    p_ing.add_argument("--force", action="store_true")

    p_voice = sub.add_parser("clone-voice", help="Tier 3: clone a voice from voice/sample.wav")
    p_voice.add_argument("slug")

    p_show = sub.add_parser("show", help="print the assembled system prompt for a persona")
    p_show.add_argument("slug")

    args = ap.parse_args()
    {
        "list": cmd_list,
        "new": cmd_new,
        "ingest-talk": cmd_ingest_talk,
        "clone-voice": cmd_clone_voice,
        "show": cmd_show,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
