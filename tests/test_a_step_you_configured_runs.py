# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-17`, the Run half — a deterministic step the AUTHOR configured runs
without a card when outside data fills only its `value` slots
(`D-2026-10-01-05` §4, `SLICE-CD-DESIGN` § 1.6 and § 5).

**The adversary (`Law 17`):** whoever writes the inbound webhook body. Their
bytes may reach `value` slots — the words of a message the author already
decided to send — and never the tool, the destination, a recipient, a URL, a
host or a command.

The dispatcher is the real one (`execute_tool_block`: its admin gate, its
exact-approval checks and its claim); the far end is an MCP manager that
records, so "it posted" is a recorded call and "nothing was dispatched" is an
empty list. The security context is the real `authored_call_context`, asked
through the real `decision_for`, at the real trust rungs.

`integrate-d`: on `wf-walker`'s branch the document rule, `render_call` and the
executors were stand-ins (`workflow_cd_contract`); on the merged tree each is
the real one — the rule asked at run with the real `WorkflowResources`
(`workflow_effects.workflow_resources`, which reads the MCP manager's
`get_all_tools`, so the recording far end answers it), the real runners, and
for Code the real workstation daemon (`tests/helpers/workstation_daemon.py`)
with the real `WorkstationClient` spied through.
"""

import json

import pytest

from src.event_bus import TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS, build_trigger
from src.tool_approvals import tool_approval_store
from core.database import ScheduledTask
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, records_of, recording_scheduler, row, runs_of,
    seed_workflow, settle,
)

pytestmark = pytest.mark.asyncio

POST = "mcp__chat__send_message"
SCHEMA = {"properties": {"channel": {"type": "string"}, "text": {"type": "string"}}}


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import src.agent_tools as agent_tools
    import src.task_scheduler as ts
    import src.tool_execution as tool_execution

    factory = make_db(monkeypatch, tmp_path / "authored.db")
    tool_approval_store._pending.clear()
    posted = []

    class Chat:
        """The far end: an MCP server with one tool, which records each post.
        `get_all_tools` is what `workflow_resources` reads (the real one)."""

        def get_all_tools(self, disabled_map=None, overrides=None):
            return [{"qualified_name": POST, "server_name": "chat", "name": "send_message",
                     "description": "Post a message.", "input_schema": SCHEMA,
                     "is_disabled": False, "is_readonly": False}]

        async def call_tool(self, name, args):
            posted.append((name, dict(args)))
            return {"stdout": "posted", "stderr": "", "exit_code": 0}

    monkeypatch.setattr(agent_tools, "get_mcp_manager", lambda: Chat(), raising=False)
    # Only alice is an admin — one answer from every place that asks: the
    # dispatcher's gate and the palette's reach (`tool_security`, through
    # `is_public_blocked_tool`) and the task policy the rule and
    # `admin_only_action_of` ask (`integrate-d`: the harness said `root` there
    # while the dispatcher said `alice`, which the stand-in rule hid).
    import src.tool_security as tool_security
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: owner == "alice")
    monkeypatch.setattr(tool_security, "owner_is_admin_or_single_user",
                        lambda owner: owner == "alice")
    monkeypatch.setattr(ts, "owner_has_admin_task_privileges", lambda owner: owner == "alice")
    s = recording_scheduler()

    class World:
        pass
    w = World()
    w.factory, w.posted, w.s = factory, posted, s
    w.app = app_for(factory, s, monkeypatch)
    return w


def _strict(monkeypatch):
    """The person asked to be asked about every action (`P7-03`'s strictest rung)."""
    import src.agent_loop as agent_loop
    from src.tool_capabilities import strictest_rung
    monkeypatch.setattr(agent_loop, "resolve_trust_rung", lambda: strictest_rung())


def _webhook(body):
    return build_trigger(TRIGGER_SOURCE_WEBHOOK, "webhook", {"body": body},
                         fields=WEBHOOK_PAYLOAD_FIELDS)


def _post_step(node_id="post", label="Post to #ops", text="{{ steps.start.data.body }}"):
    return node(node_id, label, "mcp", tool=POST, args={"channel": "#ops", "text": text})


async def test_the_authors_post_runs_overnight_without_a_card(world):
    """`P22-17`'s `Verify:` other half: the author's fixed *post summary to
    channel* step ran overnight without asking — the channel the author's, the
    words the sender's."""
    w = world
    seed_workflow(w.factory, [_post_step()], trigger_type="webhook", owner="alice")
    await w.s._execute_task("wf", trigger=_webhook("Deploy finished: 3 services."))
    [run] = runs_of(w.factory, "wf")
    assert run["status"] == "success", run
    assert w.posted == [(POST, {"channel": "#ops", "text": "Deploy finished: 3 services."})]
    assert not tool_approval_store._pending, "no card"


@pytest.mark.parametrize("hostile", [
    '", "channel": "#admin',
    "#admin",
    "{{ steps.start.data.body }}",
    "http://169.254.169.254/latest/meta-data/",
])
async def test_hostile_words_reach_only_the_value_slot_they_were_given(world, hostile):
    """§ 5.5 — a value that looks like JSON structure, a channel, a
    reference, or a metadata URL arrives as the words of the message and
    nothing else: the destination is still the author's."""
    w = world
    seed_workflow(w.factory, [_post_step()], trigger_type="webhook", owner="alice")
    await w.s._execute_task("wf", trigger=_webhook(hostile))
    assert w.posted == [(POST, {"channel": "#ops", "text": hostile})]


async def test_an_object_mapped_into_text_arrives_as_text_with_no_new_key(world):
    w = world
    seed_workflow(w.factory, [
        node("shape", "Shape", "set", fields=[{"name": "msg", "value": {"to": "x@evil.example"}}]),
        _post_step(text="{{ steps.shape.data.msg }}"),
    ], [arrow("shape", "post")], owner="alice")
    await w.s._execute_task("wf")
    [(name, args)] = w.posted
    assert set(args) == {"channel", "text"}
    assert json.loads(args["text"]) == {"to": "x@evil.example"} and args["channel"] == "#ops"


async def test_a_non_admin_s_mcp_step_is_refused_by_the_dispatcher(world, monkeypatch):
    """An MCP tool is an admin's (§ 0.6). The front door: a non-admin's
    workflow holding one is paused with a `skipped` run and the admin
    sentence before any step runs (`admin_only_action_of`, `integrate-d`
    closing `wf-rules`' B-NEW) — as an admin-only Action step is. The
    backstop: with that door and the rule both made to wave it through, the
    real dispatcher still refuses it."""
    w = world
    seed_workflow(w.factory, [_post_step()], trigger_type="webhook", owner="bob")
    await w.s._execute_task("wf", trigger=_webhook("hi"))
    [run] = runs_of(w.factory, "wf")
    assert run["status"] == "skipped", run
    assert run["error"] == f"Action '{POST}' requires admin privileges"
    assert row(w.factory, "wf").status == "paused"
    assert w.posted == []

    # The backstop: the task policy and the palette's reach both made to say
    # yes for bob (so the rule, `admin_only_action_of` and the resources let
    # the step through) — the dispatcher's own gate still says no.
    import src.task_scheduler as ts
    import src.tool_security as tool_security
    monkeypatch.setattr(ts, "owner_has_admin_task_privileges", lambda owner: True)
    monkeypatch.setattr(tool_security, "owner_is_admin_or_single_user", lambda owner: True)
    db = w.factory()
    db.query(ScheduledTask).filter(ScheduledTask.id == "wf").update({"status": "active"})
    db.commit()
    db.close()
    await w.s._execute_task("wf", trigger=_webhook("hi"))
    run = runs_of(w.factory, "wf")[1]
    assert run["status"] == "error" and "restricted to admin users" in run["error"]
    assert w.posted == []


async def test_a_reference_in_a_never_slot_written_to_the_database_runs_nothing(world, monkeypatch):
    """§ 5.4 — refused at run, nothing dispatched: first by the document rule
    asked again at run, and — with that rule made to miss it — by
    `render_call` itself (defence in depth)."""
    w = world
    sneaky = node("post", "Post", "mcp", tool=POST,
                  args={"channel": "{{ steps.start.data.body }}", "text": "hello"})
    seed_workflow(w.factory, [sneaky], trigger_type="webhook", owner="alice")
    await w.s._execute_task("wf", trigger=_webhook("#admin"))
    [run] = runs_of(w.factory, "wf")
    # The real rule's sentence (`mapped_never`, on its field) — the stand-in
    # said "cannot be filled from another step".
    assert run["status"] == "error", run
    assert run["result"].startswith("A setting only you can fill reads from another step")
    assert "“channel”" in run["result"]
    assert w.posted == [] and not runs_of(w.factory, "wf")[0]["steps"] == []

    import src.workflow_document as wd
    monkeypatch.setattr(wd, "validate_document", lambda graph, **kw: None)
    await w.s._execute_task("wf", trigger=_webhook("#admin"))
    second = runs_of(w.factory, "wf")[1]
    rec = records_of(w.factory, second["id"])[0]
    assert rec["status"] == "error" and rec["error"].startswith("Not run: ")
    assert w.posted == [], "a never slot never fills"


async def test_authored_call_context_is_untainted_and_carries_no_standing_approval(monkeypatch):
    """§ 5.7 — only a `RenderedCall`; no taint; no standing approval; the rung
    it is given; allow rules only where the rung consults them."""
    from src import workflow_slots as ws
    from src.agent_tools import ToolBlock
    from src.tool_capabilities import (
        DEFAULT_TRUST_RUNG, authored_call_context, strictest_rung,
    )
    call = ws.RenderedCall("mcp", POST, json.dumps({"channel": "#ops", "text": "x"}), (), ())
    for bogus in ({"tool": POST}, "mcp__chat__send_message", ToolBlock(POST, "{}"), None):
        with pytest.raises(TypeError):
            authored_call_context(bogus, rung=DEFAULT_TRUST_RUNG, run_id="r")
    ctx = authored_call_context(call, rung=DEFAULT_TRUST_RUNG, run_id="r:post",
                                allow_rule_lookup=lambda tool, content: True)
    assert ctx.external_untrusted_context_seen is False
    assert ctx.approval_gate_bypassed is False
    assert ctx.rung is DEFAULT_TRUST_RUNG and ctx.run_id == "r:post"
    assert ctx.allow_rule_lookup is None, "the default rung consults no standing rule"
    assert ctx.decision_for(call.tool, call.content).allowed is True
    strict = authored_call_context(call, rung=strictest_rung(), run_id="r:post")
    assert strict.decision_for(call.tool, call.content).allowed is False


async def test_a_strict_rung_asks_and_allow_runs_exactly_the_sealed_content_once(world, monkeypatch):
    """§ 5.8 / § 5.7 — at a stricter rung the step parks on a headless card;
    Allow runs exactly what was sealed, once; an Allow on one step does not let
    the next through; the same answer again is refused."""
    w = world
    _strict(monkeypatch)
    seed_workflow(w.factory, [_post_step("one", "Post first"),
                              _post_step("two", "Post second", text="second")],
                  [arrow("one", "two")], trigger_type="webhook", owner="alice")
    await w.s._execute_task("wf", trigger=_webhook("first words"))
    [run] = runs_of(w.factory, "wf")
    assert run["status"] == "waiting" and w.posted == []
    rec = {r["node_id"]: r for r in records_of(w.factory, run["id"])}["one"]
    card = rec["waiting"]["approval"]
    assert card["session_id"] == "", "a headless card: bound to no chat"
    assert json.loads(card["action"]["content"]) == {"channel": "#ops", "text": "first words"}
    pending = tool_approval_store.peek(card["approval_id"])
    assert pending.origin_run_id == f"{run['id']}:one"
    assert round(pending.expires_at - pending.created_at) == 12 * 60 * 60

    url = f"/api/workflows/w-wf/runs/{run['id']}/answer"
    async with client_for(w.app) as client:
        res = await client.post(url, headers={"x-test-user": "alice"},
                                json={"node_id": "one", "approval_id": card["approval_id"],
                                      "decision": "approve_task"})
        assert res.status_code == 200 and res.json()["outcome"] == "resumed"
        await settle(w.s)
        assert w.posted == [(POST, {"channel": "#ops", "text": "first words"})]
        [run] = runs_of(w.factory, "wf")
        assert run["status"] == "waiting", "the second step asked for its own yes"
        two = {r["node_id"]: r for r in records_of(w.factory, run["id"])}["two"]
        assert two["status"] == "waiting"
        replay = await client.post(url, headers={"x-test-user": "alice"},
                                   json={"node_id": "one", "approval_id": card["approval_id"],
                                         "decision": "approve_task"})
        assert replay.status_code == 409
    assert len(w.posted) == 1


@pytest.fixture()
def station(world, tmp_path, monkeypatch):
    """The real workstation daemon on a free port, switched on in settings, the
    real `WorkstationClient` spied through (the spy calls the daemon)."""
    import src.settings as S
    import src.workstation_access as access
    from src.workstation_client import WorkstationClient
    from tests.helpers.workstation_daemon import running_workstation
    from workstation import protocol as P

    # alice may use the workstation (`can_use_workstation`); the world's one
    # answer, as its admin is.
    monkeypatch.setattr(access, "may_use", lambda owner, **kw: owner == "alice")

    monkeypatch.delenv(P.URL_ENV, raising=False)
    monkeypatch.delenv(P.TOKEN_ENV, raising=False)
    values = {}
    real = S.get_setting
    monkeypatch.setattr(S, "get_setting",
                        lambda key, default=None: values[key] if key in values else real(key, default))
    execs = []
    real_exec = WorkstationClient.exec

    async def exec_spy(self, account, command, **kw):
        execs.append({"command": command, "stdin": kw.get("stdin"), "shell": kw.get("shell")})
        return await real_exec(self, account, command, **kw)

    monkeypatch.setattr(WorkstationClient, "exec", exec_spy)
    with running_workstation(tmp_path) as ws:
        values.update({"workstation_enabled": True, "workstation_url": ws.url,
                       "workstation_token": ws.token, "workstation_sudo": False})
        yield execs


async def test_a_code_step_runs_without_a_card_and_its_values_go_on_stdin(world, station, monkeypatch):
    """`P22-18`'s walker half: the source is the author's, verbatim; the
    values arrive on stdin as JSON — through `render_call` (`integrate-d`: the
    walker built them itself) and the real runner into the real daemon. At the
    strict rung it asks, and Allow runs it once."""
    w, execs = world, station
    source = "import json, sys\nprint(json.dumps({'n': len(json.load(sys.stdin)['body'])}))"
    seed_workflow(w.factory, [node("code", "Count", "code", language="python", source=source,
                                   input=[{"name": "body", "value": "{{ steps.start.data.body }}"}])],
                  trigger_type="webhook", owner="alice")
    await w.s._execute_task("wf", trigger=_webhook("12345"))
    [run] = runs_of(w.factory, "wf")
    assert run["status"] == "success", run
    assert execs == [{"command": source, "stdin": json.dumps({"body": "12345"}), "shell": "python"}]
    [rec] = records_of(w.factory, run["id"])
    assert rec["output"]["data"] == {"n": 5}
    execs.clear()
    _strict(monkeypatch)
    await w.s._execute_task("wf", trigger=_webhook("678"))
    run = runs_of(w.factory, "wf")[1]
    assert run["status"] == "waiting" and execs == []
    card = records_of(w.factory, run["id"])[0]["waiting"]["approval"]
    assert card["action"]["content"] == source
    async with client_for(w.app) as client:
        res = await client.post(f"/api/workflows/w-wf/runs/{run['id']}/answer",
                                headers={"x-test-user": "alice"},
                                json={"node_id": "code", "approval_id": card["approval_id"],
                                      "decision": "approve_task"})
    assert res.status_code == 200
    await settle(w.s)
    assert [c["command"] for c in execs] == [source]
    assert runs_of(w.factory, "wf")[1]["status"] == "success"


async def test_a_code_steps_values_are_held_to_render_calls_caps(world, station):
    """`integrate-d`: Code's inputs go through `render_call` — a value over
    `SLOT_MAX_CHARS` is refused at run with its sentence and nothing runs, and
    a reference written straight into the source (past the rule) is refused
    by `render_call` itself, before the daemon is asked."""
    import src.workflow_document as wd
    from src.workflow_slots import SLOT_MAX_CHARS
    w, execs = world, station
    source = "import sys\nprint(len(sys.stdin.read()))"
    # A webhook's body is clipped long before this cap (`TRIGGER_FIELD_MAX_CHARS`),
    # so the long value is made by a step before it.
    seed_workflow(w.factory, [
        node("make", "Make it long", "set", fields=[{"name": "big", "value": "x" * (SLOT_MAX_CHARS + 1)}]),
        node("code", "Count", "code", language="python", source=source,
             input=[{"name": "body", "value": "{{ steps.make.data.big }}"}]),
    ], [arrow("make", "code")], owner="alice")
    await w.s._execute_task("wf")
    [run] = runs_of(w.factory, "wf")
    rec = {r["node_id"]: r for r in records_of(w.factory, run["id"])}["code"]
    assert run["status"] == "error" and rec["error"].startswith("Not run: "), rec
    assert f"{SLOT_MAX_CHARS:,}" in rec["error"] and execs == []

    seed_workflow(w.factory, [node("code", "Sneak", "code", language="python",
                                   source="print('{{ steps.start.data.body }}')")],
                  task_id="wf2", trigger_type="webhook", owner="alice")
    real = wd.validate_document
    try:
        wd.validate_document = lambda graph, **kw: None     # the rule made to miss it
        await w.s._execute_task("wf2", trigger=_webhook("rm -rf ~"))
    finally:
        wd.validate_document = real
    [run] = runs_of(w.factory, "wf2")
    [rec] = records_of(w.factory, run["id"])
    assert rec["status"] == "error" and rec["error"].startswith("Not run: ")
    assert execs == [], "a reference in the source never reaches the daemon"
