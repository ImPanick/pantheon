// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/chatStream.js
// SSE event handlers extracted from chat.js handleChatSubmit
// Handles: ui_control events, background stream management, mid-run steering

import uiModule from './ui.js';
import Storage from './storage.js';
import themeModule from './theme.js';
import markdownModule from './markdown.js';
import sessionModule from './sessions.js';
import documentModule from './document.js?v=20260815approvalsave1';

// Tool approvals are control-plane submits for the current chat. chat.js
// deliberately leaves the composer untouched, then programmatically clicks the
// shared send button after it records the sealed approval id/decision. That
// button is polymorphic: with an empty composer it can mean New chat or Record
// voice instead of Send. Intercept only the programmatic approval click and
// route it through the form submit path, which already reaches chat.js directly.
document.addEventListener('pantheon:tool-approval', () => {
  const sendButton = document.querySelector('.send-btn');
  const chatForm = document.getElementById('chat-form');
  if (!sendButton || !chatForm) return;

  const interceptApprovalClick = (event) => {
    // A real user click must retain the normal send/new-chat/STT behavior.
    if (event.isTrusted) return;
    sendButton.removeEventListener('click', interceptApprovalClick, true);
    event.preventDefault();
    event.stopImmediatePropagation();
    if (chatForm.requestSubmit) chatForm.requestSubmit();
    else chatForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  };

  sendButton.addEventListener('click', interceptApprovalClick, true);
  // Fail-safe cleanup if the approval continuation never reaches its deferred
  // synthetic click (for example because the surrounding view is torn down).
  setTimeout(() => {
    sendButton.removeEventListener('click', interceptApprovalClick, true);
  }, 60000);
}, true);

/* ══ Mid-run steering (P6-18) ══════════════════════════════════════════════
 *
 * Two verbs, not one. **Enter queues** — the message waits until the current
 * response has finished, which is `chat.js` `_queueAgentRequest` and is not
 * touched here. **Cmd/Ctrl+Enter steers** — the message is handed to the run
 * that is *already going*.
 *
 * What steering can honestly promise, read off the backend rather than wished
 * for: `src/agent_loop.py` binds one provider request per round and cannot
 * interrupt a round that is already streaming, so a steer lands at the agent's
 * **next step**, not instantly. Every string in this file says "next step" for
 * that reason — see the `Mid-run steering` block in `src/agent_loop.py`.
 *
 * `Law 15`: a key binding nobody can discover is not a feature. So the same
 * intent gets a **visible bar** above the composer for as long as the agent is
 * working, and that bar names both verbs and both keys. It is drawn from here
 * rather than from `static/index.html` only because this module owns the
 * feature; the markup is inert until a stream is actually in flight.
 *
 * Capability probe: the transport is `POST /api/chat/steer/{session_id}`. Until
 * that route exists the probe fails, **nothing is drawn, and Cmd/Ctrl+Enter
 * keeps its current behaviour** — no dead control, no stolen key binding, no
 * promise the server cannot keep (`Law 13`).
 */

const STEER_API_BASE = window.location.origin;

let _steerSupported = null;      // null = not probed yet, then true | false
let _steerProbeInFlight = false;
let _steerBar = null;            // the visible affordance, while a run is live
let _steerSentList = null;       // <ul> of steers accepted for this run
let _steerBoundSessionId = '';   // the session the bar currently belongs to
let _steerKeyBound = false;
let _steerStyleInjected = false;
// Set the first time a `steer_applied` event actually reaches this module. It
// is the difference between "the confirmation channel is live and this steer
// missed the run" and "we have no confirmation channel, so say nothing".
let _steerConfirmSeen = false;
// `B14`. null until THIS run says what it is; then true | false. The capability
// probe answers a per-BUILD question and `_steerChatModeOnly` answers a
// per-COMPOSER one, and steerability is neither: the server decides it per run
// (`routes/chat_routes.py` `_stream_is_steerable`) and now announces the same
// value it gates the refusal on. Null keeps today's behaviour exactly — an old
// server never sends the event and the composer's guess stands — so nothing
// that works now stops working.
let _steerRunAnswer = null;
// `B81`. null until the composer says, then true | false. The PROVISIONAL half
// of the same question `_steerRunAnswer` answers authoritatively — not a second
// fact and not a second transport, just the existing client-side guess moved to
// where its terms are readable and delivered on the event that already
// announces the turn (`pantheon:chat-busy-change`). Held until the run ends, so
// a later re-announcement of the same busy state (`setStreamingState`) cannot
// erase it; reset to null there, because the next run is a new question.
let _steerComposerAnswer = null;
// Whether this page's `chat.js` announces verdicts at all. `B14` established
// that a second `active` edge with no `inactive` between them is a new run and
// must reset the run's own answer, because on a build with no verdicts those
// edges are all there is. `B81` gives the send path a marker the
// re-announcements do not carry, so the two can finally be told apart — but
// only once one verdict has actually been seen. Until then, `B14`'s rule stands
// unchanged.
let _steerVerdictsSeen = false;

const STEER_PENDING_TEXT = ' — lands at the next step';

