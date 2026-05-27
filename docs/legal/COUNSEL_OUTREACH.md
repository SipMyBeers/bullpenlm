# Counsel Outreach — Phase 0.5 → Phase 1 Unblock

> **What to send, who to send it to, what to ask for, what to pay.**
> This doc exists because the *only* remaining Phase 1 blocker is
> getting an attorney's eyes on the platform-level mechanics. Every
> code-side firewall check is green; the legal opinion is the last
> mile.

---

## What you need

A **two-hour engagement** with an attorney who has both of these
specialties (rare to find one person; OK to use one for each):

1. **MLM / FTC / Pyramid analysis** — Koscot/Omnitrition test
   familiarity, prior work on compensation structures involving
   commission + recruitment-adjacent activity, Stripe pattern-matching
   experience.
2. **1099 worker classification** — IRS 20-factor, plus state ABC
   tests (especially CA AB5, NJ 75-IIIA, NY/IL/LA Freelance Isn't
   Free).

Two hours is enough to read this packet, ask 3-5 questions over
phone/Zoom, and fill out `docs/legal/COUNSEL_REVIEW.template.md`.
Anyone quoting more than four hours for this scope is over-billing
unless they're going to also draft custom state-specific variants.

**Budget:** $1,000-$2,500 total ($500/hr to $1,250/hr depending on
firm tier + market). Solo attorneys with the right specialty are
typically $400-$600/hr and are the right fit here — Big Law is
overkill, and Big Law's MLM/employment partners typically have
3-month waitlists anyway.

---

## Who to reach out to

Don't post in /r/legaladvice. Don't go through ZenBusiness or Avvo's
matching engine. The specialties are narrow enough that you want to
go directly.

### Three avenues, ordered by yield:

**1. Specialist boutique firms (MLM/employment hybrid):**
   - **Thompson Burton PLLC** (Nashville) — `thompsonburton.com` — heavy
     direct-sales / MLM practice. Their FTC compliance group is
     literally who Beachbody and dōTERRA call.
   - **Grimes, LLC** (Salt Lake City) — `grimeslaw.com` — direct-selling
     specialty. Mark Rawlins, Spencer Reese have FTC backgrounds.
   - **Spencer Fane LLP** (Kansas City) — direct sales practice.
   - **Kelly & Hannaford** (San Diego) — boutique direct-sales / FTC.

**2. Worker-classification specialists:**
   - **Outten & Golden LLP** (NYC + SF + DC) — `outtengolden.com` — top
     employee-side firm; their partner Adam Klein is the AB5 expert.
     Pricier ($700+/hr) but unimpeachable.
   - **Schneider Wallace** (SF) — joint-employer / classification
     class actions.
   - **Solo or small-firm attorney in your state with employment-law
     focus** — for state-specific classification opinions, the local
     attorney often delivers more value per hour than the marquee
     firm.

**3. Subreddits + practitioner networks (for referrals, not for
   advice):**
   - `r/AskLawyers` — sometimes useful for "who specializes in X in Y
     state" referrals
   - **Lawyer.com**, **Martindale** — filter by "Franchise &
     Distribution" → "MLM/Direct Sales"
   - **State Bar of Oregon Lawyer Referral Service** — $35 for a
     30-min consult, can match to a specialty

### Local-to-Beers options (Oregon)

Beers Labs LLC is in Oregon. Some Portland/Salem options:

- **Tonkon Torp LLP** (Portland) — large general firm; their
  Employment + Labor group is competent but pricier
- **Stoel Rives** (Portland) — same tier
- **Buchanan Angeli Altschul & Sullivan LLP** (Portland) — boutique
  employment specialty; small enough to take a 2-hour project
- **Bullivant Houser** (Portland) — middle-market; sometimes takes
  scoped engagements

For the **MLM/FTC side specifically**, none of the Oregon firms have
deep practice. Better to use Thompson Burton (TN) or Grimes (UT)
remotely.

---

## What to send

Send a single email with these attachments / links:

### Required reading (in this order)

1. **`docs/COMP_AND_LEGAL.md`** — the canonical model. Lays out the
   three-role architecture, what the platform does and doesn't do,
   the XP firewall, the classification coach, the live-work gate.
2. **`ROADMAP.md`** — context on phases. They mainly need Phase 0.5
   section but glancing at Phase 1+ helps them understand stakes.
3. **`docs/legal/COUNSEL_REVIEW.template.md`** — the artifact you're
   asking them to fill out. Tells them exactly what their deliverable
   is.

### Code to spot-check (if they're code-literate; most are not)

4. `server/xp.py` — the two-ledger split + bucket validator
5. `server/gates.py` — the EarningInputs dataclass (no clout_xp
   field) + can_claim_live_prospect
6. `server/classification.py` — the IRS 20-factor + state veto logic
7. `tests/` — 29 firewall tests proving the structure holds in code

