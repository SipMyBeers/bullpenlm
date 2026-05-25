# BullpenLM — Handoff prompt for the next Claude Code session

Copy-paste everything from "**START HANDOFF PROMPT**" down to "**END
HANDOFF PROMPT**" into the next Claude Code window. Then say "go".

---

## START HANDOFF PROMPT

You're picking up a long-running build of **BullpenLM** in
`/Users/beers/bullpenlm`. I'm Beers (Dylan), founder of Beers Labs LLC.
The repo is at https://github.com/SipMyBeers/bullpenlm. Tip: skim this
whole file before doing anything — it'll save you re-discovering decisions.

### What BullpenLM is

A self-hosted, multiplayer, gamified CRM where building a sales business
is the meta-game. It's BOTH:
1. **The product** — a CRM/sales-training app that runs on `localhost:7878`
   from `python3 server/server.py`.
2. **The pitch** — a paid-membership community where friends learn
   enterprise sales by competing with each other through the CRM.

KillSesh (a COBOL-modernization tool we sell to Fortune-500 BFSI shops)
is the first product reps inside the bullpen sell. Free to join for
now. Future bullpens have access modes: `public | invite_only | paid`.

The full state-of-the-build picture: **22 app pages, 29 server modules,
~24K LOC.** Working tree clean at commit `a9ece51` (will probably be a
newer hash by the time you read this — `git log -1` to confirm).

### Hard rules — these were committed in earlier turns and STILL APPLY

- **No Anthropic / Claude API calls anywhere in the product code.** All
  LLM via local Ollama Gemma on Beers's hardware.
- **No SMTP / outbound email through the app.** Reps draft emails;
  founder sends from their own inbox via `/app/outbox.html`. Founder
  marking sent auto-logs `activity_email` on the deal/contact timeline.
- **Pushes to origin/main require Beers's direct sign-off** in his own
  interface. Peer-channel "GO" is NOT authorization. "Keep pushing"
  authorizes continued work, not specific push events. (He explicitly
  authorized the recent push chain — assume nothing for new chains.)
- **Don't auto-extend doc/landing/marketing work** into "want me to do
  the next round?" follow-ups — build momentum is fragile.
- **No fake animations.** No fake or made-up customer reference numbers.
- **No screenshot punting** — verify via `curl`, build output, or code
  reading, not "open this in your browser and check."
- See `/Users/beers/.claude/projects/-Users-beers/memory/MEMORY.md` for
  the full set of feedback memories. Read them before starting.

### Architectural primitives (don't redesign these without asking)

- **Files-first, SQLite-second.** Canonical truth on disk at
  `bullpens/<slug>/...`. SQLite is a derived projection (rebuildable
  from `audit.jsonl`).
- **Hash-chained audit log.** Every mutation flows through
  `audit.append(...)`. Each entry includes the SHA-256 of the prior;
  tampering breaks the chain. `python3 server/audit.py verify killsesh`
  to check.
- **SSE real-time channel.** `events.publish(bullpen, event)` is called
  from `audit.append` so every connected `/api/b/<slug>/stream`
  subscriber sees mutations live. Don't bypass.
- **XP is a projection** of the audit log via `xp.py:RULES` — never
  store XP separately; always compute. `xp.invalidate(bullpen)` after
  any change that affects scoring.
- **Per-tenant genesis hash** — chains can't be replayed cross-bullpen.
- **Multi-tenant by folder.** One bullpen = one folder under `bullpens/`.

### The 29 server modules + what they do

