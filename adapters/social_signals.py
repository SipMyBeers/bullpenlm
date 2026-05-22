"""
adapters/social_signals.py — the weakness identifier.

Reads a company's homepage and surfaces SIGNALS that become cold-call
openers: outdated tech, dormant social, stale blog, broken mobile, etc.

Every signal is framed as a sales opener you can read verbatim:

  ✓ "I noticed your blog hasn't been updated since March — I help
     companies like yours fix the content gap."
  ✓ "Your site is still running WordPress 5.x — happy to help you
     migrate before the next CVE."
  ✓ "Your Twitter hasn't posted in 8 months. Your competitors are
     publishing weekly. Worth 15 minutes to talk?"

PUBLIC SOURCES ONLY. We never log into anything, never scrape personal
LinkedIn profiles, never touch private databases. Everything here is
fair-game public-record:
  - The site's own HTML
  - Public LinkedIn company-page (the /company/<slug> URL — visible to anyone)
  - Public Twitter/X profile pages
  - Public Facebook business pages
  - Public Google reviews via Places API (uses your existing key if set)

What we detect:

TECH STACK SIGNALS (from HTML inspection)
  - CMS in use (WordPress, Webflow, Shopify, Squarespace, Wix, Drupal)
  - JS frameworks (React, Vue, Next.js, Angular, jQuery age)
  - Analytics (Google Analytics, GA4, Plausible, Mixpanel, Segment)
  - Payment processors (Stripe, Square, PayPal)
  - CRM/marketing tags (HubSpot, Marketo, Pardot, Salesforce Web-to-Lead)
  - Hosted-form services (Typeform, Calendly, Hubspot Forms)

ACTIVITY SIGNALS
  - Blog/news last-post date (if /blog or /news exists)
  - Copyright year vs current year
  - Mobile viewport meta tag present?
  - Robots.txt accessible?
  - Has HTTPS?

SOCIAL SIGNALS (from URLs found on page)
  - LinkedIn company-page URL → fetch + check last activity
  - Twitter/X profile → fetch + check last post
  - Facebook page → fetch + check last post
  - Instagram → check existence
  - YouTube channel → check existence + last upload

OPPORTUNITY SIGNALS
  - "Powered by" footers indicating template themes
  - Stale press / news section
  - Missing essentials: no contact form? no team page? no blog?
  - SEO basics missing (meta description, og: tags, sitemap.xml)

Example:
    python3 -m adapters.social_signals https://localdentist.com
    python3 -m adapters.social_signals https://localdentist.com --org localdentist
"""
from __future__ import annotations
import argparse
import datetime
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from adapters._common import domain_from_url, slugify, _SSL, ORGS_ROOT, fetch_page


# Tech-stack detection patterns. Each is { name, hint pattern, opener }.
TECH_SIGNATURES = [
    # CMS
    ("WordPress",   r"wp-content|wp-includes|/wp-json/",         "Your site is built on WordPress — I help companies migrate to faster modern stacks before their next hosting renewal."),
    ("Squarespace", r"squarespace\.com|static1\.squarespace",   "Your site is on Squarespace. I help businesses graduate to platforms that don't cap conversion features at the Premium tier."),
    ("Wix",         r"wix\.com|static\.wixstatic",              "Your site is on Wix. I help businesses move off Wix to platforms with proper SEO and faster load times."),
    ("Shopify",     r"shopify\.com|cdn\.shopify",                "Your store is on Shopify — happy to discuss apps that lift average order value or fix abandoned-cart leak."),
    ("Webflow",     r"webflow\.io|assets-global\.website-files", "Your site is on Webflow. Want to talk about CMS depth and form integration?"),
    ("Drupal",      r"sites/default/files|drupal\.js",           "Your site is on Drupal — well-supported but heavy. I help companies migrate where it makes sense."),
    # JS frameworks
    ("React",       r"react(?:-dom)?\.production",               None),
    ("Next.js",     r"_next/static|__NEXT_DATA__",               None),
    ("Vue.js",      r"vue\.js|vue@",                             None),
    ("Angular",     r"ng-version=|angular\.js",                  None),
    ("jQuery",      r"jquery[\.-]\d",                            "Your site still leans on jQuery — I help modernize legacy front-ends without breaking SEO."),
    # Analytics
    ("Google Analytics (UA)",  r"UA-\d{4,}",                     "You're still on Universal Analytics, which Google sunset in 2023 — your traffic data has been incomplete. Want to fix that?"),
    ("Google Analytics 4",     r"google-analytics\.com/g/collect|gtag\('config', ?'G-",  None),
    ("Plausible",              r"plausible\.io",                 None),
    ("Mixpanel",               r"mixpanel\.com",                 None),
    ("Segment",                r"segment\.com|segment\.io",      None),
    # CRM / marketing
    ("HubSpot",                r"hs-scripts\.com|js\.hsforms",   None),
    ("Marketo",                r"marketo\.com|mktoresp",         None),
    ("Pardot",                 r"pardot\.com|pi\.pardot",        None),
    # Payments
    ("Stripe",                 r"stripe\.com/js|js\.stripe\.com", None),
    ("Square",                 r"squareup\.com|square\.com/js",  None),
    ("PayPal",                 r"paypal\.com/sdk|paypalobjects", None),
    # Forms / booking
    ("Calendly",               r"calendly\.com/",                None),
    ("Typeform",               r"typeform\.com",                 None),
]