### Templates to review

8. `templates/legal/closer-agreement.md` — the actual contract template
9. `templates/legal/closer-disclosure.md` — required pre-signing
   acknowledgement
10. `templates/legal/operator-tos.md` — operator counterparty TOS
11. `templates/legal/dnc-acknowledgement.md` — TCPA acknowledgement

---

## Draft outreach email

```
Subject: 2-hour engagement — review of self-hosted sales-CRM platform mechanics (MLM/employment classification angles)

Dear [Attorney Name],

I'm the founder of Beers Labs LLC (Oregon) and BullpenLM, an
open-source self-hosted CRM / sales-training platform. We're at a
decision point I'd like to scope a small, focused engagement around
— and your [MLM compliance / worker-classification] background looks
like exactly the right fit.

Quick context, then the ask.

THE PLATFORM
- Each operator runs their own bullpen (a sales floor) on their own
  hardware. They hire 1099 closers, paper their own agreements with
  them, pay them directly.
- BullpenLM the *platform* is the software — Beers Labs LLC is the
  vendor. We are NOT a party to any closer agreement. We do not
  custody funds.
- The platform provides: legal-doc templates, an audit chain, a
  worker-classification coach (IRS 20-factor + state ABC),
  DNC/TCPA tooling, and a two-ledger XP firewall designed to
  structurally prevent the platform's gamification mechanics from
  taking pyramid-adjacent shape.

THE QUESTION
We've engineered three structural guarantees against the FTC's
Koscot/Omnitrition pyramid pattern. We want a qualified opinion that
the structure holds before we open distribution beyond a small
friend cohort.

Specifically:
1. Does our money-XP vs clout-XP separation + the allocation
   firewall (which prevents social/recruitment activity from
   influencing prospect routing) hold under Koscot analysis?
2. Does the Closer Agreement template, plus our state-aware
   classification coach (incl. CA AB5 / NJ ABC), defensibly support
   the 1099 framing?
3. Is the operator-pays-closer-direct architecture free from
   money-transmission / broker-dealer / Stripe-pattern-match
   exposure for Beers Labs?
4. Any jurisdictions where the design is fundamentally incompatible
   that we should flag in our operator onboarding?

THE ASK
A 2-hour engagement: 1 hour reading materials we provide + 1 hour
on a call with me to answer your questions and walk through your
findings. Deliverable: filled-out review template (we have one
prepared, exactly the questions you'd ask) that we'll commit to our
public repo so future operators can see the platform was reviewed.

Materials are clean and short — about 30 pages of documents plus
code we don't expect you to read unless you choose. The repo is at
github.com/SipMyBeers/bullpenlm if you want to look ahead.

I'm happy to send the full packet on confirmation. What's your
hourly + availability for a 2-hour scope this month?

Best,
Dylan Beers
Beers Labs LLC
dylan@ranger-beers.com
```

---

## What to negotiate

- **Flat-fee vs hourly:** if you can get a flat fee ($1,500-$2,500),
  prefer that. Reading + filling the template is a known scope.
- **NDA scope:** the platform mechanics are public (open-source MIT).
  No NDA needed for the platform-level review. If they push one,
  scope it narrowly — they shouldn't be looking at any operator-
  specific data anyway.
- **Engagement letter language:** ask for a "limited-scope opinion"
  rather than a "full legal review." Same work, very different
  malpractice insurance exposure for them, often translates to
  lower fee.
- **Timeline:** ask for 2 weeks turnaround. Phase 1 isn't on a
  burning fuse but the operator floor is small until this clears.

## What NOT to ask for

- Don't ask for a "comfort letter" or "no-action letter" — those are
  expensive and not what we need. We need their professional opinion
  on a specific structure.
- Don't ask them to draft custom state-specific agreement variants
  yet. That's Phase 1 work after they bless the base structure.
- Don't ask them to act as your counsel for any individual operator's
  bullpen — that's the operator's own job. We're getting platform
  review.

## When their review lands

1. Save the filled review at `docs/legal/COUNSEL_REVIEW.md` (no
   `.template`).
2. Commit + push to the repo.
3. Re-run `python3 server/phase_check.py` — the `counsel_review_filed`
   blocker should clear and `platform_ready: true` should appear.
4. Phase 1 (signed-binary distribution) is now structurally unblocked.

---

## What if counsel finds something?

Their review may surface required changes. That's fine — it's the
point. The template (`COUNSEL_REVIEW.template.md`) has a "Required
changes before Phase 1" section. Process:

1. Implement the changes (code or template edits).
2. Send the diff to counsel for sign-off on the change set.
3. Update `COUNSEL_REVIEW.md` to reflect that the changes were made.
4. Commit + push.

If counsel finds something fundamental (e.g. "this entire
architecture has FTC exposure in CA"), that's better to know now
than after 50 operators are running floors. Treat their hard finding
as a save, not a setback.
