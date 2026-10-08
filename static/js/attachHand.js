// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/attachHand.js
//
// `B-NEW-1` (fx5-cards). The composer's attachments, drawn as a hand of cards.
//
// The owner, 2026-10-08, from a phone: *"The images or attachments sent to the
// chat have a massive blank space blocking view."* The strip above the message
// box was a block in the composer's column, so whatever it held took that much
// height from the chat: measured on `0345288` in Chromium on the showcase world,
// the chat lost 57px to one image, 68px to three files and 42px to the "7 files"
// pill, at 1440×900 and at 390×844 alike, and the end of the reply sat behind a
// band of empty page with one thumbnail at its left end.
//
// What it is now, in the owner's words where they gave them:
//
//   * no band. The strip keeps its place in the column and gives its height
//     back (`style.css`, `.attach-strip.attach-hand`): the chat runs down to the
//     message box, and the only thing over it is the cards;
//   * *"a micro card pop up (animated slide up)"* per attachment — its
//     thumbnail, or its type and a short name — dealt once, not re-dealt on
//     every redraw (`_dealt`);
//   * *"a hand of cards"*: later cards sit behind the first, fanned; the front
//     card carries the count; past `FAN_MAX` the rest tuck behind the last one
//     and a "+N" spreads the whole hand;
//   * *"mouse-over ... will slightly bring up the card"*: hover or keyboard
//     focus lifts a card and brings it forward — a transform and a z-index,
//     nothing reflows;
//   * *"'selecting it' and right clicking it gives additional actions"*: a click
//     or Enter selects; right-click, Shift+F10, the menu key or a long press opens
//     the card's menu, on the Escape stack (`escMenuStack.js`, C-NAV).
//
// Every action is one the product already had for an attachment, reached from
// a new place: Preview is the chat's own lightbox (`.attach-lightbox`); Crop is
// the composer's own cropper, which until now only a phone ever saw; Save to
// Gallery is `POST /api/gallery/upload`, the route the Gallery's own upload
// uses; Remove and Remove all are the old strip's × and its pill's ×. The image
// editor is not offered: it has no way to hand an edit back to the composer, so
// from here it would edit a copy the message never sends (`B-NEW-2`).
//
// No DOM is assumed beyond what `fileHandler.js`'s node harnesses give it:
// every call into the page is one the shims in `tests/` answer.

import { bindMenuDismiss, registerMenuDismiss } from './escMenuStack.js';
import { topPortalZ } from './toolWindowZOrder.js';
import { attachmentKind, KIND_LABELS, formatBytes } from './contextUsage.js';
import { toolShown } from './ui_visibility.js';
import { readRefusal } from './workbench/refusal.js';

/** Cards fanned out before the rest tuck behind the last one. */
export const FAN_MAX = 5;
/** How long a touch has to rest on a card to open its menu. */
export const LONG_PRESS_MS = 480;
const MOVE_SLOP = 10;
// What `POST /api/gallery/upload` takes for a picture (its `IMAGE_EXTS`), so
// the menu does not offer a save the route will refuse.
const GALLERY_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'gif'];
// Read as text in the preview: code and prose, and the two sheets that are text
// (an .xlsx is a zip, and would print as noise).
const TEXT_KINDS = ['code', 'text'];
const TEXT_SHEETS = ['csv', 'tsv'];
const TEXT_PREVIEW_BYTES = 64 * 1024;

let _strip = null;
let _host = {};
let _selected = null;      // the File whose card is selected
let _expanded = false;     // the "+N" spread
const _dealt = new WeakSet();
let _menu = null;          // { el, file, close }
let _preview = null;       // { el, close }
let _press = null;         // a touch waiting to become a long press
let _swallowClick = false; // the click that ends a long press is not a tap
let _outsideOff = null;

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function _setVar(node, key, value) {
  const s = node && node.style;
  if (!s) return;
  if (typeof s.setProperty === 'function') s.setProperty(key, value);
  else s[key] = value;
}

