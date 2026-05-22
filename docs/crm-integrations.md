# CRM integrations

The architecture splits cleanly into two layers:

- **OSS engine** (this repo): reads personas from `personas/<slug>/` directories. Anything that writes those directories is a valid input.
- **Commercial connectors** (Bullpen Cloud): authenticated bridges between SaaS CRMs and the file system.

This page tracks what's planned, what's shipped, and what's deliberately
out of scope.

## Tier 0 — manual (today)

Edit the markdown files by hand. Works for any CRM, any pipeline size.
This is the baseline that always works.

## Tier 1 — CSV import (OSS, v0.2)

Drag a CSV export from any CRM. A wizard maps columns to persona fields:

| CSV column | Persona field |
|---|---|
| Name / Contact | `personName` |
| Title / Role | `role` |
| Company | `company` |
| HQ / City | `hq` |
| Industry | (used to suggest zone) |
| Recent activity | appended to `personality.md` |
| Notes | appended to `personality.md` |
| Tags / Stage | maps to `status` in floor state |

**Status:** planned. Implementation will be a `manage.py import-csv` command
that produces a populated `personas/<slug>/` directory per row.

## Tier 2 — HubSpot OAuth (Hosted, v0.3)

The lightest CRM integration that matters. Why HubSpot first:

- Cleanest API in SMB CRM (REST + GraphQL, both well-documented)
- 95%+ of <500-person companies use it
- Free tier of HubSpot has all the data we need
- OAuth flow is one-screen approval

Sync model:
- Pull contacts + deals + recent activity nightly
- Map HubSpot Deal Stage → Bullpen status
- Map HubSpot Owner → Bullpen workspace user
- Recent emails / call notes → appended to `personality.md` for the matching persona

**Status:** designed, not yet built. Will live in the commercial product.

## Tier 3 — Salesforce (Hosted, v0.4+)

Enterprise check, slower sales cycle:

- Salesforce REST + Bulk API
- Field-level mapping editor (Salesforce schemas are highly custom per org)
- Security review per customer (expect 4-8 weeks per logo)

**Status:** deferred until 3+ design partners on HubSpot tier confirm demand.

## Tier 4 — engagement-platform sync (future)

Once we have CRM data, the natural next move is to write *back* — log every
practice session as a CRM activity:

- "Dylan rehearsed his Rocket call on 2026-05-22 · scored A- · biggest miss: led with price"
- Visible to the sales manager in the CRM as a coaching artifact
- Optional, off by default (some reps will hate this)

Targets: HubSpot Activities API, Salesforce Task object, Outreach Sequences,
Salesloft Cadences.

**Status:** roadmap.

## What's out of scope

- **Pulling email/call recordings** — that's Gong's lane. We are a *rehearsal*
  tool, not a *call review* tool. Different surface, different buyer.
- **Web scraping LinkedIn profiles** — TOS violation and creepy. Public talks
  are fair game (and what `ingest-talk` already supports).
- **Auto-generating personas from a domain name** — sounds nice, fails badly
  on accuracy. Better to keep human-in-the-loop for persona creation.

## How to add a custom integration

The persona directory format is documented in [`architecture.md`](architecture.md).
Anything that writes valid `persona.json` + the required markdown files is a
working integration.

Example: a HubSpot integration is roughly:

```python
def sync_hubspot_to_personas(api_key, dest_dir):
    hs = HubSpotClient(api_key)
    for contact in hs.contacts.get_all():
        slug = slugify(contact.email)
        d = Path(dest_dir) / slug
        d.mkdir(exist_ok=True)
        (d / "persona.json").write_text(json.dumps({
            "slug": slug,
            "personName": contact.full_name,
            "company": contact.company,
            "role": contact.title,
            "hq": contact.city,
            "size": contact.company_size,
            "zone": map_industry_to_zone(contact.industry),
            "what": contact.company_description,
            "say_voice": pick_voice(contact),
        }, indent=2))
        # ... write personality.md from recent notes, pushbacks.txt from
        # common stage objections, etc.
```

If you build one, PR it. The OSS repo will accept generic connectors.
Customer-specific or auth-heavy ones live in the commercial product.
