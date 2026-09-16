// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B95`. Runs the two pure pieces of the tri-state panel out of
// `static/js/settings.js` — the label table and the sentence that says which
// layer answered — against the shape `GET /api/auth/settings/flag-sources`
// actually returns.
//
// Reading the file answers a different question. The row's defect was that
// three settings had no control at all, and the fix is only a fix if the
// control can express **three** states and can tell an operator that the
// environment is answering. Both of those are decided inside
// `_envflagSourceLine` and by which keys `_ENVFLAG_LABELS` covers, so the
// honest check is to run them over the real payloads.
//
// Usage:
//   node env_backed_flag_panel.js labels
//   node env_backed_flag_panel.js lines
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(
  path.join(__dirname, '..', '..', 'static', 'js', 'settings.js'), 'utf8');

function slice(startMark, endMark, label) {
  const from = src.indexOf(startMark);
  if (from < 0) { console.error(`ANCHOR-MISSING: ${label} start`); process.exit(2); }
  const to = src.indexOf(endMark, from);
  if (to < 0 || to <= from) { console.error(`ANCHOR-MISSING: ${label} end`); process.exit(2); }
  return src.slice(from, to);
}

const table = slice('const _ENVFLAG_LABELS', '/* Which of the three options', 'labels');
const picker = slice('function _envflagSelected', 'function _envflagSourceLine', 'picker');
const liner = slice('function _envflagSourceLine', '\nasync function initEnvBackedFlags', 'liner');
// eslint-disable-next-line no-eval
const sandbox = eval(`(function () { ${table}\n${picker}\n${liner}\n
  return { _ENVFLAG_LABELS, _envflagSourceLine, _envflagSelected,
           _envflagStoredValue }; })()`);

const mode = process.argv[2];
if (mode === 'labels') {
  console.log(JSON.stringify(Object.keys(sandbox._ENVFLAG_LABELS).sort()));
} else if (mode === 'states') {
  // Round-trip every stored value the API can send, and every choice the
  // control can offer, so a two-branch collapse to a checkbox shows up here
  // rather than in somebody's settings file.
  console.log(JSON.stringify({
    selected: [true, false, null, undefined].map(v => sandbox._envflagSelected(v)),
    stored: ['on', 'off', 'unset'].map(v => sandbox._envflagStoredValue(v)),
  }));
} else if (mode === 'lines') {
  const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
  console.log(JSON.stringify(cases.map(c => sandbox._envflagSourceLine(c))));
} else {
  console.error('usage: env_backed_flag_panel.js labels|states|lines');
  process.exit(2);
}
