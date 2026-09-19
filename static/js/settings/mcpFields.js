// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/settings/mcpFields.js — the Args and Env fields of the MCP server form.
//
// `P8-46`. The row's original premise — *a parse failure is caught and
// silently discarded* — was fixed on the server and in both browser forms by
// `1dc03f5` (2026-09-13); what was left is the half the row's headline names:
// **the inputs are still single-line JSON**, and a person who has never
// written an argv by hand has to produce `["-y", "@scope/pkg"]`, brackets,
// quotes, commas and all, in a 300px text box with no feedback until Save.
//
// Three things are wrong with telling that person "Args must be valid JSON":
//
//   1. it names the field and nothing else — not *where* in what they typed,
//      not *what* about it JSON refuses;
//   2. `JSON.parse`'s own message is engine-specific (`Unexpected token '-',
//      "[-y, pkg]" is not valid JSON` in V8, `expected property name or '}' at
//      line 1 column 2` in SpiderMonkey), so it cannot be shown as-is and
//      cannot be tested against;
//   3. it is advice about a format nobody asked to learn. The value a person
//      has is *two arguments*; JSON is this form's storage format, not theirs.
//
// So this module does both halves. `createMcpFieldEditor` gives the field one
// box per argument and one KEY/value pair per variable — no quoting, no
// brackets, nothing to balance — and keeps the JSON textarea as a second
// **mode of the same field** for people who have a config to paste (`Law 1`:
// the raw route is not taken away). `diagnoseJsonText` is the fallback for
// that mode: an engine-independent reading of what is actually wrong with the
// text, with the offending character pointed at.
//
// `Law 14`: one rule, one place. Shape checking lives here **and** on the
// server (`routes/mcp/mcp_routes.py:_parsed_json_field`) on purpose — the
// server is the authority and refuses these on any client, this half says
// which field before a round trip. What this side adds that the server cannot
// is the caret and the typo reading, which need the raw text.

/** Straight double quote is the only string delimiter JSON has. */
const SMART_QUOTES = /[‘’“”]/;

/** Shape of each field, so the messages never have to restate it. */
export const FIELD_KINDS = {
  args: {
    label: 'Arguments',
    container: 'array',
    open: '[',
    close: ']',
    example: '["-y", "@modelcontextprotocol/server-filesystem"]',
    item: 'argument',
  },
  env: {
    label: 'Environment',
    container: 'object',
    open: '{',
    close: '}',
    example: '{"API_KEY": "sk-..."}',
    item: 'variable',
  },
};

/**
 * Walk `raw` once, tracking JSON string state, and report what is outside the
 * strings.
 *
 * Every typo rule below needs this. `"it's fine"` is a legal JSON string and
 * a naive search for `'` calls it a single-quoted string; `"a, ]"` is a legal
 * string and a naive search for `,\s*]` calls it a trailing comma. Scanning
 * for structure means scanning outside the quotes.
 */
function scanStructure(raw) {
  const text = String(raw == null ? '' : raw);
  let outside = '';
  let inString = false;
  let escaped = false;
  let unterminatedAt = -1;
  const depth = { '[': 0, ']': 0, '{': 0, '}': 0 };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) { escaped = false; continue; }
      if (ch === '\\') { escaped = true; continue; }
      if (ch === '"') { inString = false; continue; }
      continue;
    }
    if (ch === '"') { inString = true; unterminatedAt = i; continue; }
    if (Object.prototype.hasOwnProperty.call(depth, ch)) depth[ch] += 1;
    outside += ch;
  }
  return { text, outside, unterminated: inString ? unterminatedAt : -1, depth };
}

/** Line/column for a character offset, 1-based, the way an editor counts. */
export function lineColumnAt(text, index) {
  const upto = String(text).slice(0, Math.max(0, index));
  const lines = upto.split('\n');
  return { line: lines.length, column: lines[lines.length - 1].length + 1 };
}

/**
 * A window of the text around `index`, with a caret under the character.
 *
 * Returned as two strings the caller renders in a monospace block; the caret
 * is built from the excerpt's own length so the two always line up, which a
 * caller computing its own offset would not guarantee.
 */
export function caretExcerpt(text, index, span = 46) {
  const src = String(text == null ? '' : text).replace(/\t/g, ' ');
  if (!src) return null;
  const at = Math.max(0, Math.min(src.length, Number(index) || 0));
  const half = Math.floor(span / 2);
  let start = Math.max(0, at - half);
  let end = Math.min(src.length, start + span);
  start = Math.max(0, Math.min(start, Math.max(0, end - span)));
  const lead = start > 0 ? '…' : '';
  const tail = end < src.length ? '…' : '';
  const excerpt = lead + src.slice(start, end) + tail;
  const caret = ' '.repeat(lead.length + (at - start)) + '^';
  return { excerpt, caret };
}

