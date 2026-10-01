# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P21-02` — the agent organises documents, and a big reorganisation waits for a yes.

The owner, 2026-10-01: *"… as well as giving the LLM the ability to organize and
make folders etc.."*

`manage_documents` could list, read, delete and tidy, and nothing else: a
document had no folder to be put in. It now calls the module the library's
routes call (`src/document_folders.py`), so every test below goes through the
real dispatcher — `execute_tool_block`, the function the agent loop calls — into
the real tool, against a real SQLite database, and reads the rows back:

  * each folder action does what it says and its result lists every change, in
    the words the tool card prints, so a person can undo any of it by hand;
  * more than five moves or removals in one call change NOTHING: the call
    returns a plan and the `ask_user` card, and `apply_plan` runs only when the
    chat's own last message — written by the person, not the agent — is the
    card's "Apply the plan", after the plan was made;
  * a plan the library has outgrown since it was shown is refused rather than
    applied to things the person never saw;
  * another person's documents and folders are as invisible to the agent as
    they are to the routes, and a plan is bound to its owner and its chat;
  * the registers agree: the schema offers every action, the approval card
    classifies every action, and removing is destructive.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.tool_execution as tool_execution  # noqa: E402
from src.agent_tools import ToolBlock  # noqa: E402
from src.agent_tools.document_tools import FOLDER_ACTIONS, MAX_CHANGES_PER_CALL  # noqa: E402
from src.document_folders import PLAN_APPROVE_LABEL, PLAN_DECLINE_LABEL, PLAN_THRESHOLD  # noqa: E402
from src.tool_capabilities import ToolEffect, capabilities_for_action  # noqa: E402
from src.tool_execution import NO_TOOL_SECURITY_CONTEXT, execute_tool_block, format_tool_result  # noqa: E402

LONG_AGO = datetime(2025, 1, 2, 3, 4, 5)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'docs.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    ts = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", ts)
    # `manage_documents` is in `NON_ADMIN_BLOCKED_TOOLS`; both people here are
    # admins, which is the case where owner scope is the only thing between them.
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    db = ts()
    for sid, owner in (("chat-a", "alice"), ("chat-b", "alice"), ("chat-bob", "bob")):
        db.add(cdb.Session(id=sid, owner=owner, name=sid, model="m", endpoint_url="http://x"))
    db.commit()
    db.close()
    return ts


def call(args, owner="alice", session_id="chat-a"):
    _desc, result = asyncio.run(execute_tool_block(
        ToolBlock("manage_documents", json.dumps(args)),
        session_id=session_id, owner=owner, security_context=NO_TOOL_SECURITY_CONTEXT,
    ))
    return result


def doc(lib, title, owner="alice", folder=None):
    doc_id = "d-" + uuid.uuid4().hex[:10]
    db = lib()
    db.add(cdb.Document(id=doc_id, title=title, current_content="x", owner=owner,
                        is_active=True, folder=folder, created_at=LONG_AGO, updated_at=LONG_AGO))
    db.commit()
    db.close()
    return doc_id


def where(lib, doc_id):
    db = lib()
    try:
        d = db.query(cdb.Document).filter(cdb.Document.id == doc_id).one()
        return d.folder if d.is_active else "DELETED"
    finally:
        db.close()


def folder_rows(lib, owner="alice"):
    db = lib()
    try:
        return sorted(r.path for r in db.query(cdb.DocumentFolder)
                      .filter(cdb.DocumentFolder.owner == owner).all())
    finally:
        db.close()


def say(lib, text, session_id="chat-a", later=1):
    """The person's answer, as the chat route persists it — after the plan."""
    db = lib()
    db.add(cdb.ChatMessage(id=str(uuid.uuid4()), session_id=session_id, role="user",
                           content=text, timestamp=datetime.utcnow() + timedelta(seconds=later)))
    db.commit()
    db.close()


# ── each action, small enough to apply at once ──────────────────────────────

def test_list_folders_says_there_are_none_and_then_lists_them(lib):
    doc(lib, "Loose")
    first = call({"action": "list_folders"})
    assert first["exit_code"] == 0 and first["folders"] == []
    assert "No folders yet" in first["response"]

    call({"action": "create_folder", "folder": "Clients/Acme"})
    doc(lib, "Pack", folder="Clients/Acme")
    listed = call({"action": "list_folders"})
    assert [f["path"] for f in listed["folders"]] == ["Clients", "Clients/Acme"]
    assert "- Clients — 1 document(s), 0 directly inside" in listed["response"]
    assert "  - Clients/Acme — 1 document(s)" in listed["response"]
    assert listed["unfiled"] == 1