function _files() {
  try { return (_host.files && _host.files()) || []; } catch (_) { return []; }
}

function _ext(name) {
  const base = String(name || '').split(/[\\/]/).pop();
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : '';
}

/** The test the composer has always used to decide a file gets a thumbnail. */
export function isImageFile(f) {
  const type = String((f && f.type) || '');
  return type.startsWith('image/') || /\.(png|jpg|jpeg|gif|webp|svg|bmp)$/i.test((f && f.name) || '');
}

/** The name a card shows — `getPendingInfo()`'s, so the bubble and the card agree. */
export function displayName(f) {
  return (f && f.name) || 'pasted-image';
}

/** The word on a card that has no picture: its extension, or its kind. */
export function glyphFor(f) {
  const ext = _ext(displayName(f));
  if (ext && ext.length <= 4) return ext.toUpperCase();
  const kind = attachmentKind(displayName(f), f && f.type);
  return KIND_LABELS[kind] || KIND_LABELS.file;
}

function _say(message, isError) {
  const fn = isError ? _host.error : _host.toast;
  if (typeof fn === 'function') fn(message);
}

// ── drawing ─────────────────────────────────────────────────────────────────

/**
 * Deal `files` into `strip`, which the caller has emptied. Called on every
 * redraw of the strip, with an empty list too, so a selection or a menu that
 * belonged to a file that has gone goes with it.
 */
export function drawHand(strip, files, host) {
  _strip = strip;
  _host = host || {};
  const list = Array.isArray(files) ? files : [];
  const n = list.length;
  if (_selected && !list.includes(_selected)) _select(null);
  if (_menu && !list.includes(_menu.file)) _menu.close();
  if (n <= FAN_MAX) _expanded = false;
  if (!strip) return;
  strip.classList.add('attach-hand');
  strip.classList.toggle('hand-open', _expanded);
  strip.setAttribute('role', 'list');
  strip.setAttribute('aria-label', 'Attachments');
  const shown = _expanded ? n : Math.min(n, FAN_MAX);
  _setVar(strip, '--hand-gaps', String(Math.max(1, n - 1)));
  _setVar(strip, '--hand-last', String(Math.max(0, shown - 1)));
  list.forEach((f, i) => strip.appendChild(_card(f, i, n)));
  if (n > FAN_MAX) strip.appendChild(_moreChip(n));
}

function _card(f, i, n) {
  const name = displayName(f);
  const item = _el('div', 'thumb hand-card');
  item.setAttribute('role', 'listitem');
  item.dataset.index = String(i);
  item._handFile = f;
  _setVar(item, '--slot', String(_expanded ? i : Math.min(i, FAN_MAX - 1)));
  _setVar(item, '--z', String(n - i));
  if (!_expanded && i >= FAN_MAX) item.classList.add('hand-card-tucked');
  if (!_dealt.has(f)) {
    _dealt.add(f);
    item.classList.add('hand-card-new');
  }
  const selected = f === _selected;
  if (selected) item.classList.add('is-selected');

  const lift = _el('div', 'hand-card-lift');
  const btn = _el('button', 'hand-card-btn');
  btn.type = 'button';
  btn.title = name;
  btn.setAttribute('aria-label', `${name}, ${i + 1} of ${n}`);
  btn.setAttribute('aria-pressed', selected ? 'true' : 'false');
  btn.setAttribute('aria-haspopup', 'menu');
  btn.setAttribute('aria-keyshortcuts', 'Shift+F10 Delete');
  if (isImageFile(f)) {
    item.classList.add('hand-card-image');
    const img = _el('img', 'hand-card-img');
    img.alt = '';
    img.draggable = false;
    img.addEventListener('error', () => {
      // A picture the browser cannot draw (a HEIC named .jpg, a broken file)
      // still gets a face: its type and name, like any other file.
      item.classList.remove('hand-card-image');
      if (img.parentNode) img.parentNode.removeChild(img);
      _faceFor(btn, f);
    });
    img.src = typeof _host.previewUrl === 'function' ? _host.previewUrl(f) : '';
    btn.appendChild(img);
  } else {
    _faceFor(btn, f);
  }
  lift.appendChild(btn);
  item._handBtn = btn;

  if (i === 0 && n > 1) {
    const count = _el('span', 'hand-count', String(n));
    count.setAttribute('aria-hidden', 'true');
    lift.appendChild(count);
  }

  const x = _el('button', 'hand-card-x', '×');
  x.type = 'button';
  x.tabIndex = -1;
  x.title = 'Remove';
  x.setAttribute('aria-label', `Remove ${name}`);
  x.addEventListener('click', (e) => {
    e.stopPropagation();
    _remove(f, e.detail === 0);
  });
  lift.appendChild(x);
  item.appendChild(lift);
  _wire(btn, item, f);
  return item;
}

