# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1258` — one home for "how the LLM is served": the Servers card.

**Measured on `2760dbe1`:** the machines the Forge serves on (`env.servers`)
had two writers, both reading the server cards out of the page —
`cookbook.js` `_syncServers` and `cookbook-hwfit.js` `_syncServers` — and both
saved them through the Forge's whole-state save, `POST /api/cookbook/state`,
from the browser's `_envState`. So the one place to edit a server was inside
the Forge, Settings → Forge could only offer a door to it, and a Forge left
open in another tab posted its own copy of the list over whatever had been
changed since (the route's only guard kept an *empty* list from landing).

Now:

* the servers have their own route, `GET`/`PUT /api/cookbook/servers`, the
  operator's (`require_operator`, auth map § G), and a revision: a save made
  from an older list is refused with the list as it is now (409);
* the whole-state save keeps the servers, the default server and the revision
  as they are on disk, whatever its body says;
* one editor (`cookbook-hwfit.js` `mountServersEditor`, mounted through
  `servingSettings.js` `mountServers`) in Settings → Forge, its home, and in
  the Forge's Settings tab; what it keeps is told to the Forge
  (`cookbook:servers-changed`), whose dropdowns follow.

Driven: the real routes on a real temp state file through the real router;
`tests/test_the_servers_in_a_browser.py` drives both windows in Chromium.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

LAB = {"name": "lab", "host": "me@lab", "port": "", "env": "venv", "envPath": "~/venv", "color": "",
       "modelDirs": ["~/.cache/huggingface/hub"], "downloadDir": "", "platform": ""}


@pytest.fixture()
def forge(monkeypatch, tmp_path):
    from tests.helpers.signed_in import ADMIN, MEMBER, as_person, signed_in
    import routes.cookbook_routes as cr

    manager = signed_in(monkeypatch, tmp_path / "auth")
    state = tmp_path / "cookbook_state.json"
    state.write_text(json.dumps({"env": {"servers": [dict(LAB)], "defaultServer": "", "remoteHost": "me@lab"},
                                 "tasks": [], "presets": []}), encoding="utf-8")
    monkeypatch.setattr(cr, "COOKBOOK_STATE_FILE", str(state))

    def client(person):
        app = FastAPI()
        app.include_router(cr.setup_cookbook_routes())
        return TestClient(as_person(app, person, auth_manager=manager))

    return client, state, ADMIN, MEMBER


def _on_disk(state: Path) -> dict:
    return json.loads(state.read_text(encoding="utf-8"))


def test_the_servers_are_read_and_saved_through_their_own_door(forge):
    client, state, admin, _ = forge
    op = client(admin)
    got = op.get("/api/cookbook/servers").json()
    assert got["servers"] == [LAB] and got["rev"] == 0 and got["defaultServer"] == ""
    gpu = {**LAB, "name": "gpu", "host": "me@gpu", "port": "2222", "modelDirs": ["/data/models"],
           "downloadDir": "/data/models"}
    r = op.put("/api/cookbook/servers", json={"servers": [{"host": "", "name": "Here"}, LAB, gpu],
                                              "defaultServer": "local", "rev": 0})
    assert r.status_code == 200, r.text
    kept = r.json()
    assert kept["rev"] == 1 and kept["defaultServer"] == "local"
    assert [s["host"] for s in kept["servers"]] == ["", "me@lab", "me@gpu"]
    assert kept["servers"][2]["modelDirs"] == ["~/.cache/huggingface/hub", "/data/models"], \
        "the default cache is always one of a server's folders"
    env = _on_disk(state)["env"]
    assert env["servers"] == kept["servers"] and env["serversRev"] == 1 and env["defaultServer"] == "local"
    assert env["remoteHost"] == "me@lab", "nothing else in the state was touched"
    assert op.get("/api/cookbook/state").json()["env"]["servers"] == kept["servers"], \
        "the Forge's own read sees what was kept"


def test_a_save_from_an_older_list_is_refused_with_the_list_as_it_is_now(forge):
    """A Forge left open in another tab drew revision 0; Settings saved
    revision 1 since. Its save is refused, and answered with revision 1."""
    client, state, admin, _ = forge
    op = client(admin)
    op.put("/api/cookbook/servers", json={"servers": [LAB, {**LAB, "name": "new", "host": "me@new"}], "rev": 0})
    stale = op.put("/api/cookbook/servers", json={"servers": [LAB], "rev": 0})
    assert stale.status_code == 409
    assert "another window" in stale.json()["detail"]
    assert [s["host"] for s in stale.json()["current"]["servers"]] == ["me@lab", "me@new"]
    assert stale.json()["current"]["rev"] == 1
    assert [s["host"] for s in _on_disk(state)["env"]["servers"]] == ["me@lab", "me@new"], "nothing was written"
    for rev in (None, "1", True):
        assert op.put("/api/cookbook/servers", json={"servers": [LAB], "rev": rev}).status_code == 409


def test_the_whole_state_save_no_longer_writes_the_servers(forge):
    client, state, admin, _ = forge
    op = client(admin)
    op.put("/api/cookbook/servers", json={"servers": [LAB], "defaultServer": "local", "rev": 0})
    before = _on_disk(state)["env"]
    for env in ({"servers": [{"host": "me@stale-tab"}], "defaultServer": "srv:x", "serversRev": 99},
                {"servers": []}, {}):
        body = {"env": {**env, "remoteHost": "me@lab"}, "tasks": [], "presets": []}
        assert op.post("/api/cookbook/state", json=body).status_code == 200
        now = _on_disk(state)["env"]
        assert (now["servers"], now["defaultServer"], now["serversRev"]) == \
            (before["servers"], before["defaultServer"], before["serversRev"]), env


@pytest.mark.parametrize("server,words", [
    ({"host": "me@lab; rm -rf ~"}, "not a server address"),
    ({"host": "-oProxyCommand=x"}, "not a server address"),
    ({"host": "me@lab", "port": "70000"}, "not an SSH port"),
    ({"host": "me@lab", "env": "docker"}, "none, venv or conda"),
    ({"host": "me@lab", "envPath": "~/venv\nrm -rf ~"}, "one line"),
    ({"host": "me@lab", "modelDirs": ["/a\x00b"]}, "one line"),
])
def test_a_bad_server_is_refused_with_a_sentence_and_nothing_is_saved(forge, server, words):
    client, state, admin, _ = forge
    r = client(admin).put("/api/cookbook/servers", json={"servers": [server], "rev": 0})
    assert r.status_code == 400 and words in r.json()["detail"] and "Nothing was saved" in r.json()["detail"]
    assert _on_disk(state)["env"]["servers"] == [LAB]


def test_one_local_entry_and_a_member_who_does_not_run_the_instance_is_refused(forge):
    client, state, admin, member = forge
    kept = client(admin).put("/api/cookbook/servers", json={
        "servers": [LAB, {"host": "local", "name": "A"}, {"host": "", "name": "B"}], "rev": 0}).json()
    assert [(s["host"], s["name"]) for s in kept["servers"]] == [("", "A"), ("me@lab", "lab")], \
        "the local entry first, and only once"
    m = client(member)
    assert m.get("/api/cookbook/servers").status_code == 403
    assert m.put("/api/cookbook/servers", json={"servers": [], "rev": 1}).status_code == 403
    assert _on_disk(state)["env"]["serversRev"] == 1


def test_the_token_and_the_servers_doors_leave_each_other_alone(forge):
    client, state, admin, _ = forge
    op = client(admin)
    op.put("/api/cookbook/hf-token", json={"token": "hf_abcdefghijklmnopqrstuvwxyz0123"})
    op.put("/api/cookbook/servers", json={"servers": [LAB, {**LAB, "host": "me@two"}], "rev": 0})
    env = _on_disk(state)["env"]
    assert env["hfToken"] and len(env["servers"]) == 2
    op.put("/api/cookbook/hf-token", json={"token": ""})
    assert len(_on_disk(state)["env"]["servers"]) == 2


def test_the_agents_api_bridge_cannot_rewrite_the_servers():
    """Which boxes the instance opens SSH to is the person's, in Settings →
    Forge: the generic `app_api` bridge is refused the servers' door, as it is
    the token's and the whole-state save, before any request is made."""
    import asyncio
    from src.tools.system import do_app_api
    for path in ("/api/cookbook/servers", "/api/cookbook/./servers", "/api/cookbook/x/../servers"):
        got = asyncio.run(do_app_api(json.dumps({"action": "call", "method": "PUT", "path": path,
                                                 "body": {"servers": [], "rev": 0}}), owner="ada"))
        assert got["exit_code"] == 1 and "Settings → Forge" in got["error"], got
        assert "not mine to change" in got["error"], "it says whose it is, not that a file would be overwritten"
