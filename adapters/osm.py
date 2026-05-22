"""
adapters/osm.py — nearby business search via OpenStreetMap (Overpass API).

Free, no API key, no billing. Lower quality than Google Places — especially
in US suburbs where Google maintains better data. Best for: when you just
want to bootstrap a prospect list without setting up Google Cloud.

Uses Overpass QL to query OSM data. Documentation:
    https://wiki.openstreetmap.org/wiki/Overpass_API

OSM "shop" tags equivalent to Google Place types:
    https://wiki.openstreetmap.org/wiki/Map_features#Shop

Example:
    python3 -m adapters.osm --location "Portland, OR" --radius 25mi --tag "amenity=dentist"
    python3 -m adapters.osm --location "Portland, OR" --radius 25mi --tag "shop=hairdresser"
    python3 -m adapters.osm --location "Portland, OR" --radius 25mi --tag "office=lawyer"
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from adapters._common import slugify, write_org, _SSL

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def geocode(location: str) -> tuple[float, float]:
    """Free geocoding via Nominatim. Returns (lat, lng)."""
    url = f"{NOMINATIM_URL}?format=json&limit=1&q={urllib.parse.quote(location)}"
    req = urllib.request.Request(url, headers={"User-Agent": "BullpenLM / OSM adapter"})
    with urllib.request.urlopen(req, timeout=15, context=_SSL) as r:
        data = json.loads(r.read())
    if not data:
        raise RuntimeError(f"geocode failed for '{location}'")
    return float(data[0]["lat"]), float(data[0]["lon"])


def parse_radius(s: str) -> float:
    s = s.strip().lower()
    if s.endswith("mi"): return float(s[:-2]) * 1609.34
    if s.endswith("km"): return float(s[:-2]) * 1000
    if s.endswith("m"):  return float(s[:-1])
    return float(s)


def overpass_query(lat: float, lng: float, radius_m: float, tag: str, limit: int = 50) -> list[dict]:
    """Query Overpass for nodes/ways/relations matching the tag within radius."""
    key, value = tag.split("=", 1)
    query = (
        f"[out:json][timeout:30];"
        f'(nwr["{key}"="{value}"](around:{radius_m},{lat},{lng}););'
        f"out center {limit};"
    )
    req = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": "BullpenLM / OSM adapter"},
    )
    with urllib.request.urlopen(req, timeout=45, context=_SSL) as r:
        data = json.loads(r.read())
    return data.get("elements", [])


def main():
    ap = argparse.ArgumentParser(description="Find businesses nearby via OpenStreetMap (free, no API key)")
    ap.add_argument("--location", required=True, help="City + state, e.g. 'Portland, OR'")
    ap.add_argument("--radius", default="25mi")
    ap.add_argument("--tag", required=True, help="OSM tag, e.g. 'amenity=dentist' or 'shop=hairdresser' or 'office=lawyer'")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--zone", default="End Customer")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"▸ geocoding '{args.location}' via Nominatim…")
    lat, lng = geocode(args.location)
    print(f"  → {lat:.4f}, {lng:.4f}")

    radius_m = parse_radius(args.radius)
    print(f"▸ querying Overpass for {args.tag} within {radius_m/1609.34:.1f}mi…")
    elements = overpass_query(lat, lng, radius_m, args.tag, args.limit)
    print(f"✓ found {len(elements)} matches")
    print()

    written = 0
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("brand")
        if not name:
            continue
        slug = slugify(name)
        addr_parts = []
        for k in ("addr:housenumber", "addr:street", "addr:city", "addr:state", "addr:postcode"):
            if tags.get(k): addr_parts.append(tags[k])
        addr = " ".join(addr_parts) or "(unknown)"

        print(f"  · {name}")
        print(f"    {addr}")
        if tags.get("website"): print(f"    {tags['website']}")
        if tags.get("phone"):   print(f"    {tags['phone']}")

        if args.dry_run:
            continue

        org = {
            "slug": slug,
            "company": name,
            "hq": addr,
            "size": "(unknown — local business)",
            "zone": args.zone,
            "what": f"Local {args.tag.split('=')[-1]} in the {args.location} area",
            "phone": tags.get("phone", "(unknown)"),
            "web": tags.get("website", "(no website found)"),
            "source": "openstreetmap",
            "osm_id": str(el.get("id", "")),
            "osm_tags": tags,
        }
        digital_lines = []
        if tags.get("opening_hours"): digital_lines.append(f"Hours: {tags['opening_hours']}")
        if tags.get("cuisine"):        digital_lines.append(f"Cuisine: {tags['cuisine']}")
        if tags.get("brand"):          digital_lines.append(f"Brand: {tags['brand']}")
        write_org(slug, org, digital=digital_lines)
        written += 1

    print(f"\n✓ wrote {written} orgs" if not args.dry_run else "\n(dry-run — no orgs written)")


if __name__ == "__main__":
    main()
