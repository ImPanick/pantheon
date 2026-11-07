// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/stepFields.js
//
// `P22-10`…`P22-18` (wf-canvas). The panel of a workflow step whose kind is
// not a task's: If, Switch, Set fields, Merge, Wait, For each item, HTTP
// request, MCP tool, Skill and Code — and the AI options of a Prompt step
// (its tools and the shape of its answer, `P22-16`). The four task kinds keep
// the task form (`tasks/taskFields.js` in its `'node'` mode, `Law 7`); this is
// the rest, one form per kind, in the words a person meets
// (`/work/notes/SLICE-CD-DESIGN.md` § 2, § 3's JS contract):
//
//   mountStepFields(host, { node, palette, upstream, pickField, onApply, onCancel,
//                           problem?, editInner?, classify? }) → { read, showProblem, paletteChanged, destroy }
//   (`classify(node, field)` → `{ ok, mapping, why }`, `B1099`: the rule's slot
//   for one field of the step as it stands — an HTTP entry's value by its name.)
//   mountAiOptions(host, { node, palette, pickField }) → { read, destroy }
//
// **Nothing here is a language** (`D-2026-10-01-05` §2). A condition is a
// field picked from a list, one of six words, and a typed value; a Set step is
// names and values; a Wait is a number or a clock time. Where a value may come
// from an earlier step the field offers **Insert a field…**
// (`fieldPicker.js`), and where it may not — a destination, a command, a URL,
// a time — it says why. Which is which is the palette's answer (the slots of
// each kind, `src/workflow_slots.py`), never decided here; the server checks
// every field again at save and at run.
//
// **Done hands the step over, nothing is sent** — as the task form's `'node'`
// mode: `onApply({ label, kind, config })` puts it in the workflow's draft,
// and the workflow's own Save keeps it. A field the form does not draw is kept
// as it came (the config is copied, then the form's own keys written).
//
// **Every word that came from a person, a server or a palette is text**
// (`textContent`, `.value`): integration names, tool descriptions, case labels.

import { KIND_WORDS } from '../tasks/workflowDiagram.js';
import { mountArgsForm, mountOpenBox, OPENED_SLOT } from './argsForm.js';
import { SKILL_GATE_NOTE } from '../skillGateNote.js';
import { ROOM_NAMES } from './rooms.js';

/** The kinds this file draws. */
export const STEP_FIELD_KINDS = Object.freeze(['if', 'switch', 'set', 'merge', 'wait', 'foreach', 'http', 'mcp', 'skill', 'code']);

/** `P22-10`. The six operators, in the words a person reads, when the
 *  palette does not say its own (`operators: [{ op, word }]`, C-W). The stored
 *  words are `workflow_logic.OPERATORS`. */
export const DEFAULT_OPERATORS = Object.freeze([
  { op: 'equals', word: 'is' },
  { op: 'contains', word: 'contains' },
  { op: 'is_empty', word: 'is empty' },
  { op: 'greater_than', word: 'is more than' },
  { op: 'less_than', word: 'is less than' },
  { op: 'one_of', word: 'is one of' },
]);

/** `P22-12`. What a For-each step may run for each item (design § 1.4: not
 *  If, Switch, Merge, Wait or another For-each). */
export const INNER_EXCLUDED = Object.freeze(['if', 'switch', 'merge', 'wait', 'foreach']);

/** `P22-18`. The three lines a Code step starts from: JSON in on stdin, JSON
 *  out on stdout — values are never written into the source. */
export const CODE_TEMPLATES = Object.freeze({
  python: 'import json, sys\ndata = json.load(sys.stdin)\nprint(json.dumps({"result": data}))\n',
  bash: 'input=$(cat)\necho "$input" > /dev/null\necho \'{"result": "done"}\'\n',
});

/** `P22-13`. The methods an HTTP step may use. */
export const HTTP_METHODS = Object.freeze(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']);
/** `B1885`. What an HTTP body field is sent as (stored words,
 *  `workflow_slots.ENTRY_TYPES`); no `type` is text, as before. */
export const BODY_TYPES = Object.freeze([
  ['text', 'text'], ['number', 'a number'], ['yes/no', 'yes or no'], ['json', 'JSON'],
]);
/** `B1885`. A header's name, as the server checks it (`_HEADER_NAME_RE`). */
const HEADER_NAME_RE = /^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,128}$/;
/** `B1885`. A header whose name says it carries a key: its value is hidden on
 *  the form as a password is (the Integration is where a key belongs). */
const SECRET_HEADER_RE = /auth|token|key|secret|passw|cookie|session|signature|credential/i;
const NUMBER_TEXT_RE = /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/;
const YES_NO_RE = /^(?:yes|no|true|false)$/i;
/** `B1885`. Whether a header named `name` is one whose value the form hides. */
export function headerIsSecret(name) {
  return SECRET_HEADER_RE.test(String(name || ''));
}
/** `P22-16`. The types an AI step's answer field may have (stored words). */
export const ANSWER_TYPES = Object.freeze([
  ['text', 'text'], ['number', 'a number'], ['yes/no', 'yes or no'], ['list', 'a list'],
]);
const KEY_RE = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
const ANSWER_MAX = 20;

// ── `P22-24` (wb-canvas-e). What an imported step needs ────────────────────
// A step brought in from a file that refers to something this Pantheon does
// not have carries it in its mark's `needs` (C-A: `[{ field, name, preset?,
// server?, tool? }]`, the server's rebinding answer). It is said in words on
// the step's banner, on the field it is about, and in the import's list, each
// with a door to the room where it is added (`openWorkbench({ room })`, C-R).
// One reading of a need, here (`Law 7`); the panels and the room import it.

/** The rooms a need's door opens, with the words on the button. */
export const NEED_DOORS = Object.freeze({
  integrations: `Open ${ROOM_NAMES.integrations}`,
  skills: `Open ${ROOM_NAMES.skills}`,
});

/** The field a need is about, as the step's form names it: the server writes
 *  a For-each's inner step's as `step.config.<field>` (wb-assist's
 *  `import_file`), a refusal's as `config.<field>`. */
export function needField(need) {
  return String((need && need.field) || '').replace(/^(?:step\.config\.|config\.)/, '');
}

/** What a need is: `integration` | `mcp` | `skill` | `task` | `header` |
 *  `ai_tool` | `workstation` | `other` — read from its field (wb-assist's
 *  `import_file` writes one per kind of thing a file may refer to). */
export function needKind(need) {
  const n = need && typeof need === 'object' ? need : {};
  const field = needField(n);
  if (field === 'integration') return 'integration';
  if (field === 'tool' || n.server != null || n.tool != null) return 'mcp';
  if (field === 'skill') return 'skill';
  if (field === 'task_id') return 'task';
  if (/^headers\[\d+\]\.value$/.test(field)) return 'header';
  if (field === 'tools') return 'ai_tool';
  if (field === 'language' && String(n.name || '') === 'workstation') return 'workstation';
  if (n.preset != null) return 'integration';
  return 'other';
}

/** The room a need's door opens, or null (what is picked or typed on the
 *  step itself has no room). */
export function needDoor(need) {
  const kind = needKind(need);
  if (kind === 'integration' || kind === 'mcp') return 'integrations';
  if (kind === 'skill') return 'skills';
  return null;
}

/** A need in words. `here` — said on the field itself ("pick it here"). */
export function needWords(need, { here = false } = {}) {
  const n = need && typeof need === 'object' ? need : {};
  const name = String(n.name || '').trim();
  const where = here ? 'here' : 'on the step';
  switch (needKind(n)) {
    case 'integration':
      return `It uses an Integration called “${name || 'one this Pantheon does not have'}”`
        + `${n.preset ? ` (${String(n.preset)})` : ''}, which this Pantheon does not have. `
        + `Add it in ${ROOM_NAMES.integrations}, then pick it ${where}.`;
    case 'mcp': {
      const tool = String(n.tool || name || 'a tool');
      return `It uses the tool “${tool}”${n.server ? ` of an MCP server called “${String(n.server)}”` : ''}, `
        + `which this Pantheon does not have. Add the server in ${ROOM_NAMES.integrations}, then pick the tool ${where}.`;
    }
    case 'skill':
      return `It follows a skill called “${name || 'one you do not have'}”, which you do not have. `
        + `Add it in ${ROOM_NAMES.skills}, then pick it ${where}.`;
    case 'task':
      return `It ran a task${name ? ` called “${name}”` : ''} on the Pantheon it came from. Pick the task it runs ${where}.`;
    case 'header':
      return `It sends the header “${name || 'a header'}”, and a file never carries its value. Type it ${where}.`;
    case 'ai_tool':
      return `It may use the tool “${name || 'a tool'}”, which you cannot use here. Change its tools ${where}.`;
    case 'workstation':
      return 'It runs code in your workstation, which cannot run it now.';
    default:
      return `It needs ${name ? `“${name}”` : 'something this Pantheon does not have'}`
        + `${n.field ? ` (${String(n.field)})` : ''}.`;
  }
}

