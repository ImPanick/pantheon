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

/** C-W's `origin` words for where a field was seen — keyed by the server's
 *  own three (`workflow_effects.ORIGIN_LAST_RUN` / `ORIGIN_PIN` /
 *  `ORIGIN_DECLARED`). The start's `declared` fields are what every run of
 *  its kind is handed (a webhook's body, an event's fields), not an answer. */
const ORIGINS = Object.freeze({
  last_run: 'from the last run',
  pin: 'from the pinned sample',
  declared: 'what the step promises to answer',
});
const START_DECLARED = 'what every run is handed';

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

/** "from the last run, 2 Oct 07:00" — where a source's fields were seen.
 *  `kind` is the source's (`'start'` for what started the run). */
export function originWords(origin, at, kind) {
  const o = String(origin || '');
  if (o === 'declared' && kind === 'start') return START_DECLARED;
  const base = ORIGINS[o] || '';
  if (!base) return '';
  return o === 'last_run' && at ? `${base}, ${_when(at)}` : base;
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

// ── references: the server's grammar, read the server's way ───────────────
// The grammar is `src/workflow_refs.py`'s (§ 1.1, widened by `B1879`), and
// this is a port of its reader (`_parse_ref_at`), character for character:
// the same roots (`steps`, `item`, `run`, `now`), the same segments and
// bounds, the same closed list of changes after `|`. It decides nothing — the
// server checks every reference whole at save and at run — but what it SAYS
// must agree with the server: the "Uses:" line names what a field reads,
// changes included (a reference with `| upper` was not one to the old
// pattern here, so the line left it out).

/** `B1879`. The changes a reference may end in — `workflow_refs.FILTERS`,
 *  which a test holds equal to this list. Closed: a name not here is not a
 *  reference. */
export const FILTERS = Object.freeze(['default', 'upper', 'lower', 'trim', 'length', 'join', 'split',
  'json', 'from_json', 'number', 'date', 'first', 'last']);
/** Which changes take an argument after `:`, and what they read bare. */
export const FILTER_ARG_DEFAULTS = Object.freeze({ default: '', join: ', ', split: ',', date: '%Y-%m-%d' });
const DATE_DIRECTIVES = 'YmdHMSyjIpaAbBzZ%';
const RUN_KEYS = ['id', 'workflow'];
const WS = ' \t\r\n';
const KEY_CHAR = /^[A-Za-z0-9_]$/;
const REF_MAX_SEGMENTS = 16;
const FILTERS_MAX = 8;

const isWs = (c) => c !== undefined && c !== '' && WS.includes(c);
const isKeyChar = (c) => c !== undefined && KEY_CHAR.test(c);
const skipWs = (t, i) => { while (i < t.length && isWs(t[i])) i += 1; return i; };
const wordAt = (t, i, w) => t.startsWith(w, i) && !isKeyChar(t[i + w.length]);
/** The match of sticky `re` at `i`, or null. */
function matchAt(re, t, i) { re.lastIndex = i; const m = re.exec(t); return m ? m[0] : null; }
const KEY_RE = /[A-Za-z_][A-Za-z0-9_]*/y;
const NODE_RE = /[A-Za-z0-9_-]+/y;
const INDEX_RE = /0|[1-9][0-9]*/y;
const ARG_NUMBER_RE = /-?(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,6})?/y;
const controlIn = (s) => Array.from(s).some((c) => c.charCodeAt(0) < 0x20 || c.charCodeAt(0) === 0x7F);
/** How many characters `s` has as the server counts them (code points: an
 *  emoji is one, where `.length` counts two). */
const chars = (s) => Array.from(s).length;

function dateOk(p) {
  for (let i = 0; i < p.length; i += 1) {
    if (p[i] !== '%') continue;
    if (i + 1 >= p.length || !DATE_DIRECTIVES.includes(p[i + 1])) return false;
    i += 1;
  }
  return true;
}

/** The changes after a path: `{ filters: [[name, arg]], end }` (`end` before
 *  the blank that ends it), or null when one is not on the list or takes no
 *  such argument — the server's `_parse_filters`. */
