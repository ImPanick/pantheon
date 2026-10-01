# SPDX-License-Identifier: AGPL-3.0-or-later
"""The workstation protocol's conformance cases, for every backend — `P20-07`.

`P20-07`'s `Verify:` is that the protocol tests run against each backend that
can start here. Each case below is a function of a `Backend` — an address, a
token and what that backend is — and drives it through Pantheon's real client
(`src/workstation_client.py`) over the wire, never by reaching into it, so the
same case can run against the in-process daemon, the daemon started as another
process on another address (with and without TLS), the VM backend's host, the
container image and a real VM. The test files that start backends parametrise
over `CASES` (`Law 20`: one list of what "answers the protocol" means, not one
per backend).

Every case makes its own account (`Backend.fresh`), so cases share a backend
without sharing state, and a backend that keeps state between runs (a VM's
disk) is not confused by an earlier one.
"""
from __future__ import annotations

import asyncio
import base64
import http.client
import json
import secrets
import ssl
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import pytest

from src.workstation_client import WorkstationClient, WorkstationError, account_for
from workstation import protocol as P


def run(coro):
    return asyncio.run(coro)


@dataclass
class Backend:
    """One running workstation, as a test reaches it."""
    name: str
    url: str
    token: str
    kind: str                      # what `health` must say it is: one of `P.BACKENDS`
    has_display: bool
    host: str = "127.0.0.1"
    port: int = 0
    tls: Optional[ssl.SSLContext] = None   # how a raw connection reaches it
    # A file every backend's machine has outside any home, for the jail cases.
    outside_file: str = "/etc/hostname"
    made: List[str] = field(default_factory=list)

    def client(self, token: Optional[str] = None) -> WorkstationClient:
        c = WorkstationClient(self.url, self.token if token is None else token, timeout=120.0)
        if self.kind == "vm":
            # What Pantheon's own callers do first (`sync_config`): a client
            # that has heard `backend: "vm"` waits for a person's machine to
            # boot rather than calling the workstation down.
            run(c.health())
        return c

    def fresh(self) -> str:
        account = account_for(f"conformance-{secrets.token_hex(4)}")
        self.made.append(account)
        return account


# ── the cases ────────────────────────────────────────────────────────────────

def health_says_what_it_is(b: Backend) -> None:
    anon = run(b.client("").health())
    assert (anon["agent"], anon["protocol"], anon["backend"]) == (
        P.AGENT_NAME, P.PROTOCOL_VERSION, b.kind)
    for private in ("sudo", "accounts", "machine"):
        assert private not in anon, private
    full = run(b.client().health())
    assert isinstance(full["sudo"], bool) and isinstance(full["accounts"], int)
    assert full["screen"] == [P.SCREEN_WIDTH, P.SCREEN_HEIGHT]
    machine = full["machine"]
    assert isinstance(machine["virtualization"], str) and machine["virtualization"]
    assert machine["accel"] in (*P.ACCELS, None)


def every_route_needs_the_token(b: Backend) -> None:
    account = b.fresh()
    before = run(b.client().account(account))["exists"]
    for token in ("", "pws_not-the-token"):
        c = b.client(token)
        for call in (lambda: c.ensure(account), lambda: c.account(account),
                     lambda: c.exec(account, "true"), lambda: c.config(sudo=True)):
            with pytest.raises(WorkstationError) as e:
                run(call())
            assert e.value.code == "unauthorized", e.value.message
    # The refusals made nothing: a person nobody used is still nobody.
    assert run(b.client().account(account))["exists"] is before


def looking_makes_nothing(b: Backend) -> None:
    """`B959`: whether a home exists, asked without making it."""
    c = b.client()
    account = b.fresh()
    before = run(c.health())["accounts"]
    for _ in range(2):
        seen = run(c.account(account))
        assert seen == {"account": account, "exists": False, "home": None}
    assert run(c.health())["accounts"] == before, "looking made an account"
    made = run(c.ensure(account))
    seen = run(c.account(account))
    assert seen["exists"] is True and seen["home"] == made["home"]
    assert run(c.health())["accounts"] == before + 1


def ensure_makes_the_home_once(b: Backend) -> None:
    c, account = b.client(), b.fresh()
    first, again = run(c.ensure(account)), run(c.ensure(account))
    assert first["created"] is True and again["created"] is False
    assert first["home"] == again["home"] and first["account"] == account
    assert first["holder"] == "agent" and first["screen"] == [P.SCREEN_WIDTH, P.SCREEN_HEIGHT]


