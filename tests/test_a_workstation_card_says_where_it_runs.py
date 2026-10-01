# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B967` — a workstation call's effect says where it runs.

With the workstation on, a `bash` call runs in the person's workstation
(`P20-03`), and its `tool_start` — the card, the step row and the approval
card — said "Runs code on this machine": the opposite of the *workstation*
label the same card gets when the result lands. The file tools said
"Reads/Writes workspace files" about a home this machine never sees, and
`computer` (`P20-04`), which only ever acts on the workstation, said "on this
machine" too.

Driven through the real loop (`stream_agent_loop`, with `P7-06`'s own stubs
for the model and the dispatcher) and the real approval store, with the real
`workstation_tools.routes` deciding — the workstation configured the way an
admin's settings would, and a person who may and one who may not use it:

  * where the dispatcher will run the call, the words say so — on
    `tool_start`, `tool_output`, the persisted event, the approval card and its
    *what tripped* list, and the approved replay;
  * only the words change: the effect values, the rank and the band are the
    ones the same call has here, so the gate decides exactly what it did;
  * **the seal does not include it** — two approvals for one action, one
    phrased for the workstation and one not, carry the same digest and each
    matches the other's binding;
  * with the workstation off, routing switched off, or a person without the
    grant, the phrase is the one `tests/test_tool_effect_wire.py` pins
    (`Law 1`).

