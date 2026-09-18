// SPDX-License-Identifier: AGPL-3.0-or-later
// agentThread.js — the one builder for a tool card in the agent thread.
//
// `P4-01`. There were six copies of this markup: two on the live path
// (`chat.js`, running and done), one in history replay (`chatRenderer.js`), two
// in compare mode (`compare/stream.js`), and one for document writing
// (`chat.js`). No two were byte-identical, and the differences were not
// cosmetic:
//
//   * **the icon.** The live running card picks from `TOOL_ICONS` and falls
//     back to `▶`. Compare mode wrote `▶` as a literal, so a web search there
//     could never show the magnifier the same event shows in the main chat.
//   * **the diff block.** Compare mode's finished card had no slot for one,
//     so a file edit could never show what changed.
//   * **the label, three ways.** The live path had a 21-entry map of gerunds
//     (`Searching`), used only while running; every finished card in every copy
//     showed the **raw tool id** (`web_search`); and compare mode carried its
//     own five-entry map of nouns — twice, once per handler.
//   * **the click handler.** `chat.js` binds one delegated listener on
//     `document.body`, with a comment saying per-node listeners were "the
//     source of the needs-many-clicks bug". Compare mode bound one anyway, on
//     top of it, so both fired for one click and the card toggled twice —
//     clicking a tool card in compare mode did nothing at all (`B56`).
//
// The label decision, since the row asks for it to be recorded: **two forms per
// tool, not one.** A running card is a sentence about what is happening, under
// a moving wave — "Searching" is right there and "Web Search" is not. A
// finished card is a noun naming what happened — "Web Search · done" is right
// and "Searching · done" is not. So the drift was never the two vocabularies;
// it was that nobody said there were two, and that the finished cards used the
// raw tool id instead of either.
//
// `output`, `diff` and `todo` arrive as already-rendered HTML. Those three have
// their own builders (`buildTodoCard`, the diff renderer, the output details
// block) and re-implementing them here would be a seventh copy of something.
// This module owns the card *shell* and nothing else.

import uiModule from './ui.js';
import { langIcon } from './langIcons.js';

const esc = uiModule.esc;

export const SEARCH_ICON =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
  'stroke-width="2.5" stroke-linecap="round" style="vertical-align:-2px;margin-right:4px">' +
  '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';

export const RUNNING_ICON = '▶';   // ▶
export const DONE_ICON = '✓';      // ✓
export const FAILED_ICON = '✗';    // ✗

/** Tool id → what to call it while it runs, and what to call it once it has. */
export const TOOL_LABELS = {
  'web_search':       { running: 'Searching',    done: 'Web Search' },
  'bash':             { running: 'Running',      done: 'Terminal' },
  'python':           { running: 'Running',      done: 'Python' },
  'read_document':    { running: 'Reading',      done: 'Read Document' },
  'edit_file':        { running: 'Editing',      done: 'Edit File' },
  'read_file':        { running: 'Reading',      done: 'Read File' },
  'write_file':       { running: 'Writing',      done: 'Write File' },
  'create_document':  { running: 'Writing',      done: 'Create Document' },
  'edit_document':    { running: 'Editing',      done: 'Edit Document' },
  'update_document':  { running: 'Rewriting',    done: 'Update Document' },
  'suggest_document': { running: 'Reviewing',    done: 'Suggest Edits' },
  'list_files':       { running: 'Browsing',     done: 'List Files' },
  'image_gen':        { running: 'Generating',   done: 'Image' },
  'generate_image':   { running: 'Generating',   done: 'Image' },
  'manage_memory':    { running: 'Remembering',  done: 'Memory' },
  'save_memory':      { running: 'Remembering',  done: 'Memory' },
  'search_memory':    { running: 'Recalling',    done: 'Memory Search' },
  'manage_session':   { running: 'Organizing',   done: 'Sessions' },
  'deep_research':    { running: 'Researching',  done: 'Deep Research' },
  'list_models':      { running: 'Browsing',     done: 'Models' },
  'ui_control':       { running: 'Adjusting',    done: 'Interface' },
};

