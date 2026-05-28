"""Artifact generators — turn a buyer's RAG corpus into NotebookLM-style
game assets.

Six asset kinds. Each one:
  1. Pulls relevant chunks from rag.search() with a kind-specific query
  2. Builds a structured Gemma prompt that asks for valid JSON
  3. Validates the JSON and writes it to disk under artifacts/
  4. Returns the parsed object

Cache lives at bullpens/<slug>/artifacts/<buyer>/<kind>.json. Regenerate
fires when the source corpus changes (a new ingest bumps the buyer's
collection.count() — we store the count we generated against and
compare on next read).

Asset kinds:
  flashcards   — list[{q, a, difficulty}]
  quiz         — list[{q, choices[4], correct_index, explanation}]
  briefing     — markdown one-pager (~300 words)
  one_sheeter  — markdown cheat sheet with fixed sections
  account_map  — {nodes: [{id, label, kind}], edges: [{from, to, label}]}
  data_table   — {contacts: [...], tech_stack: [...], news: [...], financials: [...]}

All generators credit clout-XP for the closer who views/passes them
(except quiz/flashcards at cert-tier scoring which can credit money-XP
via the existing xp.py rules). Generation itself is operator-side; we
don't credit XP for asking the platform to generate something.

Failure modes:
  - Ollama down → raise GeneratorUnavailable
  - Empty corpus → return {empty: true, message: ...} (don't fail)
  - Bad JSON from Gemma → retry once with a tighter prompt, then
    return {partial: true, raw: ...} so the UI can show what came back
"""
from __future__ import annotations
import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Optional

import rag


from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


class GeneratorUnavailable(RuntimeError):
    pass


# ── Cache layout ──────────────────────────────────────────────────────────

def _artifacts_dir(bullpen: str, buyer: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "artifacts" / buyer
    d.mkdir(parents=True, exist_ok=True)
    return d


def _artifact_path(bullpen: str, buyer: str, kind: str) -> Path:
    return _artifacts_dir(bullpen, buyer) / f"{kind}.json"


def _corpus_signature(bullpen: str, buyer: str) -> str:
    """A signature of the current corpus state so we know when to
    regenerate. Combines chunk count + latest source ingested_at."""
    try:
        srcs = rag.sources(bullpen, buyer)
        if not srcs:
            return "empty"
        chunks = sum(s["chunks"] for s in srcs)
        latest = max((s.get("ingested_at") or "") for s in srcs)
        return f"{chunks}__{latest}"
    except Exception:
        return "unknown"


def _read_cached(bullpen: str, buyer: str, kind: str) -> Optional[dict]:
    p = _artifact_path(bullpen, buyer, kind)
    if not p.exists():
        return None
    try:
        cached = json.loads(p.read_text())
    except Exception:
        return None
    if cached.get("__corpus_signature") != _corpus_signature(bullpen, buyer):
        # Corpus has changed since last generation — caller should regenerate
        return None
    return cached


def _write_cached(bullpen: str, buyer: str, kind: str, data: dict) -> dict:
    payload = {
        **data,
        "__corpus_signature": _corpus_signature(bullpen, buyer),
        "__generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "__buyer": buyer,
        "__kind": kind,
    }
    _artifact_path(bullpen, buyer, kind).write_text(json.dumps(payload, indent=2))
    return payload


# ── LLM call (re-using existing ollama_chat from server.py) ──────────────

def _llm_json(prompt_system: str, prompt_user: str, *, temperature: float = 0.4) -> dict:
    """Call Gemma, expect JSON back. Retries once with a tighter framing.

    Returns dict-or-list parsed from the model output.
    """
    try:
        from server import ollama_chat  # type: ignore
    except Exception as e:
        raise GeneratorUnavailable(f"ollama_chat not importable: {e}")

    def _call(sys_p: str, user_p: str) -> str:
        return ollama_chat(
            [{"role": "system", "content": sys_p},
             {"role": "user",   "content": user_p}],
            temperature=temperature,
        )

    raw = _call(prompt_system, prompt_user)
    parsed = _strip_and_parse_json(raw)
    if parsed is not None:
        return parsed

    # Retry once with explicit "JSON ONLY" framing
    raw2 = _call(
        prompt_system + "\n\nIMPORTANT: respond with valid JSON ONLY. No markdown, no commentary, no code fences.",
        prompt_user,
    )
    parsed2 = _strip_and_parse_json(raw2)
    if parsed2 is not None:
        return parsed2

    return {"__partial": True, "__raw": raw, "__retry_raw": raw2}


def _strip_and_parse_json(s: str):
    """Find the first JSON object/array in s and parse it. Returns None
    if no parseable JSON could be extracted."""
    if not s:
        return None
    # Strip markdown fences
    s = re.sub(r"^```(?:json)?\s*", "", s.strip(), flags=re.M)
    s = re.sub(r"```\s*$", "", s.strip())
    # Find the first { or [ and parse from there
    for opener in ("[", "{"):
        idx = s.find(opener)
        if idx < 0:
            continue
        # Match balanced
        depth = 0
        for j in range(idx, len(s)):
            if s[j] == opener: depth += 1
            elif s[j] == ("]" if opener == "[" else "}"): depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[idx:j+1])
                except Exception:
                    break
    try:
        return json.loads(s)
    except Exception:
        return None


