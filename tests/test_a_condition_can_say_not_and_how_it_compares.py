# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1880` (`condition-operators-and-coercion`) — a condition can say "not",
"starts with", a pattern, "at least" and "older than 2 days", and what it
compares its two sides as.

The audit found the If and Switch steps had six operators and no way to say
"status is not closed", "does not contain", "is not empty", "starts with",
"at least", a pattern, or a date relative to now; that numeric-looking text
always compared as numbers, so the zip code "02134" equalled "2134", the
order "007" equalled "7" and "1e3" equalled "1000"; that text never ordered
("b" is more than "a" was false); and that "is one of" could not hold a
choice with a comma in it ("Smith, John").

What these cases hold (pure functions, called — `Law 20`, option 1 — and the
real `TaskScheduler` over a real SQLite file for a run):

  * eleven operators added after the six, the list still closed, each
    "not" the exact opposite of its plain word;
  * a condition's `as` — text, exact text, a number, a date, yes/no, how
    many — and two texts equal as numbers only when both are plain numbers;
  * "is one of" text with new lines is one choice on each line;
  * `matches` reads a pattern in time proportional to the text whatever the
    pattern (`src/workflow_pattern.py`). The adversary (`Law 17`) is whoever
    writes the mail or webhook body a pattern is run on, and the author's
    own pattern: `(a+)+$` on 20,000 characters of "a" answers at once,
    where Python's `re` would not finish; it agrees with `re` on what is
    found, on generated patterns;
  * `is_before` / `is_after` read dates and words ("2 days ago") counted
    from the run's `{{ now }}`;
  * a pattern or date that cannot be read is refused at save, on its field.
