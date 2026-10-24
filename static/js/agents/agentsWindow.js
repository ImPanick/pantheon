// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/agents/agentsWindow.js
//
// `P24-12` / `P24-13` / `P24-14` (first cut). The Agents hall: a scrolling
// roster of pre-configured agents, each a job done end to end — find one, read
// what it will do, hire it in two clicks, and watch it work.
//
// Laid out the way PandaOS lays out its board (the owner's screenshots of
// 2026-10-22, the plan's § 4), top to bottom:
//
//   * **Your agents** — a card per hire, with a count and *Show less*;
//   * a search box over the whole catalogue (*Search 18 agents…*);
//   * a row of chips, one per section with its count;
//   * the catalogue, one titled section per chip, cards in a grid with
//     *Show more*; a hired agent stays in place with **Hired** across it.
//
// Three views in one window, with a `← Agents` back line inside it: the hall,
// an agent's page (what it does, when it starts, what it may do without asking,
// the tools it will lack for this person, its runbook, and the hire form), and
// a hire's own page (*Run now*, *Pause*, *Fire*, the update offer, its runs and
// their reports, its notebook).
//
// **Every rule is the server's** (`routes/agent_routes.py`): who may see which
// hire, what a hire may be given, what an effect may be set to. A refusal is
// shown in the server's sentence (`agentsApi.js`). The markup is built with
// `createElement` and `textContent`, so no server string is parsed as HTML —
// a manifest is a file a person may have written.
//
// A tool window like the workstation screen's (`workstationScreen.js`):
// `modalManager` for the dock, `windowDrag` for moving it, the back stack for
// Escape and Back, `/agents` for its URL.

import * as Modals from '../modalManager.js?v=20261009census';
import { makeWindowDraggable } from '../windowDrag.js';
import * as Api from './agentsApi.js';

export const MODAL_ID = 'agents-modal';

/** How many cards a section shows before *Show more* — the board's one row. */
export const SECTION_PREVIEW = 6;
/** How many hires the strip shows before *Show more*. */
export const STRIP_PREVIEW = 7;

export const AGENT_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
  + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
  + 'aria-hidden="true"><rect x="4" y="8" width="16" height="12" rx="3"/>'
  + '<path d="M12 4v4"/><circle cx="12" cy="3" r="1"/><path d="M9 13h.01M15 13h.01M9.5 16.5h5"/></svg>';

/** What each effect means, in the words a person reads. The keys are
 *  `ToolEffect`'s values (`src/tool_capabilities.py`). */
export const EFFECT_WORDS = {
  read_public: 'read public pages',
  read_workspace: 'read files in your projects',
  read_private: 'read your mail, notes, calendar and documents',
  brokered_network_read: 'search the web',
  user_interaction: 'ask you a question',
  write_workspace: 'write files in your projects',
  write_private: 'write to your documents, notes, contacts and calendar',
  execute_code: 'run commands',
  network_egress: 'reach other sites and machines',
  external_side_effect: 'send mail or act outside Pantheon',
  ui_side_effect: "change what Pantheon's screen shows",
  admin_change: "change Pantheon's settings",
  destructive: 'delete things',
};
export const RULE_WORDS = { allow: 'without asking', ask: 'asks you first', never: 'never' };
export const STATUS_WORDS = { on: 'On', paused: 'Paused', attention: 'Needs you', trial: 'Trial' };
/** How many teams the row shows before *Show more* — the board's one row. */
export const TEAMS_PREVIEW = 6;
const RUN_WORDS = {
  queued: 'Queued', running: 'Running', success: 'Done', error: 'Failed', skipped: 'Skipped',
  aborted: 'Stopped', waiting: 'Waiting for you',
};

// ── state ───────────────────────────────────────────────────────────────────

let _win = null;
let _data = null;           // the last GET /api/agents
let _view = { kind: 'hall' };
let _query = '';
let _section = '';          // '' = All
let _expanded = new Set();  // section ids showing every card
let _stripAll = false;
let _teamsAll = false;
let _everyone = false;
let _busy = false;

// ── small builders ──────────────────────────────────────────────────────────

function _el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null && text !== '') node.textContent = String(text);
  return node;
}

function _button(cls, text, onClick, { title } = {}) {
  const b = _el('button', cls, text);
  b.type = 'button';
  if (title) b.title = title;
  b.addEventListener('click', (e) => { e.preventDefault(); onClick(e); });
  return b;
}

function _clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }

function _say(text, { error = false } = {}) {
  if (!_win) return;
  _win.note.textContent = text || '';
  _win.note.hidden = !text;
  _win.note.classList.toggle('agents-note-error', !!error);
}

function _when(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit' });
}

function _tz() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (_) { return ''; }
}

/** The initial on a card's face: the agent's own first letter, so two cards
 *  side by side are told apart without an icon set to keep in step. */
function _initial(name) {
  const s = String(name || '?').trim();
  return (s[0] || '?').toUpperCase();
}

// ── the pure parts (exported for the tests) ──────────────────────────────────

/** Which agents a query and a chip leave, in the catalogue's own order. */
export function filterAgents(agents, query, section) {
  const q = String(query || '').trim().toLowerCase();
  return (agents || []).filter((a) => {
    if (section && a.section !== section) return false;
    if (!q) return true;
    return [a.name, a.tagline, a.section_label, (a.tools || []).join(' ')]
      .join(' ').toLowerCase().includes(q);
  });
}