# ── Shared corpus-context builder ─────────────────────────────────────────

def _full_context(bullpen: str, buyer: str, query: str, *, max_chars: int = 6000) -> str:
    """A richer context block for generators (3x normal context budget
    since we want maximum coverage of the corpus)."""
    return rag.context(bullpen, buyer, query, max_chars=max_chars)


def _buyer_card_summary(bullpen: str, buyer: str) -> str:
    """Fall back to the buyer card JSON if RAG is empty."""
    p = BULLPENS_ROOT / bullpen / "buyer_cards" / f"{buyer}.json"
    if not p.exists():
        return ""
    try:
        card = json.loads(p.read_text())
    except Exception:
        return ""
    out = [
        f"# {card.get('company', buyer)}",
        f"Role: {card.get('role', '')}",
        f"Vertical: {card.get('vertical', '')}",
        f"HQ: {card.get('hq', '')}",
    ]
    persona = card.get("persona", {})
    if persona:
        out.append(f"\nPersona: {persona.get('name', '')} — {persona.get('tone', '')}")
        out.append(f"Decision style: {persona.get('decision_style', '')}")
    for sect in ("their_world", "their_motivations", "their_objections"):
        items = card.get(sect, [])
        if items:
            out.append(f"\n{sect.replace('_', ' ').title()}:")
            for it in items:
                out.append(f"  - {it}")
    return "\n".join(out)


# ── 1. FLASHCARDS ─────────────────────────────────────────────────────────

FLASHCARDS_SYSTEM = (
    "You are a sales-training coach. Generate study flashcards for a closer "
    "about to call a real prospect. The flashcards drill specific, actionable "
    "knowledge — not vague generalities."
)

def gen_flashcards(bullpen: str, buyer: str, n: int = 10) -> dict:
    cached = _read_cached(bullpen, buyer, "flashcards")
    if cached: return cached

    ctx = _full_context(bullpen, buyer,
        "objections motivations decision style stakeholders hot buttons red flags",
        max_chars=5000)
    if not ctx:
        ctx = _buyer_card_summary(bullpen, buyer)
    if not ctx:
        return _write_cached(bullpen, buyer, "flashcards", {"empty": True, "cards": []})

    user_prompt = (
        f"From this buyer's dossier, generate {n} flashcards a closer would drill before a real call. "
        "Cover: top objections + the best counter, key motivations, the persona's decision style, "
        "stakeholders to map, red flags to avoid, hot buttons that move them.\n\n"
        f"{ctx}\n\n"
        'Return ONLY a JSON array: [{"q": "...", "a": "...", "difficulty": "easy|med|hard", "topic": "objection|motivation|stakeholder|red_flag|hot_button"}, ...]. '
        "Question should be the front of the card (specific scenario). Answer is the closer's best move/response/recall."
    )
    result = _llm_json(FLASHCARDS_SYSTEM, user_prompt)
    cards = result if isinstance(result, list) else result.get("cards") or []
    out = {"cards": cards, "count": len(cards)}
    if isinstance(result, dict) and result.get("__partial"):
        out["partial"] = True
    return _write_cached(bullpen, buyer, "flashcards", out)


