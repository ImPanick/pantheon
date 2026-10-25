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
  const q = (extra = '') => `?project=${encodeURIComponent(ctx.project)}${extra}`;
  const previewUrl = (extra = '') => `/api/design/designs/${encodeURIComponent(ctx.slug)}/preview${q(extra)}`;
  const state = { showing: {}, selected: null, selecting: false, data: null };
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
    if (live) {
      const sel = _btn('design-btn design-select-btn', 'Select', () => setSelecting(!state.selecting),
        'Select an element on the page to adjust it');
      sel.setAttribute('aria-pressed', String(state.selecting));
      bar.appendChild(sel);
      bar.appendChild(_btn('design-btn', 'Tweaks', () => drawTweaks()));
      const n = document.createElement('select');
      n.setAttribute('aria-label', 'How many variants');
      ['2', '3', '4'].forEach((k) => { const o = document.createElement('option'); o.value = k; o.textContent = `${k} variants`; n.appendChild(o); });
      bar.appendChild(n);
      bar.appendChild(_btn('design-btn', 'Try variants', () => {
        const k = Number(n.value);
        ctx.sendToChat(`Make ${k} variants of the design in ${d.folder}/ — each a different direction on the same brief `
          + `(layout, density, emphasis), each self-contained in ${d.folder}/variants/1/index.html … `
          + `${d.folder}/variants/${k}/index.html, using the same :root variables. Do not change ${d.folder}/index.html. `
          + 'Say when they are there.');
        ctx.say(`Asked for ${k} variants. Open this design again when the agent says they are there.`);
      }));
      bar.appendChild(_btn('design-btn', 'Keep a version', async () => {
        const r = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/versions`, { project: ctx.project });
        if (!r.ok) { ctx.say(r.sentence, { error: true }); return; }
        ctx.say(r.data.new ? `Kept as version ${r.data.version}.` : `Nothing changed since version ${r.data.version}.`);
        await load();
      }));
    } else {
      const what = state.showing.version ? `version ${state.showing.version}` : `variant ${state.showing.variant}`;
      bar.appendChild(_el('span', 'design-chip', `Showing ${what}`));
      if (state.showing.version) {
        bar.appendChild(_btn('design-btn design-btn-primary', 'Step back to this', () => restore(state.showing.version)));
      } else {
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
        top.appendChild(_btn('design-btn design-btn-primary', 'Keep this', () => keep(v)));
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
    if (vs.length >= 2 && !state.showing.version && !state.showing.variant) {
      box.appendChild(_btn('design-btn', 'Undo the last change', () => restore(vs[vs.length - 2].n)));
    }
  }

  function drawPanel() {
    side.textContent = '';
    const s = state.selected;
    if (s && !state.showing.version && !state.showing.variant) {
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
          { project: ctx.project, selector: s.selector, props: change, system: state.data.system || null });
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
    drawVersions(side);
  }

  async function drawTweaks() {
    const r = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/tweaks`, { project: ctx.project });
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
          { project: ctx.project, selector: ':root', props: { [name]: value } });
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
    const r = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/restore`, { project: ctx.project, version: n });
    if (!r.ok) { ctx.say(r.sentence, { error: true }); return; }
    ctx.say(`Stepped back to version ${n}; what was there is kept as a version too.${(r.data.left || []).length ? ` Files from later stay: ${r.data.left.join(', ')}.` : ''}`);
    state.selected = null;
    await load();
  }

  async function keep(v) {
    const r = await ctx.call('POST', `/api/design/designs/${encodeURIComponent(ctx.slug)}/keep`, { project: ctx.project, variant: v });
    if (!r.ok) { ctx.say(r.sentence, { error: true }); return; }
    ctx.say(`Kept variant ${v}.${r.data.others.length ? ` Variant${r.data.others.length > 1 ? 's' : ''} ${r.data.others.join(', ')} kept as versions.` : ''}`);
    state.selected = null;
    await load();
  }

  await load();
}

export default { renderDesign, choicesFor, PICKED_PROPS };
