// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B03`, second call site. Runs the real `_uploadMarkdownImages` out of
// `document.js` and reports what it inserted and what it said.
//
// This is the other of the two consumers that can reach `/api/upload`'s
// partial-failure path, and it got the count wrong in a way the chat composer
// did not: the success toast was chosen off `images` — the files the user
// PICKED — while `_insertMarkdownImages` only ever receives `data.files`. So a
// batch where the server refused two of five inserted three images and
// announced "Images inserted", claiming success for files that are nowhere in
// the document. Which array a count came from is not visible in the source
// line; both are in scope.
//
// It exists as a separate harness from the composer's because `Law 13` is the
// claim being tested — one helper, two callers — and a harness that only ever
// drove one caller could not tell a shared helper from a copy.
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'document.js');
const START = '  async function _uploadMarkdownImages(files) {';
const END = '  async function _handleMarkdownImageUpload(e) {';

const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END, from);
if (from < 0 || to < 0 || to <= from) {
  console.error('ANCHOR-MISSING: could not extract _uploadMarkdownImages from document.js');
  process.exit(2);
}
const body = source.slice(from, to);

const mode = process.argv[2] || 'partial';
const CHOSEN = ['one.png', 'two.png', 'three.png', 'four.png', 'five.png'];
const REFUSED = { partial: ['two.png', 'four.png'], clean: [], single: [] }[mode] || [];
const chosen = mode === 'single' ? ['only.png'] : CHOSEN;

const kept = chosen.filter(n => !REFUSED.includes(n));
const responseBody = { files: kept.map((n, i) => ({ id: `id-${i}`, name: n })) };
if (REFUSED.length) {
  responseBody.rejected = REFUSED.map(n => ({
    name: n, status: 429, error: 'Upload rate limit exceeded. Please try again later.',
  }));
}

const inserted = [];
const toasts = [];
const errors = [];
const rejectionCalls = [];
const uiModule = {
  showToast: (m) => toasts.push(m),
  showError: (m) => errors.push(m),
  showUploadRejections: (r, o) => { rejectionCalls.push({ names: r.map(x => x.name), opts: o }); return r.length; },
};

const appended = [];
const FormData = class { append(k, v) { appended.push(v && v.name); } };

const run = new Function(
  'uiModule', 'API_BASE', 'fetch', 'FormData', '_isMarkdownImageFile',
  '_activeDocLanguage', '_insertMarkdownImages', 'console',
  `${body}\n return { _uploadMarkdownImages };`,
);

const api = run(
  uiModule, 'https://host',
  async () => ({ ok: true, status: 200, json: async () => responseBody }),
  FormData,
  () => true,
  () => 'markdown',
  (files) => { files.forEach(f => inserted.push(f.name)); },
  { error() {} },
);

(async () => {
  await api._uploadMarkdownImages(chosen.map(name => ({ name })));
  console.log(JSON.stringify({
    mode, chosen: chosen.length, appended, inserted, toasts, errors, rejectionCalls,
  }));
})();
