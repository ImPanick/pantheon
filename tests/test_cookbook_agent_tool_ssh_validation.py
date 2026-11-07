# SPDX-License-Identifier: AGPL-3.0-or-later
import json

import pytest

from src import tool_implementations as tools


class FakeResponse:
    def __init__(self, data=None, status_code=200):
        self._data = data or {}
        self.status_code = status_code
        self.text = json.dumps(self._data)
        self.content = self.text.encode("utf-8")
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._data


def _install_httpx_client(monkeypatch, *, state=None, posts=None):
    import httpx

    posts = posts if posts is not None else []
    state = state if state is not None else {"tasks": []}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, **kwargs):
            return FakeResponse(state)

        async def post(self, url, json=None, **kwargs):
            posts.append((url, json, kwargs))
            return FakeResponse({"stdout": "", "stderr": "", "exit_code": 0})

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return posts


@pytest.mark.asyncio
async def test_stop_served_model_rejects_invalid_remote_host_before_shell(monkeypatch):
    posts = _install_httpx_client(monkeypatch)

    result = await tools.do_stop_served_model(
        json.dumps({"session_id": "serve-abc123", "remote_host": "-bad"})
    )

    assert result["exit_code"] == 1
    assert "Invalid remote_host" in result["error"]
    assert posts == []


@pytest.mark.asyncio
async def test_stop_served_model_rejects_invalid_state_host_before_shell(monkeypatch):
    posts = _install_httpx_client(
        monkeypatch,
        state={
            "tasks": [
                {
                    "sessionId": "serve-abc123",
                    "remoteHost": "-bad",
                    "sshPort": "22",
                }
            ]
        },
    )

    result = await tools.do_stop_served_model(
        json.dumps({"session_id": "serve-abc123"})
    )

    assert result["exit_code"] == 1
    assert "Invalid remote_host" in result["error"]
    assert posts == []


@pytest.mark.asyncio
async def test_stop_served_model_rejects_invalid_ssh_port_before_shell(monkeypatch):
    posts = _install_httpx_client(monkeypatch)

    result = await tools.do_stop_served_model(
        json.dumps(
            {
                "session_id": "serve-abc123",
                "remote_host": "gpu-box",
                "ssh_port": "not-a-port",
            }
        )
    )

    assert result["exit_code"] == 1
    assert "Invalid ssh_port" in result["error"]
    assert posts == []


@pytest.mark.asyncio
async def test_stop_served_model_uses_validated_remote_target(monkeypatch):
    posts = _install_httpx_client(monkeypatch)

    result = await tools.do_stop_served_model(
        json.dumps(
            {
                "session_id": "serve-abc123",
                "remote_host": "user@gpu-box",
                "ssh_port": 2222,
            }
        )
    )

    assert result["exit_code"] == 0
    assert len(posts) == 1
    command = posts[0][1]["command"]
    assert "ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no" in command
    assert "-p 2222 user@gpu-box" in command
    assert "tmux kill-session -t serve-abc123" in command


@pytest.mark.asyncio
async def test_cancel_download_rejects_invalid_remote_host_before_shell(monkeypatch):
    posts = _install_httpx_client(monkeypatch)

    result = await tools.do_cancel_download(
        json.dumps({"session_id": "cookbook-abc123", "remote_host": "-bad"})
    )

    assert result["exit_code"] == 1
    assert "Invalid remote_host" in result["error"]
    assert posts == []


@pytest.mark.asyncio
async def test_cancel_download_rejects_invalid_state_host_before_shell(monkeypatch):
    posts = _install_httpx_client(
        monkeypatch,
        state={
            "tasks": [
                {
                    "sessionId": "cookbook-abc123",
                    "remoteHost": "-bad",
                    "sshPort": "22",
                }
            ]
        },
    )

    result = await tools.do_cancel_download(
        json.dumps({"session_id": "cookbook-abc123"})
    )

    assert result["exit_code"] == 1
    assert "Invalid remote_host" in result["error"]
    assert posts == []


@pytest.mark.asyncio
async def test_tail_serve_output_rejects_invalid_remote_host_before_shell(monkeypatch):
    posts = _install_httpx_client(monkeypatch)

    result = await tools.do_tail_serve_output(
        json.dumps({"session_id": "serve-abc123", "remote_host": "-bad"})
    )

    assert result["exit_code"] == 1
    assert "Invalid remote_host" in result["error"]
    assert posts == []


@pytest.mark.asyncio
async def test_tail_serve_output_rejects_invalid_state_host_before_shell(monkeypatch):
    posts = _install_httpx_client(
        monkeypatch,
        state={
            "tasks": [
                {
                    "sessionId": "serve-abc123",
                    "remoteHost": "-bad",
                    "sshPort": "22",
                }
            ]
        },
    )

    result = await tools.do_tail_serve_output(
        json.dumps({"session_id": "serve-abc123"})
    )

    assert result["exit_code"] == 1
    assert "Invalid remote_host" in result["error"]
    assert posts == []


