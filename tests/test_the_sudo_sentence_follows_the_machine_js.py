# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B981` — the sentence beside `sudo` is true of the machine the workstation is.

*"With sudo on, an agent can install software — and can read other people's
workstation homes"* is the container's consequence: people are Unix accounts in
one machine. On the VM backend each person has a machine of their own and root
in one found no trace of another's home (measured in `P20-07`); on another
machine, root is root there. The panel now says the one that is true, chosen by
what the daemon says it is (`health.backend`) — or, while none has answered, by
the setting — the same rule `B956`'s *Recreate* sentence follows
(`machineKind`, one function for both).

Driven under node (`Law 20`): the real `static/js/workstation.js` in `P20-02`'s
sandbox, its nodes built from the panel's own markup (so the container's
sentence is the one `index.html` ships), fed status answers in the shapes
`src/workstation_access.status_for` gives.
"""
from __future__ import annotations

import json
import shutil

import pytest

from test_the_workstation_panel_js import (  # noqa: E402
    ADMIN_UP, DAEMON, MODULE, SETTINGS, _PREAMBLE, _SHIM, _STUBS, _panel_nodes, _serving)
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

CONTAINER = ("With sudo on, an agent can install software — and can read other people’s "
             "workstation homes.")
VM = ("With sudo on, an agent can install software in its own person’s machine. Other "
      "people’s machines are separate: it cannot reach their homes.")
REMOTE = ("With sudo on, an agent can install software on that machine — and can read other "
          "people’s workstation homes and anything else on it.")


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    shim = _SHIM.replace("__NODES__", json.dumps(_panel_nodes()))
    return _make_sandbox(tmp_path_factory.mktemp("sudo-sentence"), MODULE, shim, _STUBS)


def _sudo_why(sandbox, *statuses) -> list:
    """The sentence after each status answer, in order, as an admin sees it."""
    lets = f"const STATUSES = {json.dumps(list(statuses))};\nlet i = 0;\n"
    script = _serving("STATUSES[Math.min(i, STATUSES.length - 1)]") + """
        const seen = [byId('ws-sudo-why').textContent];
        await mod.open();
        seen.push(byId('ws-sudo-why').textContent);
        for (i = 1; i < STATUSES.length; i++) {
          await mod.load();
          seen.push(byId('ws-sudo-why').textContent);
        }
        console.log(JSON.stringify(seen));
    """
    return _run(sandbox, _PREAMBLE + lets, script)


def _status(daemon_backend, setting="container"):
    daemon = {**DAEMON, "backend": daemon_backend} if daemon_backend else None
    return {**ADMIN_UP, "daemon": daemon, "settings": {**SETTINGS, "backend": setting}}


def test_the_page_ships_the_containers_sentence():
    node = next(n for n in _panel_nodes() if n["id"] == "ws-sudo-why")
    assert node["text"] == CONTAINER


@pytest.mark.parametrize("backend, words", [
    ("container", CONTAINER), ("vm", VM), ("remote", REMOTE)])
def test_the_daemon_says_what_it_is_and_the_sentence_follows(sandbox, backend, words):
    # The setting says container every time: the daemon's own word wins.
    shipped, after = _sudo_why(sandbox, _status(backend, setting="container"))
    assert shipped == CONTAINER and after == words


@pytest.mark.parametrize("setting, words", [("vm", VM), ("remote", REMOTE),
                                            ("container", CONTAINER)])
def test_while_no_daemon_has_answered_the_setting_decides(sandbox, setting, words):
    assert _sudo_why(sandbox, _status(None, setting=setting))[-1] == words


def test_the_sentence_moves_with_the_machine_and_comes_back(sandbox):
    """A VM backend, then the container again (the admin switched it back):
    the container's sentence returns — the page's own, kept, not retyped."""
    seen = _sudo_why(sandbox, _status("vm"), _status("container"), _status("remote"),
                     _status("container"))
    assert seen == [CONTAINER, VM, CONTAINER, REMOTE, CONTAINER]


def test_a_kind_with_no_words_gets_the_cautious_sentence(sandbox):
    """A backend this panel has no words for is told the widest consequence,
    never left with another machine's narrower one."""
    seen = _sudo_why(sandbox, _status("vm"), _status("hypervisor-of-the-future"))
    assert seen[-1] == CONTAINER
