#!/usr/bin/env python3
"""Enrich an org with public info — turns a generic-CTO persona into a
deeply-grounded one that knows their tech stack, recent press, and stated
modernization priorities.

What it does:
  1. Reads organizations/<slug>/org.json for the company name + web domain
  2. Fetches the homepage + /about + /technology + /press (best-effort)
  3. Pulls bio, tech stack hints, and recent quotes via Gemma extraction
  4. Appends synthesized facts to organizations/<slug>/digital.md
  5. Optionally writes an `enriched_personality.md` that the persona bridge
     uses verbatim instead of the generic auto-synthesis

Usage:
  python3 scripts/enrich_org.py allstate
  python3 scripts/enrich_org.py allstate bank-of-america cigna capital-one
  python3 scripts/enrich_org.py --top10        # pre-baked top-10 KillSesh targets
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from adapters._common import _SSL, fetch_page, ollama_extract  # noqa: E402

ORGS_ROOT = REPO / "organizations"

# Curated default — the 10 most-strategic KillSesh targets from the COBOL corpus.
# These are the ones worth grounding deeply because you're calling them first.
TOP10 = [
    "allstate", "bank-of-america", "cigna", "capital-one",
    "bcbs-massachusetts", "centene", "citigroup", "elevance-health",
    "wellpoint-insurance", "humana",
]

# Big enterprises run consumer domains separate from corporate/investor domains.
# Corporate domains have the modernization-relevant content; consumer domains
# are SPAs that return blank HTML. Map known cases — override what's in org.json.
CORPORATE_DOMAIN_OVERRIDES = {
    "allstate":          "allstatecorporation.com",
    "bank-of-america":   "investor.bankofamerica.com",
    "cigna":             "thecignagroup.com",
    "capital-one":       "investor.capitalone.com",
    "centene":           "centene.com",
    "citigroup":         "citigroup.com",
    "elevance-health":   "elevancehealth.com",
    "humana":            "humana.com",
    "wellpoint-insurance": "elevancehealth.com",   # WellPoint rebranded to Elevance
    "bcbs-massachusetts": "bluecrossma.org",
}

# Pages worth fetching on most corporate sites. Order matters — try modernization-
# adjacent pages first since that's the highest-signal content for KillSesh outreach.
PAGE_CANDIDATES = [
    "/",
    "/technology",
    "/about",
    "/about-us",
    "/press",
    "/newsroom",
    "/news",
    "/innovation",
    "/digital-transformation",
    "/modernization",
    "/cobol",     # long shot, but if a vendor calls out COBOL on their site that's gold
    "/careers/technology",
]


ENRICHMENT_PROMPT = """\
You are reading public web content scraped from {company}'s corporate website.
Extract concrete, sourceable facts that would help a salesperson cold-calling
this company's VP of Application Modernization or CTO. Be specific. If a fact
isn't supported by the text, do not invent it.

Web content:
---
{text}
---