/**
 * Where the engine says the text went wrong, as a character offset.
 *
 * V8 says `at position N`, SpiderMonkey says `at line L column C`, JavaScript-
 * Core says neither. Nothing here depends on getting one: a null offset just
 * means no caret, and the reading below still stands on its own.
 */
function engineOffset(text, error) {
  const message = String((error && error.message) || '');
  const byPosition = message.match(/position\s+(\d+)/i);
  if (byPosition) return Math.min(text.length, Number(byPosition[1]));
  const byLineColumn = message.match(/line\s+(\d+)\s+column\s+(\d+)/i);
  if (byLineColumn) {
    const lines = text.split('\n');
    const wantLine = Math.max(1, Number(byLineColumn[1]));
    let offset = 0;
    for (let i = 0; i < wantLine - 1 && i < lines.length; i++) offset += lines[i].length + 1;
    return Math.min(text.length, offset + Math.max(0, Number(byLineColumn[2]) - 1));
  }
  return null;
}

/** Index of the first character of `needle` outside any JSON string, or -1. */
function outsideIndexOf(raw, test) {
  const text = String(raw == null ? '' : raw);
  let inString = false;
  let escaped = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) { escaped = false; continue; }
      if (ch === '\\') { escaped = true; continue; }
      if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') { inString = true; continue; }
    if (test(ch, i, text)) return i;
  }
  return -1;
}

const BARE_WORD = /[A-Za-z_@./~$-]/;
const JSON_LITERAL = /^(true|false|null)$/;

/**
 * Read the text and say, in words a person can act on, what is wrong with it.
 *
 * Independent of `JSON.parse`'s message on purpose — see the header. The order
 * matters: the rules run most-specific first, because a paste with curly
 * quotes *also* looks like it has unquoted words, and being told about the
 * quotes is the one that ends the problem.
 *
 * Returns null when the text has no recognisable typo; the caller still has
 * the engine's refusal and falls back to a general sentence.
 */
export function readJsonTypo(raw, kind) {
  const spec = FIELD_KINDS[kind] || FIELD_KINDS.args;
  const scan = scanStructure(raw);
  const text = scan.text;
  const trimmed = text.trim();
  if (!trimmed) return null;

  const smart = text.search(SMART_QUOTES);
  if (smart >= 0) {
    return {
      index: smart,
      title: 'Curly quotes',
      detail: 'This has typographic quotes (“ ”) in it, which a word processor '
        + 'or a web page inserts on your behalf. JSON only accepts the straight kind: ".',
    };
  }

  const quote = outsideIndexOf(text, (ch) => ch === "'");
  if (quote >= 0) {
    return {
      index: quote,
      title: 'Single quotes',
      detail: `JSON has no single-quoted strings. Write "text" rather than 'text' — `
        + `for example ${spec.example}.`,
    };
  }

  if (scan.unterminated >= 0) {
    return {
      index: scan.unterminated,
      title: 'A quote was never closed',
      detail: 'The string that starts here has no closing ". Everything after it is being '
        + 'read as part of that one value.',
    };
  }

  if (kind === 'env') {
    const equals = outsideIndexOf(text, (ch) => ch === '=');
    if (equals >= 0) {
      return {
        index: equals,
        title: 'Shell syntax, not JSON',
        detail: 'This looks like KEY=value, the way you would write it in a shell. '
          + 'JSON pairs a name with a value using a colon: {"KEY": "value"}.',
      };
    }
  }

  const trailing = outsideIndexOf(text, (ch, i, all) => {
    if (ch !== ',') return false;
    const rest = all.slice(i + 1).replace(/^\s+/, '');
    return rest.startsWith(']') || rest.startsWith('}');
  });
  if (trailing >= 0) {
    return {
      index: trailing,
      title: 'A comma with nothing after it',
      detail: 'JSON does not allow a comma before a closing bracket. Delete this one.',
    };
  }

  const opens = scan.depth[spec.open];
  const closes = scan.depth[spec.close];
  if (opens !== closes) {
    const missing = opens > closes ? spec.close : spec.open;
    return {
      index: opens > closes ? text.length : 0,
      title: `A ${missing} is missing`,
      detail: `There ${opens === 1 ? 'is' : 'are'} ${opens} ${spec.open} and `
        + `${closes} ${spec.close} in this. Every ${spec.open} needs its ${spec.close}.`,
    };
  }

  const firstChar = trimmed[0];
  if (firstChar !== spec.open) {
    return {
      index: text.indexOf(firstChar),
      title: `${spec.label} must start with ${spec.open}`,
      detail: `A JSON ${spec.container} is written ${spec.open}…${spec.close}. `
        + `For example ${spec.example}.`,
    };
  }

  const bare = outsideIndexOf(text, (ch, i, all) => {
    if (!BARE_WORD.test(ch)) return false;
    let end = i;
    while (end < all.length && /[^,:\]}\s]/.test(all[end])) end += 1;
    const word = all.slice(i, end);
    return !JSON_LITERAL.test(word) && Number.isNaN(Number(word));
  });
  if (bare >= 0) {
    let end = bare;
    while (end < text.length && /[^,:\]}\s]/.test(text[end])) end += 1;
    const word = text.slice(bare, end);
    return {
      index: bare,
      title: 'An unquoted word',
      detail: `${word} is not in quotes, so JSON is trying to read it as a number or a `
        + `keyword. Every piece of text here needs double quotes around it: "${word}".`,
    };
  }
  return null;
}

