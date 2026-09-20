// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B882`. This file was the fourth copy of the `markdown.js` import-rewriting
// trick and the one nobody noticed was broken: `B872` added a fifth import to
// `markdown.js`, the three Python copies were each pasted with a fifth inline,
// and this one — under node's own test runner rather than pytest — was left
// raising `ERR_UNSUPPORTED_RESOLVE_REQUEST: Failed to resolve module specifier
// "./markdown/mermaidTheme.js" from "data:text/javascript;base64,…"`, which
// failed the whole streaming suite at import. Its own comments had written
// that sentence twice already, under `B250` and `P5-06`.
//
// The loader is now `tests/helpers/markdownHarness.mjs`, which resolves
// `markdown.js`'s imports by reading them instead of listing them, so a sixth
// import needs no edit anywhere. `loadMarkdown` is re-exported here under the
// name the streaming tests have always imported — a door, not a deletion.
//
// `normalizeRender` stays, because it belongs to these tests and to nothing
// else: it is about comparing two renders of one document, not about loading
// the renderer.
export { loadMarkdown, importMarkdown, installMarkdownDom } from '../helpers/markdownHarness.mjs';

// Canonicalize rendered HTML so two renders that produce the SAME DOM compare
// equal. Collapses only newline-bearing whitespace BETWEEN tags (`>\n\n<` ->
// `><`): it is insignificant in rendered HTML, and incremental finalization
// legitimately emits `\n\n` between two blocks where a single full render emits
// `\n`. Code whitespace is safe because code is HTML-escaped, so significant
// newlines live inside <code> as text (never between a `>` and a `<`). Inline
// single spaces between tags are left alone. Structural differences (two <ul> vs
// one, <ol> vs <ul>) survive normalization and still fail, as they must.
// Mermaid ids embed Date.now(), so they are normalized too.
export function normalizeRender(html) {
  return String(html)
    .replace(/>\s*\n\s*</g, '><')
    .trim()
    .replace(/(mermaid|thinking)-\d+-\d+/g, '$1-X');
}
