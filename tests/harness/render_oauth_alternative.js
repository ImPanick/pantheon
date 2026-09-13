// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P18-09`. Runs the real `_renderOauthAlternative` against a stub DOM.
//
// Same reasoning as the setup harness beside it: the claim is *a person who
// does not want to register an application can still see the short road*, and
// that is a property of the output.
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'settings.js');
const START = '    function _renderOauthAlternative(provider, linked) {';
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
  const el = (id) => (id === 'uf-oauth-alt' ? __box : null);
  const _syncOauthUI = () => {};
  let _manualRevealed = __revealed;
`;

const body = source.slice(from, to);
const run = new Function('__box', '__revealed',
  `${stubs}\n${body}\n return _renderOauthAlternative;`);
const render = run(box, process.argv[4] === 'revealed');

render(JSON.parse(process.argv[2] || 'null'), process.argv[3] === 'linked');
console.log(JSON.stringify({ display: box.style.display, html: box.innerHTML }));
