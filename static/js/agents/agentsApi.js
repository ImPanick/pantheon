// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/agents/agentsApi.js
//
// `P24-03`. The Agents hall's one door to the server. Every path
// `routes/agent_routes.py` serves is spelled here, literally, so
// `check-unreachable.py` finds its caller (the route ceiling, `Law 13`); and
// *Run now* is the hire's task's own route — the Tasks window's — because a
// second door to a run would be a second place to keep its rules (`Law 14`).
//
// Each call answers `{ ok: true, data }` or `{ ok: false, refusal }`, the
// refusal read the one way the Workbench reads one (`refusal.js`), so the
// window says the server's sentence and never a status code.

import { readRefusal } from '../workbench/refusal.js';

const JSON_HEADERS = { 'Content-Type': 'application/json' };

async function _call(url, opts = {}, fallback) {
  let res;
  try {
    res = await fetch(url, { credentials: 'same-origin', ...opts });
  } catch (_) {
    return { ok: false, refusal: { status: 0, sentence: "Pantheon's server did not answer. Try again in a moment." } };
  }
  if (!res.ok) return { ok: false, refusal: await readRefusal(res, fallback) };
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  return { ok: true, data };
}

const _id = (s) => encodeURIComponent(String(s || ''));

/** The catalogue, its sections and families, and this person's hires
 *  (`everyone`: an admin's view of every hire). */
export function listAgents({ everyone = false } = {}) {
  return _call(everyone ? '/api/agents?everyone=1' : '/api/agents', {},
    'The Agents hall could not be read.');
}

export function getAgent(agentId) {
  return _call(`/api/agents/${_id(agentId)}`, {}, 'That agent could not be read.');
}

export function hireAgent(agentId, body) {
  return _call(`/api/agents/${_id(agentId)}/hire`,
    { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(body || {}) },
    'The hire was not made.');
}

export function getHire(hireId) {
  return _call(`/api/agents/hires/${_id(hireId)}`, {}, 'That hire could not be read.');
}

export function changeHire(hireId, body) {
  return _call(`/api/agents/hires/${_id(hireId)}`,
    { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify(body || {}) },
    'The change was not saved.');
}

export function setHireStatus(hireId, status) {
  return _call(`/api/agents/hires/${_id(hireId)}/status`,
    { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ status }) },
    'The hire was left as it was.');
}

export function fireHire(hireId) {
  return _call(`/api/agents/hires/${_id(hireId)}`, { method: 'DELETE' }, 'The hire was not fired.');
}

/** *Run now*: the hire's first task's own route (`POST /api/tasks/{id}/run`). */
export function runNow(taskId) {
  return _call(`/api/tasks/${_id(taskId)}/run`,
    { method: 'POST', headers: JSON_HEADERS, body: '{}' }, 'The run did not start.');
}

export default { listAgents, getAgent, hireAgent, getHire, changeHire, setHireStatus, fireHire, runNow };
