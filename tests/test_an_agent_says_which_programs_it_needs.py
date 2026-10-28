# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1623` — an agent says which workstation programs it needs, and a hire is
checked against them before it is made.

Measured before the fix: `manifest._check_needs` accepted `connectors`,
`min_context` and `native_tools` and refused anything else, and
`workstation/provision.sh` installs none of exiftool, ffmpeg, a postgres or
mysql server or an ssh client (`--no-install-recommends`). So Photo Organiser,
Video Clipper, Restore Drill and Vulnerability Scanner were hired as readily
as any other agent and found out at run time — on a schedule, every time —
answering "NO EXIFTOOL" with the line to install it.

Now an agent file names them (`needs.programs`, each with its install line and,
for Restore Drill, the database it is needed for), and *Hire*, *Try it once*
and *Hire all* ask the place the person's tools run — their workstation, or the
machine Pantheon runs tools on — first, and refuse with what to install.

Driven through the real `/api/agents` routes on a real SQLite file
(`test_a_team_is_hired_in_one_go.py`'s client) and the real shipped files.
"""

from __future__ import annotations

import shutil

import pytest

from tests.test_a_workflow_is_kept_as_one_document import (  # noqa: F401  (fixtures)
    admins, sched, wf_db,
)
from tests.test_a_team_is_hired_in_one_go import client  # noqa: F401  (fixture)
from tests.test_a_hire_compiles_to_tasks import call
from core.database import AgentHire
from src.agents import needs as N
from src.agents.catalogue import get_agent
from src.agents.manifest import ManifestRefused, parse_manifest


def _without(monkeypatch, *missing):
    real = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None if name in missing else (
        real(name, *a, **k) or f"/usr/bin/{name}"))


def _hires(wf_db):
    db = wf_db()
    try:
        return db.query(AgentHire).count()
    finally:
        db.close()


def test_the_four_agents_name_what_they_run():
    names = {a: [p["name"] for p in get_agent(None, a).needs.get("programs") or ()]
             for a in ("photo-organiser", "video-clipper", "restore-drill", "vulnerability-scanner")}
    assert names["photo-organiser"] == ["exiftool"]
    assert names["video-clipper"] == ["ffmpeg", "ffprobe"]
    assert names["vulnerability-scanner"] == ["ssh"]
    assert {"pg_ctlcluster", "psql", "mysqld", "python3"} <= set(names["restore-drill"])
    drill = get_agent(None, "restore-drill")
    assert [p["name"] for p in N.programs_for(drill, {"engine": "sqlite"})] == ["python3"]
    assert [p["name"] for p in N.programs_for(drill, {"engine": "postgres"})] == ["pg_ctlcluster", "psql"]


def test_a_hire_is_refused_with_what_to_install(client, wf_db, monkeypatch):
    _without(monkeypatch, "exiftool")
    res = call(client, "POST", "/api/agents/photo-organiser/hire", json={"inputs": {"folder": "photos"}})
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == (
        "Photo Organiser runs exiftool, which the machine Pantheon runs your tools on does not have, "
        "so it cannot do its job yet. Install it once — sudo apt-get install -y "
        "libimage-exiftool-perl — then hire it.")
    assert _hires(wf_db) == 0, "a refused hire leaves nothing behind"
    tried = call(client, "POST", "/api/agents/photo-organiser/try", json={"inputs": {"folder": "photos"}})
    assert tried.status_code == 409 and "exiftool" in tried.json()["detail"]


def test_a_hire_whose_programs_are_there_is_made(client, wf_db, monkeypatch):
    _without(monkeypatch)
    res = call(client, "POST", "/api/agents/photo-organiser/hire", json={"inputs": {"folder": "photos"}})
    assert res.status_code == 200, res.text
    assert _hires(wf_db) == 1


def test_only_the_programs_its_inputs_need_are_asked_for(client, monkeypatch):
    """Restore Drill on a sqlite dump needs no database server."""
    _without(monkeypatch, "pg_ctlcluster", "psql")
    sqlite = call(client, "POST", "/api/agents/restore-drill/hire",
                  json={"inputs": {"dump": "/backups/app.db", "engine": "sqlite"}})
    assert sqlite.status_code == 200, sqlite.text
    pg = call(client, "POST", "/api/agents/restore-drill/hire",
              json={"inputs": {"dump": "/backups/pg", "engine": "postgres"}})
    assert pg.status_code == 409
    assert pg.json()["detail"].startswith("Restore Drill runs pg_ctlcluster and psql, which")


def test_hire_all_asks_for_each_member_before_any_is_written(client, wf_db, monkeypatch):
    _without(monkeypatch, "ssh")
    res = call(client, "POST", "/api/agents/teams/security-watch/hire", json={"inputs": {"hosts": ["web1"]}})
    assert res.status_code == 409, res.text
    assert res.json()["detail"].startswith("Vulnerability Scanner runs ssh")
    assert _hires(wf_db) == 0


class _Workstation:
    def __init__(self, absent=(), fail=False):
        self.absent, self.fail, self.asked = absent, fail, []

    async def exec(self, account, command, **kw):
        self.asked.append(command)
        if self.fail:
            raise RuntimeError("the workstation did not answer")
        return {"exit_code": 0, "stdout": "".join(f"{n}\n" for n in self.absent), "stderr": ""}


def _in_the_workstation(monkeypatch, station):
    import src.workstation_access as wa

    async def synced(client):
        return {}
    monkeypatch.setattr(wa, "routes_tools", lambda owner, **kw: True)
    monkeypatch.setattr(wa, "workstation_for", lambda owner, **kw: (station, "alice"))
    monkeypatch.setattr(wa, "sync_config", synced)


def test_the_persons_own_workstation_is_asked_when_their_tools_run_there(client, wf_db, monkeypatch):
    station = _Workstation(absent=("ffmpeg",))
    _in_the_workstation(monkeypatch, station)
    res = call(client, "POST", "/api/agents/video-clipper/hire",
               json={"inputs": {"video": "talks/keynote.mp4", "moments": "00:01-00:20 intro"}})
    assert res.status_code == 409, res.text
    assert "runs ffmpeg, which your workstation does not have" in res.json()["detail"]
    assert "command -v" in station.asked[0] and "ffprobe" in station.asked[0]


def test_a_workstation_that_cannot_be_asked_refuses_nothing(client, wf_db, monkeypatch):
    _in_the_workstation(monkeypatch, _Workstation(fail=True))
    res = call(client, "POST", "/api/agents/video-clipper/hire",
               json={"inputs": {"video": "talks/keynote.mp4", "moments": "00:01-00:20 intro"}})
    assert res.status_code == 200, res.text


AGENT = """---
id: tool-user
name: Tool User
tagline: Uses a program.
section: devops
version: 1.0.0
inputs:
  - {key: engine, kind: choice, label: Which, choices: [a, b]}
triggers:
  - {on: hand}
tools: [bash]
needs: {programs: %s}
---
Run the program in one bash command, and report what it printed, line by line.
"""


@pytest.mark.parametrize("programs,words", [
    ("[Bad Name]", "is not a program's name"),
    ("[{name: ffmpeg, sudo: yes}]", "a field nothing reads"),
    ("[{name: ffmpeg, when: {colour: red}}]", "asks for no “colour”"),
    ("[{name: ffmpeg, when: {engine: c}}]", "not one of its choices"),
    ("[]", "is a list of the programs"),
])
def test_a_file_that_names_programs_wrongly_is_refused_in_a_sentence(programs, words):
    with pytest.raises(ManifestRefused) as refused:
        parse_manifest(AGENT % programs)
    assert words in refused.value.sentence


def test_a_file_that_names_them_rightly_reads():
    m = parse_manifest(AGENT % '[jq, {name: ffmpeg, when: {engine: a}, install: "sudo apt-get install -y ffmpeg"}]')
    assert m.needs["programs"] == [{"name": "jq"}, {"name": "ffmpeg", "when": {"engine": "a"},
                                                    "install": "sudo apt-get install -y ffmpeg"}]
