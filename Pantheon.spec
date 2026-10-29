# -*- mode: python ; coding: utf-8 -*-
import json
import os
import shutil
import subprocess


def _static_without_comments():
    """`B1666` (`D-2026-10-29-03` §4: "Strip them too"). `static/`, as this
    bundle ships it: Pantheon's own JavaScript without its comments, through
    the same stripper the image's `js-without-comments` stage runs
    (`scripts/strip-js-comments.mjs`, `B1591` — acorn's parser, every token
    kept on its line and column, the licence notices kept, each file proven
    the same token stream or the build stops), and every other file as it is.

    This was `('static', 'static')`, so the desktop build shipped every
    comment the image had stopped serving. The stripper writes into
    `build/js-without-comments/` (an empty directory each time, never over the
    source — the repository keeps its comments, `Law 1`), and each file under
    `static/` is listed from there when it was stripped and from the tree when
    it was not (`static/lib/`, the fonts, the stylesheets). PyInstaller runs
    this file with `SPECPATH` set to its directory, the repository's root.
    """
    root = SPECPATH
    out = os.path.join(root, 'build', 'js-without-comments')
    shutil.rmtree(out, ignore_errors=True)
    node = shutil.which('node')
    if not node or not os.path.isfile(os.path.join(root, 'node_modules', 'acorn', 'package.json')):
        raise SystemExit(
            "Pantheon's desktop bundle ships its JavaScript without comments, and the stripper "
            "that does it (scripts/strip-js-comments.mjs) needs Node.js and acorn. "
            + ("Install Node.js, then " if not node else "")
            + "run `npm ci --omit=dev --ignore-scripts` in " + root + " and build again.")
    proc = subprocess.run([node, os.path.join(root, 'scripts', 'strip-js-comments.mjs'), root, out])
    if proc.returncode != 0:
        raise SystemExit(
            'scripts/strip-js-comments.mjs stopped the build (it says above which file and why), '
            'so the bundle would ship that file half-done. Fix that file and build again.')
    # What it stripped is what its record names (the record the image's deploy
    # check reads); no record is no stripping, whatever the exit status said.
    try:
        with open(os.path.join(out, 'js-without-comments.json'), encoding='utf-8') as f:
            stripped = set(json.load(f)['files'])
    except (OSError, ValueError, KeyError) as e:
        raise SystemExit(
            'scripts/strip-js-comments.mjs finished without writing its record (' + str(e) + '), '
            'so nothing says which modules it stripped. Run it by hand to see why: '
            'node scripts/strip-js-comments.mjs . build/js-without-comments')
    datas = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, 'static')):
        dirnames.sort()
        dest = os.path.relpath(dirpath, root)
        for name in sorted(filenames):
            rel = os.path.join(dest, name).replace(os.sep, '/')
            datas.append((os.path.join(out, rel) if rel in stripped else os.path.join(dirpath, name), dest))
    return datas


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    # licenses/, LICENSE, NOTICE and CREDITS.md are not optional extras: MIT, BSD
    # and OFL all require the notice to travel with a redistributed copy, and this
    # bundle is one. Without them the desktop build ships other people's code with
    # their attribution stripped.
    # `B373`: the Real-ESRGAN wheel script is data too — `src/forge_pins.py`
    # reads the audited pins out of it for the Forge's Install button, which
    # refuses to install unpinned when the file is absent.
    # `B1666`: `static/` is `_static_without_comments()`, above.
    datas=_static_without_comments() + [('scripts', 'scripts'), ('mcp_servers', 'mcp_servers'), ('services/hwfit/data', 'services/hwfit/data'), ('config', 'config'), ('.env.example', '.env.example'), ('licenses', 'licenses'), ('LICENSE', '.'), ('NOTICE', '.'), ('CREDITS.md', '.'), ('docker/build-realesrgan-wheels.sh', 'docker')],
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
