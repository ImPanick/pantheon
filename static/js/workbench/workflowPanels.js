// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/workflowPanels.js
//
// `P22-05`…`P22-08` (wf-ui). What opens beside a workflow's canvas. The
// workflow's data layer (`workflowSource.js`, wf-api) decides WHICH panel a
// click opens and holds the draft; it is handed these four through
// `createWorkflowSource({ panels })` — the design's contract C3
// (`/work/notes/SLICE-B-DESIGN.md` § 7):
//
//   palette(anchorEl)                                   → Promise<kind | null>
//   node(host, { node, tasks, workflow, source, onApply, onCancel }) → { destroy }
//   start(host, { triggerTask, tasks, onSaved, onCancel })           → { destroy }
//   record(host, { node, record, run })                               → { destroy }
//
// **One form (`Law 7`).** A step's settings and a workflow's start are the task
// form itself (`tasks/taskFields.js:mountTaskFields`) in its `'node'` and
// `'trigger'` modes — the 180 lines of a kind's fields and their refusals are
// not drawn a second time here. Under a step's form sits *Test this step*
// (`P22-08`); a run's step is drawn as what it was handed, what it made, what
// went wrong and its steps (`P22-07`).
//
// **Every word that came from a person or a run is text.** Labels, prompts,
// inputs, outputs and errors reach the page through `textContent` only. The one
// markup assignment is a run's step log, drawn by the Tasks card's own renderer
// (`tasks.js:renderRunSteps`, handed in by the glue), which escapes every value
// with `ui.js:esc` — the canvas's one exception, for the same reason (`P22-04`).
//
// **Slice E (`P22-19`, `P22-20`, `P22-24`, wb-canvas-e).** A step nobody has
// checked yet — drafted by the model, or brought in by a file — opens on a
// banner: who decided it, what it needs (each with its door), what it would
// do, and *Looks right*. A failed step's record offers *Why did this fail?*:
// the model's reading, the change it proposes and what was left out, *Apply*,
// *Undo* and *Run it again*. Every word a model or a run wrote — a reason, a
// label, a value before or after — is text, as everything else here is.

import { KIND_WORDS, waitingWords } from '../tasks/workflowDiagram.js';
import { runStatusTone, runStatusLabel } from '../runStatus.js';
// `P22-09`…`P22-18` (wf-canvas): the step forms Slices C and D add, the field
// picker, and the gate card a waiting step is answered with.
import { mountStepFields, mountAiOptions, STEP_FIELD_KINDS, needLine } from './stepFields.js';
import { decorateField, openFieldPicker, exampleText } from './fieldPicker.js';
import { approvalBox } from '../approvalBox.js';

/** The kinds a step can be, in the palette's order, with what each does in
 *  the words a person meets (`D-2026-10-01-05`: the palette offers only what
 *  the agent can already reach). Since `P22-10` (wf-canvas) the server's
 *  palette (C-W's palette route, `workflowApi.getPalette`) is what is offered — every
 *  kind, grouped, a kind the person may not use greyed with the server's
 *  reason as text; these four are what a Pantheon without that route offers. */
export const PALETTE_KINDS = Object.freeze([
  { kind: 'llm', hint: 'Ask a model to read, write or decide something.' },
  { kind: 'research', hint: 'Look something up and write a report.' },
  { kind: 'action', hint: 'Run one of Pantheon’s built-in actions.' },
  { kind: 'run_task', hint: 'Run one of your tasks, with its own settings.' },
]);

/** `P22-08`. Where a test's input can come from, as the route names them
 *  (`source`), with the words for each. */
export const TEST_SOURCES = Object.freeze([
  { source: 'last', label: 'What it was handed in the last run' },
  { source: 'pinned', label: 'The pinned sample' },
  { source: 'custom', label: 'Something I type here' },
  { source: 'example', label: 'An example the model writes' },
  { source: 'none', label: 'Nothing' },
]);

/** Said wherever a pin is: the promise the design makes about it (§ 4.3). */
export const PIN_SENTENCE = 'A pinned sample is only used when you press Test. Scheduled runs never use it.';
/** Said under every test result: a test runs one step and nothing else. */
export const NOTHING_ELSE = 'Nothing else ran: no other step, no delivery, no notification.';
/** `P22-07`. Action and Research steps run with their own settings. */
export const DOES_NOT_READ = 'This kind of step does not read what it is handed; it runs with its own settings.';
/** `P22-17`. Under a waiting step's card: what each answer does. */
export const ANSWER_WORDS = 'Allow once lets this one action run, and the next one asks again. '
  + 'Deny takes the step’s “if it fails” way.';
/** `P22-19`, `P22-24` (wb-canvas-e). The banner a step nobody has checked
 *  opens with, by its mark's origin (C-A: `drafted` | `imported`). */
export const CHECK_WORDS = Object.freeze({
  drafted: 'Drafted by the model — check it.',
  imported: 'Imported from a file — check it.',
  assistant: 'Changed by your assistant — check it.',
});
/** Under it: who decided this step, and what makes it the person's. */
export const CHECK_NOTES = Object.freeze({
  drafted: 'The model wrote this step from your description and what this Pantheon can reach. It does not run '
    + 'until you say it looks right — or change it, which makes it yours.',
  imported: 'Whoever wrote the file chose this step. It does not run until you say it looks right — or change it, '
    + 'which makes it yours.',
  // `integrate-e`: a mark clears only by a person; a change made by anything
  // else (the assistant, an API token) puts one back.
  assistant: 'Your assistant, or something holding an API token, changed this step after it was last checked. It does '
    + 'not run until you say it looks right — or change it yourself, which makes it yours.',
});
/** Said once a step is checked. */
export const CHECKED_WORDS = 'Checked. It runs as it is once the workflow is switched on.';
/** `P22-20`. *Why did this fail?* — the title names who is asked. */
export const WHY_TITLE = 'Asks a model — your utility model, or your default one if none is set — to read what this step '
  + 'was handed and what came back. Nothing changes unless you press Apply.';
/** Over the model's answer: where its words come from (`Law 17`). */
export const READING_NOTE = 'It read what this step was handed and what came back — text someone else may have '
  + 'written — so read it as a suggestion.';
/** A proposed field whose slot says where the request goes (`where`). */
export const whereWords = (name) => `This changes where the request goes (still to “${name || 'the same service'}”).`;
/** A proposed value found verbatim in what the run recorded (`from_run`). */
export const FROM_RUN_WORDS = 'This value comes from what the run recorded — what the step was handed or what came '
  + 'back — not from you.';

/** The kinds the task form draws (`taskFields.js`, `'node'` mode). */
const TASK_KINDS = new Set(['llm', 'research', 'action', 'run_task']);

const OUTCOME_MARKS = { ok: '✓', error: '✗', pending: '…', info: '·', none: '○' };

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

/** A value as a person reads it: text as it is, anything else as JSON. */
export function pretty(value) {
  if (value == null) return '';
  if (typeof value === 'string') {
    const t = value.trim();
    if ((t.startsWith('{') && t.endsWith('}')) || (t.startsWith('[') && t.endsWith(']'))) {
      try { return JSON.stringify(JSON.parse(t), null, 2); } catch (_) { /* text after all */ }
    }
    return value;
  }
  try { return JSON.stringify(value, null, 2); } catch (_) { return String(value); }
}

/** `{ truncated, chars, preview }` — a record over its cap (design § 3.1) —
 *  as the preview and a sentence; anything else as itself. */
