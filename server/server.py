#!/usr/bin/env python3
"""
Cheers Beers — local trainer server
===================================
Local-only AI sales training tool. Companies live as organizations/<slug>/
folders. Click any walking character on the floor → org dossier with people,
calls, deals. Practice the conversation with the AI. Record real calls and
the debrief loop auto-extracts new contacts.

Runs against your local Ollama Gemma + whisper.cpp. No cloud, no API key,
no telemetry.

Start:
    python3 server.py
Then open the floor at floor/index.html or the trainer at
http://localhost:7878
"""
import http.server
import json
import socketserver
import subprocess
import sys
import tempfile
import urllib.request
import datetime
import re
import shutil
from pathlib import Path

# Cheers Beers uses two file stores: the legacy personas/ (still loaded if
# present, for back-compat) AND the new organizations/<slug>/ structure that
# is the canonical source going forward.
_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO / "personas"))
sys.path.insert(0, str(_REPO / "server"))

try:
    from loader import load_all as _load_personas, build_persona_prompt as _build_persona_prompt, build_scoring_prompt as _build_scoring_prompt
    _USE_FILE_PERSONAS = True
except Exception as _e:
    print(f"⚠ persona loader unavailable ({_e}); falling back to hardcoded PERSONAS")
    _USE_FILE_PERSONAS = False

# Org graph loader — always available since it ships with the server
try:
    from orgs import load_all as _load_orgs, load_org as _load_org
    _USE_ORG_GRAPH = True
except Exception as _e:
    print(f"⚠ org loader unavailable ({_e})")
    _USE_ORG_GRAPH = False

# ──────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────
PORT = 7878
OLLAMA_URL = "http://localhost:11434/api/chat"
# Preferred model order — first one available wins. Gemma 9B for roleplay,
# Gemma 12B if you've pulled it, deepseek-coder as last-resort fallback.
MODEL_PREFERENCE = ["gemma2:9b", "gemma3:12b", "gemma2:12b", "deepseek-coder:6.7b"]

# Voice stack — all local. whisper.cpp for STT, macOS `say` for TTS.
WHISPER_BIN = shutil.which("whisper-cli") or "/opt/homebrew/bin/whisper-cli"
WHISPER_MODEL = str(_REPO / "server" / "models" / "ggml-base.en.bin")
SAY_BIN = "/usr/bin/say"
AFCONVERT_BIN = "/usr/bin/afconvert"

TRAINING_DIR = _REPO / "training-runs"
TRAINING_DIR.mkdir(parents=True, exist_ok=True)

# Voice mapping — pick a different macOS voice per persona so each call sounds
# distinct. Voices available on a base macOS install (no premium download).
# `say -v "?"` shows what's available; we use the 5 that sound credibly
# enterprise: Daniel (British male), Karen (Aus female), Samantha (US female),
# Fred (older US male — good for Bill Hinshaw), Ralph (US male).
VOICES = {
    "rocket-software": ("Daniel", 175),   # British technical VP
    "syntax": ("Karen", 180),             # Director-level female
    "ensono": ("Samantha", 175),          # Polished US female practice lead
    "cobol-cowboys": ("Fred", 160),       # Older Texan male, slower pace
    "keyhole": ("Ralph", 180),            # Midwestern male
    "integrative-systems": ("Daniel", 180),
    "epam": ("Samantha", 185),            # Crisp BFSI Director
    "premera": ("Karen", 175),            # Careful, procedural
    "nw-natural": ("Ralph", 165),         # Slow utility-IT culture
    "the-standard": ("Samantha", 170),    # Pacific NW enterprise
}

