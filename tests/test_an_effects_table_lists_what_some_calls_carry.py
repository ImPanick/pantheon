# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1629` — an agent's effects table lists every effect a call of its tools
can carry, not only what each tool's registration says.

Measured before the fix: `hires.manifest_effects` read each tool's
registration whole (`capabilities_for_tool`). `bash` is registered
`execute_code` alone, so since `B1622` made a shell's `rm` destructive *per
call*, an agent with a shell and no `destructive` row had no row for it at all
— no line on the hire form, nothing a person could tighten (`check_grants`
refused "Restore Drill's tools never have the effect destructive"), and no
cautious default: Restore Drill's `rm -rf "$t"`, API Mocker's and Prototype
Builder's `kill`, Screenshot Reporter's `rm -rf` ran unasked in a clean run.
The same for a `manage_*` delete, for the `read_private` of a `manage_*`
list, and for the `read_workspace` of a `computer` screenshot. Measured on
`d1302586`'s files: 51 shipped agents with a shell or Python left
`destructive` to nobody, six with `computer` left `read_workspace`, and four
with a `manage_*` tool left `read_private`.

Now the table reads `tool_capabilities.widest_reach` — the union of
`call_reaches`, every classification `capabilities_for_action` can give a call
— so such an effect is listed, decided by the file or asking (the cautious
default of `D-2026-10-22-01` §3). The substance bar reads the same table, and
every shipped agent decides each one in its file: API Mocker and Prototype
Builder end their check servers with `timeout` now and never delete; Restore
Drill and Screenshot Reporter, whose one command removes its own scratch,
ask — no shipped agent deletes unasked — and a hirer may set theirs to delete
without asking.

Driven through the real manifest parser, the real hire store's rules
(`src/agents/hires`) and the real `ToolRunSecurityContext`.
"""

from __future__ import annotations

import pytest

from src.agents import hires as H
from src.agents.catalogue import catalogue, get_agent
from src.agents.manifest import parse_manifest
from src.tool_capabilities import (
    ToolEffect, ToolRunSecurityContext, call_reaches, capabilities_for_action, capabilities_for_tool,
    widest_reach,
)

AGENT = """---
id: shell-user
name: Shell User
tagline: Looks at a folder.
section: devops
version: 1.0.0
triggers:
  - {on: hand}
