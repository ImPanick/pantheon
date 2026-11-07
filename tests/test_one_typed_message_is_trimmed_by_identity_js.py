# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx7-dup (`B1323`) — which message a resend cuts the chat back to.

The owner's own export holds their one typed message twice
(`/work/notes/owner-shots/2026-10-09-osrs-chat-export.md`, lines 1 and 4) and
the model's reasoning for the next turn reads it twice: *"Second section:
Research: … Third section: Repeat of research request"*.

Measured on `3b40a4e`: one send saves one row on every path. What saved the
second copy was the **trim** the three re-send flows do first — Retry on a
failed reply (`_retryLastTurn` → `resendUserMessage(…, {replaceFromHere})`),
*Edit* a message, and *Regenerate* a reply. Each posted `keep_count` taken from
the clicked bubble's index among `#chat-history`'s `.msg` elements, and that is
not an index into the stored rows: an agent turn draws **two** `.msg` for one
saved reply (`B1332`'s footer copy — `data-raw-echo` while it streams,
`.msg-continuation` after a reload). One bubble too many, and the trim kept the
very message it was asked to drop; the resend then stored a second copy of it.

So the browser now says *which* user message, counted back from the newest
among the bubbles that stand for a stored row, and what it says. These cases
drive the five functions that do it, cut out of `static/js/chat.js` and run on
the suite's DOM shim with the drift the browser really produced: six `.msg` for
four rows.

`B1986`. A message's *Fork* kept the same number after `B1323`: it posted
`keep_count` = the clicked bubble's place among the `.msg` + 1, and the route
copied that many rows. A chat opens on its newest 24 rows (`sessions.js`,
`HISTORY_PAGE_LIMIT_DESKTOP`; 8 on a phone), so Fork on the newest reply of a
42-message chat copied the first 24 rows and none of the newest 18; and Fork on
an agent reply, drawn as two bubbles, copied the next message too. Fork now
names the reply by its row's id, read the way a reaction reads it
(`reactions.js` `replyIdFor`), and posts no count at all.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "static" / "js" / "chat.js"
REACTIONS = ROOT / "static" / "js" / "reactions.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SIGNATURES = (
    "function _storedUserBubbles(",
    "function _userBubbleText(",
    "function _userMessageCut(",
    "async function _truncateFromUserMessage(",
    "function _retryLastTurn(",
)


def _cut(extra=()) -> str:
    """The five, and any `(file, signature)` a case adds in `extra`."""
    out = []
    for path, sig in [(CHAT, sig) for sig in _SIGNATURES] + list(extra):
        src = path.read_text(encoding="utf-8")
        assert src.count(sig) == 1, f"{sig!r} appears {src.count(sig)} times in {path.name}"
        out.append(js_definition(src, src.index(sig)))
    return "\n\n".join(out)


@pytest.fixture(scope="module")
def dom_dir(tmp_path_factory):
    """The suite's own DOM shim on disk (`Law 14` — not a second one)."""
    import test_tool_effect_surfaces_js as harness

    directory = tmp_path_factory.mktemp("trimidentity")
    (directory / "dom.js").write_text(harness._DOM)
    # `B1986`: `replyIdFor` walks back from a footer's bubble to the turn's
    # earlier bubbles, as a browser's `previousElementSibling` does.
    (directory / "shim.js").write_text(
        "import { installDom, Node } from './dom.js';\n"
        "export const document = installDom();\n"
        "Object.defineProperty(Node.prototype, 'previousElementSibling', { get() {\n"
        "  const kids = this.parentNode ? this.parentNode.children : [];\n"
        "  const at = kids.indexOf(this);\n"
        "  return at > 0 ? kids[at - 1] : null;\n"
        "} });\n")
    return directory


