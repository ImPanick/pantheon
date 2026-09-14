// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/fileHandler.js

/**
 * File attachment and upload handling
 */

import uiModule from './ui.js';
import spinnerModule from './spinner.js';

let pendingFiles = [];
let uploaded = [];
// Holds the full meta (id/name/mime/size/width/height/…) from the most recent
// uploadPending() so callers can stamp width/height onto their attachment
// objects without changing uploadPending()'s return signature.
let _lastUploadedMeta = [];
// `B03`. The `rejected` half of the most recent `/api/upload` response, and a
// per-input-file outcome in the order the files were submitted. `_lastUploadedMeta`
// (and the ids uploadPending returns) are COMPACTED — the server skips rejected
// files — so nothing downstream could recover which attachment got which id
// without this.
let _lastUploadRejected = [];
let _lastUploadOutcome = [];
let API_BASE = '';
let _uploadSpinners = [];
let _uploadAbortCtrl = null;
let _uploading = false;
let _lastUploadCancelled = false;
const _previewUrls = new WeakMap();

const MAX_FILES = 10;
const MAX_VISIBLE = 3;
let _expanded = false;

function _isMobileViewport() {
  return window.matchMedia && window.matchMedia('(max-width: 768px)').matches;
}

// The name a pending file is sent under, and the only name the server echoes
// back verbatim: `rejected[].name` is the raw form filename, while `files[].name`
// is `secure_filename()`'d (spaces → `_`, non-ASCII stripped), so matching an
// upload result against a pending file by the ACCEPTED name is wrong for any
// filename a human typed. Derived once here because the FormData append and
// every name-keyed pairing have to agree on it — they did not: the append used
// `'paste.png'` for a nameless blob and getPendingInfo() used `'pasted-image'`.
function _wireName(f) {
  return (f && f.name) || 'paste.png';
}

function _isCroppableImage(f) {
  const mime = (f?.type || '').toLowerCase();
  const name = (f?.name || '').toLowerCase();
  if (!(mime.startsWith('image/') || /\.(png|jpe?g|webp|bmp)$/i.test(name))) return false;
  return !mime.includes('svg') && !mime.includes('gif') && !/\.svg|\.gif$/i.test(name);
}

function _loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = url;
  });
}

function _canvasToBlob(canvas, type, quality) {
  return new Promise((resolve) => canvas.toBlob(resolve, type || 'image/png', quality));
}