# ──────────────────────────────────────────────────────────────────────────
# Personas — pulled from your prospect cards. Each entry packs the same
# WHAT/ASK/ANGLE/WATCH/OPENER/GOAL fields you see in REFERENCE_BOARD.html so
# the AI plays a specific real buyer, not a generic enterprise persona.
# ──────────────────────────────────────────────────────────────────────────
PERSONAS = {
    "rocket-software": {
        "company": "Rocket Software",
        "role": "VP of Application Modernization",
        "hq": "Waltham, MA",
        "size": "≈2,500 employees",
        "zone": "Tool Partner",
        "what": "800-lb gorilla of IBM i / AS400 / mainframe modernization tools. Owns BlueZone, TeamStudio, RPG + COBOL conversion stacks.",
        "pushbacks": [
            "We already sell modernization tools — BlueZone, TeamStudio, RPG converters. How is this different?",
            "Our customers are already paying us for this. Why would they want another vendor?",
            "Send me a deck. I'll have my team look at it.",
            "We have OEM relationships locked up. Approach our partnership team in Q3.",
            "If this were valuable, IBM would have built it.",
        ],
        "personality": "Senior product/practice leader at a 2,500-person modernization vendor. Has heard hundreds of startup pitches. Polite Boston-area enterprise tone. Quick to end calls that waste time but not gratuitously rude.",
        "speech_profile": (
            "American (East Coast / Boston-area) enterprise English. Slightly clipped, professional. "
            "Sentences are short. Uses neutral acknowledgments ('Mhm,' 'Okay,' 'Sure.'). "
            "When skeptical, asks pointed questions rather than complaining ('How is this different from what BlueZone does?'). "
            "Will reference his portfolio products naturally — BlueZone, TeamStudio, Modern eXperience — but does not lecture. "
            "Never says 'absolutely' or 'awesome' — those are SaaS-sales words and he'd never use them."
        ),
    },
    "syntax": {
        "company": "Syntax",
        "role": "Director of Legacy Modernization",
        "hq": "Montreal HQ · Boston ops",
        "size": "Managed IT services",
        "zone": "Channel Partner",
        "what": "Managed IT services. Heavy in SAP, JD Edwards, mainframe outsourcing for financial / insurance carriers.",
        "pushbacks": [
            "Our insurance clients are sticky — what's the integration story?",
            "We're SAP-shop heavy. COBOL parity verification isn't where we make our money.",
            "How does this fit into our existing mainframe outsourcing engagements?",
            "Send me a deck.",
        ],
        "personality": "Pragmatic operator. Cares about delivery economics. Will ask about engagement integration, not technical depth. Easier to win than Rocket — but won't move fast without proof.",
        "speech_profile": (
            "Crisp, business-formal American English with occasional French-Canadian intonation. "
            "Director-level pacing — uses 'we' a lot ('we run SAP for a lot of carriers'). "
            "Prefers concrete questions about delivery model and economics over technical depth. "
            "Asks 'how does this fit our existing engagements?' early. Patient on the call, but won't waste cycles."
        ),
    },
    "ensono": {
        "company": "Ensono",
        "role": "Mainframe & Midrange Modernization Practice Lead",
        "hq": "Downers Grove, IL",
        "size": "≈3,500 employees",
        "zone": "Channel Partner",
        "what": "One of the last hybrid mainframe-to-cloud specialists. Owns modernization journey for ~250 enterprise clients.",
        "pushbacks": [
            "We're already deeply partnered with IBM and Microsoft on modernization tooling.",
            "Our customers want a managed service, not another tool to evaluate.",
            "How is this different from the conversion phase of an LzLabs or Heirloom engagement?",
            "Show me the FedRAMP / SOC 2 status before we go further.",
        ],
        "personality": "Senior, polished, enterprise-formal. Asks about compliance, partnerships, contract structure. Won't engage on price. Wants to know how you fit her existing delivery stack.",
        "speech_profile": (
            "Midwestern American (Chicago-area), measured, professional. Speaks in complete sentences. "
            "Uses qualifiers — 'typically,' 'in our experience,' 'historically.' "
            "Will ask about FedRAMP, SOC 2, IBM/Microsoft partnership status before the technical depth. "
            "When uncertain, defers — 'I'd need to bring in our practice lead' — rather than rejecting outright."
        ),
    },
    "cobol-cowboys": {
        "company": "Cobol Cowboys",
        "role": "Bill Hinshaw (founder, ex-IBM mainframe engineer)",
        "hq": "Gainesville, TX",
        "size": "Boutique · principals are senior retired COBOL engineers",
        "zone": "Boutique Partner",
        "what": "Famous COBOL specialists. Featured in WSJ, NPR. Bring retired mainframe engineers back to maintain bank / insurance code.",
        "pushbacks": [
            "My guys ARE the senior engineers. We don't need a tool — we ARE the tool.",
            "My cowboys have 40 years of experience. Your AI just hallucinates.",
            "Our brand is the people. Tools commoditize what we sell.",
            "Why would my customers pay for senior engineers AND a software license?",
        ],
        "personality": "Warm, Texas drawl, no-bullshit. Talks like he's seen everything. Respects competence, hates pitches. Will hang up on jargon. Listens hard to founders who can actually code.",
        "speech_profile": (
            "Bill Hinshaw — older Texas-born ex-IBM mainframe engineer. Talks plain, slow, deliberate. "
            "Uses 'son,' 'pal,' and 'we just get it done' — phrases consistent with his published WSJ/NPR interviews. "
            "Folksy but technically razor-sharp: he'll say 'son, I was writing COBOL when you were in diapers' "
            "and mean it. Sentences are short. Pauses between thoughts. "
            "Will NEVER use modern enterprise SaaS vocabulary — no 'leverage,' 'sync,' 'circle back.' "
            "Closes with 'alright pal, send me something — I gotta run.'"
        ),
    },
    "keyhole": {
        "company": "Keyhole Software",
        "role": "Practice Lead, Legacy Modernization",
        "hq": "Leawood, KS",
        "size": "Mid-sized custom software consultancy",
        "zone": "Boutique Partner",
        "what": "Mid-sized custom shop. Legacy modernization is one of several offerings (Java, .NET, mainframe).",
        "pushbacks": [
            "We're more of a Java/.NET shop. Mainframe is a small piece for us.",
            "We use our own playbooks. Why would we add a tool?",
            "Most of our clients aren't insurance-heavy.",
        ],
        "personality": "Friendly Midwestern consultancy energy. Will engage on the technical merits. Easy to get a meeting with — harder to get a contract.",
        "speech_profile": (
            "Kansas / Missouri American — warm, friendly, conversational. "
            "Uses 'we' and 'our team' a lot. Asks technical follow-ups quickly. "
            "Will say 'happy to take a look' rather than 'send me a deck.' "
            "Less rigid than Rocket/Ensono — more like talking to a mid-size shop owner."
        ),
    },
    "integrative-systems": {
        "company": "Integrative Systems",
        "role": "AS400 / COBOL Services Lead",
        "hq": "Itasca, IL",
        "size": "20+ years AS400 specialists",
        "zone": "Boutique Partner",
        "what": "Pure-play AS400 / IBM i modernization. RPG / COBOL / CL specialists across IBM i 7.1+.",
        "pushbacks": [
            "We've been doing AS400 for 20 years. We have our own conversion methodology.",
            "Our customers want our methodology, not a third-party tool.",
            "How does this work with RPG-IV and ILE programs, not just COBOL?",
        ],
        "personality": "Deep AS400 expert. Will instantly know if you're bullshitting on IBM i specifics. Respects technical depth.",
        "speech_profile": (
            "Mix of American + slight Indian-English inflection (the firm has India + US delivery). "
            "Deeply technical — will use IBM i jargon naturally ('IBM i 7.4,' 'ILE,' 'CL programs,' 'DB2/400'). "
            "If you don't speak the same language, he'll politely disengage. "
            "Asks specific implementation questions: 'How do you handle RPG-IV vs RPG-Free?'"
        ),
    },
    "epam": {
        "company": "EPAM",
        "role": "Director of Mainframe Modernization (BFSI vertical)",
        "hq": "Newtown, PA",
        "size": "≈60,000 employees",
        "zone": "Channel Partner",
        "what": "Massive engineering services firm. Deep banking + insurance verticals running COBOL.",
        "pushbacks": [
            "We have global delivery and our own modernization frameworks. Where do you fit?",
            "Our BFSI clients require enterprise vendor onboarding — NDA, MSA, security review. Are you ready for that?",
            "How is this not a feature IBM or AWS will ship in 6 months?",
            "Send a deck through partnerships@epam.com.",
        ],
        "personality": "Enterprise polish. Will route you to procurement if you don't show partnership-grade thinking. Doesn't engage on price. Cares about delivery scale.",
        "speech_profile": (
            "Sharp, corporate American English. Director-level, no time to waste but won't be rude. "
            "Uses 'we' constantly ('we have a vendor onboarding process,' 'we have global delivery'). "
            "Will reference frameworks and credentials early ('we have an AWS MSAP partnership'). "
            "If your pitch doesn't fit the enterprise lane, will route you out: 'send to partnerships@epam.com.' "
            "Doesn't engage with founders one-on-one — assumes you have a sales team behind you."
        ),
    },
    "premera": {
        "company": "Premera Blue Cross",
        "role": "Enterprise Architecture Lead (or whoever the gatekeeper hands you to)",
        "hq": "Mountlake Terrace, WA",
        "size": "≈3M members · large BCBS regional",
        "zone": "End Customer",
        "what": "Large regional Blue Cross plan. Mainframe-heavy carrier; ACORD relevance is direct. Claims processing engine carries 30+ years of COBOL.",
        "pushbacks": [
            "We have a vendor risk management process — start there.",
            "We have an existing relationship with Cognizant on modernization. Why would we change?",
            "HIPAA compliance is non-negotiable. What's your security architecture?",
            "I don't have budget. Talk to me next fiscal.",
            "Send a deck to our procurement portal.",
        ],
        "personality": "Cautious, risk-averse, procurement-driven. Will hide behind process. Warms ONLY if you make 'ticking time bomb' real to their actual systems. References HIPAA constantly.",
        "speech_profile": (
            "Pacific Northwest enterprise IT — polite but measured. Healthcare regulatory mindset baked in. "
            "Phrases everything around risk and process: 'our VRM team would need to evaluate that,' "
            "'we have a vendor onboarding portal,' 'I'd want our security architecture team in the room.' "
            "Will mention HIPAA, HITRUST, or 'protected health information' early — that's the lens she sees through. "
            "Not hostile, just hedged. If you don't address the security frame, she'll politely route you to the portal and end."
        ),
    },
    "nw-natural": {
        "company": "NW Natural",
        "role": "Office of the CIO contact",
        "hq": "Portland, OR",
        "size": "Regional natural-gas utility",
        "zone": "End Customer",
        "what": "Regional natural-gas utility. Billing + customer systems include legacy COBOL/mainframe components.",
        "pushbacks": [
            "We're a utility — we don't move fast on new tech.",
            "Our customer billing system has been stable for 20 years. Why touch it?",
            "How does this affect our PUC regulatory reporting?",
            "I'd need to involve our IT security committee. That takes 6+ months.",
        ],
        "personality": "Conservative utility-IT culture. Talks slowly. Won't say no, but won't say yes. Procurement is glacier-paced. Cares about regulator/audit risk.",
        "speech_profile": (
            "Pacific Northwest utility-IT — slow, deliberate, friendly. Will not commit to anything. "
            "Phrases like 'we'd want to bring our IT security committee into that,' 'we move pretty deliberately around here,' "
            "'our PUC oversight requires us to evaluate things carefully.' Long silences between sentences are normal. "
            "Won't end the call early — but won't move forward either without a process. Mentions regulators (PUC) naturally."
        ),
    },
    "the-standard": {
        "company": "The Standard",
        "role": "IT Sourcing / Office of the CIO",
        "hq": "Portland, OR",
        "size": "Group disability + life insurance (Meiji Yasuda subsidiary)",
        "zone": "End Customer",
        "what": "Group disability + life insurance carrier. Long-tenured COBOL claims systems.",
        "pushbacks": [
            "We have ongoing modernization work with Accenture. We're not looking for additional vendors.",
            "All vendor evals go through procurement — submit through the portal.",
            "What's your financial backing? We don't engage with one-person companies.",
            "Our claims system has zero downtime tolerance. Where's the production proof?",
        ],
        "personality": "Polite Pacific-Northwest enterprise IT. Risk-averse, procurement-heavy. Will not engage on price. Wants to see logos and case studies you don't have yet.",
        "speech_profile": (
            "Polite Portland, OR enterprise IT — calm, professional, slightly indirect. "
            "Phrases everything through process: 'all vendor evals go through procurement,' "
            "'I'd need to involve our IT sourcing team,' 'we have ongoing work with Accenture.' "
            "Doesn't say no — manages you toward the right channel. Asks about your financial backing, references, logos. "
            "If you don't have proof points, will route you to the portal and politely close."
        ),
    },
}

