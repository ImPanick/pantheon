# SPDX-License-Identifier: AGPL-3.0-or-later
"""An Android phone is given enough memory to boot.

The owner's real-machine run on Windows (2026-11-13): Android would not run
with 2 GiB and needs 8 to 12 GiB. Every way Pantheon starts a phone (the
native host worker on macOS, Windows and Linux, and the phone inside a
person's VM) now starts at 8 GiB, sized up to 12 GiB on a host that has the
room, and never past what the host can give while it keeps some for itself.
"""
from pathlib import Path
import json
import types

import pytest

from workstation import phone as PH

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("total_mib,expected", [
    (None, 8192),          # host memory unknown: the floor
    (16384, 8192),         # 16 GiB host
    (32768, 8192),         # a quarter of 32 GiB is 8 GiB
    (40960, 10240),        # a quarter of 40 GiB
    (49152, 12288),        # 48 GiB reaches the ceiling
    (131072, 12288),       # never more than 12 GiB by default
    (8192, 4096),          # a host this small keeps 4 GiB for itself
])
def test_a_phone_is_sized_to_its_host_between_8_and_12_gib(total_mib, expected):
    assert PH.default_memory_mib(total_mib) == expected


def test_a_phone_in_a_persons_vm_starts_at_8_gib(monkeypatch):
    monkeypatch.delenv(PH.MEMORY_ENV, raising=False)
    phones = PH.Phones(types.SimpleNamespace(backend="vm"))
    assert phones.memory_mib == 8192
    assert PH.DEFAULT_MEMORY_MIB == 8192


def test_an_operator_can_still_choose_the_phone_memory(monkeypatch):
    monkeypatch.setenv(PH.MEMORY_ENV, "12288")
    assert PH.Phones(types.SimpleNamespace(backend="vm")).memory_mib == 12288


@pytest.mark.parametrize("compose", ["docker-compose.yml", "docker-compose.gpu-amd.yml",
                                     "docker-compose.gpu-nvidia.yml"])
def test_compose_does_not_pin_the_phone_back_to_2_gib(compose):
    text = (ROOT / compose).read_text()
    assert "PANTHEON_PHONE_MEMORY_MIB=${PANTHEON_PHONE_MEMORY_MIB:-8192}" in text
    assert "PANTHEON_PHONE_MEMORY_MIB:-2048" not in text


def _native_host(config, total_mib, monkeypatch):
    from workstation.native_android import host as H
    monkeypatch.setattr(H.psutil, "virtual_memory",
                        lambda: types.SimpleNamespace(total=total_mib * 1024 * 1024))
    host = object.__new__(H.Host)
    host.config = config
    return host


def test_the_native_host_sizes_the_phone_to_the_machine(monkeypatch):
    pytest.importorskip("psutil")
    assert _native_host({}, 65536, monkeypatch).phone_memory_mib() == 12288
    assert _native_host({}, 16384, monkeypatch).phone_memory_mib() == 8192


def test_the_native_host_keeps_an_operators_own_choice(monkeypatch):
    pytest.importorskip("psutil")
    assert _native_host({"memory_mib": 10240}, 65536, monkeypatch).phone_memory_mib() == 10240


def test_configure_no_longer_writes_the_old_4_gib_default(tmp_path, monkeypatch):
    from workstation.native_android import configure as C
    state = tmp_path / "state"
    state.mkdir()
    (state / "host-config.json").write_text(json.dumps({"memory_mib": 4096, "max_running": 1}))
    sdk = tmp_path / "sdk"
    sdk.mkdir()
    radio = tmp_path / "netsimd"
    radio.write_text("")
    monkeypatch.setattr(C, "accepted", lambda root, abi: True)
    monkeypatch.setattr(C, "sha", lambda path: C.SERVER_SHA256)
    monkeypatch.setattr(C, "console_path", lambda config, root: None)
    _, config = C.prepare(state=state, sdk=sdk, radio_binary=radio, scrcpy_server=tmp_path / "scrcpy")
    assert "memory_mib" not in config
    fresh = tmp_path / "fresh"
    _, config = C.prepare(state=fresh, sdk=sdk, radio_binary=radio, scrcpy_server=tmp_path / "scrcpy")
    assert "memory_mib" not in config
