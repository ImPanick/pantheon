# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B909` — the Forge's **Copy tmux** has to attach from where the person is.

It copied `tmux attach -t <session>`, built in the browser. On the shipped
Docker install that names nothing on the host, and inside the container root's
`tmux attach` answers *"no server running on /tmp/tmux-0/default"*: tmux keeps a
socket per uid, `docker exec` is root, and the app runs as `PUID` under `gosu`.
The command is now built once on the server (`src/tmux_attach.py`), served at
`GET /api/shell/tmux-attach`, and drawn by `static/js/tmuxAttach.js`.

Everything here is driven, not read (`Law 20`):

  * the builder, called for each case — container, native, remote — and for
    hostile session names, which are then handed to a real `/bin/sh`;
  * real tmux, where it is on PATH: the command's target is the session tmux
    holds — exact, never a prefix sibling, and with `.`/`:` as tmux stored
    them — and, as root with `setpriv`, the container command's uid is the one
    whose socket holds the session while root's is not;
  * the route through `TestClient`, behind the real `require_admin`;
  * the browser under node, against the real `tmuxAttach.js` and the Forge
    menu's own functions cut out of `cookbookRunning.js`, fed the JSON the real
    route returned.

One assertion is a file scan, of the one kind `Law 20` allows: that no browser
module builds an attach command of its own, which would be anywhere a second
builder (`Law 7`).
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers.esc_stub import ui_default_stub  # B874

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text

import src.host_docker_access as host_docker_access
import src.tmux_attach as tmux_attach
from src.tmux_attach import (
    NOTE_DETACH,
    WHERE_CONTAINER,
    WHERE_NATIVE,
    WHERE_REMOTE,
    attach_command,
    tmux_target,
)

ROOT = Path(__file__).resolve().parents[1]
TMUX_ATTACH_JS = ROOT / "static" / "js" / "tmuxAttach.js"
RUNNING_JS = ROOT / "static" / "js" / "cookbookRunning.js"

SESSION = "cookbook-1a2b3c4d"

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
needs_tmux = pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not on PATH")


# ── the builder ──────────────────────────────────────────────────────────────


def test_a_container_gets_compose_exec_as_the_uid_that_owns_the_session():
    out = attach_command(SESSION, in_container=True, uid=1000)
    assert out["where"] == WHERE_CONTAINER
    assert shlex.split(out["command"]) == [
        "docker", "compose", "exec", "-u", "1000", "pantheon",
        "tmux", "attach", "-t", f"={SESSION}",
    ]
    assert "if you run pantheon with docker compose" in out["note"].lower()
    assert "docker-compose.yml" in out["note"]
    # The server cannot know the container's name, so it does not guess one.
    other = out["alternative"]
    assert shlex.split(other["command"].replace("<container>", "CONTAINER")) == [
        "docker", "exec", "-it", "-u", "1000", "CONTAINER",
        "tmux", "attach", "-t", f"={SESSION}",
    ]
    assert "<container>" in other["command"]
    assert "<container>" in other["note"]
    assert out["detach"] == NOTE_DETACH


def test_by_default_it_asks_the_existing_container_check_and_its_own_uid(monkeypatch):
    # `Law 14`: the one containerisation check, not a second one.
    assert tmux_attach.running_in_container is host_docker_access.running_in_container
    monkeypatch.setattr(tmux_attach, "running_in_container", lambda: True)
    out = attach_command(SESSION)
    assert out["where"] == WHERE_CONTAINER
    assert shlex.split(out["command"])[3:5] == ["-u", str(os.getuid())]
    monkeypatch.setattr(tmux_attach, "running_in_container", lambda: False)
    assert attach_command(SESSION, user="josh")["where"] == WHERE_NATIVE


def test_native_is_the_bare_command_as_the_user_pantheon_runs_as():
    out = attach_command(SESSION, in_container=False, user="josh")
    assert out["where"] == WHERE_NATIVE
    assert shlex.split(out["command"]) == ["tmux", "attach", "-t", f"={SESSION}"]
    assert "josh" in out["note"]
    assert out["alternative"] is None
    # Without a name to give, it still says whose sessions they are.
    assert "the user Pantheon runs as" in attach_command(SESSION, in_container=False, user="")["note"]


def test_a_native_install_names_its_own_login():
    import pwd

    out = attach_command(SESSION, in_container=False)
    assert pwd.getpwuid(os.getuid()).pw_name in out["note"]


