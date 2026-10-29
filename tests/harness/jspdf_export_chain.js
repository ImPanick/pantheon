// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B421`. Runs the fallback PDF's call site — lifted out of
// `static/js/document.js` — against the REAL vendored
// `static/lib/jspdf.umd.min.js`, and reports what jsPDF's own `html()` was
// handed and what it made of it.
//
// It replaces `html2pdf_export_chain.js` (`B334`), which drove the same span
// against `html2pdf.bundle.min.js`. That bundle is gone (`D-2026-10-29-02`
// §2): jsPDF 4.2.1, html2canvas 1.4.1 and DOMPurify 3.4.17 ship as their own
// published files, and `_rasterisePdf` calls
//
//     new jspdf.jsPDF(PDF_PAGE).html(container.outerHTML, { worker, margin,
//       width, windowWidth, autoPaging, html2canvas }).from(html).toPdf()
//
// The drawing itself needs a browser (html2canvas lays the page out), and
// `tests/test_the_fallback_pdf_is_jspdfs_own_with_its_links_in_a_browser.py`
// drives it there. What is asked here is everything up to the drawing, which
// is promise plumbing over plain objects: which branch of `from()` the app
// takes, whether jsPDF reads each option rather than storing it, and what the
// app's own helpers (`_plainStylesForPdfClone`, `_pdfLinkBoxes`,
// `_undrawableInPdf`, `_pdfFontsNeeded`) do with the inputs they are given.
//
//     node tests/harness/jspdf_export_chain.js
//
// Prints one line of JSON.
const fs = require('fs');
const path = require('path');

const LIB = path.join(__dirname, '..', '..', 'static', 'lib', 'jspdf.umd.min.js');
if (!fs.existsSync(LIB)) {
  console.log(JSON.stringify({ ok: false, error: 'ANCHOR-MISSING: ' + LIB }));
  process.exit(2);
}
const jspdf = require(LIB);

// ── The real call site, extracted ──────────────────────────────────────────
// Not a copy of the options: the span from `exportAsPdf` to `exportAsDocx` is
// lifted out of `document.js` and evaluated, so what reaches jsPDF below is
// what the app passes (`Law 13`).
const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'document.js');
const START = '  async function exportAsPdf() {';
const END = '  async function exportAsDocx() {';
const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END, from);
if (from < 0 || to < 0 || to <= from) {
  console.log(JSON.stringify({ ok: false, error: 'ANCHOR-MISSING: could not extract exportAsPdf from document.js' }));
  process.exit(2);
}
const span = source.slice(from, to);
// `B1675`: the clone keeps KaTeX's own sheet, named where `markdown.js` loads
// it — read from there rather than written here a second time.
const KATEX_CSS = (fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'js', 'markdown.js'), 'utf8')
  .match(/const KATEX_CSS = '([^']+)';/) || [])[1];
// `B1687`: `_pdfFontsNeeded` asks Inter's own table, which `document.js`
// imports from the module `scripts/build-pdf-font-coverage.mjs` writes. Its
// value is a JSON object, read from there and handed to the span as the
// import would be.
const COVERAGE_SRC = fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'js', 'pdfFontCoverage.js'), 'utf8');
const PDF_FONT_COVERAGE = JSON.parse(COVERAGE_SRC.slice(COVERAGE_SRC.indexOf('{', COVERAGE_SRC.indexOf('PDF_FONT_COVERAGE =')),
  COVERAGE_SRC.lastIndexOf('}') + 1));

const out = { ok: true, version: jspdf.jsPDF.version };

// ── The smallest DOM the call site touches ─────────────────────────────────
class El {
  constructor(tag) {
    this.nodeName = String(tag).toUpperCase();
    this.tagName = this.nodeName;
    this.nodeType = 1;
    this.style = { cssText: '' };
    this._html = '';
  }
  set innerHTML(v) { this._html = String(v); }
  get innerHTML() { return this._html; }
  get outerHTML() { return `<div style="${this.style.cssText}">${this._html}</div>`; }
  get textContent() { return this._html.replace(/<[^>]*>/g, ''); }
  // `B1674`: `_rasterisePdf` reads the labels of `markdown.js`'s emoji icons.
  querySelectorAll() { return []; }
}

