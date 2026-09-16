// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B11`/`B12`. Runs the two real checklist renderers — `planWindow.js`'s
// `renderStep` and `chatRenderer.js`'s `buildTodoCard` — against a stub DOM and
// reports the markup each one emits, plus the words a person reads in each
// card's head.
//
// The question the row asks cannot be answered by reading either file or by
// grepping the sheet. Both rows carry the same class list, and whether that
// makes them *look* the same depends on which CSS rules those classes select —
// a fact that lives in a third file. So the harness emits both rows, reduces
// each to its class list, and reports the intersection: identical class lists
// against one shared sheet is identical paint, and that is the claim under
// test. The head is the other half: what distinguishes the two surfaces has to
// be something a person can read, so the harness prints the visible text of
// each head rather than asserting a selector exists.
//
// Usage:
//   node checklist_surfaces.js rows
//   node checklist_surfaces.js heads
const fs = require('fs');
const path = require('path');

const JS = path.join(__dirname, '..', '..', 'static', 'js');
const planSrc = fs.readFileSync(path.join(JS, 'planWindow.js'), 'utf8');
const rendererSrc = fs.readFileSync(path.join(JS, 'chatRenderer.js'), 'utf8');
const checklistPath = path.join(JS, 'checklist.js');
const checklistSrc = fs.existsSync(checklistPath)
  ? fs.readFileSync(checklistPath, 'utf8') : '';
// `B83`. `checklist.js` no longer declares `PLAY_POINTS`; it re-exports it from
// the shared icon table, because a glyph five unrelated modules want does not
// belong in the checklist module. So the table is inlined here and the
// re-export line is dropped — the value both renderers see is still the shipped
// one, which is the whole reason this harness evaluates modules rather than
// retyping them.
const iconsPath = path.join(JS, 'icons.js');
const iconsSrc = fs.existsSync(iconsPath)
  ? fs.readFileSync(iconsPath, 'utf8').replace(/^export\s+/gm, '') : '';
const indexHtml = fs.readFileSync(
  path.join(__dirname, '..', '..', 'static', 'index.html'), 'utf8');

function slice(source, startMark, endMark, label) {
  const from = source.indexOf(startMark);
  if (from < 0) {
    console.error(`ANCHOR-MISSING: ${label} start (${startMark})`);
    process.exit(2);
  }
  const to = source.indexOf(endMark, from);
  if (to < 0 || to <= from) {
    console.error(`ANCHOR-MISSING: ${label} end (${endMark})`);
    process.exit(2);
  }
  return source.slice(from, to);
}

const unexport = (s) => s.replace(/^export\s+/gm, '');
// The shared module is plain data and pure functions with no imports, so it is
// evaluated as written rather than re-stated here: a harness that retypes the
// table is testing the harness.
const shared = checklistSrc
  ? iconsSrc + '\n' + unexport(
      checklistSrc.replace(/^\/\/.*$/gm, '')
        // A re-export has no body to keep: the value is already above.
        .replace(/^export\s*\{[^}]*\}\s*from\s*'[^']*';\s*$/gm, ''))
  : '';

// ── A DOM small enough to read and faithful enough to serialise ─────────────
// `planWindow.js` builds rows with createElement/textContent and `chatRenderer`
// builds them as strings. Comparing the two needs one representation, so the
// node stub serialises.
const VOID = new Set();
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function makeEl(tag, ns) {
  const el = {
    tagName: tag, ns: ns || null, attrs: {}, children: [], _text: null,
    dataset: new Proxy({}, {
      set(t, k, v) { t[k] = v; el.attrs['data-' + String(k).replace(/[A-Z]/g, (c) => '-' + c.toLowerCase())] = v; return true; },
      get(t, k) { return t[k]; },
    }),
    style: {},
    classList: {
      add(...c) { el.attrs.class = ((el.attrs.class || '') + ' ' + c.join(' ')).trim(); },
      remove() {}, toggle() {}, contains: (c) => (el.attrs.class || '').split(/\s+/).includes(c),
    },
    setAttribute(k, v) { el.attrs[k] = String(v); },
    getAttribute(k) { return el.attrs[k]; },
    removeAttribute(k) { delete el.attrs[k]; },
    appendChild(child) { el.children.push(child); el._text = null; return child; },
    get childNodes() { return el.children; },
    addEventListener() {},
    get className() { return el.attrs.class || ''; },
    set className(v) { el.attrs.class = v; },
    get textContent() { return el._text == null ? el.children.map(serialiseText).join('') : el._text; },
    set textContent(v) { el._text = String(v); el.children = []; },
    get title() { return el.attrs.title || ''; },
    set title(v) { el.attrs.title = String(v); },
    get hidden() { return 'hidden' in el.attrs; },
    set hidden(v) { if (v) el.attrs.hidden = ''; else delete el.attrs.hidden; },
  };
  return el;
}