function parseFilters(t, i) {
  const filters = [];
  for (;;) {
    let j = skipWs(t, i);
    if (t[j] !== '|') return { filters, end: i };
    j = skipWs(t, j + 1);
    const name = matchAt(KEY_RE, t, j);
    if (!name || !FILTERS.includes(name)) return null;
    j += name.length;
    let arg = null;
    const k = skipWs(t, j);
    if (t[k] === ':') {
      if (!(name in FILTER_ARG_DEFAULTS)) return null;
      const a = skipWs(t, k + 1);
      if (t[a] === '"') {
        const close = t.indexOf('"', a + 1);
        if (close < 0) return null;
        arg = t.slice(a + 1, close);
        if (chars(arg) > 64 ||/[\\{}]/.test(arg) || controlIn(arg)) return null;
        j = close + 1;
      } else {
        const num = matchAt(ARG_NUMBER_RE, t, a);
        if (!num || isKeyChar(t[a + num.length])) return null;
        if (name !== 'default') return null;          // join, split, date take text
        arg = Number(num);
        j = a + num.length;
      }
      if (name === 'split' && arg === '') return null;
      if (name === 'date' && (arg === '' || !dateOk(arg))) return null;
    }
    filters.push([name, arg]);
    if (filters.length > FILTERS_MAX) return null;
    i = j;
  }
}

/**
 * The reference whose `{{` is at `at` in `t`, read as the server reads one —
 * `{ ref, root, node, field, path, item, filters, end }` (`path` the segments
 * as written, `items[0].title`; `end` just past its `}}`) — or null when what
 * is there is not a reference.
 */
export function parseRefAt(t, at) {
  t = String(t == null ? '' : t);
  if (!t.startsWith('{{', at)) return null;
  let i = skipWs(t, at + 2);
  let root;
  let node = null;
  let field = null;
  let pathFrom;
  if (wordAt(t, i, 'now')) {
    root = 'now'; i += 3;
    if (t[i] === '.' || t[i] === '[') return null;
    pathFrom = i;
  } else if (wordAt(t, i, 'run')) {
    root = 'run'; i += 3;
    pathFrom = i;
    if (t[i] === '.') {
      const key = matchAt(KEY_RE, t, i + 1);
      if (!key || !RUN_KEYS.includes(key)) return null;
      i += 1 + key.length;
    }
    if (t[i] === '.' || t[i] === '[') return null;
  } else {
    if (t.startsWith('steps.', i)) {
      root = 'steps'; i += 6;
      const id = matchAt(NODE_RE, t, i);
      if (!id || id.length > 64) return null;
      node = id; i += id.length;
      if (t[i] !== '.') return null;
      i += 1;
      for (const word of ['data', 'text']) {
        if (wordAt(t, i, word)) { field = word; i += word.length; break; }
      }
      if (!field) return null;
    } else if (wordAt(t, i, 'item')) {
      root = 'item'; i += 4;
    } else {
      return null;
    }
    pathFrom = i;
    let segs = 0;
    while (i < t.length) {
      if (t[i] === '.') {
        const key = matchAt(KEY_RE, t, i + 1);
        if (!key || key.length > 64) return null;
        i += 1 + key.length;
      } else if (t[i] === '[') {
        if (t[i + 1] === '"') {
          const close = t.indexOf('"', i + 2);
          if (close < 0) return null;
          const key = t.slice(i + 2, close);
          if (!key || chars(key) > 128 ||key.includes('\\') || controlIn(key)) return null;
          if (t[close + 1] !== ']') return null;
          i = close + 2;
        } else {
          const n = matchAt(INDEX_RE, t, i + 1);
          if (!n || t[i + 1 + n.length] !== ']' || n.length > 6) return null;
          i += 2 + n.length;
        }
      } else {
        break;
      }
      segs += 1;
      if (segs > REF_MAX_SEGMENTS) return null;
    }
  }
  const pathText = t.slice(pathFrom, i).replace(/^\./, '');
  const f = parseFilters(t, i);
  if (!f) return null;
  i = skipWs(t, f.end);
  if (!t.startsWith('}}', i)) return null;
  const end = i + 2;
  return { ref: t.slice(at, end), root, node, field, path: pathText, item: root === 'item', filters: f.filters, end };
}