/**
 * `P5-04`. One glyph per tool, drawn the same way as the label beside it.
 *
 * This map had **one** entry — `web_search` — against the 21 labels above, so
 * twenty of twenty-one running cards drew the same `▶` and a thread of four
 * tools was four identical triangles. That is worse than it sounds, because
 * seven of the running labels are shared: `bash` and `python` both say
 * "Running", `read_file` and `read_document` both say "Reading", and with one
 * glyph between them **a card gave no way at all to tell which tool was
 * running** (`Law 15`).
 *
 * Inline monochrome SVG, one geometry for all of them — 14px in a 24 viewBox,
 * `stroke="currentColor"`, stroke-width 2 — so the strip inherits the theme
 * and does not need `P5-13` run on it afterwards. `currentColor` is also why
 * none of this touches `--accent`: the icon is the colour of the text it sits
 * beside, on all sixteen palettes.
 *
 * `bash` and `python` come from `langIcons.js` rather than being drawn again
 * here (`Law 14`): that module already owns "what does this language look
 * like", it is already the same stroke family, and a terminal glyph that
 * differs between a code block and a tool card is exactly the drift `P4-01`
 * spent six copies of this file fixing.
 */
const ICON_ATTRS =
  'width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
  + 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
  + 'style="vertical-align:-2px;margin-right:4px"';

/** Wrap path data in the one icon geometry this thread uses. */
function icon(body) {
  return `<svg ${ICON_ATTRS}>${body}</svg>`;
}

/** `langIcons.js`'s glyph, re-wrapped in this thread's geometry so it lines up
 *  with its neighbours. `langIcon()` returns a whole `<svg>`; only its innards
 *  are wanted here. */
function langGlyph(lang) {
  const svg = langIcon(lang, 14);
  const open = svg.indexOf('>');
  const close = svg.lastIndexOf('</svg>');
  if (open < 0 || close < 0) return '';
  return icon(svg.slice(open + 1, close));
}

const DOC_OUTLINE =
  '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
  + '<polyline points="14 2 14 8 20 8"/>';
const PENCIL =
  '<path d="M12 20h9"/>'
  + '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>';

