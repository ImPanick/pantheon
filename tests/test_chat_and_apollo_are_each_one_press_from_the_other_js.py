# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chat and Apollo are each one press from the other.

The owner's test (2026-11-24): "Once apollo is opened, there's no way to leave
apollo mode and go back to the base 'chatbot' mode of Pantheon... I want to
serve both options.. A chat mode, with agent calls.. and then a pure 'agent
coworker/partner' mode.."

Two things kept him in Apollo. New chat cleared the open chat without the
`session-changed` event Apollo's page listens for, so the page stayed up over
the new chat; and nothing on Apollo's page said "go back". Checked here, with
the real `assistant.js`, `apolloView.js` and `modeSwitch.js`:
  * the Chat / Apollo switch is drawn at the end of the top bar and lights the
    mode the page is in;
  * Apollo -> Chat goes back to the last chat that wasn't Apollo's, or, with
    none to go back to, opens a new chat and puts the chat page back;
  * Chat -> Apollo opens Apollo's chat and its page;
  * New chat, delete or archive of the open chat puts the chat page back.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
ASSISTANT = JS / "assistant.js"
SESSIONS = JS / "sessions.js"

node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom } from './dom.js';
export const document = installDom();
if (!document.documentElement) document.documentElement = document.createElement('html');
globalThis.window = globalThis.window || globalThis;
export const state = { current: null, newChats: 0, toasts: [], selected: [] };
export const APOLLO = 'apollo-chat-id';
export const rows = [
  { id: APOLLO, name: 'Apollo', folder: 'Assistant' },
  { id: 'rack', name: 'Rack power plan' },
  { id: 'old', name: 'Gone', archived: true },
];
globalThis.fetch = async (url) => {
  let out = {};
  if (url.endsWith('/api/assistant/session')) out = { session_id: APOLLO };
  else if (url.endsWith('/api/assistant/settings')) out = { crew: { session_id: APOLLO } };
  return { ok: true, status: 200, json: async () => out };
};
export function settle(n = 30) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
export function page() {
  const cc = document.createElement('main'); cc.id = 'chat-container';
  const top = document.createElement('div'); top.className = 'chat-top-bar';
  const meta = document.createElement('div'); meta.className = 'chat-meta-overlay'; top.appendChild(meta);
  const hist = document.createElement('div'); hist.id = 'chat-history';
  const input = document.createElement('textarea'); input.id = 'message'; input.placeholder = 'Message Pantheon';
  cc.appendChild(top); cc.appendChild(hist); cc.appendChild(input);
  // New chat: what `sessions.js:createDirectChat` does to the page, as far as Apollo can see.
  const fresh = document.createElement('button'); fresh.id = 'rail-new-session';
  fresh.addEventListener('click', () => {
    state.newChats += 1; state.current = null;
    document.dispatchEvent(new CustomEvent('pantheon:session-cleared'));
  });
  document.body.appendChild(fresh);
  document.body.appendChild(cc);
  return { top };
}
"""

_SESSIONS = r"""
import { document, state, rows } from './shim.js';
export function getSessions() { return rows; }
export function getCurrentSessionId() { return state.current; }
export async function selectSession(id) {
  state.current = id; state.selected.push(id);
  document.dispatchEvent(new CustomEvent('pantheon:session-changed', { detail: { sessionId: id } }));
}
export default { getSessions, getCurrentSessionId, selectSession };
"""

_STUBS = {
    "ui.js": "import { state } from './shim.js';\nexport default { showToast: (m) => state.toasts.push(m) };\n",
    "modelSort.js": "export function sortModelIds(x) { return x; }\n",
    "ui_visibility.js": "export async function toolPollMayAsk() { return true; }\n",
    "sessions.js": _SESSIONS,
    "apolloSpaces.js": (
        "import { document } from './shim.js';\n"
        "export async function spaceOfSession() { return undefined; }\n"
        "export function noteSpace() {}\n"
        "export function createSwitcher() { return { el: document.createElement('span') }; }\n"
    ),
    "apolloConversations.js": "export function barButtons() { return []; }\n",
    "apolloOrb.js": "export function setApolloChat() {}\n",
    "apolloDeck.js": "export function mountDeck() {}\nexport function unmountDeck() {}\n",
    "apolloPane.js": (
        "export function isApolloPaneOpen() { return false; }\n"
        "export function openApolloPane() {}\nexport function closeApolloPane() {}\n"
    ),
    # Imported dynamically, so the sandbox carries the real files.
    "apolloView.js": (JS / "apolloView.js").read_text(encoding="utf-8"),
    "modeSwitch.js": (JS / "modeSwitch.js").read_text(encoding="utf-8"),
}

_PREAMBLE = (
    "import { document, state, APOLLO, settle, page } from './shim.js';\n"
    "const P = page();\n"
    "localStorage.clear?.();\n"
    "const A = await import('./assistant.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const html = document.documentElement;\n"
    "const sw = () => document.getElementById('pan-mode-switch');\n"
    "const btn = (m) => sw().querySelectorAll('.pan-mode-btn').find((b) => b.dataset.mode === m);\n"
    "const lit = () => sw().querySelectorAll('.pan-mode-btn').filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.mode);\n"
    "const view = () => ({ apollo: html.classList.contains('apollo-view'), bar: !!document.getElementById('apollo-bar'), lit: lit() });\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("modes"), ASSISTANT, _SHIM, _STUBS)


@node
def test_the_switch_sits_at_the_end_of_the_top_bar_and_lights_chat_on_a_chat(box):
    o = _run(box, _PREAMBLE, """
        await settle();
        const kids = P.top.childNodes.map((n) => n.id || n.className);
        out({ last: kids[kids.length - 1], labels: sw().querySelectorAll('.pan-mode-btn').map((b) => b.textContent), ...view() });
    """)
    assert o == {"last": "pan-mode-switch", "labels": ["Chat", "Apollo"], "apollo": False, "bar": False, "lit": ["chat"]}


@node
def test_chat_to_apollo_and_back_to_the_chat_you_were_in(box):
    o = _run(box, _PREAMBLE, """
        await settle();
        const { selectSession } = await import('./sessions.js');
        await selectSession('rack');
        await settle();
        btn('apollo').click();
        await settle();
        const inApollo = { current: state.current, ...view() };
        btn('chat').click();
        await settle();
        out({ inApollo, back: { current: state.current, newChats: state.newChats, ...view() } });
    """)
    assert o["inApollo"] == {"current": "apollo-chat-id", "apollo": True, "bar": True, "lit": ["apollo"]}
    assert o["back"] == {"current": "rack", "newChats": 0, "apollo": False, "bar": False, "lit": ["chat"]}


@node
def test_with_no_chat_to_go_back_to_chat_opens_a_new_one(box):
    o = _run(box, _PREAMBLE, """
        await settle();
        await A.openAssistantChat();
        await settle();
        const before = view();
        btn('chat').click();
        await settle();
        out({ before, after: { newChats: state.newChats, ...view() } });
    """)
    assert o["before"]["apollo"] is True
    assert o["after"] == {"newChats": 1, "apollo": False, "bar": False, "lit": ["chat"]}


@node
def test_new_chat_from_apollo_puts_the_chat_page_back(box):
    o = _run(box, _PREAMBLE, """
        await settle();
        await A.openAssistantChat();
        await settle();
        document.getElementById('rail-new-session').click();
        await settle();
        out(view());
    """)
    assert o == {"apollo": False, "bar": False, "lit": ["chat"]}


def test_sessions_says_so_when_no_chat_is_open_any_more():
    src = SESSIONS.read_text(encoding="utf-8")
    assert "new CustomEvent('pantheon:session-cleared')" in src

    def body(name: str) -> str:
        start = src.index(f"function {name}(")
        end = src.index("\n}\n", start)
        return src[start:end]

    # Delete and archive both go through `_deselectCurrentSession`; New chat is `createDirectChat`.
    assert "_announceSessionCleared();" in body("_deselectCurrentSession")
    assert "_announceSessionCleared();" in body("createDirectChat")
    assert "'pantheon:session-cleared'" in ASSISTANT.read_text(encoding="utf-8")


def test_the_switch_is_styled_in_both_themes():
    cockpit = (ROOT / "static" / "cockpit.css").read_text(encoding="utf-8")
    style = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert re.search(r"html\.cockpit \.pan-mode-btn\.active \{", cockpit)
    assert ".pan-mode-btn.active {" in style
