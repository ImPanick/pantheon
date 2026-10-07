// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/documentFolders.js
/**
 * `P21-01` — folders in the Library's Documents tab.
 *
 * The owner, 2026-10-01: *"I'd like to be able to make folders to sort through
 * documents, and keep things tidy and organized."*
 *
 * **Where it sits, and why there (`Law 14`).** The row said "the library's
 * sidebar", and the Library has none: it is a 600px modal of four tabs, each a
 * toolbar, a chip row and a list. The Chats tab already files chats into
 * folders and shows them as a row of `.memory-cat-chip`s
 * (`_renderChatsChips` in `documentLibrary.js`), so documents get that row,
 * extended the one way chats never needed: a path above it — *All documents ›
 * Clients › Acme* — because document folders nest. The list stays where every
 * expand-state rule in `style.css` expects it (`.admin-card > .doclib-grid`), so
 * opening a card inside a folder works exactly as it does outside one.
 *
 * Everything a person can do with the mouse they can do from the keyboard and on
 * a phone: every crumb, chip and menu row is a `<button>`, the menus go through
 * `bindMenuDismiss` (`P10-06` — first item focused, arrows walk), and a drag has
 * a *Move to…* twin on every document and on the bulk bar.
 *
 * Nothing here decides anything about a folder. Paths are normalised, counted,
 * merged and refused by `src/document_folders.py`, which the agent's
 * `manage_documents` calls too; this module draws what the server answers and
 * sends what the person chose. Every name is user text, so every name reaches
 * the DOM through `textContent`.
 */

import uiModule from './ui.js';
import { bindMenuDismiss, dismissOrRemove } from './escMenuStack.js';
import { topPortalZ } from './toolWindowZOrder.js';

export const DOC_DRAG_TYPE = 'application/x-pantheon-documents';
export const FOLDER_DRAG_TYPE = 'application/x-pantheon-folder';
export const UNFILED = 'Unfiled';
export const ALL_DOCUMENTS = 'All documents';
const SEP = '/';

const FOLDER_ICON = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>';

// ── paths (display only — the server owns the spelling) ─────────────────────

export function folderName(path) {
  const s = String(path || '');
  const i = s.lastIndexOf(SEP);
  return i < 0 ? s : s.slice(i + 1);
}

export function parentOf(path) {
  const s = String(path || '');
  const i = s.lastIndexOf(SEP);
  return i < 0 ? null : s.slice(0, i);
}

export function joinPath(parent, name) {
  return parent ? `${parent}${SEP}${name}` : String(name || '');
}

export function isWithin(path, root) {
  return !!path && !!root && (path === root || path.startsWith(root + SEP));
}

/** Where a document lives, as a person reads it. */
export function whereLabel(path) {
  return path || UNFILED;
}

function _plural(n, word) {
  return `${n} ${word}${n === 1 ? '' : 's'}`;
}

function _howMany(n) {
  if (n === 1) return 'it';
  if (n === 2) return 'both';
  return `all ${n}`;
}

// ── the view a person is looking at ──────────────────────────────────────────
//
// `{kind: 'all'}` · `{kind: 'unfiled'}` · `{kind: 'folder', path}`. An enum, not
// a nullable path: "no folder chosen" and "the documents in no folder" are two
// different screens, and a `null` would have to mean one of them (`Law 10`).

export const VIEW_ALL = Object.freeze({ kind: 'all' });
export const VIEW_UNFILED = Object.freeze({ kind: 'unfiled' });
export function folderView(path) {
  return path ? { kind: 'folder', path } : VIEW_ALL;
}

/** Add this view's filter to the library's query. */
export function applyViewParams(view, params) {
  if (view && view.kind === 'folder' && view.path) params.set('folder', view.path);
  else if (view && view.kind === 'unfiled') params.set('unfiled', 'true');
  return params;
}

/**
 * `B997`. The folder a file imported from this view is filed into: the open
 * folder, or none — from All documents or Unfiled an import lands in Unfiled,
 * which is where it already lands.
 */
export function importFolder(view) {
  return view && view.kind === 'folder' && view.path ? view.path : null;
}

/** The view to show after `path` was moved/renamed to `to` (or removed, `to` null). */
export function viewAfterRelocate(view, path, to) {
  if (!view || view.kind !== 'folder' || !isWithin(view.path, path)) return view;
  if (to === undefined || to === null) {
    const up = parentOf(path);
    return up ? folderView(up) : VIEW_ALL;
  }
  return folderView(to + view.path.slice(path.length));
}

