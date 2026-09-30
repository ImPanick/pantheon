# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B913` — a kill that failed tells the person something that finds the session.

When a kill leaves a Forge task's session alive, the `.cookbook-task-action-kill`
handler in `static/js/cookbookRunning.js` said *"Kill failed — session may still
be running. Check `tmux ls` on the server."* On the shipped Docker install
`tmux ls` on the host names nothing, and inside the container root's answers
*"no server running on /tmp/tmux-0/default"* — `B909`'s defect as a sentence,
and it reads as "the session is gone" when it is not. The same handler serves
Windows tasks, which have no tmux at all.

`B909` made one builder for where a person runs a tmux command so it reaches
Pantheon's sessions (`src/tmux_attach.py`). It builds the list command now too
(`list_command`, the same placement), served by the same route
(`GET /api/shell/tmux-attach?action=list`) and drawn by the same panel
(`static/js/tmuxAttach.js`), which the failed kill opens under the task's name.

Driven, not read (`Law 20`): the builder for each case; real tmux as two uids;
the route through `TestClient` behind the real admin gate; and under node, the
kill handler itself, cut out of `cookbookRunning.js` and run over a card, fed
the JSON the real route returns. One file scan, of the kind `Law 20` allows.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_copy_tmux_attaches_where_pantheon_runs import (  # noqa: E402
    RUNNING_JS, SESSION, TMUX_ATTACH_JS, _SHIM, _UI_STUB, _client, _cut, _tmux, _tmux_env,
)
from tests.helpers.js_source import js_function
from tests.helpers.source_text import blank_text

from src.tmux_attach import (
    NOTE_COMPOSE,
    WHERE_CONTAINER,
    WHERE_NATIVE,
    WHERE_REMOTE,
    attach_command,
    list_command,
)

ROOT = Path(__file__).resolve().parents[1]

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
needs_tmux = pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not on PATH")


# ── the builder ──────────────────────────────────────────────────────────────


def test_a_container_lists_the_sessions_as_the_uid_that_owns_them():
    got = list_command(SESSION, in_container=True, uid=1000)
    assert got["where"] == WHERE_CONTAINER
    assert got["command"] == "docker compose exec -u 1000 pantheon tmux ls"
    assert got["note"] == NOTE_COMPOSE
    assert got["alternative"]["command"] == "docker exec -it -u 1000 <container> tmux ls"
    assert got["expect"] == f"If {SESSION} is in the list, it is still running."
    assert got["detach"] is None, "listing attaches to nothing, so there is nothing to detach from"


def test_native_and_remote_list_where_the_session_lives():
    native = list_command(SESSION, in_container=False, user="pantheon")
    assert (native["where"], native["command"], native["alternative"]) == (WHERE_NATIVE, "tmux ls", None)
    assert native["note"] == "Run this on the machine Pantheon runs on, logged in as pantheon."
    remote = list_command("serve-9f8e7d6c", remote_host="root@gpu-box", in_container=True)
    assert (remote["where"], remote["command"]) == (WHERE_REMOTE, "tmux ls")
    assert remote["note"] == "This session is on gpu-box. Log in there over SSH as root, then run this."


@pytest.mark.parametrize("case", [
    dict(in_container=True, uid=4242), dict(in_container=False, user="pan"),
    dict(remote_host="pan@lab-2", in_container=True),
], ids=["container", "native", "remote"])
def test_listing_and_attaching_are_placed_by_one_rule(case):
    """One placement for both (`Law 14`): the same where, the same notes, the
    same plain-docker form — only the tmux part differs."""
    attach, listing = attach_command("pan-agent.v2", **case), list_command("pan-agent.v2", **case)
    for key in ("where", "note", "session"):
        assert listing[key] == attach[key], key
    tail = f"tmux attach -t {shlex.quote('=pan-agent_v2')}"
    assert attach["command"].endswith(tail)
    assert listing["command"] == attach["command"][:-len(tail)] + "tmux ls"
    if attach["alternative"]:
        assert listing["alternative"]["note"] == attach["alternative"]["note"]
        assert listing["alternative"]["command"] == attach["alternative"]["command"][:-len(tail)] + "tmux ls"
    else:
        assert listing["alternative"] is None
    assert listing["expect"] == "If pan-agent_v2 is in the list, it is still running."