/** Sections in the hall's order, each with the agents a filter left — empty
 *  sections are left out, so a chip never opens on nothing. */
export function groupBySection(sections, agents) {
  const out = [];
  for (const s of sections || []) {
    const inIt = (agents || []).filter((a) => a.section === s.id);
    if (inIt.length) out.push({ ...s, agents: inIt });
  }
  return out;
}

/** What a hire form's values are, read off its fields, for `POST …/hire`. */
export function readInputs(specs, form) {
  const out = {};
  for (const spec of specs || []) {
    const field = form.querySelector(`[data-input="${spec.key}"]`);
    if (!field) continue;
    if (spec.kind === 'boolean') { out[spec.key] = !!field.checked; continue; }
    const raw = String(field.value || '').trim();
    if (!raw) continue;
    if (spec.kind === 'number') { out[spec.key] = Number(raw); continue; }
    if (spec.kind === 'list') {
      out[spec.key] = raw.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
      continue;
    }
    out[spec.key] = raw;
  }
  return out;
}

// ── the window ──────────────────────────────────────────────────────────────

function _build() {
  const modal = _el('div', 'modal agents-modal');
  modal.id = MODAL_ID;
  const content = _el('div', 'modal-content agents-content');
  content.setAttribute('role', 'dialog');
  content.setAttribute('aria-label', 'Agents');
  const header = _el('div', 'modal-header');
  const title = _el('h4', 'agents-title');
  const icon = _el('span', 'agents-title-icon');
  icon.innerHTML = AGENT_ICON;   // a constant above, never server text
  title.appendChild(icon);
  title.appendChild(document.createTextNode('Agents'));
  const close = _el('button', 'close-btn');
  close.type = 'button';
  close.title = 'Close';
  close.setAttribute('aria-label', 'Close');
  close.textContent = '✖';
  close.addEventListener('click', (e) => { e.preventDefault(); closeAgents(); });
  header.appendChild(title);
  header.appendChild(close);
  const note = _el('p', 'agents-note');
  note.setAttribute('role', 'status');
  note.setAttribute('aria-live', 'polite');
  note.hidden = true;
  const body = _el('div', 'modal-body agents-body');
  content.appendChild(header);
  content.appendChild(note);
  content.appendChild(body);
  modal.appendChild(content);
  return { modal, content, header, note, body };
}

async function _load() {
  const res = await Api.listAgents({ everyone: _everyone });
  if (!_win) return false;
  if (!res.ok) { _say(res.refusal.sentence, { error: true }); return false; }
  _data = res.data;
  return true;
}

function _render() {
  if (!_win) return;
  _clear(_win.body);
  if (!_data) {
    _win.body.appendChild(_el('p', 'agents-empty', 'Reading the hall…'));
    return;
  }
  if (_view.kind === 'agent') _renderAgent(_view.agent);
  else if (_view.kind === 'hire') _renderHire(_view.hire);
  else if (_view.kind === 'team') _renderTeam(_view.team);
  else _renderHall();
}

function _back(onto = 'hall') {
  return _button('agents-back', '← Agents', () => { _view = { kind: onto }; _say(''); _render(); });
}

// ── the hall ────────────────────────────────────────────────────────────────

