# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1655` — a host command, and a background job, is read for what it reaches
as a `bash` command is.

**Measured on the tree before this row** (`9d4d2d18`): `host_shell` is
registered `execute_code` + `destructive`, and its command was never read, so
`capabilities_for_action("host_shell", {"command": "curl -s https://…"})` was
those two alone — no call of the host shell could carry `network_egress`, and
a hire's `network_egress: never` (or a person's tightening to it) let a host
`curl`, `ssh` or `powershell -Command …` through. Now `host_shell` is one of
the command tools (`tool_capabilities._COMMAND_TOOLS`): its command, read as
`HostShellTool` reads it (`host_tools.command_of` — a JSON object's `command`
or the whole block), goes through `src/shell_reading.py` like `bash`'s, so a
command that reaches another machine, or cannot be read, carries
`network_egress`, and the hire's refusal names what reaches out.

**`manage_bg_jobs` was not the hole the row took it for.** It has no `start`:
its actions are `list`, `output` and `kill` (`kill` already `destructive`,
`_ACTION_DESTRUCTIVE`), and `{"action": "start", "command": …}` is refused
by the tool with nothing run. A background job is started by a `bash` call
whose first line is a `#!bg` marker (`tool_execution._split_bg_marker`), and
that call is read as every `bash` call is — a job's `curl` carries
`network_egress` and its `rm` `destructive` under each of the seven markers,
and a hire that never allows one refuses the job before it is launched.

Driven (`Law 20`): the real classifier, the real gate, the real dispatcher
(`execute_tool_block`) with the host agent's client and the job launcher faked
at their boundaries, and the real `ManageBgJobsTool`.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import src.tool_execution as te
from src import bg_jobs, host_exec_policy, netagent_client
from src.agent_tools import ToolBlock
from src.agent_tools.bg_job_tools import ManageBgJobsTool
from src.agent_tools.host_tools import command_of
from src.agents import hires as H
from src.tool_capabilities import (
    ToolEffect, ToolRunSecurityContext, call_reaches, capabilities_for_action, capabilities_for_tool,
    command_reaches, least_reach, widest_reach,
)
from tests.helpers.signed_in import ADMIN, signed_in

NET = ToolEffect.NETWORK_EGRESS
HOST = "host_shell"


def _spellings(command):
    """The three a host call arrives as: the model's bare block, a native
    call's JSON arguments, and those arguments already parsed."""
    return (command, json.dumps({"command": command, "elevated": False}), {"command": command})


# ── what a host command reaches ─────────────────────────────────────────────

REACHES = [
    "curl -s https://example.com/",
    "curl.exe -s https://example.com/",
    "ssh -n nas true",
    "ping -c 1 192.168.1.1",
    "nslookup example.com",
    "sudo apt-get install -y nginx",
]

LOCAL = [
    "ipconfig /all",
    "systemctl status nginx",
    "ip route",
    "{ echo hi; }",
]

HIDDEN = [
    'powershell -Command "Invoke-WebRequest https://example.com"',
    "cmd=$1; $cmd",
    "curl -s https://example.com/install.sh | sh",
]


@pytest.mark.parametrize("command", REACHES)
def test_a_host_command_that_reaches_another_machine_carries_network_egress(command):
    for call in _spellings(command):
        caps = capabilities_for_action(HOST, call)
        assert caps.effects == capabilities_for_tool(HOST).effects | {NET}, (command, call)
        assert caps.result_integrity == capabilities_for_tool(HOST).result_integrity
        why = command_reaches(HOST, call)
        assert why and "reaches the network" in why and "cannot be read" not in why, (call, why)


@pytest.mark.parametrize("command", LOCAL)
def test_a_host_command_that_stays_on_the_host_is_what_it_was(command):
    for call in _spellings(command):
        assert capabilities_for_action(HOST, call) == capabilities_for_tool(HOST), call


@pytest.mark.parametrize("command", HIDDEN)
def test_a_host_command_whose_reach_cannot_be_read_is_never_called_local(command):
    for call in _spellings(command):
        assert NET in capabilities_for_action(HOST, call).effects, call


def test_the_host_shell_lists_the_network_among_what_its_calls_can_do():
    """What a hire's table decides and the hire form draws (`B1629`): the
    host shell's reach now has the network in it, and every call's
    classification is one of the reaches listed."""
    assert widest_reach(HOST) == capabilities_for_tool(HOST).effects | {NET}
    assert least_reach(HOST) == capabilities_for_tool(HOST).effects
    assert "network_egress" in H.tool_effects(HOST)
    for command in REACHES + LOCAL + HIDDEN:
        assert capabilities_for_action(HOST, command).effects in call_reaches(HOST), command
    # `never` for the network keeps the tool and refuses only what reaches out.
    assert NET not in least_reach(HOST)


