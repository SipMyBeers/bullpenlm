# Security posture

BullpenLM is a self-hosted, files-first system. The security model is
"your machine, your data" — no central server custodies your bullpen.
This doc spells out what's safe to commit, where secrets live, and how
to think about exposure when you fork or run your own bullpen.

## What ships in this public repo

✅ Code (Python server, HTML/JS frontends, Cloudflare Workers, Rust Tauri shell)
✅ Templates (legal docs, email templates, playbook prompts) with `{{var}}` placeholders
✅ Default brand assets (BullpenLM logos, hero typography)
✅ Marketing landing page

## What NEVER ships in this repo

All of this is `.gitignore`d. Don't `git add -f` it:

| Path | What | Why it's private |
|---|---|---|
| `bullpens/<slug>/` | Each bullpen's full state | Audit logs, member records, signed agreements, invoices, deal pipeline, claims |
| `team/invites/` | Invite codes + redemption state | Live + used codes — leaking gives anyone a seat |
| `team/sessions.json` | Active rep sessions (HMAC cookies) | Leaking lets anyone impersonate any rep |
| `training-runs/` | Practice-call transcripts | Real conversation logs |
| `personas/*/voice/*.wav` | Voice samples for cloning | Per-person voice data |
| `organizations/*/calls/` | Real customer call recordings | Real audio of real people |
| `clips/*/*.mp3` etc. | Bumblebee montage source clips | Fair-use risk if redistributed |
| `server/models/*.bin` | Whisper / GGUF model binaries | Large, downloaded at install time |

## Where the secrets actually live

Outside the repo entirely, in `~/.bullpenlm/` (mode `0600`):

| File | Contains | Created by |
|---|---|---|
| `~/.bullpenlm/host-secret` | 32-byte HMAC secret for session cookies | First invite redemption |
| `~/.bullpenlm/showcase-webhook.txt` | Discord webhook for #showcase auto-posts | Operator's setup script |
| `~/.bullpenlm/start-here-webhook.txt` | Discord webhook for #start-here Bumblebee posts | Operator's setup script |
| `~/.bullpenlm/tunnel.json` | Currently-running Cloudflare Quick Tunnel state | `start_tunnel()` |
| `~/.bullpenlm/stripe.json` | Stripe API key (if/when paid invites are wired up) | `POST /api/stripe/key` |
| `~/.bullpenlm/email-worker.json` | Cloudflare Email Worker URL + shared secret | Operator after `wrangler deploy` |

The Python server reads these at runtime. They're never logged, never
committed, and never sent over the network except to the matching
service (Discord webhook → Discord, Stripe key → api.stripe.com, etc.).

## What you control as an operator

When you run BullpenLM on your Mac Mini or VPS, every commission record,
every signed agreement, every call recording lives on **your disk**.
BullpenLM has no central database. Even Cloudflare Quick Tunnels
(which give you the public URL) terminate at your machine — Cloudflare
doesn't see your bullpen's contents, only the encrypted HTTPS bytes.

To wipe a bullpen completely: `rm -rf bullpens/<slug>/` on the host.
That's the whole reset.

## What closers can see

A closer who joins your bullpen via invite code gets:

- A session cookie signed with your `~/.bullpenlm/host-secret`
- Access to `today.html`, `briefing.html`, `legal.html`, `commissions.html`,
  the floor, etc. — all per-bullpen
- **Their own** invoices and audit history (filtered server-side by rep)
- A view of the leaderboard + recent activity feed (per-bullpen)

A closer **cannot** see:

- Other closers' invoices, commissions, or signed agreements
- The audit log full chain (only their own events surface in their feed)
- The operator's `~/.bullpenlm/` files
- Other operators' bullpens at all

This separation is enforced by the bullpen-scoped audit log + the
`_current_rep()` check on every API endpoint.

## What the operator can see (and you should be transparent about)

You, as the operator, can see every closer's transcripts, calls, claims,
and audit events on your floor. Make sure your rep agreement (auto-
rendered into `bullpens/<slug>/legal/referral-agreement.md` by the
wizard) says so explicitly so closers know what they're signing up for.

The shipped template already has a confidentiality clause covering
this — review it before sending to your first rep.

## Reporting a vulnerability

If you find a security issue:

1. **Do not file a public GitHub issue.** Email beers directly via the
   address in [`README.md`](README.md).
2. Include: reproduction steps, affected version (commit hash), and
   suggested fix if you have one.
3. Don't share the issue publicly until it's patched.

## What rotating actually looks like

If a secret in `~/.bullpenlm/` ever leaks (laptop stolen, screenshot
posted publicly, etc.):

```bash
# Host secret — invalidates every active session cookie
rm ~/.bullpenlm/host-secret
# Server regenerates one on next request. Every closer has to re-redeem.

# Discord webhook — generate a new one in Discord channel settings
echo "https://discord.com/api/webhooks/<new-id>/<new-token>" > ~/.bullpenlm/showcase-webhook.txt
chmod 600 ~/.bullpenlm/showcase-webhook.txt
# Then delete the old webhook in Discord's UI so the leaked URL stops working

# Cloudflare Email Worker secret
npx wrangler secret put BULLPENLM_SHARED_SECRET
# Update ~/.bullpenlm/email-worker.json with the new value
```

## Audit chain

Every mutation flows through `audit.append()` which writes a hash-
chained JSONL line. To verify the chain at any time:

```bash
python3 server/audit.py verify <bullpen-slug>
# Prints: ✓ Chain verified for bullpen '<slug>'
# Or:     × break at index N
```

A break means someone (or something) edited `audit.jsonl` directly,
bypassing the server. Investigate before trusting any downstream
record (commissions, signed-doc snapshots, member onboarding state).
