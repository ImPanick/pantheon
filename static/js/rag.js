// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/rag.js

/**
 * RAG (Retrieval Augmented Generation) management
 */

import uiModule from './ui.js';
import spinnerModule from './spinner.js';
// C-ERR: a refused response is read once, by the one reader (`Law 14`).
import { readRefusal } from './workbench/refusal.js';

let API_BASE = '';

export function init(apiBase) {
  API_BASE = apiBase;
  _setupUploadZone();
  _setupPanelRefresh();
}

function _humanSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

/**
 * Load and display RAG documents with delete buttons
 */
export async function loadPersonalDocs() {
  const box = document.getElementById('docs-view');
  if (!box) return;

  box.innerHTML = '';
  const { element: wpEl } = spinnerModule.createWhirlpool(24);
  wpEl.title = 'Loading…';
  box.appendChild(wpEl);

  try {
    const res = await fetch(`${API_BASE}/api/personal`, { credentials: 'same-origin' });
    // `B-NEW-8` (P23 round 2). Every `/api/personal` route is `require_admin`.
    // A non-admin's RAG tab offered *Drop files here or click to upload* above
    // the refusal, and the refusal was thrown and then `console.error`ed
    // (`Error: Admin only at loadPersonalDocs`, measured on `a936b5c` as
    // `guest`). A refusal is an answer, not a fault: its sentence stands where
    // the files would be, nothing offers an upload it would refuse, nothing is
    // logged — the way `memory.js` draws a refused Brain (`SET-U-15`).
    if (res.status === 403) {
      const { sentence } = await readRefusal(res, 'Only an admin manages these files.');
      _offerUpload(false);
      _showHealth(null);
      box.innerHTML = '';
      const said = document.createElement('div');
      said.className = 'rag-refused';
      said.textContent = sentence;
      said.style.cssText = 'color:var(--color-muted);font-size:12px;padding:4px 0;';
      box.appendChild(said);
      return;
    }
    if (!res.ok) throw new Error((await readRefusal(res, 'Could not load the files.')).sentence);
    const data = await res.json();
    const files = data.files || [];

    box.innerHTML = '';
    _offerUpload(true);
    // `BRAIN-M-5` (P23-02). A dead index says so, with what to do; it used to
    // say "Drop files above to add to RAG" and let the upload find out.
    _showHealth(data);

    if (files.length === 0) {
      const placeholder = document.createElement('div');
      placeholder.textContent = 'No files yet.';
      placeholder.style.cssText = 'color:var(--color-muted);font-size:12px;padding:4px 0;';
      box.appendChild(placeholder);
      return;
    }

    files.forEach(f => {
      const row = document.createElement('div');
      row.className = 'list-item';
      row.style.cssText = 'display:flex;align-items:center;gap:4px;';

      const name = document.createElement('span');
      name.className = 'grow';
      name.textContent = f.name.split('/').pop();
      name.title = f.path || f.name;
      name.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      row.appendChild(name);

      const size = document.createElement('span');
      size.style.cssText = 'color:var(--color-muted);font-size:11px;flex-shrink:0;';
      size.textContent = _humanSize(f.size);
      row.appendChild(size);

      const del = document.createElement('button');
      del.className = 'rag-file-delete';
      del.textContent = 'x';
      del.title = 'Remove from RAG';
      del.style.cssText = 'background:none;border:none;color:var(--color-error);cursor:pointer;padding:2px 4px;font-size:12px;flex-shrink:0;';
      del.addEventListener('click', (e) => {
        e.stopPropagation();
        _deleteFile(f.path || f.name, f.name.split('/').pop());
      });
      row.appendChild(del);

      box.appendChild(row);
    });
  } catch (e) {
    console.error(e);
    box.innerHTML = '';
    const error = document.createElement('div');
    error.textContent = (e && e.message) || 'Could not load the files.';
    error.style.color = 'var(--color-error)';
    box.appendChild(error);
  }
}