# ── 2. QUIZ (Pop Quiz) ────────────────────────────────────────────────────

QUIZ_SYSTEM = (
    "You are writing a pop quiz for a closer to prove they studied the buyer's dossier. "
    "Questions test SPECIFIC knowledge from the dossier, not generic sales theory."
)

def gen_quiz(bullpen: str, buyer: str, n: int = 5) -> dict:
    cached = _read_cached(bullpen, buyer, "quiz")
    if cached: return cached

    ctx = _full_context(bullpen, buyer,
        "company facts persona role decision style objections regulatory pressure",
        max_chars=5000)
    if not ctx:
        ctx = _buyer_card_summary(bullpen, buyer)
    if not ctx:
        return _write_cached(bullpen, buyer, "quiz", {"empty": True, "questions": []})

    user_prompt = (
        f"From this dossier, write {n} multiple-choice questions to test a closer's "
        "knowledge of THIS specific buyer. Each question has 4 plausible choices and "
        "ONE correct answer. The wrong answers should be tempting but provably wrong "
        "given the dossier. Include a short explanation that cites the dossier.\n\n"
        f"{ctx}\n\n"
        'Return ONLY a JSON array: '
        '[{"q": "...", "choices": ["a","b","c","d"], "correct_index": 0, "explanation": "..."}, ...]'
    )
    result = _llm_json(QUIZ_SYSTEM, user_prompt)
    qs = result if isinstance(result, list) else result.get("questions") or []
    out = {"questions": qs, "count": len(qs)}
    if isinstance(result, dict) and result.get("__partial"):
        out["partial"] = True
    return _write_cached(bullpen, buyer, "quiz", out)


# ── 3. BRIEFING (300-word pre-call doc) ──────────────────────────────────

BRIEFING_SYSTEM = (
    "You are writing a 300-word pre-call briefing for a closer. Style: dense, "
    "specific, second-person ('you'). No filler. Cite the dossier where possible."
)

def gen_briefing(bullpen: str, buyer: str) -> dict:
    cached = _read_cached(bullpen, buyer, "briefing")
    if cached: return cached

    ctx = _full_context(bullpen, buyer,
        "company persona role pain motivation objection opener strategy",
        max_chars=5000)
    if not ctx:
        ctx = _buyer_card_summary(bullpen, buyer)
    if not ctx:
        return _write_cached(bullpen, buyer, "briefing", {"empty": True, "markdown": ""})

    user_prompt = (
        "Write a 300-word pre-call briefing in markdown. Sections (use ## headers):\n"
        "1. Who they are (1-2 sentences)\n"
        "2. What they care about (3 bullets, most → least pressing)\n"
        "3. What to avoid (1-2 bullets — red flags or hot-button language)\n"
        "4. Where to start (your opener, 1-2 sentences specific to this buyer)\n\n"
        "Dossier:\n"
        f"{ctx}\n\n"
        "Output: markdown ONLY, no JSON, no preamble. ~300 words total."
    )

    try:
        from server import ollama_chat  # type: ignore
        md = ollama_chat(
            [{"role": "system", "content": BRIEFING_SYSTEM},
             {"role": "user", "content": user_prompt}],
            temperature=0.5,
        )
    except Exception as e:
        raise GeneratorUnavailable(f"ollama_chat failed: {e}")

    md = re.sub(r"^```(?:markdown)?\s*", "", md.strip(), flags=re.M)
    md = re.sub(r"```\s*$", "", md.strip())
    out = {"markdown": md, "word_count": len(md.split())}
    return _write_cached(bullpen, buyer, "briefing", out)


# ── 4. ONE-SHEETER (cheat sheet with fixed sections) ─────────────────────

