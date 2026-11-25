# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2171`: the agent's mail tools and the Email page score unsubscribe
candidates with one scorer.

The page's copy (`routes/email_routes.py`) added +35 for a message the spam
classifier had already marked, and said why; the MCP server's copy
(`mcp_servers/email_server.py`) did not, and three helpers beside them were
byte-identical copies. The owner's pick (`D-2026-11-24-02`): the page's scorer
is the one, in `src/mail_unsubscribe.py`, which both processes import.

Before the change the MCP scorer refuses `spam_cached` and its candidate lacks
the page's `spam_reason`, and the parser, scorer and de-duplication are each
defined twice.
"""

from __future__ import annotations

import ast
from email.message import EmailMessage
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _newsletter(*, list_id: bool = True) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "Deals <deals@example.com>"
    msg["Subject"] = "Limited time offer"
    if list_id:
        msg["List-Id"] = "<deals.example.com>"
    msg["Precedence"] = "bulk"
    msg["Message-ID"] = "<m1@example.com>"
    msg["List-Unsubscribe"] = "<mailto:leave@example.com?subject=stop>, <https://example.com/u>"
    msg.set_content("hi")
    return msg


@pytest.mark.parametrize("spam_cached", [
    None,
    {},
    {"spam": True, "reason": "classified as spam: bulk promotion"},
    {"spam": True, "reason": ""},
    {"spam": False, "reason": "looked fine"},
])
@pytest.mark.parametrize("list_id", [True, False])
def test_the_agent_scores_a_message_exactly_as_the_page_does(spam_cached, list_id):
    import mcp_servers.email_server as agent
    from routes import email_routes as page

    msg = _newsletter(list_id=list_id)
    kwargs = {} if spam_cached is None else {"spam_cached": spam_cached}
    on_page = page._email_unsubscribe_candidate_from_msg(msg, "7", "INBOX", **kwargs)
    to_agent = agent._email_unsubscribe_candidate_from_msg(msg, "7", "INBOX", **kwargs)
    assert to_agent == on_page


def test_a_spam_verdict_on_record_raises_the_score_for_the_agent_too():
    import mcp_servers.email_server as agent

    msg = _newsletter(list_id=False)
    plain = agent._email_unsubscribe_candidate_from_msg(msg, "7", "INBOX")
    marked = agent._email_unsubscribe_candidate_from_msg(
        msg, "7", "INBOX", spam_cached={"spam": True, "reason": "classified as spam"})
    assert marked["score"] == min(plain["score"] + 35, 100)
    assert "classified as spam" in marked["reasons"]
    assert marked["spam_reason"] == "classified as spam"


def test_the_agent_and_the_page_de_duplicate_alike():
    import mcp_servers.email_server as agent
    from routes import email_routes as page

    first = page._email_unsubscribe_candidate_from_msg(_newsletter(), "7", "INBOX")
    second = page._email_unsubscribe_candidate_from_msg(_newsletter(), "8", "INBOX")
    assert agent._dedupe_unsubscribe_candidates([first, second]) == \
        page._dedupe_unsubscribe_candidates([first, second])


SHARED = {
    "parse_list_unsubscribe_header", "_parse_list_unsubscribe_header",
    "unsubscribe_candidate_from_msg", "_email_unsubscribe_candidate_from_msg",
    "unsubscribe_candidate_dedupe_key", "_unsubscribe_candidate_dedupe_key",
    "dedupe_unsubscribe_candidates", "_dedupe_unsubscribe_candidates",
}


def test_the_unsubscribe_scorer_is_defined_once():
    where = {}
    for root in ("src", "routes", "core", "services", "mcp_servers"):
        for path in (REPO / root).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.FunctionDef) and node.name in SHARED:
                    where.setdefault(path.relative_to(REPO).as_posix(), []).append(node.name)
    assert set(where) == {"src/mail_unsubscribe.py"}, where
