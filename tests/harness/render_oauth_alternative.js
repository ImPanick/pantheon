// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P18-09`. Runs the real `_renderOauthAlternative` against a stub DOM.
//
// Same reasoning as the setup harness beside it: the claim is *a person who
// does not want to register an application can still see the short road*, and
// that is a property of the output.
//
// `B73` extended it. The renderer now asks what the provider-note panel above
// it is already showing, so that the app-password URL is not printed twice a
// few pixels apart. That question is answered by `_noteAppPasswordUrl`, which
// lives beside `_renderProviderNote` — so this harness evaluates those too,
// out of the same file, rather than stubbing the answer. Stubbing it would
// have made this harness agree with whatever the stub said.
//
// argv[2] — provider record as JSON (or 'null')
// argv[3] — 'linked' when the account is already linked
// argv[4] — 'revealed' when the person already pressed the button
// argv[5] — optional preset key to render into the note FIRST, so the
//           two-mechanisms case can be driven as a person meets it
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'settings.js');
const source = fs.readFileSync(SRC, 'utf8');

function slice(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end);
  if (from < 0 || to < 0 || to <= from) {
    console.error(`ANCHOR-MISSING: could not extract ${start.trim()} from settings.js`);
    process.exit(2);
  }
  return source.slice(from, to);
}

const presets = slice('    const PROVIDERS = {', '    const _providerOptions');
const notes = slice('    // Provider-specific helper notes',
                    "    // `P18-08`. The operator's half of enrollment");
const alternative = slice('    function _renderOauthAlternative(provider, linked) {',
                          '    function _syncOauthUI() {');

function node() {
  return {
    style: {},
    innerHTML: '',
    addEventListener() {},
    querySelector(sel) {
      if (sel !== '.uf-prov-copy') return null;
      const m = /class="admin-btn-sm uf-prov-copy" data-url="([^"]*)"/.exec(this.innerHTML);
      return m ? { dataset: { url: m[1] } } : null;
    },
  };
}

const box = node();
const noteBox = node();
const stubs = `
  const esc = (v) => String(v === undefined || v === null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
  const el = (id) => {
    if (id === 'uf-oauth-alt') return __box;
    if (id === 'uf-email-provider-note') return __note;
    return null;
  };
  const uiModule = { copyText: async () => true, showToast() {}, showError() {} };
  const _syncOauthUI = () => {};
  let _manualRevealed = __revealed;
`;

const api = new Function('__box', '__note', '__revealed',
  `${stubs}\n${presets}\n${notes}\n${alternative}\n return {
     setProviders: (list) => { _oauthProviders = list; },
     renderNote: (key) => _renderProviderNote(key),
     renderAlt: (p, linked) => _renderOauthAlternative(p, linked),
     noteUrl: () => _noteAppPasswordUrl(),
   };`)(box, noteBox, process.argv[4] === 'revealed');

const provider = JSON.parse(process.argv[2] || 'null');
const presetKey = process.argv[5] || '';
if (presetKey) {
  // One records list for the whole panel, exactly as the fetch delivers it.
  api.setProviders(provider ? [provider] : []);
  api.renderNote(presetKey);
}
api.renderAlt(provider, process.argv[3] === 'linked');

console.log(JSON.stringify({
  display: box.style.display,
  html: box.innerHTML,
  noteHtml: noteBox.innerHTML,
  noteDisplay: noteBox.style.display,
  noteUrl: api.noteUrl(),
}));
