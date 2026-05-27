# Tauri Sidecar Binaries

Tauri's `externalBin` in `tauri.conf.json` looks for platform-suffixed
binaries here at build time. The naming convention is:

```
bullpenlm-server-<target-triple>[.exe]
```

| Target triple | Platform |
|---|---|
| `aarch64-apple-darwin` | macOS Apple Silicon |
| `x86_64-apple-darwin` | macOS Intel |
| `x86_64-unknown-linux-gnu` | Linux x64 |
| `x86_64-pc-windows-msvc` | Windows x64 (`.exe` suffix) |

## Building the sidecar locally

```bash
# From the repo root
pip3 install pyinstaller pyyaml certifi

cd desktop/src-tauri/binaries
pyinstaller bullpenlm-server.spec

# PyInstaller drops `dist/bullpenlm-server/bullpenlm-server` (Unix) or
# `dist/bullpenlm-server/bullpenlm-server.exe` (Windows). Rename it to
# the target-triple form Tauri expects:

# macOS Apple Silicon:
mv dist/bullpenlm-server/bullpenlm-server bullpenlm-server-aarch64-apple-darwin

# macOS Intel:
mv dist/bullpenlm-server/bullpenlm-server bullpenlm-server-x86_64-apple-darwin

# Linux:
mv dist/bullpenlm-server/bullpenlm-server bullpenlm-server-x86_64-unknown-linux-gnu

# Windows:
move dist\bullpenlm-server\bullpenlm-server.exe bullpenlm-server-x86_64-pc-windows-msvc.exe
```

## CI

The `.github/workflows/release.yml` job runs `pyinstaller` then
`tauri-action` on tag push, on each platform. The PyInstaller spec
file handles bundling Python + pure-Python deps; native dependencies
(whisper-cli, ffmpeg, cloudflared, ollama) are NOT bundled — operators
install those via `brew` or the equivalent on first launch.

## Why a sidecar instead of bundling Python the normal way

Tauri's `externalBin` produces a binary that Tauri's signing /
notarization pipeline knows how to handle, and `tauri_plugin_shell`
gives us `app.shell().sidecar(...)` which auto-resolves the right
platform-suffixed file at runtime. PyInstaller is the cleanest way to
produce that single binary on each platform.

## Dev fallback

If no sidecar binary is present (Phase 0 dev mode), `src/lib.rs` falls
back to `python3 server/server.py` via system Python. The fallback is
intentional so contributors can `git clone && cargo tauri dev` without
the PyInstaller step.

## Build artifacts to gitignore

These produced files should NOT be committed (`.gitignore`):

```
build/
dist/
*.spec.bak
bullpenlm-server-*    # the renamed binaries — built per-platform in CI
```
