# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1130` — an admin registers a person's build from a list, never by typing.

**Before** (measured on `7a7f9b2`): every scaffold route is the caller's own,
so *Register* filled the admin's form only for an author who was an admin;
anyone else got the fields as text — the relay's path, `--owner`, `--server`
and, since `integrate-e`'s pin, `--sha256` and a 64-character fingerprint — and
an admin typed them into *Add MCP Server*, one argument box at a time, again
after every edit.

**Now:** the person presses *Send it to an admin*; an admin sees what waits
(`GET /api/mcp/builds-sent`), opens one and reads its code as it was sent
(`GET /api/mcp/builds-sent/{id}`), and *Register* fills the existing form with
the admin route's fields, pin included — Save is `POST /api/mcp/servers`,
`require_admin`, the only door, unchanged. The build stays in its author's
workstation.

**The adversary (`Law 17`):** the person's assistant — steered by text it read
— or the person, sending a build. Its aim: an admin registers something other
than what the admin was shown. Each way has a case:

  * the assistant itself: it cannot send, read the list, read a send's code,
    take one off, or register one — through `app_api` (the real tool, its
    loopback landing on these routes) or `manage_mcp`. The internal-tool token
    passes `require_admin` outright, so "admin only" alone would have let any
    person's assistant read everyone's sends;
  * another person: one with a workstation of their own cannot send, see or
    withdraw ann's;
  * another account, or another command: a send carries the server's name and
    nothing else; whose comes from the session; the fields are Pantheon's;
  * other code than shown: what the admin reads and what the form pins come
    from one walk of the folder — every file the pin covers is in the list —
    and once registered the relay runs those bytes or nothing; a change since
    the send is said and never runs;
  * code that reads one way and runs another: a bidirectional control
    character, a coding line naming another codec, bytes that are not UTF-8,
    a file too large to show — not sent.

Driven, not read (`Law 20`): the real routes through `TestClient`, the real
workstation daemon, the real harness in ann's account, and — for the end of
the story — the relay as a real subprocess through `McpManager.connect_server`
with the fields the admin saved. Fixtures are
`test_an_mcp_server_is_built_in_your_workstation`'s.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

from core.middleware import INTERNAL_TOOL_HEADER
from src import workstation_mcp as wm
from tests.test_a_registered_server_runs_the_code_an_admin_registered import (
    CODE_THAT_SAYS_IT_RAN, _register, _relay,
)
from tests.test_an_mcp_server_is_built_in_your_workstation import (  # noqa: F401 — fixtures
    _USERS, _as, _home, _make, _relay_world, client, rows, station,
)


@pytest.fixture
def sent_store(station, monkeypatch):
    data = station.tmp / "sent-store"
    data.mkdir()
    monkeypatch.setattr("src.constants.DATA_DIR", str(data))
    return data / "mcp_builds_sent.json"


def _folder(station):
    return _home(station, "ann") / "mcp-servers" / "weather"


def _send(client, user="ann", headers=None, **body):
    return client.post("/api/mcp/scaffold/weather/send", json=body or None,
                       headers=headers or _as(user))


def _waiting(client):
    r = client.get("/api/mcp/builds-sent", headers=_as("admin"))
    assert r.status_code == 200, r.text
    return r.json()["sent"]


def _review(client, sent_id):
    r = client.get(f"/api/mcp/builds-sent/{sent_id}", headers=_as("admin"))
    assert r.status_code == 200, r.text
    return r.json()


def _assistant(client, monkeypatch, owner, method, path, body=None):
    """The agent's `app_api` tool — the real `do_app_api`, its blocklist and
    all — with its loopback landing on these routes the way `app.py`'s
    AuthMiddleware lands it: the internal-tool token kept (so `require_admin`
    lets it through, as it does in the app), and the request named as its
    `X-Pantheon-Owner`. Returns the tool's answer and the requests that
    reached a route."""
    import httpx
    from urllib.parse import urlsplit

    from src.tools.system import do_app_api
    reached = []

    class _Loopback:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, method, url, json=None, params=None, headers=None):
            sent = {k: v for k, v in (headers or {}).items() if k.lower() != "content-type"}
            sent["x-test-user"] = sent.get("X-Pantheon-Owner", "")
            reached.append((method, urlsplit(url).path))
            return client.request(method, urlsplit(url).path, json=json, params=params,
                                  headers=sent)

    with monkeypatch.context() as scoped:
        scoped.setattr(httpx, "AsyncClient", _Loopback)
        said = asyncio.run(do_app_api(json.dumps({"action": "call", "method": method,
                                                  "path": path, "body": body}), owner=owner))
    return said, reached


