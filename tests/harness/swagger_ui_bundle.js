// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B335`. Loads the REAL vendored `static/lib/swagger-ui/swagger-ui-bundle.js`
// and reports the symbols FastAPI's generated `/docs` page names.
//
// `app.py:1120` builds that page with `get_swagger_ui_html(...)` pointed at the
// vendored files rather than at `cdn.jsdelivr.net` (`B212`), and the HTML it
// generates calls
//
//     SwaggerUIBundle({ url, dom_id, layout: "BaseLayout", presets: [
//         SwaggerUIBundle.presets.apis,
//         SwaggerUIBundle.SwaggerUIStandalonePreset ] })
//
// So `SwaggerUIBundle` and `SwaggerUIBundle.presets.apis` are the two things a
// version bump can take away, and a `/docs` that fails on them fails as a blank
// page with a console error, which nobody is watching. `SwaggerUIStandalonePreset`
// is `undefined` here ON PURPOSE and is reported rather than asserted: the
// standalone preset is a second 1.4 MB file this repository deliberately does
// not ship, and upstream FastAPI's own page against jsDelivr has the same hole
// (see `scripts/fetch-swagger-ui.py`). Reporting it is how that stays a
// decision instead of turning into a surprise.
//
// Nothing renders: the bundle is React and this is a shim. Loading it and
// reading its exported surface is the bound of what can be measured off a
// browser, and it is the part a bump breaks.
//
//     node tests/harness/swagger_ui_bundle.js
//
// Prints one line of JSON.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const LIB = path.join(__dirname, '..', '..', 'static', 'lib', 'swagger-ui',
                      'swagger-ui-bundle.js');
if (!fs.existsSync(LIB)) {
  console.log(JSON.stringify({ ok: false, error: 'ANCHOR-MISSING: ' + LIB }));
  process.exit(2);
}

class El {
  constructor(tag) {
    this.nodeName = String(tag).toUpperCase();
    this.tagName = this.nodeName;
    this.nodeType = 1;
    this.style = {};
    this.childNodes = [];
  }
  appendChild(c) { this.childNodes.push(c); return c; }
  removeChild(c) { return c; }
  setAttribute() {}
  getAttribute() { return null; }
  addEventListener() {}
  removeEventListener() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  getElementsByTagName() { return []; }
}

const doc = {
  createElement: (t) => new El(t),
  createElementNS: (ns, t) => new El(t),
  createTextNode: (t) => ({ nodeType: 3, data: String(t) }),
  createDocumentFragment: () => new El('fragment'),
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

global.window = global;
global.self = global;
global.document = doc;
global.addEventListener = function () {};
global.removeEventListener = function () {};
global.navigator = { userAgent: 'node', platform: 'linux' };
global.location = {
  href: 'http://pantheon.test/docs', protocol: 'http:', host: 'pantheon.test',
  hostname: 'pantheon.test', port: '', pathname: '/docs', search: '', hash: '',
  origin: 'http://pantheon.test',
};
global.Element = El;
global.HTMLElement = El;
global.Node = El;
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
global.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} });
global.requestAnimationFrame = (f) => setTimeout(f, 0);
global.MutationObserver = class { observe() {} disconnect() {} };

const out = { ok: true };
try {
  vm.runInThisContext(fs.readFileSync(LIB, 'utf8'), { filename: LIB });
} catch (e) {
  out.ok = false;
  out.stage = 'load';
  out.error = String((e && e.message) || e).slice(0, 200);
  console.log(JSON.stringify(out));
  process.exit(0);
}

const B = global.SwaggerUIBundle;
out.bundle = typeof B;
out.presets = B && B.presets ? Object.keys(B.presets) : null;
out.apisPreset = !!(B && B.presets && B.presets.apis);
out.plugins = B && B.plugins ? Object.keys(B.plugins).slice(0, 12) : null;
// Reported, not asserted — see the header.
out.standalonePreset = typeof (B && B.SwaggerUIStandalonePreset);
console.log(JSON.stringify(out));