# The chat the browser really drew, measured in Chromium on 8782 against a
# recording model: two agent turns, four stored rows, SIX `.msg` elements —
# each reply's hidden holder plus the `.msg-continuation` bubble its footer
# sits under. `buildChat()` returns the bubbles in the order they are drawn.
_PRE = r"""
import { document } from './shim.js';
const API_BASE = '';
const posted = [];
let reply = { ok: true, status: 200 };
globalThis.fetch = async (url, init) => {
  posted.push({ url: String(url), body: JSON.parse(init.body) });
  if (reply.throws) throw new Error('offline');
  return { ...reply, text: async () => reply.text || '' };
};
globalThis.readRefusal = async (res, fallback) => ({ sentence: reply.sentence || fallback });
const shown = [];
const toasts = [];
const uiModule = { showError: (s) => shown.push(s), showToast: (s) => toasts.push(s) };
const opened = [];
const sessionModule = {
  getCurrentSessionId: () => 's-1',
  loadSessions: async () => {},
  selectSession: async (id) => { opened.push(id); },
  forkTitle: (name) => ({ title: String(name || '').replace(/^Fork: /, '') }),
};
// Read when called: `replyIdFor` is in the source only when a case cuts it.
const reactionsModule = { replyIdFor: (el) => replyIdFor(el) };
const resent = [];
globalThis.resendUserMessage = (el, opts) => { resent.push({ text: el && el.dataset.raw, opts }); };

const box = document.createElement('div');
box.id = 'chat-history';
document.body.appendChild(box);
document.getElementById = (id) => (id === 'chat-history' ? box : null);

function bubble(cls, raw) {
  const el = document.createElement('div');
  el.className = cls;
  if (raw !== undefined) el.dataset.raw = raw;
  const body = document.createElement('div');
  body.className = 'body';
  body.textContent = raw === undefined ? '' : raw;
  el.appendChild(body);
  box.appendChild(el);
  return el;
}

/** Two agent turns: user, hidden holder, continuation, user, holder,
 *  continuation. Six `.msg`, four rows. */
function buildChat() {
  const u1 = bubble('msg msg-user', 'Alpha: what do we fight in the fractured archive?');
  bubble('msg msg-ai');
  bubble('msg msg-ai msg-continuation');
  const u2 = bubble('msg msg-user', 'Bravo: why are you searching imdb and old navy? Wtf');
  bubble('msg msg-ai');
  bubble('msg msg-ai msg-continuation');
  return { u1, u2 };
}
__SOURCE__
"""