"""

import random
import re
import time
from datetime import datetime, timezone

import pytest

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

from src import workflow_document as wd  # noqa: E402
from src import workflow_logic as wl  # noqa: E402
from src import workflow_refs as wr  # noqa: E402
from tests.helpers.walker_harness import (  # noqa: E402
    arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow,
)

AT = datetime(2026, 11, 7, 8, 0, 0, tzinfo=timezone.utc)
NEW = ("not_equals", "not_contains", "is_not_empty", "not_one_of", "starts_with", "ends_with",
       "matches", "at_least", "at_most", "is_before", "is_after")


def compare(op, left, right=None, **kw):
    kw.setdefault("now", AT)
    return wl.compare(op, left, right, **kw)


# ── The list ─────────────────────────────────────────────────────────────────

def test_eleven_operators_follow_the_six_and_each_has_its_words():
    assert wl.OPERATORS == ("equals", "contains", "is_empty", "greater_than", "less_than",
                            "one_of", *NEW)
    assert {op: wl.OPERATOR_WORDS[op] for op in NEW} == {
        "not_equals": "is not", "not_contains": "does not contain",
        "is_not_empty": "is not empty", "not_one_of": "is not one of",
        "starts_with": "starts with", "ends_with": "ends with",
        "matches": "matches the pattern", "at_least": "is at least", "at_most": "is at most",
        "is_before": "is before", "is_after": "is after"}
    assert wl.UNARY_OPERATORS == ("is_empty", "is_not_empty")
    assert wl.LIST_OPERATORS == ("one_of", "not_one_of")
    assert wl.DATE_OPERATORS == ("is_before", "is_after")
    assert wl.COMPARE_AS == ("text", "exact", "number", "date", "yes/no", "length")
    assert set(wl.COMPARE_AS_WORDS) == set(wl.COMPARE_AS)


GRID = [wr.MISSING, None, True, False, 0, 7, "7", "007", 1.5, "", "  ", "closed", "Closed",
        "Smith, John", "2026-11-01", "2 days ago", ["a", "b"], ["7"], {}, {"a": 1}]


NOTS = [("is_not_empty", "is_empty"), ("not_contains", "contains"), ("not_equals", "equals"),
        ("not_one_of", "one_of")]


@pytest.mark.parametrize("op,plain", NOTS)
def test_each_not_is_exactly_the_opposite_of_its_plain_word(op, plain):
    assert sorted(wl.NEGATED.items()) == NOTS
    for kind in (None, *wl.COMPARE_AS):
        for left in GRID:
            for right in GRID:
                assert compare(op, left, right, as_type=kind) is (
                    not compare(plain, left, right, as_type=kind)), (op, kind, left, right)


def test_no_new_operator_ever_raises_whatever_it_is_handed():
    weird = [*GRID, object(), b"x", float("nan"), float("inf"), "9" * 5000, "(a+)+$",
             "in 999999 weeks", "0001-01-01T00:00:00+14:00", [[{}]], {"a": {"b": None}}]
    for op in NEW:
        for kind in (None, *wl.COMPARE_AS, "bogus"):
            for left in weird:
                for right in weird:
                    assert compare(op, left, right, as_type=kind) in (True, False)


# ── Numbers that are text, and text that orders ──────────────────────────────

@pytest.mark.parametrize("left,right,expected", [
    ("02134", "2134", False), ("007", "7", False), ("1e3", "1000", False), ("+5", "5", False),
    ("12", "12.0", True), (" 3.50 ", "3.5", True), ("-0", "0", True),
    # A real number beside text reads the text as a number, as it always did.
    ("007", 7, True), (" 1e3 ", 1000, True), (12.0, "12", True),
])
def test_two_texts_are_the_same_number_only_when_both_are_plain_numbers(left, right, expected):
    assert compare("equals", left, right) is expected
    assert compare("not_equals", left, right) is (not expected)


@pytest.mark.parametrize("op,left,right,kind,expected", [
    ("greater_than", "b", "a", None, False),         # as it looks: as it always was
    ("greater_than", "b", "a", "text", True),
    ("less_than", "Apple", "banana", "text", True),
    ("at_least", "b", "B", "text", True),
    ("less_than", "Apple", "banana", "exact", True),
    ("greater_than", "a", "B", "exact", True),         # capitals count, and sort first
    ("equals", "007", "7", "number", True),
    ("equals", "007", "7", "text", False),
    ("equals", "Hello", "hello", "exact", False),
    ("equals", " Hello ", "hello", "text", True),
    ("equals", "on", "yes", "yes/no", True),
    ("equals", "0", False, "yes/no", True),
    ("equals", "maybe", False, "yes/no", False),
    ("greater_than", "yes", "no", "yes/no", False),    # yes and no do not order
    ("equals", "2026-11-07T09:00:00+01:00", "2026-11-07T08:00Z", "date", True),
    ("greater_than", "2026-11-07", "yesterday", "date", True),
    ("at_least", ["a", "b"], "2", "length", True),
    ("at_most", "abc", 2, "length", False),
    ("equals", None, 0, "length", True),
    ("greater_than", 5, 1, "length", False),           # a number has no length
    ("contains", "Hello", "ELL", "exact", False),
    ("contains", "Hello", "ELL", "text", True),
    ("contains", ["07", "8"], 7, "number", True),
    ("contains", ["07", "8"], 7, "exact", False),
    ("contains", ["7", "8"], 7, "exact", True),        # 7 is written "7"
    ("one_of", "007", ["7", "8"], "number", True),
    ("one_of", "007", ["7", "8"], None, False),
])
def test_a_condition_compares_its_sides_as_it_says(op, left, right, kind, expected):
    assert compare(op, left, right, as_type=kind) is expected


def test_an_as_that_is_not_one_of_the_words_is_false():
    assert compare("equals", "a", "a", as_type="integer") is False
    assert compare("not_equals", "a", "b", as_type="integer") is False


# ── New words ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("op,left,right,expected", [
    ("not_equals", "open", "closed", True), ("not_equals", "Closed", "closed", False),
    ("not_equals", wr.MISSING, "closed", True),       # nothing there is not "closed"
    ("not_contains", "all calm", "urgent", True), ("not_contains", "URGENT!", "urgent", False),
    ("is_not_empty", "x", None, True), ("is_not_empty", "  ", None, False),
    ("is_not_empty", wr.MISSING, None, False), ("is_not_empty", [], None, False),
    ("starts_with", "  Re: lunch", "re:", True), ("starts_with", "Fwd: re:", "re:", False),
    ("starts_with", "anything", "", False), ("starts_with", ["urgent", "hw"], "URGENT", True),
    ("ends_with", "report.PDF", ".pdf", True), ("ends_with", ["a", "b"], "a", False),
    ("ends_with", "x", None, False),
    ("at_least", "12", 12, True), ("at_least", 11, "12", False), ("at_most", "12", 12.0, True),
    ("at_most", "2026-11-07", "2026-11-07T00:00:00Z", True),
    ("not_one_of", "qa", "dev, ops", True), ("not_one_of", "ops", ["dev", "OPS"], False),
])
def test_each_new_word_reads_the_way_it_says(op, left, right, expected):
    assert compare(op, left, right) is expected


def test_one_of_takes_a_choice_with_a_comma():
    assert compare("one_of", "Smith, John", ["Smith, John", "Doe, Jane"]) is True
    assert compare("one_of", "Smith, John", "Smith, John\nDoe, Jane") is True
    assert compare("one_of", "Smith", "Smith, John\nDoe, Jane") is False
    # Text on one line is split on commas, as it always was.
    assert compare("one_of", "ops", "dev, ops ,qa") is True


@pytest.mark.parametrize("op,left,right,expected", [
    ("is_before", "2026-11-04T23:00:00Z", "2 days ago", True),
    ("is_before", "2026-11-05T09:00:00Z", "2 days ago", False),
    ("is_after", "2026-11-07T07:30:00Z", "1 hour ago", True),
    ("is_after", "2026-11-07T06:30:00Z", "1 hour ago", False),
    ("is_before", "2026-11-06T23:59:59Z", "today", True),
    ("is_after", "2026-11-06", "yesterday", False),
    ("is_after", "2026-11-08T00:00:01Z", "tomorrow", True),
    ("is_before", "2026-11-07T09:00:00+02:00", "now", True),
    ("is_before", "2026-11-20", "in 2 weeks", True),
    ("is_after", "now", "in 3 minutes", False),
    ("is_after", 1_800_000_000, "now", True),          # seconds since 1970
    ("is_before", "not a date", "now", False),
    ("is_before", "2026-11-01", "in 3 days ago", False),
    ("is_before", "2026-11-01", "3 days", False),
    ("is_before", "2026-11-01", "in 9999999 days", False),
])
def test_before_and_after_read_dates_and_words_counted_from_now(op, left, right, expected):
    assert compare(op, left, right) is expected


def test_today_and_two_days_ago_count_from_the_runs_now():
    ctx = wr.build_context({"start": {"data": {"sent": "2026-11-04T10:00:00Z"}, "text": "",
                                      "status": "success"}}, now=AT)
    old = {"left": "{{ steps.start.data.sent }}", "op": "is_before", "right": "2 days ago"}
    assert wl.evaluate_condition(old, ctx) is True
    later = wr.build_context({"start": {"data": {"sent": "2026-11-04T10:00:00Z"}, "text": "",
                                        "status": "success"}},
                             now=datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc))
    assert wl.evaluate_condition(old, later) is False


# ── A pattern ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("left,pattern,kind,expected", [
    ("Order AB-1234 shipped", r"[A-Z]{2}-\d{4}", None, True),
    ("Order ab-1234 shipped", r"[A-Z]{2}-\d{4}", None, True),        # capitals do not count
    ("Order ab-1234 shipped", r"[A-Z]{2}-\d{4}", "exact", False),     # unless exact
    ("Re: lunch", r"^(re|fwd):", None, True),
    ("Lunch? Re: no", r"^(re|fwd):", None, False),
    ("ends here\n", r"here$", None, True),
    ("colour", r"colou?r", None, True),
    ("x", r"(unclosed", None, False),                                # a pattern that does not read
    ("a" * 30 + "!", r"(a+)+$", None, False),
])
def test_matches_finds_a_pattern_anywhere_unless_pinned(left, pattern, kind, expected):
    assert compare("matches", left, pattern, as_type=kind) is expected


def test_matches_agrees_with_python_re_on_what_it_finds():
    """Differential: generated patterns in the language a pattern here
    speaks, run on short texts where Python's `re` is safe, find the same."""
    from src.workflow_pattern import pattern_found, pattern_problem
    rng = random.Random(1880)
    atoms = ["a", "b", "A", ".", r"\d", r"\w", r"\s", r"\W", "[ab]", "[^a]", "[a-c]", "1", " ", r"\.", "-"]

    def gen(depth=0):
        k = rng.random()
        if depth > 2 or k < 0.4:
            s = rng.choice(atoms)
        elif k < 0.6:
            s = "(" + gen(depth + 1) + "|" + gen(depth + 1) + ")"
        elif k < 0.8:
            s = "(?:" + gen(depth + 1) + gen(depth + 1) + ")"   # so a repeat never follows a repeat
        else:
            s = "(?:" + gen(depth + 1) + ")"
        q = rng.random()
        return s + ("*" if q < 0.15 else "+" if q < 0.25 else "?" if q < 0.35
                    else "{%d,%d}" % (rng.randint(0, 2), rng.randint(2, 3)) if q < 0.42 else "")

    checked = 0
    for _ in range(600):
        p = ("^" if rng.random() < 0.2 else "") + gen() + ("$" if rng.random() < 0.2 else "")
        assert pattern_problem(p) is None, p
        for _ in range(6):
            t = "".join(rng.choice("abcA1 .-\n") for _ in range(rng.randint(0, 8)))
            for fold in (False, True):
                want = re.search(p, t, re.I if fold else 0) is not None
                assert pattern_found(p, t, fold=fold) is want, (p, t, fold)
                checked += 1
    assert checked == 600 * 6 * 2