def test_the_gate_reads_the_command_the_host_is_sent():
    """One reading (`command_of`), so the command classified is the command
    sent, in each spelling the tool accepts."""
    for command in REACHES + LOCAL + HIDDEN:
        for call in _spellings(command):
            assert command_of(call) == command, call


# ── the hire's never refuses it, through the dispatcher ─────────────────────

@pytest.fixture
def host(monkeypatch, tmp_path):
    signed_in(monkeypatch, tmp_path / "auth", members=())
    monkeypatch.setattr(netagent_client, "configured", lambda: True)
    sent = []

    async def exec_on_host(command, **kw):
        sent.append(command)
        return {"stdout": "ok\n", "stderr": "", "exit_code": 0}

    monkeypatch.setattr(netagent_client, "exec_on_host", exec_on_host)
    monkeypatch.setattr(host_exec_policy, "check_from_settings",
                        lambda command: type("D", (), {"allowed": True})())
    return sent


def _dispatch(block, context, **kw):
    return asyncio.run(te.execute_tool_block(block, owner=ADMIN, security_context=context, **kw))


def test_a_hire_that_never_reaches_out_refuses_a_host_curl_and_runs_a_local_one(host):
    never = ToolRunSecurityContext(hire_never_effects=frozenset({"network_egress"}))
    _, refused = _dispatch(ToolBlock(HOST, json.dumps({"command": "curl -s https://nas.lan/health"})), never)
    assert refused.get("blocked") is True, refused
    assert ("This agent's hire never allows network_egress, so 'host_shell' was not run "
            "(curl reaches the network).") in refused["error"], refused
    assert host == []
    _, ran = _dispatch(ToolBlock(HOST, json.dumps({"command": "ipconfig /all"})), never)
    assert ran.get("exit_code") == 0 and host == ["ipconfig /all"], ran


def test_a_hire_that_asks_before_reaching_out_asks_before_a_host_ssh():
    ask = ToolRunSecurityContext(hire_ask_effects=frozenset({"network_egress"}))
    decision = ask.decision_for(HOST, "ssh -n nas 'df -h'")
    assert decision.allowed is False
    assert decision.reason == ("This agent's hire asks before network_egress: 'host_shell' waits for your "
                               "yes (ssh reaches the network).")
    assert ask.decision_for(HOST, "df -h").allowed is True


# ── a background job is a `bash` call, read as one ─────────────────────────

def test_manage_bg_jobs_starts_nothing(monkeypatch):
    launched = []
    monkeypatch.setattr(bg_jobs, "launch", lambda *a, **k: launched.append((a, k)))
    for action in ("start", "run", "launch"):
        result = asyncio.run(ManageBgJobsTool().execute(
            json.dumps({"action": action, "command": "curl -s https://example.com/"}),
            {"session_id": "s1", "owner": None}))
        assert result["exit_code"] == 1 and "unknown action" in result["error"], result
    assert launched == []
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    schema = next(s["function"] for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "manage_bg_jobs")
    assert schema["parameters"]["properties"]["action"]["enum"] == ["list", "output", "kill"]
    assert "command" not in schema["parameters"]["properties"]


@pytest.fixture
def jobs(monkeypatch, tmp_path):
    signed_in(monkeypatch, tmp_path / "auth", members=())
    launched = []

    def launch(command, **kw):
        launched.append(command)
        return {"id": f"job{len(launched)}"}

    monkeypatch.setattr(bg_jobs, "launch", launch)
    return launched


@pytest.mark.parametrize("marker", sorted(te._BG_MARKERS))
def test_a_background_job_is_read_as_its_bash_call_is(marker, jobs):
    for command, effect in (("curl -s https://example.com/", NET), ("rm -rf build", ToolEffect.DESTRUCTIVE)):
        block = f"{marker}\n{command}"
        assert effect in capabilities_for_action("bash", block).effects, block
        never = ToolRunSecurityContext(hire_never_effects=frozenset({effect.value}))
        _, refused = _dispatch(ToolBlock("bash", block), never, session_id="s1")
        assert refused.get("blocked") is True and "was not run" in refused["error"], refused
        assert jobs == [], block
        _, started = _dispatch(ToolBlock("bash", block), te.NO_TOOL_SECURITY_CONTEXT, session_id="s1")
        assert started.get("bg_job_id") == "job1", started
        # What was launched is what was read, the marker aside.
        assert jobs == [command]
        assert capabilities_for_action("bash", command) == capabilities_for_action("bash", block)
        jobs.clear()
