# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1934`. A task delivering through an MCP tool said it delivered while nothing was sent.

A scheduled task's Output (or a workflow step's) can be an MCP tool, and the
Output picker offers the email server's `send_email`. `_deliver_via_mcp`
never raised. It asked `_get_email_config()` with no owner, which falls back
to the first default mailbox of any owner (another person's address, as its
own SECURITY note says), and it sent no `_pantheon_owner`. On any install
whose mail account was added in the UI the email server then refused the send
in a text reply ("Error: email MCP requires an authenticated owner ..."). That
reply, a non-zero exit, a missing MCP manager and any exception were logged and
swallowed, so the run said success and nothing was sent or staged.

Now the recipient is the owner's own mailbox and the owner rides with the call,
together: the owner alone would mail one person's result to another person's
address. A failed delivery raises, which both callers already handle (a task
run ends as an error and says why; a workflow step says the result could not
be delivered). `send_email` counts as delivered when it says it sent the mail
or that it staged a draft for approval: outbound-email confirmation is on by
default (`FORBIDDEN.md` Part 2), and a staged draft is that control working. A
custom tool keeps only the generic checks, so one that answers "ok" succeeds.

Ported from upstream Odysseus a646b591, whose test is the source of the failure
cases (`_odysseus_owner` is `_pantheon_owner` here). Upstream also fails a
staged draft, which would make every correctly owned email delivery an error
here, so that case is reversed.
"""
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.task_scheduler import TaskScheduler

SENT = "Sent email to alice@example.test with subject '[Task] Digest'."
STAGED = ("Draft staged for approval (pending id: p1). Nothing has been sent yet. "
          "Review and approve it in Pantheon before delivery.")
OWNER_REFUSAL = ("Error: email MCP requires an authenticated owner or PANTHEON_MCP_EMAIL_OWNER "
                 "when owner-scoped email accounts are configured.")


def _manager(monkeypatch, reply):
    manager = SimpleNamespace(call_tool=AsyncMock(return_value=reply))
    monkeypatch.setattr("src.tool_utils.get_mcp_manager", lambda: manager)
    return manager


async def _deliver(tool, owner="alice"):
    task = SimpleNamespace(id="task", name="Digest", owner=owner)
    await TaskScheduler(None)._deliver_via_mcp(tool, task, "content")


async def test_the_owner_s_own_mailbox_is_the_recipient_and_the_owner_rides_with_it(monkeypatch):
    asked = []
    monkeypatch.setattr("routes.email_helpers._get_email_config",
                        lambda **kw: asked.append(kw) or {"from_address": "alice@example.test"})
    manager = _manager(monkeypatch, {"exit_code": 0, "stdout": SENT})
    await _deliver("mcp__email__send_email")
    assert asked == [{"owner": "alice"}]
    args = manager.call_tool.await_args.args[1]
    assert args["to"] == "alice@example.test"
    assert args["_pantheon_owner"] == "alice"


@pytest.mark.parametrize("reply", [
    {"exit_code": 1, "stderr": "failed"},
    {"error": "not connected", "exit_code": 1},
    {"exit_code": 0, "stdout": OWNER_REFUSAL},
    {"exit_code": 0, "stdout": "Error: SMTP failed"},
    {},
    None,
])
async def test_a_send_email_that_did_not_send_fails_the_delivery(monkeypatch, reply):
    monkeypatch.setattr("routes.email_helpers._get_email_config", lambda **kw: {})
    _manager(monkeypatch, reply)
    with pytest.raises(RuntimeError):
        await _deliver("mcp__email__send_email")


async def test_a_draft_staged_for_approval_is_delivered_not_a_failure(monkeypatch):
    monkeypatch.setattr("routes.email_helpers._get_email_config",
                        lambda **kw: {"from_address": "alice@example.test"})
    manager = _manager(monkeypatch, {"exit_code": 0, "stdout": STAGED})
    await _deliver("mcp__email__send_email")
    assert manager.call_tool.await_args.args[1]["_pantheon_owner"] == "alice"


async def test_a_custom_tool_keeps_the_generic_checks(monkeypatch):
    monkeypatch.setattr("routes.email_helpers._get_email_config", lambda **kw: {})
    manager = _manager(monkeypatch, {"exit_code": 0, "stdout": "ok"})
    await _deliver("mcp__custom__send")
    assert "_pantheon_owner" not in manager.call_tool.await_args.args[1], "the email server's own field"
    _manager(monkeypatch, {"exit_code": 0, "stdout": "Error: delivery failed"})
    with pytest.raises(RuntimeError):
        await _deliver("mcp__custom__send")


async def test_with_no_mcp_manager_the_delivery_fails(monkeypatch):
    monkeypatch.setattr("src.tool_utils.get_mcp_manager", lambda: None)
    with pytest.raises(RuntimeError, match="MCP manager not available"):
        await _deliver("mcp__email__send_email")


async def test_through_the_real_email_server_the_owner_s_draft_is_staged(monkeypatch, tmp_path):
    """End to end: the real `_get_email_config` over two people's accounts,
    the real `McpManager` reply parsing and the real email server. Before, the
    recipient was bob's mailbox (the first default of any owner) and the server
    refused the ownerless send in a reply the run logged as delivered."""
    pytest.importorskip("mcp")
    import smtplib

    import core.database as cdb
    import mcp_servers.email_server as es
    import src.constants as constants
    import src.settings as settings
    from src.mcp_manager import McpManager
    from tests.helpers.sqlite_db import make_temp_sqlite

    SessionLocal, engine, db_file = make_temp_sqlite(cdb.Base.metadata)
    monkeypatch.setattr(cdb, "SessionLocal", SessionLocal)
    db = SessionLocal()
    for owner in ("bob", "alice"):   # bob's first: what the ownerless lookup picks
        db.add(cdb.EmailAccount(id=f"acct-{owner}", owner=owner, name=owner, is_default=True,
                                enabled=True, imap_user=f"{owner}@example.test",
                                from_address=f"{owner}@example.test", smtp_host="smtp.example.test"))
    db.commit()
    db.close()
    for key in es._OWNER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(es, "APP_DB", db_file.name)
    monkeypatch.setattr(constants, "SCHEDULED_EMAILS_DB", str(tmp_path / "scheduled.db"))
    real = settings.get_setting
    monkeypatch.setattr(settings, "get_setting", lambda key, default=None: (
        True if key == "agent_email_confirm" else real(key, default)))

    def no_smtp(*a, **k):
        raise AssertionError("a task delivery reached SMTP")

    monkeypatch.setattr(smtplib, "SMTP", no_smtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", no_smtp)

    class EmailServer:
        async def call_tool(self, name, arguments, read_timeout_seconds=None):
            return SimpleNamespace(content=await es.call_tool(name, dict(arguments)), isError=False)

    mgr = McpManager()
    mgr._sessions["email"] = EmailServer()
    mgr._connections["email"] = {"name": "Email", "status": "connected"}
    monkeypatch.setattr("src.tool_utils.get_mcp_manager", lambda: mgr)
    es._ACCOUNT_CACHE.clear()
    try:
        await _deliver("mcp__email__send_email")
    finally:
        es._ACCOUNT_CACHE.clear()
        engine.dispose()

    assert (tmp_path / "scheduled.db").exists(), "nothing was staged"
    conn = sqlite3.connect(tmp_path / "scheduled.db")
    rows = conn.execute("SELECT to_addr, subject, status, owner FROM scheduled_emails").fetchall()
    conn.close()
    assert rows == [("alice@example.test", "[Task] Digest", "agent_draft", "alice")]
