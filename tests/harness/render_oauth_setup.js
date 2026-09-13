// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P18-08`. Runs the real `_renderOauthSetup` out of `settings.js` against a
// stub DOM and prints what it produced.
//
// **Why a harness and not a source assertion.** The rest of this repo checks
// browser behaviour by reading the file and looking for a substring, which is
// what `Law 20` warns about: it tests the file. For the enrollment walkthrough
// that is not good enough — the thing being claimed is *an operator can follow
// this*, and every interesting property of it (a step is skipped when its value
// is absent, the box hides once configured, nothing is hard-coded per provider)
// is a property of the OUTPUT, not of the text.
//
// The function is extracted between two anchors and evaluated with `esc` and
// `el` stubbed. If either anchor moves the extraction fails loudly rather than
// silently testing nothing, which is the failure mode a substring check has.
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'settings.js');
const START = '    const _copyRow = (label, value, hint) => `';
const END = '    function _syncOauthUI() {';

const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END);
if (from < 0 || to < 0 || to <= from) {
  console.error('ANCHOR-MISSING: could not extract the renderer from settings.js');
  process.exit(2);
}

const box = { style: {}, innerHTML: '' };
const stubs = `
  const esc = (v) => String(v === undefined || v === null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
  const el = (id) => (id === 'uf-oauth-setup' ? __box : null);
`;

const body = source.slice(from, to);
const run = new Function('__box', `${stubs}\n${body}\n return _renderOauthSetup;`);
const render = run(box);

const payload = JSON.parse(process.argv[2] || 'null');
render(payload, process.argv[3] === 'linked');
console.log(JSON.stringify({ display: box.style.display, html: box.innerHTML }));