ONE_SHEETER_SYSTEM = (
    "You are writing a one-page cheat sheet a closer pins next to their phone "
    "during the call. Style: punchy, scannable, no fluff."
)

def gen_one_sheeter(bullpen: str, buyer: str) -> dict:
    cached = _read_cached(bullpen, buyer, "one_sheeter")
    if cached: return cached

    ctx = _full_context(bullpen, buyer,
        "stakeholders objections hot-button pricing competitors timeline",
        max_chars=5000)
    if not ctx:
        ctx = _buyer_card_summary(bullpen, buyer)
    if not ctx:
        return _write_cached(bullpen, buyer, "one_sheeter", {"empty": True, "markdown": ""})

    user_prompt = (
        "Write a one-page cheat sheet in markdown. Sections:\n"
        "## 🎯 The Open\n_(your literal first 8 seconds — exact words)_\n\n"
        "## 🧠 Their World\n_(3 bullets: company facts that matter)_\n\n"
        "## 💰 Hot Buttons\n_(3 bullets: what gets them leaning forward)_\n\n"
        "## ⚠️ Red Flags\n_(2 bullets: phrases to avoid)_\n\n"
        "## 🛡️ Top 3 Objections + Counters\n_(numbered: objection → your move)_\n\n"
        "## ✅ Asks\n_(your 3 escalating asks: 15-min next call → exec briefing → pilot)_\n\n"
        "Dossier:\n"
        f"{ctx}\n\n"
        "Markdown only. Short. Pin-to-the-wall energy. No closing sign-off."
    )

    try:
        from server import ollama_chat  # type: ignore
        md = ollama_chat(
            [{"role": "system", "content": ONE_SHEETER_SYSTEM},
             {"role": "user", "content": user_prompt}],
            temperature=0.5,
        )
    except Exception as e:
        raise GeneratorUnavailable(str(e))

    md = re.sub(r"^```(?:markdown)?\s*", "", md.strip(), flags=re.M)
    md = re.sub(r"```\s*$", "", md.strip())
    out = {"markdown": md}
    return _write_cached(bullpen, buyer, "one_sheeter", out)


# ── 5. ACCOUNT MAP (mind map — nodes + edges) ────────────────────────────

ACCOUNT_MAP_SYSTEM = (
    "You are extracting an account map for a sales closer — like an org chart "
    "fused with a deal map. Entities: people, departments, projects, products, "
    "competitors, regulations. Relationships: reports-to, owns, blocks, allies-with."
)

def gen_account_map(bullpen: str, buyer: str) -> dict:
    cached = _read_cached(bullpen, buyer, "account_map")
    if cached: return cached

    ctx = _full_context(bullpen, buyer,
        "stakeholders org chart decision makers blockers allies competitors",
        max_chars=5000)
    if not ctx:
        ctx = _buyer_card_summary(bullpen, buyer)
    if not ctx:
        return _write_cached(bullpen, buyer, "account_map", {"empty": True, "nodes": [], "edges": []})

    user_prompt = (
        "Extract an account map from this dossier. Identify entities (people, "
        "departments, projects, products, competitors, key regulations) and "
        "the relationships between them.\n\n"
        f"{ctx}\n\n"
        'Return ONLY JSON: {\n'
        '  "nodes": [{"id": "marcus", "label": "Marcus Chen", "kind": "person", "role": "MD Mainframe Modernization"}, ...],\n'
        '  "edges": [{"from": "marcus", "to": "accenture", "label": "leads"}, ...]\n'
        '}\n'
        'kind ∈ {"person","department","project","product","competitor","regulation","metric"}. '
        "Maximum 12 nodes, 16 edges."
    )
    result = _llm_json(ACCOUNT_MAP_SYSTEM, user_prompt)
    out = {
        "nodes": (result.get("nodes") if isinstance(result, dict) else []) or [],
        "edges": (result.get("edges") if isinstance(result, dict) else []) or [],
    }
    if isinstance(result, dict) and result.get("__partial"):
        out["partial"] = True
    return _write_cached(bullpen, buyer, "account_map", out)


