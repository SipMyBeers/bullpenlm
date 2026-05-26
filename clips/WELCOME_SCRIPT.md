# The Welcome Montage — Beers Bot's First Words

This is the canonical intro for `#start-here`. ~15 seconds. Each line is a
distinct clip stitched together with a brief crossfade. Energy ramps from
a single phone ring to wall-of-sound by the end.

## The audio "script"

| # | Mood folder | Clip name | Source | Line / sound | Length |
|---|-------------|-----------|--------|---------------|--------|
| 1 | `taps/`     | `phone-ring-short` | any 80s/90s movie ring or stock | *RING RING* (single trill) | 0.8s |
| 2 | `hard-truth/` | `wolf-pick-up-phone` | Wolf of Wall Street — Belfort training scene (~1h13m, boiler room pump-up) | **"PICK UP THE PHONE! Pick up the phone! Pick up the phone!"** | 3.5s |
| 3 | `hype/`     | `wolf-money-doesnt-sleep` | Wolf of Wall Street — Mark Hanna lunch (early in film) | **"Money doesn't sleep, pal."** | 1.5s |
| 4 | `greeting/` | `wolf-name-is-jordan` | Wolf of Wall Street — opening narration | **"My name is Jordan Belfort."** | 1.5s |
| 5 | `hard-truth/` | `glengarry-abc` | Glengarry Glen Ross — Blake's pep talk | **"A. B. C. Always be closing."** | 2.5s |
| 6 | `taps/`     | `cash-register` | any 80s movie / stock effect | *KA-CHING* | 0.5s |
| 7 | `hype/`     | `wolf-name-of-game` | Wolf of Wall Street — boardroom training | **"The name of the game…"** (cut before he finishes the line — Beers Bot's tagline picks up where Belfort leaves off) | 1.5s |

**Total: ~12 seconds.** Punchy, doesn't overstay.

## The recipe

The `welcome` recipe in `server/bumblebee.py:EVENT_RECIPES` currently uses
generic tags. Once these specific clips exist, the recipe becomes a
fully-deterministic stitch instead of random-from-tag selection:

```python
EVENT_RECIPES["welcome"] = [
    "clips/taps/phone-ring-short.mp3",
    "clips/hard-truth/wolf-pick-up-phone.mp3",
    "clips/hype/wolf-money-doesnt-sleep.mp3",
    "clips/greeting/wolf-name-is-jordan.mp3",
    "clips/hard-truth/glengarry-abc.mp3",
    "clips/taps/cash-register.mp3",
    "clips/hype/wolf-name-of-game.mp3",
]
```

(The stitcher accepts both bare tags and explicit paths — the loader
preserves order for explicit paths.)

## How to grab the clips (20 min total)

For each row above:

1. Find a YouTube video that contains the moment — there are dozens of
   "Best of Wolf of Wall Street" supercuts that include all of these.
2. Note the timestamp range (typically 2-4 seconds of audio).
3. Run:
   ```bash
   python3 scripts/fetch_clip.py "<youtube-url>" \
     --start 1:24 --end 1:28 \
     --mood hard-truth \
     --name wolf-pick-up-phone
   ```
4. Repeat for each row.

Or batch it via the manifest in `clips/SOURCING.yaml` (paste your URLs
once, run `python3 scripts/fetch_clip.py --manifest clips/SOURCING.yaml`).

## After clips are populated

```bash
# Verify
python3 server/bumblebee.py list

# Render the welcome montage to /tmp/welcome.mp3 (don't post yet)
python3 server/bumblebee.py event welcome

# Listen
afplay clips/.out/stitch-*.mp3

# When you're happy, fire it to #start-here
python3 server/bumblebee.py post-welcome
```

## Notes on delivery

- **Crossfade is set to 80ms** — long enough to not pop, short enough to
  feel like hard cuts. Adjust in `bumblebee.py:stitch()` if you want
  more theatrical transitions.
- **Loudnorm flattens all sources to -16 LUFS** so quiet dialogue and
  loud crowd noise sit at the same perceived level.
- **Total montage should land at 10-15s.** Longer than that and people
  scroll past. The Bumblebee effect requires brevity.
