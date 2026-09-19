// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B335`. Runs the REAL vendored `static/lib/mermaid.min.js` through the same
// `initialize()` call `static/js/markdown.js` makes, reads the config back, and
// parses the diagram grammars a chat message can contain.
//
// The config is READ BACK out of `mermaid.mermaidAPI.getConfig()`, which is the
// part that makes this a measurement: a key a new major silently stopped
// honouring comes back as a different value rather than as an error. That is
// how the `layout` default moving from `dagre` to `elk` in Mermaid 12.0.0 was
// measured rather than read off a changelog. It also catches a theme NAME that
// stopped existing — `initialize({theme:'light'})` is accepted in silence and
// draws `default`, and the only way to see that is that the variables come
// back as `default`'s.
//
// **`B872` changed how the config gets here, and the change was the price of
// the row.** It used to be lifted out of `markdown.js` with
//
//     /window\.mermaid\.initialize\(\s*(\{[^}]*\})\s*\)/   →   new Function('return ' + literal)
//
// which reads a *literal* and nothing else: the moment `markdown.js` computed
// its config instead of writing it out — which is exactly what `B872` needed,
// because four of the sixteen palettes are light and the literal said
// `theme: 'dark'` — the regex matched nothing and this harness bailed
// ANCHOR-MISSING. So the harness had to learn to read a computed config first.
//
// It now IMPORTS `static/js/markdown/mermaidTheme.js` and CALLS
// `applyMermaidTheme(mermaid, scheme)` — the same function `ensureMermaid`
// calls, against the same bundle, for each `color-scheme` the product can be
// in. That is strictly stronger than the regex was: the old version proved a
// literal parsed, this one proves the shipped decision function produces a
// config this Mermaid honours. It cost one import and the `schemes` block
// below; what made it affordable is that `mermaidTheme.js` has no imports and
// no DOM, so it loads under a bare node with none of the shims above.
//
// `markdown.js` itself is NOT imported here — it reaches `HTMLInputElement`
// through `ui.js` before its first statement runs, which no shim this file
// could hold would fix. That `ensureMermaid` really calls this function is
// driven in `tests/test_markdown_lazy_lib_loading_js.py`, where the module is
// loaded for real and `initialize` is watched.
//
// WHAT THIS DOES NOT COVER, said plainly: `mermaid.run()` and `mermaid.render()`
// rasterise through d3 and need `getBBox`, a real stylesheet and a live SVG
// tree — a browser, not a shim. So this harness reaches configuration and
// grammar and stops there. A regression in SVG layout would not be caught here,
// which is exactly why `B423` files Mermaid 12.0.0 rather than taking it: its
// headline change is how the layout comes out.
//
// The library is evaluated with `vm.runInThisContext`, not `require`: mermaid's
// bundle ends with `globalThis["mermaid"] = globalThis.__esbuild_esm_mermaid_nm
// ["mermaid"].default`, and `__esbuild_esm_mermaid_nm` is a top-level `var`.
// Under a `<script>` tag that is a global; under `require` it is module-local,
// so requiring the file throws on the last line. The browser's semantics are
// the ones under test.
//
//     node tests/harness/mermaid_diagram_parse.js [extra-cases.json]
//
// `P8-34` added the optional argument: a JSON file of `{name: diagramText}`
// whose entries are parsed **in addition to** the fixed cases below, never
// instead of them. It exists so the Workflow diagram this product generates is
// checked against the library that will actually draw it, rather than against
// a second opinion about Mermaid's grammar written in a test.
//
// Prints one line of JSON.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const url = require('node:url');

const ROOT = path.join(__dirname, '..', '..');
const LIB = path.join(ROOT, 'static', 'lib', 'mermaid.min.js');
const THEME_MOD = path.join(ROOT, 'static', 'js', 'markdown', 'mermaidTheme.js');

function bail(why) {
  console.log(JSON.stringify({ ok: false, error: 'ANCHOR-MISSING: ' + why }));
  process.exit(2);
}

if (!fs.existsSync(LIB)) bail(LIB);

