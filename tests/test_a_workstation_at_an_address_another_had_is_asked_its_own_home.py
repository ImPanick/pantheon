# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1661` — a workstation daemon started at an address another one had is
asked its own home.

`_home_path` (`src/agent_tools/workstation_tools.py`, `B962`) remembers each
account's home, so a command knows where it starts without asking the daemon
every call. It was keyed by the workstation's address, and an address is not a
daemon. In the suite's one-process run (the chunked run on `9d4d2d1`),
`test_testing_a_members_own_asks_from_their_workstation` was refused
*"…/test_what_is_not_a_folder_of_t0/workstation-homes/pw-ann-… is outside your
home (…/test_testing_a_members_own_ask0/workstation-homes/pw-ann-…)"*: the
refusal came from the test's own daemon, about the folder Pantheon had handed
it — the home an earlier test's daemon had answered at the same port, which
the OS had handed out again (a freed port comes back: 7,000-odd candidates,
and the process remembers every one a daemon used). No earlier daemon was
alive; this process remembered what one had said. The same happens to a
workstation reinstalled, or replaced, at the address Pantheon already knows,
with its homes elsewhere — every member's `git`, `shell_with_login` and own
`api_call` refused until Pantheon restarts.

Now the daemon says which run it is (`health`'s `run`, made when it starts,
told only to a caller with the token) and a home is remembered per run.

Driven (`Law 20`): two real daemons (`tests/helpers/workstation_daemon.py`
runs `workstation/agentd.py`), the second started on the port the first was
stopped on, behind the real `/api/auth/integrations/{id}/test` route and the
real `_Place` it opens (`src/agent_tools/git_tools.py`).
"""
from __future__ import annotations

import asyncio
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.integrations as I
from src.agent_tools import workstation_tools as wt
from src.workstation_access import sync_config
from src.workstation_client import WorkstationClient, account_for
from test_a_members_own_connection_is_called_from_their_workstation import (
    ANN_KEY, _add, _Auth, _Service)
from tests.helpers.signed_in import as_person
from tests.helpers.workstation_daemon import running_workstation

OK = {"ok": True, "message": "Connection successful"}


@pytest.fixture
def member(tmp_path, monkeypatch):
    """Ann, a member with a workstation, signed in to the real routes; the
    workstation's address is whatever `point_at` was last given."""
    import core.auth
    import src.settings as S
    from routes import auth_routes
    from workstation import protocol as P

    monkeypatch.setattr(core.auth, "AuthManager", _Auth)
    monkeypatch.setattr(core.auth, "_SHARED_AUTH_MANAGER", None, raising=False)
    monkeypatch.setattr(I, "DATA_FILE", str(tmp_path / "integrations.json"))
    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)
    monkeypatch.delenv(P.URL_ENV, raising=False)
    monkeypatch.delenv(P.TOKEN_ENV, raising=False)
    values = {}
    real = S.get_setting
    monkeypatch.setattr(S, "get_setting",
                        lambda key, default=None: values[key] if key in values else real(key, default))

    def point_at(ws):
        values.update({"workstation_enabled": True, "workstation_url": ws.url,
                       "workstation_token": ws.token, "workstation_sudo": False})

    _Service.seen = []
    service = ThreadingHTTPServer(("127.0.0.1", 0), _Service)
    threading.Thread(target=service.serve_forever, daemon=True).start()
    app = FastAPI()
    app.include_router(auth_routes.setup_auth_routes(_Auth()))
    try:
        yield SimpleNamespace(ann=TestClient(as_person(app, "ann", auth_manager=_Auth())),
                              base=f"http://127.0.0.1:{service.server_port}", point_at=point_at)
    finally:
        service.shutdown()
        service.server_close()