def test_no_session_named_lists_without_saying_what_to_look_for():
    got = list_command("", in_container=False, user="u")
    assert (got["command"], got["session"], got["expect"]) == ("tmux ls", None, None)


@pytest.mark.parametrize("kwargs", [dict(session="a\nb"), dict(session="x" * 300),
                                    dict(session=SESSION, remote_host="gpu\x00box")],
                         ids=["newline-session", "long-session", "nul-host"])
def test_what_attach_refuses_list_refuses(kwargs):
    with pytest.raises(ValueError):
        list_command(**kwargs)


# ── real tmux ────────────────────────────────────────────────────────────────


@needs_tmux
@pytest.mark.skipif(not (hasattr(os, "geteuid") and os.geteuid() == 0 and shutil.which("setpriv")),
                    reason="needs root and setpriv to run tmux as a second uid")
def test_the_container_list_command_sees_the_session_root_cannot():
    """The row's measurement, then the fix. The session is made by uid 4242 —
    the app under `gosu`. Root, which a plain `docker exec` is, finds no server
    on its own socket: the old sentence's command, reading as "gone". The list
    command's in-container half, run as the uid it names, lists the session."""
    uid = "4242"
    base = tempfile.mkdtemp(prefix="b913-tmux-")
    os.chmod(base, 0o1777)
    env = _tmux_env(base)
    env["HOME"] = base
    as_app = ("setpriv", f"--reuid={uid}", f"--regid={uid}", "--clear-groups")
    try:
        made = _tmux(env, "-f", "/dev/null", "new-session", "-d", "-s", "serve-1.5", "sleep 300",
                     prefix=as_app)
        assert made.returncode == 0, made.stderr
        got = list_command("serve-1.5", in_container=True, uid=int(uid))
        argv = shlex.split(got["command"])
        assert argv[:3] == ["docker", "compose", "exec"]
        as_user = argv[argv.index("-u") + 1]
        inside = argv[argv.index("pantheon") + 1:]
        assert inside == ["tmux", "ls"]
        # tmux 3.4 says "error connecting to …/tmux-0/default" with no socket
        # directory for root and "no server running on …" with one; either
        # way it is root's own socket, and it finds nothing.
        as_root = _tmux(env, *inside[1:])
        assert as_root.returncode != 0 and "tmux-0" in as_root.stderr, as_root
        listed = _tmux(env, *inside[1:], prefix=("setpriv", f"--reuid={as_user}", f"--regid={as_user}",
                                                 "--clear-groups"))
        assert listed.returncode == 0, listed.stderr
        names = [line.split(":", 1)[0] for line in listed.stdout.splitlines()]
        assert got["session"] in names, (got["session"], names)
    finally:
        _tmux(env, "kill-server", prefix=as_app)
        shutil.rmtree(base, ignore_errors=True)


# ── the route ────────────────────────────────────────────────────────────────


def test_the_route_answers_list_with_the_builders_words(monkeypatch):
    client = _client(monkeypatch, in_container=True)
    r = client.get("/api/shell/tmux-attach", params={"session": SESSION, "action": "list"})
    assert r.status_code == 200, r.text
    assert r.json() == list_command(SESSION, in_container=True, uid=os.getuid())
    remote = client.get("/api/shell/tmux-attach",
                        params={"session": SESSION, "host": "root@gpu-box", "action": "list"})
    assert remote.json()["where"] == WHERE_REMOTE and remote.json()["command"] == "tmux ls"
    # Without `action`, the route is `B909`'s, unchanged.
    plain = client.get("/api/shell/tmux-attach", params={"session": SESSION})
    assert plain.json() == attach_command(SESSION, in_container=True, uid=os.getuid())


@pytest.mark.parametrize("params", [{"session": SESSION, "action": "kill"},
                                    {"session": "a\nb", "action": "list"}],
                         ids=["unknown-action", "refused-session"])
def test_the_route_refuses_what_it_cannot_answer(monkeypatch, params):
    r = _client(monkeypatch).get("/api/shell/tmux-attach", params=params)
    assert r.status_code == 400 and r.json()["detail"], r.text