// ── the server ───────────────────────────────────────────────────────────────

async function _answer(res) {
  let body = null;
  try { body = await res.json(); } catch (_) { body = null; }
  if (!res.ok) {
    const detail = body && (body.detail || body.error || body.message);
    throw new Error(typeof detail === 'string' && detail ? detail : `${res.status} ${res.statusText || ''}`.trim());
  }
  return body || {};
}

export function folderApi(apiBase) {
  const base = apiBase || '';
  const post = (path, body) => fetch(base + path, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(_answer);
  return {
    list: (archived) => fetch(`${base}/api/document-folders${archived ? '?archived=true' : ''}`,
      { credentials: 'same-origin' }).then(_answer),
    create: (folder) => post('/api/document-folders', { folder }),
    rename: (folder, name) => post('/api/document-folders/rename', { folder, name }),
    move: (folder, to) => post('/api/document-folders/move', { folder, to: to || null }),
    remove: (folder, contents, dryRun) => post('/api/document-folders/remove',
      { folder, contents: contents || null, dry_run: !!dryRun }),
    file: (ids, to) => post('/api/document-folders/file', { document_ids: ids, to: to || null }),
  };
}

// ── drag and drop ────────────────────────────────────────────────────────────

export function startDocumentDrag(event, ids) {
  const dt = event && event.dataTransfer;
  if (!dt) return;
  dt.setData(DOC_DRAG_TYPE, JSON.stringify(ids));
  dt.setData('text/plain', _plural(ids.length, 'document'));
  dt.effectAllowed = 'move';
}

export function startFolderDrag(event, path) {
  const dt = event && event.dataTransfer;
  if (!dt) return;
  dt.setData(FOLDER_DRAG_TYPE, path);
  dt.setData('text/plain', path);
  dt.effectAllowed = 'move';
}

function _carries(event) {
  const types = (event && event.dataTransfer && event.dataTransfer.types) || [];
  const has = (t) => (typeof types.includes === 'function' ? types.includes(t) : Array.prototype.indexOf.call(types, t) >= 0);
  return has(DOC_DRAG_TYPE) || has(FOLDER_DRAG_TYPE);
}

/** What a drop carries: `{kind:'documents', ids}`, `{kind:'folder', path}` or null. */
export function readDrop(event) {
  const dt = event && event.dataTransfer;
  if (!dt) return null;
  const docs = dt.getData(DOC_DRAG_TYPE);
  if (docs) {
    try {
      const ids = JSON.parse(docs);
      if (Array.isArray(ids) && ids.length) return { kind: 'documents', ids: ids.map(String) };
    } catch (_) { return null; }
  }
  const folder = dt.getData(FOLDER_DRAG_TYPE);
  return folder ? { kind: 'folder', path: folder } : null;
}

/** Make `el` accept documents and folders dropped on it, filing them into `target` (null = the top). */
export function makeDropTarget(el, target, handlers) {
  el.addEventListener('dragover', (e) => {
    if (!_carries(e)) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
    el.classList.add('doclib-folder-drop');
  });
  el.addEventListener('dragleave', () => el.classList.remove('doclib-folder-drop'));
  el.addEventListener('drop', (e) => {
    el.classList.remove('doclib-folder-drop');
    const got = readDrop(e);
    if (!got) return;
    e.preventDefault();
    if (got.kind === 'documents' && handlers.dropDocuments) handlers.dropDocuments(got.ids, target);
    else if (got.kind === 'folder' && handlers.dropFolder && got.path !== target) handlers.dropFolder(got.path, target);
  });
}

// ── the bar: a path, then the folders at this level ──────────────────────────

/**
 * Draw the folder bar into `host`.
 *
 * @param {object} model  `{folders, unfiled, all, view}` — `folders` is the
 *                        server's list (`path, name, parent, depth, count, total`).
 * @param {object} on     `{open(view), newFolder(parent), folderMenu(anchor, path),
 *                        dropDocuments(ids, to), dropFolder(path, to)}`.
 */
export function renderFolderBar(host, model, on) {
  if (!host) return null;
  const folders = Array.isArray(model && model.folders) ? model.folders : [];
  const view = (model && model.view) || VIEW_ALL;
  const handlers = on || {};
  const here = view.kind === 'folder' ? view.path : null;

  const path = document.createElement('nav');
  path.className = 'doclib-folder-path';
  path.setAttribute('aria-label', 'Folder');
  const crumb = (label, target, current) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'doclib-folder-crumb';
    b.textContent = label;
    if (current) b.setAttribute('aria-current', 'page');
    b.addEventListener('click', () => handlers.open && handlers.open(target ? folderView(target) : VIEW_ALL));
    makeDropTarget(b, target, handlers);
    if (!target) b.title = 'Drop documents here to take them out of their folder';
    path.appendChild(b);
    return b;
  };
  const sep = () => {
    const s = document.createElement('span');
    s.className = 'doclib-folder-sep';
    s.setAttribute('aria-hidden', 'true');
    s.textContent = '›';
    path.appendChild(s);
  };
  crumb(ALL_DOCUMENTS, null, view.kind === 'all');
  if (view.kind === 'unfiled') {
    sep();
    const u = document.createElement('span');
    u.className = 'doclib-folder-crumb';
    u.setAttribute('aria-current', 'page');
    u.textContent = UNFILED;
    path.appendChild(u);
  } else if (here) {
    const parts = here.split(SEP);
    parts.forEach((name, i) => {
      sep();
      crumb(name, parts.slice(0, i + 1).join(SEP), i === parts.length - 1);
    });
    const menu = document.createElement('button');
    menu.type = 'button';
    menu.className = 'memory-toolbar-btn doclib-folder-actions';
    menu.textContent = 'Folder…';
    menu.setAttribute('aria-label', `Actions for the folder ${folderName(here)}`);
    menu.setAttribute('aria-haspopup', 'menu');
    menu.addEventListener('click', (e) => {
      e.stopPropagation();
      if (handlers.folderMenu) handlers.folderMenu(menu, here);
    });
    path.appendChild(menu);
  }

  const chips = document.createElement('div');
  chips.className = 'doclib-folder-chips';
  chips.setAttribute('role', 'group');
  chips.setAttribute('aria-label', here ? `Folders in ${folderName(here)}` : 'Folders');
  const chip = (label, count, target, active) => {
    const c = document.createElement('button');
    c.type = 'button';
    c.className = 'memory-cat-chip doclib-folder-chip' + (active ? ' active' : '');
    if (active) c.setAttribute('aria-pressed', 'true');
    const icon = document.createElement('span');
    icon.className = 'doclib-folder-chip-icon';
    icon.innerHTML = FOLDER_ICON;   // a constant, never user text
    c.appendChild(icon);
    const name = document.createElement('span');
    name.className = 'doclib-folder-chip-name';
    name.textContent = label;
    c.appendChild(name);
    const n = document.createElement('span');
    n.className = 'doclib-folder-count';
    n.textContent = `(${count})`;
    c.appendChild(n);
    chips.appendChild(c);
    return c;
  };
  if (!here) {
    const u = chip(UNFILED, Number((model && model.unfiled) || 0), null, view.kind === 'unfiled');
    u.dataset.folderTarget = '';
    u.title = 'Documents that are in no folder';
    u.addEventListener('click', () => handlers.open && handlers.open(view.kind === 'unfiled' ? VIEW_ALL : VIEW_UNFILED));
    makeDropTarget(u, null, handlers);
  }
  for (const f of folders) {
    if ((f.parent || null) !== here) continue;
    // `P23-06` (DOCS-M-4). The number is what opening the folder shows — the
    // documents in it, not in its folders too: "Projects (7)" opened onto
    // "0 of 17 documents" because the seven were in Projects › Lumen 2.0,
    // whose own chip says so one click in. The title keeps the whole count.
    const c = chip(f.name, Number(f.count || 0), f.path, false);
    c.dataset.folderTarget = f.path;
    c.title = f.total === f.count
      ? `${_plural(Number(f.total || 0), 'document')} in ${f.path}`
      : `${_plural(Number(f.count || 0), 'document')} in ${f.path}, ${Number(f.total || 0)} with its folders`;
    c.draggable = true;
    c.addEventListener('dragstart', (e) => startFolderDrag(e, f.path));
    c.addEventListener('click', () => handlers.open && handlers.open(folderView(f.path)));
    makeDropTarget(c, f.path, handlers);
  }
  const add = document.createElement('button');
  add.type = 'button';
  add.className = 'memory-cat-chip doclib-folder-new';
  add.textContent = here ? '+ New folder here' : '+ New folder';
  add.addEventListener('click', () => handlers.newFolder && handlers.newFolder(here));
  chips.appendChild(add);

  host.replaceChildren(path, chips);
  return host;
}

