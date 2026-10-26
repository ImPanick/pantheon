# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1374`, the composer half: `/skill-name` sends the person's words, and the
skill by name beside them.

`slashCommands._invokeSkillByName` used to put `/invoke`'s whole answer — the
SKILL.md inside an "Apply the skill below to my request" frame — into the
composer and submit it as the chat message. Now it puts only the person's words
in the box, hands the skill's **name** over on the chat form, and `chat.js`
sends that as the `skill` field of the very message whose text it was pinned to
(`build_chat_context` frames the skill server-side —
`tests/test_a_slash_skill_is_framed_not_spoken_for_the_person.py`).

`slashCommands.js` and `chat.js` cannot be imported into the node sandbox (each
sits behind dozens of static imports and a top-level that touches the page), so
this takes the middle route `tests/test_rail_settings_opens_settings_js.py`
documents: the **real source** of `_invokeSkillByName`, `_submitComposedMessage`
and `chat.js`'s hand-over block is sliced out of the files (by brace balance,
`tests/helpers/js_source.py`) and executed under the shared DOM shim.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition, js_function
from tests.test_tool_effect_surfaces_js import _make_sandbox, _run

ROOT = Path(__file__).resolve().parents[1]
SLASH = (ROOT / "static" / "js" / "slashCommands.js").read_text(encoding="utf-8")
CHAT = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _chat_handover_block() -> str:
    """The `{ … }` block in `chat.js` that reads the hand-over, cut by the
    shared reader (`js_definition`, strings, comments and regexes skipped —
    `B876`) from the brace that opens it."""
    start = CHAT.index("        const _chatForm = el('chat-form');")
    start = CHAT.rindex("{", 0, start)
    return js_definition(CHAT, start)


SHIM = """
import { installDom } from './dom.js';
export const document = installDom();
"""


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    src = tmp_path_factory.mktemp("slashskill-src") / "empty.js"
    src.write_text("export {};\n")
    return _make_sandbox(tmp_path_factory.mktemp("slashskill"), src, SHIM, {})


def _preamble(reply_js: str) -> str:
    invoke = js_function(SLASH, "async function _invokeSkillByName")
    submit = js_function(SLASH, "function _submitComposedMessage")
    handover = _chat_handover_block()
    return (
        "import { document } from './shim.js';\n"
        "const API_BASE = '';\n"
        "const replies = [];\n"
        "function slashReply(t) { replies.push(String(t)); }\n"
        "const form = document.createElement('form'); form.id = 'chat-form';\n"
        "const input = document.createElement('textarea'); input.id = 'message';\n"
        "document.body.appendChild(form); document.body.appendChild(input);\n"
        "const posted = [];\n"
        "globalThis.fetch = async (url, init = {}) => { posted.push({ url: String(url), body: JSON.parse(init.body || '{}') });\n"
        "  return { ok: true, json: async () => (" + reply_js + ") }; };\n"
        "const el = (id) => document.getElementById(id);\n"
        "const sent = [];\n"
        "form.addEventListener('submit', () => {\n"
        "  const approvalForSend = null;\n"
        "  const msg = el('message').value;\n"
        "  const fd = new FormData();\n"
        "  fd.append('message', msg);\n"
        "  " + handover + "\n"
        "  sent.push({ message: fd.get('message'), skill: fd.get('skill') });\n"
        "});\n"
        "function _submitComposedMessage(text) " + submit + "\n"
        "async function _invokeSkillByName(name, requestText, ctx) " + invoke + "\n"
        "const out = (o) => console.log(JSON.stringify(o));\n"
    )


def test_the_message_is_the_persons_words_and_the_skill_rides_beside_it(box):
    reply = ("{ ok: true, type: 'skill', name: 'rotate-logs', skill: 'rotate-logs', "
             "request: 'tidy the build box', message: 'tidy the build box' }")
    o = _run(box, _preamble(reply), """
        await _invokeSkillByName('rotate-logs', 'tidy the build box', {});
        await new Promise((r) => setTimeout(r, 420));
        // A second, ordinary message afterwards carries no skill.
        el('message').value = 'thanks';
        form.dispatchEvent(new Event('submit'));
        out({ posted, sent, replies, left: form.dataset.invokedSkill || null });
    """)
    assert o["posted"] == [{"url": "/api/skills/rotate-logs/invoke",
                            "body": {"request": "tidy the build box"}}]
    assert o["sent"][0] == {"message": "tidy the build box", "skill": "rotate-logs"}
    assert o["sent"][1] == {"message": "thanks", "skill": None}
    assert o["replies"] == [] and o["left"] is None


def test_a_different_message_in_the_box_does_not_take_the_skill(box):
    """Pinned to the exact words: something else typed before the submit lands
    is sent without it, and the hand-over is spent."""
    reply = "{ ok: true, skill: 'rotate-logs', request: 'tidy the build box' }"
    o = _run(box, _preamble(reply), """
        await _invokeSkillByName('rotate-logs', 'tidy the build box', {});
        el('message').value = 'something else entirely';
        form.dispatchEvent(new Event('submit'));
        out({ first: sent[0], left: form.dataset.invokedSkill || null });
    """)
    assert o["first"] == {"message": "something else entirely", "skill": None}
    assert o["left"] is None
