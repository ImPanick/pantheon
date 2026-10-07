# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1179` — every tool loopback names the person the call acts for.

`B1175` made `require_admin` ask, on the agent's loopback, whether the person
the request names (`X-Pantheon-Owner`) is an admin, and left a loopback naming
nobody as Pantheon itself. Forge's tools then called `_internal_headers()` with
no owner at sixteen sites, so they named nobody. **Measured 2026-10-03** on the
real app with `AUTH_ENABLED=true` (`integrate-g`, then this file's probe on
`3e4888b`): bob, not an admin, is refused `GET /api/cookbook/state` in person
(403), and his assistant read it through `list_serve_presets` (200) — with the
saved serve commands; `list_cookbook_servers` named every host; the process scan
behind `list_served_models` handed him this machine's model command lines; and
`tail_serve_output` and `list_cached_models` ran `ssh` from this box to a host he
named, through `/api/shell/exec` and `/api/model/cached?host=`.

**The fix is general.** The dispatcher binds the person a tool call acts for,
beside the workspace it already binds (`tool_execution.get_tool_person`), and
`_internal_headers` names them when its caller names nobody — so every tool
loopback, the deep Forge helpers that are never handed an owner included, is
asked what its person's own request is asked. The shell's own admin gate asks
the same question of a named person the middleware found no account for. The
Forge's read tools say a refusal is a refusal (they read a 403's body as an
empty state: "No serve presets saved"), and `list_served_models` stops there
rather than scanning this machine's processes.

**The adversary (`Law 17`):** text a non-admin's assistant reads — a mail, a
page, a document, a webhook body for a scheduled task — steering it at the
admin's Forge state, or at an SSH session from this box to a host of its
choosing.

**What does not change:** an admin's assistant; a call naming nobody (Pantheon
itself); the Forge lifecycle loop and the scheduler's serve action, which act
for nobody and keep naming nobody even if a person is bound around them; an
auth-off install. `FORBIDDEN.md` Part 2's `require_admin`: tightened, never
lifted.

