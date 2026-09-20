# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B866`'s sweep, and `B611` — one HTML escaper in `static/js/`, driven.

`B866` was a local `esc` inside `showMcpForm` shadowing `settings.js`'s own
import of `ui.js:esc`: the local one escaped `&` and `<`, the canonical one
escapes `& < > " '`, and sixty lines below the shadowed one was interpolated
into `title="${esc(t.description)}"` — an attribute, holding a description that
comes from a third-party MCP server. That one is fixed. **The row asked for the
sweep, because the pattern is invisible to every test that checks the canonical
escaper.**

**What the sweep found, measured 2026-09-19 at `HEAD`.** Nineteen local
definitions across seventeen files. Seven of them were the same DOM round-trip —
`createElement('div')`, `textContent = s`, `return innerHTML` — whose comment in
`emailLibrary/utils.js` claimed it "handles all the entities that matter for
innerHTML". It does not. The HTML fragment serialiser escapes `&`, `<`, `>` and
U+00A0 **in a text node** and leaves `"` and `'` alone, because a text node does
not need them. Measured against a real parser rather than read off the spec:

    textContent round-trip of  a"b'c<d>e&f   ->  a"b'c&lt;d&gt;e&amp;f
    ui.js:esc          of  a"b'c<d>e&f   ->  a&quot;b&#39;c&lt;d&gt;e&amp;f

and with `x" onerror=BOOM y="` fed through each into `<img alt="…">`, the
round-trip one parses to **three attributes** (`alt`, `onerror`, `y`) and the
canonical one to one. Seven of those round-trips reached attributes:
`gallery.js` at twenty sites including `alt="${_esc(img.prompt)}"` (`:1283`,
`:1465`) and `value="${_esc(img.prompt)}"` (`:1477`), which hold the prompt the
user typed; `tasks.js` at three including the task-name field (`:1384`) and the
search box (`:3586`); `emailInbox.js` at `:77`/`:79`
(`data-email-filter-tag="…"`, `title="…"`, tag derived from a third-party
message); `research/panel.js` at `:960` (`src="…"`, a thumbnail URL from a
search result). `document.js:10876`'s `_escHtml` escaped `& < >` only and
`:3434` interpolates it into `src="…"`.

`notes.js`'s `_attrEsc` was the one case the measurement **contradicted**: it
escapes `" ' < > \`` and never `&`, which reads like an attribute break-out and
is not one — an attribute value is decoded after it is delimited, so a literal
`&quot;` in the source stays inside the value. It is a fidelity bug (a note
title containing the text `&quot;` renders as `"`) and it is fixed as one.

**What this file does.** It finds every escaper definition still in
`static/js/**` — that part is discovery, not assertion — and then **runs each
one under node** against hostile input, places the result in a real HTML
attribute, and parses it with `html.parser`. Nothing here greps for a fix
(`Law 20`); a new local escaper added tomorrow with four characters instead of
five is found by the discovery and killed by the drive.

`tasks.js` is additionally driven as a whole module, because it is the file
`B611` is about: it had two escapers, `_esc` (a round-trip) and `_escHtml`
(five replaces), and every builder in it picked one by habit.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import textwrap
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.helpers.esc_stub import esc_source  # B874
from tests.helpers.js_source import js_definition  # B876

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

JS = ROOT / "static" / "js"
UI_JS = JS / "util" / "escapeHtml.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the canonical escaper, lifted rather than copied ────────────────────────
def _canonical_source() -> str:
    """The canonical `ESC_MAP` + `esc`, as shipped (`util/escapeHtml.js`).

    Copying it here would be the defect this file is about, one directory over.

    `B874` moved the lifting itself into `tests/helpers/esc_stub.py`, because
    eleven sandbox stubs needed the same text and four of them had written a
    weaker `esc` instead. Two regexes that had to know the module's exact
    layout became one call that does not.
    """
    return esc_source("__canonEsc")


# ── discovery ───────────────────────────────────────────────────────────────
#
# Names that have ever been an HTML escaper in this tree. `cookbookServe.js`'s
# `_esc` is `CSS.escape` — a selector escaper, a different job with the same
# name — and is excluded by the body check below rather than by a name list.
# `_attrEscRaw` before `_attrEsc`: a regex alternation is ordered, and the
# shorter name would match first and leave `Raw` unconsumed, so `B875`'s new
# first-stage helper would be invisible to this sweep — which is the failure
# mode of every discovery in this file.
_NAMES = (r"(?:_?esc|_?escHtml|_?escHTML|escapeHtml|escapeHTML|htmlEscape"
          r"|_attrEscRaw|_attrEsc)")
