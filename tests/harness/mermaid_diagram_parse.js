// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B335`. Runs the REAL vendored `static/lib/mermaid.min.js` through the same
// `initialize()` call `static/js/markdown.js` makes, reads the config back, and
// parses the diagram grammars a chat message can contain.
//
// `markdown.js:93` is
//
//     window.mermaid.initialize({ startOnLoad: false, theme: 'dark',
//                                 securityLevel: 'loose' })
//
// and `markdown.js:1002` is `mermaid.run({ nodes })`. The config object is
// lifted out of `markdown.js` rather than copied (`Law 13`) and then READ BACK
// out of `mermaid.mermaidAPI.getConfig()`, which is the part that makes this a
// measurement: a key a new major silently stopped honouring comes back as a
// different value rather than as an error. That is how the `layout` default
// moving from `dagre` to `elk` in Mermaid 12.0.0 was measured rather than read
// off a changelog.
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
//     node tests/harness/mermaid_diagram_parse.js
//
// Prints one line of JSON.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..', '..');
const LIB = path.join(ROOT, 'static', 'lib', 'mermaid.min.js');
const SRC = path.join(ROOT, 'static', 'js', 'markdown.js');

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

// ── The real call site's config ───────────────────────────────────────────
const source = fs.readFileSync(SRC, 'utf8');
const CALL = /window\.mermaid\.initialize\(\s*(\{[^}]*\})\s*\)/;
const found = source.match(CALL);
if (!found) bail('could not find window.mermaid.initialize({...}) in markdown.js');
let config;
try {
  config = new Function('return ' + found[1])();
} catch (e) {
  bail('the config literal in markdown.js did not evaluate: ' + e.message);
}

const out = { ok: true, callSiteConfig: config, api: {}, config: null, parse: {} };
out.api = {
  initialize: typeof mermaid.initialize,
  run: typeof mermaid.run,
  render: typeof mermaid.render,
  parse: typeof mermaid.parse,
};

(async () => {
  try {
    mermaid.initialize(config);
  } catch (e) {
    out.ok = false;
    out.error = 'initialize() rejected the app\'s config: ' + String((e && e.message) || e);
    console.log(JSON.stringify(out));
    return;
  }
  // Read back, don't assume. A key that stopped being honoured comes back
  // different; a default that moved under us comes back different too.
  const cfg = mermaid.mermaidAPI.getConfig();
  out.config = {
    theme: cfg.theme,
    securityLevel: cfg.securityLevel,
    startOnLoad: cfg.startOnLoad,
    layout: cfg.layout,
    look: cfg.look,
  };

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
