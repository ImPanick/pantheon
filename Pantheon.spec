# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    # licenses/, LICENSE, NOTICE and CREDITS.md are not optional extras: MIT, BSD
    # and OFL all require the notice to travel with a redistributed copy, and this
    # bundle is one. Without them the desktop build ships other people's code with
    # their attribution stripped.
    datas=[('static', 'static'), ('scripts', 'scripts'), ('mcp_servers', 'mcp_servers'), ('services/hwfit/data', 'services/hwfit/data'), ('config', 'config'), ('.env.example', '.env.example'), ('licenses', 'licenses'), ('LICENSE', '.'), ('NOTICE', '.'), ('CREDITS.md', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Pantheon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['static\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Pantheon',
)
