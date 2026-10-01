# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B977` — an agent refused by the workstation's network mode is told so.

Under *internet* or *none* the network gate refuses a connection at once, and
the program that made it names no policy. **Measured 2026-10-01 in the image,
under the gate's real rules** (`netrules.ruleset`, loaded into a container's own
namespace): Python, bash's `/dev/tcp` and `curl -v` print *No route to host*;
**curl 8.5.0 and git over http print only *Couldn't connect to server***; under
*none* names do not resolve either. So the routed `bash`/`python` result carries
one sentence saying the mode refused it — when the output shows such a refusal
and the mode is held (by the gate, or the daemon's own rules), and not when the
refusal named only addresses the mode lets through.

Driven, not read (`Law 20`): the real dispatcher (`execute_tool_block`) and the
real agent loop against the real daemon (`tests/helpers/workstation_daemon.py`)
and a real network gate (`workstation/gate.py` behind its HTTP layer, its `nft`
recorded — `P20-06`'s `RunningGate`), the admin's mode pushed by the sync every
call makes. The test daemon runs on this machine, under no rules, so a command
here prints what the measured programs printed; the opt-in case at the end runs
the real programs under the real rules in the image and feeds their output to
the same function.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

import src.agent_tools.workstation_tools as wt
from src.workstation_client import account_for
from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _call, _on, people, settings, ws)
from test_the_workstation_network_is_the_one_chosen import RunningGate, _point_at_gate

# What the programs printed, measured in the image under the real rules.
CURL = "curl: (7) Failed to connect to 192.168.1.1 port 80 after 0 ms: Couldn't connect to server"
CURL_V = ("* connect to 192.168.1.1 port 80 from 172.17.0.2 port 44782 failed: No route to host\n"
          "* Failed to connect to 192.168.1.1 port 80 after 0 ms: Couldn't connect to server")
GIT = ("fatal: unable to access 'http://192.168.1.1/x.git/': Failed to connect to 192.168.1.1 "
       "port 80 after 0 ms: Couldn't connect to server")
PYTHON = ("Traceback (most recent call last):\n"
          "  File \"/home/pw-ann/.cache/pantheon-run/x.py\", line 1, in <module>\n"
          "    socket.create_connection(('192.168.1.1', 80), timeout=5)\n"
          "OSError: [Errno 113] No route to host")
URLLIB = "urllib.error.URLError: <urlopen error [Errno 113] No route to host>"
BASH_TCP = "bash: line 1: /dev/tcp/192.168.1.1/80: No route to host"
CURL_NAME = ("curl: (7) Failed to connect to router.lan port 80 after 0 ms: Couldn't connect "
             "to server")
NONE_DNS = "curl: (6) Could not resolve host: example.com"
NONE_PY_DNS = "socket.gaierror: [Errno -3] Temporary failure in name resolution"


@pytest.fixture
def gate(tmp_path, monkeypatch):
    g = RunningGate(tmp_path)
    try:
        _point_at_gate(monkeypatch, tmp_path, g)
        yield g
    finally:
        g.close()


def _mode(settings, ws, mode, **more):
    _on(settings, ws, workstation_network=mode, **more)


def _printing(text: str, code: int = 7) -> str:
    """A command that prints `text` to stderr and exits as the program did."""
    return f"cat >&2 <<'EOF'\n{text}\nEOF\nexit {code}"


# ── the sentence, from the output ────────────────────────────────────────────


@pytest.mark.parametrize("output", [CURL, CURL_V, GIT, PYTHON, BASH_TCP])
def test_a_refusal_naming_a_private_address_is_said_to_be_the_mode(output):
    note = wt.network_refusal_note("internet", "", output)
    assert note == wt.NETWORK_PRIVATE_NOTE.format(address="192.168.1.1")
    assert note.startswith("192.168.1.1 is a private address, and this workstation's network "
                           "mode is internet only (an admin's setting)")


@pytest.mark.parametrize("output", [URLLIB, CURL_NAME])
def test_a_refusal_naming_no_address_says_what_the_mode_refuses_and_no_more(output):
    assert wt.network_refusal_note("internet", output) == wt.NETWORK_INTERNET_NOTE


@pytest.mark.parametrize("output", [
    "curl: (7) Failed to connect to 1.1.1.1 port 80 after 0 ms: Couldn't connect to server",
    # `curl -v` names the workstation's own end after "from" — not the target.
    "* connect to 1.1.1.1 port 80 from 172.17.0.2 port 44782 failed: No route to host",
    "* connect to [2606:4700::1111] port 443 failed: No route to host",
])
def test_a_refusal_of_a_public_address_was_not_the_modes(output):
    assert wt.network_refusal_note("internet", output) is None


@pytest.mark.parametrize("output", [CURL, URLLIB, NONE_DNS, NONE_PY_DNS,
                                    "W: Temporary failure resolving 'archive.ubuntu.com'"])
def test_under_none_every_refusal_and_every_unresolved_name_is_the_mode(output):
    assert wt.network_refusal_note("none", output) == wt.NETWORK_NONE_NOTE


@pytest.mark.parametrize("mode", [None, "full"])
@pytest.mark.parametrize("output", [CURL, PYTHON, NONE_DNS])
def test_without_a_narrowing_mode_held_nothing_is_said(mode, output):
    assert wt.network_refusal_note(mode, output) is None


@pytest.mark.parametrize("output", [
    "", "hello", "PermissionError: [Errno 1] Operation not permitted",
    "OSError: [Errno 101] Network is unreachable", NONE_DNS,
])
def test_output_that_is_not_the_modes_refusal_says_nothing_under_internet(output):
    # A name that does not resolve is not *internet*'s doing (names resolve
    # there), and EPERM is also what a file permission error says.
    assert wt.network_refusal_note("internet", output) is None


# ── through the dispatcher, against the real daemon and gate ────────────────


@pytest.mark.parametrize("tool, content", [
    ("bash", _printing(CURL)),
    ("python", "import sys\nsys.stderr.write(" + json.dumps(PYTHON + "\n") + ")\nsys.exit(1)"),
])
def test_a_routed_command_refused_under_internet_carries_the_sentence(ws, settings, people, gate,
                                                                      tool, content):
    _mode(settings, ws, "internet")
    _, r = _call(tool, content, "ann")
    assert r["ran_in"] == "workstation" and r["exit_code"] != 0, r
    assert gate.nft.loaded == "internet", "the gate does not hold the mode"
    assert wt.NETWORK_PRIVATE_NOTE.format(address="192.168.1.1") in r["note"], r
    # The output itself is the program's, untouched.
    assert "Couldn't connect to server" in r["stderr"] or "No route to host" in r["stderr"]


def test_under_none_a_name_that_does_not_resolve_carries_it(ws, settings, people, gate):
    _mode(settings, ws, "none")
    _, r = _call("bash", _printing(NONE_DNS, 6), "ann")
    assert r["note"] == wt.NETWORK_NONE_NOTE


def test_full_or_a_mode_nothing_holds_says_nothing(ws, settings, people, tmp_path, monkeypatch):
    # Full: nothing is refused by the mode.
    _mode(settings, ws, "full")
    g = RunningGate(tmp_path)
    try:
        _point_at_gate(monkeypatch, tmp_path, g)
        _, r = _call("bash", _printing(CURL), "ann")
        assert "note" not in r, r
    finally:
        g.close()
    # Internet chosen, and no gate: a container without one holds nothing
    # (`needs_recreate`), so a refusal there is not the mode's and is not
    # explained as if it were.
    monkeypatch.delenv("PANTHEON_WORKSTATION_NET_URL")
    _mode(settings, ws, "internet")
    _, r = _call("bash", _printing(CURL), "ann")
    assert "note" not in r, r


def test_a_command_that_reached_its_host_says_nothing(ws, settings, people, gate):
    _mode(settings, ws, "internet")
    _, r = _call("bash", "echo fetched", "ann")
    assert r["stdout"] == "fetched" and "note" not in r


def _turn(monkeypatch, reply, *, owner):
    """`P20-03`'s loop driver (`_loop`), keeping what the model is sent on each
    round: the second round's messages are what it reads back."""
    import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    replies, sent = iter([reply]), []

    async def fake_stream(*a, **k):
        sent.append(json.dumps(a[1] if len(a) > 1 else k.get("messages"), default=str))
        yield f"data: {json.dumps({'delta': next(replies, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "is the router up? curl http://192.168.1.1"}],
            max_rounds=2, owner=owner, session_id="s1", workspace=None,
            relevant_tools={"bash"})]

    events = []
    for chunk in asyncio.run(drain()):
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                events.append(json.loads(chunk[6:]))
            except ValueError:
                pass
    return events, sent


