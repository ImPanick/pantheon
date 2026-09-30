// SPDX-License-Identifier: AGPL-3.0-or-later
// agentTurn.js — what an agent turn draws besides its text, for every stream
// that draws one.
//
// `B918`. `P4-24` lifted a tool card's life on screen — the running card with
// its wave and its clock, the output tail and the server's clock while it runs,
// the finished card — out of the live stream's reader loop into functions at
// `chat.js`'s module scope, so a resumed stream draws what the live one draws.
// A compare pane is the third stream that draws an agent turn
// (`compare/stream.js`), and it could not reach them: `chat.js` is the page's
// chat, not a library. So it kept a copy of the card's life of its own, and the
// copy had drifted: a wave and nothing else. No clock; no arm for
// `tool_progress`, so a long command showed nothing until it finished; one
// output pane holding stdout and stderr merged, where the chat has shown two
// since `P4-19`; no screenshot. The functions live here now, and all three
// streams import them (`Law 14`).
//
// Each takes what it needs and returns what it made, as it did in `chat.js`:
// the card is the caller's, and so is knowing which card is running. What a
// pane does differently from the chat is an option, not a copy:
//
//   scroll     what to scroll once a card has changed — the chat history
//              (`ui.scrollHistory`) when it is not given; a compare pane
//              passes its own history's.
//   todoScope  where an older todo card is greyed out when a newer one lands
//              (`P6-17`) — the whole page when it is not given; a pane passes
//              its own history, so one model's plan does not grey out
//              another's.
//
// `B916`. And the spinner a new step opens with, which carries the step and
// tool-call meter (`P4-23`): a pane had no spinner after its first tool, so the
// meter had nowhere to hang for the rest of the run. It opens its steps with
// this one now, as the chat and a resumed stream do.

import uiModule from './ui.js';
import spinnerModule from './spinner.js';
import {
  buildDiffHtml,
  buildTodoCard,
  demoteSupersededTodoCards,
  safeToolScreenshotSrc,
} from './chatRenderer.js?v=20260930wavethree2';
import { applyAgentThreadNode, agentThreadContent, toolOutputPanesHtml } from './agentThread.js';

function scrollAfter(opts) {
  const scroll = opts && opts.scroll !== undefined ? opts.scroll : () => uiModule.scrollHistory();
  if (typeof scroll === 'function') scroll();
}

/** The spinner a new step opens with, carrying the meter (`P4-23`). */
export function openRoundSpinner(body, meter) {
  const roundSpinner = spinnerModule.create('Generating response', 'right', 'wave');
  body.appendChild(roundSpinner.createElement());
  if (meter) meter.attachTo(roundSpinner);
  roundSpinner.start();
  return roundSpinner;
}

/** Stop a card's wave and clock. A card still running when its stream ends
 *  would otherwise tick forever on a node nobody can see. */
export function stopCardTickers(node) {
  if (!node) return;
  if (node._waveInterval) { clearInterval(node._waveInterval); node._waveInterval = null; }
  if (node._elapsedTicker) { clearInterval(node._elapsedTicker); node._elapsedTicker = null; }
}

/** The running card for a `tool_start`, appended to `threadWrap`, with its
 *  wave and its clock going. Returns the card. */