# ── the whole story ───────────────────────────────────────────────────────────

def test_ann_sends_and_the_admin_registers_exactly_what_she_sent(client, station, rows,
                                                                 sent_store, monkeypatch):
    _make(client)
    source = (_folder(station) / "server.py").read_text()
    sent = _send(client)
    assert sent.status_code == 200, sent.text
    mine = sent.json()["sent"]
    assert (mine["server"], mine["owner"]) == ("weather", "ann")
    assert [t["name"] for t in mine["tools"]] == ["get_forecast"]
    # Her card says so.
    entry, = client.get("/api/mcp/scaffold", headers=_as("ann")).json()["servers"]
    assert entry["sent"]["id"] == mine["id"]
    read = client.get("/api/mcp/scaffold/weather", headers=_as("ann")).json()
    assert read["sent"] == {"id": mine["id"], "at": mine["sent_at"], "as_sent": True}

    pin = asyncio.run(wm.ws_fingerprint("ann", "weather"))
    listed, = _waiting(client)
    assert (listed["id"], listed["owner"], listed["server"]) == (mine["id"], "ann", "weather")
    assert listed["registered_before"] is False
    # Listed with the admin route's fields, fingerprint filled — nobody types.
    assert listed["registration"] == wm.ws_registration("ann", "weather", pin)
    review = _review(client, mine["id"])
    assert review["now"] == wm.NOW_AS_SENT and review["now_why"] is None
    shown, = review["files"]
    assert shown == {"path": "server.py", "kind": "source", "bytes": len(source.encode()),
                     "sha256": shown["sha256"], "text": source}
    # The form is filled with the admin route's fields, pinned to that code.
    reg = review["registration"]
    assert reg == listed["registration"]
    assert reg == wm.ws_registration("ann", "weather", pin)
    assert reg["args"] == [wm.RELAY_PATH, "--owner", "ann", "--server", "weather", "--sha256", pin]
    assert rows.count() == 1, "reviewing registers nothing"

    _register(client, reg)                        # the admin presses Save: one POST
    assert rows.count() == 2
    assert _waiting(client) == [], "registered with the code that was sent: it leaves the list"
    assert json.loads(sent_store.read_text()) == []
    assert client.get("/api/mcp/scaffold/weather", headers=_as("ann")).json()["registered"] == "current"
    _relay_world(station, monkeypatch)
    started, status, tools, (said,) = _relay(reg)
    assert started is True and tools == ["get_forecast"], status
    assert said["exit_code"] == 0 and "Oslo" in said["stdout"], said


# ── another account, another command ─────────────────────────────────────────

def test_a_send_carries_the_servers_name_and_nothing_else(client, station, sent_store):
    _make(client)
    forged = {"owner": "bob", "server": "elsewhere", "command": "/bin/sh",
              "args": ["-c", "id > /tmp/owned"], "pin": "0" * 64, "sent_by": "person"}
    sent = _send(client, **forged).json()["sent"]
    review = _review(client, sent["id"])
    pin = asyncio.run(wm.ws_fingerprint("ann", "weather"))
    assert review["registration"]["command"] == wm.ws_registration("ann", "weather", pin)["command"]
    assert review["registration"]["args"] == [wm.RELAY_PATH, "--owner", "ann", "--server",
                                              "weather", "--sha256", pin]
    stored, = json.loads(sent_store.read_text())
    assert "command" not in stored and "args" not in stored and "/bin/sh" not in json.dumps(stored)