export const TOOL_ICONS = {
  'web_search': SEARCH_ICON,
  // A terminal and a snake, from the module that already owns both.
  'bash': langGlyph('bash'),
  'python': langGlyph('python'),
  // Reading — an open book for a document, a page for a file.
  'read_document': icon('<path d="M2 4h6a3 3 0 0 1 3 3v13a2.5 2.5 0 0 0-2.5-2.5H2z"/>'
    + '<path d="M22 4h-6a3 3 0 0 0-3 3v13a2.5 2.5 0 0 1 2.5-2.5H22z"/>'),
  'read_file': icon(DOC_OUTLINE + '<line x1="8" y1="13" x2="14" y2="13"/>'
    + '<line x1="8" y1="17" x2="16" y2="17"/>'),
  // Writing — a page with a plus on it.
  'write_file': icon(DOC_OUTLINE + '<line x1="12" y1="12" x2="12" y2="18"/>'
    + '<line x1="9" y1="15" x2="15" y2="15"/>'),
  'create_document': icon(DOC_OUTLINE + '<line x1="12" y1="12" x2="12" y2="18"/>'
    + '<line x1="9" y1="15" x2="15" y2="15"/>'),
  // Editing — a pencil, on a page when the target is a file.
  'edit_file': icon('<path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6"/>'
    + '<path d="M17.5 2.5a2.1 2.1 0 0 1 3 3L12 14l-4 1 1-4z"/>'),
  'edit_document': icon(PENCIL),
  // Rewriting — the arrows that mean "again".
  'update_document': icon('<polyline points="21 4 21 10 15 10"/>'
    + '<polyline points="3 20 3 14 9 14"/>'
    + '<path d="M19.5 9A8 8 0 0 0 6 6.3L3 9"/>'
    + '<path d="M4.5 15A8 8 0 0 0 18 17.7l3-2.7"/>'),
  // Reviewing — a suggestion, which is a comment and not yet a change.
  'suggest_document': icon('<path d="M21 14a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'
    + '<polyline points="8.5 9.5 11 12 15.5 7.5"/>'),
  // Browsing a directory, and browsing a catalogue: a folder, and a grid.
  'list_files': icon('<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  'list_models': icon('<rect x="3" y="3" width="7" height="7" rx="1.5"/>'
    + '<rect x="14" y="3" width="7" height="7" rx="1.5"/>'
    + '<rect x="3" y="14" width="7" height="7" rx="1.5"/>'
    + '<rect x="14" y="14" width="7" height="7" rx="1.5"/>'),
  // Generating a picture — a framed image.
  'image_gen': icon('<rect x="3" y="4" width="18" height="16" rx="2"/>'
    + '<circle cx="8.5" cy="9.5" r="1.8"/>'
    + '<polyline points="21 16 15.5 10.5 5 20"/>'),
  'generate_image': icon('<rect x="3" y="4" width="18" height="16" rx="2"/>'
    + '<circle cx="8.5" cy="9.5" r="1.8"/>'
    + '<polyline points="21 16 15.5 10.5 5 20"/>'),
  // Memory — a store with a node in it; recall is the same store, rewound.
  'manage_memory': icon('<rect x="4" y="4" width="16" height="16" rx="3"/>'
    + '<circle cx="12" cy="12" r="2.4"/>'
    + '<line x1="12" y1="4" x2="12" y2="9.6"/>'
    + '<line x1="12" y1="14.4" x2="12" y2="20"/>'
    + '<line x1="4" y1="12" x2="9.6" y2="12"/>'
    + '<line x1="14.4" y1="12" x2="20" y2="12"/>'),
  'save_memory': icon('<rect x="4" y="4" width="16" height="16" rx="3"/>'
    + '<circle cx="12" cy="12" r="2.4"/>'
    + '<line x1="12" y1="4" x2="12" y2="9.6"/>'
    + '<line x1="12" y1="14.4" x2="12" y2="20"/>'
    + '<line x1="4" y1="12" x2="9.6" y2="12"/>'
    + '<line x1="14.4" y1="12" x2="20" y2="12"/>'),
  'search_memory': icon('<path d="M3 12a9 9 0 1 0 2.6-6.4"/>'
    + '<polyline points="3 3 3 8 8 8"/>'
    + '<polyline points="12 8 12 12 15 14"/>'),
  // Organising sessions — a stack of conversations.
  'manage_session': icon('<path d="M8 13a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2h-6l-4 3.5z"/>'
    + '<path d="M16 16v2a2 2 0 0 1-2 2H8l-4 3.5V20a2 2 0 0 1-2-2v-4"/>'),
  // Deep research — a compass, because the work is a survey and not a lookup.
  'deep_research': icon('<circle cx="12" cy="12" r="9"/>'
    + '<polygon points="15.5 8.5 13.5 13.5 8.5 15.5 10.5 10.5"/>'),
  // Adjusting the interface — sliders.
  'ui_control': icon('<line x1="4" y1="7" x2="20" y2="7"/>'
    + '<line x1="4" y1="12" x2="20" y2="12"/>'
    + '<line x1="4" y1="17" x2="20" y2="17"/>'
    + '<circle cx="9" cy="7" r="2.2"/><circle cx="15" cy="12" r="2.2"/>'
    + '<circle cx="8" cy="17" r="2.2"/>'),
};

/** What to call `tool` in `state` ('running' | 'done'). Unknown tools keep
 *  their id: a name nobody chose is better than a wrong one. */
export function toolLabel(tool, state) {
  const key = String(tool || '').toLowerCase();
  const entry = TOOL_LABELS[key];
  if (!entry) return String(tool || '');
  return entry[state === 'running' ? 'running' : 'done'] || String(tool || '');
}

/** The glyph for `tool` in `state`. Finished cards say whether it worked. */
export function toolIcon(tool, state, ok) {
  if (state === 'running') {
    return TOOL_ICONS[String(tool || '').toLowerCase()] || RUNNING_ICON;
  }
  return ok ? DONE_ICON : FAILED_ICON;
}

/**
 * `P4-11`. The badge naming the agent round a card belongs to.
 *
 * The number was on the wire from the first version of the agent loop and
 * never reached a card: every `json.round` read in `chat.js` belonged to Deep
 * Research progress instead. So a thread of nine tool cards gave no way to see
 * that they were three passes of three rather than one pass of nine.
 *
 * Returns `''` for anything that is not a positive integer. A round is 1-based
 * and a card that cannot name its round says nothing rather than guessing —
 * the document writer's own card is not a tool call and has no round at all.
 */
export function roundBadgeHtml(round) {
  const n = Number(round);
  if (!Number.isInteger(n) || n < 1) return '';
  return `<span class="agent-thread-round" title="Agent round ${n}">${n}</span>`;
}

