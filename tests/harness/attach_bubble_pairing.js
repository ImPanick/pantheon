// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B03`, the defect the row does not state. Runs the real id-stamping block out
// of `chat.js` over a partial batch and reports which id landed on which
// attachment row.
//
// `_pendingAttachInfo` is one entry per file the user attached, in input order.
// `ids` comes from the server's `files`, which preserves input order but SKIPS
// every rejected file. For `[a, b✗, c, d✗, e]` that is three ids against five
// rows, and pairing them by index gave row `b` the id of `c` — the user's own
// message bubble showed the WRONG THUMBNAIL under the RIGHT FILENAME. That is
// mis-attribution, not omission: no toast fixes it, and nothing in the source
// text says which of the two lists an index belongs to. The pairing has to be
// run and the result read off.
//
// Modes are the three shapes this block has to survive: a partial batch, a
// clean one, and an upload whose outcome does not describe these rows at all
// (a queue drain) — where it must fall back rather than stamp from a list
// belonging to somebody else's upload.
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'chat.js');
const START = '      if (_userMsgEl && _pendingAttachInfo && ids.length) {';
const END = '      // Offer to import text files to document library';

const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END, from);
if (from < 0 || to < 0 || to <= from) {
  console.error('ANCHOR-MISSING: could not extract the id-stamping block from chat.js');
  process.exit(2);
}
const block = source.slice(from, to);

const mode = process.argv[2] || 'partial';

const NAMES = ['a.png', 'b.png', 'c.png', 'd.png', 'e.png'];
const rejected = { partial: ['b.png', 'd.png'], clean: [], drain: [], 'drain-same-size': [] }[mode] || [];

const info = NAMES.map(n => ({ name: n, uploadName: n, previewUrl: `blob:${n}` }));
const acceptedNames = NAMES.filter(n => !rejected.includes(n));

// What the server sent back: compacted, and with the names sanitised the way
// secure_filename() does, so a pairing that tried to match on `files[].name`
// would find nothing.
const meta = acceptedNames.map((n, i) => ({
  id: `id-${n}`, name: n.toUpperCase().replace('.', '_'), width: 10 + i, height: 20 + i,
}));
const ids = meta.map(m => m.id);

const outcome = mode === 'drain'
  // A queue drain: these rows came off the queued item, and the module's last
  // upload was a different batch entirely.
  ? [{ name: 'somebody-elses.png', accepted: true, id: 'id-x', meta: { width: 1, height: 2 } }]
  : mode === 'drain-same-size'
  // The same shape, same length, different files — the case a length check
  // alone cannot separate from this batch. Only the per-row name can.
  ? NAMES.map((_, i) => ({
    name: `other-${i}.png`, accepted: true, id: `id-other-${i}`, meta: { width: 99, height: 99 },
  }))
  : NAMES.map((n) => {
    if (rejected.includes(n)) return { name: n, accepted: false, id: null, meta: null };
    const m = meta[acceptedNames.indexOf(n)];
    return { name: n, accepted: true, id: m.id, meta: m };
  });

let rendered = null;
const chatRenderer = {
  updateMessageAttachments: (_el, atts) => {
    rendered = atts.map(a => ({ name: a.name, id: a.id || null, width: a.width || null }));
  },
};
const fileHandlerModule = {
  getLastUploadedMeta: () => meta,
  getLastUploadOutcome: () => outcome.map(o => ({ ...o })),
};

const run = new Function('_userMsgEl', '_pendingAttachInfo', 'ids', 'fileHandlerModule', 'chatRenderer', block);
run({}, info, ids, fileHandlerModule, chatRenderer);

console.log(JSON.stringify({
  mode,
  ids,
  // Every row, so a rejected one carrying a borrowed id is visible.
  stamped: info.map(a => ({ name: a.name, id: a.id || null, width: a.width || null })),
  rendered,
}));
