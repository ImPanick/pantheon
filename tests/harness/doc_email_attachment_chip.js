// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B02`, the second gate. Runs the real per-attachment chip block out of
// `document.js` (the email-compose attachment strip) and reports which endpoint
// a click actually reached.
//
// This is the gate the row never mentions. `emailLibrary.js` gated the Open
// button on six suffixes; this file gated it on ONE — `isPdf` — and every other
// attachment went straight to the download route, so dropping only
// `_OPENABLE_RE` would have left the backend's decode fallback unreachable from
// here. The distinction between "downloads" and "opens in the editor" is which
// URL is fetched, which is exactly what reading the file cannot tell you once
// both URLs are present in the same block.
//
// The regression this guards in the other direction matters as much: a `.log`
// chip must still DOWNLOAD when the chip body is clicked. `B02` may not cost
// anyone the Save dialog the comment in that branch defends (`Law 1`).
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'document.js');
const START = "          const isPdf = (att.filename || '').toLowerCase().endsWith('.pdf');";
const END = "\n      } else {\n        attDiv.style.display = 'none';";

const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END, from);
if (from < 0 || to < 0 || to <= from) {
  console.error('ANCHOR-MISSING: could not extract the attachment chip block from document.js');
  process.exit(2);
}
// The slice runs to the close of the enclosing `for (const att of ...)`; drop
// that one brace so the block is a loop BODY that can be run once per
// attachment. Balance is asserted rather than assumed.
let block = source.slice(from, to).replace(/\n[ \t]*\}[ \t]*$/, '\n');
const opens = (block.match(/\{/g) || []).length;
const closes = (block.match(/\}/g) || []).length;
if (opens !== closes) {
  console.error(`ANCHOR-MISSING: unbalanced slice (${opens} { vs ${closes} })`);
  process.exit(2);
}

const mode = process.argv[2] || 'log-open';
const FILENAME = {
  'pdf-chip': 'report.pdf',
  'log-open': 'server.log',
  'log-chip': 'server.log',
  'png-open': 'photo.png',
}[mode] || 'server.log';

const fetched = [];
const opened = [];
const errors = [];
const loaded = [];
const downloads = [];

function node(tag) {
  const n = {
    tagName: tag, type: '', className: '', title: '', href: '', download: '',
    dataset: {}, children: [], _html: '', _listeners: {}, style: {}, textContent: '',
    get innerHTML() { return n._html; },
    set innerHTML(v) { n._html = String(v); },
    appendChild(c) { n.children.push(c); return c; },
    remove() {},
    click() { downloads.push({ href: n.href, name: n.download }); },
    addEventListener(t, fn) { (n._listeners[t] = n._listeners[t] || []).push(fn); },
    dispatch(t, ev) { return (n._listeners[t] || []).map(fn => fn(ev))[0]; },
  };
  return n;
}

const attDiv = node('div');
const document = { createElement: node, body: node('body') };
const spinnerModule = { createWhirlpool: () => node('span') };
const uiModule = { showError: (m) => errors.push(m), showToast: () => {} };
const window = { open: (u) => opened.push(u) };
const API_BASE = 'https://host';
const _escHtml = (s) => String(s == null ? '' : s).replace(/[<>&"]/g, '_');
const loadDocument = async (id) => { loaded.push(id); };
const att = { filename: FILENAME, index: 7, size: 4096 };
const fields = { sourceUid: '99', sourceFolder: 'Archive' };

const fetchStub = async (url, init) => {
  fetched.push({ url, method: (init && init.method) || 'GET' });
  if (url.includes('attachment-as-doc')) {
    const supported = !FILENAME.endsWith('.png');
    return { ok: true, status: 200, json: async () => (supported
      ? { doc_id: 'doc-9' }
      : { error: 'Unsupported attachment type: .png' }) };
  }
  return { ok: true, status: 200, blob: async () => ({ size: 4096 }) };
};

globalThis.URL = { createObjectURL: () => 'blob:1', revokeObjectURL: () => {} };

const run = new Function(
  'att', 'fields', 'attDiv', 'document', 'API_BASE', 'fetch', 'loadDocument',
  'uiModule', 'spinnerModule', 'window', '_escHtml', 'console', 'setTimeout', 'URL',
  block,
);
run(att, fields, attDiv, document, API_BASE, fetchStub, loadDocument, uiModule,
    spinnerModule, window, _escHtml, { error() {} }, setTimeout, globalThis.URL);

const chip = attDiv.children[0];
if (!chip) {
  console.error('ANCHOR-MISSING: the extracted block appended no chip');
  process.exit(2);
}

// The Open affordance is delegated: the listener is on the chip and reads
// `ev.target.closest('.email-attachment-open')`, so a click on the span and a
// click on the chip body are the same listener with different targets.
const onOpen = mode.endsWith('-open');
const ev = {
  target: { closest: (sel) => (onOpen && sel === '.email-attachment-open' ? { sel } : null) },
  stopPropagation() {}, preventDefault() {},
};

(async () => {
  await chip.dispatch('click', ev);
  console.log(JSON.stringify({
    mode,
    filename: FILENAME,
    chipHtmlHasOpen: chip.innerHTML.includes('email-attachment-open'),
    chipClass: chip.className,
    fetched,
    asDocCalls: fetched.filter(f => f.url.includes('attachment-as-doc')).length,
    downloadRouteCalls: fetched.filter(f => f.url.includes('/api/email/attachment/')).length,
    opened, errors, loaded, downloads,
  }));
})();