def test_a_pattern_takes_time_in_proportion_to_the_text_whatever_it_is():
    """`(a+)+$` and its kind take Python's `re` exponential time; here each
    answers over 20,000 characters, and a text of 20,000 different
    characters — every step a new one — still answers."""
    from src.workflow_pattern import PATTERN_TEXT_MAX, compile_pattern, pattern_found
    hostile = [r"(a+)+$", r"(a|a)*b", r"(a*)*b", r"(\w+\s?)+$", r"([a-z]+)*[0-9]",
               r"(\w|\W){1,20}(\d|x){1,20}(\s|q){1,20}$"]
    texts = ["a" * PATTERN_TEXT_MAX + "!", "ab " * 7000,
             "".join(chr(0x4E00 + i) for i in range(PATTERN_TEXT_MAX))]
    started = time.monotonic()
    for p in hostile:
        assert len(compile_pattern(p)) <= 400
        for t in texts:
            assert pattern_found(p, t) in (True, False)
    assert time.monotonic() - started < 20, "linear: well under a second each, even on a busy machine"


@pytest.mark.parametrize("pattern,words", [
    ("(a", "opens a group with ( that is never closed."),
    ("a)", "closes a group with ) that was never opened."),
    ("[ab", "opens a set with [ that is never closed."),
    (r"(a)\1", r"refers back to a group (\1), which a pattern here cannot."),
    ("(?=a)b", "looks ahead or behind"),
    (r"\bword", r"has \b, which a pattern here does not know"),
    ("*a", "has a *, +, ? or {…} with nothing before it to repeat"),
    ("a**", "repeats a repeat"),
    ("a{99}", "counts more than 50."),
    ("a{3,2}", "whose n is less than its m."),
    ("(a{50}){50}", "repeats too much to be checked quickly"),
    ("x" * 121, "is longer than 120 characters."),
    ("((((((((((((a))))))))))))", "has groups more than 10 deep."),
    ("[z-a]", "has the range z-a, which runs backwards."),
])
def test_a_pattern_that_does_not_read_says_why(pattern, words):
    from src.workflow_pattern import pattern_problem
    assert words in (pattern_problem(pattern) or ""), pattern_problem(pattern)


