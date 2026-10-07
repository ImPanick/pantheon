// SPDX-License-Identifier: AGPL-3.0-or-later
// turnReasoning.js — one agent turn, one reply (`B-NEW-11`).
//
// fx2-chat (P23 round 2). `P23-04` (CHAT-M-21) kept a turn's reasoning per
// step and drew it after a reload the way the live stream drew it: each step
// in a bubble of its own, under the model's name. Measured on the seeded "Plan
// the launch week" (`1049a26`): five bubbles headed *scripted-demo* for one
// reply, two of them with a time, the tool rows cut into three threads between
// them and the answer below the first screen.
//
// A step that only thought draws no bubble of its own now. Its reasoning goes
// on to the next bubble the turn draws, into that bubble's one fold, each
// step's part in order with a rule between them (`.thinking-round`); the tool
// rows it ran go above that bubble. So a turn reads its rows, then one reply
// whose fold holds how it got there. The live stream, a resumed one, Stop and
// a reload all draw it through the functions below, on the bubbles their own
// renderers drew — the fold is the one `markdown.js` builds (`P5-08`), moved,
// never a second copy of its markup.
//
// It imports nothing: the live stream (`chat.js`), the history renderer
// (`chatRenderer.js`) and the tests that run their code under node all load it
// as it is.

/** A reply bubble's reasoning and its words, apart. (`P23-04`; moved here from
 *  `chatRenderer.js`, which imports it, so the helpers below read a bubble the
 *  way `bubbleReplyText` and `dropApprovalPlaceholder` do.) */
export function bubbleParts(bubble) {
  const body = bubble && bubble.querySelector ? bubble.querySelector('.body') : null;
  const isThinking = (n) => !!(n.classList && n.classList.contains('thinking-section'));
  const holdsThinking = (n) => !!(isThinking(n) || (n.querySelector && n.querySelector('.thinking-section')));
  // The live stream writes into a wrapper (`.stream-content`) that holds the
  // reasoning and the reply side by side: look inside it.
  let box = body;
  while (box && box.children && box.children.length === 1 && !isThinking(box.children[0])
         && holdsThinking(box.children[0])) {
    box = box.children[0];
  }
  const kept = [];
  const reply = [];
  for (const child of Array.from((box && box.childNodes) || [])) (holdsThinking(child) ? kept : reply).push(child);
  const said = reply.map((n) => n.textContent || '').join('').replace(/\s+/g, ' ').trim();
  return { body, kept, reply, said };
}

const _shown = (n) => !!n && !(n.style && n.style.display === 'none');
const _hasClass = (n, c) => !!(n && n.classList && n.classList.contains(c));

function _before(n) {
  const kids = n && n.parentNode ? n.parentNode.children : null;
  if (!kids) return null;
  const i = Array.prototype.indexOf.call(kids, n);
  return i > 0 ? kids[i - 1] : null;
}

/** A step's bubble that holds reasoning and says nothing of its own. */
export function isReasoningOnly(bubble) {
  if (!_hasClass(bubble, 'msg-ai') || _hasClass(bubble, 'agent-thinking-dots') || !_shown(bubble)) return false;
  const { kept, said } = bubbleParts(bubble);
  return kept.length > 0 && !said;
}

/** What may stand between two steps of one turn: its tool rows, a bubble that
 *  is not shown, the spinner the turn waits at. Anything else — the person's
 *  message, a note, a stop line, a banner — is read, and ends the search. */
function _betweenSteps(n) {
  return !_shown(n) || _hasClass(n, 'agent-thread') || _hasClass(n, 'agent-thinking-dots');
}

/** The step above `bubble`, in the same stretch of the turn, that only thought;
 *  `null` when there is none. */
export function reasoningAbove(bubble) {
  for (let n = _before(bubble); n; n = _before(n)) {
    if (isReasoningOnly(n)) return n;
    if (!_betweenSteps(n)) return null;
  }
  return null;
}

/** The bubble at the foot of `box` that only thought — the step whose tool
 *  rows go above it — or `null`. Hidden bubbles and the spinner are passed. */
export function reasoningAtFoot(box) {
  const kids = box && box.children ? box.children : [];
  for (let i = kids.length - 1; i >= 0; i--) {
    const n = kids[i];
    if (isReasoningOnly(n)) return n;
    if (!_shown(n) || _hasClass(n, 'agent-thinking-dots')) continue;
    return null;
  }
  return null;
}

/** The thread directly above `n` — hidden bubbles and the spinner passed — or
 *  `null`. Where a step's rows go when its bubble is the one at the foot. */
export function threadAbove(n) {
  for (let p = _before(n); p; p = _before(p)) {
    if (_hasClass(p, 'agent-thread')) return p;
    if (!_shown(p) || _hasClass(p, 'agent-thinking-dots')) continue;
    return null;
  }
  return null;
}

const ROUND_PART = 'thinking-round';

function _folds(bubble) {
  const body = bubble && bubble.querySelector ? bubble.querySelector('.body') : null;
  return body ? Array.from(body.querySelectorAll('.thinking-section')) : [];
}

function _innerOf(fold) {
  return fold && fold.querySelector ? fold.querySelector('.thinking-content-inner') : null;
}

function _partsIn(folds) {
  return folds.map((f) => { const i = _innerOf(f); return i ? String(i.innerHTML || '') : ''; })
    .filter((h) => h.trim());
}