def test_a_remote_session_is_labelled_with_its_host_and_never_wrapped():
    # Its session belongs to the SSH user on that machine — even when Pantheon
    # itself runs in a container, which has nothing to do with it.
    out = attach_command(SESSION, remote_host="root@gpu-box", in_container=True, uid=1000)
    assert out["where"] == WHERE_REMOTE
    assert shlex.split(out["command"]) == ["tmux", "attach", "-t", f"={SESSION}"]
    assert "gpu-box" in out["note"] and "root" in out["note"]
    assert out["alternative"] is None
    alias = attach_command(SESSION, remote_host="gpu-box")
    assert "gpu-box" in alias["note"]
    assert "the user Pantheon connects as" in alias["note"]


def test_dots_and_colons_become_what_tmux_stores():
    # tmux rewrites both to `_` when it creates the session, and reads `-t a.b`
    # as window `a`, pane `b` (`B908` measured it for `pan-agent-` names).
    out = attach_command("pan-agent-chat.v2:x", in_container=False, user="u")
    assert out["session"] == "pan-agent-chat_v2_x"
    assert shlex.split(out["command"])[-1] == "=pan-agent-chat_v2_x"


HOSTILE = {
    "single-quote": "x'; touch CANARY; '",
    "substitution": "$(touch CANARY)",
    "backtick": "`touch CANARY`",
    "semicolon": "; touch CANARY",
    "space": "a b",
    "flag": "-t",
    "double-quote-backslash": '"double" \\back',
    "glob-brace": "*glob?[ab]{c,d}",
    "markup": "<img src=x onerror=alert(1)>",
    "pipe-background": "name|touch CANARY&",
}


@pytest.mark.parametrize("name", list(HOSTILE.values()), ids=list(HOSTILE))
@pytest.mark.parametrize("in_container", [False, True], ids=["native", "container"])
def test_a_hostile_session_name_is_one_argument_to_a_real_shell(name, in_container, tmp_path):
    out = attach_command(name, in_container=in_container, uid=1000, user="u")
    expected = "=" + name.replace(".", "_").replace(":", "_")
    argv = shlex.split(out["command"])
    assert argv[-3:] == ["attach", "-t", expected]
    # The quoted target, handed to a real /bin/sh exactly as it would be typed:
    # one word back, nothing run.
    quoted = out["command"].split(" -t ", 1)[1]
    ran = subprocess.run(["/bin/sh", "-c", "printf '%s' " + quoted], cwd=tmp_path,
                         capture_output=True, text=True, timeout=10)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == expected
    assert not (tmp_path / "CANARY").exists()


@pytest.mark.parametrize("name", ["", "   ", "a\nb", "a\x00b", "\x1b[31mred", "a\x7f", "x" * 257],
                         ids=["empty", "blank", "newline", "nul", "escape", "delete", "too-long"])
def test_a_name_that_cannot_be_a_session_is_refused(name):
    with pytest.raises(ValueError):
        attach_command(name, in_container=False, user="u")


def test_a_host_with_a_control_character_is_refused():
    with pytest.raises(ValueError):
        attach_command(SESSION, remote_host="gpu-box\nrm -rf ~")


# ── real tmux ────────────────────────────────────────────────────────────────


def _tmux_env(base):
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    env["TMUX_TMPDIR"] = str(base)
    return env


def _tmux(env, *args, prefix=()):
    return subprocess.run([*prefix, "tmux", *args], env=env, capture_output=True,
                          text=True, timeout=20)


@needs_tmux
def test_the_native_command_names_exactly_the_session_tmux_holds(tmp_path):
    env = _tmux_env(tmp_path)
    try:
        for name in ("serve-10", "pan-agent-chat.v2", "my model"):
            made = _tmux(env, "-f", "/dev/null", "new-session", "-d", "-s", name, "sleep 300")
            assert made.returncode == 0, made.stderr
        for name in ("pan-agent-chat.v2", "my model", "serve-10"):
            argv = shlex.split(attach_command(name, in_container=False, user="u")["command"])
            assert argv[:3] == ["tmux", "attach", "-t"]
            # `has-session -t` resolves a target-session exactly as
            # `attach -t` does; `display-message` needs the trailing `:` to
            # read the same string as a session, and then says which one.
            found = _tmux(env, "has-session", "-t", argv[3])
            assert found.returncode == 0, (name, found.stderr)
            named = _tmux(env, "display-message", "-p", "-t", argv[3] + ":", "#S")
            assert named.stdout.strip() == name.replace(".", "_"), (name, named.stderr)
        # `serve-1` is gone and `serve-10` is alive. The old command's target
        # lands in the wrong model server; this one finds nothing, which is true.
        assert _tmux(env, "has-session", "-t", "serve-1").returncode == 0
        assert _tmux(env, "display-message", "-p", "-t", "serve-1:", "#S").stdout.strip() == "serve-10"
        target = shlex.split(attach_command("serve-1", in_container=False, user="u")["command"])[3]
        assert _tmux(env, "has-session", "-t", target).returncode != 0
        # And the old command's target for a dotted name finds nothing at all.
        assert _tmux(env, "has-session", "-t", "pan-agent-chat.v2").returncode != 0
    finally:
        _tmux(env, "kill-server")


