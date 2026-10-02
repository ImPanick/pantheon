# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-09` — a reference reads a field, and nothing else (`src/workflow_refs.py`).

Pure functions, called (`Law 20`, option 1). The adversary (`Law 17`,
`D-2026-10-01-05` §4) is whoever writes an inbound mail or webhook body: their
bytes become step outputs that references read. What these cases hold:

  * the grammar reads exactly `steps.<id>.data|text<segs>` and `item<segs>` —
    no calls, no filters, no arithmetic, no negative index, no slice — and every
    obfuscation of it (fullwidth braces, nesting, case, Unicode look-alikes,
    stray whitespace inside the path) is not a reference;
  * resolution walks JSON only: an exact dict key, an in-range int index (a
    bool is not one), nothing on a Python object, `MISSING` for anything else;
  * one pass: a value that itself contains `{{ steps.x… }}` arrives as those
    characters and nothing it names is read;
  * the bounds (`SLICE-CD-DESIGN` § 1.1) refuse rather than cut.
"""

import json
import random
import string

import pytest

from src import workflow_refs as wr


CTX = wr.build_context({
    "start": {"data": {"body": "hello", "headers": {"x-id": "7"}}, "text": "hook", "status": "success"},
    "fetch-issue": {"data": {"title": "Printer on fire", "labels": ["urgent", "hw"],
                             "n": 3, "ok": True, "none": None,
                             "nested": {"deep": [{"k": "v"}]}, "odd key": 1},
                    "text": "Fetched it", "status": "success"},
    "secret": {"data": {"x": "TOP-SECRET"}, "text": "s", "status": "success"},
    "hostile": {"data": {"body": "{{ steps.secret.data.x }}",
                         "obj": {"to": "x@evil", "path": "/admin"}},
                "text": "{{ steps.secret.text }}", "status": "success"},
}, item={"subject": "Hi", "list": [10, 20]})


def render(text, ctx=CTX):
    return wr.render_text(wr.parse_template(text), ctx)


# ── The grammar ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,root,node,field,path", [
    ("{{ steps.fetch-issue.data.title }}", "steps", "fetch-issue", "data", ("title",)),
    ("{{steps.fetch-issue.text}}", "steps", "fetch-issue", "text", ()),
    ("{{\tsteps.start.data.headers[\"x-id\"]\n}}", "steps", "start", "data", ("headers", "x-id")),
    ("{{ steps.n1.data.items[0].name }}", "steps", "n1", "data", ("items", 0, "name")),
    ("{{ item }}", "item", None, None, ()),
    ("{{ item.list[1] }}", "item", None, None, ("list", 1)),
    ("{{ steps.a.data[999999] }}", "steps", "a", "data", (999999,)),
])
def test_a_reference_parses_into_where_it_reads(text, root, node, field, path):
    ref = wr.parse_template(text).single
    assert ref == wr.Ref(root, node, field, path, text)


@pytest.mark.parametrize("text", [
    "{{ STEPS.a.data.x }}",                 # case: not the word
    "{{ Steps.a.data.x }}",
    "{{ steps.a.DATA.x }}",
    "{{ steps.a.database }}",               # `data` must end at a boundary
    "{{ steps.a.data.x() }}",               # no calls
    "{{ steps.a.data.x | upper }}",         # no filters
    "{{ steps.a.data.n + 1 }}",             # no arithmetic
    "{{ steps.a.data.x[-1] }}",             # no negative index
    "{{ steps.a.data.x[0:2] }}",            # no slice
    "{{ steps.a.data.x[01] }}",             # no leading zero
    "{{ steps.a.data.x[1234567] }}",        # at most six digits
    "{{ steps.a.data.1x }}",                # a key starts with a letter or _
    "{{ steps.a.data.tіtle }}",             # Cyrillic і
    "{{ steps .a.data.x }}",                # whitespace inside the path
    "{{ steps.a .data.x }}",
    "{{ steps.a.data .x }}",
    "{{ {{ steps.a.data.x }} }}",           # nested
    "{{ steps.a.data.x }",                  # unclosed
    "{{ steps.a.data.x",
    "{{ items.x }}",                        # `item` must end at a boundary
    "{{ step.a.data.x }}",
    "{{ steps.a.status }}",                 # only data and text
    "{{ steps..data.x }}",
    "{{ steps.a.data[\"q\\\"k\"] }}",       # no backslash in a quoted key
    "{{ steps.a.data[\"\"] }}",             # no empty quoted key
    "{{ steps." + "a" * 65 + ".data }}",    # the id rule: 64 at most
    "{{ steps.a.data." + "k" * 65 + " }}",  # a key: 64 at most
    "{{ steps.a.data.x }}" + " {{ x }}",
    "{{}}",
])
def test_anything_else_with_braces_is_refused_not_guessed(text):
    with pytest.raises(wr.RefError) as err:
        wr.parse_template(text)
    assert err.value.reason in wr.REF_ERROR_REASONS
    assert err.value.sentence.endswith(".")


@pytest.mark.parametrize("text", [
    "｛｛ steps.fetch-issue.data.title ｝｝",   # fullwidth braces are text
    "{ { steps.fetch-issue.data.title } }",
    "﹛﹛ steps.fetch-issue.data.title ﹜﹜",
    "plain prose with no braces at all",
    "a } and a { and }} alone",
])
def test_look_alike_braces_are_text_and_never_resolve(text):
    t = wr.parse_template(text)
    assert t.refs == ()
    assert render(text) == (text, ())


def test_an_escaped_brace_is_the_literal_text_and_reads_nothing():
    text = "Write \\{{ steps.secret.data.x }} to show the syntax"
    out, missing = render(text)
    assert out == "Write {{ steps.secret.data.x }} to show the syntax"
    assert "TOP-SECRET" not in out and missing == ()


def test_whitespace_around_the_path_is_allowed_inside_it_is_not():
    for text in ("{{steps.secret.data.x}}", "{{   steps.secret.data.x\t}}",
                 "{{\n steps.secret.data.x \r\n}}"):
        assert render(text) == ("TOP-SECRET", ())
    with pytest.raises(wr.RefError):
        wr.parse_template("{{ steps.secret. data.x }}")


# ── What a reference can reach ───────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("{{ steps.fetch-issue.data.title }}", "Printer on fire"),
    ("{{ steps.fetch-issue.data.labels[1] }}", "hw"),
    ("{{ steps.fetch-issue.data.nested.deep[0].k }}", "v"),
    ("{{ steps.fetch-issue.data[\"odd key\"] }}", 1),
    ("{{ steps.fetch-issue.text }}", "Fetched it"),
    ("{{ steps.start.data.headers[\"x-id\"] }}", "7"),
    ("{{ item.subject }}", "Hi"),
    ("{{ item.list[0] }}", 10),
    ("{{ steps.fetch-issue.data.none }}", None),
])
def test_a_reference_reads_exactly_the_field_it_names(text, expected):
    assert wr.resolve(wr.parse_template(text).single, CTX) == expected


@pytest.mark.parametrize("text", [
    "{{ steps.gone.data.x }}",                       # no such step
    "{{ steps.fetch-issue.data.nope }}",             # no such key
    "{{ steps.fetch-issue.data.labels[2] }}",        # out of range
    "{{ steps.fetch-issue.data.title[0] }}",         # text is not indexable
    "{{ steps.fetch-issue.data.title.upper }}",      # nothing on an object
    "{{ steps.fetch-issue.data.labels.count }}",
    "{{ steps.fetch-issue.data.n.real }}",
    "{{ steps.fetch-issue.text.strip }}",
    "{{ steps.fetch-issue.data.__class__ }}",
    "{{ steps.fetch-issue.data.ok[0] }}",
])
def test_anything_else_is_missing_never_an_attribute(text):
    assert wr.resolve(wr.parse_template(text).single, CTX) is wr.MISSING


def test_a_bool_is_not_an_index_and_only_plain_json_is_walked():
    ctx = {"steps": {"a": {"data": [["zero"], ["one"]]}}}
    assert wr.resolve(wr.Ref("steps", "a", "data", (True,), "t"), ctx) is wr.MISSING
    assert wr.resolve(wr.Ref("steps", "a", "data", (1, 0), "t"), ctx) == "one"

    class Sneaky(dict):
        def __missing__(self, key):  # pragma: no cover - must never be reached
            raise AssertionError("a lookup ran code")

        def __getitem__(self, key):  # pragma: no cover - must never be reached
            raise AssertionError("a lookup ran code")

    sneaky = {"steps": {"a": {"data": Sneaky(x=1)}}}
    assert wr.resolve(wr.Ref("steps", "a", "data", ("x",), "t"), sneaky) is wr.MISSING
    assert wr.resolve(wr.Ref("steps", "a", "data", (), "t"), {"steps": {"a": {"data": object()}}}) \
        is wr.MISSING
    assert wr.resolve(wr.Ref("steps", "a", "data", (), "t"), "not a context") is wr.MISSING


def test_the_context_is_json_whatever_it_was_handed():
    ctx = wr.build_context({"a": {"data": {"t": (1, 2), "s": {3}, "o": object()}}})
    data = ctx["steps"]["a"]["data"]
    assert data["t"] == [1, 2] and isinstance(data["s"], str) and isinstance(data["o"], str)
    assert json.loads(json.dumps(ctx)) == ctx


# ── One pass ─────────────────────────────────────────────────────────────────

def test_a_value_holding_a_reference_arrives_as_text_and_reads_nothing():
    out, missing = render("Body: {{ steps.hostile.data.body }} / {{ steps.hostile.text }}")
    assert out == "Body: {{ steps.secret.data.x }} / {{ steps.secret.text }}"
    assert "TOP-SECRET" not in out and missing == ()
    value, _ = wr.render_value(wr.parse_template("{{ steps.hostile.data.body }}"), CTX)
    assert value == "{{ steps.secret.data.x }}"


def test_an_object_spliced_into_text_is_json_text_not_keys():
    out, _ = render("x={{ steps.hostile.data.obj }}")
    assert out == 'x={"to": "x@evil", "path": "/admin"}'
    value, _ = wr.render_value(wr.parse_template("{{ steps.hostile.data.obj }}"), CTX)
    assert value == {"to": "x@evil", "path": "/admin"}, "exactly one reference is the raw value"


def test_render_says_what_reached_nothing_and_splices_nothing_for_it():
    out, missing = render("[{{ steps.gone.text }}] [{{ steps.fetch-issue.data.n }}] "
                          "[{{ steps.fetch-issue.data.ok }}] [{{ steps.fetch-issue.data.none }}]")
    assert out == "[] [3] [true] []"
    assert missing == ("{{ steps.gone.text }}",)
    value, missing = wr.render_value(wr.parse_template("  {{ steps.gone.text }} "), CTX)
    assert value is None and missing == ("{{ steps.gone.text }}",)


def test_a_prompt_gets_named_slots_and_the_values_travel_apart():
    t = wr.parse_template("Summarise the issue titled {{ steps.fetch-issue.data.title }} "
                          "(again: {{steps.fetch-issue.data.title}}), labelled "
                          "{{ steps.fetch-issue.data.labels[0] }}; the body is "
                          "{{ steps.hostile.data.body }} and {{ steps.gone.data.title }}.")
    text, slots = wr.render_named_slots(t, CTX)
    assert text == ("Summarise the issue titled [title] (again: [title]), labelled [labels_0]; "
                    "the body is [body] and [title_2].")
    assert [(s[0], s[2]) for s in slots] == [
        ("title", "Printer on fire"), ("labels_0", "urgent"),
        ("body", "{{ steps.secret.data.x }}"), ("title_2", wr.MISSING)]
    assert "Printer on fire" not in text and "TOP-SECRET" not in text


# ── Bounds ───────────────────────────────────────────────────────────────────

def test_the_bounds_refuse_rather_than_cut():
    ok = "{{ steps.a.data" + ".k" * wr.REF_MAX_SEGMENTS + " }}"
    assert len(wr.parse_template(ok).single.path) == wr.REF_MAX_SEGMENTS
    with pytest.raises(wr.RefError) as err:
        wr.parse_template("{{ steps.a.data" + ".k" * (wr.REF_MAX_SEGMENTS + 1) + " }}")
    assert err.value.reason == wr.REF_TOO_DEEP
    many = " ".join(["{{ item }}"] * wr.TEMPLATE_MAX_REFS)
    assert len(wr.parse_template(many).refs) == wr.TEMPLATE_MAX_REFS
    with pytest.raises(wr.RefError) as err:
        wr.parse_template(many + " {{ item }}")
    assert err.value.reason == wr.REF_TOO_MANY
    with pytest.raises(wr.RefError) as err:
        wr.parse_template("{{ item }}" + "x" * wr.TEMPLATE_MAX_CHARS)
    assert err.value.reason == wr.REF_TOO_LONG
    long_plain = "x" * (wr.TEMPLATE_MAX_CHARS * 3)
    assert wr.parse_template(long_plain).parts == (long_plain,), \
        "text with no reference is not bounded: a long Slice B prompt still saves"
    with pytest.raises(wr.RefError) as err:
        wr.parse_template('{{ steps.a.data["' + "q" * (wr.QKEY_MAX + 1) + '"] }}')
    assert err.value.reason == wr.REF_BAD_KEY


def test_fuzzed_text_either_parses_into_steps_and_items_or_is_refused():
    """Whatever the text, a parsed reference names only `steps` or `item`, and
    resolving it never raises."""
    rng = random.Random(2209)
    alphabet = string.ascii_letters + string.digits + "{}[]._-\"' \t\\" + "｛｝і"
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        if rng.random() < 0.5:
            text = "{{ steps." + text
        try:
            t = wr.parse_template(text)
        except wr.RefError:
            continue
        for ref in t.refs:
            assert ref.root in (wr.REF_ROOT_STEPS, wr.REF_ROOT_ITEM)
            wr.resolve(ref, CTX)
        wr.render_text(t, CTX)


# ── Writing one, finding them, and what a value holds ────────────────────────

def test_format_ref_writes_what_parses_and_refuses_what_cannot_be_named():
    assert wr.format_ref("fetch-issue", "data", ["items", 0, "title"]) == \
        "{{ steps.fetch-issue.data.items[0].title }}"
    assert wr.format_ref("start", "data", ["headers", "x-id"]) == \
        '{{ steps.start.data.headers["x-id"] }}'
    assert wr.format_item_ref(["subject"]) == "{{ item.subject }}"
    for args in (("bad id!", "data", []), ("a", "status", []), ("a", "data", ['q"k']),
                 ("a", "data", [-1]), ("a", "data", [True]), ("a", "data", [1.5])):
        with pytest.raises(ValueError):
            wr.format_ref(*args)
    for node, path in (("n1", ["a b", 3]), ("x_y", ["k" * 64])):
        text = wr.format_ref(node, "data", path)
        assert wr.parse_template(text).single.path == tuple(path)


def test_refs_in_walks_settings_and_single_ref_names_the_one():
    config = {"prompt": "a {{ item.x }}", "args": {"text": "{{ steps.a.text }}", "n": 3},
              "fields": [{"name": "k", "value": "\\{{ not one }}"}]}
    assert [r.text for r in wr.refs_in(config)] == ["{{ item.x }}", "{{ steps.a.text }}"]
    assert wr.single_ref("  {{ steps.a.data.list }}\n").path == ("list",)
    for text in ("x {{ steps.a.data.list }}", "{{ item }}{{ item }}", "{{ STEPS.a.data }}", 5):
        assert wr.single_ref(text) is None
    with pytest.raises(wr.RefError):
        wr.refs_in({"bad": "{{ nope }}"})


def test_references_anywhere_finds_escaped_and_nested_ones_for_never_slots():
    assert wr.references_in_text("docker ps --format '{{.Names}}'") == ()
    assert wr.references_in_text("｛｛ steps.a.text ｝｝") == ()
    for text in ("{{ steps.a.text }}", "\\{{ steps.a.text }}", "{{ {{ steps.a.text }} }}",
                 "x{{{steps.a.text}}}", "{{\titem\t}}"):
        assert wr.references_in_text(text), text


def test_flatten_fields_offers_what_a_reference_can_name():
    fields = wr.flatten_fields({"title": "T", "n": 2, "ok": False, "none": None,
                                "items": [{"name": "first"}, {"name": "second"}],
                                'bad"key': 1, "deep": {"a": {"b": {"c": {"d": 1}}}}})
    by_path = {tuple(f["path"]): f for f in fields}
    assert by_path[()]["type"] == "object"
    assert by_path[("title",)] == {"path": ["title"], "type": "text", "example": "T"}
    assert by_path[("n",)]["type"] == "number" and by_path[("ok",)]["type"] == "yes/no"
    assert by_path[("none",)]["type"] == "empty"
    assert by_path[("items",)] == {"path": ["items"], "type": "list", "example": "2 items"}
    assert by_path[("items", 0, "name")]["example"] == "first"
    assert ("items", 1) not in by_path, "a list is described by its first item"
    assert not any('bad"key' in f["path"] for f in fields), "a key no reference can name"
    assert ("deep", "a", "b", "c") in by_path and ("deep", "a", "b", "c", "d") not in by_path
    for f in fields[1:]:
        wr.format_ref("n1", "data", f["path"])  # every offered path is nameable
    assert len(wr.flatten_fields({f"k{i}": i for i in range(500)})) == 200
    assert wr.flatten_fields("plain text") == [{"path": [], "type": "text", "example": "plain text"}]
    long = wr.flatten_fields("x" * 500)[0]["example"]
    assert len(long) == wr.EXAMPLE_MAX_CHARS and long.endswith("…")