// ── menus ────────────────────────────────────────────────────────────────────

function _menu(anchor, className, label) {
  document.querySelectorAll('._lib-dd').forEach(dismissOrRemove);
  const dd = document.createElement('div');
  dd.className = `dropdown session-dropdown-menu _lib-dd ${className}`;
  dd.setAttribute('role', 'menu');
  if (label) dd.setAttribute('aria-label', label);
  return dd;
}

function _place(dd, anchor) {
  document.body.appendChild(dd);
  const rect = anchor && anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : { right: 0, bottom: 0, top: 0 };
  dd.style.position = 'fixed';
  dd.style.right = Math.max(8, (window.innerWidth || 0) - rect.right) + 'px';
  dd.style.top = (rect.bottom + 2) + 'px';
  dd.style.display = 'block';
  dd.style.zIndex = String(topPortalZ());
  if (typeof requestAnimationFrame === 'function') {
    requestAnimationFrame(() => {
      const r = dd.getBoundingClientRect();
      if (r.bottom > (window.innerHeight || 0) - 8 && rect.top - r.height - 2 > 8) {
        dd.style.top = (rect.top - r.height - 2) + 'px';
      }
    });
  }
}

function _item(dd, label, onPick, opts) {
  const o = opts || {};
  const b = document.createElement('button');
  b.type = 'button';
  b.setAttribute('role', 'menuitem');
  b.className = 'dropdown-item-compact' + (o.danger ? ' dropdown-item-danger' : '') + (o.className ? ` ${o.className}` : '');
  b.textContent = label;
  if (o.depth) b.style.paddingLeft = `${10 + o.depth * 14}px`;
  if (o.disabled) {
    b.disabled = true;
    b.setAttribute('aria-disabled', 'true');
  }
  if (o.note) b.title = o.note;
  b.addEventListener('click', (e) => {
    e.stopPropagation();
    if (b.disabled) return;
    if (typeof dd._dismiss === 'function') dd._dismiss();
    onPick();
  });
  dd.appendChild(b);
  return b;
}

