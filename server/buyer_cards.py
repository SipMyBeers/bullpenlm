"""Buyer cards — what the practice partner needs to roleplay a real
prospect convincingly during 1v1 practice.

A buyer card is generated from data we already have under
`organizations/<slug>/`:
  org.json        — company profile (role, vertical, size, regulatory)
  abc.md          — the seller's ABC playbook (we INVERT the C-close into
                    what the buyer would push back on)
  pushbacks.txt   — actual objections this persona has used; perfect for
                    "play this buyer" roleplay
  people/         — known contacts (we pick a representative one)
  digital.md      — public facts (funding, deals, news)

The output is intentionally small and reusable:

{
  "prospect_slug", "company", "role", "vertical", "hq",
  "persona": { "name", "tone", "decision_style" },
  "their_world": [...short paragraphs...],
  "their_motivations": [...what they actually care about...],
  "their_objections": [...verbatim or paraphrased pushbacks...],
  "their_red_flags": [...words/phrases that close the door...],
  "their_hot_buttons": [...words/phrases that open the door...],
  "what_closed_similar_deals": [...openers/closes that have worked...],
  "the_seller_must": [...goal of the call...],
}

Caching: bullpens/<slug>/buyer_cards/<prospect>.json so the seller doesn't
have to wait. Regeneration is a single fn call.
"""
from __future__ import annotations
import json
import re
import random
from pathlib import Path
from typing import Optional

from paths import DATA_DIR as REPO
ORGS_ROOT = REPO / "organizations"
BULLPENS_ROOT = REPO / "bullpens"

# Deterministic but varied buyer "names" so each card feels personal.
# Picked from public Fortune 500 director-level first names — neutral mix.
PERSONA_NAMES = [
    "Marcus Chen", "Priya Sharma", "David Okafor", "Jennifer Liu",
    "Rajesh Kumar", "Anna Petrov", "Michael O'Brien", "Yuki Tanaka",
    "Sofia Mendez", "James Whitfield", "Aisha Hassan", "Eli Goldberg",
    "Lara Park", "Tomás García", "Nadia Volkov",
]


def _bullpen_cards_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "buyer_cards"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_org(slug: str) -> Optional[dict]:
    p = ORGS_ROOT / slug / "org.json"
    if not p.exists():
        return None
    try: return json.loads(p.read_text())
    except Exception: return None


def _read_text(slug: str, filename: str) -> str:
    p = ORGS_ROOT / slug / filename
    if not p.exists():
        return ""
    try: return p.read_text(encoding="utf-8")
    except Exception: return ""


def _pushbacks(slug: str) -> list[str]:
    txt = _read_text(slug, "pushbacks.txt")
    return [line.strip() for line in txt.splitlines() if line.strip()][:10]


def _parse_abc(slug: str) -> dict:
    """Pull A/B/C blocks out of abc.md if present."""
    md = _read_text(slug, "abc.md")
    blocks = {"attention": "", "buyin": "", "close": ""}
    if not md:
        return blocks
    sections = re.split(r"##\s+([ABC])\s+[—-]+", md)
    # sections looks like ['preamble', 'A', '<body>', 'B', '<body>', 'C', '<body>']
    for i in range(1, len(sections) - 1, 2):
        label, body = sections[i].strip(), sections[i + 1].strip()
        # Drop the first line if it's just the section subhead ("Attention hook" etc.)
        lines = body.splitlines()
        if lines and len(lines[0]) < 60 and "\n" not in lines[0]:
            body = "\n".join(lines[1:]).strip()
        if label == "A": blocks["attention"] = body
        elif label == "B": blocks["buyin"]   = body
        elif label == "C": blocks["close"]   = body
    return blocks


def _persona_name(slug: str) -> str:
    """Deterministic per prospect so the same slug always yields the same name."""
    rng = random.Random(slug)
    return rng.choice(PERSONA_NAMES)


def _persona_tone(role: str) -> tuple[str, str]:
    """Heuristic tone + decision style from job title."""
    rl = (role or "").lower()
    if any(k in rl for k in ("ceo", "founder", "owner")):
        return ("Direct. Time-pressed. Wants to know the punchline in 30 seconds.",
                "Decides fast if convinced; ghosts immediately if not.")
    if any(k in rl for k in ("cfo", "controller", "finance")):
        return ("Skeptical. Asks for proof, not promises. Hates fluff.",
                "Needs ROI math + reference customers before saying maybe.")
    if any(k in rl for k in ("cto", "cio", "vp engineering", "architect")):
        return ("Curious about tech. Will pull you into the weeds if you let him.",
                "Decides on architecture fit + team capacity; budget is secondary.")
    if any(k in rl for k in ("md", "managing director", "partner", "principal")):
        return ("Cordial but guarded. Plays politics. Won't bite without internal champion.",
                "Won't move alone — needs a peer or junior to validate first.")
    if any(k in rl for k in ("director", "vp", "head of")):
        return ("Balances upward pressure with execution risk. Wants quick wins.",
                "Will green-light a pilot if it doesn't risk her quarter.")
    if any(k in rl for k in ("manager", "lead")):
        return ("Operationally focused. Cares about her team's day-to-day.",
                "Decides on workflow impact; loops in her boss for budget.")
    return ("Professional. Polite. Reads tone as much as content.",
            "Decides based on whether this feels like a fit, not just whether it works.")


