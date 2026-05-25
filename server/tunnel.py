"""Cloudflare Quick Tunnel — expose the founder's localhost:7878 to the internet.

This is the bridge that lets closers connect to a founder's bullpen across
the internet without anyone running anything in the cloud. Uses Cloudflare's
free Quick Tunnels (trycloudflare.com) — no Cloudflare account required,
zero cost on the founder's side.

  start_tunnel(port=7878)  → spawns cloudflared, returns public URL
  stop_tunnel()            → kills the running tunnel
  tunnel_status()          → returns {running, url, pid, started_at}

State is persisted at ~/.bullpenlm/tunnel.json so subsequent calls within
the same process (or across server restarts) can find the tunnel again.

CLI for sanity-checking from the terminal:
  python3 server/tunnel.py start
  python3 server/tunnel.py status
  python3 server/tunnel.py stop
"""
from __future__ import annotations
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

STATE_PATH = Path.home() / ".bullpenlm" / "tunnel.json"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
START_TIMEOUT = 25  # seconds for cloudflared to emit the URL


def _cloudflared_bin() -> Optional[str]:
    return shutil.which("cloudflared")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _read_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _write_state(d: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(d, indent=2) + "\n")


def tunnel_status() -> dict:
    """Return {running, url, pid, started_at}. Verifies pid is still alive."""
    state = _read_state()
    pid = state.get("pid")
    url = state.get("url")
    if pid and _pid_alive(pid):
        return {"running": True, "url": url, "pid": pid,
                "started_at": state.get("started_at")}
    # Stale state — process is gone
    if state:
        state["pid"] = None
        state["running"] = False
        _write_state(state)
    return {"running": False, "url": None, "pid": None, "started_at": None}


def stop_tunnel() -> dict:
    state = _read_state()
    pid = state.get("pid")
    if pid and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                time.sleep(0.2)
                if not _pid_alive(pid):
                    break
            if _pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
        except Exception as e:
            return {"ok": False, "error": str(e)}
    _write_state({"running": False, "pid": None, "url": None,
                  "stopped_at": datetime.datetime.now().isoformat(timespec="seconds")})
    return {"ok": True}


def start_tunnel(port: int = 7878) -> dict:
    """Spawn a cloudflared Quick Tunnel pointing at localhost:<port>.

    Returns {ok, url, pid} on success or {ok: False, error: str}.

    Idempotent: if a tunnel is already running and alive, returns it.
    """
    existing = tunnel_status()
    if existing["running"] and existing["url"]:
        return {"ok": True, "url": existing["url"], "pid": existing["pid"],
                "already_running": True}

    bin_path = _cloudflared_bin()
    if not bin_path:
        return {"ok": False, "error": "cloudflared_not_installed",
                "hint": "Install: brew install cloudflared"}

    # cloudflared --no-autoupdate keeps the binary stable in dev; --url is the
    # quick-tunnel mode (no account needed). Output goes to STDERR.
    log_path = Path.home() / ".bullpenlm" / "tunnel.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_f = open(log_path, "ab")
    proc = subprocess.Popen(
        [bin_path, "--no-autoupdate", "tunnel", "--url", f"http://127.0.0.1:{port}"],
        stdout=log_f,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    # Tail the log file for the public URL. cloudflared emits a banner line
    # containing the trycloudflare.com URL within ~5-10s.
    deadline = time.monotonic() + START_TIMEOUT
    url = None
    last_size = 0
    while time.monotonic() < deadline:
        # Check the process is still alive
        if proc.poll() is not None:
            try:
                tail = log_path.read_text()[-2000:]
            except Exception:
                tail = ""
            return {"ok": False, "error": "cloudflared_exited",
                    "code": proc.returncode, "log_tail": tail}
        try:
            size = log_path.stat().st_size
        except FileNotFoundError:
            size = 0
        if size > last_size:
            try:
                buf = log_path.read_text()
            except Exception:
                buf = ""
            m = URL_RE.search(buf)
            if m:
                url = m.group(0)
                break
            last_size = size
        time.sleep(0.4)

    if not url:
        # Couldn't detect URL — kill the orphan and bail
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try: proc.terminate()
            except Exception: pass
        return {"ok": False, "error": "tunnel_url_not_emitted",
                "hint": "Check ~/.bullpenlm/tunnel.log"}

    state = {
        "running": True,
        "url": url,
        "pid": proc.pid,
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "port": port,
    }
    _write_state(state)
    return {"ok": True, "url": url, "pid": proc.pid, "already_running": False}


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python3 server/tunnel.py [start|stop|status]")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "start":
        r = start_tunnel()
        if r.get("ok"):
            print(f"✓ Tunnel up: {r['url']}  (pid {r['pid']})")
        else:
            print(f"× {r.get('error')}: {r.get('hint','')}")
            sys.exit(1)
    elif cmd == "stop":
        r = stop_tunnel()
        print("✓ Stopped" if r.get("ok") else f"× {r.get('error')}")
    elif cmd == "status":
        s = tunnel_status()
        if s["running"]:
            print(f"✓ Running: {s['url']}  (pid {s['pid']}, since {s['started_at']})")
        else:
            print("× Not running")
    else:
        print(f"× unknown command: {cmd}"); sys.exit(1)
