# BullpenLM Roadmap

The product **doesn't change** as it ships through these phases. Same Python
server, same Cloudflare tunnels, same audit log, same real-CRM and real cold
calls. What changes is **how it's distributed**, **who's allowed in**, and
**how legally airtight the platform mechanics are**.

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Phase 0     │   │  Phase 0.5   │   │  Phase 1     │   │  Phase 2     │   │  Phase 3     │
│  ALPHA       │ → │  FIREWALL    │ → │  CLOSED BETA │ → │  STEAM EA    │ → │  STEAM 1.0   │
│  (now)       │   │  (1-3 weeks) │   │  (~1-2 mo)   │   │  (~3-4 mo)   │   │  (~6-9 mo)   │
│              │   │              │   │              │   │              │   │              │
│  hand-picked │   │  legal +     │   │  signed app  │   │  Steam train │   │  + Workshop  │
│  friends     │   │  XP firewall │   │  + auto-upd. │   │  + Cloud     │   │  + DLC packs │
│  invite-code │   │  + counsel   │   │  + classif.  │   │  + Friends   │   │  + Workshop  │
│  Discord     │   │  sign-off    │   │  coach live  │   │  + EA price  │   │  + 1.0 price │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
   ~5 friends        same ~5 +         ~50 operators       ~500 wishlist     ~thousands
                     hardened plat
```

> **The framing that matters:** the gamified training sim and the real
> commission floor are *two products in one binary*. Steam will host the
> sim. Steam will NOT host the floor (real-money commission + real
> external customers is commerce, not a game, by Valve's standard). The
> floor lives on the operator's self-hosted instance. The Steam game is
> top-of-funnel; the self-hosted floor is the business. Both are real.
> Neither scales until Phase 0.5 ships.

---

## Phase 0 — ALPHA (today)

**Status:** Live. You are here.

### Distribution
- `curl install_macmini.sh | bash` on the operator's Mac Mini / VPS
- Cloudflare Quick Tunnel for the public URL (ephemeral)
- Per-friend invite codes via DM, redeem at `https://<tunnel>/app/join.html?code=…`

### Who's in
- Beers's hand-picked friends
- Each operator runs their own bullpen on their own machine
- KillSesh is the first product being sold
- **Floor stays small until Phase 0.5 lands.** Real product, real
  commission — but the closer count is intentionally capped at ~15 across
  all bullpens combined while the platform mechanics get hardened.

### Build work remaining
Nothing on the alpha distribution itself. See `docs/LAUNCH_DAY.md` for the
operator pre-flight ritual + friend-DM template.

### Exit criteria for moving to Phase 0.5
- 5+ friends are running their own bullpens (operator role)
- 10+ closers have signed agreements and logged at least one real call
- First close-won deal logged with a real client + commission paid
- At least one friend invites another friend without Beers's involvement
- `docs/LAUNCH_DAY.md` has been used by at least one non-Beers operator
  successfully

### Success metric
**Word of mouth + zero legal surprises.** Phase 0 succeeds if a friend
texts another friend "yo get on bullpenlm" without Beers asking, AND no
operator runs into a closer-pay dispute, classification challenge, or
Stripe pattern-match flag during the alpha window.

---

## Phase 0.5 — LEGAL & XP FIREWALL (1-3 weeks)

**Status:** Active build. Blocks all scaling.

This phase exists because the floor (real commission, real customers,
real closer-as-1099) is the real product, and it has to be airtight at
the platform-mechanics level before more than 15 closers exist on the
network. The work is structural, not cosmetic — once it's in code, the
"is this MLM-adjacent?" question has a code-level answer instead of a
copy-tweak answer.

### Why this phase exists

Two specific risks the platform mechanics have to extinguish:

1. **The pyramid silhouette.** FTC's Koscot/Omnitrition test asks whether
   earnings trace to product sold to real external customers, or to
   recruitment + promotion of the opportunity itself. Stripe pattern-
   matches the same shape and quietly kills accounts.