export const APPROVED_ICON =
  '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
  'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" ' +
  'style="vertical-align:-1px;margin-right:3px">' +
  '<path d="M20 6 9 17l-5-5"/></svg>';

/**
 * `P4-17`. The completion verifier's card.
 *
 * A second model with no shared history reads the request and a record of what
 * the agent actually did, and judges whether the claim of "done" holds. Its
 * findings went into the prompt and nowhere else: the reader got the sentence
 * *"Double-checked the work and found something to fix"* and never saw what.
 *
 * Three outcomes, not two. `unavailable` is the one that matters — the check
 * raised, timed out, or answered without a verdict — and it used to be
 * indistinguishable from a pass, both in the code and on screen. A card that
 * says a second model agreed, when no second model spoke, is the worst
 * available answer.
 *
 * Same shell as every other card in the thread (`P4-01`), given a label
 * because it is not a tool call.
 */
export function verifierCardOptions(o) {
  const outcome = ({ pass: 'pass', fail: 'fail' })[o && o.outcome] || 'unavailable';
  const issues = Array.isArray(o && o.issues) ? o.issues.filter(Boolean) : [];
  const label = outcome === 'pass'
    ? 'Verified'
    : (outcome === 'fail' ? 'Verification failed' : 'Not verified');
  const rows = outcome === 'fail'
    ? issues
    : (outcome === 'unavailable'
        ? [String((o && o.detail) || 'the independent check did not run')]
        : ['An independent model reviewed the work against the request and '
           + 'found nothing to fix.']);
  const body = rows.length
    ? '<ul class="agent-thread-verifier-list">'
      + rows.map((r) => `<li>${esc(String(r))}</li>`).join('')
      + '</ul>'
    : '';
  return {
    tool: '', label, state: 'done', round: o && o.round,
    // `ok` drives the glyph and the error styling. Only a pass is a tick: a
    // check that could not run has not agreed with anything.
    ok: outcome === 'pass',
    output: body,
  };
}

/**
 * `P4-19`. The output panes under a finished tool card.
 *
 * There were two copies of this markup — the live path and history replay —
 * and both showed one pane holding stdout and stderr **merged**, joined with a
 * `STDERR:` marker and truncated as one string. So a failing command with
 * chatty output lost its error message: measured, 12,000 characters of stdout
 * and the `ValueError` on the end is gone at a 10,000-character cap. The row's
 * summary — *"the user only sees stderr when stdout is empty"* — is that, plus
 * a branch in the loop that read `stdout or stderr` and so never reached the
 * second one.
 *
 * Two panes now when there is an error, and the error's pane opens itself: it
 * is short, it is the reason the card is red, and a click to reach it is a
 * click the reader should not have to make (`Law 15`). With no error there is
 * one pane, as before, because `output` and stdout are then the same string.
 *
 * The exit code is shown when it is not zero and not absent. "Exited 0" on
 * every successful card is noise; `127` and `124` are the difference between
 * "not installed" and "killed after the timeout", and both used to read as a
 * red card and nothing else.
 */
export function toolOutputPanesHtml(o) {
  const opts = o || {};
  // `P5-08`. Every other block of text in this thread can be copied — the
  // command since `P5-07`, a code block in the reply since long before that —
  // and the one a person actually wants (the traceback, the failing test's
  // output) could only be selected by dragging inside a fold. The button
  // lives in the `<summary>` so it is reachable without opening the pane, and
  // the handler that serves it is the delegated one in `chat.js`, beside the
  // command's: a per-node listener on these cards is `B56`.
  const copyBtn = (what) =>
    `<button type="button" class="agent-tool-output-copy" title="Copy ${what}" `
    + `aria-label="Copy ${what}">${COPY_ICON}</button>`;
  const stderr = typeof opts.stderr === 'string' ? opts.stderr : '';
  const merged = typeof opts.output === 'string' ? opts.output : '';
  const stdout = typeof opts.stdout === 'string' ? opts.stdout : '';
  const primary = stderr.trim() && stdout ? stdout : merged;
  let html = '';
  if (primary && primary.trim()) {
    html += '<details class="agent-tool-output"><summary>Output'
      + copyBtn('output') + '</summary>'
      + `<pre>${esc(primary)}</pre></details>`;
  }
  if (stderr.trim()) {
    html += '<details class="agent-tool-output agent-tool-stderr" open>'
      + '<summary>Error output (stderr)' + copyBtn('error output') + '</summary>'
      + `<pre>${esc(stderr)}</pre></details>`;
  }
  const code = Number(opts.exit_code);
  if (opts.exit_code != null && Number.isFinite(code) && code !== 0) {
    html += `<div class="agent-thread-exit-code">Exited ${esc(String(code))}`
      + (code === 124 ? ' (timed out)' : '') + '</div>';
  }
  return html;
}

