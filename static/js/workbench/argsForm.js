// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/argsForm.js
//
// `P22-14` (wf-canvas). An MCP tool's arguments, as a form built from the
// tool's own `inputSchema` (design § 2's P22-14). One row per top-level
// property: its name, whether it is needed, its type, the server's
// description, and a box — a choice for an enum or a yes/no, a text box for
// the rest, and literal JSON for an object or a list.
//
// **What may be filled from another step is the server's answer**
// (`workflow_slots.classify_argument`, an allowlist that fails closed — design
// § 1.2): the palette hands each tool's `args: { name: { mapping, why } }`,
// and this form draws it. A `value` argument (`text`, `message`, `subject`…)
// gets **Insert a field…**; every other (`channel`, `to`, `url`, `path`, any
// object or list) is typed here and says why, so the destination is always
// the author's (`D-2026-10-01-05` §4). An argument the palette did not
// classify gets no picker at all. The server checks the whole call again at
// save and builds it at run as JSON (`render_call`), so nothing typed here can
// become a key of the call.
//
// **Whether the tool writes is said as the settings say it** — the badge and
// sentence of `settings/mcpFields.js:describeReadonly` (`P8-48`'s overrides
// included), reused rather than reworded (`Law 14`).
//
// Every name, description and value is text (`textContent`, `.value`).

import { describeReadonly } from '../settings/mcpFields.js';

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

/** `B1886` (`anyof-optional-args-never`). An optional argument as the type it
 *  is optional of — `workflow_slots.effective_schema`'s rule, the same one
 *  the server classifies and coerces with, so the box and the slot agree.
 *  pydantic v2 and FastMCP write `count: int | None` as
 *  `{ anyOf: [{ type: 'integer' }, { type: 'null' }] }`, with no `type` of
 *  its own, and this form called it plain "text", gave it a text box and
 *  sent `"3"` as a string. Only an `anyOf`/`oneOf` of ONE schema and
 *  `{ type: 'null' }` is unwrapped; every other shape is read as it was. */
export function effectiveSchema(prop) {
  const p = prop && typeof prop === 'object' ? prop : {};
  if ('type' in p) return p;
  const keys = ['anyOf', 'oneOf'].filter((k) => Array.isArray(p[k]));
  if (keys.length !== 1) return p;
  const members = p[keys[0]];
  const isNull = (m) => m && typeof m === 'object' && m.type === 'null' && Object.keys(m).length === 1;
  const real = members.filter((m) => !isNull(m));
  if (members.length !== 2 || real.length !== 1 || !real[0] || typeof real[0] !== 'object') return p;
  const member = real[0];
  const types = typeof member.type === 'string' ? [member.type]
    : (Array.isArray(member.type) && member.type.every((t) => typeof t === 'string') ? member.type : []);
  if (!types.length || 'anyOf' in member || 'oneOf' in member) return p;
  const out = {};
  for (const [k, v] of Object.entries(p)) if (k !== keys[0]) out[k] = v;
  for (const [k, v] of Object.entries(member)) if (k !== 'type' && !(k in out)) out[k] = v;
  out.type = types.includes('null') ? types.slice() : [...types, 'null'];
  return out;
}

/** The type of one property, in a word a person reads. */
export function typeWord(prop) {
  const p = effectiveSchema(prop);
  if (Array.isArray(p.enum) && p.enum.length) return 'one of a list';
  const t = Array.isArray(p.type) ? p.type.filter((x) => x !== 'null')[0] : p.type;
  return ({ string: 'text', number: 'a number', integer: 'a whole number', boolean: 'yes or no',
    object: 'JSON (an object)', array: 'JSON (a list)' })[t] || 'text';
}

const _kind = (prop) => {
  const p = effectiveSchema(prop);
  if (Array.isArray(p.enum) && p.enum.length) return 'enum';
  const t = Array.isArray(p.type) ? p.type.filter((x) => x !== 'null')[0] : p.type;
  if (t === 'boolean') return 'boolean';
  if (t === 'object' || t === 'array') return 'json';
  if (t === 'number' || t === 'integer') return t;
  return 'string';
};

/** `B1884` (`identifiers-cannot-be-mapped`). The words of the box that opens
 *  one typed-only setting — a ticket's id, an HTTP path, a Wait's time — to
 *  a value from an earlier step, and what ticking it means. Only a setting
 *  the server says `openable: true` on is offered one (`workflow_slots.
 *  opening_problem`: never a recipient, a channel, a host, a command, a file
 *  or a key), and the save asks the rule again. */
export const OPEN_WORDS = 'Fill from an earlier step';
export const OPENED_NOTE = 'Pantheon reads what an earlier step puts here as text from outside: a webhook or a mail may '
  + 'have written it. So whenever an earlier step fills it, this step asks you first wherever your approval setting '
  + 'asks once outside text has been read.';

