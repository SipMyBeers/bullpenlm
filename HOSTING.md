# Hosting BullpenLM for a team

You host. Your friends connect. One shared bullpen, one CRM, one
leaderboard. Two supported deployment paths: **Mac Mini** (easiest, what
Beers uses) and **VPS** (Hetzner, DigitalOcean, etc. — for when you want
the team to access it without your Mac being on).

The team layer (claims · leaderboard · live feed) is server-rendered, so
teammates don't install anything. They just type a URL.

---

## Path A — Mac Mini (recommended for 2-5 reps)

Your Mac Mini stays on, runs the trainer in a Docker container,
teammates connect over Tailscale (free for personal use).

### Prereqs (one-time, on the host Mac Mini)

1. Install Docker Desktop for Mac: https://docs.docker.com/desktop/install/mac/
2. Install Ollama (so the LLM runs natively on the host's GPU, not in
   the container which would be much slower):
   ```bash
   brew install ollama
   ollama pull gemma2:9b
   ollama serve   # leave running in a Terminal tab, or set up as a launchd service
   ```
3. Install Tailscale: https://tailscale.com/download/mac

   ```bash
   tailscale up
   tailscale status   # confirm you're connected
   tailscale ip       # write down your Tailscale IP (e.g. 100.78.12.34)
   ```

### Bring up the bullpen

```bash
cd ~/bullpenlm
docker compose up -d
docker compose logs -f       # watch first-boot — whisper.cpp compile + model download takes ~5 min
```

Once you see `BullpenLM · trainer + org graph + post-call debrief listening on :7878`,
the server is live.

Open in your browser to confirm:
```
http://localhost:7878/api/team/roster
```
should return `{"reps":["self"]}`.

Open the floor UI by serving the static `floor/` directory from any web
server, or just open the HTML file directly:
```bash
open ~/bullpenlm/floor/index.html
```

### Invite teammates

1. Send them a Tailscale invite via the **Tailscale admin console →
   Users → Invite users**. They install Tailscale on their Mac/Windows
   box, accept the invite, run `tailscale up`.
2. Send them this URL:
   ```
   http://<YOUR-TAILSCALE-IP>:7878/
   ```
   (Replace `<YOUR-TAILSCALE-IP>` with the IP from `tailscale ip` above.)
   Their browser will load the trainer page. They set their **REP name**
   in the top-right of the floor UI and they're in.