def test_the_agent_reads_it_on_a_real_turn(ws, settings, people, gate, monkeypatch):
    """The loop a person's turn runs: the model's `bash` block, the routed
    call, and the result the model is sent on its next round. (A real model's
    wording of its answer is not measured here: no model runs in this suite.)"""
    _mode(settings, ws, "internet")
    events, sent = _turn(monkeypatch, "```bash\n" + _printing(CURL) + "\n```", owner="ann")
    out = next(e for e in events if e.get("type") == "tool_output")
    assert (out["ran_in"], out["ran_as"]) == ("workstation", account_for("ann"))
    assert len(sent) == 2, "the model was not asked again with the result"
    assert "Couldn't connect to server" in sent[1]
    assert "192.168.1.1 is a private address" in sent[1] and "internet only" in sent[1]
    assert "192.168.1.1 is a private address" not in sent[0]


# ── in the image, under the real rules (opt-in: `PANTHEON_WORKSTATION_E2E=1`) ─

from test_the_workstation_image_is_a_real_ubuntu_machine import (  # noqa: E402,F401 — fixture
    E2E_ENV, _docker, _docker_answers, image)

_REFUSALS = r"""
python3 -c "
from workstation import netrules as N
import os
N.apply(N.ruleset(os.environ['MODE'], table=N.GATE_TABLE, resolvers=N.lan_resolvers()))
assert N.in_force(N.GATE_TABLE) == os.environ['MODE']"
probe() { echo "<<<$1"; shift; "$@" 2>&1; echo ">>>"; }
probe curl curl -sS -m 5 http://192.168.1.1/
probe git git ls-remote http://192.168.1.1/x.git
# From a file, as the daemon runs a `python` call: the traceback quotes the line.
printf "import socket\nsocket.create_connection(('192.168.1.1', 80), timeout=5)\n" > /tmp/probe.py
probe python python3 /tmp/probe.py
probe bash bash -c 'exec 3<>/dev/tcp/192.168.1.1/80'
probe name curl -sS -m 5 http://example.com/
"""