def test_another_person_cannot_send_see_or_withdraw_anns_and_a_token_is_not_a_person(
        client, station, sent_store, monkeypatch):
    """cat has a workstation of her own: "weather" in a send is a name in HER
    folder, never ann's; the list and a send's code are an admin's; a send is
    withdrawn by its sender or an admin. bob may not use a workstation at all.
    A bearer token is not a person."""
    monkeypatch.setitem(_USERS, "cat", {"admin": False, "privs": {"can_use_workstation": True}})
    _make(client)
    sent = _send(client).json()["sent"]
    stored = sent_store.read_text()

    not_hers = client.post("/api/mcp/scaffold/weather/send", headers=_as("cat"))
    assert not_hers.status_code == 400, not_hers.text
    assert not_hers.json()["detail"] == "There is no server called 'weather' in your workstation."
    assert client.post("/api/mcp/scaffold/weather/send", headers=_as("bob")).status_code == 403
    token = client.post("/api/mcp/scaffold/weather/send",
                        headers={"x-test-user": "ann", "x-test-token": "1"})
    assert token.status_code in (401, 403)
    for user in ("cat", "bob"):
        for path in ("/api/mcp/builds-sent", f"/api/mcp/builds-sent/{sent['id']}"):
            assert client.get(path, headers=_as(user)).status_code == 403, (user, path)
        assert client.delete(f"/api/mcp/builds-sent/{sent['id']}",
                             headers=_as(user)).status_code == 403, user
        assert client.get("/api/mcp/scaffold/weather", headers=_as(user)).status_code != 200, user
    assert sent_store.read_text() == stored, "nothing anyone else did moved ann's send"
    assert [e["id"] for e in _waiting(client)] == [sent["id"]]


def test_the_assistant_cannot_send_read_withdraw_or_register_a_build(client, station, rows,
                                                                      sent_store, monkeypatch):
    """The agent's own doors, driven: ann's assistant sending her build, the
    admin's and bob's reading the list and a send's code, ann's withdrawing it,
    and the admin's registering it — through `app_api` and through
    `manage_mcp`. The admin's assistant passes `require_admin`, so the route's
    own refusal (a person's only) is what holds for it; bob's is refused by
    `require_admin` itself since `B1175` (moved at the merge, `integrate-g`:
    the token used to pass whoever's assistant it was)."""
    import src.agent_tools.admin_tools as admin_tools

    _make(client)
    said, reached = _assistant(client, monkeypatch, "ann", "POST", "/api/mcp/scaffold/weather/send")
    assert said["exit_code"] == 1 and said["status_code"] == 403, said
    assert "not your assistant" in said["body"]
    assert reached == [("POST", "/api/mcp/scaffold/weather/send")], "refused by the route itself"
    assert not sent_store.exists()

    sent = _send(client).json()["sent"]                       # ann herself sends it
    stored = sent_store.read_text()
    for owner, refusal in (("admin", "not by an API token or an assistant"),
                           ("bob", "Admin only")):
        for path in ("/api/mcp/builds-sent", f"/api/mcp/builds-sent/{sent['id']}"):
            said, _ = _assistant(client, monkeypatch, owner, "GET", path)
            assert said["exit_code"] == 1 and said["status_code"] == 403, (owner, path, said)
            assert refusal in said["body"], (owner, path, said)
            assert "weather" not in said["body"] and sent["pin"] not in said["body"]
    for owner in ("admin", "ann"):
        said, _ = _assistant(client, monkeypatch, owner, "DELETE", f"/api/mcp/builds-sent/{sent['id']}")
        assert said["status_code"] == 403, (owner, said)
    assert sent_store.read_text() == stored

    reg = _waiting(client)[0]["registration"]
    said, reached = _assistant(client, monkeypatch, "admin", "POST", "/api/mcp/servers", {
        "name": reg["name"], "transport": "stdio", "command": reg["command"],
        "args": json.dumps(reg["args"]), "env": "{}"})
    assert said["exit_code"] == 1 and reached == [], "refused before a request is built"
    monkeypatch.setattr(admin_tools, "get_mcp_manager", lambda: client.manager)
    added = asyncio.run(admin_tools.do_manage_mcp(json.dumps({
        "action": "add", "name": reg["name"], "command": reg["command"],
        "args": reg["args"], "env": reg["env"]})))
    assert added["exit_code"] == 1 and added["error"] == wm.agent_refusal(reg)
    assert rows.count() == 1 and client.manager.spawned == []
    assert [e["id"] for e in _waiting(client)] == [sent["id"]], "still waits for a person"


