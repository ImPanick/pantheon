# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1884` (`identifiers-cannot-be-mapped`) — a setting that picks WHICH thing
a step acts on (a ticket's id, an HTTP path, a Wait's time) may be opened by
its author to a value from an earlier step; one that picks who receives the
work, where it goes, a host, a command or a key never may.

**Measured before the fix:** every such setting was `never` — `ticket_id`,
`issue_number` and an HTTP path are not words a person reads, so
`classify_argument` said so, and nothing else could say otherwise. "Close the
ticket the webhook names" could not be built: a reference in `issue_id` was
refused at save ("A setting only you can fill reads from another step"), and
there was no way to say "I mean it".

**The adversary (`Law 17`)** is whoever can send the webhook or the mail —
and, through a model's output, whoever steered it. What they may now choose
is which ticket, which item, which day. Held here:

  * their text can never pick a recipient or a host: ticking `to`, `channel`,
    `chat_id`, `recipients`, `url`, `host`, `repo`, `calendar_id`, `api_key`,
    `command` … open is refused at save on that field, with why, and a
    document written straight to the database still sends nothing;
  * a value written into an opened path is one piece of it: never `/`, `?`,
    `#`, `..` or a new host; and the path's first part stays typed;
  * a destructive tool's argument filled from the webhook does not run
    without the rung: the call is built tainted, so at the DEFAULT rung the
    step parks on a card showing the exact call, Allow runs exactly that call
    once, and the same answer again is refused;
  * a draft the model writes never opens a setting.

Driven (`Law 20`): the real `workflow_slots`, `validate_document`,
`authored_call_context` and `decision_for`, the real palette, the real
classify door, and the real walker and dispatcher (`execute_tool_block`) with
an MCP manager that records.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src import workflow_document as wd
from src import workflow_slots as ws
from src.event_bus import TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS, build_trigger
from src.tool_approvals import tool_approval_store
from tests.helpers.walker_harness import (
    app_for, client_for, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow,
    settle,
)

DELETE = "mcp__tracker__delete_issue"
TRACKER_SCHEMA = {"type": "object", "required": ["issue_id"], "properties": {
    "issue_id": {"type": "string", "description": "The issue to delete."},
    "issue_number": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
    "due_date": {"type": "string", "format": "date"},
    "reason": {"type": "string"},
    # Who or where: never opened, whatever the author ticks.
    "to": {"type": "string"}, "cc": {"type": "string"}, "recipients": {"type": "string"},
    "chat_id": {"type": "integer"}, "channel": {"type": "string"}, "assignee": {"type": "string"},
    "reply_to": {"type": "string"}, "webhook_url": {"type": "string"}, "host": {"type": "string"},
    "base_url": {"type": "string"}, "server": {"type": "string"}, "repo": {"type": "string"},
    "owner": {"type": "string"}, "calendar_id": {"type": "string"}, "api_key": {"type": "string"},
    "token": {"type": "string"}, "command": {"type": "string"}, "sql": {"type": "string"},
    "path": {"type": "string"}, "file": {"type": "string"}, "role": {"type": "string"},
    "force": {"type": "string"},
    # Not one value, an address, or a choice.
    "ticket_ref": {"type": "string", "format": "email"},
    "issue_ref": {"type": "string", "format": "uri"},
    "labels": {"type": "array"}, "fields": {"type": "object"},
    "state": {"type": "string", "enum": ["open", "closed"]}, "silent": {"type": "boolean"},
}}
RES = wd.WorkflowResources(
    integrations={"tracker": {"name": "Tracker", "enabled": True}},
    mcp_tools={DELETE: {"input_schema": TRACKER_SCHEMA, "disabled": False, "is_readonly": False}},
    skills=frozenset(), ai_tools=frozenset(), workstation_why=None)
FROM_WEBHOOK = "{{ steps.start.data.body }}"
CTX = {"steps": {"start": {"data": {"body": "1234"}}}}


