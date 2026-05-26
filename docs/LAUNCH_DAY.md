# Launch Day — operator pre-flight + friend onboarding script

Run this top-to-bottom the morning you invite friends. Don't wing it.

---

## TL;DR — Beers's 8-step morning ritual

```bash
cd ~/bullpenlm

# 1. Free port 7878 + start server fresh
lsof -ti :7878 | xargs -r kill -9; sleep 1
nohup python3 -u server/server.py > /tmp/bullpen-server.log 2>&1 &
sleep 4 && head -10 /tmp/bullpen-server.log

# 2. STOP YOUR MAC FROM SLEEPING — leave this open in another Terminal tab
caffeinate -dimsu -t 43200   # 12 hours

# 3. Wizard your KillSesh (if not already done): open in browser
open http://localhost:7878/app/start-bullpen.html

# 4. Seed the 57 prospects so the floor isn't empty
python3 scripts/_seed_killsesh_prospects.py

# 5. Confirm tunnel + audit chain healthy
curl -s http://127.0.0.1:7878/api/host/status | python3 -m json.tool
python3 server/audit.py verify killsesh

# 6. Generate per-friend invites from the host panel
open http://localhost:7878/app/host.html
# OR via CLI:
# python3 server/invites.py create brad "Brad Stevens — gym friend"

# 7. Send each friend their personal invite URL + the DM template below

# 8. Stay on the floor: open http://localhost:7878/app/today.html?b=killsesh&rep=beers
#    Watch the SSE feed, jump in when closers ping
```

---

## Why each step matters

### 1. Server boot

If something errored at startup, fix it before you send anything. Look for
the lines:

```
BullpenLM · trainer + org graph + post-call debrief
Model:   gemma2:9b
[invoices] monthly auto-fire thread armed
[discord_roles] reaction-role sync live (every 20s)
```

All four should appear. If `[invoices]` or `[discord_roles]` are missing,
re-run with `python3 -u server/server.py` in the foreground and read the
traceback.

### 2. Caffeinate (the #1 thing that'll break tomorrow if you skip it)

Cloudflare Quick Tunnels die with your Mac. When the tunnel dies, **every
invite URL you sent goes 404**. Closers will think the app's down.

`caffeinate -dimsu -t 43200` keeps your CPU + display + system idle awake
for 12 hours. Run it in a Terminal tab and **don't close the lid**.

If you must close the lid (travel, etc.), accept that tunnel will restart
and you'll need to regenerate every active invite. Recovery procedure
at the bottom of this doc.

### 3. The wizard

5 steps. Don't skip Step 4 (Brand → Legal entity). Filling in:
- Legal entity: "Beers Labs LLC"
- Entity type: Single-member LLC
- State of formation: Oregon
- County for disputes: Multnomah County

…means the rep agreement renders zero `[FILL IN: …]` markers — closers
read it and it looks professional. Skip those fields and the doc has
bracketed placeholders that read like an unfinished template.

### 4. Seed prospects

If you skip this, the floor is empty. Closers join → "claim a prospect"
list is blank → confused friend → bad day-one impression. The seed script
populates 24-57 BFSI orgs (Cigna, Bank of America, BCBS, etc.) ready to
claim.

### 5. Sanity-check

`api/host/status` should return `{"running": true, "url": "https://..."}`.
If `running` is false, the tunnel didn't spawn — usually means
`cloudflared` isn't on PATH (`brew install cloudflared`).

`audit.py verify killsesh` should print `✓ Chain verified`. If it prints
`× break at index N`, do NOT send invites — the audit chain is the only
way closers can trust their commission record later. Restore from your
most recent good `audit.jsonl`.

### 6. Per-friend invites

Each invite code is single-use. Generate a separate one per friend with
their name as the rep slug (`brad`, `mike`, `tina`) so the leaderboard
reads correctly. Don't share one code between two friends — second
person to redeem gets blocked.

The host panel auto-builds the full URL with your live tunnel pre-filled.
Hit Copy on each invite and paste into each friend's DM.

---

## The friend DM template

Paste-ready. Replace `<INVITE_LINK>` and `[name]`.

```
hey [name] —

i'm running KillSesh through bullpenlm, the multiplayer sales CRM
i've been building. i set you up with a seat on the floor.

here's your invite (single-use — don't share it):
<INVITE_LINK>

what'll happen when you click:
  1. browser opens → you're connected to my floor
  2. quick 3-step setup: display name + avatar, read what we sell,
     sign the rep agreement (yes it's a real agreement, take 30
     seconds and skim it)
  3. you land on the daily-driver "floor" — your kanban, your
     prospects, your leaderboard rank

your numbers:
  • commission: 50% of every account you originate
  • tiers: Level 1-4 = 30%, Level 5-9 = 40%, Level 10+ = 50%
  • payouts: monthly invoice, your choice of method (Stripe, PayPal,
    Wise, USDC, paper check)

your first 30 min:
  → claim 3-5 prospects from the open list (locks them to you for
    14 days so nobody else gets in your way)
  → open one of them, hit "practice call" to run a few reps against
    the AI buyer before you dial the real human
  → when you're warm, dial the actual prospect

mobile note: today / profile / training / briefing / welcome work
great on a phone. the deep kanban view (deals) is better on a laptop.

i'll be on the floor too. text me if anything breaks or doesn't make
sense.

— beers
```

