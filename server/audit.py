"""Hash-chained append-only audit log — the source of truth for every
mutation that happens inside a bullpen.

Every CRUD action (claim, release, deal-stage-move, signature, etc.) calls
`audit.append(bullpen_slug, actor_rep, kind, target_type, target_id, payload)`.
The log lives at `bullpens/<slug>/audit.jsonl`. Each entry includes the
SHA-256 hash of the prior entry, forming a chain — if anyone hand-edits a
line, every subsequent line's hash check fails and the UI flags it.

Read APIs:
  * `tail(bullpen, n=200)` → newest N events
  * `iter_all(bullpen)`    → generator over every event in chronological order
  * `verify(bullpen)`      → walks the whole chain, returns (ok, broken_at_index)

Write API:
  * `append(bullpen, actor_rep, kind, target_type, target_id, payload=None)`
    Returns the written entry (with `id`, `ts`, `prev_hash`, `hash`).

Design notes:
  * Single-writer assumed (host server). No file locks. If you fork the writer,
    add `fcntl.flock` here.
  * Hash chain is over the JSON-canonical serialization of the entry without
    its own `hash` field — that's standard Merkle-style.
  * Genesis hash is the SHA-256 of the bullpen slug — deterministic per tenant.
"""
from __future__ import annotations
import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Iterator, Optional

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


def _bullpen_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen
    d.mkdir(parents=True, exist_ok=True)
    return d


def _audit_path(bullpen: str) -> Path:
    return _bullpen_dir(bullpen) / "audit.jsonl"


def _genesis_hash(bullpen: str) -> str:
    """Per-tenant genesis hash so cross-bullpen log lines can't be replayed."""
    return hashlib.sha256(f"bullpen:{bullpen}:genesis".encode()).hexdigest()


def _canonical(entry: dict) -> bytes:
    """Stable JSON serialization for hashing — sort keys, no whitespace, UTF-8.
    `hash` is stripped before hashing (it's the output of hashing the rest)."""
    clean = {k: v for k, v in entry.items() if k != "hash"}
    return json.dumps(clean, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _last_hash(bullpen: str) -> str:
    """Return the hash of the last entry in the log, or the genesis hash if empty."""
    p = _audit_path(bullpen)
    if not p.exists() or p.stat().st_size == 0:
        return _genesis_hash(bullpen)
    # Tail the file — read backwards to find the last non-empty line
    with p.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        if size == 0:
            return _genesis_hash(bullpen)
        # Read last 4KB (more than enough for a single line) and find newline
        read_back = min(size, 4096)
        f.seek(size - read_back)
        chunk = f.read(read_back)
        last_line = chunk.rstrip(b"\n").splitlines()[-1] if chunk else b""
    try:
        return json.loads(last_line).get("hash") or _genesis_hash(bullpen)
    except Exception:
        return _genesis_hash(bullpen)


def append(bullpen: str, actor_rep: Optional[str] = None, kind: Optional[str] = None,
           target_type: str = "", target_id: str = "",
           payload: Optional[dict] = None, *,
           actor: Optional[str] = None) -> dict:
    """Append an event to the bullpen's audit log. Returns the written entry.

    Both `actor_rep` (legacy positional) and `actor` (keyword) are
    accepted to allow the Phase 0.5 modules' `audit_append(bullpen,
    kind=..., actor=..., payload=...)` style alongside the older
    `audit_append(bullpen, rep, kind, ...)` style.
    """
    resolved_actor = actor_rep if actor_rep is not None else actor
    if resolved_actor is None or kind is None:
        raise TypeError("append requires bullpen + actor (or actor_rep) + kind")
    prev_hash = _last_hash(bullpen)
    entry = {
        "id": f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}",
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "bullpen": bullpen,
        "actor": resolved_actor,
        "kind": kind,
        "target_type": target_type,
        "target_id": target_id,
        "payload": payload or {},
        "prev_hash": prev_hash,
    }
    entry["hash"] = hashlib.sha256(_canonical(entry)).hexdigest()
    with _audit_path(bullpen).open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Fan out to live SSE subscribers so every connected client sees this
    # event in real-time. Import inline to avoid a circular dependency at
    # module load (events.py is allowed to depend on audit, not vice versa).
    try:
        from events import publish as _events_publish
        _events_publish(bullpen, entry)
    except Exception:
        pass

    # Cadence auto-start: when a deal moves into a stage that has a
    # cadence template, fire it. Idempotent on (deal_id, template).
    # Self-recursion guard: cadence_started events themselves don't
    # re-enter this hook (entry["kind"] != "deal_stage_moved").
    if kind == "deal_stage_moved":
        try:
            from cadence import handle_audit_event as _cad_hook
            _cad_hook(bullpen, entry)
        except Exception:
            pass

    # Discord webhook fan-out (no-op if not configured for the bullpen)
    try:
        from discord import notify as _discord_notify
        _discord_notify(bullpen, entry)
    except Exception:
        pass

    # Mobile push fan-out (APNs) — notifies operators tracking this bullpen
    # from the iOS app. No-op if no devices registered or no APNs key set.
    try:
        from push import on_audit_event as _push_hook
        _push_hook(bullpen, entry)
    except Exception:
        pass

    return entry


def iter_all(bullpen: str) -> Iterator[dict]:
    """Generator over every audit entry in chronological order."""
    p = _audit_path(bullpen)
    if not p.exists():
        return
    with p.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def tail(bullpen: str, n: int = 200) -> list[dict]:
    """Return the most recent N entries (newest first)."""
    if n <= 0:
        return []
    p = _audit_path(bullpen)
    if not p.exists():
        return []
    # Read whole file — for 200K+ event logs we'd need a more efficient tail
    lines = p.read_text().splitlines()
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    out.reverse()
    return out


def verify(bullpen: str) -> tuple[bool, Optional[int]]:
    """Walk the whole chain and verify every entry's hash + prev_hash.
    Returns (True, None) if intact, (False, <index>) at the first break."""
    expected_prev = _genesis_hash(bullpen)
    for i, entry in enumerate(iter_all(bullpen)):
        # Check chain linkage
        if entry.get("prev_hash") != expected_prev:
            return (False, i)
        # Check this entry's hash matches its content
        computed = hashlib.sha256(_canonical(entry)).hexdigest()
        if entry.get("hash") != computed:
            return (False, i)
        expected_prev = entry["hash"]
    return (True, None)


# ── CLI for the host to inspect/verify the chain ──

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage:")
        print("  python3 server/audit.py verify <bullpen>")
        print("  python3 server/audit.py tail <bullpen> [n]")
        print("  python3 server/audit.py append <bullpen> <actor> <kind>  # for testing")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "verify":
        bullpen = sys.argv[2]
        ok, idx = verify(bullpen)
        if ok:
            print(f"✓ Chain verified for bullpen '{bullpen}'")
        else:
            print(f"✗ Chain broken at index {idx} in '{bullpen}'")
            sys.exit(1)
    elif cmd == "tail":
        bullpen = sys.argv[2]
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        for e in tail(bullpen, n=n):
            print(f"  {e['ts']}  {e['actor']:12}  {e['kind']:14}  {e.get('target_type','')}/{e.get('target_id','')}")
    elif cmd == "append":
        bullpen, actor, kind = sys.argv[2], sys.argv[3], sys.argv[4]
        e = append(bullpen, actor, kind)
        print(f"✓ {e['id']}  hash={e['hash'][:16]}…")
    else:
        print(f"× unknown command: {cmd}"); sys.exit(1)
