# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1141` — two concurrent detections mixed their hosts, and cached the mix.

`services/hwfit/hardware.detect_system` wrote `_remote_host`/`_remote_port`/
`_remote_platform` at module level and `_run` read `_remote_host` to choose SSH
or a local `subprocess.run`; the hwfit handlers are sync, so FastAPI runs them
on its thread pool. Measured by the row with the transports stubbed: a remote
detection alone made 10 SSH calls and 0 local; started 120 ms before a local
detection on another thread, it made 4 SSH calls and then 3 local ones — the
serving host's `nvidia-smi` among them — and that mixed answer was cached under
the remote host's key for `CACHE_TTL`.

This is that drive, as a test: the real `detect_system` on two threads, with
only the two transports stubbed (`run_ssh_command` and `subprocess.run`, as
`hardware` reaches them) to record which thread asked which machine, each call
slow enough that the two detections overlap. The remote box has 64 GB and an
RTX 4090; this machine's `nvidia-smi` answers an A100.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from services.hwfit import hardware

pytestmark = pytest.mark.skipif(hardware.os.name == "nt", reason="the local path here is the POSIX one")

_MEMINFO_64G = "MemTotal:       67108864 kB\nMemAvailable:   60000000 kB\n"


@pytest.fixture
def transports(monkeypatch):
    calls = []   # (thread name, "ssh"|"local", host or None, command)

    def ssh(host, port, cmd, **kw):
        calls.append((threading.current_thread().name, "ssh", host, cmd))
        time.sleep(0.03)
        if "meminfo" in cmd:
            return SimpleNamespace(returncode=0, stdout=_MEMINFO_64G)
        if "nvidia-smi" in cmd and "query-gpu" in cmd:
            return SimpleNamespace(returncode=0, stdout="24564, NVIDIA GeForce RTX 4090")
        return SimpleNamespace(returncode=1, stdout="")

    def local(cmd, **kw):
        text = " ".join(cmd) if isinstance(cmd, list) else cmd
        calls.append((threading.current_thread().name, "local", None, text))
        time.sleep(0.03)
        if "nvidia-smi" in text and "query-gpu" in text:
            return SimpleNamespace(returncode=0, stdout="81920, NVIDIA A100-SXM4-80GB")
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(hardware, "run_ssh_command", ssh)
    monkeypatch.setattr(hardware, "subprocess", SimpleNamespace(run=local))
    monkeypatch.setattr(hardware, "_cache_by_host", {})
    return calls


def _both(start_gap=0.12):
    out = {}

    def remote():
        out["remote"] = hardware.detect_system(host="ada@gpu-box", platform="linux", fresh=True)

    def here():
        out["local"] = hardware.detect_system(fresh=True)

    a = threading.Thread(target=remote, name="remote")
    b = threading.Thread(target=here, name="local")
    a.start()
    time.sleep(start_gap)
    b.start()
    a.join(30)
    b.join(30)
    return out


def test_a_remote_detection_alone_asks_only_the_remote_machine(transports):
    """The row's baseline: every call over SSH, to its host."""
    hardware.detect_system(host="ada@gpu-box", platform="linux", fresh=True)
    assert transports and all(kind == "ssh" and host == "ada@gpu-box"
                              for _, kind, host, _ in transports), transports


def test_two_concurrent_detections_each_run_every_command_on_their_own_machine(transports):
    """The row's `Verify:`, first half."""
    _both()
    remote = [(kind, host) for name, kind, host, _ in transports if name == "remote"]
    local = [(kind, host) for name, kind, host, _ in transports if name == "local"]
    assert remote and set(remote) == {("ssh", "ada@gpu-box")}, remote
    assert local and set(local) == {("local", None)}, local
    # They did overlap: the local detection began before the remote one ended.
    names = [name for name, *_ in transports]
    first_local = names.index("local")
    assert "remote" in names[first_local:], "the drive did not overlap the two detections"


def test_neither_caches_the_others_answer(transports):
    """The row's `Verify:`, second half — what each key holds is that machine's."""
    out = _both()
    assert out["remote"]["gpu_name"] == "NVIDIA GeForce RTX 4090", out["remote"]
    assert out["remote"]["total_ram_gb"] == 64.0
    assert out["local"]["gpu_name"] == "NVIDIA A100-SXM4-80GB", out["local"]

    cached_remote = hardware._cache_by_host[("ada@gpu-box", "", "linux")][1]
    cached_local = hardware._cache_by_host[("_local", "", "")][1]
    assert cached_remote["gpu_name"] == "NVIDIA GeForce RTX 4090"
    assert cached_local["gpu_name"] == "NVIDIA A100-SXM4-80GB"


def test_a_detection_that_fails_leaves_no_target_behind(transports, monkeypatch):
    """However a detection leaves, the next one on the same thread starts
    from no target — the context is reset in a `finally`."""
    def boom():
        raise RuntimeError("probe failed")

    monkeypatch.setattr(hardware, "_get_ram_gb", boom)
    with pytest.raises(RuntimeError):
        hardware.detect_system(host="ada@gpu-box", platform="linux", fresh=True)
    assert hardware._PROBE.get() is None
    assert hardware._host() is None