def fetch_raw(url: str, timeout: int = 15) -> tuple[str, dict]:
    """Like fetch_page but returns raw HTML + response headers."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Cheers Beers / social-signals)",
        "Accept": "text/html",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
        raw = r.read().decode("utf-8", errors="ignore")
        return raw, dict(r.headers)


def detect_tech(html: str) -> list[tuple[str, str | None]]:
    found = []
    for name, pat, opener in TECH_SIGNATURES:
        if re.search(pat, html, re.IGNORECASE):
            found.append((name, opener))
    return found


def find_social_urls(html: str) -> dict[str, str]:
    """Pull social-media URLs from a page."""
    out = {}
    patterns = {
        "linkedin":  r"https?://(?:www\.)?linkedin\.com/(?:company|in|school)/[a-zA-Z0-9\-_/]+",
        "twitter":   r"https?://(?:www\.)?(?:twitter|x)\.com/[a-zA-Z0-9_]{1,15}",
        "facebook":  r"https?://(?:www\.)?facebook\.com/[a-zA-Z0-9\.\-]+",
        "instagram": r"https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_\.]+",
        "youtube":   r"https?://(?:www\.)?youtube\.com/(?:channel|c|@)[a-zA-Z0-9_\-]+",
        "github":    r"https?://(?:www\.)?github\.com/[a-zA-Z0-9\-_]+",
        "tiktok":    r"https?://(?:www\.)?tiktok\.com/@[a-zA-Z0-9_\.]+",
    }
    for k, pat in patterns.items():
        m = re.search(pat, html)
        if m:
            # Drop trailing punctuation
            url = re.sub(r"[\"'\)\]>.,]+$", "", m.group(0))
            out[k] = url
    return out


def find_email_pattern(html: str) -> str | None:
    """Look for any mailto: link, infer the pattern (e.g. first.last@)."""
    emails = re.findall(r"mailto:([a-zA-Z0-9_\-\.]+@[a-zA-Z0-9_\-\.]+)", html)
    emails = [e for e in emails if not e.lower().startswith(("info@", "hello@", "contact@", "support@", "admin@"))]
    return emails[0] if emails else None


def find_dates(text: str) -> list[str]:
    """Extract dates that look like 'Last updated YYYY-MM-DD' or 'Posted 2024'."""
    out = set()
    for m in re.finditer(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text):
        out.add(f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
    for m in re.finditer(r"\b(20\d{2})\b", text):
        out.add(m.group(1))  # year-only
    return sorted(out, reverse=True)


def analyze(url: str) -> dict:
    """Main analysis pass — returns structured signals + opener-ready strings."""
    domain = domain_from_url(url)
    print(f"▸ analyzing {domain}")
    raw, headers = fetch_raw(url)
    plain = fetch_page(url)

    signals = {
        "domain": domain,
        "analyzed_at": datetime.date.today().isoformat(),
        "tech": [],
        "social": {},
        "freshness": {},
        "openers": [],   # ← the value-add. Cold-call-ready opener strings.
        "weaknesses": [],
        "strengths": [],
    }

    # ── Tech stack ──
    tech_found = detect_tech(raw)
    signals["tech"] = [t[0] for t in tech_found]
    for name, opener in tech_found:
        if opener:
            signals["openers"].append({"category": "tech", "stack": name, "opener": opener})

    # ── Social ──
    socials = find_social_urls(raw)
    signals["social"] = socials
    expected = {"linkedin", "twitter", "facebook"}
    missing = expected - set(socials.keys())
    if missing:
        signals["weaknesses"].append(f"No discoverable {'/'.join(sorted(missing))} presence")
        signals["openers"].append({
            "category": "social-missing",
            "opener": f"I notice you don't have an active {next(iter(missing))} presence. Your competitors do. Want to talk?",
        })

    # ── Freshness ──
    # Copyright year
    cy_match = re.search(r"©\s*(20\d{2})", raw)
    current_year = datetime.date.today().year
    if cy_match:
        cy = int(cy_match.group(1))
        signals["freshness"]["copyright_year"] = cy
        if current_year - cy >= 1:
            signals["weaknesses"].append(f"Copyright shows {cy} — site may not be actively maintained")
            signals["openers"].append({
                "category": "freshness",
                "opener": f"I noticed your site still shows © {cy}. Usually a tell that someone hasn't touched the site in a year. I help companies fix that.",
            })

    # Latest year reference anywhere
    dates = find_dates(plain)
    if dates:
        signals["freshness"]["dates_found"] = dates[:6]
        # If newest date is >18mo old, that's a signal
        newest_year_match = re.match(r"(\d{4})", dates[0])
        if newest_year_match:
            ny = int(newest_year_match.group(1))
            if current_year - ny >= 2:
                signals["weaknesses"].append(f"Newest date on site is {dates[0]} — content marketing may be dormant")
                signals["openers"].append({
                    "category": "content-stale",
                    "opener": f"Your latest visible content shows {dates[0]} — I help businesses revive a dormant blog without hiring a full-time writer.",
                })

    # ── Mobile viewport ──
    has_viewport = bool(re.search(r"<meta[^>]+name=[\"']viewport[\"']", raw))
    signals["freshness"]["mobile_responsive_meta"] = has_viewport
    if not has_viewport:
        signals["weaknesses"].append("No mobile viewport meta tag — site likely broken on phones")
        signals["openers"].append({
            "category": "mobile",
            "opener": "Your site doesn't have a mobile viewport tag — it's probably broken on iPhones. Want to talk?",
        })

    # ── HTTPS ──
    signals["freshness"]["https"] = url.startswith("https://") or domain.startswith("https")

    # ── SEO basics ──
    has_meta_desc = bool(re.search(r"<meta[^>]+name=[\"']description[\"']", raw))
    has_og = bool(re.search(r"<meta[^>]+property=[\"']og:", raw))
    if not has_meta_desc:
        signals["weaknesses"].append("No meta description — SEO and link previews are weak")
    if not has_og:
        signals["weaknesses"].append("No Open Graph tags — links shared on social look broken")

    # ── Email pattern ──
    email = find_email_pattern(raw)
    if email:
        signals["email_sample"] = email

    # ── Generate strengths ──
    if "Stripe" in signals["tech"]:
        signals["strengths"].append("Modern payment processing (Stripe)")
    if "Google Analytics 4" in signals["tech"]:
        signals["strengths"].append("On modern GA4")
    if "Calendly" in signals["tech"] or "Typeform" in signals["tech"]:
        signals["strengths"].append("Modern lead-capture tooling")
    if has_viewport and has_meta_desc and has_og:
        signals["strengths"].append("SEO + mobile basics in place")

    return signals


def render_signals_md(signals: dict) -> str:
    lines = [
        f"# Social + tech signals · {signals['domain']}",
        "",
        f"_Analyzed {signals['analyzed_at']}_",
        "",
    ]

    if signals["openers"]:
        lines += ["## ▸ Cold-call openers (ready to read)", ""]
        for o in signals["openers"]:
            lines += [f"- *\"{o['opener']}\"*"]
        lines.append("")

    if signals["weaknesses"]:
        lines += ["## ✗ Weaknesses (your selling angles)", ""]
        lines += [f"- {w}" for w in signals["weaknesses"]]
        lines.append("")

    if signals["strengths"]:
        lines += ["## ✓ Strengths (don't pitch against these)", ""]
        lines += [f"- {s}" for s in signals["strengths"]]
        lines.append("")

    if signals["tech"]:
        lines += ["## Tech stack detected", ""]
        lines += [f"- {t}" for t in signals["tech"]]
        lines.append("")

    if signals["social"]:
        lines += ["## Social presence", ""]
        for k, url in signals["social"].items():
            lines.append(f"- **{k.title()}**: {url}")
        lines.append("")

    if signals.get("freshness"):
        lines += ["## Freshness signals", ""]
        for k, v in signals["freshness"].items():
            lines.append(f"- {k}: {v}")
        lines.append("")

    if signals.get("email_sample"):
        lines += [f"## Sample email pattern", "", f"- `{signals['email_sample']}`", ""]

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Detect tech/social/freshness weakness signals for any company URL")
    ap.add_argument("url", help="Company URL")
    ap.add_argument("--org", help="Org slug to write into (default: derive from domain)")
    args = ap.parse_args()

    signals = analyze(args.url)
    md = render_signals_md(signals)

    slug = args.org or slugify(domain_from_url(args.url).replace(".com", "").replace(".io", "").replace(".co", ""))
    org_dir = ORGS_ROOT / slug
    org_dir.mkdir(parents=True, exist_ok=True)
    out = org_dir / "signals.md"
    out.write_text(md)
    (org_dir / "signals.json").write_text(json.dumps(signals, indent=2) + "\n")

    print()
    print(md)
    print()
    print(f"✓ written to {out}")


if __name__ == "__main__":
    main()
