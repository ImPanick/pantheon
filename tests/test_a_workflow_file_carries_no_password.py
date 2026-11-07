# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1872` — a workflow file carries no value a person typed as a password or
a key, wherever on the step they typed it.

`P22-24`'s export blanked one place only — an HTTP step's header values — and
its scan refused just the prefixed shapes `diagnostic_bundle` knows (`sk-`,
`ghp_`, …) and `Bearer …`. Many real APIs take their key in the query string
(`appid`, `api_key`, `key`) or a form field, and people type passwords into a
Set step's field or a Code step's input. **Measured on `5e4c8ec`** (the audit's
probe, reproduced here): a step with query `appid=4f2a…` and `password=hunter2…`
and a Set field `db_password=P@ssw0rd-Prod-2026` exported all three verbatim.

Now, by the NAME a person gave it, a value that looks like a password or a key
leaves the file blank — query, body, a Set field, a Code input, an MCP
argument, and a `name=value` typed into an HTTP path's query — unless it is a
reference (`{{ … }}`), which carries no secret. The import says each one is
needed, as it does a header's. And a long run of mixed letters and digits
typed as such a value under any other name refuses the export, naming the step
and the field, as the prefixed shapes always did.

Mistake prevention, not a control (`Law 17`): the person typed it, and the
person is the one about to hand the file to someone.

