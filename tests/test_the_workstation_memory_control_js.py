# SPDX-License-Identifier: AGPL-3.0-or-later
"""The VM workstation's memory, chosen in Settings → Workstation — driven under
node against the real module and the panel's own markup (the harness of
`tests/test_the_workstation_panel_js.py`).

The owner, 2026-11-14: *"this needs to be a setting in the platform's overall
setting to allocate RAM"*. What is pinned:

  * the control is there only when the workstation that answered is the VM
    one, which is the only one with a size to set;
  * *Automatic* says the size it is on this host and where that came from;
  * every choice writes its own key — a number of MiB, or null for
    automatic — and then asks the workstation again, which pushes it;
  * the sentence beside it says that freed memory goes back to the host, that
    a running machine starts with a new size on its next use, and when the
    size is too small for Android.
"""
from __future__ import annotations

import pytest

from test_the_workstation_panel_js import (ADMIN_UP, DAEMON, _panel, _serving,  # noqa: F401
                                           sandbox)

VM_DAEMON = {**DAEMON, "backend": "vm", "memory_mib": 10240, "memory_choice": None,
             "memory_default_mib": 10240, "memory_default_source": "auto",
             "host_memory_mib": 65536, "memory_returns_to_host": True}
SIZES = [2048, 4096, 6144, 8192, 10240, 12288, 16384, 24576, 32768]
VM_UP = {**ADMIN_UP, "daemon": VM_DAEMON,
         "settings": {**ADMIN_UP["settings"], "backend": "vm", "vm_memory_choice": None,
                      "vm_memory_sizes": SIZES}}

READ = """
const t = (id) => (byId(id) ? byId(id).textContent : null);
const memory = {
  shown: !byId('ws-vm-memory-row').hidden,
  value: byId('ws-vm-memory').value,
  options: byId('ws-vm-memory').children.map((o) => ({ value: o.value, label: o.textContent })),
  effect: byId('ws-vm-memory-effect').hidden ? null : t('ws-vm-memory-effect'),
};
"""


def _open(sandbox, status, then: str = "") -> dict:
    return _panel(sandbox, _serving("st") + """
        await mod.open();
        calls.length = 0;
    """ + then + READ + """
        console.log(JSON.stringify({ memory, after: read() }));
    """, st=status)


def test_a_vm_workstation_offers_automatic_and_the_sizes(sandbox):
    out = _open(sandbox, VM_UP)["memory"]
    assert out["shown"] is True and out["value"] == ""
    assert out["options"][0] == {"value": "", "label": "Automatic (10 GB here)"}
    assert [o["label"] for o in out["options"][1:]] == [
        "2 GB", "4 GB", "6 GB", "8 GB", "10 GB", "12 GB", "16 GB", "24 GB", "32 GB"]
    assert [o["value"] for o in out["options"][1:]] == [str(s) for s in SIZES]
    effect = out["effect"]
    assert "sized from this host's 64 GB" in effect
    assert "freed memory goes back to the host" in effect
    assert "next use" in effect
    assert "Android" not in effect, "10 GB is room for Android: nothing to warn about"


def test_automatic_set_by_the_operator_says_so(sandbox):
    status = {**VM_UP, "daemon": {**VM_DAEMON, "memory_mib": 6144, "memory_default_mib": 6144,
                                  "memory_default_source": "env"}}
    out = _open(sandbox, status)["memory"]
    assert out["options"][0]["label"] == "Automatic (6 GB here)"
    assert "PANTHEON_WORKSTATION_VM_MEMORY_MIB" in out["effect"]


def test_a_size_too_small_for_android_is_said(sandbox):
    status = {**VM_UP, "daemon": {**VM_DAEMON, "memory_mib": 4096, "memory_choice": 4096},
              "settings": {**VM_UP["settings"], "vm_memory_choice": 4096}}
    out = _open(sandbox, status)["memory"]
    assert out["value"] == "4096"
    assert "Android needs 10 GB or more" in out["effect"]


def test_a_size_not_on_the_list_is_shown_as_it_is(sandbox):
    status = {**VM_UP, "daemon": {**VM_DAEMON, "memory_mib": 20000, "memory_choice": 20000},
              "settings": {**VM_UP["settings"], "vm_memory_choice": 20000}}
    out = _open(sandbox, status)["memory"]
    assert out["value"] == "20000"
    assert {"value": "20000", "label": "20000 MiB"} in out["options"]


@pytest.mark.parametrize("value,stored", [("12288", 12288), ("", None)])
def test_a_choice_writes_its_key_and_asks_again(sandbox, value, stored):
    status = {**VM_UP, "settings": {**VM_UP["settings"], "vm_memory_choice": 4096}}
    out = _open(sandbox, status, f"""
        byId('ws-vm-memory').value = '{value}';
        byId('ws-vm-memory').dispatchEvent({{ type: 'change' }});
        await settle();
    """)["after"]
    assert [(c["method"], c["url"]) for c in out["calls"]] == [
        ("POST", "/api/auth/settings"), ("POST", "/api/workstation/check")]
    assert out["calls"][0]["body"] == {"workstation_vm_memory_mib": stored}


def test_the_container_has_no_size_to_set(sandbox):
    out = _open(sandbox, ADMIN_UP)["memory"]
    assert out["shown"] is False and out["effect"] is None