/**
 * `P4-20`. The card for a call the policy refused.
 *
 * A blocked call never runs, so it gets no `tool_start` — and `tool_start` is
 * the only event that creates a card. The refusal then arrived as a
 * `tool_output` with nowhere to go: with no card open the call **vanished from
 * the thread**, and with an earlier card still open in the same round it
 * **overwrote that one**, so a command that had succeeded silently turned into
 * a blocked one and the successful call disappeared.
 *
 * It reads as a refusal and not as a failure, because those are different
 * things: a failed command was attempted, and this one was not. The reason is
 * the whole content — the tool's name and the command line above it are what
 * was refused, and the reason is why.
 */
export function blockedCardOptions(o) {
  const reason = String((o && o.reason) || 'refused by the current tool policy');
  return {
    tool: (o && o.tool) || '',
    label: `${toolLabel((o && o.tool) || '', 'done')} · blocked`,
    state: 'done',
    ok: false,
    round: o && o.round,
    command: (o && o.command) || '',
    fullCommand: o && o.full_command,
    output: `<div class="agent-thread-blocked-reason">${esc(reason)}</div>`,
  };
}

/**
 * `P4-12`. The badge on an action the user personally authorised.
 *
 * The flag has been on the wire on four events since exact approvals shipped
 * and nothing ever read it, so the one action in a thread that a person stopped
 * and allowed by hand looked exactly like a routine call — the same icon, the
 * same label, the same everything.
 *
 * It draws only for `true`, and `true` now means what it says: the backend
 * sends it on the result card only when the action actually ran under the
 * approval. A grant the replay's pre-check or the dispatcher's `claim()`
 * refused reports `false`, because a badge asserting *authority* over an action
 * that was blocked is worse than no badge at all.
 */
export function approvedBadgeHtml(approved) {
  if (approved !== true) return '';
  return '<span class="agent-thread-approved" title="You approved this action">'
    + APPROVED_ICON + 'approved</span>';
}

/**
 * `P4-09`. The command block, and the way back to the arguments behind it.
 *
 * `command` is what the card has always shown, and for two kinds of action it
 * is not the action: a document tool sends its **first line, capped at 80
 * characters**, and the approval replay sends the first 240 of the sealed
 * content. The rest was on `tool_start` only — live, once, and gone the moment
 * the tool finished, because the result event that rewrites the card never
 * carried it. After a reload it did not exist at all.
 *
 * The expansion is a `<details>`, not a button: the fold handler is one
 * delegated listener bound to `.agent-thread-header` (`chat.js`), this sits in
 * `.agent-thread-content`, and adding a listener of its own is the bug `B56`
 * was. `<details class="agent-tool-output">` is already how this card folds its
 * output, so this is that shape and not a second one (`Law 14`).
 *
 * The summary states the length, because a reader deciding whether to open
 * something deserves to know whether it is four lines or four hundred — and
 * because when the backend had to cap it, the cap says so in the text itself.
 */
export const COPY_ICON =
  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<rect x="9" y="9" width="13" height="13" rx="2"/>' +
  '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';

const COPY_BUTTON =
  '<button type="button" class="agent-thread-cmd-copy" title="Copy command" '
  + 'aria-label="Copy command">' + COPY_ICON + '</button>';

/** Tool id → the highlight.js language its command is written in.
 *
 *  Deliberately two entries. For `bash` and `python` the command *is* code in
 *  that language and colouring it is a straight win; for everything else the
 *  "command" is a path, a query, or a JSON argument blob, and guessing wrong
 *  paints a filename in string-literal green and reads as a bug. No entry means
 *  a plain `<pre>`, which is what every card showed before this row.
 */
export const CMD_LANGUAGES = {
  'bash': 'bash',
  'python': 'python',
};