def _mcp(args, filled=None, node_id="del", label="Delete it"):
    config = {"tool": DELETE, "args": args}
    if filled is not None:
        config["filled"] = filled
    return {"id": node_id, "kind": "mcp", "label": label, "config": config,
            "position": None, "pinned": None}


def _http(filled=None, **config):
    config = {"integration": "tracker", "method": "DELETE", **config}
    if filled is not None:
        config["filled"] = filled
    return {"id": "call", "kind": "http", "label": "Call it", "config": config,
            "position": None, "pinned": None}


def _checked(*nodes):
    graph = wd.parse_graph({"v": 1, "nodes": list(nodes), "edges": []})
    return wd.validate_document(graph, owner="alice", tasks_by_id={}, crew_ids=set(),
                                owner_is_admin=True, own_task_id="trigger", resources=RES)


# ── the rule: what may be opened, and what never may ────────────────────────

def test_an_identifier_its_author_opens_takes_the_webhooks_value():
    step = _mcp({"issue_id": FROM_WEBHOOK, "reason": "Asked by the sender."}, ["args.issue_id"])
    assert ws.slot_for(step, ("args", "issue_id"), mcp_schema=TRACKER_SCHEMA) == ws.OPENED_INLINE
    assert _checked(step) is None
    call = ws.render_call(step, CTX, mcp_schema=TRACKER_SCHEMA)
    assert json.loads(call.content) == {"issue_id": "1234", "reason": "Asked by the sender."}
    assert call.opened == ("args.issue_id",), "the opened setting a reference filled is named"


def test_without_the_tick_the_same_reference_is_still_refused_on_its_field():
    refusal = _checked(_mcp({"issue_id": FROM_WEBHOOK}))
    assert refusal.reason == wd.REFUSE_MAPPED_NEVER and refusal.field == "args.issue_id"
    assert refusal.sentence.endswith(ws.WHY_NOT_TEXT)


@pytest.mark.parametrize("name", [
    "to", "cc", "recipients", "chat_id", "channel", "assignee", "reply_to", "webhook_url", "host",
    "base_url", "server", "repo", "owner", "calendar_id", "api_key", "token", "command", "sql",
    "path", "file", "role", "force",
])
def test_the_senders_text_can_never_pick_a_recipient_or_a_host_even_when_ticked(name):
    step = _mcp({"issue_id": "1", name: FROM_WEBHOOK}, [f"args.{name}"])
    refusal = _checked(step)
    assert refusal is not None and refusal.reason == wd.REFUSE_MAPPED_NEVER
    assert refusal.field == f"args.{name}"
    assert refusal.sentence == ("A setting only you can fill reads from another step: "
                                f"“Delete it”, “{name}”, cannot be filled from an earlier step. "
                                f"{ws.OPEN_CLOSED_NAME}")
    assert ws.slot_for(step, ("args", name), mcp_schema=TRACKER_SCHEMA).mapping == ws.MAPPING_NEVER
    # Written straight to the database, past the rule: nothing is built.
    with pytest.raises(ws.SlotError):
        ws.render_call(step, {"steps": {"start": {"data": {"body": "x@evil.example"}}}},
                       mcp_schema=TRACKER_SCHEMA)


@pytest.mark.parametrize("name, why", [
    ("ticket_ref", ws.OPEN_FORMAT), ("issue_ref", ws.OPEN_FORMAT),
    ("labels", ws.OPEN_NOT_ONE_VALUE), ("fields", ws.OPEN_NOT_ONE_VALUE),
    ("state", ws.OPEN_CHOICE), ("silent", ws.OPEN_CHOICE), ("no_such_argument", ws.OPEN_UNKNOWN),
])
def test_an_address_a_list_an_object_or_a_choice_never_opens(name, why):
    refusal = _checked(_mcp({"issue_id": "1", name: FROM_WEBHOOK}, [f"args.{name}"]))
    assert refusal.field == f"args.{name}" and refusal.sentence.endswith(why)