// ── The smallest DOM the bundle will load against ─────────────────────────
class El {
  constructor(tag) {
    this.nodeName = String(tag).toUpperCase();
    this.tagName = this.nodeName;
    this.nodeType = 1;
    this.style = {};
    this.childNodes = [];
    this.attributes = {};
    this._html = '';
  }
  set innerHTML(v) { this._html = String(v); }
  get innerHTML() { return this._html; }
  appendChild(c) { this.childNodes.push(c); return c; }
  insertBefore(c) { this.childNodes.push(c); return c; }
  removeChild(c) {
    const i = this.childNodes.indexOf(c);
    if (i >= 0) this.childNodes.splice(i, 1);
    return c;
  }
  remove() {}
  setAttribute(k, v) { this.attributes[k] = v; }
  getAttribute(k) { return this.attributes[k]; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  getElementsByTagName() { return []; }
  cloneNode() { return new El(this.nodeName); }
  addEventListener() {}
  removeEventListener() {}
  getBoundingClientRect() {
    return { width: 0, height: 0, x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0 };
  }
}

const doc = {
  // `P8-34`. DOMPurify — which the bundle carries and mermaid runs every label
  // through after the grammar accepts it — bails out with
  // `isSupported = false` and returns an object with **no `sanitize`** unless
  // `document.nodeType === 9`. Without this line every case with a label in it
  // came back `ao.sanitize is not a function`, so this harness could only ever
  // parse diagrams whose nodes had no text: `graph TD; A-->B;` passed and
  // `flowchart TD\n n0[hi]` did not.
  nodeType: 9,
  createElement: (t) => new El(t),
  createElementNS: (ns, t) => new El(t),
  createTextNode: (t) => ({ nodeType: 3, data: String(t) }),
  body: new El('body'),
  head: new El('head'),
  documentElement: new El('html'),
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => null,
  getElementsByTagName: () => [],
  addEventListener() {},
  removeEventListener() {},
};
doc.implementation = { createHTMLDocument: () => doc };

global.window = global;
global.self = global;
global.document = doc;
global.addEventListener = function () {};
global.removeEventListener = function () {};
global.dispatchEvent = function () { return true; };
global.navigator = { userAgent: 'node', platform: 'linux', language: 'en' };
global.location = {
  href: 'http://pantheon.test/', protocol: 'http:', host: 'pantheon.test',
  hostname: 'pantheon.test', port: '', pathname: '/', search: '', hash: '',
  origin: 'http://pantheon.test',
};
global.Element = El;
global.HTMLElement = El;
global.Node = El;
global.DOMParser = class { parseFromString() { return doc; } };
global.XMLSerializer = class { serializeToString() { return ''; } };
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
global.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} });
global.requestAnimationFrame = (f) => setTimeout(f, 0);
global.MutationObserver = class { observe() {} disconnect() {} };

try {
  vm.runInThisContext(fs.readFileSync(LIB, 'utf8'), { filename: LIB });
} catch (e) {
  console.log(JSON.stringify({ ok: false, stage: 'load', error: String((e && e.message) || e) }));
  process.exit(0);
}
const mermaid = global.mermaid;
if (!mermaid) {
  console.log(JSON.stringify({ ok: false, error: 'the bundle no longer publishes window.mermaid' }));
  process.exit(0);
}

// ── The real call site's config, computed by the module that computes it ──
if (!fs.existsSync(THEME_MOD)) bail(THEME_MOD);

// The theme variables a diagram is actually read by. Mermaid's flowchart
// stylesheet is `.node rect, .node circle, … { fill: ${mainBkg}; stroke:
// ${nodeBorder} }` and `.label { color: ${nodeTextColor || textColor} }`, so
// these five ARE the ink: the arrows, the box outlines, the box fill and the
// two texts. Reported rather than asserted here — this file has no opinion
// about what colour is legible, it only says what Mermaid decided.
const INK = [
  'lineColor', 'nodeBorder', 'mainBkg', 'nodeTextColor', 'textColor',
  'edgeLabelBackground', 'background', 'primaryTextColor',
];

const out = { ok: true, callSiteConfig: null, api: {}, config: null, schemes: {}, parse: {} };
out.api = {
  initialize: typeof mermaid.initialize,
  run: typeof mermaid.run,
  render: typeof mermaid.render,
  parse: typeof mermaid.parse,
};

