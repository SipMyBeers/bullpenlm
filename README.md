# BullpenLM

> **NotebookLM, but for sales calls.** A self-hosted, multiplayer CRM
> where building a business is the meta-game. Drop in your CRM →
> BullpenLM creates an AI version of every prospect → cold-call them →
> get graded on filler words and pitch discipline → level up before the
> real call.

**[bullpenlm.com](https://bullpenlm.com)** · open source (MIT) · runs
entirely on your laptop · your data never leaves.

---

### Status: Phase 0 (Alpha) · Phase 0.5 firewall in code, awaiting counsel

The product is **real**: real CRM, real cold calls, real commissions,
real legal docs between operators and their closers. Not a simulator of
a sales floor — *the* sales floor, plus a sim layer for practice.

The architecture is **airtight before it's wide**: real product, small
floor, firewall in code. See [`ROADMAP.md`](./ROADMAP.md) for the
phases and [`docs/COMP_AND_LEGAL.md`](./docs/COMP_AND_LEGAL.md) for the
counterparty model.

**Platform posture in one line:** Beers Labs ships tooling. The
operator is the contracting party. The closer is the operator's 1099.
BullpenLM is on zero contracts between them.

The two structural firewalls (verified in code, see [`tests/`](./tests/)):

1. **Two-ledger XP.** Money-XP (closed deals + drill certs) and
   clout-XP (volume, social, vanity) never merge. Recruiting another
   closer awards zero of either.
2. **Allocation firewall.** The prospect-claim priority function in
   `server/gates.py` accepts only money-XP, cert score, and close rate.
   The `EarningInputs` dataclass has no field for clout-XP, invite
   count, post count, or rank — type-system-enforced.

The FTC Koscot pyramid test — does the money trace to product sold to
real external customers, or to recruitment/promotion of the
opportunity? — has a code-level answer here, not a copy-tweak answer.

---

## What this is

- **A CRM** — drop in HubSpot / Salesforce / any CSV; every contact
  becomes a roleplay persona.
- **A practice arena** — 7-phase Gauntlet of progressively harder
  drills (gatekeeper → pitch → objection → CIO elevator → handoff). Pass
  one to unlock the next. Earn badges + rank up.
- **A real-call recorder** — hit record on a real call → whisper
  transcribes locally → Gemma extracts contacts, deal signals, next
  steps → your CRM writes itself.
- **A live multiplayer game** — multiple reps join one bullpen (your
  Mac Mini hosts; teammates Tailscale or visit a tunnel URL with an
  invite code). Shared leaderboard, claims, activity feed. Plus deal
  pipeline + weighted forecast + hash-chained audit log.
- **A founder's toolkit** — anyone can spin up a new bullpen for their
  own product. They become the founder; they decide the legal docs,
  commission structure, who joins.

## Quick start (host your own)

```bash
git clone https://github.com/SipMyBeers/bullpenlm.git
cd bullpenlm

# Install dependencies
brew install ollama whisper-cpp
ollama pull gemma2:9b
ollama serve &
pip3 install pypdf certifi

# Download the whisper model (~466 MB, one-time)
mkdir -p server/models
curl -L -o server/models/ggml-small.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin

# Start the trainer
python3 server/server.py

# Open the floor in your browser
open floor/index.html
```

Or with Docker (one container hosts everything; Cloudflare Tunnel
included so you can share a public URL with teammates):

```bash
docker compose up -d
docker compose logs -f tunnel   # grab the trycloudflare.com URL it prints
```

See [HOSTING.md](HOSTING.md) for the full hosting guide
(Mac Mini · VPS · Tailscale path · invite codes).

## Architecture in 30 seconds

```
┌──────────────────────────────────────────────────────────────┐
│  YOUR MAC MINI (or a small VPS)                              │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Trainer server (Python http.server, port 7878)        │  │
│  │   ├─ Ollama (Gemma 2 9B) for AI personas + scoring     │  │
│  │   ├─ whisper.cpp for local STT                         │  │
│  │   ├─ macOS `say` / XTTS-v2 / ElevenLabs for TTS        │  │
│  │   ├─ bullpens/<slug>/ — per-tenant data on disk        │  │
│  │   └─ hash-chained audit.jsonl (tamper-evident)         │  │
│  └────────────────────────────────────────────────────────┘  │
│                            │                                 │
└────────────────────────────┼─────────────────────────────────┘
                             │
                Cloudflare Tunnel / Tailscale
                             │
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
        Brad's laptop    Mike's laptop    Your laptop
        (browser opens   (browser opens   (browser opens
         tunnel URL +     tunnel URL +     localhost:7878)
         invite code)     invite code)
```

## Repo layout

```
server/             Python HTTP server + business logic
  server.py             HTTP shell, routes
  bullpens.py           Multi-tenant: one bullpen = one folder
  team.py               Claims, roster, leaderboard, activity feed
  invites.py            HMAC-signed cookies + single-use invite codes
  pipeline.py           Pipeline + stages + probabilities
  deals.py              Deal CRUD + weighted forecast
  audit.py              Hash-chained append-only event log
  metrics.py            Speech metrics (talk ratio, fillers, hedges)
  debrief.py            Whisper + Gemma post-call extraction
  orgs.py               Org graph loader
  crm/hubspot.py        HubSpot OAuth + sync

floor/              Browser UI (vanilla JS, no framework)
  index.html            The sales-floor canvas
  app/
    deals.html          Pipeline kanban

landing/            Marketing site (deployed to bullpenlm.com)
  index.html            Hero, Gauntlet, Multiplayer, FAQ
  join.html             Friend-invite redeem page

personas/           AI buyer personas
  _library/             8 starter training personas
  loader.py             Persona loader + prompt builder

sales/              Legal-doc + sales-playbook templates
  referral-agreement.md
  house-accounts.md
  playbook.md
  cheat-card.md
  the-gauntlet.md

adapters/           Universal ingest (URL, CSV, PDF, EML, JSON, TXT)
scripts/            One-shot CLI utilities + the migration script
```

## What it's NOT

- Not a SaaS — you host it. Your data never leaves.
- Not a coach — Gemma scores you on objective metrics (filler words, talk
  ratio, pitch discipline) but it doesn't motivate you. That's your job.
- Not a CRM replacement (yet) — works alongside your existing CRM via
  CSV import; deeper integrations are roadmap.

## License

MIT. Use it. Fork it. Sell consulting on top of it. Don't pretend you
wrote it.

— Beers Labs LLC
