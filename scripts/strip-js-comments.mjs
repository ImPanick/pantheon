// SPDX-License-Identifier: AGPL-3.0-or-later
// `B1591` (the owner's call, `D-2026-10-29-02` §6). Pantheon's own JavaScript
// goes out of the image without its comments; the repository keeps every one
// of them (`Law 1`). The Docker image's `js-without-comments` stage runs this
// over the build context and copies what it writes over the app's copy, so the
// source a person reads is commented and the bytes a browser fetches are not.
// The module count stands under `D-2026-09-14-01` (no bundling): this changes
// what is in each file, not how many there are.
//
// **Why a parser and not a pattern.** Whether `/` starts a regular expression,
// a division or a comment is decided by the grammar, not by the characters
// around it — `a / b / c` is two divisions, `x = /\/\*/` is a regular
// expression holding `/*`, and a template literal can hold anything. So the
// comments are the ones acorn reports while it parses the whole module (its
// tokenizer, driven by its parser), and nothing else is touched.
//
// **What a comment becomes.** Its line breaks, kept where they were, and
// nothing else — so every token of the program keeps its line *and* its
// column, and a stack trace from the image points at the same place in the
// repository's file:
//
//   * a `//` comment, and a block comment that ends its line, are dropped with
//     the spaces around them (nothing follows them on that line);
//   * a block comment with code after it on its last line keeps that line's
//     share as spaces, so the code after it does not move left;
//   * a block comment's line breaks stay, so a comment that held one is still
//     a line terminator to automatic semicolon insertion.
//
// **What is kept whole**: a `/*! … */` comment; one naming a licence, a
// copyright or an SPDX identifier (the notices go out with the code — the same
// words `src/static_representations.py` keeps in a stylesheet, which a test
// holds equal); `@license` and `@preserve`; and a `sourceURL` or
// `sourceMappingURL` directive, which a browser reads. A hashbang and an
// HTML-like comment (`<!--`, `-->`) are never touched: only text that starts
// `//` or `/*` is ever taken out.
//
// **It proves each file before writing it.** The output is parsed again and
// its token stream — every token's type, value, line and column — must be the
// input's exactly; a file that parses both as a module and as a script must
// put its comments in the same places under both; and the line count must not
// move. A file that fails any of that stops the build with a sentence saying
// which file and why; nothing is written half-stripped.
//
//   node scripts/strip-js-comments.mjs <app-root> <out-root>
//
// reads every `.js`/`.mjs` under `<app-root>/static/` except `static/lib/`
// (vendored, byte-identical to upstream's tarballs: `check-licences.py`),
// writes each to the same path under `<out-root>`, writes
// `<out-root>/js-without-comments.json` — for each module, the git blob id of
// the bytes it was given and of the bytes it wrote, which is how
// `scripts/pantheon-deploy`'s byte check tells this from drift — and prints
// what it did. `tests/test_shipped_javascript_goes_out_without_its_comments.py`
// drives the stage's command over every shipped module.

import { parse, version as acornVersion } from 'acorn';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import zlib from 'node:zlib';

// Where the modules are, relative to the app's root; what under it is never
// ours to rewrite; and the record `scripts/pantheon-deploy` reads beside them.
export const STATIC = 'static';
export const VENDORED = ['lib/'];
export const RECORD = 'js-without-comments.json';

