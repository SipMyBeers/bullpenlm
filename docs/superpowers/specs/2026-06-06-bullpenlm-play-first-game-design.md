# BullpenLM — Play-First Game (Sub-project ①) — Design Spec

**Date:** 2026-06-06
**Status:** Approved design, pre-implementation
**Scope:** Sub-project ① of 2. (② Host-conversion + one-click hosting is deferred — gated on app notarization + bundled Ollama; see "Out of scope".)

## Goal

Turn BullpenLM from "a training tool with game elements" into an **actual game** that hooks a *cold visitor* (someone who stumbles onto bullpenlm.com with zero context) within ~30 seconds, with no download and no signup — then makes hosting your own bullpen the *earned upgrade* once they're hooked.

**Funnel decision (locked):** play-first. Landing's hero is "▶ Play now — no download", not "download & host". Hosting is surfaced in-game after the player is engaged.

**Game spine (locked):** a 7-tier **Gauntlet ladder** (PvE climb — beat each tier's boss-buyer to unlock the next) + a **Ranked overlay** (every drill's honest score moves you up the rank ladder the landing already promises — **ROOKIE → WALK-ON → STARTER → CLOSER → ALL-STAR → LEGEND** — plus a floor leaderboard position).

## Aesthetic & brand (HARD RULES — applies to landing + game UI)

The current site "reads AI-generated." These rules are non-negotiable across everything we touch:
- **No specific percentages / fake-precise stats** anywhere on the site. Claims stay qualitative or visual, never "43% / 10×"-style numbers.
- **No emojis. Anywhere.** Not in copy, CTAs, buttons, ladder states, toasts, or my own messages-as-content. Use type, color, and CSS/SVG for emphasis and iconography instead.
- **Crafted typography, not LLM-flat.** Distinctive custom fonts (build on the existing Tanker/Bespoke Serif/Switzer/JetBrains Mono, push further where it helps), deliberate scale contrast, and **hand-set emphasis: highlighted/colored key words** (marker-stroke highlights, accent-colored phrases) so copy looks designed, not generated.
- **Cash feels like money.** Every money reward (`money_xp`, commission, close payouts) renders as **actual cash** — green, currency/bill styling, `$` formatting, texture — never a gray XP integer.
- **Money-printer motif (signature moment).** Earning money (close-won, commission, money_xp gain) triggers a **money printer that prints/ejects cash bills** ("brrr"). This is the ownable reward beat that makes cash feel real and the product feel un-generic. Lives on the close/deal surfaces + the win fanfare.
- **Don't replace the existing hero or its gifs** — additive changes only on the landing (see Component 4).

## Success criteria

- A cold visitor goes landing → playing a graded drill in < 60s, no download/login.
- The first screen of the game shows an obvious **goal** (the ladder + "reach Tier 3 to dial real prospects"), **progression** (locked/unlocked rungs, rank badge), and **stakes** (rank moves per drill, leaderboard position).
- Clearing a tier produces a real **win moment** (boss-beaten celebration).
- Everything ships incrementally; no hard blockers (mostly frontend served from `~/Library/Application Support/BullpenLM/floor/app/`).

## Non-goals (this sub-project)

- Host-conversion / download / running-your-own-bullpen (sub-project ②).
- Backend rebuilds, unless we choose to move rank computation server-side (default: compute client-side to avoid a rebuild).
- New game engine — we reuse the existing floor/drill engine (Approach A).

## Existing pieces reused

- `floor/app/quickstart/index.html` — codeless entry (pick a name → spawn). Becomes the "Play now" target.
- `floor/app/spawn.html` / `office.html` — the floor + quest hub. Hosts the ladder + rank.
- `bullpens/<slug>/tcs/*.json` — 18 plays across `phase_tier` 1-7 (the Gauntlet content).
- `server/tcs.py` auto_grade (now proportional, answer-key hidden), `/api/b/<bp>/tcs`, `/spotchecks`, `/leaderboard`, `/xp/<rep>`, `/streaks/<rep>`, `/toppack` (qualifications = cleared tiers).
- XP/levels, leaderboard + lanes, fanfare + `sfx.js`.

## Components & data

