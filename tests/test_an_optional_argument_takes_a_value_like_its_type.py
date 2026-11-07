# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1886` (`anyof-optional-args-never`) — an optional argument is read as the
type it is optional of.

pydantic v2 and FastMCP — what most Python MCP servers are built on —
describe `message: str | None = None` as

    {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null}

with no `type` of its own. `workflow_slots.classify_argument` read only
`schema["type"]`, so it found none and said `never`: every optional text
argument on those servers could not take a value from an earlier step, even
one named `text` or `message`, and `render_call` coerced an optional whole
number as text. Measured before the fix:
`classify_argument("message", {"anyOf": [{"type": "string"}, {"type": "null"}]})`
answered `never` with "Typed only: this could be an address or a command."

Now `effective_schema` reads an `anyOf`/`oneOf` of ONE schema and `null` as
that schema with `null` in its type — and only that shape, so an optional
ADDRESS (`format: uri` inside the `anyOf`) is still `never`, and a choice of
two real types is still `never` (`Law 17`: the name allowlist and the address
formats are the control, and this does not move them).

Driven: the real classifier, the real `render_call`, and the real palette
entry the browser is handed (`workflow_effects._mcp_tool_entry`).
"""
import json

import pytest

from src import workflow_effects as fx
from src.workflow_slots import (
    MAPPING_NEVER,
    MAPPING_VALUE,
    WHY_NOT_TEXT,
    WHY_WHERE,
    SlotError,
    classify_argument,
    render_call,
)

OPTIONAL_TEXT = {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None,
                 "title": "Message"}
OPTIONAL_COUNT = {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None}
OPTIONAL_URL = {"anyOf": [{"type": "string", "format": "uri"}, {"type": "null"}]}


def _ctx(data):
    return {"steps": {"start": {"data": {}, "text": "", "status": "success"},
                      "a": {"data": data, "text": "", "status": "success"}}}


def test_an_optional_text_argument_named_for_text_takes_a_value():
    slot = classify_argument("message", OPTIONAL_TEXT)
    assert slot.mapping == MAPPING_VALUE, slot
    assert classify_argument("message", {**OPTIONAL_TEXT, "anyOf": list(reversed(
        OPTIONAL_TEXT["anyOf"]))}).mapping == MAPPING_VALUE, "the order of the two does not matter"
    assert classify_argument("message", {"oneOf": OPTIONAL_TEXT["anyOf"]}).mapping == MAPPING_VALUE
    # Answered exactly as the plain type is.
    assert slot == classify_argument("message", {"type": ["string", "null"]})


def test_an_optional_address_or_a_name_that_is_not_text_stays_never():
    assert classify_argument("text", OPTIONAL_URL).mapping == MAPPING_NEVER
    assert classify_argument("text", OPTIONAL_URL).why == WHY_WHERE, \
        "an address inside the anyOf is still an address"
    assert classify_argument("to", OPTIONAL_TEXT).why == WHY_NOT_TEXT, "the name allowlist still decides"
    two = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
    assert classify_argument("text", two).mapping == MAPPING_NEVER, "a choice of two types is not 'optional'"
    nested = {"anyOf": [{"$ref": "#/$defs/Thing"}, {"type": "null"}]}
    assert classify_argument("text", nested).mapping == MAPPING_NEVER, "a reference has no type"
    listy = {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]}
    assert classify_argument("body", listy).mapping == MAPPING_NEVER, "a list is never"


def _mcp_call(args, schema_props, data):
    node = {"id": "m", "kind": "mcp", "config": {"tool": "mcp__chat__send", "args": args}}
    return render_call(node, _ctx(data), mcp_schema={"type": "object", "properties": schema_props})


def test_an_optional_argument_is_filled_and_coerced_as_its_type():
    call = _mcp_call({"message": "{{ steps.a.data.words }}", "summary": "{{ steps.a.data.n }}"},
                     {"message": OPTIONAL_TEXT,
                      "summary": {"anyOf": [{"type": "number"}, {"type": "null"}]}},
                     {"words": "Hello there", "n": "4.5"})
    assert json.loads(call.content) == {"message": "Hello there", "summary": 4.5}
    assert call.value_paths == ("args.message", "args.summary")


def test_null_handed_to_an_optional_argument_stays_null():
    call = _mcp_call({"message": "{{ steps.a.data.nothing }}"}, {"message": OPTIONAL_TEXT},
                     {"nothing": None})
    assert json.loads(call.content) == {"message": None}


def test_an_optional_choice_still_holds_its_value_to_the_list():
    schema = {"anyOf": [{"type": "string", "enum": ["calm", "loud"]}, {"type": "null"}]}
    with pytest.raises(SlotError) as refused:
        _mcp_call({"text": "{{ steps.a.data.mood }}"}, {"text": schema}, {"mood": "furious"})
    assert "must be one of calm, loud" in refused.value.sentence


def test_the_palette_hands_the_browser_value_for_an_optional_text_argument():
    entry = fx._mcp_tool_entry({
        "qualified_name": "mcp__chat__send", "name": "send", "input_schema": {
            "type": "object", "properties": {"message": OPTIONAL_TEXT, "channel": OPTIONAL_TEXT,
                                             "link": OPTIONAL_URL}}})
    assert entry["args"]["message"]["mapping"] == MAPPING_VALUE
    assert entry["args"]["channel"] == {"mapping": MAPPING_NEVER, "why": WHY_NOT_TEXT}
    assert entry["args"]["link"]["mapping"] == MAPPING_NEVER
