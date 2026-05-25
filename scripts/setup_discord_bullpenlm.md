# BullpenLM master Discord — channel setup

This is the **master BullpenLM server** (Guild ID `1508278033000304700`,
invite `https://discord.gg/pXV4pPA5d5`). It hosts every bullpen — one
server, many bullpens. Each bullpen gets its own category cluster as
they launch. KillSesh is the first.

## Step 0 — Invite the bot

If the Beers bot (client ID `1500260089880117349`) isn't in the server
yet, click:

**https://discord.com/api/oauth2/authorize?client_id=1500260089880117349&permissions=8&scope=bot+applications.commands**

(Admin permissions for simplicity — it's your server. Swap for a
tighter permission integer later if you want.)

Verify by asking Claude: "list discord guilds" — `BullpenLM` should
appear in the list.

## Step 1 — Reconfigure the MCP

Point the Discord MCP at the new server:

```bash
DISCORD_GUILD_ID=1508278033000304700
```

Update wherever you have it (`~/.claude/mcp_settings.json` env-var
section or the equivalent) and restart Claude / the MCP server.

Verify: ask Claude "list discord guilds" again — `BullpenLM` should
now show `isConfigured: true`.

## Step 2 — Master server channel structure

The server is split into **master-brand channels** (everyone) and
**per-bullpen channel clusters** (each bullpen runs its own ops in its
own category). KillSesh launches with the first cluster.

### 🪧 ABOUT · master brand (everyone)

| channel              | topic                                                              |
|----------------------|--------------------------------------------------------------------|
| `welcome`            | Read this first. What BullpenLM is + how the server works.         |
| `rules`              | Don't dial House Accounts. Don't ghost teammates. Don't be cringe. |
| `how-bullpenlm-works`| The 90-second explainer + link to bullpenlm.com.                   |
| `announcements`      | Founder-only. Major updates: new bullpens, new features.           |

### 🏢 BULLPENS · directory (everyone)

| channel              | topic                                                              |
|----------------------|--------------------------------------------------------------------|
| `live-bullpens`      | Index of every bullpen running on the platform + their access mode.|
| `launch-your-own`    | How to spin up your own bullpen + pick public / invite-only / paid.|

### 💰 KILLSESH · first bullpen (members only — gated by role)

| channel              | topic                                                              |
|----------------------|--------------------------------------------------------------------|
| `killsesh-floor`     | General chat for KillSesh reps while dialing.                      |
| `killsesh-wins`      | 🔔 auto-feed from the bot on every closed-won deal.                |
| `killsesh-leaderboard`| Daily top 5 reps by XP / dials / closes.                          |
| `killsesh-pop-drills`| TCS spot checks fired from the app ping here.                      |
| `killsesh-raids`     | Raid quests announced + party-up.                                  |
| `killsesh-product`   | Product updates Beers ships that you can quote on calls.           |
| `killsesh-objections`| Bank of objections + the best counter for each.                    |
| `killsesh-wins-deep` | Long-form post-mortems on how a deal closed.                       |
| `killsesh-coaching`  | Ask Beers anything channel.                                        |

### 🎟 JOIN (public — no role needed)

| channel              | topic                                                              |
|----------------------|--------------------------------------------------------------------|
| `apply-to-killsesh`  | Link to bullpenlm.com/app/apply.html + how vetting works.          |
| `onboarding-help`    | Stuck on the wizard? Drop questions here.                          |

### 💬 COMMUNITY (everyone)

| channel              | topic                                                              |
|----------------------|--------------------------------------------------------------------|
| `general`            | Off-topic everyday chat.                                           |
| `sales-talk`         | Tactics, war stories, book recommendations.                        |
| `feature-requests`   | What you wish BullpenLM did. Beers reads everything here.          |
| `bug-reports`        | Tag with the page + a screenshot if you can.                       |

### 🎙 VOICE

| channel              | topic                                                              |
|----------------------|--------------------------------------------------------------------|
| `🎙 Sales Floor`     | Hop in while you dial. Hear the bell ring across the team.         |
| `🎙 Founder Office`  | Closed-door strategy time. Founder + senior reps only.             |

## Step 3 — Roles to create

| role                 | color    | purpose                                                |
|----------------------|----------|--------------------------------------------------------|
| `Founder`            | gold     | Beers + any bullpen founder. Full perms.               |
| `KillSesh Member`    | mint     | Vetted rep in the KillSesh bullpen.                    |
| `Bullpen Operator`   | purple   | Founders running other bullpens on the platform.       |
| `Applicant`          | grey     | Anyone who's applied but isn't approved yet.           |

KillSesh-Member-only channels (the 9 in the `KILLSESH` category)
should restrict View Channel to that role + Founder.

## Step 4 — Paste this into Claude to fire it

Once the bot is in + MCP points at BullpenLM, paste this single prompt
in Claude and approve each tool call:

```
Set up the BullpenLM master Discord (guild 1508278033000304700) per
scripts/setup_discord_bullpenlm.md.

1. Create roles in this order: Founder (gold), KillSesh Member (mint),
   Bullpen Operator (purple), Applicant (grey).

2. Create categories in this order: 🪧 ABOUT, 🏢 BULLPENS, 💰 KILLSESH,
   🎟 JOIN, 💬 COMMUNITY, 🎙 VOICE.

3. For each category, create the channels listed in the doc with the
   exact name (lowercase, hyphens for spaces) and the topic from the
   topic column.

4. After everything is created, post the welcome message to #welcome:

   "🎯 Welcome to BullpenLM.

   This is the master server. One Discord, many bullpens — each bullpen
   is a real product being sold by a real team. The first one is
   KillSesh, my product. More launching soon.

   What this is:
   - 🪧 ABOUT — start here. What BullpenLM is + the rules.
   - 🏢 BULLPENS — directory of every bullpen running on the platform.
   - 💰 KILLSESH — the first bullpen. Apply at bullpenlm.com/app/apply.html
   - 🎟 JOIN — apply to a bullpen or launch your own.
   - 💬 COMMUNITY — general chat, sales talk, feature requests.
   - 🎙 VOICE — hop in while you dial.

   Read bullpenlm.com first. Then decide which bullpen you want in.

   — Beers"
```

## Step 5 — Wire the close-won feed (per bullpen)

For each bullpen, create a webhook on its `wins` channel and save it
to that bullpen's config. For KillSesh:

1. Go to `#killsesh-wins` → ⚙ Edit Channel → Integrations → Webhooks → New Webhook
2. Name it "KillSesh Bell", copy the URL
3. Set it in `bullpens/killsesh/bullpen.json`:
   ```json
   { "discord_webhook": "https://discord.com/api/webhooks/<id>/<token>" }
   ```

Once set, `server/discord.py` auto-posts to that channel on:
- 🔔 every `deal_closed_won` event
- 🌟 every epic/legendary achievement unlock
- 🐉 every raid quest completion
- ⚔ every sprint start
- 🥊 every 1v1 duel challenge

## Future server-side automation

Things the bot doesn't do yet but the architecture supports:
- **Auto-assign `KillSesh Member` role** when an application is
  approved (needs the applicant's Discord handle to be filled in + bot
  has Manage Roles).
- **DM the invite code** when an application is approved.
- **Slash commands** (`/dials today`, `/leaderboard`, `/sprint start`).
- **Daily summary** posted at 9 AM in `#announcements`.
- **Per-bullpen channels auto-created** when a new bullpen is spun up
  on the platform.
