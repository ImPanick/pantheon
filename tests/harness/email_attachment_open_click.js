// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B02`. Runs the real `.email-attachment-open` click handler out of
// `emailLibrary.js` and reports where the click LANDED.
//
// Removing `_OPENABLE_RE` puts an Open button on `photo.png`, whose backend
// answer is `{"error": "Unsupported attachment type: .png"}` returned with
// HTTP 200 — so `res.ok` is true and only `json.doc_id` distinguishes the two
// outcomes. Whether that path dead-ends in a toast or hands the user the
// download route is a property of the branch, not of the text of the file: the
// toast string is present either way. The handler has to be driven.
//
// Three modes, one question each: the backend refused (must fall back to the
// download route), the backend opened it (must NOT), the request timed out
// (must NOT — a surprise download 55 seconds after a click is not a fallback,
// and the advisory toast already says to download it).
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'emailLibrary.js');
const START = "  reader.querySelectorAll('.email-attachment-open').forEach(openBtn => {";
const END = "  reader.querySelectorAll('.email-attachment-chip').forEach(chip => {";

const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END, from);
if (from < 0 || to < 0 || to <= from) {
  console.error('ANCHOR-MISSING: could not extract the open handler from emailLibrary.js');
  process.exit(2);
}
// `import()` inside a `new Function` body has no module base to resolve `./ui.js`
// against, so it is routed through an injected stub. The specifiers stay visible
// in the assertions below, so a handler that stopped importing ui.js fails.
const block = source.slice(from, to).replace(/\bimport\(/g, '__dynImport(');

const mode = process.argv[2] || 'unsupported';

const opened = [];
const toasts = [];
const loaded = [];
const imported = [];
let hrefSet = null;

function node(tag) {
  const n = {
    tagName: tag, dataset: {}, className: '', textContent: '', innerHTML: '<orig/>',
    style: {}, children: [],
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      has(c) { return this._s.has(c); },
    },
    appendChild(c) { n.children.push(c); return c; },
    closest() { return null; },
    addEventListener(type, fn) { if (type === 'click') n._click = fn; },
  };
  return n;
}

const openBtn = node('span');
openBtn.dataset.openUid = '42';
openBtn.dataset.openIndex = '3';
openBtn.dataset.openName = 'photo.png';
openBtn.dataset.openFolder = 'Archive';

const reader = { querySelectorAll: () => [openBtn] };
const document = { createElement: node };
const spinnerModule = { createWhirlpool: () => ({ element: node('div') }) };
const API_BASE = 'https://host';
const _acct = () => '&account_id=a1';
const useFolder = 'INBOX';
const Modals = { minimize: () => true };
const _prepareEmailWindowForDocument = () => false;
const window = { open: (u) => { opened.push(u); } };

const uiStub = {
  showError: (m) => toasts.push({ kind: 'error', msg: m }),
  showToast: (m) => toasts.push({ kind: 'toast', msg: m }),
};
const __dynImport = async (spec) => {
  imported.push(spec);
  if (spec.startsWith('./ui.js')) return uiStub;
  return { loadDocument: async (id) => { loaded.push(id); } };
};

const fetchStub = async () => {
  if (mode === 'timeout') {
    const e = new Error('aborted');
    e.name = 'AbortError';
    throw e;
  }
  return {
    ok: mode !== 'http-500',
    status: mode === 'http-500' ? 500 : 200,
    json: async () => (mode === 'opened'
      ? { doc_id: 'doc-1' }
      : { error: 'Unsupported attachment type: .png', filename: 'photo.png' }),
  };
};

const run = new Function(
  'reader', 'document', 'spinnerModule', 'API_BASE', '_acct', 'useFolder',
  'Modals', '_prepareEmailWindowForDocument', 'window', 'fetch',
  'AbortController', 'setTimeout', 'clearTimeout', 'console', 'alert',
  '__dynImport', 'location',
  block,
);

const location = { set href(v) { hrefSet = v; } };
run(reader, document, spinnerModule, API_BASE, _acct, useFolder, Modals,
    _prepareEmailWindowForDocument, window, fetchStub, AbortController,
    setTimeout, clearTimeout, { error() {}, warn() {} }, () => {}, __dynImport,
    location);

if (typeof openBtn._click !== 'function') {
  console.error('ANCHOR-MISSING: the extracted block registered no click listener');
  process.exit(2);
}

(async () => {
  await openBtn._click({ stopPropagation() {}, preventDefault() {} });
  console.log(JSON.stringify({
    mode, opened, toasts, loaded, imported, hrefSet,
    stillBusy: openBtn.dataset.opening === '1',
    loadingClassLeft: openBtn.classList.has('is-loading'),
    innerHtmlRestored: openBtn.innerHTML === '<orig/>',
  }));
})();