def _motivations_from_what(what: str, vertical: str) -> list[str]:
    """Lift motivations out of free-text 'what they do' + vertical."""
    out = []
    w = (what or "").lower()
    v = (vertical or "").lower()
    if any(k in w for k in ("modernization", "legacy", "mainframe")):
        out.append("Stop being held hostage by 1970s mainframe code")
        out.append("Show their board they're 'AI-first' without breaking compliance")
    if any(k in v for k in ("bfsi", "bank", "insurance")):
        out.append("Pass the next regulator audit without a finding")
        out.append("Cut operational cost per customer — board metric")
    if "compliance" in w or "regulatory" in w:
        out.append("Avoid headlines about a breach or audit failure")
    if any(k in v for k in ("consulting", "services")):
        out.append("Margin per engagement — billable hours saved = margin gained")
    if not out:
        out = ["Hit their number this quarter",
               "Look like a hero internally for finding the answer",
               "Avoid being the person who picked the vendor that failed"]
    return out[:5]


def _red_flags(role: str, vertical: str) -> list[str]:
    base = [
        "'Trust me' without proof",
        "Vendor talking more than listening",
        "Pricing dance instead of straight numbers",
        "No reference customer in the same vertical",
    ]
    v = (vertical or "").lower()
    if any(k in v for k in ("bank", "insurance", "finance", "bfsi")):
        base.append("Anyone who says 'we'll figure out compliance later'")
    if "gov" in v or "federal" in v:
        base.append("Anyone who can't speak to FedRAMP / FISMA / ATO")
    return base[:6]


def _hot_buttons(motivations: list[str]) -> list[str]:
    # Hot buttons are linguistic — what unlocks the prospect's energy.
    out = []
    for m in motivations:
        m = m.lower()
        if "audit" in m or "compliance" in m or "regulator" in m:
            out.append("Audit-trail mention (\"every action is signed and hash-chained\")")
        if "cost" in m or "margin" in m or "billable" in m:
            out.append("Concrete $ saved per engagement / per account")
        if "ai" in m or "modern" in m:
            out.append("Reference to specific automation that compressed weeks → days")
        if "quarter" in m or "number" in m:
            out.append("\"You can pilot this in 14 days, no procurement, no PO\"")
    if not out:
        out = ["A real story about a customer in their situation",
               "Specific numbers, not adjectives"]
    # Dedupe while preserving order
    seen = set(); dedup = []
    for x in out:
        if x not in seen: seen.add(x); dedup.append(x)
    return dedup[:5]


def generate(prospect_slug: str, bullpen: str,
             force_refresh: bool = False) -> Optional[dict]:
    """Build (or load cached) buyer card for one prospect.

    `bullpen` is required — buyer cards are cached per-bullpen at
    bullpens/<slug>/buyer-cards/. There is no platform-wide default; the
    caller (a /api/b/<slug>/... route) always knows which floor it's on.
    """
    cache = _bullpen_cards_dir(bullpen) / f"{prospect_slug}.json"
    if cache.exists() and not force_refresh:
        try: return json.loads(cache.read_text())
        except Exception: pass

    org = _read_org(prospect_slug)
    if not org:
        return None

    role = org.get("default_role") or "Decision Maker"
    company = org.get("company") or prospect_slug
    vertical = org.get("vertical") or org.get("industry") or ""
    what = org.get("what") or ""
    tone, decision_style = _persona_tone(role)
    motivations = _motivations_from_what(what, vertical)
    abc = _parse_abc(prospect_slug)

    card = {
        "prospect_slug": prospect_slug,
        "company": company,
        "role": role,
        "vertical": vertical,
        "hq": org.get("hq") or "",
        "persona": {
            "name": _persona_name(prospect_slug),
            "tone": tone,
            "decision_style": decision_style,
        },
        "their_world": [
            what,
            "Regulatory context: " + (org.get("regulatory_context") or "n/a"),
        ],
        "their_motivations": motivations,
        "their_objections": _pushbacks(prospect_slug),
        "their_red_flags": _red_flags(role, vertical),
        "their_hot_buttons": _hot_buttons(motivations),
        "what_closed_similar_deals": [
            abc.get("attention", "").split("\n\n")[0] if abc.get("attention") else "",
            abc.get("buyin", "")[:200] if abc.get("buyin") else "",
        ],
        "the_seller_must": [
            abc.get("close", "").strip()[:200] if abc.get("close")
            else "Book the next conversation. Don't try to close the deal on this call.",
            "Use their words back to them — show you've done the homework.",
        ],
    }
    # Strip empties
    card["what_closed_similar_deals"] = [x for x in card["what_closed_similar_deals"] if x]
    card["their_world"] = [x for x in card["their_world"] if x and x != "Regulatory context: n/a"]

    cache.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n")
    return card


def list_available(limit: int = 200) -> list[dict]:
    """List every prospect we can build a card for (i.e. has org.json)."""
    out = []
    for f in sorted(ORGS_ROOT.glob("*/org.json"))[:limit]:
        try:
            o = json.loads(f.read_text())
            out.append({
                "slug": o.get("slug") or f.parent.name,
                "company": o.get("company") or f.parent.name,
                "vertical": o.get("vertical") or o.get("industry") or "",
                "role": o.get("default_role") or "",
            })
        except Exception:
            continue
    return out


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 server/buyer_cards.py <prospect-slug> [--refresh]")
        sys.exit(0)
    refresh = "--refresh" in sys.argv
    card = generate(sys.argv[1], force_refresh=refresh)
    if not card:
        print("not found"); sys.exit(1)
    print(json.dumps(card, indent=2, ensure_ascii=False))