Return JSON with these fields. Use null for anything not supported.
"""

ENRICHMENT_SCHEMA = """\
{
  "summary": "2-3 sentence summary of what this company does (do not invent — only what the text says)",
  "tech_stack_signals": [
    "concrete technology mentioned in the text — e.g. 'IBM mainframe (z/OS) referenced in 2023 careers page'"
  ],
  "modernization_signals": [
    "any sign they're working on tech modernization — RFPs, partnerships, executive quotes, AWS/Azure announcements"
  ],
  "executive_quotes": [
    {"name": "name", "role": "title", "quote": "exact quote", "source": "page URL fragment"}
  ],
  "recent_initiatives": [
    "named tech initiative or product launch in the last 2 years, with year if stated"
  ],
  "openers": [
    "1-2 specific cold-call opening lines that reference one of the above facts — phrased as you'd actually say them on a call"
  ]
}
"""


def fetch_pages(domain: str) -> tuple[str, list[str]]:
    """Try each PAGE_CANDIDATES path on the domain. Return combined text and
    list of successfully-fetched URLs."""
    text_parts = []
    fetched = []
    base = domain if domain.startswith("http") else f"https://{domain}"
    base = base.rstrip("/")
    for path in PAGE_CANDIDATES:
        url = base + path
        try:
            content = fetch_page(url, timeout=10)
            if content and len(content) > 200:
                text_parts.append(f"\n\n=== {path} ===\n{content[:4000]}")
                fetched.append(url)
                time.sleep(0.5)  # polite rate limit
        except Exception:
            pass
    return ("\n".join(text_parts), fetched)


def enrich(slug: str) -> dict:
    org_dir = ORGS_ROOT / slug
    org_path = org_dir / "org.json"
    if not org_path.exists():
        return {"slug": slug, "error": "org not found"}

    org = json.loads(org_path.read_text())
    company = org.get("company", slug)
    # Corporate-domain override beats whatever org.json has (consumer site is
    # a blank SPA for big enterprises)
    if slug in CORPORATE_DOMAIN_OVERRIDES:
        domain = CORPORATE_DOMAIN_OVERRIDES[slug]
    else:
        domain = org.get("web") or org.get("domain")
    if not domain or domain == "(unknown)":
        domain = company.lower().replace(" ", "").replace(".", "") + ".com"
        print(f"  ⚠ no web domain in org.json — guessing {domain}")

    print(f"▸ enriching {slug} ({company} @ {domain})")
    text, urls = fetch_pages(domain)
    if not text:
        return {"slug": slug, "error": "no fetchable pages", "domain": domain}
    print(f"  fetched {len(urls)} page(s), {len(text)} chars")

    print(f"  running Gemma extraction (~30s)…")
    try:
        extracted = ollama_extract(
            ENRICHMENT_PROMPT.format(company=company, text=text[:16000]),
            ENRICHMENT_SCHEMA,
        )
    except Exception as e:
        return {"slug": slug, "error": f"extraction failed: {e}", "domain": domain}

    # Append to digital.md
    digital_path = org_dir / "digital.md"
    existing = digital_path.read_text() if digital_path.exists() else "# Digital footprint\n"
    new_lines = [
        "",
        f"## Enriched {time.strftime('%Y-%m-%d')}",
        "",
        f"**Summary:** {extracted.get('summary', '(none)')}",
        "",
    ]
    if extracted.get("tech_stack_signals"):
        new_lines.append("**Tech stack signals:**")
        for s in extracted["tech_stack_signals"]:
            new_lines.append(f"- {s}")
        new_lines.append("")
    if extracted.get("modernization_signals"):
        new_lines.append("**Modernization signals:**")
        for s in extracted["modernization_signals"]:
            new_lines.append(f"- {s}")
        new_lines.append("")
    if extracted.get("executive_quotes"):
        new_lines.append("**Executive quotes:**")
        for q in extracted["executive_quotes"]:
            new_lines.append(f"- *\"{q.get('quote', '')}\"* — {q.get('name', '')}, {q.get('role', '')}")
        new_lines.append("")
    if extracted.get("recent_initiatives"):
        new_lines.append("**Recent initiatives:**")
        for i in extracted["recent_initiatives"]:
            new_lines.append(f"- {i}")
        new_lines.append("")
    if extracted.get("openers"):
        new_lines.append("**Suggested cold openers:**")
        for o in extracted["openers"]:
            new_lines.append(f"- {o}")
        new_lines.append("")
    new_lines.append("**Sources:** " + ", ".join(urls))
    new_lines.append("")
    digital_path.write_text(existing + "\n".join(new_lines))

    # Write enriched_personality.md so the persona bridge uses richer context
    personality_path = org_dir / "enriched_personality.md"
    sections = []
    if extracted.get("summary"):
        sections.append(f"COMPANY CONTEXT\n{extracted['summary']}\n")
    if extracted.get("tech_stack_signals"):
        sections.append("YOUR TECH STACK (publicly known)\n" + "\n".join(f"- {s}" for s in extracted["tech_stack_signals"]))
    if extracted.get("modernization_signals"):
        sections.append("WHAT YOUR COMPANY IS WORKING ON\n" + "\n".join(f"- {s}" for s in extracted["modernization_signals"]))
    if extracted.get("recent_initiatives"):
        sections.append("RECENT NAMED INITIATIVES (you might mention these)\n" + "\n".join(f"- {i}" for i in extracted["recent_initiatives"]))
    if extracted.get("executive_quotes"):
        sections.append("PUBLIC QUOTES FROM YOUR LEADERSHIP\n" + "\n".join(f"- \"{q.get('quote', '')}\" — {q.get('name', '')}" for q in extracted["executive_quotes"]))
    personality_path.write_text("\n\n".join(sections) + "\n")

    return {
        "slug": slug,
        "company": company,
        "pages_fetched": len(urls),
        "signals": len(extracted.get("tech_stack_signals") or []) + len(extracted.get("modernization_signals") or []),
        "quotes": len(extracted.get("executive_quotes") or []),
        "initiatives": len(extracted.get("recent_initiatives") or []),
        "openers": extracted.get("openers", []),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*", help="org slugs to enrich")
    ap.add_argument("--top10", action="store_true", help="enrich the 10 highest-priority KillSesh targets")
    args = ap.parse_args()

    if args.top10:
        slugs = TOP10
    elif args.slugs:
        slugs = args.slugs
    else:
        ap.error("specify slugs or --top10")

    print(f"Enriching {len(slugs)} org(s)…\n")
    results = []
    for slug in slugs:
        try:
            r = enrich(slug)
        except KeyboardInterrupt:
            print("\n⚠ interrupted — partial progress saved")
            break
        except Exception as e:
            r = {"slug": slug, "error": str(e)}
        results.append(r)
        if "error" in r:
            print(f"  ✗ {slug}: {r['error']}")
        else:
            print(f"  ✓ {slug}: {r['pages_fetched']} pages, {r['signals']} signals, {r['quotes']} quotes")
        print()

    print("─" * 60)
    succeeded = [r for r in results if "error" not in r]
    failed = [r for r in results if "error" in r]
    print(f"✓ {len(succeeded)} enriched · ✗ {len(failed)} failed")


if __name__ == "__main__":
    main()
