# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-01`: the Ubuntu workstation's own logic, driven without a container.

Everything here calls the shipped code — `workstation/ubuntu.py`,
`workstation/__main__.py` and the parts of `workstation/agentd.py` they changed
— and nothing here touches this machine's accounts: no `useradd`, no sudoers
outside a temporary directory, no `prepare()` (`Law 20`). What needs the real
image (accounts, displays, sudo, Firefox) is driven through the real client in
`tests/test_the_workstation_image_is_a_real_ubuntu_machine.py`.

A few cases need root, because what they prove is what the kernel does to a
root daemon that has taken an account's filesystem identity; they skip
elsewhere and say so.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.workstation_client import WorkstationClient, WorkstationError as ClientError, account_for
from workstation import __main__ as cli
from workstation import agentd, ubuntu
from workstation import protocol as P

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "workstation"
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
needs_root = pytest.mark.skipif(not IS_ROOT, reason="proves what the kernel does to a root daemon")
ANN, BOB = account_for("ann"), account_for("bob")
STRANGER = 54_321  # a uid with no name on this machine


def run(coro):
    return asyncio.run(coro)


# ── the package rules ────────────────────────────────────────────────────────

def test_the_workstation_package_needs_nothing_but_the_standard_library():
    """It is copied into an image that has Python and nothing else installed
    for it; `ubuntu.py` and `__main__.py` are held to the same rule as the
    two modules that came before them."""
    stdlib = set(sys.stdlib_module_names)
    scanned, offenders = set(), []
    for path in sorted(PKG.glob("*.py")):
        scanned.add(path.name)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            offenders += [f"{path.name}: {n}" for n in names
                          if n.split(".")[0] not in stdlib | {"workstation", "__future__"}]
    assert offenders == []
    assert {"protocol.py", "agentd.py", "ubuntu.py", "__main__.py"} <= scanned