def test_moving_documents_files_them_and_the_card_lists_each_move(lib):
    a, b = doc(lib, "Board pack"), doc(lib, "Minutes", folder="Old")
    out = call({"action": "move", "document_ids": [a, b], "to": "Clients/Acme"})
    assert out["exit_code"] == 0 and out["outcome"] == "applied"
    assert where(lib, a) == "Clients/Acme" and where(lib, b) == "Clients/Acme"
    # The card's list: one line per change, saying where from and where to.
    assert '- moved "Board pack": Unfiled → Clients/Acme' in out["response"]
    assert '- moved "Minutes": Old → Clients/Acme' in out["response"]
    assert "- made folder Clients/Acme" in out["response"]
    # And what the model reads back carries the same list.
    fed_back = format_tool_result("manage_documents", out)
    assert '"Board pack": Unfiled → Clients/Acme' in fed_back


def test_create_rename_move_and_list_one_folder(lib):
    pack = doc(lib, "Board pack", folder="Clients")
    assert call({"action": "create_folder", "folder": "Archive"})["exit_code"] == 0
    again = call({"action": "create_folder", "folder": "Archive"})
    assert again["outcome"] == "unchanged", "making a folder that exists is not an error for the agent"

    renamed = call({"action": "rename_folder", "folder": "Clients", "name": "Customers"})
    assert renamed["exit_code"] == 0 and where(lib, pack) == "Customers"
    assert "moved folder Clients → Customers (with the 1 document in it)" in renamed["response"]

    moved = call({"action": "move_folder", "folder": "Customers", "to": "Archive"})
    assert moved["exit_code"] == 0 and where(lib, pack) == "Archive/Customers"

    listed = call({"action": "list", "folder": "Archive/Customers"})
    assert [d["id"] for d in listed["documents"]] == [pack]
    assert "in Archive/Customers" in listed["response"]
    assert call({"action": "list", "unfiled": True})["documents"] == []
    # `P21-04`'s folder half: the agent's lookup matches the folder path too.
    found = call({"action": "list", "search": "customers"})
    assert [d["id"] for d in found["documents"]] == [pack]


def test_remove_folder_asks_what_happens_and_does_exactly_that(lib):
    a = doc(lib, "Board pack", folder="Clients/Acme")
    refused = call({"action": "remove_folder", "folder": "Clients"})
    assert refused["exit_code"] == 1
    assert "holds 1 document and 1 folder" in refused["error"]
    assert where(lib, a) == "Clients/Acme"

    up = call({"action": "remove_folder", "folder": "Clients", "contents": "move_up"})
    assert up["exit_code"] == 0 and where(lib, a) == "Acme"
    assert "- removed folder Clients" in up["response"]

    gone = call({"action": "remove_folder", "folder": "Acme", "contents": "delete"})
    assert gone["exit_code"] == 0 and where(lib, a) == "DELETED"
    assert '- deleted "Board pack" (was in Acme)' in gone["response"]


def test_a_move_without_a_destination_is_refused_rather_than_unfiled(lib):
    a = doc(lib, "Board pack", folder="Clients")
    out = call({"action": "move", "document_ids": [a]})
    assert out["exit_code"] == 1 and "Say where to" in out["error"]
    assert where(lib, a) == "Clients"
    # `folder` where `to` belongs is read as the destination it obviously is.
    assert call({"action": "move", "document_id": a, "folder": "Archive"})["exit_code"] == 0
    assert where(lib, a) == "Archive"


def test_reorganise_runs_its_steps_in_one_transaction(lib):
    a, b = doc(lib, "Board pack"), doc(lib, "Minutes")
    ok = call({"action": "reorganize", "steps": [
        {"action": "create_folder", "folder": "Clients"},
        {"action": "move", "document_ids": [a], "to": "Clients"},
        {"action": "move", "document_ids": [b], "to": "Clients/Acme"},
    ]})
    assert ok["exit_code"] == 0, ok
    assert (where(lib, a), where(lib, b)) == ("Clients", "Clients/Acme")

    # A bad step undoes the good ones before it.
    bad = call({"action": "reorganise", "steps": [
        {"action": "move", "document_ids": [a], "to": "Elsewhere"},
        {"action": "rename_folder", "folder": "Nope", "name": "X"},
    ]})
    assert bad["exit_code"] == 1 and bad["error"].startswith("Step 2 (rename_folder)")
    assert where(lib, a) == "Clients"
    assert "Elsewhere" not in folder_rows(lib)


