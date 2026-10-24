// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P26-01` … `P26-03`. Notes pinned to the page in the agent browser's window.
//
// The owner (2026-10-24): *"the "Design" suite - where you can add real-time
// notes to the browser similar to how Claude has it as well as Codex."*
//
// **Note** turns the next click on the page into a note on the element under
// it; the daemon keeps what finds that element again (`workstation/page_notes.py`)
// and, each new frame, says where it is now — so a pin follows its element and
// a note whose element is gone says *lost* in the list instead of floating over
// the wrong thing. A note can be drawn on (arrow, circle, box, line), the
// marks kept relative to the element so they move with it. **Send** writes one
// message: the notes in words, each with a crop of the page as it is now with
// its pin and marks drawn on, and the agent reads and closes them with
// `agent_browser notes` / `note_done` — the pins grey as it does.
//
// Every value from the server is text (`textContent`); the marks are SVG built
// with `createElementNS`. Nothing here parses server text as HTML.

// A leaf: it imports nothing. The window hands it `mapPoint`
// (`workstationScreen.js`'s, the one screen-to-page rule) with its parts.

const SVG_NS = 'http://www.w3.org/2000/svg';
const LOCATE_MS = 900;
const CROP_PAD = 72;
const CROP_MIN = { w: 360, h: 220 };
const KINDS = [['arrow', 'Arrow'], ['circle', 'Circle'], ['box', 'Box'], ['line', 'Line']];
const STATUS_WORDS = { open: 'open', sent: 'sent', done: 'done', declined: 'not done' };

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function _button(cls, text, onClick, label) {
  const b = _el('button', cls, text);
  b.type = 'button';
  if (label) { b.title = label; b.setAttribute('aria-label', label); }
  b.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); onClick(e); });
  return b;
}

/** A note as the model and the person read it. */
export function describeNote(n) {
  const a = n.anchor || {};
  const what = `${a.tag || 'element'}${a.text ? ` “${a.text}”` : ''}`;
  return `${what}${n.lost ? ' — no longer on the page' : ''}`;
}

/** The message Send writes: the notes in words, in order. */
export function notesMessage(notes, { title = '', url = '' } = {}) {
  const lines = [`I left ${notes.length} note${notes.length === 1 ? '' : 's'} on ${title || 'the page'}${url ? ` (${url})` : ''}. `
    + 'For each, change what it asks. Read them with agent_browser notes, and close each with note_done '
    + '— said: what you did, or declined: true and why not. The pictures show each note on the page as it is now.', ''];
  notes.forEach((n) => {
    const drawn = (n.shapes || []).length ? ` [${n.shapes.length} mark${n.shapes.length === 1 ? '' : 's'} drawn]` : '';
    lines.push(`Note ${n.n} — on ${describeNote(n)}${drawn}: ${n.text || '(no words — see the picture)'}`);
  });
  return lines.join('\n');
}

/** The crop around a note's element, in page pixels, inside the frame. */
export function cropBox(box, w, h) {
  if (!box) return { x: 0, y: 0, w: Math.min(w, 800), h: Math.min(h, 500) };
  let x = box[0] - CROP_PAD;
  let y = box[1] - CROP_PAD;
  let cw = Math.max(box[2] + CROP_PAD * 2, CROP_MIN.w);
  let ch = Math.max(box[3] + CROP_PAD * 2, CROP_MIN.h);
  if (cw > w) cw = w;
  if (ch > h) ch = h;
  x = Math.max(0, Math.min(x - (cw - (box[2] + CROP_PAD * 2)) / 2, w - cw));
  y = Math.max(0, Math.min(y - (ch - (box[3] + CROP_PAD * 2)) / 2, h - ch));
  return { x: Math.round(x), y: Math.round(y), w: Math.round(cw), h: Math.round(ch) };
}

function _accent() {
  try { return getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || ''; } catch (_) { return ''; }
}

function _shapePath(kind, pts) {
  const [a, b] = [pts[0], pts[pts.length - 1]];
  if (kind === 'line') return { tag: 'polyline', attrs: { points: pts.map((p) => p.join(',')).join(' ') } };
  if (kind === 'box') {
    return { tag: 'rect', attrs: { x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]), width: Math.abs(b[0] - a[0]), height: Math.abs(b[1] - a[1]), rx: 4 } };
  }
  if (kind === 'circle') {
    return { tag: 'ellipse', attrs: { cx: (a[0] + b[0]) / 2, cy: (a[1] + b[1]) / 2, rx: Math.abs(b[0] - a[0]) / 2, ry: Math.abs(b[1] - a[1]) / 2 } };
  }
  return { tag: 'line', attrs: { x1: a[0], y1: a[1], x2: b[0], y2: b[1], 'marker-end': 'url(#abw-note-arrow)' } };
}