tools: %s
effects: %s
---
List the folder in one bash command, and report what it printed, line by line.
"""


def _manifest(tools: str, effects: str = "{execute_code: allow}"):
    return parse_manifest(AGENT % (tools, effects))


def _effects(*es):
    return frozenset(ToolEffect(e) for e in es)


def test_some_calls_carry_more_than_the_registration():
    assert capabilities_for_tool("bash").effects == _effects("execute_code")
    assert widest_reach("bash") == _effects("execute_code", "destructive")
    assert widest_reach("python") == _effects("execute_code", "destructive")
    assert widest_reach("manage_notes") == _effects("read_private", "write_private", "destructive")
    assert widest_reach("read_file") == _effects("read_workspace")
    # A tool whose registration is already everything its actions do is as it was.
    assert widest_reach("git") == capabilities_for_tool("git").effects
    assert widest_reach("no_such_tool") == capabilities_for_tool("no_such_tool").effects


@pytest.mark.parametrize("tool,content", [
    ("bash", '{"command": "rm -rf build"}'), ("bash", '{"command": "ls"}'),
    ("python", '{"code": "import os\\nos.remove(\\"x\\")"}'),
    ("manage_notes", '{"action": "delete", "id": "n1"}'), ("manage_notes", '{"action": "list"}'),
    ("manage_notes", '{"action": "frobnicate"}'), ("manage_memory", "search\nAna"),
    ("git", '{"action": "push"}'), ("git", '{"action": "status"}'), ("bulk_email", '{"action": "delete"}'),
    ("computer", '{"action": "screenshot"}'), ("network", '{"action": "reach"}'),
])
def test_every_call_is_one_of_the_reaches_listed(tool, content):
    """`call_reaches` is what `capabilities_for_action` can say: a call's
    classification is always one of them, so the widest is never short."""
    assert capabilities_for_action(tool, content).effects in call_reaches(tool)


def test_a_shell_agent_silent_on_deletion_now_lists_it_and_asks():
    m = _manifest("[bash]")
    table = H.manifest_effects(m)
    assert table == {"destructive": "ask", "execute_code": "allow"}
    run = ToolRunSecurityContext(hire_ask_effects=frozenset(e for e, r in table.items() if r == "ask"))
    assert run.decision_for("bash", "ls -la").allowed is True
    asked = run.decision_for("bash", 'rm -rf "$t"')
    assert asked.allowed is False and asked.reason == (
        "This agent's hire asks before destructive: 'bash' waits for your yes (rm deletes files).")


def test_a_manage_tool_lists_its_reads_quietly_and_its_deletes_asking():
    table = H.manifest_effects(_manifest("[manage_notes]", "{write_private: allow}"))
    assert table == {"destructive": "ask", "read_private": "allow", "write_private": "allow"}


def test_a_person_can_tighten_what_only_some_calls_do():
    """The row is on the hire form, so a person can say never to it; before,
    the grant was refused as an effect the tools never have."""
    m = _manifest("[bash]")
    assert H.check_grants(m, {"destructive": "never"}) == {"destructive": "never"}
    with pytest.raises(H.HireRefused) as refused:
        H.check_grants(m, {"network_egress": "never"})
    assert "never have the effect “network_egress”" in refused.value.sentence


def test_every_shipped_agent_decides_every_effect_its_calls_can_carry():
    agents, broken = catalogue(None)
    assert broken == []
    undecided = {m.id: sorted(set(H.manifest_effects(m)) - set(m.effects)) for m in agents}
    assert {a: u for a, u in undecided.items() if u} == {}
    # The four the row names, each decided in its file: the two whose one
    # command removes its own scratch ask (no shipped agent deletes unasked,
    # `tests/test_the_roster_is_shipped.py`); the two that no longer delete
    # never do.
    assert {a: get_agent(None, a).effects["destructive"] for a in
            ("restore-drill", "api-mocker", "prototype-builder", "screenshot-reporter")} == {
        "restore-drill": "ask", "api-mocker": "never", "prototype-builder": "never",
        "screenshot-reporter": "ask"}


def test_a_never_agents_own_command_reads_clean():
    """API Mocker and Prototype Builder ended their check servers with `kill`
    and `rm .pid`; now `timeout` ends them, so their own step runs under
    their `destructive: never` and a deletion is still refused."""
    filled = {"api-mocker": {"<out>": "petstore-mock", "<first path>": "/pets", "<second path>": "/pets/1"},
              "prototype-builder": {"<folder>": "plant-swap"}}
    for agent, values in filled.items():
        m = get_agent(None, agent)
        never = frozenset(e for e, r in H.effective_effects(m, {}).items() if r == "never")
        assert "destructive" in never and "bash" in H.kit(m, never)
        step = next(line for line in m.runbook.split("\n") if "`bash` command" in line)
        command = step.split("`")[3]
        for placeholder, value in values.items():
            command = command.replace(placeholder, value)
        assert "timeout 20" in command and "<" not in command, command
        run = ToolRunSecurityContext(hire_never_effects=never)
        assert run.decision_for("bash", command).allowed is True, command
        assert run.decision_for("bash", "kill $(cat .pid); rm .pid").allowed is False


@pytest.mark.parametrize("agent,command", [
    ("restore-drill", 't=$(mktemp -d); echo restore; rm -rf "$t"'),
    ("screenshot-reporter", 'd=$(date +%F) && mkdir -p .shots-$d && img2pdf .shots-$d/*.png -o $d.pdf; rm -rf .shots-$d'),
])
def test_a_scratch_deletion_asks_until_the_hirer_allows_it_and_no_other_runs_unasked(agent, command):
    """The command's own scratch deletion asks, in the hire's words and naming
    the deletion; the hirer may set "delete things" to run without asking on
    their own hire (`D-2026-10-22-01` §3, `check_grants`), and then it runs.
    Once that command's answer is in the run, any other deletion still asks —
    on Manual approve by the floor, and in Auto by its one exception
    (`B1341`)."""
    m = get_agent(None, agent)
    shipped = H.effective_effects(m, {})
    asked = ToolRunSecurityContext(hire_ask_effects=frozenset(e for e, r in shipped.items() if r == "ask"))
    d = asked.decision_for("bash", command)
    assert d.allowed is False and d.reason.endswith("waits for your yes (rm deletes files).")
    grants = H.check_grants(m, {"destructive": "allow"})
    table = H.effective_effects(m, grants)
    ask = frozenset(e for e, r in table.items() if r == "ask")
    assert "destructive" not in ask
    for auto in (False, True):
        run = ToolRunSecurityContext(hire_ask_effects=ask, auto_approved=auto)
        assert run.decision_for("bash", command).allowed is True, auto
        # The command's answer is in the run: a shell's output is the
        # workspace's words, not Pantheon's, so the gate is armed.
        run.observe_tool_result("bash", {"output": "took 94s", "exit_code": 0}, command)
        assert run.external_untrusted_context_seen
        assert run.decision_for("bash", "rm -rf /backups/pg").allowed is False, auto