function _renderHall() {
  const body = _win.body;
  const hires = _data.hires || [];
  const agents = _data.agents || [];

  // `P24-10`. Said where the agents are, not only in Settings.
  if (_data.ceilings && _data.ceilings.paused) {
    body.appendChild(_el('p', 'agents-attention agents-paused-all',
      'An admin has paused all agents: nothing runs until they are switched back on'
      + (_data.is_admin ? ' in Settings → Agents.' : '.')));
  }

  // Your agents
  const strip = _el('section', 'agents-strip');
  const head = _el('div', 'agents-strip-head');
  head.appendChild(_el('h5', 'agents-h', _everyone ? "Everyone's agents" : 'Your agents'));
  const right = _el('div', 'agents-strip-right');
  right.appendChild(_el('span', 'agents-count', `${hires.length} hired`));
  if (hires.length > STRIP_PREVIEW) {
    right.appendChild(_button('agents-link', _stripAll ? 'Show less' : `Show more (${hires.length - STRIP_PREVIEW})`,
      () => { _stripAll = !_stripAll; _render(); }));
  }
  if (_data.is_admin) {
    const lab = _el('label', 'agents-everyone');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = _everyone;
    box.addEventListener('change', async () => { _everyone = box.checked; await _load(); _render(); });
    lab.appendChild(box);
    lab.appendChild(document.createTextNode(' Everyone'));
    right.appendChild(lab);
  }
  head.appendChild(right);
  strip.appendChild(head);
  if (!hires.length) {
    strip.appendChild(_el('p', 'agents-empty',
      'No agents hired yet. Pick one below — it works on its own schedule and reports back.'));
  } else {
    const grid = _el('div', 'agents-grid');
    (_stripAll ? hires : hires.slice(0, STRIP_PREVIEW)).forEach((h) => grid.appendChild(_hireCard(h)));
    strip.appendChild(grid);
  }
  body.appendChild(strip);

  // `P24-21`. Teams: bundles hired in one go.
  const teams = _data.teams || [];
  if (teams.length && !_everyone) {
    const row = _el('section', 'agents-teams');
    const th = _el('div', 'agents-section-head');
    th.appendChild(_el('h5', 'agents-h', 'Teams'));
    if (teams.length > TEAMS_PREVIEW) {
      th.appendChild(_button('agents-link', _teamsAll ? 'Show less' : `Show more (${teams.length - TEAMS_PREVIEW})`,
        () => { _teamsAll = !_teamsAll; _render(); }));
    }
    row.appendChild(th);
    const grid = _el('div', 'agents-grid');
    (_teamsAll ? teams : teams.slice(0, TEAMS_PREVIEW)).forEach((t) => grid.appendChild(_teamCard(t)));
    row.appendChild(grid);
    body.appendChild(row);
  }

  // Search and chips
  const tools = _el('div', 'agents-tools');
  const search = document.createElement('input');
  search.type = 'search';
  search.className = 'agents-search';
  search.placeholder = `Search ${agents.length} agents…`;
  search.setAttribute('aria-label', 'Search the agents');
  search.value = _query;
  search.addEventListener('input', () => { _query = search.value; _renderCatalogue(); });
  tools.appendChild(search);
  body.appendChild(tools);
  const chips = _el('div', 'agents-chips');
  chips.setAttribute('role', 'tablist');
  chips.setAttribute('aria-label', 'Sections');
  const addChip = (id, label, count) => {
    const chip = _button('agents-chip', `${label} ${count}`, () => { _section = id; _render(); });
    chip.setAttribute('role', 'tab');
    chip.setAttribute('aria-selected', String(_section === id));
    chip.dataset.section = id;
    chips.appendChild(chip);
  };
  addChip('', 'All', agents.length);
  (_data.sections || []).filter((s) => s.count > 0).forEach((s) => addChip(s.id, s.label, s.count));
  body.appendChild(chips);

  const cat = _el('div', 'agents-catalogue');
  _win.catalogue = cat;
  body.appendChild(cat);
  _renderCatalogue();

  if ((_data.broken || []).length) {
    const broken = _el('details', 'agents-broken');
    broken.appendChild(_el('summary', '', `${_data.broken.length} agent file${_data.broken.length === 1 ? '' : 's'} could not be read`));
    _data.broken.forEach((b) => broken.appendChild(_el('p', '', `${b.folder}: ${b.sentence}`)));
    body.appendChild(broken);
  }
}

function _renderCatalogue() {
  const cat = _win && _win.catalogue;
  if (!cat) return;
  _clear(cat);
  // **Hired** on a card is this person's own hire, also in an admin's Everyone view.
  const hiredIds = new Set((_data.hires || []).filter((h) => h.owner === _data.me)
    .map((h) => h.agent_id));
  const left = filterAgents(_data.agents, _query, _section);
  const groups = groupBySection(_data.sections, left);
  if (!groups.length) {
    cat.appendChild(_el('p', 'agents-empty', 'No agent matches that. Try fewer words.'));
    return;
  }
  for (const g of groups) {
    const sec = _el('section', 'agents-section');
    sec.dataset.section = g.id;
    const head = _el('div', 'agents-section-head');
    const h = _el('h5', 'agents-h', g.label);
    h.appendChild(_el('span', 'agents-section-count', String(g.agents.length)));
    head.appendChild(h);
    const open = _expanded.has(g.id) || !!_query;
    if (g.agents.length > SECTION_PREVIEW && !_query) {
      head.appendChild(_button('agents-link', open ? 'Show less' : `Show more (${g.agents.length - SECTION_PREVIEW})`,
        () => { if (open) _expanded.delete(g.id); else _expanded.add(g.id); _renderCatalogue(); }));
    }
    sec.appendChild(head);
    const grid = _el('div', 'agents-grid');
    (open ? g.agents : g.agents.slice(0, SECTION_PREVIEW))
      .forEach((a) => grid.appendChild(_agentCard(a, hiredIds.has(a.id))));
    sec.appendChild(grid);
    cat.appendChild(sec);
  }
}

function _agentCard(a, hired) {
  const card = _button('agents-card', '', () => _openAgent(a.id));
  card.dataset.agent = a.id;
  card.setAttribute('aria-label', `${a.name}${hired ? ', hired' : ''}. ${a.tagline}`);
  const top = _el('div', 'agents-card-top');
  top.appendChild(_el('span', 'agents-avatar', _initial(a.name)));
  if (a.starred) top.appendChild(_el('span', 'agents-star', '★'));
  if (hired) top.appendChild(_el('span', 'agents-hired', 'Hired'));
  card.appendChild(top);
  card.appendChild(_el('span', 'agents-card-name', a.name));
  card.appendChild(_el('span', 'agents-card-tag', a.tagline));
  card.appendChild(_el('span', 'agents-card-when', a.starts_on));
  if (a.fit) card.appendChild(_fitBadge(a.fit));
  return card;
}

/** `P24-18`. What was measured on the model this person's hires run on —
 *  or that nothing was. Never a claim. */
function _fitBadge(fit) {
  const b = _el('span', `agents-fit agents-fit-${fit.badge}`, fit.words);
  if (fit.model) b.title = `Measured on ${fit.model}`;
  return b;
}

/** What a team card says it will do when pressed, in the board's words. */
export function teamAction(team) {
  const total = (team.members || []).length;
  if (team.hired >= total) return 'All hired';
  if (team.hired > 0) return `+${total - team.hired}`;
  return 'Hire all';
}