/**
 * `P5-08`. A JSON argument blob, printed so a person can read it.
 *
 * Most tools send their arguments as one line of minified JSON, and one line
 * of minified JSON is not a thing anyone reads — `{"path":"/etc/hosts",
 * "content":"…","mode":"append"}` wraps across four lines of the card with no
 * structure at all. Pretty-printed it is four labelled lines.
 *
 * This does **not** re-open the question `P5-07` settled. That row kept
 * highlighting to `bash` and `python` because guessing a language paints a
 * filename in string-literal green, and a wrong colour reads as a bug. There
 * is no guess here: the text either parses as a JSON object or array or it
 * does not, and only then is it called JSON. A truncated blob — the document
 * tools send the first 80 characters, the approval replay the first 240 —
 * fails to parse and is shown exactly as it was before.
 *
 * Returns `null` when the text is not JSON, which is the signal to fall back.
 */
export function prettyJson(text) {
  const t = String(text == null ? '' : text).trim();
  // One gate, on purpose. A `startsWith('{')` early-out was here too and it
  // made the real check below unreachable — anything that starts with `{` or
  // `[` and parses *is* an object or an array — so neither guard could be
  // mutated on its own and the pair tested as dead code. Cheap is not worth a
  // second rule that hides the first.
  let parsed;
  try {
    parsed = JSON.parse(t);
  } catch (_err) {
    return null;   // truncated, or not JSON at all
  }
  // The gate, and the only one: an argument blob is an object or an array.
  // `42` and `"a string"` are valid JSON and are not arguments, and calling
  // them JSON would paint a bare path in string-literal green the first time
  // one happened to parse — which is the exact failure `P5-07` chose its two
  // languages to avoid.
  if (parsed === null || typeof parsed !== 'object') return null;
  // Returned even when it comes back unchanged, so a blob that arrived
  // already laid out is still *named* JSON. Short-circuiting here made the
  // highlight depend on how the sender happened to format it, which is a
  // difference a reader can see and cannot explain.
  return JSON.stringify(parsed, null, 2);
}

export function commandBlockHtml(command, fullCommand, tool) {
  const shown = command == null ? '' : String(command);
  if (!shown) return '';
  const full = fullCommand == null ? '' : String(fullCommand);
  const mapped = CMD_LANGUAGES[String(tool || '').toLowerCase()];
  const body = (text) => {
    const pretty = prettyJson(text);
    const lang = pretty ? 'json' : mapped;
    const shownText = pretty || text;
    return lang
      ? `<pre class="agent-thread-cmd"><code class="language-${lang}">${esc(shownText)}</code></pre>`
      : `<pre class="agent-thread-cmd">${esc(shownText)}</pre>`;
  };
  const block = '<div class="agent-thread-cmd-block">' + body(shown) + COPY_BUTTON + '</div>';
  if (!full || full === shown) return block;
  return block
    + '<details class="agent-thread-cmd-full"><summary>'
    + `Full arguments (${full.length.toLocaleString('en-US')} characters)`
    + `</summary>${body(full)}</details>`;
}

/** Syntax-highlight any command block in `node`, if highlight.js is loaded.
 *
 *  Runs after the markup is in the DOM because that is what `hljs` needs, and
 *  matches the `pre code:not(.hljs)` sweep the rest of the app already does
 *  rather than introducing a second way to highlight (`Law 14`). Everything is
 *  optional: `hljs` is a page-level global this module does not import, a card
 *  can be built in a test with no DOM at all, and a highlighter that throws on
 *  one odd command may not take the tool card down with it — a plain `<pre>` is
 *  the correct fallback and is exactly what the card showed before this row.
 */
export function highlightCommandBlocks(node) {
  if (typeof window === 'undefined' || !window.hljs) return;
  if (!node || typeof node.querySelectorAll !== 'function') return;
  node.querySelectorAll('.agent-thread-cmd code:not(.hljs)').forEach((block) => {
    try {
      window.hljs.highlightElement(block);
    } catch (err) {
      console.warn('[agentThread] command highlight failed; showing it plain', err);
    }
  });
}

/** The className an `.agent-thread-node` carries in `state`. */
export function nodeClassName(state, ok) {
  if (state === 'running') return 'agent-thread-node running';
  return 'agent-thread-node' + (ok ? '' : ' error');
}

