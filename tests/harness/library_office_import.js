// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B233`. Runs the REAL per-file branch of the library import out of
// `static/js/documentLibrary.js` over one dropped file, and reports where the
// bytes went: which endpoint, and — when the branch read the file in the
// browser — what it read it as.
//
// The defect is exactly this branch's fall-through. `readFileContent` handled
// `.xlsx/.xls/.ods` and `.docx` and nothing else, so a `.doc` reached
// `FileReader.readAsText` and its OLE2 bytes were POSTed to `/api/document` as
// `content`, under `language: 'markdown'`. Reading the source cannot show that:
// the branch that is missing is not written down anywhere. Driving it can.
//
// `B400` moved that branch out of `libraryImportFiles`' loop into
// `importFileAsDocuments` — the one per-file function the Library's Import and
// the Documents panel's *Import from device* both call — so this lifts that
// function, with `CONVERTED_TO` above it, and calls it. What it reports is
// unchanged.
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'documentLibrary.js');
const source = fs.readFileSync(SRC, 'utf8');

const START = '  const CONVERTED_TO = {';
const END = '  async function libraryImportFiles(fileList';
const from = source.indexOf(START);
const to = source.indexOf(END, from);
if (from < 0 || to < 0 || to <= from
    || source.slice(from, to).indexOf('async function importFileAsDocuments(') < 0) {
  console.error('ANCHOR-MISSING: the library import branch moved');
  process.exit(2);
}
const block = source.slice(from, to);

const name = process.argv[2] || 'memo.doc';
// The first bytes of a real OLE2 compound file, which is what a legacy `.doc`
// is. Decoded as text they are control characters, which is the whole row.
const OLE2 = '\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\x00\x00\x00\x00';
const BODIES = { '.doc': OLE2, '.odt': 'PK\x03\x04', '.pptx': 'PK\x03\x04',
                 '.epub': 'PK\x03\x04', '.txt': 'plain words\n' };

const ext = name.slice(name.lastIndexOf('.')).toLowerCase();
const body = BODIES[ext] !== undefined ? BODIES[ext] : 'plain words\n';

const posts = [];
const API_BASE = '';
const file = { name, __body: body, arrayBuffer: async () => new ArrayBuffer(8) };
// The two client-side converters this module genuinely has, stubbed at their
// library boundary so the `Law 1` guards below assert that a `.xlsx` and a
// `.docx` still take the path they took before this row — client-side, never
// posted as a file.
global.window = { XLSX: {
  read: () => ({ SheetNames: ['Sheet1'], Sheets: { Sheet1: {} } }),
  utils: { sheet_to_csv: () => 'a,b\n1,2\n' },
} };
// The language is not this harness's question (`B161`'s harness asks it).
const documentLanguage = () => 'markdown';
const ingestKindFromName = () => null;

global.fetch = async (url, opts) => {
  let payload = null;
  if (opts && typeof opts.body === 'string') { try { payload = JSON.parse(opts.body); } catch (_) {} }
  posts.push({ url, form: !(opts && typeof opts.body === 'string'), payload });
  return { ok: true, status: 200, json: async () => ({ id: 'doc-1' }) };
};
class FormData { constructor() { this._p = []; } append(k, v) { this._p.push(k); } }
global.FormData = FormData;

// The real `readFileContent` is what decides how a local file is read. It is
// asynchronous and DOM-bound (`FileReader`, mammoth, SheetJS), so the two
// converters the browser genuinely has are stubbed and the PLAIN-TEXT arm — the
// one the row is about — is the real thing it does: decode the bytes as text.
async function readFileContent(f) {
  if (/\.(xlsx|xls|ods)$/i.test(f.name)) return 'a,b\n1,2\n';
  if (/\.docx$/i.test(f.name)) return '# mammoth markdown\n';
  return f.__body;
}
async function ensureXLSX() {}

(async () => {
  const lift = new Function(
    'API_BASE', 'readFileContent', 'ensureXLSX', 'fetch', 'FormData',
    'SERVER_EXTRACTED_EXTS', 'window', 'documentLanguage', 'ingestKindFromName',
    '"use strict";\n' + block + '\nreturn importFileAsDocuments;');
  // The two register constants are LIFTED OUT OF THE MODULE, not supplied:
  // handing the block a set this harness computed would test the harness.
  // `OFFICE_EXTS` comes from the generated register in `attachmentLanguage.js`
  // the same way the module imports it.
  const OFFICE = new Set(JSON.parse(process.env.OFFICE_EXTS_JSON || '[]'));
  const CSTART = "  const CLIENT_CONVERTED_EXTS";
  const CEND = "  /** Read file contents";
  const cf = source.indexOf(CSTART);
  const ct = source.indexOf(CEND, cf);
  if (cf < 0 || ct <= cf) {
    console.error('ANCHOR-MISSING: SERVER_EXTRACTED_EXTS moved');
    process.exit(2);
  }
  const SERVER = new Function('OFFICE_EXTS',
    source.slice(cf, ct) + '\nreturn SERVER_EXTRACTED_EXTS;')(OFFICE);
  let imported = 0;
  try {
    const importFileAsDocuments = lift(API_BASE, readFileContent, ensureXLSX, global.fetch,
                                       FormData, SERVER, global.window, documentLanguage,
                                       ingestKindFromName);
    // The library imports from All documents here, so there is no folder.
    const made = await importFileAsDocuments(file, { folder: null });
    imported = made.length ? 1 : 0;
  } catch (e) {
    console.log(JSON.stringify({ error: String(e && e.message || e), posts }));
    process.exit(0);
  }
  console.log(JSON.stringify({
    imported,
    endpoints: posts.map(p => p.url),
    // What was sent as the document's stored text, when anything was.
    contents: posts.map(p => (p.payload && p.payload.content) || null),
    languages: posts.map(p => (p.payload && p.payload.language) || null),
    postedAsFile: posts.map(p => p.form),
  }));
})();