// The notices, in the words `src/static_representations.py`'s `_NOTICE` uses
// for a stylesheet (a test holds the two equal), plus the JS conventions.
export const NOTICE = /licen[cs]e|copyright|spdx-license-identifier|©/i;
const KEEP_JS = /^\/\*!|@license\b|@preserve\b|^\/[/*][#@]\s*source(?:Mapping)?URL=/;

const LINE_BREAK = /\r\n|[\n\r\u2028\u2029]/g;
const IS_LINE_BREAK = (ch) => ch === '\n' || ch === '\r' || ch === '\u2028' || ch === '\u2029';
const IS_SPACE = (ch) => ch === ' ' || ch === '\t';

const OPTIONS = { ecmaVersion: 'latest', allowHashBang: true, locations: true };

class StripRefused extends Error {}

function scan(source, sourceType) {
  const tokens = [];
  const comments = [];
  parse(source, {
    ...OPTIONS,
    sourceType,
    onToken: tokens,
    onComment: (block, text, start, end) => comments.push({ block, start, end }),
  });
  return { tokens, comments };
}

// Each goal the file parses under. A module is tried first: the shipped
// files are almost all modules, and a classic script (the service worker,
// the sandbox's worker) parses as a script when it does not as a module.
function goals(source) {
  const out = [];
  const errors = [];
  for (const sourceType of ['module', 'script']) {
    try {
      out.push({ sourceType, ...scan(source, sourceType) });
    } catch (err) {
      errors.push(`as a ${sourceType}: ${err.message}`);
    }
  }
  return { out, errors };
}

// A token as it is compared: what it is, and where — its line and column at
// both ends. The end of the input is not a token of the program, and a comment
// dropped from the last line moves its column, so it is held to its line.
function tokenKey(tok) {
  let value = tok.value;
  if (value && typeof value === 'object' && 'pattern' in value) value = `/${value.pattern}/${value.flags}`;
  else if (typeof value === 'bigint') value = `${value}n`;
  if (tok.type.label === 'eof') return `eof|${tok.loc.start.line}`;
  return `${tok.type.label}|${typeof value}|${String(value)}|`
    + `${tok.loc.start.line}:${tok.loc.start.column}-${tok.loc.end.line}:${tok.loc.end.column}`;
}

// Is this comment kept whole?
export function isKept(text) {
  if (!text.startsWith('//') && !text.startsWith('/*')) return true;   // a hashbang, `<!--`, `-->`
  return KEEP_JS.test(text) || NOTICE.test(text);
}

function restOfLineIsBlank(source, from) {
  for (let i = from; i < source.length; i += 1) {
    const ch = source[i];
    if (IS_LINE_BREAK(ch)) return true;
    if (!IS_SPACE(ch)) return false;
  }
  return true;
}

// The edit for one comment, as `[from, to, replacement]` over the source.
function edit(source, comment, floor) {
  const text = source.slice(comment.start, comment.end);
  const breaks = text.match(LINE_BREAK) || [];
  const dropped = !comment.block || restOfLineIsBlank(source, comment.end);
  if (dropped) {
    // The spaces in front of it go too, back to the token or comment before it.
    let from = comment.start;
    while (from > floor && IS_SPACE(source[from - 1])) from -= 1;
    let to = comment.end;
    while (to < source.length && IS_SPACE(source[to])) to += 1;
    return [from, to, breaks.join('')];
  }
  // Code follows on its last line: that line's share stays as spaces.
  const lastBreak = Math.max(text.lastIndexOf('\n'), text.lastIndexOf('\r'),
    text.lastIndexOf('\u2028'), text.lastIndexOf('\u2029'));
  const tail = text.slice(lastBreak + 1);
  return [comment.start, comment.end, breaks.join('') + ' '.repeat(tail.length)];
}

/**
 * `source` with its comments taken out (see the header), proven to be the
 * same program. Throws `StripRefused`, whose message names the reason, when
 * it cannot be proven.
 */
export function stripComments(source, name = '<source>') {
  const { out: parsed, errors } = goals(source);
  if (!parsed.length) {
    throw new StripRefused(`${name}: acorn cannot parse it (${errors.join('; ')}). Fix the syntax `
      + `— or, if it is syntax newer than acorn knows, bump acorn in package.json, package-lock.json `
      + `and CREDITS.md`);
  }
  const where = (g) => g.comments.map((c) => `${c.start}-${c.end}`).join(',');
  if (parsed.length === 2 && where(parsed[0]) !== where(parsed[1])) {
    throw new StripRefused(`${name}: it parses as a module and as a script, and the two goals put `
      + `its comments in different places (an HTML-like comment?), so which ones a browser skips `
      + `depends on how it is loaded. Write it so both agree`);
  }
  const { tokens, comments } = parsed[0];
  // Tokens and comments in source order, so each comment knows where the
  // thing before it ends.
  const ends = tokens.map((t) => t.end).concat(comments.map((c) => c.end)).sort((a, b) => a - b);
  const edits = [];
  let kept = 0;
  let j = 0;
  let floor = 0;
  for (const comment of comments) {
    while (j < ends.length && ends[j] <= comment.start) { floor = ends[j]; j += 1; }
    if (isKept(source.slice(comment.start, comment.end))) { kept += 1; continue; }
    edits.push(edit(source, comment, floor));
  }
  let code = '';
  let at = 0;
  for (const [from, to, replacement] of edits) {
    code += source.slice(at, from) + replacement;
    at = to;
  }
  code += source.slice(at);

  // The proof: the same tokens, each on the same line and column, under the
  // same goal; no comment left but the kept ones; the same number of lines.
  let again;
  try {
    again = scan(code, parsed[0].sourceType);
  } catch (err) {
    throw new StripRefused(`${name}: the stripped copy no longer parses (${err.message}) — a defect `
      + `in scripts/strip-js-comments.mjs, not in the module`);
  }
  const before = tokens.map(tokenKey);
  const after = again.tokens.map(tokenKey);
  const differs = before.findIndex((k, i) => k !== after[i]);
  if (before.length !== after.length || differs >= 0) {
    const at_ = differs >= 0 ? differs : Math.min(before.length, after.length);
    throw new StripRefused(`${name}: the stripped copy is a different token stream from token ${at_} `
      + `(${before[at_]} became ${after[at_]}) — a defect in scripts/strip-js-comments.mjs, not in `
      + `the module`);
  }
  if (again.comments.length !== kept) {
    throw new StripRefused(`${name}: ${again.comments.length} comments are left where ${kept} were kept`);
  }
  if ((code.match(LINE_BREAK) || []).length !== (source.match(LINE_BREAK) || []).length) {
    throw new StripRefused(`${name}: the stripped copy has a different number of lines`);
  }
  return { code, removed: edits.length, kept, sourceType: parsed[0].sourceType };
}

/** Every `.js`/`.mjs` under `root` that is ours, as paths relative to it. */
export function ownModules(root) {
  const found = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      const rel = path.relative(root, full).split(path.sep).join('/');
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || VENDORED.some((v) => `${rel}/`.startsWith(v))) continue;
        walk(full);
      } else if (entry.isFile() && /\.m?js$/.test(entry.name)) {
        found.push(rel);
      }
    }
  };
  walk(root);
  return found.sort();
}

