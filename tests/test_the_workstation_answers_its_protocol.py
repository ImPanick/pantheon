# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-01`/`P20-02` foundation: the daemon and Pantheon's client agree.

Every test here runs the real `workstation/agentd.py` on a local port
(`tests/helpers/workstation_daemon.py`) and drives it through the real
`src/workstation_client.py`, so what is asserted is the wire both sides ship,
not a restatement of it (`Law 20`).
"""
from __future__ import annotations

import ast
import asyncio
import base64
from pathlib import Path

import pytest

from src.workstation_client import WorkstationClient, WorkstationError, account_for, parse_base
from tests.helpers.workstation_daemon import running_workstation
from workstation import protocol as P

ACCT = account_for(None)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def ws(tmp_path):
    with running_workstation(tmp_path) as station:
        yield station


@pytest.fixture
def client(ws):
    return WorkstationClient(ws.url, ws.token)


# ── the package rules ────────────────────────────────────────────────────────

def test_the_workstation_package_imports_nothing_from_pantheon():
    """It runs inside the workstation, where Pantheon is not installed."""
    pkg = Path(__file__).resolve().parent.parent / "workstation"
    app_roots = {"src", "core", "routes", "services", "integrations", "netagent", "companion"}
    offenders = []
    for path in sorted(pkg.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [(node.module or "").split(".")[0]]
            offenders += [f"{path.name}: {n}" for n in names if n in app_roots]
    assert offenders == []


def test_an_account_name_is_safe_and_distinct():
    names = {account_for(o) for o in (None, "", "ann", "Ann", "ann!", "../root", "x" * 200)}
    assert account_for(None) == account_for("")
    assert len(names) == 6  # None and "" are the one single-user owner
    for n in names:
        assert P.ACCOUNT_RE.match(n) and len(n) <= 32
    assert account_for("../root").startswith("pw-root-")


def test_a_route_outside_the_table_or_a_bad_account_is_refused_before_any_request():
    with pytest.raises(KeyError):
        P.route_path("shell")
    with pytest.raises(ValueError):
        P.route_path("exec", "root")
    assert parse_base("http://ws:7040/x?y#z") == "http://ws:7040"
    assert parse_base("http://u:p@ws:7040") is None
    assert parse_base("file:///etc/passwd") is None


# ── the token ─────────────────────────────────────────────────────────────────

def test_health_answers_without_a_token_but_says_less(ws):
    anon = run(WorkstationClient(ws.url, "")._call("health"))
    assert anon["agent"] == P.AGENT_NAME and anon["protocol"] == P.PROTOCOL_VERSION
    assert "sudo" not in anon and "accounts" not in anon
    full = run(WorkstationClient(ws.url, ws.token).health())
    assert full["sudo"] is False and full["screen"] == [P.SCREEN_WIDTH, P.SCREEN_HEIGHT]


@pytest.mark.parametrize("token", ["", "pws_wrong"])
def test_every_other_route_needs_the_token(ws, token):
    c = WorkstationClient(ws.url, token)
    with pytest.raises(WorkstationError) as e:
        run(c.ensure(ACCT))
    assert e.value.code == "unauthorized"


def test_an_unreachable_workstation_is_said_in_a_sentence():
    c = WorkstationClient("http://127.0.0.1:9", "pws_x")
    with pytest.raises(WorkstationError) as e:
        run(c.health())
    assert e.value.code == "unavailable" and "did not answer" in e.value.message


# ── accounts, commands, files ────────────────────────────────────────────────

def test_ensure_makes_the_home_once(client, ws):
    first = run(client.ensure(ACCT))
    again = run(client.ensure(ACCT))
    assert first["created"] is True and again["created"] is False
    assert Path(first["home"]) == ws.root / ACCT and first["holder"] == "agent"


def test_exec_runs_in_the_home_and_reports_everything(client, ws):
    r = run(client.exec(ACCT, "pwd; echo out; echo err >&2; exit 3"))
    assert r["exit_code"] == 3 and r["timed_out"] is False
    assert r["stdout"].splitlines() == [str(ws.root / ACCT), "out"]
    assert r["stderr"].strip() == "err"


def test_exec_python_and_stdin(client):
    r = run(client.exec(ACCT, "import sys; print(sys.stdin.read().upper())", shell="python",
                        stdin="hello"))
    assert r["stdout"].strip() == "HELLO" and r["exit_code"] == 0


def test_a_command_that_outlives_its_timeout_is_killed(client):
    r = run(client.exec(ACCT, "sleep 30", timeout_s=1))
    assert r["timed_out"] is True and r["exit_code"] == 124 and r["duration_ms"] < 10_000


def test_exec_streams_output_as_it_runs(client):
    seen = []
    r = run(client.exec(ACCT, "echo one; sleep 0.2; echo two >&2",
                        on_output=lambda kind, text: seen.append((kind, text))))
    assert ("stdout", "one\n") in seen and ("stderr", "two\n") in seen
    assert r["exit_code"] == 0 and r["stdout"] == "one\n"


def test_files_round_trip_and_list(client):
    run(client.write(ACCT, "proj/a.txt", "alpha"))
    run(client.write(ACCT, "proj/a.txt", "+beta", append=True))
    got = run(client.read(ACCT, "proj/a.txt"))
    assert got["data"] == b"alpha+beta" and got["truncated"] is False
    part = run(client.read(ACCT, "~/proj/a.txt", offset=2, max_bytes=3))
    assert part["data"] == b"pha" and part["truncated"] is True
    listing = run(client.list(ACCT, "proj"))
    assert [(e["path"], e["type"]) for e in listing["entries"]] == [("a.txt", "file")]
    deep = run(client.list(ACCT, recursive=True))
    assert "proj/a.txt" in {e["path"] for e in deep["entries"]}


@pytest.mark.parametrize("path", ["/etc/passwd", "../other", "proj/../../x"])
def test_a_path_out_of_the_home_is_refused(client, path):
    run(client.ensure(ACCT))
    with pytest.raises(WorkstationError) as e:
        run(client.read(ACCT, path))
    assert e.value.code == "outside_home"


def test_a_symlink_out_of_the_home_is_refused(client, ws):
    run(client.exec(ACCT, "ln -s /etc escape"))
    with pytest.raises(WorkstationError) as e:
        run(client.read(ACCT, "escape/hostname"))
    assert e.value.code == "outside_home"


def test_sudo_on_lifts_the_jail(client, ws, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("there")
    run(client.config(sudo=True))
    assert run(client.read(ACCT, str(outside)))["data"] == b"there"
    run(client.config(sudo=False))
    with pytest.raises(WorkstationError):
        run(client.read(ACCT, str(outside)))


def test_reset_puts_the_home_back(client, ws):
    run(client.write(ACCT, "junk.txt", "x"))
    run(client.reset(ACCT))
    assert run(client.list(ACCT))["entries"] == []


# ── the screen ───────────────────────────────────────────────────────────────

def test_a_screenshot_is_the_screen_and_a_repeat_frame_is_skipped(client):
    shot = run(client.screenshot(ACCT))
    png = base64.b64decode(shot["data_b64"])
    assert png.startswith(b"\x89PNG") and (shot["width"], shot["height"]) == (1280, 800)
    assert run(client.screenshot(ACCT, if_none_match=shot["digest"])) is None


def test_input_reaches_the_display_and_changes_the_picture(client, ws):
    before = run(client.screenshot(ACCT))
    r = run(client.input(ACCT, "click", x=10, y=20, screenshot_after=True))
    assert ws.screen(ACCT).actions == [{"action": "click", "x": 10, "y": 20}]
    assert r["screenshot"]["digest"] != before["digest"]


@pytest.mark.parametrize("fields", [
    {"action": "click", "x": 1280, "y": 0},
    {"action": "click", "x": -1, "y": 0},
    {"action": "type"},
    {"action": "key", "keys": "ctrl+l; rm -rf /"},
    {"action": "scroll", "x": 1, "y": 1},
    {"action": "wait", "ms": 999_999},
])
def test_an_input_outside_the_bounds_is_refused(client, ws, fields):
    action = fields.pop("action")
    with pytest.raises(WorkstationError) as e:
        run(client.input(ACCT, action, **fields))
    assert e.value.code in ("bad_request", "too_large")
    assert ws.screen(ACCT).actions == []


def test_while_a_person_holds_the_screen_the_agent_waits(client, ws):
    run(client.control(ACCT, "person"))
    with pytest.raises(WorkstationError) as e:
        run(client.input(ACCT, "click", x=1, y=1))
    assert e.value.code == "busy" and "taken over" in e.value.message
    run(client.input(ACCT, "click", x=2, y=2, holder="person"))
    run(client.control(ACCT, "agent"))
    run(client.input(ACCT, "click", x=3, y=3))
    assert [a["x"] for a in ws.screen(ACCT).actions] == [2, 3]


def test_no_display_is_said_not_faked(tmp_path):
    with running_workstation(tmp_path, with_screen=False) as station:
        c = WorkstationClient(station.url, station.token)
        with pytest.raises(WorkstationError) as e:
            run(c.screenshot(ACCT))
    assert e.value.code == "unavailable" and "no display" in e.value.message