export function readCapped(value) {
  let v = value;
  if (typeof v === 'string') {
    try { const p = JSON.parse(v); if (p && typeof p === 'object') v = p; } catch (_) { /* text */ }
  }
  if (v && typeof v === 'object' && v.truncated === true) {
    const preview = String(v.preview == null ? '' : v.preview);
    const chars = Number(v.chars) || 0;
    return {
      value: preview,
      note: chars ? `Cut short: it was ${chars.toLocaleString()} characters; the first ${preview.length.toLocaleString()} are shown.`
        : 'Cut short: only the start was kept.',
    };
  }
  return { value: v, note: '' };
}

/** A run's or a step's status, as the mark, the word and the tone. */
export function statusWords(status) {
  if (!status) return { tone: 'none', mark: OUTCOME_MARKS.none, word: 'Not reached in this run' };
  const tone = runStatusTone(status) || 'info';
  return { tone, mark: OUTCOME_MARKS[tone] || OUTCOME_MARKS.info, word: runStatusLabel(status, 'job') || String(status) };
}

/** `B1109`. The first line of `text` that is words: a reasoning model's
 *  `<think>` block is left out, and so is a code fence's line (```json). */
function _wordsLine(text) {
  const t = String(text == null ? '' : text).replace(/<think>[\s\S]*?<\/think>/gi, '');
  return t.split('\n').map((l) => l.trim()).find((l) => l && !l.startsWith('```')) || '';
}

/** `B1109`. What a For-each item's line says after its status: its error's
 *  first line; else its answer — an answer in the shape asked (`data`, an
 *  object) as its fields, "name: value", the way the picker shows a field;
 *  else the first line of its text that is words. Measured by `integrate-d`:
 *  every item that answered in shape read "Item 1 of 5: Success — ```json",
 *  the first line of a fenced answer `parse_answer` had already read. */
export function itemAnswer(rec) {
  const r = rec && typeof rec === 'object' ? rec : {};
  if (r.error) return _wordsLine(r.error);
  const out = r.output && typeof r.output === 'object' && !Array.isArray(r.output) ? r.output : { text: r.output };
  const data = out.data;
  if (data && typeof data === 'object' && !Array.isArray(data) && Object.keys(data).length) {
    return Object.entries(data).map(([k, v]) => `${k}: ${exampleText(v, 60)}`).join(' · ');
  }
  return _wordsLine(out.text);
}

function _when(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString();
}

