# BullpenLM Roadmap

The product **doesn't change** as it ships through these phases. Same Python
server, same Cloudflare tunnels, same audit log, same real-CRM and real cold
calls. What changes is **how it's distributed** and **who's allowed in**.

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Phase 0        │    │  Phase 1        │    │  Phase 2        │    │  Phase 3        │
│  ALPHA          │ →  │  CLOSED BETA    │ →  │  STEAM EA       │ →  │  STEAM 1.0      │
│  (now)          │    │  (~1-2 months)  │    │  (~3-4 months)  │    │  (~6-9 months)  │
│                 │    │                 │    │                 │    │                 │
│  Mac Mini + SSH │    │  .dmg/.exe/...  │    │  Steam install  │    │  Steam install  │
│  cloudflared    │    │  direct download│    │  + Steam Cloud  │    │  + Workshop     │
│  invite codes   │    │  signed binaries│    │  + Steam friends│    │  + DLC packs    │
│  Discord role   │    │  auto-updater   │    │  $19.99 EA      │    │  $29.99 v1.0    │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
    ~5 friends            ~50 operators          ~500 wishlist          ~thousands
```

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

### Build work remaining
Nothing — the alpha is shippable today. See `docs/LAUNCH_DAY.md` for the
operator pre-flight ritual + friend-DM template.

### Exit criteria for moving to Phase 1
- 5+ friends are running their own bullpens (operator role)
- 10+ closers have signed agreements and logged at least one real call
- First close-won deal logged with a real client + commission paid
- At least one friend invites another friend without Beers's involvement
- `docs/LAUNCH_DAY.md` has been used by at least one non-Beers operator successfully

### Success metric
**Word of mouth.** Phase 0 succeeds if a friend texts another friend "yo
get on bullpenlm" without Beers asking. If the alpha cohort isn't sharing
it organically, the product isn't ready for paid distribution.

---

## Phase 1 — CLOSED BETA (1-2 months from Phase 0 exit)

**Status:** Build phase. Engineering scope is well-defined.

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
- Phase 0 alpha cohort (auto-promoted)
- Each alpha friend invites 2-3 of their friends (the "+2 invites" model)
- BullpenLM Discord "Beta" role auto-grants when an alpha verifies they
  installed the signed app

### Exit criteria for moving to Phase 2
- Tauri installer works on a clean Mac + clean Windows machine, signed,
  notarized, no security warnings
- Auto-updater has pushed at least one patch successfully without bricking
  any operator
- 50+ operators across both macOS and Windows
- Steam Direct application approved + app ID issued (apply early —
  approval is 1-4 weeks)
- 1,000+ wishlists on the Steam store page

### Success metric
**Install friction is gone.** A non-technical friend can go from
"bullpenlm.com" link to "running my floor" in under 5 minutes without
typing a single shell command.

---

## Phase 2 — STEAM EARLY ACCESS (3-4 months from now)

**Status:** Plan locked, awaiting Phase 1 + Steam approval.

### What changes
- **Distribution = Steam.** Operators search "BullpenLM" on Steam, hit
  Install, the bundled installer downloads + sets up. Steam handles
  updates, refunds, payment processing, cloud sync.
- **Steam Friends replaces invite codes** for closers who use Steam.
  The invite-code system stays as the fallback for friends who don't.
- **Steam Cloud syncs `bullpens/<slug>/`** — the operator's entire floor
  state backs up automatically. Survives reformat/reinstall.
- **62 in-game achievements become Steam achievements** via Steamworks
  SDK. Same triggers, just published to Steam profile.
- **EA pricing: $19.99 one-time.** No subscription, no DLC at EA.

### Build work
1. Steamworks SDK integration via the `steamworks` Rust crate
   (feature-gated, off in Phase 1 builds). ~2 weeks.
2. Achievement-publishing bridge — every existing in-game achievement
   unlock calls `steamworks::Client::user_stats().set_achievement(…)`.
   ~3 days.
3. Steam Cloud bridge — at app shutdown, zip `bullpens/<slug>/` to
   Steam's remote storage; at startup, unzip if newer. ~1 week.
4. Steam Friends integration — replace the join-code paste UI with
   "Join via Steam Friends" picker. Code path still exists for non-Steam
   friends. ~1 week.
5. Steam store page (see `docs/STEAM_LAUNCH_PLAN.md`):
   - Title, short desc, long desc, tags, capsule images, hero image,
     screenshots, trailer.
   - Age rating + content warning forms.
6. Steam Direct submission + content review wait. ~2-4 weeks.

**Total engineering on top of Phase 1:** ~4-6 weeks.

### Who's in
- Anyone who buys it on Steam ($19.99 EA price)
- Phase 0 alpha + Phase 1 beta cohorts get **free Steam keys** as thanks
- New operators can still bring their own VPS / Mac Mini hosting — Steam
  just bundles the install. No platform lock-in.

### Exit criteria for moving to Phase 3
- 500+ Steam owners
- "Very Positive" Steam review rating (>80% positive)
- All core multiplayer flows are stable across 100+ concurrent operators
- At least one operator has run their bullpen for 90+ days continuously
  with no audit-chain breaks
- DLC content pipeline tested (one pack shipped to alpha for feedback)

### Success metric
**Real commissions paid through invoices generated by the app.** Phase 2
succeeds when operators are actually paying closers monthly via the
auto-generated invoices, and closers are actually receiving the money.
Until cash moves, this is a fancy practice tool.

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
  uploaders get revenue share.
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
   not a SaaS in any phase. Steam distributes the install; the floor
   runs on the operator's machine.
2. **Open source forever.** The repo stays MIT. Free for anyone who
   wants to run their own bullpen without Steam.
3. **Audit chain integrity.** Every mutation flows through
   `audit.append()`. Operators can verify the chain at any time. No
   "trust the platform" — the chain is the trust.
4. **Real-CRM real-money real-calls.** Never fictionalized for any
   platform. The Steam version IS the BullpenLM you've been using.
5. **Closer protections.** Every closer signs the auto-rendered legal
   agreement. Monthly invoices auto-generate. Operator pays via the
   agreed payout method. BullpenLM never custodies funds.

---

## How phase transitions work

Moving from Phase N → Phase N+1 requires:
1. Hitting that phase's **exit criteria** (above)
2. The next phase's **build work** is verified shippable (smoke tests +
   3 days of soaking on Beers's own bullpen)
3. The Phase N+1 plan doc is finalized (`docs/STEAM_LAUNCH_PLAN.md` for
   Phase 2, future TBD for Phase 3)
4. Beers personally signs off — phase transitions are commitments to
   downstream operators, not just engineering milestones

Phases don't roll back. If Phase 2 ships and there's a critical bug,
fix it in place; don't revert to Phase 1.

---

## Where to look next

- **Phase 0 mechanics:** `docs/LAUNCH_DAY.md`
- **Phase 1 + 2 Steam specifics:** `docs/STEAM_LAUNCH_PLAN.md`
- **Alpha program rules:** `docs/ALPHA_PROGRAM.md`
- **Security posture:** `SECURITY.md`
- **Architecture:** `HANDOFF.md`
