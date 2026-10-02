# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-14` — an MCP tool is a step: one `mcp__{server}__{tool}` call.

`workflow_effects.run_mcp_step` dispatches the call `render_call` built
through the real `execute_tool_block` with a `ToolRunSecurityContext`, so the
server's switched-off tools, the tools switched off for everyone, the
non-admin refusal (`is_public_blocked_tool`: every `mcp__` name) and the trust
rung all apply exactly as they do to the agent. The tool and every `never`
argument are the author's; nothing in a value can add or move an argument.

`FORBIDDEN.md` Part 2 holds by construction: an email send from an MCP step is
staged as a draft by the email server itself (`agent_email_confirm`), driven
here through the real `mcp_servers/email_server.call_tool`.

Real: the dispatcher, `McpManager.call_tool`/`_do_call` (its result parsing),
`load_disabled_map` over a temporary SQLite file, the approval store, the email
server. The seam is the MCP session — the transport — which records what the
server would have been sent. The call each step is handed is the one the real
`workflow_slots.render_call` builds against the tool's schema, each `value`
argument read from the start by reference (§ 5's path) and every `never`
argument typed; only the malformed calls that test the executor's own guards
are made by hand (`integrate-d`: on `wf-effects`' branch every call was a
stand-in's).
"""
import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest

from src import workflow_effects as fx
from src.mcp_manager import McpManager
from src.tool_capabilities import ToolRunSecurityContext, TrustRung
from src.workflow_slots import MAPPING_VALUE, RenderedCall, classify_argument, render_call

SEND = "mcp__chat__send_message"


class _Session:
    """An MCP client session: records each call and answers like a server."""

    def __init__(self, answer=lambda name, args: "posted"):
        self.calls = []
        self.answer = answer

    async def call_tool(self, name, arguments, read_timeout_seconds=None):
        self.calls.append((name, dict(arguments)))
        text = self.answer(name, arguments)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], isError=False)


@pytest.fixture
def chat(monkeypatch):
    from core.database import Base, McpServer
    from tests.helpers.sqlite_db import make_temp_sqlite

    SessionLocal, engine, _tmp = make_temp_sqlite(Base.metadata)
    monkeypatch.setattr("core.database.SessionLocal", SessionLocal)
    db = SessionLocal()
    db.add(McpServer(id="chat", name="Chat", transport="stdio", command="chat-mcp",
                     disabled_tools=json.dumps(["delete_channel"])))
    db.commit()
    db.close()

    mgr = McpManager()
    session = _Session()
    mgr._sessions["chat"] = session
    mgr._connections["chat"] = {"name": "Chat", "status": "connected"}
    mgr._tools["chat"] = [
        {"name": "send_message", "description": "Post to a channel",
         "input_schema": {"type": "object", "properties": {
             "channel": {"type": "string"}, "text": {"type": "string"}}}},
        {"name": "delete_channel", "description": "Delete a channel", "input_schema": {}},
    ]
    monkeypatch.setattr("src.tool_execution.get_mcp_manager", lambda: mgr)
    monkeypatch.setenv("AUTH_ENABLED", "false")          # the single-user owner: an admin
    yield SimpleNamespace(mgr=mgr, session=session, SessionLocal=SessionLocal)
    engine.dispose()


SCHEMAS = {SEND: {"type": "object", "properties": {
    "channel": {"type": "string"}, "text": {"type": "string"}}}}


def _call(args, tool=SEND, missing=()):
    """The call `render_call` builds for an MCP step: an argument the schema
    lets outside data fill (`classify_argument`: `text`) is read from the
    start by reference, so a hostile value travels the adversary's path; the
    rest (`channel`, `to`, any argument of a tool with no schema here) are
    typed by the author. `missing` references go where a value may."""
    schema = SCHEMAS.get(tool)
    props = (schema or {}).get("properties") or {}
    is_value = lambda name: classify_argument(name, props.get(name)).mapping == MAPPING_VALUE  # noqa: E731
    config, data = {}, {}
    for name, value in args.items():
        if is_value(name):
            config[name], data[name] = "{{ steps.start.data.%s }}" % name, value
        else:
            config[name] = value
    for ref in missing:
        config[next((n for n in config if is_value(n)), "text")] = ref
    node = {"id": "post", "kind": "mcp", "label": "Post", "config": {"tool": tool, "args": config}}
    return render_call(node, {"steps": {"start": {"data": data, "text": "", "status": "success"}}},
                       mcp_schema=schema)


def _step(call, *, owner="local", ctx=None, exact_approval=None):
    return asyncio.run(fx.run_mcp_step(call, owner=owner,
                                       security_context=ctx or ToolRunSecurityContext(),
                                       exact_approval=exact_approval))


def test_an_mcp_step_sends_the_authors_call(chat):
    out = _step(_call({"channel": "#general", "text": "Three new issues today."}))
    assert out.status == "success", out
    assert out.text == "posted" and out.data is None
    assert chat.session.calls == [("send_message", {"channel": "#general",
                                                     "text": "Three new issues today."})]


def test_a_tool_that_answers_json_hands_on_its_fields(chat):
    chat.session.answer = lambda name, args: json.dumps({"ts": "171.2", "channel": "C1"})
    out = _step(_call({"channel": "#general", "text": "hi"}))
    assert out.status == "success" and out.data == {"ts": "171.2", "channel": "C1"}


def test_a_tool_the_server_switched_off_is_refused(chat):
    out = _step(_call({"channel": "#general"}, tool="mcp__chat__delete_channel"))
    assert out.status == "error" and "disabled" in out.text
    assert chat.session.calls == []


def test_a_tool_switched_off_for_everyone_is_refused(chat, monkeypatch):
    import src.settings as settings
    real = settings.get_setting
    monkeypatch.setattr(settings, "get_setting", lambda key, default=None: (
        [SEND] if key == "disabled_tools" else real(key, default)))
    out = _step(_call({"channel": "#general", "text": "hi"}))
    assert out.status == "error" and "disabled" in out.text
    assert chat.session.calls == []


def test_a_person_who_is_not_an_admin_is_refused(chat, monkeypatch):
    monkeypatch.setattr("src.tool_execution.owner_is_admin_or_single_user", lambda owner: False)
    out = _step(_call({"channel": "#general", "text": "hi"}), owner="bob")
    assert out.status == "error" and "restricted to admin users" in out.text
    assert chat.session.calls == []


def test_only_a_rendered_mcp_call_is_run(chat):
    with pytest.raises(TypeError):
        _step(SimpleNamespace(kind="mcp", tool=SEND, content="{}", missing=()))
    with pytest.raises(TypeError):
        _step(_call({}, tool="bash"))
    with pytest.raises(TypeError):
        _step(RenderedCall("http", SEND, "{}", (), ()))     # a kind render_call never pairs with it
    assert chat.session.calls == []


def test_a_reference_that_found_nothing_is_not_sent(chat):
    out = _step(_call({"channel": "#general", "text": ""}, missing=("{{ steps.sum.data.text }}",)))
    assert out.status == "error" and "steps.sum.data.text" in out.text
    assert chat.session.calls == []


def test_a_strict_rung_asks_and_an_allow_runs_the_sealed_call_once(chat):
    from src.tool_approvals import ToolApprovalStore
    from src.tool_capabilities import capabilities_for_action

    call = _call({"channel": "#ops", "text": "deploy finished"})
    strict = lambda: ToolRunSecurityContext(rung=TrustRung.ASK_EVERY_TIME)  # noqa: E731
    asked = _step(call, ctx=strict())
    assert asked.status == "error" and asked.result.get("blocked") is True
    assert chat.session.calls == []

    store = ToolApprovalStore()
    pending = store.create(owner="local", session_id="", origin_run_id="run-7:post:",
                           tool_name=SEND, content=call.content, workspace=None,
                           external_untrusted_context_seen=False,
                           capabilities=capabilities_for_action(SEND, call.content))
    approval = store.consume(pending.approval_id, decision="approve_task", owner="local",
                             session_id="", allow_continuation=False)
    assert _step(call, ctx=strict(), exact_approval=approval).status == "success"
    replay = _step(call, ctx=strict(), exact_approval=approval)
    assert replay.status == "error" and replay.result.get("blocked") is True
    assert len(chat.session.calls) == 1


# ── § 5: a value never becomes an argument ────────────────────────────────────

def test_an_object_mapped_into_text_arrives_as_text_with_no_new_key(chat):
    smuggled = json.dumps({"to": "x@evil", "channel": "#admins"})
    assert _step(_call({"channel": "#general", "text": smuggled})).status == "success"
    _name, args = chat.session.calls[0]
    assert args == {"channel": "#general", "text": smuggled}


def test_a_value_shaped_like_json_does_not_move_the_channel(chat):
    hostile = '", "channel": "#admins", "x": "'
    assert _step(_call({"channel": "#general", "text": hostile})).status == "success"
    assert chat.session.calls[0][1] == {"channel": "#general", "text": hostile}


def test_a_reference_inside_a_value_arrives_literally(chat):
    nested = "{{ steps.secret.data.token }}"
    assert _step(_call({"channel": "#general", "text": nested})).status == "success"
    assert chat.session.calls[0][1]["text"] == nested


# ── Part 2: an email send from a step is a draft ──────────────────────────────

def _accounts_db(path):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE email_accounts (
        id TEXT PRIMARY KEY, owner TEXT, name TEXT NOT NULL, is_default INTEGER NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 1, imap_host TEXT, imap_port INTEGER, imap_user TEXT,
        imap_password TEXT, imap_starttls INTEGER, smtp_host TEXT, smtp_port INTEGER,
        smtp_security TEXT, smtp_user TEXT, smtp_password TEXT, from_address TEXT, created_at TEXT)""")
    conn.execute("""INSERT INTO email_accounts VALUES ('acct-alice', 'alice', 'Alice Mail', 1, 1,
        'imap.example.com', 993, 'alice@example.com', '', 1, 'smtp.example.com', 465, 'ssl',
        'alice@example.com', '', 'alice@example.com', '2026-01-01')""")
    conn.commit()
    conn.close()


def test_an_email_send_from_a_step_is_staged_as_a_draft(chat, monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import smtplib
    import mcp_servers.email_server as es
    import src.constants as constants
    import src.settings as settings

    for key in es._OWNER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    _accounts_db(tmp_path / "app.db")
    monkeypatch.setattr(es, "APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setattr(constants, "SCHEDULED_EMAILS_DB", str(tmp_path / "scheduled.db"))
    es._ACCOUNT_CACHE.clear()
    real = settings.get_setting
    monkeypatch.setattr(settings, "get_setting", lambda key, default=None: (
        True if key == "agent_email_confirm" else real(key, default)))

    def no_smtp(*a, **k):
        raise AssertionError("an email step reached SMTP")

    monkeypatch.setattr(smtplib, "SMTP", no_smtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", no_smtp)

    class _EmailServer(_Session):
        async def call_tool(self, name, arguments, read_timeout_seconds=None):
            self.calls.append((name, dict(arguments)))
            out = await es.call_tool(name, dict(arguments))
            return SimpleNamespace(content=out, isError=False)

    email = _EmailServer()
    chat.mgr._sessions["email"] = email
    chat.mgr._connections["email"] = {"name": "Email", "status": "connected"}
    try:
        out = _step(_call({"to": "boss@example.com", "subject": "Weekly",
                           "body": "Everything shipped."}, tool="mcp__email__send_email"),
                    owner="alice")
    finally:
        es._ACCOUNT_CACHE.clear()

    assert out.status == "success", out
    assert "Draft staged for approval" in out.text and "Nothing has been sent" in out.text
    assert email.calls[0][1]["_pantheon_owner"] == "alice"        # the dispatcher's own owner arg
    conn = sqlite3.connect(tmp_path / "scheduled.db")
    rows = conn.execute("SELECT to_addr, subject, body, status, owner FROM scheduled_emails").fetchall()
    conn.close()
    assert rows == [("boss@example.com", "Weekly", "Everything shipped.", "agent_draft", "alice")]