/** Every reference in `text`, in order, as the server's `parse_template`
 *  finds them: `\{{` is literal text and is not one, and a `{{` that is not a
 *  reference is passed over (here: the server refuses the text at save).
 *  `[{ ref, root, node, field, path, item, filters }]`. */
export function refsIn(text) {
  const out = [];
  const t = String(text == null ? '' : text);
  let i = t.indexOf('{{');
  while (i >= 0) {
    if (i > 0 && t[i - 1] === '\\') { i = t.indexOf('{{', i + 2); continue; }
    const r = parseRefAt(t, i);
    if (r) { out.push(r); i = t.indexOf('{{', r.end); } else { i = t.indexOf('{{', i + 1); }
  }
  return out;
}

/**
 * `B1882`. Every reference anywhere in `text`, escaped or not, nested or not
 * — the server's `workflow_refs.references_in_text`, which refuses a `never`
 * field at save, read the same way here so the field's warning as it is
 * typed says what the save will say. A `{{` that is not a reference (a Go
 * template's `{{.Names}}`, `{{ x }}`) is the person's own text. `escapes`
 * (the palette's `escape` on a slot: a Code step's source only): a
 * reference right after `\` is the code's own text, as the server's is.
 */
export function referencesInText(text, { escapes = false } = {}) {
  const t = String(text == null ? '' : text);
  const out = [];
  let i = t.indexOf('{{');
  while (i >= 0) {
    if (!(escapes && i > 0 && t[i - 1] === '\\')) {
      const r = parseRefAt(t, i);
      if (r) out.push(r);
    }
    i = t.indexOf('{{', i + 1);
  }
  return out;
}

/** Whether `text` holds a reference — what a `never` field says no to as it
 *  is typed. `B1882`: it said no to any `{{` (`docker ps --format
 *  '{{.Names}}'` was marked "Not here" and then saved), and yes to a
 *  reference after `\` (which the server refuses): now it is the server's
 *  own reading (`referencesInText`). */
export const looksLikeRef = (text, opts) => referencesInText(text, opts).length > 0;

/** `B1879`. A change in a person's words: "in capitals", "or “none” when it
 *  is not there". */
function changeWords([name, arg]) {
  const a = arg == null ? FILTER_ARG_DEFAULTS[name] : arg;
  switch (name) {
    case 'default': return a === '' ? 'or nothing when it is not there' : `or “${a}” when it is not there`;
    case 'upper': return 'in capitals';
    case 'lower': return 'in small letters';
    case 'trim': return 'without spaces around it';
    case 'length': return 'how many';
    case 'join': return `joined with “${a}”`;
    case 'split': return `split at “${a}”`;
    case 'json': return 'as JSON text';
    case 'from_json': return 'read as JSON';
    case 'number': return 'as a number';
    case 'date': return `as a date, written “${a}”`;
    case 'first': return 'the first of it';
    case 'last': return 'the last of it';
    default: return name;
  }
}

/** "Uses: title, from “Fetch issue”; its text, from “Summarise”." or ''.
 *  `labelOf(id)` names a step (`start` → the start). */
export function usesLine(text, labelOf) {
  const parts = [];
  const seen = new Set();
  for (const r of refsIn(text)) {
    if (seen.has(r.ref)) continue;
    seen.add(r.ref);
    let said;
    if (r.root === 'now') said = 'the time the step starts';
    else if (r.root === 'run') said = r.path === 'workflow' ? 'the workflow’s name' : (r.path === 'id' ? 'this run’s id' : 'this run');
    else if (r.item) said = r.path ? `${r.path}, from each item` : 'each item';
    else {
      const what = r.field === 'text' ? 'its text' : (r.path || 'everything it made');
      const name = r.node === 'start' ? 'the start'
        : `“${(typeof labelOf === 'function' && labelOf(r.node)) || r.node}”`;
      said = `${what}, from ${name}`;
    }
    if (r.filters && r.filters.length) said += ` (${r.filters.map(changeWords).join(', ')})`;
    parts.push(said);
  }
  return parts.length ? `Uses: ${parts.join('; ')}.` : '';
}

