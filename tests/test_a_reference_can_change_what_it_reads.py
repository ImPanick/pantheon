# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1879` (`no-transforms`) — a reference can change what it reads, and a Set
field can say what its value is.

The audit found a reference could only read a field as it was: no fallback
for a field that is not there, no capitals, no trimming, no list joined into a
line, no text read as a number or as JSON, no date written another way — and
no way to read the time or which run this is. The Set step wrote every typed
value as text ("5", "true", '{"a":1}') and could not build an object. So:

  * a reference may end in up to eight changes from a CLOSED list
    (`workflow_refs.FILTERS`) — `| default:"x"`, `| upper`, `| lower`,
    `| trim`, `| length`, `| join:", "`, `| split:","`, `| json`,
    `| from_json`, `| number`, `| date:"%Y-%m-%d"`, `| first`, `| last` —
    each pure, total and at most linear in what it is handed, none calling
    anything a value supplies; an argument is a short quoted text or a plain
    number, never a reference;
  * two more roots: `{{ now }}` (the time the step starts, ISO 8601 in UTC)
    and `{{ run.id }}` / `{{ run.workflow }}`;
  * a Set field may say it is text, a number, yes/no or JSON, and its name
    may be a dotted path that builds the object it names.

The adversary (`Law 17`) is whoever writes an inbound mail or webhook body:
their bytes are what a change is handed. So the cases below hold that a
change cannot be named by data (one pass, the list is closed and parsed at
save), cannot be made to run long (`from_json` reads at most a million
characters; `date` writes from its own table, not the platform's), and that
a change that cannot use what it was handed yields nothing and SAYS which
change, rather than raising or guessing.

Pure functions, called (`Law 20`, option 1), and the real `TaskScheduler`
over a real SQLite file for the run (`tests/helpers/walker_harness.py`).
"""

import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

from src import workflow_document as wd  # noqa: E402
from src import workflow_effects as fx  # noqa: E402
from src import workflow_logic as wl  # noqa: E402
from src import workflow_refs as wr  # noqa: E402
from tests.helpers.walker_harness import (  # noqa: E402
    arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow,
)

AT = datetime(2026, 11, 7, 8, 5, 9, tzinfo=timezone.utc)

STEPS = {
    "a": {"data": {"name": "  Ada Lovelace ", "tags": ["urgent", "hw", "late"],
                   "n": "42", "price": " 3.50 ", "blank": "   ", "none": None,
                   "body": '{"id": 7, "to": ["x@example.com"]}', "bad": "{not json",
                   "when": "2026-03-01T14:30:00+01:00", "day": "2026-03-01",
                   "epoch": 0, "csv": "a, b,,c", "obj": {"upper": "called?", "k": 1},
                   "yes": True, "count": 5, "empty": []},
          "text": "Fetched it", "status": "success"},
}


def _ctx():
    """The context every case reads, built per case (so each case says for
    itself what it needs, and fails on its own)."""
    return wr.build_context(STEPS, run_id="run-9", workflow="Morning digest", now=AT)


def read(text, ctx=None):
    return wr.resolve(wr.parse_template(text).single, _ctx() if ctx is None else ctx)


def render(text, ctx=None):
    return wr.render_text(wr.parse_template(text), _ctx() if ctx is None else ctx)


# ── The grammar ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,filters", [
    ("{{ steps.a.data.name | upper }}", (("upper", None),)),
    ("{{steps.a.data.name|trim|lower}}", (("trim", None), ("lower", None))),
    ('{{ steps.a.data.x | default:"none" }}', (("default", "none"),)),
    ('{{ steps.a.data.x | default : "" }}', (("default", ""),)),
    ("{{ steps.a.data.x | default:0 }}", (("default", 0),)),
    ("{{ steps.a.data.x | default:-2.5 }}", (("default", -2.5),)),
    ('{{ steps.a.data.tags | join:", " }}', (("join", ", "),)),
    ('{{ steps.a.data.csv | split:"," | first }}', (("split", ","), ("first", None))),
    ('{{ now | date:"%A %d %B %Y, %H:%M %Z" }}', (("date", "%A %d %B %Y, %H:%M %Z"),)),
    ("{{ item.n | number }}", (("number", None),)),
    ("{{ steps.a.data.body | from_json }}", (("from_json", None),)),
    ("{{ steps.a.data | json | length }}", (("json", None), ("length", None))),
])
def test_a_reference_parses_its_changes_in_order(text, filters):
    ref = wr.parse_template(text).single
    assert ref.filters == filters
    assert ref.text == text


@pytest.mark.parametrize("text,root,path", [
    ("{{ now }}", "now", ()),
    ("{{ run }}", "run", ()),
    ("{{ run.id }}", "run", ("id",)),
    ("{{run.workflow}}", "run", ("workflow",)),
])
def test_now_and_run_are_roots(text, root, path):
    ref = wr.parse_template(text).single
    assert (ref.root, ref.node, ref.field, ref.path) == (root, None, None, path)


@pytest.mark.parametrize("text,reason", [
    ("{{ steps.a.data.x | shout }}", "bad_filter"),          # not on the list
    ("{{ steps.a.data.x | UPPER }}", "bad_filter"),          # case counts
    ("{{ steps.a.data.x | upper() }}", wr.REF_SYNTAX),            # no calls
    ("{{ steps.a.data.x | __class__ }}", "bad_filter"),
    ("{{ steps.a.data.x | }}", "bad_filter"),
    ('{{ steps.a.data.x | upper:"a" }}', "bad_filter_arg"),  # takes nothing
    ("{{ steps.a.data.x | join:5 }}", "bad_filter_arg"),     # takes text
    ('{{ steps.a.data.x | split:"" }}', "bad_filter_arg"),
    ('{{ steps.a.data.x | date:"%c" }}', "bad_filter_arg"),  # a locale's words
    ('{{ steps.a.data.x | date:"%" }}', "bad_filter_arg"),
    ('{{ steps.a.data.x | date:"" }}', "bad_filter_arg"),
    ("{{ steps.a.data.x | default:none }}", "bad_filter_arg"),  # a bare word
    ("{{ steps.a.data.x | default:007 }}", "bad_filter_arg"),
    ('{{ steps.a.data.x | default:"' + "x" * 65 + '" }}', "bad_filter_arg"),
    ('{{ steps.a.data.x | default:"a\\"b" }}', "bad_filter_arg"),
    ('{{ steps.a.data.x | default:"{{ steps.b.text }}" }}', "bad_filter_arg"),
    ('{{ steps.a.data.x | default:"line\nbreak" }}', "bad_filter_arg"),
    ('{{ steps.a.data.x | default:"open }}', "bad_filter_arg"),
    ("{{ steps.a.data.x" + " | trim" * 9 + " }}", "too_many_filters"),
    ("{{ now.year }}", wr.REF_SYNTAX),
    ("{{ now[0] }}", wr.REF_SYNTAX),
    ("{{ run.secret }}", wr.REF_BAD_KEY),
    ("{{ run.id.x }}", wr.REF_BAD_KEY),
    ("{{ run[0] }}", wr.REF_BAD_KEY),
    ("{{ nowadays }}", wr.REF_SYNTAX),
    ("{{ runner.id }}", wr.REF_SYNTAX),
])
def test_a_change_off_the_list_or_badly_written_is_refused(text, reason):
    with pytest.raises(wr.RefError) as err:
        wr.parse_template(text)
    assert err.value.reason == reason


def test_eight_changes_are_allowed_and_the_ninth_is_not():
    assert len(wr.parse_template("{{ now" + " | trim" * 8 + " }}").single.filters) == 8
    with pytest.raises(wr.RefError):
        wr.parse_template("{{ now" + " | trim" * 9 + " }}")


def test_a_refused_change_is_told_with_the_whole_list():
    with pytest.raises(wr.RefError) as err:
        wr.parse_template("Hi {{ steps.a.data.name | capitalize }}")
    sentence = err.value.sentence
    assert "ends in a change a reference does not have" in sentence
    for name in wr.FILTERS:
        assert f"| {name}" in sentence, name
    assert '| date:"%Y-%m-%d"' in sentence and '| join:", "' in sentence


def test_the_list_is_closed_and_every_change_on_it_is_known():
    assert wr.FILTERS == ("default", "upper", "lower", "trim", "length", "join", "split",
                          "json", "from_json", "number", "date", "first", "last")
    assert set(wr.FILTER_ARG_DEFAULTS) <= set(wr.FILTERS)
    for name in wr.FILTERS:          # every change answers for every value, never raises
        for value in (wr.MISSING, None, "", "x", 0, 1.5, True, [], [1], {}, {"a": 1}):
            wr._apply(name, wr.FILTER_ARG_DEFAULTS.get(name), value)


def test_an_escaped_reference_with_a_change_is_text():
    t = wr.parse_template("\\{{ steps.a.data.name | upper }}")
    assert t.refs == ()
    assert render("\\{{ steps.a.data.name | upper }}")[0] == "{{ steps.a.data.name | upper }}"


# ── What each change does ────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("{{ steps.a.data.name | trim }}", "Ada Lovelace"),
    ("{{ steps.a.data.name | trim | upper }}", "ADA LOVELACE"),
    ("{{ steps.a.data.name | trim | lower }}", "ada lovelace"),
    ("{{ steps.a.data.tags | length }}", 3),
    ("{{ steps.a.data.name | length }}", 15),
    ("{{ steps.a.data.obj | length }}", 2),
    ("{{ steps.a.data.none | length }}", 0),
    ("{{ steps.a.data.tags | join }}", "urgent, hw, late"),
    ('{{ steps.a.data.tags | join:" / " }}', "urgent / hw / late"),
    ("{{ steps.a.data.csv | split }}", ["a", "b", "c"]),
    ('{{ steps.a.data.csv | split:"," | last }}', "c"),
    ("{{ steps.a.data.tags | first }}", "urgent"),
    ("{{ steps.a.data.tags | last | upper }}", "LATE"),
    ("{{ steps.a.data.n | number }}", 42),
    ("{{ steps.a.data.price | number }}", 3.5),
    ("{{ steps.a.data.count | number }}", 5),
    ("{{ steps.a.data.body | from_json }}", {"id": 7, "to": ["x@example.com"]}),
    ("{{ steps.a.data.obj | json }}", '{"upper": "called?", "k": 1}'),
    ("{{ steps.a.data.obj | upper }}", '{"UPPER": "CALLED?", "K": 1}'),
    ("{{ steps.a.data.yes | upper }}", "TRUE"),
    ('{{ steps.a.data.when | date:"%Y-%m-%d %H:%M %z" }}', "2026-03-01 14:30 +0100"),
    ('{{ steps.a.data.day | date:"%a %d %b %Y" }}', "Sun 01 Mar 2026"),
    ("{{ steps.a.data.epoch | date }}", "1970-01-01"),
    ('{{ now | date:"%A %I:%M %p, day %j" }}', "Saturday 08:05 AM, day 311"),
    ('{{ steps.a.data.x | default:"none" }}', "none"),
    ('{{ steps.a.data.none | default:"none" }}', "none"),
    ('{{ steps.a.data.blank | default:"none" }}', "none"),
    ("{{ steps.a.data.x | default }}", ""),
    ("{{ steps.a.data.x | default:0 }}", 0),
    ('{{ steps.a.data.name | default:"none" | trim }}', "Ada Lovelace"),
    ("{{ steps.a.data.empty | first }}", wr.MISSING),
])
def test_each_change_does_what_it_says(text, expected):
    assert read(text) == expected


def test_a_change_never_calls_what_a_value_supplies():
    """An object with a key called `upper` is JSON, upper-cased as text; its
    "method" is never looked up, let alone called — nothing a value names is
    ever run (the adversary's bytes stay bytes)."""
    assert read("{{ steps.a.data.obj | upper }}") == '{"UPPER": "CALLED?", "K": 1}'
    hostile = wr.build_context({"h": {"data": {"x": "{{ steps.a.data.name | upper }}"},
                                      "text": "", "status": "success"}})
    assert read("{{ steps.h.data.x | trim }}", hostile) == "{{ steps.a.data.name | upper }}"


def test_nothing_passes_through_every_change_but_default():
    for name in wr.FILTERS:
        if name != wr.FILTER_DEFAULT:
            assert wr._apply(name, wr.FILTER_ARG_DEFAULTS.get(name), wr.MISSING) is wr.MISSING


def test_from_json_reads_at_most_its_bound_and_never_nan():
    big = '["' + "x" * wr.FROM_JSON_MAX_CHARS + '"]'
    ctx = wr.build_context({"a": {"data": {"big": big, "nan": "NaN", "inf": "[Infinity]",
                                           "deep": "[" * 100000 + "]" * 100000},
                                  "text": "", "status": "success"}})
    for field in ("big", "nan", "inf", "deep"):
        assert read(f"{{{{ steps.a.data.{field} | from_json }}}}", ctx) is wr.MISSING, field


def test_a_number_change_reads_numbers_and_nothing_else():
    assert wr.to_number("1" * 400) == int("1" * 400), "a long id stays exact"
    for word in ("NaN", "inf", "1e999", "0x10", "", "twelve", True):
        assert wr.to_number(word) is wr.MISSING, word


def test_the_date_change_writes_the_same_words_on_every_platform():
    moment = datetime(2026, 1, 4, 23, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert wr._format_moment(moment, "%A %B %d %y %H %I %p %z %Z %%") == \
        "Sunday January 04 26 23 11 PM -0500 -05:00 %"
    assert wr._format_moment(AT, "%Z") == "UTC"


# ── Nothing, and saying why ──────────────────────────────────────────────────

def test_a_change_that_cannot_use_its_value_says_which_and_why():
    text, missing = render("Total: {{ steps.a.text | number }}.")
    assert text == "Total: ."
    assert missing == ("{{ steps.a.text | number }} (what “number” was handed is not a number)",)
    _, missing = render("{{ steps.a.data.bad | from_json }}")
    assert missing == ("{{ steps.a.data.bad | from_json }} (what “from_json” was handed is not JSON)",)
    _, missing = render('{{ steps.a.data.name | date:"%Y" }}')
    assert missing[0].endswith("(what “date” was handed is not a date or a time)")
    _, missing = render("{{ steps.a.data.empty | first }}")
    assert missing[0].endswith("(what “first” was handed has nothing in it)")


def test_a_field_that_is_not_there_is_named_as_written():
    _, missing = render("{{ steps.a.data.gone | upper }}")
    assert missing == ("{{ steps.a.data.gone | upper }}",)
    value, missing = wr.render_value(wr.parse_template("{{ steps.a.data.gone | number }}"), _ctx())
    assert value is None and missing == ("{{ steps.a.data.gone | number }}",)


def test_a_default_means_nothing_is_missing():
    assert render('{{ steps.a.data.gone | default:"n/a" }}') == ("n/a", ())


# ── now and run ──────────────────────────────────────────────────────────────

def test_now_and_run_read_from_the_context():
    assert read("{{ now }}") == "2026-11-07T08:05:09Z"
    assert read("{{ run.id }}") == "run-9"
    assert read("{{ run.workflow }}") == "Morning digest"
    assert read("{{ run }}") == {"id": "run-9", "workflow": "Morning digest"}
    assert render("{{ run.workflow | upper }} at {{ now | date:\"%H:%M\" }}")[0] == \
        "MORNING DIGEST at 08:05"


def test_a_context_built_without_a_run_reads_run_id_as_nothing():
    ctx = wr.build_context({})
    assert read("{{ run.id }}", ctx) is None
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", read("{{ now }}", ctx))
    assert read('{{ run.id | default:"a test" }}', ctx) == "a test"


def test_now_is_read_when_the_context_is_built_not_when_a_reference_resolves():
    ctx = wr.build_context({}, now=AT)
    t = wr.parse_template("{{ now }}")
    assert [wr.render_text(t, ctx)[0] for _ in range(3)] == ["2026-11-07T08:05:09Z"] * 3


# ── The Set step: a type, and a name that is a path ──────────────────────────

def _set(*fields):
    return {"id": "s", "kind": "set", "config": {"fields": list(fields)}}


def test_a_set_field_is_made_the_type_it_says():
    made = wl.make_set(_set(
        {"name": "n", "value": "{{ steps.a.data.n }}", "type": "number"},
        {"name": "price", "value": "{{ steps.a.data.price }}", "type": "number"},
        {"name": "ok", "value": "yes", "type": "yes/no"},
        {"name": "off", "value": "false", "type": "yes/no"},
        {"name": "body", "value": "{{ steps.a.data.body }}", "type": "json"},
        {"name": "list", "value": '["a", 1]', "type": "json"},
        {"name": "count", "value": "{{ steps.a.data.count }}", "type": "text"},
        {"name": "plain", "value": "5"},
    ), _ctx())
    assert made.wrong == () and made.missing == ()
    assert made.data == {"n": 42, "price": 3.5, "ok": True, "off": False,
                         "body": {"id": 7, "to": ["x@example.com"]}, "list": ["a", 1],
                         "count": "5", "plain": "5"}


def test_a_dotted_name_builds_the_object_it_names():
    made = wl.make_set(_set(
        {"name": "customer.name", "value": "{{ steps.a.data.name | trim }}"},
        {"name": "customer.tags", "value": "{{ steps.a.data.tags }}"},
        {"name": "customer.address.city", "value": "Paris"},
        {"name": "total", "value": "3", "type": "number"},
    ), _ctx())
    assert made.data == {"customer": {"name": "Ada Lovelace", "tags": ["urgent", "hw", "late"],
                                      "address": {"city": "Paris"}}, "total": 3}


@pytest.mark.parametrize("kind,value,words", [
    ("number", "{{ steps.a.data.name }}", "“f” should be a number, and it was handed text: “Ada Lovelace”."),
    ("yes/no", "maybe", "“f” should be yes or no, and it was handed text: “maybe”."),
    ("json", "{{ steps.a.data.bad }}", "“f” should be JSON (a list or an object), and it was handed text: “{not json”."),
    ("number", "{{ steps.a.data.yes }}", "“f” should be a number, and it was handed yes or no: “true”."),
])
def test_a_set_value_of_the_wrong_type_is_named_in_plain_words(kind, value, words):
    made = wl.make_set(_set({"name": "f", "value": value, "type": kind}), _ctx())
    assert made.wrong == (words,)
    assert made.data == {"f": None}


def test_set_names_are_checked_as_paths():
    assert wl.set_name_parts("customer.name") == ("customer", "name")
    for bad in ("", ".a", "a.", "a..b", "1a", "a.1b", "a-b", "a b", ".".join("a" * 9), "a" * 65):
        assert wl.set_name_parts(bad) is None, bad
    assert wl.set_names_clash(["a", "a.b"]) == ("a.b", "a")
    assert wl.set_names_clash(["a.b.c", "a.b", "z"]) == ("a.b.c", "a.b")
    assert wl.set_names_clash(["a.b", "a.c", "ab"]) is None


def test_build_set_keeps_its_old_answer():
    assert wl.build_set(_set({"name": "x", "value": "{{ steps.a.data.gone }}"}), _ctx()) == \
        ({"x": None}, ("{{ steps.a.data.gone }}",))


# ── At save ──────────────────────────────────────────────────────────────────

RES = wd.WorkflowResources(integrations={}, mcp_tools={}, skills=frozenset(),
                           ai_tools=frozenset(), workstation_why=None,
                           foreach_max_items=50, wait_max_hours=2)


def _check(*nodes, edges=None):
    graph = wd.parse_graph({"v": 1, "nodes": list(nodes), "edges": list(
        edges if edges is not None else [arrow("start", nodes[0]["id"])] + [
            arrow(a["id"], b["id"]) for a, b in zip(nodes, nodes[1:])])})
    return wd.validate_document(graph, owner="alice", tasks_by_id={}, crew_ids=set(),
                                owner_is_admin=True, own_task_id="t", resources=RES)


def test_a_document_with_changes_now_run_types_and_paths_is_accepted():
    assert _check(node("s", "Shape", "set", fields=[
        {"name": "customer.name", "value": '{{ steps.start.data.from | default:"someone" | trim }}'},
        {"name": "customer.id", "value": "{{ run.id }}", "type": "text"},
        {"name": "when", "value": '{{ now | date:"%Y-%m-%d" }}'},
        {"name": "n", "value": "3", "type": "number"},
        {"name": "flags", "value": "[]", "type": "json"},
    ])) is None


def test_a_change_off_the_list_is_refused_at_save_in_plain_words():
    refusal = _check(node("s", "Shape", "set", fields=[
        {"name": "x", "value": "{{ steps.start.data.from | capitalize }}"}]))
    assert refusal is not None and refusal.reason == wd.REFUSE_BAD_REFERENCE
    assert "ends in a change a reference does not have" in refusal.sentence
    assert '| default:"…"' in refusal.sentence


@pytest.mark.parametrize("fields,words", [
    ([{"name": "x", "value": "1", "type": "integer"}],
     "the field 'x' is 'integer'; a field is text, number, yes/no, json, or says nothing"),
    ([{"name": "a", "value": "1"}, {"name": "a.b", "value": "2"}],
     "“a.b” is inside “a”, which is set as well. Set one or the other"),
    ([{"name": "a..b", "value": "1"}],
     "a dot between names puts one inside the other (customer.name)"),
])
def test_a_set_field_that_cannot_be_made_is_refused_at_save(fields, words):
    refusal = _check(node("s", "Shape", "set", fields=fields))
    assert refusal is not None and words in refusal.sentence, refusal


def test_the_plan_says_what_a_typed_field_is_made():
    lines = wd.plan_lines({"id": "s", "kind": "set", "config": {"fields": [
        {"name": "n", "value": "3", "type": "number"}, {"name": "t", "value": "x"}]}})
    assert "n ← 3, as a number" in lines and "t ← x" in lines


def test_the_picker_offers_a_dotted_set_name_as_its_path():
    graph = {"v": 1, "nodes": [
        {"id": "s", "kind": "set", "label": "Shape", "config": {"fields": [
            {"name": "customer.name", "value": "x"}, {"name": "n", "value": "3", "type": "number"},
            {"name": "j", "value": "[]", "type": "json"}]}},
        {"id": "next", "kind": "action", "label": "Next", "config": {}}],
        "edges": [arrow("start", "s"), arrow("s", "next")]}
    trigger = SimpleNamespace(id=None, trigger_type="schedule", trigger_event=None)
    sources = fx.available_fields(None, SimpleNamespace(id="wf-1"), trigger, graph, "next")["sources"]
    [declared] = [s for s in sources if s["node_id"] == "s" and s["origin"] == "declared"]
    assert [(f["ref"], f["path"], f["type"]) for f in declared["fields"]] == [
        ("{{ steps.s.data.customer.name }}", ["customer", "name"], None),
        ("{{ steps.s.data.n }}", ["n"], "number"),
        ("{{ steps.s.data.j }}", ["j"], None)]


def test_the_drafter_is_told_only_what_the_grammar_reads():
    """`workflow_assist`'s prompt names `{{ now }}` and two changes: each
    reference it shows parses, and each change it names is on the list."""
    from src.workflow_assist import _SYSTEM
    [line] = [ln for ln in _SYSTEM.splitlines() if "{{ now }}" in ln]
    wr.parse_template("{{ now }}")
    named = re.findall(r"\| ([a-z_]+)", line)
    assert named and set(named) <= set(wr.FILTERS), named
    wr.parse_template('{{ now | default:"x" | lower }}')


# ── In a run ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "changes.db")


@pytest.mark.asyncio
async def test_a_run_reads_now_run_changes_and_typed_paths(factory):
    seed_workflow(factory, [
        node("read", "Read", "set", fields=[
            {"name": "name", "value": "  ada  "}, {"name": "tags", "value": '["a","b"]', "type": "json"},
            {"name": "n", "value": "7", "type": "number"}]),
        node("shape", "Shape", "set", fields=[
            {"name": "who.name", "value": "{{ steps.read.data.name | trim | upper }}"},
            {"name": "who.tags", "value": '{{ steps.read.data.tags | join:"+" }}'},
            {"name": "who.missing", "value": '{{ steps.read.data.gone | default:"none" }}'},
            {"name": "run.id", "value": "{{ run.id }}"},
            {"name": "run.workflow", "value": "{{ run.workflow }}"},
            {"name": "run.at", "value": "{{ now }}"},
            {"name": "double", "value": "{{ steps.read.data.n | number }}", "type": "number"},
            {"name": "ok", "value": "on", "type": "yes/no"}]),
    ], [arrow("start", "read"), arrow("read", "shape")])
    await recording_scheduler()._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    data = by["shape"]["output"]["data"]
    assert data["who"] == {"name": "ADA", "tags": "a+b", "missing": "none"}
    assert data["run"]["id"] == run["id"]
    assert data["run"]["workflow"] == "Morning digest"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", data["run"]["at"])
    assert data["double"] == 7 and data["ok"] is True
    assert by["shape"]["output"]["text"] == (
        "Set “who.name”, “who.tags”, “who.missing”, “run.id”, “run.workflow”, “run.at”, "
        "“double”, “ok”.")


@pytest.mark.asyncio
async def test_a_set_value_of_the_wrong_type_stops_the_run_naming_the_field(factory):
    seed_workflow(factory, [
        node("read", "Read", "set", fields=[{"name": "amount", "value": "about ten"}]),
        node("shape", "Shape", "set", fields=[
            {"name": "amount", "value": "{{ steps.read.data.amount }}", "type": "number"}]),
        node("after", "After", "set", fields=[{"name": "x", "value": "1"}]),
    ], [arrow("start", "read"), arrow("read", "shape"), arrow("shape", "after")])
    await recording_scheduler()._execute_task("wf")
    [run] = runs_of(factory, "wf")
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["shape"]["status"] == "error"
    assert "“amount” should be a number, and it was handed text: “about ten”." in (
        str(by["shape"]["output"]) + str(by["shape"].get("error")))
    assert "after" not in by
