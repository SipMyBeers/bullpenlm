"""
adapters/refresh.py — refresh org intel periodically.

For each org, re-runs:
  - website ingest (re-reads homepage with fresh Gemma extraction)
  - social_signals (tech/social/freshness)
  - modernization_signals (COBOL-specific scans)

Writes a refresh-log.md per org capturing what CHANGED since last refresh.
Cron this nightly or run manually before a big call day:

    python3 -m adapters.refresh --all
    python3 -m adapters.refresh --org allstate
    python3 -m adapters.refresh --industry Insurance --limit 10
"""
from __future__ import annotations
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from adapters._common import ORGS_ROOT
from adapters.social_signals import analyze as analyze_social, render_signals_md
from adapters.modernization_signals import run_one as scan_mod
from adapters.website import ingest_website


def _diff_signals(old_path: Path, new_data: dict) -> list[str]:
    """Compute a list of human-readable changes from old → new signals."""
    if not old_path.exists():
        return [f"first refresh — baseline established with {len(new_data.get('hits', []))} signals"]
    try:
        old = json.loads(old_path.read_text())
    except Exception:
        return ["could not parse old signals — overwriting"]

    old_hits = {(h["category"], h["match"]) for h in old.get("hits", [])}
    new_hits = {(h["category"], h["match"]) for h in new_data.get("hits", [])}
    added = new_hits - old_hits
    removed = old_hits - new_hits

    msgs = []
    if added:
        msgs.append(f"+{len(added)} new signal(s): " + ", ".join(f"{c}:{m}" for c, m in list(added)[:5]))
    if removed:
        msgs.append(f"-{len(removed)} dropped: " + ", ".join(f"{c}:{m}" for c, m in list(removed)[:5]))
    if not added and not removed:
        msgs.append("no changes since last refresh")
    return msgs


def refresh_org(slug: str, *, skip_website: bool = False) -> dict:
    d = ORGS_ROOT / slug
    if not d.exists():
        return {"slug": slug, "skipped": "org not found"}
    org = json.loads((d / "org.json").read_text())
    web = org.get("web")
    if not web or web.startswith("(") or web in ("(unknown)", "(no website found)"):
        return {"slug": slug, "skipped": "no web URL"}

    print(f"▸ refreshing {slug} ({web})…")
    changes = []
    today = datetime.date.today().isoformat()

    # ── social_signals ──
    try:
        soc = analyze_social(web)
        new_path = d / "signals.md"
        new_path.write_text(render_signals_md(soc))
        soc_json_path = d / "signals.json"
        if soc_json_path.exists():
            try:
                old_soc = json.loads(soc_json_path.read_text())
                old_tech = set(old_soc.get("tech", []))
                new_tech = set(soc.get("tech", []))
                if old_tech != new_tech:
                    changes.append(f"  tech: +{list(new_tech - old_tech) or '—'}  -{list(old_tech - new_tech) or '—'}")
            except Exception:
                pass
        soc_json_path.write_text(json.dumps(soc, indent=2) + "\n")
    except Exception as e:
        changes.append(f"  social_signals failed: {e}")

    # ── modernization_signals ──
    mod_old_path = d / "mod_signals.json"
    mod_result = scan_mod(slug)
    if mod_result:
        mod_changes = _diff_signals(mod_old_path, mod_result)
        changes.extend("  " + m for m in mod_changes)

    # ── website re-ingest (heavy — opt out for speed) ──
    if not skip_website:
        try:
            print(f"  · re-ingesting website…")
            ingest_website(web, slug=slug)
            changes.append("  website re-ingest: org.json updated")
        except Exception as e:
            changes.append(f"  website re-ingest failed: {e}")

    # ── Write refresh-log ──
    log_path = d / "refresh-log.md"
    log_lines = []
    if log_path.exists():
        log_lines = log_path.read_text().splitlines()
    log_lines.insert(0, "")
    log_lines.insert(0, "")
    for c in changes:
        log_lines.insert(0, c)
    log_lines.insert(0, f"## Refresh · {today}")
    if not log_lines[-1].startswith("# "):
        log_lines.insert(0, f"# Refresh log\n")
    log_path.write_text("\n".join(log_lines))

    return {"slug": slug, "changes": changes}


def main():
    ap = argparse.ArgumentParser(description="Refresh org intel from public sources")
    ap.add_argument("--org", help="single org slug")
    ap.add_argument("--all", action="store_true", help="refresh every org with a usable web URL")
    ap.add_argument("--industry", help="only refresh orgs in this industry (e.g. Insurance, Banking, Government)")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--skip-website", action="store_true", help="skip the full website re-ingest (faster — only signals)")
    args = ap.parse_args()

    if args.org:
        result = refresh_org(args.org, skip_website=args.skip_website)
        print(json.dumps(result, indent=2))
        return

    if args.all or args.industry:
        targets = []
        for d in sorted(ORGS_ROOT.iterdir()):
            if not d.is_dir(): continue
            org_path = d / "org.json"
            if not org_path.exists(): continue
            org = json.loads(org_path.read_text())
            if args.industry and org.get("industry") != args.industry:
                continue
            web = org.get("web")
            if not web or web.startswith("(") or web in ("(unknown)", "(no website found)"):
                continue
            targets.append(d.name)
            if len(targets) >= args.limit: break

        print(f"▸ refreshing {len(targets)} orgs"
              + (f" in industry={args.industry}" if args.industry else "")
              + (" (signals only, skipping website re-ingest)" if args.skip_website else "")
              + "…\n")

        for slug in targets:
            r = refresh_org(slug, skip_website=args.skip_website)
            if r.get("skipped"):
                print(f"  ⚠ {slug}: {r['skipped']}")
        print(f"\n✓ refresh complete · {len(targets)} orgs")
        return

    ap.error("must specify --org, --all, or --industry")


if __name__ == "__main__":
    main()