export function startToolCard(threadWrap, json, opts = {}) {
  const cmd = json.command || '';
  const node = document.createElement('div');
  applyAgentThreadNode(node, { tool: json.tool, state: 'running', command: cmd, fullCommand: json.full_command,
    round: json.round, approved: json.approved });
  // Expand/collapse via delegated click handler (init at the bottom of `chat.js`).
  threadWrap.appendChild(node);
  // Animate the wave
  const waveEl = node.querySelector('.agent-thread-wave');
  if (waveEl) {
    const waveFrames = ['▁▂▃', '▂▃▄', '▃▄▅', '▄▅▆', '▅▆▇', '▆▅▄', '▅▄▃', '▄▃▂'];
    let waveIdx = 0;
    node._waveInterval = setInterval(() => {
      waveIdx = (waveIdx + 1) % waveFrames.length;
      waveEl.textContent = waveFrames[waveIdx];
    }, 100);
  }
  // Smooth per-second "cooking" timer — ticks every 50ms (not
  // just on the 2s backend heartbeat) so a long-running tool
  // always shows visible motion and never reads as frozen.
  //
  // `P4-02`: the anchor is corrected from the server on every
  // `tool_progress`. Starting the clock here means starting it
  // when this event was *rendered* — after the dispatch, the
  // network, and for an approved tool after however long the
  // person took to press the button — so the number shown was a
  // client-side guess that could be seconds short. Worse on a
  // resumed background stream, where `tool_start` replays and
  // restarts the clock at zero on a tool that has been running
  // for a minute.
  node._startTime = Date.now();
  node._elapsedTicker = setInterval(() => {
    const hdr2 = node.querySelector('.agent-thread-header');
    if (!hdr2) return;
    let el2 = hdr2.querySelector('.agent-thread-elapsed');
    if (!el2) {
      el2 = document.createElement('span');
      el2.className = 'agent-thread-elapsed';
      // Sits on the LEFT, right after the icon.
      const icon = hdr2.querySelector('.agent-thread-icon');
      if (icon && icon.nextSibling) hdr2.insertBefore(el2, icon.nextSibling);
      else hdr2.appendChild(el2);
    }
    const s = (Date.now() - node._startTime) / 1000;
    // Hundredths so it visibly counts sub-second (1.00, 1.05, …).
    el2.textContent = s < 60 ? `${s.toFixed(2)}s` : `${Math.floor(s / 60)}m ${(s % 60).toFixed(2).padStart(5, '0')}s`;
  }, 50);
  scrollAfter(opts);
  return node;
}

/** A long-running tool's `tool_progress` on its running card: the image
 *  progress row, the server's clock, and the tail of its output. */
export function drawToolProgress(currentToolBubble, json, opts = {}) {
  const isImageProgress = /image/i.test(String(json.tool || '')) || /image/i.test(String(json.message || ''));
  if (json.total || json.percent != null || isImageProgress) {
    // `P5-02`: the fold animates on one grid item, so anything
    // added after the card was built goes inside the wrapper.
    const content = agentThreadContent(currentToolBubble);
    if (content) {
      let progressEl = currentToolBubble.querySelector('.agent-image-progress');
      if (!progressEl) {
        progressEl = document.createElement('div');
        progressEl.className = 'agent-image-progress';
        progressEl.innerHTML = '<div class="agent-image-progress-row"><span class="agent-image-progress-label"></span><span class="agent-image-progress-value"></span></div>';
        content.appendChild(progressEl);
      }
      const step = Number(json.step || 0);
      const total = Number(json.total || 0);
      const hasExactProgress = total > 0 || json.percent != null;
      progressEl.classList.toggle('is-indeterminate', !hasExactProgress);
      const pct = Number(json.percent != null ? json.percent : (total ? (step / total) * 100 : 0));
      const bounded = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
      const label = progressEl.querySelector('.agent-image-progress-label');
      const value = progressEl.querySelector('.agent-image-progress-value');
      if (label) label.textContent = json.message || 'Editing image…';
      // `P4-02`: `elapsed_s`. The server has always sent that key
      // and this read `json.elapsed`, so the indeterminate case
      // showed an empty string rather than a number.
      if (value) value.textContent = hasExactProgress ? (total ? `${step}/${total}` : `${Math.round(bounded)}%`) : (json.elapsed_s != null ? `${json.elapsed_s}s` : '');
    }
  }
  // `P4-02`. The ticker owns the *display* — 50ms so the number
  // moves — but the server owns the *time*. Re-anchor on every
  // progress event so the smooth count is a correction of server
  // truth rather than a local stopwatch that started late and
  // drifts. `elapsed_s` has been on the wire all along; nothing
  // read it.
  if (currentToolBubble && json.elapsed_s != null) {
    const _serverElapsed = Number(json.elapsed_s);
    if (Number.isFinite(_serverElapsed) && _serverElapsed >= 0) {
      currentToolBubble._startTime = Date.now() - _serverElapsed * 1000;
    }
  }
  // Below: the live output tail.
  const tailStr = (json.tail || '').trim();
  if (tailStr) {
    let tailEl = currentToolBubble.querySelector('.agent-thread-tail');
    if (!tailEl) {
      tailEl = document.createElement('pre');
      tailEl.className = 'agent-thread-tail';
      tailEl.style.cssText = 'margin:4px 0 0;padding:6px 8px;font-size:11px;background:rgba(0,0,0,0.18);border-radius:4px;max-height:140px;overflow:auto;white-space:pre-wrap;opacity:0.85;';
      const content = agentThreadContent(currentToolBubble);   // `P5-02`
      if (content) content.appendChild(tailEl);
    }
    tailEl.textContent = tailStr;
    tailEl.scrollTop = tailEl.scrollHeight;
  }
  scrollAfter(opts);
}

