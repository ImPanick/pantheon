# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1632` — whether a hire's kit is *sealed* is read from the calls its
`never`s leave, not from each tool's whole registration.

Measured before the fix: since `B1619` a tool stays in a hire's kit with only
its *never* calls refused, but `runtime.is_sealed` counted each tool's
registration whole. `git` kept under `network_egress: never` can still look
and commit, and every call of it that reaches out — pull, clone, push, any
action the table does not name — is refused before anything else is asked;
yet the kit counted as unsealed, so after outside content a commit on its own
branch asked for a yes that `D-2026-10-24-01` lifts for a kit with no way out.
It only ever made Pantheon ask more.

Both directions, driven (`Law 20`):

  * where the `never` truly removed the way out, the run is sealed and its
    writes to its own workspace after outside content run, while every call
    that would reach out is refused by the never — through the real
    `TaskScheduler._execute_llm_task` and the real `ToolRunSecurityContext`;
  * where it did not — `external_side_effect: never` leaves pull and clone, a
    shell's `destructive: never` leaves the shell — nothing changes, and over
    every registered tool, every single `never` and each action its tables
    name, a kit called sealed has no call the gate would run that carries an
    effect out (`capabilities_for_action`, the gate's own classification).
"""

from __future__ import annotations

import json

import pytest

from tests.test_a_hired_agent_runs_as_its_file_says import (  # noqa: F401  (fixtures)
    _hire, _run, _task, _tainted, wf_db, world,
)
from src.agents.runtime import SEALING_EFFECTS, is_sealed
from src.tool_capabilities import (
    TOOL_CAPABILITIES, TOOL_CLASSIFICATION_UNAVAILABLE, ToolEffect, _ACTION_CAPABILITIES,
    _ACTION_DESTRUCTIVE, _OBSERVE_ONLY_ACTIONS, _PRIVATE_ACTION_READS, _PRIVATE_ACTION_WRITES,
    capabilities_for_action, capabilities_for_tool,
)

KEEPER = """---
id: repo-keeper
name: Repo Keeper
tagline: Looks at the person's repository and commits a tidy-up on a branch.
section: development
version: 1.0.0
triggers:
  - {on: hand}
tools: [git, read_file]
effects: {read_workspace: allow, write_workspace: allow}
---
Call `git` for the status, `read_file` what changed, and answer with what you saw, line by line.
"""


@pytest.fixture()
def keeper(world, tmp_path):
    """The person's own agent with `git` in its kit — no shipped agent has it."""
    import os
    from src.agents.catalogue import own_root
    folder = tmp_path / os.path.relpath(own_root("alice"), str(tmp_path)) / "repo-keeper"
    folder.mkdir(parents=True)
    (folder / "AGENT.md").write_text(KEEPER, encoding="utf-8")
    return world


def _sealed_run(keeper, grants):
    factory, sched, seen = keeper
    db = factory()
    h, _ = _hire(db, "repo-keeper", grants=grants)
    _run(sched, db, _task(db, h.id))
    return seen["slot"]["agent"]


def test_a_never_that_removes_the_way_out_seals_the_run(keeper):
    agent = _sealed_run(keeper, {"network_egress": "never"})
    assert agent["never_effects"] == ["network_egress"]
    assert agent["sealed"] is True
    never = frozenset({"network_egress"})
    commit = ("git", json.dumps({"action": "commit", "message": "Tidy the README"}))
    # Before: unsealed, so after outside content the commit on its own branch
    # waited for a yes (`write_workspace` is behind the floor).
    assert _tainted(hire_never_effects=never).decision_for(*commit).allowed is False
    run = _tainted(hire_never_effects=never, hire_sealed=True)
    assert run.decision_for(*commit).allowed is True
    assert run.decision_for("git", json.dumps({"action": "status"})).allowed is True
    assert run.decision_for("read_file", json.dumps({"path": "README.md"})).allowed is True
    # Every call that would reach out is refused by the never, not lifted.
    for action in ("push", "pull", "clone", "rebase"):
        d = run.decision_for("git", json.dumps({"action": action}))
        assert d.allowed is False and d.classification == TOOL_CLASSIFICATION_UNAVAILABLE, action


@pytest.mark.parametrize("grants", [{}, {"external_side_effect": "never"}, {"write_workspace": "never"}])
def test_a_never_that_leaves_a_way_out_does_not_seal(keeper, grants):
    """`external_side_effect: never` refuses a push and leaves pull and clone,
    which reach the network: still a way out, so still unsealed."""
    assert _sealed_run(keeper, grants)["sealed"] is False


def test_a_shell_is_a_way_out_whatever_its_never():
    assert is_sealed(["read_file"]) is True
    assert is_sealed(["bash", "read_file"], {"destructive"}) is False
    assert is_sealed(["git"], {"network_egress"}) is True
    # Every call of `web_fetch` reaches out, so the never leaves none of it —
    # the kit drops it (`hires.kit`) and it carries nothing out here either.
    assert is_sealed(["git", "web_fetch"], {"network_egress"}) is True
    assert is_sealed(["git", "web_search"], {"network_egress"}) is False, "a search is not refused by that never"
    assert is_sealed(["mcp__someone__thing"], {"network_egress", "execute_code"}) is False, "unknown never seals"


def _sample_calls(tool):
    """Each call shape the gate's classification distinguishes for `tool`."""
    actions = set()
    for table in (_ACTION_CAPABILITIES, _OBSERVE_ONLY_ACTIONS, _PRIVATE_ACTION_READS,
                  _PRIVATE_ACTION_WRITES, _ACTION_DESTRUCTIVE):
        actions |= set(table.get(tool, ()))
    calls = [json.dumps({"action": a}) for a in sorted(actions)]
    calls += [json.dumps({"action": "no-such-action"}), "{}", ""]
    if tool in ("bash", "shell_with_login"):
        calls += [json.dumps({"command": "ls"}), json.dumps({"command": "rm -rf x"})]
    if tool == "python":
        calls += ["print(1)", "import os\nos.remove('x')"]
    return calls


@pytest.mark.parametrize("effect", sorted(e.value for e in ToolEffect))
def test_sealed_never_hides_a_call_the_gate_would_let_reach_out(effect):
    """Over every registered tool: a `never` only takes calls away, so a tool
    sealed with none stays sealed with one; and a tool sealed under a `never`
    has no call — as the gate classifies it — that carries an effect out and
    is not refused by that never."""
    never = {effect}
    for tool in TOOL_CAPABILITIES:
        if is_sealed([tool]):
            assert is_sealed([tool], never), tool
        if not is_sealed([tool], never):
            continue
        for content in _sample_calls(tool):
            effects = {e.value for e in capabilities_for_action(tool, content).effects}
            assert effects & never or not (effects & SEALING_EFFECTS), (tool, content, effects)
        assert capabilities_for_tool(tool).known
