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

/** The type of one property, in a word a person reads. */
export function typeWord(prop) {
  const p = prop && typeof prop === 'object' ? prop : {};
  if (Array.isArray(p.enum) && p.enum.length) return 'one of a list';
  const t = Array.isArray(p.type) ? p.type.filter((x) => x !== 'null')[0] : p.type;
  return ({ string: 'text', number: 'a number', integer: 'a whole number', boolean: 'yes or no',
    object: 'JSON (an object)', array: 'JSON (a list)' })[t] || 'text';
}

const _kind = (prop) => {
  const p = prop && typeof prop === 'object' ? prop : {};
  if (Array.isArray(p.enum) && p.enum.length) return 'enum';
  const t = Array.isArray(p.type) ? p.type.filter((x) => x !== 'null')[0] : p.type;
  if (t === 'boolean') return 'boolean';
  if (t === 'object' || t === 'array') return 'json';
  if (t === 'number' || t === 'integer') return t;
  return 'string';
};

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
 * Returns `{ read() → { args } | { refusal, field }, handles, destroy() }`.
 */
export function mountArgsForm(host, { tool, values = {}, pickField = null } = {}) {
  const t = tool && typeof tool === 'object' ? tool : {};
  const schema = t.input_schema && typeof t.input_schema === 'object' ? t.input_schema : {};
  const props = schema.properties && typeof schema.properties === 'object' ? schema.properties : {};
  const required = new Set(Array.isArray(schema.required) ? schema.required.map(String) : []);
  const slots = t.args && typeof t.args === 'object' ? t.args : {};
  const given = values && typeof values === 'object' ? values : {};

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
    const prop = props[name] && typeof props[name] === 'object' ? props[name] : {};
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
    if ((kind === 'string' || kind === 'number' || kind === 'integer' || kind === 'json') && typeof pickField === 'function') {
      const slot = slots[name] || null;
      handles[`args.${name}`] = pickField(input, { field: `args.${name}`, slot });
    }
    rows.push({ name, kind, prop, input });
  }
  host.appendChild(wrap);

  function read() {
    const args = {};
    for (const r of rows) {
      const raw = r.input.value;
      const field = `args.${r.name}`;
      if (r.kind === 'enum' || r.kind === 'boolean') {
        if (raw === '') {
          if (required.has(r.name)) return { refusal: `Choose ${r.name}: the tool needs it.`, field };
          continue;
        }
        try { args[r.name] = JSON.parse(raw); } catch (_) { args[r.name] = raw; }
        continue;
      }
      const text = String(raw == null ? '' : raw);
      if (!text.trim()) {
        if (required.has(r.name)) return { refusal: `Fill in ${r.name}: the tool needs it.`, field };
        continue;
      }
      if (r.kind === 'json') {
        try { args[r.name] = JSON.parse(text); } catch (_) {
          return { refusal: `${r.name} must be JSON (${typeWord(r.prop)}): it could not be read.`, field };
        }
        continue;
      }
      // A literal number stays a number; a reference stays its text, and
      // the server reads it as that type at run (`render_call`).
      if ((r.kind === 'number' || r.kind === 'integer') && !/\{\{/.test(text)) {
        const n = Number(text.trim());
        if (!Number.isFinite(n) || (r.kind === 'integer' && !Number.isInteger(n))) {
          return { refusal: `${r.name} must be ${typeWord(r.prop)}.`, field };
        }
        args[r.name] = n;
        continue;
      }
      args[r.name] = text;
    }
    return { args };
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

export default { mountArgsForm, typeWord };
