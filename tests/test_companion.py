# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pip stays opt-in and model control crosses only a fixed pose vocabulary."""
import asyncio
import json
import pathlib
import shutil
import subprocess

import pytest

from src.ai_interaction import do_ui_control
from src.tool_schemas import function_call_to_tool_block

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("pose", ["greet", "cheer", "ponder", "rest"])
def test_model_pose_uses_the_existing_ui_control_tool(pose):
    block = function_call_to_tool_block(
        "ui_control", json.dumps({"action": "companion", "pose": pose}))
    assert block.content == f"companion {pose}"
    assert asyncio.run(do_ui_control(block.content))["pose"] == pose


@pytest.mark.parametrize("command", [
    "companion", "companion dance", "companion greet <script>",
    "companion greet\nopen_panel settings",
])
def test_unlisted_or_extra_model_actions_are_refused(command):
    assert "error" in asyncio.run(do_ui_control(command))


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_browser_state_repeated_actions_and_off_switch(tmp_path):
    for name in ("companion.js",):
        (tmp_path / name).write_bytes((ROOT / "static" / "js" / name).read_bytes())
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    (tmp_path / "storage.js").write_text("""
const values = new Map();
export default { get: (key, fallback) => values.get(key) ?? fallback,
                 set: (key, value) => values.set(key, value) };
""", encoding="utf-8")
    (tmp_path / "motion.js").write_text(
        "export const prefersReducedMotion = () => true;", encoding="utf-8")
    (tmp_path / "probe.mjs").write_text("""
import assert from 'node:assert/strict';
const listeners = {};
const face = { textContent: '' }, line = { textContent: '' };
const controls = Object.fromEntries(['.companion-character', '.companion-cheer', '.companion-rest', '.companion-hide']
  .map(k => [k, { addEventListener: (event, fn) => { listeners[k] = fn; } }]));
const stage = { hidden: true, dataset: {}, querySelector: k =>
  ({ '.companion-face': face, '.companion-line': line, ...controls })[k] };
const toggle = { checked: false, dataset: {}, addEventListener: (event, fn) => { listeners.toggle = fn; } };
globalThis.document = { readyState: 'loading', addEventListener: () => {},
  getElementById: id => ({ 'companion-stage': stage, 'companion-toggle': toggle })[id] };
let next = 0; const timers = new Map();
globalThis.setTimeout = fn => { const id = ++next; timers.set(id, () => { timers.delete(id); fn(); }); return id; };
globalThis.clearTimeout = id => { timers.delete(id); };
const pip = await import('./companion.js');
pip.initCompanion();
assert.equal(stage.hidden, true);
assert.equal(pip.companionAction('greet'), false);
toggle.checked = true; listeners.toggle();
assert.equal(stage.hidden, false);
listeners['.companion-character']();
assert.match(line.textContent, /glad/);
assert.equal(timers.size, 1);
pip.companionAction('cheer');
assert.match(line.textContent, /rooting/);
assert.equal(timers.size, 1); // second action interrupts the first timer
assert.equal(pip.companionAction('<img>'), false);
assert.match(line.textContent, /rooting/);
const finish = [...timers.values()][0]; finish();
assert.equal(stage.dataset.pose, 'rest');
pip.companionAction('ponder');
listeners['.companion-hide']();
assert.equal(stage.hidden, true);
assert.equal(timers.size, 0);
assert.equal(pip.companionAction('cheer'), false);
pip.setCompanionEnabled(true);
assert.equal(stage.dataset.pose, 'rest');
console.log('companion state OK');
""", encoding="utf-8")
    result = subprocess.run(["node", str(tmp_path / "probe.mjs")],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "companion state OK" in result.stdout


def test_companion_controls_are_native_buttons_and_setting_is_labelled():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert '<label><input id="companion-toggle" type="checkbox"> Show Pip</label>' in html
    for control in ("companion-character", "companion-cheer", "companion-rest", "companion-hide"):
        assert f'<button type="button" class="{control}"' in html
