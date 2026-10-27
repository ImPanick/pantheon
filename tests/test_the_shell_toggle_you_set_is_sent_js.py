# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P7-01`, the browser half — the toggle you set is the toggle that is sent.

`static/js/chat.js` built a regex of 58 alternations — *change, update,
review, test, run, build, source, system, device, app* among them — and on a
match did two things before the request left the page: it sent the turn as
`mode=agent`, and it ran `fd.set('allow_bash', 'true')` over the line that had
just appended the shell toggle's real value. So a person who switched the shell
**off** and typed *"review the build logs in /work"* sent `allow_bash=true`,
and the route, told the person had picked Agent themselves, had no promotion to
report. The backend half (`escalation_grants_shell`,
`tests/test_the_shell_toggle_means_what_it_says.py`) could not help: the
server never saw the *off*.

`chat.js` cannot be imported into node (dozens of static imports and a top
level that touches the page), so this takes the route
`tests/test_a_slash_skill_rides_beside_the_message_js.py` takes: the **real
source** of the send's form-building block is sliced out of the file and run
in node over stubs for what it reads. Then the value it produced is handed to
the server's own rule, so the chain is driven end to end: what the page sends
is what `escalation_grants_shell` and `escalation_withholds` decide on.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from routes.chat_helpers import escalation_grants_shell, escalation_withholds

ROOT = Path(__file__).resolve().parents[1]
CHAT = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _form_block() -> str:
    """From the toggles being read to the last field appended before the
    superseded-send check — the whole of what decides mode and shell."""
    start = CHAT.index("const toggleState = Storage.loadToggleState();")
    end = CHAT.index("// Superseded during preflight", start)
    return CHAT[start:end]


def _timeout_kind() -> str:
    """The two lines that choose the response timeout's length."""
    start = CHAT.index("const _tState = Storage.loadToggleState();")
    end = CHAT.index("\n", CHAT.index("const _isAgent =", start))
    return CHAT[start:end]


def _send(tmp_path: Path, *, message: str, mode: str = "chat", bash: bool = False,
          web: bool = False, incognito: bool = False) -> dict:
    case = tmp_path / "case.mjs"
    case.write_text(
        "const toggles = " + json.dumps({"mode": mode, "plan_mode": False}) + ";\n"
        "const Storage = { loadToggleState: () => ({ ...toggles }), KEYS: { WORKSPACE: 'ws' },"
        " get: () => '' };\n"
        "const boxes = { 'bash-toggle': " + json.dumps(bash) + ", 'web-toggle': "
        + json.dumps(web) + ", 'research-toggle': false, 'rag-toggle': true };\n"
        "const el = (id) => (id in boxes ? { checked: boxes[id] } : null);\n"
        "const planWindow = { isExecuting: () => false };\n"
        "const _getStoredPlan = () => '';\n"
        "const documentModule = null; const activeDocIdForSend = null;\n"
        "const approvalForSend = null;\n"
        "const isIncognitoForSend = " + json.dumps(incognito) + ";\n"
        "const summonModule = { getSummoned: () => null };\n"
        "const presetsModule = { getSelectedPreset: () => null };\n"
        "const msg = " + json.dumps(message) + ";\n"
        "const fd = new FormData();\n"
        + _form_block() + "\n"
        + _timeout_kind() + "\n"
        "const sent = {}; for (const [k, v] of fd.entries()) sent[k] = v;\n"
        "console.log(JSON.stringify({ sent, longTimeout: _isAgent }));\n"
    )
    proc = subprocess.run(["node", str(case)], cwd=tmp_path, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# The row's own sentence, and three of the 58 words in ordinary chat.
WORKSPACE_WORDS = [
    "review the build logs in /work",
    "can you update me on the project?",
    "what system prompt would you write for a source of truth app",
    "test my understanding of photosynthesis",
]


@pytest.mark.parametrize("message", WORKSPACE_WORDS)
def test_a_shell_switched_off_is_sent_off(tmp_path, message):
    o = _send(tmp_path, message=message, bash=False)
    assert o["sent"]["allow_bash"] == "false", (
        "the page overwrote the person's shell toggle before the request left")


@pytest.mark.parametrize("message", WORKSPACE_WORDS)
def test_a_chat_turn_is_sent_as_the_chat_the_person_picked(tmp_path, message):
    # The route decides whether to promote, and says so in `auto_escalated`;
    # a page-side promotion arrives as `mode=agent` and reads to the route as
    # the person's own choice, so nothing is reported.
    o = _send(tmp_path, message=message, mode="chat")
    assert o["sent"]["mode"] == "chat"
    assert o["longTimeout"] is False


def test_a_shell_switched_on_is_sent_on(tmp_path):
    o = _send(tmp_path, message="review the build logs in /work", bash=True)
    assert o["sent"]["allow_bash"] == "true"


def test_agent_mode_the_person_picked_is_still_agent(tmp_path):
    o = _send(tmp_path, message="hello", mode="agent")
    assert o["sent"]["mode"] == "agent" and o["longTimeout"] is True


def test_the_server_withholds_the_shell_the_page_said_no_to(tmp_path):
    """The chain, driven: the value the real page block produced is the value
    the route's rule reads, and a workspace promotion on it withholds the
    shells and says so on the `auto_escalated` event's `withheld` list."""
    o = _send(tmp_path, message="review the build logs in /work", bash=False)
    granted = escalation_grants_shell(o["sent"]["allow_bash"])
    assert granted is False
    withheld = escalation_withholds(promoted=True, workspace_intent=True,
                                    allow_browser=False, browser_tools=set(),
                                    shell_granted=granted)
    assert "bash" in withheld and "host_shell" in withheld


def test_the_keyword_bag_is_gone_from_the_send():
    # Law 20: scoped to the block that builds the form, not the file — the
    # comment explaining the change quotes some of the words.
    block = _form_block()
    assert "fd.set('allow_bash'" not in block
    assert "workspaceAgentIntent" not in block