3. For the floor UI specifically, they need either:
   - A local copy of `floor/index.html` they open in a browser
     (it'll talk to your hosted backend), OR
   - You serve it from a public URL (e.g. via the same Docker container
     by adding a static mount).

   Easiest: zip + share `floor/index.html` to each teammate.

### Tearing down / upgrading

```bash
docker compose down            # stop
docker compose up -d --build   # rebuild after pulling new code
```

The four `volumes:` in `docker-compose.yml` (`organizations/`,
`training-runs/`, `team/`, `personas/`) persist your team's data
across rebuilds.

---

## Path B — VPS (no host Mac required)

When your team is bigger than 5 reps, or you want bullpen access without
keeping a Mac on, run it on a small Linux box. ~$10–20/month.

### Recommended sizing

| Provider     | Plan                                | Cost      | Notes                                                |
|--------------|-------------------------------------|-----------|------------------------------------------------------|
| Hetzner CPX21 | 3 vCPU · 4 GB RAM · 80 GB SSD       | €8/mo     | Best price/perf. Gemma 2 9B runs ~5 tok/s on CPU.    |
| DO Droplet   | Premium AMD · 4 vCPU · 8 GB RAM     | $48/mo    | Faster Ollama responses but pricier.                  |
| Fly.io       | shared-cpu-2x with 4GB              | ~$20/mo   | If you want autoscaling, but cold-starts hurt UX.     |

For a 5–10 rep team running Gemma 2 9B, Hetzner CPX21 is the sweet spot.
If you want fast LLM responses (sub-3s scoring), get a dedicated GPU box
(Hetzner GEX44, ~€200/mo) — out of scope for this guide.

### Setup (Ubuntu 24.04 host)

```bash
# As root on the VPS:
apt update && apt install -y docker.io docker-compose-plugin ollama
ollama pull gemma2:9b
systemctl enable --now ollama

# Clone the repo
git clone <your-fork-url> /opt/bullpenlm
cd /opt/bullpenlm

# Bring up the trainer
docker compose up -d --build
```

### Putting Caddy in front for HTTPS + auth

Don't expose port 7878 to the public internet directly — anyone could
ingest into your CRM. Put Caddy in front for HTTPS + HTTP-basic-auth so
only your team's invited reps can reach the floor:

```bash
apt install -y caddy
cat > /etc/caddy/Caddyfile <<'EOF'
bullpen.your-domain.com {
    basicauth {
        # Generate hash with: caddy hash-password
        beers     $2a$14$..hash..
        bradley   $2a$14$..hash..
        mike      $2a$14$..hash..
    }
    reverse_proxy localhost:7878
}
EOF
systemctl restart caddy
```

Now teammates visit `https://bullpen.your-domain.com/`, get prompted for
their user/pass, and the rest works the same as Tailscale path. The
REP field they type in the floor still drives attribution; basic auth
just gates network access.

---

## What teammates see when they connect

1. **The floor** — every prospect in your CRM. Hover for the tooltip,
   click for the dossier.
2. **The Call Queue (top-left)** — ranked Top 5 to call right now.
3. **The Team Panel (NEW)** — every rep's rank, badges, recent activity.
4. **Claim buttons** — every prospect can be claimed by one rep at a
   time. Claims auto-release after 14 days of no activity from the owner.
5. **Live activity ticker** — bottom of the floor. Real-time scroll of
   "Brad just passed Phase II on Allstate" / "Mike claimed Cigna" etc.

All of this is keyed off the **REP name** they type in the header
(persisted per-browser via localStorage). No passwords inside the app —
your Tailscale or Caddy basic-auth is the perimeter.

---

## Files & directories your team shares

When the trainer is running, every teammate's actions write to the
host's filesystem under these directories:

```
~/bullpenlm/
├── organizations/<slug>/        # CRM. Anyone can ingest new prospects here.
│   ├── org.json                 # Company facts
│   ├── digital.md               # Research notes
│   ├── calls/<call-id>/         # Per-call recordings, transcripts, metrics
│   ├── people/<slug>/           # Known contacts at this prospect
│   └── deals/<slug>/            # Open opportunities
│
├── training-runs/               # Practice + speaking session logs (per rep)
│   └── 2026-05-24-allstate-attempt-3.metrics.json
│
├── team/                        # The team layer's state
│   ├── claims/<slug>.json       # Active territory locks
│   └── activity.jsonl           # Append-only event feed
│
└── personas/                    # Library + custom personas (shared)
    └── _library/                # Built-in 8 training personas
```

Back up `organizations/`, `training-runs/`, and `team/` regularly.
Those are the team's product. The code can be re-cloned from git.

---

## Troubleshooting

**"Ollama connection refused" in container logs**
On Mac, set `OLLAMA_HOST=http://host.docker.internal:11434` in
`docker-compose.yml` (already done by default). On Linux VPS, Ollama
should be reachable at `http://localhost:11434` from the container — set
`network_mode: "host"` on the container in `docker-compose.yml`.

**Whisper timeouts**
The first run downloads + compiles whisper.cpp. Once cached, transcription
takes ~2-3x realtime on CPU. If your VPS is underpowered, bump
`--timeout 120` in the whisper invocations or use the `tiny.en` model
(swap `WHISPER_MODEL` env in `server/server.py`).

**Teammates can connect but their REP names don't show up**
The roster auto-populates as soon as a teammate writes their first call
log. Have them practice one drill — they'll appear instantly.

**Claims won't release**
Use the manual release button in the prospect dossier, or delete the
claim file: `rm team/claims/<slug>.json`. The host has final say.

---

## Default = secure-by-Tailscale

If you don't want to think about auth, the safest setup is:

1. Host on your Mac Mini
2. Use Tailscale for the network perimeter
3. Don't expose port 7878 to the public internet
4. Trust the team you've invited (`tailscale status` shows everyone)

That's how Beers Labs runs it. Public/VPS path is for when the team
grows past Tailscale's free tier (currently 3 users + 100 devices).
