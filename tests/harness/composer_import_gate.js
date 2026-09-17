// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B232`. Runs the REAL block out of `static/js/chat.js` that decides which
// attachments the composer offers to import, over a batch of real filenames and
// the server's real verdicts, and reports what it picked.
//
// The defect is invisible to a source-level check, which is why this exists: it
// was a 38-extension regex in front of a backend that derives the answer, and
// what it got wrong were files whose extension is not on any list (`.kt`,
// `.toml`) and files whose extension is on the wrong list (`.pdf`, `.docx` —
// containers offered to a path that pre-reads the raw `File` as text). Both
// halves need the block driven against the verdicts a server actually returns.
//
// Modes:
//   verdicts  — a mixed batch: text, containers, binary, and a rejected file.
//   drain     — the queue-drain shape, where the last upload belongs to another
//               batch and nothing may be believed from it.
//   mismatch  — same length, different names: the per-row name check.
//   stale     — every row accepted, but the server's reply carries no `kind`
//               (an older server, a response shape that moved). Nothing may be
//               offered: "no verdict" is not "text".
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'chat.js');
// Anchored one line EARLIER than the gate itself, so the extracted block is the
// same region on the tree before this row (where it opened with a 38-extension
// `IMPORTABLE_EXT` regex) and on the tree after it. An anchor that only exists
// after the fix makes the old tree throw, and a stack trace is weaker evidence
// than a wrong list.
const START = '      if (!approvalForSend) _pendingSendAttachInfo = null;';
const END = '      let _userMsgEl = null;';

const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END, from);
if (from < 0 || to < 0 || to <= from) {
  console.error('ANCHOR-MISSING: could not extract the import-gate block from chat.js');
  process.exit(2);
}
const block = source.slice(from, to);

const mode = process.argv[2] || 'verdicts';

// One row per shape the gate has to get right. `kind` is what the server's
// `ingest_kind` answers for those bytes — not something this harness decides.
const BATCH = [
  { name: 'notes.txt', kind: 'text' },
  { name: 'Main.kt', kind: 'text' },        // no register names it; the bytes decode
  { name: 'server.toml', kind: 'text' },    // offered before this row, and rightly
  { name: '.env', kind: 'text' },
  { name: 'report.pdf', kind: 'document' }, // MUST NOT reach the text reader
  { name: 'memo.doc', kind: 'document' },
  { name: 'deck.pptx', kind: 'document' },
  { name: 'photo.png', kind: 'binary' },
  { name: 'archive.zip', kind: 'binary' },
  { name: 'refused.txt', kind: 'text', rejected: true },
];

const _pendingAttachInfo = BATCH.map(r => ({ name: r.name, uploadName: r.name }));
const files = BATCH.map(r => ({ __file: r.name, text: async () => 'body of ' + r.name }));

let outcome;
if (mode === 'drain') {
  outcome = [];
} else if (mode === 'stale') {
  outcome = BATCH.map((r, i) => ({
    name: r.name, accepted: true, id: 'id-' + i,
    meta: { id: 'id-' + i, name: r.name }, file: files[i],
  }));
} else if (mode === 'mismatch') {
  outcome = BATCH.map((r, i) => ({
    name: 'other-' + i + '.txt', accepted: true, id: 'x' + i,
    meta: { kind: 'text' }, file: files[i],
  }));
} else {
  outcome = BATCH.map((r, i) => (r.rejected
    ? { name: r.name, accepted: false, id: null, meta: null, file: files[i] }
    : { name: r.name, accepted: true, id: 'id-' + i, meta: { kind: r.kind }, file: files[i] }));
}

// `getPendingRaw` is what the 38-extension version of this block read, and it
// is stubbed here on purpose: the old block then RUNS and produces its own
// (wrong) answer instead of throwing, so the assertions in
// `tests/test_composer_import_gate_asks_the_server.py` fail on the tree as it
// stood with a measured list rather than a stack trace (`Law 9`).
const fileHandlerModule = {
  getLastUploadOutcome: () => outcome.map(o => ({ ...o })),
  getPendingRaw: () => files,
};
const documentModule = {};
const INGEST_KIND_TEXT = 'text';
const INGEST_KIND_DOCUMENT = 'document';

let _importableFiles;
let _pendingSendAttachInfo = null;
const approvalForSend = null;
const runner = new Function(
  '_pendingAttachInfo', 'documentModule', 'fileHandlerModule',
  'INGEST_KIND_TEXT', 'INGEST_KIND_DOCUMENT', 'approvalForSend',
  '_pendingSendAttachInfo',
  block + '\nif (typeof _collectImportable === "function") _collectImportable();'
        + '\nreturn _importableFiles;');
_importableFiles = runner(_pendingAttachInfo, documentModule, fileHandlerModule,
                          INGEST_KIND_TEXT, INGEST_KIND_DOCUMENT, approvalForSend,
                          _pendingSendAttachInfo);

// The IMPORT LOOP itself, lifted between its own boundaries and run over the
// rows the gate picked, so "a container is never handed to `file.text()`" is a
// thing this harness watched happen rather than a property it inferred from a
// field. `file.text()` and the POST helper both record their calls.
const LSTART = '          let imported = 0;';
const LEND = '          banner.textContent =';
const lf = source.indexOf(LSTART);
const lt = source.indexOf(LEND, lf);
const readAsText = [];
const posted = [];
let imported = 0;
if (lf >= 0 && lt > lf) {
  const loop = source.slice(lf, lt);
  const API_BASE = '';
  global.fetch = async (url, opts) => {
    let payload = null;
    if (opts && typeof opts.body === 'string') {
      try { payload = JSON.parse(opts.body); } catch (_) {}
    }
    posted.push({ url, title: payload && payload.title });
    return { ok: true, status: 200, json: async () => ({ id: 'doc-1' }) };
  };
  const _importFileAsDocument = async (file, name) => {
    posted.push({ url: '/api/documents/import-*', title: name });
    return { id: 'doc-1' };
  };
  const documentLanguage = (n) => 'markdown';
  for (const row of _importableFiles) {
    row.file = { text: async () => { readAsText.push(row.info.name); return 'x'; } };
  }
  const runLoop = new Function(
    '_importableFiles', 'API_BASE', 'fetch', 'documentLanguage',
    '_importFileAsDocument', 'INGEST_KIND_DOCUMENT', 'console',
    '"use strict"; return (async () => {' + loop + '\nreturn imported; })();');
  runLoop(_importableFiles, API_BASE, global.fetch, documentLanguage,
          _importFileAsDocument, INGEST_KIND_DOCUMENT, console)
    .then(n => { imported = n; emit(); }, e => { emit(String(e)); });
} else {
  emit('ANCHOR-MISSING: import loop');
}

function emit(error) {
  console.log(JSON.stringify({
    offered: _importableFiles.map(x => x.info.name),
    kinds: _importableFiles.map(x => x.kind === undefined ? null : x.kind),
    // What the loop actually did with each row.
    readAsText,
    posted: posted.map(p => p.title),
    postedTo: posted.map(p => p.url),
    imported,
    error: error || null,
  }));
}