# ──────────────────────────────────────────────────────────────────────────
# Prompt builders
# ──────────────────────────────────────────────────────────────────────────

# Runtime cache of file-based personas (refreshed on every chat call so
# editing personas/<slug>/*.md takes effect without restarting the server).
_runtime_personas = {}

def _refresh_personas():
    global _runtime_personas
    if _USE_FILE_PERSONAS:
        _runtime_personas = _load_personas()


def persona_system_prompt(slug):
    """Build the system prompt that makes the model play the prospect."""
    if _USE_FILE_PERSONAS:
        _refresh_personas()
        if slug in _runtime_personas:
            return _build_persona_prompt(_runtime_personas[slug])
    p = PERSONAS[slug]
    pushbacks_block = "\n".join(f"  - \"{q}\"" for q in p["pushbacks"])
    speech = p.get("speech_profile", "")
    speech_block = f"\nHOW YOU TALK (speech profile — match this exactly)\n────────────────────────────────────────────────\n{speech}\n" if speech else ""

    return f"""You are roleplaying as a real human picking up a cold call. Dylan Beers from Beers Labs is the caller. You are NOT an assistant. You are NOT a chatbot. You just picked up a ringing phone in the middle of your workday.

WHO YOU ARE
───────────
Role: {p['role']}
Company: {p['company']}
Location: {p['hq']}
Company size: {p['size']}
What the company does: {p['what']}

YOUR INTERNAL STATE (this is YOU — feel it, don't perform it)
{p['personality']}
{speech_block}
WHAT DYLAN IS SELLING (you don't know this yet — you just answered the phone)
KillSesh: an on-prem AI pipeline that translates COBOL copybooks to TypeScript with verified field parity. Dylan wants a 15-minute technical briefing with you (or the name of the right tech lead).

═════════════════════════════════════════════════════════════════
HOW REAL PHONE CALLS WORK — READ CAREFULLY
═════════════════════════════════════════════════════════════════

▸ FIRST TURN (you just picked up the phone)
  Say ONLY a normal phone pickup — pick ONE of these patterns and use a real last name (either the one in your character if specified, or invent a plausible one fitting your background — e.g., "Patel," "Chen," "Johnson," "Reyes," "Walsh"):
    "Hello?"
    "[Lastname]."
    "[Lastname] speaking."
    "Yes?"
    "This is [Lastname]."

  CRITICAL: Output the actual name as a real word. NEVER output literal brackets like "[Your last name]" — that's a template, not a name. If you don't have a specific name, invent ONE plausible last name and use it from now on consistently.

  DO NOT — under any circumstances — volunteer that you're busy, on a deadline, in a hurry, between meetings, or annoyed. You haven't heard the caller yet. You have no opinion of them yet. Real people do not greet callers with "what's this regarding I'm busy" — that is theater, not reality. Just say hello.

▸ TURNS 2-3 (Dylan introduces himself and starts talking)
  Stay NEUTRAL. Listen. Respond in 1-2 short sentences. Reasonable acknowledgments:
    "Okay."
    "I'm listening."
    "Go ahead."
    "What's this about?"
    "Sure."
  Do not push back yet. You have no reason to. Most cold calls earn 20-30 seconds of grace from any reasonable person.

▸ TURNS 4+ (you've heard enough to form a judgment)
  NOW react based on HOW DYLAN IS DOING. This is a sliding warmth curve:

  → If Dylan is SPECIFIC about a pain you actually have, knows your company, shows real domain knowledge, asks for a meeting (not the deal), avoids jargon dumps:
       Warm up. Ask follow-up questions. Engage. Eventually agree to 15 minutes.
       Example: "Okay — you've got my attention. What did you have in mind?"

  → If Dylan is doing OK but generic — vague pitch, doesn't name your specific situation:
       Stay polite but skeptical. Push back with one of YOUR TYPICAL PUSHBACKS below.
       Example: "We already work with [incumbent]. What's different here?"

  → If Dylan is FAILING — dumping jargon early ("zero-egress", "deterministic field parity") before you've shown interest, pitching the price ($15K) before you've asked, sounding scripted, apologizing, can't articulate a clear ask:
       Get colder. Push back harder. After 3-4 bad exchanges, end the call politely.

▸ TURNS 8-12 — Time to decide
  Either AGREE to a 15-minute briefing (if earned) and ask "What's the best email to send the invite to?" — or END the call cleanly with one of:
    "I'll have to think about it — send me something."
    "Not the right fit for us right now."
    "I have a hard stop — send me an email."
  Do not soliloquize. End the call like a real busy person would.

═════════════════════════════════════════════════════════════════
ABSOLUTE RULES
═════════════════════════════════════════════════════════════════
- 1-3 sentences MAX per turn. No paragraphs. No bullet lists. No markdown.
- Match your speech profile above. If it says "Texan drawl, plain spoken" — talk like that. If it says "clipped British, technical" — talk like that.
- Hostility must be EARNED. Never volunteer hostility in turn 1 or 2.
- Skepticism is fine after turn 3. Hostility only after Dylan does something objectively wrong (jargon dump, price pitch too early, no clear ask).
- NEVER break character. NEVER mention AI, training, simulation, coaching.
- NEVER coach Dylan mid-call. You are not a teacher. You are a buyer.
- If you push back, USE YOUR ACTUAL PUSHBACKS:
{pushbacks_block}

GO. The phone just rang. Pick up."""