2. **The allocation-layer leak.** Even with separate "money" and "clout"
   XP buckets, if clout-XP drives *which closers get the juicy
   prospects*, then clout-XP converts to money one hop removed. The
   firewall has to extend to the allocation layer, not just the
   commission percentage.

### Build work

1. **`server/xp.py` two-ledger refactor.** Every `RULES` entry gets a
   `bucket: "money" | "clout" | "none"` tag. Money-XP is awarded only on
   closed deals + outcome-tagged drill certifications. Clout-XP is
   awarded for posts, attendance, drill volume, social activity.
   Recruiting another closer awards **zero of either** — not a "clout"
   reward, zero. Inviting flow is a button with no XP attached.
2. **Allocation firewall** in `server/team.py` + `server/gates.py`. The
   `team.claim()` priority function takes only `money_xp`,
   `drill_certification_score`, and historical `close_rate` as inputs.
   The signature does not accept `clout_xp` — it's structurally
   unrepresentable. Leaderboards can show clout-XP for vanity, but the
   leaderboard cannot route prospects.
3. **`server/entity.py` — operator entity profile.** Every bullpen
   captures the operator's legal entity (LLC / sole prop / individual),
   legal name, EIN/SSN, jurisdiction. Every generated doc renders from
   this; "Beers Labs LLC" never appears on a closer agreement.
4. **`server/classification.py` — IRS 20-factor coach.** Wizard walks
   the operator through the 20-factor + state-aware (CA AB5, NJ 75-IIIA,
   NY/IL/LA Freelance Isn't Free) questions when they set up commission
   terms. If their answers describe an employee, the wizard refuses to
   render a 1099 Closer Agreement and explains why.
5. **`templates/legal/` — closer agreement bundle.** Closer Agreement
   (1099 framework), W-9, Mutual NDA, Code of Conduct, DNC
   Acknowledgement, Closer Disclosure (BullpenLM is not your employer),
   Operator TOS (you are the counterparty, you carry the risk). All
   render with `{{operator_entity}}` substitution. Legal text marked
   PLACEHOLDER awaiting counsel review.
6. **`server/disclosures.py` + `server/gates.py` — live-work gate.** A
   closer cannot be assigned a real prospect (only AI-buyer drills)
   until (a) signed Closer Agreement on file w/ SHA, (b) W-9 on file,
   (c) drill certification cleared, (d) jurisdiction compliance check
   passed, (e) DNC scrub completed for the target. The platform does
   not sign the agreement (BullpenLM is on no contracts), but it
   refuses to allow live work without proof the off-platform agreement
   exists.
7. **`server/dnc.py` — telemarketing tooling.** DNC scrub against
   donotcall.gov + state lists before any prospect can be claimed.
   Two-party-consent prompts wired by jurisdiction. Hours-of-day
   enforcement (no 9pm dials in CA). Operator certifies compliance; the
   platform makes compliance trivial.
8. **`docs/COMP_AND_LEGAL.md` — canonical model.** Written down so
   counsel has a single artifact to review: platform-tooling vs
   operator-counterparty vs closer-1099. What we won't touch (escrow,
   money rails, mediation, classification calls). The counsel-review
   checklist before non-friend operators are allowed in.
9. **MLM/securities + worker-classification counsel sign-off.** One hour
   minimum. Reviews: platform XP mechanics, the closer agreement
   template, the operator TOS, jurisdiction warnings. Counsel signs off
   before Phase 1 starts.

### Who's in
- Same Phase 0 friends — no new closers, no new operators during
  Phase 0.5. The point is to harden the platform before scale.

### Exit criteria for moving to Phase 1
- `server/xp.py` ships the two-ledger split with passing tests on both
  the money/clout separation AND the allocation-layer firewall.
- `team.claim()` priority function signature is type-system-enforced to
  reject clout-XP.
- At least one closer agreement renders with a real operator's entity,
  is signed by closer + operator (both hashes in the audit log), and
  the live-work gate is verified blocking unsigned closers.
