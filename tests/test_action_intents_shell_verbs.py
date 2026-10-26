# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression: shell verbs must not promote informational chat to agent mode.

The shell-verb pattern used to be a bare word match
(`\\b(deploy|build|...|rm)\\b\\s+\\S+`), so any sentence merely containing one
of these common English words escalated a plain chat turn to agent mode via
routes/chat_routes.py. That broke the module's stated contract ("only promote
plain chat to agent mode when the user asks the assistant to take an action,
not when the user asks how a feature works"). The pattern is now anchored to
imperative position (start of message, optionally after "please") or to a
"can/could/would/will you ..." request.
"""
from src.action_intents import classify_tool_intent


def _needs_tools(text):
    # `B1485`: the live classifier; `message_needs_tools` was a wrapper only tests called.
    return classify_tool_intent(text).needs_tools



def test_informational_shell_questions_stay_plain_chat():
    assert not _needs_tools("What does the grep command do?")
    assert not _needs_tools("How do I tail a log file in production?")
    assert not _needs_tools("Is it safe to kill a process with kill -9?")


def test_incidental_shell_words_stay_plain_chat():
    assert not _needs_tools("My cat ate my homework")
    assert not _needs_tools("The movie was a real kill joy for everyone")


def test_imperative_shell_commands_still_promote_to_agent():
    assert _needs_tools("tail the nginx error log")
    assert _needs_tools("restart the media server")
    assert _needs_tools("please install docker on the host")
    assert _needs_tools("cat /etc/hosts")


def test_can_you_shell_requests_still_promote_to_agent():
    assert _needs_tools("can you grep the logs for 500 errors")
    assert _needs_tools("could you tail the access log")