/** git's object name for these bytes — what `git ls-files -s` prints, and
 * what `scripts/pantheon-deploy`'s `blob_id` computes. */
export function blobId(bytes) {
  return crypto.createHash('sha1')
    .update(Buffer.from(`blob ${bytes.length}\0`, 'latin1'))
    .update(bytes)
    .digest('hex');
}

function main(argv) {
  const [appRoot, outRoot] = argv;
  if (!appRoot || !outRoot) {
    console.error('usage: node scripts/strip-js-comments.mjs <app-root> <out-root>');
    return 2;
  }
  // Never over the source: the repository keeps its comments (`Law 1`).
  if (path.resolve(outRoot) === path.resolve(appRoot)) {
    console.error(`strip-js-comments: <out-root> is <app-root>, which would take the comments out `
      + `of the repository's own files. Give it an empty directory to write into.`);
    return 2;
  }
  const root = path.join(appRoot, STATIC);
  const files = fs.existsSync(root) ? ownModules(root) : [];
  if (!files.length) {
    console.error(`strip-js-comments: no modules under ${root} — is ${appRoot} the app's root?`);
    return 1;
  }
  const gz = (b) => zlib.gzipSync(b, { level: 6 }).length;
  const totals = { bytesIn: 0, bytesOut: 0, gzIn: 0, gzOut: 0, removed: 0 };
  const record = {};
  const failures = [];
  for (const rel of files) {
    const input = fs.readFileSync(path.join(root, rel));
    const source = input.toString('utf8');
    if (!Buffer.from(source, 'utf8').equals(input)) {
      failures.push(`${STATIC}/${rel}: it is not UTF-8, which a module served as text/javascript must be`);
      continue;
    }
    let result;
    try {
      result = stripComments(source, `${STATIC}/${rel}`);
    } catch (err) {
      if (!(err instanceof StripRefused)) throw err;
      failures.push(err.message);
      continue;
    }
    const output = Buffer.from(result.code, 'utf8');
    const target = path.join(outRoot, STATIC, rel);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, output);
    record[`${STATIC}/${rel}`] = { from: blobId(input), to: blobId(output) };
    totals.bytesIn += input.length;
    totals.bytesOut += output.length;
    totals.gzIn += gz(input);
    totals.gzOut += gz(output);
    totals.removed += result.removed;
  }
  if (failures.length) {
    console.error(`strip-js-comments: ${failures.length} of ${files.length} modules could not be `
      + `stripped, and the image would serve them half-done, so the build stops here:`);
    for (const line of failures) console.error(`  ${line}`);
    return 1;
  }
  // `scripts/pantheon-deploy` checks the image's bytes against git's. These
  // modules are meant to differ, so it is told how: each was made from the
  // bytes `from` names and is the bytes `to` names.
  fs.writeFileSync(path.join(outRoot, RECORD), `${JSON.stringify({
    what: 'B1591: these modules are served without their comments. Each was made by '
      + 'scripts/strip-js-comments.mjs from the bytes `from` names and is the bytes `to` names '
      + '(git blob ids).',
    acorn: acornVersion,
    files: record,
  }, null, 1)}\n`);
  const kb = (n) => `${Math.round(n / 1024).toLocaleString('en')} KB`;
  console.log(`strip-js-comments: ${files.length} modules, ${totals.removed} comments taken out; `
    + `${kb(totals.bytesIn)} -> ${kb(totals.bytesOut)}, gzipped ${kb(totals.gzIn)} -> ${kb(totals.gzOut)}`);
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  process.exitCode = main(process.argv.slice(2));
}
