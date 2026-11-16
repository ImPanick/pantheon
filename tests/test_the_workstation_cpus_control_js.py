# SPDX-License-Identifier: AGPL-3.0-or-later
"""The VM machine's processors, in Settings → Workstation — driven under node
against the real module and the panel's own markup (the harness of
`tests/test_the_workstation_panel_js.py`).

The owner, 2026-11-16: *"The CPU setting should be user configurable with
whatever is available for pantheon to use (admin set)"*. What is pinned:

  * a person on the VM workstation sees their own machine's count, the
    default and every count up to the admin's pool, and nothing above it;
  * their choice is a POST of their own (`/api/workstation/cpus`), a number
    or null for the default — never a write to the admin's settings;
  * the admin sees the pool: all of the host's, or a number, written as
    `workstation_vm_cpus_max` and then pushed;
  * a workstation with no machines of its own shows neither.
"""
from __future__ import annotations

import json

from test_the_workstation_panel_js import (ADMIN_UP, DAEMON, UP, _panel,  # noqa: F401
                                           sandbox)

VM_DAEMON = {**DAEMON, "backend": "vm", "cpus_max": 12, "cpus_max_choice": None,
             "cpus_default": 2, "host_cpus": 12}
ADMIN_VM = {**ADMIN_UP, "daemon": VM_DAEMON,
            "settings": {**ADMIN_UP["settings"], "backend": "vm", "vm_cpus_max_choice": None}}
UP_VM = {**UP, "daemon": {**UP["daemon"], "backend": "vm", "cpus_max": 12}}
MINE = {"cpus": 6, "cpus_choice": 6, "cpus_default": 2, "cpus_max": 8, "running_cpus": 2,
        "sentence": "Your machine starts with 6 of the 8 processors."}

READ = """
const t = (id) => (byId(id) ? byId(id).textContent : null);
const opts = (id) => byId(id).children.map((o) => ({ value: o.value, label: o.textContent }));
const cpus = {
  mine: !byId('ws-cpus-row').hidden, mineValue: byId('ws-cpus').value, mineOptions: opts('ws-cpus'),
  mineWhy: byId('ws-cpus-why').hidden ? null : t('ws-cpus-why'),
  pool: !byId('ws-vm-cpus-row').hidden, poolValue: byId('ws-vm-cpus').value,
  poolOptions: opts('ws-vm-cpus'),
  poolEffect: byId('ws-vm-cpus-effect').hidden ? null : t('ws-vm-cpus-effect'),
};
"""


def _open(sandbox, status, mine=None, then: str = "") -> dict:
    serve = f"""
respond((call) => {{
  if (call.url === '/api/workstation/cpus' && call.method !== 'POST')
    return {json.dumps({"status": 200, "body": mine} if mine else {"status": 400, "body": {"detail": "no"}})};
  if (call.url === '/api/workstation/cpus')
    return {{ status: 200, body: {{ ...{json.dumps(mine or {})}, cpus_choice: call.body.cpus,
                                    sentence: 'chosen' }} }};
  if (call.url === '/api/workstation/status' || call.url === '/api/workstation/check')
    return {{ status: 200, body: st }};
  return {{ status: 200, body: {{}} }};
}});
"""
    return _panel(sandbox, serve + """
        await mod.open();
        await settle();
        const opened = calls.map((c) => c.url);
        calls.length = 0;
    """ + then + READ + """
        console.log(JSON.stringify({ cpus, opened, after: read() }));
    """, st=status)


def test_a_person_sees_their_own_count_up_to_the_pool(sandbox):
    out = _open(sandbox, UP_VM, MINE)["cpus"]
    assert out["mine"] is True and out["mineValue"] == "6"
    assert out["mineOptions"][0] == {"value": "", "label": "Default (2)"}
    assert [o["value"] for o in out["mineOptions"][1:]] == [str(n) for n in range(1, 9)]
    assert out["mineWhy"] == MINE["sentence"]


def test_a_persons_choice_is_their_own_post_and_not_a_setting(sandbox):
    for value, sent in (("4", 4), ("", None)):
        out = _open(sandbox, UP_VM, MINE, f"""
            byId('ws-cpus').value = '{value}';
            byId('ws-cpus').dispatchEvent({{ type: 'change' }});
            await settle();
        """)
        calls = out["after"]["calls"]
        assert [(c["method"], c["url"]) for c in calls] == [("POST", "/api/workstation/cpus")]
        assert calls[0]["body"] == {"cpus": sent}
        assert out["cpus"]["mineWhy"] == "chosen"


def test_no_machine_of_ones_own_shows_no_count_and_asks_nothing(sandbox):
    out = _open(sandbox, UP, MINE)
    assert out["cpus"]["mine"] is False and out["cpus"]["mineWhy"] is None
    assert "/api/workstation/status" in out["opened"]
    assert "/api/workstation/cpus" not in out["opened"]


def test_the_admin_sets_the_pool(sandbox):
    out = _open(sandbox, ADMIN_VM, MINE)["cpus"]
    assert out["pool"] is True and out["poolValue"] == ""
    assert out["poolOptions"][0] == {"value": "", "label": "All 12 of this host's"}
    assert [o["value"] for o in out["poolOptions"][1:]] == [str(n) for n in range(1, 13)]
    assert "up to 12 processors" in out["poolEffect"]
    assert "PANTHEON_WORKSTATION_VM_CPUS" in out["poolEffect"]


def test_the_pool_writes_its_key_and_asks_again(sandbox):
    out = _open(sandbox, ADMIN_VM, MINE, """
        byId('ws-vm-cpus').value = '4';
        byId('ws-vm-cpus').dispatchEvent({ type: 'change' });
        await settle();
    """)["after"]
    posts = [c for c in out["calls"] if c["method"] == "POST"]
    assert [c["url"] for c in posts][:2] == ["/api/auth/settings", "/api/workstation/check"]
    assert posts[0]["body"] == {"workstation_vm_cpus_max": 4}


def test_the_container_shows_no_pool(sandbox):
    out = _open(sandbox, ADMIN_UP, None)["cpus"]
    assert out["pool"] is False and out["poolEffect"] is None
