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
