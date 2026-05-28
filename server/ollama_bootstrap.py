"""Ollama install + model-pull bootstrap.

Every BullpenLM operator's machine needs:
  1. The `ollama` binary on PATH (or running as a service on :11434)
  2. The required models pulled locally — `nomic-embed-text` for RAG
     embeddings and `gemma2:9b` (or a compatible Gemma) for chat.

We don't bundle Ollama itself: it's ~200MB, installs differently per
OS, and the user may already have it. The product flow is:

  Tauri setup hook → checks status() → if ollama_missing or models_missing,
  shows the first-run wizard panel which renders the install instructions
  per platform AND a 'Pull required models' button that POSTs to start a
  background pull, then polls /api/ollama/status until ready.

Why server-side (not client-side) pulls
========================================
The pull command streams JSON progress over stdout (~MB/s). Running it
from JS would need EventSource-over-cmd, which is uglier than just
spawning the subprocess in a thread and exposing a polled progress
endpoint. The server already runs on the operator's machine, so it has
the right environment to invoke `ollama` directly.

Status shape
============
  {
    "ollama_installed": true | false,
    "ollama_running":   true | false,
    "ollama_version":   "0.x.y" | null,
    "install_hint":     "brew install ollama" | "winget install ..." | "...",
    "required_models":  ["nomic-embed-text", "gemma2:9b"],
    "installed_models": [{"name": "...", "size_bytes": ..., "modified_at": "..."}],
    "missing_models":   ["gemma2:9b"],
    "ready":            true if installed + running + all models present,
    "pull_jobs":        {model: {"status": "queued|running|done|error",
                                  "percent": int, "message": str,
                                  "started_at": iso, "ended_at": iso}}
  }
"""
from __future__ import annotations
import datetime
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from typing import Optional


REQUIRED_MODELS: tuple[str, ...] = ("nomic-embed-text", "gemma2:9b")

OLLAMA_API = "http://localhost:11434"
_TIMEOUT = 4


# ── Install hints per platform ────────────────────────────────────────────

def _platform_install_hint() -> str:
    if sys.platform == "darwin":
        return (
            "Install via Homebrew (recommended):\n"
            "  brew install ollama\n"
            "Or download from https://ollama.com/download\n"
            "After installing, run:  ollama serve"
        )
    if sys.platform == "win32":
        return (
            "Install via winget:\n"
            "  winget install Ollama.Ollama\n"
            "Or download from https://ollama.com/download/windows\n"
            "Ollama runs as a service automatically once installed."
        )
    return (
        "Install via the official script:\n"
        "  curl -fsSL https://ollama.com/install.sh | sh\n"
        "Then run:  ollama serve"
    )


# ── Probes ────────────────────────────────────────────────────────────────

def _which_ollama() -> Optional[str]:
    return shutil.which("ollama")


