"""
adapters/modernization_signals.py — COBOL/mainframe-specific signal scanner.

This is the social_signals adapter's COBOL-modernization sibling. It scans
a company's public surface area for language that indicates an ACTIVE
modernization initiative. Every match becomes a high-priority cold-call
opener:

  ✓ "I saw your last 10-K mentioned the multi-year mainframe transformation
     — I help companies hit those deadlines with deterministic field parity."

  ✓ "Your careers page has 47 open mainframe modernization roles — most
     stuck for 6+ months. Want to talk about the deliverable that ships
     in 5 days?"

PUBLIC SOURCES SCANNED:
  - The company's own homepage + /careers + /press + /investors + /about
  - Their press-release feed if linked
  - Their job-posting count (anchor + scroll for "open roles")

WHAT IT DETECTS (each becomes a typed signal with an opener template):

  RFP / initiative language:
    - "mainframe modernization" / "modernization journey"
    - "core banking transformation" / "policy admin modernization"
    - "legacy system replacement"
    - "cloud migration" + "mainframe"
    - "AWS Mainframe Modernization" / "Azure Mainframe Migration"

  Tech-stack signals (COBOL-specific):
    - "COBOL" / "RPG" / "JCL" / "CICS" / "IMS" / "DB2"
    - "AS400" / "IBM i" / "iSeries"
    - "z/OS" / "System z" / "z14" / "z15" / "z16"
    - "ACORD AL3" / "ACORD XML"
    - "Mumps" / "M language"  (healthcare)
    - "Facets" / "TriZetto"   (health insurance)

  Hiring signals (pain indicators):
    - "10+ open mainframe" / "looking for COBOL developers"
    - "experience with z/OS" / "RPG-IV experience"

  Risk language (auditor / regulator-facing):
    - "audit findings" + "legacy systems"
    - "GAO report" / "OCC consent order"
    - "ransomware" / "data breach" + recent year

  Vendor-relationship signals:
    - "partnership with IBM" / "Cognizant" / "TCS" / "Accenture"
    - "AWS Mainframe Modernization partner"

Output: writes mod_signals.md and mod_signals.json into the org folder.
The pre-call brief generator reads these alongside social_signals.

Example:
    python3 -m adapters.modernization_signals https://allstate.com --org allstate
    python3 -m adapters.modernization_signals --all     # refresh every org with a known web URL
"""
from __future__ import annotations
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from adapters._common import (
    fetch_page, domain_from_url, slugify, ORGS_ROOT,
)