- Classification coach refuses to render a 1099 for at least one
  obvious-employee answer set.
- DNC scrub is live and blocking dials to listed numbers.
- Counsel review complete. Sign-off recorded as `docs/legal/COUNSEL_REVIEW.md`
  in the repo, with date + jurisdictions blessed.

### Success metric
**Zero pyramid-shaped paths in the code.** Verified by a code review
that grep's for any function consuming clout-XP that also influences
prospect routing, commission %, payout amount, or invite priority. Zero
hits, or the phase isn't done.

---

## Phase 1 — CLOSED BETA (1-2 months from Phase 0.5 exit)

**Status:** Build phase. Engineering scope is well-defined. Blocked by
Phase 0.5 — no signed binaries go to non-friends until the firewall is
in code.

### What changes
- **Tauri app replaces the curl-install ritual.** Operators download a
  `.dmg` / `.exe` / `.AppImage` from `bullpenlm.com/download`. No SSH, no
  cloudflared command, no Python knowledge required.
- **PyInstaller-bundled Python sidecar.** The Tauri app spawns the server
  as a bundled binary — operator's machine doesn't even need Python.
- **Signed installers.** Apple Developer cert ($99/yr) for macOS
  notarization, Windows Authenticode cert ($200-500/yr) for SmartScreen
  acceptance.
- **Auto-updater.** Tauri's built-in update channel ships patches
  silently. No more "git pull && restart."
- **Named Cloudflare Tunnels** (optional, recommended) — operators with a
  domain can route the tunnel through `app.theirdomain.com` instead of
  the ephemeral `<random>.trycloudflare.com`.
- **Operator onboarding gate.** Before a new operator can invite
  closers, they complete entity setup + classification coach + accept
  Operator TOS. The Phase 0.5 firewall is enforced on every new
  operator.

### Build work
1. PyInstaller spec file that bundles `python3 server/server.py` + all deps
   (whisper, ffmpeg, certifi, pyyaml) into a single executable. ~1 week.
2. Tauri sidecar wiring — `desktop/src-tauri/Cargo.toml` declares the
   bundled binary, `lib.rs` spawns it instead of shelling out to
   system `python3`. ~3 days.
3. `.github/workflows/release.yml` runs `tauri-apps/tauri-action` on every
   `v*` git tag → builds + uploads `.dmg` / `.exe` / `.AppImage`. ~2 days.
4. Apple Developer enrollment + Mac code signing + notarization workflow.
   ~1 week including waiting for Apple.
5. Windows code signing cert (Sectigo or DigiCert) + signtool integration.
   ~1 week including cert delivery.
6. Auto-updater hooked up to GitHub Releases. ~3 days.
7. **bullpenlm.com/download** landing route that auto-detects OS + serves
   the right installer. ~1 day.

**Total engineering:** ~3-5 weeks of focused work.

### Who's in (closed beta)
- Phase 0 alpha cohort (auto-promoted, no re-onboarding required)
- Each alpha friend invites 2-3 of their friends (the "+2 invites" model)
- **New operators must clear the firewall onboarding** — entity setup,
  classification coach, signed Operator TOS — before they can invite
  closers
- BullpenLM Discord "Beta" role auto-grants when an alpha verifies they
  installed the signed app

### Exit criteria for moving to Phase 2
- Tauri installer works on a clean Mac + clean Windows machine, signed,
  notarized, no security warnings
- Auto-updater has pushed at least one patch successfully without bricking
  any operator
- 50+ operators across both macOS and Windows
- 100+ closers across all bullpens have completed the live-work gate
  (signed agreement + W-9 + drill cert + jurisdiction OK)
- Zero classification disputes (no operator has had a closer challenge
  1099 status with their state DOL)
- Steam Direct application approved + app ID issued (apply early —
  approval is 1-4 weeks)
- 1,000+ wishlists on the Steam store page

### Success metric
**Install friction is gone AND the firewall holds at scale.** A
non-technical friend can go from "bullpenlm.com" link to "running my
floor" in under 5 minutes without typing a single shell command — but
they cannot dial a real prospect until the onboarding gate is cleared.