def exec_runs_in_the_home(b: Backend) -> None:
    c, account = b.client(), b.fresh()
    home = run(c.ensure(account))["home"]
    r = run(c.exec(account, "pwd; echo out; echo err >&2; exit 3"))
    assert r["exit_code"] == 3 and r["timed_out"] is False and r["truncated"] is False
    assert r["stdout"].splitlines() == [home, "out"] and r["stderr"].strip() == "err"
    assert r["cwd"] == home


def exec_python_with_stdin(b: Backend) -> None:
    c, account = b.client(), b.fresh()
    r = run(c.exec(account, "import sys; print(sys.stdin.read().upper())", shell="python",
                   stdin="hello"))
    assert r["stdout"].strip() == "HELLO" and r["exit_code"] == 0


def a_command_past_its_timeout_is_killed(b: Backend) -> None:
    c, account = b.client(), b.fresh()
    r = run(c.exec(account, "sleep 30", timeout_s=1))
    assert r["timed_out"] is True and r["exit_code"] == 124 and r["duration_ms"] < 15_000


def output_streams_while_it_runs(b: Backend) -> None:
    c, account = b.client(), b.fresh()
    seen = []
    r = run(c.exec(account, "echo one; sleep 0.3; echo two >&2",
                   on_output=lambda kind, text: seen.append((kind, text))))
    assert ("stdout", "one\n") in seen and ("stderr", "two\n") in seen
    assert r["exit_code"] == 0 and r["stdout"] == "one\n"


def files_round_trip_and_list(b: Backend) -> None:
    c, account = b.client(), b.fresh()
    run(c.write(account, "proj/a.txt", "alpha"))
    run(c.write(account, "proj/a.txt", "+beta", append=True))
    got = run(c.read(account, "proj/a.txt"))
    assert got["data"] == b"alpha+beta" and got["truncated"] is False
    part = run(c.read(account, "~/proj/a.txt", offset=2, max_bytes=3))
    assert part["data"] == b"pha" and part["truncated"] is True
    listing = run(c.list(account, "proj"))
    assert [(e["path"], e["type"]) for e in listing["entries"]] == [("a.txt", "file")]
    assert "proj/a.txt" in {e["path"] for e in run(c.list(account, recursive=True))["entries"]}
    with pytest.raises(WorkstationError) as e:
        run(c.read(account, "proj/missing.txt"))
    assert e.value.code == "not_found"


def a_path_out_of_the_home_is_refused(b: Backend) -> None:
    c, account = b.client(), b.fresh()
    was = run(c.health())["sudo"]
    run(c.config(sudo=False))
    try:
        run(c.ensure(account))
        for path in (b.outside_file, "../other", "proj/../../x"):
            with pytest.raises(WorkstationError) as e:
                run(c.read(account, path))
            assert e.value.code == "outside_home", path
        run(c.exec(account, "ln -s /etc escape"))
        with pytest.raises(WorkstationError) as e:
            run(c.read(account, "escape/hostname"))
        assert e.value.code == "outside_home"
    finally:
        run(c.config(sudo=was))


def sudo_lifts_the_jail_and_back(b: Backend) -> None:
    c, account = b.client(), b.fresh()
    was = run(c.health())["sudo"]
    try:
        assert run(c.config(sudo=True))["sudo"] is True
        assert run(c.read(account, b.outside_file))["size"] >= 0
        assert run(c.config(sudo=False))["sudo"] is False
        with pytest.raises(WorkstationError) as e:
            run(c.read(account, b.outside_file))
        assert e.value.code == "outside_home"
    finally:
        run(c.config(sudo=was))


def reset_puts_the_home_back(b: Backend) -> None:
    c, account = b.client(), b.fresh()
    run(c.write(account, "junk.txt", "x"))
    assert run(c.reset(account)) == {"account": account, "reset": True}
    with pytest.raises(WorkstationError) as e:
        run(c.read(account, "junk.txt"))
    assert e.value.code == "not_found"
    assert run(c.account(account))["exists"] is True