# ── 6. DATA TABLE (structured fields) ────────────────────────────────────

DATA_TABLE_SYSTEM = (
    "You are extracting structured data from a sales-buyer dossier so it can "
    "flow into a CRM as columns + rows."
)

def gen_data_table(bullpen: str, buyer: str) -> dict:
    cached = _read_cached(bullpen, buyer, "data_table")
    if cached: return cached

    ctx = _full_context(bullpen, buyer,
        "contacts emails titles tech stack financial figures recent news partnerships",
        max_chars=5000)
    if not ctx:
        ctx = _buyer_card_summary(bullpen, buyer)
    if not ctx:
        return _write_cached(bullpen, buyer, "data_table", {"empty": True, "tables": {}})

    user_prompt = (
        "Extract structured CRM-ready data from this dossier. Return JSON with "
        "FOUR tables:\n\n"
        "  contacts: [{name, title, role, email_guess, why_they_matter}]\n"
        "  tech_stack: [{name, category, notes}]\n"
        "  recent_news: [{headline, date, source, why_relevant}]\n"
        "  financials: [{metric, value, period, source}]\n\n"
        "Where the dossier doesn't say, OMIT the row — don't make it up. "
        "email_guess can be best-guess based on common patterns; mark with '?'.\n\n"
        f"{ctx}\n\n"
        'Return ONLY JSON: {"contacts":[...], "tech_stack":[...], "recent_news":[...], "financials":[...]}'
    )
    result = _llm_json(DATA_TABLE_SYSTEM, user_prompt)
    if not isinstance(result, dict):
        result = {}
    out = {
        "contacts": result.get("contacts") or [],
        "tech_stack": result.get("tech_stack") or [],
        "recent_news": result.get("recent_news") or [],
        "financials": result.get("financials") or [],
    }
    if result.get("__partial"):
        out["partial"] = True
    return _write_cached(bullpen, buyer, "data_table", out)


# ── Top-level dispatcher + manifest ──────────────────────────────────────

# ── 7. BRIEFING AUDIO (TTS via macOS `say`) ───────────────────────────────

def gen_briefing_audio(bullpen: str, buyer: str) -> dict:
    """Generate a spoken-audio version of the briefing — closer can
    listen on the way to the call instead of reading. Uses macOS `say`
    (always present on Mac); future builds can wire piper for
    cross-platform support.
    """
    import shutil
    import subprocess

    cached = _read_cached(bullpen, buyer, "briefing_audio")
    if cached and (_artifacts_dir(bullpen, buyer) / "briefing.aiff").exists():
        return cached

    # Need the markdown briefing first — generate it if not cached
    briefing = gen_briefing(bullpen, buyer)
    md = briefing.get("markdown", "")
    if not md.strip():
        return _write_cached(bullpen, buyer, "briefing_audio", {
            "empty": True, "audio_path": None,
            "message": "No briefing markdown to narrate yet — drop sources first.",
        })

    say_bin = shutil.which("say")
    if not say_bin:
        return _write_cached(bullpen, buyer, "briefing_audio", {
            "empty": True, "audio_path": None,
            "message": "macOS 'say' command not available. Briefing-audio "
                       "requires macOS or a piper install. Read the markdown "
                       "briefing instead.",
        })

    # Strip markdown to plain text for TTS
    plain = re.sub(r"^#+\s+", "", md, flags=re.M)        # headers → bare text
    plain = re.sub(r"\*\*([^*]+)\*\*", r"\1", plain)     # **bold** → bold
    plain = re.sub(r"`([^`]+)`", r"\1", plain)           # `code` → code
    plain = re.sub(r"^\s*[-*]\s+", "Next, ", plain, flags=re.M)  # list bullets → "next,"
    plain = re.sub(r"\s+", " ", plain).strip()

    if len(plain) < 40:
        return _write_cached(bullpen, buyer, "briefing_audio", {
            "empty": True, "audio_path": None,
            "message": "Briefing markdown too short to narrate.",
        })

    audio_path = _artifacts_dir(bullpen, buyer) / "briefing.aiff"
    # macOS `say` flags: -v voice, -r WPM, -o file (auto-detects aiff)
    try:
        subprocess.run(
            [say_bin, "-v", "Alex", "-r", "200", "-o", str(audio_path), plain],
            check=True, capture_output=True, timeout=120,
        )
    except subprocess.SubprocessError as e:
        return _write_cached(bullpen, buyer, "briefing_audio", {
            "empty": True, "audio_path": None,
            "message": f"say command failed: {e}",
        })

    if not audio_path.exists() or audio_path.stat().st_size < 1000:
        return _write_cached(bullpen, buyer, "briefing_audio", {
            "empty": True, "audio_path": None,
            "message": "TTS produced empty audio file.",
        })

    # ~150 WPM is conservative — say's defaults at -r 200 are closer to
    # 200 WPM. Estimate from word count.
    words = len(plain.split())
    duration_sec = max(20, int(words / 200 * 60))

    return _write_cached(bullpen, buyer, "briefing_audio", {
        "audio_relpath": f"artifacts/{buyer}/briefing.aiff",
        "audio_url": f"/api/b/{bullpen}/artifacts/{buyer}/briefing.aiff",
        "voice": "Alex",
        "duration_estimate_sec": duration_sec,
        "word_count": words,
        "size_bytes": audio_path.stat().st_size,
        "markdown": md,
    })