function _faceFor(btn, f) {
  const glyph = _el('span', 'hand-card-glyph', glyphFor(f));
  glyph.setAttribute('aria-hidden', 'true');
  const label = _el('span', 'hand-card-name', displayName(f));
  label.setAttribute('aria-hidden', 'true');
  btn.appendChild(glyph);
  btn.appendChild(label);
}

function _moreChip(n) {
  const hidden = n - FAN_MAX;
  const chip = _el('button', 'hand-more', _expanded ? '−' : `+${hidden}`);
  chip.type = 'button';
  // A pointer's way to the tucked cards. The keyboard already reaches each of
  // them — every card is in the tab order and comes forward when focused — so
  // the chip is kept out of it and out of the list a screen reader counts.
  chip.tabIndex = -1;
  chip.setAttribute('aria-hidden', 'true');
  chip.title = _expanded ? 'Show fewer' : `Show all ${n}`;
  chip.addEventListener('click', (e) => {
    e.stopPropagation();
    _expanded = !_expanded;
    if (typeof _host.redraw === 'function') _host.redraw();
  });
  return chip;
}

// ── selecting ───────────────────────────────────────────────────────────────

function _cards() {
  if (!_strip) return [];
  return Array.prototype.filter.call(_strip.children || [], (c) => c && c._handFile);
}

function _select(f) {
  _selected = f || null;
  for (const card of _cards()) {
    const on = card._handFile === _selected;
    card.classList.toggle('is-selected', on);
    if (card._handBtn) card._handBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
  }
  // A selected card stays up until something else is touched — the message
  // box, the chat — the way a card on a table goes back down when you reach
  // for something else.
  if (_selected && !_outsideOff && typeof document.addEventListener === 'function') {
    const onDown = (ev) => {
      const t = ev && ev.target;
      if (t && _strip && typeof _strip.contains === 'function' && _strip.contains(t)) return;
      if (t && _menu && _menu.el.contains(t)) return;
      if (t && _preview && _preview.el.contains(t)) return;
      _select(null);
    };
    document.addEventListener('pointerdown', onDown, true);
    _outsideOff = () => document.removeEventListener('pointerdown', onDown, true);
  } else if (!_selected && _outsideOff) {
    _outsideOff();
    _outsideOff = null;
  }
}

function _focusCard(i) {
  const cards = _cards();
  const card = cards[Math.max(0, Math.min(i, cards.length - 1))];
  if (card && card._handBtn) { card._handBtn.focus(); return true; }
  return false;
}

function _focusComposer() {
  const box = document.getElementById('message');
  if (box && typeof box.focus === 'function') box.focus();
}

