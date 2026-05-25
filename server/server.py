#!/usr/bin/env python3
"""
BullpenLM — local trainer server
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

# BullpenLM uses two file stores: the legacy personas/ (still loaded if
# present, for back-compat) AND the new organizations/<slug>/ structure that
# is the canonical source going forward.
_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO))           # repo root → enables `from adapters.ingest import ...`
sys.path.insert(0, str(_REPO / "personas"))
sys.path.insert(0, str(_REPO / "server"))

try:
    from loader import load_all as _load_personas, build_persona_prompt as _build_persona_prompt, build_scoring_prompt as _build_scoring_prompt, load_library as _load_library, load_library_index as _load_library_index, load_orgs_as_personas as _load_orgs_as_personas
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
# Prefer small.en (4x more accurate than base.en, still real-time on M-series).
# Falls back to base.en if small.en isn't downloaded yet — keeps the install
# graceful on fresh checkouts.
_WHISPER_DIR = _REPO / "server" / "models"
WHISPER_MODEL = str(
    (_WHISPER_DIR / "ggml-small.en.bin") if (_WHISPER_DIR / "ggml-small.en.bin").exists()
    else (_WHISPER_DIR / "ggml-base.en.bin")
)
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
    """Reload personas from disk. Library personas (curated training scenarios)
    are merged in under a `library:` slug prefix so they share the same chat /
    score / synthesize pipeline as CRM-imported personas without name collisions."""
    global _runtime_personas
    if not _USE_FILE_PERSONAS:
        return
    merged = _load_personas()
    # Auto-bridge every org in organizations/ into a practiceable persona so
    # any CRM prospect can be roleplayed. Hand-curated personas in personas/
    # take precedence over the auto-generated ones (slug collision wins).
    for slug, persona in _load_orgs_as_personas().items():
        merged.setdefault(slug, persona)
    for slug, persona in _load_library().items():
        merged[f"library:{slug}"] = persona
    _runtime_personas = merged


DIFFICULTY_MODIFIERS = {
    "beginner": """
DIFFICULTY OVERRIDE — BEGINNER MODE
───────────────────────────────────
This rep is new to sales. Be warm, patient, and supportive. Surface objections
gently — phrase them as questions, not pushback. If the rep stumbles, give them
a moment to recover instead of pouncing. You're still in character, but you're a
generous-spirited version of this character. Reward good discovery questions
with substantive answers.
""",
    "intermediate": "",   # default — no modifier
    "advanced": """
DIFFICULTY OVERRIDE — ADVANCED MODE
───────────────────────────────────
This rep is experienced. Be skeptical, time-pressured, and harder to convince.
Press on weak claims. Interrupt monologues. Ask the hard follow-up questions a
real senior buyer would. Test composure — if the rep gets defensive or starts
apologizing, become more dismissive. Reserve genuine engagement for moments
when the rep demonstrates real competence.
""",
}


def persona_system_prompt(slug, difficulty: str = "intermediate"):
    """Build the system prompt that makes the model play the prospect.

    `difficulty` ∈ {beginner, intermediate, advanced} adjusts hostility/patience
    without changing the persona identity. Library personas already encode their
    own difficulty axis — the modifier still applies on top."""
    mod = DIFFICULTY_MODIFIERS.get(difficulty, "")
    if _USE_FILE_PERSONAS:
        _refresh_personas()
        if slug in _runtime_personas:
            base = _build_persona_prompt(_runtime_personas[slug])
            return base + ("\n" + mod if mod else "")
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

GO. The phone just rang. Pick up.""" + ("\n" + mod if mod else "")


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

# Whisper hallucinations on silent/short clips — the model was trained on
# YouTube subtitles, so it emits these strings when fed near-silent audio.
# Filtering them turns "you", "Thank you.", "Thanks for watching!" into "".
_WHISPER_HALLUCINATIONS = {
    "", ".", "you", "you.", "thank you", "thank you.",
    "thanks for watching", "thanks for watching.", "thanks for watching!",
    "thank you for watching", "thank you for watching.",
    "bye", "bye.", "bye!", "okay", "okay.",
    "[music]", "[silence]", "[noise]",
}


def transcribe_wav(wav_bytes: bytes) -> str:
    """Pipe WAV audio through whisper.cpp; return transcribed text.

    Hardened against whisper's well-known hallucinations on silent/short audio:
      1. Reject clips shorter than 0.4 sec (push-to-talk false triggers)
      2. Pass --no-speech-thold + --logprob-thold to make the model conservative
      3. Filter known hallucination outputs ("you", "Thank you.", etc.)
    """
    if not Path(WHISPER_MODEL).exists():
        raise RuntimeError(f"whisper model missing at {WHISPER_MODEL}")

    # Reject very short audio outright — whisper hallucinates worst on these.
    # WAV header is ~44 bytes; 16kHz mono 16-bit = 32000 bytes/sec. 0.4s = 12800 bytes.
    if len(wav_bytes) < 12000:
        return ""

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        in_path = f.name
    out_base = in_path[:-4]
    try:
        subprocess.run(
            [
                WHISPER_BIN, "-m", WHISPER_MODEL,
                in_path, "-nt", "-otxt", "-of", out_base,
                "-l", "en", "-t", "4",
                "--no-speech-thold", "0.6",   # default 0.6; bumps make it more conservative
                "--logprob-thold", "-0.8",    # reject low-confidence segments (default -1.0)
                "--temperature", "0",          # deterministic — no creative hallucination
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        txt_path = out_base + ".txt"
        if not Path(txt_path).exists():
            return ""
        text = Path(txt_path).read_text().strip()
        # Strip known hallucinations — case-insensitive match on the whole output
        if text.lower().strip(' .!?,"\'') in _WHISPER_HALLUCINATIONS:
            return ""
        return text
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

def save_transcript(slug, messages, score, metrics: dict | None = None, rep: str = "self"):
    """Save the practice-session markdown + a sibling metrics.json so the trend
    endpoint can chart improvement over time.

    `rep` attributes the call to a specific person — set per-request so multiple
    teammates calling through the same BullpenLM instance can each track their
    own metrics."""
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

    if metrics:
        metrics_path = path.with_suffix(".metrics.json")
        record = {
            "slug": slug,
            "date": today,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "company": p["company"],
            "role": p["role"],
            "rep": rep,
            "attempt": n,
            "transcript_path": str(path),
            **metrics,
        }
        metrics_path.write_text(json.dumps(record, indent=2) + "\n")

    return str(path)


# ──────────────────────────────────────────────────────────────────────────
# HTTP server
# ──────────────────────────────────────────────────────────────────────────
HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BullpenLM · Trainer</title>
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
    <div class="brand">BullpenLM <span class="accent">·</span> Trainer</div>
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
      <button type="button" class="mic-btn" id="mic-btn" disabled aria-label="Auto-listen status — click to force-send current utterance">
        <span class="mic-dot"></span>
        <span id="mic-label">Click Start Call — the mic listens automatically</span>
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
  const params = new URLSearchParams(window.location.search);
  const difficulty = params.get("difficulty") || "intermediate";
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: activeSlug, history: messages, opening: !!opening, difficulty }),
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
    const rep = new URLSearchParams(window.location.search).get("rep") || "self";
    const r = await fetch("/api/score", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: activeSlug, history: messages, rep }),
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
  // Legacy push-to-talk shim — kept so the manual mic button still works as a
  // "force-send what you have now" gesture. The continuous-VAD loop below is
  // the primary path during a live call.
  if (!recording) return;
  recording = false;
  micBtn.classList.remove("recording");
  await flushUtterance("manual");
}

/* ────────────────────────────────────────────────────────────────────
   Continuous VAD-driven mic. While a call is live, the mic listens the
   whole time. We detect speech via per-block RMS amplitude:
     · level > THRESHOLD                → start/extend an utterance
     · level < THRESHOLD for SILENCE_MS → cut utterance, send to whisper
   We pause listening while the AI is "speaking" (TTS playback) so the
   model doesn't transcribe its own voice as your turn.
   ────────────────────────────────────────────────────────────────── */

const VAD = {
  threshold: 0.012,        // RMS amplitude — tuned for mic noise floor on Mac mics
  silenceMs: 900,          // pause after speech before we send to whisper
  minSpeechMs: 350,        // utterance must contain this much above-threshold audio
  preRollSamples: 4096,    // keep ~90ms before speech kicks in (capture "uh-")
};
let vadState = "idle";     // idle | listening | recording | suspended
let silenceFrameCount = 0;
let speechFrameCount = 0;
let utteranceSamples = [];
let preRollBuffer = [];    // ring of recent pre-speech samples
let framesPerMs = 0;

async function startContinuousMic() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") await audioCtx.resume();
  if (!mediaStream) {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  }
  sourceNode = audioCtx.createMediaStreamSource(mediaStream);
  processorNode = audioCtx.createScriptProcessor(4096, 1, 1);
  framesPerMs = audioCtx.sampleRate / 1000;

  processorNode.onaudioprocess = (e) => {
    if (vadState === "idle" || vadState === "suspended") return;
    const ch = e.inputBuffer.getChannelData(0);
    // RMS amplitude
    let sum = 0;
    for (let i = 0; i < ch.length; i++) sum += ch[i] * ch[i];
    const rms = Math.sqrt(sum / ch.length);

    if (vadState === "listening") {
      // Ring-buffer the pre-roll so we capture the start of speech
      preRollBuffer.push(new Float32Array(ch));
      if (preRollBuffer.length > 3) preRollBuffer.shift();   // ~280ms of pre-roll at 44.1kHz

      if (rms > VAD.threshold) {
        vadState = "recording";
        utteranceSamples = preRollBuffer.slice();
        preRollBuffer = [];
        silenceFrameCount = 0;
        speechFrameCount = ch.length;
        micBtn.classList.add("recording");
        micLabel.textContent = "Listening…";
      }
    } else if (vadState === "recording") {
      utteranceSamples.push(new Float32Array(ch));
      if (rms > VAD.threshold) {
        speechFrameCount += ch.length;
        silenceFrameCount = 0;
      } else {
        silenceFrameCount += ch.length;
      }
      const silenceMs = silenceFrameCount / framesPerMs;
      const speechMs = speechFrameCount / framesPerMs;
      if (silenceMs >= VAD.silenceMs && speechMs >= VAD.minSpeechMs) {
        // End of utterance
        const samples = utteranceSamples;
        utteranceSamples = [];
        speechFrameCount = 0;
        silenceFrameCount = 0;
        vadState = "suspended";
        micBtn.classList.remove("recording");
        micLabel.textContent = "Transcribing…";
        cutAndSend(samples).catch(err => console.warn("VAD send error:", err));
      } else if (silenceMs >= VAD.silenceMs && speechMs < VAD.minSpeechMs) {
        // False trigger — went quiet too fast, discard
        utteranceSamples = [];
        speechFrameCount = 0;
        silenceFrameCount = 0;
        vadState = "listening";
        micBtn.classList.remove("recording");
        micLabel.textContent = "Listening — go ahead";
      }
    }
  };

  sourceNode.connect(processorNode);
  processorNode.connect(audioCtx.destination);
  vadState = "listening";
  micLabel.textContent = "Listening — go ahead";
}