# ── other code than shown ─────────────────────────────────────────────────────

def test_every_file_the_pin_covers_is_shown(client, station, sent_store):
    _make(client)
    folder = _folder(station)
    (folder / "helper.py").write_text("SECRET_STEP = 'what server.py imports'\n")
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__" / "helper.cpython-312.pyc").write_bytes(b"\x00compiled\x00" * 3)
    os.symlink("/etc/hostname", folder / "elsewhere.py")
    sent = _send(client).json()["sent"]
    review = _review(client, sent["id"])
    by_path = {f["path"]: f for f in review["files"]}
    assert by_path["helper.py"]["text"] == "SECRET_STEP = 'what server.py imports'\n"
    assert by_path["__pycache__/helper.cpython-312.pyc"]["kind"] == "compiled"
    assert by_path["__pycache__/helper.cpython-312.pyc"]["bytes"] == 30
    assert "text" not in by_path["__pycache__/helper.cpython-312.pyc"]
    links = [f for f in review["files"] if f["kind"] == "link"]
    assert links == [{"path": "elsewhere.py", "kind": "link", "target": "/etc/hostname"}]
    assert review["registration"]["args"][6] == asyncio.run(wm.ws_fingerprint("ann", "weather"))


def test_the_snapshot_pins_what_the_registration_pins(client, station, sent_store):
    """One fingerprint function: the snapshot's walk and the registration's
    agree, so a send never pins something the relay would refuse."""
    reg = _make(client).json()["registration"]
    sent = _send(client).json()["sent"]
    assert sent["pin"] == reg["args"][6]


def test_code_changed_after_the_send_is_said_and_never_runs(client, station, rows, sent_store,
                                                            monkeypatch):
    _make(client)
    sent_source = (_folder(station) / "server.py").read_text()
    sent = _send(client).json()["sent"]
    assert client.put("/api/mcp/scaffold/weather", headers=_as("ann"),
                      json={"source": CODE_THAT_SAYS_IT_RAN}).status_code == 200
    assert client.get("/api/mcp/scaffold/weather", headers=_as("ann")).json()["sent"]["as_sent"] is False
    review = _review(client, sent["id"])
    assert review["now"] == wm.NOW_CHANGED
    assert review["files"][0]["text"] == sent_source, "the admin reads what was sent"
    reg = review["registration"]
    assert reg["args"][6] == sent["pin"] != asyncio.run(wm.ws_fingerprint("ann", "weather"))
    # Registered anyway, it runs the code the admin read — and that code is
    # gone, so nothing runs: not the code nobody showed them.
    _register(client, reg)
    _relay_world(station, monkeypatch)
    started, status, tools, out = _relay(reg)
    assert started is False and tools == [] and out == []
    assert wm.changed_since_registered("weather") in str(status.get("error")), status
    assert not (_home(station, "ann") / "it-ran").exists()


# ── code that reads one way and runs another ──────────────────────────────────

_RLO = "\u202e"  # RIGHT-TO-LEFT OVERRIDE, as an escape: a literal one is the plant


@pytest.mark.parametrize("plant, said", [
    ("bidi", "changes the direction text is drawn in"),
    ("coding", "names its own encoding"),
    ("latin1", "is not UTF-8 text"),
    ("huge", "is larger than can be shown to an admin"),
    ("many", "more code files and links than can be shown"),
])
def test_code_that_would_not_read_as_it_runs_is_not_sent(client, station, sent_store, plant, said):
    _make(client)
    folder = _folder(station)
    path = folder / "server.py"
    if plant == "bidi":
        path.write_text(path.read_text() + f"\naccess = 'user' # {_RLO} ;)resu' == ssecca(fi\n")
    elif plant == "coding":
        path.write_text("# -*- coding: unicode_escape -*-\n" + path.read_text())
    elif plant == "latin1":
        (folder / "notes.py").write_bytes("# café\n".encode("latin-1"))
    elif plant == "huge":
        # Just over what the panel's own editor opens (and so what an admin is
        # shown whole): a fixed expectation, not the harness's constant.
        (folder / "data.py").write_text("X = '" + "a" * (wm.MAX_SOURCE_BYTES + 10) + "'\n")
    else:
        for i in range(201):
            (folder / f"m{i}.py").write_text("")
    r = _send(client)
    assert r.status_code == 400, r.text
    assert said in r.json()["detail"] and "not sent" in r.json()["detail"]
    assert not sent_store.exists() or json.loads(sent_store.read_text()) == []