/**
 * The *Move to…* list: Unfiled (or the top level), every folder indented under
 * its parent, and *New folder…*. Where the thing already is cannot be chosen,
 * and a folder cannot be offered itself or anything inside it.
 *
 * @param {object} opts `{folders, current, moving: 'documents'|'folder', exclude,
 *                      onPick(path|null), onNew()}`
 */
export function showFolderPicker(anchor, opts) {
  const o = opts || {};
  const moving = o.moving === 'folder' ? 'folder' : 'documents';
  const dd = _menu(anchor, 'doclib-folder-picker', 'Move to');
  const head = document.createElement('div');
  head.className = 'doclib-folder-picker-head';
  head.textContent = 'Move to…';
  dd.appendChild(head);
  const current = o.current === undefined ? undefined : (o.current || null);
  const rootLabel = moving === 'folder' ? 'Top level' : UNFILED;
  _item(dd, current === null ? `${rootLabel} (here)` : rootLabel, () => o.onPick && o.onPick(null),
    { disabled: current === null, className: 'doclib-folder-pick' });
  for (const f of (Array.isArray(o.folders) ? o.folders : [])) {
    if (o.exclude && isWithin(f.path, o.exclude)) continue;
    const here = current === f.path;
    _item(dd, here ? `${f.name} (here)` : f.name, () => o.onPick && o.onPick(f.path), {
      depth: Number(f.depth || 0) + 1, disabled: here, note: f.path, className: 'doclib-folder-pick',
    });
  }
  if (typeof o.onNew === 'function') {
    _item(dd, 'New folder…', () => o.onNew(), { className: 'doclib-folder-pick-new' });
  }
  _place(dd, anchor);
  bindMenuDismiss(dd, () => dd.remove(), (ev) => !dd.contains(ev.target) && !(anchor && anchor.contains && anchor.contains(ev.target)));
  return dd;
}

/** The current folder's own menu: new folder inside, rename, move, remove. */
export function showFolderMenu(anchor, path, on) {
  const h = on || {};
  const dd = _menu(anchor, 'doclib-folder-menu', `Folder ${folderName(path)}`);
  _item(dd, 'New folder inside…', () => h.newFolder && h.newFolder(path));
  _item(dd, 'Rename…', () => h.rename && h.rename(path));
  _item(dd, 'Move to…', () => h.move && h.move(path));
  _item(dd, 'Remove folder…', () => h.remove && h.remove(path), { danger: true });
  _place(dd, anchor);
  bindMenuDismiss(dd, () => dd.remove(), (ev) => !dd.contains(ev.target) && !(anchor && anchor.contains && anchor.contains(ev.target)));
  return dd;
}

