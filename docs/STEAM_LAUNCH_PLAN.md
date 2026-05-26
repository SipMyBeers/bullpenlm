# Steam Launch Plan

How BullpenLM gets onto Steam. Concrete checklist + store-page draft +
SDK integration notes + pricing decisions.

For the broader phase context, see `ROADMAP.md` at the repo root.

---

## 0. Pre-application: decide before paying $100

Steam Direct charges a non-refundable **$100 per app** to submit. Before
clicking submit, lock these:

| Decision | The call |
|---|---|
| **App name** | `BullpenLM` (matches the open-source repo + bullpenlm.com) |
| **Genre tags** | Simulation · Indie · Multiplayer · Massively Multiplayer · Strategy · Sandbox |
| **Single-player or MP?** | "Online co-op" + "Massively Multiplayer." NOT single-player — Steam reviewers see "single-player simulation" and expect different things. |
| **Mature content?** | No nudity/violence. Mild profanity in AI buyer dialog (Belfort-voice). Rate `Teen` or `Mature` depending on profanity filter setting. |
| **Real-money element?** | The game does NOT involve real-money gambling or in-game purchases. Closers earn real-world commissions through their OWN business arrangements outside the app — the app generates invoices, not transactions. **This is the right framing on the application:** the game tracks calls and outcomes; payment happens out-of-band between operators and closers via Stripe/PayPal/etc. that THEY arrange. |
| **Online required?** | Yes (closers connect to operator's host via Cloudflare tunnel). |
| **Localization at launch?** | English only at EA. Spanish + Portuguese-BR for v1.0. |

---

## 1. Steam Direct application

```
1. Beers logs into partner.steamgames.com with his Steam account
2. Click "Submit an app"
3. Pay $100 USD (non-refundable, per app)
4. Fill out:
   - Company name: Beers Labs LLC (matches your other legal docs)
   - App title: BullpenLM
   - Release date: TBD (set to "Q1 2026" or whichever quarter Phase 1
     exits)
   - Tax forms + bank info (Steam payout setup)
5. Wait for app ID approval (1-4 weeks typically)
6. Once approved, you get a Steam app ID — that's the integer Steamworks
   SDK calls require.
```

**Don't skip:** the tax forms can stall the whole process. Steam needs
a W-9 (US) before they can pay you. Submit those the same day you pay
the $100 so they're processed in parallel.

---

## 2. Store page draft

This is the page Steam shoppers see at `store.steampowered.com/app/<id>`.
Steam allows iteration on the store page even after submission, but
having it ready means you can flip wishlist-on within days of approval.

### Title

```
BullpenLM — Multiplayer Sales Floor
```

### Short description (≤300 characters, shown in search results)

```
Run a real sales floor with your friends. AI buyers built from real
prospects. Live leaderboard, raids, real-money commissions. Self-hosted
multiplayer — your data never leaves your machine. Open source.
```

### Long description (Steam Markdown — supports `[h1]`, `[b]`, `[list]`)

```
[h1]Run a real sales operation. With your friends. As a game.[/h1]

BullpenLM turns your group chat into a multiplayer sales floor. You're
the operator: pick what you sell, invite closers, set the commission
rate. Your closers cold-call real prospects against AI buyers trained
on the actual companies they'll be pitching — then dial the real human
when they're ready.

[b]Every call is real. Every close is real. Every commission is real.[/b]

[h1]What you do[/h1]
[list]
[*][b]Build your bullpen.[/b] 60 seconds in the wizard — name it, pick
a commission rate, choose your closers' tier ladder.
[*][b]Recruit through Steam Friends.[/b] One click invites your buddies
to your floor. They install BullpenLM, accept your invite, they're on
the phones.
[*][b]Practice against AI.[/b] Local Ollama LLM plays the prospect.
Tuned per-vertical — BFSI buyers sound like BFSI buyers, SaaS buyers
sound like SaaS buyers. No internet required for practice.
[*][b]Dial real prospects.[/b] When your closers are warm, they hit the
phones for real. Calls log to a hash-chained audit trail. Cryptographic
proof of every deal.
[*][b]Climb the leaderboard.[/b] XP per call, classes (Hunter, Closer,
Strategist, Mentor) at Level 5, 62 achievements, raids with your squad,
1v1 duels.
[*][b]Pay closers automatically.[/b] On the 1st of each month, BullpenLM
generates per-closer invoices from the audit log. You pay via Stripe,
PayPal, Wise, USDC — whichever method your closers picked at onboarding.
[/list]

[h1]Why this is on Steam[/h1]
Steam is the install. We're not making a sales-themed minigame — we're
making real sales infrastructure that you and your friends actually use.
Steam handles the install + updates + friend graph + cloud sync.
Everything else lives on your machine. Self-hosted. Open source. Forever
free to inspect, fork, modify.

[h1]How "real" is "real"?[/h1]
[list]
[*]Real cold calls (the rep dials a real prospect, log goes into the
audit chain).
[*]Real commissions (the closer earns a real % of what they originate).
[*]Real legal docs (the sales-commission agreement renders with your
LLC + state + commission tiers, ready to sign and send).
[*]Real invoices (auto-generated monthly, in markdown + PDF-ready,
paid by you to your closer through whatever method you both agreed on).
[*]Real audit chain (hash-chained JSONL, verifiable any time).
[/list]

Self-hosted: your closers' data lives on your machine. Steam pushes
the install + updates + friend invites; your bullpen data flows through
your own Cloudflare tunnel direct to your host. We never see any of it.

[h1]Wait, is this a game or a CRM?[/h1]
Yes.

[h1]Open source[/h1]
[url=https://github.com/SipMyBeers/bullpenlm]github.com/SipMyBeers/bullpenlm[/url]
— MIT licensed. The Steam build wraps the same code. If you'd rather
self-install without Steam, the install script's right there.
```

### Tags (max 20 — pick the most-searched ones first)

```
Simulation, Indie, Massively Multiplayer, Online Co-Op, Sandbox,
Strategy, Resource Management, Building, Tycoon, Real Time,
Crime, Business Sim, Multiplayer, Open World, Procedural Generation,
Local Multiplayer, Customization, Economy, Co-op Campaign, Trading
```

### Capsule + hero images needed

- **Main capsule** (616×353) — hero typography "BULLPENLM" + "MULTIPLAYER SALES FLOOR" tagline
- **Vertical capsule** (374×448) — same brand, taller
- **Header / library capsule** (920×430)
- **Library hero** (3840×1240)
- **Library logo** (1280×720)
- **Screenshots × 5 minimum:** today.html (floor view), training.html (Top Pack), profile.html (rep card), live call coaching, leaderboard
- **Trailer** (60-90s) — Bumblebee montage stitched over real gameplay screencaps. Use the welcome.mp3 you already curated as the audio bed.

### Trailer brief

```
0:00-0:03  Black screen → phone ring (your taps/ clip)
0:03-0:08  Belfort: "PICK UP THE PHONE!" + cut to a closer on a call
0:08-0:15  Quick cuts: claim a prospect, briefing card, AI buyer dialog
0:15-0:25  Floor view — leaderboard ticking up, achievements popping
0:25-0:35  Close-won animation, invoice generates
0:35-0:45  Belfort: "money doesn't sleep" + cut to friend joining
           via Steam invite
0:45-0:55  Wide shot of the bullpen floor with multiple closers active
0:55-1:00  Logo + "Wishlist now" CTA + Steam button
```

The clips/ library already has most of these stitched. Re-render
welcome-with-floor-footage.mp4 closer to launch.

### Age rating + content warnings

Submit for both ESRB and PEGI. Expected outcomes:
- **ESRB:** Teen (T) — mild profanity in AI buyer dialog, no nudity/violence.
- **PEGI:** 12 (mild language).

If you want to allow uncensored Belfort-voice and the audio clips with
full profanity → Mature (M) / PEGI 16. Recommended: ship Teen + add a
"profanity filter: off" toggle in settings for adults.

---

## 3. Steamworks SDK integration

**Don't wire any of this until your app ID is approved.** The crate
references in code stay feature-gated.

### Dependencies

```toml
# desktop/src-tauri/Cargo.toml
[features]
default = []
steam = ["steamworks"]      # enable Steam integration

[dependencies]
steamworks = { version = "0.11", optional = true }
```

Building without `--features steam` produces a Steam-free binary
(matches the open-source self-host build). Building with `--features
steam` produces the Steam build.

### Integration points (each is a separate Tauri command)

```rust
// desktop/src-tauri/src/steam.rs (feature = "steam" only)

// Called once at app startup. Pulls the Steam user's persona name
// + Steam ID. Persists as the closer's default rep slug.
#[tauri::command]
fn steam_init() -> Result<SteamUser, String>;

// Fires every in-app achievement to Steam. The audit log already
// records the achievement; this just publishes to the user's profile.
#[tauri::command]
fn steam_unlock(achievement_id: &str) -> Result<(), String>;

// Pre-shutdown: zip bullpens/<slug>/ + write to Steam Cloud.
#[tauri::command]
fn steam_cloud_push() -> Result<u64, String>;  // returns bytes uploaded

// Post-startup: pull from Steam Cloud + unzip if newer than local.
#[tauri::command]
fn steam_cloud_pull() -> Result<bool, String>; // returns true if restored

// Open the Steam friends overlay for invite — replaces the
// invite-code copy/paste flow for Steam users.
#[tauri::command]
fn steam_invite_friend(bullpen_slug: &str) -> Result<(), String>;
```

### Steam Cloud size budget

Steam Cloud allocates ~100MB per user per app by default. A typical
bullpen folder runs 5-50MB depending on transcript count. Plan a
prune-old-transcripts pass for any operator whose bullpen exceeds 80MB.

### Achievement IDs

Use the same slugs your `achievements.py` already defines. Steamworks
just needs them registered in the partner backend with matching IDs:

```
first-close, daily-streak-7, daily-streak-30, top-pack-100,
century-of-calls, raid-bossed-fortune-500, level-10-grinder,
… (62 total — see server/achievements.py for the canonical list)
```

---

## 4. Build pipeline

### Local dev build

```bash
cd desktop
tauri dev    # no Steam, just the open-source self-host build
```

### Steam-enabled local build

```bash
cd desktop
tauri build --features steam    # produces a Steam-ready binary
```

### CI release build

`.github/workflows/release.yml` (already scaffolded) handles cross-platform
builds on every `v*` tag. Steam content depot upload happens manually
via `steamcmd` once the binary is signed + notarized.

---

## 5. Pricing

### Phase 2 (EA)
- **$19.99 USD** one-time per operator (closers play free under operator's seat)
- 10% launch discount for the first week → $17.99
- Region pricing per Steam's recommended matrix (PL, BR, RU, IN ~50% off USD)

### Phase 3 (v1.0)
- **$29.99 USD** standard
- DLC packs at $4.99-$9.99 each:
  - *Wall Street '85*
  - *SaaS Slingers*
  - *Boutique*
- Workshop content stays free (community-uploaded persona libraries)

### Free Steam keys
Phase 0 alpha + Phase 1 beta cohorts receive **free Steam keys** at EA
launch as thanks. Tracked via the BullpenLM Discord "Alpha" + "Beta"
roles. Beers grants keys manually through Steam's partner backend
(50-100 keys is typical, no extra cost).

### Refund handling
Steam refunds anything <2hr playtime. Bundled Ollama model is ~5.4GB —
if refunders cost you bandwidth, ship a smaller initial install + pull
the model on first launch (with a "skip — I have Ollama installed" option
for power users).

---

## 6. Steam-friendly framing rules

Things the store page + trailer + key art must avoid to get past Steam
content review:

- ❌ Don't call it a "real-money game" or "earn real money playing."
  Steam's terms ban this. The framing is: "the game logs sales calls;
  what you do with the leads is your own business outside the game."
- ❌ Don't show real customer names or recordings in promo material.
- ❌ Don't promise Steam-specific perks until your app ID is locked.
- ✅ Do show the game-feel: leaderboard, achievements, classes, XP,
  raids, the floor. Steam reviewers see this and approve.
- ✅ Do emphasize "open source" — Steam respects this signal.
- ✅ Do show the AI buyer in action — that's the unique hook nothing
  else on Steam has.

---

## 7. Day-of-launch checklist

When you flip the "release" switch on Steamworks:

```
□ Final build uploaded to default depot
□ All store-page text proofread + spell-checked
□ Trailer + screenshots final
□ Release date set to TODAY in Steamworks
□ Wishlist email blast queued (Steam sends automatically)
□ bullpenlm.com landing flips from "Coming Soon to Steam" to
  "Available now on Steam"
□ Discord "Alpha" + "Beta" role members DM'd their free Steam keys
□ HN + Indie Hackers + r/gamedev posts drafted
□ Twitter/X thread queued with the trailer
□ Bumblebee announcement montage queued for #announcements on Discord
□ Beers physically on his Mac with notifications on for the first 4
  hours of launch — to respond to bugs in real time
```

---

## 8. After launch

### Weeks 1-2: babysitting
- Monitor Steam reviews every 4 hours
- Patch any install / signing / launch bugs within 24 hours
- Fix any "this isn't a real game" complaints by improving the tutorial
  flow + adding more visible game-feel to early moments

### Weeks 3-8: capitalize
- Push first DLC pack into Steam Workshop as the "official" Wall Street
  '85 pack
- Start the Twitch streamer outreach — DM 20 mid-tier streamers offering
  free keys + co-op session with Beers
- File for Steam Deck Verified — the audit takes 1-3 weeks

### Months 3+: build the moat
- Localize to ES + PT-BR
- Add Workshop voting + community badges
- Plan v1.0 content additions for the EA → v1.0 transition (~6 months out)

---

## Status tracker

Update this table as you progress:

| Task | Status | Owner | Notes |
|---|---|---|---|
| Steam Direct $100 paid | ☐ | Beers | Apply once Phase 1 binaries are signing-clean |
| Tax forms (W-9) submitted | ☐ | Beers | Same day as Direct payment |
| App ID approved | ☐ | Steam | 1-4 weeks |
| Store page draft published | ☐ | Beers | Use this doc as the source |
| Wishlist live | ☐ | — | After app ID approval |
| Capsule + hero images | ☐ | Beers (or contractor) | ~$200 on Fiverr if outsourced |
| Trailer rendered | ☐ | Beers | Bumblebee stitch + screencap |
| Steamworks integration | ☐ | Beers | After app ID approval |
| Build pipeline green | ☐ | — | `release.yml` ready; needs signing certs |
| EA launch | ☐ | — | Target: Q1 next quarter from Phase 1 exit |
