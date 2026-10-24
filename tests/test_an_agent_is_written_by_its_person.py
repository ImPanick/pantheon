# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-20` — *New agent*, *Describe it*, *Customise*: a person's own agents.

One file is the whole agent (`P24-01`), so writing one is writing that file in
the person's own layer (`catalogue.own_root`), checked by the one rule
(`manifest.lint`) before it is kept. A file with a shipped agent's id is that
person's copy — for them only — and *Remove my copy* gives the shipped one back.
*Describe it* asks the model for data, never for a file: what comes back is
spelled into `AGENT.md` by `workshop.render` and checked; one repair round is
given the lint's own sentence.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from src.agents import workshop as W
from src.agents.catalogue import catalogue, get_agent
from src.agents.manifest import ManifestRefused


@pytest.fixture()
def data(tmp_path, monkeypatch):
    import src.constants as constants
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path))
    return tmp_path


def test_the_template_passes_its_own_check():
    assert W.check(W.TEMPLATE).id == "my-agent"


def test_a_new_agent_is_kept_for_its_person_only(data):
    text = W.TEMPLATE.replace("my-agent", "my-watcher")
    m, shadows = W.save("alice", text)
    assert m.id == "my-watcher" and shadows is False
    assert get_agent("alice", "my-watcher").source == "own"
    assert get_agent("bob", "my-watcher") is None, "another person's hall does not have it"
    assert "my-watcher" in {a.id for a in catalogue("alice")[0]}


def test_a_customised_agent_shadows_the_shipped_one_and_removing_it_gives_it_back(data):
    shipped = get_agent("alice", "topic-watcher")
    text = W.source(shipped).replace("version: 1.0.0", "version: 1.1.0")
    m, shadows = W.save("alice", text)
    assert shadows is True
    assert get_agent("alice", "topic-watcher").version == "1.1.0", "the save is read at once, not from the cache"
    assert get_agent("bob", "topic-watcher").version == shipped.version
    W.remove("alice", "topic-watcher")
    assert get_agent("alice", "topic-watcher").source == "shipped"
    with pytest.raises(ManifestRefused, match="nothing of yours"):
        W.remove("alice", "topic-watcher")
    with pytest.raises(ManifestRefused, match="nothing of yours"):
        W.remove("alice", "../../etc")


def test_a_file_that_does_not_pass_is_not_kept(data):
    with pytest.raises(ManifestRefused, match="not a tool Pantheon has"):
        W.save("alice", W.TEMPLATE.replace("tools: [web_search]", "tools: [launch_rockets]"))
    assert get_agent("alice", "my-agent") is None


def _fields(**kw):
    f = {"id": "client-replies", "name": "Client Replies", "tagline": "Drafts replies to client mail.",
         "section": "email", "inputs": [{"key": "account", "kind": "text", "label": "The account"}],
         "triggers": [{"on": "daily", "at": "08:00", "days": "weekdays"}], "tools": ["web_search"],
         "delivers": [{"kind": "answer", "must_contain": ["Drafted"]}],
         "effects": {"brokered_network_read": "allow"}, "budget": {"runs_per_day": 1},
         "memory": "own", "runbook": ["Search the web for the thing you were hired with.",
                                      "Write the answer under the heading Drafted, and stop."]}
    f.update(kw)
    return f


def test_render_spells_every_field_itself_and_the_lint_reads_it_back():
    m = W.check(W.render(_fields(tagline='Says "hi", then: stops.', smuggled="x")))
    assert m.id == "client-replies" and m.tagline == "Says 'hi', then: stops."
    assert m.triggers[0]["days"] == "weekdays" and m.budget["max_steps"] == 20
    assert m.runbook.startswith("1. Search the web")
    assert "smuggled" not in W.render(_fields(smuggled="x")), "a field nothing reads is never written"


def _ask(answers, seen):
    async def fake(owner, messages, *, max_tokens):
        seen.append(messages)
        return answers.pop(0)
    return fake


def test_describe_it_drafts_a_file_that_passes(monkeypatch):
    import src.workflow_assist as wa
    seen = []
    monkeypatch.setattr(wa, "ask_for_json", _ask([(_fields(), None)], seen))
    out = asyncio.run(W.draft("alice", "Draft replies to my clients every weekday."))
    assert out["ok"] is True and W.check(out["text"]).id == "client-replies"
    palette = json.loads(seen[0][1]["content"].split("The palette:\n", 1)[1].split("\n\n", 1)[0])
    assert {"web_search", "create_document"} <= {t["name"] for t in palette["tools"]}


