# BullpenLM Alpha Program

Rules of engagement for the friends-and-family alpha cohort.

For the broader phase context, see `ROADMAP.md`.

---

## What the alpha is

A closed pre-Steam release where ~5-15 of Beers's hand-picked friends
run real bullpens on real Mac Minis / VPSs, with real cold calls + real
commissions + real legal docs. They are the first wave of operators.

The alpha is **not** a beta-test of features. It's a **stress-test of the
business loop**: can a friend who isn't a developer go from "I got a DM
from Beers" to "I closed a deal and paid my closer" in a month?

---

## Who's in

Tier 1 — Operators (Phase 0 cohort, ~5 friends):
- Personally known to Beers
- Have something they could realistically sell (existing book of business,
  a product, a service, or a clear idea they're willing to drive)
- Comfortable enough with tech to run an `install_macmini.sh` script
- Will give Beers honest feedback when something sucks

Tier 2 — Closers (~10-30):
- Invited by operators (not by Beers directly)
- Willing to sign the rep agreement + actually dial real prospects
- Don't need to be technical at all — they just hit the invite link in
  their browser

---

## What alpha members get

1. **Free Steam key at EA launch.** Tracked via the BullpenLM Discord
   "Alpha" role. When the Steam version goes live, Beers DMs a key to
   every Alpha role holder.
2. **First look at every feature.** New builds drop in `#alpha-builds`
   on Discord before any wider release.
3. **Direct line to Beers.** DM him in Discord; he reads everything.
4. **First-50 status badge** on their Steam profile post-launch (custom
   achievement: "Founding Operator" / "Founding Closer").
5. **Lifetime free updates.** Even when v1.0 prices up to $29.99 +
   paid DLC, alpha members keep all DLC free forever.

---

## What's expected of them

**Operators:**
- Run their bullpen for at least 30 days continuously
- Onboard at least 2 closers via real invite codes
- Log at least 1 real cold call against an AI buyer (for the AI-buyer
  feedback) and at least 1 real cold call to a real prospect (for the
  CRM feedback)
- File at least 1 bug report or feature request per week in
  `#alpha-feedback` (be specific — "the wizard's broken" doesn't help;
  "step 3 froze on submit when I picked invite-only + no Discord URL"
  does)
- Don't redistribute the install link publicly. It's still alpha. Steam
  is the eventual public channel.

**Closers:**
- Actually dial something. Even one practice call beats zero. The audit
  log + scoring loop only works if it has data.
- If you stop using it for 14+ days, your claims auto-release back to
  the pool. No notice needed.
- Honest feedback in `#alpha-feedback` — especially if a UI flow felt
  weird, a call went sideways, or you didn't understand what to do next.

---

## How to join

**As an operator (Beers hand-picks these):**

Beers DMs you with:
1. A link to `scripts/install_macmini.sh` and the one-line `curl | bash`
2. A walkthrough of running the wizard
3. The "Alpha" Discord role grant once your bullpen is live and you've
   posted in `#showcase` introducing your floor

**As a closer (invited by an operator):**

Your operator DMs you with their personalized invite link. Click it,
walk through the 3-step welcome wizard, sign the agreement, you're on
the floor. The operator then promotes you in the BullpenLM Discord
"Closer-Alpha" role manually for the first few cohorts, automated later.

---

## The 4 rules every alpha member agrees to

1. **No public sharing of install URLs.** Alpha invite links are
   personal. Steam is the public channel.
2. **Audit chain is sacred.** Don't manually edit `bullpens/<slug>/
   audit.jsonl` — verification breaks and we lose trust in every
   downstream record.
3. **Honest feedback over polite feedback.** If something sucks, say
   so. Vague positivity ("nice tool!") helps nobody. Specific complaints
   ("the founder onboarding wizard's step 4 was confusing because the
   LLC question implied I had to have one") ship the product.
4. **What's said in the alpha stays in the alpha.** Don't tweet
   screenshots of friends' commission rates, prospect lists, or call
   transcripts. Aggregate stats ("our floor hit 1,000 calls!") fine.
   Identifying details not fine.

---

## Feedback channels

| Channel | Use for |
|---|---|
| `#alpha-feedback` | Bugs, confusion, suggestions |
| `#alpha-builds` | New build announcements + changelogs |
| `#alpha-wins` | Brag about closes — keeps morale up |
| DM Beers | Anything sensitive (commission disputes, legal Qs, etc.) |
| GitHub Issues | If you're a dev + want to track + fix something yourself |

---

## Promoting from alpha to beta

Once Phase 0 → Phase 1 happens (signed Tauri installers ship), every
alpha role holder auto-upgrades to "Beta" and gets early access to the
new installers. The Discord welcome message updates to direct new
arrivals at the Beta program if they missed alpha.

---

## Withdrawing from alpha

If at any point you want out:
1. `rm -rf bullpens/<slug>/` on your host (wipes your floor entirely)
2. Drop your Discord roles
3. Notify your closers if you have any

Your free Steam key offer still stands when EA launches — alpha
participation is one-way (joining-only). You can't lose your spot for
quitting.

---

## What happens at Steam EA launch

Day-of:
1. Alpha role members get DM'd their free Steam keys
2. Beta role members same (Phase 1 cohort)
3. Steam version becomes the public install channel
4. `install_macmini.sh` stays in the repo as the self-host path — open
   source, always available — but the friction is now "do you want to
   manage your own install or let Steam do it?"

The alpha doesn't "end." It transitions to "founding members" — same
people, new title, full Steam version + DLC perks forever.

---

## Status tracker

| Cohort | Name (Discord handle) | Role | Bullpen slug | Status |
|---|---|---|---|---|
| Alpha-01 | beers (`@itsbeers`) | Operator | killsesh | Active |
| | | | | |
| | | | | |

Beers fills this in as friends join. Keep it private to the BullpenLM
Discord — don't commit alpha-member names to a public file. (This
table lives in the doc but the cells stay blank in the public repo.)
