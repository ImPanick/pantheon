// SPDX-License-Identifier: AGPL-3.0-or-later
// Loads the real browser markdown renderer (static/js/markdown.js) under Node by
// mocking the minimal browser globals it touches and stubbing its sibling imports.
// This mirrors the loader in tests/test_markdown_rendering_js.py so the streaming
// tests exercise the exact same renderer the browser runs.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

export async function loadMarkdown() {
  globalThis.window = { location: { origin: 'http://localhost' }, katex: null };
  globalThis.document = {
    readyState: 'loading',
    addEventListener() {},
    createElement(tag) {
      if (tag !== 'template') throw new Error(`unsupported element: ${tag}`);
      return {
        _html: '',
        content: { querySelectorAll() { return []; } },
        set innerHTML(v) { this._html = v; },
        get innerHTML() { return this._html; },
      };
    },
  };
  globalThis.MutationObserver = class { observe() {} };

  let src = fs.readFileSync(path.join(REPO, 'static/js/markdown.js'), 'utf8');
  src = src.replace(/import uiModule from ['"]\.\/ui\.js['"];/, '');
  src = src.replace(
    /import \{ splitTableRow \} from ['"]\.\/markdown\/tableRow\.js['"];/,
    () => `function splitTableRow(row){return (row||'').replace(/^\\s*\\|/,'').replace(/\\|\\s*$/,'').split('|').map((c)=>c.trim());}`,
  );
  // `B250`. `B83` gave `markdown.js` its run-code play triangle from the shared
  // icon table, and a relative specifier cannot resolve from a `data:` URL, so
  // the whole streaming suite failed to import. Inlined rather than stubbed, on
  // the same terms as the emoji module below: a stub would hand this test a
  // glyph nobody ships, which is the shape `B83` existed to remove.
  //
  // Inlined verbatim, and the `export` keywords are deliberately NOT stripped.
  // The import being replaced is at module top level, where `export` is legal,
  // so a strip changes nothing a test can see — measured: removing both strips
  // survives mutation. The sibling loader in `tests/test_markdown_rendering_js.py`
  // strips anyway; that it can and this does not is `B250`.
  const icons = fs.readFileSync(path.join(REPO, 'static/js/icons.js'), 'utf8');
  src = src.replace(
    /import \{[^}]*\} from ['"]\.\/icons\.js['"];/,
    () => icons,
  );
  // `P5-06`. The code block's header draws its language glyph with
  // `langIcons.js` — the module `document.js` and `documentLibrary.js` already
  // imported and chat never did. Same treatment and the same reason as the
  // icon table above: a relative specifier cannot resolve from a `data:` URL,
  // and a stub would hand this test a glyph nobody ships. `export default` is
  // stripped because two of them in one module is a syntax error.
  const langIcons = fs
    .readFileSync(path.join(REPO, 'static/js/langIcons.js'), 'utf8')
    .replace(/^export default .*$/m, '');
  src = src.replace(
    /import \{[^}]*\} from ['"]\.\/langIcons\.js['"];/,
    () => langIcons,
  );
  // `B882`. The fifth import, and the fourth copy of this trick. `B872` moved
  // Mermaid's theme decision into `markdown/mermaidTheme.js` and inlined it into
  // the three loaders written in Python; this one is `.mjs` under node's own
  // test runner and was missed, so the whole streaming suite failed to import
  // with `ERR_UNSUPPORTED_RESOLVE_REQUEST` — the same sentence `B250` and
  // `P5-06` above already wrote twice. Four copies of one thirteen-line trick is
  // the row; this is the fourth, and it is the one that was broken.
  //
  // The module is import-free by construction (the Mermaid harness needs to
  // load it directly), so a verbatim inline works. `export default` is stripped
  // because two in one module is a syntax error; the named `export`s are left,
  // for the reason `B250` gives above.
  const mermaidTheme = fs
    .readFileSync(path.join(REPO, 'static/js/markdown/mermaidTheme.js'), 'utf8')
    .replace(/^export default [\s\S]*?^\};$/m, '');
  src = src.replace(
    /import \{[^}]*\} from ['"]\.\/markdown\/mermaidTheme\.js['"];/,
    () => mermaidTheme,
  );
  const emoji = fs
    .readFileSync(path.join(REPO, 'static/js/emojiShortcodes.js'), 'utf8')
    .replace(/^export default .*$/m, '')
    .replace(/export const /g, 'const ')
    .replace(/export function /g, 'function ');
  src = src.replace(
    /import \{ replaceEmojiShortcodes, hasEmojiShortcode \} from ['"]\.\/emojiShortcodes\.js['"];/,
    () => emoji,
  );
  src = src.replace(
    /var escapeHtml = uiModule\.esc;/,
    () =>
      `var escapeHtml = (v) => String(v ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');`,
  );
  const url = 'data:text/javascript;base64,' + Buffer.from(src).toString('base64');
  return import(url);
}

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
