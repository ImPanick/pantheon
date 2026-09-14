// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B02`. Runs the real `_buildAttsHtmlFor` out of `emailLibrary.js` over a list
// of attachments and reports, per filename, whether the reader rendered an
// "Open in document editor" affordance.
//
// Reading the file cannot answer this. The gate that was removed
// (`_OPENABLE_RE`) was one expression inside a template-literal branch, and the
// row's `Verify` — *"a `.log` attachment opens in the editor"* — is about what
// a specific filename produces. Grepping for the absence of a regex proves the
// regex is gone, not that `.log` now gets a button, and would keep passing if
// the same six suffixes came back spelled differently. So build the markup and
// look at it.
//
// The slice starts at `_isLikelySignatureImage` so that filter runs for real:
// it is the OTHER reason a chip can be missing, and a test that could not tell
// "no Open button" from "no chip at all" would be measuring the wrong thing.
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'emailLibrary.js');
const START = 'function _isLikelySignatureImage(a) {';
const END = 'async function _ensureEmailAttachmentData(';

const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END, from);
if (from < 0 || to < 0 || to <= from) {
  console.error('ANCHOR-MISSING: could not extract _buildAttsHtmlFor from emailLibrary.js');
  process.exit(2);
}
const body = source.slice(from, to);

const _esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const state = { _libFolder: 'INBOX' };

const make = new Function('_esc', 'state', `${body}\n return { _buildAttsHtmlFor, _isLikelySignatureImage };`);
const api = make(_esc, state);

// One attachment per interesting class. Sizes are 60 KB so the
// signature-image heuristic does not quietly drop the image cases — the point
// of `photo.png` here is that it IS chipped and IS offered an Open, whose
// backend answer is a rejection the click handler turns into a download.
const NAMES = [
  'report.pdf', 'notes.txt', 'readme.md', 'spec.markdown', 'letter.docx', 'fwd.eml',
  'server.log', 'rows.csv', 'config.json', 'stack.yaml', 'setup.ini', 'script.py',
  'page.html', 'schema.sql', 'pyproject.toml', 'data.tsv', 'LICENSE', 'Makefile',
  'photo.png', 'archive.zip',
];

const data = {
  folder: 'INBOX',
  attachments: NAMES.map((filename, index) => ({ filename, index, size: 60 * 1024 })),
};

const html = api._buildAttsHtmlFor('42', data);

// One chip per <button>. Split on the opening tag so each slice holds exactly
// one chip's markup, including any nested open affordance.
const chips = html.split('<button type="button" class="email-attachment-chip').slice(1);
const perName = {};
for (const name of NAMES) {
  const chip = chips.find(c => c.includes(`data-att-name="${_esc(name)}"`));
  perName[name] = {
    chipped: !!chip,
    open: !!(chip && chip.includes('class="email-attachment-open"')),
    openName: chip ? (chip.match(/data-open-name="([^"]*)"/) || [])[1] || null : null,
  };
}

console.log(JSON.stringify({
  perName,
  chipCount: chips.length,
  openCount: (html.match(/class="email-attachment-open"/g) || []).length,
}));
