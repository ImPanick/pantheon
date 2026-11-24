# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2158`. `tileManager.isModalMaximized` was exported and called by nothing;
the Workbench's maximize button decided which way to toggle from its own copy
of the same test. The toggle now asks the tile manager it has just loaded, so
the module that snaps the window is the one that says whether it is snapped.

Driven: the tile manager's predicate is called on modal stand-ins. Scoped:
the toggle's own callback is resolved before it is read (`Law 20`)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TILE = ROOT / "static" / "js" / "tileManager.js"
WORKBENCH = ROOT / "static" / "js" / "workbench" / "workbench.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_tile_manager_says_when_a_window_fills_the_screen():
    script = textwrap.dedent(f"""
        globalThis.window = {{ innerWidth: 1200, innerHeight: 800, addEventListener() {{}} }};
        globalThis.document = {{
          readyState: 'loading', body: {{ appendChild() {{}} }},
          documentElement: {{ style: {{ setProperty() {{}}, removeProperty() {{}} }} }},
          addEventListener() {{}}, getElementById() {{ return null; }},
          querySelector() {{ return null; }}, querySelectorAll() {{ return []; }},
          createElement() {{ return {{ style: {{}}, classList: {{ add() {{}}, remove() {{}} }}, remove() {{}} }}; }},
        }};
        globalThis.requestAnimationFrame = (fn) => fn();
        globalThis.MutationObserver = class {{ observe() {{}} disconnect() {{}} }};
        const mod = await import('{TILE.as_posix()}');
        const modal = (zone) => ({{ querySelector: () => ({{ dataset: zone ? {{ _tileZone: zone }} : {{}} }}) }});
        console.log(JSON.stringify({{
          maximize: mod.isModalMaximized(modal('maximize')),
          fullscreen: mod.isModalMaximized(modal('fullscreen')),
          left: mod.isModalMaximized(modal('left')),
          none: mod.isModalMaximized(modal(null)),
          nothing: mod.isModalMaximized(null),
        }}));
    """)
    out = subprocess.run(["node", "--input-type=module"], input=script, capture_output=True,
                         text=True, timeout=60, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got == {"maximize": True, "fullscreen": True, "left": False, "none": False,
                   "nothing": False}


def test_the_workbench_toggle_reads_the_tile_managers_answer():
    src = WORKBENCH.read_text(encoding="utf-8")
    start = src.index("function _wireMaximize(modal)")
    body = src[start:src.index("\n}\n", start)]
    toggle = body[body.index("const toggle = () =>"):]
    toggle = toggle[:toggle.index("};")]
    loaded = toggle[toggle.index("import('../tileManager.js').then((m) =>"):]
    assert re.search(r"m\.setModalMaximized\(modal,\s*!m\.isModalMaximized\(modal\)\)", loaded), loaded
