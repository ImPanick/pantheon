# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B974`. A `304` saved the transfer, not the grab: `agentd` answered
`screenshot?if_none_match=` by taking a whole frame and hashing it, so a person
watching a still screen cost the workstation a `scrot` every ~300 ms. Now a
screen that can tell (`Screen.mark` / `settle` / `unchanged` — the Ubuntu
display, through the X server's DAMAGE extension, `workstation/xdamage.py`) is
asked first, and the grab happens only when the screen moved, cannot tell, or
the frame is older than `agentd.FRAME_TRUST_S`. The protocol does not change.

In the normal suite: the real daemon over its real HTTP layer and Pantheon's
real client, with a screen that counts its grabs (`tests/helpers/vm_fleet.py`),
and the VM backend's host passing the conditional through to a machine. Opt-in
(`PANTHEON_WORKSTATION_E2E=1`, the workstation image present): the real display
— Xvfb, JWM with its clock, xterm — with `scrot` counted where the account runs
it, through this branch's `workstation/` code.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.workstation_client import WorkstationClient, account_for
from tests.helpers import vm_fleet
from tests.helpers.vm_fleet import CountingScreen
from tests.helpers.workstation_daemon import running_workstation
from workstation import agentd
from workstation import protocol as P

ROOT = Path(__file__).resolve().parent.parent
ANN = account_for("ann")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    from tests.helpers import workstation_daemon
    monkeypatch.setattr(workstation_daemon, "PictureScreen", CountingScreen)
    with running_workstation(tmp_path) as w:
        yield w, WorkstationClient(w.url, w.token)


def test_with_the_screen_still_a_conditional_does_not_grab(ws):
    """The row's `Verify:`, driven through the protocol."""
    w, c = ws
    first = run(c.screenshot(ANN, fmt="jpeg"))
    screen = w.screen(ANN)
    assert screen.grabs == 1
    for _ in range(5):
        assert run(c.screenshot(ANN, fmt="jpeg", if_none_match=first["digest"])) is None
    assert screen.grabs == 1, "a still screen was grabbed to answer 304"
    assert screen.asked == 5


def test_a_screen_that_moved_is_grabbed_and_sent(ws):
    w, c = ws
    first = run(c.screenshot(ANN, fmt="jpeg"))
    screen = w.screen(ANN)
    screen.draw()                       # a program's own output, nothing typed
    moved = run(c.screenshot(ANN, fmt="jpeg", if_none_match=first["digest"]))
    assert moved is not None and moved["digest"] != first["digest"] and screen.grabs == 2
    # The agent's input moves it too.
    run(c.input(ANN, "click", x=5, y=5))
    last = run(c.screenshot(ANN, fmt="jpeg", if_none_match=moved["digest"]))
    assert last is not None and last["digest"] != moved["digest"] and screen.grabs == 3
    grabs = screen.grabs
    assert run(c.screenshot(ANN, fmt="jpeg", if_none_match=last["digest"])) is None
    assert screen.grabs == grabs


def test_a_screen_that_cannot_tell_grabs_every_time_as_before(ws):
    w, c = ws
    first = run(c.screenshot(ANN, fmt="jpeg"))
    screen = w.screen(ANN)
    screen.can_tell = False
    second = run(c.screenshot(ANN, fmt="jpeg"))
    for _ in range(3):
        assert run(c.screenshot(ANN, fmt="jpeg", if_none_match=second["digest"])) is None
    assert screen.grabs == 5 and screen.asked == 0
    assert first["digest"] == second["digest"]


@pytest.mark.parametrize("why", ["other-format", "other-digest", "moved-during-grab", "too-old",
                                 "reset"])
def test_the_grab_happens_whenever_the_mark_cannot_answer(ws, monkeypatch, why):
    w, c = ws
    first = run(c.screenshot(ANN, fmt="jpeg"))
    screen = w.screen(ANN)
    fmt, digest = "jpeg", first["digest"]
    if why == "other-format":
        fmt = "png"
    elif why == "other-digest":
        digest = "0" * 16
    elif why == "moved-during-grab":
        real = CountingScreen.grab

        def grab_while_drawing(self, f):
            out = real(self, f)
            self.draw()
            return out
        monkeypatch.setattr(CountingScreen, "grab", grab_while_drawing)
        first = run(c.screenshot(ANN, fmt="jpeg"))
        monkeypatch.setattr(CountingScreen, "grab", real)
        digest = first["digest"]
    elif why == "too-old":
        monkeypatch.setattr(agentd, "FRAME_TRUST_S", -1.0)
    elif why == "reset":
        run(c.reset(ANN))
        screen = w.screen(ANN)
    before = screen.grabs
    run(c.screenshot(ANN, fmt=fmt, if_none_match=digest))
    assert screen.grabs == before + 1


def test_the_vm_host_passes_the_question_to_the_machine(tmp_path):
    """On the VM backend the machine's own display answers it; the host
    neither grabs nor turns the machine's `304` into an error."""
    with vm_fleet.vm_host(tmp_path / "state") as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.health())
        first = run(c.screenshot(ANN, fmt="jpeg"))
        screen = fleet.machine_for(ANN).screen()
        for _ in range(3):
            assert run(c.screenshot(ANN, fmt="jpeg", if_none_match=first["digest"])) is None
        assert screen.grabs == 1 and screen.asked == 3
        screen.draw()
        assert run(c.screenshot(ANN, fmt="jpeg", if_none_match=first["digest"]))["digest"] \
            != first["digest"]