/** `B1879`. What the run itself holds, offered under the steps' fields in
 *  every list: they read the same in every step. */
export const RUN_FIELDS = Object.freeze([
  { ref: '{{ run.id }}', path: 'run.id', example: 'the id of the run it is in' },
  { ref: '{{ run.workflow }}', path: 'run.workflow', example: 'this workflow’s name' },
  { ref: '{{ now }}', path: 'now', example: 'the time the step starts, such as 2026-11-07T08:00:00Z' },
]);

/** The words a field is listed by: its path as the server's own reference
 *  spells it — `title`, `json.subject`, `items[0].title`,
 *  `headers["content-type"]` — read off the field's `ref`. The fields route
 *  answers `path` as a LIST of segments (`workflow_refs.flatten_fields`, the
 *  form `format_ref` takes); printed as it came, a nested field read
 *  `json,subject` (`integrate-d`, found by the drive). A string `path` (an
 *  item's, which the panel lists itself) is read as it is. */
export function pathWords(f) {
  const r = refsIn(String((f && f.ref) || ''))[0];
  if (r && r.root === 'now') return 'now';
  if (r && r.root === 'run') return r.path ? `run.${r.path}` : 'run';
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
 * `B1882`. Where the list may go, as `{ top, left, bottom, right }`: 8 px
 * inside the window's frame around `anchor` (`.modal-content`; the screen
 * when there is none), and on the screen, and inside every element around
 * `box` that cuts off what overflows it (its `overflow` is not `visible`) —
 * the inside of each, within its border and scroll bars. The 8 px are the
 * frame's alone, as they always were: a list under a button flush with a
 * scrolling panel's edge starts where the button does.
 */
export function visibleBounds(box, anchor) {
  const view = { top: 0, left: 0, bottom: window.innerHeight, right: window.innerWidth };
  const win = anchor && typeof anchor.closest === 'function' ? anchor.closest('.modal-content') : null;
  const f = win && typeof win.getBoundingClientRect === 'function' ? win.getBoundingClientRect() : view;
  const frame = { top: f.top + 8, left: f.left + 8, bottom: f.bottom - 8, right: f.right - 8 };
  let r = { ...frame };
  const cut = (b) => {
    r = { top: Math.max(r.top, b.top), left: Math.max(r.left, b.left),
      bottom: Math.min(r.bottom, b.bottom), right: Math.min(r.right, b.right) };
  };
  if (win) cut(view);
  const style = typeof window.getComputedStyle === 'function' ? (el) => window.getComputedStyle(el) : null;
  const page = document.documentElement;
  for (let el = box && (box.parentElement || box.parentNode); style && el && el !== page && el !== document.body
    && typeof el.getBoundingClientRect === 'function'; el = el.parentElement || el.parentNode) {
    const s = style(el);
    if (!s || ![s.overflow, s.overflowX, s.overflowY].some((v) => v && v !== 'visible')) continue;
    const b = el.getBoundingClientRect();
    // What it shows is inside its border and its scroll bars.
    const t = b.top + (el.clientTop || 0);
    const l = b.left + (el.clientLeft || 0);
    cut({ top: t, left: l,
      bottom: el.clientHeight > 0 ? t + el.clientHeight : b.bottom,
      right: el.clientWidth > 0 ? l + el.clientWidth : b.right });
  }
  // Nothing left to show it in (a box measured before it is laid out): the
  // window's frame, as before.
  return r.bottom - r.top < 40 || r.right - r.left < 40 ? frame : r;
}

/**
 * `P23-06` (WB-U-9). Put the list under the *Insert a field…* that opened it
 * (the text box's own, when the box is the anchor), inside the window — above
 * the button when the window has more room there. It opened at the panel's
 * top-right corner whatever was pressed: measured, a button at y 747 and the
 * list at y 185, over the toolbar. The list keeps `position: absolute` in the
 * layer it is drawn in; this only writes its `left`/`top` and how tall it may be.
 *
 * `B1882`. "Inside the window" was the window's frame (`.modal-content`),
 * but what cuts the list off is the scrolling body inside it
 * (`.modal-body.workbench-body`, below the window's title bar): opened above
 * an If step's condition, the list's top was at y 108 and the body showed
 * from y 155, so its title and first line were hidden. The list is now kept
 * inside `visibleBounds` — the window's frame and every element around the
 * list that cuts off what overflows it.
 */
