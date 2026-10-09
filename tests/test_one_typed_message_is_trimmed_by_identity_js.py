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

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SIGNATURES = (
    "function _storedUserBubbles(",
    "function _userBubbleText(",
    "function _userMessageCut(",
    "async function _truncateFromUserMessage(",
    "function _retryLastTurn(",
)


def _cut() -> str:
    src = CHAT.read_text(encoding="utf-8")
    out = []
    for sig in _SIGNATURES:
        assert src.count(sig) == 1, f"{sig!r} appears {src.count(sig)} times in chat.js"
        out.append(js_definition(src, src.index(sig)))
    return "\n\n".join(out)


@pytest.fixture(scope="module")
def dom_dir(tmp_path_factory):
    """The suite's own DOM shim on disk (`Law 14` — not a second one)."""
    import test_tool_effect_surfaces_js as harness

    directory = tmp_path_factory.mktemp("trimidentity")
    (directory / "dom.js").write_text(harness._DOM)
    (directory / "shim.js").write_text("import { installDom } from './dom.js';\n"
                                       "export const document = installDom();\n")
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
const uiModule = { showError: (s) => shown.push(s), showToast: () => {} };
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


def _run(dom_dir: Path, script: str) -> dict:
    body = _PRE.replace("__SOURCE__", _cut()) + script
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
