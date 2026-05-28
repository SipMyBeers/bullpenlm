"""Voice mode helpers — TTS the AI buyer with a persona-mapped voice.

Closer's voice → existing whisper.cpp transcribe (server.transcribe_wav).
Buyer's reply → this module: pick a persona-appropriate macOS `say`
voice, render to AIFF, return URL.

We keep the loop server-side rather than browser Web Speech API
because:
  - Quality is consistent across operator machines (operator runs Mac)
  - Voice selection is deterministic per buyer (not user-locale-bound)
  - Browser SpeechRecognition is unreliable on iOS / Firefox / Chrome
    inconsistencies

Per-call audio is written to:
    bullpens/<slug>/voice/<buyer>/<turn_id>.aiff

Older turns aren't purged automatically — operator runs the existing
audit / housekeeping flow. ~50KB per ~5-second reply, ~10MB per
~1000-turn drill session. Fine for friends-cohort scale.
"""
from __future__ import annotations
import datetime
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional


REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"


# ── Voice mapping ────────────────────────────────────────────────────────
#
# Per-buyer-slug overrides come first. Then we fall back to gender hints
# in the buyer's persona, then a US-professional default.

VOICE_BY_BUYER_SLUG = {
    "accenture-mainframe": "Tom",        # midwest male, professional
    "allstate":            "Paulina",    # slight latin-American accent (matches Sofia Mendez persona)
    "cigna":               "Samantha",   # neutral US female
    "_drill_bank":         "Alex",       # default for synthetic drill content
}

MALE_DEFAULT   = "Tom"      # US, deep, midwest-exec read
FEMALE_DEFAULT = "Samantha"  # US, polished

# Persona-name → gender heuristic. Names are matched case-insensitively
# against the buyer card's persona.name field. Anything unrecognized
# falls through to MALE_DEFAULT (most B2B buyers Beers's friends will
# practice against are male MDs — the most likely match).
MALE_NAMES = {
    "marcus", "michael", "mike", "matt", "matthew", "john", "james", "david",
    "daniel", "dan", "robert", "rob", "william", "will", "richard", "thomas",
    "tom", "charles", "chris", "christopher", "joseph", "joe", "ravi", "raj",
    "ahmed", "carlos", "jose", "miguel", "antonio", "alejandro", "jordan",
    "ryan", "scott", "kevin", "brian", "steven", "steve", "edward", "ed",
    "ben", "benjamin", "jeff", "jeffrey", "greg", "gregory",
}
FEMALE_NAMES = {
    "sarah", "sara", "jennifer", "jen", "lisa", "linda", "mary", "patricia",
    "barbara", "elizabeth", "susan", "jessica", "amanda", "ashley", "stephanie",
    "samantha", "rachel", "lauren", "olivia", "emma", "ava", "sofia", "sophia",
    "isabella", "mia", "kelly", "anna", "emily", "danielle", "caroline",
    "rebecca", "becky", "margaret", "deborah", "ellen", "kim", "kimberly",
}


def voice_for(buyer_slug: str, persona_name: Optional[str] = None) -> str:
    """Pick the macOS `say` voice for this buyer. Operators can override
    by setting `voice` on the buyer card JSON (read elsewhere; this
    module is the fallback policy)."""
    if buyer_slug in VOICE_BY_BUYER_SLUG:
        return VOICE_BY_BUYER_SLUG[buyer_slug]
    if persona_name:
        first = re.split(r"[\s\-]+", persona_name.strip())[0].lower()
        if first in MALE_NAMES:
            return MALE_DEFAULT
        if first in FEMALE_NAMES:
            return FEMALE_DEFAULT
    return MALE_DEFAULT


# ── TTS ──────────────────────────────────────────────────────────────────

def _voice_dir(bullpen: str, buyer: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "voice" / buyer
    d.mkdir(parents=True, exist_ok=True)
    return d


def _strip_for_tts(text: str) -> str:
    """Strip markdown / stage directions so TTS sounds natural."""
    if not text:
        return ""
    # Drop bracketed stage directions like [picks up phone] — common in
    # AI buyer roleplay output.
    text = re.sub(r"\[[^\]]*\]", " ", text)
    # Markdown bold/italic/code
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Convert ... → comma (helps say's prosody)
    text = re.sub(r"\.{3,}", ",", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tts_reply(
    bullpen: str, buyer: str, text: str,
    *, voice: Optional[str] = None,
    persona_name: Optional[str] = None,
    turn_id: Optional[str] = None,
    rate: int = 200,
) -> Optional[dict]:
    """Synthesize an AI-buyer reply. Returns {url, voice, path,
    duration_estimate_sec} or None if `say` is unavailable."""
    say_bin = shutil.which("say")
    if not say_bin:
        return None
    plain = _strip_for_tts(text)
    if len(plain) < 2:
        return None
    voice = voice or voice_for(buyer, persona_name)
    turn_id = turn_id or datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out_path = _voice_dir(bullpen, buyer) / f"{turn_id}.aiff"
    try:
        subprocess.run(
            [say_bin, "-v", voice, "-r", str(rate), "-o", str(out_path), plain],
            check=True, capture_output=True, timeout=60,
        )
    except subprocess.SubprocessError:
        # Voice not available on this machine? Fall back to Alex and retry.
        try:
            subprocess.run(
                [say_bin, "-v", "Alex", "-r", str(rate), "-o", str(out_path), plain],
                check=True, capture_output=True, timeout=60,
            )
            voice = "Alex"
        except subprocess.SubprocessError:
            return None
    if not out_path.exists() or out_path.stat().st_size < 1000:
        return None
    words = len(plain.split())
    return {
        "url": f"/api/b/{bullpen}/voice/{buyer}/{turn_id}.aiff",
        "voice": voice,
        "turn_id": turn_id,
        "duration_estimate_sec": max(1, int(words / 180 * 60)),
        "size_bytes": out_path.stat().st_size,
    }


def list_available_voices() -> list[dict]:
    """Voices the operator can pick from. Calls `say -v ?` once."""
    say_bin = shutil.which("say")
    if not say_bin:
        return []
    try:
        out = subprocess.check_output([say_bin, "-v", "?"], text=True, timeout=10)
    except Exception:
        return []
    voices = []
    for line in out.splitlines():
        m = re.match(r"^([\w\-' ]+?)\s{2,}([a-z]{2}_[A-Z]{2})\s+#\s+(.+)$", line)
        if not m:
            continue
        name, locale, sample = m.groups()
        if not locale.startswith(("en_", "es_")):
            continue  # operator's cohort is anglophone for now
        voices.append({"name": name.strip(), "locale": locale, "sample": sample.strip()[:60]})
    return voices