function serialiseText(node) {
  if (node == null) return '';
  if (node._frag) return node.children.map(serialiseText).join('');
  if (node._text != null) return node._text;
  return node.children.map(serialiseText).join('');
}

function serialise(node) {
  if (node._frag) return node.children.map(serialise).join('');
  const attrs = Object.keys(node.attrs)
    .map((k) => (node.attrs[k] === '' ? ` ${k}` : ` ${k}="${esc(node.attrs[k])}"`)).join('');
  const inner = node._text != null ? esc(node._text) : node.children.map(serialise).join('');
  if (VOID.has(node.tagName)) return `<${node.tagName}${attrs}>`;
  return `<${node.tagName}${attrs}>${inner}</${node.tagName}>`;
}

const document = {
  createElement: (t) => makeEl(t),
  createElementNS: (ns, t) => makeEl(t, ns),
  createTextNode: (t) => ({ _text: String(t), children: [], attrs: {} }),
  createDocumentFragment: () => ({ _frag: true, children: [], attrs: {}, appendChild(c) { this.children.push(c); return c; } }),
};

// ── The plan window's row ───────────────────────────────────────────────────
const planPieces = [
  slice(planSrc, 'const RESULT_MAX', 'const STALE_MS', 'plan constants'),
  slice(planSrc, 'function truncate(text, max) {', '// ── Rendering', 'truncate'),
  slice(planSrc, 'function chip(cls, text, title) {', 'const STATE_TEXT = {', 'chip + renderStep'),
].join('\n');

// ── The todo card ──────────────────────────────────────────────────────────
const todoPieces = [
  slice(rendererSrc, 'const TODO_ICON =', '/** The three statuses', 'TODO_ICON'),
  slice(rendererSrc, "const TODO_STATUSES = {", 'function _normalizeTodo(', 'todo tables'),
  slice(rendererSrc, 'function _normalizeTodo(', 'export function buildDiffHtml(', 'parseTodoList'),
  slice(rendererSrc, 'export function buildTodoCard(ev) {', 'export function demoteSupersededTodoCards', 'buildTodoCard'),
].join('\n');

const uiModule = { esc };
const formatElapsed = (ms) => `${Math.round(ms / 1000)}s`;

const mode = process.argv[2] || 'rows';

