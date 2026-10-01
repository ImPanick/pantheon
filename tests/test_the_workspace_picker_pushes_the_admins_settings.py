# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B987` — the workspace picker's routes push the admin's settings, as a tool call does.

The daemon enforces what it was last *told*: the home jail follows `sudo`, the
network follows the mode, and a daemon that restarted has forgotten both. Every
routed tool call pushes them first (`run_in_workstation` → `sync_config`); the
picker's two routes (`GET /api/workspace/browse`, `/vet`, `B968`) read files
through the same daemon and did not — harmless today, because the picker stays
in the home whatever the jail, but a test wanting the jail lifted for the picker
had to lift it on the daemon itself, and *"the next route that reads files
through the daemon"* would have assumed a jail that matched the setting. Now the
two routes sync, and where `workstation_for` is defined it says who must and who
does (a comment cannot be tested; the behaviour below can).

Driven (`Law 20`): the picker's real routes in a real FastAPI app (`B968`'s
`picker` fixture), against the real daemon, whose own state is read afterwards;
and against a real network gate that refuses the mode, where the picker — like
a tool — says so instead of reading through a workstation held to a wider
network than the admin set.
"""
from __future__ import annotations

import pytest

from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _on, people, settings, ws)
from test_the_workspace_is_in_the_workstation import home, picker  # noqa: F401 — fixtures
from test_the_workstation_network_is_the_one_chosen import RunningGate, _point_at_gate


@pytest.mark.parametrize("route", ["browse", "vet"])
@pytest.mark.parametrize("wanted", [True, False])
def test_each_route_leaves_the_daemon_holding_the_admins_sudo(ws, settings, picker, home, route,
                                                              wanted):
    _on(settings, ws, workstation_sudo=wanted)
    ws.system.set_sudo(not wanted)            # a daemon told otherwise, or restarted
    r = picker(route, "ann", path="proj")
    assert r.status_code == 200, r.text
    assert ws.system.sudo is wanted


@pytest.mark.parametrize("route", ["browse", "vet"])
def test_each_route_leaves_the_daemon_holding_the_admins_network(ws, settings, picker, home, route):
    _on(settings, ws, workstation_network="none")
    assert ws.system.network == "full"
    assert picker(route, "ann", path="proj").status_code == 200
    assert ws.system.network == "none"


def test_with_sudo_on_the_answer_still_stays_in_the_home(ws, settings, picker, home):
    """The sync lifts the daemon's jail; the picker's own rule does not move."""
    _on(settings, ws, workstation_sudo=True)
    assert picker("browse", "ann", path="/etc").json()["path"] == str(home)
    assert ws.system.sudo is True
    assert picker("vet", "ann", path="/etc").json() == {"ok": False, "path": None,
                                                        "where": "workstation"}


def test_a_gate_that_will_not_take_the_mode_stops_the_picker_as_it_stops_a_tool(
        ws, settings, picker, home, tmp_path, monkeypatch):
    _on(settings, ws, workstation_network="internet")
    gate = RunningGate(tmp_path / "gate")
    try:
        _point_at_gate(monkeypatch, tmp_path, gate)
        gate.nft.refuse = True
        for route in ("browse", "vet"):
            r = picker(route, "ann", path="proj")
            assert r.status_code == 503, r.text
            assert "network gate could not put “internet” in force" in r.json()["detail"]
        gate.nft.refuse = False
        assert picker("browse", "ann", path="proj").status_code == 200
        assert gate.nft.loaded == "internet"
    finally:
        gate.close()


def test_with_the_workstation_off_the_host_answer_asks_nothing(ws, settings, picker, people):
    """`Law 1`: off, the routes are the host's, and the daemon hears nothing."""
    ws.system.set_sudo(True)
    r = picker("vet", "boss", path=str(ws.root))
    assert r.status_code == 200 and "where" not in r.json()
    assert ws.system.sudo is True and ws.system.network == "full"
