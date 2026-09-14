// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B03`. Runs the real `showUploadRejections` out of `ui.js` and prints the
// message it hands to `showError`.
//
// The row's `Verify` is *"drop 30 files, see a message naming the 5 that did
// not upload"* — a property of the TEXT, and of which of the two ui.js toasts
// it goes to. A source-level check can see the function exists; it cannot see
// that five names survive the cap, that a shared reason is said once rather
// than five times, or that a refusal reaches `showError` (dismissible, 6s) and
// not `showToast` (1.2s, styled as success).
//
// The slice starts at the real `showError` so the routing is observed rather
// than stubbed: a change that sent rejections to the success toast would still
// pass a harness that only wired up a fake.
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'ui.js');
const START = 'export function showError(msg) {';
const END = '\n/**\n * Smooth-scroll chat history to bottom';

const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END, from);
if (from < 0 || to < 0 || to <= from) {
  console.error('ANCHOR-MISSING: could not extract showUploadRejections from ui.js');
  process.exit(2);
}
const body = source.slice(from, to).replace(/^export\s+/gm, '');

const CASES = {
  // The row's own number, and the reason five batch files share.
  five: Array.from({ length: 5 }, (_, i) => ({
    name: `photo-${i}.png`, status: 429,
    error: 'Upload rate limit exceeded. Please try again later.',
  })),
  one: [{ name: 'huge.zip', status: 400, error: 'File size exceeds 100.0 MB limit' }],
  // Over the naming cap: the remainder must be counted, never dropped.
  nine: Array.from({ length: 9 }, (_, i) => ({
    name: `f${i}.txt`, status: 429, error: 'Upload rate limit exceeded. Please try again later.',
  })),
  // Two genuinely different reasons — saying only the first would imply it
  // covers both.
  mixed: [
    { name: 'empty.txt', status: 400, error: 'File is empty' },
    { name: 'late.png', status: 429, error: 'Upload rate limit exceeded. Please try again later.' },
  ],
  nameless: [{ status: 500, error: 'Upload failed' }],
  reasonless: [{ name: 'x.bin', status: 500 }],
  empty: [],
  notanarray: null,
};

const mode = process.argv[2] || 'five';
const suffix = process.argv[3] && process.argv[3] !== '-' ? process.argv[3] : undefined;

// A stub #toast node good enough for the real showError, plus a record of
// which class it ended up carrying — `error` is the visual difference between
// the two toasts.
const node = () => {
  const n = {
    _text: '', children: [], style: {}, _cls: new Set(),
    classList: {
      add(...c) { c.forEach(x => n._cls.add(x)); },
      remove(...c) { c.forEach(x => n._cls.delete(x)); },
      contains(c) { return n._cls.has(c); },
    },
    get textContent() { return n._text; },
    set textContent(v) { n._text = String(v); if (v === '') n.children = []; },
    setAttribute() {}, addEventListener() {},
    appendChild(c) { n.children.push(c); return c; },
  };
  return n;
};
const toast = node();
toast.id = 'toast';
const document = { getElementById: (id) => (id === 'toast' ? toast : null), createElement: node };

const make = new Function('document', 'spinnerModule', 'setTimeout', 'clearTimeout',
  `let toastEl = null;
   function _wireToastSwipe() {}
   ${body}
   return { showUploadRejections, showError };`);
const api = make(document, { createWhirlpool: () => node() }, () => 0, () => {});

const returned = api.showUploadRejections(CASES[mode], suffix ? { suffix } : {});
const text = toast.children.map(c => c.textContent).join('');

console.log(JSON.stringify({
  mode, returned, text,
  shown: toast._cls.has('show'),
  isErrorToast: toast._cls.has('error'),
  namesInText: Object.values(CASES[mode] || []).filter(r => r && r.name && text.includes(r.name)).length,
}));