function _teamCard(t) {
  const card = _button('agents-card agents-team-card', '', () => { _view = { kind: 'team', team: t }; _say(''); _render(); });
  card.dataset.team = t.id;
  const top = _el('div', 'agents-card-top');
  const faces = _el('span', 'agents-faces');
  (t.members || []).slice(0, 3).forEach((m) => faces.appendChild(_el('span', 'agents-avatar agents-avatar-small', _initial(m.name))));
  if ((t.members || []).length > 3) faces.appendChild(_el('span', 'agents-more', `+${t.members.length - 3}`));
  top.appendChild(faces);
  card.appendChild(top);
  card.appendChild(_el('span', 'agents-card-name', t.name));
  card.appendChild(_el('span', 'agents-card-tag', t.tagline));
  const foot = _el('span', 'agents-card-when', `${(t.members || []).length} agents · `);
  foot.appendChild(_el('span', 'agents-team-action', teamAction(t)));
  card.appendChild(foot);
  return card;
}

function _projectField(value) {
  const projects = (_data && _data.projects) || [];
  if (!projects.length) return null;
  const row = _el('label', 'agents-field');
  row.appendChild(_el('span', 'agents-field-label', 'Project (optional)'));
  const sel = document.createElement('select');
  sel.className = 'agents-input';
  sel.dataset.project = '1';
  const none = document.createElement('option');
  none.value = '';
  none.textContent = 'None — your whole projects folder';
  sel.appendChild(none);
  projects.forEach((p) => {
    const o = document.createElement('option');
    o.value = p;
    o.textContent = p;
    sel.appendChild(o);
  });
  sel.value = value || '';
  row.appendChild(sel);
  return row;
}

function _readProject(form) {
  const sel = form.querySelector('[data-project]');
  return sel ? (sel.value || null) : undefined;
}

function _renderTeam(t) {
  const body = _win.body;
  body.appendChild(_back());
  const page = _el('article', 'agents-page');
  const head = _el('div', 'agents-page-head');
  const words = _el('div', 'agents-page-words');
  words.appendChild(_el('h3', 'agents-page-name', t.name));
  words.appendChild(_el('p', 'agents-page-tag', t.tagline));
  if (t.about) words.appendChild(_el('p', 'agents-page-meta', t.about));
  head.appendChild(words);
  page.appendChild(head);
  page.appendChild(_el('h5', 'agents-h', 'Its agents'));
  const list = _el('div', 'agents-grid');
  (t.members || []).forEach((m) => {
    const a = (_data.agents || []).find((x) => x.id === m.id);
    if (a) list.appendChild(_agentCard(a, m.hired));
  });
  page.appendChild(list);
  page.appendChild(_el('p', 'agents-small',
    'Hire all makes one hire per agent you have not hired, each with its own settings and reports. '
    + 'They do not hand work to each other.'));
  const left = (t.members || []).filter((m) => !m.hired).length;
  if (!left) {
    page.appendChild(_el('p', 'agents-empty', 'You have hired every agent in this team.'));
    body.appendChild(page);
    return;
  }
  const form = _el('form', 'agents-form');
  form.appendChild(_el('h5', 'agents-h', `Hire ${left === (t.members || []).length ? 'all' : `the other ${left}`}`));
  (t.inputs || []).forEach((spec) => form.appendChild(_inputField(spec)));
  const proj = _projectField();
  if (proj) form.appendChild(proj);
  const tz = _tz();
  if (tz) form.appendChild(_el('p', 'agents-small', `Times are in ${tz}.`));
  const go = _el('button', 'agents-primary', 'Hire all');
  go.type = 'submit';
  form.appendChild(go);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (_busy) return;
    _busy = true;
    go.disabled = true;
    const res = await Api.hireTeam(t.id, { inputs: readInputs(t.inputs, form), tz_name: tz || null,
      project: _readProject(form) || null });
    _busy = false;
    go.disabled = false;
    if (!_win) return;
    if (!res.ok) { _say(res.refusal.sentence, { error: true }); return; }
    await _load();
    const n = (res.data.hired || []).length;
    _say(`${t.name}: ${n} agent${n === 1 ? '' : 's'} hired.`);
    _view = { kind: 'hall' };
    _render();
  });
  page.appendChild(form);
  body.appendChild(page);
}

function _hireCard(h) {
  const card = _button('agents-card agents-hire-card', '', () => _openHire(h.id));
  card.dataset.hire = h.id;
  card.dataset.status = h.status;
  const top = _el('div', 'agents-card-top');
  top.appendChild(_el('span', 'agents-avatar', _initial(h.name)));
  top.appendChild(_el('span', `agents-status agents-status-${h.status}`, STATUS_WORDS[h.status] || h.status));
  card.appendChild(top);
  card.appendChild(_el('span', 'agents-card-name', h.name));
  if (_everyone && h.owner) card.appendChild(_el('span', 'agents-card-tag', h.owner));
  card.appendChild(_el('span', 'agents-card-when',
    h.status === 'attention' ? (h.attention || '') :
      h.next_run ? `Next: ${_when(h.next_run)}` : h.starts_on || ''));
  return card;
}

// ── an agent's page and the hire form ───────────────────────────────────────