async function _deleteFile(filepath, displayName) {
  if (!await uiModule.styledConfirm(`Remove "${displayName}" from RAG?`, { confirmText: 'Remove', danger: true })) return;
  try {
    const res = await fetch(`${API_BASE}/api/personal/file?filepath=${encodeURIComponent(filepath)}`, {
      method: 'DELETE',
      credentials: 'same-origin'
    });
    if (!res.ok) throw new Error((await readRefusal(res, `Could not remove ${displayName}.`)).sentence);
    await loadPersonalDocs();
  } catch (e) {
    // `BRAIN-M-4` (P23-02): the app's own error toast with the server's
    // sentence — never a native alert dialog of the raw response body.
    console.error('Delete failed:', e);
    uiModule.showError((e && e.message) || `Could not remove ${displayName}.`);
  }
}

/**
 * Upload files to RAG
 */
export async function uploadRagFiles(fileList) {
  if (!fileList || !fileList.length) return;

  const zone = document.getElementById('rag-upload-zone');
  if (zone) zone.textContent = 'Uploading…';

  const fd = new FormData();
  for (const file of fileList) {
    fd.append('files', file);
  }

  try {
    const res = await fetch(`${API_BASE}/api/personal/upload`, {
      method: 'POST',
      credentials: 'same-origin',
      body: fd
    });

    if (!res.ok) throw new Error((await readRefusal(res, 'The upload failed.')).sentence);

    const data = await res.json();
    if (zone) zone.textContent = 'Drop files here or click to upload';
    await loadPersonalDocs();
    return data;
  } catch (e) {
    console.error('Upload failed:', e);
    if (zone) zone.textContent = 'Drop files here or click to upload';
    // `BRAIN-M-4` (P23-02). Was a native alert dialog reading `Upload failed:
    // {"detail":"RAG system is not available — is the embedding service
    // running?"}` — raw JSON, naming a cause the server knew was wrong
    // (measured on `32df791`).
    uiModule.showError((e && e.message) || 'The upload failed.');
  }
}

/** `B-NEW-8`. The drop zone is offered only to someone the list answered. Its
 *  markup carries an inline `display:block`, which a `hidden` attribute does
 *  not beat. */
function _offerUpload(on) {
  const zone = document.getElementById('rag-upload-zone');
  if (zone) zone.style.display = on ? 'block' : 'none';
}

/** The one line under the RAG heading saying the index is down, and why. */
function _showHealth(data) {
  const line = document.getElementById('rag-health');
  if (!line) return;
  const down = data && data.healthy === false;
  line.hidden = !down;
  line.textContent = down ? String(data.reason || 'RAG is off.') : '';
}

function _setupUploadZone() {
  const zone = document.getElementById('rag-upload-zone');
  const input = document.getElementById('rag-file-input');
  if (!zone || !input) return;

  zone.addEventListener('click', () => input.click());

  zone.addEventListener('dragover', (e) => {
    e.preventDefault();
    zone.classList.add('dragover');
  });

  zone.addEventListener('dragleave', () => {
    zone.classList.remove('dragover');
  });

  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      uploadRagFiles(e.dataTransfer.files);
    }
  });

  input.addEventListener('change', () => {
    if (input.files.length) {
      uploadRagFiles(input.files);
      input.value = '';
    }
  });
}

/**
 * Refresh the file list whenever the panel holding `#docs-view` is shown.
 *
 * `loadPersonalDocs()` runs once from `app.js`'s non-critical startup queue
 * (~9s after boot) and after this module's own uploads and deletes. Without
 * this, a file added by `/rag`, by the agent's document tools, or from the
 * admin panel would not appear until the page was reloaded — the panel would
 * show a snapshot taken nine seconds after boot for the rest of the session.
 *
 * Keyed off the panel's own `hidden` class rather than a specific tab button,
 * so it keeps working wherever the markup lands and quietly does nothing if
 * `#docs-view` is not inside a tab panel at all.
 */
function _setupPanelRefresh() {
  const box = document.getElementById('docs-view');
  if (!box || typeof MutationObserver !== 'function') return;
  const panel = box.closest('.memory-tab-panel[data-memory-panel]');
  if (!panel) return;

  new MutationObserver(() => {
    if (!panel.classList.contains('hidden')) loadPersonalDocs();
  }).observe(panel, { attributes: true, attributeFilter: ['class'] });
}

const ragModule = {
  init,
  loadPersonalDocs,
  uploadRagFiles
};

export default ragModule;