def test_listing_is_behind_the_same_admin_gate(monkeypatch):
    client = _client(monkeypatch, auth={"alice"})
    params = {"session": SESSION, "action": "list"}
    assert client.get("/api/shell/tmux-attach", params=params).status_code == 403
    assert client.get("/api/shell/tmux-attach", params=params,
                      headers={"x-test-user": "bob"}).status_code == 403
    assert client.get("/api/shell/tmux-attach", params=params,
                      headers={"x-test-user": "alice"}).status_code == 200


# ── the kill handler, in the browser ─────────────────────────────────────────


def _kill_handler(source: str) -> str:
    """The `.cookbook-task-action-kill` click handler's body, cut out of the
    card's render by its own anchor — the real handler, run below."""
    code = blank_text(source, "js")
    anchor = ".cookbook-task-action-kill').addEventListener('click', "
    assert code.count(anchor) == 1, "the kill handler is no longer where it was"
    at = code.index(anchor) + len(anchor)
    return js_function(source[at:], "async () =>")


def _card_module() -> str:
    source = RUNNING_JS.read_text(encoding="utf-8")
    return (
        "import uiModule from './ui.js';\n"
        "import { prefetchTmuxAttach, copyTmuxAttach, renderTmuxAttach } from './tmuxAttach.js';\n"
        # Stand-ins for what the handler reaches for besides the notice.
        "const _isWindows = (task) => !!task && task.platform === 'windows';\n"
        "const _ollamaUnloadCommand = () => '';\n"
        "const _tmuxGracefulKill = (task) => 'graceful-kill ' + task.sessionId;\n"
        "const _tmuxCmd = (task, args) => 'probe ' + args;\n"
        "const _endpointUrlForTask = () => 'http://127.0.0.1:8000/v1';\n"
        "const _removeEndpointByUrl = () => {};\n"
        "const _refreshModelsAfterEndpointChange = () => {};\n"
        "globalThis.__removed = [];\n"
        "const _animateOutThenRemove = (el, sid) => globalThis.__removed.push(sid);\n\n"
        + "\n\n".join(_cut(source, name) for name in ("_taskRemoteHost", "_showTaskAttach")
                        # Cut when it exists, so the same cases run the handler
                        # before `B913` and fail on what it said, not on a name.
                        + (("_showKillFailure",) if "function _showKillFailure(" in source else ()))
        + "\n\nexport function kill(task, el) { return (" + "async () => " + _kill_handler(source) + ")(); }\n"
    )


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("killfailure"), TMUX_ATTACH_JS, _SHIM,
                         {"ui.js": _UI_STUB, "card.js": _card_module()})


@pytest.fixture
def wire(monkeypatch):
    """What the real route puts on the wire for each case."""
    def get(in_container=True, **params):
        r = _client(monkeypatch, in_container=in_container).get("/api/shell/tmux-attach", params=params)
        return {"status": r.status_code, "body": r.json()}

    return {
        "container": get(session=SESSION, action="list"),
        "remote": get(session="serve-9f8e7d6c", host="root@gpu-box", action="list"),
    }


_PAGE = r"""
import { document, Node, serve, card, order, tick, describe } from './shim.js';
const { kill } = await import('./card.js');
/** The route for `tmux-attach`, and `/api/shell/exec` answering the kill and
 *  then the probe: `alive` says whether `has-session` still finds it. */
function server(alive, pick) {
  serve((url) => (url.includes('/api/shell/tmux-attach') ? pick(url)
    : { status: 200, body: { stdout: '', stderr: '', exit_code: alive ? 0 : 1 } }));
}
"""


def _page(sandbox, wire, script):
    return _run(sandbox, _PAGE + "const WIRE = " + json.dumps(wire) + ";\n", script)