# ── At save ──────────────────────────────────────────────────────────────────

RES = wd.WorkflowResources(integrations={}, mcp_tools={}, skills=frozenset(),
                           ai_tools=frozenset(), workstation_why=None,
                           foreach_max_items=50, wait_max_hours=2)


def _check(step):
    graph = wd.parse_graph({"v": 1, "nodes": [step], "edges": [arrow("start", step["id"])]})
    return wd.validate_document(graph, owner="alice", tasks_by_id={}, crew_ids=set(),
                                owner_is_admin=True, own_task_id="t", resources=RES)


def _if(*conditions):
    return node("i", "Check", "if", conditions=list(conditions))


F = "{{ steps.start.data.subject }}"


def test_every_new_operator_and_comparison_saves():
    assert _check(_if(
        {"left": F, "op": "not_equals", "right": "closed", "as": "text"},
        {"left": F, "op": "is_not_empty"},
        {"left": F, "op": "not_one_of", "right": ["Smith, John", "Doe"]},
        {"left": F, "op": "matches", "right": r"^(re|fwd):\s"},
        {"left": F, "op": "is_before", "right": "2 days ago"},
        {"left": F, "op": "at_least", "right": "3", "as": "length"},
        {"left": F, "op": "matches", "right": "{{ steps.start.data.pattern }}"},
    )) is None


