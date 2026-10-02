# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-10` — decide and reshape: If, Switch, Set, with no language
(`src/workflow_logic.py`).

`D-2026-10-01-05` §2: a closed list of six operators and two joins, evaluated
with no model and no expression language. The real functions are called
(`Law 20`, option 1): truth tables for every operator, a type mismatch is
false, no operator raises whatever it is handed, `MISSING` is empty and
equal to nothing, Switch takes the first match, and Set builds an object from
picked fields and typed values.
"""

import json
import math
import random

import pytest

from src import workflow_logic as wl
from src import workflow_refs as wr


CTX = wr.build_context({
    "start": {"data": {"subject": "  URGENT: printer on fire ", "from": "Boss@Example.com",
                       "count": "12", "n": 7, "when": "2026-10-02T07:00:00Z", "tags": ["hw", "Ops"],
                       "meta": {"Priority": "high"}, "empty": "", "none": None, "flag": True},
              "text": "hook"},
})


def cond(left, op, right=None):
    return {"left": left, "op": op, "right": right}


def test_the_closed_list_is_six_operators_and_two_joins_each_with_its_words():
    assert wl.OPERATORS == ("equals", "contains", "is_empty", "greater_than", "less_than", "one_of")
    assert wl.JOINS == ("all", "any")
    assert set(wl.OPERATOR_WORDS) == set(wl.OPERATORS) and set(wl.JOIN_WORDS) == set(wl.JOINS)


@pytest.mark.parametrize("op,left,right,expected", [
    # text: trimmed, regardless of case
    ("equals", "  Hello ", "hello", True), ("equals", "Hello", "Hell", False),
    ("equals", "Straße", "STRASSE", True),
    # numbers, numeric text included
    ("equals", "12", 12, True), ("equals", 12.0, "12", True), ("equals", " 1e3 ", 1000, True),
    ("equals", "12a", 12, False), ("equals", 7, 8, False),
    # yes/no
    ("equals", True, "true", True), ("equals", True, " Yes", True), ("equals", False, "no", True),
    ("equals", True, "no", False), ("equals", True, 1, False), ("equals", True, True, True),
    # null, lists, objects, mismatches
    ("equals", None, None, True), ("equals", None, "", False), ("equals", [1, "a"], [1, "a"], True),
    ("equals", {"a": 1}, {"a": 1}, True), ("equals", [1], {"1": 1}, False),
    ("equals", "x", ["x"], False), ("equals", wr.MISSING, wr.MISSING, False),
    ("equals", wr.MISSING, None, False),
    # contains: substring, list member, object key
    ("contains", "URGENT: fire", "urgent", True), ("contains", "calm", "urgent", False),
    ("contains", "anything", "", False), ("contains", "anything", "   ", False),
    ("contains", ["hw", "Ops"], "ops", True), ("contains", [1, 2], "2", True),
    ("contains", ["a"], "b", False), ("contains", {"Priority": 1}, "priority", True),
    ("contains", {"a": 1}, "b", False), ("contains", 12345, "234", False),
    ("contains", wr.MISSING, "x", False), ("contains", "x", None, False),
    # is_empty
    ("is_empty", None, None, True), ("is_empty", wr.MISSING, None, True), ("is_empty", "  ", None, True),
    ("is_empty", [], None, True), ("is_empty", {}, None, True), ("is_empty", 0, None, False),
    ("is_empty", False, None, False), ("is_empty", "x", None, False), ("is_empty", [None], None, False),
    # ordering: numbers and ISO dates, nothing else
    ("greater_than", "12", 9, True), ("greater_than", 9, "12", False), ("less_than", -1, "0", True),
    ("greater_than", 10 ** 400, 5, True), ("equals", 10 ** 400, "1" + "0" * 400, True),
    ("greater_than", "1" + "0" * 400, 1e300, True), ("equals", "007", 7, True),
    ("less_than", "0001-01-01T00:00:00+14:00", "2026-01-01", False),
    ("greater_than", "2026-10-02", "2026-10-01T23:59", True),
    ("less_than", "2026-10-02T07:00:00Z", "2026-10-02T08:00:00+00:00", True),
    ("greater_than", "2026-10-02T09:00:00+02:00", "2026-10-02T08:00:00Z", False),
    ("greater_than", "2026-10-02T08:00", "2026-10-02T07:59:59Z", True),
    ("greater_than", "b", "a", False), ("less_than", "2026-13-40", "2027-01-01", False),
    ("greater_than", True, False, False), ("greater_than", None, 0, False),
    ("greater_than", wr.MISSING, 0, False), ("greater_than", [2], [1], False),
    # one_of: a list, or text split on commas and new lines
    ("one_of", "ops", ["Dev", "OPS"], True), ("one_of", "ops", "dev, ops ,qa", True),
    ("one_of", "ops", "dev\nops", True), ("one_of", 3, "1,2,3", True), ("one_of", "x", "a,b", False),
    ("one_of", "x", None, False), ("one_of", wr.MISSING, "a", False), ("one_of", "", ",,", False),
])
def test_each_operator_reads_the_way_the_design_writes_it(op, left, right, expected):
    assert wl.compare(op, left, right) is expected


WEIRD = [None, wr.MISSING, True, 0, -1, 1.5, math.nan, math.inf, "", "  ", "x", "12", "1e309",
         "2026-10-02", "2026-02-30", "NaN", [], [1, [2]], {}, {"a": {"b": None}}, object(),
         b"bytes", ("t",), {1, 2}, "9" * 400,
         json.loads("1" + "0" * 400),  # a 400-digit integer from a webhook body
         "0001-01-01T00:00:00+14:00",  # a date whose UTC is before year 1: astimezone() overflows
         "9" * 5000]  # more digits than int() reads


def test_no_operator_ever_raises_whatever_it_is_handed():
    for op in (*wl.OPERATORS, "nope", None, 7):
        for left in WEIRD:
            for right in WEIRD:
                assert wl.compare(op, left, right) in (True, False), (op, left, right)


def test_an_unknown_operator_is_false_and_nan_is_not_a_number():
    assert wl.compare("matches", "a", "a") is False
    assert wl.evaluate_condition(cond("a", "eval", "a"), CTX) is False
    assert wl.compare("equals", math.nan, math.nan) is False


@pytest.mark.parametrize("condition,expected", [
    (cond("{{ steps.start.data.subject }}", "contains", "urgent"), True),
    (cond("{{ steps.start.data.subject }}", "equals", "urgent: printer on fire"), True),
    (cond("{{ steps.start.data.from }}", "equals", "boss@example.com"), True),
    (cond("{{ steps.start.data.count }}", "greater_than", "{{ steps.start.data.n }}"), True),
    (cond("{{ steps.start.data.when }}", "less_than", "2026-10-02T08:00:00Z"), True),
    (cond("{{ steps.start.data.tags }}", "contains", "ops"), True),
    (cond("{{ steps.start.data.meta }}", "contains", "priority"), True),
    (cond("{{ steps.start.data.empty }}", "is_empty"), True),
    (cond("{{ steps.start.data.none }}", "is_empty"), True),
    (cond("{{ steps.start.data.gone }}", "is_empty"), True),
    (cond("{{ steps.start.data.gone }}", "equals", ""), False),
    (cond("{{ steps.start.data.none }}", "equals", None), True),   # a real null is null
    (cond("{{ steps.start.data.gone }}", "equals", None), False),  # nothing there is not null
    (cond("{{ steps.start.data.flag }}", "equals", "yes"), True),
    (cond("{{ steps.start.data.from }}", "one_of", ["x@y", "BOSS@example.com"]), True),
    (cond("From {{ steps.start.data.from }}", "contains", "from boss"), True),
    (cond("{{ steps.gone.text }}", "contains", ""), False),
    (cond("{{ STEPS.start.text }}", "equals", "{{ STEPS.start.text }}"), False),
])
def test_a_condition_reads_its_fields_then_compares(condition, expected):
    assert wl.evaluate_condition(condition, CTX) is expected


def test_a_value_holding_a_reference_is_compared_as_text_not_followed():
    ctx = wr.build_context({"a": {"data": {"x": "{{ steps.b.data.y }}"}},
                            "b": {"data": {"y": "secret"}}})
    assert wl.evaluate_condition(cond("{{ steps.a.data.x }}", "equals", "secret"), ctx) is False
    assert wl.evaluate_condition(cond("{{ steps.a.data.x }}", "contains", "steps.b"), ctx) is True


def test_groups_join_all_or_any_and_an_empty_group_is_never_taken():
    yes = cond("a", "equals", "a")
    no = cond("a", "equals", "b")
    assert wl.evaluate_group([yes, yes], "all", CTX) is True
    assert wl.evaluate_group([yes, no], "all", CTX) is False
    assert wl.evaluate_group([yes, no], None, CTX) is False, "all is the default"
    assert wl.evaluate_group([no, yes], "any", CTX) is True
    assert wl.evaluate_group([no, no], "any", CTX) is False
    assert wl.evaluate_group([], "any", CTX) is False and wl.evaluate_group(None, "all", CTX) is False
    assert wl.evaluate_group(["junk", 3], "any", CTX) is False


def test_if_goes_then_or_otherwise_and_has_no_error_port():
    node = {"kind": "if", "config": {"conditions": [
        cond("{{ steps.start.data.subject }}", "contains", "urgent")]}}
    assert wl.choose_port(node, CTX) == "then"
    calm = wr.build_context({"start": {"data": {"subject": "lunch?"}}})
    assert wl.choose_port(node, calm) == "otherwise"
    assert wl.choose_port(node, {}) == "otherwise", "nothing to read is false, never an error"


def test_switch_takes_the_first_case_that_matches_else_otherwise():
    node = {"kind": "switch", "config": {"cases": [
        {"id": "boss", "label": "From the boss",
         "conditions": [cond("{{ steps.start.data.from }}", "contains", "boss")]},
        {"id": "urgent", "label": "Urgent",
         "conditions": [cond("{{ steps.start.data.subject }}", "contains", "urgent")]},
        {"id": "never", "label": "Nothing to test", "conditions": []},
    ]}}
    assert wl.choose_port(node, CTX) == "case:boss", "both match; the first wins"
    other = wr.build_context({"start": {"data": {"from": "a@b", "subject": "URGENT"}}})
    assert wl.choose_port(node, other) == "case:urgent"
    assert wl.choose_port(node, wr.build_context({"start": {"data": {}}})) == "otherwise"
    assert wl.case_port("x") == "case:x"
    with pytest.raises(ValueError):
        wl.choose_port({"kind": "set"}, CTX)


def test_set_builds_an_object_from_picked_fields_and_typed_values():
    node = {"kind": "set", "config": {"fields": [
        {"name": "headline", "value": "{{ steps.start.data.subject }}"},
        {"name": "who", "value": "Mail from {{ steps.start.data.from }}"},
        {"name": "tags", "value": "{{ steps.start.data.tags }}"},
        {"name": "count", "value": 3}, {"name": "ok", "value": False},
        {"name": "shape", "value": {"k": [1]}},
        {"name": "gone", "value": "{{ steps.start.data.gone }}"},
        {"name": "literal", "value": "\\{{ not a reference }}"},
    ]}}
    data, missing = wl.build_set(node, CTX)
    assert data == {"headline": "  URGENT: printer on fire ", "who": "Mail from Boss@Example.com",
                    "tags": ["hw", "Ops"], "count": 3, "ok": False, "shape": {"k": [1]},
                    "gone": None, "literal": "{{ not a reference }}"}
    assert missing == ("{{ steps.start.data.gone }}",)


def test_the_dry_run_says_a_condition_in_words_with_its_references_as_written():
    assert wl.describe_condition(cond("{{ steps.start.data.subject }}", "contains", "URGENT")) == \
        "{{ steps.start.data.subject }} contains “URGENT”"
    assert wl.describe_condition(cond("{{ item.x }}", "is_empty")) == "{{ item.x }} is empty"
    assert wl.describe_condition(cond("a", "one_of", ["b", "c"])) == "a is one of “b, c”"


def test_fuzzed_conditions_evaluate_to_a_boolean_and_never_raise():
    rng = random.Random(2210)
    pieces = ["{{ steps.start.data.subject }}", "{{ steps.start.data.tags }}", "{{ item }}",
              "{{ steps.nope }}", "x", "", "12", None, 3, True, ["a", 1], "{{", "}}"]
    for _ in range(3000):
        c = {"left": rng.choice(pieces), "op": rng.choice((*wl.OPERATORS, "bad")),
             "right": rng.choice(pieces)}
        assert wl.evaluate_condition(c, CTX) in (True, False)
