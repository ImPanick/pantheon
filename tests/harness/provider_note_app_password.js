// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B73`. Runs the REAL preset table, the REAL provider-record lookup and the
// REAL `_renderProviderNote` out of `settings.js` against a stub DOM.
//
// The claim is *one mechanism tells a person where an app password comes
// from*, and that is a property of the rendered note plus the record it read.
// So nothing in the chain preset → host → record → URL is stubbed: `PROVIDERS`,
// `PROVIDER_NOTES`, `_presetAppPasswordUrl`, `_oauthFor` and the renderer all
// come out of the file. The only inputs are the DOM and the provider payload,
// and the test feeds the payload the real backend serves.
//
// argv[2] — preset key ('' for Custom…). Several may be given comma-separated
//           and are rendered in order, so a second selection can be driven
//           against the state the first one left behind.
// argv[3] — JSON array of provider records, as `/api/email/oauth/providers`
//           returns them. Omit or pass 'none' for "the fetch has not landed".
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'settings.js');
const source = fs.readFileSync(SRC, 'utf8');

// Two slices, because the form's own `innerHTML` template sits between them
// and drags in half the panel's local scope. Both are real source.
function slice(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end);
  if (from < 0 || to < 0 || to <= from) {
    console.error(`ANCHOR-MISSING: ${start.trim()} .. ${end.trim()}`);
    process.exit(2);
  }
  return source.slice(from, to);
}

const presets = slice('    const PROVIDERS = {', '    const _providerOptions');
const notes = slice('    // Provider-specific helper notes',
                    "    // `P18-08`. The operator's half of enrollment");

// A DOM node thin enough to be obviously not the thing under test: it stores
// the HTML it is given and answers `querySelector` for the one selector the
// code asks about.
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

const noteNode = node();
const stubs = `
  const esc = (v) => String(v === undefined || v === null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
  const el = (id) => (id === 'uf-email-provider-note' ? __note : null);
  const uiModule = { copyText: async () => true, showToast() {}, showError() {} };
`;

const api = new Function('__note', `${stubs}\n${presets}\n${notes}\n return {
  setProviders: (list) => { _oauthProviders = list; },
  renderNote: (key) => _renderProviderNote(key),
  noteUrl: () => _noteAppPasswordUrl(),
  presetUrl: (key) => _presetAppPasswordUrl(key),
  presetHost: (key) => (PROVIDERS[key] && PROVIDERS[key].imap.host) || '',
  hasNoteEntry: (key) => Object.prototype.hasOwnProperty.call(PROVIDER_NOTES, key),
};`)(noteNode);

const raw = process.argv[3];
api.setProviders(!raw || raw === 'none' ? [] : JSON.parse(raw));
const keys = String(process.argv[2] || '').split(',');
keys.forEach(k => api.renderNote(k));

const key = keys[keys.length - 1];
const urls = [...noteNode.innerHTML.matchAll(/https?:\/\/[^"<\s]+/g)].map(m => m[0]);
console.log(JSON.stringify({
  display: noteNode.style.display,
  html: noteNode.innerHTML,
  urls,
  distinctUrls: [...new Set(urls)],
  noteUrl: api.noteUrl(),
  presetUrl: api.presetUrl(key),
  presetHost: api.presetHost(key),
  hasNoteEntry: api.hasNoteEntry(key),
  hasLinkRow: noteNode.innerHTML.includes('uf-prov-copy'),
}));
