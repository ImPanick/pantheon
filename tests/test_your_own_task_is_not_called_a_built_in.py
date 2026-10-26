# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1493` — a task a person made with a housekeeping action is not served as
a built-in.

**Measured before this file:** `_task_to_dict` set `is_builtin = defs is not
None` — "has one of the housekeeping actions" — so "Tidy memories", a
`consolidate_memory` task a person made (which `B1063` now keeps), came back
`is_builtin: true`: its card said *built-in*, ⋮ offered *Revert to default*,
and `POST /revert` renamed it "Memory Tidy" — a second row under the built-in's
name, which the next reconcile collapsed into one.

Now which rows are a built-in is the reconcile's own answer
(`housekeeping_builtin_ids`): the rows under the built-in's names, or — where
none carries one — the action's only row, a built-in the person renamed, which
keeps its *Revert to default* (`Law 1`). Driven (`Law 20`): the real task
routes and the real `ensure_defaults` over a real SQLite file (`B1063`'s world).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_your_own_housekeeping_task_is_kept import (  # noqa: E402,F401
    _mine, _reconcile, _rows, world,
)


def test_a_task_you_made_with_a_housekeeping_action_is_not_a_built_in(world):
    factory, s, client, _ran = world
    _reconcile(s)
    builtin = next(t for t in _rows(factory).values() if t.action == "consolidate_memory")
    mine = _mine(client, "Tidy memories", "consolidate_memory")

    listed = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert listed[mine]["is_builtin"] is False, "a task you made is served as a built-in"
    assert listed[mine]["is_modified"] is False
    assert listed[builtin.id]["is_builtin"] is True and listed[builtin.id]["is_modified"] is False
    # The one-row door says the same as the list.
    assert client.get(f"/api/tasks/{mine}").json()["is_builtin"] is False
    assert client.get(f"/api/tasks/{builtin.id}").json()["is_builtin"] is True

    # And there is no default for it to go back to: the API refuses in words
    # rather than making it a copy of the built-in.
    r = client.post(f"/api/tasks/{mine}/revert")
    assert r.status_code == 400, r.text
    assert "a task you made" in r.json()["detail"] and "Memory Tidy" in r.json()["detail"]
    _reconcile(s)
    rows = _rows(factory)
    assert rows[mine].name == "Tidy memories" and rows[mine].trigger_type == "webhook"
    assert builtin.id in rows


def test_a_built_in_you_renamed_is_still_one_and_can_go_back(world):
    """`Law 1`. The built-in, renamed — the only row of its action — is still
    the built-in: it says so, as edited, and *Revert to default* restores it."""
    factory, s, client, _ran = world
    _reconcile(s)
    builtin = next(t for t in _rows(factory).values() if t.action == "audit_skills")
    r = client.put(f"/api/tasks/{builtin.id}", json={"name": "Check my skills"})
    assert r.status_code == 200, r.text
    served = r.json()
    assert served["is_builtin"] is True and served["is_modified"] is True

    listed = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert listed[builtin.id]["is_builtin"] is True and listed[builtin.id]["is_modified"] is True

    r = client.post(f"/api/tasks/{builtin.id}/revert")
    assert r.status_code == 200, r.text
    assert r.json()["task"]["name"] == "Skills Audit"
    assert r.json()["task"]["is_modified"] is False


def test_a_paused_built_in_still_tells_your_own_apart_in_a_filtered_list(world):
    """The list may be filtered by status; the answer is read over every row
    of the action, so a paused built-in beside an active task you made does
    not make yours look like the action's only row."""
    factory, s, client, _ran = world
    _reconcile(s)
    builtin = next(t for t in _rows(factory).values() if t.action == "consolidate_memory")
    client.post(f"/api/tasks/{builtin.id}/pause")
    mine = _mine(client, "Tidy memories", "consolidate_memory")
    active = {t["id"]: t for t in client.get("/api/tasks?status=active").json()["tasks"]}
    assert builtin.id not in active
    assert active[mine]["is_builtin"] is False
