// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/evalsPanel.js — `B490`. The eval harness's door.
//
// `P14-03` built `src/evals.py` (a suite is a list of past runs plus what each
// answer should say; running it replays them and scores the answers), `P14-04`
// wired the receipt diff to its failures, and `routes/diagnostics_routes.py`
// served `GET /api/diagnostics/evals` and `POST /api/diagnostics/evals/{name}/run`
// — and nothing under static/ called either. Suites lived in the `eval_suites`
// setting with no editor, and the run ids a case is made of were shown on no
// page. So the only way to use the harness was to hand-write JSON into a
// setting and curl an admin endpoint.
//
// This panel is the whole loop without leaving the page: pick a recent run
// (`GET /api/diagnostics/runs`), say what its answer should contain, save it
// into a suite (`POST /api/auth/settings`, `eval_suites` — the settings door,
// which validates the list), and run the suite, optionally against another
// model. The result shows the pass rate, the skipped count and how it was
// graded (`grading`), and each case's verdict — the row's `Verify:`.
//
// Built with textContent and DOM calls: every string here is server-derived or
// the operator's own, and none of it is markup.

import { getSettings, invalidateSettings } from './appConfig.js';

const $ = (id) => document.getElementById(id);

function _node(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = String(text);
  return n;
}

function _say(id, text) {
  const out = $(id);
  if (out) out.textContent = text || '';
}

async function _json(res) {
  try { return await res.json(); } catch (_) { return {}; }
}

function _refusal(res, data) {
  return (data && (data.detail || data.error)) || `HTTP ${res.status}`;
}

/** Split "a, b\nc" into ['a', 'b', 'c']. */
function _words(raw) {
  return String(raw || '').split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
}

/** The suites as stored, read fresh (the cache may predate a save elsewhere). */
async function _storedSuites() {
  invalidateSettings();
  const s = await getSettings();
  const raw = s && s.eval_suites;
  if (Array.isArray(raw)) return raw.map((x) => ({ ...x }));
  if (typeof raw === 'string' && raw.trim()) {
    try { const v = JSON.parse(raw); return Array.isArray(v) ? v : []; } catch (_) { return []; }
  }
  return [];
}

async function _saveSuites(suites) {
  const res = await fetch('/api/auth/settings', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ eval_suites: suites }),
  });
  const data = await _json(res);
  invalidateSettings();
  if (!res.ok) throw new Error(_refusal(res, data));
  return data;
}

function _runLabel(r) {
  const when = r.ts ? String(r.ts).replace('T', ' ').slice(0, 16) : '';
  return [when, r.chat || 'a chat', r.model].filter(Boolean).join(' · ');
}

/** The newest runs into the picker. */
export async function loadRuns() {
  const sel = $('evals-run');
  if (!sel) return [];
  let data;
  try {
    const res = await fetch('/api/diagnostics/runs?limit=30', { credentials: 'same-origin' });
    data = await _json(res);
    if (!res.ok) { _say('evals-build-msg', `Could not list recent runs: ${_refusal(res, data)}`); return []; }
  } catch (_) {
    _say('evals-build-msg', 'Could not reach this Pantheon.');
    return [];
  }
  const runs = Array.isArray(data.runs) ? data.runs : [];
  sel.replaceChildren();
  if (!runs.length) {
    const opt = _node('option', '', 'No runs recorded yet — send a message first');
    opt.value = '';
    sel.appendChild(opt);
  }
  for (const r of runs) {
    const opt = _node('option', '', _runLabel(r));
    opt.value = r.run_id;
    sel.appendChild(opt);
  }
  return runs;
}

function _renderResult(result) {
  const out = $('evals-result');
  if (!out) return;
  out.replaceChildren();
  out.appendChild(_node('p', 'usage-headline', result.headline || ''));
  if (Array.isArray(result.problems) && result.problems.length) {
    const ul = _node('ul', 'evals-problems');
    result.problems.forEach((p) => ul.appendChild(_node('li', '', p)));
    out.appendChild(ul);
    return;
  }
  const scored = (result.passed || 0) + (result.failed || 0);
  const rate = result.pass_rate == null ? 'no case ran'
    : `${Math.round(result.pass_rate * 100)}% (${result.passed}/${scored})`;
  const facts = _node('dl', 'evals-facts');
  for (const [k, v] of [['Pass rate', rate], ['Skipped', String(result.skipped || 0)],
                        ['Graded', result.grading || 'unknown'],
                        ['Model', result.model || 'each run’s own']]) {
    facts.appendChild(_node('dt', '', k));
    facts.appendChild(_node('dd', `evals-${k.toLowerCase().replace(/\s+/g, '-')}`, v));
  }
  out.appendChild(facts);
  const ul = _node('ul', 'evals-cases');
  for (const c of (result.cases || [])) {
    let line = `${c.status} — ${c.label || c.run_id}`;
    if (c.status === 'skipped' && c.reason) line += `: ${c.reason}`;
    if (c.status === 'failed') {
      const missed = (c.checks || []).filter((x) => !x.passed).map((x) => `${x.check} ${x.detail}`);
      if (missed.length) line += `: ${missed.join('; ')}`;
      if (c.why) line += ` (${c.why})`;
    }
    ul.appendChild(_node('li', `evals-case is-${c.status}`, line));
  }
  out.appendChild(ul);
}