/** The finished card for a `tool_output`: its clock stopped, its result, its
 *  diff and its todo list drawn, and the browser screenshot if it took one. */
export function finishToolCard(currentToolBubble, json, opts = {}) {
  // Stop wave animation + the per-second cooking ticker
  stopCardTickers(currentToolBubble);
  const ok = (json.exit_code === 0 || json.exit_code == null);
  const cmd = json.command || '';
  // `P4-19`: one builder for the panes. There were two copies
  // of this markup and both merged stdout and stderr into one
  // pane, which is how a failing command with chatty output
  // came to lose its error message.
  const outHtml = toolOutputPanesHtml(json);
  // File-write diff (write_file). `P4-01`: one renderer, shared
  // with history replay and compare mode.
  const diffHtml = buildDiffHtml(json.diff);
  // The agent's own todo list (P6-17). `todowrite` keeps a
  // structured task list and the prompt tells the model to use
  // it for multi-step work; until now it surfaced only as the
  // raw args JSON plus a text listing, both behind the fold.
  // The card goes BETWEEN the header and .agent-thread-content
  // so it needs no click (Law 15) — the raw output keeps its
  // <details> inside the fold, so nothing is taken away.
  const todoHtml = buildTodoCard(json);
  // `P4-01`: hiding the raw-JSON command next to a diff or a
  // todo card, and preserving the user's `.open` choice across
  // the rewrite, both moved into `applyAgentThreadNode` — they
  // were right here and absent from the other five copies.
  // Click handling is delegated (see init at the bottom of `chat.js`),
  // so no per-node listener is added anywhere.
  applyAgentThreadNode(currentToolBubble, {
    tool: json.tool, state: 'done', ok, round: json.round, approved: json.approved,
    command: cmd, fullCommand: json.full_command,
    output: outHtml, diff: diffHtml, todo: todoHtml,
  });
  if (todoHtml) demoteSupersededTodoCards(opts && opts.todoScope);
  // --- Render browser screenshots in tool output ---
  if (json.screenshot) {
    const contentEl = agentThreadContent(currentToolBubble);   // `P5-02`
    if (contentEl) {
      const screenshotSrc = safeToolScreenshotSrc(json.screenshot);
      if (screenshotSrc) {
        const details = document.createElement('details');
        details.className = 'agent-tool-output';
        const summary = document.createElement('summary');
        summary.textContent = 'Screenshot';
        const img = document.createElement('img');
        img.src = screenshotSrc;
        img.style.cssText = 'max-width:100%;border-radius:6px;margin-top:6px;border:1px solid var(--border)';
        details.appendChild(summary);
        details.appendChild(img);
        contentEl.appendChild(details);
      }
    }
  }
  scrollAfter(opts);
}

export default { openRoundSpinner, stopCardTickers, startToolCard, drawToolProgress, finishToolCard };
