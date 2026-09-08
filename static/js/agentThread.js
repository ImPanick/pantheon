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

/** Tool id → an icon for the running card. Anything absent gets `▶`. */
export const TOOL_ICONS = {
  'web_search': SEARCH_ICON,
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
  const stderr = typeof opts.stderr === 'string' ? opts.stderr : '';
  const merged = typeof opts.output === 'string' ? opts.output : '';
  const stdout = typeof opts.stdout === 'string' ? opts.stdout : '';
  const primary = stderr.trim() && stdout ? stdout : merged;
  let html = '';
  if (primary && primary.trim()) {
    html += '<details class="agent-tool-output"><summary>Output</summary>'
      + `<pre>${esc(primary)}</pre></details>`;
  }
  if (stderr.trim()) {
    html += '<details class="agent-tool-output agent-tool-stderr" open>'
      + '<summary>Error output (stderr)</summary>'
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

export function commandBlockHtml(command, fullCommand, tool) {
  const shown = command == null ? '' : String(command);
  if (!shown) return '';
  const full = fullCommand == null ? '' : String(fullCommand);
  const lang = CMD_LANGUAGES[String(tool || '').toLowerCase()];
  const body = (text) => (lang
    ? `<pre class="agent-thread-cmd"><code class="language-${lang}">${esc(text)}</code></pre>`
    : `<pre class="agent-thread-cmd">${esc(text)}</pre>`);
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
    + `<div class="agent-thread-content">${cmd}${o.output || ''}${diff}</div>`;
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

export default { agentThreadNodeHtml, applyAgentThreadNode, toolLabel, toolIcon,
                 nodeClassName, roundBadgeHtml, approvedBadgeHtml,
                 commandBlockHtml, highlightCommandBlocks, verifierCardOptions,
                 blockedCardOptions, toolOutputPanesHtml,
                 TOOL_LABELS, TOOL_ICONS, CMD_LANGUAGES, SEARCH_ICON,
                 APPROVED_ICON, COPY_ICON };
