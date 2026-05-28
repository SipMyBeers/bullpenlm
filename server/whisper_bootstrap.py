"""Whisper model first-run downloader.

The whisper-cli binary ships inside the .app (250-700 KB depending on
platform). The MODEL is ~250 MB (small.en) or ~140 MB (base.en) — too
big to bundle without doubling the .app size. We download on demand
from the official ggml-org HuggingFace mirror.

Storage
=======
  DATA_DIR/whisper-models/ggml-<name>.bin

Selection
=========
small.en is the recommended default — 4x more accurate than base.en
for English call transcription, still real-time on M-series. Operators
on tighter disk budgets can pick base.en.

The server.py whisper config already searches the right paths via
_WHISPER_DIR_CANDIDATES — DATA_DIR/server/models AND ASSETS_DIR/server/models.
We write the downloaded file to DATA_DIR/server/models/ggml-<name>.bin
so the existing lookup picks it up without any further wiring.

Status shape
============
  {
    "models_dir":       "/Users/.../bullpenlm/server/models",
    "preferred_model":  "small.en",
    "available": [
      {"name": "small.en", "url": "...", "size_mb": 250,
       "installed": true, "path": "...", "active": true}
    ],
    "ready":            true if any model installed,
    "download_jobs":    {model_name: {status, percent, bytes_done,
                                       total_bytes, started_at, ended_at}}
  }
"""
from __future__ import annotations
import datetime
import os
import shutil
import threading
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from paths import DATA_DIR as REPO


MODELS_DIR = REPO / "server" / "models"

# Whisper.cpp official ggml model index. URLs are stable per the project's
# release docs (https://huggingface.co/ggerganov/whisper.cpp/tree/main).
MODELS = {
    "small.en": {
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin",
        "size_mb": 244,
        "filename": "ggml-small.en.bin",
        "blurb": "4× more accurate than base.en, still real-time on Apple Silicon",
    },
    "base.en": {
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin",
        "size_mb": 142,
        "filename": "ggml-base.en.bin",
        "blurb": "Smaller, faster on older hardware",
    },
}

PREFERRED = "small.en"


# ── Download jobs ─────────────────────────────────────────────────────────

_DL_JOBS: dict[str, dict] = {}
_DL_LOCK = threading.Lock()


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _set_job(name: str, **fields) -> dict:
    with _DL_LOCK:
        job = _DL_JOBS.setdefault(name, {
            "model": name,
            "status": "queued",
            "percent": 0,
            "bytes_done": 0,
            "total_bytes": 0,
            "started_at": None,
            "ended_at": None,
            "message": "",
        })
        job.update(fields)
        return dict(job)


def _model_path(name: str) -> Path:
    return MODELS_DIR / MODELS[name]["filename"]


def _downloader(name: str) -> None:
    spec = MODELS[name]
    path = _model_path(name)
    tmp_path = path.with_suffix(path.suffix + ".partial")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    _set_job(name, status="running", started_at=_now())
    try:
        req = urllib.request.Request(spec["url"], headers={
            "User-Agent": "BullpenLM-WhisperBootstrap/1.0",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            total = int(r.headers.get("Content-Length") or 0)
            _set_job(name, total_bytes=total)
            done = 0
            chunk_size = 1024 * 256
            with tmp_path.open("wb") as f:
                while True:
                    chunk = r.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    pct = int(100 * done / total) if total else 0
                    _set_job(name, bytes_done=done, percent=max(0, min(100, pct)),
                              message=f"{done // (1024*1024)} / {total // (1024*1024) if total else '?'} MB")
        # Atomic rename so the model is either fully present or absent
        tmp_path.replace(path)
        _set_job(name, status="done", percent=100, ended_at=_now(),
                  message=f"ready ({path.stat().st_size // (1024*1024)} MB)")
    except Exception as e:
        try: tmp_path.unlink()
        except Exception: pass
        _set_job(name, status="error", ended_at=_now(),
                  message=f"{type(e).__name__}: {e}")


def start_download(name: str) -> dict:
    if name not in MODELS:
        return _set_job(name, status="error", message=f"unknown model: {name}",
                          ended_at=_now())
    with _DL_LOCK:
        existing = _DL_JOBS.get(name)
        if existing and existing.get("status") in ("queued", "running"):
            return dict(existing)
    if _model_path(name).exists():
        # Idempotent: present means done
        return _set_job(name, status="done", percent=100,
                          message="already installed", ended_at=_now())
    _set_job(name, status="queued", percent=0, bytes_done=0,
              started_at=None, ended_at=None, message="queued")
    t = threading.Thread(target=_downloader, args=(name,), daemon=True,
                          name=f"whisper-dl-{name}")
    t.start()
    return _set_job(name, status="running")


def get_jobs() -> dict:
    with _DL_LOCK:
        return {k: dict(v) for k, v in _DL_JOBS.items()}


# ── Top-level status ──────────────────────────────────────────────────────

def status() -> dict:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    out_available = []
    any_installed = False
    for name, spec in MODELS.items():
        path = _model_path(name)
        installed = path.exists()
        if installed:
            any_installed = True
        out_available.append({
            "name": name,
            "url": spec["url"],
            "size_mb": spec["size_mb"],
            "blurb": spec["blurb"],
            "installed": installed,
            "path": str(path) if installed else None,
            "active": installed and name == PREFERRED,
        })
    return {
        "models_dir": str(MODELS_DIR),
        "preferred_model": PREFERRED,
        "available": out_available,
        "ready": any_installed,
        "download_jobs": get_jobs(),
    }
