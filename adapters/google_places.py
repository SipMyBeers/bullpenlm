"""
adapters/google_places.py — location + category → many orgs.

Pulls every business of a given category within a radius of a location via
the Google Places Nearby Search API, then chains adapters/website.py over
each result to populate organizations/.

USE CASE: "I want to sell AI integrations to every dentist within 25 miles
of Portland." One command → 80 populated org folders.

REQUIREMENTS:
    1. A Google Cloud account (free)
    2. Enable the "Places API (New)" — https://console.cloud.google.com/apis/library/places.googleapis.com
    3. Enable billing on the project (Places has a $200/mo free credit; nearby
       search is $32/1000 requests; you can hit the free tier for months)
    4. Create an API key with Places API access
    5. Set the env var:
           export GOOGLE_PLACES_API_KEY="AIza..."

If you don't want to set this up, use adapters/osm.py (Overpass / OpenStreetMap)
which is free + keyless but lower-fidelity, especially in suburbs.

Example:
    export GOOGLE_PLACES_API_KEY="..."
    python3 -m adapters.google_places \\
        --location "Portland, OR" \\
        --radius 25mi \\
        --type "dentist" \\
        --limit 50
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from adapters._common import slugify
from adapters.website import ingest_website

API_BASE = "https://places.googleapis.com/v1/places:searchNearby"
GEOCODE_BASE = "https://maps.googleapis.com/maps/api/geocode/json"


def geocode(location: str, api_key: str) -> tuple[float, float]:
    """Convert 'Portland, OR' → (lat, lng) via Google Geocoding API."""
    url = f"{GEOCODE_BASE}?address={urllib.parse.quote(location)}&key={api_key}"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read())
    if data.get("status") != "OK" or not data.get("results"):
        raise RuntimeError(f"geocode failed for '{location}': {data.get('status')}")
    loc = data["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]


def parse_radius(s: str) -> float:
    """Parse '25mi' or '40km' into meters."""
    s = s.strip().lower()
    if s.endswith("mi"):
        return float(s[:-2]) * 1609.34
    if s.endswith("km"):
        return float(s[:-2]) * 1000
    if s.endswith("m"):
        return float(s[:-1])
    return float(s)  # assume meters


def nearby_search(lat: float, lng: float, radius_m: float, place_type: str, api_key: str, limit: int = 50) -> list[dict]:
    """Call Places Nearby Search (new API). Returns list of place dicts."""
    body = {
        "includedTypes": [place_type],
        "maxResultCount": min(limit, 20),  # API max per call
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius_m,
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.websiteUri,places.nationalPhoneNumber,places.id,places.types",
    }
    req = urllib.request.Request(API_BASE, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return data.get("places", [])


def main():
    ap = argparse.ArgumentParser(description="Find businesses nearby via Google Places → populate organizations/")
    ap.add_argument("--location", required=True, help="City + state, e.g. 'Portland, OR'")
    ap.add_argument("--radius", default="25mi", help="Search radius — '25mi', '40km', or meters")
    ap.add_argument("--type", required=True, help="Google Places type — 'dentist', 'lawyer', 'restaurant', 'real_estate_agency', etc. Full list: https://developers.google.com/maps/documentation/places/web-service/place-types")
    ap.add_argument("--limit", type=int, default=20, help="Max results (Places caps at 20 per call)")
    ap.add_argument("--zone", default="End Customer", help="Zone label for all imported orgs")
    ap.add_argument("--ingest-websites", action="store_true", help="Also crawl each business's website (slow but populates full intel)")
    ap.add_argument("--dry-run", action="store_true", help="List results without writing any org files")
    args = ap.parse_args()

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        print("× GOOGLE_PLACES_API_KEY env var not set.")
        print()
        print("To set this up (one-time, free):")
        print("  1. Create a Google Cloud project at https://console.cloud.google.com")
        print("  2. Enable Places API (New): https://console.cloud.google.com/apis/library/places.googleapis.com")
        print("  3. Enable billing (Places gives $200/mo free credit — Nearby Search is $32/1K)")
        print("  4. Create an API key: APIs & Services → Credentials → Create Credentials → API Key")
        print("  5. Restrict it to the Places API (recommended)")
        print("  6. Export the key:")
        print("       export GOOGLE_PLACES_API_KEY=\"AIza...\"")
        print()
        print("Alternative if you don't want billing setup:")
        print("  Use the OpenStreetMap adapter (no auth, lower quality):")
        print("    python3 -m adapters.osm --location \"Portland, OR\" --type dentist")
        print("  (TODO — not yet implemented)")
        sys.exit(1)

    print(f"▸ geocoding '{args.location}'…")
    lat, lng = geocode(args.location, api_key)
    print(f"  → {lat:.4f}, {lng:.4f}")

    radius_m = parse_radius(args.radius)
    print(f"▸ searching '{args.type}' within {radius_m/1609.34:.1f}mi…")
    places = nearby_search(lat, lng, radius_m, args.type, api_key, args.limit)
    print(f"✓ found {len(places)} results")
    print()

    for i, p in enumerate(places, 1):
        name = p.get("displayName", {}).get("text", "(unnamed)")
        addr = p.get("formattedAddress", "")
        website = p.get("websiteUri")
        phone = p.get("nationalPhoneNumber", "")
        print(f"  {i:>3}. {name}")
        print(f"       {addr}")
        if website: print(f"       {website}")
        if phone:   print(f"       {phone}")
        print()

    if args.dry_run:
        print("(dry-run — no orgs written)")
        return

    print(f"▸ writing {len(places)} orgs to organizations/")
    written = 0
    for p in places:
        name = p.get("displayName", {}).get("text", "(unnamed)")
        slug = slugify(name)
        website = p.get("websiteUri")
        if args.ingest_websites and website:
            # Full pipeline — Places metadata + website scrape + Gemma extraction
            print(f"\n▸ {name} → {slug}")
            result = ingest_website(website, zone=args.zone, slug=slug)
            if result: written += 1
            time.sleep(0.5)  # gentle on the target sites
        else:
            # Skeleton only — just Places metadata, no website crawl
            from adapters._common import write_org
            org = {
                "slug": slug, "company": name,
                "role": "(unknown — pending discovery)",
                "hq": p.get("formattedAddress", "(unknown)"),
                "size": "(unknown — local business)",
                "zone": args.zone,
                "what": f"Local {args.type.replace('_', ' ')} in the {args.location} area",
                "phone": phone or "(unknown)",
                "web": website or "(no website found)",
                "source": "google-places",
            }
            write_org(slug, org)
            written += 1
            print(f"  ✓ {name} → organizations/{slug}/")

    print(f"\n✓ wrote {written} orgs.")
    print(f"  Next: open floor/index.html (will need a v0.2 build that reads from organizations/)")
    print(f"  Or: python3 -m adapters.website <website-url> to enrich any one of them with full intel.")


if __name__ == "__main__":
    main()