@needs_tmux
@pytest.mark.skipif(not (hasattr(os, "geteuid") and os.geteuid() == 0 and shutil.which("setpriv")),
                    reason="needs root and setpriv to run tmux as a second uid")
def test_the_container_command_runs_as_the_uid_whose_socket_holds_the_session():
    """What `docker compose exec -u <uid>` does to the command, minus Docker:
    run it as that uid. The session is made by uid 4242 — the app under `gosu`
    — and root, which is what a plain `docker exec` gives you, cannot see it."""
    uid = "4242"
    base = tempfile.mkdtemp(prefix="b909-tmux-")
    os.chmod(base, 0o1777)
    env = _tmux_env(base)
    env["HOME"] = base
    as_app = ("setpriv", f"--reuid={uid}", f"--regid={uid}", "--clear-groups")
    try:
        made = _tmux(env, "-f", "/dev/null", "new-session", "-d", "-s", "cookbook-probe", "sleep 300",
                     prefix=as_app)
        assert made.returncode == 0, made.stderr
        argv = shlex.split(attach_command("cookbook-probe", in_container=True, uid=int(uid))["command"])
        assert argv[:3] == ["docker", "compose", "exec"]
        as_user = argv[argv.index("-u") + 1]
        inside = argv[argv.index("pantheon") + 1:]
        assert inside[:2] == ["tmux", "attach"]
        probe = ("has-session", *inside[2:])
        exec_as = ("setpriv", f"--reuid={as_user}", f"--regid={as_user}", "--clear-groups")
        assert _tmux(env, *probe, prefix=exec_as).returncode == 0
        as_root = _tmux(env, *probe)
        assert as_root.returncode != 0
        assert "tmux-0" in as_root.stderr
    finally:
        _tmux(env, "kill-server", prefix=as_app)
        shutil.rmtree(base, ignore_errors=True)


# ── the route ────────────────────────────────────────────────────────────────


def _client(monkeypatch, *, in_container=True, auth=None):
    pytest.importorskip("starlette.testclient")
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from routes.shell_routes import setup_shell_routes

    monkeypatch.setattr(tmux_attach, "running_in_container", lambda: in_container)
    app = FastAPI()
    if auth is None:
        monkeypatch.setenv("AUTH_ENABLED", "false")
    else:
        monkeypatch.delenv("AUTH_ENABLED", raising=False)
        app.state.auth_manager = SimpleNamespace(is_configured=True, is_admin=lambda u: u in auth)

        @app.middleware("http")
        async def _who(request, call_next):
            request.state.current_user = request.headers.get("x-test-user")
            return await call_next(request)

    app.include_router(setup_shell_routes())
    return TestClient(app, raise_server_exceptions=False)


def test_the_route_answers_with_the_builders_words(monkeypatch):
    client = _client(monkeypatch, in_container=True)
    r = client.get("/api/shell/tmux-attach", params={"session": SESSION})
    assert r.status_code == 200, r.text
    assert r.json() == attach_command(SESSION, in_container=True, uid=os.getuid())
    assert r.json()["command"].startswith(f"docker compose exec -u {os.getuid()} pantheon ")


def test_the_route_passes_a_remote_tasks_host(monkeypatch):
    client = _client(monkeypatch, in_container=True)
    r = client.get("/api/shell/tmux-attach", params={"session": SESSION, "host": "root@gpu-box"})
    assert r.status_code == 200, r.text
    assert r.json()["where"] == WHERE_REMOTE
    assert r.json()["command"] == f"tmux attach -t ={SESSION}"


@pytest.mark.parametrize("params", [{}, {"session": ""}, {"session": "a\nb"},
                                    {"session": SESSION, "host": "h\x00"}],
                         ids=["no-session", "empty-session", "newline-session", "nul-host"])
