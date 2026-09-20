// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B03`. Runs the real `uploadPending()` out of `fileHandler.js` against a
// stubbed `/api/upload` that answers the way the server now actually answers a
// partial batch — **200** with `{files, rejected}` — and reports what the
// module did with both halves.
//
// Three properties, none of them readable out of the file:
//
//   1. the user is told which files were refused. `tests/test_upload_error_surfaced.py`
//      asserts a `!res.ok` branch exists and the string "Upload failed" is
//      present; both were true throughout, because a partial batch is a 200
//      and never enters that branch.
//   2. the refused Files stay in `pendingFiles`. The line said
//      `pendingFiles = []; // clear only on success`, and a 200 with rejections
//      is not one — but only running it shows which files survive.
//   3. the per-file outcome reconstructs the compaction. `files` skips the
//      rejected entries, so `ids[i]` is not file `i`; nothing that reads the
//      source can show which id ended up on which attachment.
//
// Its docstring also says `fileHandler.js` "pulls in browser globals so it
// can't run under node". It is running under node here.
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'fileHandler.js');
const source = fs.readFileSync(SRC, 'utf8');

function slice(startAnchor, endAnchor, label) {
  const from = source.indexOf(startAnchor);
  const to = source.indexOf(endAnchor, from + 1);
  if (from < 0 || to < 0 || to <= from) {
    console.error(`ANCHOR-MISSING: could not extract ${label} from fileHandler.js`);
    process.exit(2);
  }
  return source.slice(from, to);
}

// `_wireName` comes along because the pairing and the FormData append have to
// agree on it — extracting one without the other would test a name the module
// does not actually send.
const wireName = slice('function _wireName(f) {', '\n}\n', '_wireName') + '\n}\n';
const uploadPending = slice(
  'export async function uploadPending(opts = {}) {',
  '/**\n * Add files to pending list',
  'uploadPending',
).replace(/^export\s+/gm, '');
// The real `_showToast`, not a stub. Whether the four failure messages reach
// ui.js's one toast or a private div is the `Law 14` half of this row, and a
// harness that supplied its own would prove nothing.
const showToast = slice('function _showToast(msg) {', '\n}\n', '_showToast') + '\n}\n';
// `getPendingInfo` is what the composer hands chat.js. The name it publishes
// has to be the name the FormData above posted, or the pairing keys on a string
// the server never saw — so it is extracted rather than modelled.
const pendingInfo = slice('export function getPendingInfo() {', '\n}\n', 'getPendingInfo')
  .replace(/^export\s+/gm, '') + '\n}\n';
// `B893`. `uploadPending` now asks which chat the working set belongs to before
// it posts anything, so the bucket machinery comes with it — extracted rather
// than stubbed, for the same reason `_showToast` is: a stand-in would prove the
// harness agrees with itself. This harness drives one chat, so the key stays
// `''` and the swap never fires; what it does exercise is that the ordinary
// send is untouched by the guard.
const bucket = slice(
  'const _buckets = new Map();',
  '/** Register how this module learns which chat is current.',
  'bucket machinery',
);

const mode = process.argv[2] || 'partial';

// Five files in, two refused — the row's own shape, [f0, f1x, f2, f3x, f4].
const NAMES = ['a.png', 'b.png', 'c.png', 'd.png', 'e.png'];
const REJECT = {
  partial: ['b.png', 'd.png'], clean: [],
  allbut1: ['b.png', 'c.png', 'd.png', 'e.png'], dup: ['a.png'],
  // Two consecutive uploads: the second must not be able to read the first's
  // results.
  stale: ['b.png', 'd.png'],
  // A `rejected` list that names nothing that was submitted — modelled as the
  // server sanitising both halves. The pairing cannot then account for the
  // compaction, and publishing it anyway would attribute ids by guesswork.
  unreconciled: ['b.png'],
};
const names = mode === 'dup' ? ['a.png', 'a.png', 'z.png'] : NAMES;
const rejectNames = REJECT[mode] || [];

const files = names.map((name, i) => ({ name, size: 100 + i, type: 'image/png' }));

function _isRejected(f, i) {
  // Reject by position so the duplicate-name case is unambiguous on the
  // stub side: in `dup` mode the FIRST a.png is refused.
  if (!rejectNames.includes(f.name)) return false;
  const seenBefore = files.slice(0, i).filter(x => x.name === f.name).length;
  const rejectCount = rejectNames.filter(n => n === f.name).length;
  return seenBefore < rejectCount;
}

const acceptedFiles = files.filter((f, i) => !_isRejected(f, i));
const rejectedFiles = files.filter((f, i) => _isRejected(f, i));

const responseBody = {
  // The server sanitises: `files[].name` is secure_filename()'d, while
  // `rejected[].name` is the raw form filename. Modelled, because matching an
  // accepted entry by name is exactly the mistake that shape invites.
  files: acceptedFiles.map((f, i) => ({
    id: `id-${f.name}`,
    name: f.name.toUpperCase().replace('.', '_'),
    mime: 'image/png',
    size: f.size,
    width: 10 + i,
    height: 20 + i,
  })),
};
if (rejectedFiles.length) {
  responseBody.rejected = rejectedFiles.map(f => ({
    name: mode === 'unreconciled' ? f.name.toUpperCase().replace('.', '_') : f.name,
    status: 429,
    error: 'Upload rate limit exceeded. Please try again later.',
  }));
}

