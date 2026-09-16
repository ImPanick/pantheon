// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B334`. Runs the REAL vendored `static/lib/html2pdf.bundle.min.js` through
// the same call `document.js` makes, and reports what the worker ended up
// holding.
//
// `document.js:9689` builds a detached `<div>`, fills it, and calls
//
//     window.html2pdf().set({ margin, filename, image, html2canvas, jsPDF })
//                      .from(container).save();
//
// That crosses jsPDF 2 -> 4 as of 2026-09-16, and an option key that silently
// stopped being read is exactly the kind of break that produces a PDF nobody
// looks at until a user does. So the chain is driven and the resulting `opt`
// and `prop` are printed: a renamed or dropped option shows up as a missing
// value rather than as a subtly wrong page.
//
// It also reports which branch `from()` took, which is the CVE-2026-22787
// question. `Worker.prototype.from` switches on the source's type: a string is
// wrapped with `createElement('div', {innerHTML: src})` — the sink — while an
// element is stored as-is. Both branches are exercised here, so the test can
// say "we take the element branch" as a measurement rather than by reading the
// call site.
//
// `save()` is never called: it rasterises through html2canvas and needs a real
// browser. Everything up to it is promise plumbing over plain objects, which is
// why a small DOM shim is enough.
//
//     node tests/harness/html2pdf_export_chain.js
//
// Prints one line of JSON.
const fs = require('fs');
const path = require('path');

const BUNDLE = path.join(__dirname, '..', '..', 'static', 'lib', 'html2pdf.bundle.min.js');
if (!fs.existsSync(BUNDLE)) {
  console.log(JSON.stringify({ ok: false, error: 'ANCHOR-MISSING: ' + BUNDLE }));
  process.exit(2);
}

// ── The smallest DOM the bundle will load against ──────────────────────────
// html2canvas reads `location.href` at module scope and jsPDF asks for
// `navigator`. Nothing here renders; an element is a bag of properties with an
// `innerHTML` accessor, because `innerHTML` is the one property whose value
// this harness exists to look at.
class El {
  constructor(tag) {
    this.nodeName = String(tag).toUpperCase();
    this.tagName = this.nodeName;
    this.nodeType = 1;
    this.style = {};
    this.className = '';
    this.childNodes = [];
    this._html = '';
  }
  set innerHTML(v) { this._html = String(v); }
  get innerHTML() { return this._html; }
  appendChild(c) { this.childNodes.push(c); return c; }
  removeChild(c) {
    const i = this.childNodes.indexOf(c);
    if (i >= 0) this.childNodes.splice(i, 1);
    return c;
  }
  getElementsByTagName() { return []; }
  setAttribute(k, v) { this[k] = v; }
  cloneNode() { return new El(this.nodeName); }
}

const doc = {
  createElement: (t) => new El(t),
  createElementNS: (ns, t) => new El(t),
  createTextNode: (t) => ({ nodeType: 3, data: String(t) }),
  body: new El('body'),
  head: new El('head'),
  documentElement: new El('html'),
  addEventListener() {}, removeEventListener() {},
};
global.document = doc;
global.window = global;
global.self = global;
global.navigator = { userAgent: 'node', platform: 'linux' };
global.location = {
  href: 'http://pantheon.test/', protocol: 'http:', host: 'pantheon.test',
  hostname: 'pantheon.test', port: '', pathname: '/', search: '', hash: '',
  origin: 'http://pantheon.test',
};
global.HTMLElement = El;
global.Element = El;
global.Node = El;
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
global.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} });
global.Image = class {};
global.XMLSerializer = class { serializeToString() { return ''; } };

const html2pdf = require(BUNDLE);
if (typeof global.window.html2pdf === 'undefined') global.window.html2pdf = html2pdf;

// ── The real call site, extracted and run ─────────────────────────────────
// Not a copy of the options: `exportAsPdf` is lifted out of `static/js/document.js`
// between two anchors and evaluated, so what reaches the bundle below is what
// the app actually passes. A hand-copied literal here would keep testing what
// the app used to do, and `Law 13` is the claim under test — one call site, one
// set of options, and the element branch rather than the string one.
const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'document.js');
const START = '  async function exportAsPdf() {';
const END = '  async function exportAsDocx() {';
const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END, from);
if (from < 0 || to < 0 || to <= from) {
  console.log(JSON.stringify({
    ok: false, error: 'ANCHOR-MISSING: could not extract exportAsPdf from document.js',
  }));
  process.exit(2);
}
const exportAsPdfSource = source.slice(from, to);

