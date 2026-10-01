# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P21-04` — a document is found by the name of the file it came from and by
its folder, in the library and by the agent.

`P21-01` made folders and `P21-03` kept the file's own name on the document
(`source_name`); this row makes both findable. Driven through the real library
route and the real `manage_documents` dispatch, on a real SQLite database built
from the real models (`Law 20`), reusing those rows' fixtures.
"""
from __future__ import annotations

import uuid

import core.database as cdb
from tests.test_documents_keep_their_folders import ALICE, LONG_AGO, lib  # noqa: F401
from tests.test_the_agent_files_documents import call
from tests.test_the_agent_files_documents import lib as agent_lib  # noqa: F401


def _doc(db_factory, title, *, folder=None, source_name=None, owner="alice"):
    doc_id = "d-" + uuid.uuid4().hex[:10]
    db = db_factory()
    db.add(cdb.Document(id=doc_id, title=title, current_content="nothing here", owner=owner,
                        is_active=True, folder=folder, source_name=source_name,
                        created_at=LONG_AGO, updated_at=LONG_AGO))
    db.commit()
    db.close()
    return doc_id


def _library(lib, search):
    res = lib.get(f"/api/documents/library?search={search}", headers=ALICE)
    assert res.status_code == 200, res.text
    return {d["id"] for d in res.json()["documents"]}


def test_the_library_finds_a_word_only_in_the_file_s_own_name(lib):
    pack = _doc(lib.db, "Board pack", source_name="Q3 Board Pack – final (v2).pdf",
                folder="Clients/Acme")
    _doc(lib.db, "Shopping list", source_name="list.txt")
    assert _library(lib, "final") == {pack}
    assert _library(lib, "pdf") == {pack}
    assert _library(lib, "board%20acme") == {pack}       # title and folder, any order


def test_the_agent_finds_the_board_pack_by_name_and_folder(agent_lib):
    pack = _doc(agent_lib, "Q3 Board Pack – final (v2)", folder="Clients/Acme",
                source_name="Q3 Board Pack – final (v2).pdf")
    _doc(agent_lib, "Board minutes", folder="Clients/Other")
    found = call({"action": "list", "search": "board pack acme"})
    assert [d["id"] for d in found["documents"]] == [pack], found
    assert found["documents"][0]["source_name"] == "Q3 Board Pack – final (v2).pdf"
    by_file = call({"action": "list", "search": "v2).pdf"})
    assert [d["id"] for d in by_file["documents"]] == [pack], by_file


def test_another_person_s_file_name_is_not_found(agent_lib):
    _doc(agent_lib, "Bob's pack", source_name="secret-pack.pdf", owner="bob")
    found = call({"action": "list", "search": "secret-pack"})
    assert found.get("documents") == [], found


# ── `B993`: a delete with the wrong id deletes nothing ───────────────────────
# Found by `P21-02`: `manage_documents delete` fell back to the most recently
# edited document when the id it was given did not match, and reported deleting
# *that* one.

def _alive(db_factory, doc_id):
    db = db_factory()
    try:
        return db.query(cdb.Document).filter(cdb.Document.id == doc_id).one().is_active
    finally:
        db.close()


def test_a_delete_with_a_wrong_id_deletes_nothing(agent_lib):
    keep = _doc(agent_lib, "Last edited")
    refused = call({"action": "delete", "document_id": "d-typo"})
    assert refused["exit_code"] == 1 and "not found" in refused["error"], refused
    assert _alive(agent_lib, keep)


def test_a_delete_naming_nothing_deletes_nothing(agent_lib):
    from src.agent_tools import document_tools
    document_tools.set_active_document(None)
    keep = _doc(agent_lib, "Last edited")
    refused = call({"action": "delete"})
    assert refused["exit_code"] == 1 and "Say which document" in refused["error"], refused
    assert _alive(agent_lib, keep)


def test_a_delete_with_the_right_id_still_deletes(agent_lib):
    from src.document_folders import PLAN_APPROVE_LABEL
    from tests.test_the_agent_files_documents import say

    gone = _doc(agent_lib, "Old draft")
    # `B994`: a plan of one first; the delete happens on the person's yes.
    planned = call({"action": "delete", "document_id": gone})
    assert planned.get("outcome") == "planned", planned
    assert _alive(agent_lib, gone)
    say(agent_lib, PLAN_APPROVE_LABEL)
    done = call({"action": "apply_plan", "plan_id": planned["plan_id"]})
    assert done.get("exit_code", 0) == 0, done
    assert not _alive(agent_lib, gone)