Nothing here reads a source file (`Law 20`).
"""
from __future__ import annotations

import pytest

import core.auth
import src.agent_loop as agent_loop
import src.workstation_access as wa
import src.workstation_client as wc
from src.tool_approvals import ToolApprovalStore
from src.tool_capabilities import (
    RUNS_IN_WORKSTATION,
    capabilities_for_action,
    describe_effects,
)
from test_tool_effect_wire import (
    EFFECT_KEYS,
    _approved_run,
    _events,
    _first,
    _gated_run,
    _patch,
    _persisted,
)
from workstation import protocol as P

MAY, MAY_NOT = "alice", "bob"
HERE = "Runs code on this machine"
THERE = "Runs code in your workstation"


class _Auth:
    """Two people and the real `resolve_privilege` behind `may_use`."""

    is_configured = True
    PRIVILEGES = {MAY: {"can_use_workstation": True}, MAY_NOT: {}}

    def __init__(self, *args, **kwargs):
        pass

    def get_privileges(self, owner):
        return dict(self.PRIVILEGES.get(owner, {}))


@pytest.fixture
def workstation(monkeypatch):
    """On, addressed and routing — the shipped default once an admin turns it
    on. A test switches a part off by editing the dict. Nothing is called on
    the address: the dispatcher is `P7-06`'s stub, and where a call runs is
    decided before any of it."""
    settings = {"workstation_enabled": True, "workstation_url": "http://workstation:7040",
                "workstation_token": "pws_test", "workstation_route_tools": True}
    monkeypatch.setattr(wc, "_setting", lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(wa, "_setting", lambda key: settings.get(key, wa._DEFAULTS.get(key)))
    monkeypatch.delenv(P.URL_ENV, raising=False)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(core.auth, "AuthManager", _Auth)
    return settings


def _turn(monkeypatch, reply, tool, owner=MAY):
    _patch(monkeypatch, [reply])
    return _events(agent_loop.stream_agent_loop(
        "http://local.test/v1", "small-local-model",
        [{"role": "user", "content": "do the thing"}],
        max_rounds=1, owner=owner, session_id="session-1", relevant_tools={tool}))


# ── the words, and only the words ────────────────────────────────────────────

@pytest.mark.parametrize("tool,content,label", [
    ("bash", "rm -rf /tmp/scratch", THERE),
    ("python", "print(1)", THERE),
    ("read_file", "/home/x/notes.txt", "Reads from your workstation"),
    ("write_file", "notes.txt\nhello", "Writes files in your workstation"),
    ("computer", '{"action": "click", "x": 1, "y": 1}', THERE),
    ("computer", '{"action": "screenshot"}', "Reads from your workstation"),
])
def test_the_words_change_and_nothing_else_does(tool, content, label):
    caps = capabilities_for_action(tool, content)
    here = describe_effects(caps)
    there = describe_effects(caps, runs_in=RUNS_IN_WORKSTATION)
    assert label in there["effect_labels"]
    assert not {HERE, "Reads workspace files", "Writes workspace files"} & set(
        there["effect_labels"])
    for key in ("effects", "effect", "effect_severity", "effect_band"):
        assert there[key] == here[key], key
    assert len(there["effect_labels"]) == len(here["effect_labels"])
    # An effect with no workstation phrase keeps its own words.
    for value, words_here, words_there in zip(here["effects"], here["effect_labels"],
                                              there["effect_labels"]):
        if value not in ("execute_code", "read_workspace", "write_workspace"):
            assert words_there == words_here


@pytest.mark.parametrize("where", [None, "", "host", "Workstation", True, 1, ["workstation"]])
def test_only_the_exact_place_changes_the_words(where):
    caps = capabilities_for_action("bash", "ls")
    assert describe_effects(caps, runs_in=where) == describe_effects(caps)


# ── the live card, through the loop ──────────────────────────────────────────

@pytest.mark.parametrize("tool,reply,label", [
    ("bash", "```bash\nrm -rf /tmp/scratch\n```", THERE),
    ("python", "```python\nprint(1)\n```", THERE),
    ("read_file", "```read_file\nnotes.txt\n```", "Reads from your workstation"),
])
def test_with_the_workstation_on_tool_start_says_where_it_will_run(monkeypatch, workstation,
                                                                   tool, reply, label):
    events = _turn(monkeypatch, reply, tool)
    start, output = _first(events, "tool_start"), _first(events, "tool_output")
    assert start["tool"] == tool
    assert start["effect_label"] == label
    assert label in start["effect_labels"]
    for key in EFFECT_KEYS:
        assert output[key] == start[key], key
    [saved] = _persisted(events)
    assert saved["effect_label"] == label


def test_the_computer_says_workstation_whatever_the_routing_switch(monkeypatch, workstation):
    """It never runs here, so routing the shell elsewhere is not its question."""
    workstation["workstation_route_tools"] = False
    events = _turn(monkeypatch, '```computer\n{"action": "click", "x": 3, "y": 4}\n```',
                   "computer")
    start = _first(events, "tool_start")
    assert THERE in start["effect_labels"] and HERE not in start["effect_labels"]


@pytest.mark.parametrize("case", ["off", "routing_off", "not_permitted"])
def test_where_it_runs_here_the_phrase_is_the_one_it_always_was(monkeypatch, workstation, case):
    owner = MAY
    if case == "off":
        workstation["workstation_enabled"] = False
    elif case == "routing_off":
        workstation["workstation_route_tools"] = False
    else:
        owner = MAY_NOT
    events = _turn(monkeypatch, "```bash\nrm -rf /tmp/scratch\n```", "bash", owner=owner)
    assert _first(events, "tool_start")["effect_label"] == HERE


# ── the approval card, and the seal ──────────────────────────────────────────

def test_the_approval_card_says_where_and_what_tripped_says_it_too(monkeypatch, workstation):
    """`_gated_run` drives the gate for `alice` with untrusted content seen, so
    the card is the one `PendingToolApproval.public_payload()` really mints."""
    events = _gated_run(monkeypatch, "```bash\nrm -rf /tmp/scratch\n```", tool="bash")
    [saved] = _persisted(events)
    card = saved["ask_user"]
    assert card["effect_label"] == THERE
    assert HERE not in card["effect_labels"]
    assert THERE in card["gate"]["tripped_effect_labels"]
    assert card["action"]["effects"] == sorted(card["effects"])
    assert "execute_code" in card["action"]["effects"]


def test_the_seal_does_not_include_where(workstation):
    """One action, minted twice in two stores — one phrased for the workstation
    and one not. Same digest, and each grant matches the same binding."""
    caps = capabilities_for_action("bash", "rm -rf /tmp/scratch")

    def mint(runs_in):
        store = ToolApprovalStore()
        pending = store.create(owner=MAY, session_id="s-1", origin_run_id="run-1",
                               tool_name="bash", content="rm -rf /tmp/scratch", workspace=None,
                               external_untrusted_context_seen=True, capabilities=caps,
                               runs_in=runs_in)
        return store, pending

    store_there, there = mint(RUNS_IN_WORKSTATION)
    store_here, here = mint(None)
    assert there.digest == here.digest, "where it runs entered the seal"
    assert there.public_payload()["effect_label"] == THERE
    assert here.public_payload()["effect_label"] == HERE
    assert here.public_payload()["action"] == {
        **there.public_payload()["action"], "digest": here.digest[:16]}
    for store, pending in ((store_there, there), (store_here, here)):
        grant = store.consume(pending.approval_id, decision="approve", owner=MAY,
                              session_id="s-1")
        assert grant is not None
        assert grant.matches(owner=MAY, session_id="s-1", tool_name="bash",
                             content="rm -rf /tmp/scratch", workspace=None)


def test_the_approved_replay_says_where_it_ran(monkeypatch, workstation):
    events = _approved_run(monkeypatch, tool_name="bash", content="printf hi")
    start, output = _first(events, "tool_start"), _first(events, "tool_output")
    assert start["approved"] is True
    assert start["effect_label"] == output["effect_label"] == THERE
    [saved] = _persisted(events)
    assert saved["effect_label"] == THERE
