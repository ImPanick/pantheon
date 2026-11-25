// SPDX-License-Identifier: AGPL-3.0-or-later
//
// modeSwitch.js — Chat or Apollo, one switch, both ways.
//
// Pantheon serves two ways of working: the chat (a chatbot that can call
// agents) and Apollo (a partner that runs the work). Once Apollo's page was
// open there was no way back to the chat (owner's test, 2026-11-24: "Once
// apollo is opened, there's no way to leave apollo mode and go back to the base
// 'chatbot' mode of Pantheon ... I want to serve both options"). New chat
// cleared the open chat without saying so, so Apollo's page stayed up over it,
// and Apollo's own control pane had put the sidebar's list away.
//
// This switch sits at the end of the chat's top bar in both modes. Chat goes
// back to the last chat that wasn't Apollo's, or to a new one; Apollo opens
// Apollo's chat. Which one is lit follows `html.apollo-view`, which
// `apolloView.js` sets and clears. The moves themselves are `assistant.js`'s,
// passed in as hooks, so this module draws and nothing else.

const ID = 'pan-mode-switch';

let _hooks = {};

const byId = (id) => document.getElementById(id);

function _inApollo() {
  return !!document.documentElement?.classList?.contains('apollo-view');
}

function _btn(mode, label, title) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'pan-mode-btn';
  b.dataset.mode = mode;
  b.textContent = label;
  b.title = title;
  b.addEventListener('click', () => {
    const apollo = _inApollo();
    if (mode === 'chat' && apollo) _hooks.toChat?.();
    else if (mode === 'apollo' && !apollo) _hooks.toApollo?.();
  });
  return b;
}

/** Light the mode the page is in. */
export function syncModeSwitch() {
  const el = byId(ID);
  if (!el) return;
  const apollo = _inApollo();
  for (const b of el.querySelectorAll('.pan-mode-btn')) {
    const on = (b.dataset.mode === 'apollo') === apollo;
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.classList.toggle('active', on);
  }
}

/** Draw the switch into the chat's top bar. `hooks`: { toChat, toApollo }. */
export function mountModeSwitch(hooks = {}) {
  _hooks = hooks || {};
  let el = byId(ID);
  if (!el) {
    const host = document.querySelector('.chat-top-bar');
    if (!host) return null;
    el = document.createElement('div');
    el.id = ID;
    el.className = 'pan-modes';
    el.setAttribute('role', 'group');
    el.setAttribute('aria-label', 'Mode');
    el.appendChild(_btn('chat', 'Chat', 'Chat: talk to a model, and call agents when you want them'));
    el.appendChild(_btn('apollo', 'Apollo', 'Apollo: your partner runs the work'));
    host.appendChild(el);
  }
  syncModeSwitch();
  return el;
}