/**
 * The card's inner HTML.
 *
 * @param {object} o
 * @param {string} o.tool     tool id, used for the label and the icon
 * @param {string} [o.label]  an explicit label, for a card that is not a tool
 *                            call (the document writer's own thread)
 * @param {string} o.state    'running' | 'done'
 * @param {boolean} [o.ok]    finished cards only: did it succeed
 * @param {string} [o.command] the command line, escaped and wrapped here
 * @param {string} [o.fullCommand] the untruncated arguments; drawn behind a
 *                            `<details>` when it differs from `command`
 * @param {string} [o.output]  pre-rendered HTML
 * @param {string} [o.diff]    pre-rendered HTML
 * @param {string} [o.todo]    pre-rendered HTML
 * @param {number} [o.round]   1-based agent round; anything else draws no badge
 * @param {boolean} [o.approved] exactly `true` badges the card as authorised
 *
 * A `diff` or a `todo` suppresses the command line. For a file edit the
 * "command" is the raw JSON arguments, which is redundant beside the diff; for
 * a todowrite it *is* the task list, which the card above already formats. The
 * live path did this and compare mode did half of it — it has no diff slot, so
 * it only ever suppressed for a todo.
 */
export function agentThreadNodeHtml(o) {
  const state = o.state === 'running' ? 'running' : 'done';
  const label = o.label !== undefined && o.label !== null
    ? String(o.label)
    : toolLabel(o.tool, state);
  const todo = o.todo || '';
  const diff = o.diff || '';
  const cmd = (o.command && !todo && !diff)
    ? commandBlockHtml(o.command, o.fullCommand, o.tool) : '';
  const tail = state === 'running'
    ? '<span class="agent-thread-wave">▁▂▃</span>'
    : `<span class="agent-thread-status">${o.ok ? 'done' : 'failed'}</span>`
      + '<span class="agent-thread-chevron">▶</span>';
  return '<div class="agent-thread-dot"></div>'
    + '<div class="agent-thread-header">'
    + `<span class="agent-thread-icon">${toolIcon(o.tool, state, o.ok)}</span>`
    + `<span class="agent-thread-tool">${esc(label)}</span>`
    + approvedBadgeHtml(o.approved)
    + roundBadgeHtml(o.round)
    + tail
    + '</div>'
    + todo
    + '<div class="agent-thread-content">'
    + `<div class="agent-thread-content-inner">${cmd}${o.output || ''}${diff}</div>`
    + '</div>';
}

/**
 * `P5-02`. Where a caller appends something to an open card.
 *
 * The fold animates on `grid-template-rows: 0fr -> 1fr`, and that only works
 * with **one** grid item: a second child lands in an implicit `auto` row and
 * stays visible while the card is shut. So `.agent-thread-content` now holds a
 * single wrapper, and anything added after the card was built goes inside it.
 *
 * Three callers in `chat.js` append here — the screenshot pane, the image
 * progress row and the browser-step block — and all three found the box with
 * `querySelector('.agent-thread-content')`. Pointing them at a helper rather
 * than at a second class name means the next one cannot get it wrong, and the
 * fallback covers a card built by an older cached module (the buster contract
 * makes that unlikely, not impossible).
 */
export function agentThreadContent(node) {
  if (!node || typeof node.querySelector !== 'function') return null;
  return node.querySelector('.agent-thread-content-inner')
    || node.querySelector('.agent-thread-content');
}

/**
 * `P5-08`. Open or shut every card in one thread.
 *
 * A nine-tool round is nine folds, and reading what the agent actually did
 * meant nine clicks — then nine more to put it back. The control says
 * "Expand all" and "Collapse all" in words rather than drawing a symbol,
 * because a glyph here is a thing somebody has to be taught (`Law 15`), and
 * the words also tell a first-time reader that these cards open at all, which
 * the collapsed chevron on its own does not.
 *
 * It is drawn by one function called from one observer rather than by the
 * three places that build an `.agent-thread` (live, history replay, compare),
 * because three copies of a control is how this file came to need `P4-01`.
 * Threads of a single card do not get one: "expand all" over one thing is
 * noise, and the chevron beside it already does the job.
 */
export const EXPAND_ALL_LABEL = 'Expand all';
export const COLLAPSE_ALL_LABEL = 'Collapse all';

