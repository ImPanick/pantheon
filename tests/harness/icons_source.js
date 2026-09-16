// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B230`. The shared icon table as source, for the harnesses that evaluate a
// SLICE of a module rather than importing it.
//
// Those harnesses cut a function out of a `.js` file and hand it to
// `new Function(...)`, so the module's imports are not in scope. That was free
// while `icons.js` had two importers among them and none; `B230` moved the
// chevron onto the table and four harnesses — over `notes.js`,
// `emailLibrary.js` and the todo card — started throwing
// `ReferenceError: chevronIcon is not defined`, on a commit that changed no
// behaviour at all.
//
// **The table is inlined, never stubbed**, which is the ruling `B250` made when
// the same thing happened to `markdown.js`: a stub hands the test a glyph
// nobody ships, which is the arrangement `B83` built the table to remove. It is
// a leaf module with no imports of its own, so evaluating the shipped file is
// cheap and exact.
//
// One place, because four copies of `readFileSync(...).replace(/^export/...)`
// is the defect this whole area is about (`Law 13`, `Law 14`). A new harness
// that needs a glyph requires this and prepends `iconsSource()`.
const fs = require('fs');
const path = require('path');

const TABLE = path.join(__dirname, '..', '..', 'static', 'js', 'icons.js');

/** The shipped table with its `export` keywords stripped, so the declarations
 *  land in whatever scope the caller evaluates it in. */
function iconsSource() {
  return fs.readFileSync(TABLE, 'utf8').replace(/^export\s+/gm, '');
}

module.exports = { iconsSource, TABLE };