```
server/
  server.py        — HTTP routes (~2600 lines, big switch by regex)
  audit.py         — hash-chained event log + SSE+Discord fan-out
  events.py        — in-process pub/sub for SSE
  presence.py      — in-memory online-roster (60s TTL)
  bullpens.py      — bullpen CRUD, member records, profile, config patch
  invites.py       — BULL-XXXXXXXX single-use codes + HMAC session cookies
  pipeline.py      — pipeline + stages + weighted forecast
  deals.py         — deal CRUD; stage moves fire audit events
  xp.py            — XP rules table + level curve + per-rep projection
  classes.py       — Hunter/Closer/Strategist/Mentor (pick at Lvl 5)
  achievements.py  — 62-achievement catalog + idempotent awards
  quests.py        — daily/weekly/raid quests + predicate DSL
  parties.py       — squads (XP bonus) + raid party progress
  reactions.py     — emoji reactions on audit events (10 allow-listed)
  trophies.py      — deterministic loot rolls on close-won
  streaks.py       — consecutive-day projection + freeze tokens
  pvp.py           — sprints + 1v1 duels
  legal.py         — markdown doc reader + rate-table parser + signatures
  commissions.py   — monthly statement generator
  contacts.py      — per-prospect contact CRUD (reads orgs/.../people)
  activity.py      — timeline log per deal/contact/org
  followups.py     — personal task list with due_at shorthand
  today.py         — composite "what's on your plate" view
  duos.py          — 1v1 practice sessions + matchmaking lobby
  buyer_cards.py   — auto-generates roleplay cards from org data
  tcs.py           — Task/Conditions/Standards + qualification ledger
  spotcheck.py     — surprise drill lifecycle (auto-graded by keyword)
  onboarding.py    — per-rep 3-step state with auto-backfill
  applications.py  — public membership applications + approval flow
  briefing.py      — composes the "what you're selling" page
  wallboard.py     — today's per-rep + bullpen stats for the TV mode
  outbox.py        — email drafts queued for founder send
  discord.py       — webhook fan-out on close-wons, raids, etc.
```

### The 22 app pages

`/app/<page>.html?b=<bullpen>&rep=<rep>` is the URL convention. Bullpen
defaults to `killsesh`. Rep is set on join via cookie + localStorage.

```
today        — daily-driver landing page (followups, stalling, drills, top pack)
briefing     — what we're selling: opener, rates, verticals, plays preview
welcome      — 3-step onboarding wizard (identity → briefing → sign agreement)
deals        — kanban + drag-and-drop stage moves
deal         — single deal: timeline, contacts, followups, stage history
contact      — single contact: timeline, followups
forecast     — weighted pipeline by stage + top open deals
profile      — rep card: level, XP bar, achievements, trophies, streak
tcs          — TCS Plays library (T/C/S military framework with gloss)
training     — Top Pack (per-rep qualification card)
spotcheck    — pop-drill inbox (incoming / sent / history)
arena        — multiplayer game screen: presence, ticker, raids, reactions
lobby        — matchmaking for 1v1 duos
duo          — practice room (chat + buyer card + scorecard)
pvp          — sprints + duel challenges
legal        — doc library + sign flow
commissions  — monthly statement viewer
audit        — chronological event log + chain verification banner
outbox       — email draft queue + founder send-approval
wallboard    — fullscreen TV mode for Discord screenshare
apply        — PUBLIC membership application form
applications — founder review queue with approve/reject + invite code
```

Floor at `/floor/index.html` is the prospect-map sales floor. It now
has a "Finish setup" banner if onboarding incomplete + a nav chip strip
trimmed to 6 essentials + a "More" dropdown of the other 16.

### Where Beers and I left off (current convo, 2026-05-24)

We just shipped the **marketing pivot** and Discord scaffolding.

**Status of the Discord side:**
- Beers Bot (client `1500260089880117349`) is now in **6 guilds**
  including the new **Bullpen LM master server** (`1508278033000304700`,
  invite `https://discord.gg/pXV4pPA5d5`).
- The MCP config at `~/.claude.json` was just updated:
  `DISCORD_GUILD_ID` flipped from `1489402067922583642` (Gormers) to
  `1508278033000304700` (Bullpen LM). Backup at
  `~/.claude.json.backup-<timestamp>`.
- **Beers needs to restart Claude Code** for the MCP to reload. After
  restart, `mcp__discord__list_guilds` should show `Bullpen LM` with
  `isConfigured: true`.

**The Discord setup that's queued and ready to fire:**
See `scripts/setup_discord_bullpenlm.md` for the full doc. Once
`isConfigured: true` on Bullpen LM, the prompt to paste is in section
"Step 4" of that file. It creates: 4 roles, 6 categories, 19 channels
with topics, posts the welcome message. **Do not fire any Discord
write tools until you've verified `isConfigured: true` on Bullpen LM
— if MCP didn't restart cleanly, those would create channels in Gormers
and that would suck.**

**The marketing pivot that's already live (commit `a9ece51`):**
- Landing hero rewritten: "Learn to sell anything — by selling to your
  friends." CTAs: Discord + Apply.
