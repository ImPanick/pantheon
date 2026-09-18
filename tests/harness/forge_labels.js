// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P0-29`. The three places a task's category name has to agree with itself,
// evaluated out of the shipped module rather than read.
//
// **The join moved across the wire on 2026-09-18 (`P8-22`) and so did this
// harness.** Two of the three lived here — `_CATEGORY_MAP`, an action→category
// table, and `_CATEGORY_ORDER`, the order the groups render in — and both were
// second copies of what `src/builtin_actions.py` already knew, so a new action
// needed an edit on the far side of the wire before it could be filed or drawn.
// They are `/meta/actions`'s `category` and `categories` now. What is still
// only in `static/js/tasks.js` is `_CATEGORY_ICONS`, one glyph per category,
// and the category NAME is still the join key — so renaming it server-side is
// how the Forge section silently loses its icon.
//
// This file therefore reports the half that lives in the browser. The caller
// (`tests/test_the_product_noun_is_forge.py`) reads the other two out of the
// Python registry and checks the three agree, which is a stronger check than
// the one it replaced: it now spans the wire the rename would have to cross.
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

const code = [decl('_CATEGORY_ICONS'), decl('_TASK_ICONS')].join('\n');
// eslint-disable-next-line no-eval
const out = eval(`${code}\n({icons: Object.keys(_CATEGORY_ICONS), actionIcons: Object.keys(_TASK_ICONS)})`);
console.log(JSON.stringify(out));
