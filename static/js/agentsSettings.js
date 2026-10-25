// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P24-15`. Settings → Agents: the two instance-wide brakes on hired agents.
//
// *Pause all agents* is `agents_paused`; *Most agent runs at once* is
// `agents_max_concurrent`. Both are read by `src/agents/runtime.py` before
// every agent run and saved through `POST /api/auth/settings`, which checks
// the switch is a yes/no and clamps the number to its range — so the panel
// draws the value the server kept, not the one typed (`Law 7`: the range lives
// in `src/settings.py`, and this file reads it back rather than restating it).

import { invalidateSettings } from './appConfig.js';

const $ = (id) => document.getElementById(id);
let _wired = false;

function _say(text, { error = false } = {}) {
  const out = $('agents-settingsResult');
  if (!out) return;
  out.textContent = text || '';
  out.hidden = !text;
  out.classList.toggle('agents-settings-error', !!error);
}

async function _read() {
  try {
    const res = await fetch('/api/auth/settings', { credentials: 'same-origin' });
    return res.ok ? await res.json() : {};
  } catch (_) {
    return {};
  }
}

function _draw(settings) {
  const toggle = $('agents-pausedToggle');
  const input = $('agents-maxInput');
  if (toggle) toggle.checked = settings.agents_paused === true;
  if (input && settings.agents_max_concurrent != null) input.value = String(settings.agents_max_concurrent);
  _drawSlotNote(settings);
}

/** `B1464`. A scheduled agent run also takes one of the background-model
 *  slots (`task_concurrency_cap`, 1 by default), so below this number that is
 *  the real limit — say so, rather than let a 4 here read as four at once. */
function _drawSlotNote(settings) {
  const note = $('agents-maxNote');
  if (!note) return;
  const slots = Number(settings.task_concurrency_cap);
  const most = Number(settings.agents_max_concurrent);
  if (Number.isFinite(slots) && Number.isFinite(most) && slots < most) {
    note.textContent = `Scheduled runs also wait for one of Pantheon's ${slots} background-model ` +
      `slot${slots === 1 ? '' : 's'} (task_concurrency_cap), so at most ${slots} run at once. ` +
      'A first run when you summon, and a workflow step, do not wait for one.';
    note.hidden = false;
  } else {
    note.textContent = '';
    note.hidden = true;
  }
}

/** Save one change; draw what the server kept. */
export async function save(body) {
  let res;
  try {
    res = await fetch('/api/auth/settings', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (_) {
    _say("Pantheon's server did not answer. Nothing was changed.", { error: true });
    return false;
  }
  if (!res.ok) {
    let detail = 'The change was not saved.';
    try {
      const err = await res.json();
      if (err && err.detail) detail = String(err.detail);
    } catch (_) { /* keep the sentence */ }
    _say(detail, { error: true });
    _draw(await _read());
    return false;
  }
  invalidateSettings();
  const kept = await _read();
  _draw(kept);
  if ('agents_paused' in body) {
    _say(kept.agents_paused ? 'Every agent is paused.' : 'Agents run again at their next time.');
  } else {
    _say(`Saved: at most ${kept.agents_max_concurrent} at once.`);
  }
  return true;
}

export async function open() {
  _draw(await _read());
  _say('');
  if (_wired) return;
  _wired = true;
  $('agents-pausedToggle')?.addEventListener('change', (e) => {
    save({ agents_paused: !!e.target.checked });
  });
  $('agents-maxInput')?.addEventListener('change', (e) => {
    const n = parseInt(e.target.value, 10);
    if (!Number.isFinite(n)) { _say('Type a whole number.', { error: true }); return; }
    save({ agents_max_concurrent: n });
  });
}

export default { open, save };
