# Launch Day — operator pre-flight + friend onboarding script

This is the checklist you run the morning of inviting friends to your
bullpen, and the script you send each friend. Print it, screenshot it,
whatever — just don't wing it.

---

## Pre-flight (you, the operator) — 10 minutes

### 1. Boot the host

```bash
cd ~/bullpenlm
# Kill any stale server
lsof -ti :7878 | xargs -r kill -9
# Start it
nohup python3 -u server/server.py > /tmp/bullpen-server.log 2>&1 &
sleep 4
tail -20 /tmp/bullpen-server.log
```

You should see "BullpenLM · trainer ..." plus the invoice + discord
threads arming. If anything errored, stop and fix before continuing.

### 2. Stop your Mac from sleeping for the day

Cloudflare Quick Tunnels die when the Mac sleeps. Run this in a separate
Terminal tab and **leave it open** — `caffeinate` is a one-line solution:

```bash
# Keep CPU + display awake for 12 hours (Cmd+C to stop early)
caffeinate -dimsu -t 43200
```

If you need to step away for a few hours, that's fine — just don't close
the laptop lid. Closing the lid kills network, which kills cloudflared,
which gives every invite link a new (broken) URL.

### 3. Wizard your bullpen (if not already done)

Open <http://localhost:7878/app/start-bullpen.html> in your browser
and walk through the 5 steps. The Cloudflare tunnel + first invite
link generate automatically when you hit Launch.

Make sure you fill in:

- **Step 4 (Brand):** legal entity name + state + county. Otherwise the
  rep agreement has `[FILL IN: …]` markers that look unprofessional.
- **Step 3 (Economics):** check the payout methods you actually accept
  (Stripe / PayPal / Wise / whatever). Closers pick from this set.

### 4. Seed your prospect list

```bash
cd ~/bullpenlm
# If you have a prospects JSON ready (the killsesh one is in
# scripts/_killsesh_prospects.json), run:
python3 scripts/_seed_killsesh_prospects.py <your-bullpen-slug>
# Otherwise the floor will be empty — closers won't have anyone to claim.
```

This is the difference between "friend joins and sees something" vs
"friend joins and stares at an empty kanban." Don't skip.

### 5. Verify the chain end-to-end before sending invites

```bash
# Get your tunnel URL
TUNNEL=$(curl -s http://127.0.0.1:7878/api/host/status | python3 -c "import json,sys;print(json.load(sys.stdin)['url'])")
echo "Tunnel: $TUNNEL"

# Hit it like a closer would — should return the join page
curl -s -o /dev/null -w "HTTP %{http_code}\n" "$TUNNEL/app/join.html?code=test"

# Verify the bullpen poster page
curl -s "$TUNNEL/b/<your-slug>" -o /tmp/poster.html
grep "<title>" /tmp/poster.html
```

If both come back HTTP 200 and the poster has your bullpen name in the
title, you're live.

### 6. Generate an invite for each friend you're inviting

```bash
# Either via the host panel UI:
open "http://localhost:7878/app/host.html"
# (Fill in rep name + optional note, click Generate, click Copy link)

# Or via the CLI:
python3 server/invites.py create brad "First friend invite"
# Then paste your tunnel URL in front:
#   https://<your-tunnel>.trycloudflare.com/app/join.html?code=BULL-XXXX
```

Save each invite link next to its intended recipient — once a code is
redeemed, it's burned. Don't share the same code with two people.

### 7. Sanity-check the audit chain

```bash
python3 server/audit.py verify <your-slug>
# Should print: ✓ Chain verified for bullpen '<your-slug>'
```

If this fails, do NOT send invites. The chain is broken and any future
closes won't be trustworthy. Restore from the most recent good audit.jsonl.

---

## Friend onboarding — the script you send each friend

Paste this into a DM, replacing `<INVITE_LINK>` with the link you just
generated. Adjust the voice to your relationship with them — the
structure matters more than the exact wording.

```
hey [name] —

i'm running KillSesh through bullpenlm, the multiplayer sales CRM
i've been building. i set you up with a seat on the floor.

here's your invite (single-use — don't share it):
<INVITE_LINK>

what'll happen when you click:
  1. browser opens to a join page → you're connected to my floor
  2. quick 3-step setup: pick a display name + avatar, read what we
     sell, sign the rep agreement (yes it's a real agreement, take 30
     seconds and skim it)
  3. you land on the daily-driver "floor" — your kanban, your prospects,
     your leaderboard rank

commission is 50% of every account you originate. you get a real
auto-generated invoice at the end of each month for whatever you closed,
paid out via stripe / paypal / crypto — your choice on the way in.

your first 30 min:
  → claim 3-5 prospects from the open list (locks them to you for 14
    days so nobody else gets in your way)
  → open one of them, hit "practice call" to run a few reps against the
    AI buyer before you dial the real human
  → when you're warm, dial the actual prospect

i'll be on the floor too. text me if anything breaks or doesn't make
sense.

— beers
```

---

## If a friend's link breaks

The most common reason: your Mac slept and the cloudflared tunnel
restarted, giving you a new URL. Old invite links → 404. Fix:

```bash
# Get the current tunnel URL
TUNNEL=$(curl -s http://127.0.0.1:7878/api/host/status | python3 -c "import json,sys;print(json.load(sys.stdin)['url'])")
echo "New tunnel: $TUNNEL"

# Re-generate the friend's invite link with the new URL
python3 server/invites.py create <friend-rep-slug> "regen after tunnel restart"
# Combine: $TUNNEL/app/join.html?code=BULL-XXXX
```

DM them the new link. Their previously-redeemed account on your floor is
still intact — they just need a fresh URL to reach it.

---

## After the first day

Things to do once friends have logged some calls:

1. **Verify the audit chain again** — `python3 server/audit.py verify <slug>`
2. **Check the first invoices look right** — `python3 server/invoices.py list <slug>`
   (they auto-generate on the 1st of next month; you can also force-gen
   from `/app/host.html` or the CLI)
3. **Set up a named Cloudflare Tunnel** so the URL stays stable across
   reboots. See `docs/NAMED_TUNNEL_SETUP.md` (you'll need to write this
   if you don't have it yet; the gist: `cloudflared tunnel create
   killsesh && cloudflared tunnel route dns killsesh app.killsesh.com`)
4. **Move the host off your laptop** — a Mac Mini or VPS keeps your
   floor online without your laptop running. Per the wizard's "Rent a
   VPS" cards, this is the natural next step.
