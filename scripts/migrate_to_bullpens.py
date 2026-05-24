#!/usr/bin/env python3
"""Migrate the existing single-bullpen data layout into the multi-tenant
v2 shape at bullpens/<slug>/. Idempotent — safe to re-run.

What it does:
  1. Creates `bullpens/killsesh/` with the standard subdirectories.
  2. Moves existing claims, invites, activity log from `team/` into the
     bullpen folder; rewrites activity.jsonl → audit.jsonl as a properly
     hash-chained log (the existing log isn't chained yet).
  3. Copies all sales/*.md docs into `bullpens/killsesh/legal/`.
  4. Writes a member record for every rep ever seen on this host.
  5. Symlinks `bullpens/killsesh/orgs` → `../../organizations/` so the
     shared prospect graph is reachable via the bullpen-scoped path.
  6. Backfills `bullpen: "killsesh"` into existing training-runs metrics.
  7. Leaves the original `team/` and `organizations/` in place — nothing
     is deleted. Verify the migration, then optionally clean up later.

Usage:
  python3 scripts/migrate_to_bullpens.py            # dry-run, no writes
  python3 scripts/migrate_to_bullpens.py --apply    # actually do it
  python3 scripts/migrate_to_bullpens.py --slug killsesh --founder beers
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "server"))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="Actually perform the migration (default is dry-run)")
    ap.add_argument("--slug", default="killsesh",
                    help="Bullpen slug to migrate into (default: killsesh)")
    ap.add_argument("--founder", default="beers",
                    help="Founder rep name (default: beers)")
    ap.add_argument("--product", default="KillSesh",
                    help="Product this bullpen sells (default: KillSesh)")
    args = ap.parse_args()

    dry = not args.apply
    if dry:
        print("=== DRY RUN — pass --apply to actually migrate ===\n")
    print(f"Target bullpen: {args.slug}  founder: {args.founder}  product: {args.product}\n")

    from bullpens import (create_bullpen, exists, write_member,
                          _bullpen_dir as bullpen_dir)
    from audit import append as audit_append

    bp_dir = bullpen_dir(args.slug)

    # ── Step 1: create the bullpen if missing ──
    if exists(args.slug):
        print(f"✓ Bullpen '{args.slug}' already exists — skipping create")
        manifest_path = bp_dir / "bullpen.json"
    else:
        if dry:
            print(f"WOULD create bullpen '{args.slug}' → {bp_dir}/")
        else:
            m = create_bullpen(args.slug, args.founder, args.product)
            print(f"✓ Created bullpen '{m['slug']}'")

    # ── Step 2: migrate claims ──
    old_claims = REPO / "team" / "claims"
    new_claims = bp_dir / "claims"
    if old_claims.exists():
        moved = 0
        for f in old_claims.glob("*.json"):
            dest = new_claims / f.name
            if dest.exists():
                continue
            if dry:
                print(f"  WOULD move claim: {f.name}")
            else:
                shutil.copy2(f, dest)
                moved += 1
        if not dry and moved:
            print(f"✓ Copied {moved} claim(s) into bullpens/{args.slug}/claims/")

    # ── Step 3: migrate invites ──
    old_inv = REPO / "team" / "invites"
    new_inv = bp_dir / "invites"
    if old_inv.exists():
        for f in old_inv.glob("*.json"):
            dest = new_inv / f.name
            if dest.exists():
                continue
            if dry:
                print(f"  WOULD copy invite: {f.name}")
            else:
                shutil.copy2(f, dest)
        used = old_inv / "used"
        if used.exists():
            for f in used.glob("*.json"):
                dest = new_inv / "used" / f.name
                if dest.exists():
                    continue
                if not dry:
                    shutil.copy2(f, dest)

    # ── Step 4: migrate activity.jsonl → audit.jsonl with hash chain ──
    old_activity = REPO / "team" / "activity.jsonl"
    new_audit = bp_dir / "audit.jsonl"
    if old_activity.exists() and not new_audit.exists():
        # Only do the conversion if there's no existing audit log
        # (otherwise we'd double-import on re-run)
        if not dry:
            from audit import _genesis_hash, _canonical
            import hashlib
            prev = _genesis_hash(args.slug)
            count = 0
            with new_audit.open("w") as out:
                for line in old_activity.read_text().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        old = json.loads(line)
                    except Exception:
                        continue
                    entry = {
                        "id": old.get("ts", "") + f"-mig{count:04d}",
                        "ts": old.get("ts", ""),
                        "bullpen": args.slug,
                        "actor": old.get("rep", "?"),
                        "kind": old.get("kind", "legacy"),
                        "target_type": "prospect" if old.get("prospect") else "",
                        "target_id": old.get("prospect", ""),
                        "payload": {k: v for k, v in old.items()
                                    if k not in ("ts", "rep", "kind", "prospect")},
                        "prev_hash": prev,
                    }
                    entry["hash"] = hashlib.sha256(_canonical(entry)).hexdigest()
                    out.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    prev = entry["hash"]
                    count += 1
            print(f"✓ Converted {count} legacy events into hash-chained audit.jsonl")
        else:
            line_count = sum(1 for _ in old_activity.read_text().splitlines() if _.strip())
            print(f"  WOULD convert {line_count} legacy events into audit.jsonl")
    elif new_audit.exists():
        print(f"✓ audit.jsonl already exists ({new_audit.stat().st_size} bytes) — skipping conversion")

    # ── Step 5: seed legal docs from sales/ (if not already there) ──
    legal_dir = bp_dir / "legal"
    sales_dir = REPO / "sales"
    if sales_dir.exists():
        for md in sales_dir.glob("*.md"):
            dest = legal_dir / md.name
            if dest.exists():
                continue
            if dry:
                print(f"  WOULD copy legal doc: {md.name}")
            else:
                shutil.copy2(md, dest)

    # ── Step 6: write member records for every rep ever seen ──
    reps = {args.founder}
    tr = REPO / "training-runs"
    if tr.exists():
        for mf in tr.glob("*.metrics.json"):
            try:
                reps.add(json.loads(mf.read_text()).get("rep") or "self")
            except Exception:
                pass
    orgs = REPO / "organizations"
    if orgs.exists():
        for md in orgs.glob("*/calls/*/metadata.json"):
            try:
                reps.add(json.loads(md.read_text()).get("rep") or "self")
            except Exception:
                pass
    reps.discard("")
    if dry:
        print(f"  WOULD write member records for: {sorted(reps)}")
    else:
        for rep in sorted(reps):
            role = "founder" if rep == args.founder else "rep"
            write_member(args.slug, rep, role=role)
        print(f"✓ Wrote {len(reps)} member record(s)")

    # ── Step 7: symlink orgs ──
    org_link = bp_dir / "orgs"
    if not org_link.exists():
        if dry:
            print(f"  WOULD symlink {org_link} → ../../organizations")
        else:
            try:
                org_link.symlink_to("../../organizations")
                print(f"✓ Symlinked bullpens/{args.slug}/orgs → organizations/")
            except OSError as e:
                print(f"  ⚠ symlink failed ({e}) — orgs will load via repo path fallback")

    # ── Step 8: backfill `bullpen` field into existing training-runs ──
    if tr.exists():
        touched = 0
        for mf in tr.glob("*.metrics.json"):
            try:
                d = json.loads(mf.read_text())
            except Exception:
                continue
            if "bullpen" in d:
                continue
            if dry:
                touched += 1
                continue
            d["bullpen"] = args.slug
            mf.write_text(json.dumps(d, indent=2) + "\n")
            touched += 1
        if dry:
            print(f"  WOULD backfill bullpen='{args.slug}' on {touched} metrics record(s)")
        elif touched:
            print(f"✓ Backfilled bullpen='{args.slug}' on {touched} metrics record(s)")

    # ── Step 9: log a migration event so we know when it ran ──
    if not dry:
        audit_append(args.slug, "system", "migration_completed",
                     payload={"from": "team/ + sales/", "to": f"bullpens/{args.slug}/"})

    print()
    if dry:
        print("=== DRY RUN COMPLETE — re-run with --apply to commit ===")
    else:
        print("=== MIGRATION COMPLETE ===")
        print(f"   bullpens/{args.slug}/")
        print(f"   ├── claims/, invites/, members/, legal/, deals/, …")
        print(f"   ├── audit.jsonl (hash-chained)")
        print(f"   └── orgs → ../../organizations (symlink)")
        print()
        print(f"Verify the chain: python3 server/audit.py verify {args.slug}")


if __name__ == "__main__":
    main()
