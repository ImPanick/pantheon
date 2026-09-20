# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B875` — `notes.js:_attrEsc` had two contracts and one implementation.

`static/js/notes.js` called one `_attrEsc` from two places that hand it
different things.

  * `_linkify` (`:575`) runs `_esc` over the whole string and then calls it on a
    href cut out of the **already-escaped** text. There, omitting `&` is
    **correct**: escaping it a second time turns `?a=1&amp;b=2` into
    `?a=1&amp;amp;b=2`, which is what `tests/test_email_linkify_security_js.py`
    has pinned since it was written.
  * The todo row (`:1989`, `:1995`) hands it **raw** text — `agentMenuTitle`,
    built from the todo's own words, and `note.id` — and there omitting `&` is a
    fidelity bug: a todo whose text contains the six characters `&quot;` was
    drawn as a single `"`, because the browser decoded an entity the note never
    meant as one.

This is fidelity, not injection, and `B866` proved the subtlety by measurement
rather than by reading: it changed both second-stage escapers to add `&`,
watched the linkify test go red, and changed them back with the reasoning
written into both files. **A comment is not a fix.** The row's answer, and this
one, is two named helpers — `_attrEsc` for text that has been escaped once,
`_attrEscRaw` for text that has not — with the second written *in terms of* the
first, so the five characters they share cannot drift apart. That last part is
`B611` in one line: two escapers in one file that disagree about one character
is exactly what this fortnight has been about.