/** Draw one mark onto a 2D canvas context (for the crop), at `dx, dy`. */
function _strokeOnCanvas(ctx, kind, pts, dx, dy) {
  const P = pts.map((p) => [p[0] + dx, p[1] + dy]);
  const [a, b] = [P[0], P[P.length - 1]];
  ctx.beginPath();
  if (kind === 'line') { P.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]))); }
  else if (kind === 'box') ctx.rect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
  else if (kind === 'circle') ctx.ellipse((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, Math.abs(b[0] - a[0]) / 2 || 1, Math.abs(b[1] - a[1]) / 2 || 1, 0, 0, Math.PI * 2);
  else {
    ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
    const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
    ctx.moveTo(b[0], b[1]); ctx.lineTo(b[0] - 14 * Math.cos(ang - 0.45), b[1] - 14 * Math.sin(ang - 0.45));
    ctx.moveTo(b[0], b[1]); ctx.lineTo(b[0] - 14 * Math.cos(ang + 0.45), b[1] - 14 * Math.sin(ang + 0.45));
  }
  ctx.stroke();
}

/**
 * The notes layer for one window. `win` is the window's parts (`page`, `img`,
 * `stage`), `size()` the frame's pixels, `say(text, {error})` its status line,
 * `send(text, files)` what writes a message into the chat.
 */