if (mode === 'rows') {
  const planApi = new Function('document', 'formatElapsed', 'SHARED', `
    ${shared}
    const _meta = { steps: {} };
    const _activeStartedAt = 0;
    ${planPieces}
    return { renderStep };
  `)(document, formatElapsed, null);

  const todoApi = new Function('uiModule', 'document', 'SHARED', `
    ${shared}
    ${unexport(todoPieces)}
    return { buildTodoCard };
  `)(uiModule, document, null);

  // Same three states, same words, one from each surface.
  const steps = [
    { id: 'a', text: 'Read the config', done: true },
    { id: 'b', text: 'Patch the parser', done: false },
    { id: 'c', text: 'Run the suite', done: false },
  ];
  const planRows = steps.map((s, i) => serialise(planApi.renderStep(s, i, 1)));

  const todoHtml = todoApi.buildTodoCard({
    tool: 'todowrite',
    command: JSON.stringify({ todos: [
      { content: 'Read the config', status: 'completed', priority: 'medium' },
      { content: 'Patch the parser', status: 'in_progress', priority: 'medium' },
      { content: 'Run the suite', status: 'pending', priority: 'medium' },
    ] }),
    exit_code: 0,
  });
  const todoRows = todoHtml.match(/<li [\s\S]*?<\/li>/g) || [];

  const classesOf = (html) => ((html.match(/^<li class="([^"]*)"/) || [])[1] || '')
    .split(/\s+/).filter(Boolean).sort();
  // Structure only: the words go, `data-step-id` goes (it paints nothing), and
  // class lists are sorted — CSS does not read attribute order, so two rows
  // that differ only in how their author spelled the list are the same row.
  const shapeOf = (html) => html
    .replace(/>[^<>]*</g, '><')
    .replace(/ (title|data-step-id)="[^"]*"/g, '')
    .replace(/class="([^"]*)"/g, (_, c) => `class="${c.split(/\s+/).filter(Boolean).sort().join(' ')}"`);

  const out = [];
  for (let i = 0; i < 3; i++) {
    const p = planRows[i] || '';
    const t = todoRows[i] || '';
    out.push({
      state: ['done', 'in progress', 'pending'][i],
      planClasses: classesOf(p),
      todoClasses: classesOf(t),
      sameClasses: classesOf(p).join(' ') === classesOf(t).join(' '),
      // Two rows built by two files, reduced to structure: identical here means
      // one sheet paints them identically, whatever it says.
      sameShape: shapeOf(p) === shapeOf(t),
      plan: p,
      todo: t,
    });
  }
  console.log(JSON.stringify(out));
} else {
  // ── What a person reads in each head ──────────────────────────────────────
  const todoApi = new Function('uiModule', 'document', `
    ${shared}
    ${unexport(todoPieces)}
    return { buildTodoCard };
  `)(uiModule, document);

  const todoHtml = todoApi.buildTodoCard({
    tool: 'todowrite',
    command: JSON.stringify({ todos: [
      { content: 'Read the config', status: 'completed', priority: 'medium' },
      { content: 'Patch the parser', status: 'pending', priority: 'medium' },
    ] }),
    exit_code: 0,
  });
  // Everything above the rows: the head plus the identity line under it, which
  // is what a person reads before they read a single step.
  const headHtml = todoHtml.slice(0, todoHtml.indexOf('<ul') >= 0
    ? todoHtml.indexOf('<ul') : todoHtml.length);
  const strip = (h) => h.replace(/<svg[\s\S]*?<\/svg>/g, '').replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ').trim();

  // The plan window's head is static markup in index.html plus four textContent
  // writes in `render()`. Both halves are run/read, never re-stated.
  const planHead = (indexHtml.match(/<div class="plan-window-head">[\s\S]*?\n      <\/div>/) || [''])[0];
  const headBlock = slice(planSrc, '  _els.count.textContent =', '  _els.execute.textContent', 'plan head writes');
  const stateText = slice(planSrc, 'const STATE_TEXT = {', 'function render()', 'STATE_TEXT');

  const els = {
    count: makeEl('span'), status: makeEl('span'), hint: makeEl('span'),
    fill: makeEl('span'), origin: makeEl('span'),
  };
  new Function('_els', 'done', 'total', 'state', '_meta', 'currentSessionId', 'SHARED', `
    ${shared}
    ${unexport(stateText)}
    ${headBlock}
  `)(els, 1, 2, 'executing', { sessionId: '' }, () => 's1', null);

  // The blurb, when the surface has one, is written by init() from the shared
  // table; read it the same way the browser would.
  let planBlurb = '';
  const blurbWrite = planSrc.match(/_els\.blurb\.textContent\s*=\s*([^;]+);/);
  if (blurbWrite && shared) {
    planBlurb = new Function(`${shared}\nreturn ${blurbWrite[1]};`)();
  }
  // Same for the title the module writes over the pre-JS paint: reported so a
  // test can hold the two equal rather than asserting a literal twice.
  let planTitle = '';
  const titleWrite = planSrc.match(/_els\.title\.textContent\s*=\s*([^;]+);/);
  if (titleWrite && shared) {
    planTitle = new Function(`${shared}\nreturn ${titleWrite[1]};`)();
  }

  console.log(JSON.stringify({
    plan: {
      static: strip(planHead),
      count: els.count.textContent,
      status: els.status.textContent,
      title: planTitle,
      blurb: planBlurb,
      visible: [strip(planHead), els.count.textContent, els.status.textContent, planBlurb]
        .filter(Boolean).join(' · '),
    },
    todo: {
      head: strip(headHtml),
      aria: (todoHtml.match(/aria-label="([^"]*)"/) || [])[1] || '',
      blurb: (todoHtml.match(/<p class="todo-card-note">([^<]*)<\/p>/) || [])[1] || '',
      visible: strip(headHtml),
    },
  }));
}