---

## Phase 2 — STEAM EARLY ACCESS (3-4 months from now)

**Status:** Plan locked, awaiting Phase 1 + Steam approval.

> **Critical scope clarification:** the Steam build is the *training
> sim*, not the full bullpen. AI-buyer drills, ranks, leaderboards,
> achievements, cosmetics, PvP duels — all on Steam. The real-customer
> commission floor stays on the operator's self-hosted instance (the
> Tauri app from Phase 1). The Steam title is top-of-funnel for the
> floor. Valve will not host real-world commission/recruitment commerce,
> and we don't ask them to.

### What changes
- **Distribution = Steam.** Operators search "BullpenLM" on Steam, hit
  Install, the bundled sim downloads. From inside the sim, an "Open My
  Floor" button launches the self-hosted Tauri app (or prompts to
  install it). Steam handles updates, refunds, and payment processing
  for the SIM. The FLOOR's money flow stays operator-direct.
- **Steam Friends replaces invite codes** for *the sim's* PvP and
  leaderboard side. Floor invites still go through invite codes (real
  legal flow).
- **Steam Cloud syncs sim-side progress** — rank, drill history, drill
  certifications. Floor data (real CRM, signed docs, real calls) stays
  local-only by default; an opt-in encrypted Steam Cloud backup is
  available but disabled by default.
- **62 in-game achievements become Steam achievements** via Steamworks
  SDK. Same triggers, sim-side only.
- **EA pricing: $19.99 one-time.** No subscription, no DLC at EA. Buying
  the game does not grant any closer-side earning capability — the
  earning side is gated by the firewall onboarding, period.

### Build work
1. Steamworks SDK integration via the `steamworks` Rust crate
   (feature-gated, off in Phase 1 builds). ~2 weeks.
2. Achievement-publishing bridge — every existing sim-side achievement
   unlock calls `steamworks::Client::user_stats().set_achievement(…)`.
   ~3 days.
3. Sim/floor split — clear partition between what's Steam-distributed
   (sim) and what's self-hosted (floor). ~1 week.
4. Steam Cloud bridge (sim-side only). ~1 week.
5. Steam Friends integration for sim's PvP/leaderboard. ~1 week.
6. Steam store page (see `docs/STEAM_LAUNCH_PLAN.md`):
   - Title, short desc, long desc, tags, capsule images, hero image,
     screenshots, trailer.
   - Age rating + content warning forms.
7. Steam Direct submission + content review wait. ~2-4 weeks.

**Total engineering on top of Phase 1:** ~4-6 weeks.

### Who's in
- Anyone who buys the sim on Steam ($19.99 EA price)
- Phase 0 alpha + Phase 1 beta cohorts get **free Steam keys** as thanks
- Floor access (real commission work) remains gated by the Phase 0.5
  firewall — Steam buyers who want to run a real bullpen go through the
  same entity setup + classification coach + signed TOS as any other
  operator

### Exit criteria for moving to Phase 3
- 500+ Steam owners (sim side)
- "Very Positive" Steam review rating (>80% positive)
- All core multiplayer flows are stable across 100+ concurrent operators
- At least one operator has run their bullpen for 90+ days continuously
  with no audit-chain breaks
- Zero Stripe / counterparty / classification disputes in the floor side
  during Phase 2
- DLC content pipeline tested (one pack shipped to alpha for feedback)

### Success metric
**Real commissions paid through operator-direct rails recorded in the
audit chain.** Phase 2 succeeds when operators are actually paying
closers monthly (Stripe / Wise / Zelle / USDC — any rail they choose,
direct between them) and the audit chain records every payment for
year-end 1099-NEC prep. Until cash moves and the firewall holds at
scale, the floor is a fancy practice tool with extra steps.

---

## Phase 3 — STEAM 1.0 (6-9 months from now)

**Status:** Aspirational. Locked once Phase 2 metrics hit.