function lift(textareaValue, win) {
  const textarea = { value: textareaValue };
  const doc = {
    getElementById: (id) => (id === 'doc-editor-textarea' ? textarea
      : id === 'doc-language-select' ? { value: 'plain' } : null),
    createElement: (t) => new El(t),
  };
  const ui = { toasts: [], errors: [] };
  const uiModule = { showToast: (m) => ui.toasts.push(m), showError: (m) => ui.errors.push(m) };
  const fns = new Function(
    'document', 'window', 'activeDocId', 'ensurePdfLibs', 'uiModule', 'markdownModule',
    '_getExportBaseName', 'printHtmlInFrame', 'PDF_FONT_COVERAGE',
    span + '\nreturn { _rasterisePdf, _pdfLinkBoxes, _plainStylesForPdfClone, _undrawableInPdf, _pdfFontsNeeded };'
  )(doc, win, 'doc-1', async () => {}, uiModule, { renderMath: async () => {}, KATEX_CSS },
    () => 'pantheon-export', async () => false, PDF_FONT_COVERAGE);
  return { fns, ui };
}

// ── 1. What the call site hands jsPDF ──────────────────────────────────────
// A real jsPDF instance whose `html()` is recorded and then answered by the
// real Worker up to (not including) the drawing; `save()` is recorded.
const recorded = { ctor: null, src: null, opts: null, fromArg: null, saved: null };
// jsPDF's constructor returns its own API object, so the recording is put on
// the instance rather than on a subclass.
function RecordingJsPDF(o) {
  const pdf = new jspdf.jsPDF(o);
  recorded.ctor = o;
  pdf.html = (src, opts) => {
    recorded.src = src;
    recorded.opts = opts;
    return { from: (s) => { recorded.fromArg = s; return { toPdf: async () => {} }; } };
  };
  pdf.save = (name) => { recorded.saved = name; };
  return pdf;
}
const site = lift('# heading\n\nbody text', { jspdf: { jsPDF: RecordingJsPDF }, location: { href: 'http://pantheon.test/' } });

