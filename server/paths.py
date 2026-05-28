"""Runtime path resolution — works the same in dev tree and PyInstaller bundle.

The product is shipped two ways:
  1. **Dev**: cloned repo, `python3 server/server.py`. Code, assets, and
     user data all live under the repo. REPO = the cloned tree.
  2. **Bundled**: PyInstaller binary inside a Tauri app. Code + assets
     live read-only inside the bundle's temp `_MEIPASS` dir; user data
     must live somewhere persistent and writable.

We split the world into:
  - ASSETS_DIR  — read-only files shipped with the binary
                  (floor/, templates/, sales/, personas/_sample/)
  - DATA_DIR    — writable user-state directory
                  (bullpens/, organizations/, training-runs/, .secrets/)

On first run in a bundled build we **seed** ASSETS_DIR → DATA_DIR so the
rest of the codebase can keep using one canonical root (DATA_DIR).
After seeding, every existing `REPO = Path(__file__).parent.parent`
becomes `REPO = DATA_DIR` and nothing else changes.

Environment override
====================
Set `BULLPENLM_HOME=/path/to/data` to point DATA_DIR at any directory.
Useful for the install_macmini.sh quickstart, for testing, and for
multi-instance dev where two bullpens want isolated state.

Defaults per platform
=====================
  macOS:    ~/Library/Application Support/BullpenLM
  Windows:  %APPDATA%/BullpenLM
  Linux:    ~/.local/share/bullpenlm
  Dev:      <repo root>
"""
from __future__ import annotations
import os
import shutil
import sys
from pathlib import Path


# ── Detect runtime mode ───────────────────────────────────────────────────

def _is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _platform_data_default() -> Path:
    """OS-specific user-data location."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "BullpenLM"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or str(home)
        return Path(appdata) / "BullpenLM"
    # Linux / other Unix
    xdg = os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return Path(xdg) / "bullpenlm"


def _resolve_roots() -> tuple[Path, Path]:
    if _is_frozen():
        assets = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        data = Path(os.environ.get("BULLPENLM_HOME", str(_platform_data_default())))
    else:
        repo = Path(__file__).resolve().parent.parent
        assets = repo
        data = Path(os.environ.get("BULLPENLM_HOME", str(repo)))
    data.mkdir(parents=True, exist_ok=True)
    return assets, data


ASSETS_DIR, DATA_DIR = _resolve_roots()

# Most modules in the codebase use `REPO = Path(__file__).parent.parent`
# and reach for both code-adjacent assets AND writable state under it. To
# keep the migration small we point them at DATA_DIR, and on first run in
# a bundle we copy assets there so the relative paths still resolve.
REPO = DATA_DIR


# ── First-run asset seeding (bundle → data dir) ───────────────────────────

# Directories we ship inside the bundle and need accessible under DATA_DIR
# so existing `REPO / "templates"` etc keep working. Each entry: (subdir,
# overwrite_on_upgrade). We never overwrite directories that contain user
# data — only ones that are read-only by convention.
_SEED_DIRS: tuple[tuple[str, bool], ...] = (
    ("floor", True),       # static UI — overwrite each version
    ("templates", True),   # legal templates — overwrite each version
    ("sales", True),       # canonical sales markdown — overwrite
    ("personas/_sample", True),
)


def _log(msg: str) -> None:
    """Debug breadcrumb used to diagnose bundled-launch issues.

    Off by default. To enable, set BULLPENLM_BOOTLOG=/path/to/log; lines
    will be appended there. File-based because PyInstaller's bootloader
    buffers stdout/stderr until process exit which made a previous
    silent-hang impossible to diagnose from stdout alone.
    """
    bootlog = os.environ.get("BULLPENLM_BOOTLOG")
    if not bootlog:
        return
    try:
        with open(bootlog, "a") as f:
            f.write(f"[{os.getpid()}] [paths] {msg}\n")
    except Exception:
        pass


def _seed_bundle_assets() -> None:
    """Copy ASSETS_DIR/<sub> → DATA_DIR/<sub> on first run / version bump.

    No-op in dev (ASSETS_DIR == DATA_DIR), so the source tree stays
    canonical. Safe to call every boot; uses dirs_exist_ok so it acts as
    an upgrade-in-place once we wire a version stamp.
    """
    _log(f"frozen={_is_frozen()} assets={ASSETS_DIR} data={DATA_DIR}")
    if not _is_frozen() or ASSETS_DIR == DATA_DIR:
        _log("skip seeding (dev or same-root)")
        return
    for sub, _overwrite in _SEED_DIRS:
        src = ASSETS_DIR / sub
        dst = DATA_DIR / sub
        if not src.exists():
            _log(f"skip {sub} — not bundled at {src}")
            continue
        try:
            _log(f"seed {sub} -> {dst}")
            shutil.copytree(src, dst, dirs_exist_ok=True)
            _log(f"  ok ({sum(1 for _ in dst.rglob('*'))} entries)")
        except Exception as e:
            _log(f"  FAILED: {e!r}")


_seed_bundle_assets()
_log("paths.py loaded; ready")


# ── Diagnostics ───────────────────────────────────────────────────────────

def info() -> dict:
    return {
        "frozen": _is_frozen(),
        "platform": sys.platform,
        "assets_dir": str(ASSETS_DIR),
        "data_dir": str(DATA_DIR),
        "data_writable": os.access(str(DATA_DIR), os.W_OK),
        "env_bullpenlm_home": os.environ.get("BULLPENLM_HOME"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(info(), indent=2))