/**
 * Move the reasoning of `from` — a step that only thought — into `to`, the
 * next bubble of the same turn, and hide `from`. The fold itself moves (its
 * header, its id, whether it is open); the steps' parts are kept as the markup
 * the renderer gave them. The time the turn started moves with it, so the one
 * bubble a turn shows says when. Returns whether anything moved.
 */
export function carryTurnReasoning(from, to) {
  if (!from || !to || from === to || !isReasoningOnly(from)) return false;
  // Only within a stretch of one turn: nothing a person reads between them.
  let n = _before(to);
  while (n && n !== from) {
    if (!_betweenSteps(n)) return false;
    n = _before(n);
  }
  if (n !== from || !to.querySelector || !to.querySelector('.body')) return false;
  const folds = _folds(from);
  const parts = from._turnReasoningParts ? from._turnReasoningParts.slice() : _partsIn(folds);
  if (!parts.length) return false;
  from.style.display = 'none';
  const stamp = from.querySelector('.role .role-timestamp');
  const role = to.querySelector('.role');
  const moved = !!(stamp && role && !role.querySelector('.role-timestamp'));
  if (moved) role.appendChild(stamp);
  // `live`: the fold is the live stream's, opened to stream into and never
  // shut (a turn that paused at a card ends that way).
  const live = !!(folds[0] && folds[0].querySelector && folds[0].querySelector('.live-think-toggle'));
  to._carriedReasoning = { from, parts, shell: folds[0], stamp: moved ? stamp : null, live };
  settleTurnReasoning(to);
  return true;
}

/**
 * Draw `bubble`'s fold as the turn's: the parts carried in, then the bubble's
 * own reasoning, one `.thinking-round` each, in the one fold. Called after
 * every render of a bubble that carries reasoning — a render replaces the
 * bubble's markup and draws its own step's fold again. A bubble that ends up
 * hidden (its step wrote nothing at all) gives the reasoning back to the bubble
 * it came from, which is shown again. Does nothing to a bubble that carries
 * nothing; returns whether it drew.
 */
export function settleTurnReasoning(bubble) {
  const carried = bubble && bubble._carriedReasoning;
  if (!carried) return false;
  const body = bubble.querySelector('.body');
  if (!body) return false;
  const shell = carried.shell;
  if (!_shown(bubble)) {
    const from = carried.from;
    delete bubble._carriedReasoning;
    if (!from || !from.querySelector) return false;
    from.style.display = '';
    const home = from.querySelector('.stream-content') || from.querySelector('.body');
    if (home && shell) home.insertBefore(shell, home.firstChild);
    const fromRole = from.querySelector('.role');
    if (carried.stamp && fromRole) fromRole.appendChild(carried.stamp);
    const inner = _innerOf(shell);
    if (inner) inner.innerHTML = carried.parts.map((p) => `<div class="${ROUND_PART}">${p}</div>`).join('');
    from._turnReasoningParts = carried.parts.slice();
    return false;
  }
  const own = _folds(bubble).filter((f) => f !== shell);
  const holds = (f) => !!(f && typeof body.contains === 'function' && body.contains(f));
  let ownParts;
  if (own.length) ownParts = _partsIn(own);
  // Settled before and not drawn over since: the fold already holds them.
  else if (holds(shell)) ownParts = bubble._ownReasoning || [];
  else ownParts = [];
  bubble._ownReasoning = ownParts;
  const parts = carried.parts.concat(ownParts);
  // A fold as the live stream left it is not what a reload draws: it is open,
  // and its header keeps that step's clock. It is shut until a fresh fold of
  // this step's own — the renderer's — takes its place. Once the person has
  // opened it again, it is theirs and stays as they left it.
  let fold = shell;
  if (fold && carried.live) {
    const reopened = carried.shut && fold.querySelector('.thinking-content.expanded');
    if (reopened) {
      carried.live = false;
    } else if (own.length) {
      fold.remove();
      fold = carried.shell = own[0];
      carried.live = false;
    } else {
      fold.querySelectorAll('.expanded').forEach((n) => n.classList.remove('expanded'));
      carried.shut = true;
    }
  }
  if (fold) {
    if (own.length) {
      if (fold !== own[0]) own[0].parentNode.insertBefore(fold, own[0]);
      own.forEach((f) => { if (f !== fold) f.remove(); });
    } else if (!holds(fold)) {
      body.insertBefore(fold, body.firstChild);
    }
    const inner = _innerOf(fold);
    if (inner) inner.innerHTML = parts.map((p) => `<div class="${ROUND_PART}">${p}</div>`).join('');
  }
  bubble._turnReasoningParts = parts;
  return true;
}

/** The bubble a turn's footer goes under when neither its step bubble nor its
 *  first one is shown: the last one it shows, from `first` to the foot. */
export function lastShownStep(first) {
  let last = null;
  const kids = first && first.parentNode ? first.parentNode.children : [];
  const start = Array.prototype.indexOf.call(kids, first);
  for (let i = Math.max(start, 0); i < kids.length; i++) {
    const n = kids[i];
    if (i > start && _hasClass(n, 'msg-user')) break;
    if (_hasClass(n, 'msg-ai') && !_hasClass(n, 'agent-thinking-dots') && _shown(n)) last = n;
  }
  return last;
}

export default {
  bubbleParts, isReasoningOnly, reasoningAbove, reasoningAtFoot, threadAbove,
  carryTurnReasoning, settleTurnReasoning, lastShownStep,
};