Real (`Law 20`): the workflow routes over an ASGI client on a real SQLite file,
the store, the rule and `workflow_share`.
"""

import json

import pytest

from src import workflow_store as store
from tests.helpers.assist_harness import PERSON, build_world, marks_of
from tests.helpers.walker_harness import client_for

pytestmark = pytest.mark.asyncio

APPID = "4f2a9c8e1b7d6a5f3e2c1b0a9d8e7f6a"
QUERY_PASSWORD = "hunter2hunter2"
DB_PASSWORD = "P@ssw0rd-Prod-2026"
BODY_KEY = "body-key-0451-zz"
CODE_TOKEN = "code-token-value-77"
PATH_KEY = "path-key-in-the-url-9"
SECRETS = (APPID, QUERY_PASSWORD, DB_PASSWORD, BODY_KEY, CODE_TOKEN, PATH_KEY)

FEEDS = {"id": "intg-weather", "name": "Weather", "enabled": True,
         "base_url": "http://weather.lan", "auth_type": "none", "api_key": "",
         "auth_header": "", "auth_param": "", "description": "", "preset": ""}

NODES = [
    {"id": "get", "kind": "http", "label": "Get forecast",
     "config": {"integration": "intg-weather", "method": "POST",
                "path": f"/data/2.5/weather?key={PATH_KEY}&units=metric",
                "query": [{"name": "appid", "value": APPID},
                          {"name": "password", "value": QUERY_PASSWORD},
                          {"name": "q", "value": "London"},
                          {"name": "max_tokens", "value": 500}],
                "body": [{"name": "api_key", "value": BODY_KEY},
                         {"name": "author", "value": "Ana"}]}},
    {"id": "set", "kind": "set", "label": "Remember the login",
     "config": {"fields": [{"name": "db_password", "value": DB_PASSWORD},
                           {"name": "sort_key", "value": "name"},
                           {"name": "city", "value": "London"}]}},
    {"id": "code", "kind": "code", "label": "Count",
     "config": {"language": "python", "source": "print(1)",
                "input": [{"name": "token", "value": CODE_TOKEN},
                          {"name": "forecast", "value": "{{ steps.get.text }}"}]}},
]
EDGES = [{"from": "get", "port": "success", "to": "set"},
         {"from": "set", "port": "success", "to": "code"}]


def _world(monkeypatch, tmp_path, name):
    return build_world(monkeypatch, tmp_path, name=name, integrations=[FEEDS], workstation=True)


async def _made(w, nodes=NODES, edges=EDGES):
    db = w.factory()
    try:
        wf, _trigger, _ = store.create_from_document(
            db, owner="alice", name="Weather digest",
            graph={"v": 1, "nodes": json.loads(json.dumps(nodes)), "edges": list(edges)},
            trigger_fields={"trigger_type": "webhook"}, origin="drafted")
        return wf.id
    finally:
        db.close()


async def _export(w, wf_id):
    async with client_for(w.app) as client:
        return await client.get(f"/api/workflows/{wf_id}/export", headers=PERSON)


async def test_a_value_named_like_a_password_or_a_key_leaves_the_file_blank(monkeypatch, tmp_path):
    w = _world(monkeypatch, tmp_path, "out.db")
    res = await _export(w, await _made(w))
    assert res.status_code == 200, res.text
    for secret in SECRETS:
        assert secret not in res.text, secret
    by_id = {n["id"]: n["config"] for n in json.loads(res.text)["graph"]["nodes"]}
    assert by_id["get"]["query"] == [{"name": "appid", "value": ""},
                                     {"name": "password", "value": ""},
                                     {"name": "q", "value": "London"},
                                     {"name": "max_tokens", "value": 500}]
    assert by_id["get"]["body"] == [{"name": "api_key", "value": ""},
                                    {"name": "author", "value": "Ana"}]
    assert by_id["get"]["path"] == "/data/2.5/weather?key=&units=metric"
    assert by_id["set"]["fields"] == [{"name": "db_password", "value": ""},
                                      {"name": "sort_key", "value": "name"},
                                      {"name": "city", "value": "London"}]
    # A reference carries no secret: it is kept, whatever its name.
    assert by_id["code"]["input"] == [{"name": "token", "value": ""},
                                      {"name": "forecast", "value": "{{ steps.get.text }}"}]


async def test_the_import_says_each_blank_value_is_needed(monkeypatch, tmp_path):
    w = _world(monkeypatch, tmp_path, "round.db")
    data = json.loads((await _export(w, await _made(w))).text)
    async with client_for(w.app) as client:
        res = await client.post("/api/workflows", headers=PERSON, json={"file": data})
    assert res.status_code == 200, res.text
    body = res.json()
    marks = marks_of(body["workflow"]["graph"])
    assert marks["get"]["needs"] == [
        {"field": "path", "name": "key"},
        {"field": "query[0].value", "name": "appid"},
        {"field": "query[1].value", "name": "password"},
        {"field": "body[0].value", "name": "api_key"}]
    assert marks["set"]["needs"] == [{"field": "fields[0].value", "name": "db_password"}]
    assert marks["code"]["needs"] == [{"field": "input[0].value", "name": "token"}]
    said = [m for m in body["missing"] if "looks like a password or a key" in m]
    assert said == [
        "“Get forecast”: “key” looks like a password or a key, and a file never carries its "
        "value. Type it on the step.",
        "“Get forecast”: “appid” looks like a password or a key, and a file never carries its "
        "value. Type it on the step.",
        "“Get forecast”: “password” looks like a password or a key, and a file never carries "
        "its value. Type it on the step.",
        "“Get forecast”: “api_key” looks like a password or a key, and a file never carries "
        "its value. Type it on the step.",
        "“Remember the login”: “db_password” looks like a password or a key, and a file never "
        "carries its value. Type it on the step.",
        "“Count”: “token” looks like a password or a key, and a file never carries its value. "
        "Type it on the step."]


async def test_a_long_run_of_letters_and_digits_under_another_name_refuses_and_says_where(
        monkeypatch, tmp_path):
    w = _world(monkeypatch, tmp_path, "opaque.db")
    nodes = json.loads(json.dumps(NODES))
    nodes[1]["config"]["fields"][2]["value"] = "Zq8vR2kT9mWx4LpN7bYc3HdF6sJg1QaE"
    res = await _export(w, await _made(w, nodes))
    assert res.status_code == 400, res.text
    body = res.json()
    assert body["reason"] == "secret_shape" and body["node_ids"] == ["set"]
    assert body["field"] == "fields[2].value"
    assert body["detail"].startswith("“Remember the login”, Field “city”, holds something "
                                     "that looks like a key or a token")
    assert "Zq8vR2kT" not in body["detail"]
    # Words, a date, a UUID-shaped id and a long plain number are not keys.
    for ordinary in ("summary_2024_report_for_the_whole_team", "2026-11-07T08:00:00Z",
                     "0c5ca534-0f00-434a-871a-7caa1e0de6cf", "12345678901234567890123456"):
        nodes[1]["config"]["fields"][2]["value"] = ordinary
        w2 = _world(monkeypatch, tmp_path, f"ok-{abs(hash(ordinary))}.db")
        ok = await _export(w2, await _made(w2, nodes))
        assert ok.status_code == 200, (ordinary, ok.text)