def test_the_package_runs_alone_as_the_image_copies_it(tmp_path):
    """The Dockerfile copies `workstation/*.py` and nothing else. The same
    copy, imported by an isolated interpreter (`-I`: no site-packages, no
    PYTHONPATH), must load every module and answer `--help`."""
    dest = tmp_path / "workstation"
    dest.mkdir()
    for path in PKG.glob("*.py"):
        shutil.copy(path, dest / path.name)
    # `-I` also leaves the working directory off the path; the image's
    # WORKDIR puts it there, so the probe does the same by hand.
    here = "import sys; sys.path.insert(0, '.'); "
    probe = subprocess.run(
        [sys.executable, "-I", "-c", here +
         "import workstation.protocol, workstation.agentd, workstation.ubuntu, "
         "workstation.__main__; print('loaded')"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "loaded"
    helped = subprocess.run(
        [sys.executable, "-I", "-c", here + "import runpy; runpy.run_module('workstation', "
         "run_name='__main__')", "--help"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert helped.returncode == 0 and "--system {ubuntu,single}" in helped.stdout


# ── accounts keep their numbers ──────────────────────────────────────────────

def _registry(tmp_path, **kw):
    homes = tmp_path / "homes"
    homes.mkdir(exist_ok=True)
    kw.setdefault("id_in_use", lambda n: False)
    return ubuntu.AccountRegistry(homes / ubuntu.STATE_DIRNAME / "accounts.json", homes, **kw)


def test_a_new_account_gets_the_lowest_free_number_and_keeps_it_after_a_restart(tmp_path):
    reg = _registry(tmp_path)
    ann, bob = reg.uid_for(ANN), reg.uid_for(BOB)
    assert (ann, bob) == (ubuntu.UID_MIN, ubuntu.UID_MIN + 1)
    assert reg.uid_for(ANN) == ann
    # A container restart: a new daemon, the same volume.
    again = _registry(tmp_path)
    assert again.uid_for(BOB) == bob and again.uid_for(ANN) == ann
    assert again.accounts() == sorted([ANN, BOB])
    on_disk = json.loads(reg.path.read_text())["accounts"]
    assert on_disk == {ANN: {"uid": ann}, BOB: {"uid": bob}}
    assert stat.S_IMODE(reg.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(reg.path.parent.stat().st_mode) == 0o700


def test_a_number_the_system_or_the_pairing_group_holds_is_never_given(tmp_path):
    taken = {ubuntu.UID_MIN, ubuntu.UID_MIN + 1}
    reg = _registry(tmp_path, reserved=[ubuntu.UID_MIN + 2], id_in_use=lambda n: n in taken)
    assert reg.uid_for(ANN) == ubuntu.UID_MIN + 3


def test_a_lost_registry_is_rebuilt_from_the_homes_not_renumbered(tmp_path):
    reg = _registry(tmp_path)
    ann, bob = reg.uid_for(ANN), reg.uid_for(BOB)
    owners = {ANN: ann, BOB: bob}
    for name in owners:
        (reg.homes / name).mkdir()
    reg.path.unlink()
    rebuilt = _registry(tmp_path, owner_of=lambda p: owners[p.name])
    carol = rebuilt.uid_for(account_for("carol"))
    assert rebuilt.uid_for(ANN) == ann and rebuilt.uid_for(BOB) == bob
    assert carol not in (ann, bob)


def test_an_unreadable_registry_is_rebuilt_from_the_homes_too(tmp_path):
    reg = _registry(tmp_path)
    uid = reg.uid_for(ANN)
    (reg.homes / ANN).mkdir()
    reg.path.write_text("{ not json")
    rebuilt = _registry(tmp_path, owner_of=lambda p: uid)
    assert rebuilt.uid_for(ANN) == uid
    assert json.loads(rebuilt.path.read_text())["accounts"][ANN]["uid"] == uid


def test_a_home_that_predates_its_entry_keeps_its_owner(tmp_path):
    reg = _registry(tmp_path, owner_of=lambda p: ubuntu.UID_MIN + 40)
    (reg.homes / ANN).mkdir()
    assert reg.uid_for(ANN) == ubuntu.UID_MIN + 40


@pytest.mark.parametrize("entry", [
    {"pw-evil-00000000": {"uid": 0}},              # root, written while sudo was on
    {"root": {"uid": ubuntu.UID_MIN}},             # not an account name
    {"pw-evil-00000000": {"uid": True}},           # a bool is not a uid
    {"pw-evil-00000000": {"uid": ubuntu.UID_MAX + 1}},
])
def test_an_entry_outside_the_rules_is_not_believed(tmp_path, entry):
    """With sudo on an agent is root and can edit the file; the range check is
    what keeps such an edit from surviving a later sudo off as uid 0."""
    reg = _registry(tmp_path)
    reg.path.parent.mkdir(parents=True)
    reg.path.write_text(json.dumps({"version": 1, "accounts": entry}))
    fresh = _registry(tmp_path)
    assert fresh.accounts() == []
    assert fresh.uid_for(ANN) == ubuntu.UID_MIN


def test_two_entries_claiming_one_number_leave_one_owner(tmp_path):
    reg = _registry(tmp_path)
    reg.path.parent.mkdir(parents=True)
    reg.path.write_text(json.dumps({"accounts": {ANN: {"uid": 20_005}, BOB: {"uid": 20_005}}}))
    fresh = _registry(tmp_path)
    assert fresh.accounts() == [sorted([ANN, BOB])[0]]


def test_the_range_running_out_is_said(tmp_path):
    reg = _registry(tmp_path, lo=30_000, hi=30_000)
    reg.uid_for(ANN)
    with pytest.raises(agentd.WorkstationError) as e:
        reg.uid_for(BOB)
    assert e.value.code == "unavailable" and "no free account" in e.value.message


# ── sudo ─────────────────────────────────────────────────────────────────────

def _rules(text):
    return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]


def test_the_sudo_rule_is_one_group_line_when_on_and_nothing_when_off():
    assert _rules(ubuntu.sudoers_text(True)) == [f"%{ubuntu.AGENTS_GROUP} ALL=(ALL:ALL) NOPASSWD: ALL"]
    assert _rules(ubuntu.sudoers_text(False)) == []


@needs_root
@pytest.mark.skipif(not shutil.which("visudo"), reason="visudo is not installed here")
@pytest.mark.parametrize("on", [True, False])
def test_sudo_itself_accepts_both_files(tmp_path, on):
    path = tmp_path / "pantheon-workstation"
    ubuntu.write_sudoers(on, path)  # the real validator: visudo -c
    assert stat.S_IMODE(path.stat().st_mode) == 0o440
    assert subprocess.run(["visudo", "-c", "-q", "-f", str(path)]).returncode == 0


def test_a_rule_that_does_not_validate_leaves_the_old_file(tmp_path):
    path = tmp_path / "pantheon-workstation"
    ubuntu.write_sudoers(False, path, validate=lambda p: True)
    before = path.read_text()
    with pytest.raises(agentd.WorkstationError):
        ubuntu.write_sudoers(True, path, validate=lambda p: False)
    assert path.read_text() == before
    # No half-written file left for `#includedir` — which skips dotted names anyway.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["pantheon-workstation"]


def _system(tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(ubuntu, "_visudo_ok", lambda p: True)
    sudoers = tmp_path / "sudoers.d"
    sudoers.mkdir(exist_ok=True)
    return ubuntu.UbuntuSystem(tmp_path / "homes", skeleton=tmp_path / "skel",
                               sudoers_path=sudoers / "pantheon-workstation",
                               runtime_root=tmp_path / "run-user", prepare=False, **kw)


def test_the_admins_sudo_choice_outlives_a_restart(tmp_path, monkeypatch):
    first = _system(tmp_path, monkeypatch, sudo_default=True)
    assert first.sudo is True
    first.set_sudo(False)
    assert _rules(first.sudoers_path.read_text()) == []
    # Restarted with the product default (on): the admin's "off" stands.
    again = _system(tmp_path, monkeypatch, sudo_default=True)
    assert again.sudo is False
    again.set_sudo(True)
    assert _system(tmp_path, monkeypatch, sudo_default=False).sudo is True


# ── running as the account ───────────────────────────────────────────────────

def test_a_command_runs_as_the_account_with_its_own_environment_and_nothing_of_the_daemons(
        tmp_path, monkeypatch):
    monkeypatch.setenv(P.TOKEN_ENV, "pws_secret-the-daemon-holds")
    system = _system(tmp_path, monkeypatch)
    uid = system.registry.uid_for(ANN)
    prefix, env = system.run_as(ANN)
    assert prefix == ["setpriv", f"--reuid={uid}", f"--regid={uid}", "--init-groups", "--"]
    home = str(tmp_path / "homes" / ANN)
    assert env == {
        "HOME": home, "USER": ANN, "LOGNAME": ANN, "SHELL": "/bin/bash",
        "PATH": f"{home}/.local/bin:{ubuntu.SYSTEM_PATH}", "LANG": "C.UTF-8",
        "TERM": "xterm-256color", "XDG_RUNTIME_DIR": str(tmp_path / "run-user" / str(uid)),
    }  # no DISPLAY until a display runs, and no token


def test_an_unknown_account_is_not_run_as_anyone(tmp_path, monkeypatch):
    system = _system(tmp_path, monkeypatch)
    with pytest.raises(agentd.WorkstationError) as e:
        system.run_as(BOB)
    assert e.value.code == "not_found"


def test_what_the_daemon_made_is_given_to_the_account_only_inside_its_home(tmp_path, monkeypatch):
    system = _system(tmp_path, monkeypatch, sudo_default=True)
    uid = system.registry.uid_for(ANN)
    home = system.home(ANN)
    (home / "sub").mkdir(parents=True)
    inside, outside = home / "sub" / "f", tmp_path / "etc-hosts"
    inside.write_text("x")
    outside.write_text("y")
    chowned = []
    monkeypatch.setattr(os, "chown", lambda p, u, g, **kw: chowned.append((str(p), u, g)))
    # sudo on: written as root; inside the home it becomes the account's,
    # outside it stays root's, like `sudo tee`.
    system.own(ANN, [inside, outside])
    assert chowned == [(str(inside), uid, uid)]
    # sudo off: written as the account already, so nothing is chowned —
    # a chown of a path the account controls is the race `acting_as` closes.
    chowned.clear()
    system.set_sudo(False)
    with _acting(system, ANN):
        system.own(ANN, [inside])
    assert chowned == []


@contextmanager
def _acting(system, account):
    """The bookkeeping `acting_as` does, without changing this process's
    identity (the cases that do are the root-only ones below)."""
    system._acting.account = account
    try:
        yield
    finally:
        system._acting.account = None


def test_a_display_that_will_not_start_does_not_take_ensure_down(tmp_path, monkeypatch):
    system = _system(tmp_path, monkeypatch)
    system.registry.uid_for(ANN)

    class Broken:
        def start(self):
            raise OSError("no Xvfb here")

    monkeypatch.setattr(system, "screen", lambda account: Broken())
    assert system.wake(ANN) is None


# ── reset kills what the account left running ────────────────────────────────

def _proc(root, pid, uids, state="S"):
    d = root / str(pid)
    d.mkdir()
    (d / "status").write_text(f"Name:\tx\nState:\t{state} (x)\nUid:\t{uids}\nGid:\t0\t0\t0\t0\n")


def test_reset_kills_every_process_the_account_owns_and_nothing_else(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    _proc(proc, 101, "20000\t20000\t20000\t20000")   # the account's shell
    _proc(proc, 102, "0\t0\t0\t0")                   # the daemon
    _proc(proc, 103, "0\t20000\t0\t20000")           # effective uid is the account's
    _proc(proc, 104, "20000\t20000\t20000\t20000", state="Z")  # already dead
    _proc(proc, 105, "20001\t20001\t20001\t20001")   # somebody else
    (proc / "self").mkdir()
    killed = []

    def kill(pid, sig):
        assert sig == signal.SIGKILL
        killed.append(pid)
        shutil.rmtree(proc / str(pid))

    assert ubuntu.kill_processes(20_000, proc=proc, kill=kill, pause=0) == 2
    assert sorted(killed) == [101, 103]


# ── the display ──────────────────────────────────────────────────────────────

def test_the_display_number_is_read_to_its_newline_so_xvfb_can_finish_writing_it():
    """Xvfb writes the number and the newline in two calls and dies if the
    second fails. Closing the pipe after the first read killed displays it had
    just started (measured in the image, one start in several)."""
    read_fd, write_fd = os.pipe()
    outcome = {}

    def xvfb():
        os.write(write_fd, b"7")
        time.sleep(0.2)
        try:
            os.write(write_fd, b"\n")
            outcome["second_write"] = "ok"
        except BrokenPipeError:
            outcome["second_write"] = "EPIPE — the server would exit"
        os.close(write_fd)

    writer = threading.Thread(target=xvfb)
    writer.start()
    try:
        assert ubuntu.read_display_number(read_fd, 5.0) == "7"
    finally:
        os.close(read_fd)
        writer.join()
    assert outcome["second_write"] == "ok"


def test_a_server_that_never_answers_is_a_timeout_not_a_hang():
    read_fd, write_fd = os.pipe()
    try:
        started = time.monotonic()
        assert ubuntu.read_display_number(read_fd, 0.3) == ""
        assert time.monotonic() - started < 2
    finally:
        os.close(read_fd)
        os.close(write_fd)


def _parse_xauth(data):
    out, i = [], 0
    while i < len(data):
        family, = struct.unpack(">H", data[i:i + 2])
        i += 2
        fields = []
        for _ in range(4):
            n, = struct.unpack(">H", data[i:i + 2])
            fields.append(data[i + 2:i + 2 + n])
            i += 2 + n
        out.append((family, *fields))
    return out


def test_the_display_key_is_one_wildcard_cookie(tmp_path):
    cookie = bytes(range(16))
    entry = ubuntu.xauthority_entry(cookie)
    assert _parse_xauth(entry) == [(0xFFFF, b"", b"", b"MIT-MAGIC-COOKIE-1", cookie)]
    if shutil.which("xauth"):
        path = tmp_path / "Xauthority"
        path.write_bytes(entry)
        listed = subprocess.run(["xauth", "-f", str(path), "list"], capture_output=True, text=True)
        assert cookie.hex() in listed.stdout and "MIT-MAGIC-COOKIE-1" in listed.stdout


def _argv(**body):
    return ubuntu.xdotool_argv(agentd._validated_action(body))


HOLD = ["mousedown", "1", "sleep", "0.05", "mouseup", "1"]


@pytest.mark.parametrize("body, argv, stdin", [
    ({"action": "click", "x": 10, "y": 20},
     ["xdotool", "mousemove", "10", "20", "sleep", "0.05", *HOLD], None),
    ({"action": "double_click", "x": 1, "y": 2},
     ["xdotool", "mousemove", "1", "2", "sleep", "0.05", *HOLD, "sleep", "0.08", *HOLD], None),
    ({"action": "triple_click", "x": 1, "y": 2},
     ["xdotool", "mousemove", "1", "2", "sleep", "0.05",
      *HOLD, "sleep", "0.08", *HOLD, "sleep", "0.08", *HOLD], None),
    ({"action": "right_click", "x": 5, "y": 6},
     ["xdotool", "mousemove", "5", "6", "sleep", "0.05",
      "mousedown", "3", "sleep", "0.05", "mouseup", "3"], None),
    ({"action": "middle_click", "x": 5, "y": 6},
     ["xdotool", "mousemove", "5", "6", "sleep", "0.05",
      "mousedown", "2", "sleep", "0.05", "mouseup", "2"], None),
    ({"action": "move", "x": 1279, "y": 799}, ["xdotool", "mousemove", "1279", "799"], None),
    ({"action": "drag", "x": 1, "y": 2, "to_x": 30, "to_y": 40},
     ["xdotool", "mousemove", "1", "2", "sleep", "0.05", "mousedown", "1", "sleep", "0.1",
      "mousemove", "30", "40", "sleep", "0.1", "mouseup", "1"], None),
    ({"action": "mouse_down"}, ["xdotool", "mousedown", "1"], None),
    ({"action": "mouse_up", "x": 3, "y": 4},
     ["xdotool", "mousemove", "3", "4", "sleep", "0.05", "mouseup", "1"], None),
    ({"action": "scroll", "x": 1, "y": 2, "dy": 3},
     ["xdotool", "mousemove", "1", "2", "sleep", "0.05",
      "click", "--repeat", "3", "--delay", "30", "5"], None),
    ({"action": "scroll", "x": 1, "y": 2, "dy": -2, "dx": 4},
     ["xdotool", "mousemove", "1", "2", "sleep", "0.05",
      "click", "--repeat", "2", "--delay", "30", "4",
      "click", "--repeat", "4", "--delay", "30", "7"], None),
    ({"action": "type", "text": "-rf / \n"},
     ["xdotool", "type", "--delay", "12", "--file", "-"], b"-rf / \n"),
    ({"action": "key", "keys": "ctrl+l Return"},
     ["xdotool", "key", "--clearmodifiers", "--delay", "40", "ctrl+l", "Return"], None),
])
def test_each_input_becomes_the_xdotool_command_that_does_it(body, argv, stdin):
    assert _argv(**body) == (argv, stdin)


def test_every_protocol_action_but_wait_reaches_the_display():
    """`wait` is agentd's own sleep; every other action must map, so a new
    one added to the protocol fails here until the display can do it."""
    minimal = {"x": 1, "y": 1, "to_x": 2, "to_y": 2, "dy": 1, "text": "a", "keys": "a"}
    for action in P.INPUT_ACTIONS:
        if action == "wait":
            continue
        argv, _ = _argv(action=action, **minimal)
        assert argv[0] == "xdotool" and len(argv) > 1, action


def test_long_text_is_typed_fast_enough_to_finish():
    argv, stdin = _argv(action="type", text="x" * P.MAX_TYPE_CHARS)
    delay = int(argv[argv.index("--delay") + 1])
    assert delay * P.MAX_TYPE_CHARS / 1000 <= 25 and len(stdin) == P.MAX_TYPE_CHARS


# ── the daemon acts as the account (root: this is about the kernel) ──────────

@pytest.fixture
def open_dir():
    """A directory another uid can traverse — pytest's own tmp root is 0700."""
    path = Path(tempfile.mkdtemp(prefix="pantheon-ws-"))
    os.chmod(path, 0o755)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@needs_root
def test_acting_as_an_account_is_that_accounts_access_on_this_thread_only(open_dir):
    secret = open_dir / "root-only"
    secret.write_text("root's")
    os.chmod(secret, 0o600)
    mine = open_dir / "mine"
    mine.mkdir()
    os.chown(mine, STRANGER, STRANGER)
    other_thread = {}
    inside = threading.Event()
    done = threading.Event()

    def elsewhere():
        inside.wait(5)
        other_thread["read"] = secret.read_text()  # still root over here
        done.set()

    t = threading.Thread(target=elsewhere)
    t.start()
    with ubuntu.fs_identity(STRANGER, STRANGER):
        (mine / "made").write_text("x")
        with pytest.raises(PermissionError):
            secret.read_text()
        inside.set()
        done.wait(5)
    t.join()
    assert other_thread["read"] == "root's"
    assert (mine / "made").stat().st_uid == STRANGER
    assert secret.read_text() == "root's"  # and back to root after


class _AccountFiles(agentd.SingleUserSystem):
    """The single-user system with `UbuntuSystem`'s file identity: every file
    operation is the stranger uid's. What is under test is agentd using it."""

    def acting_as(self, account):
        return ubuntu.fs_identity(STRANGER, STRANGER)


@contextmanager
def _serving(system):
    server = agentd.make_server(system, "pws_t", bind="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    try:
        yield WorkstationClient("http://127.0.0.1:%d" % server.server_address[1], "pws_t")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


@pytest.fixture
def stranger_station(open_dir, monkeypatch):
    homes = open_dir / "homes"
    system = _AccountFiles(homes)
    run(asyncio.sleep(0))
    system.ensure(ANN)
    os.chown(system.home(ANN), STRANGER, STRANGER)
    os.chmod(system.home(ANN), 0o700)
    outside = open_dir / "etc"
    outside.mkdir()
    with _serving(system) as client:
        yield client, system, outside, monkeypatch


def _escape_to(monkeypatch, target):
    """What a directory swapped for a symlink between the jail check and the
    open does: `resolve` said the path was inside; the open lands outside."""
    real = agentd.Workstation.resolve

    def resolve(self, account, raw, **kw):
        return target if raw == "escape" else real(self, account, raw, **kw)

    monkeypatch.setattr(agentd.Workstation, "resolve", resolve)


@needs_root
def test_a_write_that_escaped_the_jail_check_is_still_refused_by_the_kernel(stranger_station):
    client, system, outside, monkeypatch = stranger_station
    _escape_to(monkeypatch, outside / "sudoers-evil")
    with pytest.raises(ClientError) as e:
        run(client.write(ANN, "escape", "pw-evil ALL=(ALL) NOPASSWD: ALL\n"))
    assert e.value.code == "forbidden" and e.value.status == 403
    assert not (outside / "sudoers-evil").exists()
    # And an honest write lands as the account, not as root.
    run(client.write(ANN, "notes/a.txt", "hello"))
    made = system.home(ANN) / "notes" / "a.txt"
    assert made.stat().st_uid == STRANGER and made.parent.stat().st_uid == STRANGER


@needs_root
def test_a_read_that_escaped_the_jail_check_is_still_refused_by_the_kernel(stranger_station):
    client, system, outside, monkeypatch = stranger_station
    secret = outside / "shadow"
    secret.write_text("root:$6$...")
    os.chmod(secret, 0o600)
    _escape_to(monkeypatch, secret)
    with pytest.raises(ClientError) as e:
        run(client.read(ANN, "escape"))
    assert e.value.code == "forbidden"


@needs_root
def test_the_script_exec_runs_is_written_as_the_account(stranger_station):
    client, system, outside, monkeypatch = stranger_station
    r = run(client.exec(ANN, 'stat -c %u "$0"'))
    assert r["exit_code"] == 0 and r["stdout"].strip() == str(STRANGER)


def test_a_file_the_account_may_not_touch_is_forbidden_not_a_daemon_failure():
    """The mapping from what the filesystem said to what the protocol says,
    without which a chmod-000 file answered 500 "internal"."""
    denied = agentd._os_error(PermissionError(13, "Permission denied", "/home/x/f"))
    assert (denied.code, P.ERRORS[denied.code]) == ("forbidden", 403)
    assert "/home/x/f" in denied.message
    assert agentd._os_error(FileNotFoundError(2, "No such file", "/x")).code == "not_found"
    assert agentd._os_error(IsADirectoryError(21, "Is a directory", "/x")).code == "bad_request"


# ── ensure brings the display up ─────────────────────────────────────────────

def test_ensure_answers_the_display_the_system_woke(tmp_path):
    class Woken(agentd.SingleUserSystem):
        def wake(self, account):
            return ":7"

    station = agentd.Workstation(Woken(tmp_path / "homes"), "pws_t")
    assert station.ensure(ANN)["display"] == ":7"
    plain = agentd.Workstation(agentd.SingleUserSystem(tmp_path / "plain"), "pws_t")
    assert plain.ensure(ANN)["display"] is None


# ── the command line ─────────────────────────────────────────────────────────

def test_the_defaults_are_the_safe_ones(monkeypatch):
    for var in (cli.BIND_ENV, cli.PORT_ENV, cli.PAIRING_GID_ENV, P.PAIRING_DIR_ENV):
        monkeypatch.delenv(var, raising=False)
    args = cli.parse_args([])
    assert (args.system, args.bind, args.port) == ("single", "127.0.0.1", P.DEFAULT_PORT)
    assert args.sudo is False and args.pairing_group is None
    assert args.pairing_dir == P.DEFAULT_PAIRING_DIR
    ubuntu_args = cli.parse_args(["--system", "ubuntu"])
    assert ubuntu_args.sudo is True and ubuntu_args.homes == "/home"


def test_the_environment_fills_what_the_flags_leave(monkeypatch):
    monkeypatch.setenv(cli.PAIRING_GID_ENV, "1000")
    monkeypatch.setenv(cli.PORT_ENV, "7999")
    args = cli.parse_args(["--sudo", "off"])
    assert (args.pairing_group, args.port, args.sudo) == (1000, 7999, False)


@pytest.mark.parametrize("argv", [
    ["--system", "vm"], ["--pairing-group", "0"], ["--pairing-group", "staff"],
    ["--sudo", "maybe"], ["--port", "70000"],
])
def test_a_bad_flag_is_refused_before_anything_starts(argv, capsys):
    with pytest.raises(SystemExit) as e:
        cli.parse_args(argv)
    assert e.value.code == 2


def test_the_ubuntu_system_says_it_needs_root_rather_than_half_starting(tmp_path, monkeypatch,
                                                                        caplog):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr(ubuntu, "_run_root", lambda argv: pytest.fail(f"ran {argv}"))
    code = cli.main(["--system", "ubuntu", "--homes", str(tmp_path / "homes"),
                     "--pairing-dir", str(tmp_path / "pair"), "--port", "0"])
    assert code == 2
    assert "runs as root" in caplog.text
    assert not (tmp_path / "pair").exists()  # no token minted for a daemon that never ran


def test_a_pairing_group_an_account_owns_stops_the_daemon(tmp_path):
    reg = _registry(tmp_path)
    uid = reg.uid_for(ANN)

    class WithRegistry:
        registry = reg

    with pytest.raises(agentd.WorkstationError) as e:
        cli.check_pairing_group(WithRegistry(), uid)
    assert ANN in e.value.message
    cli.check_pairing_group(WithRegistry(), uid + 1)  # anything else is fine


def test_the_daemon_starts_pairs_answers_and_stops_from_the_command_line(tmp_path):
    """`python3 -m workstation` as the image runs it, minus root: it logs to
    stdout, writes the token where Pantheon reads it, readable by the pairing
    group only, answers the real client, and stops cleanly on SIGTERM."""
    pairing = tmp_path / "pairing"
    argv = [sys.executable, "-m", "workstation", "--system", "single", "--port", "0",
            "--homes", str(tmp_path / "homes"), "--pairing-dir", str(pairing)]
    if IS_ROOT:
        argv += ["--pairing-group", "4242"]
    env = {k: v for k, v in os.environ.items() if k != P.TOKEN_ENV}
    proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    try:
        line = proc.stdout.readline()
        m = re.search(r"listening on 127\.0\.0\.1:(\d+)", line)
        assert m, line
        token = (pairing / P.TOKEN_FILENAME).read_text().strip()
        assert token.startswith(P.TOKEN_PREFIX) and token not in line
        client = WorkstationClient(f"http://127.0.0.1:{m.group(1)}", token)
        assert run(client.health())["sudo"] is False
        assert run(client.exec(ANN, "echo hi"))["stdout"] == "hi\n"
        tok_stat, dir_stat = (pairing / P.TOKEN_FILENAME).stat(), pairing.stat()
        if IS_ROOT:
            assert (tok_stat.st_uid, tok_stat.st_gid, stat.S_IMODE(tok_stat.st_mode)) == (0, 4242, 0o640)
            assert (dir_stat.st_gid, stat.S_IMODE(dir_stat.st_mode)) == (4242, 0o750)
        else:
            assert stat.S_IMODE(tok_stat.st_mode) == 0o600
            assert stat.S_IMODE(dir_stat.st_mode) == 0o700
        proc.send_signal(signal.SIGTERM)
        rest, _ = proc.communicate(timeout=15)
        assert proc.returncode == 0 and "workstation stopping" in rest
        assert token not in rest
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


# ── the compose overlay, as compose itself resolves it ───────────────────────

def _compose(pgid="1234"):
    if not shutil.which("docker"):
        pytest.skip("the docker CLI is not installed here")
    env = {k: v for k, v in os.environ.items() if k not in ("COMPOSE_FILE", "PGID")}
    env["PGID"] = pgid
    done = subprocess.run(["docker", "compose", "-f", "docker-compose.yml", "-f",
                           "docker/workstation.yml", "config", "--format", "json"],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    if done.returncode != 0 and "is not a docker command" in done.stderr:
        pytest.skip("docker compose is not installed here")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _mounts(service):
    return [(m.get("type"), m.get("source"), m.get("target"), bool(m.get("read_only")))
            for m in service.get("volumes", [])]


def test_the_overlay_gives_the_workstation_its_volumes_and_nothing_of_the_hosts():
    """No Docker socket, not privileged, no added capability, no published
    port, and no volume but its own two — asked of compose's own merge of the
    two files, which is what `docker compose up` runs."""
    cfg = _compose()
    ws = cfg["services"]["workstation"]
    assert ws["build"]["context"] == str(ROOT / "workstation")
    assert ws["command"][:2] == ["--system", "ubuntu"]
    assert _mounts(ws) == [("volume", "workstation-homes", "/home", False),
                           ("volume", "workstation-pairing", P.DEFAULT_PAIRING_DIR, False)]
    assert not ws.get("privileged") and not ws.get("cap_add") and not ws.get("ports")
    assert not ws.get("devices") and ws.get("network_mode") in (None, "")
    assert int(ws["shm_size"]) >= 1 << 30  # Firefox's tabs share memory through it
    assert ws.get("healthcheck", {}).get("test")


def test_pantheon_finds_the_workstation_and_reads_its_token_with_nothing_typed():
    cfg = _compose(pgid="1234")
    pantheon, ws = cfg["services"]["pantheon"], cfg["services"]["workstation"]
    assert pantheon["environment"][P.URL_ENV] == f"http://{P.DEFAULT_HOST}:{P.DEFAULT_PORT}"
    assert ("volume", "workstation-pairing", P.DEFAULT_PAIRING_DIR, True) in _mounts(pantheon)
    # The token is readable by the group Pantheon runs as, from one setting.
    assert pantheon["environment"]["PGID"] == ws["environment"][cli.PAIRING_GID_ENV] == "1234"
    others = [name for name, svc in cfg["services"].items() if name not in ("pantheon", "workstation")
              and any(src in ("workstation-pairing", "workstation-homes")
                      for _, src, _, _ in _mounts(svc))]
    assert others == []
