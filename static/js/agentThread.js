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
 * @param {string} [o.output]  pre-rendered HTML
 * @param {string} [o.diff]    pre-rendered HTML
 * @param {string} [o.todo]    pre-rendered HTML
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
    ? `<pre class="agent-thread-cmd">${esc(o.command)}</pre>` : '';
  const tail = state === 'running'
    ? '<span class="agent-thread-wave">▁▂▃</span>'
    : `<span class="agent-thread-status">${o.ok ? 'done' : 'failed'}</span>`
      + '<span class="agent-thread-chevron">▶</span>';
  return '<div class="agent-thread-dot"></div>'
    + '<div class="agent-thread-header">'
    + `<span class="agent-thread-icon">${toolIcon(o.tool, state, o.ok)}</span>`
    + `<span class="agent-thread-tool">${esc(label)}</span>`
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
  node.innerHTML = agentThreadNodeHtml(o);
  return node;
}

export default { agentThreadNodeHtml, applyAgentThreadNode, toolLabel, toolIcon,
                 nodeClassName, TOOL_LABELS, TOOL_ICONS, SEARCH_ICON };