const _steerIsMac = (() => {
  try {
    const p = (navigator.userAgentData && navigator.userAgentData.platform)
      || navigator.platform || '';
    return /mac|iphone|ipad|ipod/i.test(p);
  } catch (_) { return false; }
})();
const STEER_KEY_LABEL = _steerIsMac ? '⌘⏎' : 'Ctrl+⏎';

/** Same predicate app.js uses to decide the composer is talking to a live run
 *  (`_isForegroundChatBusy`). Reused verbatim rather than re-derived so the two
 *  can never disagree about whether Enter queues. Note its deliberate ~1.2s
 *  tail after a stream ends: a steer sent inside that tail is refused by the
 *  server (no active run) and falls back to the queue, which is correct. */
function _steerChatBusy() {
  try {
    const sendBtn = document.querySelector('.send-btn');
    return !!window.__pantheonChatBusy
      || Date.now() < (window.__pantheonChatBusyUntil || 0)
      || !!document.querySelector('.send-btn[data-mode="streaming"], .send-btn.send-pending')
      || !!(sendBtn && (sendBtn.title || '').toLowerCase().includes('stop'));
  } catch (_) { return false; }
}

function _steerSessionId() {
  try { return (sessionModule && sessionModule.getCurrentSessionId()) || ''; }
  catch (_) { return ''; }
}

/**
 * True when this turn is a plain chat turn — no agent loop, so no rounds.
 *
 * Unknown counts as steerable: the server is the authority and refuses what it
 * cannot deliver, so a missing getter costs one honest refusal rather than
 * silently hiding a working control.
 *
 * `B14`: this is a GUESS, and it is only consulted until the run says otherwise.
 * It reads the composer's mode toggle, which is not what the server decides the
 * turn is — see `_steerRunAnswer`.
 */
function _steerChatModeOnly() {
  try {
    const get = window.__pantheonGetChatMode;
    return typeof get === 'function' && get() === 'chat';
  } catch (_) {
    return false;
  }
}

/**
 * Does anything the CLIENT can see say this turn cannot take a steer? (`B81`)
 *
 * `P6-18` asked one term — is the composer in chat mode — and drew the bar
 * whenever the answer was no. That left a research turn drawing a bar for the
 * ~880 lines of composer setup plus a network round trip it takes
 * `stream_steerable` to contradict it, because research is sent in AGENT mode:
 * the one term it read says nothing about the case. `chat.js` now evaluates the
 * terms it can actually see — the mode AND the research toggle, which is still
 * checked at send-path entry and cleared just before the POST — and ships the
 * verdict on the busy edge that raises the bar.
 *
 * `_steerChatModeOnly` stays as the fallback rather than being deleted
 * (`Law 1`): the busy event has other dispatchers' worth of history and any
 * edge that arrives without a verdict must behave exactly as it does today.
 *
 * Whatever this says, the run overrules it — `handleStreamSteerable` runs in
 * both directions, so a turn the composer wrote off still gets its bar if the
 * server says it is steerable.
 */
function _steerComposerSaysNo() {
  if (_steerComposerAnswer !== null) return _steerComposerAnswer === false;
  return _steerChatModeOnly();
}

function _steerComposer() {
  return document.getElementById('message');
}

/** Theme tokens only — `--accent` is never defined at `:root` (D-2026-08-26-03),
 *  so every accent use carries the `var(--red)` fallback the rest of the app
 *  uses. Injected from JS because this module does not own `static/style.css`. */
function _injectSteerStyle() {
  if (_steerStyleInjected) return;
  _steerStyleInjected = true;
  const style = document.createElement('style');
  style.textContent = `
.steer-bar{display:flex;align-items:center;flex-wrap:wrap;gap:8px;
  margin:0 0 6px;padding:6px 10px;border-radius:8px;font-size:11.5px;
  border:1px solid color-mix(in srgb, var(--accent, var(--red)) 34%, var(--border));
  background:color-mix(in srgb, var(--accent, var(--red)) 8%, var(--panel));
  color:var(--fg);}
.steer-bar-title{display:inline-flex;align-items:center;gap:5px;font-weight:600;
  color:var(--accent, var(--red));white-space:nowrap;}
.steer-bar-dot{width:6px;height:6px;border-radius:50%;
  background:var(--accent, var(--red));animation:steer-pulse 1.4s ease-in-out infinite;}
@keyframes steer-pulse{0%,100%{opacity:.35}50%{opacity:1}}
@media (prefers-reduced-motion: reduce){.steer-bar-dot{animation:none;opacity:.8}}
.steer-bar-hint{color:var(--color-muted);flex:1;min-width:180px;}
.steer-bar-hint kbd{font:inherit;font-weight:600;color:var(--fg);
  border:1px solid var(--border);border-radius:4px;padding:0 4px;}
.steer-bar-btn{cursor:pointer;font:inherit;font-weight:600;white-space:nowrap;
  padding:3px 10px;border-radius:6px;color:var(--bg);
  border:1px solid var(--accent, var(--red));
  background:var(--accent, var(--red));}
.steer-bar-btn:disabled{cursor:default;opacity:.45;}
.steer-sent{list-style:none;margin:0;padding:0;flex-basis:100%;
  display:flex;flex-direction:column;gap:3px;}
.steer-sent li{color:var(--color-muted);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;}
.steer-sent li strong{color:var(--fg);font-weight:500;}
`;
  document.head.appendChild(style);
}

