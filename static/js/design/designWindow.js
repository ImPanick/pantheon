// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P26-04` / `P26-05`. The Design window: *What will you design?* — starting
// points as cards, each a short brief or *describe it in the chat* — and the
// person's design systems: palette, type, spacing, radii and a sentence of
// voice, extracted by the model from what they paste or upload, corrected by
// them as swatches, and kept (`routes/design_routes.py`).
//
// The owner's reference (PandaOS): a Design window beside the chat, *What will
// you design?*, cards for Document, Mockup, Prototype, Motion…, and a Design
// systems page — a name, Project or Global, a box to paste into, *Extract from
// text*, *Upload a file*, and the saved list.
//
// Every value from the server is text (`textContent`, `value`); colours are
// checked hex before they are painted. Markup is built with `createElement`.

import * as Modals from '../modalManager.js?v=20261009census';
import { makeWindowDraggable } from '../windowDrag.js';
import workspaceModule from '../workspace.js';
import { STARTS, briefMessage } from './starts.js';

export const MODAL_ID = 'design-modal';
const HEX = /^#[0-9a-f]{6}$/i;
const ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
  + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="13.5" cy="6.5" r="1"/>'
  + '<circle cx="17.5" cy="10.5" r="1"/><circle cx="8.5" cy="7.5" r="1"/><circle cx="6.5" cy="12.5" r="1"/>'
  + '<path d="M12 2a10 10 0 0 0 0 20c.9 0 1.6-.7 1.6-1.6 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1 0-.9.7-1.6 '
  + '1.6-1.6H16a6 6 0 0 0 6-6c0-5-4.5-8.6-10-8.6z"/></svg>';

let _win = null;
let _view = { kind: 'home' };
let _systems = [];
let _roles = [];

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function _btn(cls, text, onClick, label) {
  const b = _el('button', cls, text);
  b.type = 'button';
  if (label) { b.title = label; b.setAttribute('aria-label', label); }
  b.addEventListener('click', (e) => { e.preventDefault(); onClick(e); });
  return b;
}

function _svg(path) {
  const ns = 'http://www.w3.org/2000/svg';
  const s = document.createElementNS(ns, 'svg');
  ['width', 'height'].forEach((k) => s.setAttribute(k, '22'));
  s.setAttribute('viewBox', '0 0 24 24');
  s.setAttribute('fill', 'none');
  s.setAttribute('stroke', 'currentColor');
  s.setAttribute('stroke-width', '1.8');
  s.setAttribute('stroke-linecap', 'round');
  s.setAttribute('stroke-linejoin', 'round');
  s.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS(ns, 'path');
  p.setAttribute('d', path);
  s.appendChild(p);
  return s;
}

function _say(text, { error = false } = {}) {
  if (!_win) return;
  _win.note.textContent = text || '';
  _win.note.hidden = !text;
  _win.note.classList.toggle('design-note-error', !!error);
}