/** A need's line: its words, and — when there is a room to add it in and an
 *  `openRoom(room)` to open it — the door. */
export function needLine(need, { here = false, openRoom = null, cls = 'wf-need' } = {}) {
  const line = _el('p', cls);
  line.appendChild(_el('span', cls + '-text', needWords(need, { here })));
  const room = needDoor(need);
  if (room && typeof openRoom === 'function') {
    const door = _button(cls + '-door', NEED_DOORS[room]);
    door.dataset.room = room;
    door.addEventListener('click', () => { openRoom(room); });
    line.appendChild(door);
  }
  return line;
}

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

let _ids = 0;
const _nextId = () => `wf-sf-${++_ids}`;
/** `B1099`. How long after the last key in an HTTP entry's name its value's
 *  slot is asked (one request per pause, not per key). */
export const CLASSIFY_DELAY_MS = 250;

const clone = (v) => (v == null ? v : JSON.parse(JSON.stringify(v)));

/** `B1884` (`identifiers-cannot-be-mapped`). What ticking *Fill from an
 *  earlier step* means on an HTTP step's path and on a Wait's time — said
 *  under the box while it is ticked (`argsForm.mountOpenBox`). */
export const PATH_OPEN_NOTE = 'Pantheon reads what an earlier step puts here as text from outside: a webhook or a mail may '
  + 'have written it. So whenever an earlier step fills it, this step asks you first wherever your approval setting '
  + 'asks once outside text has been read. The path’s first part stays what you type, such as /items/, and each '
  + 'value goes in as one piece of it: never a /, a ? or a ..';