def scoring_system_prompt(slug):
    """Build the system prompt for the post-call grading pass."""
    if _USE_FILE_PERSONAS:
        _refresh_personas()
        if slug in _runtime_personas:
            return _build_scoring_prompt(_runtime_personas[slug])
    p = PERSONAS[slug]
    return f"""You are a senior sales coach reviewing a recorded cold-call practice session.

CONTEXT
The rep, Dylan Beers, was cold-calling someone playing {p['role']} at {p['company']}.
Dylan's ONE GOAL on this call: book a 15-minute technical briefing with the right technical lead. NOT close a deal. NOT quote price. NOT explain SOW. Just get the meeting.

THE KILLSESH COLD-CALL PLAYBOOK
Dylan should have followed this structure:
  1. GREET (3 sec): "Hi, this is Dylan Beers with Beers Labs. I'll be quick."
     [Then pause one full second for them to say "go ahead"]
  2. P&L PUNCH (8 sec): A specific pain you know they have — "I know your team is burning hundreds of hours manually reverse-engineering copybooks..." (channel partner) or "The engineers who wrote your claims system are retiring..." (end customer).
  3. PROOF (10 sec): "We built a tool that translates the code AND mathematically proves nothing got lost. Runs on your hardware — code never leaves your network."
  4. ASK (6 sec): "I'm looking for the person who [role-specific]. 15 minutes to see if it fits — who's the right contact?"

HARD RULES Dylan must follow:
  ✓ Energy: calm, clinical, hyper-competent. Like a senior partner at a law firm. NOT alpha/hyperactive.
  ✓ Pause one full second after "I'll be quick."
  ✓ Say the company name at least once in the first 20 seconds.
  ✗ DO NOT mention $15K to a gatekeeper or non-decision-maker.
  ✗ DO NOT use jargon ("zero-egress", "deterministic field parity") UNLESS they ask a technical follow-up first.
  ✗ DO NOT lead with the price — lead with the pain, then proof, then price.
  ✗ DO NOT apologize. DO NOT say "sorry to bother you."
  ✗ DO NOT say "I emailed you last week" — sounds like a beggar.

KEY OBJECTION RESPONSES Dylan should know:
  - "Send me a deck" → "Better — live trace at killsesh.com/demo, signed tarball at killsesh.com/downloads. Take 5 minutes on those, then 15 minutes Thursday. Calendar?"
  - "What does it cost?" → "Pilot is $15K flat, full program $250K+. But let's not talk price until you see the deliverable. Can we do 15 minutes Thursday?"
  - "We already use IBM" → "Right — most of our pilots run alongside the incumbent. We don't replace them, we verify them."
  - "I'm not the right person" → "Appreciate it. Who in your org owns mainframe modernization or COBOL-to-modern translation?"

YOUR OUTPUT (use these EXACT section headers):
SCORE: [letter grade A through F]
WOULD THIS BOOK THE MEETING: [YES / MAYBE / NO]
WHAT WORKED:
- bullet
- bullet
- bullet
WHAT TO FIX:
- bullet
- bullet
- bullet
THE SINGLE BIGGEST MISS:
[1-2 sentences naming the one thing that hurt this call most]
NEXT TIME:
[1-2 sentences of specific corrective action — what to say differently on the next dial]

Be honest. Be direct. Score against the playbook, not against effort. If Dylan dumped jargon early, dock him. If he failed to ask for the meeting, dock him. If he buckled on price, dock him. The goal of training is to make tomorrow's real call land — not make him feel good now."""


# ──────────────────────────────────────────────────────────────────────────
# Ollama call
# ──────────────────────────────────────────────────────────────────────────
_resolved_model = None

def get_model():
    """Pick the best available Ollama model from MODEL_PREFERENCE."""
    global _resolved_model
    if _resolved_model:
        return _resolved_model
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            installed = {m["name"] for m in json.loads(r.read())["models"]}
    except Exception:
        return MODEL_PREFERENCE[0]
    for m in MODEL_PREFERENCE:
        if m in installed:
            _resolved_model = m
            return m
    _resolved_model = MODEL_PREFERENCE[-1]
    return _resolved_model


# ──────────────────────────────────────────────────────────────────────────
# Voice — local STT (whisper.cpp) + TTS (macOS `say`)
# ──────────────────────────────────────────────────────────────────────────