function _wire(btn, item, f) {
  btn.addEventListener('click', () => {
    if (_swallowClick) { _swallowClick = false; return; }
    if (_menu && _menu.file === f) { _menu.close(); return; }
    _select(_selected === f ? null : f);
  });
  btn.addEventListener('dblclick', (e) => {
    if (e && e.preventDefault) e.preventDefault();
    _select(f);
    openPreview(f);
  });
  btn.addEventListener('contextmenu', (e) => {
    // Right-click, and on Android the long press — the browser's own menu for
    // an image would otherwise open over ours.
    if (e && e.preventDefault) e.preventDefault();
    _select(f);
    openMenu(f, item);
  });
  btn.addEventListener('keydown', (e) => _onKey(e, f, item));
  btn.addEventListener('pointerdown', (e) => {
    _swallowClick = false;
    _cancelPress();
    if (!e || e.pointerType === 'mouse') return;
    _press = {
      x: e.clientX, y: e.clientY,
      timer: setTimeout(() => {
        _press = null;
        _swallowClick = true;
        _select(f);
        openMenu(f, item);
      }, LONG_PRESS_MS),
    };
  });
  btn.addEventListener('pointermove', (e) => {
    if (_press && Math.hypot(e.clientX - _press.x, e.clientY - _press.y) > MOVE_SLOP) _cancelPress();
  });
  for (const t of ['pointerup', 'pointercancel', 'pointerleave']) btn.addEventListener(t, _cancelPress);
}

function _cancelPress() {
  if (_press) clearTimeout(_press.timer);
  _press = null;
}

function _onKey(e, f, item) {
  if (e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey)) {
    e.preventDefault();
    _select(f);
    openMenu(f, item);
    return;
  }
  if (e.key === 'Delete' || e.key === 'Backspace') {
    e.preventDefault();
    _remove(f, true);
    return;
  }
  const i = _files().indexOf(f);
  let to = null;
  if (e.key === 'ArrowRight') to = i + 1;
  else if (e.key === 'ArrowLeft') to = i - 1;
  else if (e.key === 'Home') to = 0;
  else if (e.key === 'End') to = _files().length - 1;
  if (to === null) return;
  e.preventDefault();
  _focusCard(to);
}

// ── acting ──────────────────────────────────────────────────────────────────

/** What the card's menu offers for `f`, in order. Exported for the tests. */
export function actionsFor(f) {
  const n = _files().length;
  const image = isImageFile(f);
  const out = [{ id: 'preview', label: 'Preview', run: () => openPreview(f) }];
  if (image && typeof _host.canCrop === 'function' && _host.canCrop(f)) {
    out.push({ id: 'crop', label: 'Crop', run: (kb) => _crop(f, kb) });
  }
  const sentAs = typeof _host.wireName === 'function' ? _host.wireName(f) : displayName(f);
  if (image && GALLERY_EXTS.includes(_ext(sentAs)) && toolShown('gallery')) {
    out.push({ id: 'gallery', label: 'Save to Gallery', run: () => saveToGallery(f) });
  }
  out.push({ id: 'remove', label: 'Remove', run: (kb) => _remove(f, kb) });
  if (n > 1) out.push({ id: 'remove-all', label: 'Remove all', run: (kb) => _removeAll(kb) });
  return out;
}

async function _crop(f, fromKeyboard) {
  const i = _files().indexOf(f);
  const changed = await _host.crop(f);
  // A crop puts a new card where the old one was; the keyboard goes with it.
  // (Cancelled, the cropper hands the focus back to the card itself.)
  if (changed && fromKeyboard && i >= 0) _focusCard(i);
}

function _remove(f, fromKeyboard) {
  const i = _files().indexOf(f);
  if (i < 0) return;
  if (_selected === f) _select(null);
  if (typeof _host.remove === 'function') _host.remove(i);
  // Only a keyboard needs to be told where it is now: a mouse is where it was.
  if (fromKeyboard && !_focusCard(i)) _focusComposer();
}

function _removeAll(fromKeyboard) {
  _select(null);
  if (typeof _host.clear === 'function') _host.clear();
  if (fromKeyboard) _focusComposer();
}

