// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B331`. Runs the REAL vendored `static/lib/mammoth.browser.min.js` over a
// real `.docx` and prints what came out.
//
// The document library's import path is
// `documentLibrary.js:1459 window.mammoth.convertToHtml({ arrayBuffer: buf })`
// on a file the user picked — which is to say, on a document somebody else
// authored. That is the feature, so a bump to the library that parses it is a
// bump to the thing standing between a hostile or merely malformed file and the
// app. "The file changed" is not evidence that still works; converting an
// actual document is.
//
// Deliberately not a stub and deliberately not an extraction: the point is the
// vendored bytes, so the bundle is loaded as the browser loads it. mammoth's
// browser build carries its own unzip and XML reader and needs no DOM, which is
// why this can be a plain `node` run rather than a sandbox.
//
// The conversion is driven through `readFileContent`, lifted out of
// `static/js/documentLibrary.js` between two anchors and evaluated — so the
// `{ arrayBuffer }` shape, the `.docx` extension test and the hand-off to
// `htmlToMarkdown` are the app's, not this file's. `htmlToMarkdown` itself is
// stubbed to return what it was given: it needs a `DOMParser` node does not
// have, and turning HTML into markdown is not what this row changed.
//
//     node tests/harness/mammoth_docx_import.js <path-to-.docx>
//
// Prints one line of JSON: { ok, html, messages } or { ok: false, error }.
const fs = require('fs');
const path = require('path');

const BUNDLE = path.join(__dirname, '..', '..', 'static', 'lib', 'mammoth.browser.min.js');
if (!fs.existsSync(BUNDLE)) {
  console.log(JSON.stringify({ ok: false, error: 'ANCHOR-MISSING: ' + BUNDLE }));
  process.exit(2);
}

// The bundle is a UMD wrapper that prefers `module.exports`; `window` is set
// because the app reaches it as `window.mammoth` and a build that stopped
// publishing there would break the call site without breaking `require`.
global.window = global;
global.self = global;

const mammoth = require(BUNDLE);
if (typeof global.window.mammoth === 'undefined') {
  global.window.mammoth = mammoth;
}

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'documentLibrary.js');
const START = '  async function readFileContent(file) {';
const END = '  async function libraryImportFiles(fileList) {';
const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END, from);
if (from < 0 || to < 0 || to <= from) {
  console.log(JSON.stringify({
    ok: false,
    error: 'ANCHOR-MISSING: could not extract readFileContent from documentLibrary.js',
  }));
  process.exit(2);
}

const messages = [];
const readFileContent = new Function(
  'window', 'ensureXLSX', 'ensureMammoth', 'htmlToMarkdown', 'FileReader',
  source.slice(from, to) + '\nreturn readFileContent;'
)(
  global.window,
  async () => {},
  async () => {},
  (html) => html,   // identity: the HTML mammoth produced is the result
  class { readAsText() { throw new Error('plain-text path not under test'); } }
);

const docxPath = process.argv[2];
if (!docxPath) {
  console.log(JSON.stringify({ ok: false, error: 'no .docx argument' }));
  process.exit(2);
}

const buf = fs.readFileSync(docxPath);
// `file.arrayBuffer()` in the browser hands over exactly the file's bytes;
// slicing on byteOffset/byteLength is what makes a Node Buffer behave that way
// rather than handing over the whole pooled allocation.
const arrayBuffer = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);

// An unhandled rejection is the failure shape 1.8.0 produced on a document with
// `mc:AlternateContent` and no `mc:Fallback`, and it kills the process without
// ever reaching `.catch`. Reporting it as a result rather than a crash is what
// lets the test say *which* document broke the import.
process.on('unhandledRejection', (err) => {
  console.log(JSON.stringify({
    ok: false, error: String((err && err.message) || err), unhandled: true,
  }));
  process.exit(0);
});

// The `File` the app is handed by an <input type="file">, reduced to the two
// members `readFileContent` touches.
const file = {
  name: path.basename(docxPath),
  arrayBuffer: async () => arrayBuffer,
};

// `messages` is not on `readFileContent`'s return value — it returns markdown —
// so the warnings mammoth produced are captured by wrapping the one call the
// extracted code makes.
const realConvertToHtml = global.window.mammoth.convertToHtml;
global.window.mammoth.convertToHtml = function (options) {
  return realConvertToHtml.call(this, options).then((result) => {
    for (const m of result.messages) messages.push({ type: m.type, message: m.message });
    return result;
  });
};

readFileContent(file)
  .then((html) => {
    console.log(JSON.stringify({ ok: true, html: html, messages: messages }));
  })
  .catch((err) => {
    console.log(JSON.stringify({ ok: false, error: String((err && err.message) || err) }));
  });