export function placeNear(box, anchor) {
  if (!box || !anchor || typeof anchor.getBoundingClientRect !== 'function') return;
  const slot = anchor.nextElementSibling || anchor.nextSibling;
  const btn = slot && slot.classList && slot.classList.contains('wf-slot')
    && typeof slot.querySelector === 'function' && slot.querySelector('.wf-slot-pick');
  const at = (btn || anchor).getBoundingClientRect();
  const host = box.offsetParent;
  if (!host || typeof host.getBoundingClientRect !== 'function') return;
  const h = host.getBoundingClientRect();
  const w = visibleBounds(box, anchor);
  const gap = 4;
  const below = w.bottom - at.bottom - gap;
  const above = at.top - w.top - gap;
  const down = below >= 200 || below >= above;
  const room = Math.max(120, Math.min(520, down ? below : above));
  box.style.maxHeight = `${Math.round(room)}px`;
  const width = box.offsetWidth || 330;
  const left = Math.max(w.left, Math.min(at.left, w.right - width));
  const height = Math.min(box.offsetHeight || 0, room);
  const top = down ? at.bottom + gap : at.top - gap - height;
  box.style.right = 'auto';
  box.style.left = `${Math.round(left - h.left + (host.scrollLeft || 0))}px`;
  box.style.top = `${Math.round(top - h.top + (host.scrollTop || 0))}px`;
}

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
    // `B1879`. What the run itself holds — its id, its workflow's name, the
    // time — is the same for every step, so it is offered under every list,
    // and how to change a field after it is picked is said once, under it.
    // Its own section (not a `.wf-picker-source`: the steps' groups are
    // what earlier steps made, and this is not one of them).
    const runBox = _el('section', 'wf-picker-run');
    const runHead = _el('p', 'wf-picker-step');
    runHead.appendChild(_el('span', 'wf-picker-step-name', 'This run'));
    runBox.appendChild(runHead);
    const runButtons = [];
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
    for (const f of RUN_FIELDS) {
      const b = _button('wf-picker-field', null);
      b.dataset.ref = f.ref;
      b.appendChild(_el('span', 'wf-picker-path', f.path));
      b.appendChild(_el('span', 'wf-picker-example', f.example));
      b.setAttribute('aria-label', `${f.path}: ${f.example}`);
      b.addEventListener('click', () => finish(f.ref));
      runButtons.push(b);
      runBox.appendChild(b);
    }
    runBox.appendChild(_el('p', 'wf-picker-lede',
      'After a field, a change can follow: | default:"none" when it is not there, | lower, | trim, | number, '
      + '| from_json, | join:", ", | date:"%Y-%m-%d" and a few more.'));
    box.appendChild(runBox);
    const cancel = _button('wf-picker-cancel', 'Cancel');
    box.appendChild(cancel);
    cancel.addEventListener('click', () => finish(null));
    let nav = runButtons;
    box.addEventListener('keydown', (e) => {
      const i = nav.indexOf(e.target);
      if (i < 0 || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp')) return;
      e.preventDefault();
      nav[(i + (e.key === 'ArrowDown' ? 1 : nav.length - 1)) % nav.length].focus();
    });
    room.appendChild(box);
    placeNear(box, anchor);
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
        const from = originWords(src.origin, src.at, src.kind);
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
      nav = [...buttons, ...runButtons];
      placeNear(box, anchor);   // as tall as its list now
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
      const refused = looksLikeRef(v, { escapes: slot.escape === true });
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
  NEVER_FALLBACK, placeNear, parseRefAt, FILTERS, FILTER_ARG_DEFAULTS, RUN_FIELDS,
  referencesInText, visibleBounds,
};