(async () => {
  let theme;
  try {
    theme = await import(url.pathToFileURL(THEME_MOD).href);
  } catch (e) {
    bail('static/js/markdown/mermaidTheme.js did not load: ' + String((e && e.message) || e));
  }
  for (const name of ['applyMermaidTheme', 'mermaidConfig', 'mermaidTheme']) {
    if (typeof theme[name] !== 'function') bail('mermaidTheme.js no longer exports ' + name + '()');
  }

  // Every `color-scheme` the product can be in, through the shipped decision.
  // `''` is the fourth case on purpose: `documentScheme()` answers it before
  // any palette has been applied, and a first-paint diagram must still get a
  // theme rather than Mermaid's default.
  for (const scheme of ['dark', 'light', 'unset']) {
    const asked = scheme === 'unset' ? '' : scheme;
    let applied;
    try {
      applied = theme.applyMermaidTheme(mermaid, asked);
    } catch (e) {
      out.ok = false;
      out.error = 'applyMermaidTheme(' + JSON.stringify(asked) + ') threw: '
        + String((e && e.message) || e);
      console.log(JSON.stringify(out));
      return;
    }
    // Read back, don't assume. A key that stopped being honoured comes back
    // different; a default that moved under us comes back different too; and
    // a theme NAME that stopped existing comes back with another theme's ink.
    const cfg = mermaid.mermaidAPI.getConfig();
    const vars = cfg.themeVariables || {};
    const ink = {};
    for (const k of INK) ink[k] = vars[k] === undefined ? null : vars[k];
    out.schemes[scheme] = {
      applied,
      theme: cfg.theme,
      securityLevel: cfg.securityLevel,
      startOnLoad: cfg.startOnLoad,
      layout: cfg.layout,
      look: cfg.look,
      ink,
    };
  }

  // The two keys this file has always answered, kept pointing at the dark
  // scheme — the one the pinned literal used to hold — so a caller that only
  // ever asked "does the app's config survive initialize()" still gets it.
  out.callSiteConfig = out.schemes.dark.applied;
  out.config = (({ theme: t, securityLevel, startOnLoad, layout, look }) =>
    ({ theme: t, securityLevel, startOnLoad, layout, look }))(out.schemes.dark);

  const CASES = {
    flowchart: 'graph TD; A-->B;',
    sequence: 'sequenceDiagram\n  Alice->>Bob: hi',
    er: 'erDiagram\n  A ||--o{ B : has',
    // `B335`'s differential: shapes added in Mermaid 11.17.0. On 11.16.1 these
    // come back as `No such shape: <name>.`
    personShape: 'flowchart TD\n  A@{ shape: person }\n  A --> B',
    folderShape: 'flowchart TD\n  A@{ shape: folder }',
    browserShape: 'flowchart TD\n  A@{ shape: browser }',
    // Not a diagram at any version: has to be rejected, not accepted.
    broken: 'graph TD; A--%%>B ??? [',
  };
  // `P8-34`. Extra cases from a file, merged after the fixed ones so a name
  // collision cannot quietly replace one of them.
  const extraPath = process.argv[2];
  if (extraPath) {
    let extra;
    try {
      extra = JSON.parse(fs.readFileSync(extraPath, 'utf8'));
    } catch (e) {
      out.ok = false;
      out.error = 'could not read the extra cases at ' + extraPath + ': ' + String(e && e.message || e);
      console.log(JSON.stringify(out));
      return;
    }
    for (const [name, text] of Object.entries(extra)) {
      if (name in CASES) {
        out.ok = false;
        out.error = 'extra case ' + name + ' collides with a fixed one';
        console.log(JSON.stringify(out));
        return;
      }
      CASES[name] = String(text);
    }
  }

  for (const [name, text] of Object.entries(CASES)) {
    try {
      const r = await mermaid.parse(text);
      out.parse[name] = { ok: true, diagramType: (r && r.diagramType) || null };
    } catch (e) {
      out.parse[name] = {
        ok: false,
        error: String((e && e.message) || e).split('\n')[0].slice(0, 120),
      };
    }
  }
  console.log(JSON.stringify(out));
})();