# ── who sees the list, and who takes one off it ──────────────────────────────

def test_only_an_admin_reads_the_list_and_only_they_or_the_sender_take_one_off(client, station,
                                                                                 sent_store):
    _make(client)
    sent = _send(client).json()["sent"]
    for path in ("/api/mcp/builds-sent", f"/api/mcp/builds-sent/{sent['id']}"):
        assert client.get(path, headers=_as("ann")).status_code == 403
        assert client.get(path, headers=_as("bob")).status_code == 403
    assert client.delete(f"/api/mcp/builds-sent/{sent['id']}", headers=_as("bob")).status_code == 403
    assert client.delete(f"/api/mcp/builds-sent/{sent['id']}",
                         headers=_as("ann")).json() == {"removed": True, "server": "weather"}
    assert _waiting(client) == []
    again = _send(client).json()["sent"]
    assert client.delete(f"/api/mcp/builds-sent/{again['id']}", headers=_as("admin")).status_code == 200
    gone = client.get(f"/api/mcp/builds-sent/{again['id']}", headers=_as("admin"))
    assert gone.status_code == 404 and "not waiting for an admin" in gone.json()["detail"]


def test_a_send_replaces_that_servers_last_and_one_person_has_a_limit(client, station, sent_store,
                                                                       monkeypatch):
    _make(client)
    first = _send(client).json()["sent"]
    path = _folder(station) / "server.py"
    client.put("/api/mcp/scaffold/weather", headers=_as("ann"),
               json={"source": path.read_text() + "\n# a second go\n"})
    second = _send(client).json()["sent"]
    listed, = _waiting(client)
    assert listed["id"] == second["id"] != first["id"] and listed["pin"] == second["pin"] != first["pin"]
    monkeypatch.setattr(wm, "MAX_SENT_PER_PERSON", 1)
    _make(client, name="tides", tools=["get_tide"])
    over = client.post("/api/mcp/scaffold/tides/send", headers=_as("ann"))
    assert over.status_code == 400 and "waiting for an admin already" in over.json()["detail"]


def test_one_registered_before_says_so_and_still_waits(client, station, rows, sent_store):
    """Registered with older code, then changed and sent: the admin's Register
    re-registers that row (the browser opens its Edit) — the list says so."""
    reg = _make(client).json()["registration"]
    _register(client, reg)
    client.put("/api/mcp/scaffold/weather", headers=_as("ann"), json={"source": CODE_THAT_SAYS_IT_RAN})
    _send(client)
    listed, = _waiting(client)
    assert listed["registered_before"] is True