# Pattern → category → opener template. The opener may use {company} which
# gets substituted with the company name from the org if available.
SIGNAL_PATTERNS = [
    # Active initiative language
    (r"\bmainframe modernization\b",        "initiative", "I noticed your public materials reference an active mainframe modernization initiative. The biggest hidden risk on those programs is silent field drops on REDEFINES translations. Worth 15 minutes?"),
    (r"\bcore banking transformation\b",    "initiative", "Your core banking transformation is exactly the kind of program where AI translation tools quietly drop fields. I help BFSI customers verify field parity deterministically. 15 minutes?"),
    (r"\bpolicy admin modernization\b",     "initiative", "Your policy admin modernization is in the highest-risk category for legacy translation — one field drop on a long-tail annuity is a regulatory event. Worth 15 minutes?"),
    (r"\blegacy system replacement\b",      "initiative", "Your legacy system replacement work is the exact use case I help carriers de-risk. Worth 15 minutes?"),
    (r"\bcloud migration\b.{0,80}\bmainframe\b", "initiative", "Your cloud migration of mainframe workloads — happy to talk about the deterministic field-parity verification layer that AWS/Azure don't ship."),
    (r"\bAWS Mainframe Modernization\b",    "vendor",     "I see you're using AWS Mainframe Modernization. I'm the deterministic verification layer that sits underneath. Worth 15 minutes?"),
    (r"\bAzure Mainframe Migration\b",      "vendor",     "I see you're using Azure Mainframe Migration. The verification step is usually manual — we automate it. Worth 15 minutes?"),

    # COBOL-specific tech-stack
    (r"\bCOBOL\b",                          "tech",       "Your site references COBOL directly — that's where my customers spend the most QA cycles. Worth 15 minutes?"),
    (r"\bRPG[\s\-](?:IV|Free)?\b",           "tech",       "Your RPG codebase modernization is a category where deterministic field parity is gold. Worth 15 minutes?"),
    (r"\bz/OS\b|\bSystem z\b|\bz1[456]\b",  "tech",       "Your z/OS footprint is exactly the workload I help customers translate. Worth 15 minutes?"),
    (r"\bAS\s?-?400\b|\bIBM i\b|\biSeries\b","tech",      "Your IBM i / AS400 modernization workstream is the harder of the two main legacy categories. We've solved the field-parity gap. 15 minutes?"),
    (r"\bACORD AL3\b",                       "tech",       "Your ACORD AL3 data exchange is exactly the kind of copybook where REDEFINES + OCCURS DEPENDING ON quietly breaks AI translation. Worth 15 minutes?"),
    (r"\b(?:CICS|IMS|IDMS|Adabas)\b",        "tech",       "Your legacy DBMS (CICS/IMS/IDMS/Adabas) modernization is exactly where I help customers verify field parity. Worth 15 minutes?"),
    (r"\bMumps\b|\bM language\b",            "tech",       "Your MUMPS modernization is rare expertise — happy to talk about the verification layer that goes on top."),
    (r"\bFacets\b|\bTriZetto\b",             "tech",       "Your Facets/TriZetto migration leaves COBOL under the surface — that's the gap I close."),

    # Hiring signals (pain)
    (r"\b(?:looking for|hiring) (?:experienced )?COBOL\b", "hiring", "Your job postings show open COBOL roles — the talent gap is exactly the problem my tool solves. Your existing team ships 5× faster."),
    (r"\bmainframe (?:developer|engineer|programmer)\b",    "hiring", "Your open mainframe-engineer roles are a signal the talent gap is biting. I help your existing team ship 5× faster."),

    # Risk + regulator language
    (r"\b(?:OCC|FFIEC|FRB|GAO)\b.{0,80}\bconsent order\b", "risk", "Your consent-order context means every modernization workstream is auditor-watched. Off-the-shelf AI translation that drops fields is a regulatory finding waiting to happen."),
    (r"\bdata breach\b.{0,80}\b202[3456]\b",              "risk", "Your recent breach context means new vendor trust is rebuilt slowly. We're on-prem-only, no API calls, verifiable via docker network inspect."),
    (r"\bransomware\b",                                    "risk", "Your ransomware exposure makes legacy-system attack surface a real priority. Modernization that doesn't add new vendor cloud calls fits that posture."),
]


def scan_text(text: str, company: str = "") -> list[dict]:
    """Scan the text against the signal patterns. Returns ordered list of hits."""
    hits = []
    seen = set()
    for pat, category, opener in SIGNAL_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            key = (pat, category)
            if key in seen: continue
            seen.add(key)
            opener_text = opener.replace("{company}", company) if company else opener
            hits.append({
                "category": category,
                "match": m.group(0),
                "opener": opener_text,
                "context": text[max(0, m.start()-80):min(len(text), m.end()+80)].strip(),
            })
    return hits


def analyze(url: str, company: str = "") -> dict:
    """Fetch homepage + try /press + /careers + /investors. Score signals."""
    base = url.rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "https://" + base

    pages_text = []
    fetched_pages = []
    for path in ["", "/press", "/news", "/careers", "/investors", "/about"]:
        u = base + path
        try:
            t = fetch_page(u)
            if t and len(t) > 200:
                pages_text.append(t)
                fetched_pages.append(u)
        except Exception:
            continue

    combined = "\n\n".join(pages_text)
    hits = scan_text(combined, company)

    by_cat = {}
    for h in hits:
        by_cat.setdefault(h["category"], []).append(h)

    return {
        "url": base,
        "company": company,
        "analyzed_at": datetime.date.today().isoformat(),
        "pages_fetched": fetched_pages,
        "total_chars": len(combined),
        "hits": hits,
        "hits_by_category": by_cat,
        "summary": _summarize(hits),
    }


