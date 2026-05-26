# PyInstaller spec for the BullpenLM Python server.
#
# Produces a single executable that bundles:
#   - Python 3.11 interpreter
#   - server/ (the whole Python module tree)
#   - All pure-Python deps (pyyaml, certifi)
#
# Builds:
#   cd desktop/src-tauri/binaries
#   pyinstaller bullpenlm-server.spec
#
# Output: ./dist/bullpenlm-server-<platform>/bullpenlm-server[.exe]
#
# Tauri's `externalBin` field in tauri.conf.json picks up the binary at
# bundle time. The Rust sidecar code in src/lib.rs spawns it with the
# repo path as CWD instead of shelling out to system `python3`.
#
# Native deps NOT bundled (must exist on the user's machine):
#   - whisper-cli (whisper.cpp binary) — installed by install_macmini.sh
#                                         or brew install whisper-cpp
#   - ffmpeg — same
#   - cloudflared — same
#   - ollama — same (large LLM weights, separate install)
#
# Bundling those native binaries pushes the install over 1GB which we
# don't want for the Steam build. Better path: Phase 1 installer wraps
# `brew install` of these once, then the Tauri app uses them.

# vi: ft=python

block_cipher = None

a = Analysis(
    ['../../../server/server.py'],
    pathex=[
        '../../../server',
        '../../../personas',
    ],
    binaries=[],
    datas=[
        # Ship the templates, sales markdown, and personas/_sample inside
        # the binary so a fresh install can wizard immediately.
        ('../../../templates', 'templates'),
        ('../../../sales', 'sales'),
        ('../../../personas/_sample', 'personas/_sample'),
    ],
    hiddenimports=[
        # PyInstaller can't always discover dynamically-imported modules.
        # These come up via import_module/__import__ in the server code.
        'audit', 'bullpens', 'invites', 'invoices', 'tunnel', 'discord',
        'discord_roles', 'email_send', 'email_templates', 'docs',
        'stripe_client', 'calls', 'bumblebee', 'events', 'presence',
        'classes', 'achievements', 'quests', 'parties', 'reactions',
        'trophies', 'streaks', 'pvp', 'legal', 'commissions', 'contacts',
        'activity', 'followups', 'today', 'duos', 'buyer_cards', 'tcs',
        'spotcheck', 'onboarding', 'applications', 'briefing',
        'wallboard', 'outbox', 'pipeline', 'deals', 'debrief',
        'team', 'orgs', 'xp',
        'yaml', 'certifi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='bullpenlm-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,         # compress the binary; ~30% smaller, no runtime cost
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,     # keep stdout/stderr — Tauri tails it for the ready signal
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='bullpenlm-server',
)