@pytest.mark.asyncio
async def test_adopt_served_model_rejects_invalid_remote_host_before_shell(monkeypatch):
    posts = _install_httpx_client(monkeypatch)

    result = await tools.do_adopt_served_model(
        json.dumps(
            {
                "tmux_session": "serve_abc123",
                "model": "org/model",
                "host": "-bad",
            }
        )
    )

    assert result["exit_code"] == 1
    assert "Invalid remote_host" in result["error"]
    assert posts == []


# ── B1910: a session id never ends the quoted command ssh runs ──────────────
#
# stop_served_model, cancel_download and adopt_served_model put the model's
# session id inside the single-quoted command that ssh runs on the GPU host:
# `ssh user@gpu-box 'tmux kill-session -t <id>'`. shlex.quote wraps the id in
# quotes of its own, and those end the outer string, so an id such as
# `x;touch /tmp/pwn` ran `touch /tmp/pwn` on this host, through
# /api/shell/exec. The approval card names a model stop, never the command.
# Now the three tools hold the id to the rule tail_serve_output already used
# (letters, digits, `-`, `_`) before any command is built.

_BREAKOUTS = [
    "x;touch /tmp/pwn",
    "x`touch /tmp/pwn`",
    "x$(touch /tmp/pwn)",
    "x'; touch /tmp/pwn; '",
    'x"; touch /tmp/pwn; "',
    "x && touch /tmp/pwn",
    "x|touch /tmp/pwn",
    "x\ntouch /tmp/pwn",
    "x y",
]

# Every id Pantheon mints or lists, and the names a person gives tmux:
# cookbook-<hex> (downloads, routes/cookbook_routes.py), serve-<hex> (serves),
# queue-<base36> (a download the Cookbook queued, static/js/cookbookDownload.js),
# pid-<n> (a server list_served_models found outside tmux), an adopted
# session's own name, and tmux's own numbered default.
_MINTED = [
    "cookbook-1a2b3c4d",
    "serve-1a2b3c4d",
    "queue-mh6x0k3c",
    "pid-4242",
    "minimax-m27",
    "serve_abc123",
    "0",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["do_stop_served_model", "do_cancel_download"])
@pytest.mark.parametrize("session_id", _BREAKOUTS)
async def test_a_session_id_that_could_end_the_ssh_command_never_reaches_the_shell(
    monkeypatch, tool, session_id
):
    posts = _install_httpx_client(monkeypatch)

    result = await getattr(tools, tool)(
        json.dumps({"session_id": session_id, "remote_host": "user@gpu-box"})
    )

    assert result["exit_code"] == 1
    assert "Invalid session_id" in result["error"]
    assert posts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", _BREAKOUTS)
async def test_adopt_refuses_a_tmux_session_that_could_end_the_ssh_command(
    monkeypatch, session_id
):
    posts = _install_httpx_client(monkeypatch)

    result = await tools.do_adopt_served_model(
        json.dumps(
            {
                "tmux_session": session_id,
                "model": "org/model",
                "host": "user@gpu-box",
                "add_endpoint": False,
            }
        )
    )

    assert result["exit_code"] == 1
    assert "Invalid tmux_session" in result["error"]
    assert posts == []


@pytest.mark.asyncio
async def test_a_local_stop_holds_the_session_id_to_the_same_rule(monkeypatch):
    posts = _install_httpx_client(monkeypatch)

    result = await tools.do_stop_served_model(json.dumps({"session_id": "x;touch /tmp/pwn"}))

    assert result["exit_code"] == 1
    assert "Invalid session_id" in result["error"]
    assert posts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", _MINTED)
async def test_every_session_id_pantheon_mints_still_reaches_tmux(monkeypatch, session_id):
    for tool, verb in (("do_stop_served_model", "kill-session"), ("do_cancel_download", "kill-session")):
        posts = _install_httpx_client(monkeypatch)
        result = await getattr(tools, tool)(
            json.dumps({"session_id": session_id, "remote_host": "user@gpu-box"})
        )
        assert result["exit_code"] == 0, (tool, result)
        assert len(posts) == 1
        assert f"'tmux {verb} -t {session_id}'" in posts[0][1]["command"]

    posts = _install_httpx_client(monkeypatch)
    result = await tools.do_adopt_served_model(
        json.dumps(
            {
                "tmux_session": session_id,
                "model": "org/model",
                "host": "user@gpu-box",
                "add_endpoint": False,
            }
        )
    )
    assert result["exit_code"] == 0, result
    assert f"'tmux has-session -t {session_id} 2>&1'" in posts[0][1]["command"]
