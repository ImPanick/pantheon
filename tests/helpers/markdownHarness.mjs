// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B882` — one loader for `static/js/markdown.js` under node.
//
// `markdown.js` is a browser ES module with six relative imports. A test that
// wants the real renderer cannot `import` it: `ui.js` pulls six more modules
// and a DOM. So four separate test files each read the source, replaced its
// imports with inlined copies of the modules they named, base64'd the result
// into a `data:` URL and imported that. Three were Python
// (`test_markdown_lazy_lib_loading_js.py`, `test_markdown_rendering_js.py`,
// `test_copy_message_strips_thinking_js.py`) and the fourth was
// `tests/streaming/markdownHarness.mjs`, under node's own test runner.
//
// **The cost, measured.** `B872` added ONE import line to `markdown.js` and
// turned fourteen tests red across two files that have nothing to do with
// Mermaid, each needing the same thirteen lines pasted in again — and the
// `.mjs` copy was missed, so the whole streaming suite failed to import with
// `ERR_UNSUPPORTED_RESOLVE_REQUEST: Failed to resolve module specifier
// "./markdown/mermaidTheme.js" from "data:text/javascript;base64,…"`. That
// file's own comments had already recorded the same sentence twice, under
// `B250` and `P5-06`, each time fixed by pasting in one more inline.
//
// **Why this is not the fifth copy.** The old inlines were a LIST: five
// specifiers, each named in a regex, each with its own hand-written
// `export`-stripping. A sixth import meant a sixth entry, in four places. This
// resolves `markdown.js`'s import statements by reading them — whatever they
// are — and inlines each module's real source, recursively. Adding an import
// to `markdown.js` needs no edit here and none in any test file;
// `tests/test_one_markdown_harness.py` proves that by adding one and loading
// the renderer.
//
// **How both a Python loader and an `.mjs` one reach it.** The harness is
// JavaScript, because the thing it does is JavaScript and a Python copy of it
// would be the row again in another language. The `.mjs` tests `import` it.
// The Python tests build a node script that `import`s it by `file://` URL —
// `tests/helpers/markdown_harness.py` writes that one line — so there is one
// implementation and two spellings of the same `import`.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO = path.resolve(HERE, '..', '..');

export const MARKDOWN_JS = path.join(REPO, 'static/js/markdown.js');

// `ui.js` is the one import that cannot be inlined: it imports six modules and
// touches the DOM at load. `markdown.js` uses exactly three things from it —
// `uiModule.esc` at module top level and `showToast`/`showError` behind `?.` —
// so the stand-in is an object with the SHIPPED escaper in it. `B866` moved
// that escaper into `static/js/util/escapeHtml.js`, a file that imports
// nothing, precisely so a module which cannot afford `ui.js` can still have the
// real one; this is that case. It also retires the fourth copy of the
// five-character escaper `B874` is about — the renderer under test now escapes
// the way the browser escapes, because it is the same function.
const UI_STUB = (repo) => `
${stripExports(fs.readFileSync(path.join(repo, 'static/js/util/escapeHtml.js'), 'utf8'))}
const uiModule = { esc, showToast: () => {}, showError: () => {} };
`;

const STUBS = {
  './ui.js': UI_STUB,
};

/** Every top-level `import … from '…'` statement, with its specifier. */
export function importStatements(source) {
  const out = [];
  const re = /^import\s+(?:[\s\S]*?\s+from\s+)?['"]([^'"]+)['"]\s*;?[ \t]*$/gm;
  let m;
  while ((m = re.exec(source)) !== null) out.push({ text: m[0], spec: m[1] });
  return out;
}

/**
 * A module's source with its `export` keywords removed, so it can be pasted
 * into another module's body.
 *
 * `export default …;` goes entirely — nothing inlined here is imported by its
 * default binding, and two defaults in one module is a syntax error, which is
 * the thing `P5-06` and `B250` each rediscovered. `export const`/`function`/
 * `class`/`let`/`var` lose the keyword and keep the declaration, so the name
 * is in scope where the import used to be. `export { a, b };` goes: the names
 * are already declared.
 */
export function stripExports(source) {
  return source
    .replace(/^export default\s+\{[\s\S]*?^\};[ \t]*$/m, '')
    .replace(/^export default\s+[\s\S]*?;[ \t]*$/m, '')
    .replace(/^export\s+\{[^}]*\}\s*;?[ \t]*$/gm, '')
    .replace(/^export\s+(?=(?:async\s+)?(?:const|let|var|function|class)\b)/gm, '');
}

/**
 * `markdown.js`, with every relative import replaced by the module it names.
 *
 * Recursive, so a module that is itself inlined and has its own relative
 * imports is handled without anybody editing anything. Each module is inlined
 * once; a second importer of the same specifier gets the empty string, because
 * the declarations are already in the file.
 */
export function bundle(entry = MARKDOWN_JS, { stubs = STUBS, repo = REPO } = {}) {
  const seen = new Set();

  function read(file) {
    let src = fs.readFileSync(file, 'utf8');
    const dir = path.dirname(file);
    for (const { text, spec } of importStatements(src)) {
      if (!spec.startsWith('.')) continue;          // bare specifiers: node resolves them
      let replacement;
      if (Object.prototype.hasOwnProperty.call(stubs, spec)) {
        const stub = stubs[spec];
        replacement = typeof stub === 'function' ? stub(repo) : stub;
      } else {
        const resolved = path.resolve(dir, spec);
        replacement = seen.has(resolved) ? '' : stripExports(read(resolved));
      }
      src = src.replace(text, () => replacement);
    }
    seen.add(file);
    return src;
  }

  return read(entry);
}

/** `bundle()` as a `data:` URL node can `import()`. */
export function bundleUrl(entry = MARKDOWN_JS, options = undefined) {
  return 'data:text/javascript;base64,'
    + Buffer.from(bundle(entry, options)).toString('base64');
}

/**
 * Import the real renderer. Installs nothing — the caller's DOM stub is its
 * own, and the three Python loaders each have a different one.
 */
export function importMarkdown(entry = MARKDOWN_JS, options = undefined) {
  return import(bundleUrl(entry, options));
}

/**
 * The smallest browser `markdown.js` loads against: a `window`, a `document`
 * that can make one `<template>`, and a `MutationObserver`. Callers that need
 * more (the lazy-library tests need an injectable `<head>`) install their own
 * and never call this.
 */
export function installMarkdownDom() {
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
}

/** The streaming suite's entry point since `B250`: globals, then the module. */
export async function loadMarkdown() {
  installMarkdownDom();
  return importMarkdown();
}