Everything below is executed. The two helpers are lifted out of the shipped
module with `tests/helpers/js_source.py` and run under node, and the todo row's
attributes are built from the module's **own template text**, read out of the
file rather than retyped, with the real helpers in scope — so an assertion here
cannot pass on a template this repository does not ship.
"""
import json
import re
import shutil
import subprocess
import textwrap
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
NOTES_JS = ROOT / "static" / "js" / "notes.js"
SRC = NOTES_JS.read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(not shutil.which("node"),
                                reason="node binary not on PATH")


def _fn(signature: str) -> str:
    """One function out of `notes.js`, as a declaration node can run."""
    name = signature.split()[-1]
    return "function %s(s) %s" % (name, js_function(SRC, signature))


def _line_holding(needle: str) -> str:
    """The one source line that contains `needle`, read not retyped.

    `P0-31`'s rule, applied to a template literal: a test that retypes the
    markup it is asserting on is testing its own copy. If this raises, the
    builder moved and the case has to be pointed at where it went — which is the
    failure everybody wants, rather than a green test over a template nobody
    ships.
    """
    hits = [ln for ln in SRC.splitlines() if needle in ln]
    assert len(hits) == 1, (needle, len(hits))
    return hits[0].strip()


def _node(script: str):
    done = subprocess.run(["node", "--input-type=module", "-e",
                           textwrap.dedent(script)],
                          cwd=str(ROOT), capture_output=True, text=True,
                          timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


_HELPERS = "\n".join((
    _fn("function _attrEsc"),
    _fn("function _attrEscRaw"),
))


class _Attrs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def _first_tag(markup: str):
    parser = _Attrs()
    parser.feed(markup)
    assert parser.tags, markup
    return parser.tags[0]


# ── two helpers, two contracts ──────────────────────────────────────────────


def test_there_are_two_helpers_and_the_raw_one_is_built_from_the_other():
    """`Law 13`'s answer, in the shape the row asked for: not one function with
    a comment about which caller is which."""
    assert "function _attrEsc(s)" in SRC
    assert "function _attrEscRaw(s)" in SRC
    raw = js_function(SRC, "function _attrEscRaw")
    assert "_attrEsc(" in raw, (
        "the raw helper must delegate; a second list of the same five "
        "characters is the defect this row is closing")
    assert raw.count("replace") == 1, (
        "exactly one extra replace — the `&` — and the other five come from "
        "the helper it calls")


def test_the_second_stage_helper_still_leaves_the_ampersand_alone():
    """The half `B866` measured and changed back. `_linkify` escapes first and
    cuts a href out of the result; escaping `&` here would double it."""
    out = _node(_HELPERS + """
        console.log(JSON.stringify({
          href: _attrEsc('https://x.test/?a=1&amp;b=2'),
          quote: _attrEsc('a"b'),
        }));
    """)
    assert out["href"] == "https://x.test/?a=1&amp;b=2"
    assert out["quote"] == "a&quot;b"


def test_the_raw_helper_escapes_the_ampersand_first():
    """`&` before the rest, or `<` becomes `&amp;lt;`."""
    out = _node(_HELPERS + """
        console.log(JSON.stringify({
          amp: _attrEscRaw('a&b'),
          entity: _attrEscRaw('&quot;'),
          tag: _attrEscRaw('<b>'),
          all: _attrEscRaw('a"b\\'c<d>e&f`g'),
        }));
    """)
    assert out["amp"] == "a&amp;b"
    assert out["entity"] == "&amp;quot;"
    assert out["tag"] == "&lt;b&gt;", "not &amp;lt;b&amp;gt;"
    assert out["all"] == "a&quot;b&#39;c&lt;d&gt;e&amp;f&#96;g"


def test_the_old_single_helper_lost_the_entity():
    """The defect, reproduced, so the row can be checked rather than believed.

    This is what `_attrEsc` did at the todo row before the split: a note whose
    text holds the six characters `&quot;` came back as five, and the browser
    then decoded those five into one `"`.
    """
    out = _node(_HELPERS + """
        console.log(JSON.stringify({ old: _attrEsc('&quot;') }));
    """)
    assert out["old"] == "&quot;"
    assert _first_tag('<b title="%s">' % out["old"])[1]["title"] == '"', (
        "the old behaviour: six characters in, one out of the DOM")


# ── the row's Verify, through the module's own template ─────────────────────


_MENU_TITLE = _line_holding("const agentMenuTitle =")
_SESSION_ATTR = _line_holding("const agentSessionAttr =")
_BUTTON = _line_holding('data-agent-title="${_attrEscRaw(agentMenuTitle)}"')


def _render_row(item: dict, note: dict, agent_title: str = "Solve this todo with the agent"):
    """The todo row's opening `<button>`, built by the module's own template.

    The three lines below are read out of `static/js/notes.js` — the
    `agentMenuTitle` expression, the `agentSessionAttr` expression and the
    `<button>` itself — and evaluated with the real `_attrEsc`/`_attrEscRaw` in
    scope. Nothing here restates the markup or the escaping, so this case fails
    if either moves.
    """
    return _node(_HELPERS + """
        const item = %s;
        const note = %s;
        const i = 0;
        const agentDoneClass = '';
        const agentStyleAttr = '';
        const agentTitle = %s;
        %s
        %s
        console.log(JSON.stringify({ html: `%s` }));
    """ % (json.dumps(item), json.dumps(note), json.dumps(agent_title),
           _SESSION_ATTR, _MENU_TITLE, _BUTTON))["html"]


def test_a_todo_whose_text_contains_an_entity_keeps_all_six_characters():
    """The row's `Verify`.

    A person writes `&quot;` in a todo — six characters, meaning those six. The
    menu title is built from that text and goes into `data-agent-title`. Parsed
    back out of the DOM it has to be the six characters, not the one they used
    to decode into.
    """
    html = _render_row({"text": 'say &quot;hello&quot; nicely'}, {"id": "n1"})
    tag, attrs = _first_tag(html)
    assert tag == "button"
    assert attrs["data-agent-title"] == 'Agent: say &quot;hello&quot; nicely', (
        attrs["data-agent-title"])


def test_a_todo_with_a_bare_ampersand_keeps_it():
    """`AT&T &copy; 2026` and not `AT&T © 2026`.

    The probe is an ampersand the browser *would* complete into an entity. A
    bare `&` followed by a space survives an unescaped attribute too, so it
    cannot tell the two helpers apart and would have been a case that passes
    either way.
    """
    html = _render_row({"text": "AT&T &copy; 2026"}, {"id": "n1"})
    assert _first_tag(html)[1]["data-agent-title"] == "Agent: AT&T &copy; 2026"


def test_a_quote_in_a_todo_is_still_one_attribute():
    """The fidelity fix must not cost the safety property. `B866`'s probe."""
    html = _render_row({"text": 'x" onerror=BOOM y="'}, {"id": "n1"})
    tag, attrs = _first_tag(html)
    assert tag == "button"
    assert "onerror" not in attrs, attrs
    assert attrs["data-agent-title"] == 'Agent: x" onerror=BOOM y="'


def test_a_session_title_the_server_chose_is_raw_too():
    """`agent_session_title` comes back from the server and is not escaped on
    the way in; it takes the same path."""
    html = _render_row({"text": "t", "agent_session_title": "R&D &amp; ops"},
                       {"id": "n1"})
    assert _first_tag(html)[1]["data-agent-title"] == "R&D &amp; ops"


def test_the_session_id_attribute_survives_an_ampersand():
    """Same discriminating probe for the other raw call site (`:1989`).

    `a&b` would pass whichever helper built it, because `&b` is not an entity
    the parser completes; `a&amp;b` only survives the round trip if `&` was
    escaped on the way in.
    """
    html = _render_row({"text": "t", "agent_session_id": "a&amp;b"}, {"id": "n1"})
    assert _first_tag(html)[1]["data-session-id"] == "a&amp;b"


def test_every_raw_attribute_in_the_row_uses_the_raw_helper():
    """All four of them, not just the one the row's sentence names.

    `agentTitle` is one of six literals in the module today and none holds an
    `&`, so swapping its helper is a mutation nothing can observe from the
    module's own values — measured, and the reason this case feeds the template
    a value instead of taking the module's. `note.id` is the server's and could
    hold anything. The template is the module's own line either way, so this
    pins which helper each attribute in it is built with.
    """
    html = _render_row({"text": "t", "agent_session_id": "s&amp;1"},
                       {"id": "n&amp;1"}, agent_title="Stop the &amp; run")
    _tag, attrs = _first_tag(html)
    assert attrs["data-note-id"] == "n&amp;1", attrs
    assert attrs["data-session-id"] == "s&amp;1", attrs
    assert attrs["title"] == "Stop the &amp; run", attrs


def test_the_six_agent_titles_are_still_literals_with_no_ampersand():
    """Why the case above has to supply its own value, stated as a check rather
    than as a claim — if a future title gains an `&`, this fails and the case
    above can take the module's value instead."""
    titles = re.findall(r"'([^']*this todo[^']*)'", SRC)
    assert len(titles) >= 4, titles
    assert not any("&" in t for t in titles), titles


def test_the_row_renders_at_all_without_an_agent_session():
    """A guard against a probe that passes because the template produced
    nothing recognisable."""
    html = _render_row({"text": "plain"}, {"id": "n1"})
    tag, attrs = _first_tag(html)
    assert tag == "button"
    assert attrs["data-note-id"] == "n1"
    assert "data-session-id" not in attrs
    assert attrs["data-agent-title"] == "Agent: plain"


# ── the linkify contract, end to end ────────────────────────────────────────


def test_linkify_does_not_double_escape_a_query_string():
    """The second-stage contract from the caller's side, not the helper's.

    `_esc` then `_attrEsc`, which is the pair `B866` measured. `_esc` delegates
    to `uiModule.esc`, so it is stubbed with the shipped escaper rather than a
    fourth opinion about which characters matter (`B874`).
    """
    from tests.helpers.esc_stub import esc_source

    linkify = "function _linkify(s) %s" % js_function(SRC, "function _linkify")
    esc = "function _esc(s) { return esc(s || ''); }"
    out = _node(esc_source() + _HELPERS + "\n" + esc + "\n" + linkify + """
        console.log(JSON.stringify({
          html: _linkify('see https://x.test/?a=1&b=2 for more'),
          plain: _linkify('a & b < c'),
        }));
    """)
    href = re.search(r'href="([^"]*)"', out["html"]).group(1)
    assert href == "https://x.test/?a=1&amp;b=2", href
    assert "&amp;amp;" not in out["html"], out["html"]
    assert out["plain"] == "a &amp; b &lt; c"
