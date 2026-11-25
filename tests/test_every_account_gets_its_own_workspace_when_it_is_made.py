# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every account gets its own workspace when the account is made.

The owner (2026-11-25): Apollo "should be able to link into users workspaces
which should be predefined and assigned on account creation." A person's
workspace is their workstation home: with no folder picked, the shell and file
tools start there and `get_workspace` answers it (`B968`). It used to be made
the first time a tool ran there. Now:

  * making an account (signup or an admin's) starts making its home, beside
    the answer so a slow workstation never holds the account up;
  * startup makes a home for every existing account that has none;
  * a person whose work doesn't run in the workstation gets none, and a
    workstation that doesn't answer never stops an account being made.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest

from src import workstation_access as wa
from src.workstation_client import WorkstationError


@pytest.fixture
def station(monkeypatch):
    made = []

    async def ensure_ready(owner, *, auth_manager=None):
        if owner == "down":
            raise WorkstationError("unreachable", "The workstation didn't answer.")
        made.append(owner)
        return wa.Ready(None, f"pw-{owner}", {}, {"home": f"/home/pw-{owner}"})

    monkeypatch.setattr(wa, "ensure_ready", ensure_ready)
    monkeypatch.setattr(wa, "routes_tools", lambda owner, auth_manager=None: owner != "host-only")
    return made


def test_a_persons_home_is_made_and_named(station):
    assert asyncio.run(wa.provision_home("ana")) == "pw-ana"
    assert station == ["ana"]


def test_no_home_where_their_work_doesnt_run_in_the_workstation(station):
    assert asyncio.run(wa.provision_home("host-only")) is None
    assert asyncio.run(wa.provision_home(None)) is None
    assert station == []


def test_a_workstation_that_doesnt_answer_never_raises(station):
    assert asyncio.run(wa.provision_home("down")) is None


def test_startup_makes_a_home_for_every_existing_account(station):
    am = NS(users={"panick": {"is_admin": True}, "ana": {}, "host-only": {}, "down": {}})
    out = asyncio.run(wa.provision_all(am))
    assert out == {"ana": "pw-ana", "down": None, "host-only": None, "panick": "pw-panick"}
    assert sorted(station) == ["ana", "panick"]


def test_making_an_account_starts_making_its_home(monkeypatch):
    import routes.auth_routes as ar
    started = []

    async def provision_home(owner, *, auth_manager=None):
        started.append((owner, auth_manager))
        return f"pw-{owner}"

    monkeypatch.setattr(wa, "provision_home", provision_home)
    am = object()

    async def go():
        ar._make_their_workspace("ana", am)
        await asyncio.sleep(0)
        await asyncio.gather(*list(ar._WORKSPACE_TASKS))

    asyncio.run(go())
    assert started == [("ana", am)]
    assert not ar._WORKSPACE_TASKS


def test_both_ways_of_making_an_account_and_startup_call_it():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    routes = (root / "routes" / "auth_routes.py").read_text(encoding="utf-8")
    assert routes.count("_make_their_workspace(body.username, auth_manager)") == 2
    assert "_provision_all(auth_manager)" in (root / "app.py").read_text(encoding="utf-8")
