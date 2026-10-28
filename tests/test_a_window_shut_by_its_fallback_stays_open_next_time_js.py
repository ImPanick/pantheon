# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1567`, the product half — a window shut by its fallback timer opens again.

`B1567` was filed as two browser drives that fail under a loaded machine and
pass alone. One of them — the Brain walk — timed out clicking
`#close-memory-modal` because *the element is not visible*: the Brain had shut
itself. Measured in Chromium, opening and closing the Brain three times in a
row with nothing else running: the third open showed the window for ~290 ms
and hid it again with no click.

The cause was in the closer, not the drive. `app.js` `dismissModal` (and the
Skills window's own close) ran two callbacks: an `animationend` listener with
`{ once: true }` and a 250 ms fallback. When the fallback won — a starved
frame — it hid the window, and display:none cut the closing animation, so the
listener stayed attached. The window's next OPENING animation ended, fired it,
and the window shut. `motion.js` `whenShut` is the one answer now: whichever
comes first, once, and the other taken back.

Driven in node on the real `motion.js` with a stand-in element that records
its listeners and fires `animationend` as the browser does.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
MOTION = ROOT / "static" / "js" / "motion.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_HARNESS = r"""
const listeners = new Set();
const content = {
  addEventListener(type, fn) { if (type === 'animationend') listeners.add(fn); },
  removeEventListener(type, fn) { if (type === 'animationend') listeners.delete(fn); },
};
const end = (target = content) => [...listeners].forEach((fn) => fn({ target }));
const tick = (ms) => new Promise((r) => setTimeout(r, ms));
"""


def _run(tmp_path, script: str) -> dict:
    (tmp_path / "motion.js").write_text(MOTION.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "case.mjs").write_text(
        "import { whenShut } from './motion.js';\n" + _HARNESS + script, encoding="utf-8")
    proc = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_fallback_that_wins_takes_the_listener_back(tmp_path):
    """The defect: the timer shut the window, and the next opening animation's
    end shut it again."""
    out = _run(tmp_path, """
        let shut = 0;
        whenShut(content, () => { shut += 1; }, 20);
        await tick(60);                       // the closing animation never ended
        const after = { shut, listeners: listeners.size };
        end();                                // the NEXT open's animation ends
        console.log(JSON.stringify({ after, final: shut }));
    """)
    assert out["after"] == {"shut": 1, "listeners": 0}
    assert out["final"] == 1, "the window's next opening shut it again"


def test_an_animation_that_ends_first_cancels_the_fallback(tmp_path):
    out = _run(tmp_path, """
        let shut = 0;
        whenShut(content, () => { shut += 1; }, 40);
        end();
        await tick(80);
        console.log(JSON.stringify({ shut, listeners: listeners.size }));
    """)
    assert out == {"shut": 1, "listeners": 0}


def test_a_childs_animation_is_not_the_windows(tmp_path):
    out = _run(tmp_path, """
        let shut = 0;
        whenShut(content, () => { shut += 1; }, 40);
        end({ child: true });
        const early = shut;
        await tick(80);
        console.log(JSON.stringify({ early, shut }));
    """)
    assert out == {"early": 0, "shut": 1}


@pytest.mark.parametrize("path,signature,element", [
    ("static/app.js", "function dismissModal(", "content"),
    ("static/js/skills.js", "export function closeSkillsWindow(", "content"),
    # `B1638`: the three closers `B1567` missed, each the same race — the
    # model picker's (the picture drive's load flake), the Theme popup's, and
    # the backdrop tap every modal shares. Found by the shape (an
    # `animationend` listener that adds `hidden`, beside a timer), measured
    # 2026-10-28: five sites, of which the Forge's `_doClose` (its opening
    # bumps `_closeGen`) and Settings' `hideSettingsModal` (its own `finish`,
    # once) already answer once.
    ("static/js/modelPicker.js", "function _close(", "menu"),
    ("static/js/theme.js", "export function closePopup(", "content"),
    ("static/js/ui.js", "function closeFromBackdrop(", "content"),
])
def test_every_closer_that_hides_a_window_uses_it(path, signature, element):
    """Scoped to each closer's own body (`Law 20`): none keeps a bare
    `animationend` listener of its own beside a timer."""
    body = js_function((ROOT / path).read_text(encoding="utf-8"), signature)
    assert f"whenShut({element}" in body
    assert "addEventListener('animationend'" not in body
