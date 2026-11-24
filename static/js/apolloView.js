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
//   - Its pane opened and docked on the right, so the work is on the page
//     from the first look rather than behind a button.
//   - Its own empty state and composer prompt.
// Leaving the chat puts every one of those back.

const BAR_ID = 'apollo-bar';
const EMPTY_ID = 'apollo-empty';
const PROMPT = 'Tell Apollo what you need';

const SUN = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></svg>';
const PANE = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M14.5 4.5v15"/></svg>';
const GEAR = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/></svg>';

let _on = false;
let _priorMode = null;        // 'chat' when the person had Chat mode on before Apollo
let _priorPrompt = null;      // the composer's own placeholder, put back on the way out
let _hooks = {};

const byId = (id) => document.getElementById(id);
const root = () => document.documentElement || document.body;

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
    space.appendChild(Sp.createSwitcher().el);
  }).catch(() => {});
  return bar;
}

function _buildEmpty() {
  if (byId(EMPTY_ID)) return;
  const history = byId('chat-history');
  if (!history || !history.parentNode) return;
  const box = document.createElement('section');
  box.id = EMPTY_ID;
  box.className = 'apo-empty';
  box.setAttribute('aria-label', 'Apollo');
  const mark = document.createElement('div');
  mark.className = 'apo-empty-mark';
  mark.innerHTML = SUN;
  const title = document.createElement('div');
  title.className = 'apo-empty-t';
  title.textContent = _hooks.name || 'Apollo';
  const line = document.createElement('p');
  line.className = 'apo-empty-p';
  line.textContent = "Tell me what you're working toward. I'll set up the work, run it with the right agents, and come back when something needs you.";
  box.appendChild(mark);
  box.appendChild(title);
  box.appendChild(line);
  history.parentNode.insertBefore(box, history);
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
  const html = root();
  if (html && html.classList) html.classList.add('apollo-view');
  _buildBar();
  _buildEmpty();
  if (!_on) {
    _agentMode();
    const input = byId('message');
    if (input) {
      _priorPrompt = input.placeholder;
      input.placeholder = PROMPT;
    }
    import('./apolloPane.js').then((m) => { if (_on && !m.isApolloPaneOpen()) _openPane(m); }).catch(() => {});
  }
  _on = true;
}

/** Put the generic chat page back. */
export function leaveApolloView() {
  if (!_on) return;
  _on = false;
  const html = root();
  if (html && html.classList) html.classList.remove('apollo-view');
  byId(BAR_ID)?.remove();
  byId(EMPTY_ID)?.remove();
  _restoreMode();
  const input = byId('message');
  if (input && _priorPrompt !== null) input.placeholder = _priorPrompt;
  _priorPrompt = null;
  import('./apolloPane.js').then((m) => { if (m.isApolloPaneOpen()) m.closeApolloPane(); }).catch(() => {});
}

export function isApolloView() { return _on; }