def _blocks(stdout: str):
    out, name, buf = {}, None, []
    for line in stdout.splitlines():
        if line.startswith("<<<"):
            name, buf = line[3:], []
        elif line == ">>>" and name:
            out[name] = "\n".join(buf)
            name = None
        elif name:
            buf.append(line)
    return out


@pytest.mark.skipif(os.environ.get(E2E_ENV) != "1" or not _docker_answers(),
                    reason=f"runs the workstation image: set {E2E_ENV}=1 where Docker answers")
@pytest.mark.parametrize("mode", ["internet", "none"])
def test_what_the_real_programs_print_under_the_real_rules_is_recognised(image, mode):
    """The gate's ruleset in a container's own namespace (it holds NET_ADMIN
    for that, as the gate does), the image's own curl, git, Python and bash."""
    done = _docker("run", "--rm", "--cap-add", "NET_ADMIN", "-e", f"MODE={mode}",
                   "--entrypoint", "bash", image, "-c", _REFUSALS, timeout=300)
    got = _blocks(done.stdout)
    assert set(got) == {"curl", "git", "python", "bash", "name"}, done.stdout + done.stderr
    for program in ("curl", "git", "python", "bash"):
        note = wt.network_refusal_note(mode, got[program])
        expected = (wt.NETWORK_NONE_NOTE if mode == "none"
                    else wt.NETWORK_PRIVATE_NOTE.format(address="192.168.1.1"))
        assert note == expected, (program, got[program])
    # A public name: refused under none (it does not resolve), reached under
    # internet — or failing for this sandbox's own reasons, never the mode's.
    assert (wt.network_refusal_note(mode, got["name"]) == wt.NETWORK_NONE_NOTE) == (mode == "none")