async function _openMobileCropper(file) {
  const url = _getPreviewUrl(file);
  const imgProbe = await _loadImage(url);
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'attach-crop-overlay';
    overlay.innerHTML = `
      <div class="attach-crop-panel" role="dialog" aria-modal="true" aria-label="Crop image">
        <div class="attach-crop-stage">
          <img class="attach-crop-img" alt="">
          <div class="attach-crop-box"><span class="attach-crop-handle"></span></div>
        </div>
        <div class="attach-crop-actions">
          <button type="button" class="attach-crop-btn" data-action="cancel">Cancel</button>
          <button type="button" class="attach-crop-btn" data-action="original">Original</button>
          <button type="button" class="attach-crop-btn attach-crop-primary" data-action="crop">Use crop</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const img = overlay.querySelector('.attach-crop-img');
    const box = overlay.querySelector('.attach-crop-box');
    img.src = url;
    img.alt = file.name || 'image';

    let crop = { x: 0.08, y: 0.08, w: 0.84, h: 0.84 };
    let drag = null;

    function applyCrop() {
      const r = img.getBoundingClientRect();
      const pr = overlay.querySelector('.attach-crop-stage').getBoundingClientRect();
      box.style.left = (r.left - pr.left + crop.x * r.width) + 'px';
      box.style.top = (r.top - pr.top + crop.y * r.height) + 'px';
      box.style.width = (crop.w * r.width) + 'px';
      box.style.height = (crop.h * r.height) + 'px';
    }
    function clampCrop() {
      crop.w = Math.max(0.12, Math.min(1, crop.w));
      crop.h = Math.max(0.12, Math.min(1, crop.h));
      crop.x = Math.max(0, Math.min(1 - crop.w, crop.x));
      crop.y = Math.max(0, Math.min(1 - crop.h, crop.y));
    }
    function finish(value) {
      overlay.remove();
      window.removeEventListener('resize', applyCrop);
      resolve(value);
    }
    requestAnimationFrame(applyCrop);
    img.addEventListener('load', applyCrop);
    window.addEventListener('resize', applyCrop);

    box.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      box.setPointerCapture(e.pointerId);
      drag = {
        mode: e.target.classList.contains('attach-crop-handle') ? 'resize' : 'move',
        sx: e.clientX,
        sy: e.clientY,
        start: { ...crop },
      };
    });
    box.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const r = img.getBoundingClientRect();
      const dx = (e.clientX - drag.sx) / Math.max(1, r.width);
      const dy = (e.clientY - drag.sy) / Math.max(1, r.height);
      if (drag.mode === 'resize') {
        crop.w = drag.start.w + dx;
        crop.h = drag.start.h + dy;
      } else {
        crop.x = drag.start.x + dx;
        crop.y = drag.start.y + dy;
      }
      clampCrop();
      applyCrop();
    });
    box.addEventListener('pointerup', () => { drag = null; });
    box.addEventListener('pointercancel', () => { drag = null; });

    overlay.querySelector('[data-action="cancel"]').addEventListener('click', () => finish(null));
    overlay.querySelector('[data-action="original"]').addEventListener('click', () => finish(file));
    overlay.querySelector('[data-action="crop"]').addEventListener('click', async () => {
      clampCrop();
      const canvas = document.createElement('canvas');
      const sx = Math.round(crop.x * imgProbe.naturalWidth);
      const sy = Math.round(crop.y * imgProbe.naturalHeight);
      const sw = Math.max(1, Math.round(crop.w * imgProbe.naturalWidth));
      const sh = Math.max(1, Math.round(crop.h * imgProbe.naturalHeight));
      canvas.width = sw;
      canvas.height = sh;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(imgProbe, sx, sy, sw, sh, 0, 0, sw, sh);
      const type = file.type && file.type !== 'image/bmp' ? file.type : 'image/png';
      const blob = await _canvasToBlob(canvas, type, 0.92);
      if (!blob) { finish(file); return; }
      const ext = type.includes('jpeg') ? 'jpg' : (type.split('/')[1] || 'png');
      const base = (file.name || 'image').replace(/\.[^.]+$/, '');
      finish(new File([blob], `${base}-cropped.${ext}`, { type, lastModified: Date.now() }));
    });
  });
}

function _getPreviewUrl(f) {
  if (!f) return '';
  let url = _previewUrls.get(f);
  if (!url) {
    url = URL.createObjectURL(f);
    _previewUrls.set(f, url);
  }
  return url;
}

function _revokePreviewUrl(f) {
  const url = _previewUrls.get(f);
  if (url) {
    try { URL.revokeObjectURL(url); } catch (_) {}
    _previewUrls.delete(f);
  }
}

/**
 * Initialize with dependencies
 */
export function init(apiBase) {
  API_BASE = apiBase;
}

/**
 * Open file picker dialog
 */
export function openPicker() {
  document.getElementById('file-input').click();
}

/**
 * Render the attachment strip with pending files.
 * 1-3 files: show individual chips.
 * 4+  files: collapse into a single "N files" badge (click to expand).
 */
export function renderAttachStrip() {
  const strip = document.getElementById('attach-strip');

  while (strip.firstChild) strip.removeChild(strip.firstChild);
  if (pendingFiles.length === 0) {
    _expanded = false;
    if (window._updateSendBtnIcon) window._updateSendBtnIcon();
    return;
  }

  const total = pendingFiles.length;
  const collapsed = total > MAX_VISIBLE && !_expanded;

  if (collapsed) {
    // Single compact badge: "5 files ×"
    const badge = document.createElement('div');
    badge.className = 'thumb thumb-collapsed';
    const label = document.createElement('span');
    label.textContent = total + ' file' + (total > 1 ? 's' : '');
    label.className = 'thumb-collapsed-label';
    badge.appendChild(label);
    badge.title = pendingFiles.map(f => f.name || 'pasted-image').join('\n');
    badge.style.cursor = 'pointer';
    badge.addEventListener('click', (e) => {
      if (e.target.closest('.thumb-collapsed-x')) return;
      _expanded = true;
      renderAttachStrip();
    });
    const x = document.createElement('button');
    x.className = 'thumb-collapsed-x';
    x.textContent = '\u00d7';
    x.title = 'Remove all';
    x.addEventListener('click', (e) => { e.stopPropagation(); clearPending(); });
    badge.appendChild(x);
    strip.appendChild(badge);
  } else {
    // Show individual chips
    for (let idx = 0; idx < total; idx++) {
      strip.appendChild(_createChip(pendingFiles[idx], idx));
    }
  }
  if (window._updateSendBtnIcon) window._updateSendBtnIcon();
}

function _createChip(f, idx) {
  const chip = document.createElement('div');
  chip.className = 'thumb';
  const isImage = f.type?.startsWith('image/') || /\.(png|jpg|jpeg|gif|webp|svg|bmp)$/i.test(f.name || '');
  if (isImage) {
    chip.classList.add('thumb-image');  // lets CSS overlay the remove-X on the corner (mobile)
    const img = document.createElement('img');
    img.className = 'thumb-img';
    img.src = _getPreviewUrl(f);
    img.alt = f.name || 'image';
    chip.appendChild(img);
  } else {
    const span = document.createElement('span');
    span.textContent = f.name || 'pasted-image';
    chip.appendChild(span);
  }
  const x = document.createElement('button');
  x.textContent = '\u00d7';
  x.setAttribute('aria-label', 'Remove attachment');
  x.addEventListener('click', (e) => { e.stopPropagation(); removePending(idx); });
  chip.appendChild(x);
  return chip;
}

/**
 * Remove a pending file by index
 */
export function removePending(idx) {
  if (_uploading) cancelUpload();
  _revokePreviewUrl(pendingFiles[idx]);
  pendingFiles.splice(idx, 1);
  renderAttachStrip();
}

/**
 * Upload all pending files to server
 */
export async function uploadPending(opts = {}) {
  if (pendingFiles.length === 0) return [];
  _lastUploadCancelled = false;
  // Stale results from the previous batch must not be readable as if they
  // described this one — every early return below leaves them empty.
  _lastUploadRejected = [];
  _lastUploadOutcome = [];

  // The message bubble is shown immediately, but the upload can take a moment —
  // dim the chips and overlay a whirlpool so it's clear the files are still
  // being sent (and aren't stuck). Cleared in the finally below.
  const strip = document.getElementById('attach-strip');
  if (strip) {
    strip.classList.add('attach-uploading');
    // Put a whirlpool ON each attachment chip (image/doc) so the spinner sits on
    // the thing being uploaded, not floating over the whole strip.
    strip.querySelectorAll('.thumb').forEach(chip => {
      try {
        const sp = spinnerModule.create('', 'clean', 'whirlpool');
        const ov = document.createElement('span');
        ov.className = 'thumb-upload-spinner';
        ov.appendChild(sp.createElement());
        chip.appendChild(ov);
        sp.start();
        _uploadSpinners.push(sp);
      } catch (_) { /* spinner is best-effort */ }
    });
  }

  const fd = new FormData();
  const submitted = pendingFiles.slice();   // input order, frozen for the pairing below
  submitted.forEach(f => fd.append('files', f, _wireName(f)));
  if (opts.sessionId) fd.append('session_id', opts.sessionId);
  _uploadAbortCtrl = new AbortController();
  _uploading = true;
  const timeoutId = setTimeout(() => {
    if (_uploadAbortCtrl && !_uploadAbortCtrl.signal.aborted) {
      try { _uploadAbortCtrl.abort(); } catch (_) {}
    }
  }, 120000);

  try {
    const res = await fetch(`${API_BASE}/api/upload`, {
      method: 'POST',
      body: fd,
      signal: _uploadAbortCtrl.signal,
    });
    if (!res.ok) {
      // Surface the failure instead of swallowing it. Previously a non-OK
      // response (e.g. 429 rate limit, 413 too large) was ignored: the files
      // silently vanished and the chat sent with no attachments, so the model
      // "didn't even see them" (issue #1346). Show the server's reason and keep
      // pendingFiles so the strip re-renders for a retry (see finally below).
      let detail = '';
      try { const e = await res.json(); detail = e.detail || e.error || ''; } catch (_) {}
      _showToast('Upload failed' + (detail ? ': ' + detail : ` (HTTP ${res.status})`));
      return [];
    }
    const data = await res.json();
    uploaded = (data.files || []);
    // `B03`. A partial batch answers 200 with both halves. This read only
    // `files` — the refused half was parsed and thrown away.
    const rejected = Array.isArray(data.rejected) ? data.rejected : [];
    if (uploaded.some(x => x && x.gallery_id)) {
      try { localStorage.setItem('gallery-fresh-chat-upload', String(Date.now())); } catch (_) {}
      window.dispatchEvent(new CustomEvent('gallery-refresh', { detail: { source: 'chat-upload' } }));
    }

    // Rebuild which submitted file got which id. `files` preserves input order
    // but SKIPS the rejected ones, so for [f0, f1✗, f2, f3✗, f4] it is three
    // entries long and index i in it is not file i. `rejected[].name` is the
    // raw form filename — the one this module chose in `_wireName` — so the
    // compaction is recoverable here and nowhere else. Counted, not just
    // tested for membership, so two attachments sharing a name consume one
    // rejection each instead of both being called rejected.
    const remaining = new Map();
    for (const r of rejected) {
      const k = (r && r.name) || 'paste.png';
      remaining.set(k, (remaining.get(k) || 0) + 1);
    }
    let taken = 0;
    const outcome = submitted.map((f) => {
      const name = _wireName(f);
      const left = remaining.get(name) || 0;
      if (left > 0) {
        remaining.set(name, left - 1);
        return { name, accepted: false, id: null, meta: null, file: f };
      }
      const meta = uploaded[taken++] || null;
      return { name, accepted: true, id: meta ? meta.id : null, meta, file: f };
    });
    // The pairing is only worth publishing if it consumed exactly the files
    // the server said it kept. If it did not (a server that renamed them, a
    // response shape that moved), say nothing rather than attribute a
    // thumbnail from a pairing we cannot trust — callers fall back to their
    // previous positional behaviour, which is no worse than before.
    const reconciled = taken === uploaded.length;

    // "clear only on success" was the rule, and a 200 carrying `rejected` is
    // not a success. Clearing the whole list on any 2xx is what made a refused
    // file vanish from the composer with nothing to click and nothing to read:
    // it could not be retried because it was no longer there. Keep exactly the
    // refused Files pending — the `finally` below re-renders the strip with
    // them — and drop the ones that landed so a retry does not re-upload what
    // the server already has.
    //
    // Their preview blob URLs are deliberately not revoked: the optimistic
    // message bubble chat.js rendered a moment ago is still displaying them,
    // and the pre-existing clear did not revoke either.
    pendingFiles = reconciled ? outcome.filter(o => !o.accepted).map(o => o.file) : [];
    _lastUploadOutcome = reconciled ? outcome : [];
    _lastUploadRejected = rejected;
    // Stash the full meta (incl. width/height for images) on the module so
    // callers that want it can grab it via getLastUploadedMeta(). Keep the
    // returned shape as `ids` for backward-compatibility with existing call sites.
    _lastUploadedMeta = uploaded;
    if (rejected.length) {
      uiModule.showUploadRejections(rejected, {
        suffix: pendingFiles.length ? 'Kept in the composer so you can retry.' : '',
      });
    }
    return uploaded.map(x => x.id);
  } catch (e) {
    if (e && e.name === 'AbortError') {
      _lastUploadCancelled = true;
      _showToast('Upload cancelled');
      return [];
    }
    _showToast('Upload failed: ' + (e?.message || 'network error'));
    return [];
  } finally {
    clearTimeout(timeoutId);
    _uploading = false;
    _uploadAbortCtrl = null;
    _uploadSpinners.forEach(sp => { try { sp.stop && sp.stop(); } catch (_) {} });
    _uploadSpinners = [];
    if (strip) strip.classList.remove('attach-uploading');
    // Re-render: empty on success (chips gone), or restored on error so the
    // user can retry — and either way the spinners are removed.
    renderAttachStrip();
  }
}

/**
 * Add files to pending list (capped at MAX_FILES)
 */
export async function addFiles(files, opts = {}) {
  for (const f of files) {
    if (pendingFiles.length >= MAX_FILES) {
      _showToast(`Max ${MAX_FILES} files allowed`);
      break;
    }
    let nextFile = f;
    if (!opts.skipCrop && _isMobileViewport() && _isCroppableImage(f)) {
      try {
        nextFile = await _openMobileCropper(f);
      } catch (_) {
        nextFile = f;
      }
      if (!nextFile) continue;
    }
    pendingFiles.push(nextFile);
  }
  renderAttachStrip();
}

export async function cropForMobileUpload(file) {
  if (!_isMobileViewport() || !_isCroppableImage(file)) return file;
  try {
    return await _openMobileCropper(file);
  } catch (_) {
    return file;
  }
}

// `B03` / `Law 14`. This used to read `window.showToast` and, when it was
// absent, build and style its own `#_attach-toast` div. `window.showToast` is
// ASSIGNED NOWHERE in the tree — three files read it, zero write it — so the
// branch was never taken and the private div was the only path this function
// has ever run. That made a second toast implementation, with its own markup,
// its own 2.5s timer and no dismiss control, live permanently beside ui.js's.
//
// Delegate to the one toast. `showError` and not `showToast` for all four
// call sites because the private div was red-on-panel unconditionally — every
// message that reached it, "Upload cancelled" included, already looked like an
// error, so routing them all to the error toast is what keeps the appearance
// the user has today (Law 1) rather than a judgement about severity.
function _showToast(msg) {
  uiModule.showError(msg);
}

/**
 * Get pending files count
 */
export function getPendingCount() {
  return pendingFiles.length;
}

/**
 * Get raw pending File objects (for reading content before upload clears them)
 */
export function getPendingRaw() {
  return [...pendingFiles];
}

/**
 * Get pending file metadata (name, size, type) for display
 */
export function getPendingInfo() {
  return pendingFiles.map(f => {
    const isImage = f.type?.startsWith('image/') || /\.(png|jpg|jpeg|gif|webp|svg|bmp)$/i.test(f.name || '');
    return {
      name: f.name || 'pasted-image',
      // The name this file is POSTed under, which is what an upload result
      // can be matched against. Kept separate from `name` because `name` is
      // what the composer and the message bubble display, and 'paste.png' is
      // a worse label than 'pasted-image' (`B03`).
      uploadName: _wireName(f),
      size: f.size || 0,
      mime: f.type || '',
      previewUrl: isImage ? _getPreviewUrl(f) : '',
    };
  });
}

/**
 * Clear all pending files
 */
export function clearPending() {
  if (_uploading) cancelUpload();
  pendingFiles.forEach(_revokePreviewUrl);
  pendingFiles = [];
  renderAttachStrip();
}

/** Full meta (incl. width/height for images) from the most recent uploadPending(). */
export function getLastUploadedMeta() {
  return _lastUploadedMeta;
}

/**
 * The `rejected` half of the most recent `/api/upload` response — `[{name,
 * status, error}]`, empty when the batch was clean or the request never got a
 * body. `B03`.
 */
export function getLastUploadRejections() {
  return _lastUploadRejected.slice();
}

/**
 * Per-submitted-file outcome of the most recent `uploadPending()`, in the
 * order the files were POSTed: `{name, accepted, id, meta, file}`.
 *
 * Empty when there is nothing trustworthy to say (a failed request, a
 * cancellation, or a `rejected` list that did not reconcile against `files`),
 * so an empty array means "fall back", never "everything was rejected".
 * Callers pairing their own per-file state against the upload need this: the
 * ids `uploadPending()` returns are compacted and cannot be indexed by the
 * position of the file the user attached. `B03`.
 */
export function getLastUploadOutcome() {
  return _lastUploadOutcome.map(o => ({ ...o }));
}

export function isUploading() {
  return _uploading;
}

export function wasLastUploadCancelled() {
  return _lastUploadCancelled;
}

export function cancelUpload() {
  _lastUploadCancelled = true;
  if (_uploadAbortCtrl && !_uploadAbortCtrl.signal.aborted) {
    try { _uploadAbortCtrl.abort(); } catch (_) {}
  }
}

var escapeHtml = uiModule.esc;

const fileHandlerModule = {
  init,
  openPicker,
  renderAttachStrip,
  removePending,
  uploadPending,
  addFiles,
  cropForMobileUpload,
  getPendingCount,
  getPendingInfo,
  getPendingRaw,
  clearPending,
  getLastUploadedMeta,
  getLastUploadRejections,
  getLastUploadOutcome,
  isUploading,
  wasLastUploadCancelled,
  cancelUpload,
};

export default fileHandlerModule;