def _ollama_version() -> Optional[str]:
    """Return Ollama version string if `ollama --version` succeeds."""
    bin_path = _which_ollama()
    if not bin_path:
        return None
    try:
        out = subprocess.check_output(
            [bin_path, "--version"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=_TIMEOUT,
        ).strip()
        return out or "unknown"
    except Exception:
        return None


def _api_get(path: str) -> Optional[dict]:
    """Hit the Ollama HTTP API on localhost:11434. None on any error."""
    try:
        req = urllib.request.Request(OLLAMA_API + path)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            if r.status != 200:
                return None
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _list_installed_models() -> list[dict]:
    """Return [{name, size_bytes, modified_at}] for everything `ollama list`
    knows about. Goes through the HTTP API so we don't need to parse text
    output."""
    data = _api_get("/api/tags") or {}
    out = []
    for m in (data.get("models") or []):
        out.append({
            "name": m.get("name", ""),
            "size_bytes": m.get("size", 0),
            "modified_at": m.get("modified_at", ""),
        })
    return out


def _normalize_model(name: str) -> str:
    """`nomic-embed-text` vs `nomic-embed-text:latest` — Ollama treats them
    interchangeably but `/api/tags` reports the :latest form. Normalize so
    the missing-models check doesn't false-positive."""
    return name.split(":", 1)[0]


def _have_model(installed: list[dict], required: str) -> bool:
    req_base = _normalize_model(required)
    req_tag = required.split(":", 1)[1] if ":" in required else "latest"
    for m in installed:
        name = m.get("name", "")
        base = _normalize_model(name)
        tag = name.split(":", 1)[1] if ":" in name else "latest"
        if base == req_base and tag == req_tag:
            return True
        # Allow :latest to satisfy any tag the operator pulled if no tag
        # was specified
        if base == req_base and req_tag == "latest":
            return True
    return False


# ── Pull jobs (background) ────────────────────────────────────────────────
#
# In-memory job state. Lost on restart — fine, since a finished pull
# leaves the model on disk which the next status() poll discovers.

_PULL_JOBS: dict[str, dict] = {}
_PULL_LOCK = threading.Lock()


def _set_job(model: str, **fields) -> dict:
    with _PULL_LOCK:
        job = _PULL_JOBS.setdefault(model, {
            "model": model,
            "status": "queued",
            "percent": 0,
            "message": "",
            "started_at": None,
            "ended_at": None,
        })
        job.update(fields)
        return dict(job)


def get_pull_jobs() -> dict:
    with _PULL_LOCK:
        return {k: dict(v) for k, v in _PULL_JOBS.items()}


def _pull_worker(model: str) -> None:
    """Stream `ollama pull <model>` and update _PULL_JOBS as progress lines
    arrive. The HTTP /api/pull endpoint streams ND-JSON with status +
    completed/total bytes per layer; we parse that to derive a single
    percent number."""
    _set_job(model, status="running", started_at=datetime.datetime.now().isoformat(timespec="seconds"))
    try:
        req = urllib.request.Request(
            OLLAMA_API + "/api/pull",
            data=json.dumps({"name": model, "stream": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=None) as r:
            current_layer_total = 0
            current_layer_completed = 0
            for raw_line in r:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                status = evt.get("status") or ""
                total = evt.get("total")
                completed = evt.get("completed")
                if total and completed is not None:
                    current_layer_total = total
                    current_layer_completed = completed
                pct = int(100 * current_layer_completed / current_layer_total) \
                       if current_layer_total else 0
                _set_job(model, percent=max(0, min(100, pct)), message=status[:120])
                if status == "success":
                    _set_job(model, status="done", percent=100,
                              ended_at=datetime.datetime.now().isoformat(timespec="seconds"),
                              message="ready")
                    return
        _set_job(model, status="done", percent=100,
                  ended_at=datetime.datetime.now().isoformat(timespec="seconds"),
                  message="ready (stream closed)")
    except Exception as e:
        _set_job(model, status="error",
                  ended_at=datetime.datetime.now().isoformat(timespec="seconds"),
                  message=f"{type(e).__name__}: {e}")


def start_pull(model: str) -> dict:
    """Kick off a background pull. Idempotent — returns the existing job
    if one is already running."""
    with _PULL_LOCK:
        existing = _PULL_JOBS.get(model)
        if existing and existing.get("status") in ("queued", "running"):
            return dict(existing)
    if not _which_ollama() or not _api_get("/api/tags"):
        return _set_job(model, status="error",
                          message="ollama not installed or not running",
                          ended_at=datetime.datetime.now().isoformat(timespec="seconds"))
    _set_job(model, status="queued", percent=0, message="queued",
              started_at=None, ended_at=None)
    t = threading.Thread(target=_pull_worker, args=(model,), daemon=True,
                          name=f"ollama-pull-{model}")
    t.start()
    return _set_job(model, status="running")


# ── Top-level status ──────────────────────────────────────────────────────

def status() -> dict:
    installed_bin = _which_ollama() is not None
    api_ok = _api_get("/api/version") is not None
    version = _ollama_version() if installed_bin else None
    installed_models = _list_installed_models() if api_ok else []
    missing = [m for m in REQUIRED_MODELS
                if not _have_model(installed_models, m)]
    return {
        "ollama_installed": installed_bin,
        "ollama_running":   api_ok,
        "ollama_version":   version,
        "install_hint":     _platform_install_hint() if not installed_bin else None,
        "required_models":  list(REQUIRED_MODELS),
        "installed_models": installed_models,
        "missing_models":   missing,
        "ready":            installed_bin and api_ok and not missing,
        "pull_jobs":        get_pull_jobs(),
    }
