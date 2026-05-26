# BullpenLM Email Worker

Cloudflare Worker that sends branded outreach email on behalf of a BullpenLM
host. One Worker per Cloudflare account — each operator who wants their own
sending domain deploys their own copy.

## What it does

- Receives POST `/send` from the BullpenLM Python host
- Authenticates via shared secret (`Authorization: Bearer <secret>`)
- Sends the email via the `send_email` Workers binding (no SMTP, no API keys)
- Optionally enforces a domain allow-list

Template rendering lives in the host (`server/email_templates.py`). This
Worker is the thin last mile to Cloudflare's email infra.

## One-time setup (per operator)

1. **Onboard your sending domain to Cloudflare Email Service.**

   ```bash
   cd email-worker
   npm install
   npx wrangler login                         # authenticate this machine
   npx wrangler email sending enable killsesh.com
   ```

   Add the DNS records Cloudflare prints (SPF / DKIM / DMARC) to your zone.
   Wait a few minutes for verification to clear.

2. **Set the shared secret.** This is what the BullpenLM host uses to
   authenticate into this Worker.

   ```bash
   # Generate a strong random value (32+ chars). Write it down — you'll
   # paste it on the host machine in step 4.
   openssl rand -hex 32

   # Then put it into the Worker as a Cloudflare secret:
   npx wrangler secret put BULLPENLM_SHARED_SECRET
   ```

3. **(Optional) Restrict which `from` domains this Worker will send for.**
   Edit `wrangler.jsonc`:

   ```jsonc
   "vars": {
     "ALLOWED_FROM_DOMAINS": "killsesh.com,bullpenlm.com",
     "DEFAULT_REPLY_TO": "dylan@killsesh.com"
   }
   ```

4. **Deploy.**

   ```bash
   npx wrangler deploy
   ```

   Wrangler prints the deployed URL (e.g. `https://bullpenlm-email.<your-account>.workers.dev`).
   Note it.

5. **Tell the BullpenLM host where the Worker lives.** On the operator's
   machine:

   ```bash
   mkdir -p ~/.bullpenlm
   cat > ~/.bullpenlm/email-worker.json <<EOF
   {
     "url":    "https://bullpenlm-email.<your-account>.workers.dev",
     "secret": "<the same value you set in step 2>"
   }
   EOF
   chmod 600 ~/.bullpenlm/email-worker.json
   ```

   The BullpenLM server reads this file when it needs to send. Missing
   file = no-op (the audit log still records the intent so you can
   manually send later).

## Verify

```bash
curl https://bullpenlm-email.<account>.workers.dev/
# {"ok":true,"service":"bullpenlm-email","v":"0.1"}

# Smoke send (with the secret):
SECRET=$(cat ~/.bullpenlm/email-worker.json | jq -r .secret)
URL=$(cat ~/.bullpenlm/email-worker.json | jq -r .url)

curl -X POST "$URL/send" \
  -H "Authorization: Bearer $SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "from": { "email": "dylan@killsesh.com", "name": "Dylan Beers" },
    "to":   "youremail@gmail.com",
    "subject": "Smoke test from BullpenLM",
    "text":    "If you got this, the Worker is wired.",
    "html":    "<p>If you got this, the Worker is wired.</p>"
  }'
```

If you get `{"ok": true, ...}`, you're live.

## How BullpenLM calls it

The Python host's `POST /api/b/<slug>/email/send` (founder-only) renders the
template via `server/email_templates.py:render(name, vars, bullpen)`, looks
up the Worker URL + secret from `~/.bullpenlm/email-worker.json`, and POSTs
`/send` here. The result + recipient + template name get written to the
bullpen's audit log.

Auto-fire wiring (close-won → `close-won-thanks` template, level-up →
`level-up-congrats`, etc.) lives in `server/discord.py:notify` alongside
the existing webhook fires — same pattern.

## Cost

Cloudflare Email Service is **free for the first 100 sends/day**, then
pay-as-you-go. BullpenLM doesn't add overhead. The Worker itself is on
Workers free tier (100k requests/day).

## Don't put this in source control

The shared secret and Worker URL live in `~/.bullpenlm/email-worker.json`
on each host — that file is outside the repo. Never commit it.