function _removeSteerBar() {
  if (_steerBar && _steerBar.parentNode) _steerBar.parentNode.removeChild(_steerBar);
  _steerBar = null;
  _steerSentList = null;
  _steerBoundSessionId = '';
}

/** Draw the affordance directly above the composer, as a sibling of
 *  `.chat-input-bar` (the same place `#attach-strip` already sits) so it never
 *  fights the composer's own layout. */
function _steerEl(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function _ensureSteerBar() {
  if (_steerSupported !== true) return null;
  const inputBar = document.querySelector('.chat-input-bar');
  if (!inputBar || !inputBar.parentNode) return null;
  if (_steerBar && _steerBar.isConnected) return _steerBar;
  _injectSteerStyle();
  const bar = _steerEl('div', 'steer-bar');
  bar.setAttribute('role', 'status');

  const title = _steerEl('span', 'steer-bar-title');
  title.appendChild(_steerEl('span', 'steer-bar-dot'));
  title.appendChild(_steerEl('span', null, 'Agent is working'));
  bar.appendChild(title);

  // Both verbs, both keys, in the one place a person is already looking while
  // the agent works. This sentence IS the Law 15 answer for this feature.
  const hint = _steerEl('span', 'steer-bar-hint');
  hint.appendChild(_steerEl('span', null, 'Change course: type it and press '));
  hint.appendChild(_steerEl('kbd', null, STEER_KEY_LABEL));
  hint.appendChild(_steerEl('span', null, ' — it reaches the agent at its next step. '));
  hint.appendChild(_steerEl('kbd', null, '⏎'));
  hint.appendChild(_steerEl('span', null, ' queues it for after this response instead.'));
  bar.appendChild(hint);

  const btn = _steerEl('button', 'steer-bar-btn', 'Steer now');
  btn.setAttribute('type', 'button');
  btn.addEventListener('click', (e) => {
    if (e && e.preventDefault) e.preventDefault();
    const input = _steerComposer();
    const text = ((input && input.value) || '').trim();
    if (!text) {
      try { uiModule.showToast && uiModule.showToast('Type the change first, then Steer now'); } catch (_) {}
      if (input && input.focus) input.focus();
      return;
    }
    submitSteer(text);
  });
  bar.appendChild(btn);

  const sent = _steerEl('ul', 'steer-sent');
  bar.appendChild(sent);

  inputBar.parentNode.insertBefore(bar, inputBar);
  _steerBar = bar;
  _steerSentList = sent;
  _steerBoundSessionId = _steerSessionId();
  return bar;
}

/** One accepted steer, echoed where the user can see it. Built from text nodes
 *  rather than an innerHTML string so the user's own words can never be markup. */
function _noteSteerSent(text) {
  const bar = _ensureSteerBar();
  if (!bar || !_steerSentList) return;
  const li = document.createElement('li');
  const shown = text.length > 120 ? text.slice(0, 120) + '…' : text;
  li.appendChild(_steerEl('span', null, '↪ '));
  li.appendChild(_steerEl('strong', null, shown));
  li.appendChild(_steerEl('span', 'steer-sent-state', STEER_PENDING_TEXT));
  _steerSentList.appendChild(li);
}

/** How many accepted steers are still waiting for a `steer_applied`. */
function _steerPendingCount() {
  if (!_steerSentList) return 0;
  let n = 0;
  _steerSentList.querySelectorAll('.steer-sent-state').forEach((el) => {
    if ((el.textContent || '') === STEER_PENDING_TEXT) n++;
  });
  return n;
}

/** Hand the text to the queue instead, and say so. The queue is `chat.js`'s and
 *  stays the only queue (`Law 14`); this never builds a second one. */
function _queueInsteadOfSteering(reason) {
  let queued = false;
  try {
    const cm = window.chatModule;
    queued = !!(cm && cm.queueStreamingComposerRequest && cm.queueStreamingComposerRequest());
  } catch (_) { queued = false; }
  try {
    if (queued) {
      uiModule.showToast && uiModule.showToast(reason + ' — queued for after this response instead');
    } else {
      // The queue declined too (nothing is streaming any more). The text was
      // never cleared, so say where it is rather than leaving the user guessing.
      uiModule.showError && uiModule.showError(
        reason + ' — your message is still in the composer, press Enter to send it');
    }
  } catch (_) {}
  return queued;
}

function _clearComposerAfterSteer(input) {
  if (!input) return;
  input.value = '';
  try { input.dispatchEvent(new Event('input', { bubbles: true })); } catch (_) {}
  try { if (uiModule.autoResize) uiModule.autoResize(input); } catch (_) {}
  try { window._updateSendBtnIcon && window._updateSendBtnIcon(); } catch (_) {}
}

/**
 * Ask the server whether this build can steer, once per page load.
 * A missing route is the expected answer on a build where the transport has
 * not landed: it resolves `false`, nothing is drawn and no key is rebound.
 */
async function probeSteerSupport() {
  if (_steerSupported !== null || _steerProbeInFlight) return _steerSupported;
  const sid = _steerSessionId();
  if (!sid) return null;
  _steerProbeInFlight = true;
  try {
    const res = await fetch(`${STEER_API_BASE}/api/chat/steer/${encodeURIComponent(sid)}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ probe: true }),
    });
    // 404/405 = route absent. Anything else (including 409 "no active run")
    // means the endpoint is there and answering.
    _steerSupported = !(res.status === 404 || res.status === 405 || res.status === 501);
  } catch (_) {
    _steerSupported = false;
  } finally {
    _steerProbeInFlight = false;
  }
  return _steerSupported;
}

/**
 * Send one steer to the run in flight for the current session.
 * Bound to the session read at THIS moment, never at delivery: a steer is
 * addressed to one conversation and posting it into another is the P6-01
 * defect in a different costume.
 */
export async function submitSteer(text) {
  const body = String(text || '').trim();
  if (!body) return false;
  const sid = _steerSessionId();
  if (!sid) {
    _queueInsteadOfSteering('No active chat to steer');
    return false;
  }
  const input = _steerComposer();
  const btn = _steerBar && _steerBar.querySelector('.steer-bar-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${STEER_API_BASE}/api/chat/steer/${encodeURIComponent(sid)}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: body }),
    });
    if (res.status === 404 || res.status === 405 || res.status === 501) {
      _steerSupported = false;
      _removeSteerBar();
      _queueInsteadOfSteering('Steering is not available on this server');
      return false;
    }
    let data = {};
    try { data = await res.json(); } catch (_) { data = {}; }
    if (!res.ok || data.accepted === false) {
      const why = {
        // Covers both causes the server folds into this reason: the run
        // finished, and the run cannot take a steer at all (a plain chat or
        // image turn). Saying "already finished" for the second was wrong, and
        // the sentence has to hold for whichever one it was.
        no_active_run: 'There is no agent run to steer right now',
        too_many: 'Too many steers are already waiting',
        too_long: 'That steer is too long to send mid-run',
        empty: 'Nothing to steer with',
      }[data.reason] || 'Could not steer that';
      _queueInsteadOfSteering(why);
      return false;
    }
    _clearComposerAfterSteer(input);
    _noteSteerSent(body);
    try {
      uiModule.showToast && uiModule.showToast('Steering — the agent picks this up at its next step');
    } catch (_) {}
    return true;
  } catch (err) {
    _queueInsteadOfSteering('Steering failed: ' + ((err && err.message) || err));
    return false;
  } finally {
    if (btn) btn.disabled = false;
  }
}

/** Cmd/Ctrl+Enter in the composer, in the CAPTURE phase.
 *  app.js binds plain Enter on `#message` itself and does not exclude the
 *  modifier, so without capturing first Cmd/Ctrl+Enter would fall through to
 *  the queue. The key is only taken when steering is genuinely available and a
 *  run is genuinely live; every other case is left exactly as it was. */
function _steerKeydown(e) {
  if (e.key !== 'Enter' || e.isComposing || e.repeat) return;
  if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return;
  if (_steerSupported !== true) return;
  // The run has said it cannot consume a steer (`B14`). Hand the key back
  // rather than spending a round trip to be refused: app.js's plain-Enter
  // binding does not exclude the modifier, so the text lands in the same queue
  // the refusal would have put it in, with no "Steering…" toast in front of it.
  if (_steerRunAnswer === false) return;
  const input = _steerComposer();
  if (!input || e.target !== input) return;
  if (!_steerChatBusy()) return;
  const text = (input.value || '').trim();
  if (!text) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  submitSteer(text);
}

/** `pantheon:chat-busy-change` is chat.js's own "a foreground run started /
 *  ended" signal (`_setForegroundChatBusy`) and app.js already listens to it.
 *  Reusing it means the bar can never disagree with the composer about whether
 *  a run is live, and costs no polling. */
export function initSteerControl() {
  if (_steerKeyBound) return false;   // idempotent: one keydown hook, one busy hook
  _steerKeyBound = true;
  document.addEventListener('keydown', _steerKeydown, true);
  window.addEventListener('pantheon:chat-busy-change', async (e) => {
    const active = !!(e && e.detail && e.detail.active);
    if (!active) {
      // A steer accepted in the last moments of a run can miss it: the loop
      // ended before it reached a round boundary. Say so — but only when the
      // confirmation channel has been seen working at least once, or a build
      // without it would cry wolf on every steer that landed perfectly well.
      const missed = _steerConfirmSeen ? _steerPendingCount() : 0;
      if (missed) {
        try {
          uiModule.showToast && uiModule.showToast(
            missed === 1
              ? 'The response finished before your steer was picked up — send it again if it still applies'
              : `${missed} steers were not picked up before the response finished — send them again if they still apply`,
            { duration: 7000 });
        } catch (_) {}
      }
      _removeSteerBar();
      _steerRunAnswer = null;
      _steerComposerAnswer = null;
      return;
    }
    // A new run: what the last one said about itself does not carry over. This
    // is the whole reason the answer is per-run rather than per-page (`B14`).
    //
    // `B81`. A busy edge that CARRIES a verdict is a turn starting — that is
    // the send path, and only the send path, announcing itself. One without is
    // a re-announcement of the run already going (`setStreamingState`,
    // `_syncForegroundStreamGlobals`), and it must change nothing: resetting
    // the run's own answer there threw away the only authoritative fact in
    // hand, and recomputing the composer's would answer "steerable" for the
    // exact turn this row is about, because the research toggle has been
    // cleared by then. Per-run freshness is kept by the `active === false`
    // branch above, which clears both — including on a build whose `chat.js`
    // sends no verdict at all, where this stays exactly today's behaviour.
    if (typeof (e && e.detail && e.detail.steerable) === 'boolean') {
      _steerVerdictsSeen = true;
      _steerRunAnswer = null;
      _steerComposerAnswer = e.detail.steerable;
    } else if (!_steerVerdictsSeen) {
      // No verdict has ever been seen here, so this edge cannot be told apart
      // from a turn starting. `B14`'s rule, kept verbatim for that build.
      _steerRunAnswer = null;
    }
    if (_steerSupported === null) await probeSteerSupport();
    if (_steerSupported !== true) return;
    // The stream can beat the probe on the first run of a page, so its verdict
    // is re-read after the await rather than assumed not to have arrived (`B14`).
    if (_steerRunAnswer === false) { _removeSteerBar(); return; }
    // Chat mode has no rounds, so it has no step boundary to deliver a steer
    // at, and the server refuses one — correctly, since accepting it would
    // report words as landing that nothing would ever read. Drawing the bar
    // anyway would offer a control that always declines, which is the `Law 15`
    // failure this whole feature exists to avoid.
    //
    // This stays the PROVISIONAL answer only (`B14`). The composer's mode is
    // not the turn's mode: `research_pending` runs research on a message sent
    // with the toggle cleared, and auto-escalation runs the agent loop on a
    // turn typed in chat mode — so this guess is wrong in both directions, and
    // in the second it withholds a bar from a run that would have taken the
    // steer. It is kept because it costs nothing and is right most of the time
    // in the window before the run answers, and because a server that does not
    // send `stream_steerable` must keep behaving exactly as it does today.
    //
    // `B81` widened it from one term to the two the client can evaluate, so a
    // research turn started from the toggle is now caught here rather than a
    // round trip later. What remains wrong is what the client genuinely cannot
    // see: an image-generation session, and a `research_pending` continuation
    // whose toggle is already clear. Both are still corrected by the run's own
    // answer, which is the only thing that knows.
    if (_steerRunAnswer === null && _steerComposerSaysNo()) { _removeSteerBar(); return; }
    // A run that belongs to a different chat than the one on screen gets a
    // fresh bar rather than another session's accepted-steer list.
    if (_steerBar && _steerBoundSessionId && _steerBoundSessionId !== _steerSessionId()) {
      _removeSteerBar();
    }
    _ensureSteerBar();
  });
  return true;
}

/**
 * `stream_steerable` from `routes/chat_routes.py`: this run's own answer to
 * "can a steer reach you", emitted as the stream's first event and carrying the
 * exact value `agent_runs.start` was given (`B14`).
 *
 * `P6-18` gated the bar on the composer's mode getter, which closed the
 * chat-mode case and left three others open — a research turn, an
 * image-generation session, and a compare pane all draw a bar the server then
 * refuses with `no_active_run`. None of them is visible from the composer:
 * research in particular is decided server-side from `research_pending` on a
 * message whose research toggle `chat.js` has already cleared. So the fix is
 * not a fourth client-side rule but the end of client-side rules — the one
 * predicate that decides the refusal now also decides the affordance.
 *
 * It runs in both directions. `false` takes the bar down; `true` puts it up,
 * which is a control the user did not have before on an auto-escalated turn —
 * chat mode promoted to agent IS steerable, and the composer's guess was hiding
 * a bar that would have worked.
 */
export function handleStreamSteerable(data) {
  const steerable = !!(data && data.steerable);
  _steerRunAnswer = steerable;
  if (!steerable) { _removeSteerBar(); return; }
  // Only while a run is actually live: this event is replayed from the run's
  // buffer on `/api/chat/resume`, and a replay that arrives after the run ended
  // must not resurrect the bar.
  if (_steerSupported === true && _steerChatBusy()) _ensureSteerBar();
}

/**
 * `steer_applied` from `src/agent_loop.py`: the steer actually reached the
 * model, at round `round`. Purely a confirmation — the bar already told the
 * user it was pending, and this upgrades that line to "applied".
 */
export function handleSteerApplied(data) {
  _steerConfirmSeen = true;
  if (!_steerSentList) return;
  const round = Number((data && data.round) || 0);
  const states = _steerSentList.querySelectorAll('.steer-sent-state');
  states.forEach((el) => {
    el.textContent = ' — applied' + (round ? ' at step ' + round : '');
  });
}

initSteerControl();

/**
 * Handle a ui_control SSE event — AI-driven UI manipulation.
 * Extracted from the duplicated ui_control + tool_output.ui_event handlers.
 */
/**
 * Chat toggle name → the hidden checkbox that holds its state. `H19`.
 *
 * There were three copies of this map and they disagreed. This one was
 * complete; the two in `slashCommands.js` were missing `rag` and `incognito`,
 * which is why `_cmdToggleRag` — a handler that exists, at `:1220` — could not
 * have worked even if it had been registered: `toggleMap['rag']` was
 * `undefined`, `getElementById(undefined)` was null, and the function returned
 * without doing anything or saying so.
 *
 * `Law 14`, the same shape as the keybind table two commits earlier: not a
 * fourth map, the complete one becoming the only one.
 */
export const TOGGLE_CHECKBOX_IDS = Object.freeze({
  web: 'web-toggle',
  bash: 'bash-toggle',
  rag: 'rag-toggle',
  research: 'research-toggle',
  incognito: 'incognito-toggle',
});


export function handleUIControl(uiData) {
  var uiEvent = uiData.ui_event || uiData;
  var esc = uiModule.esc;

  try {
    if (uiEvent === 'toggle' || uiData.ui_event === 'toggle') {
      var toggleMap = TOGGLE_CHECKBOX_IDS;
      var btnMap = {
        web: 'web-toggle-btn', bash: 'bash-toggle-btn', rag: 'rag-indicator-btn',
      };
      var chkId = toggleMap[uiData.toggle_name];
      var btnId = btnMap[uiData.toggle_name];
      if (uiData.toggle_name === 'rag' && window._syncRagIndicator) {
        window._syncRagIndicator(!!uiData.state);
      } else {
        if (chkId) {
          var chk = document.getElementById(chkId);
          if (chk) chk.checked = !!uiData.state;
        }
        if (btnId) {
          var btn = document.getElementById(btnId);
          if (btn) btn.classList.toggle('active', !!uiData.state);
        }
      }
      var ts = Storage.getJSON(Storage.KEYS.TOGGLES, {});
      ts[uiData.toggle_name] = !!uiData.state;
      Storage.setJSON(Storage.KEYS.TOGGLES, ts);

    } else if (uiEvent === 'set_mode' || uiData.ui_event === 'set_mode') {
      var modeVal = uiData.mode;
      var agentBtn = document.getElementById('mode-agent-btn');
      var chatBtn = document.getElementById('mode-chat-btn');
      if (agentBtn && chatBtn) {
        agentBtn.classList.toggle('active', modeVal === 'agent');
        chatBtn.classList.toggle('active', modeVal !== 'agent');
      }
      var ts2 = Storage.getJSON(Storage.KEYS.TOGGLES, {});
      ts2.mode = modeVal;
      Storage.setJSON(Storage.KEYS.TOGGLES, ts2);
      document.querySelectorAll('[data-mode-tool]').forEach(function(b) {
        b.style.display = modeVal === 'agent' ? '' : 'none';
      });

    } else if (uiEvent === 'switch_model' || uiData.ui_event === 'switch_model') {
      var modelDisplay = document.querySelector('.current-model-name, #current-model');
      if (modelDisplay) modelDisplay.textContent = uiData.model;

    } else if (uiEvent === 'set_theme' || uiData.ui_event === 'set_theme') {
      var tm = themeModule;
      if (tm && tm.THEMES && tm.applyColors && tm.save) {
        var themeName = uiData.theme_name;
        if (themeName === 'chatgpt') themeName = 'gpt';  // renamed preset
        var customThemes = tm.getCustomThemes ? tm.getCustomThemes() : {};
        var colors = tm.THEMES[themeName] || customThemes[themeName] || uiData.colors;
        if (colors) {
          tm.applyColors(colors);
          tm.save(themeName, colors);
          var grid = document.getElementById('themeGrid');
          if (grid) {
            grid.querySelectorAll('.theme-swatch').forEach(function(s) { s.classList.remove('active'); });
            var sw = grid.querySelector('[data-theme="' + themeName + '"]');
            if (sw) sw.classList.add('active');
          }
        }
      }

    } else if (uiEvent === 'create_theme' || uiData.ui_event === 'create_theme') {
      var tm2 = themeModule;
      if (tm2 && tm2.applyColors && tm2.save) {
        var colors2 = uiData.colors;
        var name = uiData.theme_name || 'custom';
        if (colors2) {
          tm2.applyColors(colors2);
          tm2.save(name, colors2);
          // Background effects (animated pattern / frosted glass) the model
          // optionally set — apply them live and persist with the theme so
          // they survive re-applying it later.
          var bg = uiData.bg || null;
          var opts = {};
          if (bg) {
            if (bg.pattern && tm2.applyBgPattern) { tm2.applyBgPattern(bg.pattern); opts.bgPattern = bg.pattern; }
            if (bg.effectColor && tm2.applyBgEffectColor) { tm2.applyBgEffectColor(bg.effectColor); opts.bgEffectColor = bg.effectColor; }
            if (bg.effectIntensity != null && tm2.applyBgEffectIntensity) { tm2.applyBgEffectIntensity(bg.effectIntensity); opts.bgEffectIntensity = bg.effectIntensity; }
            if (bg.effectSize != null && tm2.applyBgEffectSize) { tm2.applyBgEffectSize(bg.effectSize); opts.bgEffectSize = bg.effectSize; }
            if (bg.frosted != null && tm2.applyFrostedGlass) { tm2.applyFrostedGlass(bg.frosted); opts.frosted = bg.frosted; }
          }
          if (tm2.saveCustomTheme) tm2.saveCustomTheme(name, colors2, Object.keys(opts).length ? opts : undefined);
        }
      }

    } else if (uiEvent === 'highlight' || uiData.ui_event === 'highlight') {
      document.querySelectorAll('.pantheon-highlight').forEach(function(e) { e.classList.remove('pantheon-highlight'); });
      document.querySelectorAll('.pantheon-hl-label').forEach(function(e) { e.remove(); });
      var target = document.querySelector(uiData.selector);
      if (target) {
        target.classList.add('pantheon-highlight');
        target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        if (uiData.label) {
          var lbl = document.createElement('div');
          lbl.className = 'pantheon-hl-label';
          lbl.textContent = uiData.label;
          if (!target.style.position) target.style.position = 'relative';
          target.appendChild(lbl);
        }
      }

    } else if (uiEvent === 'clear_highlight' || uiData.ui_event === 'clear_highlight') {
      document.querySelectorAll('.pantheon-highlight').forEach(function(e) { e.classList.remove('pantheon-highlight'); });
      document.querySelectorAll('.pantheon-hl-label').forEach(function(e) { e.remove(); });

    } else if (uiEvent === 'research_started' || uiData.ui_event === 'research_started') {
      // Agent kicked off deep research — adopt the session into the
      // sidebar immediately so the user sees it without waiting for
      // the 12s active-poll.
      var rsid = uiData.research_session_id || uiData.session_id;
      if (rsid) {
        import('./research/jobs.js?v=20260630researchthumb').then(function(mod) {
          var fn = mod.adoptSession || (mod.default && mod.default.adoptSession);
          if (fn) fn(rsid);
        }).catch(function(){});
        // The clickable "Open in Deep Research" link is now emitted by the
        // agent loop as a `#research-<id>` markdown anchor in the assistant's
        // response text — it renders as a regular clickable chat link AND
        // persists across refresh (saved with the message). No ephemeral
        // chip injection needed here anymore.
      }

    } else if (uiEvent === 'open_panel' || uiData.ui_event === 'open_panel') {
      var panel = uiData.panel;
      if (panel === 'documents') {
        import('./documentLibrary.js').then(function(mod) {
          var fn = mod.openLibrary || (mod.default && mod.default.openLibrary);
          if (fn) fn();
        }).catch(function(){});
      } else if (panel === 'gallery') {
        import('./gallery.js?v=20260708match1').then(function(mod) {
          var fn = mod.openGallery || (mod.default && mod.default.openGallery);
          if (fn) fn();
        }).catch(function(){});
      } else if (panel === 'email') {
        import('./emailLibrary.js?v=20260815approvalsave1').then(function(mod) {
          var fn = mod.openEmailLibrary || (mod.default && mod.default.openEmailLibrary);
          if (fn) fn();
        }).catch(function(){});
      } else if (panel === 'sessions') {
        import('./sessions.js').then(function(mod) {
          var fn = mod.openLibrary || (mod.default && mod.default.openLibrary);
          if (fn) fn();
        }).catch(function(){});
      } else if (panel === 'forge' || panel === 'cookbook') {
        // `P0-29`. `open_panel` is wire protocol between the model and this
        // switch, and a model that has read the new tool description says
        // `forge` while a model quoting an older conversation still says
        // `cookbook`. Both land here (`Law 1`); neither is the panel's id.
        import('./cookbook.js').then(function(mod) {
          var fn = mod.open || (mod.default && mod.default.open);
          if (fn) fn();
        }).catch(function(){});
      } else if (panel === 'notes') {
        import('./notes.js').then(function(mod) {
          var fn = mod.openPanel || mod.openNotes || (mod.default && (mod.default.openPanel || mod.default.openNotes));
          if (fn) fn();
        }).catch(function(){});
      } else if (panel === 'memories' || panel === 'skills' || panel === 'settings') {
        // CORRECTED 2026-08-30. This used to read
        //   `var ids = { memories: 'tool-memory-btn', skills: 'skills-btn',
        //                settings: 'open-settings-btn' };`
        // and **two of those three ids exist nowhere in the product** — the only
        // occurrence of either string in the whole repository was that line. The
        // `if (btn)` swallowed it, so `open_panel skills` and `open_panel
        // settings` did nothing while `ui_control` returned "Opening skills
        // panel" to the model, which then told the user it had opened.
        //
        // Worse, the system prompt steers *towards* this path: "'open skills'
        // … means OPEN THE PANEL — call `ui_control`, NOT a manage/list tool."
        // So the one phrasing a person would use was routed off a working tool
        // onto a silent no-op.
        //
        // It also shows what `check-wiring.py` cannot see: it matches only a
        // lookup whose argument is a string literal, and this one indexed an
        // object with a variable. A lookup with nothing behind it scored clean.
        // (Writing that sentence with the literal call spelled out made the
        // checker count *this comment* as a fourth unresolved lookup — it does
        // not strip comments before scanning. Filed with the rest of P3-15.)
        if (panel === 'memories' || panel === 'skills') {
          var memBtn = document.getElementById('tool-memory-btn');
          if (memBtn) memBtn.click();
          // Skills is not a panel of its own — it is a tab inside the memory
          // panel (`static/index.html:350`). Select it the way memory.js's own
          // code does, after the panel has had a frame to render its tabs.
          if (panel === 'skills') {
            setTimeout(function () {
              var tab = document.querySelector('.memory-tab[data-memory-tab="skills"]');
              if (tab) tab.click();
            }, 0);
          }
        } else {
          // Settings is a body-level modal with a module opener — the same one
          // the rail gear, the user bar, `/settings` and four other modules use
          // (`P1-05`). Going through the module rather than clicking a sidebar
          // button keeps this working when Customize UI hides that button.
          import('./settings.js?v=20260815approvalsave1').then(function (mod) {
            var open = (mod && mod.open) || (mod && mod.default && mod.default.open);
            if (open) open();
          }).catch(function () {});
        }
      }

    } else if (uiEvent === 'open_email_reply' || uiData.ui_event === 'open_email_reply') {
      try {
        var activeCtx = documentModule && documentModule.getActiveEmailComposerContext
          ? documentModule.getActiveEmailComposerContext()
          : null;
        var sameActiveDraft = activeCtx
          && String(activeCtx.sourceUid || '') === String(uiData.uid || '')
          && String(activeCtx.sourceFolder || 'INBOX') === String(uiData.folder || 'INBOX');
        var existingDocId = sameActiveDraft && activeCtx.docId
          ? activeCtx.docId
          : (documentModule && documentModule.findEmailDocId
            ? documentModule.findEmailDocId(uiData.uid, uiData.folder || 'INBOX')
            : null);
        if (existingDocId && documentModule.replaceEmailReplyBody) {
          if (documentModule.loadDocument) documentModule.loadDocument(existingDocId);
          documentModule.replaceEmailReplyBody(existingDocId, uiData.body || '', { force: true });
          if (uiModule && uiModule.showToast) uiModule.showToast('Wrote reply into the open email');
          return;
        }
      } catch (e) {
        console.warn('open_email_reply existing draft update failed:', e);
      }
      import('./emailInbox.js?v=20260815approvalsave1').then(function(mod) {
        var fn = mod.openReplyDraft || (mod.default && mod.default.openReplyDraft);
        if (fn) fn(uiData.uid, uiData.folder || 'INBOX', uiData.mode || 'reply', uiData.body || '');
      }).catch(function(e) {
        console.warn('open_email_reply failed:', e);
      });
    }
  } catch(e) {
    console.warn('ui_control handler error:', e);
  }
}

/**
 * Notify user when a background stream completes.
 */
export function notifyStreamComplete(sessionId, query) {
  var isHidden = document.hidden;
  var isOtherSession = sessionModule && sessionModule.getCurrentSessionId() !== sessionId;
  if (!isHidden && !isOtherSession) return;
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  var body = query ? 'Response to "' + query.substring(0, 60) + '" is ready' : 'Your chat response has completed';
  var notification = new Notification('Response Complete', {
    body: body,
    tag: 'stream-' + sessionId,
  });
  notification.onclick = function() {
    window.focus();
    if (isOtherSession && sessionModule) {
      sessionModule.selectSession(sessionId);
    }
    notification.close();
  };
  setTimeout(function() { notification.close(); }, 10000);
}

/**
 * Insert a clickable in-chat toast when a background stream finishes.
 */
export function insertStreamDoneToast(sessionId, query) {
  var box = document.getElementById('chat-history');
  if (!box) return;
  var sessions = sessionModule ? sessionModule.getSessions() : [];
  var sess = sessions.find(function(s) { return s.id === sessionId; });
  var name = sess ? sess.name : 'another session';
  var preview = query ? '"' + query.substring(0, 50) + (query.length > 50 ? '...' : '') + '"' : '';
  var div = document.createElement('div');
  div.className = 'msg msg-system stream-done-toast';
  div.innerHTML = '<div class="body">'
    + '<span class="stream-done-indicator">●</span>'
    + '<span>Response ready in <strong>' + (name || 'session').replace(/</g, '&lt;') + '</strong>'
    + (preview ? ' &mdash; ' + preview.replace(/</g, '&lt;') : '')
    + '</span>'
    + '</div>';
  div.addEventListener('click', function() {
    if (sessionModule) sessionModule.selectSession(sessionId);
  });
  box.appendChild(div);
  uiModule.scrollHistory();
}

/**
 * Notify when research completes (browser notification).
 */
export function notifyResearchComplete(sessionId, query) {
  var isHidden = document.hidden;
  var isOtherSession = sessionModule && sessionModule.getCurrentSessionId() !== sessionId;
  if (!isHidden && !isOtherSession) return;
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  var body = query ? 'Research on "' + query.substring(0, 60) + '" is ready' : 'Your deep research has completed';
  var notification = new Notification('Research Complete', {
    body: body,
    tag: 'research-' + sessionId,
  });
  notification.onclick = function() {
    window.focus();
    if (isOtherSession && sessionModule) {
      sessionModule.selectSession(sessionId);
    }
    notification.close();
  };
  setTimeout(function() { notification.close(); }, 10000);
}

const chatStream = {
  handleUIControl,
  notifyStreamComplete,
  insertStreamDoneToast,
  notifyResearchComplete,
  // P6-18. `handleSteerApplied` is the consumer for the `steer_applied` SSE
  // event; `chat.js` owns the SSE dispatch chain and routes it here.
  // `B14` adds `handleStreamSteerable` on the same chain, for the event that
  // says whether this run can take a steer at all.
  initSteerControl,
  probeSteerSupport,
  submitSteer,
  handleSteerApplied,
  handleStreamSteerable,
};

export default chatStream;