async function _openAgent(agentId) {
  _say('');
  const res = await Api.getAgent(agentId);
  if (!_win) return;
  if (!res.ok) { _say(res.refusal.sentence, { error: true }); return; }
  _view = { kind: 'agent', agent: res.data };
  _render();
}

function _effectsList(effects) {
  const ul = _el('ul', 'agents-effects');
  Object.entries(effects || {}).forEach(([eff, rule]) => {
    const li = _el('li', `agents-effect agents-rule-${rule}`);
    li.appendChild(_el('span', 'agents-effect-what', EFFECT_WORDS[eff] || eff));
    li.appendChild(_el('span', 'agents-effect-rule', RULE_WORDS[rule] || rule));
    ul.appendChild(li);
  });
  return ul;
}

function _inputField(spec, value) {
  const row = _el('label', 'agents-field');
  row.appendChild(_el('span', 'agents-field-label', spec.label + (spec.optional ? ' (optional)' : '')));
  let field;
  const v = value !== undefined && value !== null ? value : spec.default;
  if (spec.kind === 'long_text') {
    field = document.createElement('textarea');
    field.rows = 4;
  } else if (spec.kind === 'list') {
    field = document.createElement('textarea');
    field.rows = 3;
    field.placeholder = 'One per line';
  } else if (spec.kind === 'choice') {
    field = document.createElement('select');
    (spec.choices || []).forEach((c) => {
      const o = document.createElement('option');
      o.value = c;
      o.textContent = c;
      field.appendChild(o);
    });
  } else if (spec.kind === 'boolean') {
    field = document.createElement('input');
    field.type = 'checkbox';
    field.checked = !!v;
  } else {
    field = document.createElement('input');
    field.type = spec.kind === 'number' ? 'number' : spec.kind === 'time' ? 'time'
      : spec.kind === 'url' ? 'url' : 'text';
    if (spec.kind === 'email_account') field.placeholder = 'The account as Mail names it';
    if (spec.kind === 'folder') field.placeholder = 'A folder in your projects folder';
  }
  field.className = 'agents-input';
  field.dataset.input = spec.key;
  if (spec.kind !== 'boolean' && v !== undefined && v !== null) {
    field.value = Array.isArray(v) ? v.join('\n') : String(v);
  }
  if (spec.help) field.title = spec.help;
  row.appendChild(field);
  return row;
}

function _renderAgent(a) {
  const body = _win.body;
  body.appendChild(_back());
  const page = _el('article', 'agents-page');
  const head = _el('div', 'agents-page-head');
  head.appendChild(_el('span', 'agents-avatar agents-avatar-big', _initial(a.name)));
  const words = _el('div', 'agents-page-words');
  const h = _el('h3', 'agents-page-name', a.name);
  if (a.starred) h.appendChild(_el('span', 'agents-star', ' ★'));
  words.appendChild(h);
  words.appendChild(_el('p', 'agents-page-tag', a.tagline));
  words.appendChild(_el('p', 'agents-page-meta',
    `${a.section_label} · starts on ${a.starts_on} · version ${a.version}${a.source === 'own' ? ' · your own' : ''}`));
  head.appendChild(words);
  page.appendChild(head);

  page.appendChild(_el('h5', 'agents-h', 'What it may do'));
  page.appendChild(_effectsList(a.effects));
  page.appendChild(_el('p', 'agents-small', `Tools: ${(a.tools || []).join(', ')}`));
  if ((a.lacking || []).length) {
    const lack = _el('div', 'agents-lacking');
    lack.appendChild(_el('p', '', `Your runs of it will not have ${a.lacking.length === 1 ? 'this tool' : 'these tools'}, so it may not finish every step:`));
    const ul = _el('ul');
    a.lacking.forEach((x) => ul.appendChild(_el('li', '', `${x.tool} — ${x.reason}`)));
    lack.appendChild(ul);
    page.appendChild(lack);
  }
  const rb = _el('details', 'agents-runbook');
  rb.appendChild(_el('summary', '', 'Read its runbook — every word the model is told'));
  rb.appendChild(_el('pre', 'agents-pre', a.runbook));
  page.appendChild(rb);

  // `P24-18` / `P24-17`. How it measures, and what a run leaves.
  if (a.fit) {
    const fitLine = _el('p', 'agents-small agents-fit-line');
    fitLine.appendChild(_fitBadge(a.fit));
    const row = a.fit.row;
    fitLine.appendChild(document.createTextNode(row
      ? ` on ${row.model}: ${Math.round((row.pass_rate || 0) * 100)}% of ${row.runs} runs passed, median ${row.median_minutes} min.`
      : (a.eval_cases ? ` on this model yet. Its ${a.eval_cases} evaluation cases run with a proof run.`
        : ' on this model yet.')));
    page.appendChild(fitLine);
  }
  if (a.sample) {
    const sd = _el('details', 'agents-sample');
    sd.appendChild(_el('summary', '', `A sample report (${a.sample.from})`));
    if ((a.sample.read || []).length) sd.appendChild(_el('p', 'agents-small', `Read with: ${a.sample.read.join(', ')}`));
    if ((a.sample.wrote || []).length) sd.appendChild(_el('p', 'agents-small', `Wrote with: ${a.sample.wrote.join(', ')}`));
    sd.appendChild(_el('pre', 'agents-pre', a.sample.answer || ''));
    page.appendChild(sd);
  }

  const form = _el('form', 'agents-form');
  form.appendChild(_el('h5', 'agents-h', `Hire ${a.name}`));
  (a.inputs || []).forEach((spec) => form.appendChild(_inputField(spec)));
  const proj = _projectField();
  if (proj) form.appendChild(proj);
  const tz = _tz();
  if (tz) form.appendChild(_el('p', 'agents-small', `Times are in ${tz}.`));
  const buttons = _el('div', 'agents-actions');
  const go = _el('button', 'agents-primary', 'Hire');
  go.type = 'submit';
  buttons.appendChild(go);
  // `P24-13`. Try it once: hired as a trial, run now, its schedule off until
  // the person chooses Hire.
  const tryBtn = _button('agents-btn agents-try', 'Try it once', async () => {
    if (_busy) return;
    _busy = true;
    tryBtn.disabled = true;
    const res = await Api.tryAgent(a.id, { inputs: readInputs(a.inputs, form), tz_name: tz || null,
      project: _readProject(form) || null });
    _busy = false;
    tryBtn.disabled = false;
    if (!_win) return;
    if (!res.ok) { _say(res.refusal.sentence, { error: true }); return; }
    await _load();
    _say(`Trying ${res.data.name} once. Its report appears below when it finishes; `
      + 'nothing runs on a schedule until you choose Hire.');
    _openHire(res.data.id, { keepNote: true });
  });
  buttons.appendChild(tryBtn);
  form.appendChild(buttons);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (_busy) return;
    _busy = true;
    go.disabled = true;
    const res = await Api.hireAgent(a.id, { inputs: readInputs(a.inputs, form), tz_name: tz || null,
      project: _readProject(form) || null });
    _busy = false;
    go.disabled = false;
    if (!_win) return;
    if (!res.ok) { _say(res.refusal.sentence, { error: true }); return; }
    await _load();
    _say(`${res.data.name} is hired. ${res.data.starts_on ? `It starts on ${res.data.starts_on}.` : ''}`);
    _openHire(res.data.id, { keepNote: true });
  });
  page.appendChild(form);
  body.appendChild(page);
}

