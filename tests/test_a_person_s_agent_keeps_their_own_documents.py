# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B995` + `B994` — a non-admin's agent organises their own documents, and a
delete waits for them.

The owner, 2026-10-01 (`D-2026-10-01-02`): *"Yes, their own docs"* — and a big
move or a delete still waits for the person's approval, which makes `B994` part
of the same change: the promise is only true once `tidy` and `delete` ask first.

Before this change `manage_documents` was in `NON_ADMIN_BLOCKED_TOOLS`, so on a
multi-user install only an admin's agent could use it; its `tidy` hard-deleted
everything its rules named in one call, and its `delete` deleted at once. Every
test here drives the real dispatcher (`execute_tool_block`, the function the
agent loop calls) against a real SQLite database and a REAL auth store with an
admin and two non-admins — the admin check is not stubbed — and reads the rows
back (`Law 20`):

  * a non-admin is offered the tool and may run it; the shell stays theirs to
    be refused;
  * every action — list, read and its aliases, delete, tidy, every folder
    action, reorganise, apply_plan — run by one non-admin against the other's
    documents and folders refuses or does not see them, and leaves them as they
    were;
  * a bearer token still may not have it (`B70`), at the advertisement, in the
    chat route and at the gate; the document-editor switch takes it too;
  * `tidy` and `delete` show a plan, change nothing, and apply only on the
    person's own "Apply the plan" — sealed to the content the person saw;
  * the scheduled `tidy_documents` action is unchanged (`Law 1`).
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
from src.agent_tools import ToolBlock  # noqa: E402
from src.agent_tools import document_tools  # noqa: E402
from src.agent_tools.document_tools import MAX_CHANGES_PER_CALL  # noqa: E402
from src.document_folders import PLAN_APPROVE_LABEL, PLAN_DECLINE_LABEL  # noqa: E402
from src.tool_capabilities import ToolRunSecurityContext  # noqa: E402
from src.tool_execution import (  # noqa: E402
    NO_TOOL_SECURITY_CONTEXT, execute_tool_block, format_tool_result,
)
from src.tool_security import (  # noqa: E402
    blocked_tool_reason, blocked_tools_for_owner, delegated_credential_blocked_tools,
)

LONG_AGO = datetime(2025, 1, 2, 3, 4, 5)


# ── a real auth store, a real database ──────────────────────────────────────

@pytest.fixture(scope="module")
def auth_store(tmp_path_factory):
    """`boss` is an admin; `bob` and `ann` are not. Made once: hashing three
    passwords is most of what a test here would otherwise spend."""
    from core.auth import AuthManager

    am = AuthManager(str(tmp_path_factory.mktemp("auth") / "auth.json"))
    assert am.setup("boss", "correct-horse-1")
    assert am.create_user("bob", "correct-horse-1")
    assert am.create_user("ann", "correct-horse-1")
    return am


@pytest.fixture
def people(tmp_path, monkeypatch, auth_store):
    """The real auth store answering every admin check, and a fresh database
    in which each of the three has a chat."""
    import core.auth
    import src.settings as S

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(core.auth, "AuthManager", lambda *a, **k: auth_store)
    sp = tmp_path / "settings.json"
    sp.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "SETTINGS_FILE", str(sp))
    S._invalidate_caches()

    engine = create_engine(f"sqlite:///{tmp_path / 'docs.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    ts = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", ts)
    db = ts()
    for sid, owner in (("chat-bob", "bob"), ("chat-ann", "ann"), ("chat-boss", "boss")):
        db.add(cdb.Session(id=sid, owner=owner, name=sid, model="m", endpoint_url="http://x"))
    db.commit()
    db.close()
    document_tools.set_active_document(None)
    yield ts
    document_tools.set_active_document(None)
    S._invalidate_caches()


def call(args, owner="bob", session_id="chat-bob", security_context=NO_TOOL_SECURITY_CONTEXT):
    _desc, result = asyncio.run(execute_tool_block(
        ToolBlock("manage_documents", json.dumps(args)),
        session_id=session_id, owner=owner, security_context=security_context,
    ))
    return result