_DEF = re.compile(
    r"^(?P<indent>[ \t]*)(?:export\s+)?"
    r"(?:function\s+(?P<fname>%s)\s*\(|"
    r"(?:const|let|var)\s+(?P<vname>%s)\s*=\s*(?=[^;\n]*=>))" % (_NAMES, _NAMES),
    re.M,
)


def _definition(src: str, start: int) -> str:
    """The whole definition beginning at `start`, by brace balance.

    Handles both a `{ … }` body and a single-expression arrow, which ends at
    the first `;` or newline outside any bracket.

    **`B876`.** This used to be forty lines here, with their own string,
    template, comment and regex-literal rules — a sixth scanner in a suite that
    already had one, in the file whose whole subject is "there is one escaper
    and everybody uses it". It is now `tests/helpers/js_source.py`, which gets
    its regex-start rule from `.pantheon/check-specifiers.py` rather than
    guessing that "every regex in an escaper in this tree sits directly after
    `(` or `,`", which is what the comment here used to say.
    """
    return js_definition(src, start)


class Escaper:
    def __init__(self, path: Path, name: str, line: int, source: str):
        self.path, self.name, self.line, self.source = path, name, line, source
        self.rel = str(path.relative_to(ROOT))

    def __repr__(self) -> str:                       # pragma: no cover - ids only
        return "%s:%d %s" % (self.rel, self.line, self.name)


def _discover() -> list:
    found = []
    for path in sorted(JS.rglob("*.js")):
        if path == UI_JS or "/lib/" in str(path):
            continue
        src = path.read_text(encoding="utf-8")
        for m in _DEF.finditer(src):
            name = m.group("fname") or m.group("vname")
            body = _definition(src, m.start())
            # Not an HTML escaper: an injected binding with no body of its own
            # (`let esc;`, `_esc = config.esc`), or `CSS.escape`.
            if "CSS.escape" in body or "=>" not in body and "function" not in body:
                continue
            if "replace" not in body and "innerHTML" not in body and "uiModule" not in body \
               and "esc(" not in body:
                continue
            found.append(Escaper(path, name, src[:m.start()].count("\n") + 1, body))
    return found


ESCAPERS = _discover()


def test_the_sweep_found_the_escapers_it_is_about():
    """A discovery regex that matched nothing would make every case below vacuous."""
    rels = {e.rel for e in ESCAPERS}
    assert len(ESCAPERS) >= 12, [repr(e) for e in ESCAPERS]
    for expected in ("static/js/tasks.js", "static/js/gallery.js",
                     "static/js/settings.js", "static/js/notes.js"):
        assert expected in rels, (expected, sorted(rels))


# ── the drive ───────────────────────────────────────────────────────────────
_PROBE_JS = r"""
%(canonical)s
const uiModule = { esc: __canonEsc };

// The browser's text-node serialiser, measured against a real parser on
// 2026-09-19: it escapes `&`, `<`, `>` and U+00A0 and leaves `"` and `'`
// alone. Here so that a re-added `textContent` round-trip escaper is caught
// with the right message instead of throwing on a missing `document`.
const document = {
  createElement: () => ({
    set textContent(v) { this._t = String(v == null ? '' : v); },
    get textContent() { return this._t || ''; },
    get innerHTML() {
      return (this._t || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/ /g, '&nbsp;');
    },
  }),
};

%(subject)s

%(alias)s
const probes = %(probes)s;
console.log(JSON.stringify(probes.map((p) => String(%(name)s(p)))));
"""


def _subject_with_its_dependencies(esc: Escaper) -> str:
    """The escaper, plus any escaper in ITS OWN file that it calls.

    `B875` split `notes.js:_attrEsc` into two — `_attrEsc` for text `_esc` has
    already been through and `_attrEscRaw` for text nothing has escaped yet —
    and wrote the second in terms of the first, so the five characters they
    share cannot drift apart. Lifting the second alone into the probe would
    leave that call unresolved, so its neighbour comes with it. Aliasing it to
    the canonical escaper instead would be wrong in a way that passes: the
    canonical one escapes `&`, and the whole point of the pair is which of them
    does.
    """
    extra = [other for other in ESCAPERS
             if other.path == esc.path and other.name != esc.name
             and re.search(r"\b%s\s*\(" % re.escape(other.name), esc.source)]
    names = {esc.name} | {other.name for other in extra}
    return "\n".join([other.source for other in extra] + [esc.source]), names