const toasts = [];
const rejectionCalls = [];
const uiModule = {
  showError: (m) => toasts.push({ kind: 'error', msg: m }),
  showToast: (m) => toasts.push({ kind: 'toast', msg: m }),
  showUploadRejections: (r, o) => { rejectionCalls.push({ rejected: r, opts: o }); return r.length; },
};

// `_showToast` used to build a private `#_attach-toast` div whenever
// `window.showToast` was missing — which is always, since nothing in the tree
// assigns it. `window` below has no `showToast` (production's shape) and every
// createElement / body.appendChild is recorded, so a second toast
// implementation coming back is visible rather than merely absent from the
// `toasts` list.
const created = [];
const bodyAppends = [];
const stubNode = () => ({
  id: '', className: '', textContent: '', _timer: null,
  classList: { add() {}, remove() {} },
  querySelectorAll: () => [],
  appendChild() {}, style: { cssText: '' },
});
const document = {
  getElementById: () => stubNode(),
  createElement: () => { const n = stubNode(); created.push(n); return n; },
  body: { appendChild: (n) => { bodyAppends.push(n); return n; } },
};
const spinnerModule = { create: () => ({ createElement: () => stubNode(), start() {}, stop() {} }) };
const window = { dispatchEvent() {} };
const localStorage = { setItem() {} };
const CustomEvent = class { constructor(t, i) { this.type = t; this.detail = (i || {}).detail; } };

let renders = 0;
const renderAttachStrip = () => { renders += 1; };

// `P12-09`. `uploadPending` hands the response's `context_budget` block to the
// composer's meter, which lives in the same module and is not sliced in here.
// Injected and RECORDED rather than silently no-op'd, for the same reason
// `renderAttachStrip` is: a harness that swallows a call cannot tell "it was
// made" from "it was removed". What the meter then draws is
// `tests/test_context_meter_js.py`'s subject, not this file's.
const budgetCalls = [];
const noteContextBudget = (report, ids) => { budgetCalls.push({ kind: 'note', ids }); };
const refreshContextMeter = (ids) => { budgetCalls.push({ kind: 'refresh', ids }); };
let phase = 0;
const fetchStub = async () => {
  if (mode === 'stale' && phase === 1) {
    return { ok: false, status: 429, json: async () => ({ detail: 'Maximum concurrent uploads (3) exceeded' }) };
  }
  if (mode === 'abort') {
    const e = new Error('aborted');
    e.name = 'AbortError';
    throw e;
  }
  if (mode === 'http-429') {
    return { ok: false, status: 429, json: async () => ({ detail: 'Maximum concurrent uploads (3) exceeded' }) };
  }
  return { ok: true, status: 200, json: async () => responseBody };
};

// Node's real FormData refuses a plain object, and the names appended here are
// the wire names the server echoes back in `rejected[].name` — the whole basis
// of the pairing — so they are recorded rather than discarded.
const appended = [];
const FormData = class {
  append(k, v, name) { appended.push({ key: k, name: name === undefined ? null : name }); }
};

const build = new Function(
  'document', 'spinnerModule', 'uiModule', 'renderAttachStrip', 'fetch',
  'API_BASE', 'localStorage', 'window', 'CustomEvent', 'AbortController',
  'setTimeout', 'clearTimeout', 'FormData', '_getPreviewUrl',
  'noteContextBudget', 'refreshContextMeter', 'INITIAL',
  `
  let pendingFiles = INITIAL.slice();
  let uploaded = [];
  let _contextBudget = null;
  let _contextMeasuredIds = [];
  ${bucket}
  let _lastUploadedMeta = [];
  let _lastUploadRejected = [];
  let _lastUploadOutcome = [];
  let _uploadSpinners = [];
  let _uploadAbortCtrl = null;
  let _uploading = false;
  let _lastUploadCancelled = false;
  ${wireName}
  ${showToast}
  ${uploadPending}
  ${pendingInfo}
  return {
    uploadPending,
    read: () => ({
      pendingNames: pendingFiles.map(f => f.name),
      pendingInfo: getPendingInfo(),
      rejected: _lastUploadRejected,
      outcome: _lastUploadOutcome.map(o => ({ name: o.name, accepted: o.accepted, id: o.id, file: o.file && o.file.name })),
      meta: _lastUploadedMeta,
    }),
  };
  `,
);

const api = build(document, spinnerModule, uiModule, renderAttachStrip, fetchStub,
  '', localStorage, window, CustomEvent, AbortController, setTimeout, clearTimeout,
  FormData, (f) => `blob:${f.name}`, noteContextBudget, refreshContextMeter, files);

(async () => {
  let ids = await api.uploadPending({});
  if (mode === 'stale') {
    // Second upload, from what the first one left pending. Its failure must
    // not leave the first batch's outcome readable as if it described this one.
    phase = 1;
    ids = await api.uploadPending({});
  }
  console.log(JSON.stringify({
    mode, ids, renders, toasts, rejectionCalls, appended, budgetCalls,
    // Any node the private-toast fallback would have built and parked on body.
    privateToastNodes: bodyAppends.filter(n => n && n.id === '_attach-toast').length,
    nodesAppendedToBody: bodyAppends.length,
    ...api.read(),
  }));
})();