async function _call(method, url, body) {
  let res;
  try {
    res = await fetch(url, {
      method, credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (_) {
    return { ok: false, status: 0, sentence: "Pantheon's server did not answer." };
  }
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) return { ok: false, status: res.status, sentence: (data && data.detail) || 'That was not done.' };
  return { ok: true, data };
}

function _project() {
  try { return workspaceModule.getWorkspace() || ''; } catch (_) { return ''; }
}

function _projectName() {
  const p = _project();
  return p ? p.replace(/\/+$/, '').split('/').pop() : '';
}

async function _loadSystems() {
  const q = _project() ? `?project=${encodeURIComponent(_project())}` : '';
  const r = await _call('GET', `/api/design/systems${q}`);
  if (r.ok) { _systems = r.data.systems || []; _roles = r.data.roles || []; }
  else _say(r.sentence, { error: true });
}

// ── the home: starting points and design systems ─────────────────────────────

function _swatches(tokens, n = 8) {
  const row = _el('div', 'design-swatches');
  ((tokens && tokens.palette) || []).slice(0, n).forEach((c) => {
    const s = _el('span', 'design-swatch');
    if (HEX.test(c.value)) s.style.background = c.value;
    s.title = `${c.name} ${c.value}`;
    row.appendChild(s);
  });
  return row;
}

function _renderHome() {
  const body = _win.body;
  const hero = _el('div', 'design-hero');
  hero.appendChild(_el('h2', 'design-hero-title', 'What will you design?'));
  hero.appendChild(_el('p', 'design-hero-sub', 'Pick a starting point, or just describe it in the chat.'));
  body.appendChild(hero);
  const grid = _el('div', 'design-starts');
  STARTS.forEach((s) => {
    const card = _btn('design-start', '', () => { _say(''); _view = { kind: 'brief', start: s.id }; _render(); }, `${s.label}: ${s.hint}`);
    card.dataset.start = s.id;
    const art = _el('span', 'design-start-art');
    art.appendChild(_svg(s.icon));
    card.appendChild(art);
    card.appendChild(_el('span', 'design-start-label', s.label));
    card.appendChild(_el('span', 'design-start-hint', s.hint));
    grid.appendChild(card);
  });
  body.appendChild(grid);

  const head = _el('div', 'design-section-head');
  head.appendChild(_el('h3', 'design-section-title', 'Design systems'));
  head.appendChild(_btn('design-btn', '+ New design system', () => { _say(''); _view = { kind: 'system' }; _render(); }));
  body.appendChild(head);
  body.appendChild(_el('p', 'design-section-sub', 'Palette, type and voice — reusable by you and the agent.'));
  if (!_systems.length) {
    body.appendChild(_el('p', 'design-empty', 'No design systems yet. Make one from a style guide, your CSS or brand notes, '
      + 'and every design here can use it.'));
  }
  const list = _el('div', 'design-systems');
  _systems.forEach((sys) => {
    const card = _btn('design-system-card', '', () => { _say(''); _view = { kind: 'system', id: sys.id }; _render(); }, `Open ${sys.name}`);
    card.appendChild(_el('span', 'design-system-name', sys.name));
    card.appendChild(_el('span', 'design-chip', sys.scope === 'project' ? 'Project' : 'Personal'));
    card.appendChild(_swatches(sys.tokens));
    if ((sys.warnings || []).length) card.appendChild(_el('span', 'design-system-warn', 'low contrast'));
    list.appendChild(card);
  });
  body.appendChild(list);
}

// ── a brief ──────────────────────────────────────────────────────────────────

function _field(label, input) {
  const l = _el('label', 'design-field');
  l.appendChild(_el('span', '', label));
  l.appendChild(input);
  return l;
}

function _input(placeholder, multiline = false) {
  const i = document.createElement(multiline ? 'textarea' : 'input');
  if (!multiline) i.type = 'text';
  else i.rows = 3;
  i.placeholder = placeholder || '';
  return i;
}

/** Write `text` into the composer and send it. */
function _sendToChat(text) {
  const box = document.getElementById('message');
  if (!box) { _say('There is no chat to send the brief to.', { error: true }); return false; }
  box.value = text;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  const send = document.querySelector('.send-btn');
  if (send) send.click();
  return true;
}

function _renderBrief(startId) {
  const start = STARTS.find((s) => s.id === startId) || STARTS[0];
  const body = _win.body;
  body.appendChild(_btn('design-back', '← What will you design?', () => { _say(''); _view = { kind: 'home' }; _render(); }));
  body.appendChild(_el('h2', 'design-page-title', start.label));
  body.appendChild(_el('p', 'design-section-sub', `${start.hint}. A short brief, then the agent makes it in your workspace.`));
  const form = _el('form', 'design-brief');
  const who = _input('Who will read or use it?');
  const what = _input('What it shows — the sections, screens or story', true);
  form.appendChild(_field('Who it is for', who));
  form.appendChild(_field('What it shows', what));
  const extra = {};
  (start.asks || []).forEach((q) => { extra[q.key] = _input(q.placeholder); form.appendChild(_field(q.label, extra[q.key])); });
  const sys = document.createElement('select');
  const none = document.createElement('option');
  none.value = '';
  none.textContent = _systems.length ? 'No design system' : 'No design systems yet';
  sys.appendChild(none);
  _systems.forEach((s) => { const o = document.createElement('option'); o.value = s.id; o.textContent = s.name; sys.appendChild(o); });
  if (_systems.length) sys.value = _systems[0].id;
  form.appendChild(_field('Design system', sys));
  const go = _el('button', 'design-btn design-btn-primary', 'Start designing');
  go.type = 'submit';
  form.appendChild(go);
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const answers = { who: who.value.trim(), what: what.value.trim() };
    Object.entries(extra).forEach(([k, i]) => { answers[k] = i.value.trim(); });
    if (!answers.what) { _say('Say what it shows — a sentence is enough.', { error: true }); what.focus(); return; }
    const system = _systems.find((s) => s.id === sys.value) || null;
    if (_sendToChat(briefMessage(start, answers, system))) {
      _say(`Sent to the chat. The agent makes the ${start.label.toLowerCase()} in ${_projectName() || 'your workspace'}.`);
      _view = { kind: 'home' };
      _render();
    }
  });
  body.appendChild(form);
  who.focus();
}

