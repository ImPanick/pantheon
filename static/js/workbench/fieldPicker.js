// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/fieldPicker.js
//
// `P22-09` (wf-canvas). Data between steps: pick a field from a list
// (`D-2026-10-01-05` §2 — picked fields, not code; design
// `/work/notes/SLICE-CD-DESIGN.md` § 1.1, § 2's P22-09).
//
// A step reads what an earlier step made through a reference,
// `{{ steps.<id>.data.<path> }}`. A person never types one: beside a field
// that may take one, **Insert a field…** opens a list of the earlier steps and
// the fields each has made — from the last run, from a pinned sample, or what
// the step promises to answer — each with an example and where it came from,
// and the field picked goes in at the caret. Under the field, in words, what it
// uses: "Uses: title, from “Fetch issue”".
//
// **Which fields may take one is the server's answer, never this file's**
// (`src/workflow_slots.py`, the one registry, `Law 7`): the palette hands each
// field's slot — `{ mapping: "value" | "never", why }` — and a field whose slot
// is `never` (a destination, a command, a recipient, a URL, a host, a time)
// gets no picker and says why, as text, on the field. A field with no slot at
// all gets nothing: the picker is offered only where the server said yes
// (fails closed). The server checks every reference again at save and at run;
// what is drawn here is help, not the control.
//
// **Everything shown is text.** Labels, paths and examples came from a person
// or from outside data (a mail subject, a webhook body) and reach the page
// through `textContent` only.

/** C-W's `origin` words for where a field was seen. */
const ORIGINS = Object.freeze({
  last_run: 'from the last run',
  run: 'from the last run',
  pinned: 'from the pinned sample',
  declared: 'what the step promises to answer',
  shape: 'what the step promises to answer',
  trigger: 'what the start hands on',
});

/** Said on a `never` field when the server gave no sentence of its own. */
export const NEVER_FALLBACK = 'Typed here only: a field from another step cannot go here.';

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function _button(cls, text, title) {
  const b = _el('button', cls, text);
  b.type = 'button';
  if (title) b.title = title;
  return b;
}