def doc(db_factory, title, owner="bob", folder=None, content="x", created=LONG_AGO):
    doc_id = "d-" + uuid.uuid4().hex[:10]
    db = db_factory()
    db.add(cdb.Document(id=doc_id, title=title, current_content=content, owner=owner,
                        is_active=True, folder=folder, created_at=created, updated_at=created))
    db.commit()
    db.close()
    return doc_id


def folder_row(db_factory, path, owner):
    db = db_factory()
    db.add(cdb.DocumentFolder(id=str(uuid.uuid4()), owner=owner, path=path))
    db.commit()
    db.close()


def state(db_factory, owner):
    """Everything a person has: each document's title, folder, liveness and
    content, and every folder row — compared before and after to show a call
    touched none of it."""
    db = db_factory()
    try:
        docs = sorted((d.id, d.title, d.folder, bool(d.is_active), d.current_content)
                      for d in db.query(cdb.Document).filter(cdb.Document.owner == owner).all())
        folders = sorted(r.path for r in db.query(cdb.DocumentFolder)
                         .filter(cdb.DocumentFolder.owner == owner).all())
        return {"docs": docs, "folders": folders}
    finally:
        db.close()


def alive(db_factory, doc_id):
    db = db_factory()
    try:
        row = db.query(cdb.Document).filter(cdb.Document.id == doc_id).one()
        return bool(row.is_active)
    finally:
        db.close()


def say(db_factory, text, session_id="chat-bob", later=1):
    """The person's answer, as the chat route persists it — after the plan, and
    sealed as the person's (`B1005`: the chat route seals a person's own
    request, and a plan reads only a sealed answer)."""
    from src.tool_approval_scopes import PERSON_MESSAGE_SEAL_FIELD, seal_person_message

    when = datetime.utcnow() + timedelta(seconds=later)
    seal = seal_person_message(session_id, text, said_at=when)
    db = db_factory()
    db.add(cdb.ChatMessage(id=str(uuid.uuid4()), session_id=session_id, role="user",
                           content=text, timestamp=when,
                           meta_data=json.dumps({PERSON_MESSAGE_SEAL_FIELD: seal})))
    db.commit()
    db.close()


@pytest.fixture
def ann(people):
    """Ann's library: a filed document, two the tidy rules would remove, and an
    empty folder of her own."""
    ids = {
        "plan": doc(people, "Ann's plan", owner="ann", folder="Ann stuff"),
        "junk": doc(people, "test", owner="ann"),
        "empty": doc(people, "Untitled", owner="ann", content=""),
    }
    folder_row(people, "Ann stuff", "ann")
    folder_row(people, "Ann empty", "ann")
    return ids


# ── B995: offered to a non-admin, and run ───────────────────────────────────

def test_a_non_admin_s_agent_is_offered_the_tool_and_still_not_the_shell(people):
    """`blocked_tools_for_owner` is what the agent loop subtracts from the
    prompt and the schemas for this person (`agent_loop`), asked of the real
    auth store."""
    bobs = blocked_tools_for_owner("bob")
    assert "manage_documents" not in bobs
    assert {"bash", "python", "read_file", "manage_memory"} <= bobs, "only this one tool opened"
    assert blocked_tools_for_owner("boss") == set()
    # Not blocked, so it has no reason to give (`Law 10`: "" means not blocked).
    assert blocked_tool_reason("manage_documents") == ""


def test_a_non_admin_s_agent_runs_it_on_their_own_documents(people):
    mine = doc(people, "Bob's notes")
    listed = call({"action": "list"})
    assert listed["exit_code"] == 0, listed
    assert [d["id"] for d in listed["documents"]] == [mine]
    filed = call({"action": "move", "document_ids": [mine], "to": "Work"})
    assert filed["exit_code"] == 0 and filed["outcome"] == "applied", filed
    assert state(people, "bob")["folders"] == ["Work"]


# ── B995: every action stays inside its caller's library ────────────────────