@pytest.mark.parametrize("condition,field,words", [
    ({"left": F, "op": "matches", "right": "(a"}, "conditions[0].right",
     "the pattern “(a” opens a group with ( that is never closed. A pattern knows"),
    ({"left": F, "op": "is_after", "right": "last week"}, "conditions[0].right",
     "“last week” is not a date or a time. Write one such as 2026-11-07"),
    ({"left": F, "op": "equals", "right": "7", "as": "integer"}, "",
     "a condition compares as text, exact, number, date, yes/no, length, or says nothing"),
])
def test_what_cannot_be_read_is_refused_at_save_on_its_field(condition, field, words):
    refusal = _check(_if(condition))
    assert refusal is not None and refusal.reason == wd.REFUSE_BAD_SETTING, refusal
    assert words in refusal.sentence and refusal.field == field, refusal


def test_a_switch_cases_pattern_is_refused_on_its_own_field():
    refusal = _check(node("s", "Sort", "switch", cases=[
        {"id": "c1", "label": "A", "conditions": [{"left": F, "op": "equals", "right": "1"}]},
        {"id": "c2", "label": "B", "conditions": [{"left": F, "op": "matches", "right": "a{99}"}]}]))
    assert refusal.field == "cases[1].conditions[0].right", refusal


def test_the_plan_says_how_a_condition_compares():
    assert wl.describe_condition({"left": F, "op": "not_equals", "right": "007", "as": "number"}) == \
        f"{F} is not “007”, as a number"
    assert wl.describe_condition({"left": F, "op": "is_not_empty"}) == f"{F} is not empty"


# ── In a run ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "logic.db")


@pytest.mark.asyncio
async def test_a_run_goes_the_way_the_new_words_say(factory):
    seed_workflow(factory, [
        node("mail", "Read", "set", fields=[
            {"name": "zip", "value": "02134"}, {"name": "status", "value": "Open"},
            {"name": "subject", "value": "Order AB-1234 shipped"},
            {"name": "sent", "value": "{{ now }}"}, {"name": "tags", "value": '["a","b"]', "type": "json"}]),
        node("check", "Check", "if", join="all", conditions=[
            {"left": "{{ steps.mail.data.zip }}", "op": "not_equals", "right": "2134"},
            {"left": "{{ steps.mail.data.status }}", "op": "not_one_of", "right": ["Closed", "Done, archived"]},
            {"left": "{{ steps.mail.data.subject }}", "op": "matches", "right": r"[A-Z]{2}-\d{4}"},
            {"left": "{{ steps.mail.data.sent }}", "op": "is_after", "right": "1 hour ago"},
            {"left": "{{ steps.mail.data.tags }}", "op": "at_least", "right": "2", "as": "length"}]),
        node("sort", "Sort", "switch", cases=[
            {"id": "c1", "label": "Old", "conditions": [
                {"left": "{{ steps.mail.data.sent }}", "op": "is_before", "right": "2 days ago"}]},
            {"id": "c2", "label": "Fresh", "conditions": [
                {"left": "{{ steps.mail.data.subject }}", "op": "starts_with", "right": "order"}]}]),
    ], [arrow("start", "mail"), arrow("mail", "check"), arrow("check", "sort", "then")])
    await recording_scheduler()._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["check"]["port"] == "then"
    assert by["sort"]["port"] == "case:c2"
