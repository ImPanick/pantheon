# SPDX-License-Identifier: AGPL-3.0-or-later
"""The real workstation daemon, started for a test — `P20`.

Not a fake. `workstation/agentd.py` runs on a free local port with a
`SingleUserSystem` under a temporary directory, so every test that talks to
"the workstation" talks to the file that ships (`Law 20`). What stands in is
only what a test machine does not have — an X display — and it stands in behind
the daemon's own `Screen` interface:

`PictureScreen` is a 1280x800 PNG that changes with every action it is sent and
remembers the actions, so a test can assert both what the agent did and that a
screenshot taken after it is a different picture.

    from tests.helpers.workstation_daemon import running_workstation

    with running_workstation(tmp_path) as ws:
        client = WorkstationClient(ws.url, ws.token)
        ...
        ws.screen("pw-local-e3b0c442").actions   # what reached the display
"""
from __future__ import annotations

import struct
import threading
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from workstation import protocol as P
from workstation.agentd import Screen, SingleUserSystem, WorkstationError, make_server

TEST_TOKEN = "pws_test-token-for-the-workstation-daemon"


def _png(width: int, height: int, rgb) -> bytes:
    """A solid-colour PNG, standard library only."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    row = b"\x00" + bytes(rgb) * width
    raw = zlib.compress(row * height, 9)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


class PictureScreen(Screen):
    """A display a test can see into. Each action shifts the colour, so the
    next screenshot's digest differs from the last one."""

    def __init__(self, account: str):
        self.account = account
        self.actions: List[Dict] = []
        self.fail_with: Optional[str] = None

    def _colour(self):
        n = len(self.actions)
        return ((40 + n * 17) % 256, (90 + n * 29) % 256, (160 + n * 43) % 256)

    def grab(self, fmt: str):
        if self.fail_with:
            raise WorkstationError("unavailable", self.fail_with)
        # A JPEG encoder is not in the standard library; the picture a test
        # needs is the same either way, so both formats carry PNG bytes here
        # and say so in the MIME type.
        return _png(P.SCREEN_WIDTH, P.SCREEN_HEIGHT, self._colour()), "image/png"

    def send(self, action: Dict) -> None:
        if self.fail_with:
            raise WorkstationError("unavailable", self.fail_with)
        self.actions.append(dict(action))


@dataclass
class RunningWorkstation:
    url: str
    token: str
    root: Path
    system: SingleUserSystem
    server: object
    screens: Dict[str, PictureScreen] = field(default_factory=dict)

    def screen(self, account: str) -> PictureScreen:
        return self.system.screen(account)  # type: ignore[return-value]

    @property
    def station(self):
        return self.server.station  # type: ignore[attr-defined]


@contextmanager
def running_workstation(tmp_path: Path, *, token: str = TEST_TOKEN, with_screen: bool = True,
                        sudo: bool = False) -> Iterator[RunningWorkstation]:
    root = Path(tmp_path) / "workstation-homes"
    system = SingleUserSystem(root, screen_factory=PictureScreen if with_screen else None,
                              backend="container")
    system.set_sudo(sudo)
    server = make_server(system, token, bind="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield RunningWorkstation(url=f"http://{host}:{port}", token=token, root=root,
                                 system=system, server=server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
