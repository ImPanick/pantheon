# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1824`. A draft the mail server refused was reported as saved.

The composer's Draft button APPENDs the draft to the account's Drafts folder.
`save_draft` dropped the APPEND's answer, and imaplib raises only on `BAD`: a
server that answers `NO` — over quota, or `[TRYCREATE]` for a Drafts folder it
does not have (`_detect_drafts_folder` falls back to a bare "Drafts") — saved
nothing, and the composer said "Draft saved to mailbox". Its Close button then
deletes the compose document, and a new compose keeps no copy in the browser,
so what had been written was gone. Now a refusal is the route's error, in the
server's words, which the composer already shows for any other failure.

Pantheon's two other APPENDs (the Sent copy that `/send` and the agent's
`send_email` keep) already read the answer. Upstream Odysseus made the same
check in 84aa9a91.

Driven (`Law 20`): the real route, over a fake IMAP connection.
"""
import asyncio
from contextlib import contextmanager

import pytest


def _route_endpoint(router, path: str, method: str):
    for route in router.routes:
        if route.path == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class _Mailbox:
    """A mailbox with a Drafts folder that answers an APPEND with `answer`."""

    def __init__(self, answer):
        self.answer = answer
        self.appended = []

    def list(self, *args):
        return "OK", [b'(\\HasNoChildren \\Drafts) "/" "Drafts"']

    def append(self, mailbox, flags, date_time, message):
        self.appended.append((mailbox, flags))
        return self.answer


def _save_a_draft(monkeypatch, answer):
    import routes.email_routes as email_routes
    from routes.email_helpers import SendEmailRequest

    mailbox = _Mailbox(answer)

    @contextmanager
    def fake_imap(account_id=None, owner=""):
        yield mailbox

    monkeypatch.setattr(email_routes, "_start_poller", lambda: None)
    monkeypatch.setattr(email_routes, "_imap", fake_imap)
    monkeypatch.setattr(email_routes, "_get_email_config",
                        lambda *_a, **_k: {"from_address": "alice@example.test"})
    save_draft = _route_endpoint(email_routes.setup_email_routes(), "/api/email/draft", "POST")
    request = SendEmailRequest(to="bob@example.test", subject="Plans", body="What I wrote")
    return asyncio.run(save_draft(request, owner="alice")), mailbox


@pytest.mark.parametrize("words", [b"[OVERQUOTA] Quota exceeded",
                                   b"[TRYCREATE] Mailbox does not exist"],
                         ids=["over-quota", "no-such-folder"])
def test_a_draft_the_server_refuses_is_not_called_saved(monkeypatch, words):
    result, mailbox = _save_a_draft(monkeypatch, ("NO", [words]))
    assert mailbox.appended == [("Drafts", "\\Draft")]
    assert result["success"] is False, result
    assert words.decode() in result["error"]
    assert "Drafts" in result["error"]


def test_a_draft_the_server_takes_is_saved(monkeypatch):
    result, mailbox = _save_a_draft(monkeypatch, ("OK", [b"[APPENDUID 1 7] APPEND completed"]))
    assert mailbox.appended == [("Drafts", "\\Draft")]
    assert result == {"success": True, "message": "Draft saved"}