def test_a_key_is_open_where_it_names_the_thing_and_closed_where_it_is_a_credential():
    assert ws.argument_opening_problem("issue_key", {"type": "string"}) is None
    assert ws.argument_opening_problem("project_key", {"type": "string"}) == ws.OPEN_CLOSED_NAME
    for name in ("key", "api_key", "apiKey", "private_key", "access_key", "keys"):
        assert ws.argument_opening_problem(name, {"type": "string"}) == ws.OPEN_CLOSED_NAME, name
    for name in ("ticket_id", "issueNumber", "order_id", "query", "page", "due_date", "message_id"):
        assert ws.argument_opening_problem(name, {"type": "string"}) is None, name


def test_an_optional_number_and_a_date_open_and_are_coerced():
    step = _mcp({"issue_id": "1", "issue_number": "{{ steps.start.data.n }}",
                 "due_date": "{{ steps.start.data.d }}"}, ["args.issue_number", "args.due_date"])
    assert _checked(step) is None
    call = ws.render_call(step, {"steps": {"start": {"data": {"n": "42", "d": "2026-11-09"}}}},
                          mcp_schema=TRACKER_SCHEMA)
    assert json.loads(call.content) == {"issue_id": "1", "issue_number": 42, "due_date": "2026-11-09"}
    with pytest.raises(ws.SlotError):
        ws.render_call(step, {"steps": {"start": {"data": {"n": "forty", "d": "x"}}}},
                       mcp_schema=TRACKER_SCHEMA)


def test_only_a_setting_that_picks_the_thing_may_be_ticked_and_each_only_once():
    for filled, field in [(["tool"], "tool"), (["args"], "args")]:
        refusal = _checked(_mcp({"issue_id": "1"}, filled))
        assert refusal.field == field and refusal.sentence.endswith(ws.OPEN_NOT_HERE), filled
    for bad in (["args.issue_id", "args.issue_id"], ["args..x"], "args.issue_id", [7]):
        refusal = _checked(_mcp({"issue_id": "1"}, bad))
        assert refusal.reason == wd.REFUSE_BAD_SETTING, bad
    refusal = _checked(_http(["integration"], path="/x"))
    assert refusal.field == "integration" and refusal.sentence.endswith(ws.OPEN_NOT_HERE)
    refusal = _checked(_http(["query[3].value"], path="/x", query=[{"name": "id", "value": "1"}]))
    assert refusal.field == "query[3].value" and refusal.sentence.endswith(ws.OPEN_NO_ENTRY)


def test_an_http_query_or_body_value_opens_by_its_name_and_type():
    step = _http(["query[0].value", "body[0].value"], method="POST", path="/v1/issues",
                 query=[{"name": "ticket_id", "value": FROM_WEBHOOK}],
                 body=[{"name": "priority", "value": "{{ steps.start.data.p }}", "type": "number"}])
    assert _checked(step) is None
    call = ws.render_call(step, {"steps": {"start": {"data": {"body": "T-9", "p": "4"}}}})
    sent = json.loads(call.content)
    assert sent["params"] == {"ticket_id": "T-9"} and sent["body"] == {"priority": 4}
    assert call.opened == ("query[0].value", "body[0].value")
    for entry, why in [({"name": "to", "value": FROM_WEBHOOK}, ws.OPEN_CLOSED_NAME),
                       ({"name": "url", "value": FROM_WEBHOOK}, ws.OPEN_CLOSED_NAME),
                       ({"name": "items", "value": FROM_WEBHOOK, "type": "json"}, ws.OPEN_NOT_ONE_VALUE)]:
        refusal = _checked(_http(["body[0].value"], method="POST", path="/x", body=[entry]))
        assert refusal.field == "body[0].value" and refusal.sentence.endswith(why), entry


# ── an opened path ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, path", [
    ("1234", "/items/1234/close"),
    ("../admin", "/items/..%2Fadmin/close"),
    ("a/b?c=d#e", "/items/a%2Fb%3Fc%3Dd%23e/close"),
    ("http://evil.example", "/items/http%3A%2F%2Fevil.example/close"),
    ("%2e%2e", "/items/%252e%252e/close"),
    ("x y", "/items/x%20y/close"),
    (42, "/items/42/close"),
])
def test_a_value_in_an_opened_path_is_one_piece_of_it(value, path):
    step = _http(["path"], path="/items/" + FROM_WEBHOOK + "/close")
    assert _checked(step) is None
    call = ws.render_call(step, {"steps": {"start": {"data": {"body": value}}}})
    assert json.loads(call.content)["path"] == path
    assert call.opened == ("path",)


