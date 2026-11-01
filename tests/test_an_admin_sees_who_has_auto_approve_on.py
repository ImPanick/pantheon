# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1705` — an admin sees every open Auto-approve acceptance, and can turn
one off.

Before: `auto_approve_acceptances` was readable one chat or hire at a time,
by its own person (`GET …/approval-mode`'s `accepted`, a hire's
`auto_approve.accepted`), so an admin could not see who had accepted Auto
where. Now `GET /api/auth/auto-approve` lists every open one with the person,
the chat's or hire's name and the time, and `POST …/withdraw` turns a gate
back on; Settings → Users draws the list (`admin.js` `loadAutoApprove`).

Driven over a real SQLite file (`wf_db`) with a real `AuthManager` (`ada`
the admin, who holds `can_auto_approve`; `bob` a member, who does not), the
real `mode_for` / `hire_lift_for` the agent loop asks, and the real route
handlers.
"""

from __future__ import annotations

import asyncio
import types
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

import core.database as cdb
from src import approval_mode as am
from tests.helpers.signed_in import ADMIN, MEMBER, signed_in
from tests.test_a_workflow_is_kept_as_one_document import wf_db  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def people(monkeypatch, tmp_path):
    return signed_in(monkeypatch, tmp_path / "auth")


def _chat(factory, owner=ADMIN, name="Quarterly numbers"):
    sid = str(uuid.uuid4())
    db = factory()
    try:
        db.add(cdb.Session(id=sid, owner=owner, name=name, endpoint_url="http://localhost", model="m"))
        db.commit()
    finally:
        db.close()
    return sid


def _hire(factory, owner=ADMIN, name="Inbox triage"):
    hid = str(uuid.uuid4())
    db = factory()
    try:
        db.add(cdb.AgentHire(id=hid, owner=owner, agent_id="inbox-triage", version="1", name=name))
        db.commit()
    finally:
        db.close()
    return hid


def _accept_chat(sid, person=ADMIN):
    return am.turn_auto_on(sid, person, am.chat_warning()["id"])


def _accept_hire(hid, person=ADMIN, effects=("external_side_effect",)):
    return cdb.record_auto_approve_acceptance(am.SUBJECT_HIRE, hid, person, "w1", "words", effects)


class _Request:
    def __init__(self, name, manager, body=None):
        self.state = types.SimpleNamespace(current_user=name, api_token=False)
        self.app = types.SimpleNamespace(state=types.SimpleNamespace(auth_manager=manager))
        self.headers = {}
        self.cookies = {}
        self.client = types.SimpleNamespace(host="127.0.0.1")
        self.url = types.SimpleNamespace(path="/api/auth/auto-approve")
        self._body = body or {}

    async def json(self):
        return self._body


@pytest.fixture()
def routes(people):
    import routes.auth_routes as ar

    router = ar.setup_auth_routes(people)

    def endpoint(method, path):
        for r in router.routes:
            if r.path == path and method in r.methods:
                return r.endpoint
        raise AssertionError(path)

    return types.SimpleNamespace(
        list=endpoint("GET", "/api/auth/auto-approve"),
        withdraw=endpoint("POST", "/api/auth/auto-approve/withdraw"),
        manager=people,
    )


def test_every_open_acceptance_is_listed_with_its_person_name_and_time(wf_db, people):  # noqa: F811
    chat = _chat(wf_db)
    hire = _hire(wf_db)
    _accept_chat(chat)
    _accept_hire(hire)
    records = am.open_acceptances(auth_manager=people)
    by_subject = {r["subject"]: r for r in records}
    assert set(by_subject) == {"chat", "hire"}
    assert by_subject["chat"]["name"] == "Quarterly numbers"
    assert by_subject["chat"]["by"] == ADMIN and by_subject["chat"]["at"]
    assert by_subject["hire"]["name"] == "Inbox triage"
    assert by_subject["hire"]["effects"] == ["external_side_effect"]
    assert by_subject["hire"]["effect_words"] == ["send mail or act outside Pantheon"]
    assert all(r["in_effect"] for r in records)


def test_an_acceptance_whose_person_lost_the_privilege_is_listed_as_lifting_nothing(wf_db, people):  # noqa: F811
    chat = _chat(wf_db, owner=MEMBER)
    # Recorded as if bob had held the privilege when he accepted.
    cdb.record_auto_approve_acceptance(am.SUBJECT_CHAT, chat, MEMBER, "w", "words")
    [record] = am.open_acceptances(auth_manager=people)
    assert record["by"] == MEMBER and record["in_effect"] is False


def test_a_withdrawn_one_and_a_gone_chat_read_right(wf_db, people):  # noqa: F811
    chat = _chat(wf_db)
    _accept_chat(chat)
    am.set_mode_for(chat, am.ApprovalMode.MANUAL)
    assert am.open_acceptances(auth_manager=people) == []
    gone = str(uuid.uuid4())
    cdb.record_auto_approve_acceptance(am.SUBJECT_CHAT, gone, ADMIN, "w", "words")
    [record] = am.open_acceptances(auth_manager=people)
    assert record["name"] is None and record["subject_id"] == gone


def test_turning_a_chat_off_puts_it_on_manual_approve(wf_db, people):  # noqa: F811
    chat = _chat(wf_db)
    _accept_chat(chat)
    assert am.mode_for(chat, ADMIN, auth_manager=people) is am.ApprovalMode.AUTO
    assert am.withdraw_for(am.SUBJECT_CHAT, chat) is True
    assert am.mode_for(chat, ADMIN, auth_manager=people) is am.ApprovalMode.MANUAL
    assert cdb.get_session_approval_mode(chat) == "manual"
    assert am.open_acceptances(auth_manager=people) == []


def test_turning_a_hire_off_stops_its_lift(wf_db, people):  # noqa: F811
    hire = _hire(wf_db)
    _accept_hire(hire)
    lift = dict(hired=True, hire_id=hire, allow_effects=("external_side_effect",), auth_manager=people)
    assert am.hire_lift_for(ADMIN, **lift) is True
    assert am.withdraw_for(am.SUBJECT_HIRE, hire) is True
    assert am.hire_lift_for(ADMIN, **lift) is False
    assert am.withdraw_for(am.SUBJECT_HIRE, hire) is False


def test_a_subject_this_module_does_not_have_is_refused():
    with pytest.raises(am.AutoRefused) as refused:
        am.withdraw_for("everything", "x")
    assert refused.value.status == 400


def test_the_routes_are_an_admins(wf_db, routes):  # noqa: F811
    chat = _chat(wf_db)
    _accept_chat(chat)
    listed = asyncio.run(routes.list(_Request(ADMIN, routes.manager)))
    [row] = listed["acceptances"]
    assert row["subject_id"] == chat and row["name"] == "Quarterly numbers"
    assert "warning" not in row
    with pytest.raises(HTTPException) as refused:
        asyncio.run(routes.list(_Request(MEMBER, routes.manager)))
    assert refused.value.status_code == 403
    with pytest.raises(HTTPException) as refused:
        asyncio.run(routes.withdraw(_Request(MEMBER, routes.manager,
                                             {"subject": "chat", "subject_id": chat})))
    assert refused.value.status_code == 403
    done = asyncio.run(routes.withdraw(_Request(ADMIN, routes.manager,
                                                {"subject": "chat", "subject_id": chat})))
    assert done == {"ok": True, "was_on": True}
    assert asyncio.run(routes.list(_Request(ADMIN, routes.manager)))["acceptances"] == []
    with pytest.raises(HTTPException) as refused:
        asyncio.run(routes.withdraw(_Request(ADMIN, routes.manager, {"subject": "nope"})))
    assert refused.value.status_code == 400


def test_settings_users_draws_the_list():
    html = (ROOT / "static" / "index.html").read_text()
    js = (ROOT / "static" / "js" / "admin.js").read_text()
    users = html[html.index('data-settings-panel="users"'):html.index('data-settings-panel="services"')]
    assert 'id="adm-autoApproveList"' in users
    assert "fetch('/api/auth/auto-approve'" in js
    assert "'/api/auth/auto-approve/withdraw'" in js
    refresh = js[js.index("function refreshAll("):]
    assert "loadAutoApprove();" in refresh[:refresh.index("\n}\n")]
