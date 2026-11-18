# SPDX-License-Identifier: AGPL-3.0-or-later
"""A phone proves its control listener is its own when the host hides sockets.

Seen on the owner's Windows host (2026-11-18, Docker Desktop) from a shell
running as the phone service's user: the emulator's executable was readable
but its open sockets were not (psutil AccessDenied). A later audit found that
shell had the service's user but not its group (`docker exec -u 500`), which
is what hid them; the service itself read them, and what made every control
connection say "The Android control listener no longer belongs to this VM"
there was the host's stepping clock
(`test_a_phone_stays_its_vms_own_when_the_clock_steps.py`). This proof stays
for a host that does hide another process's sockets from the service.

Pinned here: with the sockets hidden, the phone is attested by the kernel's
listener table plus the emulator console, which must accept this account's
own token and name this account's AVD. Another account's emulator, a foreign
listener on the port, or a wrong AVD never pass.
"""
from __future__ import annotations

import logging
import socket
import threading
import time as real_time
from types import SimpleNamespace

import pytest

from workstation.native_android import host as H
from workstation.native_android.adb import AdbError

UID = 500


class Gone(Exception):
    """psutil.Error, without needing psutil installed (CI's lean leg has none)."""


class Denied(Gone):
    """psutil.AccessDenied: the host hides another process's open sockets."""


FAKE_PSUTIL = SimpleNamespace(Error=Gone, AccessDenied=Denied, CONN_LISTEN="LISTEN")


class Console:
    """The emulator console on 127.0.0.1, as the Android emulator answers it."""

    def __init__(self, token, avd):
        self.token, self.avd, self.connections = token, avd, 0
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            self.connections += 1
            with connection:
                connection.sendall(b"Android Console: Authentication required\r\nOK\r\n")
                authed = False
                for line in connection.makefile("rb"):
                    line = line.decode().strip()
                    if line.startswith("auth "):
                        authed = line[5:] == self.token
                        connection.sendall(b"\r\nOK\r\n" if authed else b"KO: authentication token does not match\r\n")
                    elif line == "avd name" and authed:
                        connection.sendall(self.avd.encode() + b"\r\nOK\r\n")
                    else:
                        connection.sendall(b"KO: unknown command\r\n")

    def close(self):
        self.server.close()


class HiddenEmulator:
    """An emulator process whose sockets the service may not list."""

    def __init__(self, sdk, uid=UID):
        self.pid, self._exe, self._uid = 4242, str(sdk / "emulator/qemu/linux-x86_64/qemu-system-x86_64-headless"), uid

    def exe(self):
        return self._exe

    def net_connections(self, kind):
        raise Denied(self.pid)

    def uids(self):
        return SimpleNamespace(real=self._uid, effective=self._uid, saved=self._uid)


def _table(tmp_path, listeners):
    """Write /proc/net/tcp and tcp6 with LISTEN rows for {port: uid}."""
    head = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    rows4 = [f"   {i}: 0100007F:{port:04X} 00000000:0000 0A 00000000:00000000 00:00000000 00000000 {uid:5d}        0 {9000 + i} 1"
             for i, (port, uid) in enumerate(listeners.items())]
    rows6 = [f"   {i}: 00000000000000000000000001000000:{port:04X} 00000000000000000000000000000000:0000 0A "
             f"00000000:00000000 00:00000000 00000000 {uid:5d}        0 {9100 + i} 1"
             for i, (port, uid) in enumerate(listeners.items())]
    net = tmp_path / "proc-net"
    net.mkdir(exist_ok=True)
    (net / "tcp").write_text(head + "\n".join(rows4) + "\n")
    (net / "tcp6").write_text(head + "\n".join(rows6) + "\n")
    return net


@pytest.fixture
def phone(tmp_path, monkeypatch):
    home = tmp_path / "owner"
    home.mkdir()
    (home / ".emulator_console_auth_token").write_text("this-accounts-token\n")
    system = SimpleNamespace(config={}, sdk=tmp_path / "sdk", abi="x86_64", why=None, home=lambda _: home)
    monkeypatch.setattr(H, "psutil", FAKE_PSUTIL)
    made = H.NativePhone(system, "owned", None)
    made.avd = "pantheon_owned_pixel"
    made.process_identity = 1.0
    emulator = HiddenEmulator(system.sdk)
    monkeypatch.setattr(made, "_process_family", lambda: [emulator])
    monkeypatch.setattr(H, "console_path", lambda config, owner_home: owner_home / ".emulator_console_auth_token")
    consoles = []

    def serve(token="this-accounts-token", avd="pantheon_owned_pixel", adb_uid=UID, console_uid=UID):
        console = Console(token, avd)
        consoles.append(console)
        made.port = console.port
        monkeypatch.setattr(H, "PROC_NET", _table(tmp_path, {console.port: console_uid, console.port + 1: adb_uid}))
        return console
    made.serve = serve
    yield made
    for console in consoles:
        console.close()


def test_hidden_sockets_still_prove_this_accounts_listener(phone):
    console = phone.serve()
    assert phone._owned(), "the owner's phone must attest when only its sockets are hidden"
    assert phone._owned()
    assert console.connections == 1, "a pass is kept for the same emulator"


def test_another_accounts_emulator_on_the_port_does_not_pass(phone):
    phone.serve(token="another-accounts-token")
    assert not phone._owned()


def test_a_different_avd_on_the_console_does_not_pass(phone):
    phone.serve(avd="pantheon_someone_else")
    assert not phone._owned()


def test_a_foreign_listener_on_the_adb_port_does_not_pass_and_gets_no_token(phone):
    console = phone.serve(adb_uid=0)
    assert not phone._owned()
    assert console.connections == 0, "the token is never sent while the ports are not the emulator's"


def test_a_foreign_listener_on_the_console_port_gets_no_token(phone):
    console = phone.serve(console_uid=1234)
    assert not phone._owned()
    assert console.connections == 0


def test_a_new_emulator_proves_itself_again(phone):
    console = phone.serve()
    assert phone._owned()
    phone.process_identity = 2.0
    assert phone._owned()
    assert console.connections == 2


def test_console_operations_work_with_hidden_sockets(phone, monkeypatch):
    phone.serve()
    phone.screen = SimpleNamespace(release_all=lambda: None)
    with pytest.raises(AdbError, match="refused"):  # the fake console knows no rotate; ownership passed
        phone.console(["rotate"], 3)


# ---- a phone that never answers says why, in the log and in its failure ----

def test_a_phone_pantheon_never_reaches_names_why(tmp_path, monkeypatch, caplog):
    system = SimpleNamespace(config={}, sdk=tmp_path / "sdk", abi="x86_64", why=None, home=lambda _: tmp_path)
    phone = H.NativePhone(system, "owned", None)
    phone.state, phone.boot_phase = "starting", "emulator"
    phone.emulator = proc = SimpleNamespace(poll=lambda: None)

    def shell(args, **kw):
        raise AdbError("The Android control listener no longer belongs to this VM.")
    phone.direct = SimpleNamespace(shell=shell)
    monkeypatch.setattr(phone, "_stop_locked", lambda: setattr(phone, "emulator", None))
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    def monotonic():
        now[0] += 0.01
        return now[0]
    monkeypatch.setattr(H, "time", SimpleNamespace(monotonic=monotonic, sleep=sleep, time=real_time.time))
    with caplog.at_level(logging.WARNING, logger=H.__name__):
        phone._boot(proc)
    assert phone.state == "unavailable"
    assert "never reached Android" in phone.why and "no longer belongs" in phone.why
    assert caplog.text.count("cannot reach Android yet") == 1, "logged once, after a minute, not every retry"