/**
 * `B1884`. Draw the box that opens `field` beside its input, and the note
 * that says what that means while it is ticked. `onChange(checked)` is told
 * each time it is ticked or not, so the caller decorates the input again —
 * *Insert a field…* while it is open, the reason it is typed only while it
 * is not. Returns `{ box, label, note, checked(), destroy() }`.
 */
export function mountOpenBox(parent, { field, checked = false, note = OPENED_NOTE, onChange = null } = {}) {
  const label = _el('label', 'wf-sf-label');
  const box = _el('input');
  box.type = 'checkbox';
  box.checked = !!checked;
  box.dataset.opens = String(field || '');
  label.appendChild(box);
  label.appendChild(_el('span', null, ` ${OPEN_WORDS}`));
  const said = _el('p', 'wf-sf-gate', note);
  said.dataset.opens = String(field || '');
  parent.appendChild(label);
  parent.appendChild(said);
  const sync = () => { said.hidden = !box.checked; };
  box.addEventListener('change', () => {
    sync();
    if (typeof onChange === 'function') onChange(box.checked);
  });
  sync();
  return {
    box,
    label,
    note: said,
    checked: () => !!box.checked,
    /** Shown or not, keeping a tick that is there (a person unticks it). */
    offer(on) { label.hidden = !on && !box.checked; said.hidden = !box.checked; },
    destroy() { label.remove(); said.remove(); },
  };
}

/** The slot an opened setting has: `value`, so it offers *Insert a field…*. */
export const OPENED_SLOT = Object.freeze({ mapping: 'value', why: '' });

/** The literal JSON of a value for an object/list box. */
function _jsonText(v) {
  if (v === undefined || v === null || v === '') return '';
  if (typeof v === 'string') return v;
  try { return JSON.stringify(v, null, 2); } catch (_) { return String(v); }
}

/**
 * Draw the arguments of `tool` into `host`.
 *
 * `tool`   — a C-W `mcp_tools` entry: `{ qualified_name, name, description,
 *            input_schema, annotations, is_readonly, readonly_source,
 *            override, args: { name: { mapping, why } } }`.
 * `values` — the step's `config.args`, as stored.
 * `pickField(input, { field, slot })` — decorates one text box with what its
 *            slot allows (`fieldPicker.js:decorateField`); null → nothing.
 *
 * `lenient`  — `P22-22`'s *Try a tool* (`settings/mcpBuild.js`): `read()`
 *            never refuses. An empty box is left out and text that does not
 *            read as its type is sent as typed, so the server — which
 *            enforces its own schema (`D-2026-09-27-02`) — is the one that
 *            answers. A workflow step keeps the refusals (the default).
 *
 * `filled`  — `B1884`: the step's `config.filled`, the fields its author
 *            opened. An argument the palette says `openable: true` on (or one
 *            already opened) is drawn with *Fill from an earlier step*.
 *
 * Returns `{ read() → { args, filled? } | { refusal, field }, handles,
 * destroy() }` — `filled` the `args.<name>` fields ticked open, when any are.
 */