@needs_node
def test_a_failed_kill_on_a_docker_install_shows_the_command_that_finds_the_session(sandbox, wire):
    """The row's `Verify:`. The panel under the task's name carries the list
    command for where Pantheon runs, and what to look for; the toast points at
    it; the row stays, so the kill can be tried again."""
    out = _page(sandbox, wire, """
        server(true, () => WIRE.container);
        const el = card();
        const task = { sessionId: 'cookbook-1a2b3c4d', type: 'serve', status: 'running' };
        await kill(task, el);
        await tick(); await tick();
        const panel = el.querySelector('.tmux-attach');
        console.log(JSON.stringify({ seen: describe(panel), order: order(el), toasts: __toasts,
          title: panel && panel.querySelector('.tmux-attach-head').readable,
          label: panel && panel.getAttribute('aria-label'),
          asked: __fetches.map((f) => f.url).filter((u) => u.includes('tmux-attach')),
          removed: globalThis.__removed }));
    """)
    body = wire["container"]["body"]
    assert out["asked"] == ["/api/shell/tmux-attach?session=cookbook-1a2b3c4d&action=list"]
    assert out["seen"]["where"] == "container"
    assert out["seen"]["commands"] == [body["command"], body["alternative"]["command"]]
    assert out["seen"]["notes"] == [body["note"], body["alternative"]["note"], body["expect"]]
    assert set(out["seen"]["html"]) == {""}
    assert out["title"].startswith("Check whether it is still running")
    assert out["label"] == "Check whether it is still running"
    assert out["order"] == ["cookbook-task-header", "cookbook-task-sub", "tmux-attach", "cookbook-output-wrap"]
    assert out["toasts"] == ["Kill failed — the session may still be running. "
                             "Check it with the command under the task name."]
    assert not any("tmux ls" in t for t in out["toasts"])
    assert out["removed"] == [], "a session that may still be running kept its row"


@needs_node
def test_a_remote_task_is_checked_on_its_own_host(sandbox, wire):
    out = _page(sandbox, wire, """
        server(true, (url) => (url.includes('host=') ? WIRE.remote : WIRE.container));
        const el = card();
        await kill({ sessionId: 'serve-9f8e7d6c', type: 'serve', status: 'running',
                     remoteHost: 'root@gpu-box' }, el);
        await tick(); await tick();
        console.log(JSON.stringify({ seen: describe(el.querySelector('.tmux-attach')),
          asked: __fetches.map((f) => f.url).filter((u) => u.includes('tmux-attach')) }));
    """)
    assert out["asked"] == ["/api/shell/tmux-attach?session=serve-9f8e7d6c&host=root%40gpu-box&action=list"]
    assert out["seen"]["commands"] == ["tmux ls"]
    assert out["seen"]["notes"][0] == wire["remote"]["body"]["note"]


@needs_node
def test_a_windows_task_is_pointed_at_its_log(sandbox, wire):
    """No tmux there: the menu's log command is what shows it running."""
    out = _page(sandbox, wire, """
        server(true, () => WIRE.container);
        const el = card();
        await kill({ sessionId: 'cookbook-9', type: 'serve', status: 'running', platform: 'windows' }, el);
        await tick();
        console.log(JSON.stringify({ toasts: __toasts, panel: !!el.querySelector('.tmux-attach'),
          asked: __fetches.map((f) => f.url).filter((u) => u.includes('tmux-attach')) }));
    """)
    assert out["toasts"] == ["Kill failed — the process may still be running. Watch its log: ⋮ → Copy log cmd."]
    assert out["panel"] is False and out["asked"] == []


@needs_node
def test_a_kill_that_worked_says_nothing_and_takes_the_row(sandbox, wire):
    out = _page(sandbox, wire, """
        server(false, () => WIRE.container);
        const el = card();
        await kill({ sessionId: 'cookbook-1a2b3c4d', type: 'serve', status: 'running' }, el);
        await tick();
        console.log(JSON.stringify({ toasts: __toasts, panel: !!el.querySelector('.tmux-attach'),
                                     removed: globalThis.__removed }));
    """)
    assert out == {"toasts": [], "panel": False, "removed": ["cookbook-1a2b3c4d"]}


# ── one builder ──────────────────────────────────────────────────────────────


def test_no_browser_module_tells_a_person_to_list_sessions_itself():
    """`Law 20`'s one allowed file scan: a string that would be wrong anywhere
    in the browser. Where to run `tmux ls` is the server's to say."""
    tracked = subprocess.run(["git", "ls-files", "static"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.split()
    scanned, offenders = 0, []
    for rel in tracked:
        if rel.startswith("static/lib/") or not rel.endswith((".js", ".html")):
            continue
        text = blank_text((ROOT / rel).read_text(encoding="utf-8"), "html" if rel.endswith(".html") else "js")
        scanned += 1
        for m in re.finditer(r"tmux\s+(?:ls|list-sessions)\b", text):
            offenders.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")
    assert scanned > 100, "the scan found almost nothing to read"
    assert offenders == [], f"a browser module names a list command: {offenders}"
