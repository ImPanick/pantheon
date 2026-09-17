// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B301`. Runs the REAL chip-rendering path out of `static/js/chatRenderer.js`
// over an attachment whose SVG preview the server refused, and reports the
// accessible name the `<img>` ends up with.
//
// This has to be driven rather than read. The defect is that an `<img alt>` is
// set from the filename and nothing later changes it — a source-level check
// sees one assignment and cannot tell whether a second one ever happens, and
// the second one is asynchronous and lives behind a `fetch`.
//
// Modes:
//   refused   — the server says `X-Preview-Refused: active-content`.
//   allowed   — no refusal header; the alt must stay exactly what it was.
//   raster    — a `.png` attachment: no request may be made at all.
//   offline   — `fetch` rejects; the alt must survive untouched.
//   wiring    — the chip-render block itself, run with a recorder in place of
//               the announcement, so the CALL SITE is driven and not assumed.
//               A helper nothing calls is the defect this row is about.
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'chatRenderer.js');
const source = fs.readFileSync(SRC, 'utf8');

const mode = process.argv[2] || 'refused';

const ATT = {
  refused: { id: 'a'.repeat(32), name: 'diagram.svg', mime: 'image/svg+xml' },
  allowed: { id: 'b'.repeat(32), name: 'diagram.svg', mime: 'image/svg+xml' },
  raster:  { id: 'c'.repeat(32), name: 'photo.png', mime: 'image/png' },
  offline: { id: 'd'.repeat(32), name: 'diagram.svg', mime: 'image/svg+xml' },
}[mode];

const requests = [];
const HEADERS = {
  refused: {
    'x-preview-refused': 'active-content',
    'x-preview-refused-text': 'It contains a script.',
  },
  allowed: {},
  raster: {},
}[mode] || {};

global.fetch = async (url, opts) => {
  requests.push({ url, method: (opts && opts.method) || 'GET' });
  if (mode === 'offline') throw new Error('network down');
  return {
    ok: true,
    headers: { get: (k) => HEADERS[String(k).toLowerCase()] || null },
  };
};

if (mode === 'wiring') {
  // The real `<img>` construction, lifted between its own boundaries and run
  // against a shim just big enough to hold it up.
  const WSTART = "        const img = document.createElement('img');";
  const WEND = '        imgWrap.appendChild(img);';
  const wf = source.indexOf(WSTART);
  const wt = source.indexOf(WEND, wf);
  if (wf < 0 || wt < 0) {
    console.error('ANCHOR-MISSING: the chip <img> block moved');
    process.exit(2);
  }
  const slice = source.slice(wf, wt + WEND.length);
  const calls = [];
  const el = () => ({
    style: { cssText: '', display: '' }, classList: { add() {}, remove() {} },
    addEventListener() {}, appendChild() {}, remove() {}, dataset: {},
  });
  const document = { createElement: el };
  const imgWrap = el();
  const att = { id: 'e'.repeat(32), name: 'diagram.svg', mime: 'image/svg+xml' };
  const _announceRefusedPreview = (i, a) => { calls.push({ alt: i.alt, name: a && a.name }); };
  const run = new Function('document', 'imgWrap', 'att', 'skel', 'sp',
                           '_announceRefusedPreview', 'setTimeout', slice);
  run(document, imgWrap, att, null, null, _announceRefusedPreview, () => 0);
  console.log(JSON.stringify({ missing: false, calls }));
  process.exit(0);
}

// The real function, lifted whole between its own boundaries — no stub of it,
// and no second implementation of the header read.
const START = 'async function _announceRefusedPreview(img, att) {';
const from = source.indexOf(START);
if (from < 0) {
  console.error('ANCHOR-MISSING: _announceRefusedPreview is not in chatRenderer.js');
  console.log(JSON.stringify({ missing: true, alt: null, requests: [] }));
  process.exit(0);
}
const to = source.indexOf('\n}\n', from);
const body = source.slice(from, to + 3);

const img = { alt: (ATT.name || 'Image'), title: undefined };

(async () => {
  const fn = new Function(body + '\nreturn _announceRefusedPreview;')();
  await fn(img, ATT);
  console.log(JSON.stringify({
    missing: false,
    alt: img.alt,
    title: img.title === undefined ? null : img.title,
    requests,
  }));
})();