# ── more than a handful: a plan the person approves first ───────────────────

def _seven(lib, folder=None):
    return [doc(lib, f"Doc {i}", folder=folder) for i in range(PLAN_THRESHOLD + 2)]


def test_a_big_move_changes_nothing_and_asks_first(lib):
    ids = _seven(lib)
    out = call({"action": "move", "document_ids": ids, "to": "Archive"})
    assert out["exit_code"] == 0 and out["outcome"] == "planned"
    assert all(where(lib, i) is None for i in ids), "a plan moved documents before anyone said yes"
    assert folder_rows(lib) == [], "a plan made its folder before anyone said yes"

    ask = out["ask_user"]
    assert [o["label"] for o in ask["options"]] == [PLAN_APPROVE_LABEL, PLAN_DECLINE_LABEL]
    assert "moves 7 documents and makes 1 folder" in ask["question"]
    # The card lists the whole plan, so the yes is a yes to something seen.
    for i in range(7):
        assert f'- moved "Doc {i}": Unfiled → Archive' in out["response"]
    assert out["plan_id"] in out["response"]


def test_apply_plan_waits_for_the_persons_own_yes(lib):
    ids = _seven(lib)
    plan = call({"action": "move", "document_ids": ids, "to": "Archive"})["plan_id"]

    early = call({"action": "apply_plan", "plan_id": plan})
    assert early["exit_code"] == 1 and "has not answered" in early["error"]
    assert all(where(lib, i) is None for i in ids)

    say(lib, PLAN_APPROVE_LABEL)
    done = call({"action": "apply_plan", "plan_id": plan})
    assert done["exit_code"] == 0 and done["outcome"] == "applied", done
    assert all(where(lib, i) == "Archive" for i in ids)
    for i in range(7):
        assert f'- moved "Doc {i}": Unfiled → Archive' in done["response"]

    again = call({"action": "apply_plan", "plan_id": plan})
    assert again["exit_code"] == 1, "a plan applied twice"


def test_any_other_answer_is_a_no(lib):
    ids = _seven(lib)
    plan = call({"action": "move", "document_ids": ids, "to": "Archive"})["plan_id"]
    say(lib, PLAN_DECLINE_LABEL)
    out = call({"action": "apply_plan", "plan_id": plan})
    assert out["exit_code"] == 1 and "did not choose" in out["error"]
    assert all(where(lib, i) is None for i in ids)

    plan2 = call({"action": "move", "document_ids": ids, "to": "Archive"})["plan_id"]
    say(lib, "hmm, actually only the first three", later=2)
    assert call({"action": "apply_plan", "plan_id": plan2})["exit_code"] == 1
    assert all(where(lib, i) is None for i in ids)


def test_a_yes_from_before_the_plan_does_not_count(lib):
    say(lib, PLAN_APPROVE_LABEL, later=-60)
    ids = _seven(lib)
    plan = call({"action": "move", "document_ids": ids, "to": "Archive"})["plan_id"]
    assert call({"action": "apply_plan", "plan_id": plan})["exit_code"] == 1
    assert all(where(lib, i) is None for i in ids)


def test_a_plan_the_library_has_outgrown_is_refused(lib):
    """The plan is the change list the person read, not just the steps: a
    document filed into the folder after the plan was shown would otherwise be
    deleted with it, unseen."""
    ids = _seven(lib, folder="Old")
    plan = call({"action": "remove_folder", "folder": "Old", "contents": "delete"})
    assert plan["outcome"] == "planned"
    late = doc(lib, "Filed later", folder="Old")
    say(lib, PLAN_APPROVE_LABEL)
    out = call({"action": "apply_plan", "plan_id": plan["plan_id"]})
    assert out["exit_code"] == 1 and "changed after this plan was shown" in out["error"]
    assert where(lib, late) == "Old"
    assert all(where(lib, i) == "Old" for i in ids), "an outgrown plan deleted documents"


def test_a_plan_belongs_to_its_owner_and_its_chat(lib):
    ids = _seven(lib)
    plan = call({"action": "move", "document_ids": ids, "to": "Archive"})["plan_id"]
    say(lib, PLAN_APPROVE_LABEL)
    say(lib, PLAN_APPROVE_LABEL, session_id="chat-b")
    say(lib, PLAN_APPROVE_LABEL, session_id="chat-bob")
    assert call({"action": "apply_plan", "plan_id": plan}, session_id="chat-b")["exit_code"] == 1
    assert call({"action": "apply_plan", "plan_id": plan}, owner="bob",
                session_id="chat-bob")["exit_code"] == 1
    # Even in the chat the yes was given in, somebody else's call finds no plan.
    intruder = call({"action": "apply_plan", "plan_id": plan}, owner="bob")
    assert intruder["exit_code"] == 1 and "No plan with that id" in intruder["error"]
    assert all(where(lib, i) is None for i in ids)
    assert call({"action": "apply_plan", "plan_id": plan})["exit_code"] == 0