// ── a design system: make, correct, keep ────────────────────────────────────

function _readFile(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result || '').split(',', 2)[1] || '');
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

function _nums(text) {
  return String(text || '').split(/[\s,]+/).map((x) => parseFloat(x)).filter((x) => Number.isFinite(x));
}

function _renderSystem(id) {
  const existing = _systems.find((s) => s.id === id) || null;
  let tokens = existing ? JSON.parse(JSON.stringify(existing.tokens)) : null;
  const body = _win.body;
  body.appendChild(_btn('design-back', '← Design', () => { _say(''); _view = { kind: 'home' }; _render(); }));
  body.appendChild(_el('h2', 'design-page-title', existing ? existing.name : 'New design system'));
  body.appendChild(_el('p', 'design-section-sub', 'Palette, type and voice. Reusable by you and the agent.'));

  const top = _el('div', 'design-system-top');
  const name = _input('Name (e.g. Acme Brand)');
  name.className = 'design-name';
  name.value = existing ? existing.name : '';
  name.setAttribute('aria-label', 'Name');
  top.appendChild(name);
  const scope = _el('div', 'design-scope');
  scope.setAttribute('role', 'radiogroup');
  scope.setAttribute('aria-label', 'Where it belongs');
  let scopeNow = existing ? existing.scope : (_project() ? 'project' : 'personal');
  const scopeBtn = (value, label, hint) => {
    const b = _btn('design-scope-btn', label, () => { scopeNow = value; sync(); }, hint);
    b.setAttribute('role', 'radio');
    b.dataset.scope = value;
    return b;
  };
  const projBtn = scopeBtn('project', 'Project', `Kept in ${_projectName() || 'the workspace'} as a file the agent reads`);
  const persBtn = scopeBtn('personal', 'Personal', 'Yours, in every project');
  if (!_project()) { projBtn.disabled = true; projBtn.title = 'Pick a workspace first to keep it in a project'; }
  scope.appendChild(projBtn);
  scope.appendChild(persBtn);
  const sync = () => [projBtn, persBtn].forEach((b) => b.setAttribute('aria-checked', String(b.dataset.scope === scopeNow)));
  sync();
  top.appendChild(scope);
  body.appendChild(top);

  // Extract.
  const source = _el('div', 'design-source');
  const text = _input('Paste a style guide, brand notes, CSS, or a tokens export — or choose a PDF, PPTX or CSS file.', true);
  text.rows = 5;
  text.setAttribute('aria-label', 'Material to read');
  source.appendChild(text);
  const file = document.createElement('input');
  file.type = 'file';
  file.accept = '.css,.scss,.less,.json,.txt,.md,.svg,.html,.yaml,.yml,.toml,.pdf,.pptx,.docx';
  file.hidden = true;
  const acts = _el('div', 'design-source-acts');
  const extractBtn = _btn('design-btn design-btn-primary', 'Extract from text', () => extract({ text: text.value }));
  const upload = _btn('design-btn', 'Upload a file', () => file.click());
  file.addEventListener('change', async () => {
    const f = file.files && file.files[0];
    if (!f) return;
    try { await extract({ text: text.value, file: { name: f.name, data_b64: await _readFile(f) } }); } finally { file.value = ''; }
  });
  acts.appendChild(extractBtn);
  acts.appendChild(upload);
  source.appendChild(acts);
  source.appendChild(file);
  body.appendChild(source);

  const editor = _el('div', 'design-tokens');
  body.appendChild(editor);
  const foot = _el('div', 'design-system-foot');
  body.appendChild(foot);

  async function extract(payload) {
    if (!String(payload.text || '').trim() && !payload.file) { _say('Paste something to read, or choose a file.', { error: true }); return; }
    extractBtn.disabled = true;
    upload.disabled = true;
    _say('Reading it…');
    const r = await _call('POST', '/api/design/systems/extract', payload);
    extractBtn.disabled = false;
    upload.disabled = false;
    if (!r.ok) { _say(r.sentence, { error: true }); return; }
    tokens = r.data.tokens;
    _say('Here is what it read. Correct anything, then save.');
    drawTokens();
  }

  function drawTokens() {
    editor.textContent = '';
    foot.textContent = '';
    if (!tokens) {
      editor.appendChild(_el('p', 'design-empty', 'Nothing read yet. What it finds appears here as swatches to correct.'));
      return;
    }
    editor.appendChild(_el('h3', 'design-section-title', 'Palette'));
    const pal = _el('div', 'design-palette');
    tokens.palette.forEach((c, i) => {
      const row = _el('div', 'design-colour');
      const pick = document.createElement('input');
      pick.type = 'color';
      pick.value = HEX.test(c.value) ? c.value : '#000000';
      pick.setAttribute('aria-label', `${c.name} colour`);
      const hex = _input('#000000');
      hex.value = c.value;
      hex.className = 'design-hex';
      hex.setAttribute('aria-label', `${c.name} value`);
      pick.addEventListener('input', () => { c.value = pick.value; hex.value = pick.value; });
      hex.addEventListener('change', () => { if (HEX.test(hex.value.trim())) { c.value = hex.value.trim().toLowerCase(); pick.value = c.value; } });
      const nm = _input('name');
      nm.value = c.name;
      nm.setAttribute('aria-label', 'Colour name');
      nm.addEventListener('change', () => { c.name = nm.value.trim() || c.name; });
      const role = document.createElement('select');
      role.setAttribute('aria-label', `${c.name} role`);
      (_roles.length ? _roles : ['background', 'text', 'accent', 'other']).forEach((r) => {
        const o = document.createElement('option'); o.value = r; o.textContent = r; role.appendChild(o);
      });
      role.value = c.role;
      role.addEventListener('change', () => { c.role = role.value; });
      row.appendChild(pick);
      row.appendChild(hex);
      row.appendChild(nm);
      row.appendChild(role);
      row.appendChild(_btn('design-x', '×', () => { tokens.palette.splice(i, 1); drawTokens(); }, `Remove ${c.name}`));
      pal.appendChild(row);
    });
    pal.appendChild(_btn('design-btn', '+ Colour', () => { tokens.palette.push({ name: `colour ${tokens.palette.length + 1}`, value: '#888888', role: 'other' }); drawTokens(); }));
    editor.appendChild(pal);
    editor.appendChild(_el('h3', 'design-section-title', 'Type, spacing and voice'));
    const grid = _el('div', 'design-type');
    const t = tokens.type || (tokens.type = {});
    [['heading', 'Headings'], ['body', 'Body'], ['mono', 'Code']].forEach(([k, label]) => {
      const i = _input('A font family');
      i.value = t[k] || '';
      i.addEventListener('change', () => { t[k] = i.value.trim(); });
      grid.appendChild(_field(label, i));
    });
    [['scale', 'Type sizes (px)', t], ['spacing', 'Spacing (px)', tokens], ['radii', 'Corners (px)', tokens]].forEach(([k, label, obj]) => {
      const i = _input('4, 8, 16');
      i.value = (obj[k] || []).join(', ');
      i.addEventListener('change', () => { obj[k] = _nums(i.value); });
      grid.appendChild(_field(label, i));
    });
    const voice = _input('One sentence on the tone', true);
    voice.rows = 2;
    voice.value = tokens.voice || '';
    voice.addEventListener('change', () => { tokens.voice = voice.value.trim(); });
    grid.appendChild(_field('Voice', voice));
    editor.appendChild(grid);
    // A preview: the tokens on a small card.
    const bg = tokens.palette.find((c) => c.role === 'background');
    const fg = tokens.palette.find((c) => c.role === 'text');
    const ac = tokens.palette.find((c) => c.role === 'accent' || c.role === 'primary');
    const prev = _el('div', 'design-preview');
    if (bg && HEX.test(bg.value)) prev.style.background = bg.value;
    if (fg && HEX.test(fg.value)) prev.style.color = fg.value;
    const ph = _el('div', 'design-preview-h', 'A heading in this system');
    if (t.heading) ph.style.fontFamily = t.heading;
    const pb = _el('div', 'design-preview-b', tokens.voice || 'Body text reads like this, at the size and colour the tokens give it.');
    if (t.body) pb.style.fontFamily = t.body;
    const pa = _el('span', 'design-preview-a', 'Action');
    if (ac && HEX.test(ac.value)) { pa.style.background = ac.value; pa.style.color = bg && HEX.test(bg.value) ? bg.value : '#ffffff'; }
    prev.appendChild(ph);
    prev.appendChild(pb);
    prev.appendChild(pa);
    editor.appendChild(prev);

    const save = _btn('design-btn design-btn-primary', existing ? 'Save changes' : 'Save', () => doSave(false));
    foot.appendChild(save);
    if (existing) {
      foot.appendChild(_btn('design-btn design-danger', 'Remove', async () => {
        const r = await _call('DELETE', `/api/design/systems/${encodeURIComponent(existing.id)}`);
        if (!r.ok) { _say(r.sentence, { error: true }); return; }
        _say(`Removed “${existing.name}”.`);
        await _loadSystems();
        _view = { kind: 'home' };
        _render();
      }));
    }
  }

  async function doSave(accept) {
    const payload = { name: name.value, scope: scopeNow, tokens, project: _project() || null };
    if (accept) payload.accept_low_contrast = true;
    const r = existing
      ? await _call('PUT', `/api/design/systems/${encodeURIComponent(existing.id)}`, payload)
      : await _call('POST', '/api/design/systems', payload);
    if (!r.ok) {
      _say(r.sentence, { error: true });
      if (r.status === 422) {
        foot.querySelector('.design-accept')?.remove();
        foot.appendChild(_btn('design-btn design-accept', 'Save anyway', () => doSave(true)));
      }
      return;
    }
    _say(`Saved “${r.data.name}”.${r.data.write_note ? ` ${r.data.write_note}` : ''}`);
    await _loadSystems();
    _view = { kind: 'system', id: r.data.id };
    _render();
  }

  drawTokens();
  if (!existing) name.focus();
}