def _run_escaper(tmp_path: Path, esc: Escaper, probes: list) -> list:
    entry = tmp_path / "case.mjs"
    subject, declared = _subject_with_its_dependencies(esc)
    entry.write_text(_PROBE_JS % {
        "canonical": _canonical_source(),
        # Several of these delegate through a bare name imported from the leaf
        # module rather than through `uiModule.esc`; the aliases give the lifted
        # function the bindings it has in its own file. The subject's own name
        # is never aliased, which would redeclare it.
        "alias": "\n".join("const %s = __canonEsc;" % n
                           for n in ("esc", "escapeHtml") if n not in declared),
        "subject": textwrap.dedent(subject),
        "probes": json.dumps(probes),
        "name": esc.name,
    }, encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, "%s\n%s" % (repr(esc), proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


class _Attrs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs))


def _attrs_of(markup: str):
    p = _Attrs()
    p.feed(markup)
    assert p.tags, markup
    return p.tags[0][1]


@pytest.mark.parametrize("esc", ESCAPERS, ids=repr)
def test_a_quote_cannot_open_a_second_attribute(tmp_path, esc):
    """`B866`'s exact shape, per escaper, driven rather than read.

    The probe is what a third-party MCP tool description, an image prompt or a
    mail tag can contain. If the escaper leaves the `"` alone, the parser reads
    `onerror` as a second attribute on the element.
    """
    double, single = _run_escaper(tmp_path, esc, ['x" onerror=BOOM y="', "x' onerror=BOOM y='"])

    got = _attrs_of('<img alt="%s">' % double)
    assert [n for n, _ in got] == ["alt"], (repr(esc), got)

    got = _attrs_of("<img alt='%s'>" % single)
    assert [n for n, _ in got] == ["alt"], (repr(esc), got)


# `_attrEsc` is a **second-stage** escaper in both files that have one:
# `notes.js:537` and `emailLibrary/utils.js:76` escape the whole string with
# `_esc` and then call `_attrEsc` on a href cut out of the result. It therefore
# must not escape `&` — doing so turns `?a=1&amp;b=2` into `?a=1&amp;amp;b=2`,
# which `tests/test_email_linkify_security_js.py` asserts against by name. The
# sweep measured whether the omission is an attribute break-out and it is not:
# an attribute value is decoded after it is delimited, so a literal `&quot;` in
# the source stays inside the value. Its own expectations, then, rather than a
# parametrised exception with no reason attached.
_SECOND_STAGE = [e for e in ESCAPERS if e.name == "_attrEsc"]
_SINGLE_STAGE = [e for e in ESCAPERS if e.name != "_attrEsc"]


def test_the_sweep_found_both_kinds():
    assert len(_SECOND_STAGE) == 2, [repr(e) for e in _SECOND_STAGE]
    assert len(_SINGLE_STAGE) >= 11, len(_SINGLE_STAGE)
    assert "static/js/notes.js:548 _attrEscRaw" in [repr(e) for e in _SINGLE_STAGE], (
        "`B875`'s first-stage helper must be swept as a single-stage escaper: "
        "it is handed raw text and has to escape `&`")


@pytest.mark.parametrize("esc", _SECOND_STAGE, ids=repr)
def test_the_second_stage_escaper_closes_the_attribute_and_does_not_double_escape(tmp_path, esc):
    quoted, amped = _run_escaper(tmp_path, esc, ['x" onerror=BOOM y="', "a&amp;b"])
    assert [n for n, _ in _attrs_of('<img alt="%s">' % quoted)] == ["alt"], quoted
    assert amped == "a&amp;b", amped


@pytest.mark.parametrize("esc", _SINGLE_STAGE, ids=repr)
def test_a_tag_in_a_text_node_stays_text(tmp_path, esc):
    out, = _run_escaper(tmp_path, esc, ["<script>alert(1)</script>&amp;"])
    assert "<script" not in out, (repr(esc), out)
    # `&` first, or `&amp;` typed by a person comes back out as a bare `&`.
    assert out.startswith("&lt;") and "&amp;amp;" in out, (repr(esc), out)