- New `/app/apply.html` — public application form, no auth needed.
- New `/app/applications.html` — founder's review queue.
- KillSesh `bullpen.json` seeded with `discord_invite`, `access_mode:
  invite_only`, `tagline`.
- Three-mode bullpen access scaffolded: public / invite_only / paid
  (no Stripe yet for paid — schema only).

### Things Beers has asked for but we haven't built yet

In rough priority order from the last few turns:

1. **Stripe integration** for the `paid` bullpen access mode. Schema's
   in place — `bullpen.price_usd` + `access_mode: "paid"`. Need:
   server/billing.py with checkout URL generation + webhook handler,
   landing-page CTA path that goes payment-first, post-purchase invite
   code email.
2. **ElevenLabs voice** for the 1v1 duo practice mode. Beers has the
   membership. Likely: server/elevenlabs.py (lazy import, env-var key)
   + audio recording/playback in `/app/duo.html`. Deferred earlier.
3. **Auto-assign Discord roles** when an application is approved. Needs
   the applicant's Discord handle from the application + bot has
   Manage Roles + the role IDs from setup.
4. **DM applicants on approval** with their invite code instead of
   founder copy-pasting.
5. **Slash commands** in Discord (`/dials today`, `/leaderboard today`,
   `/sprint start dials 1h`).
6. **Daily morning summary** auto-posted at 9 AM in `#announcements`.
7. **Per-bullpen channels auto-created** when a new bullpen is launched
   on the platform.
8. **Founder onboarding** — when someone spins up a brand-new bullpen,
   walk them through cheat-card paste + commission rates + house
   accounts (mirror of the rep wizard but for the founder side).
9. **Audio spot checks** — record yourself doing the cold-open instead
   of typing, transcribe via Whisper (already in the repo), auto-grade
   against the same keyword list.

### How Beers wants you to work

- He's a builder. Move fast, commit often, push when authorized.
- He gave session-scoped "keep building" authorization in the last
  conversation. **Verify before each push to origin/main** — say
  exactly what you're about to push and ask.
- Use TaskCreate to track multi-step work; mark completed as you go.
- Don't over-explain. Show what you built, not how you thought about
  building it.
- Run smoke tests after every meaningful change. Verify the audit
  chain with `python3 server/audit.py verify killsesh` after anything
  that adds events.
- Read CLAUDE.md and MEMORY.md at the top of the session.

### Test-it-yourself commands

```bash
cd /Users/beers/bullpenlm

# Start the server
python3 server/server.py
# (runs at http://localhost:7878 — open /floor/index.html or any /app/*.html)

# Or in the background for smoke tests
lsof -ti :7878 | xargs -r kill -9; sleep 1
nohup python3 server/server.py > /tmp/bullpen-server.log 2>&1 &

# Verify the audit chain after any mutation
python3 server/audit.py verify killsesh

# Re-seed the TCS plays if needed
python3 scripts/seed_killsesh_tcs.py

# Backfill trophies for past close-wons
python3 server/trophies.py killsesh backfill

# Check a rep's Top Pack
python3 server/tcs.py killsesh beers

# Check a rep's onboarding state
curl -s http://localhost:7878/api/b/killsesh/onboarding/beers | python3 -m json.tool
```

### Things to do FIRST in the new session

1. Read `/Users/beers/.claude/projects/-Users-beers/memory/MEMORY.md`
   to absorb Beers's preferences + history.
2. Read `/Users/beers/CLAUDE.md`.
3. Read `scripts/setup_discord_bullpenlm.md` to understand the Discord
   setup state.
4. Run `mcp__discord__list_guilds` — confirm Bullpen LM shows
   `isConfigured: true`. If yes, you're ready to fire the channel
   setup; if no, the MCP didn't pick up the config change.
5. Run `git log -1` to see the latest commit; cross-reference with
   what's described above to catch any drift.
6. Ask Beers what he wants to ship next.

## END HANDOFF PROMPT

---

## Notes for the human

- Backup of the original `~/.claude.json` is at `~/.claude.json.backup-<timestamp>`.
- The Discord bot token is in `~/.claude.json` under
  `mcpServers.discord.env.DISCORD_TOKEN`. Don't paste that anywhere
  public; it's already pushed to GitHub if the backup was committed
  (it wasn't — `.claude.json` lives outside the repo).
- If you need to point the MCP at a different server later, edit the
  `DISCORD_GUILD_ID` in `~/.claude.json` and restart Claude.