function _when(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

/** "from the last run, 2 Oct 07:00" — where a source's fields were seen. */
export function originWords(origin, at) {
  const base = ORIGINS[String(origin || '')] || '';
  if (!base) return '';
  return (origin === 'last_run' || origin === 'run') && at ? `${base}, ${_when(at)}` : base;
}

/** An example value as one short line of text. */
export function exampleText(value, max = 80) {
  if (value === undefined) return '';
  let t;
  if (typeof value === 'string') t = value;
  else { try { t = JSON.stringify(value); } catch (_) { t = String(value); } }
  t = String(t).replace(/\s+/g, ' ').trim();
  return t.length > max ? t.slice(0, max - 1) + '…' : t;
}

// ── references, read for the words under a field ──────────────────────────
// The grammar is `src/workflow_refs.py`'s (§ 1.1). This reading is for the
// "Uses:" line only — what a person is told a field reads — and decides
// nothing: a reference this misses or reads wrongly is still checked whole by
// the server at save and at run.
const SEG = String.raw`(?:\.[A-Za-z_][A-Za-z0-9_]{0,63}|\[(?:0|[1-9][0-9]{0,5})\]|\["[^"\\]{0,128}"\])`;
const REF_RE = new RegExp(String.raw`(\\)?\{\{\s*(?:steps\.([A-Za-z0-9_-]{1,64})\.(data|text)(` + SEG + String.raw`*)|item(` + SEG + String.raw`*))\s*\}\}`, 'g');

/** Every reference in `text`: `[{ ref, node, field, path, item }]`, in order.
 *  `\{{` is literal text and is not one. */
export function refsIn(text) {
  const out = [];
  const t = String(text == null ? '' : text);
  REF_RE.lastIndex = 0;
  let m;
  while ((m = REF_RE.exec(t))) {
    if (m[1]) continue;
    if (m[2] != null) out.push({ ref: m[0], node: m[2], field: m[3], path: (m[4] || '').replace(/^\./, ''), item: false });
    else out.push({ ref: m[0], node: null, field: null, path: (m[5] || '').replace(/^\./, ''), item: true });
  }
  return out;
}

/** Whether `text` holds anything that looks like a reference — what a
 *  `never` field says no to as it is typed. */
export const looksLikeRef = (text) => /\{\{/.test(String(text == null ? '' : text).replace(/\\\{\{/g, ''));

/** "Uses: title, from “Fetch issue”; its text, from “Summarise”." or ''.
 *  `labelOf(id)` names a step (`start` → the start). */
export function usesLine(text, labelOf) {
  const parts = [];
  const seen = new Set();
  for (const r of refsIn(text)) {
    if (seen.has(r.ref)) continue;
    seen.add(r.ref);
    if (r.item) { parts.push(r.path ? `${r.path}, from each item` : 'each item'); continue; }
    const what = r.field === 'text' ? 'its text' : (r.path || 'everything it made');
    const name = r.node === 'start' ? 'the start'
      : `“${(typeof labelOf === 'function' && labelOf(r.node)) || r.node}”`;
    parts.push(`${what}, from ${name}`);
  }
  return parts.length ? `Uses: ${parts.join('; ')}.` : '';
}

/** The words a field is listed by: its path as the server's own reference
 *  spells it — `title`, `json.subject`, `items[0].title`,
 *  `headers["content-type"]` — read off the field's `ref`. The fields route
 *  answers `path` as a LIST of segments (`workflow_refs.flatten_fields`, the
 *  form `format_ref` takes); printed as it came, a nested field read
 *  `json,subject` (`integrate-d`, found by the drive). A string `path` (an
 *  item's, which the panel lists itself) is read as it is. */
export function pathWords(f) {
  const r = refsIn(String((f && f.ref) || ''))[0];
  if (r && r.path) return r.path;
  if (f && typeof f.path === 'string' && f.path) return f.path;
  return String((f && f.ref) || '').includes('.text') ? 'its text' : 'everything it made';
}

/** Put `text` at `input`'s caret (or over its selection), and say so to the
 *  form the way typing would (`input`, bubbling). */
export function insertAtCaret(input, text) {
  const value = String(input.value == null ? '' : input.value);
  const s = Number.isInteger(input.selectionStart) ? input.selectionStart : value.length;
  const e = Number.isInteger(input.selectionEnd) ? input.selectionEnd : s;
  input.value = value.slice(0, s) + text + value.slice(e);
  const at = s + String(text).length;
  try { if (typeof input.setSelectionRange === 'function') input.setSelectionRange(at, at); } catch (_) { /* not a text field */ }
  try { input.dispatchEvent(new Event('input', { bubbles: true })); } catch (_) {
    input.dispatchEvent({ type: 'input', target: input, bubbles: true, stopPropagation() {}, preventDefault() {} });
  }
  if (typeof input.focus === 'function') input.focus();
}

// ── the list ───────────────────────────────────────────────────────────────

/**
 * Open the list of fields beside `anchor`. `load()` answers
 * `{ ok, sources, sentence }` (C-W's `sources`: `[{ node_id, label, kind,
 * origin, at, fields: [{ ref, path, type, example }] }]`); `extra` are
 * sources the panel adds itself (a For-each step's item). Resolves to the
 * picked field's `ref`, or null.
 *
 * `holdEscape(dismiss)` → release — the room's Escape layer; `layer()` — the
 * element to draw in.
 */
export function openFieldPicker(anchor, { load, extra = [], holdEscape = null, layer = null, title = 'Pick a field' } = {}) {
  return new Promise((resolve) => {
    const room = (typeof layer === 'function' && layer())
      || (anchor && typeof anchor.closest === 'function' && anchor.closest('.wb-panel'))
      || document.body;
    const box = _el('div', 'wf-picker');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', title);
    box.appendChild(_el('p', 'wf-picker-head', title));
    box.appendChild(_el('p', 'wf-picker-lede', 'What earlier steps made. The one you pick goes in where the cursor is.'));
    const list = _el('div', 'wf-picker-list');
    const note = _el('p', 'wf-picker-note', 'Looking at what the earlier steps made…');
    note.setAttribute('role', 'status');
    box.appendChild(note);
    box.appendChild(list);
    const cancel = _button('wf-picker-cancel', 'Cancel');
    box.appendChild(cancel);
    let done = false;
    let release = () => {};
    const finish = (ref) => {
      if (done) return;
      done = true;
      release();
      box.remove();
      if (!ref && anchor && typeof anchor.focus === 'function') anchor.focus();
      resolve(ref || null);
    };
    cancel.addEventListener('click', () => finish(null));
    room.appendChild(box);
    if (typeof holdEscape === 'function') release = holdEscape(() => finish(null));

    const draw = (sources) => {
      const all = [...(Array.isArray(extra) ? extra : []), ...(Array.isArray(sources) ? sources : [])]
        .filter((s) => s && Array.isArray(s.fields) && s.fields.length);
      list.replaceChildren();
      if (!all.length) {
        note.textContent = 'No earlier step has made anything to pick yet. Run the workflow once, pin a sample '
          + 'on an earlier step, or give an AI step an answer shape, and its fields are listed here.';
        cancel.focus();
        return;
      }
      note.textContent = '';
      const buttons = [];
      for (const src of all) {
        const group = _el('section', 'wf-picker-source');
        const head = _el('p', 'wf-picker-step');
        head.appendChild(_el('span', 'wf-picker-step-name', String(src.label || src.node_id || 'A step')));
        const from = originWords(src.origin, src.at);
        if (from) head.appendChild(_el('span', 'wf-picker-origin', from));
        group.appendChild(head);
        for (const f of src.fields) {
          if (!f || !f.ref) continue;
          const b = _button('wf-picker-field', null);
          b.dataset.ref = String(f.ref);
          const path = pathWords(f);
          b.appendChild(_el('span', 'wf-picker-path', path));
          if (f.type) b.appendChild(_el('span', 'wf-picker-type', String(f.type)));
          // A field a step only promises (`declared`) has no value yet: the
          // server sends `example: null`, which read as the word "null" under
          // every promised field (`integrate-d`, found by the drive).
          const ex = src.origin === 'declared' ? '' : exampleText(f.example);
          if (ex) b.appendChild(_el('span', 'wf-picker-example', ex));
          b.setAttribute('aria-label', `${path}, from ${String(src.label || 'a step')}${ex ? '. For example: ' + ex : ''}`);
          b.addEventListener('click', () => finish(String(f.ref)));
          buttons.push(b);
          group.appendChild(b);
        }
        list.appendChild(group);
      }
      box.addEventListener('keydown', (e) => {
        const i = buttons.indexOf(e.target);
        if (i < 0 || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp')) return;
        e.preventDefault();
        buttons[(i + (e.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length].focus();
      });
      if (buttons[0]) buttons[0].focus();
    };

    Promise.resolve().then(() => (typeof load === 'function' ? load() : { ok: true, sources: [] }))
      .then((res) => {
        if (done) return;
        if (!res || res.ok === false) {
          // What the step's own extra sources hold (an item) is still offered.
          if (Array.isArray(extra) && extra.length) { draw([]); note.textContent = String((res && res.sentence) || ''); return; }
          note.textContent = String((res && res.sentence) || 'The fields could not be listed.');
          cancel.focus();
          return;
        }
        draw(res.sources);
      }, (err) => {
        if (done) return;
        note.textContent = String((err && (err.sentence || err.message)) || 'The fields could not be listed.');
      });
  });
}

// ── a field, told what it may take ─────────────────────────────────────────

/**
 * Decorate one text field with what its slot allows.
 *
 * `slot` — `{ mapping, why }` from the palette, or null (nothing is drawn: the
 *   picker is offered only where the server said a field may take one).
 * `pick()` → Promise<ref|null> — opens the list (`openFieldPicker`).
 * `labelOf(id)` — a step's name, for the "Uses:" line.
 *
 * A `value` field gets **Insert a field…** and the "Uses:" line; a `never`
 * field gets its reason, always, and says no again if `{{` is typed into it.
 * Returns `{ show(sentence), refresh(), pick(), destroy() }` — `show` puts a
 * refusal (the server's, at save) on this field.
 */
export function decorateField(input, { slot = null, pick = null, labelOf = null, field = '' } = {}) {
  const mapping = slot && (slot.mapping === 'value' || slot.mapping === 'never') ? slot.mapping : null;
  const box = _el('div', 'wf-slot');
  if (field) box.dataset.slotFor = String(field);
  if (mapping) box.dataset.mapping = mapping;
  const problem = _el('p', 'wf-slot-problem');
  problem.setAttribute('role', 'alert');
  problem.hidden = true;
  let pickBtn = null;
  let uses = null;
  let never = null;
  if (mapping === 'value') {
    pickBtn = _button('wf-slot-pick', 'Insert a field…', 'Pick a field an earlier step made; it goes in where the cursor is');
    uses = _el('p', 'wf-slot-uses');
    box.appendChild(pickBtn);
    box.appendChild(uses);
  } else if (mapping === 'never') {
    never = _el('p', 'wf-slot-never', String(slot.why || '') || NEVER_FALLBACK);
    box.appendChild(never);
  }
  box.appendChild(problem);
  const parent = input && input.parentNode;
  if (parent) {
    const next = input.nextSibling || null;
    if (next && typeof parent.insertBefore === 'function') parent.insertBefore(box, next);
    else parent.appendChild(box);
  }

  function refresh() {
    const v = input.value;
    if (uses) { uses.textContent = usesLine(v, labelOf); uses.hidden = !uses.textContent; }
    if (never) {
      const refused = looksLikeRef(v);
      box.classList.toggle('wf-slot-refused', refused);
      never.textContent = (refused ? 'Not here: ' : '') + (String(slot.why || '') || NEVER_FALLBACK);
    }
  }
  async function doPick() {
    if (mapping !== 'value' || typeof pick !== 'function') {
      // A `never` field is never handed a reference, whatever asks.
      if (mapping === 'never') show(String(slot.why || '') || NEVER_FALLBACK);
      return null;
    }
    const ref = await pick(input);
    if (ref) insertAtCaret(input, ref);
    refresh();
    return ref || null;
  }
  function show(sentence) {
    problem.textContent = String(sentence || '');
    problem.hidden = !problem.textContent;
  }
  const onInput = () => { refresh(); if (!problem.hidden) show(''); };
  input.addEventListener('input', onInput);
  if (pickBtn) pickBtn.addEventListener('click', () => { doPick(); });
  refresh();
  return {
    box, show, refresh, pick: doPick,
    destroy() { input.removeEventListener('input', onInput); box.remove(); },
  };
}

export default {
  pathWords,
  openFieldPicker, decorateField, refsIn, usesLine, insertAtCaret, originWords, exampleText, looksLikeRef,
  NEVER_FALLBACK,
};
