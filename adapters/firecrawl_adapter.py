"""
adapters/firecrawl_adapter.py — deep multi-page crawl via Firecrawl.

For when the simple `website` adapter returns too little — JS-rendered SPAs,
multi-page sites where the about/team/careers/blog pages have the real intel.

Firecrawl gets you cleaned markdown from any URL (rendered, JS-aware) plus
multi-page crawl. ~$16/mo starter, generous free tier. Docs:
    https://docs.firecrawl.dev

Setup:
    export FIRECRAWL_API_KEY="fc-..."

Example:
    python3 -m adapters.firecrawl_adapter https://stripe.com
    python3 -m adapters.firecrawl_adapter https://stripe.com --crawl --max-pages 20
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from adapters._common import (
    domain_from_url, slugify, ollama_extract, write_org, _SSL,
)
from adapters.website import EXTRACTION_PROMPT

API_BASE = "https://api.firecrawl.dev/v1"


def firecrawl_scrape(url: str, api_key: str) -> str:
    """Single-page scrape — returns clean markdown."""
    req = urllib.request.Request(
        f"{API_BASE}/scrape",
        data=json.dumps({"url": url, "formats": ["markdown"]}).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60, context=_SSL) as r:
        data = json.loads(r.read())
    if not data.get("success"):
        raise RuntimeError(f"Firecrawl scrape failed: {data}")
    return data["data"].get("markdown", "")


def firecrawl_crawl(url: str, api_key: str, max_pages: int = 10) -> list[str]:
    """Multi-page crawl — returns list of markdown blobs."""
    # Submit crawl job
    req = urllib.request.Request(
        f"{API_BASE}/crawl",
        data=json.dumps({
            "url": url,
            "limit": max_pages,
            "scrapeOptions": {"formats": ["markdown"]},
        }).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30, context=_SSL) as r:
        job = json.loads(r.read())
    job_id = job["id"]

    # Poll until done
    import time
    while True:
        time.sleep(3)
        req = urllib.request.Request(
            f"{API_BASE}/crawl/{job_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=30, context=_SSL) as r:
            status = json.loads(r.read())
        if status.get("status") == "completed":
            return [p.get("markdown", "") for p in status.get("data", [])]
        if status.get("status") in ("failed", "cancelled"):
            raise RuntimeError(f"crawl failed: {status}")


def main():
    ap = argparse.ArgumentParser(description="Deep crawl a website via Firecrawl → one org")
    ap.add_argument("url", help="Site URL")
    ap.add_argument("--crawl", action="store_true", help="Multi-page crawl (default: single page)")
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--zone")
    args = ap.parse_args()

    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        print("× FIRECRAWL_API_KEY env var not set.")
        print()
        print("To set this up:")
        print("  1. Sign up at https://firecrawl.dev (free tier: 500 pages/mo)")
        print("  2. Copy your API key from the dashboard")
        print("  3. export FIRECRAWL_API_KEY=\"fc-...\"")
        print()
        print("Alternative: use adapters/website.py for simple HTML fetch (no JS, no auth).")
        sys.exit(1)

    domain = domain_from_url(args.url)
    slug = slugify(domain.replace(".com", "").replace(".io", "").replace(".co", ""))
    print(f"▸ firecrawl ingest {args.url} → {slug}")

    if args.crawl:
        print(f"  crawling up to {args.max_pages} pages…")
        blobs = firecrawl_crawl(args.url, api_key, args.max_pages)
        text = "\n\n---\n\n".join(blobs)
        print(f"  collected {len(blobs)} pages, {len(text)} chars")
    else:
        print(f"  scraping single page…")
        text = firecrawl_scrape(args.url, api_key)
        print(f"  collected {len(text)} chars")

    text_clip = text[:18000]
    print(f"  running Gemma extraction…")
    extracted = ollama_extract(EXTRACTION_PROMPT.format(text=text_clip))

    org = {
        "slug": slug,
        "company": extracted.get("company") or domain,
        "hq": extracted.get("hq") or "(unknown)",
        "size": extracted.get("size") or "(unknown)",
        "zone": (args.zone or extracted.get("zone") or "End Customer"),
        "what": extracted.get("what") or "(unknown)",
        "techStack": extracted.get("techStack") or "(unknown)",
        "phone": extracted.get("phone") or "(unknown)",
        "web": domain,
        "source": "firecrawl",
    }
    digital = extracted.get("digital") or []
    if extracted.get("contactsHints"):
        digital.append("Names mentioned: " + ", ".join(extracted["contactsHints"][:8]))
    out = write_org(slug, org, digital=digital)
    print(f"✓ wrote {out}")


if __name__ == "__main__":
    main()