/** Run one suite and show what came back. */
export async function runSuite(name) {
  const model = ($('evals-model')?.value || '').trim();
  _say('evals-result', `Running ${name}… each case is a model call.`);
  let res, data;
  try {
    res = await fetch(`/api/diagnostics/evals/${encodeURIComponent(name)}/run`
      + (model ? `?model=${encodeURIComponent(model)}` : ''), {
      method: 'POST', credentials: 'same-origin',
    });
    data = await _json(res);
  } catch (_) {
    _say('evals-result', 'Could not reach this Pantheon.');
    return null;
  }
  if (!res.ok) { _say('evals-result', `Not run: ${_refusal(res, data)}`); return null; }
  _renderResult(data);
  return data;
}

/** The suites, each with its cases and either its problems or a Run button. */
export async function loadSuites() {
  const host = $('evals-list');
  if (!host) return [];
  let data;
  try {
    const res = await fetch('/api/diagnostics/evals', { credentials: 'same-origin' });
    data = await _json(res);
    if (!res.ok) { host.textContent = `Could not load suites: ${_refusal(res, data)}`; return []; }
  } catch (_) {
    host.textContent = 'Could not reach this Pantheon.';
    return [];
  }
  const suites = Array.isArray(data.suites) ? data.suites : [];
  host.replaceChildren();
  if (!suites.length) {
    host.appendChild(_node('p', 'usage-empty',
      'No suites yet. Open “Add a case” below: pick a run, say what its answer should contain, and it becomes the first case of a suite.'));
    return suites;
  }
  for (const s of suites) {
    const row = _node('div', 'evals-suite');
    row.dataset.suite = s.name;
    row.appendChild(_node('strong', '', s.name));
    row.appendChild(_node('span', 'evals-count', ` ${s.cases} case${s.cases === 1 ? '' : 's'} `));
    if (Array.isArray(s.problems) && s.problems.length) {
      const ul = _node('ul', 'evals-problems');
      s.problems.forEach((p) => ul.appendChild(_node('li', '', p)));
      row.appendChild(ul);
    } else {
      const btn = _node('button', 'btn-secondary evals-run-btn', 'Run');
      btn.type = 'button';
      btn.addEventListener('click', () => { runSuite(s.name); });
      row.appendChild(btn);
    }
    host.appendChild(row);
  }
  return suites;
}

/** Append one case — the picked run and what its answer should say — to the
 *  named suite (made if new), and save. */
export async function addCase() {
  const name = ($('evals-suite-name')?.value || '').trim();
  const runId = ($('evals-run')?.value || '').trim();
  if (!name) { _say('evals-build-msg', 'Name the suite first.'); return false; }
  if (!runId) { _say('evals-build-msg', 'Pick a run. If the list is empty, send a message first.'); return false; }
  const expect = {};
  const contains = _words($('evals-contains')?.value);
  const not = _words($('evals-not-contains')?.value);
  const cap = String($('evals-max-failures')?.value ?? '').trim();
  if (contains.length) expect.contains = contains;
  if (not.length) expect.not_contains = not;
  if (cap !== '') expect.max_tool_failures = Math.max(0, parseInt(cap, 10) || 0);
  if (!Object.keys(expect).length) expect.no_error = true;
  const label = $('evals-run')?.selectedOptions?.[0]?.textContent || runId;
  let suites;
  try { suites = await _storedSuites(); } catch (_) { suites = []; }
  let suite = suites.find((s) => s && s.name === name);
  if (!suite) { suite = { name, cases: [] }; suites.push(suite); }
  suite.cases = Array.isArray(suite.cases) ? suite.cases : [];
  suite.cases.push({ run_id: runId, label, expect });
  try {
    await _saveSuites(suites);
  } catch (e) {
    _say('evals-build-msg', `Not saved: ${e.message}`);
    return false;
  }
  _say('evals-build-msg', `Saved — ${name} has ${suite.cases.length} case${suite.cases.length === 1 ? '' : 's'}.`);
  await loadSuites();
  return true;
}

let _wired = false;

/** Called by Diagnostics when the panel is first opened. */
export async function open() {
  if (!_wired) {
    _wired = true;
    $('evals-add-case')?.addEventListener('click', () => { addCase(); });
  }
  await Promise.all([loadSuites(), loadRuns()]);
}
