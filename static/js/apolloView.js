// SPDX-License-Identifier: AGPL-3.0-or-later
//
// apolloView.js — Apollo's own page.
//
// Until this, Apollo was a pinned chat drawn by the generic chat page with
// every generic control on it, and everything the phases built (Needs you,
// tasks, activity, team, Spaces, budgets, new agents) sat in a pane opened
// from a header button. That button, the Space switcher and the settings gear
// were mounted into `.chat-header-right, #chat-header .actions, .chat-header`,
// and the page has none of those (its header is `.chat-top-bar`), so none of
// them was ever drawn. On a fresh deploy Apollo looked exactly like any chat,
// plus the orb (owner's test, 2026-11-24).
//
// Entering the Apollo chat now turns the page into Apollo's:
//   - `html.apollo-view`, under which `cockpit.css` takes the generic controls
//     off the composer and the header (mode toggle, tool toggles, plan,
//     research, group, character, compare, workspace and summon chips, the
//     Nobody button and the welcome scenery). The model picker stays: Apollo
//     runs on the model the person picks, local or paid.
//   - Apollo's own bar at the top of the chat: its name, the Space it is in,
//     and its controls (the pane, settings).
//   - Agent mode, always: Apollo works through its tools. The person's own
//     choice for other chats is put back on the way out.
//   - Its deck (`apolloDeck.js`) above the chat: the goals rail, the board of
//     the open goal (its plan, owners, handoffs and the lead's own chat),
//     Needs you, and home. The owner's verdict on the first cut was that the
//     pane "does absolutely nothing different ... no planning, delegation,
//     nothing", so the work is the page now, and the chat is Apollo's command
//     line under it. The pane stays one press away on the bar.
//   - Its own composer prompt.
//   - Apollo's control pane in the sidebar's place (`apolloDeck.js`
//     `placeControl`): goals, the person's other chats and their mail, so the
//     generic sidebar's list is put away while Apollo is up.
// Leaving the chat puts every one of those back. The Chat / Apollo switch at
// the end of the top bar (`modeSwitch.js`) is lit from `html.apollo-view`, so
// both moves below tell it.

const BAR_ID = 'apollo-bar';
const PROMPT = 'Tell Apollo what you need';

const SUN = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></svg>';
const PANE = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M14.5 4.5v15"/></svg>';
const GEAR = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/></svg>';

let _on = false;
let _priorMode = null;        // 'chat' when the person had Chat mode on before Apollo
let _priorPrompt = null;      // the composer's own placeholder, put back on the way out
let _hooks = {};

const byId = (id) => document.getElementById(id);

function _button(id, label, svg, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.id = id;
  b.className = 'apo-bar-btn';
  b.title = label;
  b.setAttribute('aria-label', label);
  b.innerHTML = svg;
  b.addEventListener('click', onClick);
  return b;
}

function _togglePane() {
  import('./apolloPane.js').then((m) => {
    if (m.isApolloPaneOpen()) m.closeApolloPane();
    else _openPane(m);
  }).catch(() => {});
}

function _openPane(m) {
  m.openApolloPane();
  // The dock seats the pane on the right; untuck it if the person tucked it.
  try { window.pantheonCockpit?.toggleWorkspace?.(false); } catch { /* no dock on a phone */ }
}

function _buildBar() {
  if (byId(BAR_ID)) return byId(BAR_ID);
  const bar = document.createElement('div');
  bar.id = BAR_ID;
  bar.className = 'apo-bar';
  bar.setAttribute('role', 'toolbar');
  bar.setAttribute('aria-label', 'Apollo');

  const mark = document.createElement('span');
  mark.className = 'apo-bar-mark';
  mark.innerHTML = SUN;
  const name = document.createElement('span');
  name.className = 'apo-bar-name';
  name.textContent = _hooks.name || 'Apollo';
  const space = document.createElement('span');
  space.id = 'apollo-space-switcher';
  space.className = 'apo-bar-space';
  const grow = document.createElement('span');
  grow.className = 'apo-bar-grow';

  bar.appendChild(mark);
  bar.appendChild(name);
  bar.appendChild(space);
  bar.appendChild(grow);
  for (const extra of (_hooks.extraButtons || [])) bar.appendChild(extra());
  bar.appendChild(_button('apollo-pane-btn', "Apollo's pane", PANE, _togglePane));
  bar.appendChild(_button('assistant-header-gear', 'Apollo settings', GEAR, () => _hooks.openSettings?.()));

  const top = document.querySelector('.chat-top-bar');
  const host = top || byId('chat-container');
  if (host) host.insertBefore(bar, host.firstChild || null);

  import('./apolloSpaces.js').then((Sp) => {
    if (!space.isConnected) return;
    space.appendChild(Sp.createSwitcher({ topLabel: 'All spaces' }).el);
  }).catch(() => {});
  return bar;
}

function _mountDeck() {
  import('./apolloDeck.js').then((m) => { if (_on) m.mountDeck(); }).catch(() => { /* the bar and the chat still work */ });
}

function _syncSwitch() {
  import('./modeSwitch.js').then((m) => m.syncModeSwitch()).catch(() => { /* no switch drawn */ });
}

function _unmountDeck() {
  import('./apolloDeck.js').then((m) => m.unmountDeck()).catch(() => { /* nothing was mounted */ });
}

function _agentMode() {
  const agent = byId('mode-agent-btn');
  const chat = byId('mode-chat-btn');
  if (!agent) return;
  if (chat && chat.classList.contains('active') && !agent.classList.contains('active')) {
    _priorMode = 'chat';
    agent.click();
  }
}

function _restoreMode() {
  if (_priorMode === 'chat') byId('mode-chat-btn')?.click();
  _priorMode = null;
}

/** Turn the page into Apollo's. `hooks`: { name, openSettings, extraButtons }. */
export function enterApolloView(hooks = {}) {
  _hooks = hooks || {};
  const html = document.documentElement;
  // Only when it isn't on yet: New chat and the switch enter this page while
  // it is up, and a second write wakes every class watcher on the page.
  if (html && !html.classList.contains('apollo-view')) html.classList.add('apollo-view');
  _buildBar();
  if (!_on) {
    _agentMode();
    const input = byId('message');
    if (input) {
      _priorPrompt = input.placeholder;
      input.placeholder = PROMPT;
    }
    _on = true;
    _mountDeck();
  }
  _on = true;
  _syncSwitch();
}

/** Put the generic chat page back. */
export function leaveApolloView() {
  if (!_on) return;
  _on = false;
  const html = document.documentElement;
  if (html) html.classList.remove('apollo-view');
  byId(BAR_ID)?.remove();
  _unmountDeck();
  _restoreMode();
  const input = byId('message');
  if (input && _priorPrompt !== null) input.placeholder = _priorPrompt;
  _priorPrompt = null;
  import('./apolloPane.js').then((m) => { if (m.isApolloPaneOpen()) m.closeApolloPane(); }).catch(() => {});
  _syncSwitch();
}

export function isApolloView() { return _on; }