function stopContinuousMic() {
  vadState = "idle";
  try {
    if (processorNode) { processorNode.disconnect(); processorNode.onaudioprocess = null; processorNode = null; }
    if (sourceNode) { sourceNode.disconnect(); sourceNode = null; }
  } catch (_) {}
  micBtn.classList.remove("recording");
  micLabel.textContent = "Call ended";
}

async function cutAndSend(samples) {
  let total = 0;
  for (const c of samples) total += c.length;
  if (total < audioCtx.sampleRate * 0.3) {  // < 300ms → likely noise
    if (vadState === "suspended") {
      vadState = "listening";
      micLabel.textContent = "Listening — go ahead";
    }
    return;
  }
  const flat = new Float32Array(total);
  let off = 0;
  for (const c of samples) { flat.set(c, off); off += c.length; }
  const wav = floatToWav(flat, audioCtx.sampleRate);
  try {
    const r = await fetch("/api/transcribe", {
      method: "POST",
      headers: { "Content-Type": "audio/wav" },
      body: wav,
    });
    const data = await r.json();
    const text = (data.text || "").trim();
    if (text) {
      await sendUser(text);   // sendUser → aiTurn → speakReply (which suspends mic)
    }
  } catch (e) {
    console.warn("transcribe error:", e);
  } finally {
    // If TTS playback didn't kick in (e.g. text was empty), resume listening
    if (vadState === "suspended" && (!lastAudio || lastAudio.paused || lastAudio.ended)) {
      vadState = "listening";
      micLabel.textContent = "Listening — go ahead";
    }
  }
}

async function flushUtterance(reason) {
  if (utteranceSamples.length === 0) return;
  const samples = utteranceSamples;
  utteranceSamples = [];
  speechFrameCount = 0;
  silenceFrameCount = 0;
  vadState = "suspended";
  await cutAndSend(samples);
}