@pytest.mark.parametrize("value", ["..", ".", "", " ", None, ["a"], {"a": 1}, "x" * 1001])
def test_a_value_that_would_change_which_address_is_called_sends_nothing(value):
    step = _http(["path"], path="/items/" + FROM_WEBHOOK)
    with pytest.raises(ws.SlotError) as refused:
        ws.render_call(step, {"steps": {"start": {"data": {"body": value}}}})
    assert refused.value.field == "path"
    # Refused for what it was handed — the path is open, so a reference in it
    # is not itself the reason.
    assert "only takes what you typed" not in refused.value.sentence
    assert "{{ steps.start.data.body }}" in refused.value.sentence


@pytest.mark.parametrize("path", [
    "/" + FROM_WEBHOOK, "/" + FROM_WEBHOOK + "/close", "/items" + FROM_WEBHOOK, FROM_WEBHOOK,
])
def test_an_opened_paths_first_part_stays_typed(path):
    refusal = _checked(_http(["path"], path=path))
    assert refusal is not None and refusal.field == "path"
    if path.startswith("/"):
        assert refusal.sentence == ("A step has a setting it does not take: "
                                    f"“Call it”: {ws.OPEN_PATH_HEAD}")
        with pytest.raises(ws.SlotError):
            ws.render_call(_http(["path"], path=path), CTX)


def test_an_unopened_path_still_refuses_a_reference():
    refusal = _checked(_http(path="/items/" + FROM_WEBHOOK))
    assert refusal.reason == wd.REFUSE_MAPPED_NEVER and refusal.field == "path"


# ── the rung ─────────────────────────────────────────────────────────────────

def test_a_filled_opened_setting_builds_the_call_tainted_so_the_default_rung_asks():
    from src.tool_capabilities import (
        DEFAULT_TRUST_RUNG, TAINT_KIND_CONTEXT, authored_call_context,
    )
    step = _mcp({"issue_id": FROM_WEBHOOK}, ["args.issue_id"])
    filled = ws.render_call(step, CTX, mcp_schema=TRACKER_SCHEMA)
    ctx = authored_call_context(filled, rung=DEFAULT_TRUST_RUNG, run_id="r:del")
    assert ctx.external_untrusted_context_seen is True
    assert ctx.taint_trail == [{"kind": TAINT_KIND_CONTEXT, "source": (
        "a value from an earlier step, in a setting the workflow's author opened: args.issue_id")}]
    decision = ctx.decision_for(filled.tool, filled.content)
    assert decision.allowed is False, "a tool that may delete asks before the sender's id is used"

    typed = ws.render_call(_mcp({"issue_id": "1234"}, ["args.issue_id"]), CTX,
                           mcp_schema=TRACKER_SCHEMA)
    assert typed.opened == ()
    clean = authored_call_context(typed, rung=DEFAULT_TRUST_RUNG, run_id="r:del")
    assert clean.external_untrusted_context_seen is False
    assert clean.decision_for(typed.tool, typed.content).allowed is True, \
        "what the author typed runs as it always did"


# ── what a person reads ──────────────────────────────────────────────────────