def test_a_plan_with_no_chat_to_ask_in_is_refused(lib):
    ids = _seven(lib)
    out = call({"action": "move", "document_ids": ids, "to": "Archive"}, session_id=None)
    assert out["exit_code"] == 1 and "no chat to ask them in" in out["error"]
    assert all(where(lib, i) is None for i in ids)


def test_more_changes_than_a_card_can_list_are_refused(lib):
    ids = [doc(lib, f"D{i}") for i in range(MAX_CHANGES_PER_CALL + 1)]
    out = call({"action": "move", "document_ids": ids, "to": "Archive"})
    assert out["exit_code"] == 1 and "Split it" in out["error"]
    assert where(lib, ids[0]) is None


# ── owner scope ─────────────────────────────────────────────────────────────

def test_another_persons_documents_and_folders_are_untouchable(lib):
    bobs = doc(lib, "Bob's plan", owner="bob", folder="Bob stuff")
    mine = doc(lib, "Mine")

    assert call({"action": "list_folders"})["folders"] == []
    stolen = call({"action": "move", "document_ids": [mine, bobs], "to": "Taken"})
    assert stolen["exit_code"] == 1 and f"Document '{bobs}' not found" in stolen["error"]
    assert where(lib, bobs) == "Bob stuff" and where(lib, mine) is None

    for args in ({"action": "rename_folder", "folder": "Bob stuff", "name": "Mine"},
                 {"action": "move_folder", "folder": "Bob stuff", "to": "Mine"},
                 {"action": "remove_folder", "folder": "Bob stuff", "contents": "delete"}):
        out = call(args)
        assert out["exit_code"] == 1 and "Folder 'Bob stuff' not found" in out["error"], args
    assert where(lib, bobs) == "Bob stuff"

    listed = call({"action": "list", "search": "Bob"})
    assert listed["documents"] == []


def test_a_call_with_no_owner_files_nothing(lib):
    a = doc(lib, "Board pack")
    out = call({"action": "move", "document_ids": [a], "to": "X"}, owner=None)
    assert out["exit_code"] == 1
    assert where(lib, a) is None


# ── the registers agree ─────────────────────────────────────────────────────

def test_every_folder_action_is_offered_and_classified(lib):
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    schema = next(s["function"] for s in FUNCTION_TOOL_SCHEMAS
                  if s["function"]["name"] == "manage_documents")
    offered = set(schema["parameters"]["properties"]["action"]["enum"])
    assert FOLDER_ACTIONS <= offered

    # Classified, not caught by the fail-high default for an unknown action.
    from src.tool_capabilities import _PRIVATE_ACTION_READS, _PRIVATE_ACTION_WRITES
    classified = (_PRIVATE_ACTION_READS["manage_documents"]
                  | _PRIVATE_ACTION_WRITES["manage_documents"])
    assert FOLDER_ACTIONS <= classified, FOLDER_ACTIONS - classified

    def effects(action):
        return capabilities_for_action("manage_documents", json.dumps({"action": action})).effects

    assert ToolEffect.DESTRUCTIVE in effects("remove_folder")
    assert ToolEffect.DESTRUCTIVE in effects("apply_plan")
    assert ToolEffect.DESTRUCTIVE in effects("reorganize"), "the alias missed its own action"
    assert ToolEffect.DESTRUCTIVE not in effects("move")
    assert effects("list_folders") == frozenset({ToolEffect.READ_PRIVATE})


def test_asking_to_sort_documents_into_folders_reaches_the_tool():
    """Agent mode offers the model the tools a request looks like it needs; a
    request to organise documents that never says "document library" must
    still be offered `manage_documents`."""
    from src.tool_index import ToolIndex
    for ask in ("please sort my documents into folders by client",
                "organize my files into folders",
                "file these under Clients/Acme"):
        assert "manage_documents" in ToolIndex.select_without_embeddings(ask, set()), ask
    assert "manage_documents" not in ToolIndex.select_without_embeddings(
        "move that email to the Receipts folder", set())
