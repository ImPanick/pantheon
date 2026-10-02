# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-16` — an AI step answers as JSON with the fields a person asked for.

The step's `answer_fields` (`[{name, type: text|number|yes/no|list,
description}]`, at most 20) become one instruction at the end of its turn
(`workflow_effects.answer_instruction`), and the reply is checked after the run
(`parse_answer`): the first JSON object found — through code fences and a
reasoning model's `<think>` block — must hold every field with its type.
Fields nobody asked for are dropped, so the step's `data` is exactly what the
next step's picker promised before any run. A reply that does not fit leaves
by the error port with the reason, never with a guess.
"""
import json

import pytest

from src.workflow_effects import (
    ANSWER_FIELDS_MAX,
    ANSWER_FIELD_TYPES,
    answer_instruction,
    parse_answer,
)

FIELDS = [
    {"name": "title", "type": "text", "description": "the page's title"},
    {"name": "url", "type": "text"},
    {"name": "why", "type": "text", "description": "one sentence"},
]


def test_the_instruction_names_every_field_with_its_type():
    text = answer_instruction(FIELDS + [{"name": "score", "type": "number"},
                                        {"name": "urgent", "type": "yes/no"},
                                        {"name": "tags", "type": "list"}])
    assert "```json" in text
    assert '- "title" (text): the page\'s title' in text
    assert '- "url" (text)' in text
    assert '- "score" (a number)' in text
    assert '- "urgent" (true or false)' in text
    assert '- "tags" (a list)' in text


def test_the_instruction_keeps_twenty_fields_and_reads_an_unknown_type_as_text():
    many = [{"name": f"f{i}", "type": "number"} for i in range(30)]
    text = answer_instruction(many)
    assert '"f19"' in text and '"f20"' not in text
    assert ANSWER_FIELDS_MAX == 20
    assert '- "x" (text)' in answer_instruction([{"name": "x", "type": "a schema"}])
    assert ANSWER_FIELD_TYPES == ("text", "number", "yes/no", "list")


def test_a_fenced_answer_gives_exactly_the_fields_asked_for():
    reply = ("Here is what I found.\n```json\n"
             + json.dumps({"title": "Tide tables", "url": "https://example.org/t",
                           "why": "It lists every port.", "extra": "dropped"})
             + "\n```\n")
    data, problem = parse_answer(reply, FIELDS)
    assert problem is None
    assert data == {"title": "Tide tables", "url": "https://example.org/t",
                    "why": "It lists every port."}


def test_reasoning_and_prose_around_the_object_are_looked_through():
    reply = ("<think>I could answer {\"title\": \"wrong\"} but let me check.</think>"
             'Sure! {"title": "Right", "url": "u", "why": "w"} Hope that helps.')
    data, problem = parse_answer(reply, FIELDS)
    assert problem is None and data["title"] == "Right"


def test_the_first_object_is_the_answer():
    reply = ('```json\n{"title": "first", "url": "a", "why": "b"}\n```\n'
             '```json\n{"title": "second", "url": "c", "why": "d"}\n```')
    assert parse_answer(reply, FIELDS)[0]["title"] == "first"


def test_a_model_is_met_halfway_on_types():
    fields = [{"name": "n", "type": "number"}, {"name": "ok", "type": "yes/no"},
              {"name": "items", "type": "list"}, {"name": "label", "type": "text"}]
    data, problem = parse_answer('{"n": "1,250", "ok": "Yes", "items": [1, 2], "label": 7}', fields)
    assert problem is None
    assert data == {"n": 1250, "ok": True, "items": [1, 2], "label": "7"}
    assert parse_answer('{"n": 2.5, "ok": false, "items": [], "label": "x"}', fields)[0]["n"] == 2.5


@pytest.mark.parametrize("reply,problem", [
    ('{"title": "t", "url": "u"}', "The answer has no “why”."),
    ('{"title": ["t"], "url": "u", "why": "w"}', "The answer's “title” is not text."),
    ("I could not find anything.", "The answer did not end in the JSON object this step asks for."),
    ('["title", "url", "why"]', "The answer did not end in the JSON object this step asks for."),
])
def test_an_answer_that_does_not_fit_says_why(reply, problem):
    assert parse_answer(reply, FIELDS) == (None, problem)


@pytest.mark.parametrize("value,kind", [
    ("many", "number"), (True, "number"), ("maybe", "yes/no"), (1, "yes/no"),
    ("a, b", "list"), ({"a": 1}, "text"), (None, "text"),
])
def test_a_wrong_type_is_refused(value, kind):
    data, problem = parse_answer(json.dumps({"f": value}), [{"name": "f", "type": kind}])
    assert data is None and problem.startswith("The answer's “f” is not")


def test_the_instruction_and_the_check_agree():
    fields = [{"name": "total", "type": "number"}, {"name": "late", "type": "yes/no"}]
    text = answer_instruction(fields)
    reply = "Done.\n```json\n" + json.dumps({"total": 12, "late": False}) + "\n```"
    assert parse_answer(reply, fields) == ({"total": 12, "late": False}, None)
    assert all(f'"{f["name"]}"' in text for f in fields)
