// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B335`. Runs the REAL vendored `static/lib/katex/katex.min.js` through the
// same call `static/js/markdown.js` makes, and reports what came back.
//
// `markdown.js:804` is
//
//     katex.renderToString(raw, { displayMode, throwOnError: false })
//
// and `throwOnError: false` is the load-bearing half: with it, a formula KaTeX
// cannot parse comes back as `<span class="katex-error">` inside the message,
// and without it the call THROWS and takes `mdToHtml` down with it. Math in a
// chat message is written by a model or pasted by somebody else, so which of
// those two happens is a user-visible behaviour and not an edge case.
//
// The options are lifted out of `markdown.js` rather than copied, `Law 13`: a
// change to `throwOnError` at that one call site has to show up here.
//
// The library is evaluated with `vm.runInThisContext`, not `require`. KaTeX's
// UMD assigns to a top-level `var`, which becomes a property of the global
// object under a `<script>` tag and a module-local binding under `require` —
// so requiring it produces a file that "loads" and publishes no `katex`. That
// difference is the browser's, and this harness reproduces the browser's.
//
//     node tests/harness/katex_math_render.js
//
// Prints one line of JSON.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..', '..');
const LIB = path.join(ROOT, 'static', 'lib', 'katex', 'katex.min.js');
const SRC = path.join(ROOT, 'static', 'js', 'markdown.js');

function bail(why) {
  console.log(JSON.stringify({ ok: false, error: 'ANCHOR-MISSING: ' + why }));
  process.exit(2);
}

if (!fs.existsSync(LIB)) bail(LIB);

// The smallest DOM KaTeX asks for. It builds its HTML as a string and only
// touches `document` for the quirks-mode warning.
global.window = global;
global.self = global;
global.document = {
  compatMode: 'CSS1Compat',
  createElement: () => ({ style: {}, setAttribute() {}, appendChild() {} }),
  createTextNode: () => ({}),
  body: { appendChild() {}, removeChild() {} },
};

vm.runInThisContext(fs.readFileSync(LIB, 'utf8'), { filename: LIB });
const katex = global.katex;
if (!katex || typeof katex.renderToString !== 'function') {
  console.log(JSON.stringify({
    ok: false,
    error: 'the bundle no longer publishes window.katex.renderToString',
  }));
  process.exit(0);
}

// ── The real call site's options ──────────────────────────────────────────
// Not a copy: the object literal is read out of `markdown.js`, so the flags
// this harness hands KaTeX are the ones the app hands it.
const source = fs.readFileSync(SRC, 'utf8');
const CALL = /katex\.renderToString\(\s*raw\s*,\s*(\{[^}]*\})\s*\)/;
const found = source.match(CALL);
if (!found) bail('could not find katex.renderToString(raw, {...}) in markdown.js');
let options;
try {
  // `displayMode` is a variable at the call site; it is the caller's choice of
  // block or inline, and both are exercised below.
  options = new Function('displayMode', 'return ' + found[1]);
} catch (e) {
  bail('the options literal in markdown.js did not evaluate: ' + e.message);
}

const out = {
  ok: true,
  version: katex.version || null,
  callSiteOptions: options(false),
  render: {},
};

// Each case is `[name, tex, displayMode]`.
const CASES = [
  ['simple', 'E = mc^2', false],
  ['display', '\\int_0^\\infty e^{-x}\\,dx', true],
  ['aligned', '\\begin{aligned} a &= b \\\\ c &= d \\end{aligned}', false],
  // `B335`'s differentials. Both are valid LaTeX that KaTeX 0.16.22 refuses.
  ['bracedDelimiter', '\\bigl{(} x \\bigr{)}', false],
  ['soutInText', '\\text{\\sout{x}}', false],
  // Not valid at any version: this is the one that has to come back as an
  // error span rather than as a thrown exception.
  ['broken', '\\frac{', false],
];

for (const [name, tex, displayMode] of CASES) {
  try {
    const html = katex.renderToString(tex, options(displayMode));
    out.render[name] = {
      error: html.includes('katex-error'),
      // The two class names `static/style.css` hangs its own rules on. KaTeX
      // 0.18.0 renamed its INTERNAL classes (`base` -> `katex-base`); these
      // two are the ones an app is supposed to target and they did not move.
      katex: html.includes('class="katex"'),
      display: html.includes('class="katex-display"'),
      length: html.length,
    };
  } catch (e) {
    out.render[name] = { threw: String((e && e.message) || e).slice(0, 160) };
  }
}

console.log(JSON.stringify(out));