def test_the_route_refuses_what_the_builder_refuses(monkeypatch, params):
    r = _client(monkeypatch).get("/api/shell/tmux-attach", params=params)
    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str) and r.json()["detail"]


def test_the_route_is_behind_the_real_admin_gate(monkeypatch):
    client = _client(monkeypatch, auth={"alice"})
    url = "/api/shell/tmux-attach"
    assert client.get(url, params={"session": SESSION}).status_code == 403
    assert client.get(url, params={"session": SESSION}, headers={"x-test-user": "bob"}).status_code == 403
    ok = client.get(url, params={"session": SESSION}, headers={"x-test-user": "alice"})
    assert ok.status_code == 200, ok.text


# ── the browser ──────────────────────────────────────────────────────────────

# `B874`: the stub carries the shipped escaper, read out of
# `static/js/util/escapeHtml.js` by the suite's one helper, rather than a
# local `esc` that escapes less than the real one does.
# The real copyToClipboard reaches the clipboard before its first await
# (`B59`); recording the call as it is made is what that property looks like.
_UI_STUB = ui_default_stub(
    "copyToClipboard(text) { globalThis.__copies.push(String(text)); return Promise.resolve(true); },\n"
    "  copyText(text) { globalThis.__copies.push(String(text)); return Promise.resolve(true); },\n"
    "  showToast(msg) { globalThis.__toasts.push(String(msg)); },\n"
    "  showError(msg) { globalThis.__toasts.push('error: ' + String(msg)); },"
)

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
globalThis.__copies = [];
globalThis.__toasts = [];
globalThis.__fetches = [];

/** Answer every fetch with what `pick(url)` returns: `{ status, body }`. */
export function serve(pick) {
  globalThis.fetch = async (url, init) => {
    globalThis.__fetches.push({ url: String(url), credentials: (init || {}).credentials || null });
    const r = pick(String(url));
    return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body };
  };
}

/** A fetch that answers only when the returned function is called. */
export function hold(answer) {
  let release = null;
  globalThis.fetch = (url) => {
    globalThis.__fetches.push({ url: String(url) });
    return new Promise((resolve) => {
      release = () => resolve({ ok: true, status: 200, json: async () => answer });
    });
  };
  return () => release();
}

/** The parts of a Forge task card the menu touches, in the card's order. */
export function card() {
  const el = document.body.appendChild(new Node('div'));
  el.className = 'cookbook-task';
  for (const cls of ['cookbook-task-header', 'cookbook-task-sub', 'cookbook-output-wrap']) {
    el.appendChild(new Node('div')).className = cls;
  }
  return el;
}

export function order(el) { return el.childNodes.map((n) => n.className); }

export function click(node) {
  node.dispatchEvent({ type: 'click', stopPropagation() {}, preventDefault() {} });
}

export const tick = () => new Promise((r) => setTimeout(r, 0));

