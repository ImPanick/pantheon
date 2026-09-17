// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/attachmentLanguage.js

/**
 * `B161`. What the browser calls a file, answered once, from the server's rule.
 *
 * ── What was measured ───────────────────────────────────────────────────────
 * `B100` replaced the server's two hand-written lists — a 27-entry label map
 * and a separate 24-entry fence list, in one function, that had to agree with
 * each other — with one derivation in `src/document_processor.py`:
 *
 *     a suffix IS its language unless it is not a word
 *     LANGUAGE_ALIASES holds only the residues where that is false
 *     the fence is `language not in PROSE_LANGUAGES`
 *
 * The browser kept three copies of the OLD shape and they predate it:
 * `chat.js` (21 entries, on the import banner), `document.js` (36, on
 * "Import from device") and `documentLibrary.js` (40, on a library import).
 * None of them knew `.toml`, `.markdown`, `.kt`, `.swift` or `.h` — so a file
 * the composer labelled `toml` was offered as plain text by the document editor
 * it opened in, and `.markdown`, which the product loads as a markdown Document
 * everywhere else, imported as prose with no language at all.
 *
 * ── Why this is not a fourth copy ───────────────────────────────────────────
 * `Law 14`: the answer to three copies is not a fourth one written more
 * carefully. The client genuinely cannot import a Python register, so the two
 * registers below are **generated** from `src/document_processor.py` and
 * `.pantheon/check-attachment-language.py` fails the gate when they drift —
 * both the registers, byte for byte, AND the rule, by putting every alias key,
 * every ingestible extension and the structural cases through both
 * implementations and comparing the answers. A hand-copied list is what the
 * next language added would be missing from; a generated one with a checker is
 * a list that cannot be stale without something going red.
 *
 * The rule below is a second implementation of a *rule*, which is the cheaper
 * of the two things to keep true — and the checker is what makes "cheaper"
 * mean "checked" rather than "hoped".
 */