def test_list_and_search_see_only_the_caller_s_documents(people, ann):
    mine = doc(people, "Bob's notes")
    before = state(people, "ann")
    assert [d["id"] for d in call({"action": "list"})["documents"]] == [mine]
    assert call({"action": "list", "search": "Ann"})["documents"] == []
    assert call({"action": "list", "folder": "Ann stuff"})["documents"] == []
    assert call({"action": "list", "unfiled": True})["documents"] == [
        {"id": mine, "title": "Bob's notes", "language": "text", "size": 1,
         "folder": None, "source_name": None}]
    assert state(people, "ann") == before


@pytest.mark.parametrize("action", ["read", "view", "open", "get"])
def test_read_and_its_aliases_refuse_another_person_s_document(people, ann, action):
    out = call({"action": action, "document_id": ann["plan"]})
    assert out["exit_code"] == 1 and "not found" in out["error"], out
    assert "Ann's plan" not in json.dumps(out)


def test_delete_refuses_another_person_s_document_every_way_it_can_be_named(people, ann):
    mine = doc(people, "Bob's notes")
    before = state(people, "ann")
    named = call({"action": "delete", "document_id": ann["plan"]})
    assert named["exit_code"] == 1 and "not found" in named["error"], named
    mixed = call({"action": "delete", "document_ids": [mine, ann["plan"]]})
    assert mixed["exit_code"] == 1 and f"Document '{ann['plan']}' not found" in mixed["error"]
    assert "plan_id" not in mixed, "a refused delete made a plan anyway"
    # "The open document" is a process-wide pointer; when it is Ann's, Bob's
    # call means nothing by it.
    document_tools.set_active_document(ann["plan"])
    open_one = call({"action": "delete"})
    assert open_one["exit_code"] == 1 and "Say which document" in open_one["error"]
    assert document_tools.get_active_document() == ann["plan"]
    assert state(people, "ann") == before and alive(people, mine)


def test_tidy_judges_only_the_caller_s_documents(people, ann):
    bobs_junk = doc(people, "asdf")
    before = state(people, "ann")
    plan = call({"action": "tidy"})
    assert plan["outcome"] == "planned", plan
    assert [c["id"] for c in plan["changes"]] == [bobs_junk]
    say(people, PLAN_APPROVE_LABEL)
    done = call({"action": "apply_plan", "plan_id": plan["plan_id"]})
    assert done["exit_code"] == 0, done
    assert not alive(people, bobs_junk)
    assert state(people, "ann") == before, "Bob's tidy reached Ann's junk"


def test_folder_actions_cannot_see_or_touch_another_person_s_folders(people, ann):
    before = state(people, "ann")
    assert call({"action": "list_folders"})["folders"] == []
    for args in ({"action": "rename_folder", "folder": "Ann stuff", "name": "Mine"},
                 {"action": "move_folder", "folder": "Ann stuff", "to": "Mine"},
                 {"action": "remove_folder", "folder": "Ann stuff", "contents": "move_up"},
                 {"action": "remove_folder", "folder": "Ann empty"}):
        out = call(args)
        assert out["exit_code"] == 1 and "not found" in out["error"], args
    moved = call({"action": "move", "document_ids": [ann["plan"]], "to": "Mine"})
    assert moved["exit_code"] == 1 and "not found" in moved["error"]
    # A folder of the same name is Bob's own; Ann's is not touched.
    made = call({"action": "create_folder", "folder": "Ann stuff"})
    assert made["exit_code"] == 0 and "- made folder Ann stuff" in made["response"], made
    assert state(people, "bob")["folders"] == ["Ann stuff"]
    assert state(people, "ann") == before


def test_a_reorganisation_with_one_foreign_step_does_nothing(people, ann):
    mine = doc(people, "Bob's notes")
    before = state(people, "ann")
    out = call({"action": "reorganise", "steps": [
        {"action": "move", "document_ids": [mine], "to": "Work"},
        {"action": "move", "document_ids": [ann["plan"]], "to": "Work"},
    ]})
    assert out["exit_code"] == 1 and out["error"].startswith("Step 2 (move)"), out
    assert state(people, "bob")["folders"] == [] and state(people, "ann") == before