def test_the_plan_and_the_dry_run_say_what_is_open_and_what_that_means():
    step = _mcp({"issue_id": FROM_WEBHOOK, "reason": "x"}, ["args.issue_id"])
    lines = wd.plan_lines(step, RES)
    assert lines[-1] == ("Filled from an earlier step, because you chose it: “issue_id”. "
                         "A webhook or a mail may have written that value, so whenever an earlier "
                         "step fills it, this step asks you first wherever your approval setting "
                         "asks once outside text has been read.")
    assert f"issue_id: {FROM_WEBHOOK}" in lines
    [where] = wd.destination_lines({"nodes": [step]}, RES)
    assert f"issue_id: {FROM_WEBHOOK} (filled from an earlier step)" in where
    http = _http(["path"], path="/items/" + FROM_WEBHOOK)
    assert wd.plan_lines(http, RES)[-1].startswith("Filled from an earlier step, because you chose "
                                                   "it: Path. ")
    assert "(its path filled from an earlier step)" in wd.destination_lines({"nodes": [http]}, RES)[0]
    wait = {"id": "w", "kind": "wait", "label": "Hold", "config": {
        "mode": "until", "time": "{{ steps.start.data.when }}", "filled": ["time"]}}
    assert wd.plan_lines(wait, RES)[-1] == (
        "Its time is filled from an earlier step, because you chose it: a time of day (HH:MM) or "
        f"a date and time, at most {RES.wait_max_hours} hours away.")


def test_the_palette_and_the_door_say_what_may_be_opened():
    from routes.workflow.workflow_routes import field_slot_answer
    from src import workflow_effects as fx
    entry = fx._mcp_tool_entry({"qualified_name": DELETE, "name": "delete_issue",
                                "input_schema": TRACKER_SCHEMA})
    assert entry["args"]["issue_id"] == {"mapping": "never", "why": ws.WHY_NOT_TEXT, "openable": True}
    for name in ("to", "channel", "chat_id", "host", "labels", "state", "ticket_ref"):
        assert "openable" not in entry["args"][name], name
    assert entry["args"]["reason"] == {"mapping": "never", "why": ws.WHY_NOT_TEXT, "openable": True}
    assert fx._kind_slots("http")["path"]["openable"] is True
    assert fx._kind_slots("wait")["time"]["openable"] is True
    assert "openable" not in fx._kind_slots("http")["integration"]

    def door(name, type_=None):
        entry = {"name": name, "value": ""} if type_ is None else {"name": name, "value": "", "type": type_}
        return field_slot_answer({"node": {"kind": "http", "config": {"query": [entry]}},
                                  "field": "query[0].value"})
    assert door("ticket_id") == {"mapping": "never", "why": ws.WHY_NOT_TEXT, "openable": True}
    assert door("to") == {"mapping": "never", "why": ws.WHY_NOT_TEXT}
    assert door("text") == {"mapping": "value", "why": ""}


def test_a_draft_never_opens_a_setting():
    from src.workflow_assist import _drafted_config
    notes = []
    out = _drafted_config("mcp", {"tool": DELETE, "args": {"issue_id": FROM_WEBHOOK},
                                  "filled": ["args.issue_id"]}, "Delete it", notes)
    assert "filled" not in out and out["args"] == {"issue_id": FROM_WEBHOOK}
    assert notes == ["“Delete it”: filled was left out — a draft does not set it."]


def test_a_wait_until_a_time_from_an_earlier_step_is_checked_when_it_is_reached():
    wait = {"id": "w", "kind": "wait", "label": "Hold", "position": None, "pinned": None,
            "config": {"mode": "until", "time": "{{ steps.start.data.when }}", "filled": ["time"]}}
    assert _checked(wait) is None
    unticked = json.loads(json.dumps(wait))
    del unticked["config"]["filled"]
    assert _checked(unticked).reason == wd.REFUSE_MAPPED_NEVER
    for_a_while = json.loads(json.dumps(wait))
    for_a_while["config"] = {"mode": "for", "minutes": 5, "filled": ["time"]}
    refusal = _checked(for_a_while)
    assert refusal.field == "time" and refusal.sentence.endswith(ws.OPEN_WAIT_FOR)


# ── through the real walker and dispatcher ───────────────────────────────────

