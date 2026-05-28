"""
Pre-call brief generator.

Right before you dial, the system reads everything it knows about the org
(intel, prior calls, known people, deals, social signals, ABCs) and runs
an Ollama pass that returns a 1-pager focused on THIS specific next call:
  - who you're calling (named person if known, else the role)
  - what they care about
  - what you said last time + what they said
  - your 3-sentence opener
  - the 3 likely objections + your verbatim responses
  - what success looks like for THIS call

Called from /api/brief?org=<slug>[&person=<slug>].
"""
from __future__ import annotations
import json
import re
import urllib.request
from pathlib import Path

from paths import DATA_DIR as REPO
import sys
sys.path.insert(0, str(REPO / "server"))
from orgs import load_org


BRIEF_PROMPT = """You are a senior sales coach writing a one-page pre-call brief for a rep about to dial a specific prospect. Read the structured intel below and produce a tight, focused brief.

INTEL ABOUT THE ORGANIZATION:
{org_json}

KNOWN CONTACTS (people we've already discovered):
{people_json}

RECENT CALL HISTORY (most recent first):
{calls_json}

THE TARGET FOR THIS CALL:
{target}

Write the brief in this exact markdown structure. Be concrete, not generic. If we don't have data for a section, write "(no intel yet)" rather than padding.

# Pre-call brief · {company}

**Calling:** {target_short}
**Goal of THIS call:** [1 sentence — what specific outcome would mean success today]

## Why now
[2-3 sentences pulling from the company intel — what specific pain or signal makes this the right call. Be specific.]

## What we know about them
[3-5 bullets, mixing company-level and person-level intel if known]

## What they said last time
[If there are prior calls, summarize what was said. Otherwise: "First touch — no prior conversation."]

## Your opener (30 seconds, read aloud)
"[Verbatim opener — pull the ABC attention hook from intel, adapt to the specific person if known]"

## Top 3 objections to expect — with your verbatim responses

**1. They say:** "[likely objection 1]"
**You say:** "[verbatim response]"

**2. They say:** "[likely objection 2]"
**You say:** "[verbatim response]"

**3. They say:** "[likely objection 3]"
**You say:** "[verbatim response]"

## The close
[1-2 sentences — the exact ask that defines success on this call]

## Red flags to avoid
[2-3 bullets — what NOT to say to this specific prospect]
"""


def generate_brief(org_slug: str, person_slug: str = None) -> str:
    org = load_org(org_slug)
    if not org:
        raise RuntimeError(f"org not found: {org_slug}")

    target = None
    target_short = org.get("default_role", "the right contact at " + org["company"])
    if person_slug:
        for p in org.get("people", []):
            if p.get("slug") == person_slug:
                target = p
                target_short = f"{p.get('personName', p.get('slug'))} ({p.get('role', '?')})"
                break

    # Build compact JSON contexts — strip noise
    org_compact = {k: v for k, v in org.items()
                   if k in ("company", "hq", "zone", "what", "techStack",
                            "phone", "web", "dealsInFlight",
                            "decisionMakers", "alreadyUsing", "competition",
                            "digital", "bio", "abc_md")}
    people_compact = [
        {k: p.get(k) for k in ("slug", "personName", "role", "relationship",
                               "email", "discovered_from")}
        for p in (org.get("people") or [])
    ]
    calls_compact = []
    for c in (org.get("calls") or [])[:5]:
        calls_compact.append({
            "id": c.get("slug"),
            "date": c.get("date"),
            "summary": c.get("summary_preview"),
            "signal": c.get("deal_signal"),
        })

    prompt = BRIEF_PROMPT.format(
        org_json=json.dumps(org_compact, indent=2),
        people_json=json.dumps(people_compact, indent=2),
        calls_json=json.dumps(calls_compact, indent=2),
        target=json.dumps(target, indent=2) if target else "(no specific person — calling cold to find the right one)",
        company=org["company"],
        target_short=target_short,
    )

    body = json.dumps({
        "model": "gemma2:9b",
        "messages": [
            {"role": "system", "content": "You write concise, concrete sales briefs. No corporate fluff. No hedging language. Direct, actionable, verbatim where possible."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.5, "num_ctx": 16384},
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read())
    brief_md = data.get("message", {}).get("content", "").strip()
    # Strip ``` fences if the model added them
    brief_md = re.sub(r"^```(?:markdown)?\s*", "", brief_md)
    brief_md = re.sub(r"\s*```\s*$", "", brief_md)
    return brief_md


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("org_slug")
    ap.add_argument("--person", help="optional person slug to target the brief at")
    args = ap.parse_args()
    print(generate_brief(args.org_slug, args.person))
