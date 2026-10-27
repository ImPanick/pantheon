# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1582` — the workflow palette offers a workstation member the HTTP steps the dispatcher runs.

`B1573` lifted `api_call` for a member whose tools run in their workstation: the
dispatcher (`tool_execution._lifted_for`) lets it through, and `do_api_call`
finds that member's own connections (`integrations.agent_integrations_for`).
`workflow_effects._reaches` asked only the non-admin blocklist, so the palette
greyed *HTTP request* with *Only an admin's agent can send HTTP requests* and
listed no Integration, and `workflow_resources` held none for `validate_document`
— while the dispatcher would have run the step. And `_integrations` read
`integrations_for`, so the shared connections a member may see but whose key
must never reach their workstation would have been offered as steps the
dispatcher then cannot find.

Driven (`Law 20`) in the palette's world (`tests/test_the_palette_offers_what_the_agent_reaches.py`:
the real auth manager, the real workstation settings and integration store
seam), with the member given the real `can_use_workstation` privilege; the
dispatcher is the real `execute_tool_block` down to `execute_api_call`, which is
recorded rather than sent (its trip to the workstation is `B1573`'s test).
"""
import asyncio
import json

import pytest

import src.tool_execution as te
from src import integrations as integrations_mod
from src import workflow_effects as fx
from src.agent_tools import ToolBlock
from test_the_palette_offers_what_the_agent_reaches import world  # noqa: F401

SHARED = {"id": "intg-shared", "name": "Miniflux", "enabled": True, "base_url": "http://feeds.lan",
          "api_key": "shared-key", "preset": "miniflux", "description": "everyone's"}
BOBS = {"id": "intg-bob", "name": "Bob's Gitea", "enabled": True, "base_url": "http://git.lan",
        "api_key": "bob-key", "preset": "gitea", "description": "mine", "owner": "bob"}
CATS = {"id": "intg-cat", "name": "Cat's", "enabled": True, "base_url": "http://cat.lan",
        "api_key": "cat-key", "preset": "", "description": "", "owner": "cat"}


@pytest.fixture
def member(world, monkeypatch):  # noqa: F811
    """`bob`, a member whose tools run in his workstation (`B1573`)."""
    import core.auth
    assert core.auth._SHARED_AUTH_MANAGER.set_privileges("bob", {"can_use_workstation": True})
    monkeypatch.setattr(integrations_mod, "load_integrations", lambda: [SHARED, BOBS, CATS])
    sent = []

    async def recorded(integration_id, method, path, params=None, body=None,
                       extra_headers=None, structured=False, *, owner=None):
        sent.append({"integration": integration_id, "owner": owner, "path": path})
        return {"output": "{}", "exit_code": 0, "http_status": 200, "body_json": {}}

    monkeypatch.setattr(integrations_mod, "execute_api_call", recorded)
    return sent


def _dispatch(integration: str):
    _desc, result = asyncio.run(te.execute_tool_block(
        ToolBlock("api_call", json.dumps({"integration": integration, "method": "GET",
                                          "path": "/api/v1/version", "structured": True})),
        session_id=None, owner="bob", security_context=te.NO_TOOL_SECURITY_CONTEXT))
    return result


def test_the_palette_and_the_dispatcher_agree_for_a_workstation_member(member):
    """The row's `Verify:`."""
    from src.agent_tools.workstation_tools import lifted_tools
    assert "api_call" in lifted_tools("bob"), "the premise: B1573 lifts api_call for bob"

    palette = fx.build_palette("bob")
    http = {k["kind"]: k for k in palette["kinds"]}["http"]
    assert (http["available"], http["why"]) == (True, ""), http
    offered = [i["id"] for i in palette["integrations"]]
    assert offered == ["intg-bob"], offered
    assert set(fx.workflow_resources("bob").integrations) == {"intg-bob"}

    # Each one the palette offers, the dispatcher runs for him...
    for integration in offered:
        result = _dispatch(integration)
        assert result.get("exit_code") == 0, result
    assert member == [{"integration": "intg-bob", "owner": "bob", "path": "/api/v1/version"}]
    # ...and the ones it does not offer, the dispatcher does not find.
    for integration in ("intg-shared", "intg-cat"):
        result = _dispatch(integration)
        assert "No integration matching" in result.get("error", ""), result
    assert len(member) == 1


def test_a_member_with_no_connection_of_their_own_is_told_to_add_one(member, monkeypatch):
    monkeypatch.setattr(integrations_mod, "load_integrations", lambda: [SHARED])
    http = {k["kind"]: k for k in fx.build_palette("bob")["kinds"]}["http"]
    assert (http["available"], http["why"]) == (False, fx.NO_OWN_INTEGRATIONS_SENTENCE)


def test_a_member_without_the_workstation_is_still_refused_both(member):
    import core.auth
    assert core.auth._SHARED_AUTH_MANAGER.set_privileges("bob", {"can_use_workstation": False})
    http = {k["kind"]: k for k in fx.build_palette("bob")["kinds"]}["http"]
    assert (http["available"], http["why"]) == (False, fx._ADMIN_ONLY_WHY["http"])
    result = _dispatch("intg-bob")
    assert result.get("exit_code") == 1 and result.get("error"), result
    assert member == [], "the dispatcher refused it too"


def test_an_admin_is_offered_the_shared_ones_as_before(member):
    from tests.helpers.signed_in import ADMIN
    offered = [i["id"] for i in fx.build_palette(ADMIN)["integrations"]]
    assert offered == ["intg-shared"], offered