/** Open the menu for `f`'s card. A second call for the same card is a no-op. */
export function openMenu(f, anchor) {
  if (_menu && _menu.file === f) return _menu.el;
  if (_menu) _menu.close();
  closePreview();
  const menu = _el('div', 'hand-menu');
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', displayName(f));
  const entry = { el: menu, file: f, close: () => {} };
  for (const action of actionsFor(f)) {
    const item = _el('button', 'hand-menu-item', action.label);
    item.type = 'button';
    item.setAttribute('role', 'menuitem');
    item.dataset.action = action.id;
    item.addEventListener('click', (ev) => {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      const fromKeyboard = !!(ev && ev.detail === 0);
      entry.close();
      action.run(fromKeyboard);
    });
    menu.appendChild(item);
  }
  document.body.appendChild(menu);
  menu.style.zIndex = String(topPortalZ());
  _place(menu, anchor && anchor._handBtn ? anchor._handBtn : anchor);
  // The card is inside: the click that ends a long press lands on it, and it
  // must not close the menu it just opened.
  entry.close = bindMenuDismiss(menu, () => {
    menu.remove();
    if (_menu === entry) _menu = null;
  }, (ev) => !menu.contains(ev.target) && !(anchor && typeof anchor.contains === 'function' && anchor.contains(ev.target)));
  _menu = entry;
  return menu;
}

function _place(menu, anchor) {
  if (!anchor || typeof anchor.getBoundingClientRect !== 'function') return;
  const r = anchor.getBoundingClientRect();
  const vw = window.innerWidth || 0;
  const vh = window.innerHeight || 0;
  const h = menu.offsetHeight || 0;
  const w = menu.offsetWidth || 0;
  // Above the card: the hand sits on the message box, so there is room above
  // it and none below.
  let top = r.top - h - 8;
  if (top < 8) top = Math.max(8, Math.min(r.bottom + 8, vh - h - 8));
  let left = r.left;
  if (vw && left + w > vw - 8) left = Math.max(8, vw - w - 8);
  menu.style.top = `${Math.round(top)}px`;
  menu.style.left = `${Math.round(left)}px`;
}

/** `POST /api/gallery/upload`, the Gallery's own upload, with this file. */
export async function saveToGallery(f) {
  const base = typeof _host.apiBase === 'function' ? _host.apiBase() : '';
  const fd = new FormData();
  fd.append('file', f, typeof _host.wireName === 'function' ? _host.wireName(f) : displayName(f));
  let res;
  try {
    res = await fetch(`${base}/api/gallery/upload`, { method: 'POST', body: fd, credentials: 'same-origin' });
  } catch (_) {
    _say('Could not reach Pantheon. The image is still attached.', true);
    return false;
  }
  if (!res.ok) {
    const refusal = await readRefusal(res, 'The Gallery did not take the image. It is still attached.');
    _say(refusal.sentence, true);
    return false;
  }
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (data && data.duplicate) {
    _say('Already in the Gallery.');
    return true;
  }
  _say('Saved to the Gallery.');
  try { window.dispatchEvent(new CustomEvent('gallery-refresh')); } catch (_) { /* no window to tell */ }
  return true;
}

// ── preview ─────────────────────────────────────────────────────────────────

export function closePreview() {
  if (_preview) _preview.close();
}

/**
 * The attachment, large. A picture is drawn the way the chat's own lightbox
 * draws one (`.attach-lightbox`); a text file shows its first 64 KB; a sound
 * plays; anything else shows what it is and how big. Escape, the ×, or a click
 * outside it closes it, and the focus goes back where it was.
 */
