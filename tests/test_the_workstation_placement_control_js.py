# SPDX-License-Identifier: AGPL-3.0-or-later
"""Own VM or the shared one, in Settings → Workstation — driven under node
against the real module and the panel's own markup (the harness of
`tests/test_the_workstation_panel_js.py`).

The owner, 2026-11-17: the admin decides whether each person runs their own
VM or an account in a shared one, with a default for new accounts and a word
for each person. What is pinned:

  * the admin sees the default and one row per person, with where each one's
    workstation is now, only when the workstation reports `placement`;
  * the default writes `workstation_vm_placement` and then asks again;
  * a person's row writes the whole `workstation_vm_placement_people` map, so
    choosing one person never drops another's, and an empty row drops theirs;
  * a person on the shared machine is told why there is no processors choice.
"""
from __future__ import annotations

import json

from test_the_workstation_panel_js import (ADMIN_UP, DAEMON, UP, _panel,  # noqa: F401
                                           sandbox)

ANN, BOB = "pw-ann-00000001", "pw-bob-00000002"
VM_DAEMON = {**DAEMON, "backend": "vm",
             "placement": {"default": "own", "people": {BOB: "shared"},
                           "where": {ANN: "own", BOB: "shared"},
                           "shared": {"running": True, "accounts": [BOB]},
                           "shared_sudo": False}}
PEOPLE = [{"name": "ann", "account": ANN, "choice": None, "where": "own"},
          {"name": "bob", "account": BOB, "choice": "shared", "where": "shared"},
          {"name": "cy", "account": "pw-cy-00000003", "choice": None, "where": None}]
ADMIN_VM = {**ADMIN_UP, "daemon": VM_DAEMON,
            "settings": {**ADMIN_UP["settings"], "backend": "vm", "vm_placement": "own",
                         "vm_placement_people": {"bob": "shared"}, "vm_people": PEOPLE}}
SHARED_CPUS = {"cpus": 12, "cpus_max": 12, "cpus_default": 12, "cpus_choice": None,
               "placement": "shared", "sentence": "Your workstation is an account on the "
               "machine several people share."}

READ = """
const t = (id) => (byId(id) ? byId(id).textContent : null);
const list = byId('ws-vm-placement-people');
const rows = list.children.map((line) => {
  const [label, pick] = line.children;
  return { name: label.textContent, value: pick.value,
           options: pick.children.map((o) => ({ value: o.value, label: o.textContent })) };
});
const placement = {
  shown: !byId('ws-vm-placement-row').hidden, peopleShown: !byId('ws-vm-placement-people-row').hidden,
  value: byId('ws-vm-placement').value,
  effect: byId('ws-vm-placement-effect').hidden ? null : t('ws-vm-placement-effect'),
  rows,
  mine: !byId('ws-cpus-row').hidden, mineWhy: byId('ws-cpus-why').hidden ? null : t('ws-cpus-why'),
};
"""


def _open(sandbox, status, cpus=None, then: str = "") -> dict:
    serve = f"""
respond((call) => {{
  if (call.url === '/api/workstation/cpus')
    return {json.dumps({"status": 200, "body": cpus} if cpus else {"status": 400, "body": {"detail": "no"}})};
  if (call.url === '/api/workstation/status' || call.url === '/api/workstation/check')
    return {{ status: 200, body: st }};
  return {{ status: 200, body: {{}} }};
}});
"""
    return _panel(sandbox, serve + """
        await mod.open();
        await settle();
        calls.length = 0;
    """ + then + READ + """
        console.log(JSON.stringify({ placement, after: read() }));
    """, st=status)


def test_the_admin_sees_the_default_and_each_person(sandbox):
    out = _open(sandbox, ADMIN_VM)["placement"]
    assert out["shown"] and out["peopleShown"] and out["value"] == "own"
    assert "1 person works on the shared machine" in out["effect"]
    assert "moves nobody" in out["effect"]
    assert [(r["name"], r["value"]) for r in out["rows"]] == [
        ("ann", ""), ("bob", "shared"), ("cy", "")]
    assert out["rows"][0]["options"][0]["label"] == "Leave it (now: own machine)"
    assert out["rows"][2]["options"][0]["label"] == "Leave it (now: none yet)"
    assert [o["value"] for o in out["rows"][0]["options"]] == ["", "own", "shared"]


def test_the_default_writes_its_key_and_asks_again(sandbox):
    out = _open(sandbox, ADMIN_VM, then="""
        byId('ws-vm-placement').value = 'shared';
        byId('ws-vm-placement').dispatchEvent({ type: 'change' });
        await settle();
    """)["after"]
    posts = [c for c in out["calls"] if c["method"] == "POST"]
    assert [c["url"] for c in posts][:2] == ["/api/auth/settings", "/api/workstation/check"]
    assert posts[0]["body"] == {"workstation_vm_placement": "shared"}


def test_a_persons_row_writes_everyones_word(sandbox):
    out = _open(sandbox, ADMIN_VM, then="""
        const [annLine, bobLine] = byId('ws-vm-placement-people').children;
        annLine.children[1].value = 'shared';
        annLine.children[1].dispatchEvent({ type: 'change' });
        await settle();
    """)["after"]
    posts = [c for c in out["calls"] if c["method"] == "POST"]
    assert posts[0]["url"] == "/api/auth/settings"
    assert posts[0]["body"] == {"workstation_vm_placement_people": {"ann": "shared", "bob": "shared"}}


def test_an_empty_row_drops_that_persons_word(sandbox):
    out = _open(sandbox, ADMIN_VM, then="""
        const bobLine = byId('ws-vm-placement-people').children[1];
        bobLine.children[1].value = '';
        bobLine.children[1].dispatchEvent({ type: 'change' });
        await settle();
    """)["after"]
    posts = [c for c in out["calls"] if c["method"] == "POST"]
    assert posts[0]["body"] == {"workstation_vm_placement_people": {}}


def test_a_workstation_without_placement_shows_none_of_it(sandbox):
    out = _open(sandbox, ADMIN_UP)["placement"]
    assert not out["shown"] and not out["peopleShown"] and out["effect"] is None


def test_a_person_on_the_shared_machine_is_told_why_there_is_no_choice(sandbox):
    up = {**UP, "daemon": {**UP["daemon"], "backend": "vm", "cpus_max": 12}}
    out = _open(sandbox, up, SHARED_CPUS)["placement"]
    assert out["mine"] is False
    assert out["mineWhy"] == SHARED_CPUS["sentence"]
