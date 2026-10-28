# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1630` — every agent that runs ssh from the workstation declares it.

Measured before the fix: `B1623` gave an agent file `needs.programs`, and
Vulnerability Scanner declared `ssh`; thirteen other agents whose one command
is `ssh … "$h" '…'` — Access Reviewer, Config Drift, Container Keeper, Disk
Janitor, Firewall Auditor, Incident Scribe, Log Watcher, Login Watcher, Media
Library Tidier, NAS Health, Network Mapper, Server Health and Update Planner —
declared nothing, and `workstation/provision.sh` installs no openssh-client
(`--no-install-recommends`). So each was hired, ran on its schedule, and found
"ssh: command not found" every time, where *Hire* would have said what to
install before anything was written.

The set is not carried by hand (`Law 6`): which agents run ssh is read from
their runbooks' own commands, and must equal the set that declares it. The
hire's refusal is driven through the real `/api/agents` routes.
"""

from __future__ import annotations

import re

from tests.test_a_workflow_is_kept_as_one_document import (  # noqa: F401  (fixtures)
    admins, sched, wf_db,
)
from tests.test_a_team_is_hired_in_one_go import client  # noqa: F401  (fixture)
from tests.test_a_hire_compiles_to_tasks import call
from tests.test_an_agent_says_which_programs_it_needs import _hires, _without
from src.agents.catalogue import catalogue, get_agent

THE_ROWS_THIRTEEN = {
    "access-reviewer", "config-drift", "container-keeper", "disk-janitor", "firewall-auditor",
    "incident-scribe", "log-watcher", "login-watcher", "media-library-tidier", "nas-health",
    "network-mapper", "server-health", "update-planner",
}
INSTALL = "sudo apt-get install -y openssh-client"


def _runs_ssh(runbook: str) -> bool:
    """A command in the runbook — a backticked span — that runs `ssh` with an
    option, as every one of these does (`ssh -o BatchMode=yes …`)."""
    return any(re.search(r"(?:^|[\s;&|(])ssh\s+-[A-Za-z]", span) for span in re.findall(r"`([^`]+)`", runbook))


def _declares_ssh(m) -> bool:
    return any(p["name"] == "ssh" for p in (m.needs.get("programs") or ()))


def test_the_thirteen_declare_ssh_with_its_install_line():
    for agent in sorted(THE_ROWS_THIRTEEN | {"vulnerability-scanner"}):
        m = get_agent(None, agent)
        ssh = [p for p in m.needs.get("programs") or () if p["name"] == "ssh"]
        assert ssh == [{"name": "ssh", "install": INSTALL}], agent


def test_every_agent_that_runs_ssh_declares_it_and_none_other_does():
    agents, broken = catalogue(None)
    assert broken == []
    runs = {m.id for m in agents if _runs_ssh(m.runbook)}
    declares = {m.id for m in agents if _declares_ssh(m)}
    assert runs == THE_ROWS_THIRTEEN | {"vulnerability-scanner"}
    assert declares == runs


def test_a_hire_without_ssh_is_refused_with_what_to_install(client, wf_db, monkeypatch):
    _without(monkeypatch, "ssh")
    res = call(client, "POST", "/api/agents/config-drift/hire",
               json={"inputs": {"hosts": ["web1"], "folder": "infra"}})
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == (
        "Config Drift runs ssh, which the machine Pantheon runs your tools on does not have, so it "
        f"cannot do its job yet. Install it once — {INSTALL} — then hire it.")
    team = call(client, "POST", "/api/agents/teams/home-lab/hire", json={"inputs": {"hosts": ["nas"]}})
    assert team.status_code == 409 and team.json()["detail"].startswith("Server Health runs ssh")
    assert _hires(wf_db) == 0, "a refused hire leaves nothing behind"


def test_with_ssh_there_the_hire_is_made(client, wf_db, monkeypatch):
    _without(monkeypatch)
    res = call(client, "POST", "/api/agents/config-drift/hire",
               json={"inputs": {"hosts": ["web1"], "folder": "infra"}})
    assert res.status_code == 200, res.text
    assert _hires(wf_db) == 1