// ---- generated from src/document_processor.py ----
// Regenerate with:  python3 .pantheon/check-attachment-language.py --write
// Hand edits here are reverted by the checker, which fails the gate first.
export const LANGUAGE_ALIASES = {
  ".py": "python",
  ".js": "javascript",
  ".mjs": "javascript",
  ".cjs": "javascript",
  ".jsx": "javascript",
  ".ts": "typescript",
  ".tsx": "typescript",
  ".htm": "html",
  ".md": "markdown",
  ".markdown": "markdown",
  ".mdx": "markdown",
  ".rb": "ruby",
  ".rs": "rust",
  ".kt": "kotlin",
  ".kts": "kotlin",
  ".pl": "perl",
  ".ps1": "powershell",
  ".sh": "bash",
  ".zsh": "bash",
  ".yml": "yaml",
  ".h": "c",
  ".hh": "cpp",
  ".hpp": "cpp",
  ".hxx": "cpp",
  ".cc": "cpp",
  ".cxx": "cpp",
  ".cs": "csharp",
  ".patch": "diff",
  ".ipynb": "json",
  ".txt": "text",
  ".text": "text",
};
export const PROSE_LANGUAGES = new Set(["log", "text"]);
const LANGUAGE_TOKEN = /^[a-z][a-z0-9+#]{0,11}$/;
export const TEXT_EXTS = new Set([".bash", ".c", ".cpp", ".css", ".csv", ".go", ".h", ".htm", ".html", ".java", ".js", ".json", ".jsx", ".log", ".md", ".nix", ".php", ".py", ".rb", ".rs", ".sh", ".sql", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml"]);
export const OFFICE_EXTS = new Set([".doc", ".docx", ".epub", ".odt", ".pptx", ".xls", ".xlsx"]);
export const PDF_EXTS = new Set([".pdf"]);
export const INGESTIBLE_EXTS = new Set([".bash", ".c", ".cpp", ".css", ".csv", ".doc", ".docx", ".epub", ".go", ".h", ".htm", ".html", ".java", ".js", ".json", ".jsx", ".log", ".md", ".nix", ".odt", ".pdf", ".php", ".pptx", ".py", ".rb", ".rs", ".sh", ".sql", ".ts", ".tsx", ".txt", ".xls", ".xlsx", ".xml", ".yaml", ".yml"]);
// ---- end generated ----

/**
 * `os.path.splitext`'s extension, to the letter.
 *
 * Not `name.split('.').pop()`, which the three maps this file replaces all
 * used: that answers `"bashrc"` for `.bashrc` and `"gz"` for `archive.tar.gz`,
 * where Python answers `""` and `".gz"`. A leading dot is part of the name, not
 * a separator, and the dot has to be the last one in the BASENAME — so the two
 * implementations agree on a name with a directory in it even though a browser
 * `File` never has one.
 */
function splitExt(lowered) {
  const sep = lowered.lastIndexOf('/');
  const dot = lowered.lastIndexOf('.');
  if (dot > sep) {
    for (let i = sep + 1; i < dot; i++) {
      if (lowered[i] !== '.') return lowered.slice(dot);
    }
  }
  return '';
}

/**
 * The one word this product uses for what *name* is — the browser's half.
 *
 * Mirrors `document_processor.attachment_language`. A file with no extension,
 * or one whose suffix is not a word, is `text`.
 */
export function attachmentLanguage(name) {
  const lowered = String(name == null ? '' : name).toLowerCase();
  let ext = splitExt(lowered);
  if (!ext && lowered.startsWith('.')) {
    // A bare dotfile: `.md` has no splitext extension and is still markdown.
    ext = lowered.slice(lowered.lastIndexOf('/') + 1);
  }
  if (!ext) return 'text';
  const alias = LANGUAGE_ALIASES[ext];
  if (alias) return alias;
  const token = ext.slice(1);
  return LANGUAGE_TOKEN.test(token) ? token : 'text';
}

/** Whether a language's content is prose. The server's fence decision, and the
 *  browser's "leave the Document's language empty" decision, are the same
 *  question — both mean "this file has no syntax to colour". */
export function isProseLanguage(language) {
  return PROSE_LANGUAGES.has(String(language || ''));
}

/**
 * Languages the browser's editor has no mode of its own for, routed to the one
 * it does.
 *
 * **This is not a second language register and the checker enforces that.** It
 * is keyed on a LANGUAGE, never on an extension, and every entry exists because
 * `document.js` has a syntax mode and a toolbar for the value and none for the
 * key — `.scss` is `scss` everywhere the server speaks, and edits in the CSS
 * mode because that is the mode there is. An entry whose key is a language the
 * server would answer differently for the same file is the drift `B161` is
 * about, and `check-attachment-language.py` fails on one.
 *
 * Each of these was the client's ANSWER before this file existed — `.scss` was
 * mapped straight to `css` by all three copies — so routing rather than
 * relabelling is what keeps the editor's toolbar exactly where it was
 * (`Law 1`). What changes is that the label the composer shows and the language
 * the document is stored with now come from the same derivation.
 */
const EDITOR_LANGUAGE = {
  scss: 'css',
  sass: 'css',
  less: 'css',
  cfg: 'ini',
  conf: 'ini',
  tsv: 'csv',
  vue: 'html',
  svelte: 'html',
};

/**
 * The `language` field a Document gets when the browser imports *name*.
 *
 * Three call sites asked this and each answered it with a map of its own. It is
 * `attachmentLanguage`, routed through the editor's own modes, with prose
 * coming back as the empty string — which is what all three copies meant by
 * mapping `.txt` and `.log` to `''`, and is what the document editor reads as
 * "no syntax highlighting".
 */
export function documentLanguage(name) {
  const language = attachmentLanguage(name);
  if (isProseLanguage(language)) return '';
  return EDITOR_LANGUAGE[language] || language;
}

// ── `B232`: which door a file goes through, not whether it is on a list ─────
//
// `chat.js` answered this twice with two hand-written regexes — 38 extensions
// on the composer's import banner and 36 on *open this attachment as a
// document* — in front of a backend that derives it. Measured against the
// registers above, the gate was wrong in **both** directions: 10 ingestible
// extensions were not offered (`.bash .doc .docx .epub .nix .odt .pdf .pptx
// .xls .xlsx`) and 9 offered extensions no register names (`.conf .env .ini
// .less .sass .scss .svelte .toml .vue`).
//
// The nine are the interesting half, because they were the *right* answer:
// `looks_like_text` rescues them on the server (`B76`), so the composer was
// already offering files no register names — which is the evidence that the
// question was never "is the extension on a list". The server publishes its
// verdict now (`X-Upload-Kind`, and `kind` on each file in the upload
// response), and the functions below exist only for the one caller that cannot
// ask it: a local `File` the browser is about to import, which has no upload id
// yet.
export const INGEST_KIND_TEXT = 'text';
export const INGEST_KIND_DOCUMENT = 'document';
export const INGEST_KIND_BINARY = 'binary';

/** The extensions the server has an EXTRACTOR for — the ones a client must
 *  post rather than read. `document_processor.EXTRACTED_EXTS`, derived from
 *  the same two generated registers the server derives it from. */
export function isExtractedExtension(name) {
  const lowered = String(name == null ? '' : name).toLowerCase();
  const ext = splitExt(lowered);
  return !!ext && (OFFICE_EXTS.has(ext) || PDF_EXTS.has(ext));
}

/**
 * What the browser can say about *name* on its own, or `null` when only the
 * server can answer.
 *
 * Mirrors `document_processor.ingest_kind`'s **extension** arm exactly —
 * extractor first, then the text register — and stops where that function's
 * second arm begins, because the second arm is `looks_like_text` reading the
 * bytes and there is no browser copy of that (`Law 14`). `null` is the honest
 * answer for `.kt`, `.toml`, `.env` and a file with no suffix at all: they are
 * text, the server says so from the bytes, and a register cannot.
 *
 * A `text/*` MIME is taken as text because the server takes it too — the
 * `mime.startswith("text/")` arm at `build_user_content`'s dispatch is a
 * superset of the extension register there for the same reason it is here.
 */
export function ingestKindFromName(name, mime) {
  const lowered = String(name == null ? '' : name).toLowerCase();
  const ext = splitExt(lowered);
  if (ext && (OFFICE_EXTS.has(ext) || PDF_EXTS.has(ext))) return INGEST_KIND_DOCUMENT;
  if (ext && TEXT_EXTS.has(ext)) return INGEST_KIND_TEXT;
  if (/^text\//.test(String(mime || ''))) return INGEST_KIND_TEXT;
  return null;
}
