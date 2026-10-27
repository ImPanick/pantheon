# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1559` — typing while a reply is arriving leaves the send button receiving.

`.send-btn` is `FORBIDDEN.md` Part 1: its states and titles are the machine and
do not move. Inside the `streaming` state it carries a `data-phase` —
`processing` while the run works, `receiving` once the first token has arrived
(`chat.js`), each with its own look (`style.css`
`.send-btn[data-mode="streaming"][data-phase=…]`). `_updateStreamingSubmitButton`
(`app.js`) runs on every keystroke while streaming and returned early only for
`processing`, so a keystroke during `receiving` reset the phase to
`processing`: the button went back to its waiting look for as long as someone
typed during a reply. The launch animation's 300 ms timer in
`chat.js` `updateSubmitButton` made the same flip when the first token beat it.

Neither changes a state or a title now; each only sets a phase where it would
not erase `receiving`. Driven under node on the real functions cut out of the
two files (`Law 20`), with the button stub `P23-04`'s test uses.
"""

from pathlib import Path

from tests.test_the_send_button_and_the_mode_follow_the_chat import _BUTTON, _cut, _node

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "static" / "app.js"
CHAT = ROOT / "static" / "js" / "chat.js"


def _app_button():
    return (_BUTTON + _cut(APP, "function _updateStreamingSubmitButton(") + "\n"
            + _cut(APP, "function _updateSendBtnIcon(") + "\n")


def test_typing_during_receiving_leaves_the_phase_receiving(tmp_path):
    """The row's `Verify:`."""
    out = _node(tmp_path, _app_button() + """
        sendBtn.dataset.mode = 'streaming';
        sendBtn.dataset.phase = 'receiving';
        sendBtn.title = 'Stop generation';
        sendBtn.innerHTML = 'STOP';
        const seen = [];
        for (const text of ['h', 'he', 'hel', '']) {
          messageInput.value = text;
          _updateSendBtnIcon();
          seen.push({ phase: sendBtn.dataset.phase, title: sendBtn.title, icon: sendBtn.innerHTML });
        }
        console.log(JSON.stringify(seen));
    """)
    assert out == [{"phase": "receiving", "title": "Stop generation", "icon": "STOP"}] * 4


def test_typing_while_processing_is_unchanged(tmp_path):
    out = _node(tmp_path, _app_button() + """
        sendBtn.dataset.mode = 'streaming';
        sendBtn.dataset.phase = 'processing';
        sendBtn.title = 'Stop generation';
        messageInput.value = 'a draft';
        _updateSendBtnIcon();
        console.log(JSON.stringify({ phase: sendBtn.dataset.phase, title: sendBtn.title }));
    """)
    assert out == {"phase": "processing", "title": "Stop generation"}


def test_a_streaming_button_with_no_phase_still_gets_processing(tmp_path):
    """The machine's own default, kept: Stop is drawn and the phase is set."""
    out = _node(tmp_path, _app_button() + """
        sendBtn.dataset.mode = 'streaming';
        messageInput.value = 'x';
        _updateSendBtnIcon();
        console.log(JSON.stringify({ phase: sendBtn.dataset.phase, title: sendBtn.title, icon: sendBtn.innerHTML }));
    """)
    assert out == {"phase": "processing", "title": "Stop generation", "icon": "STOP"}


_CHAT_STUBS = """
const timers = [];
globalThis.setTimeout = (f) => { timers.push(f); return timers.length; };
const stopIcon = () => 'STOPSVG';
let isStreaming = false;
function _setForegroundChatBusy() {}
function _startStallWatchdog() {}
function _stopStallWatchdog() {}
globalThis.window = { _pantheonBtnIcons: { send: 'SEND' } };
sendBtn.offsetWidth = 0;
"""


def test_the_launch_timer_does_not_undo_a_first_token(tmp_path):
    """A first token inside the 300 ms launch animation moves the phase to
    `receiving`; the icon swap that follows draws Stop and leaves it."""
    out = _node(tmp_path, _BUTTON + _CHAT_STUBS + _cut(CHAT, "function updateSubmitButton(") + """
        updateSubmitButton('streaming', sendBtn);
        const started = sendBtn.dataset.phase;
        sendBtn.dataset.phase = 'receiving';      // chat.js, on the first delta
        timers.splice(0).forEach((f) => f());     // the 300 ms launch timer
        console.log(JSON.stringify({ started, after: sendBtn.dataset.phase,
                                     title: sendBtn.title, icon: sendBtn.innerHTML }));
    """)
    assert out == {"started": "processing", "after": "receiving",
                   "title": "Stop generation", "icon": "STOPSVG"}


def test_the_launch_timer_still_lands_processing_before_a_token(tmp_path):
    out = _node(tmp_path, _BUTTON + _CHAT_STUBS + _cut(CHAT, "function updateSubmitButton(") + """
        updateSubmitButton('streaming', sendBtn);
        timers.splice(0).forEach((f) => f());
        console.log(JSON.stringify({ phase: sendBtn.dataset.phase, mode: sendBtn.dataset.mode }));
    """)
    assert out == {"phase": "processing", "mode": "streaming"}
