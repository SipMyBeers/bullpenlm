# Architecture

Three components, ~2,400 lines of code total, all read-in-one-sitting.

## 1. Personas (`personas/`)

The source of truth. Each persona is a directory on disk:

```
personas/<slug>/
├── persona.json       — base fields (required)
├── personality.md     — internal state (required)
├── speech_profile.md  — linguistic fingerprint (Tier 1)
├── pushbacks.txt      — verbatim objections (required)
├── examples.md        — real quotes (Tier 2)
├── transcripts/       — full transcripts of public talks (Tier 2)
└── voice/             — sample.wav + clone_config.json (Tier 3)
```

**`loader.py`** reads every persona directory into runtime `Persona` objects.
Builds the system prompt the LLM sees, layering in Tier 2/3 enrichment when
present.

**`manage.py`** is the CLI: `list`, `new`, `ingest-talk`, `clone-voice`, `show`.

**`clone_voice.py`** is the Tier-3 voice-cloning helper — wraps Coqui XTTS-v2.

The whole loader + CLI knows nothing about the trainer or the floor. You can
use it standalone to manage personas in any other tool.

## 2. Trainer server (`server/server.py`)

A single Python file using stdlib `http.server`. No web framework.

### Endpoints

| Path | What it does |
|---|---|
| `GET /` | Serves the chat UI (HTML embedded in `server.py`) |
| `GET /api/personas` | Returns the loaded persona list + tier indicators |
| `POST /api/chat` | One conversation turn — sends history to Ollama, returns AI reply |
| `POST /api/transcribe` | Raw WAV bytes → whisper-cli → transcript |
| `POST /api/synthesize` | `{text, slug}` → WAV (XTTS-v2 if cloned, else macOS `say`) |
| `POST /api/score` | Full transcript → coach grading → saves markdown to `training-runs/` |

### Voice stack

- **STT:** `whisper-cli` (whisper.cpp) on the `ggml-base.en` model. ~500ms per utterance on Apple Silicon.
- **TTS Tier 1:** macOS `say` command piped through `afconvert` → browser-playable WAV. Distinct voice per persona via the `say_voice` field.
- **TTS Tier 3:** Coqui XTTS-v2 (optional pip install). Reads `voice/clone_config.json` and synthesizes in the cloned voice. Falls back gracefully if not installed.

## 3. Sales floor (`floor/index.html`)

A single static HTML file. No server. Loads in any browser.

- Top-down 2D Canvas rendering of every persona as a walking character
- Procedural-sprite walk cycle (sliced quads, à la [boona13/crowds-system-js](https://github.com/boona13/crowds-system-js))
- Zone quadrants (End Customer / Channel / Tool / Boutique)
- Click any character → dossier modal with bio + ABCs + pushbacks
- Status indicators above each head (cold/sent/voicemail/connected/qualified/discovery/signed/disqualified)
- Meeting-time pills below each name when scheduled
- Editable status panel inside the dossier (saves to `localStorage`)
- "Practice Call" button → opens trainer at `http://localhost:7878/?persona=<slug>&autostart=1`

The floor is the **at-a-glance pipeline view**. The trainer is the
**rehearsal lab**. They share persona data; the floor stores transient state
(status, meeting time, notes) in localStorage.

## Data flow

```
                ┌──────────────────┐
                │  personas/<slug>/│
                │   (files on disk)│
                └────────┬─────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
┌───────▼──────┐  ┌──────▼──────┐  ┌──────▼─────────┐
│  loader.py   │  │  manage.py  │  │  server.py     │
│  (build      │  │  (CLI ops)  │  │  (HTTP +       │
│   prompts)   │  │             │  │   Ollama)      │
└───────┬──────┘  └─────────────┘  └───────┬────────┘
        │                                  │
        │   ┌──────────────────────────────┘
        │   │
┌───────▼───▼────────┐
│  floor/index.html  │ ◀── reads /api/personas
│  (sales floor UI)  │ ◀── practice-button POSTs to /api/chat, /api/transcribe
└────────────────────┘
```

## What this design optimizes for

1. **No lock-in.** Personas are plain text. Migrating to a different tool is `cp -r`.
2. **No build step.** Read the file, run the file. No bundlers, no transpilers, no node_modules.
3. **Air-gappable.** Once installed, no external network calls. Verifiable via `docker network inspect` or `lsof -i` while running.
4. **Composable.** The loader is a standalone Python module — pull personas into any other tool you want to build.

## What this design defers

- **Multi-tenant auth** — there is none. This is single-user/team-local.
- **Database** — there is none. Files on disk.
- **Real-time collaboration** — no. (Could add via the same localStorage→sync pattern, but not yet.)
- **CRM integration** — the personas loader is the integration surface. Connectors live downstream in the (paid) hosted version.