def _summarize(hits: list[dict]) -> str:
    if not hits:
        return "No COBOL-modernization signals detected on public surfaces."
    cats = {}
    for h in hits:
        cats[h["category"]] = cats.get(h["category"], 0) + 1
    pieces = []
    if cats.get("initiative"): pieces.append(f"{cats['initiative']} active-initiative signal(s)")
    if cats.get("tech"):       pieces.append(f"{cats['tech']} tech-stack signal(s)")
    if cats.get("hiring"):     pieces.append(f"{cats['hiring']} hiring-pain signal(s)")
    if cats.get("risk"):       pieces.append(f"{cats['risk']} regulator/risk signal(s)")
    if cats.get("vendor"):     pieces.append(f"{cats['vendor']} incumbent-vendor signal(s)")
    return "Detected " + " · ".join(pieces) + "."


def render_md(result: dict) -> str:
    lines = [
        f"# Modernization signals · {result.get('company') or result.get('url', '?')}",
        "",
        f"_Analyzed {result['analyzed_at']} · scanned {len(result['pages_fetched'])} page(s) · {result['total_chars']:,} chars_",
        "",
        "## Summary",
        "",
        result["summary"],
        "",
    ]

    by_cat = result["hits_by_category"]

    cat_labels = {
        "initiative": "▸ Active initiative signals",
        "tech":       "▸ COBOL/mainframe tech-stack signals",
        "vendor":     "▸ Incumbent-vendor signals",
        "hiring":     "▸ Hiring-pain signals",
        "risk":       "▸ Regulatory / risk signals",
    }
    for cat, label in cat_labels.items():
        if cat not in by_cat: continue
        lines.append(f"## {label}")
        lines.append("")
        for h in by_cat[cat]:
            lines.append(f"- **Matched:** `{h['match']}`")
            lines.append(f"  - Context: …{h['context']}…")
            lines.append(f"  - Opener: *\"{h['opener']}\"*")
            lines.append("")

    if not result["hits"]:
        lines.append("No public signals found. Either the site is opaque, the company has no public modernization conversation, or it's already done. Worth manually checking earnings calls + SEC filings.")
        lines.append("")

    return "\n".join(lines)


def run_one(slug: str, web: str = None, company: str = None) -> dict:
    """Analyze one org. Looks up its org.json to get web URL + company name."""
    org_dir = ORGS_ROOT / slug
    if not org_dir.exists():
        print(f"× org not found: {slug}")
        return None
    org = json.loads((org_dir / "org.json").read_text())
    web = web or org.get("web")
    company = company or org.get("company", slug)
    if not web or web in ("(unknown)", "(no website found)") or web.startswith("("):
        print(f"  ⚠ {slug}: no usable web URL — skipping")
        return None

    print(f"▸ scanning {company} ({web})…")
    try:
        result = analyze(web, company)
    except Exception as e:
        print(f"  × scan failed: {e}")
        return None

    md = render_md(result)
    (org_dir / "mod_signals.md").write_text(md)
    (org_dir / "mod_signals.json").write_text(json.dumps(result, indent=2) + "\n")

    n_hits = len(result["hits"])
    print(f"  ✓ {n_hits} signal(s)" if n_hits else "  · no signals")
    return result


def main():
    ap = argparse.ArgumentParser(description="Scan a company's public surface for COBOL-modernization signals")
    ap.add_argument("--url", help="Direct URL to scan")
    ap.add_argument("--org", help="Org slug to scan (reads web URL from org.json)")
    ap.add_argument("--all", action="store_true", help="Scan every org in organizations/ with a known web URL")
    args = ap.parse_args()

    if args.all:
        results = []
        for d in sorted(ORGS_ROOT.iterdir()):
            if not d.is_dir(): continue
            r = run_one(d.name)
            if r:
                results.append((d.name, len(r["hits"])))
        # Sort by signal density
        results.sort(key=lambda x: -x[1])
        print("\n▸ priority ranking (most signals = best dial targets):")
        for slug, n in results[:20]:
            print(f"  {n:>3}  {slug}")
    elif args.url:
        result = analyze(args.url)
        print(render_md(result))
    elif args.org:
        run_one(args.org)
    else:
        ap.error("must specify --url, --org, or --all")


if __name__ == "__main__":
    main()