site.fns._rasterisePdf().then(() => {
  const o = recorded.opts || {};
  out.callSite = {
    ctor: recorded.ctor,
    srcType: typeof recorded.src,
    src: recorded.src,
    fromIsSrc: recorded.fromArg === recorded.src,
    options: {
      worker: o.worker, margin: o.margin, width: o.width, windowWidth: o.windowWidth,
      autoPaging: o.autoPaging,
      html2canvas: o.html2canvas && Object.fromEntries(Object.entries(o.html2canvas)
        .map(([k, v]) => [k, typeof v === 'function' ? 'function' : v])),
    },
    saved: recorded.saved,
    errors: site.ui.errors,
    toasts: site.ui.toasts,
  };
  // ── 2. The real Worker, handed exactly those options ─────────────────────
  // `set()` is where an option is understood or quietly dropped: reading the
  // value back after it ran is the difference (`B334`'s trick).
  const pdf = new jspdf.jsPDF(recorded.ctor || {});
  const worker = pdf.html(recorded.src, Object.assign({}, o));
  return Promise.all(['margin', 'width', 'windowWidth', 'autoPaging', 'html2canvas', 'pageSize', 'jsPDF']
    .map((k) => worker.get(k))).then(([margin, width, windowWidth, autoPaging, h2c, pageSize, jsPDFopt]) => {
    out.worker = {
      margin, width, windowWidth, autoPaging,
      allowTaint: h2c && h2c.allowTaint,
      // `html()` hands html2canvas jsPDF's own canvas, whose 2D context
      // writes PDF operators: that is why the text is text.
      drawsIntoThePdf: !!(h2c && h2c.canvas && h2c.canvas === pdf.canvas),
      sameDocument: jsPDFopt === pdf,
      innerWidth: pageSize && pageSize.inner && pageSize.inner.width,
    };
  });
}).then(() => {
  // ── 3. The clone html2canvas reads (`B1322`, `B421`) ─────────────────────
  const onclone = recorded.opts && recorded.opts.html2canvas && recorded.opts.html2canvas.onclone;
  out.onclone = { type: typeof onclone };
  if (typeof onclone !== 'function') return;
  const removed = [];
  const head = { kids: [], appendChild(n) { this.kids.push(n); } };
  // An SVG clone the way html2canvas leaves one: the live page's computed
  // style copied inline, `oklab()` and `color(srgb …)` included.
  const decl = {
    color: 'oklab(0.81 -0.04 -0.03)',
    'border-block-start-color': 'oklab(0.81 -0.04 -0.03)',
    'background-color': 'color(srgb 0.6 0.87 0.95 / 0.05)',
    'box-shadow': 'none',
    'stroke-width': '2',
    'border-top-width': '0px',
    'outline-color': 'rgb(0, 0, 0)',
  };
  const style = {
    get length() { return Object.keys(decl).length; },
    item: (i) => Object.keys(decl)[i],
    getPropertyValue: (p) => decl[p] || '',
    removeProperty: (p) => { delete decl[p]; },
  };
  const svg = { tagName: 'svg', style };
  const linkEls = [];
  const clone = {
    querySelectorAll: (sel) => {
      if (sel.indexOf('stylesheet') >= 0) {
        const link = (href, name) => ({
          tagName: 'LINK', getAttribute: (a) => (a === 'href' ? href : null), remove() { removed.push(name); },
        });
        return [link('/static/style.css', 'link'), { tagName: 'STYLE', remove() { removed.push('style'); } },
          link(KATEX_CSS, 'katex')];
      }
      if (sel === '[style]') return [svg];
      return linkEls;
    },
    createElement: () => ({ textContent: '' }),
    head,
  };
  try {
    onclone(clone, null);
    out.onclone.removed = removed;
    out.onclone.katexSheet = KATEX_CSS || null;
    out.onclone.added = head.kids.length;
    out.onclone.rules = head.kids.length ? head.kids[0].textContent : '';
    out.onclone.svgKept = Object.keys(decl).sort();
  } catch (err) {
    out.onclone.error = String((err && err.message) || err);
  }
}).then(() => {
  // ── 4. `_pdfLinkBoxes`: html2pdf's link plugin, rebuilt ──────────────────
  const a = (href, rects) => ({ getAttribute: () => href, getClientRects: () => rects });
  const r = (left, top, width, height) => ({ left, top, width, height });
  const root = {
    getBoundingClientRect: () => r(100, 50, 718, 2000),
    querySelectorAll: () => [
      a('https://example.com/x', [r(120, 70, 60, 16)]),
      a('https://example.com/wraps', [r(600, 90, 200, 16), r(120, 106, 80, 16)]),
      a('#section-2', [r(120, 130, 40, 16)]),
      a('javascript:alert(1)', [r(120, 150, 40, 16)]),
      a('mailto:someone@example.com', [r(120, 170, 40, 16)]),
    ],
  };
  out.links = site.fns._pdfLinkBoxes(root, 0.25);
  // ── 5. What the built-in fonts cannot draw ──────────────────────────────
  // A zero-width space (KaTeX puts them in math) is invisible, so not named.
  out.undrawable = site.fns._undrawableInPdf('café “naïve” — ™ Привет 你好 🎉 €\u200b');
  // ── 6. Which faces a text fetches (`B1674`, `B1687`) ────────────────────
  // Each probe alone: every symbol `B1687` names, the two Inter lacks, an
  // emoji past U+FFFF, a variation selector, a private-use code point, and
  // one word of each script `B1674` named.
  out.needs = {};
  for (const probe of [...'™↔↕▶◀❤☀‼⁉↩✔⌚─', '🎉', '\ufe0f', '\ue0a0', 'שלום', 'Привет', 'Γειά', '你好',
    'café “naïve” — €']) {
    out.needs[probe] = site.fns._pdfFontsNeeded(probe);
  }
}).then(() => {
  console.log(JSON.stringify(out));
}, (err) => {
  out.ok = false;
  out.error = String((err && err.stack) || err);
  console.log(JSON.stringify(out));
});