/**
 * Check the parsed value's shape, and each entry inside it.
 *
 * The server checks the container (`_parsed_json_field`) because it must — a
 * browser is not an authority. It does **not** check the entries, and two of
 * those reach a subprocess: `{"PORT": 3000}` is a valid JSON object that the
 * route accepts and `StdioServerParameters(env=…)` then hands to `os.environ`
 * as an int. Catching it here costs a round trip instead of a failed spawn,
 * and the row editor makes it unreachable in the first place, because a text
 * input cannot produce a number.
 */
export function checkShape(value, kind) {
  const spec = FIELD_KINDS[kind] || FIELD_KINDS.args;
  if (kind === 'args') {
    if (!Array.isArray(value)) {
      return {
        title: `${spec.label} must be a list`,
        detail: `This parsed as ${describeType(value)}, not a list of arguments. `
          + `Write it as ${spec.example}.`,
      };
    }
    for (let i = 0; i < value.length; i++) {
      if (typeof value[i] !== 'string') {
        return {
          title: `Argument ${i + 1} is not text`,
          detail: `Every argument is passed to the command as text. ${describeType(value[i])} `
            + `cannot be. Put quotes around it: "${String(value[i])}".`,
        };
      }
    }
    return null;
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {
      title: `${spec.label} must be a set of name/value pairs`,
      detail: `This parsed as ${describeType(value)}, not a set of variables. `
        + `Write it as ${spec.example}.`,
    };
  }
  for (const key of Object.keys(value)) {
    if (typeof value[key] !== 'string') {
      return {
        title: `${key} is not text`,
        detail: `Environment variables reach the server as text, so ${describeType(value[key])} `
          + `cannot be sent. Put quotes around it: "${String(value[key])}".`,
      };
    }
  }
  return null;
}

function describeType(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'a list';
  switch (typeof value) {
    case 'number': return 'a number';
    case 'boolean': return 'true/false';
    case 'string': return 'a single piece of text';
    case 'object': return 'a set of name/value pairs';
    default: return 'something else';
  }
}

/**
 * Parse one field's raw text into the value the form will post.
 *
 * `{ok: true, value}` or `{ok: false, problem}` where `problem` carries the
 * field, a heading, a sentence, and — when the offending character could be
 * located — the excerpt and caret to draw under the box. Blank is not a
 * failure: most servers take no args and no env (`Law 1`).
 */
export function parseJsonField(raw, kind) {
  const spec = FIELD_KINDS[kind] || FIELD_KINDS.args;
  const text = String(raw == null ? '' : raw).trim();
  if (!text) return { ok: true, value: kind === 'args' ? [] : {} };
  let value;
  try {
    value = JSON.parse(text);
  } catch (error) {
    const typo = readJsonTypo(text, kind);
    const index = typo ? typo.index : engineOffset(text, error);
    return {
      ok: false,
      problem: {
        field: kind,
        title: typo ? typo.title : `${spec.label} is not valid JSON yet`,
        detail: typo
          ? typo.detail
          : `Something here is not JSON the browser can read. A ${spec.container} looks `
            + `like ${spec.example}.`,
        ...(index == null ? {} : { position: lineColumnAt(text, index) }),
        ...(index == null ? {} : (caretExcerpt(text, index) || {})),
      },
    };
  }
  const shape = checkShape(value, kind);
  if (shape) return { ok: false, problem: { field: kind, ...shape } };
  return { ok: true, value };
}

/**
 * Turn the server's refusal into the sentence to show, on the field it names.
 *
 * `add_server` answers 400 with a `detail` that already says which field and
 * what shape would have worked. The Settings form read `r.status` and threw
 * `data` away, so *"args must be a JSON array, e.g. [\"-y\", \"pkg\"]"* was
 * rendered as **"Failed (400)"** — the server explaining itself into a socket
 * nobody was listening on. Measured 2026-09-19 at `settings.js:5686`.
 */