### What changes
- **Price up to $29.99.** EA → full release transition.
- **DLC packs** drop quarterly. First three planned:
  - *Wall Street '85* — Boiler-room aesthetic pack, vintage prospect persona library, retro UI theme.
  - *SaaS Slingers* — Modern B2B SaaS persona library + objection trees.
  - *Boutique* — Solo / creative-services persona pack (designers, consultants, freelancers).
- **Steam Workshop** for community-uploaded persona libraries. Top
  uploaders get revenue share **on the sim**, not on the floor.
- **Controller support + Steam Deck verification** — 10× store visibility.
- **Localization** — en → es, pt-BR, ja, de. The four highest-leverage
  languages for sales-game audiences.
- **Twitch streamer mode** — anonymizes prospect data so the app is
  streamable without leaking the operator's real CRM. PII tokens get
  replaced with `[PROSPECT_001]` on screen, full data persists in the
  underlying audit log.

### Build work
TBD based on Phase 2 metrics. The roadmap from Phase 2 → Phase 3 is
about content + localization + polish, not core engineering.

### Success metric
**Steam Deck verified + 5,000+ owners + 70%+ retention at 30 days.** At
that point BullpenLM-on-Steam is a real product with a real business
behind it, and the next move is either:
- Lean further into game/community (sequels, expansions, esports)
- Spin off a separate enterprise SKU (B2B sales-team licensing) using
  the same engine

---

## Cross-phase commitments

These never change as we move through phases:

1. **Self-hosted forever.** Every operator owns their data. BullpenLM is
   not a SaaS in any phase. Steam distributes the sim; the floor runs
   on the operator's machine.
2. **Open source forever.** The repo stays MIT. Free for anyone who
   wants to run their own bullpen without Steam.
3. **Audit chain integrity.** Every mutation flows through
   `audit.append()`. Operators can verify the chain at any time. No
   "trust the platform" — the chain is the trust.
4. **Real-CRM real-money real-calls.** Never fictionalized for any
   platform. The Steam sim drills against AI buyers; the self-hosted
   floor handles real customers. Both are real to what they are.
5. **Closer protections.** Every closer signs the auto-rendered legal
   agreement *with the operator* (BullpenLM is on no contracts).
   Settlement runs operator-direct on the rail they pick. BullpenLM
   never custodies funds.
6. **Platform on no contracts.** BullpenLM provides the tooling;
   operators carry the counterparty relationship. The platform refuses
   to be escrow, judge, or insurer. Operator TOS makes this explicit
   and is enforced at every gate.
7. **Two-ledger XP forever.** Money-XP and clout-XP never merge.
   Recruitment never pays.
8. **No earning without certification.** Drill cert + signed agreement
   + W-9 + jurisdiction OK gates every live-prospect claim, in every
   phase, in every distribution channel.

---

## How phase transitions work

Moving from Phase N → Phase N+1 requires:
1. Hitting that phase's **exit criteria** (above)
2. The next phase's **build work** is verified shippable (smoke tests +
   3 days of soaking on Beers's own bullpen)
3. The Phase N+1 plan doc is finalized (`docs/COMP_AND_LEGAL.md` +
   counsel sign-off for Phase 0.5, `docs/STEAM_LAUNCH_PLAN.md` for
   Phase 2, future TBD for Phase 3)
4. Beers personally signs off — phase transitions are commitments to
   downstream operators, not just engineering milestones

Phases don't roll back. If Phase 2 ships and there's a critical bug,
fix it in place; don't revert to Phase 1.

---

## Where to look next

- **Phase 0 mechanics:** `docs/LAUNCH_DAY.md`
- **Phase 0.5 model + counsel checklist:** `docs/COMP_AND_LEGAL.md`
- **Phase 1 + 2 Steam specifics:** `docs/STEAM_LAUNCH_PLAN.md`
- **Alpha program rules:** `docs/ALPHA_PROGRAM.md`
- **Security posture:** `SECURITY.md`
- **Architecture:** `HANDOFF.md`