def test_changed_and_sent_again_it_is_registered_again_in_one_save(client, station, rows,
                                                                  sent_store, monkeypatch):
    """`integrate-e`'s Verify: an admin registers *and re-registers* a person's
    build without typing a fingerprint. Registered, changed by ann, sent
    again: the list carries the new fingerprint, and one `PUT` of that row —
    the admin route the browser's Register opens (`registerBuilt`) — re-pins
    it; no second row, and the relay answers the new code."""
    _make(client)
    _send(client)
    first, = _waiting(client)
    server_id = _register(client, first["registration"])
    assert rows.count() == 2 and _waiting(client) == []

    assert client.put("/api/mcp/scaffold/weather", headers=_as("ann"),
                      json={"source": CODE_THAT_SAYS_IT_RAN}).json() == {"saved": True, "registered": True}
    assert client.get("/api/mcp/scaffold/weather", headers=_as("ann")).json()["registered"] == "changed"
    _send(client)
    again, = _waiting(client)
    new_pin = asyncio.run(wm.ws_fingerprint("ann", "weather"))
    assert again["registered_before"] is True
    assert again["registration"] == wm.ws_registration("ann", "weather", new_pin)
    assert new_pin != first["registration"]["args"][6]

    reg = again["registration"]
    saved = client.put(f"/api/mcp/servers/{server_id}", headers=_as("admin"), data={
        "name": reg["name"], "transport": "stdio", "command": reg["command"],
        "args": json.dumps(reg["args"]), "env": json.dumps(reg["env"])})
    assert saved.status_code == 200, saved.text
    assert rows.count() == 2, "the same row, re-pinned"
    assert _waiting(client) == []
    assert client.get("/api/mcp/scaffold/weather", headers=_as("ann")).json()["registered"] == "current"
    _relay_world(station, monkeypatch)
    started, status, tools, (said,) = _relay(reg)
    assert started is True and tools == ["get_forecast"], status
    assert said["stdout"] == "the new code answered", said


# ── the walk did not move ─────────────────────────────────────────────────────

#: `fingerprint` of the folder `_plant_every_kind` makes, computed by the
#: harness as it stood before B1130 (`7a7f9b2`). Every registration stored
#: since `integrate-e` carries a pin from that walk; a walk that hashed one
#: byte differently would take every one of them off the air.
PIN_BEFORE_B1130 = "3ebc910e2ea7ce63a670666fa1f12588e28c63a96f95bacff82da5eef4cfae9a"


def _plant_every_kind(root):
    (root / "pkg" / "__pycache__").mkdir(parents=True)
    (root / "server.py").write_text("print('hello')\n")
    (root / "pkg" / "__init__.py").write_text("X = 1\n")
    (root / "pkg" / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"\x00\x01\x02")
    (root / "README.md").write_text("not code\n")
    (root / "native.so").write_bytes(b"\x7fELF")
    os.symlink("/etc/hostname", root / "link.py")
    os.symlink("/usr/lib", root / "vendored")


def _harness(home, job):
    import subprocess
    import sys
    done = subprocess.run([sys.executable, "-c", wm.PROBE_HARNESS], input=json.dumps(job),
                          capture_output=True, text=True, timeout=60,
                          env={"HOME": str(home), "PATH": os.environ.get("PATH", "")})
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_pin_stored_before_the_snapshot_existed_still_matches(tmp_path):
    folder = tmp_path / "mcp-servers" / "weather"
    _plant_every_kind(folder)
    assert _harness(tmp_path, {"slug": "weather", "action": "digest"})["digest"] == PIN_BEFORE_B1130
    snap = _harness(tmp_path, {"slug": "weather", "action": "snapshot"})
    assert snap["digest"] == PIN_BEFORE_B1130
    assert [(f["path"], f["kind"]) for f in snap["files"]] == [
        ("vendored", "link"), ("link.py", "link"), ("link.py", "source"), ("native.so", "compiled"),
        ("server.py", "source"), ("pkg/__init__.py", "source"),
        ("pkg/__pycache__/m.cpython-312.pyc", "compiled")]


def test_code_changed_while_it_is_being_sent_is_not_sent(client, station, sent_store, monkeypatch):
    """The tools an admin is told about are the snapshot's code's: the start
    check runs against the snapshot's fingerprint, so code changed between the
    two (as the author's assistant could, from the workstation) is refused."""
    _make(client)
    real = wm._probe

    async def probe(client_, account, job, timeout):
        answer = await real(client_, account, job, timeout)
        if job.get("action") == "snapshot":
            (_folder(station) / "server.py").write_text(CODE_THAT_SAYS_IT_RAN)
        return answer

    monkeypatch.setattr(wm, "_probe", probe)
    r = _send(client)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "It changed while it was being sent, so it was not sent. Send it again."
    assert not (_home(station, "ann") / "it-ran").exists()
    assert not sent_store.exists() or json.loads(sent_store.read_text()) == []