export function describeServerRefusal(status, body) {
  const payload = body && typeof body === 'object' ? body : {};
  const raw = payload.detail != null ? payload.detail
    : payload.error != null ? payload.error
    : payload.message != null ? payload.message : '';
  const text = typeof raw === 'string' ? raw.trim()
    : Array.isArray(raw) ? raw.map((d) => (d && d.msg) || String(d)).join('; ').trim()
    : raw ? JSON.stringify(raw) : '';
  if (!text) {
    return {
      field: null,
      text: status === 403
        ? 'The server refused this: you are not signed in as an administrator.'
        : `The server refused this and gave no reason (HTTP ${status}).`,
    };
  }
  const lower = text.toLowerCase();
  let field = null;
  if (/\bargs?\b/.test(lower)) field = 'args';
  else if (/\benv\b/.test(lower)) field = 'env';
  // Shown verbatim. `add_server` writes these for a person to read and
  // they open on the field's own name — dressing `url is required for SSE
  // transport` up as `Url is required…` gains nothing and loses the name.
  return { field, text };
}

/** The command line as it will actually be run, for the line under the form. */
export function formatCommandLine(command, args) {
  const parts = [String(command || '').trim()]
    .concat((Array.isArray(args) ? args : []).map((a) => String(a)))
    .filter((p) => p !== '');
  return parts.map((p) => (/\s/.test(p) ? `"${p}"` : p)).join(' ');
}

// ── Tool schemas (`P8-48`, read half) ───────────────────────────────────────
//
// **Measured 2026-09-19, and the row's premise is half true.**
// `McpManager.get_all_tools` (`src/mcp_manager.py:606-622`) puts
// `input_schema` on every entry, and `GET /api/mcp/servers/{id}/tools`
// (`routes/mcp/mcp_routes.py:415-433`) returns those entries unchanged — so
// the schema *is* carried to the browser today. The panel that received it
// drew a checkbox, the tool name, and `description.slice(0, 80)`, and dropped
// the schema on the floor: `grep -c input_schema static/` returned **0** over
// the whole of `static/` before this.
//
// What is **not** on the wire is `annotations`. It is captured at connect
// (`src/mcp_manager.py:217` stdio, `:286` SSE) and `mcp_tool_is_readonly`
// reads it, and `get_all_tools` does not copy it into the payload — so the
// readOnlyHint/destructiveHint half of the row cannot be shown, let alone
// edited, without a backend change. Deriving the verdict here from the tool
// name would be a second copy of `mcp_tool_is_readonly` in a language that
// cannot be kept in step with it (`Law 14`), so this side shows what the
// server sent and says nothing it was not told.

/**
 * Flatten a tool's JSON Schema into the rows a parameter table needs.
 *
 * Deliberately forgiving: an MCP server writes this, not us, and a schema that
 * is missing `properties`, types an argument as `["string","null"]` or puts
 * the type inside `anyOf` must render rather than throw. An unreadable type
 * comes back as null and the caller omits it — a parameter list missing one
 * word is legible; a panel that threw is not.
 */
export function summariseSchema(schema) {
  const source = schema && typeof schema === 'object' && !Array.isArray(schema) ? schema : {};
  const properties = source.properties && typeof source.properties === 'object'
    ? source.properties : {};
  const required = new Set(Array.isArray(source.required) ? source.required.map(String) : []);
  const params = Object.keys(properties).map((name) => {
    const field = properties[name] && typeof properties[name] === 'object' ? properties[name] : {};
    return {
      name,
      type: readSchemaType(field),
      required: required.has(name),
      description: typeof field.description === 'string' ? field.description : '',
      choices: Array.isArray(field.enum) ? field.enum.map((v) => String(v)) : [],
    };
  });
  params.sort((a, b) => (a.required === b.required ? 0 : a.required ? -1 : 1));
  return { params, count: params.length };
}

function readSchemaType(field) {
  if (typeof field.type === 'string') return field.type;
  if (Array.isArray(field.type)) {
    const named = field.type.map(String).filter((t) => t && t !== 'null');
    return named.length ? named.join(' or ') : null;
  }
  const union = Array.isArray(field.anyOf) ? field.anyOf
    : Array.isArray(field.oneOf) ? field.oneOf : null;
  if (union) {
    const named = union
      .map((branch) => (branch && typeof branch.type === 'string' ? branch.type : null))
      .filter((t) => t && t !== 'null');
    if (named.length) return Array.from(new Set(named)).join(' or ');
  }
  if (Array.isArray(field.enum) && field.enum.length) return 'one of';
  return null;
}