export function openPreview(f) {
  closePreview();
  const name = displayName(f);
  const url = typeof _host.previewUrl === 'function' ? _host.previewUrl(f) : '';
  const overlay = _el('div', 'attach-lightbox hand-preview');
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', name);
  overlay.tabIndex = -1;
  const shut = _el('button', 'hand-preview-close', '×');
  shut.type = 'button';
  shut.title = 'Close';
  shut.setAttribute('aria-label', 'Close');
  overlay.appendChild(shut);

  let body;
  if (isImageFile(f)) {
    body = _el('img', 'hand-preview-img');
    body.alt = name;
    body.src = url;
  } else {
    body = _el('div', 'hand-preview-doc');
    const kind = attachmentKind(name, f && f.type);
    const head = _el('div', 'hand-preview-head');
    const glyph = _el('span', 'hand-card-glyph', glyphFor(f));
    glyph.setAttribute('aria-hidden', 'true');
    head.appendChild(glyph);
    head.appendChild(_el('span', 'hand-preview-name', name));
    body.appendChild(head);
    const size = formatBytes(f && f.size);
    body.appendChild(_el('div', 'hand-preview-meta',
      [KIND_LABELS[kind] || KIND_LABELS.file, size].filter(Boolean).join(' · ')));
    if (kind === 'audio' && url) {
      const audio = _el('audio', 'hand-preview-audio');
      audio.controls = true;
      audio.src = url;
      body.appendChild(audio);
    } else if ((TEXT_KINDS.includes(kind) || TEXT_SHEETS.includes(_ext(name))) && f && typeof f.slice === 'function') {
      const pre = _el('pre', 'hand-preview-text', '…');
      pre.tabIndex = 0;   // a long file scrolls from the keyboard too
      body.appendChild(pre);
      const cut = (Number(f.size) || 0) > TEXT_PREVIEW_BYTES;
      Promise.resolve()
        .then(() => f.slice(0, TEXT_PREVIEW_BYTES).text())
        .then((text) => { pre.textContent = cut ? `${text}\n…` : text; })
        .catch(() => { pre.textContent = 'This file could not be read.'; });
      if (cut) body.appendChild(_el('div', 'hand-preview-meta', 'The first 64 KB.'));
    }
  }
  overlay.appendChild(body);

  const opener = document.activeElement;
  let done = false;
  let release = () => {};
  const entry = { el: overlay, close: () => {} };
  entry.close = () => {
    if (done) return;
    done = true;
    release();
    overlay.remove();
    if (_preview === entry) _preview = null;
    if (opener && opener.isConnected !== false && typeof opener.focus === 'function') {
      try { opener.focus(); } catch (_) { /* gone with a redraw */ }
    }
  };
  overlay.addEventListener('click', (e) => {
    // A picture closes on any click, like the chat's lightbox; a document's
    // panel is for reading and selecting, so only the backdrop closes it.
    if (e.target === overlay || (e.target === body && body.tagName === 'IMG')) entry.close();
  });
  shut.addEventListener('click', (e) => { if (e && e.stopPropagation) e.stopPropagation(); entry.close(); });
  overlay.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    // `aria-modal`: the Tab stays in the preview.
    const stops = [shut].concat(Array.prototype.slice.call(overlay.querySelectorAll('audio, pre')));
    const at = stops.indexOf(document.activeElement);
    e.preventDefault();
    const next = stops[(at + (e.shiftKey ? stops.length - 1 : 1)) % stops.length] || shut;
    next.focus();
  });
  document.body.appendChild(overlay);
  overlay.style.zIndex = String(topPortalZ());
  release = registerMenuDismiss(entry.close);
  _preview = entry;
  try { shut.focus(); } catch (_) { /* no focus in a test shim */ }
  return overlay;
}

/** Test hook: what is selected and open, read without the DOM. */
export function handState() {
  return {
    selected: _selected ? _files().indexOf(_selected) : -1,
    expanded: _expanded,
    menu: _menu ? _files().indexOf(_menu.file) : -1,
    preview: !!_preview,
  };
}

export default {
  FAN_MAX, LONG_PRESS_MS, drawHand, openMenu, openPreview, closePreview,
  actionsFor, saveToGallery, isImageFile, displayName, glyphFor, handState,
};