def test_another_person_cannot_apply_a_plan_that_is_not_theirs(people, ann):
    plan = call({"action": "delete", "document_id": ann["plan"]},
                owner="ann", session_id="chat-ann")
    assert plan["outcome"] == "planned", plan
    say(people, PLAN_APPROVE_LABEL, session_id="chat-ann")
    say(people, PLAN_APPROVE_LABEL, session_id="chat-bob")
    for session in ("chat-bob", "chat-ann"):
        out = call({"action": "apply_plan", "plan_id": plan["plan_id"]}, session_id=session)
        assert out["exit_code"] == 1 and "No plan with that id" in out["error"], session
    assert alive(people, ann["plan"])
    mine = call({"action": "apply_plan", "plan_id": plan["plan_id"]},
                owner="ann", session_id="chat-ann")
    assert mine["exit_code"] == 0 and not alive(people, ann["plan"])


# ── B995: a token is still capped; the editor switch takes it too ───────────

def test_a_token_still_may_not_have_it(people):
    """`B70`: a bearer token resolves to the admin who minted it. The plan's yes
    is the chat's next user message, and a token's turn writes that message
    itself — so for a token the tool stays closed, at the advertisement and at
    the gate, whoever minted it."""
    mine = doc(people, "Boss's notes", owner="boss")
    assert "manage_documents" in delegated_credential_blocked_tools()
    token_run = ToolRunSecurityContext(delegated_credential=True)
    decision = token_run.decision_for("manage_documents", '{"action": "list"}')
    assert decision.allowed is False and "API-token" in (decision.reason or "")
    refused = call({"action": "list"}, owner="boss", session_id="chat-boss",
                   security_context=ToolRunSecurityContext(delegated_credential=True))
    assert refused["exit_code"] == 1 and "Boss's notes" not in json.dumps(refused), refused
    # The same call from the admin's own browser run is answered.
    browser = call({"action": "list"}, owner="boss", session_id="chat-boss",
                   security_context=ToolRunSecurityContext())
    assert [d["id"] for d in browser["documents"]] == [mine]


async def _route_disabled(monkeypatch, *, privileges=None, token=False) -> set:
    """`disabled_tools` as the real chat route hands them to the agent loop."""
    import routes.chat_routes as chat_routes
    from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint

    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured)

    async def capturing_loop(endpoint_url, model, messages, **kwargs):
        captured["disabled"] = set(kwargs.get("disabled_tools") or ())
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_routes, "stream_agent_loop", capturing_loop)
    request = _RouteRequest("agent", privileges=privileges)
    request._form["compare_mode"] = "false"
    if token:
        # What the auth middleware sets for a bearer token with the chat scope.
        request.state.api_token = True
        request.state.api_token_scopes = ["chat"]
        request.state.api_token_owner = "alice"
    response = await endpoint(request)
    async for _ in response.body_iterator:
        pass
    return captured["disabled"]


@pytest.mark.asyncio
async def test_the_chat_route_withholds_it_from_a_token(monkeypatch):
    assert "manage_documents" in await _route_disabled(monkeypatch, token=True)
    assert "manage_documents" not in await _route_disabled(monkeypatch)


@pytest.mark.asyncio
async def test_the_document_editor_switch_takes_the_agent_s_document_tool_too(monkeypatch):
    """A person whose document editor an admin switched off is refused the
    library's writes (`require_privilege("can_use_documents")`); their agent
    must not file and delete for them instead."""
    off = await _route_disabled(monkeypatch, privileges={"can_use_documents": False})
    assert {"manage_documents", "create_document", "edit_document"} <= off
    on = await _route_disabled(monkeypatch, privileges={"can_use_documents": True})
    assert "manage_documents" not in on


# ── B994: tidy asks first ───────────────────────────────────────────────────

