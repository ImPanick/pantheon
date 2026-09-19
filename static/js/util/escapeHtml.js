// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/util/escapeHtml.js
//
// `B866`'s sweep put this file here, and the reason is worth stating.
//
// The canonical HTML escaper has always been `ui.js:esc`, and `ui.js` is not a
// leaf: it imports `theme.js`, `modalManager.js`, `spinner.js`,
// `escMenuStack.js`, `toolWindowZOrder.js` and `motion.js`. Two of the modules
// the sweep found carrying their own weaker copy are deliberately free of that
// — `emailLibrary/utils.js` says so at the top of the file ("no DOM state, no
// fetch, no shared mutable references — safe to import anywhere") and three
// test files import it directly, with no sandbox, and would stop resolving if
// it reached for `ui.js`. So "use the canonical one" and "stay a leaf" were in
// conflict, and the copies were what that conflict produced.
//
// They are not in conflict any more. The implementation lives here, in a file
// that imports nothing; `ui.js` imports it and re-exports it under the name
// every caller already uses, so `uiModule.esc` and `import { esc } from
// './ui.js'` are unchanged at all of their call sites. A module that cannot
// afford `ui.js` imports this instead, and gets the same function rather than
// a fourth opinion about which characters matter.

// Hoisted out of the replace callback so it is allocated once rather than per
// matched character.
const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

/**
 * HTML-escape a string to prevent XSS.
 *
 * All five characters, not three: `>` and `'` matter, and `"` matters most —
 * `B866` was a four-line local copy that escaped `&` and `<` only, used inside
 * `title="…"` on a description that came from a third-party MCP server.
 *
 * Canonical implementation. Other modules use `uiModule.esc()`, or import
 * `esc` from here when they cannot import `ui.js`.
 */
export function esc(s) {
  return (s || '').replace(/[&<>"']/g, (m) => ESC_MAP[m]);
}

export default esc;