/** `P22-11`, `P22-17`. A waiting step's times, short: "Oct 2, 04:40 AM". */
function _short(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso)
    : d.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function _took(a, b) {
  const s = Date.parse(a);
  const e = Date.parse(b);
  if (!Number.isFinite(s) || !Number.isFinite(e) || e < s) return '';
  const ms = e - s;
  return ms < 1000 ? `${ms} ms` : ms < 60000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms / 60000)} min`;
}

/** A `<details>` with a `<pre>` of `text` (as text), open or not. */
function _section(title, text, { open = false, note = '', cls = '' } = {}) {
  const d = _el('details', 'wf-record-part' + (cls ? ' ' + cls : ''));
  if (open) d.open = true;
  d.appendChild(_el('summary', null, title));
  if (note) d.appendChild(_el('p', 'wf-record-note', note));
  if (text != null && text !== '') d.appendChild(_el('pre', 'wf-record-pre', text));
  return d;
}

/**
 * The four panels, for one workflow room.
 *
 * `mountTaskFields` — the `P22` panel contract's form, with its `mode`.
 * `renderSteps` — `tasks.js:renderRunSteps`, or null (then a plain list).
 * `holdEscape(dismiss)` → `release` — the room's Escape layer: registers on
 *   `escMenuStack.js` and marks the room so `ui.js` asks the stack first.
 * `onRecordShown({ node, record, run })` — a run's step was opened (the room
 *   says where to look when it opened a failed run on its failed step).
 * `onChanged(nodeId)` — a sample was pinned or unpinned (saved at once, no
 *   version): the room redraws the canvas so the step's mark says so.
 * `layer()` — the element a palette is drawn in (the room).
 * `fixer` — `P22-20`: `{ apply(proposal) → { ok, sentence, undoVersion },
 *   undo(version) → { ok, sentence }, runAgain() }`, the room's, which holds
 *   the document (a run's panel holds only the run).
 * `openRoom(room)` — `P22-24`: opens the Workbench at a room (C-R's
 *   `openWorkbench({ room })`), the door beside what a step needs.
 */
export function createWorkflowPanels({
  mountTaskFields, renderSteps = null, holdEscape = null, onRecordShown = null, onChanged = null, layer = null,
  onAnswered = null, fixer = null, openRoom = null,
} = {}) {
  const hold = typeof holdEscape === 'function' ? holdEscape : () => () => {};

  // ── the palette: which kind of step to add ────────────────────────────────
  /** The kinds to offer: the server's palette (`kinds: [{ kind, word, group,
   *  hint, available, why }]`) when there is one, else Slice B's four. */
  function offered(pal) {
    const listed = pal && Array.isArray(pal.kinds) ? pal.kinds.filter((k) => k && k.kind) : [];
    if (!listed.length) return PALETTE_KINDS.map((k) => ({ ...k, word: KIND_WORDS[k.kind] || k.kind, group: '', available: true, why: '' }));
    return listed.map((k) => ({
      kind: String(k.kind), word: String(k.word || KIND_WORDS[k.kind] || k.kind), group: String(k.group || ''),
      hint: String(k.hint || ''), available: k.available !== false, why: String(k.why || ''),
    }));
  }

  function palette(anchorEl, { palette: pal = null } = {}) {
    return new Promise((resolve) => {
      const room = (typeof layer === 'function' && layer())
        || (anchorEl && typeof anchorEl.closest === 'function' && anchorEl.closest('.wf-room'))
        || document.body;
      const box = _el('div', 'wf-palette');
      box.setAttribute('role', 'dialog');
      box.setAttribute('aria-label', 'Add a step');
      box.appendChild(_el('p', 'wf-palette-head', 'Add a step'));
      const kinds = [];
      let done = false;
      let release = () => {};
      const finish = (kind) => {
        if (done) return;
        done = true;
        release();
        box.remove();
        if (!kind && anchorEl && typeof anchorEl.focus === 'function') anchorEl.focus();
        resolve(kind || null);
      };
      // `P22-10`. Grouped as the server groups them ("Decide and reshape",
      // "Reach out" …), each group ONCE, under its own words, in the order its
      // first kind comes — the server lists kinds in its own order, not by
      // group (`integrate-d`: Skill comes after MCP tool there, so "Ask a
      // model" and "Reach out" were each drawn twice). The arrow keys follow
      // the order drawn.
      const groups = new Map();
      for (const k of offered(pal)) {
        if (!groups.has(k.group)) groups.set(k.group, []);
        groups.get(k.group).push(k);
      }
      for (const [groupName, members] of groups) {
        const group = _el('div', 'wf-palette-group');
        if (groupName) group.appendChild(_el('p', 'wf-palette-group-head', groupName));
        box.appendChild(group);
        for (const k of members) {
          const b = _button('wf-palette-kind', null);
          b.dataset.kind = k.kind;
          b.appendChild(_el('span', 'wf-palette-word', k.word));
          if (k.hint) b.appendChild(_el('span', 'wf-palette-hint', k.hint));
          if (!k.available) {
            // `D-2026-10-01-05`: the palette offers only what the person's agent
            // can reach. A kind they may not use is shown, greyed, with the
            // server's reason in words — never a colour or a lock alone.
            b.disabled = true;
            b.setAttribute('aria-disabled', 'true');
            b.dataset.available = 'false';
            b.appendChild(_el('span', 'wf-palette-why', k.why || 'Not available here.'));
            b.setAttribute('aria-label', `${k.word}: not available. ${k.why || ''}`.trim());
          } else {
            b.setAttribute('aria-label', `${k.word}: ${k.hint}`);
            b.addEventListener('click', () => finish(k.kind));
            kinds.push(b);
          }
          group.appendChild(b);
        }
      }
      const cancel = _button('wf-palette-cancel', 'Cancel');
      cancel.addEventListener('click', () => finish(null));
      box.appendChild(cancel);
      // The arrow keys go between the kinds; Tab still works, and Escape is the
      // room's layer (so it closes this before the window).
      box.addEventListener('keydown', (e) => {
        const i = kinds.indexOf(e.target);
        if (i < 0) return;
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          const j = (i + (e.key === 'ArrowDown' ? 1 : kinds.length - 1)) % kinds.length;
          kinds[j].focus();
        }
      });
      try {
        const a = anchorEl.getBoundingClientRect();
        const r = room.getBoundingClientRect();
        const top = Math.max(8, Math.round(a.bottom - r.top + 4));
        box.style.top = top + 'px';
        box.style.left = Math.max(8, Math.min(Math.round(a.left - r.left), Math.round((r.width || 0) - 300))) + 'px';
        // Every kind fits the room it opens in, scrolling inside it: measured in
        // Chromium at 1400×860, fourteen kinds ran past the window's edge and
        // the last group (where Code is greyed) could not be reached.
        if (r.height) box.style.maxHeight = Math.max(160, Math.round(r.height - top - 12)) + 'px';
      } catch (_) { /* no layout (a test): the sheet places it */ }
      room.appendChild(box);
      release = hold(() => finish(null));
      (kinds[0] || cancel).focus();
    });
  }

  // ── a step: the task form in its step mode, and Test this step ────────────
  /**
   * `P22-09`. A decorator for one step's text boxes: *Insert a field…* opens
   * the list of what earlier steps made (`fields()`, C-W), plus `extra`
   * sources (a For-each step's item); a `never` box says why.
   */
  function slotDecorator({ upstream = [], fields = null, extra = () => [] } = {}) {
    const labelOf = (id) => {
      if (id === 'start') return 'The start';
      const u = (Array.isArray(upstream) ? upstream : []).find((x) => x && String(x.id) === String(id));
      return u ? u.label : id;
    };
    return (input, { field, slot }) => decorateField(input, {
      slot, field, labelOf,
      pick: async (anchor) => {
        const load = typeof fields === 'function' ? fields : async () => ({ ok: true, sources: [] });
        const res = await load();
        return openFieldPicker(anchor, { load: () => res, extra: extra(res), holdEscape: hold, layer });
      },
    });
  }

  /** The palette's entry for `kind`. */
  const entryOf = (pal, kind) => (pal && Array.isArray(pal.kinds) ? pal.kinds.find((k) => k && k.kind === kind) || {} : {});

  /** `P22-12`. What `{{ item }}` holds inside a For-each step whose list is
   *  `listRef`: the whole item, and — when the fields listed show an example
   *  of that list — each key of its first item. */
  function itemSources(listRef, res) {
    const fieldsOut = [{ ref: '{{ item }}', path: 'the whole item', type: '' }];
    const ref = String(listRef || '').trim();
    const sources = res && Array.isArray(res.sources) ? res.sources : [];
    for (const src of sources) {
      for (const f of (src && Array.isArray(src.fields) ? src.fields : [])) {
        if (!f || String(f.ref) !== ref || !Array.isArray(f.example) || !f.example.length) continue;
        const first = f.example[0];
        if (first && typeof first === 'object' && !Array.isArray(first)) {
          for (const k of Object.keys(first)) {
            if (/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(k)) fieldsOut.push({ ref: `{{ item.${k} }}`, path: `item.${k}`, type: '', example: first[k] });
          }
        }
      }
    }
    return [{ node_id: 'item', label: 'Each item', origin: '', fields: fieldsOut }];
  }

  /** One step's editor in `formHost`: the task form for a task kind (with
   *  the hooks), the step forms for the rest. */
  function mountEditor(formHost, { step, tasks, pal, upstream, fields, problem, inForeach = null, onApply, onCancel, editInner,
    needs = null }) {
    const n = step || {};
    const kind = String(n.kind || 'llm');
    const entry = entryOf(pal, kind);
    const pickField = slotDecorator({
      upstream, fields,
      extra: (res) => (inForeach ? itemSources(inForeach(), res) : []),
    });
    if (TASK_KINDS.has(kind)) {
      if (typeof mountTaskFields !== 'function') return null;
      // The step in the form's own field names (`taskFields.js`'s `'node'`
      // mode): a step's `config` keys ARE `ScheduledTask`'s (design § 1.2).
      const asTask = { ...(n.config && typeof n.config === 'object' ? n.config : {}), name: n.label || '', task_type: kind };
      return mountTaskFields(formHost, {
        mode: 'node',
        task: asTask,
        // A step may not run a workflow (§ 8), nor this workflow's own start.
        tasks: (Array.isArray(tasks) ? tasks : []).filter((t) => t && t.task_type !== 'workflow'),
        slots: entry.slots && typeof entry.slots === 'object' ? entry.slots : null,
        pickField,
        // `P22-16`. A Prompt step's tools and answer shape, under its fields.
        extra: kind === 'llm' ? (el) => mountAiOptions(el, { node: n, palette: pal }) : null,
        problem,
        onSaved: (change) => { if (typeof onApply === 'function') onApply(change); },
        onCancel: () => { if (typeof onCancel === 'function') onCancel(); },
      });
    }
    if (!STEP_FIELD_KINDS.includes(kind)) return null;
    return mountStepFields(formHost, {
      node: n, palette: pal, upstream, pickField, problem, editInner, needs, openRoom,
      onApply: (change) => { if (typeof onApply === 'function') onApply(change); },
      onCancel: () => { if (typeof onCancel === 'function') onCancel(); },
    });
  }

  function node(host, {
    node: step, tasks = [], workflow = null, source = null, palette: pal = null, upstream = [], fields = null,
    problem = null, check = null, onApply, onCancel,
  } = {}) {
    const n = step || {};
    const wrap = _el('div', 'wf-step');
    // `P22-19`, `P22-24`. A step nobody has checked yet opens on that.
    const banner = check ? checkBanner(wrap, n, check) : null;
    const formHost = _el('div', 'wf-step-form');
    wrap.appendChild(formHost);
    host.appendChild(wrap);
    // `P22-12`. A For-each step's inner step is edited in this panel, in
    // place of the For-each's form, and handed back to it on Done.
    let inner = null;
    const editInner = (innerStep, done) => {
      if (inner) return;
      const box = _el('div', 'wf-step-inner');
      box.appendChild(_el('p', 'wf-step-inner-head', `For each item: ${KIND_WORDS[innerStep.kind] || innerStep.kind}`));
      box.appendChild(_el('p', 'wf-step-inner-note',
        'This runs once for each item. Insert a field… lists the item as “Each item”.'));
      const innerHost = _el('div', 'wf-step-form');
      box.appendChild(innerHost);
      formHost.hidden = true;
      if (test) test.hide(true);
      wrap.appendChild(box);
      const listNow = () => {
        const el = Array.from(formHost.querySelectorAll('[data-field]')).find((x) => x.dataset.field === 'list');
        return el ? el.value : ((n.config && n.config.list) || '');
      };
      const close = (made) => {
        if (!inner) return;
        const view = inner;
        inner = null;
        try { if (view && view.destroy) view.destroy(); } catch (_) { /* gone */ }
        box.remove();
        formHost.hidden = false;
        if (test) test.hide(false);
        done(made || null);
      };
      inner = mountEditor(innerHost, {
        step: innerStep, tasks, pal, upstream, fields, problem: null, inForeach: listNow,
        onApply: (made) => close({ ...made, kind: innerStep.kind }), onCancel: () => close(null), editInner: null,
      }) || { destroy() {} };
    };
    const form = mountEditor(formHost, {
      step: n, tasks, pal, upstream, fields, problem, onApply, onCancel, editInner,
      needs: check && Array.isArray(check.needs) ? check.needs : null,
    });
    if (!form) formHost.textContent = 'The step form did not load. Close the Workbench and open it again to retry.';
    let edited = false;
    const markEdited = () => { edited = true; syncHint(); };
    formHost.addEventListener('input', markEdited);
    formHost.addEventListener('change', markEdited);
    const test = n.id != null && source && typeof source.test === 'function'
      ? testSection(wrap, { step: n, source, workflow })
      : null;
    function syncHint() { if (test) test.formEdited(edited); }
    return {
      /** `B1136`. A palette read again while this step is open (the room was
       *  shown again): its form — and an inner step being edited — offer what
       *  was added, in place. The task form reads no palette list. */
      paletteChanged(next) {
        for (const f of [form, inner]) {
          if (f && typeof f.paletteChanged === 'function') { try { f.paletteChanged(next); } catch (_) { /* kept */ } }
        }
      },
      destroy() {
        if (banner) banner.destroy();
        if (test) test.destroy();
        try { if (inner && typeof inner.destroy === 'function') inner.destroy(); } catch (_) { /* gone */ }
        try { if (form && typeof form.destroy === 'function') form.destroy(); } catch (_) { /* gone */ }
        wrap.remove();
      },
    };
  }

  /**
   * `P22-19`, `P22-24` (wb-canvas-e). The banner of a step nobody has checked
   * yet (`check`, from the source: `{ origin, needs, plan(), looksRight() }`):
   * who decided it, what it needs (each with its door), what it would do —
   * the dry run's plan of the saved version, nothing run — and *Looks right*
   * (C-A's `PUT {checked}`; a person only, so a refusal is said as it came).
   */
  function checkBanner(parent, step, check) {
    let alive = true;
    const origin = Object.prototype.hasOwnProperty.call(CHECK_WORDS, check.origin) ? check.origin : 'drafted';
    const box = _el('section', 'wf-step-check');
    box.dataset.origin = origin;
    box.setAttribute('aria-label', CHECK_WORDS[origin]);
    box.appendChild(_el('p', 'wf-step-check-head', CHECK_WORDS[origin]));
    box.appendChild(_el('p', 'wf-step-check-note', CHECK_NOTES[origin]));
    for (const need of (Array.isArray(check.needs) ? check.needs : [])) {
      box.appendChild(needLine(need, { openRoom, cls: 'wf-step-check-need' }));
    }
    const planHead = _el('p', 'wf-step-check-sub', 'What it would do (planned; nothing ran):');
    const plan = _el('ul', 'wf-step-check-plan');
    plan.appendChild(_el('li', 'wf-step-check-wait', 'Planning…'));
    box.appendChild(planHead);
    box.appendChild(plan);
    const row = _el('div', 'wf-step-check-buttons');
    const yes = _button('wf-step-check-yes', 'Looks right', 'Say this step is right as it is. Nothing else changes.');
    row.appendChild(yes);
    box.appendChild(row);
    const said = _el('p', 'wf-step-check-said');
    said.setAttribute('role', 'status');
    said.setAttribute('aria-live', 'polite');
    box.appendChild(said);
    parent.appendChild(box);

    if (typeof check.plan === 'function') {
      Promise.resolve().then(() => check.plan()).then((r) => {
        if (!alive) return;
        if (!r || r.ok === false) {
          plan.replaceChildren(_el('li', 'wf-step-check-wait',
            `It could not be planned: ${String((r && r.sentence) || 'no answer').replace(/\.$/, '')}.`));
          return;
        }
        const lines = Array.isArray(r.lines) ? r.lines.map(String).filter(Boolean) : null;
        if (!lines) {
          plan.replaceChildren(_el('li', 'wf-step-check-wait', r.declined
            ? `It cannot be planned yet: ${String(r.declined).replace(/\.$/, '')}.` : 'The plan did not reach this step.'));
          return;
        }
        plan.replaceChildren(...(lines.length ? lines : ['It would do nothing.']).map((l) => _el('li', null, l)));
      }, () => { if (alive) plan.replaceChildren(_el('li', 'wf-step-check-wait', 'It could not be planned.')); });
    } else {
      planHead.hidden = true;
      plan.hidden = true;
    }

    yes.addEventListener('click', async () => {
      if (typeof check.looksRight !== 'function') return;
      yes.disabled = true;
      said.textContent = 'Saying it looks right…';
      let r = null;
      try { r = await check.looksRight(); } catch (err) { r = { ok: false, sentence: String((err && (err.sentence || err.message)) || '') }; }
      if (!alive) return;
      if (!r || r.ok === false) {
        yes.disabled = false;
        said.textContent = `Not checked: ${String((r && r.sentence) || 'the server refused').replace(/\.$/, '')}.`;
        said.classList.add('wf-step-check-refusal');
        return;
      }
      box.dataset.checked = 'true';
      box.replaceChildren(_el('p', 'wf-step-check-head', CHECKED_WORDS));
      if (typeof onChanged === 'function') { try { onChanged(step.id); } catch (_) { /* the mark only */ } }
    });
    return { destroy() { alive = false; box.remove(); } };
  }

  /**
   * `P22-20` (wb-canvas-e). *Why did this fail?* under a failed step's record
   * (or a failed item's): asks a model through the run's own source
   * (`explain`, C-A's explain route; nothing is written) and shows its
   * reading AS TEXT, labelled as coming from what the step was handed; each
   * change it proposes as a row — what it is now, what it would be, and in
   * words when it changes where the request goes (`where`) or when the new
   * value came out of the run (`from_run`); what was left out (`left_out`);
   * then *Apply* (the room's `fixer`, with the proposal's base version),
   * *Undo* (`restoreVersion` of `undo_version`) and *Run it again*.
   */
  function whySection(parent, { nodeId, item = null, explain, current = null, palette: pal = null }) {
    let alive = true;
    const box = _el('section', 'wf-why');
    box.setAttribute('aria-label', 'Why did this fail?');
    const ask = _button('wf-why-ask', 'Why did this fail?', WHY_TITLE);
    box.appendChild(ask);
    const said = _el('p', 'wf-why-said');
    said.setAttribute('role', 'status');
    said.setAttribute('aria-live', 'polite');
    box.appendChild(said);
    const answerHost = _el('div', 'wf-why-answer');
    answerHost.hidden = true;
    box.appendChild(answerHost);
    parent.appendChild(box);

    /** Where a proposed `where` change still sends: the step's Integration,
     *  or its MCP tool's server, by name. */
    const destination = () => {
      const c = current && current.config && typeof current.config === 'object' ? current.config : {};
      const list = (key) => (pal && Array.isArray(pal[key]) ? pal[key] : []);
      const integ = list('integrations').find((i) => i && String(i.id) === String(c.integration));
      if (integ) return String(integ.name || '');
      const tool = list('mcp_tools').find((t) => t && String(t.qualified_name) === String(c.tool));
      return tool ? String(tool.server_name || tool.name || '') : '';
    };

    function draw(r) {
      answerHost.replaceChildren();
      const head = _el('p', 'wf-why-head', 'The model’s reading');
      answerHost.appendChild(head);
      answerHost.appendChild(_el('p', 'wf-why-note', READING_NOTE));
      answerHost.appendChild(_el('p', 'wf-why-text', String(r.why == null ? '' : r.why).trim() || 'It gave no reason.'));
      if (r.model) answerHost.appendChild(_el('p', 'wf-why-model', `Asked: ${String(r.model)}`));
      if (r.changed_since_run) {
        answerHost.appendChild(_el('p', 'wf-why-note wf-why-changed',
          'This step has changed since this run. A change below is to the step as it is now.'));
      }
      const proposal = r.proposal && typeof r.proposal === 'object' ? r.proposal : null;
      const changes = proposal && Array.isArray(proposal.changes) ? proposal.changes.filter((c) => c && typeof c === 'object') : [];
      if (proposal && changes.length) {
        answerHost.appendChild(_el('p', 'wf-why-sub', 'What it would change:'));
        const ul = _el('ul', 'wf-why-changes');
        for (const c of changes) {
          const li = _el('li', 'wf-why-change');
          if (c.field != null) li.dataset.field = String(c.field);
          li.appendChild(_el('p', 'wf-why-field', String(c.words || c.field || 'A setting')));
          const diff = _el('div', 'wf-why-diff');
          diff.appendChild(_el('span', 'wf-why-label', 'Now'));
          diff.appendChild(_el('pre', 'wf-why-before', pretty(c.before) || '(empty)'));
          diff.appendChild(_el('span', 'wf-why-label', 'It would be'));
          diff.appendChild(_el('pre', 'wf-why-after', pretty(c.after) || '(empty)'));
          li.appendChild(diff);
          if (c.where === true) li.appendChild(_el('p', 'wf-why-where', whereWords(destination())));
          if (c.from_run === true) li.appendChild(_el('p', 'wf-why-from-run', FROM_RUN_WORDS));
          ul.appendChild(li);
        }
        answerHost.appendChild(ul);
      }
      const left = (Array.isArray(r.left_out) ? r.left_out : []).map((x) => String(x == null ? '' : x)).filter(Boolean);
      if (left.length) {
        answerHost.appendChild(_el('p', 'wf-why-sub', 'It also suggested these, which are yours to decide:'));
        const ul = _el('ul', 'wf-why-left');
        for (const line of left) ul.appendChild(_el('li', null, line));
        answerHost.appendChild(ul);
      }
      if (!(proposal && changes.length)) {
        answerHost.appendChild(_el('p', 'wf-why-note', 'It proposes no change that can be applied here.'));
      } else if (fixer && typeof fixer.apply === 'function') {
        answerHost.appendChild(applyRow(proposal));
      }
      answerHost.hidden = false;
    }

    function applyRow(proposal) {
      const row = _el('div', 'wf-why-buttons');
      const apply = _button('wf-why-apply', 'Apply', 'Save this change as a new version of the workflow. Undo puts the version before it back.');
      const undo = _button('wf-why-undo', 'Undo', 'Put the version before this fix back');
      const again = _button('wf-why-again', 'Run it again', 'Run the workflow now, as it is saved');
      undo.hidden = true;
      again.hidden = true;
      const out = _el('p', 'wf-why-applied');
      out.setAttribute('role', 'status');
      out.setAttribute('aria-live', 'polite');
      let undoVersion = null;
      apply.addEventListener('click', async () => {
        apply.disabled = true;
        out.textContent = 'Applying…';
        let r = null;
        try { r = await fixer.apply(proposal); } catch (err) { r = { ok: false, sentence: String((err && (err.sentence || err.message)) || '') }; }
        if (!alive) return;
        if (!r || r.ok === false) {
          apply.disabled = false;
          out.textContent = `Not applied: ${String((r && r.sentence) || 'the server refused').replace(/\.$/, '')}.`;
          return;
        }
        undoVersion = r.undoVersion != null ? r.undoVersion : proposal.base_version;
        out.textContent = r.sentence || 'Applied.';
        apply.hidden = true;
        undo.hidden = !(typeof fixer.undo === 'function' && undoVersion != null);
        again.hidden = typeof fixer.runAgain !== 'function';
      });
      undo.addEventListener('click', async () => {
        undo.disabled = true;
        let r = null;
        try { r = await fixer.undo(undoVersion); } catch (err) { r = { ok: false, sentence: String((err && (err.sentence || err.message)) || '') }; }
        if (!alive) return;
        if (!r || r.ok === false) {
          undo.disabled = false;
          out.textContent = `Not undone: ${String((r && r.sentence) || 'the server refused').replace(/\.$/, '')}.`;
          return;
        }
        out.textContent = r.sentence || 'Undone.';
        undo.hidden = true;
      });
      again.addEventListener('click', () => { try { fixer.runAgain(); } catch (_) { /* the room says */ } });
      for (const b of [apply, undo, again]) row.appendChild(b);
      const wrap = _el('div', 'wf-why-apply-row');
      wrap.appendChild(row);
      wrap.appendChild(out);
      return wrap;
    }

    ask.addEventListener('click', async () => {
      ask.disabled = true;
      said.textContent = 'Asking the model… it reads this step’s record.';
      let r = null;
      try { r = await explain({ nodeId, item }); } catch (err) { r = { ok: false, sentence: String((err && (err.sentence || err.message)) || '') }; }
      if (!alive) return;
      ask.disabled = false;
      if (!r || r.ok === false) {
        said.textContent = `Not answered: ${String((r && r.sentence) || 'no answer').replace(/\.$/, '')}.`;
        said.classList.add('wf-why-refusal');
        return;
      }
      said.textContent = '';
      said.classList.remove('wf-why-refusal');
      ask.textContent = 'Ask again';
      draw(r);
    });
    return { destroy() { alive = false; box.remove(); } };
  }

  /** `P22-08`. *Test this step*: one step, on an input the person chose, and
   *  nothing else. A step whose effects reach past Pantheon's own data asks
   *  first with its dry plan (the route decides which, from `effects` it does
   *  not send the browser — design § 0.11); a pinned sample is marked on the
   *  canvas and never used by a scheduled run. */
  function testSection(parent, { step, source }) {
    let pinned = step.pinned != null ? step.pinned : null;
    let lastUsed = null;       // `input_used` of the last answer, for *Pin this*
    let busy = false;
    let alive = true;
    const box = _el('section', 'wf-test');
    box.setAttribute('aria-label', 'Test this step');
    box.appendChild(_el('h4', 'wf-test-head', 'Test this step'));
    box.appendChild(_el('p', 'wf-test-lede',
      'Runs this step on its own, on the input you choose. ' + NOTHING_ELSE.replace('Nothing else ran', 'Nothing else runs')));
    const edits = _el('p', 'wf-test-edits', 'Your changes above are not in the test until you press Done.');
    edits.hidden = true;
    box.appendChild(edits);

    const pick = _el('label', 'wf-test-field');
    pick.appendChild(_el('span', 'wf-test-label', 'Input'));
    const sel = _el('select', 'wf-test-source');
    pick.appendChild(sel);
    box.appendChild(pick);
    const text = _el('textarea', 'wf-test-input');
    text.rows = 5;
    text.setAttribute('aria-label', 'The input for the test, as text or JSON');
    text.placeholder = 'Text, or JSON such as {"subject": "Your statement is ready"}';
    box.appendChild(text);
    const pinNote = _el('p', 'wf-test-pin-note', PIN_SENTENCE);
    box.appendChild(pinNote);

    const row = _el('div', 'wf-test-buttons');
    const go = _button('wf-test-go', 'Test');
    const pinBtn = _button('wf-test-pin', 'Pin this', 'Keep this input on the step, to test with again');
    const unpinBtn = _button('wf-test-unpin', 'Unpin');
    for (const b of [go, pinBtn, unpinBtn]) row.appendChild(b);
    box.appendChild(row);

    const said = _el('p', 'wf-test-say');
    said.setAttribute('role', 'status');
    said.setAttribute('aria-live', 'polite');
    box.appendChild(said);
    const confirm = _el('div', 'wf-test-confirm');
    confirm.setAttribute('role', 'group');
    confirm.setAttribute('aria-label', 'Testing this does something real');
    confirm.hidden = true;
    box.appendChild(confirm);
    const result = _el('div', 'wf-test-result');
    result.hidden = true;
    box.appendChild(result);
    // What is typed or chosen here is a test's input, not an edit to the step:
    // the canvas counts `input` / `change` reaching the panel as unsaved edits
    // (`B1052`, `B1067`), and found in Chromium, a test input typed on one step
    // made opening the next one ask about "changes that are not saved".
    for (const type of ['input', 'change']) box.addEventListener(type, (e) => e.stopPropagation());
    parent.appendChild(box);

    function syncSources() {
      const keep = sel.value;
      sel.replaceChildren();
      for (const s of TEST_SOURCES) {
        if (s.source === 'pinned' && pinned == null) continue;
        const o = _el('option', null, s.label);
        o.value = s.source;
        sel.appendChild(o);
      }
      const values = TEST_SOURCES.map((s) => s.source).filter((v) => v !== 'pinned' || pinned != null);
      sel.value = values.includes(keep) ? keep : (pinned != null ? 'pinned' : 'last');
      syncInput();
    }
    function syncInput() {
      const s = sel.value;
      text.hidden = !(s === 'custom' || s === 'pinned');
      text.readOnly = s === 'pinned';
      if (s === 'pinned') text.value = pretty(pinned && typeof pinned === 'object' && 'data' in pinned ? pinned.data : pinned);
      unpinBtn.hidden = pinned == null;
      pinBtn.hidden = !(s === 'custom' ? text.value.trim() : lastUsed != null);
      pinNote.hidden = pinned == null && pinBtn.hidden;
    }
    sel.addEventListener('change', () => { if (sel.value === 'custom' && text.readOnly) text.value = ''; syncInput(); });
    text.addEventListener('input', syncInput);

    function readCustom() {
      const raw = text.value;
      const t = raw.trim();
      if (!t) return undefined;
      try { return JSON.parse(t); } catch (_) { return raw; }
    }

    function sayLine(words, refusal = false) {
      said.textContent = words || '';
      said.classList.toggle('wf-test-refusal', !!refusal);
    }

    async function run(confirmed) {
      if (busy) return;
      busy = true;
      go.disabled = true;
      go.textContent = 'Testing…';
      confirm.hidden = true;
      const chosen = sel.value;
      const args = { source: chosen, confirm: !!confirmed };
      if (chosen === 'custom') args.input = readCustom();
      sayLine(confirmed ? 'Running it for real…' : 'Testing…');
      let reply = null;
      let refusal = '';
      try {
        reply = await source.test(step.id, args);
      } catch (err) {
        refusal = String((err && (err.sentence || err.message)) || 'The test could not run.');
      }
      busy = false;
      if (!alive) return;
      go.disabled = false;
      go.textContent = 'Test';
      if (!reply || reply.ok === false) {
        sayLine(`Not tested: ${(refusal || (reply && reply.sentence) || 'the test could not run').replace(/\.$/, '')}.`, true);
        return;
      }
      if (reply.input_used !== undefined) lastUsed = reply.input_used;
      if (reply.outcome === 'needs_confirmation') {
        showConfirm(reply, args);
      } else {
        showResult(reply);
      }
      syncInput();
    }

    function droppedLine(reply) {
      const dropped = Array.isArray(reply && reply.dropped) ? reply.dropped.map(String) : [];
      return dropped.length
        ? `Left out, because this step is not handed them: ${dropped.join(', ')}.` : '';
    }

    function showConfirm(reply, args) {
      result.hidden = true;
      confirm.replaceChildren();
      confirm.appendChild(_el('p', 'wf-test-confirm-head',
        'Testing this step does something real. This is what it would do:'));
      const plan = _el('ol', 'wf-test-plan');
      for (const line of (Array.isArray(reply.plan) ? reply.plan : [])) {
        plan.appendChild(_el('li', null, String(line && typeof line === 'object' ? (line.detail || '') : line)));
      }
      confirm.appendChild(plan);
      const effects = (Array.isArray(reply.effects) ? reply.effects : []).map(String).filter(Boolean);
      if (effects.length) {
        const ul = _el('ul', 'wf-test-effects');
        for (const e of effects) ul.appendChild(_el('li', null, e));
        confirm.appendChild(ul);
      }
      const dl = droppedLine(reply);
      if (dl) confirm.appendChild(_el('p', 'wf-test-dropped', dl));
      const buttons = _el('div', 'wf-test-buttons');
      const yes = _button('wf-test-yes', 'Run it for real');
      const no = _button('wf-test-no', 'Cancel');
      yes.addEventListener('click', () => { if (args.source === sel.value) run(true); else run(false); });
      no.addEventListener('click', () => { confirm.hidden = true; sayLine('Not tested. Nothing ran.'); go.focus(); });
      buttons.appendChild(yes);
      buttons.appendChild(no);
      confirm.appendChild(buttons);
      confirm.hidden = false;
      sayLine('Nothing has run yet.');
      yes.focus();
    }

    function showResult(reply) {
      confirm.hidden = true;
      result.replaceChildren();
      const w = statusWords(reply.status || 'success');
      const head = _el('p', 'wf-test-outcome');
      head.dataset.tone = w.tone;
      const mark = _el('span', 'wf-test-mark', w.mark);
      mark.setAttribute('aria-hidden', 'true');
      head.appendChild(mark);
      const took = Number(reply.took_ms);
      head.appendChild(_el('span', 'wf-test-word',
        `Test: ${w.word}` + (Number.isFinite(took) && took >= 0 ? ` · ${took < 1000 ? took + ' ms' : (took / 1000).toFixed(1) + ' s'}` : '')
        + (reply.model ? ` · ${reply.model}` : '')));
      result.appendChild(head);
      result.appendChild(_section('What it made', pretty(reply.text), { open: true }));
      if (reply.data != null && !(typeof reply.data === 'object' && !Array.isArray(reply.data) && !Object.keys(reply.data).length)) {
        result.appendChild(_section('Its data', pretty(reply.data)));
      }
      if (reply.input_used != null) result.appendChild(_section('What it was handed', pretty(reply.input_used)));
      const steps = Array.isArray(reply.steps) ? reply.steps : [];
      if (steps.length) result.appendChild(stepsPart(steps, false));
      const dl = droppedLine(reply);
      if (dl) result.appendChild(_el('p', 'wf-test-dropped', dl));
      result.appendChild(_el('p', 'wf-test-alone', NOTHING_ELSE));
      result.hidden = false;
      sayLine('');
    }

    async function setPin(data) {
      if (typeof source.setPin !== 'function') return;
      let reply = null;
      let refusal = '';
      try { reply = await source.setPin(step.id, data); } catch (err) {
        refusal = String((err && (err.sentence || err.message)) || '');
      }
      if (!alive) return;
      if (refusal || (reply && reply.ok === false)) {
        sayLine(`Not ${data == null ? 'unpinned' : 'pinned'}: ${(refusal || reply.sentence || 'it could not be saved').replace(/\.$/, '')}.`, true);
        return;
      }
      pinned = data;
      syncSources();
      if (typeof onChanged === 'function') { try { onChanged(step.id); } catch (_) { /* the mark only */ } }
      const dl = droppedLine(reply);
      sayLine(data == null ? 'Unpinned. Test uses another input now.'
        : `Pinned. ${PIN_SENTENCE}${dl ? ' ' + dl : ''}`);
    }

    go.addEventListener('click', () => run(false));
    pinBtn.addEventListener('click', () => {
      // What to pin: what the last test was actually handed (its fields), or
      // what is typed here.
      let data;
      if (sel.value === 'custom' && text.value.trim()) data = readCustom();
      else if (lastUsed && typeof lastUsed === 'object' && 'data' in lastUsed) data = lastUsed.data;
      else data = lastUsed;
      if (data === undefined || data === null || data === '') { sayLine('There is nothing to pin yet.', true); return; }
      setPin(data);
    });
    unpinBtn.addEventListener('click', () => setPin(null));
    syncSources();

    return {
      formEdited(on) { edits.hidden = !on; },
      hide(on) { box.hidden = !!on; },
      destroy() { alive = false; box.remove(); },
    };
  }

  /** A run's step log: the Tasks card's renderer when there is one. */
  function stepsPart(steps, open) {
    const d = _el('details', 'wf-record-part wf-record-steps');
    if (open) d.open = true;
    d.appendChild(_el('summary', null, `Steps (${steps.length})`));
    const body = _el('div', 'wf-record-steps-body');
    if (typeof renderSteps === 'function') {
      // `tasks.js:renderRunSteps` escapes every value it is given with
      // `ui.js:esc`: its markup, not the run's.
      body.innerHTML = renderSteps({ steps }, { open: true, summary: 'Steps' });
    } else {
      const ol = _el('ol', 'wf-record-lines');
      for (const s of steps) ol.appendChild(_el('li', null, String((s && (s.detail || s.tool)) || '')));
      body.appendChild(ol);
    }
    d.appendChild(body);
    return d;
  }

  // ── a workflow's start: the task form in its trigger mode ─────────────────
  function start(host, { triggerTask = null, tasks = [], onSaved, onCancel } = {}) {
    const wrap = _el('div', 'wf-start');
    host.appendChild(wrap);
    const form = typeof mountTaskFields === 'function'
      ? mountTaskFields(wrap, {
        mode: 'trigger',
        task: triggerTask,
        tasks,
        // The start is saved through `PUT /api/tasks/{id}` when its own Save
        // is pressed (it is not part of the draft), so the canvas says so.
        onSaved: (row) => {
          if (typeof onSaved !== 'function') return undefined;
          const saved = row && typeof row === 'object' ? { ...row } : {};
          saved.sentence = 'Saved what starts this workflow.';
          return onSaved(saved);
        },
        onCancel: () => { if (typeof onCancel === 'function') onCancel(); },
      })
      : null;
    if (!form) wrap.textContent = 'The form did not load. Close the Workbench and open it again to retry.';
    return {
      destroy() {
        try { if (form && typeof form.destroy === 'function') form.destroy(); } catch (_) { /* gone */ }
        wrap.remove();
      },
    };
  }

  // ── a step of a run: what it was handed and what it made (`P22-07`) ───────
  /** `P22-11`, `P22-17`. A waiting step: what it waits for, and — when it
   *  waits for a yes — the gate card, answered with `approve_task` (Allow
   *  once) or `deny` through the run's own source (C-W's answer route). */
  function waitingPart(rec, { answer = null, nodeId = '', item = null } = {}) {
    const wt = rec && rec.waiting && typeof rec.waiting === 'object' ? rec.waiting : {};
    const part = _el('section', 'wf-record-waiting');
    part.setAttribute('aria-label', 'What this step is waiting for');
    part.appendChild(_el('p', 'wf-record-waiting-head', waitingWords(wt)
      + (wt.since ? ` · since ${_short(wt.since)}` : '')));
    const said = _el('p', 'wf-record-waiting-said');
    said.setAttribute('role', 'status');
    said.setAttribute('aria-live', 'polite');
    if (wt.kind === 'time') {
      part.appendChild(_el('p', 'wf-record-note', wt.until
        ? `It goes on at ${_short(wt.until)}, or as soon after as Pantheon is idle.`
        : 'It goes on when its wait is over, as soon as Pantheon is idle.'));
    } else if (wt.kind === 'idle') {
      part.appendChild(_el('p', 'wf-record-note', 'Pantheon was busy with something you were doing. This step runs '
        + 'again as soon as Pantheon is idle; the steps before it are not run again.'));
    } else if (wt.kind === 'approval') {
      if (wt.until) part.appendChild(_el('p', 'wf-record-note', `If nobody answers by ${_short(wt.until)}, it is not done and the step takes its “if it fails” way.`));
      if (wt.approval && typeof answer === 'function') {
        part.appendChild(approvalBox(wt.approval, {
          allowValue: 'approve_task',
          allowLabel: 'Allow once',
          onDecide: async (decision) => {
            said.textContent = decision === 'deny' ? 'Denying…' : 'Allowing it once…';
            const r = await answer({ nodeId, item, approvalId: wt.approval.approval_id, decision });
            if (!r || r.ok === false) throw new Error((r && r.sentence) || 'The answer was not taken.');
            said.textContent = r.sentence || (decision === 'deny' ? 'Denied. The step takes its “if it fails” way.'
              : 'Allowed once. The run goes on.');
            if (typeof onAnswered === 'function') { try { onAnswered({ nodeId, item, decision, reply: r }); } catch (_) { /* the room's */ } }
          },
          onError: (message) => { said.textContent = `Not answered: ${String(message).replace(/\.$/, '')}.`; },
        }));
        part.appendChild(_el('p', 'wf-record-note', ANSWER_WORDS));
      } else {
        part.appendChild(_el('p', 'wf-record-note', 'Its question is in your notifications.'));
      }
    }
    part.appendChild(said);
    return part;
  }

  /** `P22-12`. A For-each step's items: each a line, the failed one first
   *  to be read. */
  function itemsPart(items, nodeId, answer, why = null) {
    const d = _el('details', 'wf-record-part wf-record-items');
    const failed = items.filter((r) => runStatusTone(r.status) === 'error');
    if (failed.length || items.some((r) => r.status === 'waiting')) d.open = true;
    d.appendChild(_el('summary', null, `Items (${items.length})`));
    const ol = _el('ol', 'wf-record-item-list');
    const total = items.length;
    for (const r of items) {
      const li = _el('li', 'wf-record-item');
      const w = r.status === 'waiting' ? { tone: 'pending', mark: OUTCOME_MARKS.pending, word: waitingWords(r.waiting) } : statusWords(r.status);
      li.dataset.tone = w.tone;
      const mark = _el('span', 'wf-record-mark', w.mark);
      mark.setAttribute('aria-hidden', 'true');
      li.appendChild(mark);
      const first = itemAnswer(r);
      li.appendChild(_el('span', 'wf-record-item-word',
        `Item ${Number(r.item) + 1} of ${total}: ${w.word}${first ? ` — ${first.length > 160 ? first.slice(0, 159) + '…' : first}` : ''}`));
      if (r.status === 'waiting') li.appendChild(waitingPart(r, { answer, nodeId, item: Number(r.item) }));
      // `P22-20`. A failed item is explained on its own (`item`).
      if (why && w.tone === 'error') why(li, Number(r.item));
      ol.appendChild(li);
    }
    d.appendChild(ol);
    return d;
  }

  function record(host, {
    node: step = null, record: rec = null, run = null, items = [], answer = null,
    explain = null, current = null, palette: pal = null,
  } = {}) {
    const n = step || {};
    const wrap = _el('div', 'wf-record');
    host.appendChild(wrap);
    const kind = String((rec && rec.kind) || n.kind || '');
    const status = rec ? rec.status : null;
    const w = rec && status === 'waiting'
      ? { tone: 'pending', mark: OUTCOME_MARKS.pending, word: waitingWords(rec.waiting) }
      : statusWords(status);
    const head = _el('p', 'wf-record-head');
    head.dataset.tone = w.tone;
    const mark = _el('span', 'wf-record-mark', w.mark);
    mark.setAttribute('aria-hidden', 'true');
    head.appendChild(mark);
    head.appendChild(_el('span', 'wf-record-word', w.word));
    const label = String((rec && rec.label) || n.label || '');
    wrap.appendChild(_el('p', 'wf-record-kind', [KIND_WORDS[kind] || kind, label].filter(Boolean).join(' · ')));
    wrap.appendChild(head);

    const itemRecs = Array.isArray(items) ? items : [];
    const nodeId = String(n.id || (rec && rec.node_id) || '');
    // `P22-20`. *Why did this fail?*, on a failed record only, when the run's
    // source can ask (C-A).
    const whys = [];
    const why = typeof explain === 'function'
      ? (parent, item) => whys.push(whySection(parent, { nodeId, item, explain, current, palette: pal }))
      : null;
    if (rec && status === 'waiting') wrap.appendChild(waitingPart(rec, { answer, nodeId, item: null }));
    if (itemRecs.length) wrap.appendChild(itemsPart(itemRecs, nodeId, answer, why));
    if (!rec && itemRecs.length) {
      // A For-each step whose own record is not written yet: its items are
      // what there is to read.
    } else if (!rec) {
      const cleared = !!(run && (run.cleared === true));
      // The server's sentence names the window as it is set; a fixed number
      // here was false once `workflow_node_records_days` was changed.
      const clearedText = (run && typeof run.cleared_sentence === 'string' && run.cleared_sentence)
        || 'Its step details were cleared after the time Pantheon keeps them (workflow_node_records_days).';
      wrap.appendChild(_el('p', 'wf-record-note', cleared
        ? clearedText
        : 'This step was not reached in this run, so it was handed nothing and made nothing.'));
    } else {
      const times = [_when(rec.started_at), _took(rec.started_at, rec.finished_at)].filter(Boolean).join(' · ');
      if (times) wrap.appendChild(_el('p', 'wf-record-times', times));
      const failed = runStatusTone(status) === 'error';
      if (rec.dry) wrap.appendChild(_el('p', 'wf-record-note', 'A dry run: this is what it would have done. Nothing ran.'));

      // What it was handed — open when the step failed, which is where a
      // person looks first (`P22-07`'s Verify: without being told where).
      const input = readCapped(rec.input);
      const handed = _el('details', 'wf-record-part wf-record-input');
      if (failed) handed.open = true;
      handed.appendChild(_el('summary', null, 'What it was handed'));
      if (kind === 'action' || kind === 'research') handed.appendChild(_el('p', 'wf-record-note', DOES_NOT_READ));
      if (rec.input_summary) handed.appendChild(_el('p', 'wf-record-summary', String(rec.input_summary)));
      const inputText = pretty(input.value);
      if (inputText) handed.appendChild(_el('pre', 'wf-record-pre', inputText));
      else if (!rec.input_summary) handed.appendChild(_el('p', 'wf-record-note', 'Nothing: it was the first step and its start hands it nothing.'));
      if (input.note) handed.appendChild(_el('p', 'wf-record-note', input.note));
      wrap.appendChild(handed);

      if (failed || rec.error) {
        wrap.appendChild(_section('What went wrong', String(rec.error || 'It failed and left no message.'),
          { open: true, cls: 'wf-record-error' }));
      }
      if (failed && why && !rec.dry) why(wrap, null);
      const output = readCapped(rec.output);
      const out = output.value && typeof output.value === 'object' && !Array.isArray(output.value) ? output.value : { text: output.value };
      const made = _el('details', 'wf-record-part wf-record-output');
      if (!failed) made.open = true;
      made.appendChild(_el('summary', null, 'What it made'));
      const madeText = pretty(out.text);
      if (madeText) made.appendChild(_el('pre', 'wf-record-pre', madeText));
      if (out.data != null && pretty(out.data) && !(typeof out.data === 'object' && !Object.keys(out.data).length)) {
        made.appendChild(_el('p', 'wf-record-note', 'Its data:'));
        made.appendChild(_el('pre', 'wf-record-pre', pretty(out.data)));
      }
      if (!madeText && !(out.data != null && pretty(out.data))) made.appendChild(_el('p', 'wf-record-note', 'Nothing.'));
      if (output.note) made.appendChild(_el('p', 'wf-record-note', output.note));
      wrap.appendChild(made);

      let steps = rec.steps;
      if (typeof steps === 'string') { try { steps = JSON.parse(steps); } catch (_) { steps = []; } }
      if (Array.isArray(steps) && steps.length) wrap.appendChild(stepsPart(steps, false));
      if (rec.model) wrap.appendChild(_el('p', 'wf-record-model', `Model: ${rec.model}`));
    }
    if (typeof onRecordShown === 'function') {
      try { onRecordShown({ node: n, record: rec, run }); } catch (_) { /* the room's sentence only */ }
    }
    return { destroy() { for (const x of whys) x.destroy(); wrap.remove(); } };
  }

  return { palette, node, start, record };
}

export default {
  createWorkflowPanels, PALETTE_KINDS, TEST_SOURCES, PIN_SENTENCE, NOTHING_ELSE, DOES_NOT_READ, ANSWER_WORDS,
  CHECK_WORDS, CHECK_NOTES, CHECKED_WORDS, WHY_TITLE, READING_NOTE, whereWords, FROM_RUN_WORDS,
};
