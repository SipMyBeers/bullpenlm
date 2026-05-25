"""Seed the killsesh bullpen with the 7 TCS plays — one per Gauntlet phase.

Each play is a structured Task / Conditions / Standards / Performance
Steps card. Auto_grade_keywords are deliberate words/phrases the rep
SHOULD say to demonstrate they've internalized the play.

Run once: `python3 scripts/seed_killsesh_tcs.py`
Idempotent — overwriting is fine, attempt-log preserved.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "server"))
import tcs as _tcs

BULLPEN = "killsesh"

PLAYS = [
    {
        "id": "cold-open-bfsi",
        "name": "Cold-open a BFSI Managing Director",
        "phase_tier": 1,
        "task":
            "Open a cold call into a BFSI (banking / insurance / financial services) "
            "Managing Director on mainframe modernization, earn the next 30 seconds.",
        "conditions":
            "Gatekeeper is already cleared and the prospect just said hello. You have <30 sec to "
            "earn another 30. You know their org is currently engaged with a Big-4 SI on a "
            "12–24 month mainframe modernization. You have the cheat-card opener loaded. "
            "Compliance context applies (SOX/HIPAA/PCI).",
        "standards":
            "Land at least 2 of: identify yourself + company + reason for call in <8 seconds; "
            "name a peer-firm reference; mention the audit-trail / hash-chain proof point; "
            "ask for the next conversation (15–20 min) — OR cleanly disqualify within 90 sec.",
        "performance_steps": [
            "1. State name + company + WHY you're calling in one breath (<8 sec).",
            "2. Drop a peer-firm story or stat that puts you in their world.",
            "3. Probe for the current pain: \"are you running the field-mapping QA manually right now?\"",
            "4. If positive signal — ask for 15–20 min next conversation; pencil a time.",
            "5. If negative — disqualify cleanly, ask for a referral, end inside 90 sec.",
        ],
        "auto_grade_keywords": [
            "Beers Labs", "audit trail", "20 minutes",
            "peer firm", "mainframe", "field mapping",
        ],
        "auto_grade_min_hits": 3,
        "spot_check_prompt":
            "You're on the phone with the MD of Mainframe Modernization at a top-5 US bank. "
            "Gatekeeper cleared you. Marcus just picked up and said 'this is Marcus.' "
            "Type your opening — first 30 seconds, every word.",
        "spot_check_seconds": 90,
    },
    {
        "id": "leave-a-mark-voicemail",
        "name": "Leave a voicemail that gets a callback",
        "phase_tier": 2,
        "task":
            "Hit voicemail and leave a 25–35 second message that makes the prospect "
            "actually call back.",
        "conditions":
            "The prospect's voicemail just beeped. You have ~30 seconds before the prospect "
            "deletes it. You have their name and you know their org's vertical.",
        "standards":
            "Use the prospect's first name. State your name + company. Reference a peer "
            "or vertical-specific hook. State a clear ask (a 15-min conversation, specific "
            "day/time slot). End with a callback number repeated twice — slowly.",
        "performance_steps": [
            "1. Greet by first name. State your name + company in the first 5 sec.",
            "2. Drop one peer reference or stat that ties them to your world.",
            "3. Make a specific ask — date, time, length. Not 'when's good?'",
            "4. Repeat your callback number TWICE, slowly, at the end.",
            "5. Total length under 35 seconds.",
        ],
        "auto_grade_keywords": [
            "first name", "Beers Labs", "peer", "20 minutes",
            "callback", "thursday", "specific",
        ],
        "auto_grade_min_hits": 3,
        "spot_check_prompt":
            "You got Marcus Chen's voicemail. Type the EXACT message you'd leave, word for word.",
        "spot_check_seconds": 90,
    },
    {
        "id": "earn-the-room",
        "name": "Get past the BFSI gatekeeper",
        "phase_tier": 3,
        "task":
            "Get transferred to your target prospect by the executive assistant or "
            "front-desk gatekeeper without sounding like a vendor.",
        "conditions":
            "You're cold. The gatekeeper picks up. They ask 'and what is this regarding?' "
            "You have the prospect's full name, the org's name, and you know their vertical.",
        "standards":
            "Stay calm and conversational. Use the prospect's first name (signals you know them). "
            "Avoid 'I'd like to schedule a meeting' / 'I'm calling about'. Use a short "
            "behavioral pattern: confident, brief, reason that's specific not generic. "
            "Pass the gate OR get a direct extension or email.",
        "performance_steps": [
            "1. \"Hi, I need to reach Marcus please.\" — first name only, calm, no qualifiers.",
            "2. If asked: \"It's Dylan from Beers Labs — Marcus and I haven't spoken yet, I'm "
            "   reaching out about [specific peer-firm trigger].\"",
            "3. Do NOT pitch the gatekeeper. Do NOT sound rehearsed.",
            "4. If blocked: ask for the best email or extension; do NOT push.",
        ],
        "auto_grade_keywords": [
            "first name", "calm", "specific", "Beers Labs",
            "haven't spoken", "extension",
        ],
        "auto_grade_min_hits": 3,
        "spot_check_prompt":
            "Front desk picks up: 'Accenture, how can I help you?' Get past them to Marcus. "
            "Type the entire interaction — both your lines AND what you'd expect the gatekeeper "
            "to say back.",
        "spot_check_seconds": 120,
    },
    {
        "id": "hold-the-line-pre-demo",
        "name": "Pre-demo qualification call",
        "phase_tier": 4,
        "task":
            "Run a 10-minute qualification call before booking the actual product demo, "
            "so you don't waste anyone's time.",
        "conditions":
            "The prospect agreed to 'take a quick look' — you have 10 min. You need to "
            "confirm: budget, authority, need, timeline (BANT) AND that they're not a "
            "House Account, AND that you can map their environment to your demo flow.",
        "standards":
            "Ask 3+ qualifying questions explicitly. Confirm budget ballpark. Confirm "
            "decision process (who else is involved). Confirm timeline. Confirm technical "
            "fit (their mainframe stack matches your demo). Either book the demo OR "
            "graciously disqualify.",
        "performance_steps": [
            "1. Restate why you're talking — '20 minutes to see if there's a fit.'",
            "2. Ask about their current modernization engagement (current state).",
            "3. Ask who else is involved in evaluating tools like this (decision power).",
            "4. Ask what 'success' looks like 90 days from now (urgency).",
            "5. Ask what the budget conversation looks like (qualification).",
            "6. Book the demo OR refer them to a better-fit vendor.",
        ],
        "auto_grade_keywords": [
            "budget", "timeline", "who else", "decision",
            "current state", "success", "ballpark",
        ],
        "auto_grade_min_hits": 4,
        "spot_check_prompt":
            "Marcus took your 10-min qual call. Type the 5 questions you'd ask him, "
            "in order, and the order matters.",
        "spot_check_seconds": 180,
    },
    {
        "id": "corner-office-pricing",
        "name": "Pricing pushback handling",
        "phase_tier": 5,
        "task":
            "Handle the 'your pricing is too high' or 'send me a quote' pushback without "
            "discounting OR losing the deal.",
        "conditions":
            "Prospect has seen the demo, agrees there's value, but says 'I need to see "
            "pricing before I can move this forward' OR 'we already have $X budgeted'. "
            "You know your floor pricing. You know what 1 dropped field costs them.",
        "standards":
            "Anchor on outcome value, not vendor cost. Reframe the question: not 'what does "
            "it cost' but 'what does NOT having it cost'. Quote a specific peer-firm ROI "
            "data point. Don't discount. Offer pilot pricing if natural. Move to next step.",
        "performance_steps": [
            "1. Acknowledge the question — 'fair, let's talk about it.'",
            "2. Reframe — \"the better question is what one dropped field costs you in audit "
            "   findings 6 months out — north of $200K just on remediation cycles.\"",
            "3. Quote the peer-firm ROI specifically — name the firm if you can.",
            "4. Anchor your number, do NOT discount on the call.",
            "5. Offer a structured pilot — fixed scope, fixed timeline, fixed price.",
            "6. Move to next step — \"who else needs to be in the room for the pilot conversation?\"",
        ],
        "auto_grade_keywords": [
            "reframe", "ROI", "peer", "pilot", "audit findings",
            "dropped field", "anchor", "next step",
        ],
        "auto_grade_min_hits": 4,
        "spot_check_prompt":
            "Marcus says: 'Look, I like what you're showing. But I need a quote before we "
            "can take this further — your pricing came back high.' Type your response.",
        "spot_check_seconds": 120,
    },
    {
        "id": "clarity-test-pilot-close",
        "name": "Pilot-close conversation",
        "phase_tier": 6,
        "task":
            "Convert a warm prospect into a signed pilot agreement with a 14-day kickoff date.",
        "conditions":
            "Prospect has done a demo + qual call + pricing convo. You have the pilot "
            "scope and pricing approved on your side. You're on the call with the buyer "
            "AND (ideally) an additional decision-maker. The signed agreement is in their "
            "DocuSign queue.",
        "standards":
            "Confirm the scope verbally. Confirm the timeline (kickoff date inside 14 days). "
            "Confirm the price + payment terms. Ask for the signature TODAY. If they push "
            "back, isolate the one specific blocker, address it, and re-ask.",
        "performance_steps": [
            "1. Recap the pilot: 4 weeks, fixed scope, $X, pass/fail success criteria.",
            "2. Confirm the kickoff date — name a specific Monday.",
            "3. Confirm the signatory + email — \"the agreement's in your DocuSign queue.\"",
            "4. Ask for signature today. Silent. Wait through the pause.",
            "5. If pushback — isolate the blocker. Don't try to address the whole agreement.",
            "6. End the call with a signature OR a specific next-step date.",
        ],
        "auto_grade_keywords": [
            "fixed scope", "kickoff date", "DocuSign", "signature today",
            "specific", "pause", "isolate blocker",
        ],
        "auto_grade_min_hits": 4,
        "spot_check_prompt":
            "You're 8 minutes into the pilot-close call. Marcus seems to be on the fence. "
            "Type the next 90 seconds of your side of the conversation — verbatim.",
        "spot_check_seconds": 180,
    },
    {
        "id": "pass-the-torch-handoff",
        "name": "Hand a won account to the founder cleanly",
        "phase_tier": 7,
        "task":
            "Hand off a freshly-closed pilot account to the founder for kickoff without "
            "dropping anything — every contact, every promise, every objection on the record.",
        "conditions":
            "Pilot agreement signed. You have the deal in BullpenLM with stage 'won'. "
            "You have the contact records under organizations/<slug>/people/. Kickoff is "
            "in 7 days. The founder needs everything they need to lead the kickoff without "
            "looking confused.",
        "standards":
            "Complete activity log on the deal (every call, email, meeting, note). All "
            "contacts captured with role + email + phone. Every promise you made on the "
            "sales call documented as a note. One hand-off summary doc (1 page max) "
            "covering: who, what we sold, what we promised, what could go wrong.",
        "performance_steps": [
            "1. Open the deal page; verify every activity is logged with notes.",
            "2. Verify every contact has email + phone + role filled in.",
            "3. Write a note titled 'HANDOFF — what I promised:' listing every promise made.",
            "4. Write a note titled 'HANDOFF — risks:' listing anything that could go sideways.",
            "5. DM the founder; @mention them in a final activity log.",
            "6. Schedule a 15-min handoff call ≤48hr before kickoff.",
        ],
        "auto_grade_keywords": [
            "activity logged", "every contact", "promises", "risks",
            "handoff", "kickoff", "summary",
        ],
        "auto_grade_min_hits": 4,
        "spot_check_prompt":
            "Marcus just signed. Kickoff is in 6 days. Type the handoff doc to the founder — "
            "every section, what's IN each section.",
        "spot_check_seconds": 240,
    },
]


def main():
    print(f"Seeding {len(PLAYS)} TCS plays into bullpen '{BULLPEN}'...")
    for play in PLAYS:
        _tcs.write(BULLPEN, play)
        print(f"  ✓ P{play['phase_tier']} {play['id']:30} {play['name']}")
    print(f"\nDone. View them in /app/tcs.html?b={BULLPEN}")


if __name__ == "__main__":
    main()