/** One line saying what the tool takes, for the collapsed row. */
export function describeParameters(summary) {
  if (!summary || !summary.count) return 'Takes no parameters';
  const needed = summary.params.filter((p) => p.required).length;
  const plural = summary.count === 1 ? 'parameter' : 'parameters';
  if (!needed) return `${summary.count} optional ${plural}`;
  if (needed === summary.count) return `${summary.count} required ${plural}`;
  return `${summary.count} ${plural}, ${needed} required`;
}

// ── The field itself ────────────────────────────────────────────────────────


function elem(tag, props) {
  const node = document.createElement(tag);
  Object.assign(node, props || {});
  return node;
}

const ROW_STYLE = 'display:flex;gap:6px;align-items:center;margin-bottom:4px;';
const DROP_STYLE = 'background:transparent;border:1px solid var(--border);color:var(--fg);'
  + 'opacity:0.55;border-radius:4px;width:24px;height:24px;flex-shrink:0;cursor:pointer;'
  + 'line-height:1;font-size:14px;padding:0;';
const LINK_STYLE = 'background:none;border:none;padding:0;font-size:11px;cursor:pointer;'
  + 'color:var(--accent, var(--red));text-decoration:underline;';
const HINT_STYLE = 'font-size:11px;opacity:0.6;line-height:1.4;margin-bottom:5px;';

/**
 * One field of the MCP form, in two modes over one value.
 *
 * Fields mode is the default and is the whole point of the row: a box per
 * argument, a name and a value per variable, nothing to quote or balance.
 * JSON mode is the same field showing its storage format, for a config
 * somebody has been given to paste — switching either way carries the value
 * across, and a paste that will not parse **stays on screen** with the caret
 * under the character that stopped it. Nothing typed is ever cleared by an
 * error; that is the half of `P8-46` a validator alone does not deliver.
 *
 * `spec`: `{kind, id, hint}`. Returns `{element, read, setValue, showProblem,
 * clearProblem, mode, setMode, onChange}`.
 */