/** True when every card in `thread` is open (and there is at least one). */
export function threadIsAllOpen(thread) {
  if (!thread || typeof thread.querySelectorAll !== 'function') return false;
  const nodes = [...thread.querySelectorAll('.agent-thread-node')];
  return nodes.length > 0 && nodes.every((n) => n.classList.contains('open'));
}

/** Put the control's label in step with what the thread is actually showing.
 *  A button reading "Expand all" over an already-open thread is the `Law 15`
 *  failure this whole row is about, one level up. */
export function syncThreadToggleAll(thread) {
  const btn = thread && typeof thread.querySelector === 'function'
    ? thread.querySelector('.agent-thread-expand-all') : null;
  if (!btn) return null;
  const allOpen = threadIsAllOpen(thread);
  btn.textContent = allOpen ? COLLAPSE_ALL_LABEL : EXPAND_ALL_LABEL;
  btn.setAttribute('aria-expanded', allOpen ? 'true' : 'false');
  return btn;
}

/** Add the control to `thread` when it has earned one, and keep it current. */
export function ensureThreadToggleAll(thread) {
  if (!thread || typeof thread.querySelectorAll !== 'function') return null;
  const count = thread.querySelectorAll('.agent-thread-node').length;
  let bar = thread.querySelector('.agent-thread-toolbar');
  if (count < 2) {
    if (bar && bar.remove) bar.remove();
    return null;
  }
  if (!bar) {
    const doc = thread.ownerDocument || (typeof document !== 'undefined' ? document : null);
    if (!doc) return null;
    bar = doc.createElement('div');
    bar.className = 'agent-thread-toolbar';
    const btn = doc.createElement('button');
    btn.type = 'button';
    btn.className = 'agent-thread-expand-all';
    btn.textContent = EXPAND_ALL_LABEL;
    btn.setAttribute('aria-expanded', 'false');
    bar.appendChild(btn);
    thread.insertBefore(bar, thread.firstChild);
  }
  syncThreadToggleAll(thread);
  return bar;
}

/** Open or shut every card in `thread`; returns what it did. */
export function toggleThreadAll(thread) {
  if (!thread || typeof thread.querySelectorAll !== 'function') return null;
  const open = !threadIsAllOpen(thread);
  thread.querySelectorAll('.agent-thread-node').forEach((n) => {
    n.classList.toggle('open', open);
  });
  syncThreadToggleAll(thread);
  return open ? 'expanded' : 'collapsed';
}

/** Set both the className and the markup, so a caller cannot drift on one.
 *  Fold/expand is a single delegated listener on `document.body` (`chat.js`);
 *  nothing here may add a per-node one — two listeners toggle twice and the
 *  card does not move (`B56`). */
export function applyAgentThreadNode(node, o) {
  // Carry `open` across the rewrite. Expanding a running tool used to collapse
  // it the moment the result landed, and the live path fixed that by rebuilding
  // the className by hand — one caller out of six. It belongs here, where every
  // caller gets it.
  const wasOpen = node.classList && node.classList.contains('open');
  node.className = nodeClassName(o.state === 'running' ? 'running' : 'done', o.ok)
    + (wasOpen ? ' open' : '');
  // `P4-11`. Same reason as `open`: a card is built twice, once from
  // `tool_start` and once from `tool_output`, and the second event deciding
  // the badge means the badge can vanish when the tool finishes. Remember the
  // round the card was opened with and use it when the rewrite does not bring
  // one, so a card that showed a round keeps it.
  const round = Number.isInteger(Number(o.round)) && Number(o.round) >= 1
    ? Number(o.round) : node._agentRound;
  if (round) node._agentRound = round;
  node.innerHTML = agentThreadNodeHtml(round === o.round ? o : { ...o, round });
  highlightCommandBlocks(node);
  return node;
}

export default { agentThreadNodeHtml, applyAgentThreadNode, agentThreadContent,
                 ensureThreadToggleAll, toggleThreadAll, syncThreadToggleAll,
                 threadIsAllOpen, prettyJson,
                 toolLabel, toolIcon,
                 nodeClassName, roundBadgeHtml, approvedBadgeHtml,
                 commandBlockHtml, highlightCommandBlocks, verifierCardOptions,
                 blockedCardOptions, toolOutputPanesHtml,
                 TOOL_LABELS, TOOL_ICONS, CMD_LANGUAGES, SEARCH_ICON,
                 APPROVED_ICON, COPY_ICON };