def transcribe_wav(wav_bytes: bytes) -> str:
    """Pipe WAV audio through whisper.cpp; return transcribed text."""
    if not Path(WHISPER_MODEL).exists():
        raise RuntimeError(f"whisper model missing at {WHISPER_MODEL}")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        in_path = f.name
    out_base = in_path[:-4]  # strip .wav for -of arg
    try:
        subprocess.run(
            [
                WHISPER_BIN, "-m", WHISPER_MODEL,
                in_path, "-nt", "-otxt", "-of", out_base,
                "-l", "en", "-t", "4",  # threads
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        txt_path = out_base + ".txt"
        if not Path(txt_path).exists():
            return ""
        return Path(txt_path).read_text().strip()
    finally:
        for p in (in_path, out_base + ".txt"):
            try: Path(p).unlink()
            except FileNotFoundError: pass


def _xtts_synthesize(text: str, clone_cfg: dict) -> bytes:
    """Tier 3: use Coqui XTTS-v2 to synthesize in the cloned voice. Returns WAV bytes.
    Falls back to RuntimeError if TTS isn't installed — caller should catch."""
    from TTS.api import TTS  # type: ignore  # lazy import
    # Cache the model across calls — XTTS load takes ~10s on first call.
    global _XTTS
    try:
        _XTTS
    except NameError:
        _XTTS = TTS(model_name=clone_cfg["model_name"], progress_bar=False, gpu=False)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out = f.name
    try:
        _XTTS.tts_to_file(
            text=text,
            speaker_wav=clone_cfg["speaker_wav"],
            language=clone_cfg.get("language", "en"),
            file_path=out,
        )
        return Path(out).read_bytes()
    finally:
        try: Path(out).unlink()
        except FileNotFoundError: pass


def synthesize_wav(text: str, slug: str) -> bytes:
    """Tier 3 (cloned voice) if available, otherwise Tier 1 (macOS `say`)."""
    # Tier 3 path: persona has voice/clone_config.json
    if _USE_FILE_PERSONAS:
        p = _runtime_personas.get(slug)
        if p and p.cloned_voice_path:
            try:
                cfg = json.loads(Path(p.cloned_voice_path).read_text())
                return _xtts_synthesize(text, cfg)
            except ImportError:
                # XTTS not installed — fall through to `say` silently. The CLI
                # already told the user how to install when they ran clone-voice.
                pass
            except Exception as e:
                print(f"⚠ XTTS synthesis failed for {slug}: {e}; falling back to say")

    # Tier 1 fallback: macOS `say` with the configured voice.
    if _USE_FILE_PERSONAS and slug in _runtime_personas:
        p = _runtime_personas[slug]
        voice, rate = p.say_voice, p.say_rate
    else:
        voice, rate = VOICES.get(slug, ("Samantha", 175))
    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as f:
        aiff_path = f.name
    wav_path = aiff_path.replace(".aiff", ".wav")
    try:
        subprocess.run(
            [SAY_BIN, "-v", voice, "-r", str(rate), "-o", aiff_path, text],
            check=True,
            capture_output=True,
            timeout=30,
        )
        # 22050 Hz mono 16-bit PCM — universally browser-playable + small file.
        subprocess.run(
            [AFCONVERT_BIN, aiff_path, "-f", "WAVE", "-d", "LEI16@22050", "-c", "1", wav_path],
            check=True,
            capture_output=True,
            timeout=15,
        )
        return Path(wav_path).read_bytes()
    finally:
        for p in (aiff_path, wav_path):
            try: Path(p).unlink()
            except FileNotFoundError: pass


def ollama_chat(messages, temperature=0.85):
    """Call Ollama's /api/chat. Returns the assistant message string."""
    payload = {
        "model": get_model(),
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": 8192},
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return data.get("message", {}).get("content", "").strip()


# ──────────────────────────────────────────────────────────────────────────
# Transcript saving
# ──────────────────────────────────────────────────────────────────────────

def save_transcript(slug, messages, score):
    """Drop a markdown transcript into ~/killsesh-pilots/training-runs/."""
    if _USE_FILE_PERSONAS and slug in _runtime_personas:
        rp = _runtime_personas[slug]
        p = {"company": rp.company, "role": rp.role, "zone": rp.zone}
    else:
        p = PERSONAS[slug]
    today = datetime.date.today().isoformat()
    existing = list(TRAINING_DIR.glob(f"{today}-{slug}-*.md"))
    n = len(existing) + 1
    path = TRAINING_DIR / f"{today}-{slug}-attempt-{n}.md"

    lines = [
        f"# Training Run · {p['company']} · attempt {n}",
        "",
        f"**Date:** {today}",
        f"**Persona:** {p['role']} at {p['company']} ({p['zone']})",
        f"**Model:** {get_model()}",
        "",
        "## Transcript",
        "",
    ]
    for m in messages:
        if m["role"] == "system":
            continue
        speaker = "**Dylan**" if m["role"] == "user" else f"**{p['company']}**"
        lines.append(f"{speaker}: {m['content']}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Coach's Score")
    lines.append("")
    lines.append(score)
    lines.append("")

    path.write_text("\n".join(lines))
    return str(path)


# ──────────────────────────────────────────────────────────────────────────
# HTTP server
# ──────────────────────────────────────────────────────────────────────────
HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cheers Beers · Trainer</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;500;600&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0a0a; --panel: #111; --panel-2: #161616; --border: #1f1f1f;
    --text: #e6e6e6; --muted: #8a8a8a;
    --accent: #34d399; --accent-2: #6ee7b7; --accent-dim: #064e3b;
    --warn: #fbbf24; --danger: #f87171; --cyan: #22d3ee; --cyan-2: #67e8f9;
    --mono: "JetBrains Mono",ui-monospace,Menlo,monospace;
    --sans: "Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    --serif: "Fraunces",ui-serif,Georgia,serif;
  }
  *{box-sizing:border-box}
  html,body{background:var(--bg);color:var(--text);margin:0;font-family:var(--sans);font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased;height:100%}
  body{display:flex;flex-direction:column}
  header{padding:14px 24px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
  header .brand{font-family:var(--serif);font-weight:600;font-size:18px}
  header .brand .accent{color:var(--accent)}
  header .meta{font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;color:var(--muted);text-transform:uppercase}
  .controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  select,button{font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;padding:7px 12px;border-radius:3px;border:1px solid var(--border);background:#0d0d0d;color:var(--text);cursor:pointer}
  select{padding-right:28px;text-transform:none;letter-spacing:0;font-family:var(--sans);font-size:13px}
  select:focus,button:focus{outline:1px solid var(--accent);outline-offset:1px}
  button.primary{background:rgba(52,211,153,0.10);border-color:var(--accent-dim);color:var(--accent)}
  button.primary:hover{background:rgba(52,211,153,0.20)}
  button.danger{background:rgba(248,113,113,0.08);border-color:#4a1818;color:var(--danger)}
  button.danger:hover{background:rgba(248,113,113,0.18)}
  button:disabled{opacity:0.4;cursor:not-allowed}
  main{flex:1;display:grid;grid-template-columns:1.5fr 1fr;gap:16px;padding:16px 24px;overflow:hidden;min-height:0}
  @media(max-width:880px){main{grid-template-columns:1fr;overflow:auto}}
  .panel{background:var(--panel);border:1px solid var(--border);border-radius:6px;display:flex;flex-direction:column;overflow:hidden;min-height:0}
  .panel-h{padding:10px 14px;border-bottom:1px solid var(--border);font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);display:flex;justify-content:space-between;align-items:center}
  .panel-h .live{color:var(--accent)}
  .panel-h .live::before{content:"●";margin-right:4px}
  .chat{flex:1;overflow-y:auto;padding:16px 18px}
  .msg{margin:8px 0;display:flex;gap:10px}
  .msg .speaker{font-family:var(--mono);font-size:9.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);min-width:64px;flex-shrink:0;padding-top:2px}
  .msg .body{flex:1;font-family:var(--serif);font-size:15.5px;line-height:1.6;color:#dcdcdc;white-space:pre-wrap}
  .msg.user .speaker{color:var(--accent)}
  .msg.user .body{color:#fff}
  .msg.persona .speaker{color:var(--cyan)}
  .msg.system{font-family:var(--mono);font-size:11px;color:var(--muted);font-style:italic;padding:6px 10px;background:#0d0d0d;border-radius:3px;border-left:2px solid var(--border);text-align:left}
  .msg.system .speaker{display:none}
  .msg.system .body{font-family:var(--mono);font-size:11px}
  .compose{padding:12px 14px;border-top:1px solid var(--border);display:flex;gap:8px;background:#0d0d0d}
  .compose textarea{flex:1;resize:none;min-height:42px;max-height:160px;font-family:var(--serif);font-size:15px;background:#161616;color:#fff;border:1px solid var(--border);border-radius:4px;padding:10px 12px;line-height:1.5}
  .compose textarea:focus{outline:none;border-color:var(--accent)}
  .compose button{align-self:stretch;padding:8px 16px}
  .side{padding:14px 16px;overflow-y:auto}
  .persona-card{margin-bottom:14px}
  .persona-card .who{font-family:var(--serif);font-size:18px;font-weight:600;color:#fff;line-height:1.3}
  .persona-card .role{font-family:var(--mono);font-size:11px;letter-spacing:.1em;color:var(--cyan);text-transform:uppercase;margin-top:4px}
  .persona-card .zone{display:inline-block;font-family:var(--mono);font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;padding:2px 7px;border-radius:2px;margin-top:6px}
  .persona-card .zone.end{color:var(--warn);background:rgba(251,191,36,0.10);border:1px solid #3a2a05}
  .persona-card .zone.channel{color:var(--cyan);background:rgba(34,211,238,0.10);border:1px solid #06262c}
  .persona-card .zone.tool{color:#a78bfa;background:rgba(167,139,250,0.08);border:1px solid #2a1f4a}
  .persona-card .zone.boutique{color:var(--accent);background:rgba(52,211,153,0.10);border:1px solid var(--accent-dim)}
  .persona-card .meta{font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:6px}
  .persona-card .what{margin-top:10px;font-size:13px;line-height:1.55;color:#cfcfcf}
  .reminder{margin-top:14px;padding:10px 12px;background:#0d0d0d;border-radius:4px;border:1px dashed var(--accent-dim)}
  .reminder h4{margin:0 0 6px;font-family:var(--mono);font-size:10px;letter-spacing:.18em;color:var(--accent);text-transform:uppercase}
  .reminder p{margin:0;font-size:12.5px;color:#cfcfcf;line-height:1.5}
  .score-card{padding:14px;font-family:var(--mono);font-size:12.5px;line-height:1.65;white-space:pre-wrap;color:#dcdcdc;overflow-y:auto;margin:0}
  .score-grade{font-family:var(--serif);font-size:48px;color:var(--accent);font-weight:600;display:block;margin-bottom:8px;line-height:1}
  .empty{padding:24px;color:var(--muted);font-size:13px;text-align:center;font-style:italic}
  .spinner{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--accent);animation:pulse 1s infinite}
  @keyframes pulse{0%,100%{opacity:0.3}50%{opacity:1}}
  .typing{padding:6px 14px;font-family:var(--mono);font-size:10.5px;color:var(--muted);letter-spacing:.12em;text-transform:uppercase}
  /* Push-to-talk mic + voice toggle */
  .voice-bar{display:flex;align-items:center;gap:10px;padding:10px 14px;border-top:1px solid var(--border);background:#0d0d0d}
  .mic-btn{flex:1;display:flex;align-items:center;justify-content:center;gap:10px;font-family:var(--mono);font-size:12px;letter-spacing:.18em;text-transform:uppercase;padding:14px 18px;border-radius:4px;border:1.5px solid var(--accent-dim);background:rgba(52,211,153,0.06);color:var(--accent);cursor:pointer;user-select:none;-webkit-user-select:none;transition:all .12s ease}
  .mic-btn:hover{background:rgba(52,211,153,0.12)}
  .mic-btn:disabled{opacity:.4;cursor:not-allowed}
  .mic-btn.recording{background:rgba(248,113,113,0.18);border-color:var(--danger);color:var(--danger);box-shadow:0 0 0 4px rgba(248,113,113,0.10);animation:micPulse 1s infinite}
  .mic-btn .mic-dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:currentColor}
  .mic-btn.recording .mic-dot{animation:pulse 0.8s infinite}
  @keyframes micPulse{0%,100%{box-shadow:0 0 0 4px rgba(248,113,113,0.10)}50%{box-shadow:0 0 0 8px rgba(248,113,113,0.05)}}
  .mic-hint{font-family:var(--mono);font-size:9.5px;color:var(--muted);letter-spacing:.14em;text-transform:uppercase;padding:0 4px;text-align:center;line-height:1.4}
  .voice-toggle{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);cursor:pointer;padding:6px 10px;border:1px solid var(--border);border-radius:3px;background:#111}
  .voice-toggle input{accent-color:var(--accent)}
  .voice-toggle.on{color:var(--accent);border-color:var(--accent-dim)}
  .audio-indicator{display:inline-block;margin-left:8px;font-family:var(--mono);font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
  .audio-indicator.playing{color:var(--cyan)}
  .audio-indicator.playing::before{content:"♪ ";color:var(--cyan)}
</style>
</head>
<body>

<header>
  <div>
    <div class="brand">Cheers Beers <span class="accent">·</span> Trainer</div>
    <div class="meta" id="model-tag">loading model…</div>
  </div>
  <div class="controls">
    <select id="persona-select"></select>
    <button class="primary" id="start-btn">▸ Start Call</button>
    <button class="danger" id="hangup-btn" disabled>⏏ Hang Up &amp; Grade</button>
    <button id="reset-btn" disabled>↻ Reset</button>
  </div>
</header>

<main>
  <section class="panel">
    <div class="panel-h">
      <span><span class="live" id="call-status">Ready · pick a prospect</span></span>
      <span id="turn-count" style="font-family:var(--mono);font-size:10px;color:var(--muted)"></span>
    </div>
    <div class="chat" id="chat">
      <div class="empty">Pick a prospect on the right, then click Start Call.</div>
    </div>
    <div class="typing" id="typing" style="display:none"><span class="spinner"></span> <span id="typing-name">prospect</span> is thinking…<span class="audio-indicator" id="audio-indicator"></span></div>
    <div class="voice-bar">
      <button type="button" class="mic-btn" id="mic-btn" disabled aria-label="Hold to talk">
        <span class="mic-dot"></span>
        <span id="mic-label">Hold space (or click and hold) to talk</span>
      </button>
      <label class="voice-toggle on" id="voice-toggle-wrap"><input type="checkbox" id="voice-toggle" checked> AI voice</label>
    </div>
    <form class="compose" id="compose-form">
      <textarea id="user-input" placeholder="…or type if you'd rather not talk" disabled rows="2"></textarea>
      <button type="submit" class="primary" id="send-btn" disabled>Send</button>
    </form>
  </section>

  <aside class="panel">
    <div class="panel-h">Prospect · context</div>
    <div class="side" id="side">
      <div class="empty">Pick a persona on the top right.</div>
    </div>
  </aside>
</main>

<script>
// ── State ─────────────────────────────────────────────────────────
let personas = {};
let activeSlug = null;
let messages = [];  // { role, content }
let live = false;

const $ = id => document.getElementById(id);
const chatEl = $("chat"), sideEl = $("side"), inputEl = $("user-input");
const startBtn = $("start-btn"), hangBtn = $("hangup-btn"), resetBtn = $("reset-btn");
const sendBtn = $("send-btn"), select = $("persona-select");
const statusEl = $("call-status"), turnEl = $("turn-count"), typingEl = $("typing"), typingName = $("typing-name");

// ── Init ──────────────────────────────────────────────────────────
async function init() {
  const r = await fetch("/api/personas");
  const data = await r.json();
  personas = data.personas;
  $("model-tag").textContent = `model: ${data.model}`;
  for (const [slug, p] of Object.entries(personas)) {
    const o = document.createElement("option");
    o.value = slug;
    o.textContent = `${p.company} · ${p.zone}`;
    select.appendChild(o);
  }
  select.addEventListener("change", () => renderPersonaSidebar(select.value));

  // Honor URL params from the Sales Floor: ?persona=<slug>&autostart=1
  const params = new URLSearchParams(window.location.search);
  const wantSlug = params.get("persona");
  const wantStart = params.get("autostart") === "1";
  if (wantSlug && personas[wantSlug]) {
    select.value = wantSlug;
  }
  renderPersonaSidebar(select.value);
  if (wantStart) {
    // Slight delay so the page paints first.
    setTimeout(() => startCall(), 200);
  }
}

function renderPersonaSidebar(slug) {
  const p = personas[slug];
  if (!p) return;
  const zoneLc = (p.zone || "").toLowerCase();
  const zoneClass = zoneLc.includes("end") ? "end"
    : zoneLc.includes("channel") ? "channel"
    : zoneLc.includes("tool") ? "tool"
    : "boutique";
  sideEl.replaceChildren();
  const card = document.createElement("div");
  card.className = "persona-card";

  const who = document.createElement("div"); who.className = "who"; who.textContent = p.company; card.appendChild(who);
  const role = document.createElement("div"); role.className = "role"; role.textContent = p.role; card.appendChild(role);
  const zone = document.createElement("div"); zone.className = "zone " + zoneClass; zone.textContent = p.zone; card.appendChild(zone);
  const meta = document.createElement("div"); meta.className = "meta"; meta.textContent = `${p.hq} · ${p.size}`; card.appendChild(meta);
  const what = document.createElement("div"); what.className = "what"; what.textContent = p.what; card.appendChild(what);

  const rem = document.createElement("div"); rem.className = "reminder";
  const h = document.createElement("h4"); h.textContent = "Your goal on this call"; rem.appendChild(h);
  const pp = document.createElement("p");
  pp.textContent = "Book a 15-minute technical briefing — or get the name of the right tech lead. Do NOT pitch the $15K. Do NOT dump jargon. Pause one full second after \"I'll be quick.\" Energy: lawyer-calm.";
  rem.appendChild(pp);
  card.appendChild(rem);

  sideEl.appendChild(card);
}

// ── Chat helpers ──────────────────────────────────────────────────
function addMsg(role, content, klass) {
  const m = document.createElement("div");
  m.className = "msg " + (klass || role);
  const s = document.createElement("div"); s.className = "speaker";
  s.textContent = role === "user" ? "Dylan" : (role === "system" ? "system" : (personas[activeSlug]?.company || "prospect"));
  m.appendChild(s);
  const b = document.createElement("div"); b.className = "body"; b.textContent = content;
  m.appendChild(b);
  chatEl.appendChild(m);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function setLive(on) {
  live = on;
  inputEl.disabled = !on;
  sendBtn.disabled = !on;
  hangBtn.disabled = !on;
  startBtn.disabled = on;
  resetBtn.disabled = !on && messages.length === 0;
  select.disabled = on;
  if (on) inputEl.focus();
}

function updateTurn() {
  const userTurns = messages.filter(m => m.role === "user").length;
  turnEl.textContent = userTurns ? `${userTurns} turn${userTurns === 1 ? "" : "s"}` : "";
}

// ── Start / send / hangup ─────────────────────────────────────────
async function startCall() {
  activeSlug = select.value;
  messages = [];
  chatEl.replaceChildren();
  addMsg("system", `▸ Dialing ${personas[activeSlug].company} · ${personas[activeSlug].role}…`, "system");
  setLive(true);
  statusEl.textContent = `Live · ${personas[activeSlug].company}`;
  typingName.textContent = personas[activeSlug].company;
  await aiTurn(true);
}

async function aiTurn(opening) {
  typingEl.style.display = "block";
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: activeSlug, history: messages, opening: !!opening }),
    });
    if (!r.ok) throw new Error("chat failed");
    const data = await r.json();
    messages.push({ role: "assistant", content: data.reply });
    addMsg("assistant", data.reply, "persona");
    updateTurn();
  } catch (e) {
    addMsg("system", `× error: ${e.message}. Is Ollama running on :11434?`, "system");
  } finally {
    typingEl.style.display = "none";
  }
}

async function sendUser(text) {
  if (!text.trim()) return;
  messages.push({ role: "user", content: text });
  addMsg("user", text);
  updateTurn();
  inputEl.value = "";
  await aiTurn(false);
}

async function hangUp() {
  if (!messages.length) return;
  addMsg("system", "▸ Hanging up · sending transcript to the coach…", "system");
  setLive(false);
  statusEl.textContent = "Grading…";
  typingEl.style.display = "block";
  typingName.textContent = "coach";
  try {
    const r = await fetch("/api/score", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: activeSlug, history: messages }),
    });
    const data = await r.json();
    statusEl.textContent = "Call complete";
    renderScore(data.score, data.path);
  } catch (e) {
    addMsg("system", `× scoring error: ${e.message}`, "system");
  } finally {
    typingEl.style.display = "none";
  }
}

function renderScore(text, path) {
  sideEl.replaceChildren();
  const h = document.createElement("div");
  h.style.fontFamily = "var(--mono)";
  h.style.fontSize = "10px";
  h.style.letterSpacing = ".18em";
  h.style.textTransform = "uppercase";
  h.style.color = "var(--muted)";
  h.style.marginBottom = "6px";
  h.textContent = "Coach's feedback";
  sideEl.appendChild(h);

  const gradeMatch = text.match(/SCORE:\s*([A-F][+-]?)/i);
  if (gradeMatch) {
    const g = document.createElement("span");
    g.className = "score-grade";
    g.textContent = gradeMatch[1];
    sideEl.appendChild(g);
  }
  const sc = document.createElement("pre");
  sc.className = "score-card";
  sc.textContent = text;
  sideEl.appendChild(sc);

  if (path) {
    const note = document.createElement("p");
    note.style.fontSize = "11px";
    note.style.color = "var(--muted)";
    note.style.fontFamily = "var(--mono)";
    note.style.marginTop = "10px";
    note.textContent = "Saved: " + path;
    sideEl.appendChild(note);
  }
}

function resetChat() {
  messages = [];
  chatEl.replaceChildren();
  const empty = document.createElement("div");
  empty.className = "empty";
  empty.textContent = "Pick a prospect on the right, then click Start Call.";
  chatEl.appendChild(empty);
  setLive(false);
  statusEl.textContent = "Ready · pick a prospect";
  turnEl.textContent = "";
  renderPersonaSidebar(select.value);
}

// ──────────────────────────────────────────────────────────────────
// Voice — local STT (whisper.cpp via /api/transcribe) + TTS (say via
// /api/synthesize). Push-to-talk mic, auto-play AI replies.
// ──────────────────────────────────────────────────────────────────
const micBtn = $("mic-btn"), micLabel = $("mic-label");
const voiceToggle = $("voice-toggle"), voiceWrap = $("voice-toggle-wrap");
const audioIndicator = $("audio-indicator");

let audioCtx = null, mediaStream = null, sourceNode = null, processorNode = null;
let recordedSamples = [];  // Float32 chunks
let recording = false, lastAudio = null;

function aiVoiceEnabled() { return voiceToggle.checked; }
voiceToggle.addEventListener("change", () => {
  voiceWrap.classList.toggle("on", aiVoiceEnabled());
});

// Encode Float32 PCM samples → 16-bit mono WAV blob at the source rate.
function floatToWav(samples, sampleRate) {
  // Downsample to 16kHz for whisper (it's what the model expects).
  const targetRate = 16000;
  let down;
  if (sampleRate === targetRate) {
    down = samples;
  } else {
    const ratio = sampleRate / targetRate;
    const out = new Float32Array(Math.floor(samples.length / ratio));
    for (let i = 0; i < out.length; i++) out[i] = samples[Math.floor(i * ratio)];
    down = out;
  }
  const buffer = new ArrayBuffer(44 + down.length * 2);
  const view = new DataView(buffer);
  function writeStr(off, s) { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); }
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + down.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);             // PCM
  view.setUint16(22, 1, true);             // mono
  view.setUint32(24, targetRate, true);
  view.setUint32(28, targetRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, down.length * 2, true);
  let off = 44;
  for (let i = 0; i < down.length; i++) {
    const s = Math.max(-1, Math.min(1, down[i]));
    view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    off += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

async function startRecording() {
  if (recording || !live) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    addMsg("system", "× mic not available — falling back to text", "system");
    return;
  }
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") await audioCtx.resume();
    if (!mediaStream) {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    }
    recordedSamples = [];
    sourceNode = audioCtx.createMediaStreamSource(mediaStream);
    // ScriptProcessor is deprecated but ubiquitous; AudioWorklet would be nicer.
    processorNode = audioCtx.createScriptProcessor(4096, 1, 1);
    processorNode.onaudioprocess = (e) => {
      const ch = e.inputBuffer.getChannelData(0);
      recordedSamples.push(new Float32Array(ch));
    };
    sourceNode.connect(processorNode);
    processorNode.connect(audioCtx.destination);
    recording = true;
    micBtn.classList.add("recording");
    micLabel.textContent = "Recording — release to send";
  } catch (e) {
    addMsg("system", `× mic error: ${e.message}`, "system");
  }
}

async function stopRecording() {
  if (!recording) return;
  recording = false;
  micBtn.classList.remove("recording");
  micLabel.textContent = "Transcribing…";
  try {
    if (processorNode) { processorNode.disconnect(); processorNode.onaudioprocess = null; processorNode = null; }
    if (sourceNode) { sourceNode.disconnect(); sourceNode = null; }
  } catch (_) {}
  // Concat all chunks.
  let total = 0;
  for (const c of recordedSamples) total += c.length;
  const flat = new Float32Array(total);
  let off = 0;
  for (const c of recordedSamples) { flat.set(c, off); off += c.length; }
  recordedSamples = [];
  if (flat.length < 1600) {  // < 0.1s
    micLabel.textContent = "Too short — hold longer";
    setTimeout(() => { micLabel.textContent = "Hold space (or click and hold) to talk"; }, 1500);
    return;
  }
  const wav = floatToWav(flat, audioCtx.sampleRate);
  try {
    const r = await fetch("/api/transcribe", {
      method: "POST",
      headers: { "Content-Type": "audio/wav" },
      body: wav,
    });
    const data = await r.json();
    const text = (data.text || "").trim();
    micLabel.textContent = "Hold space (or click and hold) to talk";
    if (text) {
      await sendUser(text);
    } else {
      addMsg("system", "× nothing transcribed — try again", "system");
    }
  } catch (e) {
    micLabel.textContent = "Hold space (or click and hold) to talk";
    addMsg("system", `× transcription error: ${e.message}`, "system");
  }
}

// Play TTS for the AI reply.
async function speakReply(text) {
  if (!aiVoiceEnabled() || !text) return;
  audioIndicator.textContent = "speaking";
  audioIndicator.classList.add("playing");
  try {
    const r = await fetch("/api/synthesize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: activeSlug, text }),
    });
    if (!r.ok) throw new Error("synth failed");
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    if (lastAudio) { lastAudio.pause(); }
    const audio = new Audio(url);
    lastAudio = audio;
    audio.onended = () => { audioIndicator.textContent = ""; audioIndicator.classList.remove("playing"); URL.revokeObjectURL(url); };
    audio.onerror = () => { audioIndicator.textContent = ""; audioIndicator.classList.remove("playing"); };
    await audio.play();
  } catch (e) {
    audioIndicator.textContent = "";
    audioIndicator.classList.remove("playing");
    // Silent fallback — don't break the chat for a TTS error.
  }
}

// Wrap the existing aiTurn to auto-speak the reply.
const _aiTurn = aiTurn;
aiTurn = async function(opening) {
  await _aiTurn(opening);
  const last = messages[messages.length - 1];
  if (last && last.role === "assistant") {
    speakReply(last.content);
  }
};

// Wire mic button — hold-to-talk (mouse + keyboard).
micBtn.addEventListener("mousedown", e => { e.preventDefault(); startRecording(); });
micBtn.addEventListener("mouseup", e => { e.preventDefault(); stopRecording(); });
micBtn.addEventListener("mouseleave", () => { if (recording) stopRecording(); });
micBtn.addEventListener("touchstart", e => { e.preventDefault(); startRecording(); });
micBtn.addEventListener("touchend", e => { e.preventDefault(); stopRecording(); });

document.addEventListener("keydown", e => {
  if (e.code === "Space" && live && !recording && document.activeElement !== inputEl) {
    e.preventDefault();
    startRecording();
  }
});
document.addEventListener("keyup", e => {
  if (e.code === "Space" && recording) {
    e.preventDefault();
    stopRecording();
  }
});

// Tie mic enable/disable to call state.
const _setLive = setLive;
setLive = function(on) {
  _setLive(on);
  micBtn.disabled = !on;
};

// ── Events ────────────────────────────────────────────────────────
startBtn.addEventListener("click", startCall);
hangBtn.addEventListener("click", hangUp);
resetBtn.addEventListener("click", resetChat);
$("compose-form").addEventListener("submit", e => { e.preventDefault(); sendUser(inputEl.value); });
inputEl.addEventListener("keydown", e => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendUser(inputEl.value); }
});

init();
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _cors(self):
        # Allow the static floor (file:// or any localhost port) to hit us.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            body = HTML_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        # ── Org graph endpoints ──
        if self.path == "/api/organizations":
            if not _USE_ORG_GRAPH:
                self._send_json(503, {"error": "org loader unavailable"})
                return
            orgs = _load_orgs()
            self._send_json(200, {"organizations": orgs, "model": get_model()})
            return

        m = re.match(r"^/api/organizations/([a-z0-9\-]+)$", self.path)
        if m:
            if not _USE_ORG_GRAPH:
                self._send_json(503, {"error": "org loader unavailable"})
                return
            org = _load_org(m.group(1))
            if not org:
                self._send_json(404, {"error": "org not found"})
                return
            self._send_json(200, org)
            return

        if self.path == "/api/personas":
            if _USE_FILE_PERSONAS:
                _refresh_personas()
                slim = {}
                for slug, p in _runtime_personas.items():
                    slim[slug] = {
                        "company": p.company, "role": p.role, "hq": p.hq,
                        "size": p.size, "zone": p.zone, "what": p.what,
                        "tier": p.tier,
                        "tier_indicators": {
                            "speech_profile": bool(p.speech_profile),
                            "examples": len(p.examples),
                            "transcripts": len(p.transcripts),
                            "cloned_voice": bool(p.cloned_voice_path),
                        },
                    }
            else:
                slim = {
                    slug: {k: v for k, v in p.items() if k not in ("pushbacks", "personality")}
                    for slug, p in PERSONAS.items()
                }
            self._send_json(200, {"personas": slim, "model": get_model()})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""

        # /api/transcribe takes binary WAV — skip JSON parsing for that path.
        if self.path == "/api/transcribe":
            try:
                text = transcribe_wav(raw)
                self._send_json(200, {"text": text})
            except subprocess.CalledProcessError as e:
                self._send_json(500, {"error": "whisper failed", "stderr": e.stderr.decode(errors="ignore")[:400]})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # /api/upload-call also takes binary audio. Path: /api/upload-call?org=<slug>
        # Saves to organizations/<slug>/calls/<timestamp>/recording.wav and
        # optionally auto-runs the debrief.
        if self.path.startswith("/api/upload-call"):
            try:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                org_slug = (qs.get("org") or [None])[0]
                auto_debrief = (qs.get("debrief") or ["1"])[0] == "1"
                if not org_slug:
                    self._send_json(400, {"error": "missing ?org=<slug>"})
                    return
                org_dir = _REPO / "organizations" / org_slug
                if not org_dir.exists():
                    self._send_json(404, {"error": f"org not found: {org_slug}"})
                    return
                call_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                call_dir = org_dir / "calls" / call_id
                call_dir.mkdir(parents=True, exist_ok=True)
                (call_dir / "recording.wav").write_bytes(raw)
                result = {"org": org_slug, "call_id": call_id, "bytes": len(raw)}
                if auto_debrief:
                    try:
                        from debrief import debrief_call
                        d = debrief_call(org_slug, call_id)
                        result["debrief"] = {
                            "deal_signal": d.get("deal_signal"),
                            "created_people": d.get("created_people"),
                        }
                    except Exception as e:
                        result["debrief_error"] = str(e)
                self._send_json(200, result)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # Everything else is JSON.
        try:
            req = json.loads(raw) if raw else {}
        except Exception:
            self._send_json(400, {"error": "bad json"})
            return

        if self.path == "/api/chat":
            slug = req.get("slug")
            history = req.get("history") or []
            opening = bool(req.get("opening"))
            _refresh_personas() if _USE_FILE_PERSONAS else None
            if slug not in PERSONAS and slug not in _runtime_personas:
                self._send_json(400, {"error": "unknown slug"})
                return
            sys_prompt = persona_system_prompt(slug)
            msgs = [{"role": "system", "content": sys_prompt}] + history
            if opening:
                msgs.append({
                    "role": "user",
                    "content": "[The phone is ringing. You just picked up. Answer in 1-4 words — \"Hello?\" or \"[Last name] speaking.\" Nothing else.]",
                })
            try:
                reply = ollama_chat(msgs)
                # Strip any leading stage directions if the model leaks them.
                reply = re.sub(r"^\s*\*[^*]+\*\s*", "", reply).strip()
                self._send_json(200, {"reply": reply})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path == "/api/synthesize":
            slug = req.get("slug", "")
            text = (req.get("text") or "").strip()
            if not text:
                self._send_json(400, {"error": "no text"})
                return
            try:
                wav = synthesize_wav(text, slug)
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav)))
                self._cors()
                self.end_headers()
                self.wfile.write(wav)
            except subprocess.CalledProcessError as e:
                self._send_json(500, {"error": "say/afconvert failed", "stderr": e.stderr.decode(errors="ignore")[:400]})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path == "/api/brief":
            try:
                from brief import generate_brief
                org_slug = req.get("org")
                person_slug = req.get("person")
                if not org_slug:
                    self._send_json(400, {"error": "missing org"})
                    return
                brief_md = generate_brief(org_slug, person_slug)
                self._send_json(200, {"brief": brief_md})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path == "/api/debrief":
            try:
                from debrief import debrief_call
                org_slug = req.get("org")
                call_id = req.get("call_id")
                if not org_slug or not call_id:
                    self._send_json(400, {"error": "missing org or call_id"})
                    return
                result = debrief_call(org_slug, call_id)
                self._send_json(200, result)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path == "/api/score":
            slug = req.get("slug")
            history = req.get("history") or []
            _refresh_personas() if _USE_FILE_PERSONAS else None
            if slug not in PERSONAS and slug not in _runtime_personas:
                self._send_json(400, {"error": "unknown slug"})
                return
            score_sys = scoring_system_prompt(slug)
            transcript = []
            if _USE_FILE_PERSONAS and slug in _runtime_personas:
                company = _runtime_personas[slug].company
            else:
                company = PERSONAS[slug]["company"]
            for m in history:
                speaker = "Dylan" if m["role"] == "user" else company
                transcript.append(f"{speaker}: {m['content']}")
            user_prompt = (
                "Here is the full transcript of Dylan's practice cold call. "
                "Grade it against the playbook. Use the exact output format described in your instructions.\n\n"
                "TRANSCRIPT:\n" + "\n".join(transcript)
            )
            msgs = [
                {"role": "system", "content": score_sys},
                {"role": "user", "content": user_prompt},
            ]
            try:
                score = ollama_chat(msgs, temperature=0.4)
                path = save_transcript(slug, history, score)
                self._send_json(200, {"score": score, "path": path})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        self._send_json(404, {"error": "not found"})


class ReusableServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    model = get_model()
    print("─" * 60)
    print("  Cheers Beers · trainer + org graph + post-call debrief")
    print(f"  Model:   {model}")
    print(f"  Server:  http://localhost:{PORT}")
    print(f"  Logs:    {TRAINING_DIR}")
    print("─" * 60)
    with ReusableServer(("127.0.0.1", PORT), Handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nshutdown")


if __name__ == "__main__":
    main()