export function createMcpFieldEditor(spec) {
  const kind = spec && spec.kind === 'env' ? 'env' : 'args';
  const meta = FIELD_KINDS[kind];
  const idBase = (spec && spec.id) || `uf-mcp-${kind}`;
  const listeners = [];

  const element = elem('div', { className: 'mcp-field' });
  element.setAttribute('data-mcp-field', kind);

  const head = elem('div', {
    style: 'display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:3px;',
  });
  const label = elem('label', { className: 'settings-label', textContent: meta.label });
  label.style.cssText = 'padding:0;';
  const modeLink = elem('button', { type: 'button', textContent: 'Paste JSON' });
  modeLink.style.cssText = LINK_STYLE;
  modeLink.setAttribute('data-mcp-mode-toggle', kind);
  head.appendChild(label);
  head.appendChild(modeLink);
  element.appendChild(head);

  const hint = elem('div', { textContent: (spec && spec.hint) || '' });
  hint.style.cssText = HINT_STYLE;
  if (hint.textContent) element.appendChild(hint);

  const rowsBox = elem('div');
  rowsBox.setAttribute('data-mcp-rows', kind);
  element.appendChild(rowsBox);

  const addBtn = elem('button', { type: 'button', textContent: `+ Add ${meta.item}` });
  addBtn.className = 'admin-btn-sm';
  addBtn.style.cssText = 'font-size:11px;margin-top:2px;';
  addBtn.setAttribute('data-mcp-add', kind);
  element.appendChild(addBtn);

  const jsonBox = elem('textarea', { className: 'settings-input', rows: 3 });
  jsonBox.id = `${idBase}-json`;
  jsonBox.setAttribute('data-mcp-json', kind);
  jsonBox.style.cssText = 'display:none;width:100%;box-sizing:border-box;font-family:monospace;'
    + 'font-size:11px;resize:vertical;';
  jsonBox.placeholder = meta.example;
  element.appendChild(jsonBox);

  const problemBox = elem('div');
  problemBox.setAttribute('data-mcp-problem', kind);
  problemBox.setAttribute('role', 'alert');
  problemBox.style.cssText = 'display:none;margin-top:5px;font-size:11px;line-height:1.45;'
    + 'border-left:2px solid var(--red);padding:4px 0 4px 7px;';
  element.appendChild(problemBox);

  let mode = 'fields';

  function fire() { listeners.forEach((fn) => { try { fn(); } catch (_) {} }); }

  function makeRow(first, second) {
    const row = elem('div');
    row.style.cssText = ROW_STYLE;
    row.className = 'mcp-field-row';
    const a = elem('input', { className: 'settings-input', type: 'text', value: first || '' });
    a.style.cssText = 'flex:1;min-width:0;';
    a.placeholder = kind === 'args' ? '-y' : 'API_KEY';
    a.setAttribute('data-mcp-cell', 'key');
    row.appendChild(a);
    if (kind === 'env') {
      const b = elem('input', { className: 'settings-input', type: 'text', value: second || '' });
      b.style.cssText = 'flex:1.4;min-width:0;';
      b.placeholder = 'sk-…';
      b.setAttribute('data-mcp-cell', 'value');
      row.appendChild(b);
      b.addEventListener('input', fire);
    }
    const drop = elem('button', { type: 'button', textContent: '×' });
    drop.style.cssText = DROP_STYLE;
    drop.title = `Remove this ${meta.item}`;
    drop.setAttribute('aria-label', `Remove this ${meta.item}`);
    drop.setAttribute('data-mcp-drop', kind);
    drop.addEventListener('click', () => {
      row.remove();
      if (!rowsBox.childNodes.length) makeRow('', '');
      fire();
    });
    row.appendChild(drop);
    a.addEventListener('input', fire);
    rowsBox.appendChild(row);
    return row;
  }

  function rowValues() {
    // `Array.from`, not `NodeList.prototype.map` — a live `NodeList` has
    // `forEach` and no `map`, so this reads as working under any test shim
    // backed by arrays and throws in the browser.
    const rows = Array.from(rowsBox.querySelectorAll('.mcp-field-row'));
    return rows.map((row) => {
      const cells = row.querySelectorAll('input');
      return {
        key: String((cells[0] && cells[0].value) || '').trim(),
        value: String((cells[1] && cells[1].value) || ''),
        keyCell: cells[0] || null,
      };
    });
  }

  /** The value the rows currently describe, with the blank rows dropped. */
  function readRows() {
    const entries = rowValues();
    if (kind === 'args') {
      return { ok: true, value: entries.map((e) => e.key).filter((v) => v !== '') };
    }
    const out = {};
    for (const entry of entries) {
      if (!entry.key && !entry.value) continue;
      if (!entry.key) {
        return {
          ok: false,
          problem: {
            field: kind,
            title: 'A variable with no name',
            detail: `There is a value with nothing in its name box. Give it a name, or `
              + `remove the row with ×.`,
            focus: entry.keyCell,
          },
        };
      }
      out[entry.key] = entry.value;
    }
    return { ok: true, value: out };
  }

  function setRows(value) {
    rowsBox.replaceChildren();
    if (kind === 'args') {
      const list = Array.isArray(value) ? value : [];
      if (!list.length) makeRow('', '');
      else list.forEach((v) => makeRow(String(v), ''));
      return;
    }
    const pairs = value && typeof value === 'object' && !Array.isArray(value)
      ? Object.keys(value) : [];
    if (!pairs.length) makeRow('', '');
    else pairs.forEach((k) => makeRow(k, String(value[k])));
  }

  function currentValue() {
    if (mode === 'fields') {
      const read = readRows();
      return read.ok ? read.value : (kind === 'args' ? [] : {});
    }
    const parsed = parseJsonField(jsonBox.value, kind);
    return parsed.ok ? parsed.value : null;
  }

  function showProblem(problem) {
    problemBox.replaceChildren();
    if (!problem) { problemBox.style.display = 'none'; return; }
    const title = elem('div', { textContent: problem.title || 'That is not going to work' });
    title.style.cssText = 'font-weight:600;color:var(--red);';
    problemBox.appendChild(title);
    if (problem.detail) {
      const detail = elem('div', { textContent: problem.detail });
      detail.style.cssText = 'opacity:0.85;margin-top:2px;';
      problemBox.appendChild(detail);
    }
    if (problem.excerpt) {
      const where = elem('pre', {
        textContent: `${problem.excerpt}\n${problem.caret}`,
      });
      where.style.cssText = 'font-family:monospace;font-size:11px;margin:4px 0 0;'
        + 'white-space:pre;overflow-x:auto;opacity:0.8;';
      problemBox.appendChild(where);
    }
    if (problem.position) {
      const at = elem('div', {
        textContent: `Line ${problem.position.line}, character ${problem.position.column}.`,
      });
      at.style.cssText = 'opacity:0.6;margin-top:2px;';
      problemBox.appendChild(at);
    }
    problemBox.style.display = 'block';
    const target = problem.focus || (mode === 'json' ? jsonBox : null);
    if (target) {
      target.setAttribute('aria-invalid', 'true');
      target.style.borderColor = 'var(--red)';
      if (target.focus) target.focus();
    }
  }

  function clearProblem() {
    problemBox.replaceChildren();
    problemBox.style.display = 'none';
    jsonBox.setAttribute('aria-invalid', 'false');
    jsonBox.style.borderColor = '';
    Array.from(rowsBox.querySelectorAll('input')).forEach((input) => {
      input.setAttribute('aria-invalid', 'false');
      input.style.borderColor = '';
    });
  }

  function applyMode(next) {
    mode = next;
    const fields = next === 'fields';
    rowsBox.style.display = fields ? 'block' : 'none';
    addBtn.style.display = fields ? 'inline-block' : 'none';
    jsonBox.style.display = fields ? 'none' : 'block';
    modeLink.textContent = fields ? 'Paste JSON' : `Back to ${meta.item} boxes`;
  }

  /**
   * Switch mode, carrying the value across.
   *
   * Fields → JSON always works. JSON → fields only when the text parses;
   * when it does not the field **stays in JSON mode with the text intact**
   * and says why, because throwing away a bad paste is the failure this row
   * is about, one step removed.
   */
  function setMode(next) {
    if (next === mode) return true;
    if (next === 'json') {
      const read = readRows();
      if (!read.ok) { showProblem(read.problem); return false; }
      jsonBox.value = JSON.stringify(read.value, null, kind === 'env' ? 2 : 0);
      clearProblem();
      applyMode('json');
      return true;
    }
    const parsed = parseJsonField(jsonBox.value, kind);
    if (!parsed.ok) { showProblem(parsed.problem); return false; }
    setRows(parsed.value);
    clearProblem();
    applyMode('fields');
    return true;
  }

  modeLink.addEventListener('click', (event) => {
    if (event && event.preventDefault) event.preventDefault();
    setMode(mode === 'fields' ? 'json' : 'fields');
    fire();
  });
  addBtn.addEventListener('click', (event) => {
    if (event && event.preventDefault) event.preventDefault();
    const row = makeRow('', '');
    const first = row.querySelectorAll('input')[0];
    if (first && first.focus) first.focus();
  });
  jsonBox.addEventListener('input', fire);

  setRows(kind === 'args' ? [] : {});
  applyMode('fields');

  return {
    element,
    kind,
    mode: () => mode,
    setMode,
    onChange: (fn) => { if (typeof fn === 'function') listeners.push(fn); },
    /** `{ok, value}` or `{ok:false, problem}` — never throws, never clears. */
    read: () => (mode === 'fields' ? readRows() : parseJsonField(jsonBox.value, kind)),
    /** Best-effort current value for the live command-line preview. */
    peek: currentValue,
    setValue: (value) => {
      if (mode === 'json') jsonBox.value = JSON.stringify(value, null, kind === 'env' ? 2 : 0);
      else setRows(value);
      clearProblem();
      fire();
    },
    showProblem,
    clearProblem,
  };
}

