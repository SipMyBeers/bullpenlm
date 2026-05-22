# Data sources — how to populate your org graph

BullpenLM is data-source agnostic. You bring the data, the engine turns
it into practice-ready org folders + AI personas. This page is the menu of
ways to get data in.

## The model

All adapters write to the same place:

```
organizations/<slug>/
├── org.json        — company name, role, hq, size, zone, what, phone, web
├── digital.md      — bullets of public-source intel (auto-merged on re-ingest)
├── people/         — contacts discovered over time (empty initially)
├── calls/          — call recordings + transcripts (empty initially)
└── deals/          — qualified opportunities (empty initially)
```

Personas (your practice partners) get auto-created **under** an org as you
discover contacts during real calls — see [post-call extraction](architecture.md#post-call).

## Adapter menu

### `website` — single URL → one org · **free, works tonight**

```bash
# From the repo root
python3 -m adapters.website https://acme-finance.com
python3 -m adapters.website acme-finance.com --zone "End Customer"
```

Fetches the homepage, strips to text, runs an Ollama Gemma extraction pass,
writes `organizations/acme-finance/`. No API key needed. ~30 seconds per URL.

If the site is a JS-rendered SPA, the simple HTTP fetch will return very
little text. In that case use Firecrawl (TODO) for a real headless crawl.

### `google_places` — location + category → many orgs · **needs API key (free tier)**

```bash
export GOOGLE_PLACES_API_KEY="AIza..."

# List dentists near Portland
python3 -m adapters.google_places \
    --location "Portland, OR" \
    --radius 25mi \
    --type dentist \
    --limit 20 \
    --dry-run

# Same but write skeleton orgs (Places metadata only — fast)
python3 -m adapters.google_places \
    --location "Portland, OR" \
    --radius 25mi \
    --type dentist \
    --limit 20

# Same but also crawl each business's website (slow but full intel)
python3 -m adapters.google_places \
    --location "Portland, OR" \
    --radius 25mi \
    --type dentist \
    --limit 20 \
    --ingest-websites
```

**Use case:** *"I'm starting a local AI/web agency, I want to call every
dentist within 25 miles of Portland."* One command gets you 80 populated
org folders with phone numbers, websites, and AI-extracted company
descriptions — ready to dial.

**Cost:** Google Places gives a $200/mo free credit. Nearby Search is
$32/1000 requests. You can do thousands of searches/month for free.

**Setup (10 min, one-time):**
1. Create a Google Cloud project at [console.cloud.google.com](https://console.cloud.google.com)
2. Enable [Places API (New)](https://console.cloud.google.com/apis/library/places.googleapis.com)
3. Enable billing (required even for free tier — they pre-auth a card but don't charge)
4. APIs & Services → Credentials → Create Credentials → API Key
5. Restrict the key to the Places API (recommended for security)
6. `export GOOGLE_PLACES_API_KEY="AIza..."`

**Common Place Types:** `dentist`, `lawyer`, `restaurant`, `real_estate_agency`,
`accounting`, `electrician`, `plumber`, `gym`, `bakery`, `car_repair`,
`hair_care`, `pet_store`, `veterinary_care`, `auto_parts_store`.

Full list: [Google Places types](https://developers.google.com/maps/documentation/places/web-service/place-types).

### `osm` — same as Google Places, no auth · **TODO**

Free, no key, no billing. Uses the Overpass API on OpenStreetMap. Quality
is lower in suburbs but it gets you started.

### `csv` — bulk import from existing CRM · **TODO**

Drop a CSV export from HubSpot, Salesforce, Pipedrive, Airtable. Column
mapper UI. Creates one org per row.

### `firecrawl` — deep multi-page crawl · **TODO**

For when `website` returns too little (JS-rendered SPAs, multi-page
companies where the about / team / careers page have the real intel).
Requires a Firecrawl account (~$16/mo).

### `hubspot` / `salesforce` — OAuth CRM sync · **commercial tier**

Two-way sync with your existing CRM. Lives in the hosted product, not the
OSS repo (auth complexity + per-customer security review aren't worth
maintaining on the open side).

## Recommended workflow for "I'm building a sales op from scratch tonight"

### If you're selling to local businesses

```bash
# 1. List businesses nearby (~10 minutes once you have the Places key)
python3 -m adapters.google_places \
    --location "Your City, ST" \
    --radius 30mi \
    --type "your-target-category" \
    --limit 50 \
    --ingest-websites

# 2. Open the sales floor — 50 walking characters, one per business
open floor/index.html

# 3. Click any character → dossier with auto-extracted intel + the phone number
# 4. Click Practice Call → AI roleplay before you actually dial
# 5. Dial. Record the call. Drop it in organizations/<slug>/calls/.
# 6. python3 personas/manage.py debrief <slug>/<call-folder>     [TODO]
#    → extracts new people, updates deal stage, drafts follow-up email
```

### If you're selling to enterprise B2B

Manual research is better than scraping for enterprise — you only have 20-50
target accounts, and you want to invest the curation time. Use:

```bash
# One website at a time, after manual research
python3 -m adapters.website https://target-account.com --zone "End Customer"
```

Then enrich with Tier 2 (real public talks):

```bash
python3 personas/manage.py ingest-talk <slug> "https://youtube.com/watch?v=..."
```

## What we deliberately don't do

- **LinkedIn scraping** — TOS violation, will get your account banned. The
  partner API requires a $50K+ enterprise relationship. If you need
  LinkedIn data, use Apollo / Phantombuster / Lusha as third-party
  middlemen (gray-market but tolerated).
- **Email scraping from random websites** — high false-positive rate
  (catches webmasters@, info@, junk addresses). Use Hunter.io's free tier
  (25 lookups/mo) for clean email-from-domain enrichment.
- **Phone number lookup beyond what's on the website** — paid services like
  ZoomInfo / Lusha do this but the OSS scope ends at what's publicly
  visible. If you need direct-dials, the hosted tier is the right surface.