@pytest.mark.parametrize("esc", _SINGLE_STAGE, ids=repr)
def test_every_escaper_agrees_with_the_canonical_one(tmp_path, esc):
    """`Law 13`: one behaviour, however many call sites spell it.

    Falsy handling is deliberately left out of the comparison — `gallery.js`'s
    returns `''` for `0` and always has — so this is about the five characters
    and nothing else.

    **The `_attrEsc*` family escapes a sixth, and that is allowed here rather
    than waved through.** A backtick is nothing in a text node and is a template
    delimiter in an attribute an inline handler later reads, so `notes.js` has
    escaped it since before `B866`. The rule this test enforces is therefore:
    an escaper may escape MORE than the canonical five, and may never escape
    fewer or escape one of the five differently. `B875`'s `_attrEscRaw` is the
    first escaper to exercise that clause, and it inherits the backtick from the
    `_attrEsc` it delegates to.
    """
    probe = "a\"b'c<d>e&f`g"
    got, = _run_escaper(tmp_path, esc, [probe])
    canonical = (probe.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                 .replace('"', "&quot;").replace("'", "&#39;"))
    if esc.name.startswith("_attrEsc"):
        canonical = canonical.replace("`", "&#96;")
    assert got == canonical, (repr(esc), got, canonical)


# ── `B611`: the whole module, not a lifted function ─────────────────────────
#
# The cases above run each escaper on its own, which is the only way to cover
# seventeen files. This one drives the real `tasks.js` through the shared
# sandbox and asserts on what a *builder* emitted, because `B611` is not about
# an escaper in isolation — it is about a file with two of them where every
# builder picked one by habit, and `_showForm` picked the weaker one for the
# field that holds a name the user typed.

from test_the_palette_moves_to_the_server_js import (  # noqa: E402
    _SHIM, _STUBS, TASKS_JS,
)
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

_FORM_EXPORT = "\nexport const __f = { _showForm, _escHtml };\n"


@pytest.fixture(scope="module")
def form_sandbox(tmp_path_factory):
    box = _make_sandbox(tmp_path_factory.mktemp("escform"), TASKS_JS, _SHIM, _STUBS)
    copy = box / TASKS_JS.name
    copy.write_text(copy.read_text(encoding="utf-8") + _FORM_EXPORT, encoding="utf-8")
    return box


_FORM_PREAMBLE = (
    "import { document, Node } from './shim.js';\n"
    "const { __f } = await import('./tasks.js');\n"
)


def test_a_quote_in_a_task_name_does_not_open_an_attribute_in_the_form(form_sandbox):
    """`tasks.js:1384`. Before the merge this line read

        value="${_esc(existing?.name || '')}"

    and `_esc` was the DOM round-trip, which does not escape `"`. A task named
    `x" onfocus=… y="` therefore shipped three extra attributes on the name
    input every time somebody opened it to edit.
    """
    hostile = 'x" onfocus=BOOM autofocus y="'
    out = _run(form_sandbox, _FORM_PREAMBLE, """
        const modal = document.body.appendChild(new Node('div'));
        modal.setAttribute('id', 'tasks-modal');
        const body = modal.appendChild(new Node('div'));
        body.className = 'modal-body';
        // `_showForm` writes the card as one `innerHTML` string and then wires
        // it up by id. The shared shim stores markup as a string rather than
        // parsing it, so the wiring finds nothing unless the ids are seeded —
        // which is why they are, rather than the call being wrapped in a
        // `try` that would also swallow a builder that stopped building.
        for (const id of ['task-form-type-toggle', 'task-form-trigger-toggle',
                          'task-form-type-opts', 'task-form-trigger-opts',
                          'task-form-action', 'task-form-action-extra',
                          'task-form-action-param', 'task-form-notif',
                          'task-form-urgent-email-prompt']) {
          const n = document.body.appendChild(new Node('div'));
          n.setAttribute('id', id);
        }
        let wiring = null;
        try { __f._showForm({ id: 7, name: %s }); }
        catch (e) { wiring = String(e && e.message || e); }
        console.log(JSON.stringify({ html: body.innerHTML, wiring }));
    """ % json.dumps(hostile))

    class _Input(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.hit = None

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)

        def handle_starttag(self, tag, attrs):
            if dict(attrs).get("id") == "task-form-name":
                self.hit = attrs

    # Said plainly rather than glossed: `_showForm` writes the card as one
    # `innerHTML` string and then wires eleven nested renderers up by id. Those
    # renderers write `innerHTML` into elements the shim stores as strings, so
    # the chain runs out of nodes partway and throws. The card itself is
    # already written by then, which is what this case is about. A builder that
    # threw *before* writing it leaves `body.innerHTML` empty and fails on the
    # next line, so the `catch` cannot hide a builder that stopped building.
    assert out["wiring"] in (None,) or "addEventListener" in out["wiring"], out["wiring"]

    p = _Input()
    p.feed(out["html"])
    assert p.hit is not None, out["html"][:400]
    names = [n for n, _ in p.hit]
    assert "onfocus" not in names and "autofocus" not in names, names
    assert dict(p.hit)["value"] == hostile, dict(p.hit)["value"]