GENERATORS = {
    "flashcards":      gen_flashcards,
    "quiz":            gen_quiz,
    "briefing":        gen_briefing,
    "one_sheeter":     gen_one_sheeter,
    "account_map":     gen_account_map,
    "data_table":      gen_data_table,
    "briefing_audio":  gen_briefing_audio,
}


def generate(bullpen: str, buyer: str, kind: str, *, force: bool = False) -> dict:
    if kind not in GENERATORS:
        raise ValueError(f"unknown kind: {kind}")
    if force:
        # Invalidate cache
        p = _artifact_path(bullpen, buyer, kind)
        if p.exists():
            try: p.unlink()
            except Exception: pass
    return GENERATORS[kind](bullpen, buyer)


def manifest(bullpen: str, buyer: str) -> dict:
    """One-shot status check across all asset kinds for a buyer."""
    out = {
        "bullpen": bullpen,
        "buyer": buyer,
        "corpus_signature": _corpus_signature(bullpen, buyer),
        "assets": {},
    }
    for kind in GENERATORS:
        p = _artifact_path(bullpen, buyer, kind)
        if p.exists():
            try:
                cached = json.loads(p.read_text())
                out["assets"][kind] = {
                    "generated_at": cached.get("__generated_at"),
                    "fresh": cached.get("__corpus_signature") == out["corpus_signature"],
                    "summary": _summary_for(kind, cached),
                }
            except Exception:
                out["assets"][kind] = {"error": "unreadable"}
        else:
            out["assets"][kind] = None
    return out


def _summary_for(kind: str, data: dict) -> str:
    if kind == "flashcards": return f"{len(data.get('cards') or [])} cards"
    if kind == "quiz":       return f"{len(data.get('questions') or [])} questions"
    if kind == "briefing":   return f"{data.get('word_count') or 0} words"
    if kind == "one_sheeter": return "ready"
    if kind == "account_map": return f"{len(data.get('nodes') or [])} entities, {len(data.get('edges') or [])} edges"
    if kind == "data_table":  return f"{len(data.get('contacts') or [])} contacts, {len(data.get('recent_news') or [])} news"
    if kind == "briefing_audio":
        if data.get("empty"): return "TTS not available"
        return f"{data.get('duration_estimate_sec', 0)}s · {data.get('voice', '?')} voice"
    return ""


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python3 server/generators.py <kind> <bullpen> <buyer> [--force]")
        print("       kinds: " + ", ".join(GENERATORS))
        sys.exit(0)
    kind, bp, buyer = sys.argv[1], sys.argv[2], sys.argv[3]
    force = "--force" in sys.argv
    out = generate(bp, buyer, kind, force=force)
    print(json.dumps(out, indent=2))