@pytest.fixture
def mess(people):
    """Bob's library as the tidy rules see it."""
    return {
        "junk": doc(people, "test", content="something"),
        "empty": doc(people, "Untitled", content=""),
        "quotes": doc(people, "Re: lunch", content="On Mon, Bob wrote:\n> lunch?\n> at 1"),
        # Two copies of one note; the one edited later is the copy that stays.
        "copy_long": doc(people, "Notes", content="the same notes", folder="Work",
                         created=LONG_AGO + timedelta(days=1)),
        "copy": doc(people, "Notes", content="the same notes"),
        "keep": doc(people, "Budget 2026", content="real numbers"),
        # Made a minute ago: the rules leave a document being written alone.
        "fresh": doc(people, "test", content="", created=datetime.utcnow() - timedelta(minutes=1)),
    }


def test_tidy_shows_its_list_and_deletes_nothing(people, mess):
    out = call({"action": "tidy"})
    assert out["exit_code"] == 0 and out["outcome"] == "planned", out
    assert [c["id"] for c in out["changes"]] == [
        mess["junk"], mess["empty"], mess["quotes"], mess["copy"]]
    assert all(alive(people, i) for i in mess.values()), "a tidy deleted before anyone said yes"
    # Every document on the card, with the reason the rules gave.
    assert "- deleted \"test\" (was in Unfiled) — junk title 'test'" in out["response"]
    assert '- deleted "Untitled" (was in Unfiled) — empty' in out["response"]
    assert '- deleted "Re: lunch" (was in Unfiled) — email quote-chain only' in out["response"]
    assert '— a duplicate — the fullest copy stays' in out["response"]
    ask = out["ask_user"]
    assert [o["label"] for o in ask["options"]] == [PLAN_APPROVE_LABEL, PLAN_DECLINE_LABEL]
    assert ask["question"].startswith("Delete 4 documents?")
    # The seal stays on the server: neither the card nor the model reads a hash.
    fed_back = format_tool_result("manage_documents", out)
    assert "digest" not in fed_back and "digest" not in json.dumps(out)


def test_tidy_applies_on_the_person_s_yes_and_only_then(people, mess):
    plan = call({"action": "tidy"})
    early = call({"action": "apply_plan", "plan_id": plan["plan_id"]})
    assert early["exit_code"] == 1 and "has not answered" in early["error"]
    assert all(alive(people, i) for i in mess.values())

    say(people, PLAN_APPROVE_LABEL)
    done = call({"action": "apply_plan", "plan_id": plan["plan_id"]})
    assert done["exit_code"] == 0 and done["outcome"] == "applied", done
    for key in ("junk", "empty", "quotes", "copy"):
        assert not alive(people, mess[key]), key
    for key in ("copy_long", "keep", "fresh"):
        assert alive(people, mess[key]), key
    # The library's own delete: the row stays, switched off — not `db.delete`.
    db = people()
    try:
        assert db.query(cdb.Document).filter(cdb.Document.id == mess["junk"]).count() == 1
    finally:
        db.close()
    assert '- deleted "Untitled" (was in Unfiled) — empty' in done["response"]
    assert "can't be brought back" in done["response"]


def test_any_answer_but_the_yes_deletes_nothing(people, mess):
    plan = call({"action": "tidy"})
    say(people, PLAN_DECLINE_LABEL)
    out = call({"action": "apply_plan", "plan_id": plan["plan_id"]})
    assert out["exit_code"] == 1 and "did not choose" in out["error"]
    plan2 = call({"action": "tidy"})
    say(people, "yes do it", later=2)
    assert call({"action": "apply_plan", "plan_id": plan2["plan_id"]})["exit_code"] == 1
    assert all(alive(people, i) for i in mess.values())


def test_a_tidy_with_nothing_to_remove_says_so(people):
    keep = doc(people, "Budget 2026", content="real numbers")
    # Already deleted: nothing a person can see, so nothing to put to them.
    gone = doc(people, "test", content="")
    db = people()
    db.query(cdb.Document).filter(cdb.Document.id == gone).update({cdb.Document.is_active: False})
    db.commit()
    db.close()
    out = call({"action": "tidy"})
    assert out["exit_code"] == 0 and out["outcome"] == "unchanged", out
    assert "Nothing to tidy" in out["response"] and "ask_user" not in out
    assert alive(people, keep)