Driven, not read (`Law 20`): the real app booted gated out of process
(`tests/helpers/gated_app.py`), the real dispatcher, the real tools, the real
scheduler and agent loop (only the model's words scripted), with every httpx
client landing on the app from `127.0.0.1` and every process this app would
spawn — `ssh`, `tmux`, the cache scan — recorded at the spawn boundary and
never run.
"""
import asyncio
import json

import pytest

from tests.helpers.gated_app import gated_app_probe

_HOST = "ops@attacker-box"
_SECRET_CMDLINE = "vllm serve /srv/models/secret --api-key sk-B1179-NOT-FOR-BOB"

_PROBE = r'''
import asyncio, subprocess, httpx
from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
from src.constants import COOKBOOK_STATE_FILE

HOST, SECRET_CMDLINE = %(host)r, %(cmdline)r

# `B1229`: the Forge's switch for Hugging Face ships off; this world has it on,
# so the search below is about whom its loopback names, not about the switch.
from src.settings import load_settings, save_settings
_s = load_settings(); _s["forge_model_hubs"] = True; save_settings(_s)
PAST_STOP = [{"id": "qwen1", "sessionId": "qwen1", "type": "serve", "status": "running",
              "remoteHost": "ops@gpu-box", "_scheduledStopAtMs": 1, "_endpointId": "ep-gone",
              "payload": {"_cmd": "vllm serve Qwen/Qwen3-8B --port 8000"}}]


def seed(tasks=()):
    """The admin's Forge: one saved preset, one server, the given tasks."""
    with open(COOKBOOK_STATE_FILE, "w") as f:
        json.dump({"presets": [{"name": "qwen-big", "model": "Qwen/Qwen3-8B",
                                "host": "ops@gpu-box",
                                "cmd": "vllm serve Qwen/Qwen3-8B --port 8000"}],
                   "env": {"servers": [{"name": "gpu-box", "host": "ops@gpu-box",
                                        "platform": "linux"}],
                           "remoteHost": "ops@gpu-box"},
                   "tasks": list(tasks)}, f)


# Every process the app would start, recorded and never run.
spawned = []

class _Proc:
    returncode = 0
    pid = 4242

    async def communicate(self, *a, **k):
        return b'{"models": []}', b""

    async def wait(self):
        return 0

    def kill(self):
        pass


async def _shell(cmd, *a, **k):
    spawned.append(cmd)
    return _Proc()


async def _exec(*argv, **k):
    spawned.append(" ".join(map(str, argv)))
    return _Proc()


def _run(argv, *a, **k):
    spawned.append(argv if isinstance(argv, str) else " ".join(map(str, argv)))
    return subprocess.CompletedProcess(argv, 1, "", "")


asyncio.create_subprocess_shell = _shell
asyncio.create_subprocess_exec = _exec
subprocess.run = _run

# This machine's model processes, as the scan would find one.
import src.tools.cookbook as cookbook_tools
cookbook_tools._scan_running_model_processes = lambda: [{
    "session_id": "pid-7", "model": "/srv/models/secret", "phase": "running (external)",
    "type": "serve", "remote": "local", "pid": 7, "cmdline_preview": SECRET_CMDLINE,
    "external": True}]

# Every httpx client lands on this app from loopback — the one substitution;
# the token, the header, the middleware and the gates are real. Anything else
# (the HuggingFace search) is recorded and answered empty.
_Real = httpx.AsyncClient
reached, outbound = [], []
_asgi = httpx.ASGITransport(app=app_module.app, client=("127.0.0.1", 40000))


class _Switch(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        if request.url.host in ("127.0.0.1", "localhost"):
            res = await _asgi.handle_async_request(request)
            reached.append([request.method, request.url.path, res.status_code,
                            request.headers.get("X-Pantheon-Owner")])
            return res
        outbound.append([request.method, request.url.host])
        return httpx.Response(200, json=[], request=request)


class _Loopback(_Real):
    def __init__(self, *a, **k):
        k.pop("mounts", None)
        k["transport"] = _Switch()
        super().__init__(*a, **k)


httpx.AsyncClient = _Loopback


def watched(make):
    reached.clear(); spawned.clear(); outbound.clear()
    out = asyncio.run(make())
    return {"out": out, "reached": list(reached), "spawned": list(spawned),
            "outbound": list(outbound)}


from src.agent_tools import ToolBlock
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block

TOOLS = {
    "list_serve_presets": ("list_serve_presets", {}),
    "list_cookbook_servers": ("list_cookbook_servers", {}),
    "list_served_models": ("list_served_models", {}),
    "list_downloads": ("list_downloads", {}),
    "list_cached_models": ("list_cached_models", {"host": HOST}),
    "tail_serve_output": ("tail_serve_output", {"session_id": "qwen1", "remote_host": HOST}),
    # No host named: the tool looks the task's host up in the Forge first.
    "tail_serve_output, the task's host": ("tail_serve_output", {"session_id": "qwen1"}),
    "search_hf_models": ("search_hf_models", {"query": "qwen"}),
}


def tool(label, owner):
    seed()
    name, args = TOOLS[label]

    async def go():
        _, said = await execute_tool_block(ToolBlock(name, json.dumps(args)), owner=owner,
                                           security_context=NO_TOOL_SECURITY_CONTEXT)
        return json.loads(json.dumps(said, default=str))
    return watched(go)


WHO = {"bob": MEMBER, "ada": ADMIN, "nobody": None, "local owner": "__pantheon_local__"}
RESULT["auth_enabled"] = bool(app_module.AUTH_ENABLED)
RESULT["tools"] = {label: {name: tool(name, who) for name in TOOLS}
                   for label, who in WHO.items()}

if app_module.AUTH_ENABLED:
    # The reference answer: what each person gets in person.
    def in_person(who):
        c = client(who)
        spawned.clear()
        got = {p: c.get(p).status_code for p in (
            "/api/cookbook/state", "/api/cookbook/tasks/status",
            "/api/model/cached?host=" + HOST, "/api/cookbook/hf-latest?limit=2")}
        got["POST /api/shell/exec"] = c.post(
            "/api/shell/exec", json={"command": "ssh " + HOST + " true"}).status_code
        got["spawned to the named host"] = [s for s in spawned if HOST in s]
        return got
    seed()
    RESULT["in_person"] = {"bob": in_person(MEMBER), "ada": in_person(ADMIN)}

    # A scheduled Prompt task: the real scheduler and agent loop; only the
    # model's words are scripted.
    import src.agent_loop as agent_loop
    import src.task_endpoint as task_endpoint
    script = []

    async def _model(candidates, messages, **kwargs):
        said = script.pop(0) if script else "All done."
        yield "data: " + json.dumps({"delta": said}) + "\n\n"
        yield "data: [DONE]\n\n"
    agent_loop.stream_llm_with_fallback = _model
    agent_loop.estimate_tokens = lambda *a, **k: 10
    task_endpoint.resolve_task_candidates = lambda **kw: []
    from core.database import ScheduledTask, SessionLocal, TaskRun
    from src.task_scheduler import TaskScheduler
    _db = SessionLocal()
    for tid, who in (("bobs-task", MEMBER), ("adas-task", ADMIN)):
        _db.add(ScheduledTask(id=tid, owner=who, name="Forge check", task_type="llm",
                              prompt="List the serve presets.", status="active",
                              model="scripted", endpoint_url="http://127.0.0.1:9/v1"))
    _db.commit()
    _db.close()
    scheduler = TaskScheduler(None)
    scheduler._log_to_assistant = lambda *a, **k: None

    def scheduled(tid):
        seed()
        script.append("```list_serve_presets\n{}\n```")
        got = watched(lambda: scheduler._execute_task(tid))
        db = SessionLocal()
        try:
            run = db.query(TaskRun).filter(TaskRun.task_id == tid).first()
            got["run"] = {"status": run.status, "steps": json.loads(run.steps or "[]")}
        finally:
            db.close()
        got.pop("out")
        return got
    RESULT["scheduled"] = {"bob": scheduled("bobs-task"), "ada": scheduled("adas-task")}

    # Pantheon itself: the Forge lifecycle loop's stop at window-end, and the
    # scheduler's serve action — outside any tool call, and inside one bound to
    # bob, which neither may read.
    import src.cookbook_serve_lifecycle as lifecycle
    import src.tool_execution as tool_execution
    from src.builtin_actions import action_cookbook_serve

    async def inside_bobs_call(make):
        # The dispatcher's binding, made by hand around a caller that is never
        # inside a tool call. (Read with `getattr` so the probe also measures a
        # tree that has no binding: there it runs unbound.)
        person = getattr(tool_execution, "_tool_person", None)
        if person is None:
            return await make()
        token = person.set(MEMBER)
        try:
            return await make()
        finally:
            person.reset(token)

    def tick(bound):
        seed(PAST_STOP)
        got = watched((lambda: inside_bobs_call(lifecycle._tick)) if bound else lifecycle._tick)
        got.pop("out")
        return got

    cfg = json.dumps({"preset": "qwen-big", "set_default": False})

    def serve_action(bound):
        seed()
        make = lambda: action_cookbook_serve(owner=ADMIN, command=cfg)
        got = watched((lambda: inside_bobs_call(make)) if bound else make)
        got["out"] = list(got["out"])
        return got
    RESULT["lifecycle"] = {"unbound": tick(False), "inside bob's call": tick(True)}
    RESULT["serve_action"] = {"unbound": serve_action(False),
                              "inside bob's call": serve_action(True)}

    # The shell's own gate, asked directly by a loopback naming each.
    def raw_shell(owner):
        headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        if owner:
            headers["X-Pantheon-Owner"] = owner

        async def go():
            async with _Loopback() as c:
                r = await c.post("http://127.0.0.1:7000/api/shell/exec", headers=headers,
                                 json={"command": "ssh " + HOST + " true"})
                return r.status_code
        return watched(go)
    RESULT["raw_shell"] = {"nobody": raw_shell(None), "no account": raw_shell("ghost"),
                           "bob": raw_shell(MEMBER), "ada": raw_shell(ADMIN)}
''' % {"host": _HOST, "cmdline": _SECRET_CMDLINE}

# The read tools a non-admin may call whose routes are `require_admin`: the
# first loopback each makes, refused for bob as bob is refused in person.
_ADMIN_ROUTE_READS = {
    "list_serve_presets": ["GET", "/api/cookbook/state"],
    "list_cookbook_servers": ["GET", "/api/cookbook/state"],
    "list_served_models": ["GET", "/api/cookbook/tasks/status"],
    "list_downloads": ["GET", "/api/cookbook/tasks/status"],
    "list_cached_models": ["GET", "/api/cookbook/state"],
    "tail_serve_output": ["POST", "/api/shell/exec"],
    "tail_serve_output, the task's host": ["GET", "/api/cookbook/state"],
}
# What the admin's Forge holds that bob may not read: the saved command, the
# server's address, a process's command line.
_ADMINS = ("vllm serve Qwen/Qwen3-8B", "ops@gpu-box", "sk-B1179-NOT-FOR-BOB")


@pytest.fixture(scope="module")
def gated(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("b1179"), _PROBE,
                           env_overrides={"BACKGROUND_TASK_FOREGROUND_GATE": "0"})


@pytest.fixture(scope="module")
def no_login(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("b1179-off"), _PROBE,
                           env_overrides={"AUTH_ENABLED": "false"})


def test_the_app_is_gated_and_bob_is_refused_the_forge_in_person(gated):
    """The reference answer every other case compares with: bob is refused each
    Forge route the read tools reach and starts nothing on the named host; the
    HuggingFace search is anyone's; ada gets all of it."""
    assert gated["premise"] == {
        "auth_enabled": True, "localhost_bypass": False,
        "admin_is_admin": True, "member_is_admin": False,
    }, gated["premise"]
    bob, ada = gated["in_person"]["bob"], gated["in_person"]["ada"]
    assert bob == {"/api/cookbook/state": 403, "/api/cookbook/tasks/status": 403,
                   f"/api/model/cached?host={_HOST}": 403,
                   "/api/cookbook/hf-latest?limit=2": 200,
                   "POST /api/shell/exec": 403, "spawned to the named host": []}, bob
    assert {k: v for k, v in ada.items() if k != "spawned to the named host"} == {
        "/api/cookbook/state": 200, "/api/cookbook/tasks/status": 200,
        f"/api/model/cached?host={_HOST}": 200, "/api/cookbook/hf-latest?limit=2": 200,
        "POST /api/shell/exec": 200}, ada


@pytest.mark.parametrize("name", sorted(_ADMIN_ROUTE_READS))
def test_a_non_admins_assistant_is_refused_where_the_person_is(gated, name):
    """The row's `Verify:`. Each read tool's first loopback names bob, is
    refused as bob is in person, and goes no further; the tool says it was
    refused, and nothing of the admin's Forge comes back. On `3e4888b` every
    one reached its route as nobody and got 200."""
    row = gated["tools"]["bob"][name]
    method, path = _ADMIN_ROUTE_READS[name]
    assert row["reached"] == [[method, path, 403, "bob"]], (name, row)
    assert row["out"]["exit_code"] == 1, (name, row["out"])
    assert "restricted to admin users" in row["out"]["error"] or \
        "HTTP 403" in row["out"]["error"], (name, row["out"])
    said = json.dumps(row["out"])
    assert not [s for s in _ADMINS if s in said], (name, said)
    assert row["spawned"] == [], (name, row["spawned"])


def test_no_ssh_from_this_box_to_a_host_the_assistant_names(gated):
    """`tail_serve_output` posts `ssh <host> 'tail …'` to `/api/shell/exec`, and
    `list_cached_models` asks `/api/model/cached?host=`, which runs `ssh <host>`.
    For bob's assistant nothing reaches the spawn boundary; for ada's the same
    two calls do reach it — so the probe would have seen one (on `3e4888b`,
    bob's did)."""
    for name in ("tail_serve_output", "list_cached_models"):
        assert not [s for s in gated["tools"]["bob"][name]["spawned"] if _HOST in s], name
        assert [s for s in gated["tools"]["ada"][name]["spawned"]
                if s.startswith("ssh ") and _HOST in s], (name, gated["tools"]["ada"][name])


def test_the_machines_model_processes_are_not_handed_to_a_non_admin(gated):
    """`list_served_models` merges Forge's tasks with a scan of this machine's
    processes, command lines included. No route shows a non-admin either, so a
    refusal ends the call before the scan; an admin's assistant still sees it."""
    assert _SECRET_CMDLINE not in json.dumps(gated["tools"]["bob"]["list_served_models"]["out"])
    assert _SECRET_CMDLINE in json.dumps(gated["tools"]["ada"]["list_served_models"]["out"])


def test_the_huggingface_search_gives_the_assistant_what_the_person_gets(gated):
    """The one Forge read a non-admin may make in person (`require_user`):
    the loopback names bob and is answered as bob's own request is."""
    row = gated["tools"]["bob"]["search_hf_models"]
    assert row["reached"] == [["GET", "/api/cookbook/hf-latest", 200, "bob"]], row
    assert row["out"]["exit_code"] == 0, row


def test_an_admins_assistant_is_unchanged(gated):
    """`Law 1`. Every loopback names ada and is answered; the tools read her
    Forge as before."""
    tools = gated["tools"]["ada"]
    for name, row in tools.items():
        assert row["out"]["exit_code"] == 0, (name, row["out"])
        assert row["reached"] and {r[2] for r in row["reached"]} == {200}, (name, row["reached"])
        assert {r[3] for r in row["reached"]} == {"ada"}, (name, row["reached"])
    assert "vllm serve Qwen/Qwen3-8B" in tools["list_serve_presets"]["out"]["output"]
    assert "gpu-box → ops@gpu-box" in tools["list_cookbook_servers"]["out"]["output"]


def test_a_scheduled_tasks_tool_loopback_names_its_owner(gated):
    """The scheduler's agent loop reaches the same dispatcher, so a task's tool
    acts for the task's owner: bob's task is refused the admin's presets, ada's
    reads them. The refusal is the run's step output, said as a refusal."""
    bob, ada = gated["scheduled"]["bob"], gated["scheduled"]["ada"]
    assert bob["reached"] == [["GET", "/api/cookbook/state", 403, "bob"]], bob
    [step] = [s for s in bob["run"]["steps"] if s.get("kind") == "tool"]
    assert step["tool"] == "list_serve_presets" and step["status"] == "error", step
    assert "restricted to admin users" in step["output"], step
    assert ada["reached"] == [["GET", "/api/cookbook/state", 200, "ada"]], ada
    [step] = [s for s in ada["run"]["steps"] if s.get("kind") == "tool"]
    assert step["status"] == "ok" and "qwen-big" in step["output"], step


@pytest.mark.parametrize("where", ["unbound", "inside bob's call"])
def test_the_forge_lifecycle_loop_still_acts_for_nobody(gated, where):
    """At window-end the loop kills the serve over `/api/shell/exec` and drops
    its endpoint, naming nobody — and keeps naming nobody when a person is
    bound around it, because its headers are its own."""
    row = gated["lifecycle"][where]
    assert row["reached"] == [["POST", "/api/shell/exec", 200, None],
                              ["GET", "/api/model-endpoints", 200, None]], row
    assert [s for s in row["spawned"] if s.startswith("ssh ") and "ops@gpu-box" in s
            and "kill-session" in s], row["spawned"]


@pytest.mark.parametrize("where", ["unbound", "inside bob's call"])
def test_the_schedulers_serve_action_still_acts_for_nobody(gated, where):
    """`cookbook_serve` (an admin-only task action) launches through
    `/api/model/serve` with the token and no person, as before."""
    row = gated["serve_action"][where]
    assert row["reached"][0] == ["POST", "/api/model/serve", 200, None], row
    assert row["out"][1] is True, row["out"]


def test_the_shell_asks_about_the_person_a_loopback_names(gated):
    """`/api/shell/exec` has its own admin gate, which passed the internal tool
    user whoever the loopback named — and the middleware stamps that user for a
    name that is no account. Now a named person is asked about (`B1175`'s
    question); naming nobody is still Pantheon itself. On `3e4888b` the name
    that is no account ran its command (200)."""
    raw = gated["raw_shell"]
    assert raw["nobody"]["out"] == 200 and raw["nobody"]["spawned"], raw["nobody"]
    assert raw["ada"]["out"] == 200 and raw["ada"]["spawned"], raw["ada"]
    for who in ("no account", "bob"):
        assert raw[who]["out"] == 403 and raw[who]["spawned"] == [], (who, raw[who])


def test_a_call_naming_nobody_is_still_pantheon_itself(gated):
    """A tool call with no owner binds nobody, so its loopback names nobody,
    as before; a gated install's reserved local owner is a person asked about,
    and is not an admin (`B1175`)."""
    assert gated["tools"]["nobody"]["list_serve_presets"]["reached"] == [
        ["GET", "/api/cookbook/state", 200, None]]
    assert gated["tools"]["local owner"]["list_serve_presets"]["reached"] == [
        ["GET", "/api/cookbook/state", 403, "__pantheon_local__"]]


def test_a_no_login_install_keeps_what_it_had(no_login):
    """`AUTH_ENABLED=false`: no middleware, `require_admin` passes, and whoever
    a tool call names reads the Forge as before."""
    assert no_login["auth_enabled"] is False
    for label in ("bob", "nobody", "local owner"):
        for name in ("list_serve_presets", "list_cookbook_servers", "list_downloads"):
            row = no_login["tools"][label][name]
            assert row["out"]["exit_code"] == 0, (label, name, row["out"])
            assert {r[2] for r in row["reached"]} == {200}, (label, name, row["reached"])


# ── the binding itself, in process ───────────────────────────────────────────

def test_the_person_is_bound_for_the_call_and_for_nothing_after(monkeypatch):
    """Two calls at once each name their own person, and once a call returns
    the loopback names nobody again — the binding is the call's, as the
    workspace's is."""
    import src.tool_execution as tool_execution
    from src.agent_tools import ToolBlock
    from src.tools._common import _internal_headers

    named = []

    async def impl(block, **kwargs):
        await asyncio.sleep(0.01)
        named.append((block.content, _internal_headers().get("X-Pantheon-Owner")))
        await asyncio.sleep(0.01)
        named.append((block.content, _internal_headers().get("X-Pantheon-Owner")))
        return "ok", {"output": "ok", "exit_code": 0}

    monkeypatch.setattr(tool_execution, "_execute_tool_block_impl", impl)

    def call(who):
        return tool_execution.execute_tool_block(
            ToolBlock("list_downloads", who), owner=who,
            security_context=tool_execution.NO_TOOL_SECURITY_CONTEXT)

    async def both():
        await asyncio.gather(call("bob"), call("ada"))
        # Awaited in this task, so a binding that outlived the call would be
        # this task's.
        await call("bob")
        return _internal_headers()

    after = asyncio.run(both())
    assert sorted(named) == [("ada", "ada")] * 2 + [("bob", "bob")] * 4
    assert "X-Pantheon-Owner" not in after
    assert tool_execution.get_tool_person() is None


def test_a_caller_that_names_someone_is_not_overruled():
    """`app_api`, the image and research tools pass their owner; the binding
    fills in only when a caller names nobody."""
    import src.tool_execution as tool_execution
    from src.tools._common import _internal_headers

    async def inside():
        token = tool_execution._tool_person.set("bob")
        try:
            return _internal_headers(owner="ada"), _internal_headers()
        finally:
            tool_execution._tool_person.reset(token)

    explicit, filled = asyncio.run(inside())
    assert explicit["X-Pantheon-Owner"] == "ada"
    assert filled["X-Pantheon-Owner"] == "bob"