export function describe(panel) {
  if (!panel) return null;
  const cmds = panel.querySelectorAll('.tmux-attach-cmd');
  const notes = panel.querySelectorAll('.tmux-attach-note');
  return {
    where: panel.dataset.where || null,
    commands: cmds.map((n) => n.textContent),
    notes: notes.map((n) => n.textContent),
    // The raw `_html` behind each piece of text. '' if and only if it went in
    // through `textContent`; the shim's `textContent` getter strips tags out
    // of `_html`, so reading text alone cannot see a switch to `innerHTML`.
    html: cmds.concat(notes).map((n) => n._html),
    copies: panel.querySelectorAll('.tmux-attach-copy').length,
    text: panel.readable,
  };
}
"""

_PREAMBLE = (
    "import { document, Node, serve, hold, card, order, click, tick, describe } from './shim.js';\n"
    "const { prefetchTmuxAttach, copyTmuxAttach, renderTmuxAttach } = await import('./tmuxAttach.js');\n"
    "const menu = await import('./menu.js');\n"
)

_MENU_FUNCTIONS = ("_taskRemoteHost", "_tmuxAttachMenuItem", "_showTaskAttach")


def _cut(source: str, name: str) -> str:
    """One top-level function of `cookbookRunning.js`, whole, by brace balance."""
    match = re.search(r"^function " + re.escape(name) + r"\(", source, re.M)
    assert match, f"cookbookRunning.js has no top-level `function {name}(`"
    return js_definition(source, match.start())


def _menu_module() -> str:
    source = RUNNING_JS.read_text(encoding="utf-8")
    return (
        "import uiModule from './ui.js';\n"
        "import { prefetchTmuxAttach, copyTmuxAttach, renderTmuxAttach } from './tmuxAttach.js';\n\n"
        + "\n\n".join(_cut(source, name) for name in _MENU_FUNCTIONS)
        + "\n\nexport { _tmuxAttachMenuItem, _showTaskAttach };\n"
    )


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("tmuxattach"), TMUX_ATTACH_JS, _SHIM,
                         {"ui.js": _UI_STUB, "menu.js": _menu_module()})


@pytest.fixture
def wire(monkeypatch):
    """What the real route puts on the wire, for the browser to be fed."""
    def get(in_container=True, **params):
        r = _client(monkeypatch, in_container=in_container).get("/api/shell/tmux-attach", params=params)
        return {"status": r.status_code, "body": r.json()}

    return {
        "container": get(session=SESSION),
        "native": get(in_container=False, session=SESSION),
        "remote": get(session="serve-9f8e7d6c", host="root@gpu-box"),
        "hostile": get(in_container=False, session="<img src=x onerror=alert(1)>"),
        "refused": get(session="a\nb"),
    }


def _browser(sandbox, wire, script):
    return _run(sandbox, _PREAMBLE + "const WIRE = " + json.dumps(wire) + ";\n", script)


@needs_node
def test_the_panel_shows_both_container_commands_as_text(sandbox, wire):
    out = _browser(sandbox, wire, """
        serve(() => WIRE.container);
        const handle = prefetchTmuxAttach('cookbook-1a2b3c4d');
        await handle.ready;
        const panel = renderTmuxAttach(handle);
        const seen = describe(panel);
        const buttons = panel.querySelectorAll('.tmux-attach-copy');
        click(buttons[1]);
        click(buttons[0]);
        console.log(JSON.stringify({ seen, copies: __copies, fetches: __fetches }));
    """)
    body = wire["container"]["body"]
    assert out["seen"]["where"] == "container"
    assert out["seen"]["commands"] == [body["command"], body["alternative"]["command"]]
    assert out["seen"]["notes"] == [body["note"], body["alternative"]["note"], body["detach"]]
    assert "<container>" in out["seen"]["text"]
    assert set(out["seen"]["html"]) == {""}
    assert out["copies"] == [body["alternative"]["command"], body["command"]]
    assert out["fetches"] == [{"url": "/api/shell/tmux-attach?session=cookbook-1a2b3c4d",
                               "credentials": "same-origin"}]


@needs_node
def test_a_hostile_name_reaches_the_page_as_text(sandbox, wire):
    out = _browser(sandbox, wire, """
        serve(() => WIRE.hostile);
        const handle = prefetchTmuxAttach('<img src=x onerror=alert(1)>');
        await handle.ready;
        console.log(JSON.stringify(describe(renderTmuxAttach(handle))));
    """)
    assert out["commands"] == [wire["hostile"]["body"]["command"]]
    assert "<img src=x onerror=alert(1)>" in out["commands"][0]
    assert set(out["html"]) == {""}


@needs_node
def test_a_refusal_is_said_in_the_panel(sandbox, wire):
    out = _browser(sandbox, wire, """
        serve(() => WIRE.refused);
        const handle = prefetchTmuxAttach('a\\nb');
        await handle.ready;
        const copied = copyTmuxAttach(handle);
        console.log(JSON.stringify({ copied, seen: describe(renderTmuxAttach(handle)), copies: __copies }));
    """)
    assert out["copied"] is False and out["copies"] == []
    assert out["seen"]["commands"] == []
    assert wire["refused"]["body"]["detail"] in out["seen"]["text"]
    assert "Could not get the command" in out["seen"]["text"]


@needs_node
def test_the_menu_copies_inside_the_click_and_opens_the_panel_under_the_name(sandbox, wire):
    out = _browser(sandbox, wire, """
        serve((url) => (url.includes('host=') ? WIRE.remote : WIRE.container));
        const el = card();
        const task = { sessionId: 'cookbook-1a2b3c4d', type: 'serve', status: 'running' };
        const item = menu._tmuxAttachMenuItem(task, el);
        await tick(); await tick();
        const before = __copies.length;
        item.custom();
        // Counted before anything is awaited: the copy happened in the click.
        const inClick = __copies.slice(before);
        const panel = el.querySelector('.tmux-attach');
        const first = order(el);
        // The menu opened a second time, and its item clicked.
        const second = menu._tmuxAttachMenuItem(task, el);
        await tick(); await tick();
        second.custom();
        console.log(JSON.stringify({
          label: item.label, action: item.action, group: item.group,
          inClick, first, again: order(el), seen: describe(panel),
          fetches: __fetches.map((f) => f.url), toasts: __toasts,
        }));
    """)
    body = wire["container"]["body"]
    assert (out["label"], out["action"], out["group"]) == ("Copy tmux", "copy-tmux", "copy")
    assert out["inClick"] == [body["command"]]
    assert out["seen"]["commands"] == [body["command"], body["alternative"]["command"]]
    assert out["first"] == ["cookbook-task-header", "cookbook-task-sub", "tmux-attach",
                            "cookbook-output-wrap"]
    assert out["again"] == out["first"], "opening it again must replace the panel, not stack one"
    assert out["fetches"][0] == "/api/shell/tmux-attach?session=cookbook-1a2b3c4d"
    assert out["toasts"] == []


@needs_node
@pytest.mark.parametrize("task_host", [
    "{ remoteHost: 'root@gpu-box' }",
    "{ payload: { remote_host: 'root@gpu-box' } }",
], ids=["remoteHost", "payload-remote_host"])
def test_a_remote_task_asks_about_its_own_host(sandbox, wire, task_host):
    out = _browser(sandbox, wire, """
        serve((url) => (url.includes('host=') ? WIRE.remote : WIRE.container));
        const el = card();
        const task = Object.assign({ sessionId: 'serve-9f8e7d6c', type: 'serve' }, __TASK__);
        const item = menu._tmuxAttachMenuItem(task, el);
        await tick(); await tick();
        item.custom();
        console.log(JSON.stringify({ fetches: __fetches.map((f) => f.url), copies: __copies,
                                     seen: describe(el.querySelector('.tmux-attach')) }));
    """.replace("__TASK__", task_host))
    body = wire["remote"]["body"]
    assert out["fetches"] == ["/api/shell/tmux-attach?session=serve-9f8e7d6c&host=root%40gpu-box"]
    assert out["copies"] == [body["command"]]
    assert out["seen"]["where"] == "remote"
    assert out["seen"]["notes"][0] == body["note"]


@needs_node
def test_a_click_before_the_answer_copies_nothing_and_says_so(sandbox, wire):
    out = _browser(sandbox, wire, """
        const release = hold(WIRE.native.body);
        const el = card();
        const item = menu._tmuxAttachMenuItem({ sessionId: 'cookbook-1a2b3c4d' }, el);
        item.custom();
        const early = { copies: __copies.slice(), toasts: __toasts.slice(),
                        text: el.querySelector('.tmux-attach').readable };
        release();
        await tick(); await tick(); await tick();
        console.log(JSON.stringify({ early, late: describe(el.querySelector('.tmux-attach')),
                                     copies: __copies }));
    """)
    assert out["early"]["copies"] == []
    assert out["early"]["toasts"] == ["Not copied yet. Use Copy under the task name."]
    assert "Asking the server" in out["early"]["text"]
    assert out["late"]["commands"] == [wire["native"]["body"]["command"]]
    assert out["copies"] == [], "nothing is copied behind the person's back once it lands"


@needs_node
def test_the_close_button_takes_the_panel_away(sandbox, wire):
    out = _browser(sandbox, wire, """
        serve(() => WIRE.native);
        const el = card();
        const item = menu._tmuxAttachMenuItem({ sessionId: 'cookbook-1a2b3c4d' }, el);
        await tick(); await tick();
        item.custom();
        click(el.querySelector('.tmux-attach-close'));
        console.log(JSON.stringify({ order: order(el) }));
    """)
    assert out["order"] == ["cookbook-task-header", "cookbook-task-sub", "cookbook-output-wrap"]


# ── one builder ──────────────────────────────────────────────────────────────


def test_no_browser_module_builds_an_attach_command():
    """`Law 20`'s one allowed file scan: a string that would be wrong anywhere.
    Comments are blanked first — the modules explain what they used to copy —
    and string literals are kept, because a literal is how a builder looks."""
    tracked = subprocess.run(["git", "ls-files", "static"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.split()
    scanned, offenders = 0, []
    for rel in tracked:
        if rel.startswith("static/lib/") or not rel.endswith((".js", ".html")):
            continue
        text = blank_text((ROOT / rel).read_text(encoding="utf-8"), "html" if rel.endswith(".html") else "js")
        scanned += 1
        for m in re.finditer(r"tmux\s+attach\b|attach-session", text):
            offenders.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")
    assert scanned > 100, "the scan found almost nothing to read"
    assert offenders == [], f"a second attach-command builder: {offenders}"