def test_a_delete_plan_is_sealed_to_the_content_the_person_saw(people):
    """The card listed an empty "Untitled"; the person then wrote in it. The yes
    was to deleting an empty document, not this one."""
    empty = doc(people, "Untitled", content="")
    plan = call({"action": "tidy"})
    assert [c["id"] for c in plan["changes"]] == [empty]
    db = people()
    db.query(cdb.Document).filter(cdb.Document.id == empty).update(
        {cdb.Document.current_content: "my draft, typed after the plan"})
    db.commit()
    db.close()
    say(people, PLAN_APPROVE_LABEL)
    out = call({"action": "apply_plan", "plan_id": plan["plan_id"]})
    assert out["exit_code"] == 1 and "changed after this plan was shown" in out["error"], out
    assert alive(people, empty)


def test_an_owner_less_tidy_touches_nobody(people, ann):
    """It called `run_document_tidy("")`, and an empty owner there means every
    document in the database."""
    mine = doc(people, "asdf")
    before = state(people, "ann")
    out = call({"action": "tidy"}, owner=None, session_id=None)
    assert out["exit_code"] == 1, out
    assert state(people, "ann") == before and alive(people, mine)


def test_tidy_lists_one_card_s_worth_and_says_how_many_more(people):
    ids = [doc(people, "test", content=f"junk {i}") for i in range(MAX_CHANGES_PER_CALL + 2)]
    out = call({"action": "tidy"})
    assert out["outcome"] == "planned" and len(out["changes"]) == MAX_CHANGES_PER_CALL
    assert f"the first {MAX_CHANGES_PER_CALL} of {MAX_CHANGES_PER_CALL + 2}" in out["response"]
    assert all(alive(people, i) for i in ids)


# ── B994: delete asks first, even for one ───────────────────────────────────

def test_a_single_named_delete_asks_with_a_plan_of_one(people):
    gone = doc(people, "Old draft", folder="Work")
    plan = call({"action": "delete", "document_id": gone})
    assert plan["exit_code"] == 0 and plan["outcome"] == "planned", plan
    assert alive(people, gone)
    assert '- deleted "Old draft" (was in Work)' in plan["response"]
    assert plan["ask_user"]["question"].startswith("Delete 1 document?")

    say(people, PLAN_DECLINE_LABEL)
    assert call({"action": "apply_plan", "plan_id": plan["plan_id"]})["exit_code"] == 1
    assert alive(people, gone)

    again = call({"action": "delete", "document_id": gone})
    say(people, PLAN_APPROVE_LABEL, later=2)
    done = call({"action": "apply_plan", "plan_id": again["plan_id"]})
    assert done["exit_code"] == 0 and not alive(people, gone), done


def test_a_planned_delete_leaves_the_open_document_open_until_it_is_deleted(people):
    """A plan runs its steps and rolls them back. The open-document pointer is
    not in the transaction, so clearing it inside the step cleared it for a
    delete that never happened."""
    gone = doc(people, "Open one")
    document_tools.set_active_document(gone)
    plan = call({"action": "delete"})          # no id: the open document
    assert plan["outcome"] == "planned", plan
    assert document_tools.get_active_document() == gone
    say(people, PLAN_APPROVE_LABEL)
    assert call({"action": "apply_plan", "plan_id": plan["plan_id"]})["exit_code"] == 0
    assert document_tools.get_active_document() is None and not alive(people, gone)


def test_several_deletes_are_one_plan_and_a_wrong_id_refuses_them_all(people):
    a, b = doc(people, "One"), doc(people, "Two")
    refused = call({"action": "delete", "document_ids": [a, "d-typo"]})
    assert refused["exit_code"] == 1 and "d-typo" in refused["error"]
    plan = call({"action": "delete", "document_ids": [a, b]})
    assert plan["outcome"] == "planned" and len(plan["changes"]) == 2
    assert alive(people, a) and alive(people, b)


