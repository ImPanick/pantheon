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
const art = { textContent: '' }, line = { textContent: '' };
const controls = Object.fromEntries(['.companion-character', '.companion-cheer', '.companion-rest', '.companion-hide']
  .map(k => [k, { addEventListener: (event, fn) => { listeners[k] = fn; } }]));
const stage = { hidden: true, dataset: {}, querySelector: k =>
  ({ '.companion-art': art, '.companion-line': line, ...controls })[k] };
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
assert.match(line.textContent, /Glad/);
assert.equal(timers.size, 1);
pip.companionAction('cheer');
assert.match(line.textContent, /Rooting/);
assert.equal(timers.size, 1); // second action interrupts the first timer
assert.equal(pip.companionAction('<img>'), false);
assert.match(line.textContent, /Rooting/);
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
    for control in ("companion-character", "companion-cheer", "companion-rest", "companion-hide",
                    "companion-helpful", "companion-off-track"):
        assert f'<button type="button" class="{control}"' in html
    assert '<button type="submit" class="companion-save-feedback"' in html


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_feedback_display_tracks_variant_and_clears_on_new_chat(tmp_path):
    (tmp_path / "companion.js").write_bytes((ROOT / "static/js/companion.js").read_bytes())
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    (tmp_path / "storage.js").write_text("""
const values = new Map();
export default { get: (key, fallback) => values.get(key) ?? fallback,
                 set: (key, value) => values.set(key, value) };
""", encoding="utf-8")
    (tmp_path / "motion.js").write_text("export const prefersReducedMotion = () => true;", encoding="utf-8")
    (tmp_path / "probe.mjs").write_text("""
import assert from 'node:assert/strict';
const listeners = {};
const el = () => ({ hidden: false, disabled: false, textContent: '',
  addEventListener() {}, setAttribute() {}, focus() {} });
const art = el(), line = el(), hint = el(), actions = el(), status = el(), retry = el(), use = el();
const helpful = el(), offTrack = el(), save = el(), correction = el();
const form = { ...el(), querySelector: key => key === '.companion-save-feedback' ? save : null };
const controls = Object.fromEntries(['.companion-character', '.companion-cheer', '.companion-rest', '.companion-hide',
  '.companion-cancel-feedback'].map(key => [key, el()]));
const parts = { '.companion-art': art, '.companion-line': line, '.companion-feedback-hint': hint,
  '.companion-feedback-actions': actions, '.companion-feedback-form': form,
  '.companion-feedback-status': status, '.companion-feedback-retry': retry,
  '.companion-use-in-chat': use, '.companion-helpful': helpful,
  '.companion-off-track': offTrack, '#companion-correction': correction, ...controls };
const stage = { ...el(), hidden: true, dataset: {}, style: {}, querySelector: key => parts[key] };
const toggle = { ...el(), dataset: {} };
const reply = { dataset: { dbId: 'reply-1', raw: 'Original answer', variantIndex: '0' } };
let sessionId = 'chat-1', replies = [reply];
globalThis.window = { sessionModule: { getCurrentSessionId: () => sessionId }, addEventListener() {} };
globalThis.document = { readyState: 'loading',
  addEventListener: (name, fn) => { listeners[name] = fn; },
  getElementById: id => ({ 'companion-stage': stage, 'companion-toggle': toggle })[id],
  querySelectorAll: () => replies, querySelector: () => null };
const requests = [];
globalThis.fetch = async url => {
  requests.push(url);
  const variant = new URL(url, 'http://local').searchParams.get('variant_index');
  return { ok: true, json: async () => variant === '0'
    ? { rating: 'off_track', correction: 'Fix the old answer.' }
    : { rating: null, correction: '' } };
};
const pip = await import('./companion.js');
pip.initCompanion();
pip.setCompanionEnabled(true);
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
await settle();
assert.match(hint.textContent, /Fix the old answer/);
reply.dataset.raw = 'Different variant'; reply.dataset.variantIndex = '1';
listeners['pantheon:reply-list-changed']();
await settle();
assert.match(hint.textContent, /Different variant/);
assert.equal(use.hidden, true);
assert.equal(requests.at(-1).includes('variant_index=1'), true);
sessionId = ''; replies = [];
listeners['pantheon:session-changed']();
assert.match(hint.textContent, /No assistant reply/);
assert.equal(actions.hidden, true);
console.log('variant and new-chat state OK');
""", encoding="utf-8")
    result = subprocess.run(["node", str(tmp_path / "probe.mjs")],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "variant and new-chat state OK" in result.stdout