// ── a hire's page ───────────────────────────────────────────────────────────

function _waitingRow(q) {
  const row = _el('div', 'agents-question');
  const card = q.approval || {};
  const action = card.action || {};
  row.appendChild(_el('p', 'agents-question-what',
    `It wants to use ${q.tool_label || action.tool || q.label || 'a tool'}.`));
  if (card.description) row.appendChild(_el('p', 'agents-small', card.description));
  if (action.display || action.content) {
    row.appendChild(_el('pre', 'agents-pre', String(action.display || action.content).slice(0, 2000)));
  }
  if (!card.approval_id) {
    row.appendChild(_el('p', 'agents-small', 'This question cannot be answered any more; the run will end.'));
    return row;
  }
  const bar = _el('div', 'agents-actions');
  const answer = (decision) => _act(() => Api.answer(q.task_id, q.run_id, card.approval_id, decision),
    { sentence: (d) => (d && d.sentence) || (decision === 'deny' ? 'Denied.' : 'Allowed once.') });
  bar.appendChild(_button('agents-primary', 'Allow once', () => answer('approve_task')));
  bar.appendChild(_button('agents-btn', 'Deny', () => answer('deny')));
  row.appendChild(bar);
  return row;
}

/** How often a hire's page asks again while one of its runs is going. */
export const RUN_POLL_MS = 3000;
let _pollTimer = null;

function _stopPoll() { if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null; } }

async function _openHire(hireId, { keepNote = false } = {}) {
  if (!keepNote) _say('');
  _stopPoll();
  const res = await Api.getHire(hireId);
  if (!_win) return;
  if (!res.ok) { _say(res.refusal.sentence, { error: true }); return; }
  // `P24-14`. The questions its runs wait on, from the task engine's own list
  // (`GET /api/tasks/waiting`), answered in place.
  const ids = new Set((res.data.tasks || []).map((t) => t.id));
  const waiting = await Api.waiting();
  if (!_win) return;
  res.data.waiting = waiting.ok ? ((waiting.data && waiting.data.waiting) || [])
    .filter((q) => ids.has(q.task_id)) : [];
  _view = { kind: 'hire', hire: res.data };
  _render();
  const going = (res.data.runs || []).some((r) => r.status === 'running' || r.status === 'queued')
    || (res.data.status === 'trial' && !(res.data.runs || []).length);
  if (going) {
    _pollTimer = setTimeout(() => {
      _pollTimer = null;
      if (_win && _view.kind === 'hire' && _view.hire.id === hireId) _openHire(hireId, { keepNote: true });
    }, RUN_POLL_MS);
  }
}

async function _act(fn, { reload = true, sentence } = {}) {
  if (_busy) return;
  _busy = true;
  const res = await fn();
  _busy = false;
  if (!_win) return;
  if (!res.ok) { _say(res.refusal.sentence, { error: true }); return; }
  if (sentence) _say(typeof sentence === 'function' ? sentence(res.data) : sentence);
  await _load();
  if (reload && _view.kind === 'hire') await _openHire(_view.hire.id, { keepNote: true });
  else _render();
}