def test_a_delete_with_no_chat_to_ask_in_is_refused(people):
    gone = doc(people, "Old draft")
    out = call({"action": "delete", "document_id": gone}, session_id=None)
    assert out["exit_code"] == 1 and "no chat to ask them in" in out["error"], out
    assert alive(people, gone)


def test_the_threshold_one_delete_asks_and_five_moves_do_not(people):
    """The two rules side by side (`document_folders.needs_plan`): five moves
    are undone from the card by hand and go ahead; one delete has no way back
    from the library and waits; an empty folder removed is a removal, not a
    delete, and goes ahead."""
    five = [doc(people, f"Doc {i}") for i in range(5)]
    moved = call({"action": "move", "document_ids": five, "to": "Archive"})
    assert moved["outcome"] == "applied", moved
    assert call({"action": "create_folder", "folder": "Spare"})["outcome"] == "applied"
    removed = call({"action": "remove_folder", "folder": "Spare"})
    assert removed["outcome"] == "applied", removed
    one = call({"action": "delete", "document_id": five[0]})
    assert one["outcome"] == "planned"
    step = call({"action": "reorganise", "steps": [
        {"action": "move", "document_ids": [five[1]], "to": "Keep"},
        {"action": "delete", "document_ids": [five[2]]},
    ]})
    assert step["outcome"] == "planned", step
    assert alive(people, five[2]) and state(people, "bob")["folders"].count("Keep") == 0


# ── the scheduled action is not this door (`Law 1`) ─────────────────────────

def test_the_scheduled_tidy_still_runs_unattended_as_it_did(people, mess):
    """`tidy_documents` (`builtin_actions`) is a task the person scheduled; it
    keeps its rules, its hard delete and its sentence."""
    from src.document_actions import run_document_tidy
    said = asyncio.run(run_document_tidy("bob"))
    assert said.startswith("Removed 4 of 7: ") and said.endswith(" · 3 kept"), said
    assert "Notes (+1 duplicate copies)" in said
    db = people()
    try:
        left = {d.id for d in db.query(cdb.Document).filter(cdb.Document.owner == "bob").all()}
    finally:
        db.close()
    assert left == {mess["copy_long"], mess["keep"], mess["fresh"]}


# ── the yes is the person's: the agent cannot write it ──────────────────────

def test_the_agent_cannot_answer_its_own_plan_by_messaging_its_own_chat(people, monkeypatch):
    """Measured before the fix: a plan to delete, then `send_to_session` to the
    chat it was proposed in with "Apply the plan", then `apply_plan` — and the
    document was gone. The message was persisted as the chat's newest user
    message, which is where the plan reads the person's answer. Sending to
    another chat still works (`Law 1`), and does not answer this one's plan."""
    import core.session_manager as csm
    import src.ai_interaction as ai
    import src.llm_core as llm_core

    db = people()
    db.add(cdb.Session(id="chat-bob-2", owner="bob", name="other", model="m",
                       endpoint_url="http://x"))
    db.commit()
    db.close()
    monkeypatch.setattr(csm, "SessionLocal", people)

    async def _reply(*_a, **_k):
        return "ok"

    monkeypatch.setattr(llm_core, "llm_call_async", _reply)
    previous = ai.get_session_manager()
    ai.set_session_manager(csm.SessionManager())
    try:
        gone = doc(people, "Keep me")
        plan = call({"action": "delete", "document_id": gone})
        assert plan["outcome"] == "planned"

        def send(target):
            _d, out = asyncio.run(execute_tool_block(
                ToolBlock("send_to_session", f"{target}\n{PLAN_APPROVE_LABEL}"),
                session_id="chat-bob", owner="bob", security_context=NO_TOOL_SECURITY_CONTEXT))
            return out

        own = send("chat-bob")
        assert own.get("exit_code") == 1 and "chat you are in" in own["error"], own
        other = send("chat-bob-2")
        assert other.get("session_id") == "chat-bob-2" and "error" not in other, other

        out = call({"action": "apply_plan", "plan_id": plan["plan_id"]})
        assert out["exit_code"] == 1 and "has not answered" in out["error"], out
        assert alive(people, gone)
    finally:
        ai.set_session_manager(previous)