# ── the real display, opt-in ─────────────────────────────────────────────────

_IMAGE = os.environ.get("PANTHEON_WORKSTATION_E2E_IMAGE", "").strip() or "pantheon-workstation:e2e-test"


def _image_present() -> bool:
    if os.environ.get("PANTHEON_WORKSTATION_E2E") != "1" or not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "image", "inspect", _IMAGE], capture_output=True).returncode == 0


_REAL = r'''
import base64, json, os, sys, time, hashlib
sys.path.insert(0, "/opt/pantheon-workstation")
from pathlib import Path
from workstation.ubuntu import UbuntuSystem
from workstation.agentd import Workstation
from workstation import protocol as P
system = UbuntuSystem(Path("/home"), skeleton=Path("/etc/skel"), sudo_default=False)
station = Workstation(system, "pws_x")
acct = P.account_name("ann")
station.ensure(acct)
home = system.home(acct)
count = home / ".scrot-count"
bin_ = home / ".local" / "bin"
bin_.mkdir(parents=True, exist_ok=True)
wrapper = bin_ / "scrot"
wrapper.write_text('#!/bin/sh\necho x >> "$HOME/.scrot-count"\nexec /usr/bin/scrot "$@"\n')
os.chmod(wrapper, 0o755)
uid = system.uid(acct)
for p in (home / ".local", bin_, wrapper):
    os.chown(p, uid, uid)
def grabs():
    try:
        return len(count.read_text().split())
    except OSError:
        return 0
time.sleep(4)  # the window manager and its terminal settle
out = {}
first = station.screenshot(acct, "jpeg")
# A frame taken while something was still drawing is not trusted (`settle`);
# the next question grabs once more. Asked until one is.
for _ in range(10):
    again = station.screenshot_unless(acct, "jpeg", first["digest"])
    if again is None:
        break
    first = again
out["warm_up_grabs"] = grabs() - 1
before = grabs()
t = time.perf_counter()
answers = [station.screenshot_unless(acct, "jpeg", first["digest"]) for _ in range(20)]
for _ in range(10):
    time.sleep(0.3)
    answers.append(station.screenshot_unless(acct, "jpeg", first["digest"]))
out["still_304s"] = sum(a is None for a in answers)
out["still_grabs"] = grabs() - before
out["still_ms_each"] = round((time.perf_counter() - t - 3.0) * 1000 / 30, 3)
station.input(acct, {"action": "type", "text": "echo b974"})
before = grabs()
moved = station.screenshot_unless(acct, "jpeg", first["digest"])
out["after_typing_frame_sent"] = moved is not None and moved["digest"] != first["digest"]
out["after_typing_grabs"] = grabs() - before
# What the mark costs a grab: the same grab with the watch and without it,
# taken in turn so the host's load falls on both alike.
display = system.screen(acct)
watch = display._watch
with_watch, without = [], []
for _ in range(8):
    for keep, into in ((watch, with_watch), (None, without)):
        display._watch = keep
        t = time.perf_counter()
        station.screenshot(acct, "jpeg")
        into.append((time.perf_counter() - t) * 1000)
display._watch = watch
out["grab_ms_median"] = round(sorted(with_watch)[4], 1)
out["grab_ms_median_without_watch"] = round(sorted(without)[4], 1)
print(json.dumps(out))
'''


@pytest.mark.skipif(not _image_present(),
                    reason="the real display: PANTHEON_WORKSTATION_E2E=1 and the workstation image")
def test_on_the_real_display_a_still_screen_is_not_grabbed(tmp_path):
    """Xvfb, JWM (its clock redraws three times a second with the same
    pixels), the skeleton's terminal — and `scrot` counted where the account
    runs it, through this branch's `workstation/` mounted over the image's."""
    script = tmp_path / "real.py"
    script.write_text(_REAL)
    done = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--entrypoint", "python3",
         "-v", f"{ROOT / 'workstation'}:/opt/pantheon-workstation/workstation:ro",
         "-v", f"{script}:/real.py:ro", _IMAGE, "/real.py"],
        capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-3000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    print(out)
    assert out["still_304s"] == 30 and out["still_grabs"] == 0, out
    assert out["after_typing_frame_sent"] and out["after_typing_grabs"] == 1, out