export function createNotes({ win, size, say, send, frameInfo, mapPoint }) {
  let notes = [];
  let mode = null;          // null | 'note' | 'draw'
  let drawing = null;       // { noteId, kind, points }
  let drawKind = 'arrow';
  let drawFor = null;
  let lastLocate = 0;
  let locateTimer = null;
  let editor = null;

  // ── toolbar ───────────────────────────────────────────────────────────────
  const bar = _el('div', 'abw-notes-bar');
  bar.setAttribute('role', 'toolbar');
  bar.setAttribute('aria-label', 'Notes');
  const noteBtn = _button('abw-notes-btn abw-note-mode', 'Note', () => setMode(mode === 'note' ? null : 'note'),
    'Pin a note to an element: click this, then the element (N)');
  noteBtn.setAttribute('aria-pressed', 'false');
  const kindSel = document.createElement('select');
  kindSel.className = 'abw-notes-kind';
  kindSel.setAttribute('aria-label', 'Mark');
  KINDS.forEach(([k, label]) => { const o = document.createElement('option'); o.value = k; o.textContent = label; kindSel.appendChild(o); });
  kindSel.addEventListener('change', () => { drawKind = kindSel.value; });
  kindSel.hidden = true;
  const sendBtn = _button('abw-notes-btn abw-notes-send', 'Send notes', () => { sendNotes(); }, 'Send the open notes to the agent as one message');
  sendBtn.hidden = true;
  bar.appendChild(noteBtn);
  bar.appendChild(kindSel);
  bar.appendChild(sendBtn);

  // ── the layer over the page: pins and marks ───────────────────────────────
  const layer = _el('div', 'abw-notes-layer');
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'abw-notes-marks');
  svg.setAttribute('aria-hidden', 'true');
  layer.appendChild(svg);
  win.page.appendChild(layer);

  // ── the list ──────────────────────────────────────────────────────────────
  const list = _el('ol', 'abw-notes-list');
  list.setAttribute('aria-label', 'Notes on this page');
  list.hidden = true;

  function _frameRects() {
    return { img: win.img.getBoundingClientRect(), page: win.page.getBoundingClientRect() };
  }

  /** Page pixels → place in the page box (the `placeOf` of browserWindow.js). */
  function _place(x, y) {
    const { img, page } = _frameRects();
    const s = size();
    if (!(img.width > 0) || !(s.w > 0)) return null;
    return { left: img.left - page.left + (x / s.w) * img.width, top: img.top - page.top + (y / s.h) * img.height, k: img.width / s.w };
  }

  function _drawLayer() {
    // Pins.
    layer.querySelectorAll('.abw-note-pin').forEach((p) => p.remove());
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const { img, page } = _frameRects();
    svg.setAttribute('width', String(Math.round(page.width)));
    svg.setAttribute('height', String(Math.round(page.height)));
    const colour = _accent();
    if (colour) layer.style.color = colour;
    const defs = document.createElementNS(SVG_NS, 'defs');
    const marker = document.createElementNS(SVG_NS, 'marker');
    Object.entries({ id: 'abw-note-arrow', viewBox: '0 0 10 10', refX: '8', refY: '5', markerWidth: '6', markerHeight: '6', orient: 'auto-start-reverse' })
      .forEach(([k, v]) => marker.setAttribute(k, v));
    const tip = document.createElementNS(SVG_NS, 'path');
    tip.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
    tip.setAttribute('fill', 'currentColor');
    marker.appendChild(tip);
    defs.appendChild(marker);
    svg.appendChild(defs);
    notes.forEach((n) => {
      if (!n.box || n.where !== 'here') return;
      const at = _place(n.box[0] + (n.at ? n.at[0] : 0), n.box[1] + (n.at ? n.at[1] : 0));
      if (!at) return;
      const pin = _el('button', `abw-note-pin abw-note-${n.status}`, String(n.n));
      pin.type = 'button';
      pin.title = `${n.n}. ${n.text || describeNote(n)}`;
      pin.setAttribute('aria-label', `Note ${n.n}: ${n.text || describeNote(n)}`);
      pin.style.transform = `translate(${Math.round(at.left)}px, ${Math.round(at.top)}px)`;
      pin.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); _focusItem(n.id); });
      layer.appendChild(pin);
      const origin = _place(n.box[0], n.box[1]);
      if (!origin) return;
      (n.shapes || []).forEach((s) => {
        const pts = s.points.map((p) => [origin.left + p[0] * origin.k, origin.top + p[1] * origin.k]);
        const { tag, attrs } = _shapePath(s.kind, pts);
        const node = document.createElementNS(SVG_NS, tag);
        Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, String(v)));
        node.setAttribute('class', `abw-note-mark abw-note-${n.status}`);
        svg.appendChild(node);
      });
    });
    if (drawing && drawing.points.length > 1) {
      const pts = drawing.points.map((p) => { const q = _place(p[0], p[1]); return [q.left, q.top]; });
      const { tag, attrs } = _shapePath(drawing.kind, pts);
      const node = document.createElementNS(SVG_NS, tag);
      Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, String(v)));
      node.setAttribute('class', 'abw-note-mark abw-note-drawing');
      svg.appendChild(node);
    }
    void img;   // the frame's box is read through `_place`; kept for symmetry with `page`
  }

  function _focusItem(id) {
    const item = [...list.querySelectorAll('[data-note-id]')].find((li) => li.dataset.noteId === id);
    if (item) { item.scrollIntoView?.({ block: 'nearest' }); const t = item.querySelector('.abw-note-text'); if (t) t.focus(); }
  }

  function _drawList() {
    list.textContent = '';
    const shown = notes.filter((n) => n.status !== 'done' || n.said);
    list.hidden = !shown.length;
    shown.forEach((n) => {
      const li = _el('li', `abw-note-item abw-note-${n.status}`);
      li.dataset.noteId = n.id;
      const head = _el('div', 'abw-note-head');
      head.appendChild(_el('span', 'abw-note-num', String(n.n)));
      head.appendChild(_el('span', 'abw-note-where', describeNote(n)
        + (n.where === 'above' ? ' · scrolled above' : n.where === 'below' ? ' · scrolled below' : '')));
      head.appendChild(_el('span', 'abw-note-status', STATUS_WORDS[n.status] || n.status));
      li.appendChild(head);
      const text = _el('div', 'abw-note-text', n.text || '');
      text.tabIndex = 0;
      if (n.status === 'open') {
        text.contentEditable = 'true';
        text.setAttribute('role', 'textbox');
        text.setAttribute('aria-label', `Note ${n.n}`);
        text.addEventListener('blur', () => {
          const t = (text.textContent || '').trim();
          if (t !== (n.text || '')) _post({ action: 'note_edit', note: n.id, text: t });
        });
      }
      li.appendChild(text);
      if (n.said) li.appendChild(_el('div', 'abw-note-said', `Agent: ${n.said}`));
      const tools = _el('div', 'abw-note-tools');
      if (n.status === 'open' && !n.lost) {
        tools.appendChild(_button('abw-note-tool', drawFor === n.id ? 'Done drawing' : 'Draw',
          () => { drawFor = drawFor === n.id ? null : n.id; setMode(drawFor ? 'draw' : null); _drawList(); },
          `Draw on the page beside note ${n.n}`));
        if ((n.shapes || []).length) {
          tools.appendChild(_button('abw-note-tool', 'Clear marks', () => _post({ action: 'note_edit', note: n.id, shapes: [] })));
        }
      }
      if (n.status === 'done' || n.status === 'declined') {
        tools.appendChild(_button('abw-note-tool', 'Reopen', () => _post({ action: 'note_done', note: n.id, status: 'open' })));
      }
      tools.appendChild(_button('abw-note-tool abw-note-remove', 'Remove', () => _post({ action: 'note_remove', note: n.id })));
      li.appendChild(tools);
      list.appendChild(li);
    });
    const open = notes.filter((n) => n.status === 'open');
    sendBtn.hidden = !open.length;
    sendBtn.textContent = `Send ${open.length} note${open.length === 1 ? '' : 's'}`;
  }

  function _apply(answer) {
    if (!answer || !Array.isArray(answer.notes)) return;
    notes = answer.notes;
    _drawList();
    _drawLayer();
  }

  async function _post(body) {
    try {
      const res = await fetch('/api/workstation/browser', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      let data = null;
      try { data = await res.json(); } catch (_) { data = null; }
      if (!res.ok) { say((data && data.detail) || 'That note was not saved.', { error: true }); return null; }
      _apply(data);
      return data;
    } catch (e) {
      say(`Pantheon could not reach the browser: ${String((e && e.message) || e)}`, { error: true });
      return null;
    }
  }

  function setMode(next) {
    mode = next;
    if (next !== 'draw') drawFor = null;
    noteBtn.setAttribute('aria-pressed', String(mode === 'note'));
    kindSel.hidden = mode !== 'draw';
    win.page.classList.toggle('abw-noting', !!mode);
    if (mode === 'note') say('Click the element the note is about.');
    else if (mode === 'draw') say('Drag on the page to draw beside the note.');
    _drawList();
  }

  function _closeEditor() { if (editor) { editor.remove(); editor = null; } }

  function _openEditor(p, ev) {
    _closeEditor();
    const { page } = _frameRects();
    editor = _el('form', 'abw-note-editor');
    editor.style.left = `${Math.round(ev.clientX - page.left)}px`;
    editor.style.top = `${Math.round(ev.clientY - page.top)}px`;
    const input = document.createElement('textarea');
    input.className = 'abw-note-input';
    input.rows = 2;
    input.maxLength = 2000;
    input.placeholder = 'What should change here?';
    input.setAttribute('aria-label', 'Note');
    const save = _el('button', 'memory-toolbar-btn', 'Pin note');
    save.type = 'submit';
    const cancel = _button('memory-toolbar-btn', 'Cancel', () => _closeEditor());
    editor.appendChild(input);
    editor.appendChild(save);
    editor.appendChild(cancel);
    editor.addEventListener('click', (e) => e.stopPropagation());
    editor.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Escape') { e.preventDefault(); _closeEditor(); }
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); editor.requestSubmit ? editor.requestSubmit() : save.click(); }
    });
    editor.addEventListener('submit', async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      _closeEditor();
      const got = await _post({ action: 'note_add', x: p.x, y: p.y, text });
      if (got) say(`Pinned. ${text ? '' : 'Add words to it in the list. '}Send the notes when you are ready.`);
    });
    win.page.appendChild(editor);
    input.focus();
  }

  function _pointAt(ev) {
    const s = size();
    return mapPoint(ev.clientX, ev.clientY, win.img.getBoundingClientRect(), s.w, s.h);
  }

  function _onClick(ev) {
    if (mode !== 'note') return;
    if (ev.target.closest && ev.target.closest('.abw-note-editor, .abw-note-pin')) return;
    const p = _pointAt(ev);
    if (!p) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    _openEditor(p, ev);
    setMode(null);
    say('');
  }

  function _onDown(ev) {
    if (mode !== 'draw' || !drawFor) return;
    const p = _pointAt(ev);
    if (!p) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    drawing = { noteId: drawFor, kind: drawKind, points: [[p.x, p.y]] };
    try { win.page.setPointerCapture(ev.pointerId); } catch (_) {}
  }

  function _onMove(ev) {
    if (!drawing) return;
    const p = _pointAt(ev);
    if (!p) return;
    if (drawing.kind === 'line') { if (drawing.points.length < 200) drawing.points.push([p.x, p.y]); }
    else drawing.points = [drawing.points[0], [p.x, p.y]];
    _drawLayer();
  }

  async function _onUp() {
    if (!drawing) return;
    const d = drawing;
    drawing = null;
    const n = notes.find((x) => x.id === d.noteId);
    if (!n || !n.box || d.points.length < 2) { _drawLayer(); return; }
    const rel = d.points.map((p) => [p[0] - n.box[0], p[1] - n.box[1]]);
    await _post({ action: 'note_edit', note: n.id, shapes: [...(n.shapes || []), { kind: d.kind, points: rel }] });
  }

  // Before the window's own click handler (capture), so a note click is never
  // also a click on the page.
  win.page.addEventListener('click', _onClick, true);
  win.page.addEventListener('pointerdown', _onDown, true);
  win.page.addEventListener('pointermove', _onMove);
  win.page.addEventListener('pointerup', _onUp);
  win.page.addEventListener('pointercancel', _onUp);
  win.page.addEventListener('keydown', (ev) => {
    if (ev.key === 'n' && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !win.page.classList.contains('abw-holding')) {
      ev.preventDefault();
      setMode(mode === 'note' ? null : 'note');
    }
  });

  /** A new frame was drawn: ask where the notes' elements are now — at most
   *  once a `LOCATE_MS`, and only when there are notes to place. */
  function onFrame() {
    if (!notes.length && !mode) { _drawLayer(); return; }
    const wait = Math.max(0, LOCATE_MS - (Date.now() - lastLocate));
    if (locateTimer) return;
    locateTimer = setTimeout(() => {
      locateTimer = null;
      lastLocate = Date.now();
      _post({ action: 'notes' });
    }, wait);
  }

  async function sendNotes() {
    const open = notes.filter((n) => n.status === 'open');
    if (!open.length) return;
    const s = size();
    const files = [];
    if (win.img.naturalWidth > 0) {
      for (const n of open) {
        const c = cropBox(n.box && n.where === 'here' ? n.box : null, win.img.naturalWidth, win.img.naturalHeight);
        const canvas = document.createElement('canvas');
        canvas.width = c.w;
        canvas.height = c.h;
        const ctx = canvas.getContext('2d');
        if (!ctx) continue;
        const k = win.img.naturalWidth / (s.w || win.img.naturalWidth);
        ctx.drawImage(win.img, c.x, c.y, c.w, c.h, 0, 0, c.w, c.h);
        const colour = _accent() || '#e5484d';
        ctx.strokeStyle = colour;
        ctx.fillStyle = colour;
        ctx.lineWidth = 3;
        if (n.box && n.where === 'here') {
          (n.shapes || []).forEach((sh) => _strokeOnCanvas(ctx, sh.kind,
            sh.points.map((p) => [(n.box[0] + p[0]) * k, (n.box[1] + p[1]) * k]), -c.x, -c.y));
          const px = (n.box[0] + (n.at ? n.at[0] : 0)) * k - c.x;
          const py = (n.box[1] + (n.at ? n.at[1] : 0)) * k - c.y;
          ctx.beginPath(); ctx.arc(px, py, 12, 0, Math.PI * 2); ctx.fill();
          ctx.fillStyle = '#fff'; ctx.font = 'bold 13px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText(String(n.n), px, py + 0.5);
        }
        const blob = await new Promise((r) => canvas.toBlob(r, 'image/png'));
        if (blob) files.push(new File([blob], `note-${n.n}.png`, { type: 'image/png' }));
      }
    }
    setMode(null);
    const info = frameInfo ? frameInfo() : {};
    const ok = await send(notesMessage(open, info), files);
    if (ok === false) return;
    await _post({ action: 'notes_sent', notes: open.map((n) => n.id) });
    say(`Sent ${open.length} note${open.length === 1 ? '' : 's'} to the agent.`);
  }

  function destroy() {
    if (locateTimer) clearTimeout(locateTimer);
    _closeEditor();
    layer.remove();
  }

  _post({ action: 'notes' });
  return { bar, list, onFrame, setMode, sendNotes, destroy, notes: () => notes.map((n) => ({ ...n })) };
}
