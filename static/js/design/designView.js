// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P26-06` / `P26-07`. One design in the Design window: its page previewed in a
// sandboxed frame, its versions and variants, and the canvas — select an
// element and adjust it, or move the page's own sliders (`src/design_files.py`).
//
// **The preview is the person's browser's.** The page is its own document,
// `…/designs/{slug}/preview`, bundled and served with `sandbox allow-scripts`
// and nothing to fetch (`core/middleware.py`) — scripts run, but in an opaque
// origin with no access to Pantheon, its cookies or this window. The one script
// added to it is the picker (`src/design_files.py`, `PICKER`), which outlines
// what is under the pointer while *Select* is on and posts the clicked element's
// path and the computed styles this window asks for; the window believes a
// message only from its own frame.
//
// **An adjustment is a file change**, made by the server in one style block of
// the page and kept as a version; the frame reloads from the file, so what is
// shown is what is saved. Values are the design system's tokens first.
//
// **Shared** (`P26-09`): a design someone shared is opened by its share's id,
// never its owner's path; the server answers the caller's role and decides
// every write by it. A viewer sees, a commenter adds notes (*Select* then
// picks the element a note is about), an editor changes it as its owner does.

import { drawCollab, may } from './collab.js';

const PROPS_TEXT = ['color', 'font-size', 'font-weight', 'text-align', 'line-height', 'letter-spacing'];
const PROPS_BOX = ['background-color', 'padding', 'gap', 'border-radius', 'justify-content', 'align-items', 'max-width'];
const TEXT_TAGS = new Set(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'span', 'a', 'button', 'label', 'li', 'strong', 'em', 'small', 'td', 'th', 'blockquote', 'figcaption']);
const KEYWORDS = {
  'font-weight': ['400', '500', '600', '700', '800'],
  'text-align': ['left', 'center', 'right', 'justify'],
  'justify-content': ['flex-start', 'center', 'flex-end', 'space-between', 'space-around'],
  'align-items': ['flex-start', 'center', 'flex-end', 'stretch'],
};
const COLOUR_PROPS = new Set(['color', 'background-color', 'border-color']);

/** The choices for one property: the design system's tokens first. */
export function choicesFor(prop, tokens) {
  const t = tokens || {};
  const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  if (COLOUR_PROPS.has(prop)) return (t.palette || []).map((c) => ({ label: `${c.name} (${c.value})`, value: `var(--color-${slug(c.name)})` }));
  if (prop === 'font-size') return ((t.type || {}).scale || []).map((v, i) => ({ label: `${v}px`, value: `var(--text-${i + 1})` }));
  if (prop === 'padding' || prop === 'gap') return (t.spacing || []).map((v, i) => ({ label: `${v}px`, value: `var(--space-${i + 1})` }));
  if (prop === 'border-radius') return (t.radii || []).map((v, i) => ({ label: `${v}px`, value: `var(--radius-${i + 1})` }));
  return (KEYWORDS[prop] || []).map((v) => ({ label: v, value: v }));
}

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

function _frame(url, label) {
  const f = document.createElement('iframe');
  f.className = 'design-frame';
  f.setAttribute('sandbox', 'allow-scripts');
  f.setAttribute('referrerpolicy', 'no-referrer');
  f.title = label;
  f.src = url;
  return f;
}

/** Every property the panel can show, asked of the picker. */
export const PICKED_PROPS = [...new Set([...PROPS_TEXT, ...PROPS_BOX])];

/**
 * Draw one design into `ctx.body`. `ctx`: { body, slug, project, systems,
 * say(text, {error}), call(method, url, body), sendToChat(text), back() }.
 */