function _runRow(run) {
  const row = _el('details', `agents-run agents-run-${run.status}`);
  const sum = _el('summary', 'agents-run-head');
  sum.appendChild(_el('span', 'agents-run-status', RUN_WORDS[run.status] || run.status));
  sum.appendChild(_el('span', 'agents-run-when', _when(run.started_at)));
  if (run.report && run.report.summary) {
    sum.appendChild(_el('span', 'agents-run-line', run.report.summary.split('\n')[0].replace(/^[-*]\s*/, '')));
  } else if (run.error || run.said) {
    sum.appendChild(_el('span', 'agents-run-line', run.error || run.said));
  }
  row.appendChild(sum);
  const r = run.report;
  if (r) {
    if (r.read && r.read.length) row.appendChild(_el('p', 'agents-small', `Read with: ${r.read.join(', ')}`));
    if (r.wrote && r.wrote.length) row.appendChild(_el('p', 'agents-small', `Wrote with: ${r.wrote.join(', ')}`));
    (r.refused || []).forEach((x) => row.appendChild(_el('p', 'agents-small agents-refused',
      `Refused ${x.tool}: ${x.reason}`)));
    if ((r.checks || []).length) {
      // `P24-09`. What it had to leave behind, checked by code.
      const ul = _el('ul', 'agents-checks');
      r.checks.forEach((c) => ul.appendChild(_el('li', c.ok ? 'agents-check-ok' : 'agents-check-failed',
        `${c.ok ? '✓' : '✗'} ${c.detail}`)));
      row.appendChild(ul);
      if (r.repaired) row.appendChild(_el('p', 'agents-small', 'It took one more try to deliver.'));
    }
    row.appendChild(_el('pre', 'agents-pre', r.answer || ''));
  } else if (run.error || run.said) {
    row.appendChild(_el('p', 'agents-small', run.error || run.said));
  } else {
    row.appendChild(_el('p', 'agents-small', 'No report: the run has not finished, or it left none.'));
  }
  return row;
}

function _renderHire(h) {
  const body = _win.body;
  body.appendChild(_back());
  const page = _el('article', 'agents-page');
  const head = _el('div', 'agents-page-head');
  head.appendChild(_el('span', 'agents-avatar agents-avatar-big', _initial(h.name)));
  const words = _el('div', 'agents-page-words');
  const name = _el('h3', 'agents-page-name', h.name);
  name.appendChild(_el('span', `agents-status agents-status-${h.status}`, STATUS_WORDS[h.status] || h.status));
  words.appendChild(name);
  words.appendChild(_el('p', 'agents-page-meta',
    [h.starts_on && `Starts on ${h.starts_on}`, h.next_run && `next ${_when(h.next_run)}`,
      `version ${h.version}`, h.owner && _everyone ? `hired by ${h.owner}` : '']
      .filter(Boolean).join(' · ')));
  head.appendChild(words);
  page.appendChild(head);
  if (h.attention) page.appendChild(_el('p', 'agents-attention', h.attention));
  if (h.missing) page.appendChild(_el('p', 'agents-attention', "This agent's file is gone or broken. Fire the hire, or put the file back."));

  const bar = _el('div', 'agents-actions');
  const firstTask = (h.tasks || [])[0];
  // A paused hire's task does not run (the engine records it skipped), so
  // *Run now* is offered only where it would run.
  if (firstTask && !h.missing && (h.status === 'on' || h.status === 'trial')) {
    bar.appendChild(_button('agents-primary', 'Run now', () => _act(() => Api.runNow(firstTask.id),
      { sentence: `${h.name} is running. Its report appears below when it finishes.` })));
  }
  if (h.status === 'trial') {
    bar.appendChild(_button('agents-btn', 'Hire', () => _act(() => Api.setHireStatus(h.id, 'on'),
      { sentence: `${h.name} is hired. ${h.starts_on ? `It starts on ${h.starts_on}.` : ''}` })));
  }
  if (h.update_to) {
    bar.appendChild(_button('agents-btn', `Update to ${h.update_to}`, () => _act(
      () => Api.changeHire(h.id, { update: true }), { sentence: `Updated to ${h.update_to}.` })));
  }
  if (h.status === 'trial') {
    // Hire is above; a trial is neither on nor paused.
  } else if (h.status === 'on') {
    bar.appendChild(_button('agents-btn', 'Pause', () => _act(() => Api.setHireStatus(h.id, 'paused'),
      { sentence: `${h.name} is paused. Nothing runs until you switch it back on.` })));
  } else if (!h.missing) {
    bar.appendChild(_button('agents-btn', 'Switch on', () => _act(() => Api.setHireStatus(h.id, 'on'),
      { sentence: `${h.name} is on.` })));
  }
  const trial = h.status === 'trial';
  bar.appendChild(_button('agents-btn agents-danger', trial ? 'Discard…' : 'Fire…', async () => {
    // The app's own question (`ui.js`'s default export, as `workstation.js`
    // asks it); a page where it cannot load asks nothing and fires nothing.
    let ok = false;
    try {
      const uiMod = await import('../ui.js');
      const ui = uiMod.default || uiMod;
      ok = await ui.styledConfirm(trial
        ? `Discard the trial of ${h.name}? Its run and report go with it.`
        : `Fire ${h.name}? Its tasks, runs and reports go with it.`,
      { title: trial ? 'Discard this trial' : 'Fire this agent', confirmText: trial ? 'Discard' : 'Fire',
        danger: true });
    } catch (_) { ok = false; }
    if (ok !== true) return;
    const res = await Api.fireHire(h.id);
    if (!_win) return;
    if (!res.ok) { _say(res.refusal.sentence, { error: true }); return; }
    _say(trial ? `The trial of ${res.data.fired} is discarded.`
      : `${res.data.fired} is fired; ${res.data.tasks_removed} task${res.data.tasks_removed === 1 ? '' : 's'} removed.`);
    await _load();
    _view = { kind: 'hall' };
    _render();
  }));
  page.appendChild(bar);

  if ((h.waiting || []).length) {
    const box = _el('section', 'agents-waiting');
    box.appendChild(_el('h5', 'agents-h', 'Waiting for you'));
    h.waiting.forEach((q) => box.appendChild(_waitingRow(q)));
    page.appendChild(box);
  }

  const hooks = (h.tasks || []).filter((t) => t.trigger_type === 'webhook' && t.webhook_token);
  if (hooks.length) {
    const url = `${location.origin}/api/tasks/${hooks[0].id}/webhook/${hooks[0].webhook_token}`;
    const p = _el('p', 'agents-small', 'Starts when something POSTs to: ');
    p.appendChild(_el('code', 'agents-code', url));
    page.appendChild(p);
  }

  if (h.effects) {
    page.appendChild(_el('h5', 'agents-h', 'What it may do'));
    page.appendChild(_effectsList(h.effects));
  }
  if ((h.lacking || []).length) {
    page.appendChild(_el('p', 'agents-small agents-refused',
      `Its runs lack: ${h.lacking.map((x) => x.tool).join(', ')}.`));
  }

  const ownProjects = (_data && _data.projects) || [];
  if (h.agent && ((h.agent.inputs || []).length || ownProjects.length) && !_everyone && h.owner === _data.me) {
    const form = _el('details', 'agents-settings');
    form.appendChild(_el('summary', '', 'Settings'));
    const f = _el('form', 'agents-form');
    (h.agent.inputs || []).forEach((spec) => f.appendChild(_inputField(spec, (h.inputs || {})[spec.key])));
    const proj = _projectField(h.project);
    if (proj) f.appendChild(proj);
    const save = _el('button', 'agents-btn', 'Save');
    save.type = 'submit';
    f.appendChild(save);
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      const change = { inputs: readInputs(h.agent.inputs, f) };
      const project = _readProject(f);
      if (project !== undefined) change.project = project;
      _act(() => Api.changeHire(h.id, change), { sentence: 'Saved.' });
    });
    form.appendChild(f);
    page.appendChild(form);
  }

  if (h.notebook) {
    const nb = _el('details', 'agents-notebook');
    nb.appendChild(_el('summary', '', 'Its notebook — what it carries to the next run'));
    nb.appendChild(_el('pre', 'agents-pre', h.notebook));
    page.appendChild(nb);
  }

  page.appendChild(_el('h5', 'agents-h', 'Runs'));
  const runs = h.runs || [];
  if (!runs.length) page.appendChild(_el('p', 'agents-empty', 'No runs yet.'));
  runs.forEach((r) => page.appendChild(_runRow(r)));
  body.appendChild(page);
}

