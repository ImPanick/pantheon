# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-06` (WB-U-16, WB-M-8) — a new workflow does not take a name its owner already uses.

Measured by the Workbench audit on `9560d50`: *Describe it* twice with one
sentence made two workflows called "Bank mail to chat", alike on the shelf, in
*Connect…* and as Tasks cards. `src/workflow_store.unused_name` suffixes the
name at create — `(2)`, `(3)` — for the person who owns it, and nobody else's
workflows count. Driven through the real `POST /api/workflows` with the routes
and fixtures `tests/test_a_workflow_is_kept_as_one_document.py` builds (imported).
"""

from __future__ import annotations

from tests.test_a_workflow_is_kept_as_one_document import (  # noqa: F401  (fixtures)
    admins, call, client, new, sched, wf_db,
)


def test_a_second_workflow_of_one_name_is_numbered(client):
    first = new(client, name="Bank mail to chat")
    second = new(client, name="Bank mail to chat")
    third = new(client, name="  Bank   mail to chat ")   # the same name, as `clean_name` reads it
    assert [first["name"], second["name"], third["name"]] == [
        "Bank mail to chat", "Bank mail to chat (2)", "Bank mail to chat (3)"]
    # The start task is named with it: Tasks and *Connect…* list the same words.
    assert second["trigger_task"]["name"] == "Bank mail to chat (2)"


def test_another_persons_workflow_does_not_count(client):
    mine = new(client, name="Morning digest", user="alice")
    theirs = new(client, name="Morning digest", user="bob")
    assert (mine["name"], theirs["name"]) == ("Morning digest", "Morning digest")


def test_the_default_name_is_numbered_too(client):
    a = call(client, "POST", "/api/workflows", json={}).json()["workflow"]
    b = call(client, "POST", "/api/workflows", json={}).json()["workflow"]
    assert (a["name"], b["name"]) == ("New workflow", "New workflow (2)")


def test_a_name_at_the_limit_keeps_its_number(client):
    from src.workflow_store import WORKFLOW_NAME_MAX
    long_name = "x" * WORKFLOW_NAME_MAX
    new(client, name=long_name)
    second = new(client, name=long_name)
    assert len(second["name"]) == WORKFLOW_NAME_MAX and second["name"].endswith(" (2)"), second["name"]