def _run(dom_dir: Path, script: str, extra=()) -> dict:
    body = _PRE.replace("__SOURCE__", _cut(extra)) + script
    out = subprocess.run(["node", "--input-type=module"], input=body, capture_output=True,
                         text=True, cwd=dom_dir, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# ── which message, not which bubble ─────────────────────────────────────────

def test_the_cut_names_the_message_and_not_its_place_on_screen(dom_dir):
    """The number that went wrong, and the number that replaces it.

    The newest user bubble is the 4th `.msg` in the box and the 3rd stored row;
    `index_from_end` is 0 for it either way, and 1 for the one before it,
    because the continuation bubbles are not user bubbles at all.
    """
    out = _run(dom_dir, """
        const { u1, u2 } = buildChat();
        const all = box.querySelectorAll('.msg');
        console.log(JSON.stringify({
          msgEls: all.length,
          domIndexOfNewest: all.indexOf(u2),
          newest: _userMessageCut(u2),
          older: _userMessageCut(u1),
        }));
    """)
    assert out["msgEls"] == 6, "six bubbles for four rows — the drift the browser draws"
    assert out["domIndexOfNewest"] == 3, "and the old keep_count would have been 3, not 2"
    assert out["newest"]["index_from_end"] == 0
    assert out["newest"]["text"].startswith("Bravo: why are you searching")
    assert out["older"]["index_from_end"] == 1
    assert out["older"]["text"].startswith("Alpha: what do we fight")


def test_a_queued_bubble_is_not_a_message_this_chat_holds(dom_dir):
    """`.msg-user-queued` is drawn from the browser's own queue and has no row,
    so counting it would move every boundary after it."""
    out = _run(dom_dir, """
        const { u2 } = buildChat();
        bubble('msg msg-user msg-user-queued', 'Charlie: still waiting to send');
        console.log(JSON.stringify({
          userEls: box.querySelectorAll('.msg-user').length,
          stored: _storedUserBubbles(box).length,
          newest: _userMessageCut(u2),
        }));
    """)
    assert out["userEls"] == 3, "three user-class bubbles are on screen"
    assert out["stored"] == 2, "two of them stand for a stored row"
    assert out["newest"]["index_from_end"] == 0, "the queued one is not newer than the newest"


def test_retry_sends_the_last_message_and_never_the_queued_one(dom_dir):
    out = _run(dom_dir, """
        buildChat();
        bubble('msg msg-user msg-user-queued', 'Charlie: still waiting to send');
        _retryLastTurn();
        console.log(JSON.stringify({ resent }));
    """)
    assert len(out["resent"]) == 1
    assert out["resent"][0]["text"].startswith("Bravo: why are you searching")
    assert out["resent"][0]["opts"] == {"replaceFromHere": True}


def test_a_bubble_this_chat_does_not_hold_has_no_cut(dom_dir):
    """Nothing to resolve means nothing is posted — never a cut at 0, which
    would take the whole chat."""
    out = _run(dom_dir, """
        buildChat();
        const stray = document.createElement('div');
        stray.className = 'msg msg-user';
        const res = await _truncateFromUserMessage('s-1', _userMessageCut(stray));
        console.log(JSON.stringify({ cut: _userMessageCut(stray), ok: res.ok,
                                     sentence: res.sentence, posted }));
    """)
    assert out["cut"] is None
    assert out["ok"] is False
    assert out["posted"] == [], "nothing was asked of the server"
    assert "Reload" in out["sentence"]


# ── what goes on the wire ───────────────────────────────────────────────────

def test_the_server_is_asked_for_the_message_and_not_for_a_count(dom_dir):
    out = _run(dom_dir, """
        const { u2 } = buildChat();
        const res = await _truncateFromUserMessage('s-1', _userMessageCut(u2));
        console.log(JSON.stringify({ ok: res.ok, posted }));
    """)
    assert out["ok"] is True
    assert len(out["posted"]) == 1
    sent = out["posted"][0]
    assert sent["url"] == "/api/session/s-1/truncate"
    assert "keep_count" not in sent["body"], "the number that was wrong is not sent"
    assert sent["body"]["from_user_message"]["index_from_end"] == 0
    assert sent["body"]["from_user_message"]["text"].startswith("Bravo: why are you searching")


def test_an_attachment_count_is_not_part_of_what_the_person_typed(dom_dir):
    """The bubble's body carries a `[2 attachment(s)]` suffix the row does not;
    the three flows already strip it before resending and the cut does too, so
    the server's text check compares like with like."""
    out = _run(dom_dir, """
        const el = bubble('msg msg-user');
        el.querySelector('.body').textContent = 'Look at these [2 attachment(s)]';
        console.log(JSON.stringify({ text: _userMessageCut(el).text }));
    """)
    assert out["text"] == "Look at these"


# ── a refusal removes nothing, so nothing is sent ───────────────────────────

def test_a_refused_cut_says_what_the_server_said(dom_dir):
    out = _run(dom_dir, """
        const { u2 } = buildChat();
        reply = { ok: false, status: 409, sentence: 'This chat has changed since that message was drawn — reload and try again.' };
        const res = await _truncateFromUserMessage('s-1', _userMessageCut(u2));
        console.log(JSON.stringify({ ok: res.ok, sentence: res.sentence }));
    """)
    assert out["ok"] is False
    assert out["sentence"].startswith("This chat has changed since that message was drawn")


def test_a_server_that_cannot_be_reached_is_a_refusal_too(dom_dir):
    """Not an exception out of the flow: the caller has to know nothing was
    removed, or it sends the message again on top of the old one."""
    out = _run(dom_dir, """
        const { u2 } = buildChat();
        reply = { throws: true };
        const res = await _truncateFromUserMessage('s-1', _userMessageCut(u2));
        console.log(JSON.stringify({ ok: res.ok, sentence: res.sentence }));
    """)
    assert out["ok"] is False
    assert "Could not reach Pantheon" in out["sentence"]


def test_no_session_is_not_a_cut_at_the_start_of_one(dom_dir):
    out = _run(dom_dir, """
        const { u2 } = buildChat();
        const res = await _truncateFromUserMessage('', _userMessageCut(u2));
        console.log(JSON.stringify({ ok: res.ok, posted }));
    """)
    assert out["ok"] is False
    assert out["posted"] == []


# ── `B1986`: Fork names the reply, not its place on screen ─────────────────

_FORK = ((CHAT, "async function forkFrom("), (REACTIONS, "function replyIdFor("))
_FORKED = "reply = { ok: true, status: 200, json: async () => ({ id: 'fork-1', name: 'Fork: Long chat' }) };"


def test_fork_on_the_newest_reply_of_a_long_chat_names_that_reply(dom_dir):
    """The page holds the newest 24 rows of a 42-message chat. The old count
    was 24 (the bubble's place + 1), and the fork had none of the newest 18."""
    out = _run(dom_dir, _FORKED + """
        let last = null;
        for (let row = 18; row < 42; row += 1) {
          last = bubble(row % 2 ? 'msg msg-ai' : 'msg msg-user', 'row ' + row);
          last.dataset.dbId = 'row-' + row;
        }
        await forkFrom(last);
        console.log(JSON.stringify({ drawn: box.querySelectorAll('.msg').length, posted, opened, toasts }));
    """, extra=_FORK)
    assert out["drawn"] == 24
    assert [p["url"] for p in out["posted"]] == ["/api/session/s-1/fork"]
    assert out["posted"][0]["body"] == {"through_msg_id": "row-41"}, "the reply's id, and no count of bubbles"
    assert out["opened"] == ["fork-1"]
    assert out["toasts"] == ["Forked → Long chat"], "B1530's toast: the name without its prefix"


def test_fork_on_the_step_an_agent_reply_ends_with_names_that_reply(dom_dir):
    """Live, an agent reply is its holder (which `message_saved` gave the id)
    and the step its footer sits under: two `.msg` for one row. The old count
    was 3, and the fork took the next question with it."""
    out = _run(dom_dir, _FORKED + """
        bubble('msg msg-user', 'first question').dataset.dbId = 'row-0';
        bubble('msg msg-ai').dataset.dbId = 'row-1';
        const step = bubble('msg msg-ai msg-continuation', 'first answer');
        bubble('msg msg-user', 'second question').dataset.dbId = 'row-2';
        bubble('msg msg-ai').dataset.dbId = 'row-3';
        bubble('msg msg-ai msg-continuation', 'second answer');
        await forkFrom(step);
        console.log(JSON.stringify({ posted }));
    """, extra=_FORK)
    assert [p["body"] for p in out["posted"]] == [{"through_msg_id": "row-1"}]


def test_a_reply_with_no_saved_copy_on_the_page_is_not_forked_by_a_guess(dom_dir):
    out = _run(dom_dir, _FORKED + """
        bubble('msg msg-user', 'a question');
        const answer = bubble('msg msg-ai', 'an answer drawn before its row was saved');
        await forkFrom(answer);
        console.log(JSON.stringify({ posted, shown, opened }));
    """, extra=_FORK)
    assert out["posted"] == [], "no count of bubbles is posted in its place"
    assert out["shown"] == ["That message has no saved copy on this page yet. Reload the chat, then fork it."]
    assert out["opened"] == []


def test_a_reply_the_chat_no_longer_holds_is_said_in_the_servers_words(dom_dir):
    out = _run(dom_dir, """
        reply = { ok: false, status: 404, sentence: 'That message is no longer in this chat — reload and try again.' };
        bubble('msg msg-user', 'a question').dataset.dbId = 'row-0';
        const answer = bubble('msg msg-ai', 'an answer');
        answer.dataset.dbId = 'row-1';
        await forkFrom(answer);
        console.log(JSON.stringify({ shown, opened }));
    """, extra=_FORK)
    assert out["shown"] == ["That message is no longer in this chat — reload and try again."]
    assert out["opened"] == []