// ── open, close ─────────────────────────────────────────────────────────────

function _teardown() {
  _stopPoll();
  if (!_win) return;
  const modal = _win.modal;
  _win = null;
  _view = { kind: 'hall' };
  _busy = false;
  if (modal.parentNode) modal.parentNode.removeChild(modal);
}

async function _refresh() {
  if (!_win) return;
  if (await _load()) {
    if (_view.kind === 'hire') await _openHire(_view.hire.id, { keepNote: true });
    else _render();
  }
}

/** Open the hall, or bring it forward: restored from the dock when minimized,
 *  raised when already open, built when closed. `agent` opens on one agent's
 *  page, `hire` on one hire's. */
export async function openAgents({ agent, hire } = {}) {
  if (_win && Modals.isRegistered(MODAL_ID)) {
    if (Modals.isMinimized(MODAL_ID)) Modals.restore(MODAL_ID);
    else Modals.showWindow(MODAL_ID);
  } else {
    if (_win) _teardown();
    _win = _build();
    document.body.appendChild(_win.modal);
    Modals.register(MODAL_ID, { restoreFn: _refresh, closeFn: _teardown });
    Modals.injectMinimizeButton(_win.modal, MODAL_ID);
    makeWindowDraggable(_win.modal, {
      content: _win.content, header: _win.header,
      skipSelector: 'button, input, select, textarea, label, summary', minWidth: 360, minHeight: 320,
    });
    _render();
    await _load();
  }
  if (agent) await _openAgent(agent);
  else if (hire) await _openHire(hire);
  else _render();
  return true;
}

export function closeAgents() {
  if (Modals.isRegistered(MODAL_ID)) Modals.close(MODAL_ID);
  else _teardown();
}

export function isAgentsOpen() { return !!_win; }

export const _test = {
  win: () => _win,
  state: () => ({ view: _view.kind, query: _query, section: _section, everyone: _everyone,
    data: _data }),
  openAgent: _openAgent,
  openHire: _openHire,
  stopPoll: () => _stopPoll(),
  reset: () => { _query = ''; _section = ''; _expanded = new Set(); _stripAll = false; _everyone = false; },
};

export default { openAgents, closeAgents, isAgentsOpen, MODAL_ID };
