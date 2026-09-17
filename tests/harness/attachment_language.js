// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B161`. What the browser calls a file, from the modules that ship.
//
// Two things need driving and they are different claims. The first is that the
// shared derivation answers what the server's does — that is `attachmentLanguage.js`
// evaluated as a real ES module, with nothing stubbed, because it is a leaf with
// no imports and stubbing it would be testing the stub.
//
// The second is that the import paths actually ASK it. Each of those used to
// hold an extension map of its own, so "the shared module is right" says
// nothing about what a person gets when they drop a file on the library. The
// `library` mode lifts `libraryImportFiles` — the biggest of the four, 40
// entries before this row — and runs it against a stubbed `fetch`, reporting the
// `language` each POSTed document was actually given. `Law 20`: the answer is
// read off the request, not off the source line that built it.
//
// Usage:
//   node attachment_language.js answer  '<names-json-array>'
//   node attachment_language.js library '<file-names-json-array>'
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'documentLibrary.js');
const MODULE = path.join(__dirname, '..', '..', 'static', 'js', 'attachmentLanguage.js');

const source = fs.readFileSync(SRC, 'utf8');
// The real shared module, inlined rather than stubbed. `export` is stripped so
// it can be evaluated inside a function body; nothing else about it changes.
const shared = fs.readFileSync(MODULE, 'utf8').replace(/^export\s+/gm, '');

function slice(startMark, endMark, label) {
  const from = source.indexOf(startMark);
  if (from < 0) {
    console.error(`ANCHOR-MISSING: ${label} start (${startMark})`);
    process.exit(2);
  }
  const to = source.indexOf(endMark, from);
  if (to < 0 || to <= from) {
    console.error(`ANCHOR-MISSING: ${label} end (${endMark})`);
    process.exit(2);
  }
  return source.slice(from, to);
}

// `CONVERTED_TO` is module-level and `libraryImportFiles` reads it, so the two
// are lifted together — the whole question for a `.docx` is which of the two
// answers wins.
const converted = slice('  const CONVERTED_TO = {',
                        '  async function libraryImportFiles(fileList) {',
                        'CONVERTED_TO');
// `B233` added a second module-level register `libraryImportFiles` reads: the
// office formats the SERVER extracts and this browser has no converter for.
// Lifted the same way and derived from the same generated `OFFICE_EXTS` the
// module imports, so this harness never spells the set itself.
const registers = slice('  const CLIENT_CONVERTED_EXTS = new Set(',
                        '  /** Read file contents',
                        'SERVER_EXTRACTED_EXTS');
// `OFFICE_EXTS` itself needs nothing extra here: `shared` above already inlines
// the whole of `attachmentLanguage.js`, generated registers and all, which is
// exactly where `documentLibrary.js` imports it from.
const importer = slice('  async function libraryImportFiles(fileList) {',
                       '  export function openLibrary(opts) {',
                       'libraryImportFiles');

const mode = process.argv[2] || 'answer';

if (mode === 'answer') {
  const names = JSON.parse(process.argv[3] || '[]');
  const api = new Function(`
    ${shared}
    return { attachmentLanguage, documentLanguage, isProseLanguage,
             LANGUAGE_ALIASES, PROSE_LANGUAGES: [...PROSE_LANGUAGES] };
  `)();
  console.log(JSON.stringify({
    aliases: api.LANGUAGE_ALIASES,
    prose: api.PROSE_LANGUAGES,
    answers: Object.fromEntries(names.map((n) => [n, {
      language: api.attachmentLanguage(n),
      prose: api.isProseLanguage(api.attachmentLanguage(n)),
      document: api.documentLanguage(n),
    }])),
  }));
} else if (mode === 'library') {
  const names = JSON.parse(process.argv[3] || '[]');
  const posted = [];
  const files = names.map((n) => ({
    name: n,
    arrayBuffer: async () => new ArrayBuffer(0),
  }));
  const deps = {
    API_BASE: '',
    uiModule: { showToast() {}, showError() {} },
    libraryFetch: async () => {},
    ensureXLSX: async () => {},
    ensureMammoth: async () => {},
    // The reader is stubbed because reading bytes is not this question; what a
    // file's CONTENT becomes is `readFileContent`'s own business and the row is
    // about the label beside it.
    readFileContent: async (f) => `content of ${f.name}`,
    htmlToMarkdown: (h) => h,
    window: { XLSX: { read: () => ({ SheetNames: ['S1'], Sheets: { S1: {} } }),
                      utils: { sheet_to_csv: () => 'a,b\n1,2' } } },
    FormData: function FormDataStub() { this.append = () => {}; },
    fetch: async (url, opts) => {
      let body = {};
      try { body = JSON.parse(opts.body); } catch (_) {}
      posted.push({ url: String(url), title: body.title ?? null,
                    language: body.language === undefined ? '<absent>' : body.language });
      return { ok: true, json: async () => ({ id: 1 }) };
    },
  };
  const ks = Object.keys(deps);
  const run = new Function(...ks, `
    ${shared}
    ${registers}
    ${converted}
    ${importer.replace(/^  export function /gm, '  function ')}
    return libraryImportFiles;
  `)(...ks.map((k) => deps[k]));
  run(files).then(() => {
    console.log(JSON.stringify(names.map((n, i) => ({ name: n, ...posted[i] }))));
  });
} else {
  console.error(`unknown mode: ${mode}`);
  process.exit(2);
}
