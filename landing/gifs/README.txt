Drop these four GIF files into this folder. Cloudflare Pages will serve
them at https://bullpenlm.com/gifs/<filename>.gif and the landing page
references them directly.

Required filenames:

  bateman-nod.gif       — Patrick Bateman approving nod (American Psycho)
  wolf-floor-cheer.gif  — Sales floor erupts / cheering scene (Wolf of Wall Street)
  wolf-chest-pound.gif  — The chest-pound chant (Wolf of Wall Street, McConaughey)
  wolf-pump-up.gif      — Belfort's "I'm not leaving" pump-up (Wolf of Wall Street)

Until you drop a file, the slot shows a stylized "DROP GIF HERE" placeholder
with the right aspect ratio + film-stock styling. As soon as the file
exists in this folder and you redeploy (wrangler pages deploy landing
--project-name=bullpenlm --branch=main --commit-dirty=true), it shows up.

Easiest way to source: search the scene on giphy.com or tenor.com, hit
"copy GIF link" or download the GIF, drop it here with the exact filename
above. Keep them under ~3MB each so the page doesn't drag.