export const OPEN_PATH_HEAD = 'A path filled from an earlier step starts with a part you type, such as /items/{{ steps.read.data.id }}.';
const OPEN_PATH_HEAD_RE = /^\/[^/?#{}\s]+\//;
export function timeOpenNote(maxH) {
  return `An earlier step may give the time: a time of day (HH:MM) or a date and time such as 2026-11-08T09:00, at most ${maxH} `
    + 'hours away. Anything else ends the step, and says why.';
}
/** The fields a step's author opened (`config.filled`), as a set. */
const filledOf = (cfg) => new Set(cfg && Array.isArray(cfg.filled) ? cfg.filled.map(String) : []);

/** A text box (or area) with its label and, under it, a hint. */
function _textField(parent, label, { value = '', field = '', area = false, rows = 3, placeholder = '', hint = '', mono = false } = {}) {
  const id = _nextId();
  const lab = _el('label', 'wf-sf-label', label);
  lab.setAttribute('for', id);
  const input = area ? _el('textarea', 'wf-sf-input wf-sf-area' + (mono ? ' wf-sf-mono' : '')) : _el('input', 'wf-sf-input');
  if (!area) input.type = 'text';
  else input.rows = rows;
  input.id = id;
  input.value = value == null ? '' : String(value);
  if (placeholder) input.placeholder = placeholder;
  if (field) input.dataset.field = field;
  parent.appendChild(lab);
  parent.appendChild(input);
  if (hint) parent.appendChild(_el('p', 'wf-sf-hint', hint));
  return input;
}

/** A `<select>` with its label: `choices` are `[value, words]`. */
function _selectField(parent, label, choices, { value = '', field = '', hint = '' } = {}) {
  const id = _nextId();
  const lab = _el('label', 'wf-sf-label', label);
  lab.setAttribute('for', id);
  const sel = _el('select', 'wf-sf-input wf-sf-select');
  sel.id = id;
  for (const [v, words] of choices) {
    const o = _el('option', null, words);
    o.value = String(v);
    sel.appendChild(o);
  }
  if (field) sel.dataset.field = field;
  sel.value = String(value == null ? '' : value);
  if (sel.value !== String(value == null ? '' : value) && choices.length) sel.value = String(choices[0][0]);
  parent.appendChild(lab);
  parent.appendChild(sel);
  if (hint) parent.appendChild(_el('p', 'wf-sf-hint', hint));
  return sel;
}

/**
 * `B1136`. Offer `choices` on a select already drawn, keeping what is chosen
 * when it is still offered — else `prefer` (the step's saved value, which may
 * be offered again now), else the first choice. Answers whether the choice
 * moved.
 */
function _offer(sel, choices, prefer = '') {
  const was = sel.value;
  sel.replaceChildren(...choices.map(([v, words]) => {
    const o = _el('option', null, words);
    o.value = String(v);
    return o;
  }));
  const has = (v) => v !== '' && choices.some(([c]) => String(c) === String(v));
  sel.value = has(was) ? String(was) : (has(prefer) ? String(prefer) : String(choices.length ? choices[0][0] : ''));
  return sel.value !== was;
}

/**
 * The slot the palette gives field `path` of a kind: the path as it is
 * (`fields[].value`, with each index written `[]`), then its last name
 * (`value`). None → null, and the field is offered no picker (fails closed).
 */
export function slotFor(slots, path) {
  if (!slots || typeof slots !== 'object') return null;
  const p = String(path || '');
  const generic = p.replace(/\[\d+\]/g, '[]');
  const last = generic.split(/[.[\]]+/).filter(Boolean).pop() || '';
  for (const key of [p, generic, last]) {
    const s = key && slots[key];
    if (s && (s.mapping === 'value' || s.mapping === 'never')) return s;
  }
  return null;
}

/** The palette's entry for `kind`, or `{}`. */
const kindEntry = (palette, kind) => (palette && Array.isArray(palette.kinds)
  ? palette.kinds.find((k) => k && k.kind === kind) || {} : {});

/** A list of rows the person adds to and takes from. `draw(row, item, i)`
 *  fills one row and answers its `read(i)`. */
function _rows(parent, items, { addLabel, draw, empty = '', min = 0 }) {
  const list = _el('div', 'wf-sf-rows');
  const add = _button('wf-sf-add', addLabel);
  const none = _el('p', 'wf-sf-hint wf-sf-empty', empty);
  parent.appendChild(list);
  parent.appendChild(none);
  parent.appendChild(add);
  let entries = [];
  const current = () => entries.map((e, i) => e.snapshot(i));
  function render(values) {
    for (const e of entries) { try { e.destroy(); } catch (_) { /* gone */ } }
    list.replaceChildren();
    entries = values.map((item, i) => {
      const row = _el('div', 'wf-sf-row');
      const handle = draw(row, item, i);
      const remove = _button('wf-sf-remove', 'Remove');
      remove.setAttribute('aria-label', `Remove row ${i + 1}`);
      remove.disabled = values.length <= min;
      remove.addEventListener('click', () => {
        const kept = current();
        kept.splice(i, 1);
        render(kept);
        // An edit to the step, as typing is (the canvas counts `change`).
        try { list.dispatchEvent(new Event('change', { bubbles: true })); } catch (_) { /* no Event: a test */ }
      });
      row.appendChild(remove);
      list.appendChild(row);
      return handle;
    });
    none.hidden = !!values.length || !empty;
  }
  add.addEventListener('click', () => { render([...current(), null]); });
  render(Array.isArray(items) ? items : []);
  return {
    read: () => entries.map((e, i) => e.read(i)),
    count: () => entries.length,
    destroy() { for (const e of entries) { try { e.destroy(); } catch (_) { /* gone */ } } },
  };
}

/** `P22-10`. A list of conditions — field, one of six words, value — and
 *  whether all or any must hold. Shared by If and each Switch case. */
function _conditions(parent, value, { prefix, decorate, operators, joinLabel }) {
  const v = value && typeof value === 'object' ? value : {};
  const join = _selectField(parent, joinLabel,
    [['all', 'all of these are true'], ['any', 'any of these is true']],
    { value: v.join === 'any' ? 'any' : 'all', field: prefix ? `${prefix}.join` : 'join' });
  const ops = Array.isArray(operators) && operators.length ? operators : DEFAULT_OPERATORS;
  const base = prefix ? `${prefix}.conditions` : 'conditions';
  const rows = _rows(parent, Array.isArray(v.conditions) && v.conditions.length ? v.conditions : [null], {
    addLabel: 'Add a condition',
    min: 1,
    draw(row, item, i) {
      const c = item && typeof item === 'object' ? item : {};
      const left = _textField(row, 'This', { value: c.left || '', field: `${base}[${i}].left`,
        placeholder: 'Pick a field from an earlier step' });
      const hl = decorate(left, `${base}[${i}].left`);
      const op = _selectField(row, 'Is', ops.map((o) => [o.op, o.word]), { value: c.op || 'equals', field: `${base}[${i}].op` });
      const rightBox = _el('div', 'wf-sf-right');
      row.appendChild(rightBox);
      const right = _textField(rightBox, 'This value', { value: c.right == null ? '' : c.right, field: `${base}[${i}].right`,
        placeholder: 'Type a value, or pick a field' });
      const hr = decorate(right, `${base}[${i}].right`);
      const oneOf = _el('p', 'wf-sf-hint', 'Separate the choices with commas.');
      rightBox.appendChild(oneOf);
      const sync = () => { rightBox.hidden = op.value === 'is_empty'; oneOf.hidden = op.value !== 'one_of'; };
      op.addEventListener('change', sync);
      sync();
      return {
        snapshot: () => ({ left: left.value, op: op.value, right: right.value }),
        read: (j) => {
          const field = `${base}[${j}]`;
          if (!String(left.value).trim()) return { refusal: 'Pick the field this condition looks at.', field: `${field}.left` };
          if (op.value !== 'is_empty' && !String(right.value).trim() && op.value !== 'equals') {
            return { refusal: `Give the value “${(ops.find((o) => o.op === op.value) || {}).word || op.value}” compares with.`, field: `${field}.right` };
          }
          const out = { left: String(left.value).trim(), op: op.value };
          if (op.value !== 'is_empty') out.right = String(right.value);
          return { value: out };
        },
        destroy() { for (const h of [hl, hr]) { try { if (h && h.destroy) h.destroy(); } catch (_) { /* gone */ } } },
      };
    },
  });
  return {
    read() {
      const conditions = [];
      for (const r of rows.read()) {
        if (r.refusal) return r;
        conditions.push(r.value);
      }
      return { value: { join: join.value === 'any' ? 'any' : 'all', conditions } };
    },
    destroy: () => rows.destroy(),
  };
}

// ── one builder per kind: (ctx) → read() ─────────────────────────────────

function buildIf(ctx) {
  const { body, cfg } = ctx;
  body.appendChild(_el('p', 'wf-sf-lede', 'Goes the “if so” way when the conditions hold, and the “otherwise” way when they do not.'));
  const conds = _conditions(body, cfg, { prefix: '', decorate: ctx.decorate, operators: ctx.operators,
    joinLabel: 'It goes the “if so” way when' });
  ctx.onDestroy(() => conds.destroy());
  return () => {
    const r = conds.read();
    if (r.refusal) return r;
    return { config: { join: r.value.join, conditions: r.value.conditions } };
  };
}

function buildSwitch(ctx) {
  const { body, cfg } = ctx;
  body.appendChild(_el('p', 'wf-sf-lede', 'Each case is checked in order and the first that holds is the way it goes. '
    + 'Each case is a way out of this step, with its own arrow.'));
  const existing = Array.isArray(cfg.cases) ? cfg.cases : [];
  const taken = new Set(existing.map((c) => String(c && c.id)));
  const freshCase = () => { let k = 1; while (taken.has(`c${k}`)) k += 1; taken.add(`c${k}`); return `c${k}`; };
  const rows = _rows(body, existing.length ? existing : [null], {
    addLabel: 'Add a case',
    min: 1,
    draw(row, item, i) {
      const c = item && typeof item === 'object' ? item : {};
      const id = c.id != null && String(c.id) !== '' ? String(c.id) : freshCase();
      row.dataset.caseId = id;
      const label = _textField(row, `Case ${i + 1}: its name`, { value: c.label || '', field: `cases[${i}].label`,
        placeholder: 'e.g. Urgent', hint: 'The name is the words on its arrow.' });
      const hl = ctx.decorate(label, `cases[${i}].label`);
      const conds = _conditions(row, c, { prefix: `cases[${i}]`, decorate: ctx.decorate, operators: ctx.operators,
        joinLabel: 'It goes this way when' });
      return {
        snapshot: () => { const r = conds.read(); return { id, label: label.value, ...(r.value || c) }; },
        read: (j) => {
          if (!String(label.value).trim()) return { refusal: 'Name this case: its name is the words on its arrow.', field: `cases[${j}].label` };
          const r = conds.read();
          if (r.refusal) return r;
          return { value: { id, label: String(label.value).trim(), join: r.value.join, conditions: r.value.conditions } };
        },
        destroy() { conds.destroy(); if (hl && hl.destroy) hl.destroy(); },
      };
    },
  });
  body.appendChild(_el('p', 'wf-sf-hint', 'If no case holds, it goes the “otherwise” way.'));
  ctx.onDestroy(() => rows.destroy());
  return () => {
    const cases = [];
    for (const r of rows.read()) {
      if (r.refusal) return r;
      cases.push(r.value);
    }
    return { config: { cases } };
  };
}

function buildSet(ctx) {
  const { body, cfg } = ctx;
  body.appendChild(_el('p', 'wf-sf-lede', 'Hands the next step these fields, by these names. A value is typed, or picked from an earlier step.'));
  const rows = _rows(body, Array.isArray(cfg.fields) && cfg.fields.length ? cfg.fields : [null], {
    addLabel: 'Add a field',
    min: 1,
    draw(row, item, i) {
      const f = item && typeof item === 'object' ? item : {};
      const name = _textField(row, 'Name', { value: f.name || '', field: `fields[${i}].name`, placeholder: 'e.g. headline' });
      const hn = ctx.decorate(name, `fields[${i}].name`);
      const value = _textField(row, 'Value', { value: f.value == null ? '' : f.value, field: `fields[${i}].value`,
        placeholder: 'Type it, or pick a field' });
      const hv = ctx.decorate(value, `fields[${i}].value`);
      return {
        snapshot: () => ({ name: name.value, value: value.value }),
        read: (j) => {
          const n = String(name.value).trim();
          if (!KEY_RE.test(n)) {
            return { refusal: 'A field’s name is letters, digits and _ (not starting with a digit), such as headline.', field: `fields[${j}].name` };
          }
          return { value: { name: n, value: String(value.value) } };
        },
        destroy() { for (const h of [hn, hv]) { try { if (h && h.destroy) h.destroy(); } catch (_) { /* gone */ } } },
      };
    },
  });
  ctx.onDestroy(() => rows.destroy());
  return () => {
    const fields = [];
    const names = new Set();
    for (const [j, r] of rows.read().entries()) {
      if (r.refusal) return r;
      if (names.has(r.value.name)) return { refusal: `“${r.value.name}” is set twice. Each name once.`, field: `fields[${j}].name` };
      names.add(r.value.name);
      fields.push(r.value);
    }
    return { config: { fields } };
  };
}

function buildMerge(ctx) {
  const { body, cfg } = ctx;
  body.appendChild(_el('p', 'wf-sf-lede', 'Where branches that run at the same time come back together.'));
  const mode = _selectField(body, 'It goes on', [
    ['all', 'when every branch that reaches it has arrived'],
    ['first', 'as soon as the first branch arrives'],
  ], { value: cfg.mode === 'first' ? 'first' : 'all', field: 'mode',
    hint: 'What each branch made is handed on together; a branch that failed is named as missing.' });
  return () => ({ config: { mode: mode.value === 'first' ? 'first' : 'all' } });
}

function buildWait(ctx) {
  const { body, cfg, limits } = ctx;
  const maxH = Number(limits && limits.wait_max_hours) || 168;
  body.appendChild(_el('p', 'wf-sf-lede', 'Holds the run here, then goes on. A wait survives Pantheon restarting.'));
  const mode = _selectField(body, 'Wait', [['for', 'for a while'], ['until', 'until a time of day']],
    { value: cfg.mode === 'until' ? 'until' : 'for', field: 'mode' });
  const forBox = _el('div', 'wf-sf-group');
  const untilBox = _el('div', 'wf-sf-group');
  body.appendChild(forBox);
  body.appendChild(untilBox);
  const minutes = Number(cfg.minutes) > 0 ? Number(cfg.minutes) : 30;
  const byHours = minutes % 60 === 0 && minutes >= 60;
  const amount = _textField(forBox, 'How long', { value: String(byHours ? minutes / 60 : minutes), field: 'minutes' });
  const ha = ctx.decorate(amount, 'minutes');
  const unit = _selectField(forBox, 'In', [['1', 'minutes'], ['60', 'hours']], { value: byHours ? '60' : '1' });
  const time = _textField(untilBox, 'Until (HH:MM, 24-hour)', { value: cfg.time || '08:00', field: 'time', placeholder: '08:00' });
  // `B1884`. A Wait until a time may take the time from an earlier step, when
  // its author ticks the box the palette offers (`openable`) — a time of day
  // or a date and time, read when the step is reached.
  const timeSlot = slotFor(ctx.slots, 'time');
  const opened = filledOf(cfg);
  let ht = null;
  const timeOpen = timeSlot && timeSlot.mapping === 'never' && (timeSlot.openable === true || opened.has('time'))
    ? mountOpenBox(untilBox, { field: 'time', checked: opened.has('time'), note: timeOpenNote(maxH),
      onChange: (on) => {
        try { if (ht && ht.destroy) ht.destroy(); } catch (_) { /* gone */ }
        ht = on ? ctx.decorateSlot(time, { field: 'time', slot: OPENED_SLOT }) : ctx.decorate(time, 'time');
        sync();
      } })
    : null;
  const fromData = () => !!(timeOpen && timeOpen.checked()) && String(time.value).includes('{{');
  ht = timeOpen && timeOpen.checked() ? ctx.decorateSlot(time, { field: 'time', slot: OPENED_SLOT }) : ctx.decorate(time, 'time');
  const tz = _textField(untilBox, 'Time zone (optional)', { value: cfg.tz || '', field: 'tz',
    placeholder: 'The start’s time zone', hint: 'Leave it blank for the time zone the workflow’s start uses.' });
  const htz = ctx.decorate(tz, 'tz');
  const said = _el('p', 'wf-sf-hint wf-sf-wait-said');
  body.appendChild(said);
  body.appendChild(_el('p', 'wf-sf-hint', `At most ${maxH} hours.`));
  const sync = () => {
    forBox.hidden = mode.value !== 'for';
    untilBox.hidden = mode.value !== 'until';
    said.textContent = mode.value === 'until'
      ? (fromData() ? 'It runs at the time an earlier step hands it, or as soon after as Pantheon is idle.'
        : `It runs at ${String(time.value || '08:00').trim()}, or as soon after as Pantheon is idle.`)
      : 'Then it runs on as soon as Pantheon is idle.';
  };
  for (const n of [mode, time]) n.addEventListener(n === mode ? 'change' : 'input', sync);
  sync();
  ctx.onDestroy(() => { for (const h of [ha, ht, htz]) { try { if (h && h.destroy) h.destroy(); } catch (_) { /* gone */ } } });
  return () => {
    const isOpen = !!(timeOpen && timeOpen.checked());
    if (mode.value === 'until') {
      const t = String(time.value).trim();
      if (!fromData() && !/^([01]\d|2[0-3]):[0-5]\d$/.test(t)) {
        return { refusal: isOpen ? 'Write the time as HH:MM, such as 08:00, or pick it from an earlier step.'
          : 'Write the time as HH:MM, such as 08:00.', field: 'time' };
      }
      const out = { mode: 'until', time: t };
      if (String(tz.value).trim()) out.tz = String(tz.value).trim();
      // `B1884`: a Wait that opened nothing, and had nothing open, stays
      // without the key.
      if (isOpen || Array.isArray(cfg.filled)) out.filled = isOpen ? ['time'] : [];
      return { config: out };
    }
    const n = Number(String(amount.value).trim());
    if (!Number.isFinite(n) || n <= 0) return { refusal: 'Say how long, as a number above 0.', field: 'minutes' };
    const total = Math.round(n * Number(unit.value));
    if (total > maxH * 60) return { refusal: `A wait is at most ${maxH} hours (workflow_wait_max_hours).`, field: 'minutes' };
    const out = { mode: 'for', minutes: total };
    // A Wait for a while opens nothing: only a time is ever filled from a step.
    if (Array.isArray(cfg.filled)) out.filled = [];
    return { config: out };
  };
}

function buildForeach(ctx) {
  const { body, cfg, limits, palette } = ctx;
  const cap = Number(limits && limits.foreach_max_items) || 50;
  body.appendChild(_el('p', 'wf-sf-lede', 'Runs one step for each item of a list an earlier step made, in order, one at a time.'));
  const list = _textField(body, 'The list', { value: cfg.list || '', field: 'list',
    placeholder: 'Pick a list from an earlier step', hint: `At most ${cap} items: a longer list is refused, never cut (workflow_foreach_max_items).` });
  const hl = ctx.decorate(list, 'list');
  let step = cfg.step && typeof cfg.step === 'object' ? clone(cfg.step) : null;
  const kinds = (palette && Array.isArray(palette.kinds) && palette.kinds.length
    ? palette.kinds.filter((k) => k && !INNER_EXCLUDED.includes(k.kind) && k.available !== false).map((k) => k.kind)
    : ['llm', 'research', 'action', 'run_task']);
  const kind = _selectField(body, 'For each item, it runs',
    kinds.map((k) => [k, KIND_WORDS[k] || k]), { value: step ? step.kind : kinds[0], field: 'step.kind' });
  const what = _el('p', 'wf-sf-inner');
  body.appendChild(what);
  const edit = _button('wf-sf-inner-edit', 'Set up that step…', 'What it does with each item; {{ item }} is the item');
  body.appendChild(edit);
  const onError = _selectField(body, 'If an item fails', [
    ['continue', 'go on with the next item'], ['stop', 'stop there'],
  ], { value: cfg.on_error === 'stop' ? 'stop' : 'continue', field: 'on_error',
    hint: 'Either way the step says which item failed, and leaves by “if it fails”.' });
  const sync = () => {
    what.textContent = step && step.kind === kind.value
      ? `Each item: ${step.label || KIND_WORDS[step.kind] || step.kind}.`
      : 'Not set up yet.';
  };
  kind.addEventListener('change', () => { if (step && step.kind !== kind.value) step = null; sync(); });
  edit.addEventListener('click', () => {
    if (typeof ctx.editInner !== 'function') return;
    const base = step && step.kind === kind.value ? step : { kind: kind.value, label: KIND_WORDS[kind.value] || kind.value, config: {} };
    ctx.editInner(clone(base), (made) => {
      if (made && typeof made === 'object') {
        step = { kind: String(made.kind || kind.value), label: String(made.label || ''), config: clone(made.config || {}) };
        kind.value = step.kind;
      }
      sync();
    });
  });
  sync();
  ctx.onDestroy(() => { if (hl && hl.destroy) hl.destroy(); });
  return () => {
    if (!String(list.value).trim()) return { refusal: 'Pick the list it goes through.', field: 'list' };
    if (!step || step.kind !== kind.value) return { refusal: 'Set up the step it runs for each item.', field: 'step.kind' };
    return { config: { list: String(list.value).trim(), step: clone(step), on_error: onError.value === 'stop' ? 'stop' : 'continue' } };
  };
}

function buildHttp(ctx) {
  const { body, cfg, palette } = ctx;
  let integrations = palette && Array.isArray(palette.integrations) ? palette.integrations : [];
  // `integrate-e`: these two said "Settings → Integrations" — the card is the
  // Workbench's MCP & Integrations room since `P22-21` (`B1126`).
  body.appendChild(_el('p', 'wf-sf-lede', `Calls a service you set up in ${ROOM_NAMES.integrations}. Its address and key are never `
    + 'shown here: Pantheon adds them when the step runs.'));
  let warn = null;
  if (!integrations.length) {
    // The same door the MCP step's hint has (`Law 15`: the hint names a room,
    // so it opens it).
    warn = body.appendChild(_el('p', 'wf-sf-hint wf-sf-warn'));
    warn.appendChild(_el('span', null, `No integration is set up yet. Add one in ${ROOM_NAMES.integrations}, then pick it here.`));
    if (typeof ctx.openRoom === 'function') {
      const door = warn.appendChild(_button('wf-sf-door', NEED_DOORS.integrations));
      door.dataset.room = 'integrations';
      door.addEventListener('click', () => ctx.openRoom('integrations'));
    }
  }
  const choices = () => [['', 'Choose one…'],
    ...integrations.map((i) => [i.id, `${i.name}${i.preset ? ` (${i.preset})` : ''}`])];
  const integ = _selectField(body, 'Integration', choices(), { value: cfg.integration || '', field: 'integration' });
  const desc = _el('p', 'wf-sf-hint');
  body.appendChild(desc);
  const method = _selectField(body, 'Method', HTTP_METHODS.map((m) => [m, m]),
    { value: String(cfg.method || 'GET').toUpperCase(), field: 'method' });
  const path = _textField(body, 'Path', { value: cfg.path || '', field: 'path', placeholder: '/v1/entries' });
  // `B1884` (`identifiers-cannot-be-mapped`). The path, and a query or body
  // value whose name allows it, may be opened to a value from an earlier step
  // with *Fill from an earlier step* — offered where the server says
  // `openable` (the palette for the path, the rule's answer for an entry as
  // its name is typed), kept ticked where the step already opened it.
  const opened = filledOf(cfg);
  const pathSlot = slotFor(ctx.slots, 'path');
  let hp = null;
  const pathOpen = pathSlot && pathSlot.mapping === 'never' && (pathSlot.openable === true || opened.has('path'))
    ? mountOpenBox(body, { field: 'path', checked: opened.has('path'), note: PATH_OPEN_NOTE,
      onChange: (on) => {
        try { if (hp && hp.destroy) hp.destroy(); } catch (_) { /* gone */ }
        hp = on ? ctx.decorateSlot(path, { field: 'path', slot: OPENED_SLOT }) : ctx.decorate(path, 'path');
      } })
    : null;
  hp = pathOpen && pathOpen.checked() ? ctx.decorateSlot(path, { field: 'path', slot: OPENED_SLOT }) : ctx.decorate(path, 'path');
  // `B1885` (`http-body-strings-no-headers`). The headers the step sends. The
  // server always kept, checked and sent them, but there was no list here, so
  // a header that came in a file was sent unseen and could not be removed —
  // and the file's own need said "Type it on the step" about a box that did
  // not exist. Every header is typed only (a `never` slot: it says how the
  // request is read, never a value from another step). A value whose name says
  // it is a key is hidden as a password is; the Integration is where a key
  // belongs — kept encrypted, added when the step runs, and sent in place of a
  // header here of the same name (`integrations._credentials`).
  const headersBox = _el('div', 'wf-sf-group');
  headersBox.appendChild(_el('p', 'wf-sf-sub', 'Headers'));
  body.appendChild(headersBox);
  const headerRows = _rows(headersBox, Array.isArray(cfg.headers) ? cfg.headers : [], {
    addLabel: 'Add a header',
    empty: 'None.',
    draw(row, item, i) {
      const it = item && typeof item === 'object' ? item : {};
      const k = _textField(row, 'Name', { value: it.name || '', field: `headers[${i}].name`, placeholder: 'e.g. Accept' });
      const hk = ctx.decorate(k, `headers[${i}].name`);
      const v = _textField(row, 'Value', { value: it.value == null ? '' : it.value, field: `headers[${i}].value` });
      v.autocomplete = 'off';
      v.spellcheck = false;
      const hv = ctx.decorate(v, `headers[${i}].value`);
      const hide = () => {
        const secret = headerIsSecret(k.value);
        v.type = secret ? 'password' : 'text';
        // A browser offers a saved login for a password box; this is not one.
        v.autocomplete = secret ? 'new-password' : 'off';
      };
      k.addEventListener('input', hide);
      hide();
      return {
        snapshot: () => ({ name: k.value, value: v.value }),
        read: (j) => {
          const n = String(k.value).trim();
          if (!n) return { refusal: 'Give this header a name, or remove it.', field: `headers[${j}].name` };
          if (!HEADER_NAME_RE.test(n)) {
            return { refusal: 'A header’s name is letters, digits and - with no spaces, such as Accept.', field: `headers[${j}].name` };
          }
          return { value: { name: n, value: String(v.value) } };
        },
        destroy() { for (const h of [hk, hv]) { try { if (h && h.destroy) h.destroy(); } catch (_) { /* gone */ } } },
      };
    },
  });
  ctx.onDestroy(() => headerRows.destroy());
  headersBox.appendChild(_el('p', 'wf-sf-hint', `A key or token belongs in the Integration (${ROOM_NAMES.integrations}): `
    + 'Pantheon keeps it encrypted there and adds it when the step runs, in place of a header here of the same name. '
    + 'A header typed here is kept with the workflow, hidden on this form when its name says it is a key, '
    + 'never shown in a plan, and left out of an exported file.'));
  // `P22-13`. Each query or body entry is `{ name, value }` — the shape the
  // document rule checks and `render_call` sends (`src/workflow_document.py`
  // `_check_entries`, `src/workflow_slots.py`), as a Set field's and a Code
  // input's are. `integrate-d`: this wrote `{ key, value }`, which every save
  // refused ("each of “query” is a name and a value"). `B1885`: a body field
  // also says what it is sent as (`type`): text, a number, yes or no, or JSON.
  const kv = (parent, label, list, add, items, { typed = false } = {}) => {
    const box = _el('div', 'wf-sf-group');
    box.appendChild(_el('p', 'wf-sf-sub', label));
    parent.appendChild(box);
    const rows = _rows(box, items, {
      addLabel: add,
      empty: 'None.',
      draw(row, item, i) {
        const it = item && typeof item === 'object' ? item : {};
        const field = `${list}[${i}].value`;
        const k = _textField(row, 'Name', { value: it.name || '', field: `${list}[${i}].name` });
        const hk = ctx.decorate(k, `${list}[${i}].name`);
        const v = _textField(row, 'Value', { value: it.value == null ? '' : it.value, field });
        let hv = ctx.decorate(v, field);
        const type = typed
          ? _selectField(row, 'Sent as', BODY_TYPES, { value: it.type || 'text', field: `${list}[${i}].type` })
          : null;
        // `B1884`: offered once the rule says this name may be opened; a row
        // the step already opened keeps its tick (a new row starts unticked).
        let said = slotFor(ctx.slots, field);
        const open = mountOpenBox(row, {
          field,
          checked: item == null ? false : (typeof it.opened === 'boolean' ? it.opened : opened.has(field)),
          onChange: (on) => {
            try { if (hv && hv.destroy) hv.destroy(); } catch (_) { /* gone */ }
            hv = on ? ctx.decorateSlot(v, { field, slot: OPENED_SLOT }) : ctx.decorateSlot(v, { field, slot: said });
          },
        });
        open.offer(false);
        if (open.checked()) {
          try { if (hv && hv.destroy) hv.destroy(); } catch (_) { /* gone */ }
          hv = ctx.decorateSlot(v, { field, slot: OPENED_SLOT });
        }
        // `B1099`. Whether another step may fill this value depends on the
        // entry's name (`classify_argument`), which the palette cannot say
        // once per kind (it says `never`). The rule is asked as the name is
        // typed, and the value offers *Insert a field…* or says why not, before
        // Done. A Pantheon without the door keeps the palette's `never`.
        // `B1885`: and on what it is sent as — JSON is never filled.
        let alive = true;
        let asked = null;
        let timer = null;
        const ask = async () => {
          const name = String(k.value).trim();
          const typeWord = type && type.value !== 'text' ? type.value : null;
          const key = `${name}\u0000${typeWord || ''}`;
          if (!ctx.classify || !name || key === asked) return;
          asked = key;
          const entry = typeWord ? { name, type: typeWord } : { name };
          let r = null;
          try { r = await ctx.classify({ kind: 'http', config: { [list]: [entry] } }, `${list}[0].value`); } catch (_) { r = null; }
          if (!alive || String(k.value).trim() !== name || !r || r.ok === false) return;
          if (r.mapping !== 'value' && r.mapping !== 'never') return;
          said = { mapping: r.mapping, why: r.why || '' };
          open.offer(r.mapping === 'never' && r.openable === true);
          try { if (hv && hv.destroy) hv.destroy(); } catch (_) { /* gone */ }
          hv = ctx.decorateSlot(v, { field, slot: open.checked() ? OPENED_SLOT : said });
        };
        k.addEventListener('input', () => {
          if (timer) clearTimeout(timer);
          timer = setTimeout(() => { timer = null; ask(); }, CLASSIFY_DELAY_MS);
        });
        if (type) type.addEventListener('change', () => { ask(); });
        if (String(k.value).trim()) ask();
        const sentAs = () => (type ? type.value : 'text');
        return {
          snapshot: () => ({ name: k.value, value: v.value, ...(type ? { type: type.value } : {}), opened: open.checked() }),
          read: (j) => {
            const name = String(k.value).trim();
            if (!name) return { refusal: 'Give this a name, or remove it.', field: `${list}[${j}].name` };
            const value = String(v.value);
            const word = sentAs();
            const typedOwn = !value.includes('{{');
            if (typedOwn && word === 'number' && !NUMBER_TEXT_RE.test(value.trim())) {
              return { refusal: `“${name}” is sent as a number, and “${value.slice(0, 40)}” is not one.`, field: `${list}[${j}].value` };
            }
            if (typedOwn && word === 'yes/no' && !YES_NO_RE.test(value.trim())) {
              return { refusal: `“${name}” is sent as yes or no: write yes or no.`, field: `${list}[${j}].value` };
            }
            if (word === 'json') {
              try { JSON.parse(value); } catch (_) {
                return { refusal: `“${name}” is sent as JSON, and what is written is not JSON.`, field: `${list}[${j}].value` };
              }
            }
            const out = { name, value };
            // No `type` is text, as before; a field that said text keeps saying it.
            if (type && (word !== 'text' || it.type === 'text')) out.type = word;
            return { value: out, opens: open.checked() };
          },
          destroy() {
            alive = false;
            if (timer) clearTimeout(timer);
            for (const h of [hk, hv]) { try { if (h && h.destroy) h.destroy(); } catch (_) { /* gone */ } }
          },
        };
      },
    });
    ctx.onDestroy(() => rows.destroy());
    return { box, rows };
  };
  const query = kv(body, 'Query', 'query', 'Add a query value', Array.isArray(cfg.query) ? cfg.query : []);
  // `B1885`. The body is its fields (sent as a JSON object, as it always was)
  // or JSON written whole, whose values may be references where their names
  // say they are words — the same rule a field's name is held to.
  const bodyBox = _el('div', 'wf-sf-group');
  body.appendChild(bodyBox);
  const bodyMode = _selectField(bodyBox, 'Body', [['json', 'fields, sent as JSON'], ['raw', 'JSON you write']],
    { value: cfg.body_mode === 'raw' ? 'raw' : 'json', field: 'body_mode' });
  const bodyKv = kv(bodyBox, 'Body fields', 'body', 'Add a body field', Array.isArray(cfg.body) ? cfg.body : [], { typed: true });
  const rawBox = _el('div', 'wf-sf-group');
  bodyBox.appendChild(rawBox);
  const written = cfg.raw_body && typeof cfg.raw_body === 'object' ? JSON.stringify(cfg.raw_body, null, 2) : '';
  const raw = _textField(rawBox, 'JSON you write', { value: written, field: 'raw_body', area: true, rows: 8, mono: true,
    placeholder: '{ "title": "Daily brief", "text": "{{ steps.read.text }}", "priority": 4 }',
    hint: 'Sent exactly as written. A value may be a reference, inside quotes, where its name says it is words '
      + '(text, message, title…); a reference alone keeps its type, so a number stays a number.' });
  raw.spellcheck = false;
  body.appendChild(_el('p', 'wf-sf-hint', 'Whether a value may come from an earlier step depends on its name: words that '
    + 'carry content (text, message, subject, title, summary…) may; a name that says where something goes never does. '
    + 'The value says which as you type the name.'));
  // `B1885`. What the step hands on: the answer's body (as before), or its
  // status and headers with it.
  const response = _selectField(body, 'It hands on', [['body', 'the answer’s body'], ['full', 'its status, headers and body']],
    { value: cfg.response === 'full' ? 'full' : 'body', field: 'response',
      hint: 'With its status, headers and body, a later step reads data.http_status, data.headers and data.body.' });
  const sync = () => {
    const i = integrations.find((x) => String(x.id) === integ.value);
    desc.textContent = i && i.description ? String(i.description) : '';
    bodyBox.hidden = method.value === 'GET';
    bodyKv.box.hidden = bodyMode.value === 'raw';
    rawBox.hidden = bodyMode.value !== 'raw';
  };
  integ.addEventListener('change', sync);
  method.addEventListener('change', sync);
  bodyMode.addEventListener('change', sync);
  sync();
  // `B1136`. An Integration added in the room this step's door opens is
  // offered here once the palette is read again — no reopening the Workbench.
  ctx.onPalette((pal) => {
    integrations = pal && Array.isArray(pal.integrations) ? pal.integrations : [];
    _offer(integ, choices(), cfg.integration || '');
    if (warn) warn.hidden = integrations.length > 0;
    sync();
  });
  ctx.onDestroy(() => { if (hp && hp.destroy) hp.destroy(); });
  return () => {
    if (!integ.value) return { refusal: 'Choose the integration it calls.', field: 'integration' };
    const p = String(path.value).trim();
    if (p && !p.startsWith('/')) return { refusal: 'A path starts with /, such as /v1/entries.', field: 'path' };
    const pathOpened = !!(pathOpen && pathOpen.checked());
    if (pathOpened && p.includes('{{') && !OPEN_PATH_HEAD_RE.test(p)) return { refusal: OPEN_PATH_HEAD, field: 'path' };
    // `opens`: the `B1884` fields of a list ticked open, as the panel names them.
    const read = (rows, list = '') => {
      const out = [];
      const opens = [];
      for (const [j, r] of rows.read().entries()) {
        if (r.refusal) return r;
        out.push(r.value);
        if (list && r.opens) opens.push(`${list}[${j}].value`);
      }
      return { value: out, opens };
    };
    const h = read(headerRows);
    if (h.refusal) return h;
    const seen = new Set();
    for (const [j, one] of h.value.entries()) {
      const lower = one.name.toLowerCase();
      if (seen.has(lower)) return { refusal: `“${one.name}” is sent twice. Each header once.`, field: `headers[${j}].name` };
      seen.add(lower);
    }
    const q = read(query.rows, 'query');
    if (q.refusal) return q;
    const writes = method.value !== 'GET' && bodyMode.value === 'raw';
    const b = method.value === 'GET' || writes ? { value: [], opens: [] } : read(bodyKv.rows, 'body');
    if (b.refusal) return b;
    let rawBody;
    if (writes) {
      try { rawBody = JSON.parse(String(raw.value)); } catch (_) {
        return { refusal: 'This is not JSON. A reference goes inside quotes, such as "text": "{{ steps.read.text }}".', field: 'raw_body' };
      }
      if (!rawBody || typeof rawBody !== 'object') {
        return { refusal: 'Write a JSON object { … } or a list [ … ].', field: 'raw_body' };
      }
    }
    const out = { integration: integ.value, method: method.value, path: p, query: q.value, body: b.value };
    // A step that had no headers and was given none stays without the key.
    if (h.value.length || Array.isArray(cfg.headers)) out.headers = h.value;
    if (method.value !== 'GET') out.body_mode = writes ? 'raw' : 'json';
    else if (cfg.body_mode === 'raw') out.body_mode = 'json';
    // Undefined drops a body written before, once it is not sent.
    if (writes) out.raw_body = rawBody;
    else if ('raw_body' in cfg) out.raw_body = undefined;
    if (response.value === 'full') out.response = 'full';
    else if (cfg.response != null) out.response = 'body';
    // `B1884`: what is open, by where it is now; a step that opened nothing,
    // and had nothing open, stays without the key.
    const filled = [...(pathOpened ? ['path'] : []), ...q.opens, ...b.opens];
    if (filled.length || Array.isArray(cfg.filled)) out.filled = filled;
    return { config: out };
  };
}

function buildMcp(ctx) {
  const { body, cfg, palette } = ctx;
  let tools = palette && Array.isArray(palette.mcp_tools) ? palette.mcp_tools : [];
  body.appendChild(_el('p', 'wf-sf-lede', 'Calls one tool of an MCP server you added, with the arguments you give it here.'));
  // `wb-canvas-e`: this named "Settings → MCP", a place that does not exist
  // (design § 0.6 — MCP servers are a card of Integrations, and the
  // Workbench's MCP & Integrations room since `P22-21`); it names the room and
  // opens it.
  let warn = null;
  if (!tools.length) {
    warn = body.appendChild(_el('p', 'wf-sf-hint wf-sf-warn'));
    warn.appendChild(_el('span', null, `No MCP tool is available. Add a server in ${ROOM_NAMES.integrations}, then pick its tool here.`));
    if (typeof ctx.openRoom === 'function') {
      const door = warn.appendChild(_button('wf-sf-door', NEED_DOORS.integrations));
      door.dataset.room = 'integrations';
      door.addEventListener('click', () => ctx.openRoom('integrations'));
    }
  }
  const choices = () => [['', 'Choose one…'],
    ...tools.map((t) => [t.qualified_name, `${t.server_name ? t.server_name + ': ' : ''}${t.name}`])];
  const choice = _selectField(body, 'Tool', choices(), { value: cfg.tool || '', field: 'tool' });
  const desc = _el('p', 'wf-sf-hint');
  body.appendChild(desc);
  const argsHost = _el('div', 'wf-sf-args');
  body.appendChild(argsHost);
  let form = null;
  let args = cfg.args && typeof cfg.args === 'object' ? clone(cfg.args) : {};
  // `B1884`: the arguments its author opened to a value from an earlier step.
  let filled = Array.isArray(cfg.filled) ? cfg.filled.map(String) : [];
  const sync = () => {
    if (form) {
      const r = form.read();
      if (r.args) { args = { ...args, ...r.args }; filled = Array.isArray(r.filled) ? r.filled : []; }
      form.destroy(); form = null;
    }
    const t = tools.find((x) => x.qualified_name === choice.value);
    desc.textContent = t && t.description ? String(t.description) : '';
    if (t) form = mountArgsForm(argsHost, { tool: t, values: args, pickField: ctx.decorateSlot, filled });
    ctx.argsHandles = form ? form.handles : {};
  };
  choice.addEventListener('change', () => { args = {}; filled = []; sync(); });
  sync();
  // `B1136`. A server added in the room this step's door opens: its tools
  // are offered here once the palette is read again. The arguments typed so
  // far stay, unless the chosen tool is no longer there.
  ctx.onPalette((pal) => {
    tools = pal && Array.isArray(pal.mcp_tools) ? pal.mcp_tools : [];
    if (_offer(choice, choices(), cfg.tool || '')) sync();
    if (warn) warn.hidden = tools.length > 0;
  });
  ctx.onDestroy(() => { if (form) form.destroy(); });
  return () => {
    if (!choice.value) return { refusal: 'Choose the tool it calls.', field: 'tool' };
    const r = form ? form.read() : { args: {} };
    if (r.refusal) return r;
    const out = { tool: choice.value, args: r.args };
    // `B1884`: a step that opened none, and had none, stays without the key.
    if ((r.filled && r.filled.length) || Array.isArray(cfg.filled)) out.filled = r.filled || [];
    return { config: out };
  };
}

function buildSkill(ctx) {
  const { body, cfg, palette } = ctx;
  let skills = palette && Array.isArray(palette.skills) ? palette.skills : [];
  body.appendChild(_el('p', 'wf-sf-lede', 'Runs a model that follows one of your skills. The skill is read when the step runs, '
    + 'so an edit to it reaches the next run.'));
  const choices = () => [['', 'Choose one…'], ...skills.map((s) => [s.name, s.name])];
  const choice = _selectField(body, 'Skill', choices(), { value: cfg.skill || '', field: 'skill' });
  const desc = _el('p', 'wf-sf-hint');
  body.appendChild(desc);
  const prompt = _textField(body, 'What to do with it', { value: cfg.prompt || '', field: 'prompt', area: true, rows: 4,
    placeholder: 'e.g. Print the queue for today' });
  const hp = ctx.decorate(prompt, 'prompt');
  // `P8-18`'s sentence, the same words the skill test says (one constant).
  body.appendChild(_el('p', 'wf-sf-gate', SKILL_GATE_NOTE));
  const sync = () => {
    const s = skills.find((x) => x.name === choice.value);
    desc.textContent = s && s.description ? String(s.description) : '';
  };
  choice.addEventListener('change', sync);
  sync();
  // `B1136`. A skill added in the Skills room an import's door opens.
  ctx.onPalette((pal) => {
    skills = pal && Array.isArray(pal.skills) ? pal.skills : [];
    _offer(choice, choices(), cfg.skill || '');
    sync();
  });
  ctx.onDestroy(() => { if (hp && hp.destroy) hp.destroy(); });
  return () => {
    if (!choice.value) return { refusal: 'Choose the skill it follows.', field: 'skill' };
    const out = { skill: choice.value };
    if (String(prompt.value).trim()) out.prompt = String(prompt.value).trim();
    return { config: out };
  };
}

function buildCode(ctx) {
  const { body, cfg, palette } = ctx;
  const ws = palette && palette.workstation && typeof palette.workstation === 'object' ? palette.workstation : null;
  body.appendChild(_el('p', 'wf-sf-lede', 'Runs your code in your own workstation. What it is handed arrives as JSON on '
    + 'stdin; print JSON on stdout and the next step can pick its fields.'));
  if (ws && ws.available === false) body.appendChild(_el('p', 'wf-sf-hint wf-sf-warn', String(ws.why || 'Your workstation is not available.')));
  const lang = _selectField(body, 'Language', [['python', 'Python'], ['bash', 'Bash']],
    { value: cfg.language === 'bash' ? 'bash' : 'python', field: 'language' });
  const src = _textField(body, 'Code', { value: cfg.source != null && cfg.source !== '' ? cfg.source : CODE_TEMPLATES[lang.value],
    field: 'source', area: true, rows: 8, mono: true });
  src.spellcheck = false;
  const hs = ctx.decorate(src, 'source');
  lang.addEventListener('change', () => {
    // A template not yet changed follows the language; written code stays.
    if (Object.values(CODE_TEMPLATES).includes(src.value)) src.value = CODE_TEMPLATES[lang.value];
  });
  const timeout = _textField(body, 'Time limit (seconds)', { value: String(Number(cfg.timeout_seconds) > 0 ? cfg.timeout_seconds : 60),
    field: 'timeout_seconds' });
  const ht = ctx.decorate(timeout, 'timeout_seconds');
  const box = _el('div', 'wf-sf-group');
  box.appendChild(_el('p', 'wf-sf-sub', 'What it is handed (on stdin)'));
  body.appendChild(box);
  const rows = _rows(box, Array.isArray(cfg.input) ? cfg.input : [], {
    addLabel: 'Add an input',
    empty: 'Nothing: it is handed {}.',
    draw(row, item, i) {
      const it = item && typeof item === 'object' ? item : {};
      const n = _textField(row, 'Name', { value: it.name || '', field: `input[${i}].name`, placeholder: 'prices' });
      const hn = ctx.decorate(n, `input[${i}].name`);
      const v = _textField(row, 'Value', { value: it.value == null ? '' : it.value, field: `input[${i}].value` });
      const hv = ctx.decorate(v, `input[${i}].value`);
      return {
        snapshot: () => ({ name: n.value, value: v.value }),
        read: (j) => (KEY_RE.test(String(n.value).trim())
          ? { value: { name: String(n.value).trim(), value: String(v.value) } }
          : { refusal: 'An input’s name is letters, digits and _, such as prices.', field: `input[${j}].name` }),
        destroy() { for (const h of [hn, hv]) { try { if (h && h.destroy) h.destroy(); } catch (_) { /* gone */ } } },
      };
    },
  });
  ctx.onDestroy(() => { rows.destroy(); for (const h of [hs, ht]) { try { if (h && h.destroy) h.destroy(); } catch (_) { /* gone */ } } });
  return () => {
    if (!String(src.value).trim()) return { refusal: 'Write the code it runs.', field: 'source' };
    const t = Number(String(timeout.value).trim());
    if (!Number.isFinite(t) || t <= 0) return { refusal: 'A time limit is a number of seconds above 0.', field: 'timeout_seconds' };
    const input = [];
    for (const r of rows.read()) { if (r.refusal) return r; input.push(r.value); }
    return { config: { language: lang.value, source: String(src.value), timeout_seconds: Math.round(t), input } };
  };
}

const BUILDERS = {
  if: buildIf, switch: buildSwitch, set: buildSet, merge: buildMerge, wait: buildWait, foreach: buildForeach,
  http: buildHttp, mcp: buildMcp, skill: buildSkill, code: buildCode,
};

/** Put `problem` (a refusal with a `field`, the server's or the form's) on
 *  its field in `root`; answers whether a field took it. */
function showOnField(root, handles, problem, fallbackEl) {
  const field = String((problem && problem.field) || '').replace(/^config\./, '');
  const sentence = String((problem && (problem.sentence || problem.refusal)) || '');
  for (const old of Array.from(root.querySelectorAll('.wf-sf-problem'))) old.remove();
  if (field && handles[field] && typeof handles[field].show === 'function') {
    handles[field].show(sentence);
    return true;
  }
  const el = field ? Array.from(root.querySelectorAll('[data-field]')).find((n) => n.dataset.field === field) : null;
  const line = _el('p', 'wf-sf-problem', sentence);
  line.setAttribute('role', 'alert');
  if (field) line.dataset.field = field;
  if (el && el.parentNode) {
    const next = el.nextSibling;
    if (next) el.parentNode.insertBefore(line, next); else el.parentNode.appendChild(line);
    return true;
  }
  if (fallbackEl) fallbackEl.appendChild(line);
  return false;
}

/**
 * A step's panel, for one of `STEP_FIELD_KINDS`.
 *
 * `node`      — `{ id, kind, label, config }` (a copy; nothing here edits it).
 * `palette`   — C-W's palette, or null.
 * `upstream`  — the steps before this one (`[{ id, label, kind }]`), for words.
 * `pickField(input, { field, slot })` — decorates a text box with what its slot
 *               allows and returns its handle (`fieldPicker.js:decorateField`
 *               with the step's own picker); null → nothing is decorated.
 * `problem`   — the draft's refusal naming this step (`{ sentence, field }`),
 *               said on its field when the panel opens.
 * `editInner(step, done)` — a For-each step's inner step, edited in place.
 * `needs`     — `P22-24`: what an imported step needs (its mark's `needs`),
 *               each said on its field with its door.
 * `openRoom(room)` — opens the Workbench at a room (`openWorkbench({ room })`).
 * `onApply({ label, kind, config })`, `onCancel()`.
 */
export function mountStepFields(host, {
  node, palette = null, upstream = [], pickField = null, onApply = null, onCancel = null, problem = null, editInner = null,
  needs = null, openRoom = null, classify = null,
} = {}) {
  const n = node && typeof node === 'object' ? node : {};
  const kind = String(n.kind || '');
  const cfg = n.config && typeof n.config === 'object' ? clone(n.config) : {};
  const entry = kindEntry(palette, kind);
  const slots = entry.slots && typeof entry.slots === 'object' ? entry.slots : null;
  const wrap = _el('div', 'wf-sf');
  wrap.dataset.kind = kind;
  wrap.appendChild(_el('h3', 'wf-sf-head', `Edit step · ${KIND_WORDS[kind] || kind}`));
  wrap.appendChild(_el('p', 'wf-sf-hint', 'Done puts it on the canvas; Save above the canvas keeps the workflow.'));
  const unavailable = entry.available === false && entry.why
    ? wrap.appendChild(_el('p', 'wf-sf-hint wf-sf-warn', String(entry.why))) : null;
  const top = _el('div', 'wf-sf-problems');
  wrap.appendChild(top);
  const name = _textField(wrap, 'Name', { value: n.label || '', field: 'label', placeholder: KIND_WORDS[kind] || 'Step' });
  const body = _el('div', 'wf-sf-body');
  wrap.appendChild(body);
  const handles = {};
  const destroyers = [];
  const onPalette = [];
  const ctx = {
    body, cfg, palette, upstream, slots, editInner, openRoom,
    classify: typeof classify === 'function' ? classify : null,
    limits: palette && palette.limits ? palette.limits : {},
    operators: palette && Array.isArray(palette.operators) && palette.operators.length ? palette.operators : DEFAULT_OPERATORS,
    onDestroy: (fn) => destroyers.push(fn),
    /** `B1136`. Called with a palette read again while this form is open. */
    onPalette: (fn) => onPalette.push(fn),
    argsHandles: {},
    decorate(input, field) {
      return ctx.decorateSlot(input, { field, slot: slotFor(slots, field) });
    },
    /** For a field whose slot is not the kind's (an MCP argument's). */
    decorateSlot(input, { field, slot }) {
      if (typeof pickField !== 'function') return null;
      const h = pickField(input, { field, slot });
      if (h) handles[field] = h;
      return h;
    },
  };
  const builder = BUILDERS[kind];
  const readKind = builder ? builder(ctx) : () => ({ config: cfg });
  if (!builder) body.appendChild(_el('p', 'wf-sf-hint', 'This kind of step has no settings to change here.'));

  const row = _el('div', 'wf-sf-buttons');
  const cancel = _button('wf-step-cancel', 'Cancel');
  const done = _button('wf-step-done', 'Done');
  row.appendChild(cancel);
  row.appendChild(done);
  wrap.appendChild(row);
  host.appendChild(wrap);

  function read() {
    const r = readKind();
    if (r && r.refusal) return r;
    const label = String(name.value || '').trim() || KIND_WORDS[kind] || 'Step';
    // What the form does not draw is kept as it came.
    return { step: { label, kind, config: { ...cfg, ...(r ? r.config : {}) } } };
  }
  const allHandles = () => ({ ...handles, ...(ctx.argsHandles || {}) });
  done.addEventListener('click', () => {
    const r = read();
    if (r.refusal) { showOnField(wrap, allHandles(), r, top); return; }
    if (typeof onApply === 'function') onApply(r.step);
  });
  cancel.addEventListener('click', () => { if (typeof onCancel === 'function') onCancel(); });
  if (problem && problem.sentence) showOnField(wrap, allHandles(), problem, top);
  // `P22-24`. What an imported step needs, said on the field it is about
  // (the Integration, the tool, the skill), with its door; one the form does
  // not draw is said at the top.
  for (const need of (Array.isArray(needs) ? needs : [])) {
    // A For-each's inner step's need (`step.config.…`) is not a field of
    // this form: it is said at the top, as one the form does not draw is.
    const inner = /^step\.config\./.test(String((need && need.field) || ''));
    const field = inner ? '' : needField(need);
    const el = field ? Array.from(wrap.querySelectorAll('[data-field]')).find((x) => x.dataset.field === field) : null;
    const line = needLine(need, { here: !!el, openRoom, cls: 'wf-sf-need' });
    if (field) line.dataset.field = field;
    if (el && el.parentNode) {
      const next = el.nextSibling;
      if (next) el.parentNode.insertBefore(line, next); else el.parentNode.appendChild(line);
    } else {
      top.appendChild(line);
    }
  }

  return {
    read,
    showProblem: (p) => showOnField(wrap, allHandles(), p, top),
    /** `B1136`. What the palette offers now — an Integration, an MCP tool or
     *  a skill added in another room — on this open form, in place: what is
     *  typed and chosen stays. */
    paletteChanged(pal) {
      // Measured in Chromium: with Miniflux offered, the kind's own line still
      // said "No Integrations are switched on" above it.
      if (unavailable) {
        const now = kindEntry(pal, kind);
        unavailable.hidden = !(now.available === false && now.why);
        if (!unavailable.hidden) unavailable.textContent = String(now.why);
      }
      for (const fn of onPalette) { try { fn(pal); } catch (_) { /* the form keeps what it had */ } }
    },
    destroy() {
      for (const fn of destroyers) { try { fn(); } catch (_) { /* gone */ } }
      for (const h of Object.values(handles)) { try { if (h && h.destroy) h.destroy(); } catch (_) { /* gone */ } }
      wrap.remove();
    },
  };
}

/**
 * `P22-16`. A Prompt step's AI options, drawn under the task form's step
 * mode: which tools it may use, and the shape of its answer.
 *
 * `tools` absent is today's way (Pantheon picks tools by what the prompt
 * asks); `[]` is no tools; a list is only those. `answer_fields` is a list of
 * `{ name, type, description }` (at most 20), and the next step's picker lists
 * them before any run. Returns `{ read() → { config } | { refusal, field },
 * destroy() }` — `config` holds only these two keys (or neither).
 */
export function mountAiOptions(host, { node, palette = null } = {}) {
  const cfg = node && node.config && typeof node.config === 'object' ? node.config : {};
  const choices = palette && Array.isArray(palette.ai_tools) ? palette.ai_tools : [];
  const wrap = _el('div', 'wf-ai');
  wrap.appendChild(_el('p', 'wf-sf-sub', 'Its tools'));
  const how = _selectField(wrap, 'It may use', [
    ['auto', 'tools Pantheon picks by what the prompt asks'],
    ['none', 'no tools: it only reads and writes'],
    ['only', 'only the tools I choose'],
  ], { value: Array.isArray(cfg.tools) ? (cfg.tools.length ? 'only' : 'none') : 'auto', field: 'tools' });
  const list = _el('div', 'wf-ai-tools');
  wrap.appendChild(list);
  const chosen = new Set(Array.isArray(cfg.tools) ? cfg.tools.map(String) : []);
  const boxes = [];
  if (!choices.length) list.appendChild(_el('p', 'wf-sf-hint', 'This Pantheon did not list the tools a step may use.'));
  for (const t of choices) {
    const lab = _el('label', 'wf-ai-tool');
    const box = _el('input', 'wf-ai-tool-box');
    box.type = 'checkbox';
    box.value = String(t.name);
    box.checked = chosen.has(String(t.name));
    lab.appendChild(box);
    lab.appendChild(_el('span', 'wf-ai-tool-name', String(t.label || t.name)));
    if (t.kind) lab.appendChild(_el('span', 'wf-ai-tool-kind', ` · ${String(t.kind)}`));
    list.appendChild(lab);
    boxes.push(box);
  }
  const sync = () => { list.hidden = how.value !== 'only'; };
  how.addEventListener('change', sync);
  sync();

  wrap.appendChild(_el('p', 'wf-sf-sub', 'Its answer'));
  const shaped = _el('label', 'wf-ai-shaped');
  const shapedBox = _el('input', 'wf-ai-shaped-box');
  shapedBox.type = 'checkbox';
  shapedBox.checked = Array.isArray(cfg.answer_fields) && cfg.answer_fields.length > 0;
  shaped.appendChild(shapedBox);
  shaped.appendChild(_el('span', null, 'Answer in fields the next step can pick'));
  wrap.appendChild(shaped);
  const fieldsBox = _el('div', 'wf-sf-group');
  wrap.appendChild(fieldsBox);
  const rows = _rows(fieldsBox, Array.isArray(cfg.answer_fields) && cfg.answer_fields.length ? cfg.answer_fields : [null], {
    addLabel: 'Add a field',
    min: 1,
    draw(row, item, i) {
      const f = item && typeof item === 'object' ? item : {};
      const name = _textField(row, 'Name', { value: f.name || '', field: `answer_fields[${i}].name`, placeholder: 'title' });
      const type = _selectField(row, 'It is', ANSWER_TYPES, { value: f.type || 'text', field: `answer_fields[${i}].type` });
      const desc = _textField(row, 'What it holds', { value: f.description || '', field: `answer_fields[${i}].description`,
        placeholder: 'The page’s title' });
      return {
        snapshot: () => ({ name: name.value, type: type.value, description: desc.value }),
        read: (j) => (KEY_RE.test(String(name.value).trim())
          ? { value: { name: String(name.value).trim(), type: type.value, description: String(desc.value).trim() } }
          : { refusal: 'A field’s name is letters, digits and _, such as title.', field: `answer_fields[${j}].name` }),
        destroy() {},
      };
    },
  });
  fieldsBox.appendChild(_el('p', 'wf-sf-hint', 'The answer is checked against these after the step runs; '
    + 'one that does not fit leaves by “if it fails”, with why.'));
  const syncShape = () => { fieldsBox.hidden = !shapedBox.checked; };
  shapedBox.addEventListener('change', syncShape);
  syncShape();
  host.appendChild(wrap);

  function read() {
    const config = {};
    if (how.value === 'none') config.tools = [];
    else if (how.value === 'only') {
      const picked = boxes.filter((b) => b.checked).map((b) => b.value);
      if (!picked.length) return { refusal: 'Choose at least one tool, or choose no tools.', field: 'tools' };
      config.tools = picked;
    }
    if (shapedBox.checked) {
      const fields = [];
      const names = new Set();
      for (const [j, r] of rows.read().entries()) {
        if (r.refusal) return r;
        if (names.has(r.value.name)) return { refusal: `“${r.value.name}” is asked for twice.`, field: `answer_fields[${j}].name` };
        names.add(r.value.name);
        fields.push(r.value);
      }
      if (fields.length > ANSWER_MAX) return { refusal: `At most ${ANSWER_MAX} fields.`, field: 'answer_fields' };
      config.answer_fields = fields;
    }
    return { config };
  }
  return {
    read,
    /** The keys this section owns: a read without one of them clears it. */
    keys: ['tools', 'answer_fields'],
    destroy() { rows.destroy(); wrap.remove(); },
  };
}

export default {
  mountStepFields, mountAiOptions, slotFor, STEP_FIELD_KINDS, DEFAULT_OPERATORS, INNER_EXCLUDED, CODE_TEMPLATES,
  HTTP_METHODS, ANSWER_TYPES, NEED_DOORS, needField, needKind, needDoor, needWords, needLine,
  BODY_TYPES, headerIsSecret, PATH_OPEN_NOTE, OPEN_PATH_HEAD, timeOpenNote,
};
