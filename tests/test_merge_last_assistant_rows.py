# SPDX-License-Identifier: AGPL-3.0-or-later
"""merge-last-assistant must not delete tool/system rows between the messages.

The in-memory merge removes the second assistant message plus only the
"continue" user message between the last two assistant replies. The DB path
deleted the ENTIRE index range between them, destroying any tool/system/user
rows in between — so on reload the DB lost messages the in-memory history
kept (data loss + count desync). _merge_continue_rows_to_delete makes the DB
deletion mirror the in-memory rule.

`B2016`. The merge joined the last two assistant messages whatever stood
between them. `_continue_prompt_between` is the rule it now asks first, of the
conversation in memory and of the stored rows: the message just before the
second reply is a prompt a Continue sent (`is_continue_prompt`, so the step
limit's Continue ▸ prompt is one too, which upstream's list of phrases misses).
"""
from types import SimpleNamespace

import routes.history_routes as history_routes
from routes.history_routes import _merge_continue_rows_to_delete
from src.agent_stops import STEP_LIMIT_CONTINUE_PROMPT


def _m(role, content=""):
    return SimpleNamespace(role=role, content=content)


def test_tool_message_between_is_not_deleted():
    u, a1, tool, a2 = _m("user", "q"), _m("assistant", "a1"), _m("tool", "RESULT"), _m("assistant", "a2")
    rows = _merge_continue_rows_to_delete([u, a1, tool, a2], a1, a2)
    assert rows == [a2]            # only the 2nd assistant
    assert tool not in rows        # the tool result survives


def test_continue_user_message_is_deleted():
    u, a1, cont, a2 = (_m("user", "q"), _m("assistant", "a1"),
                       _m("user", "(the previous response was interrupted)"), _m("assistant", "a2"))
    rows = _merge_continue_rows_to_delete([u, a1, cont, a2], a1, a2)
    assert a2 in rows and cont in rows and len(rows) == 2


def test_adjacent_assistants_delete_only_second():
    a1, a2 = _m("assistant", "a1"), _m("assistant", "a2")
    assert _merge_continue_rows_to_delete([a1, a2], a1, a2) == [a2]


def test_plain_user_between_not_deleted():
    a1, usr, a2 = _m("assistant", "a1"), _m("user", "a real follow-up question"), _m("assistant", "a2")
    rows = _merge_continue_rows_to_delete([a1, usr, a2], a1, a2)
    assert rows == [a2] and usr not in rows


# ── `B2016`: what makes two replies one ─────────────────────────────────────

def test_a_question_the_person_typed_between_two_replies_is_not_a_continue():
    a1, usr, a2 = _m("assistant", "calendar answer"), _m("user", "delete it"), _m("assistant", "search answer")
    assert not history_routes._continue_prompt_between([a1, usr, a2], 0, 2)


def test_an_interrupted_replys_continue_prompt_is_a_continue():
    a1, cont, a2 = (_m("assistant", "partial"),
                    _m("user", "Your previous response was interrupted. Continue."),
                    _m("assistant", "rest"))
    assert history_routes._continue_prompt_between([a1, cont, a2], 0, 2)


def test_the_step_limits_continue_prompt_is_a_continue():
    a1, cont, a2 = _m("assistant", "steps one and two"), _m("user", STEP_LIMIT_CONTINUE_PROMPT), _m("assistant", "step three")
    assert history_routes._continue_prompt_between([a1, cont, a2], 0, 2)


def test_two_replies_with_nothing_between_them_are_not_a_continue():
    a1, a2 = _m("assistant", "a1"), _m("assistant", "a2")
    assert not history_routes._continue_prompt_between([a1, a2], 0, 1)


def test_a_message_held_as_a_dict_is_read_the_same_way():
    """Memory may hold a message as a plain dict; the merge reads both."""
    a1, a2 = {"role": "assistant", "content": "partial"}, {"role": "assistant", "content": "rest"}
    cont = {"role": "user", "content": "Your previous response was interrupted. Continue."}
    typed = {"role": "user", "content": "and the weather?"}
    assert history_routes._continue_prompt_between([a1, cont, a2], 0, 2)
    assert not history_routes._continue_prompt_between([a1, typed, a2], 0, 2)
