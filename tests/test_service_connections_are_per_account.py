# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P27-02` — service connections, per account.

`data/integrations.json` was one global list: every admin's key was in every
admin's list, every admin's agent's prompt and `api_call`, and in a non-admin's
reminder and daily brief. **Measured on `a16e7d75`:** an admin's Gitea token,
added by `ada`, was listed to `cyd` (another admin) with its first four
characters, named in `cyd`'s agent's integrations block, and callable from
`cyd`'s `api_call` by its name.

Now each record is its owner's (`owner`), shared with every account only when
its owner says so (`shared`); a person sees and their tools use their own and
the shared — another person's own is not even found (404) — and a shared one is
read-only to everyone but its owner (403, saying whose). A one-time migration
gives today's entries to the install's first admin, shared, so nothing in use
stops working.

Driven (`Law 20`): the real routes (`routes/auth_routes.py`) in a real app over
a real `AuthManager` with three accounts, the real store on a temp file, and
the real readers — the agent's integrations block, `api_call`, `execute_api_call`,
a workflow's list of integrations.
"""
from __future__ import annotations

import ast
import asyncio
import json
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.integrations as I
from tests.helpers.signed_in import ADMIN, MEMBER, PASSWORD, as_person, signed_in

ROOT = pathlib.Path(__file__).resolve().parents[1]
CYD = "cyd"           # a second admin
ADA_KEY = "ADA-SECRET-gitea-1"
CYD_KEY = "CYD-SHARED-ntfy-2"


@pytest.fixture()
def accounts(monkeypatch, tmp_path):
    monkeypatch.setattr(I, "DATA_FILE", str(tmp_path / "integrations.json"))
    manager = signed_in(monkeypatch, tmp_path / "auth")
    assert manager.create_user(CYD, PASSWORD, is_admin=True)
    from routes import auth_routes
    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)

    def client(person):
        app = FastAPI()
        app.include_router(auth_routes.setup_auth_routes(manager))
        return TestClient(as_person(app, person, auth_manager=manager))

    return client


def _add(client, **body):
    r = client.post("/api/auth/integrations", json={"base_url": "http://svc.lan:3000", **body})
    assert r.status_code == 200, r.text
    return r.json()["integration"]["id"]


@pytest.fixture()
def two(accounts):
    ada, cyd = accounts(ADMIN), accounts(CYD)
    a = _add(ada, name="Ada Gitea", auth_type="bearer", api_key=ADA_KEY)
    c = _add(cyd, name="House ntfy", auth_type="bearer", api_key=CYD_KEY, shared=True)
    return accounts, ada, cyd, a, c


def test_a_persons_own_key_is_never_in_another_persons_list(two):
    _, ada, cyd, a, c = two
    seen_by_cyd = cyd.get("/api/auth/integrations")
    assert [i["name"] for i in seen_by_cyd.json()["integrations"]] == ["House ntfy"]
    assert "ADA-" not in seen_by_cyd.text and a not in seen_by_cyd.text, "not a character of it, nor its id"

    seen_by_ada = {i["name"]: i for i in ada.get("/api/auth/integrations").json()["integrations"]}
    mine, theirs = seen_by_ada["Ada Gitea"], seen_by_ada["House ntfy"]
    assert (mine["mine"], mine["shared"], mine["read_only"], mine["api_key"]) == (True, False, False, "ADA-****")
    assert (theirs["mine"], theirs["shared"], theirs["read_only"], theirs["owner"]) == (False, True, True, CYD)
    assert theirs["api_key"] == "" and theirs["has_key"] is True, "a shared key is used, never shown"


def test_another_persons_own_is_not_found_and_a_shared_one_is_read_only(two):
    _, ada, cyd, a, c = two
    for r in (cyd.put(f"/api/auth/integrations/{a}", json={"name": "mine now"}),
              cyd.delete(f"/api/auth/integrations/{a}"),
              cyd.post(f"/api/auth/integrations/{a}/test")):
        assert r.status_code == 404, r.text
    for r in (ada.put(f"/api/auth/integrations/{c}", json={"base_url": "http://evil.lan"}),
              ada.delete(f"/api/auth/integrations/{c}")):
        assert r.status_code == 403
        assert r.json()["detail"] == ("“House ntfy” is cyd's, shared with everyone to use; "
                                      "only cyd can change or remove it.")
    stored = {i["id"]: i for i in I.load_integrations()}
    assert stored[a]["name"] == "Ada Gitea" and stored[c]["base_url"] == "http://svc.lan:3000"


def test_a_body_cannot_name_its_owner_and_only_the_owner_moves_shared(two):
    _, ada, cyd, a, c = two
    x = _add(ada, name="Sneaky", owner=CYD, shared="yes")
    stored = {i["id"]: i for i in I.load_integrations()}
    assert stored[x]["owner"] == ADMIN and stored[x]["shared"] is False
    assert ada.put(f"/api/auth/integrations/{a}", json={"owner": CYD, "shared": True}).status_code == 200
    stored = {i["id"]: i for i in I.load_integrations()}
    assert stored[a]["owner"] == ADMIN and stored[a]["shared"] is True, "shared by its owner, still theirs"


def test_a_member_has_no_list_and_their_tools_see_only_the_shared(two):
    accounts, *_ = two
    assert accounts(MEMBER).get("/api/auth/integrations").status_code == 403
    assert [i["name"] for i in I.integrations_for(MEMBER)] == ["House ntfy"]
    assert [i["name"] for i in I.integrations_for(None)] == ["House ntfy"], "the server's own: the shared"


def test_the_agents_block_and_api_call_are_the_persons_own_and_the_shared(two, monkeypatch):
    _, _, _, a, c = two
    prompt = I.get_integrations_prompt(CYD)
    assert "House ntfy" in prompt and "Ada Gitea" not in prompt and a not in prompt
    assert "Ada Gitea" in I.get_integrations_prompt(ADMIN)

    from src.tools.system import do_api_call
    refused = asyncio.run(do_api_call(json.dumps({"integration": "Ada Gitea", "path": "/"}), owner=CYD))
    assert refused["exit_code"] == 1
    assert refused["error"] == "No integration matching 'Ada Gitea'. Available: House ntfy"

    assert asyncio.run(I.execute_api_call(a, "GET", "/", owner=CYD))["error"] == f"Integration not found: {a}"
    # Found for its owner: it reaches the request stage (refused here by the
    # SSRF guard, standing in for the network).
    import src.url_safety as us
    monkeypatch.setattr(us, "check_outbound_url", lambda url, **kw: (False, "test: no network"))
    assert asyncio.run(I.execute_api_call(a, "GET", "/", owner=ADMIN))["error"] == "URL rejected: test: no network"


def test_a_workflows_list_of_integrations_is_the_persons_own_and_the_shared(two):
    from src.workflow_effects import _integrations
    assert [i["name"] for i in _integrations(CYD)] == ["House ntfy"]
    assert sorted(i["name"] for i in _integrations(ADMIN)) == ["Ada Gitea", "House ntfy"]


def test_todays_entries_become_the_first_admins_shared_once(accounts):
    I.save_integrations([{"id": "old1", "name": "Miniflux", "base_url": "http://rss.lan", "api_key": "k1"},
                         {"id": "old2", "name": "Linkding", "base_url": "http://ld.lan", "api_key": "k2"}])
    assert sorted(i["name"] for i in I.integrations_for(CYD)) == ["Linkding", "Miniflux"], \
        "before the migration they are everyone's, as they were"
    accounts(CYD)                     # the routes' setup runs the migration, as a boot does
    stored = I.load_integrations()
    assert {(i["owner"], i["shared"]) for i in stored} == {(ADMIN, True)}
    assert I.migrate_to_accounts() == 0, "once"
    cyd = accounts(CYD)
    assert {i["read_only"] for i in cyd.get("/api/auth/integrations").json()["integrations"]} == {True}
    ada = accounts(ADMIN)
    assert ada.put("/api/auth/integrations/old1", json={"name": "RSS"}).status_code == 200


def test_nothing_that_answers_a_person_reads_every_account_s_integrations():
    """`Law 13`'s door, kept shut: every reader asks `integrations_for(person)`.
    A call to `load_integrations()` outside `src/integrations.py` is a reader
    that answers somebody with everybody's — parsed, not grepped."""
    offenders = []
    for path in sorted(ROOT.glob("src/**/*.py")) + sorted(ROOT.glob("routes/**/*.py")) + \
            sorted(ROOT.glob("services/**/*.py")) + [ROOT / "app.py"]:
        if path.name == "integrations.py" and path.parent.name == "src":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
                if name == "load_integrations":
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, "read every account's integrations: " + ", ".join(offenders)
