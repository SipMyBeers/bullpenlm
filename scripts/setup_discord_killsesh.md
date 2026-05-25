# KillSesh Discord — channel setup

The Beers bot is already a member of the KillSesh Discord server
(`1489398489787011256`). To give Claude write access through MCP, point
your Discord MCP config at KillSesh, restart, then paste the prompt at
the bottom into Claude and the channels create themselves.

## Step 1 — Reconfigure the MCP

Find wherever your Discord MCP server is set up (likely an Anthropic /
Claude Code MCP config file or env file) and update the guild ID:

```bash
# Old (Gormers):
DISCORD_GUILD_ID=1489402067922583642

# New (KillSesh):
DISCORD_GUILD_ID=1489398489787011256
```

Restart Claude / the MCP server.

Verify the bot is targeting KillSesh:
- in Claude, ask "list discord guilds" — `KillSesh` should show
  `isConfigured: true`.

## Step 2 — Channel structure

Six categories, 19 channels total. Bot-creatable via the prompt below
OR create them by hand in the Discord UI in ~15 minutes.

### 📋 INFO

| channel              | topic                                                              |
|----------------------|--------------------------------------------------------------------|
| `welcome`            | Read this first. Rules + how the bullpen works.                    |
| `rules`              | Don't dial House Accounts. Don't ghost. Don't be cringe.           |
| `briefing`           | What we're selling. The opener. The plays. (also lives in-app.)    |
| `commission-structure` | 50% pilot · expansion · renewal · 24-month window per account.   |

### 🎯 DAILY OPS

| channel              | topic                                                              |
|----------------------|--------------------------------------------------------------------|
| `floor`              | General chat. Where the team hangs while dialing.                  |
| `wins`               | 🔔 auto-feed from the bot on every closed-won deal.                |
| `pop-drills`         | TCS spot checks called from the app fire pings here.               |
| `raids`              | Raid quests announced + party-up.                                  |
| `daily-summary`      | Auto-posted morning recap of yesterday's bullpen activity.         |

### 🥊 COMPETITION

| channel              | topic                                                              |
|----------------------|--------------------------------------------------------------------|
| `leaderboard`        | Daily top 5 reps by XP / dials / closes.                           |
| `sprints`            | Active PvP sprints + start one with `!sprint` (future bot cmd).    |
| `duels`              | 1v1 practice-mode results + new challenges.                        |

### 💰 KILLSESH (the actual product we sell)

| channel              | topic                                                              |
|----------------------|--------------------------------------------------------------------|
| `killsesh-product`   | Product updates Beers ships that you can quote to prospects.       |
| `killsesh-objections`| Bank of objections we've heard + the best counter for each.        |
| `killsesh-wins-deep` | Long-form write-ups of how a deal closed (post-mortem style).     |

### 🎟 MEMBERSHIP

| channel              | topic                                                              |
|----------------------|--------------------------------------------------------------------|
| `apply`              | Read before you apply. Link to bullpenlm.com/app/apply.html        |
| `onboarding-help`    | Stuck on the wizard? Drop questions here.                          |
| `coaching`           | Ask Beers anything channel — public Q&A.                           |

### 🎙 VOICE

| channel              | topic                                                              |
|----------------------|--------------------------------------------------------------------|
| `🎙 Sales Floor`     | Hop in while you dial. Hear the bell ring across the team.         |
| `🎙 Strategy Room`   | Founder + senior reps. Closed.                                     |

## Step 3 — Paste this into Claude to fire it

Once the MCP is pointing at KillSesh, paste this single prompt and
Claude will create everything in sequence. Approve each tool call.

```
Set up the KillSesh Discord with the channel structure documented in
scripts/setup_discord_killsesh.md. Steps:

1. Create 6 categories in this order: INFO, DAILY OPS, COMPETITION,
   KILLSESH, MEMBERSHIP, VOICE.

2. For each category, create the channels listed in the doc with the
   exact name (lowercase, hyphens for spaces) and the topic field set
   to the topic column.

3. After all channels are created, post a #welcome message:

   "🎯 Welcome to the KillSesh bullpen.

   You're here because you want to learn enterprise sales by actually
   doing it. KillSesh is the product we sell — it makes Fortune-500
   mainframe-modernization engagements faster. You'll be calling
   Managing Directors at top BFSI shops.

   First: open bullpenlm.com and read the Briefing.
   Second: drill The Plays until they're reflex.
   Third: claim a prospect, dial, log the call.

   Every close-won rings the bell here in #wins. Every leaderboard
   change posts in #leaderboard. Every spot-check the founder fires at
   you pings in #pop-drills. Stay close to the channel during work
   hours and you'll learn fast.

   — Beers"
```

## Step 4 — Wire the close-won feed

In `bullpens/killsesh/bullpen.json`, set the webhook URL:

```json
{
  "discord_webhook": "https://discord.com/api/webhooks/<wins_channel_id>/<token>"
}
```

Get the webhook URL from Discord:
1. Go to `#wins` channel → ⚙ Edit Channel
2. Integrations → Webhooks → New Webhook
3. Name it "BullpenLM Bell", copy the URL
4. Paste into `bullpen.json` as shown

Once that's set, `server/discord.py` will auto-post:
- 🔔 every `deal_closed_won` event
- 🌟 every epic/legendary achievement unlock
- 🐉 every raid quest completion
- ⚔ every sprint start
- 🥊 every 1v1 duel challenge

## What's NOT in the bot's scope (yet)

- Reading Discord messages → posting them as activity in the CRM
- Sending DMs to applicants when they're approved (planned)
- A slash-command set (`/dials`, `/leaderboard`, etc.) (planned)