### 1. The Gauntlet ladder view (game home)
A ladder UI rendered on the floor (new section in `spawn.html`, the cold-visitor landing surface):
- 7 rungs (one per `phase_tier`), each with a **boss-buyer name** and a state: `cleared`, `current` ("YOU ARE HERE"), or `locked`. **No emoji markers** — render states with type weight, accent color, and CSS/SVG (e.g. a drawn lock, a struck-through cleared rung), never ✓/🔒/▶ glyphs.
- A tier is **cleared** when the rep has a GO on that tier's play(s). Source: `GET /api/b/<bp>/toppack/<rep>` (qualifications) or the per-rep cleared set; computed client-side.
- A tier is **unlocked** when the previous tier is cleared (Tier 1 always unlocked). Locked rungs show "beat Tier N to unlock" and are non-clickable.
- Persistent goal banner: **"Reach Tier 3 to dial real prospects"** (ties to the existing cert gate).
- Boss-buyer names: a small static map (tier → boss name/flavor) added as data — either a `boss` field on the tier's lead play, or a `floor/app/gauntlet.json` config consumed by the ladder view. (Choose: `gauntlet.json` config, single source, no per-play edits.)

### 2. The Ranked overlay
- **Rank ladder:** ROOKIE → WALK-ON → STARTER → CLOSER → ALL-STAR → LEGEND (the six the landing already names; thresholds by total XP and/or level). Computed **client-side** from `GET /api/b/<bp>/xp/<rep>` (level/clout/money) — no rebuild.
- **Rank badge** near the player identity (the YOU pawn / header), with progress-to-next-rank bar.
- **Per-drill rank movement:** after a drill, show "RANK +N" / promotion toast (reuse the XP-toast/fanfare patterns).
- **Floor position:** "#N on the floor" from `GET /api/b/<bp>/leaderboard` (overall lane).

### 3. Boss-clear celebration
- On clearing a tier (last needed GO flips a tier `current`→`cleared`), fire a boss-beaten celebration: reuse the office `fanfare` + `sfx.js` (`levelUp`/`bell`), with "TIER N CLEARED — <boss> beaten" + the next rung unlocking animation.
- Detected client-side by diffing cleared-tiers before/after a drill result.

### 4. Cold-visitor "Play now" entry
- **Do NOT touch the existing hero or its gifs.** Insert a new **"Play now" block directly BELOW the hero gifs** — leave the current hero, headline, and gifs intact. We are adding, not replacing.
- The new block: primary CTA **Play now — no download** → `https://app.bullpenlm.com/app/quickstart/?b=default` (no emoji/glyph on the button). Secondary CTA **Host your own bullpen** (→ learn-more/waitlist until ②).
- Cold visitors land on `default` (the public floor; codeless quickstart target, kept clean). Fake-friend grinding stays on `drill-yard`.
- Quickstart copy reframed from "you were invited" → "enter the floor / start your climb" for cold (no-code) visitors; keep the invited-friend variant when a code is present.

## Build slices (each ships independently, frontend-first)

0. **Aesthetic foundation (cross-cutting, do first):** purge emojis + specific percentages from landing + game UI; establish the type/highlight system (custom fonts, marker/accent word-highlighting) as shared CSS; build the **cash component** (money rendered as green textured currency) + the **money-printer animation** (CSS/SVG, no assets) wired into close-won / money_xp gains. Everything below uses these.
1. **Gauntlet ladder view** on `spawn.html` (+ `gauntlet.json` boss config) — the climb, locked/unlocked/cleared (typographic, no emoji), goal banner.
2. **Ranked overlay** — rank badge + client-side rank computation + per-drill rank movement + floor position; money shown via the cash component.
3. **Boss-clear celebration** — tier-clear detection + fanfare/sfx win moment (no emoji); money wins fire the **money printer**.
4. **Landing "Play now" funnel** — new Play-now block **below the existing hero gifs** (hero + gifs untouched); reframed cold-visitor copy; no emojis, no percentages.

Deploy: edit `floor/app/*` (+ `landing/index.html`), copy to the served dir (`~/Library/Application Support/BullpenLM/floor/app/`), verify in browser. `landing/index.html` deploys to the marketing host (Cloudflare Pages `bullpenlm`).

## Risks / decisions

- **Rank computation location:** client-side (chosen) → no rebuild, fast iteration. If ranks need to be authoritative/anti-cheat later, move server-side (a rebuild) — out of scope now.
- **Cold visitors on `default`:** they'll populate the real floor. Acceptable — they're real players; this is the public floor. Test reps continue on `drill-yard`.
- **Boss names** are flavor (data), not new mechanics — keep them punchy and on-theme (BFSI/KillSesh).

## Out of scope (→ sub-project ②, separate spec)

- In-game "Host your own bullpen" conversion flow.
- Notarized/signed installer; one-click host with bundled Ollama + model + auto-tunnel.
- Operator/empire meta (recruit closers, revenue) as a primary surface.
