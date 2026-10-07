# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B-NEW-3`, `B-NEW-4`, `B-NEW-6` — Back walks the chats a person opened, and
never a chat that is gone.

Measured on `a936b5c` (`/work/notes/p23-acceptance.md`) and again on `cdf040f`
in Chromium with the browser's own Back:

  * **B-NEW-3.** At 390×844 a chat picked in the phone drawer never became a
    history entry: ☰ → chat A → ☰ → chat B, the URL `/` after each tap, and
    Back left the app (`about:blank`). The switch replaced the URL of the
    drawer's entry, the drawer closed, and the back stack took the drawer's
    entry off with `history.back()` — the entry that now carried the chat.
  * **B-NEW-4.** At 1440×900 the first chat opened from the welcome screen
    replaced the welcome's entry (`history.length` 2 → 2), so Back from it left
    the app.
  * **B-NEW-6.** Reply in the mail reader pushed `/email#<helper chat>`; Close
    deleted that chat and pushed `/email#<the chat before>`; the second Back
    landed on `/email#<deleted chat>` and nothing on screen changed.

Driven here, not read (`Law 20`): the real `static/js/backStack.js` under node
over the session history `tests/test_one_back_stack_js.py` built (entries and
an index; `back()` fires `popstate` a task later), with `hashchange` after a
`popstate` that changes the fragment, as a browser fires it; and the real
`sessions.js` functions that write a switch into the URL and answer Back
(`chatSwitchIsAnEntry`, `_writeChatUrl`, `_onHashChange`,
`_welcomeFromHistory`, `_deselectCurrentSession`), the mail Reply's
`_createEmailChat` (`emailInbox.js`) and the draft's way back
`_leaveDeletedChat` (`document.js`), cut out of the shipped files with
`js_definition`. What stands in for `selectSession` is its order of events —
the chat, then the URL, then (a person's tap on a phone) the drawer away.

**The adversary is the phone's Back button** (`Law 17`): it is the only way
back a phone has, and it left the app.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests.helpers.js_source import js_definition  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_one_back_stack_js import _SHIM as _BACK_SHIM, _PREAMBLE as _BACK_PREAMBLE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
BACK_JS = JS / "backStack.js"
SESSIONS_JS = (JS / "sessions.js").read_text(encoding="utf-8")
INBOX_JS = (JS / "emailInbox.js").read_text(encoding="utf-8")
DOC_JS = (JS / "document.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _cut(source: str, *signatures: str) -> str:
    return "\n".join(js_definition(source, source.index(sig)) for sig in signatures)


# A browser fires `hashchange` after the `popstate` of a traversal whose
# fragment differs, a task later; `pushState` / `replaceState` fire neither.
_SHIM = _BACK_SHIM + r"""
const _hashListeners = [];
const _addListener = globalThis.addEventListener;
globalThis.addEventListener = (t, fn, o) => { if (t === 'hashchange') _hashListeners.push(fn); else _addListener(t, fn, o); };
const _go = history.go;
history.go = function go(d) {
  const before = location.hash;
  _go.call(this, d);
  setTimeout(() => { if (location.hash !== before) _hashListeners.forEach((f) => f({ type: 'hashchange' })); }, 0);
};
/** A click on `<a href="#">`: a new entry with no state and no fragment. */
export function hashLinkClick() {
  history.pushState(null, '', location.pathname + '#');
  location.hash = '';
  _hashListeners.forEach((f) => f({ type: 'hashchange' }));
}
"""

_SESSIONS = _cut(SESSIONS_JS, "function chatSwitchIsAnEntry(", "function _writeChatUrl(",
                 "function _onHashChange(", "function _welcomeFromHistory(",
                 "function _deselectCurrentSession(", "function _syncAttachmentsToSession(")

_PREAMBLE = _BACK_PREAMBLE.replace(
    "import { document, Node, H, history, pressBack,",
    "import { hashLinkClick } from './shim.js';\nimport { document, Node, H, history, pressBack,",
) + r"""
const backStack = B;
// ── the page around the chat list ──────────────────────────────────────────
const sb = document.body.appendChild(new Node('div')); sb.setAttribute('id', 'sidebar'); sb.className = 'sidebar hidden';
const bd = document.body.appendChild(new Node('div')); bd.setAttribute('id', 'sidebar-backdrop');
const drawerUp = () => !sb.classList.contains('hidden');
const openDrawer = () => { sb.classList.remove('hidden'); bd.classList.add('visible'); };
const closeDrawer = () => { sb.classList.add('hidden'); bd.classList.remove('visible'); };
B.configure({ closeWindow: (id) => { log.push('close ' + id);
  if (id === 'sidebar-drawer') closeDrawer(); else if (!asks.has(id)) down(id); } });
for (const id of ['chat-history', 'current-meta']) {
  const n = document.body.appendChild(new Node('div')); n.setAttribute('id', id);
}
document.getElementById('chat-history').innerHTML = '<div class="msg">hello</div>';
const shown = [];
const uiModule = { el: (id) => document.getElementById(id) };
const Storage = { remove: (k) => shown.push('forget ' + k), set() {}, get: () => null };
const updateModelPicker = () => {};
window.chatModule = { showWelcomeScreen: () => shown.push('welcome'), detachCurrentStream: (id) => shown.push('detach ' + id) };
window.documentModule = { isPanelOpen: () => false };
// ── the chats ──────────────────────────────────────────────────────────────
let currentSessionId = null;
let _sessionNavToken = 0;
const sessions = [{ id: 'chatA' }, { id: 'chatB' }, { id: 'week' }, { id: 'helper-9' }];
const selects = [];
/** `selectSession`'s order of events: the chat, its URL, then — a person's
 *  tap in the phone drawer — the drawer away. */
async function selectSession(id, { keepSidebar = false, fromHistory = false, replace = false } = {}) {
  selects.push([id, fromHistory ? 'history' : replace ? 'replace' : 'person']);
  const prevSessionId = currentSessionId;
  currentSessionId = id;
  _writeChatUrl(id, prevSessionId, { fromHistory, replace });
  if (!keepSidebar && drawerUp()) closeDrawer();
}
const sessionModule = {
  getCurrentSessionId: () => currentSessionId, getSessions: () => sessions,
  loadSessions: async () => {}, selectSession,
};
const back = async () => { pressBack(); await settle(); await step(); await settle(); };
const forward = async () => { pressForward(); await settle(); await step(); await settle(); };
const urls = () => H.entries.map((e) => String(e.url).replace(/^http:\/\/t\.local/, ''));
const here = () => ({ url: location.pathname + location.hash, n: H.entries.length, chat: currentSessionId });
""" + _SESSIONS + "\nwindow.addEventListener('hashchange', _onHashChange);\n"


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("backchats"), BACK_JS, _SHIM, {})


def _case(box, script, start="/", chat=None):
    boot = (f"history.replaceState(null, '', {json.dumps(start)});\n"
            f"currentSessionId = {json.dumps(chat)};\n"
            "B.init(); B.ready(); await settle();\n")
    return _run(box, _PREAMBLE + boot, script)


# ── B-NEW-3 · the phone drawer ─────────────────────────────────────────────

def test_two_chats_picked_in_the_phone_drawer_are_two_entries_and_back_walks_them(box):
    """`P23-00`'s third sentence at 390×844: ☰ → A → ☰ → B; Back is A; Back is
    the welcome screen they started on; one more Back is the browser's."""
    o = _case(box, """
        openDrawer(); await step();
        const drawer = here();
        await selectSession('chatA');
        const tappedA = location.pathname + location.hash;     // before the back stack runs
        await step(); await settle();
        const afterA = { ...here(), state: top().state };
        openDrawer(); await step();
        await selectSession('chatB');
        await step(); await settle();
        const afterB = here();
        await back();
        const back1 = here();
        await back();
        const back2 = { ...here(), shown: shown.slice(), history: document.getElementById('chat-history').innerHTML };
        pressBack(); await settle();
        out({ drawer, tappedA, afterA, afterB, back1, back2, left: H.left, ourBacks: H.backs, urls: urls() });
    """)
    assert o["drawer"] == {"url": "/", "n": 2, "chat": None}
    assert o["tappedA"] == "/#chatA", "the URL names the chat as soon as it is picked"
    # The drawer's entry stayed, as chat A's — no `history.back()` took it off.
    assert o["afterA"] == {"url": "/#chatA", "n": 2, "chat": "chatA",
                           "state": {"wins": [], "opened": None}}
    assert o["afterB"] == {"url": "/#chatB", "n": 3, "chat": "chatB"}
    assert o["ourBacks"] == 0
    assert o["urls"] == ["/", "/#chatA", "/#chatB"]
    assert o["back1"] == {"url": "/#chatA", "n": 3, "chat": "chatA"}
    assert o["back2"]["url"] == "/" and o["back2"]["chat"] is None
    assert "welcome" in o["back2"]["shown"] and "detach chatA" in o["back2"]["shown"]
    assert o["back2"]["history"] == "", "the chat's messages are not left under the welcome screen"
    assert o["left"] is True, "the welcome screen is the app's first page: the next Back is the browser's"


def test_the_drawer_closed_without_a_pick_still_takes_its_entry_off(box):
    """The rule `B-NEW-3` changes is narrow: a drawer opened and closed with no
    chat picked goes, entry and all, as it did."""
    o = _case(box, """
        openDrawer(); await step();
        closeDrawer(); await step(); await settle(); await step();
        out({ ...here(), ourBacks: H.backs });
    """, start="/#chatA", chat="chatA")
    assert o == {"url": "/#chatA", "n": 2, "chat": "chatA", "ourBacks": 1}


def test_a_chat_picked_while_the_drawer_s_entry_is_coming_off_waits_for_the_entry_beneath(box):
    """The drawer went first and the back stack's own `back()` is under way:
    the switch is written on the entry that pop lands on, not on the one it
    takes off."""
    o = _case(box, """
        openDrawer(); await step();
        closeDrawer(); B.sync();                // the pop is under way
        await selectSession('chatB');
        await settle(); await step(); await settle();
        const after = here();
        await back();
        out({ after, back1: here(), urls: urls() });
    """, start="/#chatA", chat="chatA")
    assert o["after"]["url"] == "/#chatB" and o["after"]["chat"] == "chatB"
    assert o["urls"][:2] == ["/#chatA", "/#chatB"]
    assert o["back1"]["url"] == "/#chatA" and o["back1"]["chat"] == "chatA"


def test_a_window_closed_as_a_chat_opens_gives_its_entry_to_the_chat(box):
    """The same rule for a window: Tasks closes in the same click that opens a
    chat from it; its entry becomes the chat's, not a stale one under it."""
    o = _case(box, """
        up('tasks-modal'); await step();
        down('tasks-modal');                    // closed; the back stack has not run yet
        await selectSession('chatB');
        await step(); await settle(); await step();
        const after = here();
        await back();
        out({ after, back1: here(), urls: urls(), ourBacks: H.backs });
    """, start="/#chatA", chat="chatA")
    assert o["after"] == {"url": "/#chatB", "n": 2, "chat": "chatB"}
    assert o["urls"] == ["/#chatA", "/#chatB"]
    assert o["back1"] == {"url": "/#chatA", "n": 2, "chat": "chatA"}
    assert o["ourBacks"] == 0


# ── B-NEW-4 · the welcome screen ───────────────────────────────────────────

def test_the_first_chat_from_the_welcome_screen_is_an_entry_and_back_is_the_welcome_screen(box):
    """At 1440×900: welcome → A → B; Back is A, Back is the welcome screen,
    Forward is A again."""
    o = _case(box, """
        await selectSession('chatA');
        const afterA = here();
        await selectSession('chatB');
        await back();
        const back1 = here();
        await back();
        const back2 = { ...here(), shown: shown.slice() };
        await forward();
        const fwd = here();
        out({ afterA, back1, back2, fwd, selects });
    """)
    assert o["afterA"] == {"url": "/#chatA", "n": 2, "chat": "chatA"}
    assert o["back1"] == {"url": "/#chatA", "n": 3, "chat": "chatA"}
    assert o["back2"]["url"] == "/" and o["back2"]["chat"] is None and "welcome" in o["back2"]["shown"]
    assert o["fwd"] == {"url": "/#chatA", "n": 3, "chat": "chatA"}
    assert o["selects"] == [["chatA", "person"], ["chatB", "person"], ["chatA", "history"], ["chatA", "history"]]


def test_which_switches_are_entries(box):
    """A person's switch is an entry — from a chat the URL names, or from the
    welcome screen; Back's own, the list's own pick and a helper chat are not."""
    o = _case(box, """
        const cases = {
          fromWelcome: chatSwitchIsAnEntry(null, 'A', { hash: '' }),
          fromChat: chatSwitchIsAnEntry('A', 'B', { hash: '#A' }),
          sameChat: chatSwitchIsAnEntry('A', 'A', { hash: '#A' }),
          fromAChatTheUrlDoesNotName: chatSwitchIsAnEntry('assistant', 'B', { hash: '#A' }),
          fromADeepLink: chatSwitchIsAnEntry(null, 'A', { hash: '#document-7' }),
          back: chatSwitchIsAnEntry(null, 'A', { hash: '', fromHistory: true }),
          replace: chatSwitchIsAnEntry('A', 'B', { hash: '#A', replace: true }),
        };
        out(cases);
    """)
    assert o == {"fromWelcome": True, "fromChat": True, "sameChat": False, "fromAChatTheUrlDoesNotName": False,
                 "fromADeepLink": False, "back": False, "replace": False}


def test_a_click_on_an_empty_hash_link_keeps_the_chat(box):
    """Many `<a href="#">` in the app: a click lands on a new entry with no
    state and no fragment. That is not Back to the welcome screen."""
    o = _case(box, """
        hashLinkClick();
        out({ chat: currentSessionId, shown, owns: B.ownsEntry() });
    """, start="/#chatA", chat="chatA")
    assert o == {"chat": "chatA", "shown": [], "owns": False}


# ── B-NEW-6 · the mail's helper chat ───────────────────────────────────────

_MAIL = r"""
const API_BASE = '';
globalThis.fetch = async (url, init = {}) => {
  if (url === '/api/default-chat') return { ok: true, json: async () => ({ endpoint_url: 'http://m', model: 'm' }) };
  return { ok: true, status: 200, json: async () => ({ id: 'helper-9' }) };
};
const _docModule = { noteHelperChat: () => {} };
makeWin('email-lib-modal');
""" + _cut(INBOX_JS, "async function _createEmailChat(") + "\n" + _cut(DOC_JS, "async function _leaveDeletedChat(")


def test_reply_then_close_leaves_no_entry_naming_the_deleted_chat(box):
    """The acceptance's Reply → Close → Back, Back: the helper chat takes the
    mail entry's `#chat` and gives it back; Back closes the mail onto the chat
    replied from; nothing names the deleted chat."""
    o = _case(box, _MAIL + """
        up('email-lib-modal'); await step();
        const mail = here();
        const sid = await _createEmailChat({ subject: 'Q3 Board Pack' }, { forceNew: true });
        const during = here();
        await _leaveDeletedChat(sid, 'week');   // the draft's Close: the helper is deleted
        const closed = here();
        await back();
        out({ sid, mail, during, closed, back1: { ...here(), mail: isUp('email-lib-modal') }, urls: urls(), selects });
    """, start="/#week", chat="week")
    assert o["sid"] == "helper-9"
    assert o["mail"] == {"url": "/email#week", "n": 2, "chat": "week"}
    assert o["during"] == {"url": "/email#helper-9", "n": 2, "chat": "helper-9"}
    assert o["closed"] == {"url": "/email#week", "n": 2, "chat": "week"}
    assert o["back1"] == {"url": "/#week", "n": 2, "chat": "week", "mail": False}
    assert not any("helper-9" in u for u in o["urls"]), o["urls"]
    assert o["selects"] == [["helper-9", "replace"], ["week", "replace"]]


def test_closing_the_mail_while_the_reply_chat_is_open_keeps_that_chat(box):
    """The replace has a second half: the mail entry now names the reply's chat,
    so closing the mail keeps that chat on screen — its entry stays, as the
    chat's — rather than `back()` onto the chat replied from."""
    o = _case(box, _MAIL + """
        up('email-lib-modal'); await step();
        await _createEmailChat({ subject: 'Q3 Board Pack' }, { forceNew: true });
        down('email-lib-modal'); await step(); await settle(); await step();
        const closed = here();
        await back();
        out({ closed, back1: here(), ourBacks: H.backs, selects });
    """, start="/#week", chat="week")
    assert o["closed"] == {"url": "/#helper-9", "n": 2, "chat": "helper-9"}
    assert o["ourBacks"] == 0
    assert o["back1"] == {"url": "/#week", "n": 2, "chat": "week"}
