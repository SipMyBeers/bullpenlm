# Social signals — the weakness identifier

The single most useful adapter for *outbound sales to local businesses*.

The idea: any company's homepage + public social presence already broadcasts
their weaknesses. Outdated CMS, dormant Twitter, broken mobile site, missing
SEO basics, last blog post 18 months ago. These become **cold-call openers
that don't sound like cold calls.**

## What it detects

### Tech stack
From inspection of the rendered HTML:

| Detected | Auto-generated opener |
|---|---|
| WordPress | *"I help companies migrate off WordPress to faster modern stacks before their next hosting renewal."* |
| Wix / Squarespace | *"I help businesses graduate to platforms that don't cap conversion features at the Premium tier."* |
| Shopify | *"Happy to discuss apps that lift average order value or fix abandoned-cart leak."* |
| jQuery | *"Your site still leans on jQuery — I help modernize legacy front-ends without breaking SEO."* |
| Universal Analytics (UA) | *"You're still on Universal Analytics, which Google sunset in 2023 — your traffic data has been incomplete."* |
| (No CMS / payment / analytics detected) | Possibly the right opener is *"What's your current stack?"* |

Plus passive detection of: React, Vue, Next.js, Angular, GA4, Plausible,
Mixpanel, Segment, HubSpot, Marketo, Pardot, Stripe, Square, PayPal,
Calendly, Typeform.

### Social presence

Pulls URLs found anywhere on the homepage:

- LinkedIn company page
- Twitter / X profile
- Facebook business page
- Instagram, YouTube, TikTok, GitHub

If any of LinkedIn / Twitter / Facebook is **missing**, that's flagged as a
weakness and a corresponding opener gets generated.

### Freshness

- **Copyright year** — if it shows last year or earlier, "© 2024 in mid-2026" is a tell
- **Dates referenced anywhere on the page** — if the newest visible date is 2+ years old, content is dormant
- **Mobile viewport meta tag** — missing = mobile experience broken
- **HTTPS** — basic security check
- **SEO basics** — `<meta description>`, Open Graph tags

### Email patterns

If a `mailto:` link exists for an actual person (skipping `info@` / `hello@`),
we capture the pattern as a sample. Useful for guessing direct emails of
others at the same company.

## What it does NOT do

- **No LinkedIn personal-profile scraping** — TOS violation, kills accounts
- **No private/auth-gated data** — only the public homepage + public social URLs
- **No deep multi-page crawl** — that's what the `firecrawl` adapter is for
- **No paid-API enrichment** — Hunter, Apollo, ZoomInfo all live in the
  hosted tier

The adapter intentionally stops at "what would a senior account exec see
in 3 minutes of public research." More than that and you're either
violating ToS or you're slow.

## Using it

```bash
# Analyze any URL
python3 -m adapters.social_signals https://localdentist.com

# Write the signals to a specific org folder
python3 -m adapters.social_signals https://localdentist.com --org dr-smith-dental
```

Output: a `signals.md` written to `organizations/<slug>/signals.md` with
the openers + weaknesses + strengths + tech stack + social URLs sections,
plus a parallel `signals.json` for programmatic use.

## Reading the output

The `signals.md` always starts with the **▸ Cold-call openers** section —
the highest-signal info, ready to read verbatim on a call. Each opener is
phrased as something you could literally say to whoever picks up:

```markdown
## ▸ Cold-call openers (ready to read)

- *"I notice you don't have an active LinkedIn presence. Your competitors do. Want to talk?"*
- *"Your site is still running WordPress 5.x — happy to help you migrate before the next CVE."*
- *"Your latest visible content shows 2024-03 — I help businesses revive a dormant blog without hiring a full-time writer."*
```

That's your script. Pick the most relevant one for the call you're about
to make.

## Integration with the rest of BullpenLM

When you click "Brief" in the org dossier (the `/api/brief` endpoint),
the pre-call brief generator reads `signals.md` and `signals.json` if
they exist, and includes the weaknesses in the brief output.

So the workflow looks like:

```
1. Pull 100 local businesses via OSM or Google Places
2. For each, run social_signals to detect weaknesses
3. Sort by "most weaknesses" — that's your priority dialing order
4. Click the top one in the floor → Brief tab → generate brief
   → see weaknesses inline as openers
5. Make the call · auto-debrief on hangup
```

That's the loop.

## Roadmap

Not built yet, in priority order:

1. **Google reviews / rating sentiment** — pull via Places API (you already have the key from the `google_places` adapter), surface low-rated complaints as openers (*"Your Google reviews mention slow response times — that's where I help."*)
2. **Glassdoor public review sentiment** — public-facing review pages, extract themes about tech / culture / management complaints
3. **Job-posting count** — scrape `/careers` to count open roles; pain signal if 10+ open positions stuck for 6+ months
4. **Last-tweet timestamp scrape** — read Twitter's public profile page (no auth) for the timestamp of the most recent post
5. **LinkedIn company-page headcount estimate** — public-page only; surface "company shrank 15% in last year" as a signal
6. **Press / news scraper** — recent news mentions via Google News RSS

Each of these is its own ~1-hour add. PRs welcome — the adapter format is
documented in `docs/data-sources.md`.