export function mountArgsForm(host, { tool, values = {}, pickField = null, lenient = false, filled = [] } = {}) {
  const t = tool && typeof tool === 'object' ? tool : {};
  const schema = t.input_schema && typeof t.input_schema === 'object' ? t.input_schema : {};
  const props = schema.properties && typeof schema.properties === 'object' ? schema.properties : {};
  const required = new Set(Array.isArray(schema.required) ? schema.required.map(String) : []);
  const slots = t.args && typeof t.args === 'object' ? t.args : {};
  const given = values && typeof values === 'object' ? values : {};
  const opened = new Set(Array.isArray(filled) ? filled.map(String) : []);

  const wrap = _el('div', 'wf-args');
  // Whether it writes, as Settings → MCP says it (`P8-48`).
  const ro = describeReadonly({ ...t, name: t.name || t.qualified_name });
  const badge = _el('p', 'wf-args-writes');
  badge.dataset.writes = ro.readOnly ? 'no' : (ro.destructive ? 'destroys' : 'yes');
  badge.appendChild(_el('span', 'wf-args-writes-label', ro.label));
  if (ro.note) badge.appendChild(_el('span', 'wf-args-writes-note', ` (${ro.note})`));
  wrap.appendChild(badge);
  if (ro.sentence) wrap.appendChild(_el('p', 'wf-args-writes-sentence', ro.sentence));

  const names = Object.keys(props);
  if (!names.length) wrap.appendChild(_el('p', 'wf-args-none', 'This tool takes no arguments.'));
  const rows = [];
  const handles = {};
  for (const name of names) {
    // `B1886`: an optional argument is drawn as the type it is optional of —
    // its choices, its default and its description included.
    const prop = effectiveSchema(props[name] && typeof props[name] === 'object' ? props[name] : {});
    const kind = _kind(prop);
    const row = _el('div', 'wf-arg');
    row.dataset.arg = name;
    const label = _el('label', 'wf-arg-label');
    const id = `wf-arg-${Math.random().toString(36).slice(2, 9)}`;
    label.setAttribute('for', id);
    label.appendChild(_el('span', 'wf-arg-name', name));
    label.appendChild(_el('span', 'wf-arg-need', required.has(name) ? ' needed' : ' optional'));
    label.appendChild(_el('span', 'wf-arg-type', ` · ${typeWord(prop)}`));
    row.appendChild(label);
    if (prop.description) row.appendChild(_el('p', 'wf-arg-desc', String(prop.description)));
    let input;
    const v = given[name];
    if (kind === 'enum' || kind === 'boolean') {
      input = _el('select', 'wf-arg-input');
      const choices = kind === 'boolean' ? [['', '—'], ['true', 'Yes'], ['false', 'No']]
        : [['', '—'], ...prop.enum.map((x) => [JSON.stringify(x), String(x)])];
      for (const [val, words] of choices) {
        const o = _el('option', null, words);
        o.value = val;
        input.appendChild(o);
      }
      input.value = v === undefined || v === null ? '' : (kind === 'boolean' ? String(!!v) : JSON.stringify(v));
    } else if (kind === 'json') {
      input = _el('textarea', 'wf-arg-input wf-arg-json');
      input.rows = 3;
      input.value = _jsonText(v);
      input.placeholder = typeWord(prop);
    } else {
      input = _el('input', 'wf-arg-input');
      input.type = 'text';
      input.value = v === undefined || v === null ? '' : String(v);
      if (prop.default !== undefined) input.placeholder = `Default: ${String(prop.default)}`;
    }
    input.id = id;
    input.dataset.field = `args.${name}`;
    row.appendChild(input);
    wrap.appendChild(row);
    // A text box is where a reference could be typed: it is told what its
    // slot allows. A choice cannot hold one.
    let open = null;
    if ((kind === 'string' || kind === 'number' || kind === 'integer' || kind === 'json') && typeof pickField === 'function') {
      const field = `args.${name}`;
      const slot = slots[name] || null;
      // `B1884`: an argument the server says may be opened (a ticket's id,
      // not a channel) offers the box; ticking it offers *Insert a field…*.
      const offered = !lenient && kind !== 'json' && slot && slot.mapping === 'never'
        && (slot.openable === true || opened.has(field));
      const decorate = (isOpen) => {
        try { if (handles[field] && handles[field].destroy) handles[field].destroy(); } catch (_) { /* gone */ }
        handles[field] = pickField(input, { field, slot: isOpen ? OPENED_SLOT : slot });
      };
      if (offered) open = mountOpenBox(row, { field, checked: opened.has(field), onChange: decorate });
      decorate(!!(open && open.checked()));
    }
    rows.push({ name, kind, prop, input, open });
  }
  host.appendChild(wrap);

  function read() {
    const args = {};
    for (const r of rows) {
      const raw = r.input.value;
      const field = `args.${r.name}`;
      if (r.kind === 'enum' || r.kind === 'boolean') {
        if (raw === '') {
          if (required.has(r.name) && !lenient) return { refusal: `Choose ${r.name}: the tool needs it.`, field };
          continue;
        }
        try { args[r.name] = JSON.parse(raw); } catch (_) { args[r.name] = raw; }
        continue;
      }
      const text = String(raw == null ? '' : raw);
      if (!text.trim()) {
        if (required.has(r.name) && !lenient) return { refusal: `Fill in ${r.name}: the tool needs it.`, field };
        continue;
      }
      if (r.kind === 'json') {
        try { args[r.name] = JSON.parse(text); } catch (_) {
          if (lenient) { args[r.name] = text; continue; }
          return { refusal: `${r.name} must be ${typeWord(r.prop)}: it could not be read.`, field };
        }
        continue;
      }
      // A literal number stays a number; a reference stays its text, and
      // the server reads it as that type at run (`render_call`).
      if ((r.kind === 'number' || r.kind === 'integer') && !/\{\{/.test(text)) {
        const n = Number(text.trim());
        if (!Number.isFinite(n) || (r.kind === 'integer' && !Number.isInteger(n))) {
          if (lenient) { args[r.name] = text; continue; }
          return { refusal: `${r.name} must be ${typeWord(r.prop)}.`, field };
        }
        args[r.name] = n;
        continue;
      }
      args[r.name] = text;
    }
    // `B1884`: the arguments ticked open, named as the panel names them —
    // said only when there are some, so a form with none reads as it did.
    const ticked = rows.filter((r) => r.open && r.open.checked()).map((r) => `args.${r.name}`);
    return ticked.length ? { args, filled: ticked } : { args };
  }

  return {
    read,
    handles,
    destroy() {
      for (const h of Object.values(handles)) { try { if (h && h.destroy) h.destroy(); } catch (_) { /* gone */ } }
      wrap.remove();
    },
  };
}

export default { mountArgsForm, typeWord, effectiveSchema, mountOpenBox, OPEN_WORDS, OPENED_NOTE, OPENED_SLOT };
