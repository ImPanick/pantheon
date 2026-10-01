# SPDX-License-Identifier: AGPL-3.0-or-later
"""The VM backend's host with machines a test can see into — `B974`, `B979`,
`B984`, `B992`.

`LocalMachine` (`tests/test_every_workstation_backend_answers_alike.py`) runs
each person's "machine" as the real daemon in its own process. These run the
same daemon (`workstation/agentd.py`, its own HTTP layer, its own token) in
this process instead, so a test can give a machine what only a VM has and a
test machine does not — a screen that counts its grabs, a clock it can move, a
network layer it says it holds — behind the daemon's own `Screen` and `System`
interfaces. Everything between Pantheon and the machine's daemon is the
shipped code: `vm.Fleet`, `vm.VmStation`, the forwarding, the per-machine
token. What stands in is the hypervisor, and the machine's own kernel.
"""
from __future__ import annotations

import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from tests.helpers.workstation_daemon import PictureScreen
from workstation import protocol as P
from workstation import vm
from workstation.agentd import SingleUserSystem, make_server

HOST_TOKEN = "pws_the-vm-host-token-pantheon-holds"


class CountingScreen(PictureScreen):
    """A display that counts its grabs and can say, like the Ubuntu display's
    damage watch, whether anything was drawn since a mark (`Screen.mark`).
    `draw()` is something drawn with no input — a program's own output."""

    can_tell = True

    def __init__(self, account: str):
        super().__init__(account)
        self.grabs = 0
        self.asked = 0
        self._drawn = 0     # drawing done (what DAMAGE reports)
        self.content = 0    # what the pixels are: drawing can put them back

    def grab(self, fmt: str):
        self.grabs += 1
        return super().grab(fmt)

    def send(self, action: Dict) -> None:
        super().send(action)
        self._drawn += 1
        self.content += 1

    def draw(self, content: Optional[int] = None) -> None:
        """Something drawn; `content` puts the pixels back to an earlier
        picture (a blink, a redraw of the same thing)."""
        self.actions.append({"action": "drawn"})  # the picture changes with it
        self._drawn += 1
        self.content = self.content + 1 if content is None else content

    # Like `xdamage.DamageWatch`: a frame is trusted only if nothing at all
    # was drawn while it was taken, and later the drawn pixels are compared.
    def mark(self):
        return ("mark", self._drawn, self.content) if self.can_tell else None

    def settle(self, mark):
        return mark if mark is not None and mark[1] == self._drawn else None

    def unchanged(self, mark) -> bool:
        self.asked += 1
        return mark is not None and mark[2] == self.content


class GuestSystem(SingleUserSystem):
    """What a machine's daemon runs on: one user, `--backend vm`, a screen
    per person — and, for the rows that need them, a clock that is the host's
    plus a drift the test sets, and a network layer the test says it holds."""

    def __init__(self, root: Path, *, holds_network: bool = True) -> None:
        super().__init__(root, screen_factory=CountingScreen, backend="vm")
        self.drift = 0.0
        self.steps: List[float] = []
        self.holds_network = holds_network
        self.network_in_force: Optional[str] = None

    # `B984`: the machine's clock, as far as the daemon can see it.
    def clock_now(self) -> float:
        return time.time() + self.drift

    def step_clock(self, seconds: float) -> None:
        self.steps.append(seconds)
        self.drift += seconds

    # `B992`: the accounts layer a real machine holds with nft.
    def set_network(self, mode: str) -> None:
        super().set_network(mode)
        self.network_in_force = mode if self.holds_network else None

    def network_report(self) -> Dict:
        out = super().network_report()
        if self.network_in_force is not None:
            out.update(network_in_force=self.network_in_force, network_enforcement="accounts")
        return out


class InProcessMachine(vm.Machine):
    """A person's machine: the daemon, in this process, on a port of its own."""

    holds_network = True  # what a machine made from the current image does

    def __init__(self, fleet: vm.Fleet, account: str) -> None:
        self.fleet, self.account = fleet, account
        self.dir = fleet.state / "machines" / account
        self.port: Optional[int] = None
        self.token = ""
        self.server = None
        self.system: Optional[GuestSystem] = None
        self.starts = 0
        self.stops: List[bool] = []          # graceful, per stop
        self.argv: List[str] = []            # QEMU's command line, had it been QEMU

    def exists(self) -> bool:
        return (self.dir / "homes").is_dir()

    def running(self) -> bool:
        return self.server is not None

    def start(self) -> None:
        if self.running():
            return
        (self.dir / "homes").mkdir(parents=True, exist_ok=True)
        self.token = vm.mint_machine_token(self.dir / "token")
        self.system = GuestSystem(self.dir / "homes", holds_network=self.holds_network)
        self.server = make_server(self.system, self.token, bind="127.0.0.1", port=0)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02},
                         daemon=True).start()
        self.port = self.server.server_address[1]
        # What QEMU would have been started with, had this been QEMU (`B992`).
        self.argv = self.fleet.machine_argv(self) if hasattr(self.fleet, "machine_argv") else []
        self.starts += 1

    def stop(self, *, graceful: bool = True) -> None:
        server, self.server, self.port = self.server, None, None
        if server is not None:
            server.shutdown()
            server.server_close()
            self.stops.append(graceful)

    def destroy(self) -> None:
        self.stop(graceful=False)
        shutil.rmtree(self.dir, ignore_errors=True)

    def screen(self) -> CountingScreen:
        assert self.system is not None
        return self.system.screen(self.account)  # type: ignore[return-value]


@contextmanager
def vm_host(state: Path, *, factory=InProcessMachine, **fleet_kw) -> Iterator[tuple]:
    """`(fleet, url)`: the VM host answering on a free local port."""
    fleet_kw.setdefault("start_timeout", 30.0)
    fleet = vm.Fleet(state, accel="kvm", need_image=False, machine_factory=factory, **fleet_kw)
    server = make_server(fleet, HOST_TOKEN, bind="127.0.0.1", port=0,
                         station=vm.VmStation(fleet, HOST_TOKEN))
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02},
                     daemon=True).start()
    try:
        yield fleet, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        for m in list(fleet._machines.values()):
            m.stop()


__all__ = ["CountingScreen", "GuestSystem", "HOST_TOKEN", "InProcessMachine", "P", "vm_host"]