def test_a_members_test_reaches_the_daemon_now_at_the_address(member, tmp_path):
    """The suite's failure, made to happen every time: the second daemon is
    started on the port the first was stopped on."""
    own = _add(member.ann, member.base, name="Ann's ntfy", preset="ntfy", auth_type="bearer",
               api_key=ANN_KEY)
    with running_workstation(tmp_path / "first") as first:
        member.point_at(first)
        assert member.ann.post(f"/api/auth/integrations/{own['id']}/test").json() == OK
        port = urlsplit(first.url).port
    with running_workstation(tmp_path / "second", port=port) as second:
        assert second.url == first.url, "the same address, a different daemon"
        member.point_at(second)
        answer = member.ann.post(f"/api/auth/integrations/{own['id']}/test").json()
        assert answer == OK, answer
    assert [hit["path"] for hit in _Service.seen] == ["/", "/"], "each daemon's curl reached it"


def _homes_asked(monkeypatch):
    asked = []
    real = WorkstationClient.list

    async def spy(self, account, path, **kw):
        if path is None:
            asked.append(str(self.base))
        return await real(self, account, path, **kw)

    monkeypatch.setattr(WorkstationClient, "list", spy)
    return asked


def _home(ws, *, introduced=True):
    async def go():
        client = WorkstationClient(ws.url, ws.token)
        if introduced:
            await sync_config(client)   # as every caller of `_home_path` does first
        return await wt._home_path(client, account_for("ann"))
    return asyncio.run(go())


def test_a_home_is_asked_once_per_daemon_run(tmp_path, monkeypatch):
    asked = _homes_asked(monkeypatch)
    with running_workstation(tmp_path / "first") as first:
        homes = [_home(first) for _ in range(3)]
        port = urlsplit(first.url).port
    assert homes == [str(first.root / account_for("ann"))] * 3
    assert len(asked) == 1, "`B962` holds: one daemon is asked its home once"
    with running_workstation(tmp_path / "second", port=port) as second:
        assert _home(second) == str(second.root / account_for("ann"))
        assert _home(second) == str(second.root / account_for("ann"))
    assert len(asked) == 2, "the daemon now at the address was asked once, for its own"


def test_the_run_is_told_to_the_token_and_differs_between_daemons(tmp_path):
    def health(ws, token):
        return asyncio.run(WorkstationClient(ws.url, token).health())

    with running_workstation(tmp_path / "first") as first:
        one = health(first, first.token)
        port = urlsplit(first.url).port
        assert "run" not in health(first, ""), "the token's to know, as `sudo` is"
        assert health(first, first.token)["run"] == one["run"], "one daemon, one run"
    with running_workstation(tmp_path / "second", port=port) as second:
        two = health(second, second.token)
    assert one["run"] and two["run"] and one["run"] != two["run"]


def test_a_client_that_has_not_asked_which_daemon_answers_asks_for_the_home(tmp_path,
                                                                            monkeypatch):
    """Without `health` the client cannot say which daemon it reached, so a
    remembered home is never its answer."""
    asked = _homes_asked(monkeypatch)
    with running_workstation(tmp_path / "first") as first:
        _home(first)
        port = urlsplit(first.url).port
    with running_workstation(tmp_path / "second", port=port) as second:
        assert _home(second, introduced=False) == str(second.root / account_for("ann"))
        assert _home(second, introduced=False) == str(second.root / account_for("ann"))
    assert len(asked) == 3


def test_a_daemon_that_does_not_say_its_run_is_remembered_by_its_address(tmp_path,
                                                                        monkeypatch):
    """A workstation older than `B1661`: as before — asked once per address."""
    from workstation.agentd import Workstation
    real = Workstation.health

    def older(self, authorised):
        out = real(self, authorised)
        out.pop("run", None)
        return out

    monkeypatch.setattr(Workstation, "health", older)
    asked = _homes_asked(monkeypatch)
    with running_workstation(tmp_path / "old") as old:
        assert [_home(old) for _ in range(2)] == [str(old.root / account_for("ann"))] * 2
    assert len(asked) == 1
