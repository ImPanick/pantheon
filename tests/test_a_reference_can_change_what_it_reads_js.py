# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1879` (`no-transforms`) — the browser reads a reference with changes as the server does, offers the run's own fields, and a Set field says what its value is.

The server's grammar grew (`src/workflow_refs.py`): a reference may end in
changes from a closed list (`| default:"x"`, `| upper`, `| join:", "`,
`| date:"%Y-%m-%d"` …) and may read `{{ now }}`, `{{ run.id }}` and
`{{ run.workflow }}`. The field picker's "Uses:" line under a field read
references with a pattern of its own that knew none of this: a field holding
`{{ steps.read.data.subject | upper }}` said nothing about what it used, and
`{{ now }}` was not a field anyone could pick. So `fieldPicker.js` reads a
reference character by character the way `_parse_ref_at` does
(`parseRefAt`), and a differential case holds the two equal on generated
texts; the list is held equal to the server's; the picker offers *This run*
under every list; and the Set form gains its type chooser ("It is": as it
comes, text, a number, yes or no, JSON) and dotted names, refused in the
server's words.

Driven: the real `fieldPicker.js` and `stepFields.js` in node over the DOM
shim (whose events do not bubble: each is fired on the element listening).
"""

from __future__ import annotations

import json
import random
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from helpers.workflow_cw_fake import build_sandbox, palette_json  # noqa: E402

from src import workflow_logic as wl  # noqa: E402
from src import workflow_refs as wr  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_PREAMBLE = (
    "import { document, Node, fire, settle, host, markup } from './shim.js';\n"
    "const FP = await import('./fieldPicker.js');\n"
    "const SF = await import('./stepFields.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const PAL = %s;\n"
    "const mount = (node, more = {}) => {\n"
    "  const h = host();\n"
    "  const got = [];\n"
    "  SF.mountStepFields(h, { node, palette: PAL, onApply: (s) => got.push(s), onCancel: () => got.push('cancel'), ...more });\n"
    "  return { h, got, done: () => fire(h.querySelector('.wf-step-done'), 'click') };\n"
    "};\n"
    "const problemOf = (h) => { const p = h.querySelector('.wf-sf-problem');\n"
    "  return p ? [p.textContent, p.dataset.field || null] : null; };\n"
    "const typed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'input', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const changed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'change', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const byField = (h, f) => h.querySelectorAll('[data-field]').find((n) => n.dataset.field === f);\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("changes"), _CANVAS_SHIM)


def _case(box, script):
    return _run(box, _PREAMBLE % palette_json(), script)


# ── One list, one grammar ────────────────────────────────────────────────────

def test_the_browsers_list_of_changes_and_set_types_are_the_servers(box):
    o = _case(box, "out({ filters: FP.FILTERS, defaults: FP.FILTER_ARG_DEFAULTS, types: SF.SET_TYPES });")
    assert o["filters"] == list(wr.FILTERS)
    assert o["defaults"] == wr.FILTER_ARG_DEFAULTS
    assert o["types"][0] == ["", "as it comes"]
    assert {k: w for k, w in o["types"][1:]} == wl.SET_TYPE_WORDS
    assert [k for k, _ in o["types"][1:]] == list(wl.SET_TYPES)


_GOOD = [
    "{{ steps.read.data.subject }}", "{{steps.read.text}}", "{{ item }}", "{{ item.list[1] }}",
    '{{ steps.start.data.headers["x-id"] }}', "{{ steps.a-b_c.data.items[0].name }}",
    "{{ now }}", "{{ run }}", "{{ run.id }}", "{{ run.workflow }}",
    "{{ steps.a.data.x | upper }}", "{{ steps.a.data.x|trim|lower }}",
    '{{ steps.a.data.x | default:"none" }}', '{{ steps.a.data.x | default : "" }}',
    "{{ steps.a.data.x | default:0 }}", "{{ steps.a.data.x | default:-12.25 }}",
    '{{ steps.a.data.tags | join:", " }}', '{{ steps.a.data.csv | split:"," | first }}',
    '{{ now | date:"%A %d %B %Y, %H:%M %Z" }}', "{{ item.n | number | default:0 }}",
    "{{ steps.a.data.body | from_json | json | length | last }}",
    "{{ now" + " | trim" * 8 + " }}",
]
_BAD = [
    "{{ steps.a.data.x | shout }}", "{{ steps.a.data.x | UPPER }}", "{{ steps.a.data.x | upper() }}",
    "{{ steps.a.data.x | }}", '{{ steps.a.data.x | upper:"a" }}', "{{ steps.a.data.x | join:5 }}",
    '{{ steps.a.data.x | split:"" }}', '{{ steps.a.data.x | date:"%c" }}', '{{ steps.a.data.x | date:"%" }}',
    "{{ steps.a.data.x | default:none }}", "{{ steps.a.data.x | default:007 }}",
    '{{ steps.a.data.x | default:"' + "x" * 65 + '" }}', '{{ steps.a.data.x | default:"a\\"b" }}',
    '{{ steps.a.data.x | default:"{{ steps.b.text }}" }}', '{{ steps.a.data.x | default:"open }}',
    "{{ now" + " | trim" * 9 + " }}", "{{ now.year }}", "{{ now[0] }}", "{{ run.secret }}",
    "{{ run.id.x }}", "{{ run[0] }}", "{{ nowadays }}", "{{ runner.id }}", "{{ steps.a.data.x[-1] }}",
    "{{ steps.a.data.x | default:1.1234567 }}", "{{ steps.a.data | lower lower }}",
]
# What a mutation may put in: the grammar's own characters and words.
_BITS = ["{", "}", "|", ":", ".", '"', " ", "\t", "[", "]", "0", "7", "-", "_", "a", "Z", "%", "\\",
         "\n", "é", "😀", "now", "run", "item", "steps.", ".data", ".text", "| default:", "| upper",
         "| date:", '"%Y"', "id", "workflow", "| join:", "1.5", "}}", "{{"]
# What, put before the `}}`, usually keeps a reference one (or makes a ninth change).
_KEEPS = [" ", "\t", "\n", " | trim", "|upper", ' | default:"x"', " | date", ' | join:"-"',
          " | number", " | first ", ' | date:"%d %B"', " | default:-3"]


def _generated(n=900, seed=1879):
    rng = random.Random(seed)
    out = list(_GOOD) + list(_BAD)
    for _ in range(n):
        t = rng.choice(_GOOD)
        for _ in range(rng.choice((1, 1, 2))):
            i = rng.randint(2, max(2, len(t) - 1))
            how = rng.random()
            if how < 0.35 and "}}" in t:
                end = t.rindex("}}")
                t = t[:end] + rng.choice(_KEEPS) + t[end:]
            elif how < 0.6:
                t = t[:i] + rng.choice(_BITS) + t[i:]
            elif how < 0.8:
                t = t[:i] + t[i + rng.randint(1, 4):]
            else:
                t = t[:i] + rng.choice(_BITS) + t[i + 1:]
        if t.startswith("{{"):
            out.append(t)
    return out


def _server(text):
    try:
        ref, end = wr._parse_ref_at(text, 0)
    except wr.RefError:
        return None
    return {"ref": text[:end], "root": ref.root, "node": ref.node, "field": ref.field,
            "filters": [[n, a] for n, a in ref.filters]}


def test_the_browser_reads_a_reference_exactly_as_the_server_does(box):
    """Differential (`Law 20`): the same texts — the cases above and seeded
    mutations of them — read by `_parse_ref_at` and by `parseRefAt`: the same
    references, the same roots, steps and changes, and the same refusals."""
    texts = _generated()
    o = _case(box, """
        const texts = %s;
        out(texts.map((t) => { const r = FP.parseRefAt(t, 0);
          return r && { ref: r.ref, root: r.root, node: r.node, field: r.field, filters: r.filters }; }));
    """ % json.dumps(texts))
    want = [_server(t) for t in texts]
    assert sum(1 for w in want if w) > 150 and sum(1 for w in want if not w) > 150, "both kinds, often"
    bad = [(t, w, g) for t, w, g in zip(texts, want, o) if w != g]
    assert not bad, bad[:5]


def test_refs_in_finds_each_reference_and_passes_over_an_escaped_one(box):
    o = _case(box, r"""
        const text = 'Hi {{ steps.read.data.name | trim | upper }}, \\{{ steps.read.text }} is text; {{ nope }} '
          + 'at {{ now | date:"%H:%M" }} in {{ run.workflow }}.';
        out(FP.refsIn(text).map((r) => [r.ref, r.root, r.path, r.filters]));
    """)
    assert o == [
        ["{{ steps.read.data.name | trim | upper }}", "steps", "name", [["trim", None], ["upper", None]]],
        ['{{ now | date:"%H:%M" }}', "now", "", [["date", "%H:%M"]]],
        ["{{ run.workflow }}", "run", "workflow", []],
    ]


@pytest.mark.parametrize("text,line", [
    ("{{ steps.read.data.subject | upper }}", "Uses: subject, from “Read” (in capitals)."),
    ('{{ steps.read.data.to | default:"nobody" | trim }}',
     "Uses: to, from “Read” (or “nobody” when it is not there, without spaces around it)."),
    ("{{ steps.read.data.tags | join }}", "Uses: tags, from “Read” (joined with “, ”)."),
    ('{{ steps.read.data.when | date:"%d %B" }}', "Uses: when, from “Read” (as a date, written “%d %B”)."),
    ("{{ now }} by {{ run.workflow }}, run {{ run.id }}",
     "Uses: the time the step starts; the workflow’s name; this run’s id."),
    ("{{ item.amount | number }}", "Uses: amount, from each item (as a number)."),
    ("{{ steps.read.data.x | shout }}", ""),
])
def test_the_uses_line_says_what_a_change_does_in_words(box, text, line):
    o = _case(box, "out(FP.usesLine(%s, (id) => ({ read: 'Read' })[id]));" % json.dumps(text))
    assert o == line


def test_pathwords_names_the_runs_fields(box):
    o = _case(box, "out(FP.RUN_FIELDS.map((f) => [f.ref, FP.pathWords(f)]));")
    assert o == [["{{ run.id }}", "run.id"], ["{{ run.workflow }}", "run.workflow"], ["{{ now }}", "now"]]
    for ref, _ in o:
        wr.parse_template(ref)


def test_the_picker_offers_this_run_under_every_list_and_says_what_can_follow(box):
    o = _case(box, """
        const root = host();
        const wrap = root.appendChild(new Node('div'));
        const ta = wrap.appendChild(new Node('textarea'));
        const sources = [{ node_id: 'read', label: 'Read', kind: 'set', origin: 'declared',
          fields: [{ ref: '{{ steps.read.data.subject }}', path: ['subject'], type: 'text', example: null }] }];
        const got = FP.openFieldPicker(ta, { load: async () => ({ ok: true, sources }), layer: () => root });
        await settle(5);
        const picker = root.querySelector('.wf-picker');
        const run = picker.querySelector('.wf-picker-run');
        const shown = {
          groups: picker.querySelectorAll('.wf-picker-source').map((s) => s.querySelector('.wf-picker-step-name').textContent),
          head: run.querySelector('.wf-picker-step-name').textContent,
          fields: run.querySelectorAll('.wf-picker-field').map((b) => [b.dataset.ref,
            b.querySelector('.wf-picker-path').textContent]),
          hint: run.querySelector('.wf-picker-lede').textContent,
        };
        fire(run.querySelectorAll('.wf-picker-field').find((b) => b.dataset.ref === '{{ now }}'), 'click');
        const picked = await got;
        // Nothing to pick from the steps: this run's fields are still there.
        const ta2 = wrap.appendChild(new Node('textarea'));
        const got2 = FP.openFieldPicker(ta2, { load: async () => ({ ok: true, sources: [] }), layer: () => root });
        await settle(5);
        const empty = root.querySelector('.wf-picker').querySelector('.wf-picker-run').querySelectorAll('.wf-picker-field').length;
        fire(root.querySelector('.wf-picker-cancel'), 'click');
        out({ shown, picked, empty, cancelled: await got2, markup: markup(root) });
    """)
    assert o["shown"]["groups"] == ["Read"], "this run is not one of the earlier steps"
    assert o["shown"]["head"] == "This run"
    assert o["shown"]["fields"] == [["{{ run.id }}", "run.id"], ["{{ run.workflow }}", "run.workflow"],
                                    ["{{ now }}", "now"]]
    assert o["shown"]["hint"].startswith('After a field, a change can follow: | default:"none" when it is not there')
    for name in ("default", "lower", "trim", "number", "from_json", "join", "date"):
        assert f"| {name}" in o["shown"]["hint"] and name in wr.FILTERS
    assert o["picked"] == "{{ now }}"
    assert o["empty"] == 3 and o["cancelled"] is None
    assert o["markup"] == []


# ── The Set form ─────────────────────────────────────────────────────────────

def test_a_set_field_says_what_its_value_is_and_comes_back_unchanged(box):
    config = {"fields": [
        {"name": "customer.name", "value": "{{ steps.read.data.name | trim }}", "type": "text"},
        {"name": "n", "value": "3", "type": "number"},
        {"name": "ok", "value": "yes", "type": "yes/no"},
        {"name": "list", "value": "[1, 2]", "type": "json"},
        {"name": "plain", "value": "as it came"},
        {"name": "count", "value": 7}]}
    o = _case(box, """
        const m = mount({ id: 's', kind: 'set', label: 'Shape', config: %s });
        const choosers = m.h.querySelectorAll('[data-field]').filter((n) => /^fields\\[\\d+\\]\\.type$/.test(n.dataset.field));
        const words = choosers[0].querySelectorAll('option').map((op) => [op.value, op.textContent]);
        const labels = choosers[0].parentNode.querySelectorAll('.wf-sf-label').map((l) => l.textContent);
        m.done();
        out({ config: m.got[0].config, chosen: choosers.map((c) => c.value), words, labels });
    """ % json.dumps(config))
    assert o["config"] == config, "a number stays a number; no type is no type"
    assert o["chosen"] == ["text", "number", "yes/no", "json", "", ""]
    assert o["words"] == [["", "as it comes"], ["text", "text"], ["number", "a number"],
                          ["yes/no", "yes or no"], ["json", "JSON (a list or an object)"]]
    assert o["labels"] == ["Name", "It is", "Value"]


def test_choosing_a_type_writes_it_and_as_it_comes_writes_none(box):
    o = _case(box, """
        const m = mount({ id: 's', kind: 'set', label: 'Shape', config: { fields: [
          { name: 'a', value: '1' }, { name: 'b', value: '2', type: 'number' }] } });
        changed(byField(m.h, 'fields[0].type'), 'number');
        changed(byField(m.h, 'fields[1].type'), '');
        typed(byField(m.h, 'fields[1].name'), 'order.total');
        m.done();
        out(m.got[0].config);
    """)
    assert o == {"fields": [{"name": "a", "value": "1", "type": "number"},
                            {"name": "order.total", "value": "2"}]}


@pytest.mark.parametrize("fields,refusal", [
    ([{"name": "a", "value": "1"}, {"name": "a.b", "value": "2"}],
     ["“a.b” is inside “a”, which is set as well. Set one or the other.", "fields[1].name"]),
    ([{"name": "a.b.c", "value": "1"}, {"name": "a.b", "value": "2"}],
     ["“a.b.c” is inside “a.b”, which is set as well. Set one or the other.", "fields[1].name"]),
    ([{"name": "a..b", "value": "1"}],
     ["A field’s name is letters, digits and _ (not starting with a digit), such as headline; "
      "a dot puts one inside another, such as customer.name.", "fields[0].name"]),
    ([{"name": ".".join("abcdefghi"), "value": "1"}],
     ["A field’s name is letters, digits and _ (not starting with a digit), such as headline; "
      "a dot puts one inside another, such as customer.name.", "fields[0].name"]),
])
def test_a_set_name_the_server_would_refuse_is_refused_on_the_field(box, fields, refusal):
    o = _case(box, """
        const m = mount({ id: 's', kind: 'set', label: 'Shape', config: { fields: %s } });
        m.done();
        out({ problem: problemOf(m.h), applied: m.got.length });
    """ % json.dumps(fields))
    assert o == {"problem": refusal, "applied": 0}
    # The server refuses the same names, in the same words.
    names = [f["name"] for f in fields]
    assert any(wl.set_name_parts(n) is None for n in names) or wl.set_names_clash(names)


def test_a_set_name_the_server_takes_the_form_takes(box):
    names = ["customer.name", "a_b.c1.d", ".".join("abcdefgh"), "x" * 64]
    o = _case(box, """
        const names = %s;
        const m = mount({ id: 's', kind: 'set', label: 'Shape', config: { fields: names.map((n) => ({ name: n, value: 'v' })) } });
        m.done();
        out({ problem: problemOf(m.h), names: m.got[0] && m.got[0].config.fields.map((f) => f.name) });
    """ % json.dumps(names))
    assert o == {"problem": None, "names": names}
    assert all(wl.set_name_parts(n) for n in names) and wl.set_names_clash(names) is None