def test_a_draft_that_fails_is_told_why_once_then_handed_to_the_person(monkeypatch):
    import src.workflow_assist as wa
    seen = []
    bad = _fields(tools=["launch_rockets"])
    monkeypatch.setattr(wa, "ask_for_json", _ask([(bad, None), (_fields(), None)], seen))
    assert asyncio.run(W.draft("alice", "x y z"))["ok"] is True
    assert "not a tool Pantheon has" in seen[1][-1]["content"], "the repair round carries the lint's sentence"
    monkeypatch.setattr(wa, "ask_for_json", _ask([(bad, None), (bad, None)], []))
    out = asyncio.run(W.draft("alice", "x y z"))
    assert out["ok"] is False and "launch_rockets" in out["text"] and "does not pass its check yet" in out["sentence"]


def test_describe_it_says_why_when_it_cannot(monkeypatch):
    import src.workflow_assist as wa

    async def none(owner, messages, *, max_tokens):
        raise wa.NoModelSetUp()
    monkeypatch.setattr(wa, "ask_for_json", none)
    assert asyncio.run(W.draft("alice", "anything"))["sentence"] == W.NO_MODEL
    assert asyncio.run(W.draft("alice", "  "))["sentence"] == W.DESCRIBE_EMPTY
    assert asyncio.run(W.draft("alice", "x" * 2001))["sentence"] == W.DESCRIBE_TOO_LONG


# ── over HTTP ───────────────────────────────────────────────────────────────

from tests.test_a_team_is_hired_in_one_go import client  # noqa: E402,F401
from tests.test_a_workflow_is_kept_as_one_document import admins, sched, wf_db  # noqa: E402,F401
from tests.test_a_hire_compiles_to_tasks import call  # noqa: E402


def test_the_routes_keep_check_remove_and_serve_the_template(client):
    text = W.TEMPLATE.replace("my-agent", "alices-agent")
    assert call(client, "POST", "/api/agents/own", json={"text": text, "dry": True}).json()["sentence"] == \
        "It passes its check."
    assert get_agent("alice", "alices-agent") is None, "a dry run keeps nothing"
    res = call(client, "POST", "/api/agents/own", json={"text": text.replace("1.0.0", "x")})
    assert res.status_code == 422 and "is not like 1.0.0" in res.json()["detail"]
    assert call(client, "POST", "/api/agents/own", json={"text": text}).json()["shadows"] is False
    hall = call(client, "GET", "/api/agents").json()
    assert hall["template"] == W.TEMPLATE
    assert {a["id"]: a["source"] for a in hall["agents"]}["alices-agent"] == "own"
    src = call(client, "GET", "/api/agents/alices-agent/source").json()
    assert src["text"].startswith("---\nid: alices-agent") and src["source"] == "own"
    assert call(client, "GET", "/api/agents/alices-agent/source", user="bob").status_code == 404
    assert call(client, "DELETE", "/api/agents/own/alices-agent", user="bob").status_code == 404
    assert call(client, "DELETE", "/api/agents/own/alices-agent").json() == {"ok": True, "back_to_shipped": False}


def test_only_a_person_writes_an_agent(client, monkeypatch):
    import routes.agent_routes as agent_routes
    monkeypatch.setattr(agent_routes, "request_is_a_person", lambda request: False)
    for method, url, body in (("POST", "/api/agents/own", {"text": W.TEMPLATE}),
                              ("DELETE", "/api/agents/own/my-agent", None),
                              ("POST", "/api/agents/draft", {"description": "x"})):
        res = call(client, method, url, json=body)
        assert res.status_code == 403 and res.json()["detail"] == agent_routes.ONLY_A_PERSON, url


def test_describe_it_over_http_says_no_model_as_a_503(client, monkeypatch):
    import src.workflow_assist as wa

    async def none(owner, messages, *, max_tokens):
        raise wa.NoModelSetUp()
    monkeypatch.setattr(wa, "ask_for_json", none)
    res = call(client, "POST", "/api/agents/draft", json={"description": "watch the news"})
    assert res.status_code == 503 and res.json()["detail"] == W.NO_MODEL
