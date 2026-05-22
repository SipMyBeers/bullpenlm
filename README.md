# BullpenLM

> **AI sales-call rehearsal grounded in your actual pipeline.**
> NotebookLM for your CRM — every prospect becomes an AI roleplay partner the moment you import them.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Local-first](https://img.shields.io/badge/local--first-100%25-success)
![Voice in/out](https://img.shields.io/badge/voice%20in%2Fout-whisper%20%2B%20say%2FXTTS-blue)

---

## What it is

Every sales-training tool out there (Second Nature, Mindtickle, Gong) trains
your reps on **generic personas you season with content**. That misses the
point. The conversation your AE is about to have isn't with "a skeptical
enterprise buyer." It's with **Sarah at Premera, who pushed back on price in
Q2 and prefers technical depth**.

BullpenLM flips it. Connect your CRM. Every prospect becomes an AI
roleplay partner with their actual context: company, role, pushback patterns,
public-talk transcripts, even a cloned voice if you want it. Your reps
rehearse the exact call they're about to make.

- 🧑‍💼 **Walking sales floor** — see your pipeline as people you can approach
- 🎙️ **Voice in, voice out** — push-to-talk practice, AI replies in the persona's voice
- 📊 **Auto-scored against your playbook** — every transcript graded A–F with specific fixes
- 🔒 **100% local** — Ollama + whisper.cpp + macOS TTS. Your CRM data never leaves your machine
- 🧱 **File-based personas** — every persona lives as plain markdown/JSON, no database, no lock-in

## Demo

```bash
git clone https://github.com/your-org/bullpen.git
cd bullpen
./scripts/install.sh      # brew installs ollama, whisper-cpp, yt-dlp
./scripts/pull-model.sh   # ollama pull gemma2:9b
python3 server/server.py
# → open http://localhost:7878 (trainer)
# → open floor/index.html (walking sales floor)
```

A sample persona ships at `personas/_sample/acme-finance/`. Copy it and edit
the markdown files to add your own.

---

## How it works

```
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Your CRM      │ →  │  personas/<slug>/│ →  │  BullpenLM    │
│  (CSV / HubSpot │    │  (markdown +     │    │  (local AI       │
│   / Salesforce) │    │   transcripts +  │    │   roleplay +     │
│                 │    │   voice samples) │    │   voice + score) │
└─────────────────┘    └──────────────────┘    └──────────────────┘
       ↑                       ↑                       ↑
   commercial             open source              open source
    (paid tier)              (this repo)             (this repo)
```

### The three enrichment tiers

| Tier | What's added | Effort | Quality gain |
|---|---|---|---|
| **★1** Personality + speech profile + pushbacks | `personality.md`, `speech_profile.md`, `pushbacks.txt` | 5 min | Baseline persona |
| **★2** Real quotes + public-talk transcripts | `examples.md`, `transcripts/*.txt` | 5–30 min | Mimics actual phrasing |
| **★3** Cloned voice from 30s sample | `voice/sample.wav` → XTTS-v2 | 10 min + one-time install | Sounds like the actual person |

Lower tiers always work — Tier 3 falls back to Tier 2 falls back to Tier 1.

### The CLI

```bash
cd personas

python3 manage.py list                            # show all personas + their tier
python3 manage.py new <slug>                      # scaffold a new persona
python3 manage.py ingest-talk <slug> <yt-url>     # tier-2 from a YouTube talk
python3 manage.py ingest-talk <slug> <file.mp3>   # or any local audio file
python3 manage.py clone-voice <slug>              # tier-3 voice cloning (XTTS-v2)
python3 manage.py show <slug>                     # dump the assembled system prompt
```

---

## Why local-first

Sales conversations are confidential. Pre-call rehearsal where the AI knows
real prospect names, deal stages, and notes is the kind of thing security
teams kill on the first VRM review if it touches a cloud LLM.

BullpenLM ships designed-for-air-gap from day one:

- **LLM:** Ollama (Gemma 2 9B by default — runs on any modern Mac/PC)
- **Speech-to-text:** whisper.cpp (~150MB model, runs locally, <1s transcription)
- **Text-to-speech (Tier 1):** macOS `say` command (built-in, no install)
- **Text-to-speech (Tier 3):** Coqui XTTS-v2 (local, optional, voice cloning)
- **No telemetry. No phone-home. No cloud API. Verifiable: `docker network inspect` on any deployment shows zero outbound connections.**

## Why "BullpenLM"

Built by [Beers Labs](https://github.com/SipMyBeers) (Dylan "Beers"). The
tool was first built to rehearse cold calls for **KillSesh**, an on-prem
COBOL modernization product. After 24 prospects of self-training, we
realized the engine should be its own thing.

The name is a toast — *cheers* to whoever picks up the other end of the line.

---

## CRM integrations (roadmap)

The OSS engine reads personas from files. **Commercial CRM connectors** write
those files automatically:

| Integration | Status | Tier |
|---|---|---|
| **CSV import** | ✅ planned for v0.2 | OSS |
| **HubSpot OAuth** | 🔜 v0.3 | Hosted |
| **Salesforce** | 🔜 v0.4 | Hosted |
| **Pipedrive, Outreach, Salesloft** | future | Hosted |

The roadmap lives at [`docs/crm-integrations.md`](docs/crm-integrations.md).

---

## Pricing

**Open source forever:** the entire engine (this repo). MIT license. Use it
solo, in your team, behind your own VPN, however you want.

**BullpenLM Cloud** *(coming · pre-launch)*:

| Tier | $/seat/mo | What you get |
|---|---|---|
| **Free (OSS)** | $0 | Everything in this repo · self-hosted |
| **Pro** | $49 | CSV import · hosted multi-tenant · unlimited practice |
| **Team** | $99 | CRM connectors · shared playbook · manager dashboard · scoring history |
| **Enterprise** | contact | SSO · audit logs · on-prem Ollama deployment · custom voice clones · SOC 2 |

If you're curious about the hosted version, email `hello@bullpen.com`.

---

## What's NOT here yet

Be honest about it:

- ✅ Personas as files · ★1 / ★2 / ★3 enrichment · CLI · local STT/TTS · trainer server · sales floor UI · scoring pass
- ✅ Org-centric model — companies as top-level, people accumulate underneath
- ✅ Post-call extraction loop — record → whisper → Gemma → auto-creates new contacts + deals
- ✅ Pre-call brief generator — AI 1-pager per call
- ✅ Adapter system — `website`, `google_places`, `osm`, `firecrawl`, `csv`, `social_signals`
- ❌ HubSpot/Salesforce OAuth sync — planned, hosted-tier
- ❌ Multi-tenant auth / workspaces — local-only for now
- ❌ Mobile / iOS app — desktop-only
- ❌ Cross-language (English-only for STT; XTTS supports more if you wire it up)
- ❌ Speaker diarization in call transcripts (one transcript stream; no per-speaker labels)

## Contributing

Issues + PRs welcome. The architecture is small enough to read in one sitting:

```
~440 lines  personas/loader.py     # how personas become system prompts
~340 lines  personas/manage.py     # the CLI
~ 80 lines  personas/clone_voice.py
~600 lines  server/server.py       # the trainer HTTP server
~900 lines  floor/index.html       # the walking sales floor + dossier
```

No build step. No bundler. Open the files and read.

## License

[MIT](LICENSE). Use it however you want.

Built by [Beers Labs](https://beerslabs.com).