@pytest.fixture()
def tracker(monkeypatch, tmp_path):
    """The far end: an MCP server whose one tool deletes an issue, and records
    each call. Only alice is an admin, as in `test_a_step_you_configured_runs`."""
    import src.agent_tools as agent_tools
    import src.task_scheduler as ts
    import src.tool_execution as tool_execution
    import src.tool_security as tool_security

    factory = make_db(monkeypatch, tmp_path / "opened.db")
    tool_approval_store._pending.clear()
    deleted = []

    class Tracker:
        def get_all_tools(self, disabled_map=None, overrides=None):
            return [{"qualified_name": DELETE, "server_name": "tracker", "name": "delete_issue",
                     "description": "Delete an issue.", "input_schema": TRACKER_SCHEMA,
                     "is_disabled": False, "is_readonly": False}]

        async def call_tool(self, name, args):
            deleted.append((name, dict(args)))
            return {"stdout": "deleted", "stderr": "", "exit_code": 0}

    monkeypatch.setattr(agent_tools, "get_mcp_manager", lambda: Tracker(), raising=False)
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: owner == "alice")
    monkeypatch.setattr(tool_security, "owner_is_admin", lambda owner: owner == "alice")
    monkeypatch.setattr(ts, "owner_has_admin_task_privileges", lambda owner: owner == "alice")
    s = recording_scheduler()

    class World:
        pass
    w = World()
    w.factory, w.deleted, w.s = factory, deleted, s
    w.app = app_for(factory, s, monkeypatch)
    return w


def _webhook(body):
    return build_trigger(TRIGGER_SOURCE_WEBHOOK, "webhook", {"body": body},
                         fields=WEBHOOK_PAYLOAD_FIELDS)


@pytest.mark.asyncio
async def test_the_webhooks_issue_is_deleted_only_after_allow_and_exactly_once(tracker):
    """At the DEFAULT rung — the one most people never change — a delete whose
    issue id the sender wrote parks on a card showing the exact call; Allow
    runs exactly that call, once; the same answer again is refused."""
    w = tracker
    seed_workflow(w.factory, [node("del", "Delete it", "mcp", tool=DELETE,
                                   args={"issue_id": FROM_WEBHOOK}, filled=["args.issue_id"])],
                  trigger_type="webhook", owner="alice")
    await w.s._execute_task("wf", trigger=_webhook("1234"))
    [run] = runs_of(w.factory, "wf")
    assert run["status"] == "waiting" and w.deleted == [], "nothing deleted without the person"
    rec = records_of(w.factory, run["id"])[0]
    card = rec["waiting"]["approval"]
    assert json.loads(card["action"]["content"]) == {"issue_id": "1234"}
    pending = tool_approval_store.peek(card["approval_id"])
    assert pending.external_untrusted_context_seen is True
    assert any("args.issue_id" in entry["source"] for entry in pending.taint_trail)

    url = f"/api/workflows/w-wf/runs/{run['id']}/answer"
    async with client_for(w.app) as client:
        res = await client.post(url, headers={"x-test-user": "alice"},
                                json={"node_id": "del", "approval_id": card["approval_id"],
                                      "decision": "approve_task"})
        assert res.status_code == 200 and res.json()["outcome"] == "resumed", res.text
        await settle(w.s)
        assert w.deleted == [(DELETE, {"issue_id": "1234"})]
        assert runs_of(w.factory, "wf")[0]["status"] == "success"
        again = await client.post(url, headers={"x-test-user": "alice"},
                                  json={"node_id": "del", "approval_id": card["approval_id"],
                                        "decision": "approve_task"})
        assert again.status_code == 409
    assert len(w.deleted) == 1


@pytest.mark.asyncio
async def test_a_typed_id_in_an_opened_setting_runs_without_a_card(tracker):
    w = tracker
    seed_workflow(w.factory, [node("del", "Delete it", "mcp", tool=DELETE,
                                   args={"issue_id": "1234"}, filled=["args.issue_id"])],
                  trigger_type="webhook", owner="alice")
    await w.s._execute_task("wf", trigger=_webhook('{"issue_id": "9999"}'))
    [run] = runs_of(w.factory, "wf")
    assert run["status"] == "success", run
    assert w.deleted == [(DELETE, {"issue_id": "1234"})]
    assert not tool_approval_store._pending, "no card"