export async function renderDesign(ctx) {
  const q = (extra = '') => (ctx.share ? `?share=${encodeURIComponent(ctx.share)}` : `?project=${encodeURIComponent(ctx.project)}`) + extra;
  // Where a write names the design: by the share it came through, or the caller's own project.
  const where = () => (ctx.share ? { share: ctx.share } : { project: ctx.project });
  const previewUrl = (extra = '') => `/api/design/designs/${encodeURIComponent(ctx.slug)}/preview${q(extra)}`;
  const state = { showing: {}, selected: null, selecting: false, data: null, collab: null };
  const role = () => ((state.data && state.data.access) || {}).role || 'owner';
  const body = ctx.body;
  body.textContent = '';
  body.appendChild(_btn('design-back', '← Design', () => ctx.back()));
  const head = _el('div', 'design-view-head');
  const title = _el('h2', 'design-page-title', '…');
  head.appendChild(title);
  const bar = _el('div', 'design-view-bar');
  head.appendChild(bar);
  body.appendChild(head);
  const layout = _el('div', 'design-view');
  const stage = _el('div', 'design-stage');
  const side = _el('aside', 'design-side');
  layout.appendChild(stage);
  layout.appendChild(side);
  body.appendChild(layout);
  let frame = null;

  const system = () => (ctx.systems || []).find((s) => state.data && s.id === state.data.system) || null;

  async function load(extra = '') {
    const r = await ctx.call('GET', `/api/design/designs/${encodeURIComponent(ctx.slug)}${q(extra)}`);
    if (!r.ok) { ctx.say(r.sentence, { error: true }); return false; }
    state.data = r.data;
    state.showing = r.data.showing || {};
    if (!state.collab) {
      state.collab = _el('div', 'design-collab-box');
      const acc = r.data.access || { role: 'owner' };
      drawCollab(state.collab, { kind: 'design', ref: ctx.slug, project: ctx.project, share: ctx.share || null,
        role: acc.role, owner: acc.owner, name: r.data.name }, {
        call: ctx.call, say: ctx.say, me: ctx.me || acc.owner,
        selected: () => (state.selected ? state.selected.selector : null),
        onLeave: ctx.onLeave,
      });
    }
    draw();
    return true;
  }

  function onMessage(ev) {
    if (!frame || ev.source !== frame.contentWindow) return;   // only our own frame
    const d = ev.data || {};
    if (d.type !== 'pantheon-selected' || typeof d.selector !== 'string') return;
    state.selected = { selector: d.selector, tag: String(d.tag || ''), text: String(d.text || ''), styles: d.styles || {} };
    drawPanel();
  }
  window.addEventListener('message', onMessage);
  ctx.onLeave && ctx.onLeave(() => window.removeEventListener('message', onMessage));

  function setSelecting(on) {
    state.selecting = on;
    if (frame && frame.contentWindow) frame.contentWindow.postMessage({ type: 'pantheon-select-mode', on, props: PICKED_PROPS }, '*');
    const b = bar.querySelector('.design-select-btn');
    if (b) b.setAttribute('aria-pressed', String(on));
  }

  function draw() {
    const d = state.data;
    title.textContent = d.name;
    bar.textContent = '';
    const live = !state.showing.version && !state.showing.variant;
    const canEdit = may(role(), 'edit');
    if (live && !canEdit) {
      // `P26-09`. Not an editor: the page, and for a commenter an element to
      // pin a note to. The server refuses a change whatever is drawn here.
      bar.appendChild(_el('span', 'design-chip', role() === 'commenter' ? 'You can comment' : 'You can look'));
      if (may(role(), 'note')) {
        const sel = _btn('design-btn design-select-btn', 'Select', () => setSelecting(!state.selecting),
          'Select the element your note is about');
        sel.setAttribute('aria-pressed', String(state.selecting));
        bar.appendChild(sel);
      }
    }
    if (live && canEdit) {
      const sel = _btn('design-btn design-select-btn', 'Select', () => setSelecting(!state.selecting),
        'Select an element on the page to adjust it');
      sel.setAttribute('aria-pressed', String(state.selecting));
      bar.appendChild(sel);
      bar.appendChild(_btn('design-btn', 'Tweaks', () => drawTweaks()));
      // Variants are the agent's work in the owner's project, asked in the
      // owner's chat — an editor's agent works in its own person's folders.
      const n = document.createElement('select');
      n.setAttribute('aria-label', 'How many variants');
      ['2', '3', '4'].forEach((k) => { const o = document.createElement('option'); o.value = k; o.textContent = `${k} variants`; n.appendChild(o); });
      if (role() === 'owner') bar.appendChild(n);
      if (role() === 'owner') bar.appendChild(_btn('design-btn', 'Try variants', () => {
        const k = Number(n.value);
        ctx.sendToChat(`Make ${k} variants of the design in ${d.folder}/ — each a different direction on the same brief `
          + `(layout, density, emphasis), each self-contained in ${d.folder}/variants/1/index.html … `
          + `${d.folder}/variants/${k}/index.html, using the same :root variables. Do not change ${d.folder}/index.html. `
          + 'Say when they are there.');
        ctx.say(`Asked for ${k} variants. Open this design again when the agent says they are there.`);
      }));
      bar.appendChild(_btn('design-btn', 'Keep a version', async () => {
        const r = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/versions`, where());
        if (!r.ok) { ctx.say(r.sentence, { error: true }); return; }
        ctx.say(r.data.new ? `Kept as version ${r.data.version}.` : `Nothing changed since version ${r.data.version}.`);
        await load();
      }));
      // `P26-08`. The owner's: the design as work on the project, on a branch.
      if (role() === 'owner') {
        const b = _btn('design-btn', 'Build it', () => { state.building = !state.building; drawPanel(); },
          'Hand this design to the project as a branch');
        b.setAttribute('aria-pressed', String(!!state.building));
        bar.appendChild(b);
      }
    } else if (!live) {
      const what = state.showing.version ? `version ${state.showing.version}` : `variant ${state.showing.variant}`;
      bar.appendChild(_el('span', 'design-chip', `Showing ${what}`));
      if (canEdit && state.showing.version) {
        bar.appendChild(_btn('design-btn design-btn-primary', 'Step back to this', () => restore(state.showing.version)));
      } else if (canEdit) {
        bar.appendChild(_btn('design-btn design-btn-primary', 'Keep this variant', () => keep(state.showing.variant)));
      }
      bar.appendChild(_btn('design-btn', 'Back to the present', () => { state.selected = null; load(); }));
    }
    bar.appendChild(_btn('design-btn', 'Refresh', () => load(state.showing.version ? `&version=${state.showing.version}` : (state.showing.variant ? `&variant=${state.showing.variant}` : ''))));

    stage.textContent = '';
    const page = d.page || {};
    if (live && (d.variants || []).length) {
      const grid = _el('div', 'design-variants');
      d.variants.forEach((v) => {
        const cell = _el('div', 'design-variant');
        const top = _el('div', 'design-variant-head');
        top.appendChild(_el('strong', '', `Variant ${v}`));
        top.appendChild(_btn('design-btn', 'Look closer', () => load(`&variant=${encodeURIComponent(v)}`)));
        if (canEdit) top.appendChild(_btn('design-btn design-btn-primary', 'Keep this', () => keep(v)));
        cell.appendChild(top);
        const holder = _el('div', 'design-variant-frame');
        cell.appendChild(holder);
        grid.appendChild(cell);
        holder.appendChild(_frame(previewUrl(`&variant=${encodeURIComponent(v)}`), `Variant ${v}`));
      });
      stage.appendChild(_el('p', 'design-section-sub', 'The agent made these side by side. Keep one; the rest are kept as versions.'));
      stage.appendChild(grid);
    }
    if (!page.html) {
      stage.appendChild(_el('p', 'design-empty', `No page yet. The agent writes it in ${d.folder}/index.html; open this design again when it says the page is there.`));
      frame = null;
    } else {
      frame = _frame(previewUrl(state.showing.version ? `&version=${state.showing.version}` : (state.showing.variant ? `&variant=${encodeURIComponent(state.showing.variant)}` : '')) + `&_=${Date.now()}`, d.name);
      frame.addEventListener('load', () => { if (state.selecting) setSelecting(true); });
      stage.appendChild(frame);
      if ((page.missing || []).length) stage.appendChild(_el('p', 'design-section-sub', `Not found beside the page: ${page.missing.join(', ')}.`));
    }
    drawPanel();
  }

  function drawVersions(box) {
    const d = state.data;
    box.appendChild(_el('h3', 'design-section-title', 'Versions'));
    const list = _el('ol', 'design-versions');
    (d.versions || []).slice().reverse().forEach((v) => {
      const li = _el('li', `design-version${state.showing.version === v.n ? ' design-version-on' : ''}`);
      const when = v.at ? new Date(v.at * 1000).toLocaleString() : '';
      li.appendChild(_btn('design-version-pick', `${v.n}. ${v.note || ''}`, () => { state.selected = null; load(`&version=${v.n}`); }, `Show version ${v.n}`));
      li.appendChild(_el('span', 'design-version-when', when));
      list.appendChild(li);
    });
    if (!(d.versions || []).length) box.appendChild(_el('p', 'design-section-sub', 'No versions yet: the first is kept when the page is.'));
    box.appendChild(list);
    const vs = d.versions || [];
    if (vs.length >= 2 && !state.showing.version && !state.showing.variant && may(role(), 'edit')) {
      box.appendChild(_btn('design-btn', 'Undo the last change', () => restore(vs[vs.length - 2].n)));
    }
  }

  function drawPanel() {
    side.textContent = '';
    const s = state.selected;
    if (s && !may(role(), 'edit')) {
      // A commenter's pick is what a note is about, nothing more.
      const panel = _el('div', 'design-props');
      panel.appendChild(_el('h3', 'design-section-title', `<${s.tag}>${s.text ? ` “${s.text}”` : ''}`));
      panel.appendChild(_el('p', 'design-section-sub design-selector', s.selector));
      panel.appendChild(_el('p', 'design-section-sub', 'Your next note is about this element.'));
      panel.appendChild(_btn('design-btn', 'Done', () => { state.selected = null; setSelecting(false); drawPanel(); }));
      side.appendChild(panel);
    } else if (s && !state.showing.version && !state.showing.variant) {
      const panel = _el('div', 'design-props');
      panel.appendChild(_el('h3', 'design-section-title', `<${s.tag}>${s.text ? ` “${s.text}”` : ''}`));
      panel.appendChild(_el('p', 'design-section-sub design-selector', s.selector));
      const props = TEXT_TAGS.has(s.tag) ? PROPS_TEXT : PROPS_BOX;
      const tokens = (system() || {}).tokens || null;
      const inputs = {};
      props.forEach((p) => {
        const row = _el('label', 'design-field');
        row.appendChild(_el('span', '', `${p} — now ${String(s.styles[p] || '').trim() || '—'}`));
        const sel = document.createElement('select');
        sel.setAttribute('aria-label', p);
        const keep = document.createElement('option');
        keep.value = '';
        keep.textContent = 'Leave as it is';
        sel.appendChild(keep);
        choicesFor(p, tokens).forEach((c) => { const o = document.createElement('option'); o.value = c.value; o.textContent = c.label; sel.appendChild(o); });
        const custom = document.createElement('option');
        custom.value = '__custom';
        custom.textContent = 'A value of my own…';
        sel.appendChild(custom);
        const reset = document.createElement('option');
        reset.value = '__reset';
        reset.textContent = 'Undo my adjustment';
        sel.appendChild(reset);
        const own = document.createElement('input');
        own.type = COLOUR_PROPS.has(p) ? 'color' : 'text';
        own.hidden = true;
        own.setAttribute('aria-label', `${p}, my own value`);
        sel.addEventListener('change', () => { own.hidden = sel.value !== '__custom'; });
        row.appendChild(sel);
        row.appendChild(own);
        inputs[p] = { sel, own };
        panel.appendChild(row);
      });
      panel.appendChild(_btn('design-btn design-btn-primary', 'Apply', async () => {
        const change = {};
        Object.entries(inputs).forEach(([p, { sel, own }]) => {
          if (sel.value === '__custom') { if (own.value.trim()) change[p] = own.value.trim(); }
          else if (sel.value === '__reset') change[p] = null;
          else if (sel.value) change[p] = sel.value;
        });
        if (!Object.keys(change).length) { ctx.say('Pick something to change first.'); return; }
        const r = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/adjust`,
          { ...where(), selector: s.selector, props: change, system: state.data.system || null });
        if (!r.ok) { ctx.say(r.sentence, { error: true }); return; }
        ctx.say(`Adjusted and kept as version ${r.data.version}.`);
        // "now" is what was just written, not what was picked before it.
        Object.entries(change).forEach(([p, v]) => { s.styles[p] = v == null ? 'the page’s own' : v; });
        await load();
      }));
      panel.appendChild(_btn('design-btn', 'Done', () => { state.selected = null; setSelecting(false); drawPanel(); }));
      side.appendChild(panel);
    }
    if (state.tweaks && !state.showing.version && !state.showing.variant) side.appendChild(state.tweaks);
    if (state.building && role() === 'owner') {
      if (!state.buildBox) { state.buildBox = _el('div', 'design-build'); drawBuild(); }
      side.appendChild(state.buildBox);
    }
    if (state.collab) side.appendChild(state.collab);
    drawVersions(side);
  }

  // ── `P26-08`: Build it — a branch, its brief, a preview, and the person's yes ──
  async function drawBuild() {
    const box = state.buildBox;
    box.textContent = '';
    box.appendChild(_el('h3', 'design-section-title', 'Build it'));
    const r = await ctx.call('GET', `/api/design/designs/${encodeURIComponent(ctx.slug)}/build${q()}`);
    if (!r.ok) { box.appendChild(_el('p', 'design-section-sub', r.sentence)); return; }
    const rec = r.data.build;
    if (!rec || rec.status === 'closed' || rec.status === 'merged') {
      if (rec && rec.status === 'merged') {
        box.appendChild(_el('p', 'design-section-sub', `Merged into ${rec.base}${rec.merged_sha ? ` (${rec.merged_sha.slice(0, 8)})` : ''}. Build it again to start a new branch.`));
        if (!rec.folder_removed) {
          box.appendChild(_btn('design-btn', 'Remove the build folder', async () => {
            const cl = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/build/close`, where());
            if (!cl.ok) { ctx.say(cl.sentence, { error: true }); return; }
            ctx.say(`The build folder is removed; ${rec.branch} stays.`);
            drawBuild();
          }));
        }
        if (ctx.backToProject && rec.project) box.appendChild(_btn('design-btn', 'Back to the project', () => ctx.backToProject(rec.project)));
      }
      box.appendChild(_el('p', 'design-section-sub', 'A branch of its own, design/' + ctx.slug + ', in a folder beside the project, with a brief the agent follows. Nothing reaches your branch until you say yes.'));
      const base = document.createElement('input');
      base.type = 'text';
      base.placeholder = 'The project’s current branch';
      base.setAttribute('aria-label', 'Build from the branch');
      const acc = document.createElement('textarea');
      acc.rows = 3;
      acc.placeholder = 'What must be true when it is done — a line each';
      acc.setAttribute('aria-label', 'Acceptance');
      const lab = (t, el) => { const l = _el('label', 'design-field'); l.appendChild(_el('span', '', t)); l.appendChild(el); return l; };
      box.appendChild(lab('From the branch', base));
      box.appendChild(lab('Acceptance', acc));
      box.appendChild(_btn('design-btn design-btn-primary', 'Make the branch', async () => {
        const made = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/build`, { ...where(), base: base.value.trim() || null, acceptance: acc.value });
        if (!made.ok) { ctx.say(made.sentence, { error: true }); return; }
        state.buildMessage = made.data.message;
        ctx.say(`Made ${made.data.branch} from ${made.data.base} in ${made.data.worktree}, with its brief committed. Start the work when you are ready.`);
        drawBuild();
      }));
      return;
    }
    const st = r.data;
    box.appendChild(_el('p', 'design-section-sub', `${rec.branch} from ${rec.base}, in ${rec.worktree}.`));
    if (ctx.startBuild) {
      box.appendChild(_btn('design-btn', 'Start the work in the chat', () => ctx.startBuild(rec, state.buildMessage
        || `Build the design on the branch ${rec.branch}, in ${rec.worktree}: follow design/${ctx.slug}/BUILD.md there. Commit with the git tool on ${rec.branch} only — never switch to ${rec.base} and never merge; merging is mine.`),
        'Make the build folder the chat’s workspace and send the brief'));
    }
    if (st.base_moved) box.appendChild(_el('p', 'design-section-sub', `${rec.base} has moved since the branch was made; the merge may need the branch brought up to date.`));
    if (st.uncommitted) box.appendChild(_el('p', 'design-section-sub', `${st.uncommitted} change${st.uncommitted === 1 ? '' : 's'} in the build folder not committed yet.`));
    const commits = _el('ol', 'design-versions');
    (st.commits || []).forEach((c) => commits.appendChild(_el('li', 'design-version', c)));
    box.appendChild(_el('p', 'design-section-sub', `${(st.commits || []).length} commit${(st.commits || []).length === 1 ? '' : 's'} on the branch:`));
    box.appendChild(commits);
    if (st.changes) { const pre = _el('pre', 'design-selector', st.changes); box.appendChild(pre); }
    // Preview: the branch running, in the agent browser.
    const addr = document.createElement('input');
    addr.type = 'text';
    addr.placeholder = 'localhost:5173';
    addr.value = rec.preview || '';
    addr.setAttribute('aria-label', 'Where the branch runs');
    const row = _el('div', 'design-share-form');
    row.appendChild(addr);
    row.appendChild(_btn('design-btn', 'Preview', async () => {
      const a = addr.value.trim();
      if (!a) { ctx.say('Say where the branch runs — the agent tells you the address when it starts it.', { error: true }); return; }
      const p = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/build/preview`, { ...where(), address: a });
      if (!p.ok) { ctx.say(p.sentence, { error: true }); return; }
      if (ctx.openBrowser) ctx.openBrowser(a);
    }, 'Open the branch in the browser'));
    box.appendChild(row);
    // The merge: a press, then a yes.
    const confirm = _el('div', 'design-share-form');
    confirm.hidden = true;
    const n = (st.commits || []).length;
    confirm.appendChild(_el('p', 'design-section-sub', `Put ${n} commit${n === 1 ? '' : 's'} from ${rec.branch} into ${rec.base}?`));
    confirm.appendChild(_btn('design-btn design-btn-primary', `Yes, merge into ${rec.base}`, async () => {
      const m = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/build/merge`, { ...where(), yes: true });
      if (!m.ok) { ctx.say(m.sentence, { error: true }); confirm.hidden = true; return; }
      ctx.say(`Merged into ${m.data.into}.`);
      drawBuild();
    }));
    confirm.appendChild(_btn('design-btn', 'Not now', () => { confirm.hidden = true; }));
    box.appendChild(_btn('design-btn design-btn-primary', `Merge into ${rec.base}…`, () => { confirm.hidden = false; }));
    box.appendChild(confirm);
    box.appendChild(_btn('design-btn', 'Close the build', async () => {
      const cl = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/build/close`, where());
      if (!cl.ok) { ctx.say(cl.sentence, { error: true }); return; }
      ctx.say(`The build folder is removed; ${rec.branch} stays.`);
      drawBuild();
    }, 'Remove the build folder; the branch stays'));
    if (ctx.backToProject && rec.project) box.appendChild(_btn('design-btn', 'Back to the project', () => ctx.backToProject(rec.project)));
  }

  async function drawTweaks() {
    const r = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/tweaks`, where());
    if (!r.ok) { ctx.say(r.sentence, { error: true }); return; }
    const box = _el('div', 'design-tweaks');
    box.appendChild(_el('h3', 'design-section-title', 'Tweaks'));
    if (r.data.sentence) box.appendChild(_el('p', 'design-section-sub', r.data.sentence));
    let timer = null;
    const save = (name, value) => {
      if (frame && frame.contentWindow) frame.contentWindow.postMessage({ type: 'pantheon-var', name, value }, '*');
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const w = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/adjust`,
          { ...where(), selector: ':root', props: { [name]: value } });
        if (!w.ok) ctx.say(w.sentence, { error: true });
        else { ctx.say(`Tweaked; kept as version ${w.data.version}.`); state.data.versions.push({ n: w.data.version, note: `Tweaked ${name}` }); drawPanel(); }
      }, 600);
    };
    (r.data.tweaks || []).forEach((t) => {
      const row = _el('label', 'design-field design-tweak');
      const out = _el('span', 'design-tweak-value', `${t.value}${t.unit || ''}`);
      const cap = _el('span', '', t.label);
      cap.appendChild(out);
      row.appendChild(cap);
      const i = document.createElement('input');
      if (t.kind === 'colour') {
        i.type = 'color';
        i.value = t.value;
        i.addEventListener('input', () => { out.textContent = i.value; save(t.name, i.value); });
      } else {
        i.type = 'range';
        i.min = String(t.min);
        i.max = String(t.max);
        i.step = String(t.step);
        i.value = String(t.value);
        i.addEventListener('input', () => { out.textContent = `${i.value}${t.unit || ''}`; save(t.name, `${i.value}${t.unit || ''}`); });
      }
      i.setAttribute('aria-label', t.label);
      row.appendChild(i);
      box.appendChild(row);
    });
    state.tweaks = box;
    drawPanel();
  }

  async function restore(n) {
    const r = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/restore`, { ...where(), version: n });
    if (!r.ok) { ctx.say(r.sentence, { error: true }); return; }
    ctx.say(`Stepped back to version ${n}; what was there is kept as a version too.${(r.data.left || []).length ? ` Files from later stay: ${r.data.left.join(', ')}.` : ''}`);
    state.selected = null;
    await load();
  }

  async function keep(v) {
    const r = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/keep`, { ...where(), variant: v });
    if (!r.ok) { ctx.say(r.sentence, { error: true }); return; }
    ctx.say(`Kept variant ${v}.${r.data.others.length ? ` Variant${r.data.others.length > 1 ? 's' : ''} ${r.data.others.join(', ')} kept as versions.` : ''}`);
    state.selected = null;
    await load();
  }

  await load();
}

export default { renderDesign, choicesFor, PICKED_PROPS };
