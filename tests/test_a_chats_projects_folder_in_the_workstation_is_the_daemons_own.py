# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1684` — a chat's `$PANTHEON_PROJECTS` in the workstation is the value
the daemon gives its commands, and the daemon says what that is.

Measured before the fix: in a workstation chat, `cd "$PANTHEON_PROJECTS"/w
&& echo hi > brand-new.md` read as *it cannot be known whether brand-new.md
in your workstation was there before this run began* — destructive — because
the value is the daemon's own (`agentd._exec_prepare`: the account's folder
under the first shared root that holds one) and Pantheon did not know it.
Its own guess (`projects_folder`: the first mounted root) is not always it:
with several roots, the first may not hold the account's folder — a symlink
there is not its folder — while a later one does.

Now the daemon gives the value by one rule (`System.projects_env`) and
reports it on the account route (`projects_env`), and the run reads a chat's
path by it (`workstation_tools.shell_station`); a hire's stays the folder
Pantheon hands its command (`run_env`, `B1646`). A daemon that does not
report it — older than this, or a VM host whose machine is not running —
leaves the path unknown, as before.

Driven (`Law 20`): the real daemon, its real `exec` and account route, the
real gate and dispatcher running real `bash` there under a never, and the VM
host's forwarding.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.agent_tools.workstation_tools import projects_folder
from src.run_files import RunFiles
from src.tool_capabilities import ToolRunSecurityContext, call_destroys
from src.workstation_client import WorkstationClient, account_for
from test_a_hires_files_and_its_cd_meet_in_the_workstation import _mine, data, station  # noqa: F401
from test_the_agents_hands_are_in_the_workstation import people, settings, ws  # noqa: F401
from tests.helpers import vm_fleet
from workstation import agentd
from workstation import protocol as P

THERE = "which was there before this run began"
NEW = 'cd "$PANTHEON_PROJECTS"/w && echo hi > brand-new.md'
OVER = 'cd "$PANTHEON_PROJECTS"/w && echo hi > notes.md'
ANN = account_for("ann")


def run(coro):
    return asyncio.run(coro)


def _chat(owner: str = "ann") -> RunFiles:
    return RunFiles(None, owner, session_id=f"s-{uuid.uuid4().hex[:8]}")


def test_the_daemon_reports_the_folder_it_gives_commands_where_pantheons_guess_differs(ws, tmp_path):
    """Two shared roots: the first is mounted but holds only a symlink by
    the account's name, the second holds its folder. Commands are given the
    second; the account route says so; Pantheon's own reading of `health`
    names the first."""
    first, second, elsewhere = (tmp_path / n for n in ("roots-a", "roots-b", "elsewhere"))
    for d in (first, second, elsewhere):
        d.mkdir()
    name = P.project_folder_of(ANN)
    os.symlink(elsewhere, first / name)
    (second / name).mkdir()
    ws.system.shared_roots = [first, second]
    client = WorkstationClient(ws.url, ws.token)
    given = run(client.exec(ANN, 'printf %s "$PANTHEON_PROJECTS"'))["stdout"]
    assert given == str(Path(os.path.realpath(second)) / name)
    assert run(client.account(ANN))["projects_env"] == given
    guessed, _mounted = projects_folder(run(client.health()), ANN)
    assert guessed != given, "the case the row is about: Pantheon could not have guessed it"


def test_a_chats_new_file_there_is_a_plain_write_and_the_persons_is_not(station):
    """The row's `Verify:`: read by the run's record, after the loop asks the
    workstation (`RunFiles.look`)."""
    there = _mine(station) / "w"
    there.mkdir(parents=True)
    (there / "notes.md").write_text("keep", encoding="utf-8")
    chat = _chat()
    assert chat.in_workstation("bash")
    run(chat.look("bash", NEW))
    run(chat.look("bash", OVER))
    assert call_destroys("bash", NEW, chat) is None
    assert call_destroys("bash", OVER, chat) == \
        f"a > redirect replaces notes.md in your workstation, {THERE}"


def test_through_the_real_gate_and_shell_under_a_never(station):
    """The real `bash` in the workstation makes the new file in the folder
    the reading looked in, and the person's file is refused and kept."""
    there = _mine(station) / "w"
    there.mkdir(parents=True)
    (there / "notes.md").write_text("keep", encoding="utf-8")
    files = _chat()

    async def go():
        out = []
        for command in (NEW, OVER):
            await files.look("bash", command)
            ctx = ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=files,
                                         approval_gate_bypassed=True)
            out.append((await te.execute_tool_block(
                ToolBlock("bash", command), owner="ann", session_id=files.session_id,
                security_context=ctx))[1])
        return out

    made, refused = run(go())
    assert made.get("ran_in") == "workstation" and made.get("exit_code") == 0, made
    assert (there / "brand-new.md").read_text(encoding="utf-8") == "hi\n"
    assert refused.get("blocked") is True, refused
    assert f"(a > redirect replaces notes.md in your workstation, {THERE})" in refused["error"]
    assert (there / "notes.md").read_text(encoding="utf-8") == "keep"


def test_a_daemon_that_does_not_report_it_leaves_the_path_unknown(station, monkeypatch):
    """Older than the report: the cautious reading, as before this row."""
    real = agentd.Workstation.account

    def older(self, account):
        answer = real(self, account)
        answer.pop("projects_env", None)
        return answer

    monkeypatch.setattr(agentd.Workstation, "account", older)
    (_mine(station) / "w").mkdir(parents=True)
    chat = _chat()
    run(chat.look("bash", NEW))
    assert call_destroys("bash", NEW, chat) == \
        "it cannot be known whether brand-new.md in your workstation was there before this run began"


def test_the_vm_host_says_it_only_while_the_machine_runs(tmp_path):
    """The machine gives its commands the value, so the host forwards the
    machine's own answer while it runs, and says nothing while it is off."""
    with vm_fleet.vm_host(tmp_path / "state") as (fleet, url):
        client = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(client.health())
        given = run(client.exec(ANN, 'printf %s "$PANTHEON_PROJECTS"'))["stdout"]
        assert given.endswith("/" + P.project_folder_of(ANN))
        assert run(client.account(ANN))["projects_env"] == given
        fleet.machine_for(ANN).stop()
        seen = run(client.account(ANN))
        assert seen["machine"] == "stopped" and "projects_env" not in seen