// ── the window ───────────────────────────────────────────────────────────────

function _build() {
  const modal = _el('div', 'modal design-modal');
  modal.id = MODAL_ID;
  const content = _el('div', 'modal-content design-content');
  content.setAttribute('role', 'dialog');
  content.setAttribute('aria-label', 'Design');
  const header = _el('div', 'modal-header');
  const title = _el('h4', 'design-title');
  const icon = _el('span', 'design-title-icon');
  icon.innerHTML = ICON;   // a constant above, never server text
  title.appendChild(icon);
  title.appendChild(document.createTextNode('Design'));
  const where = _el('span', 'design-where', '');
  title.appendChild(where);
  const close = _el('button', 'close-btn');
  close.type = 'button';
  close.title = 'Close';
  close.setAttribute('aria-label', 'Close');
  close.textContent = '✖';
  close.addEventListener('click', (e) => { e.preventDefault(); closeDesign(); });
  header.appendChild(title);
  header.appendChild(close);
  const note = _el('p', 'design-note');
  note.setAttribute('role', 'status');
  note.setAttribute('aria-live', 'polite');
  note.hidden = true;
  const body = _el('div', 'modal-body design-body');
  content.appendChild(header);
  content.appendChild(note);
  content.appendChild(body);
  modal.appendChild(content);
  return { modal, content, header, note, body, where };
}

function _render() {
  if (!_win) return;
  _win.where.textContent = _projectName();
  _win.body.textContent = '';
  if (_view.kind === 'brief') _renderBrief(_view.start);
  else if (_view.kind === 'system') _renderSystem(_view.id);
  else _renderHome();
}

function _teardown() {
  if (!_win) return;
  const m = _win.modal;
  _win = null;
  _view = { kind: 'home' };
  if (m.parentNode) m.parentNode.removeChild(m);
}

async function _refresh() {
  await _loadSystems();
  _render();
}

/** Open the window, or bring it forward. `start` opens on that starting
 *  point's brief, `system: 'new'` on a new design system. */
export async function openDesign({ start, system } = {}) {
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
      skipSelector: 'button, input, select, textarea, label', minWidth: 360, minHeight: 320,
    });
  }
  _view = start ? { kind: 'brief', start } : (system === 'new' ? { kind: 'system' } : { kind: 'home' });
  await _loadSystems();
  _render();
  return true;
}

export function closeDesign() {
  if (Modals.isRegistered(MODAL_ID)) Modals.close(MODAL_ID);
  else _teardown();
}

export const _test = { win: () => _win, view: () => ({ ..._view }), systems: () => _systems };

export default { openDesign, closeDesign };
