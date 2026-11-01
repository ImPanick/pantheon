// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/nextStepGhost.js
//
// `B1739`. When a reply finishes, the empty message box offers the next most
// valuable step as ghost text: one sentence the person would most likely send
// next, written by the chat's own model (`POST /api/chat/next-step`,
// `src/next_step.py`). Tab puts the whole sentence in the box, ready to send;
// nothing is sent for them. Typing over it, Escape, a new send or another
// chat puts it away. On a touch screen the key cap is a button.
//
// Tab still moves the focus whenever no suggestion is showing (`B948`): the
// key is borrowed only while there is something on offer to take.

const GHOST_ID = 'next-step-ghost';
const ON_CLASS = 'next-step-on';

let _ta = null;
let _ghost = null;
let _words = null;
let _cap = null;
let _offer = null;      // { sessionId, text }
let _ask = null;        // AbortController of the request in flight
let _ticket = 0;

function _currentSession() {
  try { return window.sessionModule?.getCurrentSessionId?.() || ''; } catch (_) { return ''; }
}

function _busy() {
  return !!window.__pantheonChatBusy;
}

function _ensureGhost() {
  if (_ghost && _ghost.isConnected) return _ghost;
  const host = _ta.parentElement;
  if (!host) return null;
  host.classList.add('next-step-host');
  _ghost = document.createElement('div');
  _ghost.id = GHOST_ID;
  _ghost.className = 'next-step-ghost';
  _ghost.setAttribute('aria-hidden', 'true');
  _words = document.createElement('span');
  _words.className = 'next-step-words';
  _cap = document.createElement('button');
  _cap.type = 'button';
  _cap.className = 'next-step-cap';
  _cap.tabIndex = -1;
  _cap.title = 'Use this suggestion (Tab)';
  _cap.addEventListener('mousedown', (e) => { e.preventDefault(); accept(); });
  _ghost.appendChild(_words);
  _ghost.appendChild(_cap);
  host.appendChild(_ghost);
  return _ghost;
}

function _place() {
  if (!_ghost || !_ta) return;
  const cs = getComputedStyle(_ta);
  _ghost.style.left = _ta.offsetLeft + 'px';
  _ghost.style.top = _ta.offsetTop + 'px';
  _ghost.style.width = _ta.offsetWidth + 'px';
  _ghost.style.font = cs.font;
  _ghost.style.lineHeight = cs.lineHeight;
  _ghost.style.letterSpacing = cs.letterSpacing;
  _ghost.style.paddingTop = cs.paddingTop;
  _ghost.style.paddingLeft = cs.paddingLeft;
  _ghost.style.paddingRight = cs.paddingRight;
}

function _draw() {
  const show = !!(_offer && _ta && !_ta.value && _offer.sessionId === _currentSession() && !_busy());
  if (!show) {
    if (_ghost) _ghost.style.display = 'none';
    if (_ta && _ta.classList.contains(ON_CLASS)) {
      _ta.classList.remove(ON_CLASS);
      _ta.style.minHeight = '';
    }
    return;
  }
  if (!_ensureGhost()) return;
  _words.textContent = _offer.text;
  const touch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
  _cap.textContent = touch ? 'Use' : 'Tab';
  _place();
  _ghost.style.display = 'block';
  _ta.classList.add(ON_CLASS);
  // A sentence longer than the box's one line: the empty box grows to hold
  // it, so the words never spill over the row below.
  const tall = _ghost.offsetHeight;
  if (tall > _ta.offsetHeight) _ta.style.minHeight = tall + 'px';
}

/** Put the offer away for good (a send, Escape, another chat). */
export function dismiss() {
  _ticket++;
  if (_ask) { try { _ask.abort(); } catch (_) {} _ask = null; }
  _offer = null;
  _draw();
}

/** Tab: the sentence goes in the box, the caret at its end. */
export function accept() {
  if (!_offer || !_ta || _ta.value) return false;
  const text = _offer.text;
  _offer = null;
  _ta.value = text;
  _draw();
  _ta.dispatchEvent(new Event('input', { bubbles: true }));
  _ta.focus();
  try { _ta.setSelectionRange(text.length, text.length); } catch (_) {}
  return true;
}

/** The offer on show, for the tests and the console. */
export function current() {
  return _offer ? { ..._offer } : null;
}

async function _fetchFor(sessionId) {
  const mine = ++_ticket;
  if (_ask) { try { _ask.abort(); } catch (_) {} }
  const ctl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
  _ask = ctl;
  let text = '';
  try {
    const res = await fetch('/api/chat/next-step', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
      signal: ctl ? ctl.signal : undefined,
    });
    if (res.ok) text = String((await res.json()).suggestion || '').trim();
  } catch (_) { text = ''; }
  if (mine !== _ticket) return;
  _ask = null;
  if (!text) return;
  _offer = { sessionId, text };
  _draw();
}

function _afterReply(sessionId) {
  if (!sessionId || window.__pantheonVoiceCall) return;
  const mine = ++_ticket;
  // The reply's last round has ended; the run may still be closing. Ask
  // once the composer is idle, or after a short wait at most.
  const go = () => {
    window.removeEventListener('pantheon:chat-busy-change', onIdle);
    if (mine !== _ticket) return;
    if (_currentSession() !== sessionId) return;
    _fetchFor(sessionId);
  };
  const onIdle = (e) => { if (!(e && e.detail && e.detail.active)) setTimeout(go, 50); };
  if (!_busy()) { setTimeout(go, 50); return; }
  window.addEventListener('pantheon:chat-busy-change', onIdle);
  setTimeout(go, 2500);
}

export function initNextStepGhost(textarea) {
  if (!textarea || textarea._nextStepWired) return;
  textarea._nextStepWired = true;
  _ta = textarea;

  window.addEventListener('pantheon:reply', (e) => {
    const d = (e && e.detail) || {};
    if (d.phase === 'end') _afterReply(d.sessionId);
    else if (d.phase === 'start') dismiss();
  });
  window.addEventListener('pantheon:message-sent', dismiss);
  window.addEventListener('pantheon:chat-busy-change', (e) => {
    if (e && e.detail && e.detail.active) dismiss();
  });
  document.addEventListener('pantheon:session-changed', dismiss);

  textarea.addEventListener('input', _draw);
  // Capture on the document: Tab and Escape are answered before the box's
  // other listeners (and before the browser moves the focus).
  document.addEventListener('keydown', (e) => {
    if (e.target !== textarea || !_offer || textarea.value) return;
    if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
      if (_ghost && _ghost.style.display === 'block' && accept()) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    } else if (e.key === 'Escape' && _ghost && _ghost.style.display === 'block') {
      e.preventDefault();
      e.stopImmediatePropagation();
      dismiss();
    }
  }, true);

  if (typeof ResizeObserver !== 'undefined') {
    try { new ResizeObserver(() => { if (_offer) _place(); }).observe(textarea); } catch (_) {}
  }
  window.addEventListener('resize', () => { if (_offer) _place(); });
}

export default { initNextStepGhost, accept, dismiss, current };
