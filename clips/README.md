# Bumblebee Clips

Beers Bot communicates Bumblebee-style — it stitches together short clips
from the salesfloor canon to deliver each message. No synthetic voice
cloning. No fake impersonation. Just collage of real moments, recontextualized.

## How to add clips

Drop MP3 / M4A / WAV / OGG files into the right mood folder:

```
clips/
  hype/         — pump-up energy ("LET'S GO!", war drums, hype reel)
  greeting/     — openers, intros, "look who just walked in"
  close/        — closed-won celebrations, money sounds, cheers
  hard-truth/   — Belfort/Glengarry/Boiler-Room reality checks
  objection/    — pushback / disbelief / "pump the brakes"
  raid/         — group hype, team callouts, raid-quest energy
  taunt/        — duel challenges, 1v1 callouts
  taps/         — short stings (door slam, gavel, cash register)
```

Keep each clip **1-3 seconds**. Longer clips dilute the Bumblebee effect.

## Naming

Use kebab-case descriptive names so a human can browse the library:

```
clips/hype/eye-of-the-tiger-riff.mp3
clips/close/wolf-pound-chest.mp3
clips/hard-truth/glengarry-coffee-is-for-closers.mp3
clips/taps/cash-register.mp3
```

## Legal notes

We're using short clips of copyrighted media under fair use (transformative,
non-substitutive). The risk is small for a private Discord but real if you
post the stitched audio publicly at scale. Don't ship the raw clip library
in any product downloads — it stays out of git (`clips/*/` is gitignored).
Beers Bot stitches and posts the result; the source clips never leave the
host.

## Sources Beers tends to pull from

- Wolf of Wall Street
- Boiler Room
- Glengarry Glen Ross
- Wall Street (1987)
- The Sopranos
- The Wire
- 80s/90s hip-hop hype tracks (sting drops, not full songs)
- Sports commentary (clutch-moment audio)

## Testing your library

```bash
# List what's loaded
python3 server/bumblebee.py list

# Build a montage of 3 hype clips + 1 close → /tmp/test.mp3
python3 server/bumblebee.py stitch --tags hype,hype,hype,close --out /tmp/test.mp3

# Play it (macOS)
afplay /tmp/test.mp3

# Post it to #start-here as a pinnable welcome message
python3 server/bumblebee.py post-welcome
```