/**
 * One row of the connected server's tool list, with its parameters behind a
 * disclosure.
 *
 * Built node by node rather than as an HTML string. That is `H01` — every
 * string here is written by a third-party MCP server — and it also closes a
 * live escaping hole in the markup this replaces: the panel put the tool's
 * description into `title="${esc(t.description)}"`, and that `esc` (declared
 * at `settings.js:5552`) replaced `&` and `<` and **not** `"`, so a
 * description containing a double quote closed the attribute early. Measured
 * 2026-09-19.
 *
 * The checkbox keeps `data-mcp-tool-name` and its `checked` state, because the
 * save path (`panel.querySelectorAll('input[type=checkbox]')`) reads exactly
 * that and this row is not the place to reorganise it.
 */
export function createMcpToolRow(tool) {
  const data = tool && typeof tool === 'object' ? tool : {};
  const name = String(data.name || '');
  const description = String(data.description || '');
  const summary = summariseSchema(data.input_schema);

  const entry = elem('div', { className: 'mcp-tool-entry' });
  entry.setAttribute('data-mcp-tool-entry', name);

  const label = elem('label');
  const box = elem('input', { type: 'checkbox', checked: !data.is_disabled });
  box.setAttribute('data-mcp-tool-name', name);
  box.dataset.mcpToolName = name;
  label.appendChild(box);

  const text = elem('span');
  const strong = elem('strong', { textContent: name });
  text.appendChild(strong);
  if (description) {
    const dim = elem('span', { textContent: ` \u2014 ${description}` });
    dim.style.cssText = 'opacity:0.5;';
    text.appendChild(dim);
  }
  label.appendChild(text);

  const toggle = elem('button', { type: 'button' });
  toggle.className = 'mcp-tool-more';
  toggle.style.cssText = 'background:none;border:none;color:var(--fg);opacity:0.55;'
    + 'font-size:10px;cursor:pointer;padding:0 2px;flex-shrink:0;white-space:nowrap;';
  toggle.setAttribute('aria-expanded', 'false');
  label.appendChild(toggle);
  entry.appendChild(label);

  const detail = elem('div');
  detail.className = 'mcp-tool-schema';
  detail.style.cssText = 'margin:0 0 6px 26px;font-size:11px;line-height:1.5;';
  // Set on its own and not inside `cssText`: the toggle reads `style.display`
  // back, and a `cssText` assignment is not guaranteed to be readable that way
  // outside a full CSSOM.
  detail.style.display = 'none';
  entry.appendChild(detail);

  const closedLabel = `${describeParameters(summary)} \u25b8`;
  toggle.textContent = closedLabel;
  toggle.title = `Show what ${name} takes and how the model names it`;

  let built = false;
  function build() {
    if (built) return;
    built = true;
    const called = elem('div');
    const lead = elem('span', { textContent: 'The model calls this ' });
    lead.style.cssText = 'opacity:0.6;';
    const qualified = elem('code', {
      textContent: String(data.qualified_name || name),
    });
    qualified.style.cssText = 'font-family:monospace;';
    called.appendChild(lead);
    called.appendChild(qualified);
    detail.appendChild(called);

    if (description && description.length > 80) {
      const full = elem('div', { textContent: description });
      full.style.cssText = 'opacity:0.75;margin-top:3px;';
      detail.appendChild(full);
    }

    if (!summary.count) {
      const none = elem('div', {
        textContent: 'This tool takes no parameters — the model calls it with nothing.',
      });
      none.style.cssText = 'opacity:0.6;margin-top:3px;';
      detail.appendChild(none);
      return;
    }
    const list = elem('div');
    list.style.cssText = 'margin-top:4px;display:flex;flex-direction:column;gap:3px;';
    for (const param of summary.params) {
      const row = elem('div');
      const pname = elem('code', { textContent: param.name });
      pname.style.cssText = 'font-family:monospace;';
      row.appendChild(pname);
      const bits = [];
      if (param.type) bits.push(param.type);
      bits.push(param.required ? 'required' : 'optional');
      const tag = elem('span', { textContent: ` ${bits.join(', ')}` });
      tag.style.cssText = `opacity:0.55;${param.required ? 'font-weight:600;' : ''}`;
      row.appendChild(tag);
      if (param.choices.length) {
        const choices = elem('div', { textContent: `one of: ${param.choices.join(', ')}` });
        choices.style.cssText = 'opacity:0.55;margin-left:10px;';
        row.appendChild(choices);
      }
      if (param.description) {
        const pdesc = elem('div', { textContent: param.description });
        pdesc.style.cssText = 'opacity:0.7;margin-left:10px;';
        row.appendChild(pdesc);
      }
      list.appendChild(row);
    }
    detail.appendChild(list);
  }

  toggle.addEventListener('click', (event) => {
    if (event && event.preventDefault) event.preventDefault();
    const open = detail.style.display !== 'none';
    if (!open) build();
    detail.style.display = open ? 'none' : 'block';
    toggle.setAttribute('aria-expanded', open ? 'false' : 'true');
    toggle.textContent = open ? closedLabel : `${describeParameters(summary)} \u25be`;
  });

  return entry;
}

