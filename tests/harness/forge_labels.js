// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P0-29`. The three places a task's category name has to agree with itself,
// evaluated out of the shipped module rather than read.
//
// `static/js/tasks.js` maps a built-in action key to a display category
// (`_CATEGORY_MAP`), fixes the order categories are listed in
// (`_CATEGORY_ORDER`), and holds one glyph per category (`_CATEGORY_ICONS`).
// The category name is the join key for all three, so renaming it in one is
// how the Forge section loses its icon, or its place at the top, or both —
// silently, because a missing key is just a category drawn plain and last.
// None of the three is exported, so this slices the declarations out and
// evaluates them: the answer comes from the file's own values, not from a
// regex that would be a second copy of them.
//
// Usage: node forge_labels.js
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(
  path.join(__dirname, '..', '..', 'static', 'js', 'tasks.js'), 'utf8');

function decl(name) {
  const at = src.indexOf(`const ${name}`);
  if (at < 0) throw new Error(`${name} not found in tasks.js`);
  const end = src.indexOf('\n};', at);
  const endArr = src.indexOf('];', at);
  const stop = (end >= 0 && (endArr < 0 || end < endArr)) ? end + 3 : endArr + 2;
  if (stop <= at) throw new Error(`could not find the end of ${name}`);
  return src.slice(at, stop);
}

const code = [decl('_CATEGORY_MAP'), decl('_CATEGORY_ORDER'), decl('_CATEGORY_ICONS')]
  .join('\n');
// eslint-disable-next-line no-eval
const out = eval(`${code}\n({map: _CATEGORY_MAP, order: _CATEGORY_ORDER, icons: Object.keys(_CATEGORY_ICONS)})`);
console.log(JSON.stringify(out));