// ── removing a folder: say what is in it, then ask ───────────────────────────

/**
 * The question a removal asks, built from the server's dry run. Pure, so the
 * sentence a person reads is tested rather than assumed.
 *
 * An empty folder is one plain question. A folder with anything in it gets two
 * answers with the counts in their labels — move it all up a level, or delete
 * it with the folder — and the safe one is the button that has the focus. There
 * is no answer that deletes a document without the sentence above it saying how
 * many, and the button says it again ("Delete all 4").
 */
export function describeRemoval(summary) {
  const s = summary || {};
  const path = String(s.path || '');
  const name = folderName(path);
  const docs = Number(s.documents || 0);
  const subs = Number(s.folders || 0);
  const archived = Number(s.archived || 0);
  const parent = s.parent || null;
  if (!docs && !subs) {
    return {
      message: `Remove the empty folder “${name}”?`,
      options: { title: 'Remove folder', confirmText: 'Remove folder', danger: true },
      choices: { confirm: null },
    };
  }
  const holds = [docs ? _plural(docs, 'document') : '', subs ? _plural(subs, 'folder') : '']
    .filter(Boolean).join(' and ');
  const items = [];
  if (docs) items.push({ label: _plural(docs, 'document'), note: archived ? `${archived} archived` : '' });
  if (subs) items.push({ label: _plural(subs, 'folder'), note: 'with what is in them' });
  return {
    message: `“${name}” holds ${holds}. What should happen to ${docs + subs === 1 ? 'it' : 'them'}?`,
    options: {
      title: 'Remove folder',
      // Short enough for the dialog's three buttons to keep one line each in
      // its 360px (measured: "Delete 4 documents" wrapped and overflowed its
      // button); the sentence above names what, the label keeps the number,
      // and the footnote says where "up" is.
      confirmText: 'Move up',
      alternateText: docs ? `Delete ${_howMany(docs)}` : `Remove ${_howMany(subs)}`,
      alternateDanger: true,
      details: {
        heading: `In “${name}”`,
        items,
        footnote: parent
          ? `Moving up puts everything in “${parent}”. Deleting removes the documents the way Delete does.`
          : 'Moving up makes its documents Unfiled and its folders top-level. Deleting removes the documents the way Delete does.',
      },
    },
    choices: { confirm: 'move_up', alternate: 'delete' },
  };
}

/**
 * Remove `path` after asking. Resolves `{outcome, result}` where outcome is
 * `cancelled` · `removed` · `moved_up` · `deleted`.
 */
export async function removeFolderFlow(api, path, confirm) {
  const ask = typeof confirm === 'function' ? confirm : uiModule.styledConfirm;
  const summary = await api.remove(path, null, true);
  const question = describeRemoval(summary);
  const answer = await ask(question.message, question.options);
  if (!answer) return { outcome: 'cancelled', result: null };
  const contents = answer === 'alternate' ? question.choices.alternate : question.choices.confirm;
  const result = await api.remove(path, contents, false);
  const outcome = contents === 'delete' ? 'deleted' : (contents === 'move_up' ? 'moved_up' : 'removed');
  return { outcome, result };
}

/** The toast after a removal, from what the server says it did. */
export function describeRemovalOutcome(outcome, result) {
  const r = result || {};
  const name = folderName(r.path || '');
  const changes = Array.isArray(r.changes) ? r.changes : [];
  if (outcome === 'deleted') {
    const n = changes.filter((c) => c.change === 'deleted' && c.kind === 'document').length;
    return n ? `Removed “${name}” and deleted ${_plural(n, 'document')}` : `Removed “${name}”`;
  }
  if (outcome === 'moved_up') {
    const docs = changes.filter((c) => c.change === 'moved' && c.kind === 'document').length;
    const subs = changes.filter((c) => c.change === 'moved' && c.kind === 'folder').length;
    const parts = [docs ? _plural(docs, 'document') : '', subs ? _plural(subs, 'folder') : ''].filter(Boolean);
    return `Removed “${name}” — ${parts.join(' and ')} moved to ${whereLabel(r.parent)}`;
  }
  return `Removed “${name}”`;
}

/** The toast after filing documents. */
export function describeFiled(result) {
  const r = result || {};
  const moved = (Array.isArray(r.changes) ? r.changes : []).filter((c) => c.change === 'moved' && c.kind === 'document').length;
  if (!moved) return `Already in ${whereLabel(r.to)}`;
  return `Moved ${_plural(moved, 'document')} to ${whereLabel(r.to)}`;
}
