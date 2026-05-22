"""
adapters/website.py — single URL → one org.

Fetches a company's homepage, strips to text, runs an Ollama extraction pass,
and writes organizations/<slug>/{org.json, digital.md}. No paid APIs. No
network deps beyond Python stdlib + Ollama.

Example:
    python3 -m adapters.website https://acme-finance.com
    python3 -m adapters.website acme-finance.com --zone "End Customer"
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from adapters._common import (
    fetch_page, domain_from_url, slugify, ollama_extract, write_org
)


EXTRACTION_PROMPT = """Read the following company homepage text and extract structured facts about the company. Return ONLY a JSON object with these keys:

  company:           The company's display name (e.g. "Acme Finance")
  what:              ONE sentence describing what the company does, in plain English
  hq:                City + state (or country) if visible — e.g. "Portland, OR" or "(unknown)"
  size:              Employee count if visible — e.g. "≈50 employees" or "(unknown)"
  zone:              Best guess: "End Customer" | "Channel Partner" | "Tool Partner" | "Boutique Partner"
  techStack:         Tech the company appears to use, comma-separated string, or "(unknown)"
  digital:           Array of 3-6 short factual bullets pulled from the page (e.g. "Founded 2018", "Active in BFSI vertical", "Recent hires in AI/ML")
  contactsHints:     Array of any names + titles mentioned on the page (the leadership / about page)
  phone:             Phone number if visible, or "(unknown)"

Be conservative. If you can't infer a field with reasonable confidence, write "(unknown)" rather than hallucinating. For zone: "End Customer" = they buy enterprise software. "Channel Partner" = services firm selling to others. "Tool Partner" = software product company. "Boutique Partner" = small specialist consultancy / staffing.

Page text:
---
{text}
---"""


def ingest_website(url: str, *, zone: str = None, force: bool = False, slug: str = None) -> dict:
    """Main entrypoint. Returns the written org dict."""
    domain = domain_from_url(url)
    if not slug:
        slug = slugify(domain.replace(".com", "").replace(".io", "").replace(".co", ""))
    print(f"▸ ingesting {url}")
    print(f"  slug:   {slug}")
    print(f"  domain: {domain}")

    print(f"  fetching homepage…")
    try:
        text = fetch_page(url)
    except Exception as e:
        print(f"× fetch failed: {e}")
        return None
    if len(text) < 100:
        print(f"× page returned only {len(text)} chars — likely a JS-rendered SPA; try Firecrawl adapter (TODO)")
        return None
    text_clip = text[:12000]  # cap context — most homepage content is in first ~10k chars

    print(f"  running Gemma extraction (this can take 20-40s)…")
    try:
        extracted = ollama_extract(EXTRACTION_PROMPT.format(text=text_clip))
    except Exception as e:
        print(f"× extraction failed: {e}")
        return None

    # Build the org record
    org = {
        "slug": slug,
        "company": extracted.get("company") or domain,
        "role": "(unknown — pending discovery)",     # filled in as you learn contacts
        "hq": extracted.get("hq") or "(unknown)",
        "size": extracted.get("size") or "(unknown)",
        "zone": (zone or extracted.get("zone") or "End Customer"),
        "what": extracted.get("what") or "(unknown)",
        "techStack": extracted.get("techStack") or "(unknown)",
        "phone": extracted.get("phone") or "(unknown)",
        "web": domain,
        "source": "website-ingest",
    }
    digital = extracted.get("digital") or []
    if extracted.get("contactsHints"):
        digital.append("Names mentioned on site: " + ", ".join(extracted["contactsHints"][:6]))

    out = write_org(slug, org, digital=digital, force=force)
    print(f"✓ wrote {out}")
    print(f"  company:  {org['company']}")
    print(f"  zone:     {org['zone']}")
    print(f"  what:     {org['what']}")
    print(f"  hq:       {org['hq']}")
    if org["phone"] != "(unknown)":
        print(f"  phone:    {org['phone']}")
    print(f"  digital:  {len(digital)} facts captured")
    return org


def main():
    ap = argparse.ArgumentParser(description="Ingest a single company website into organizations/")
    ap.add_argument("url", help="URL of the company homepage")
    ap.add_argument("--zone", choices=["End Customer", "Channel Partner", "Tool Partner", "Boutique Partner"], help="Override the auto-detected zone")
    ap.add_argument("--slug", help="Override the slug")
    ap.add_argument("--force", action="store_true", help="Overwrite existing org.json instead of merging")
    args = ap.parse_args()
    result = ingest_website(args.url, zone=args.zone, force=args.force, slug=args.slug)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