def the_screen_is_shown_or_its_absence_said(b: Backend) -> None:
    c, account = b.client(), b.fresh()
    if not b.has_display:
        with pytest.raises(WorkstationError) as e:
            run(c.screenshot(account))
        assert e.value.code == "unavailable" and "display" in e.value.message
        return
    shot = run(c.screenshot(account))
    data = base64.b64decode(shot["data_b64"])
    assert shot["mime"] == "image/png" and data.startswith(b"\x89PNG")
    assert (shot["width"], shot["height"]) == (P.SCREEN_WIDTH, P.SCREEN_HEIGHT)
    assert len(shot["digest"]) == 16


def an_input_outside_the_bounds_is_refused(b: Backend) -> None:
    c, account = b.client(), b.fresh()
    for action, fields in (("click", {"x": P.SCREEN_WIDTH, "y": 0}), ("type", {}),
                           ("key", {"keys": "ctrl+l; rm -rf /"}), ("wait", {"ms": 999_999})):
        with pytest.raises(WorkstationError) as e:
            run(c.input(account, action, **fields))
        assert e.value.code in ("bad_request", "too_large"), action


def while_a_person_holds_the_screen_the_agent_waits(b: Backend) -> None:
    c, account = b.client(), b.fresh()
    assert run(c.control(account, "person"))["holder"] == "person"
    with pytest.raises(WorkstationError) as e:
        run(c.input(account, "click", x=1, y=1))
    assert e.value.code == "busy" and "taken over" in e.value.message
    assert run(c.ensure(account))["holder"] == "person"
    run(c.control(account, "agent"))
    if b.has_display:
        assert run(c.input(account, "move", x=3, y=3))["ok"] is True
    else:
        with pytest.raises(WorkstationError) as e:
            run(c.input(account, "move", x=3, y=3))
        assert e.value.code == "unavailable"


def _raw_exec_then_hang_up(b: Backend, account: str, command: str) -> None:
    if b.tls is not None:
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            b.host, b.port, timeout=30, context=b.tls)
    else:
        conn = http.client.HTTPConnection(b.host, b.port, timeout=30)
    conn.request("POST", P.route_path("exec", account)[1],
                 json.dumps({"command": command, "stream": True, "timeout_s": 60}),
                 {"Authorization": f"Bearer {b.token}", "Content-Type": "application/json"})
    assert conn.getresponse().status == 200
    time.sleep(1.0)
    conn.close()


def _pid_state(c: WorkstationClient, account: str, pid: int) -> str:
    r = run(c.exec(account, f"if [ -r /proc/{pid}/status ] && ! grep -q '^State:[[:space:]]*Z' "
                            f"/proc/{pid}/status; then echo alive; else echo gone; fi"))
    return r["stdout"].strip()


def a_hang_up_takes_its_command_with_it(b: Backend) -> None:
    """`B965` on every backend — through TLS, and through the VM host to
    the machine behind it."""
    c, account = b.client(), b.fresh()
    run(c.ensure(account))
    _raw_exec_then_hang_up(b, account, "echo $$ > pid.txt; sleep 6; echo late > late.txt")
    pid = 0
    for _ in range(50):
        try:
            pid = int(run(c.read(account, "pid.txt"))["data"].decode().strip())
            break
        except (WorkstationError, ValueError):
            time.sleep(0.2)
    assert pid, "the command never started"
    deadline = time.monotonic() + 8
    while _pid_state(c, account, pid) == "alive" and time.monotonic() < deadline:
        time.sleep(0.3)
    assert _pid_state(c, account, pid) == "gone"
    time.sleep(6.5)
    with pytest.raises(WorkstationError):
        run(c.read(account, "late.txt"))


CASES: List[Callable[[Backend], None]] = [
    health_says_what_it_is,
    every_route_needs_the_token,
    looking_makes_nothing,
    ensure_makes_the_home_once,
    exec_runs_in_the_home,
    exec_python_with_stdin,
    a_command_past_its_timeout_is_killed,
    output_streams_while_it_runs,
    files_round_trip_and_list,
    a_path_out_of_the_home_is_refused,
    sudo_lifts_the_jail_and_back,
    reset_puts_the_home_back,
    the_screen_is_shown_or_its_absence_said,
    an_input_outside_the_bounds_is_refused,
    while_a_person_holds_the_screen_the_agent_waits,
    a_hang_up_takes_its_command_with_it,
]

__all__ = ["Backend", "CASES", "run"]