---

## Pages I verified work end-to-end at iPhone-14 width

Tested via Chrome DevTools at 390×844 pt, touch, mobile UA.

| Page | Mobile status |
|---|---|
| `/app/join.html` | ✅ Clean card layout, big paste-friendly input |
| `/app/welcome.html` (closer 3-step) | ✅ Avatar grid reflows 8→6 cols, big SAVE button |
| `/app/today.html` | ✅ Setup banner stacks on narrow, sections all stack cleanly |
| `/app/briefing.html` | ✅ Hero scales, sections stack |
| `/app/training.html` (Top Pack) | ✅ Card layout, clear sections |
| `/app/profile.html` | ✅ Rep card + level + achievements all stack |
| `/app/legal.html` (doc viewer) | ✅ Doc list mobile-friendly |
| `/app/host.html` (operator panel) | ✅ Big copy buttons, clean sections |
| `/app/start-bullpen.html` (wizard) | ✅ 5-step flow, mobile-perfect |
| `/app/deals.html` (kanban) | ⚠ Horizontal scroll, works but cramped — laptop preferred |
| `/floor/index.html` (sales-floor map) | ⚠ Desktop-only by design — closers don't need this for day 1 |

The "⚠" pages are usable but desktop-preferred. Friends who only have a
phone tomorrow should stick to `today.html` as their hub — it has the
"finish setup" banner if onboarding's incomplete, sections for follow-ups,
quick-add for next steps, and a recent close-wons feed.

---

## If a friend's link breaks mid-day

Most common cause: your Mac slept and the tunnel restarted with a new URL.

```bash
# Get the current tunnel URL
TUNNEL=$(curl -s http://127.0.0.1:7878/api/host/status | python3 -c "import json,sys;print(json.load(sys.stdin)['url'])")
echo "$TUNNEL"

# Make a new invite for the friend (with their actual rep slug)
python3 server/invites.py create <friend-rep-slug> "regen after tunnel restart"
# Returns a code BULL-XXXXXXXX. Combine:
#   $TUNNEL/app/join.html?code=BULL-XXXXXXXX
```

DM them the new link. **Their floor account is intact** — once they redeem
the new code, their member record + onboarding state + claimed prospects
are all still there. The fresh code just re-issues the session cookie.

---

## After friends are on

### Verify the audit chain stays clean as activity rolls in

```bash
# Run any time you want to check; should always print ✓
python3 server/audit.py verify killsesh
```

### First monthly invoices auto-generate June 1

Background thread fires at 00:01 local on the 1st. Output lands at
`bullpens/killsesh/invoices/<rep>-2026-05.md`. You can force-generate
earlier with:

```bash
python3 server/invoices.py generate-all killsesh 2026-05
```

A closer who wants a mid-month early-payout invoice hits a button on
their commissions page (or you can POST to
`/api/b/killsesh/invoices/request-payout` on their behalf).

### Mark an invoice paid after you wire them

```bash
curl -X POST http://127.0.0.1:7878/api/b/killsesh/invoices/<invoice-id>/mark-paid \
  -H "Content-Type: application/json" \
  -d '{"paid_via":"Stripe transfer #ch_abc123"}'
```

This audit-logs the payment + flips the invoice status in the closer's
commissions view.

---

## Day-2 next steps (skip for tomorrow, but know they're coming)

1. **Named Cloudflare Tunnel** — replaces the ephemeral
   `<random>.trycloudflare.com` URL with a stable subdomain like
   `app.killsesh.com`. Means surviving a Mac restart without re-sending
   every invite link. Setup:
   ```bash
   cloudflared tunnel login
   cloudflared tunnel create killsesh
   cloudflared tunnel route dns killsesh app.killsesh.com
   # Then edit ~/.bullpenlm/tunnel.json to point at the named tunnel
   ```

2. **Move the host off your laptop** — a $5/mo VPS (Hetzner / DigitalOcean
   / Vultr — the wizard's "Rent a VPS" cards show your referral links)
   keeps your floor online 24/7 regardless of whether your laptop is on.
   `scp -r ~/bullpenlm root@vps:` + `python3 server/server.py` + repoint
   the named tunnel → done.

3. **Mobile-first kanban** — if friends are doing serious dialing on
   their phones, the deals.html kanban needs a single-column-with-tabs
   view at narrow widths. That's a future polish pass — today.html
   covers most day-one closer needs.
