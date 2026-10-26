# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1268` (fx4-models) — a send refused in a chat is said as a note, not as
the model's reply.

In a chat whose model's server had stopped, the refusal — *"Demo model
(scripted) isn't answering. Pick another from the model menu."* — was typed
into the reply holder (`typewriterInto(holder…)`), under the model's own name
and the time: the model that was not answering appeared to say so itself. The
composer's no-model note was made not-a-reply in `P23-04`; the refused arm now
draws the server's sentence the same kind of way (`_sayRefused`): the holder
goes, and a note with no sender says the sentence.

Driven (`Law 20`): the real `_sayRefused`, cut out of `chat.js`, over the DOM
shim; and, scoped to `handleChatSubmit`'s refused arm (option 2), that the arm
calls it and types into no holder.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.helpers.js_source import js_function
from tests.helpers.source_text import blank_text
from test_chat_actions_say_what_they_do import _cut  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
REFUSAL = "Demo model (scripted) isn't answering. Pick another from the model menu."

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
globalThis.window = globalThis;
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = tmp_path_factory.mktemp("refusedsend")
    (d / "noop.js").write_text("export default {};\n")
    return _make_sandbox(d, JS / "agentStops.js", _SHIM, {})


def test_the_refusal_is_a_note_with_no_sender(sandbox):
    out = _run(sandbox, "import { document } from './shim.js';\n", """
        const uiModule = { scrollHistory: () => {} };
        %s
        const box = document.createElement('div'); box.id = 'chat-history'; document.body.appendChild(box);
        const user = document.createElement('div'); user.className = 'msg msg-user'; box.appendChild(user);
        // The reply holder the send drew: the model's name and time, and a body.
        const holder = document.createElement('div'); holder.className = 'msg msg-ai';
        const role = document.createElement('div'); role.className = 'role'; role.textContent = 'scripted-demo 3:29 AM';
        const body = document.createElement('div'); body.className = 'body';
        holder.appendChild(role); holder.appendChild(body); box.appendChild(holder);
        const note = _sayRefused(document, %s, holder);
        console.log(JSON.stringify({
          replies: box.querySelectorAll('.msg-ai').length,
          senders: box.querySelectorAll('.role').length,
          last: box.children[box.children.length - 1] === note,
          cls: note.className, role: note.getAttribute('role'), text: note.textContent,
          msgs: box.querySelectorAll('.msg').length,
        }));
    """ % (_cut(JS / "chat.js", "export function _sayRefused("), json.dumps(REFUSAL)))
    assert out == {"replies": 0, "senders": 0, "last": True, "cls": "send-refused-note",
                   "role": "status", "text": REFUSAL, "msgs": 1}


def test_the_refused_arm_says_it_through_the_note():
    """Scoped to `handleChatSubmit` (`js_function`, comments blanked): the
    refusal goes through the note, and nothing there types into the holder."""
    src = (JS / "chat.js").read_text(encoding="utf-8")
    body = blank_text(js_function(src, "export async function handleChatSubmit("), "js")
    refused = body.index("if (!res.ok) {")
    assert body.index("_sayRefused(document, errText, holder)", refused) < body.index(
        "const streamRunId", refused), "the note is not drawn in the refused arm"
    assert "typewriterInto(holder" not in body