@pytest.mark.asyncio
async def test_a_recipient_ticked_open_runs_nothing_whatever_the_sender_wrote(tracker):
    w = tracker
    seed_workflow(w.factory, [node("del", "Delete it", "mcp", tool=DELETE,
                                   args={"issue_id": "1", "to": FROM_WEBHOOK}, filled=["args.to"])],
                  trigger_type="webhook", owner="alice")
    await w.s._execute_task("wf", trigger=_webhook("attacker@evil.example"))
    [run] = runs_of(w.factory, "wf")
    assert run["status"] == "error" and "“to”, cannot be filled from an earlier step" in run["result"]
    assert w.deleted == [] and not tool_approval_store._pending


@pytest.mark.asyncio
async def test_a_wait_waits_until_the_time_the_webhook_gave(monkeypatch, tmp_path):
    factory = make_db(monkeypatch, tmp_path / "wait.db")
    when = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(microsecond=0)
    seed_workflow(factory, [node("w", "Until then", "wait", mode="until",
                                 time="{{ steps.start.data.body }}", filled=["time"])],
                  trigger_type="webhook")
    s = recording_scheduler()
    await s._execute_task("wf", trigger=_webhook(when.isoformat().replace("+00:00", "Z")))
    [run] = runs_of(factory, "wf")
    rec = records_of(factory, run["id"])[0]
    assert run["status"] == "waiting" and rec["waiting"]["kind"] == "time", run
    until = datetime.fromisoformat(rec["waiting"]["until"].rstrip("Z")).replace(tzinfo=timezone.utc)
    assert until == when

    seed_workflow(factory, [node("w", "Until then", "wait", mode="until",
                                 time="{{ steps.start.data.body }}", filled=["time"])],
                  task_id="wf2", trigger_type="webhook")
    await s._execute_task("wf2", trigger=_webhook("whenever you like"))
    [run] = runs_of(factory, "wf2")
    assert run["status"] == "error"
    assert "was handed “whenever you like” for its time" in run["error"]

    far = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    seed_workflow(factory, [node("w", "Until then", "wait", mode="until",
                                 time="{{ steps.start.data.body }}", filled=["time"])],
                  task_id="wf3", trigger_type="webhook")
    await s._execute_task("wf3", trigger=_webhook(far))
    [run] = runs_of(factory, "wf3")
    assert run["status"] == "error" and "workflow_wait_max_hours" in run["error"]


@pytest.mark.asyncio
async def test_a_path_the_webhook_fills_parks_on_a_card_with_the_encoded_path(monkeypatch, tmp_path):
    """Through the real walker: an HTTP step whose path the author opened, at
    the default rung, asks first — and the card shows the path exactly as it
    would be sent, the sender's `../admin` one piece of it. The dispatcher is
    the one seam, as in `B1885`'s run test; it is never reached."""
    from src import integrations
    from src import workflow_effects as fx
    from tests.helpers.signed_in import signed_in

    factory = make_db(monkeypatch, tmp_path / "path.db")
    signed_in(monkeypatch, tmp_path / "auth", admin="root", members=())
    tool_approval_store._pending.clear()
    monkeypatch.setattr(integrations, "load_integrations", lambda: [
        {"id": "int1", "name": "Tracker", "enabled": True, "base_url": "http://tracker.lan",
         "api_key": "k", "preset": "", "description": ""}])
    sent = []

    async def answer(tool, content, **_kw):
        sent.append(json.loads(content))
        return "api_call", {"output": "HTTP 204", "exit_code": 0, "http_status": 204}

    monkeypatch.setattr(fx, "_dispatch", answer)
    seed_workflow(factory, [node("call", "Close it", "http", integration="int1", method="POST",
                                 path="/items/" + FROM_WEBHOOK + "/close", filled=["path"])],
                  trigger_type="webhook", owner="root")
    s = recording_scheduler()
    await s._execute_task("wf", trigger=_webhook("../admin"))
    [run] = runs_of(factory, "wf")
    assert run["status"] == "waiting" and sent == [], run
    card = records_of(factory, run["id"])[0]["waiting"]["approval"]
    assert json.loads(card["action"]["content"])["path"] == "/items/..%2Fadmin/close"