// Play TTS for the AI reply.
async function speakReply(text) {
  if (!aiVoiceEnabled() || !text) {
    // Even without TTS, give the user a beat then resume listening
    if (vadState === "suspended") {
      vadState = "listening";
      micLabel.textContent = "Listening — go ahead";
    }
    return;
  }
  audioIndicator.textContent = "speaking";
  audioIndicator.classList.add("playing");
  // Mic is already suspended from cutAndSend; keep it suspended so we don't
  // transcribe the AI's own voice as the user's next turn.
  vadState = "suspended";
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
    const resumeMic = () => {
      audioIndicator.textContent = "";
      audioIndicator.classList.remove("playing");
      URL.revokeObjectURL(url);
      if (live && vadState === "suspended") {
        vadState = "listening";
        micLabel.textContent = "Listening — go ahead";
      }
    };
    audio.onended = resumeMic;
    audio.onerror = resumeMic;
    await audio.play();
  } catch (e) {
    audioIndicator.textContent = "";
    audioIndicator.classList.remove("playing");
    if (live && vadState === "suspended") {
      vadState = "listening";
      micLabel.textContent = "Listening — go ahead";
    }
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

// Mic button is now a status indicator + manual "force-send" button rather
// than push-to-talk. Clicking it during a paused/suspended state flushes
// whatever is buffered (useful for the "model didn't notice I finished" case).
micBtn.addEventListener("click", () => {
  if (!live) return;
  if (vadState === "recording") {
    flushUtterance("button").catch(_ => {});
  }
});

// Spacebar still works as a manual flush during a live call — useful if the
// VAD silence-detection is slow.
document.addEventListener("keydown", e => {
  if (e.code === "Space" && live && vadState === "recording" && document.activeElement !== inputEl) {
    e.preventDefault();
    flushUtterance("space").catch(_ => {});
  }
});

// Tie continuous VAD lifecycle to call state.
const _setLive = setLive;
setLive = async function(on) {
  _setLive(on);
  micBtn.disabled = !on;
  if (on) {
    try { await startContinuousMic(); }
    catch (e) { addMsg("system", `× mic error: ${e.message}`, "system"); }
  } else {
    stopContinuousMic();
  }
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


def _is_localhost(addr: tuple) -> bool:
    """Localhost connections bypass auth — the host is always trusted."""
    if not addr or not addr[0]:
        return False
    ip = addr[0]
    return ip in ("127.0.0.1", "::1", "localhost") or ip.startswith("127.")


# Endpoints that are public (no session required) even over the public tunnel.
_PUBLIC_PATHS = {
    "/api/invite/redeem",      # POST: redeem a code → set session cookie
    "/api/team/roster",        # GET: friend's /join page shows rep count
    "/api/health",             # for cloudflared liveness checks
}

# Regex patterns matched in addition to _PUBLIC_PATHS (for routes with
# variable bullpen slugs that should be reachable without auth).
_PUBLIC_PATH_PATTERNS = [
    re.compile(r"^/api/b/[a-z0-9\-]+/apply$"),         # POST a membership application
    re.compile(r"^/api/b/[a-z0-9\-]+/public(?:$|\?)"),  # GET public-facing bullpen info
    re.compile(r"^/api/bullpens$"),                     # POST: founder onboarding (create bullpen)
]


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

    def _current_rep(self) -> str | None:
        """Read the session cookie and return the rep name if valid."""
        cookie = self.headers.get("Cookie", "") or ""
        for part in cookie.split(";"):
            kv = part.strip().split("=", 1)
            if len(kv) == 2 and kv[0].strip() == "bullpen-session":
                try:
                    from invites import validate_session_cookie
                    from urllib.parse import unquote
                    return validate_session_cookie(unquote(kv[1].strip()))
                except Exception:
                    return None
        return None

    def _require_auth(self) -> bool:
        """Return True if this request should be allowed through. Localhost
        always allowed; public endpoints (invite redeem, roster) always allowed;
        everything else needs a valid session cookie."""
        # Path-based bypass — must match before cookie check
        from urllib.parse import urlparse
        path_only = urlparse(self.path).path
        if path_only in _PUBLIC_PATHS:
            return True
        for pat in _PUBLIC_PATH_PATTERNS:
            if pat.match(path_only):
                return True
        # Localhost bypass — host machine never needs auth
        if _is_localhost(self.client_address):
            return True
        # Cookie check
        return self._current_rep() is not None

    def _deny_auth(self):
        """Respond with a 401 + helpful pointer to /join."""
        body = json.dumps({"error": "auth_required",
                           "join_url": "/join.html"}).encode()
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("WWW-Authenticate", "BullpenInvite")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        # Gate: localhost + public-path bypass, otherwise need cookie
        if not self._require_auth():
            return self._deny_auth()

        # Lightweight health endpoint (public)
        if self.path == "/api/health":
            self._send_json(200, {"ok": True})
            return

        if self.path == "/" or self.path.startswith("/?"):
            body = HTML_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        # ── /join?code=XYZ shorthand → redirect to /app/join.html ──
        # Lets host URLs printed by `invites.py create` use a clean /join path.
        if self.path.startswith("/join"):
            q = ""
            if "?" in self.path:
                q = "?" + self.path.split("?", 1)[1]
            self.send_response(302)
            self.send_header("Location", "/app/join.html" + q)
            self._cors()
            self.end_headers()
            return

        # ── /b/<slug> public bullpen poster page → redirect to /app/bullpen.html
        # This is the URL founders share in #showcase. Closers land here, read
        # what the operator is moving, and click Apply (or skip straight to
        # /app/join.html if they were sent an invite code separately).
        m = re.match(r"^/b/([a-z0-9][a-z0-9\-]{1,38}[a-z0-9])(?:/|$|\?)", self.path)
        if m:
            slug = m.group(1)
            self.send_response(302)
            self.send_header("Location", f"/app/bullpen.html?b={slug}")
            self._cors()
            self.end_headers()
            return

        # ── Host tunnel status (PUBLIC — anyone can check if a host is live) ──
        if self.path == "/api/host/status":
            try:
                from tunnel import tunnel_status
                self._send_json(200, tunnel_status())
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── List invites (localhost-only) ──
        if self.path.startswith("/api/invites"):
            if not _is_localhost(self.client_address):
                return self._deny_auth()
            try:
                from invites import list_invites
                include_used = "include_used=true" in self.path
                self._send_json(200, {"invites": list_invites(include_used=include_used)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Stripe config status (localhost-only) ──
        if self.path == "/api/stripe/status":
            if not _is_localhost(self.client_address):
                return self._deny_auth()
            try:
                from stripe_client import is_configured, mode
                self._send_json(200, {"configured": is_configured(), "mode": mode()})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
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

        if self.path == "/api/crm/hubspot/status":
            try:
                from crm.hubspot import status
                self._send_json(200, status())
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path == "/api/crm/hubspot/connect":
            """Redirect to HubSpot OAuth. Caller's browser goes to HubSpot, approves,
            and is sent back to /api/crm/hubspot/callback with a `?code=...`."""
            try:
                from crm.hubspot import build_authorize_url
                url, err = build_authorize_url()
                if err:
                    self._send_json(400, {"error": err})
                    return
                self.send_response(302)
                self.send_header("Location", url)
                self._cors()
                self.end_headers()
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path.startswith("/api/crm/hubspot/callback"):
            """OAuth landing page — receives ?code=..., exchanges it for tokens,
            persists tokens to ~/.bullpenlm/hubspot-tokens.json, then shows a
            confirmation page so the user knows it worked."""
            try:
                from urllib.parse import urlparse, parse_qs
                from crm.hubspot import exchange_code
                qs = parse_qs(urlparse(self.path).query)
                code = (qs.get("code") or [None])[0]
                if not code:
                    self._send_json(400, {"error": "missing ?code= from HubSpot"})
                    return
                exchange_code(code)
                html = ("<!doctype html><html><body style='font-family:system-ui;background:#1a1208;color:#dcdcdc;padding:40px;text-align:center'>"
                        "<h2 style='color:#34d399'>HubSpot connected ✓</h2>"
                        "<p>Tokens saved. You can close this tab and run "
                        "<code style='background:#2a1d10;padding:4px 8px;border-radius:3px'>POST /api/crm/hubspot/sync</code> "
                        "to pull your CRM.</p></body></html>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self._cors()
                self.end_headers()
                self.wfile.write(html)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path.startswith("/api/metrics/history"):
            """Return chronological metrics records. Query params:
                 slug=<persona-slug>   restrict to one persona
                 rep=<name>            restrict to one rep (your calls vs friend's)
                 limit=<int>           cap result count (default 100)
            """
            try:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                want_slug = (qs.get("slug") or [None])[0]
                want_rep = (qs.get("rep") or [None])[0]
                limit = int((qs.get("limit") or ["100"])[0])
                records = []
                reps_seen = set()
                # Practice + speaking metrics
                for mf in sorted(TRAINING_DIR.glob("*.metrics.json")):
                    try:
                        rec = json.loads(mf.read_text())
                    except Exception:
                        continue
                    reps_seen.add(rec.get("rep", "self"))
                    if want_slug and rec.get("slug") != want_slug: continue
                    if want_rep and rec.get("rep") != want_rep: continue
                    records.append(rec)
                # Real recorded calls — pull metrics from each call dir + the
                # org/metadata for rep + slug attribution.
                orgs_dir = _REPO / "organizations"
                if orgs_dir.exists():
                    for call_metrics in orgs_dir.glob("*/calls/*/metrics.json"):
                        try:
                            mdata = json.loads(call_metrics.read_text())
                            meta_path = call_metrics.parent / "metadata.json"
                            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
                        except Exception:
                            continue
                        rec = {
                            "slug": meta.get("org") or call_metrics.parent.parent.parent.name,
                            "kind": "real-call",
                            "call_id": meta.get("call_id") or call_metrics.parent.name,
                            "date": meta.get("date"),
                            "timestamp": meta.get("call_id", ""),  # call_id IS the timestamp
                            "company": meta.get("org"),
                            "role": "(real call)",
                            "rep": meta.get("rep", "self"),
                            **mdata,
                        }
                        reps_seen.add(rec["rep"])
                        if want_slug and rec["slug"] != want_slug: continue
                        if want_rep and rec["rep"] != want_rep: continue
                        records.append(rec)
                records.sort(key=lambda r: r.get("timestamp", ""))
                self._send_json(200, {
                    "records": records[-limit:],
                    "count": len(records),
                    "reps_seen": sorted(reps_seen),
                })
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Team layer endpoints (multi-rep coordination) ──
        # ── Bullpens (multi-tenant) — list, get, members ──
        if self.path == "/api/bullpens":
            try:
                from bullpens import list_bullpens
                self._send_json(200, {"bullpens": list_bullpens()})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/bullpens/([a-z0-9\-]+)$", self.path)
        if m:
            try:
                from bullpens import get_bullpen, list_members
                b = get_bullpen(m.group(1))
                if not b:
                    self._send_json(404, {"error": "bullpen_not_found"}); return
                b["members"] = list_members(m.group(1))
                self._send_json(200, b)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Pipeline + Deals ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/pipeline(?:/([a-z0-9\-]+))?$", self.path)
        if m:
            try:
                from pipeline import get as get_pipeline, list_pipelines
                bullpen, name = m.group(1), m.group(2)
                if name:
                    p = get_pipeline(bullpen, name)
                    if not p: self._send_json(404, {"error": "pipeline_not_found"}); return
                    self._send_json(200, p)
                else:
                    self._send_json(200, {"pipelines": list_pipelines(bullpen)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/deals(?:$|\?)", self.path)
        if m:
            try:
                from urllib.parse import urlparse, parse_qs
                from deals import list_all
                bullpen = m.group(1)
                qs = parse_qs(urlparse(self.path).query)
                owner = (qs.get("rep") or [None])[0]
                self._send_json(200, {"deals": list_all(bullpen, owner_rep=owner)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/forecast(?:$|\?)", self.path)
        if m:
            try:
                from urllib.parse import urlparse, parse_qs
                from deals import forecast
                bullpen = m.group(1)
                qs = parse_qs(urlparse(self.path).query)
                owner = (qs.get("rep") or [None])[0]
                self._send_json(200, forecast(bullpen, owner_rep=owner))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── XP / Levels ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/xp(?:/([a-z0-9_\-\.]+))?(?:$|\?)", self.path)
        if m:
            try:
                from xp import get as xp_get
                bullpen, rep = m.group(1), m.group(2)
                self._send_json(200, xp_get(bullpen, rep))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Achievements: catalog + per-rep awards + force evaluate ──
        if self.path == "/api/achievements/catalog":
            try:
                from achievements import catalog
                self._send_json(200, {"catalog": catalog()})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/achievements/([a-z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from achievements import awards_for
                bullpen, rep = m.group(1), m.group(2)
                self._send_json(200, {"awards": awards_for(bullpen, rep)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Classes catalog ──
        if self.path == "/api/classes":
            try:
                from classes import list_classes
                self._send_json(200, {"classes": list_classes()})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Quests: active list + per-rep progress ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/quests(?:$|\?)", self.path)
        if m:
            try:
                from urllib.parse import urlparse, parse_qs
                from quests import list_active, progress
                bullpen = m.group(1)
                qs = parse_qs(urlparse(self.path).query)
                rep = (qs.get("rep") or [None])[0]
                if rep:
                    self._send_json(200, progress(bullpen, rep))
                else:
                    self._send_json(200, list_active(bullpen))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Member profile ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/members/([a-z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from bullpens import get_member, write_member
                from xp import get as xp_get
                from achievements import awards_for
                bullpen, rep = m.group(1), m.group(2)
                member = get_member(bullpen, rep) or write_member(bullpen, rep)
                xp_data = xp_get(bullpen, rep)
                awards = awards_for(bullpen, rep)
                self._send_json(200, {
                    "member": member,
                    "xp": xp_data,
                    "achievements": awards,
                })
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/audit(?:$|\?)", self.path)
        if m:
            try:
                from urllib.parse import urlparse, parse_qs
                from audit import tail, verify
                bullpen = m.group(1)
                qs = parse_qs(urlparse(self.path).query)
                limit = int((qs.get("limit") or ["100"])[0])
                ok, broken_at = verify(bullpen)
                self._send_json(200, {"events": tail(bullpen, n=limit),
                                       "chain_ok": ok, "broken_at": broken_at})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Legal docs ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/legal(?:$|\?)", self.path)
        if m:
            try:
                from legal import list_docs
                self._send_json(200, {"docs": list_docs(m.group(1))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/legal/([a-z0-9_\-]+)(?:$|\?)", self.path)
        if m:
            try:
                from legal import get_doc
                doc = get_doc(m.group(1), m.group(2))
                if not doc:
                    self._send_json(404, {"error": "doc_not_found"}); return
                self._send_json(200, doc)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/signatures/([a-z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from legal import get_signatures
                self._send_json(200, {"signatures": get_signatures(m.group(1), m.group(2))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Commissions ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/commissions/([a-z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from commissions import list_for_rep
                self._send_json(200, {"statements": list_for_rep(m.group(1), m.group(2))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/commissions/([a-z0-9_\-\.]+)/(\d{4}-\d{2})(?:$|\?)", self.path)
        if m:
            try:
                from commissions import get as cget
                s = cget(m.group(1), m.group(2), m.group(3))
                if not s:
                    self._send_json(404, {"error": "no_statement_for_period"}); return
                self._send_json(200, s)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/commissions(?:$|\?)", self.path)
        if m:
            try:
                from commissions import list_all
                self._send_json(200, {"by_rep": list_all(m.group(1))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Trophies ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/trophies/([a-z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from trophies import for_rep
                self._send_json(200, {"trophies": for_rep(m.group(1), m.group(2))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Streaks ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/streaks/([a-z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from streaks import compute as streak_compute
                self._send_json(200, streak_compute(m.group(1), m.group(2)))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── PvP sprints + duels ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/pvp/sprints(?:$|\?)", self.path)
        if m:
            try:
                from urllib.parse import urlparse, parse_qs
                from pvp import list_sprints
                qs = parse_qs(urlparse(self.path).query)
                inc = (qs.get("include_expired") or ["false"])[0].lower() in ("1", "true", "yes")
                self._send_json(200, {"sprints": list_sprints(m.group(1), include_expired=inc),
                                       "score_kinds": __import__("pvp").SCORE_KINDS})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/pvp/sprints/([a-zA-Z0-9_\-]+)(?:$|\?)", self.path)
        if m:
            try:
                from pvp import sprint_leaderboard
                self._send_json(200, sprint_leaderboard(m.group(1), m.group(2)))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/pvp/duels(?:$|\?)", self.path)
        if m:
            try:
                from urllib.parse import urlparse, parse_qs
                from pvp import list_duels
                qs = parse_qs(urlparse(self.path).query)
                rep = (qs.get("rep") or [None])[0]
                self._send_json(200, {"duels": list_duels(m.group(1), rep)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/pvp/duels/([a-zA-Z0-9_\-]+)/scores(?:$|\?)", self.path)
        if m:
            try:
                from pvp import duel_scores
                self._send_json(200, duel_scores(m.group(1), m.group(2)))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Presence roster (who's online) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/presence(?:$|\?)", self.path)
        if m:
            try:
                from presence import roster
                self._send_json(200, {"online": roster(m.group(1))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Squads ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/squads(?:$|\?)", self.path)
        if m:
            try:
                from parties import list_squads
                self._send_json(200, {"squads": list_squads(m.group(1))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Raid party state ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/raids/([a-zA-Z0-9_\-]+)(?:$|\?)", self.path)
        if m:
            try:
                from parties import raid_party_progress
                from pathlib import Path as _P
                bullpen, raid_id = m.group(1), m.group(2)
                rp = _P(__file__).parent.parent / "bullpens" / bullpen / "quests" / "raids" / f"{raid_id}.json"
                if not rp.exists():
                    self._send_json(404, {"error": "raid_not_found"}); return
                raid = json.loads(rp.read_text())
                prog = raid_party_progress(bullpen, raid_id, raid)
                self._send_json(200, {"raid": raid, "progress": prog})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Reaction counts for a set of events (POST-style body via ?ids=) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/reactions(?:$|\?)", self.path)
        if m:
            try:
                from urllib.parse import urlparse, parse_qs
                from reactions import counts_for_events
                qs = parse_qs(urlparse(self.path).query)
                ids = (qs.get("ids") or [""])[0].split(",")
                ids = [i for i in ids if i]
                self._send_json(200, {"counts": counts_for_events(m.group(1), ids)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Contacts ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/orgs/([a-z0-9\-]+)/contacts(?:$|\?)", self.path)
        if m:
            try:
                from contacts import list_for_org
                self._send_json(200, {"contacts": list_for_org(m.group(2))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/orgs/([a-z0-9\-]+)/contacts/([a-z0-9\-]+)(?:$|\?)", self.path)
        if m:
            try:
                from contacts import get as contact_get
                c = contact_get(m.group(2), m.group(3))
                if not c:
                    self._send_json(404, {"error": "contact_not_found"}); return
                self._send_json(200, c)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Activity timeline (per target) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/activity/(deal|contact|org)/([a-zA-Z0-9_\-\.\/]+)(?:$|\?)", self.path)
        if m:
            try:
                from activity import for_target
                self._send_json(200, {"activity": for_target(m.group(1), m.group(2), m.group(3))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # Convenience: full activity timeline rolled up for an org or deal
        m = re.match(r"^/api/b/([a-z0-9\-]+)/timeline/(org|deal|contact)/([a-zA-Z0-9_\-\.\/]+)(?:$|\?)", self.path)
        if m:
            try:
                from activity import for_org, for_deal, for_contact
                kind, key = m.group(2), m.group(3)
                if kind == "org":
                    self._send_json(200, {"activity": for_org(m.group(1), key)})
                elif kind == "deal":
                    self._send_json(200, {"activity": for_deal(m.group(1), key)})
                else:
                    org, slug = key.split("/", 1)
                    self._send_json(200, {"activity": for_contact(m.group(1), org, slug)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Follow-ups ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/followups/([a-z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from urllib.parse import urlparse, parse_qs
                from followups import list_for_rep as fu_list
                qs = parse_qs(urlparse(self.path).query)
                status = (qs.get("status") or [None])[0]
                due_before = (qs.get("due_before") or [None])[0]
                self._send_json(200, {"followups": fu_list(m.group(1), m.group(2),
                                                            status=status, due_before=due_before)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/followups-for/(deal|contact|org)/([a-zA-Z0-9_\-\.\/]+)(?:$|\?)", self.path)
        if m:
            try:
                from followups import for_target
                self._send_json(200, {"followups": for_target(m.group(1), m.group(2), m.group(3))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Public bullpen-facing info (for landing page, no auth) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/public(?:$|\?)", self.path)
        if m:
            try:
                from bullpens import get_bullpen
                cfg = get_bullpen(m.group(1))
                if not cfg:
                    self._send_json(404, {"error": "bullpen_not_found"}); return
                # Only expose the public-safe subset
                pub = {
                    "slug": cfg.get("slug"),
                    "name": cfg.get("name"),
                    "product": cfg.get("product"),
                    "tagline": cfg.get("tagline"),
                    "founder_rep": cfg.get("founder_rep"),
                    "founder_display_name": cfg.get("founder_display_name"),
                    "commission_rate": cfg.get("commission_rate"),
                    "seats_open": cfg.get("seats_open"),
                    "discord_invite": cfg.get("discord_invite"),
                    "access_mode": cfg.get("access_mode") or "invite_only",
                    "price_usd": cfg.get("price_usd"),
                    "public_url": cfg.get("public_url"),
                    "created_at": cfg.get("created_at"),
                }
                self._send_json(200, pub)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Applications ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/applications(?:$|\?)", self.path)
        if m:
            try:
                from urllib.parse import urlparse, parse_qs
                from applications import list_all
                qs = parse_qs(urlparse(self.path).query)
                status = (qs.get("status") or [None])[0]
                self._send_json(200, {"applications": list_all(m.group(1), status=status)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/applications/([a-zA-Z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from applications import get as app_get
                r = app_get(m.group(1), m.group(2))
                if not r:
                    self._send_json(404, {"error": "application_not_found"}); return
                self._send_json(200, r)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Onboarding state ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/onboarding/([a-z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from onboarding import get_state
                self._send_json(200, get_state(m.group(1), m.group(2)))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── TCS library ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/tcs(?:$|\?)", self.path)
        if m:
            try:
                from tcs import list_all
                self._send_json(200, {"tcs": list_all(m.group(1))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/tcs/([a-z0-9\-]+)(?:$|\?)", self.path)
        if m:
            try:
                from tcs import get as tcs_get
                t = tcs_get(m.group(1), m.group(2))
                if not t:
                    self._send_json(404, {"error": "tcs_not_found"}); return
                self._send_json(200, t)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Top Pack (rep's qualifications) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/toppack/([a-z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from tcs import top_pack, attempts_for_rep
                bullpen, rep = m.group(1), m.group(2)
                tp = top_pack(bullpen, rep)
                tp["attempts"] = attempts_for_rep(bullpen, rep)[:30]
                self._send_json(200, tp)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Spot checks ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/spotchecks(?:$|\?)", self.path)
        if m:
            try:
                from urllib.parse import urlparse, parse_qs
                from spotcheck import list_for_rep
                qs = parse_qs(urlparse(self.path).query)
                rep = (qs.get("rep") or [None])[0]
                status = (qs.get("status") or [None])[0]
                role = (qs.get("role") or ["any"])[0]
                if not rep:
                    self._send_json(400, {"error": "rep_required"}); return
                self._send_json(200, {"spotchecks": list_for_rep(m.group(1), rep,
                                                                  status=status, as_role=role)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/spotchecks/([a-zA-Z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from spotcheck import get as sc_get
                r = sc_get(m.group(1), m.group(2))
                if not r:
                    self._send_json(404, {"error": "spotcheck_not_found"}); return
                self._send_json(200, r)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Outbox (email drafts) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/outbox(?:$|\?)", self.path)
        if m:
            try:
                from urllib.parse import urlparse, parse_qs
                from outbox import list_all, queue_for_founder
                qs = parse_qs(urlparse(self.path).query)
                if (qs.get("scope") or [""])[0] == "queue":
                    self._send_json(200, {"drafts": queue_for_founder(m.group(1))})
                else:
                    self._send_json(200, {"drafts": list_all(m.group(1),
                                            status=(qs.get("status") or [None])[0],
                                            author_rep=(qs.get("author") or [None])[0])})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/outbox/([a-zA-Z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from outbox import get as outbox_get
                d = outbox_get(m.group(1), m.group(2))
                if not d:
                    self._send_json(404, {"error": "draft_not_found"}); return
                self._send_json(200, d)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Wallboard (composite, TV-mode) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/wallboard(?:$|\?)", self.path)
        if m:
            try:
                from wallboard import today_stats
                self._send_json(200, today_stats(m.group(1)))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Briefing (composite) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/briefing(?:$|\?)", self.path)
        if m:
            try:
                from briefing import for_bullpen
                self._send_json(200, for_bullpen(m.group(1)))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Today (composite) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/today/([a-z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from today import for_rep as today_for_rep
                self._send_json(200, today_for_rep(m.group(1), m.group(2)))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Single deal (with stage history etc.) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/deals/([a-zA-Z0-9_\-]+)(?:$|\?)", self.path)
        if m:
            try:
                from deals import get as deal_get
                d = deal_get(m.group(1), m.group(2))
                if not d:
                    self._send_json(404, {"error": "deal_not_found"}); return
                self._send_json(200, d)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Buyer cards ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/cards(?:$|\?)", self.path)
        if m:
            try:
                from buyer_cards import list_available
                self._send_json(200, {"cards": list_available()})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/cards/([a-z0-9\-]+)(?:$|\?)", self.path)
        if m:
            try:
                from buyer_cards import generate as bc_generate
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                refresh = (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes")
                c = bc_generate(m.group(2), bullpen=m.group(1), force_refresh=refresh)
                if not c:
                    self._send_json(404, {"error": "card_not_found"}); return
                self._send_json(200, c)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Duos ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/duos(?:$|\?)", self.path)
        if m:
            try:
                from urllib.parse import urlparse, parse_qs
                from duos import list_for_rep
                qs = parse_qs(urlparse(self.path).query)
                rep    = (qs.get("rep") or [None])[0]
                status = (qs.get("status") or [None])[0]
                self._send_json(200, {"duos": list_for_rep(m.group(1), rep, status)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/duos/([a-zA-Z0-9_\-\.]+)(?:$|\?)", self.path)
        if m:
            try:
                from duos import get as duo_get
                d = duo_get(m.group(1), m.group(2))
                if not d:
                    self._send_json(404, {"error": "duo_not_found"}); return
                self._send_json(200, d)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/lobby(?:$|\?)", self.path)
        if m:
            try:
                from duos import lobby_state
                self._send_json(200, lobby_state(m.group(1)))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── SSE event stream (text/event-stream) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/stream(?:$|\?)", self.path)
        if m:
            try:
                from events import subscribe, unsubscribe
                from audit import tail as audit_tail
                bullpen = m.group(1)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache, no-transform")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")
                self._cors()
                self.end_headers()
                # Replay the last 20 events so a freshly-opened tab has context
                try:
                    for e in audit_tail(bullpen, n=20):
                        self.wfile.write(b"data: " + json.dumps(e, default=str).encode() + b"\n\n")
                    self.wfile.flush()
                except Exception:
                    pass
                q = subscribe(bullpen)
                try:
                    while True:
                        try:
                            payload = q.get(timeout=15)
                            self.wfile.write(b"data: " + payload.encode() + b"\n\n")
                        except Exception:
                            # 15s idle → send a comment as keepalive
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    unsubscribe(bullpen, q)
            except Exception:
                # Headers already sent — just close
                try: self.wfile.flush()
                except Exception: pass
            return

        # ── Live calls: list active for a bullpen (for the coach lobby) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/calls/active(?:$|\?)", self.path)
        if m:
            try:
                from calls import list_active_calls
                self._send_json(200, {"calls": list_active_calls(m.group(1))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Live calls: full session for one call (replay or refresh) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/call/([a-zA-Z0-9\-]+)$", self.path)
        if m:
            try:
                from calls import get_call
                d = get_call(m.group(1), m.group(2))
                if not d:
                    self._send_json(404, {"error": "call_not_found"}); return
                self._send_json(200, d)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path == "/api/team/roster":
            try:
                from team import get_roster
                self._send_json(200, {"reps": get_roster()})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path == "/api/team/leaderboard":
            try:
                from team import get_leaderboard
                self._send_json(200, {"leaderboard": get_leaderboard()})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path.startswith("/api/team/feed"):
            try:
                from urllib.parse import urlparse, parse_qs
                from team import get_activity_feed
                qs = parse_qs(urlparse(self.path).query)
                limit = int((qs.get("limit") or ["30"])[0])
                self._send_json(200, {"events": get_activity_feed(limit=limit)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path == "/api/team/claims":
            try:
                from team import list_all_claims
                self._send_json(200, {"claims": list_all_claims()})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/team/claim/([a-z0-9\-]+)$", self.path)
        if m:
            try:
                from team import get_claim
                self._send_json(200, {"claim": get_claim(m.group(1))})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path == "/api/library":
            try:
                idx = _load_library_index() if _USE_FILE_PERSONAS else {"tiers": {}, "personas": []}
                self._send_json(200, idx)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
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

        # ── Static fallback: serve /app/<page>.html from floor/app/ ──
        m = re.match(r"^/app/([a-z0-9_\-]+\.html)(?:$|\?)", self.path)
        if m:
            page = m.group(1)
            from pathlib import Path as _P
            f = _P(__file__).parent.parent / "floor" / "app" / page
            try:
                body = f.read_bytes()
            except Exception:
                self._send_json(404, {"error": "page not found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""

        # ── Invite redeem (public) — must come before auth gate ──
        if self.path == "/api/invite/redeem":
            try:
                from invites import redeem_invite, make_session_cookie
                req = json.loads(raw) if raw else {}
                result = redeem_invite(req.get("code", ""))
                if not result.get("ok"):
                    self._send_json(400, result)
                    return
                rep = result["rep"]
                cookie_val = make_session_cookie(rep)
                # Set-Cookie: 30-day expiry, HttpOnly, secure-if-https,
                # Lax SameSite so the cookie survives the redirect to /floor
                body = json.dumps({"ok": True, "rep": rep}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Set-Cookie",
                    f"bullpen-session={cookie_val}; Path=/; Max-Age={30*86400}; "
                    f"SameSite=Lax; HttpOnly")
                self._cors()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Invite create (localhost-only) ──
        if self.path == "/api/invite/create":
            if not _is_localhost(self.client_address):
                return self._deny_auth()
            try:
                from invites import create_invite, attach_stripe_session
                req = json.loads(raw) if raw else {}
                rep = (req.get("rep") or "").strip()
                if not rep:
                    self._send_json(400, {"error": "rep name required"})
                    return
                price_usd = float(req.get("price_usd") or 0)
                inv = create_invite(rep, note=req.get("note", ""), price_usd=price_usd)

                public_url = None
                try:
                    from tunnel import tunnel_status
                    st = tunnel_status()
                    if st.get("running") and st.get("url"):
                        public_url = st["url"]
                except Exception:
                    pass

                if price_usd > 0:
                    from stripe_client import (is_configured as stripe_ok,
                                                create_checkout_session)
                    if not stripe_ok():
                        self._send_json(400, {
                            "error": "stripe_not_configured",
                            "hint": "Save your Stripe key via POST /api/stripe/key first.",
                            "code": inv["code"],
                        })
                        return
                    if not public_url:
                        self._send_json(400, {
                            "error": "tunnel_required_for_paid_invites",
                            "hint": "Publish your floor first — POST /api/host/publish.",
                            "code": inv["code"],
                        })
                        return
                    success_url = (f"{public_url}/app/join.html?code={inv['code']}"
                                   f"&session_id={{CHECKOUT_SESSION_ID}}")
                    cancel_url = f"{public_url}/app/join.html?code={inv['code']}&payment=cancelled"
                    cs = create_checkout_session(
                        code=inv["code"],
                        price_usd=price_usd,
                        product_name=f"Bullpen access · {rep}",
                        success_url=success_url,
                        cancel_url=cancel_url,
                    )
                    if not cs.get("ok"):
                        self._send_json(502, {"error": cs.get("error", "stripe_session_failed"),
                                              "stripe": cs.get("stripe")})
                        return
                    attach_stripe_session(inv["code"], cs["id"], cs["url"])
                    inv["stripe_session_id"] = cs["id"]
                    inv["checkout_url"] = cs["url"]
                    inv["join_url"] = cs["url"]
                    inv["public_url"] = public_url
                else:
                    if public_url:
                        inv["join_url"] = f"{public_url}/app/join.html?code={inv['code']}"
                        inv["public_url"] = public_url

                self._send_json(200, inv)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Stripe: save the API key (localhost-only) ──
        if self.path == "/api/stripe/key":
            if not _is_localhost(self.client_address):
                return self._deny_auth()
            try:
                from stripe_client import save_config
                req = json.loads(raw) if raw else {}
                r = save_config(req.get("key", ""))
                self._send_json(200, r)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Stripe: verify a checkout session + mark invite paid (PUBLIC) ──
        # Called by /app/join.html after redirect-back from Stripe success_url.
        if self.path == "/api/invite/verify-payment":
            try:
                from stripe_client import retrieve_checkout_session
                from invites import get_invite, mark_paid
                req = json.loads(raw) if raw else {}
                code = (req.get("code") or "").strip().upper()
                session_id = (req.get("session_id") or "").strip()
                if not code or not session_id:
                    self._send_json(400, {"error": "code_and_session_id_required"}); return
                inv = get_invite(code)
                if not inv:
                    self._send_json(404, {"error": "invalid_code"}); return
                # Defense: session must match the one we attached when minting.
                if inv.get("stripe_session_id") and inv["stripe_session_id"] != session_id:
                    self._send_json(400, {"error": "session_mismatch"}); return
                cs = retrieve_checkout_session(session_id)
                if not cs.get("ok"):
                    self._send_json(502, cs); return
                if cs.get("payment_status") != "paid":
                    self._send_json(402, {"error": "payment_not_complete",
                                          "stripe_status": cs.get("payment_status")})
                    return
                # Cross-check that the session was for THIS code.
                meta = cs.get("metadata") or {}
                if (meta.get("bullpen_code") or cs.get("client_reference_id")) != code:
                    self._send_json(400, {"error": "code_session_mismatch"}); return
                mark_paid(code)
                self._send_json(200, {"ok": True, "code": code})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Host: publish / unpublish (localhost-only) ──
        # The founder spawns a Cloudflare Quick Tunnel so closers anywhere on
        # the internet can hit /app/join.html?code=... on their host.
        if self.path == "/api/host/publish":
            if not _is_localhost(self.client_address):
                return self._deny_auth()
            try:
                from tunnel import start_tunnel
                r = start_tunnel(port=PORT)
                self._send_json(200 if r.get("ok") else 500, r)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path == "/api/host/unpublish":
            if not _is_localhost(self.client_address):
                return self._deny_auth()
            try:
                from tunnel import stop_tunnel
                self._send_json(200, stop_tunnel())
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Founder onboarding — PUBLIC (no auth) ──
        # Anyone can spin up a new bullpen on the platform. This is the
        # entry point promised by the landing page and the #how-to-start
        # walkthrough in Discord. Self-serve by design.
        if self.path == "/api/bullpens":
            try:
                from bullpens import (create_bullpen, set_bullpen_config,
                                      set_profile, exists as _bp_exists)
                req2 = json.loads(raw) if raw else {}

                slug = (req2.get("slug") or "").strip().lower()
                founder_rep = (req2.get("founder_rep") or "").strip().lower()
                product = (req2.get("product") or "").strip()[:120]
                name = (req2.get("name") or "").strip()[:80] or None
                tagline = (req2.get("tagline") or "").strip()[:240]
                commission_rate = (req2.get("commission_rate") or "").strip()[:80]
                seats_open = req2.get("seats_open")
                access_mode = (req2.get("access_mode") or "invite_only").strip()
                price_usd = req2.get("price_usd")
                discord_invite = (req2.get("discord_invite") or "").strip()[:200]
                founder_display_name = (req2.get("founder_display_name") or "").strip()[:48]

                if not slug or not founder_rep:
                    self._send_json(400, {"error": "slug and founder_rep required"}); return
                if _bp_exists(slug):
                    self._send_json(409, {"error": "bullpen_slug_taken", "slug": slug}); return
                if access_mode not in {"public", "invite_only", "paid"}:
                    self._send_json(400, {"error": "invalid_access_mode"}); return
                if access_mode == "paid":
                    try:
                        price_usd = float(price_usd or 0)
                    except Exception:
                        self._send_json(400, {"error": "price_usd_required_for_paid"}); return
                    if price_usd <= 0:
                        self._send_json(400, {"error": "price_usd_must_be_positive"}); return
                else:
                    price_usd = None
                try:
                    seats_open_int = int(seats_open) if seats_open not in (None, "") else None
                except Exception:
                    seats_open_int = None

                manifest = create_bullpen(slug, founder_rep,
                                          product=product, name=name)
                updates = {
                    "tagline": tagline,
                    "access_mode": access_mode,
                    "commission_rate": commission_rate,
                    "founder_display_name": founder_display_name or founder_rep,
                }
                if seats_open_int is not None:
                    updates["seats_open"] = seats_open_int
                if price_usd is not None:
                    updates["price_usd"] = price_usd
                if discord_invite:
                    updates["discord_invite"] = discord_invite
                cfg = set_bullpen_config(slug, updates) or manifest

                if founder_display_name:
                    try:
                        set_profile(slug, founder_rep,
                                    display_name=founder_display_name,
                                    title="Founder")
                    except Exception:
                        pass

                # Fire the master #showcase auto-announce (no-op if the
                # ~/.bullpenlm/showcase-webhook.txt isn't configured on this host).
                try:
                    from discord import announce_new_bullpen
                    from tunnel import tunnel_status as _ts
                    st = _ts()
                    pub = st.get("url") if st.get("running") else None
                    announce_new_bullpen(cfg, public_url=pub)
                except Exception:
                    pass

                self._send_json(200, {
                    "ok": True,
                    "slug": slug,
                    "name": cfg.get("name") or slug,
                    "founder_rep": founder_rep,
                    "app_url": f"/app/today.html?b={slug}&rep={founder_rep}",
                    "share_url": f"/b/{slug}",
                    "config": cfg,
                })
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Live calls (auth required: only members of the bullpen) ──
        # NB: the chunk endpoint accepts raw opus/webm bytes (not JSON);
        # all other call endpoints take JSON. Routing first because the
        # generic auth gate below still applies.
        m = re.match(r"^/api/b/([a-z0-9\-]+)/call/start$", self.path)
        if m:
            if not self._require_auth():
                return self._deny_auth()
            try:
                from calls import start_call
                bullpen = m.group(1)
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                rec = start_call(bullpen, rep,
                                 prospect=req2.get("prospect", ""),
                                 deal_id=req2.get("deal_id", ""))
                self._send_json(200, rec)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/call/([a-zA-Z0-9\-]+)/chunk$", self.path)
        if m:
            if not self._require_auth():
                return self._deny_auth()
            try:
                from calls import transcribe_chunk, add_transcript_chunk
                bullpen, call_id = m.group(1), m.group(2)
                # raw body is the opus/webm blob from MediaRecorder
                r = transcribe_chunk(raw)
                if not r.get("ok"):
                    self._send_json(502, r); return
                if r.get("skipped"):
                    self._send_json(200, {"ok": True, "skipped": r["skipped"]}); return
                if not (r.get("text") or "").strip():
                    self._send_json(200, {"ok": True, "skipped": "empty_transcript"}); return
                add_transcript_chunk(bullpen, call_id, r["text"],
                                      chunk_seconds=r.get("chunk_seconds", 0))
                self._send_json(200, {"ok": True, "text": r["text"]})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/call/([a-zA-Z0-9\-]+)/coach$", self.path)
        if m:
            if not self._require_auth():
                return self._deny_auth()
            try:
                from calls import add_coach_message
                bullpen, call_id = m.group(1), m.group(2)
                req2 = json.loads(raw) if raw else {}
                coach = (req2.get("coach") or self._current_rep() or "anon").strip()
                r = add_coach_message(bullpen, call_id, coach,
                                       req2.get("message", ""))
                self._send_json(200 if r.get("ok") else 400, r)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/call/([a-zA-Z0-9\-]+)/end$", self.path)
        if m:
            if not self._require_auth():
                return self._deny_auth()
            try:
                from calls import end_call
                self._send_json(200, end_call(m.group(1), m.group(2)))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # Gate everything else
        if not self._require_auth():
            return self._deny_auth()

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

        # ── Class selection ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/members/([a-z0-9_\-\.]+)/class$", self.path)
        if m:
            try:
                from bullpens import get_member, write_member, _bullpen_dir as bd
                from classes import can_pick
                from xp import get as xp_get
                from audit import append as audit_append
                bullpen, rep = m.group(1), m.group(2)
                req2 = json.loads(raw) if raw else {}
                class_id = (req2.get("class") or "").strip()
                member = get_member(bullpen, rep) or write_member(bullpen, rep)
                # Sync the member's level from the live XP projection
                # (the stored level in members/<rep>.json can drift)
                live_level = xp_get(bullpen, rep).get("level", 1)
                member["level"] = live_level
                ok, reason = can_pick(member, class_id)
                if not ok:
                    self._send_json(400, {"error": reason, "current_level": live_level,
                                          "required": __import__("classes").CLASSES.get(class_id, {}).get("min_level")}); return
                member["class"] = class_id
                (bd(bullpen) / "members" / f"{rep}.json").write_text(
                    json.dumps(member, indent=2) + "\n")
                audit_append(bullpen, rep, "class_picked",
                             target_type="member", target_id=rep,
                             payload={"class": class_id})
                self._send_json(200, {"ok": True, "member": member})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Bullpen config patch (founder-only via localhost or auth) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/config$", self.path)
        if m:
            try:
                from bullpens import set_bullpen_config
                req2 = json.loads(raw) if raw else {}
                cfg = set_bullpen_config(m.group(1), req2)
                if cfg is None:
                    self._send_json(404, {"error": "bullpen_not_found"}); return
                self._send_json(200, cfg)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Membership application — PUBLIC (no auth) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/apply$", self.path)
        if m:
            try:
                from applications import submit
                from bullpens import get_bullpen
                req2 = json.loads(raw) if raw else {}
                # Don't accept applications when the bullpen is public/paid w/o gates
                cfg = get_bullpen(m.group(1)) or {}
                if cfg.get("access_mode") == "public":
                    self._send_json(400, {"error": "public_bullpen_no_application_needed"}); return
                rec = submit(
                    m.group(1),
                    name=req2.get("name") or "",
                    email=req2.get("email") or "",
                    discord_handle=req2.get("discord_handle") or "",
                    sales_experience=req2.get("sales_experience") or "",
                    why=req2.get("why") or "",
                    referred_by=req2.get("referred_by") or "",
                )
                # Expose only the safe subset back to the public submitter
                self._send_json(200, {"ok": True, "id": rec["id"],
                                      "status": rec["status"],
                                      "discord_invite": cfg.get("discord_invite")})
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Applications: approve / reject (founder) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/applications/([a-zA-Z0-9_\-\.]+)/(approve|reject)$", self.path)
        if m:
            try:
                from applications import approve as app_approve, reject as app_reject
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                bullpen, app_id, action = m.group(1), m.group(2), m.group(3)
                if action == "approve":
                    rec = app_approve(bullpen, app_id, founder=rep,
                                      rep_slug=req2.get("rep_slug"))
                else:
                    rec = app_reject(bullpen, app_id, founder=rep,
                                     reason=req2.get("reason") or "")
                self._send_json(200, rec)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Profile patch (display_name, avatar, title) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/members/([a-z0-9_\-\.]+)/profile$", self.path)
        if m:
            try:
                from bullpens import set_profile, write_member, get_member
                req2 = json.loads(raw) if raw else {}
                bullpen, rep = m.group(1), m.group(2)
                if not get_member(bullpen, rep):
                    write_member(bullpen, rep)
                rec = set_profile(bullpen, rep,
                                  display_name=req2.get("display_name"),
                                  avatar=req2.get("avatar"),
                                  title=req2.get("title"))
                if rec is None:
                    self._send_json(404, {"error": "member_not_found"}); return
                self._send_json(200, rec)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Onboarding: mark a step done ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/onboarding/([a-z0-9_\-\.]+)/step$", self.path)
        if m:
            try:
                from onboarding import mark_step_done
                req2 = json.loads(raw) if raw else {}
                step = (req2.get("step") or "").strip()
                rec = mark_step_done(m.group(1), m.group(2), step)
                self._send_json(200, rec)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Claim quest rewards ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/quests/claim$", self.path)
        if m:
            try:
                from quests import claim_rewards
                from xp import invalidate as xp_invalidate
                bullpen = m.group(1)
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or "").strip() or "self"
                claimed = claim_rewards(bullpen, rep)
                xp_invalidate(bullpen)
                self._send_json(200, {"claimed": claimed, "count": len(claimed)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Force re-evaluate achievements (manual trigger / cron) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/achievements/evaluate$", self.path)
        if m:
            try:
                from achievements import evaluate
                from xp import invalidate as xp_invalidate
                bullpen = m.group(1)
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or "").strip() or None
                new = evaluate(bullpen, rep)
                xp_invalidate(bullpen)
                self._send_json(200, {"new_awards": new, "count": len(new)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Create a raid quest (Strategist/Founder authored) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/quests/raid$", self.path)
        if m:
            try:
                from quests import create_raid
                bullpen = m.group(1)
                req2 = json.loads(raw) if raw else {}
                raid = create_raid(
                    bullpen,
                    authored_by=(req2.get("rep") or "self").strip(),
                    name=(req2.get("name") or "").strip(),
                    predicate=req2.get("predicate") or {},
                    xp_reward=int(req2.get("xp_reward") or 200),
                    expires_in_days=int(req2.get("expires_in_days") or 7),
                    party_size=int(req2.get("party_size") or 2),
                )
                self._send_json(200, raid)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Sign a legal doc ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/legal/([a-z0-9_\-]+)/sign$", self.path)
        if m:
            try:
                from legal import sign as legal_sign
                bullpen, doc = m.group(1), m.group(2)
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                typed = (req2.get("typed_name") or "").strip()
                if not typed:
                    self._send_json(400, {"error": "missing_typed_name"}); return
                sig = legal_sign(bullpen, rep, doc, typed)
                # XP from doc_signed event is automatically picked up by xp.py
                try:
                    from xp import invalidate as xp_invalidate
                    xp_invalidate(bullpen)
                except Exception: pass
                self._send_json(200, {"ok": True, "signature": sig})
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Generate (rebuild) a commission statement ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/commissions/([a-z0-9_\-\.]+)/(\d{4}-\d{2})/generate$", self.path)
        if m:
            try:
                from commissions import generate as cgen
                s = cgen(m.group(1), m.group(2), m.group(3))
                self._send_json(200, s)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Start a PvP sprint ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/pvp/sprints$", self.path)
        if m:
            try:
                from pvp import create_sprint
                req2 = json.loads(raw) if raw else {}
                s = create_sprint(
                    m.group(1),
                    authored_by=(req2.get("rep") or self._current_rep() or "self").strip(),
                    score_kind=(req2.get("score_kind") or "dials").strip(),
                    duration_hours=int(req2.get("duration_hours") or 1),
                    name=req2.get("name"),
                )
                self._send_json(200, s)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Challenge / accept a duel ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/pvp/duels$", self.path)
        if m:
            try:
                from pvp import create_duel
                req2 = json.loads(raw) if raw else {}
                d = create_duel(
                    m.group(1),
                    challenger=(req2.get("challenger") or self._current_rep() or "self").strip(),
                    opponent=(req2.get("opponent") or "").strip(),
                    score_kind=(req2.get("score_kind") or "dials").strip(),
                    duration_days=int(req2.get("duration_days") or 7),
                )
                self._send_json(200, d)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/pvp/duels/([a-zA-Z0-9_\-]+)/accept$", self.path)
        if m:
            try:
                from pvp import accept_duel
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                d = accept_duel(m.group(1), m.group(2), rep)
                self._send_json(200, d)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Backfill trophies for any past close-won that missed a roll ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/trophies/backfill$", self.path)
        if m:
            try:
                from trophies import backfill
                new = backfill(m.group(1))
                self._send_json(200, {"count": len(new), "new": new})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Presence heartbeat ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/presence/beat$", self.path)
        if m:
            try:
                from presence import beat
                req2 = json.loads(raw) if raw else {}
                rec = beat(m.group(1),
                           rep=(req2.get("rep") or self._current_rep() or "self").strip(),
                           page=req2.get("page"),
                           status=req2.get("status"),
                           color=req2.get("color"))
                self._send_json(200, rec)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Squads ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/squads$", self.path)
        if m:
            try:
                from parties import create_squad
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                s = create_squad(m.group(1),
                                 name=(req2.get("name") or "").strip(),
                                 founder=rep,
                                 members=req2.get("members") or [],
                                 color=req2.get("color"))
                # Squad XP bonus invalidates cached projections
                try: __import__("xp").invalidate(m.group(1))
                except Exception: pass
                self._send_json(200, s)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/squads/([a-z0-9_\-]+)/(join|leave)$", self.path)
        if m:
            try:
                from parties import join_squad, leave_squad
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                fn = join_squad if m.group(3) == "join" else leave_squad
                s = fn(m.group(1), m.group(2), rep)
                try: __import__("xp").invalidate(m.group(1))
                except Exception: pass
                self._send_json(200, s)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Raid party (join / leave / claim) ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/raids/([a-zA-Z0-9_\-]+)/(join|leave|claim)$", self.path)
        if m:
            try:
                from parties import join_raid, leave_raid, claim_raid_rewards
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                bullpen, raid_id, action = m.group(1), m.group(2), m.group(3)
                if action == "join":
                    self._send_json(200, join_raid(bullpen, raid_id, rep))
                elif action == "leave":
                    self._send_json(200, leave_raid(bullpen, raid_id, rep))
                else:
                    # Claim — need to load the raid file from quests
                    from pathlib import Path as _P
                    rp = _P(__file__).parent.parent / "bullpens" / bullpen / "quests" / "raids" / f"{raid_id}.json"
                    if not rp.exists():
                        self._send_json(404, {"error": "raid_not_found"}); return
                    raid = json.loads(rp.read_text())
                    claim = claim_raid_rewards(bullpen, raid_id, raid, rep)
                    if not claim:
                        self._send_json(400, {"error": "not_eligible_or_already_claimed"}); return
                    try: __import__("xp").invalidate(bullpen)
                    except Exception: pass
                    self._send_json(200, claim)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Spot checks: fire / respond / grade ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/spotchecks$", self.path)
        if m:
            try:
                from spotcheck import fire as sc_fire
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                rec = sc_fire(
                    m.group(1),
                    checker_rep=rep,
                    target_rep=(req2.get("target") or "").strip(),
                    tcs_id=(req2.get("tcs_id") or "").strip(),
                    seconds=req2.get("seconds"),
                    prompt_override=req2.get("prompt"),
                )
                self._send_json(200, rec)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/spotchecks/([a-zA-Z0-9_\-\.]+)/(respond|grade)$", self.path)
        if m:
            try:
                from spotcheck import respond as sc_respond, grade as sc_grade
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                bullpen, sc_id, action = m.group(1), m.group(2), m.group(3)
                if action == "respond":
                    rec = sc_respond(bullpen, sc_id, rep, req2.get("response") or "")
                else:
                    rec = sc_grade(bullpen, sc_id, grader_rep=rep,
                                   result=req2.get("result"),
                                   score=req2.get("score"),
                                   feedback=req2.get("feedback") or "")
                try: __import__("xp").invalidate(bullpen)
                except Exception: pass
                self._send_json(200, rec)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Outbox: create / submit / mark-sent / reject / update ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/outbox$", self.path)
        if m:
            try:
                from outbox import create as outbox_create
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                rec = outbox_create(
                    m.group(1), author_rep=rep,
                    to=req2.get("to") or "",
                    subject=req2.get("subject") or "",
                    body=req2.get("body") or "",
                    target_type=req2.get("target_type") or "none",
                    target_id=req2.get("target_id") or "",
                    contact_slug=req2.get("contact_slug"),
                    deal_id=req2.get("deal_id"),
                    org_slug=req2.get("org_slug"),
                    submit=bool(req2.get("submit")),
                )
                self._send_json(200, rec)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/outbox/([a-zA-Z0-9_\-\.]+)/(submit|sent|reject)$", self.path)
        if m:
            try:
                from outbox import submit as outbox_submit, mark_sent, reject
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                bullpen, did, action = m.group(1), m.group(2), m.group(3)
                if action == "submit":
                    rec = outbox_submit(bullpen, did, rep)
                elif action == "sent":
                    rec = mark_sent(bullpen, did, rep)
                    try: __import__("xp").invalidate(bullpen)
                    except Exception: pass
                else:
                    rec = reject(bullpen, did, rep, reason=req2.get("reason") or "")
                self._send_json(200, rec)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/outbox/([a-zA-Z0-9_\-\.]+)$", self.path)
        if m:
            try:
                from outbox import update as outbox_update
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                rec = outbox_update(m.group(1), m.group(2), req2, rep)
                if not rec:
                    self._send_json(404, {"error": "draft_not_found"}); return
                self._send_json(200, rec)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Contacts: create / update ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/orgs/([a-z0-9\-]+)/contacts$", self.path)
        if m:
            try:
                from contacts import create as contact_create
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                rec = contact_create(
                    m.group(1), m.group(2),
                    person_name=req2.get("person_name") or req2.get("name") or "",
                    role=req2.get("role") or "",
                    email=req2.get("email") or "",
                    phone=req2.get("phone") or "",
                    linkedin=req2.get("linkedin") or "",
                    bio=req2.get("bio") or "",
                    notes=req2.get("notes") or "",
                    tags=req2.get("tags") or [],
                    relationship=req2.get("relationship") or "contact",
                    created_by=rep,
                )
                self._send_json(200, rec)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/orgs/([a-z0-9\-]+)/contacts/([a-z0-9\-]+)$", self.path)
        if m:
            try:
                from contacts import update as contact_update
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                rec = contact_update(m.group(1), m.group(2), m.group(3),
                                     updates=req2.get("updates") or req2 or {}, actor=rep)
                if not rec:
                    self._send_json(404, {"error": "contact_not_found"}); return
                self._send_json(200, rec)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Activity logging ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/activity$", self.path)
        if m:
            try:
                from activity import log as activity_log
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                rec = activity_log(
                    m.group(1), actor=rep,
                    kind=(req2.get("kind") or "").strip(),
                    target_type=(req2.get("target_type") or "").strip(),
                    target_id=(req2.get("target_id") or "").strip(),
                    summary=req2.get("summary") or "",
                    notes=req2.get("notes") or "",
                    outcome=req2.get("outcome") or None,
                    direction=req2.get("direction") or "outbound",
                    duration_sec=req2.get("duration_sec"),
                    contact_slug=req2.get("contact_slug"),
                    deal_id=req2.get("deal_id"),
                    org_slug=req2.get("org_slug"),
                )
                self._send_json(200, rec)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Follow-ups: create / complete / snooze ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/followups$", self.path)
        if m:
            try:
                from followups import create as fu_create
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                rec = fu_create(
                    m.group(1), owner_rep=rep,
                    title=req2.get("title") or "",
                    due_at=req2.get("due_at"),
                    notes=req2.get("notes") or "",
                    target_type=(req2.get("target_type") or "none").strip(),
                    target_id=(req2.get("target_id") or "").strip(),
                )
                self._send_json(200, rec)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/followups/([a-z0-9_\-\.]+)/([a-z0-9_\-\.]+)/(complete|snooze)$", self.path)
        if m:
            try:
                from followups import complete as fu_complete, snooze as fu_snooze
                req2 = json.loads(raw) if raw else {}
                bullpen, rep, fu_id, action = m.group(1), m.group(2), m.group(3), m.group(4)
                if action == "complete":
                    rec = fu_complete(bullpen, rep, fu_id)
                    try: __import__("xp").invalidate(bullpen)
                    except Exception: pass
                else:
                    rec = fu_snooze(bullpen, rep, fu_id, req2.get("snooze_to") or "+1d")
                if not rec:
                    self._send_json(404, {"error": "followup_not_found"}); return
                self._send_json(200, rec)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Duos: create / accept / msg / end / lobby join+leave ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/duos$", self.path)
        if m:
            try:
                from duos import create as duo_create
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                duo = duo_create(
                    m.group(1),
                    challenger_rep=rep,
                    opponent_rep=(req2.get("opponent") or "").strip(),
                    prospect_slug=(req2.get("prospect_slug") or "").strip(),
                    challenger_role=(req2.get("role") or "seller").strip(),
                    duration_minutes=int(req2.get("duration_minutes") or 10),
                )
                self._send_json(200, duo)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/duos/([a-zA-Z0-9_\-\.]+)/accept$", self.path)
        if m:
            try:
                from duos import accept as duo_accept
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                self._send_json(200, duo_accept(m.group(1), m.group(2), rep))
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/duos/([a-zA-Z0-9_\-\.]+)/msg$", self.path)
        if m:
            try:
                from duos import msg as duo_msg
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                entry = duo_msg(m.group(1), m.group(2), rep, req2.get("text") or "")
                self._send_json(200, entry)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/duos/([a-zA-Z0-9_\-\.]+)/end$", self.path)
        if m:
            try:
                from duos import end as duo_end
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                self._send_json(200, duo_end(m.group(1), m.group(2), rep))
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/lobby/(join|leave)$", self.path)
        if m:
            try:
                from duos import lobby_join, lobby_leave
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                if m.group(2) == "join":
                    r = lobby_join(m.group(1), rep,
                                   role=(req2.get("role") or "seller").strip(),
                                   prospect_slug=(req2.get("prospect_slug") or "").strip() or None)
                else:
                    r = lobby_leave(m.group(1), rep)
                self._send_json(200, r)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── React to an event ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/react$", self.path)
        if m:
            try:
                from reactions import react
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or self._current_rep() or "self").strip()
                r = react(m.group(1),
                          event_id=(req2.get("event_id") or "").strip(),
                          rep=rep, emoji=(req2.get("emoji") or "").strip())
                self._send_json(200, r)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Deals POSTs — create, move-stage, update-amount ──
        m = re.match(r"^/api/b/([a-z0-9\-]+)/deals$", self.path)
        if m:
            try:
                from deals import create
                bullpen = m.group(1)
                req2 = json.loads(raw) if raw else {}
                prospect = (req2.get("prospect_slug") or "").strip()
                rep = (req2.get("owner_rep") or "").strip() or "self"
                if not prospect:
                    self._send_json(400, {"error": "prospect_slug required"}); return
                d = create(bullpen, prospect, rep,
                           amount=req2.get("amount", 0),
                           pipeline_name=req2.get("pipeline", "default"),
                           stage_id=req2.get("stage", "lead"),
                           source_call_id=req2.get("source_call_id"),
                           notes=req2.get("notes", ""))
                self._send_json(200, d)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/deals/([0-9\-a-z]+)/stage$", self.path)
        if m:
            try:
                from deals import move_stage
                bullpen, deal_id = m.group(1), m.group(2)
                req2 = json.loads(raw) if raw else {}
                new_stage = (req2.get("stage") or "").strip()
                rep = (req2.get("rep") or "").strip() or "self"
                if not new_stage:
                    self._send_json(400, {"error": "stage required"}); return
                self._send_json(200, move_stage(bullpen, deal_id, new_stage, rep))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        m = re.match(r"^/api/b/([a-z0-9\-]+)/deals/([0-9\-a-z]+)/amount$", self.path)
        if m:
            try:
                from deals import update_amount
                bullpen, deal_id = m.group(1), m.group(2)
                req2 = json.loads(raw) if raw else {}
                rep = (req2.get("rep") or "").strip() or "self"
                self._send_json(200, update_amount(bullpen, deal_id,
                                                    req2.get("amount", 0), rep))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # ── Team-layer POSTs: claim + release (parse JSON inline since this
        #    block runs before the shared `req = json.loads(raw)` line below) ──
        if self.path in ("/api/team/claim", "/api/team/release"):
            try:
                team_req = json.loads(raw) if raw else {}
                prospect = (team_req.get("prospect") or "").strip()
                rep = (team_req.get("rep") or "").strip() or "self"
                if not prospect:
                    self._send_json(400, {"error": "missing prospect slug"})
                    return
                if self.path == "/api/team/claim":
                    from team import claim as team_claim
                    self._send_json(200, team_claim(prospect, rep))
                else:
                    from team import release_claim
                    self._send_json(200, release_claim(prospect, by=rep))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path.startswith("/api/speaking/record"):
            """Speaking-only mode: take audio, transcribe via whisper, compute
            metrics (filler/hedge/question count, avg sentence length), persist
            into training-runs/ so the Trend view can chart it alongside calls.
            No persona involved — just the rep practicing how they speak."""
            try:
                from metrics import compute_text_metrics
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                label = (qs.get("label") or ["speaking"])[0]
                rep = (qs.get("rep") or ["self"])[0]
                if not raw:
                    self._send_json(400, {"error": "empty audio body"})
                    return
                transcript = transcribe_wav(raw)
                metrics = compute_text_metrics(transcript)
                today = datetime.date.today().isoformat()
                ts = datetime.datetime.now().isoformat(timespec="seconds")
                existing = list(TRAINING_DIR.glob(f"{today}-speaking-*.metrics.json"))
                n = len(existing) + 1
                metrics_path = TRAINING_DIR / f"{today}-speaking-attempt-{n}.metrics.json"
                record = {
                    "slug": "speaking",
                    "date": today,
                    "timestamp": ts,
                    "company": "Speaking practice",
                    "role": label,
                    "rep": rep,
                    "attempt": n,
                    "transcript": transcript,
                    **metrics,
                }
                metrics_path.write_text(json.dumps(record, indent=2) + "\n")
                self._send_json(200, {"transcript": transcript, "metrics": metrics, "path": str(metrics_path)})
            except subprocess.CalledProcessError as e:
                self._send_json(500, {"error": "whisper failed", "stderr": e.stderr.decode(errors="ignore")[:400]})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path == "/api/crm/hubspot/sync":
            """Pull contacts/companies/deals from HubSpot into the org graph.
            Tokens must already be saved (visit /api/crm/hubspot/connect first)."""
            try:
                from crm.hubspot import sync_to_org_graph
                result = sync_to_org_graph()
                self._send_json(200, result)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # /api/ingest — universal "drop anything" endpoint. Accepts:
        #   * Raw file bytes (with ?filename=<name> + Content-Type header) for
        #     CSV/PDF/EML/JSON/TXT/MD uploads from the drop-zone UI.
        #   * JSON body {"text": "..."} or {"url": "..."} for paste-box inputs.
        # Sniffs the input via adapters.ingest and routes to the right parser.
        if self.path.startswith("/api/ingest"):
            try:
                from urllib.parse import urlparse, parse_qs
                from adapters.ingest import ingest_anything
                qs = parse_qs(urlparse(self.path).query)
                filename = (qs.get("filename") or [None])[0]
                ctype = self.headers.get("Content-Type", "").lower()

                if ctype.startswith("application/json"):
                    payload = json.loads(raw) if raw else {}
                    if "url" in payload:
                        body = payload["url"].encode("utf-8")
                        sniff_name = None
                    elif "text" in payload:
                        body = payload["text"].encode("utf-8")
                        sniff_name = filename
                    else:
                        self._send_json(400, {"error": "JSON body must include 'url' or 'text'"})
                        return
                    result = ingest_anything(body, filename=sniff_name, mime=None)
                else:
                    result = ingest_anything(raw, filename=filename, mime=ctype)

                self._send_json(200, result)
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
                rep = (qs.get("rep") or ["self"])[0]
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
                (call_dir / "rep.txt").write_text(rep + "\n")
                result = {"org": org_slug, "call_id": call_id, "bytes": len(raw), "rep": rep}
                # Team: bump the claim's last-activity + log the event
                try:
                    from team import touch_claim, log_call
                    touch_claim(org_slug, rep)
                    log_call(rep=rep, prospect_slug=org_slug, kind="real")
                except Exception:
                    pass
                if auto_debrief:
                    try:
                        from debrief import debrief_call
                        d = debrief_call(org_slug, call_id)
                        result["debrief"] = {
                            "deal_signal": d.get("deal_signal"),
                            "created_people": d.get("created_people"),
                            "metrics": d.get("metrics"),
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
            difficulty = (req.get("difficulty") or "intermediate").lower()
            if difficulty not in DIFFICULTY_MODIFIERS:
                difficulty = "intermediate"
            _refresh_personas() if _USE_FILE_PERSONAS else None
            if slug not in PERSONAS and slug not in _runtime_personas:
                self._send_json(400, {"error": "unknown slug"})
                return
            sys_prompt = persona_system_prompt(slug, difficulty=difficulty)
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
                # Safety net: if Gemma slips out of character and starts pitching
                # as the rep ("Hi, my name's Dylan / Beers Labs / I'm calling
                # about..."), kick it back into character with a single in-role
                # acknowledgement instead of the broken line.
                low = reply.lower()
                rep_hijack = (
                    "my name's dylan" in low or "my name is dylan" in low
                    or "beers labs" in low or "i'm calling about" in low
                    or "i'm with beers" in low or "this is dylan" in low
                )
                if rep_hijack:
                    reply = "Hello? Sorry — what's this about?"
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
                from metrics import compute_metrics
                metrics = compute_metrics(history)
                rep = (req.get("rep") or "self").strip() or "self"
                score = ollama_chat(msgs, temperature=0.4)
                path = save_transcript(slug, history, score, metrics=metrics, rep=rep)
                # Team feed: every practice scoring is a team event
                try:
                    from team import log_call
                    log_call(rep=rep, prospect_slug=slug, kind="practice", metrics=metrics)
                except Exception:
                    pass
                self._send_json(200, {"score": score, "path": path, "metrics": metrics})
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
    print("  BullpenLM · trainer + org graph + post-call debrief")
    print(f"  Model:   {model}")
    print(f"  Server:  http://localhost:{PORT}")
    print(f"  Logs:    {TRAINING_DIR}")
    print("─" * 60)
    try:
        from discord_roles import start_background as _start_role_sync
        _start_role_sync()
    except Exception as _e:
        print(f"[discord_roles] not started: {_e}")
    with ReusableServer(("127.0.0.1", PORT), Handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nshutdown")


if __name__ == "__main__":
    main()
