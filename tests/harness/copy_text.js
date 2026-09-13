// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B59`. Runs the real `copyText` out of `ui.js` against a stub DOM and reports
// **when** each step happened, not just that it did.
//
// The property the row asks for — *the gesture path is synchronous* — cannot be
// checked by reading the file. An `async` body runs to its first `await`, so
// whether `execCommand` lands inside the user's gesture depends on whether any
// `await` precedes it. Calling the function without awaiting and then looking
// at what has already run is the only way to see that.
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'ui.js');
const START = 'export async function copyText(text) {';
// Extends to the end of the toasting wrapper when asked, so the thing thirteen
// callers actually use can be run rather than read.
const END = '// Wire swipe-to-dismiss';

const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END);
if (from < 0 || to < 0 || to <= from) {
  console.error('ANCHOR-MISSING: could not extract copyText from ui.js');
  process.exit(2);
}

const mode = process.argv[2] || 'legacy-ok';
const log = [];

const ta = {
  style: {}, value: '',
  setAttribute() {}, focus() { log.push('focus'); },
  select() { log.push('select'); },
  setSelectionRange() {}, remove() { log.push('remove'); },
};
const document = {
  createElement: () => ta,
  body: { appendChild: () => log.push('append') },
  execCommand: (cmd) => {
    log.push('execCommand:' + cmd);
    if (mode === 'legacy-throws') throw new Error('denied');
    return mode === 'legacy-ok';
  },
};
if (mode === 'no-execCommand') delete document.execCommand;

const navigator = {};
if (mode !== 'no-clipboard') {
  navigator.clipboard = {
    writeText: async (v) => {
      log.push('writeText');
      if (mode === 'clipboard-rejects') throw new Error('NotAllowed');
      return v;
    },
  };
}
const window = { isSecureContext: mode !== 'insecure' };

const toasts = [];
const body = source.slice(from, to).replace(/^export\s+/gm, '');
const make = new Function('document', 'navigator', 'window', 'showToast',
  `${body}\n return { copyText, copyToClipboard };`);
const api = make(document, navigator, window, (m) => toasts.push(m));

const wrapper = process.argv[3] === 'wrapper';
const fn = wrapper ? api.copyToClipboard : api.copyText;

// Called and NOT awaited. Whatever is in `log` on the next line happened
// synchronously, inside what would be the user's gesture.
const promise = fn('hello');
const synchronous = log.slice();
promise.then((ok) => {
  console.log(JSON.stringify({ ok, synchronous, full: log, value: ta.value, toasts }));
});
