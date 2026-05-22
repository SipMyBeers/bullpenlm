# The post-call loop

The single most defensible feature in Cheers Beers. Most CRMs are *manual
data entry after a call*. This one **uses the call as the data-entry
mechanism.**

## What happens after you hang up

```
┌──────────────┐
│ Click 🔴 in   │ ── MediaRecorder captures audio
│ org dossier   │
└──────┬───────┘
       ▼
┌──────────────┐
│ Hang up      │ ── audio uploaded to /api/upload-call
└──────┬───────┘
       ▼
┌──────────────────────────────────────┐
│ whisper-cli transcribes              │ ~30s for a 10-minute call
└──────┬───────────────────────────────┘
       ▼
┌──────────────────────────────────────┐
│ Ollama Gemma structured extraction:  │
│  - speakers (names, roles, emails)   │
│  - new contacts mentioned            │
│  - commitments (who/what/when)       │
│  - deal-stage signal                 │
│  - next action + meeting time        │
│  - red/green flags                   │
│  - 2-3 sentence summary              │
└──────┬───────────────────────────────┘
       ▼
┌──────────────────────────────────────┐
│ Auto-writes to disk:                 │
│  organizations/<slug>/                │
│    calls/<timestamp>/                 │
│      recording.wav                    │
│      transcript.txt                   │
│      extracted.json                   │
│      summary.md                       │
│      metadata.json                    │
│    people/<new-person>/   ← created   │
│      person.json                      │
│      speech_profile.md                │
│    deals/deal-<date>/    ← created    │
│      deal.json                        │
│    timeline.md           ← appended   │
└──────────────────────────────────────┘
```

The whole loop runs **locally**. No call audio leaves your machine.

## Using it from the CLI

```bash
# After dropping a recording.wav into a call folder:
python3 -m server.debrief cobol-cowboys/2026-05-23-001
```

Or:

```bash
python3 -m server.debrief organizations/cobol-cowboys/calls/2026-05-23-001
```

## Using it from the floor

1. Click any walking character → org dossier opens
2. Click the **People** tab
3. Hit the red **🔴 Record a call** button
4. Talk
5. Hit ⏹ to stop
6. The dossier updates in real-time as the debrief runs

## What the extraction prompt actually looks for

The system prompt to Gemma is intentionally strict — it asks for a JSON
schema with these fields:

| Field | Type | Example |
|---|---|---|
| `speakers` | array | `[{name:"Janet Patel", role:"Director Enterprise Arch", relationship:"decision_maker"}]` |
| `newContacts` | array | Names mentioned but not on the call (e.g. "talk to Rajeev") |
| `commitments` | array | `[{who:"Dylan", what:"send the SOW", by_when:"Friday"}]` |
| `dealSignal` | string | `cold` / `interest` / `warm` / `meeting_booked` / `proposal_requested` / `rejected` |
| `nextAction` | string | The single concrete thing to do next |
| `nextActionDate` | ISO date | If specified |
| `meetingTime` | ISO datetime | If a meeting was scheduled |
| `redFlags` | array | Concerning signals to escalate |
| `greenFlags` | array | Positive signals to capitalize on |
| `summary` | string | 2-3 sentence neutral summary |

The prompt also instructs Gemma to be **conservative** — return `(unknown)`
or `null` rather than hallucinate a name. We'd rather miss a contact than
invent one.

## Deal stage automation

The deal-signal output maps to a stage:

| Signal | Stage flip |
|---|---|
| `cold` | (no change) |
| `interest` | → `connected` |
| `warm` | → `qualified` |
| `meeting_booked` | → `discovery` |
| `proposal_requested` | → `proposal` |
| `rejected` | → `disqualified` |

A `deals/deal-<date>/deal.json` is auto-created the first time a non-cold
signal fires. Subsequent calls update the stage and append to the
`history[]` array.

## Things to watch out for

- **English-only transcription** — the model we ship is `ggml-base.en`. For
  multilingual support pull `ggml-base` (or `medium`) and update
  `WHISPER_MODEL` in `server/server.py`.
- **Long calls** — Gemma's context is capped at 16K tokens (~12K words /
  ~80 minutes of speech). For longer calls, the transcript gets truncated
  to the first 18K characters. Most cold-call conversations fit.
- **Quiet audio** — whisper happily transcribes silence as empty output;
  the debrief catches this and bails with `transcript too short`.
- **Two people on speakerphone vs handset** — quality drops on speakerphone.
  We don't run speaker diarization yet (would need pyannote or similar).
  For now, use a headset and the extraction works fine.

## What this is NOT

- Not a real-time transcription / coaching layer during a live call
- Not a sentiment dashboard for the whole team
- Not integrated with phone systems (Twilio, Aircall) — bring your own audio
- Not a Gong replacement at the enterprise tier — Gong does diarization,
  team-wide analytics, executive dashboards. Cheers Beers does *the moment
  after a single call*, very well, for free, on your laptop.