/**
 * Read both stdio fields and decide whether this form may be posted.
 *
 * The decision lives here rather than in the click handler so that it can be
 * driven in a test: `static/js/settings.js` builds its form with
 * `formEl.innerHTML = ...`, and a DOM shim that stores markup as a string
 * instead of parsing it can never reach a control inside it — so a handler
 * that decides is a handler nothing can check. What stays at the call site is
 * `fd.append` and `textContent =`.
 *
 * Returns `{ok: true, args, env}` — both already JSON-encoded, ready for the
 * `FormData` the route's `Form(...)` parameters expect — or `{ok: false,
 * field, problem}` naming the **first** field that will not do, which is the
 * one to point at. Nothing is read destructively and no value is cleared: a
 * refusal leaves both fields exactly as the person left them.
 */
export function collectMcpStdioFields(argsField, envField) {
  const readArgs = argsField.read();
  if (!readArgs.ok) return { ok: false, field: 'args', problem: readArgs.problem };
  const readEnv = envField.read();
  if (!readEnv.ok) return { ok: false, field: 'env', problem: readEnv.problem };
  return {
    ok: true,
    args: JSON.stringify(readArgs.value),
    env: JSON.stringify(readEnv.value),
  };
}

export default {
  createMcpFieldEditor, parseJsonField, describeServerRefusal, formatCommandLine,
  summariseSchema, describeParameters, createMcpToolRow, collectMcpStdioFields,
};