// An `<img>` whose src cannot load fires `onerror` as soon as it is parsed into
// a live tree, so removing `<script>` elements — which is all 0.10.2 did — never
// touched it.
const PAYLOAD = '<img src=x onerror="pantheonWasHere()"><b>kept</b>';

const out = {
  ok: true,
  exportsFunction: typeof global.window.html2pdf === 'function',
  callSite: null,
  element: null,
  string: null,
};

// The stubs `exportAsPdf` needs. Everything here is a fixture except
// `window.html2pdf`, which is the real bundle: the point is that the real call
// site reaches the real library.
const textarea = { value: '# heading\n\nbody text' };
const stubDocument = Object.create(doc);
stubDocument.getElementById = (id) => (
  id === 'doc-editor-textarea' ? textarea
    : id === 'doc-language-select' ? { value: 'plain' } : null
);
stubDocument.createElement = (t) => new El(t);

let fromArgument;
let recordedOptions;
const recordingHtml2pdf = () => {
  const worker = global.window.html2pdf();   // the real bundle
  return {
    set(opt) { recordedOptions = opt; worker.set(opt); return this; },
    from(src) { fromArgument = src; worker.from(src); return this; },
    save() { return this; },
  };
};

const runExport = new Function(
  'document', 'window', 'activeDocId', 'ensureHtml2Pdf', 'uiModule',
  'markdownModule', '_getExportBaseName',
  exportAsPdfSource + '\nreturn exportAsPdf();'
);

const el = new El('div');
el.innerHTML = '<p>hello</p>';

function finish() {
  console.log(JSON.stringify(out));
}

function driveCallSite() {
  return runExport(
    stubDocument,
    { html2pdf: recordingHtml2pdf },
    'doc-1',
    async () => {},
    { showToast() {}, showError(m) { out.callSite = { error: 'showError: ' + m }; } },
    { renderMath: async () => {} },
    () => 'pantheon-export'
  ).then(() => {
    out.callSite = {
      // What the app passed, not what this harness thinks it passes.
      options: recordedOptions,
      // The CVE-2026-22787 question, asked of the app rather than of a literal:
      // `from()` switches on the source's type, and a string takes the branch
      // that sets innerHTML. Reporting the type is how "we take the element
      // branch" becomes a measurement.
      fromType: typeof fromArgument,
      fromNodeName: fromArgument && fromArgument.nodeName,
      fromInnerHTML: fromArgument && fromArgument.innerHTML,
    };
  }, (err) => {
    out.callSite = { error: String((err && err.message) || err) };
  });
}

driveCallSite().then(function () {
  // Feed the bundle exactly what the call site produced, so the options under
  // test below are the app's rather than this file's.
  const OPTIONS = (out.callSite && out.callSite.options) || {};
  return global.window.html2pdf().set(OPTIONS).from(el).then(function () {
  out.element = {
    // `set()` normalises margin to a four-sided array; reading it back proves
    // the option was understood rather than merely stored.
    margin: this.opt.margin,
    filename: this.opt.filename,
    image: this.opt.image,
    html2canvasScale: this.opt.html2canvas && this.opt.html2canvas.scale,
    jsPDF: this.opt.jsPDF,
    // Identity, not equality: the element branch stores the very node it was
    // given. The string branch cannot produce this.
    srcIsTheElementWeGave: this.prop.src === el,
    srcInnerHTML: this.prop.src && this.prop.src.innerHTML,
  };
  }, function (err) {
    out.element = { error: String((err && err.message) || err) };
  });
}).then(function () {
  return global.window.html2pdf().from(PAYLOAD).then(function () {
    out.string = {
      reached: true,
      // What a string source leaves in the DOM the exporter will rasterise.
      // On 0.10.2 this is the payload, verbatim.
      srcInnerHTML: this.prop.src && this.prop.src.innerHTML,
    };
  }, function (err) {
    // 0.14.0 routes this through DOMPurify, which refuses to run without a real
    // document. Refusing is not the payload surviving, and that distinction is
    // the whole point of recording the branch rather than asserting on a throw.
    out.string = { reached: false, error: String((err && err.message) || err) };
  });
}).then(finish, function (err) {
  out.ok = false;
  out.error = String((err && err.message) || err);
  finish();
});
