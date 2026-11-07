# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-09` — a reference reads a field, and nothing else. Pure.

`D-2026-10-01-05` §2: data moves between a workflow's steps by picking a field
from a list, never by writing code. What the picker inserts is a reference,

    {{ steps.<step id>.data.<path> }}     what a step made, as data
    {{ steps.<step id>.text }}            what a step said, as text
    {{ steps.start.data.<path> }}         what the trigger handed the workflow
    {{ item.<path> }}                     the item, inside a For-each step
    {{ run.id }} / {{ run.workflow }}     this run's id and its workflow's name
    {{ now }}                             when the step started, ISO 8601 in UTC

and this module is the only thing that reads one (`Law 7`): the save route, the
walker at run, the dry run, the picker and `workflow_slots.render_call` all ask
it. The grammar (`SLICE-CD-DESIGN` § 1.1, widened by `B1879`):

    ref    := "{{" ws* path change* ws* "}}"
    path   := "steps" "." NODE "." FIELD seg*  |  "item" seg*
            | "run" ["." RUNKEY]  |  "now"
    FIELD  := "data" | "text"          RUNKEY := "id" | "workflow"
    seg    := "." KEY | "[" INDEX "]" | "[" '"' QKEY '"' "]"
    change := ws* "|" ws* NAME [ws* ":" ws* ARG]
    NAME   := one of `FILTERS` (below), lower case, exactly
    ARG    := '"' 0-64 characters, no '"', '\\', '{', '}' or control '"'
            | -?(0|[1-9][0-9]{0,14})(.[0-9]{1,6})?
    KEY    := [A-Za-z_][A-Za-z0-9_]{0,63}    INDEX := 0|[1-9][0-9]{0,5}
    QKEY   := 1-128 characters, no '"', no '\\', no control character
    "\\{{" is the literal text "{{"

**`B1879` — a CLOSED list of changes, and still no language.** The audit
(`no-transforms`) found a reference could only name a place: no fallback when
a branch was not taken, no way to read a model's text answer as JSON, nothing
to upper-case, join or count, no date, and the only way out — a Code step —
runs in a workstation that is switched off on a default install. So a
reference may end in up to `FILTERS_MAX` changes from the closed list
`FILTERS`, applied in order AFTER the path has been read, each a pure function
of the value it is handed and its one typed argument:

    default:"x"   x when nothing is there, null or blank text (bare: "")
    upper, lower, trim                    the value as text, changed
    length        characters of text, items of a list, fields of an object
    join:", "     a list as one text (bare: ", ")
    split:","     a text as a list, each part trimmed, blanks dropped (bare: ",")
    json          the value as JSON text
    from_json     a text read as JSON (anything else as it is)
    number        a number, or numeric text as one
    date:"%Y-%m-%d"  an ISO date or time (or seconds since 1970) written out
    first, last   a list's first or last item, a text's first or last letter

**There are still no calls, no arithmetic, no negative indexes, no slices and
no names a value can supply.** A change's name is one of those thirteen words
and its argument is typed by the author; nothing in a resolved VALUE is ever
read as a change, a path or a pattern (the value is data the change is handed).
Each costs at most linear time in the value it is handed (`from_json` reads at
most `FROM_JSON_MAX_CHARS`; `date` writes its pattern with this module's own
table, never the platform's `strftime`, so no locale and no directive the
platform reads differently). A change that cannot apply — `number` handed
"abc", `from_json` handed text that is not JSON, `first` handed an empty list
— answers `MISSING`, exactly as a field that is not there does, so `default`
after it catches it and a step that needs the value says what is missing
(`missing_text` adds which change could not read it).

Every character class is spelled out in ASCII (`[A-Za-z]`, never `\\w` or
`str.isalpha`), so a fullwidth `｛｛`, a Cyrillic letter or a Unicode space is
not part of a reference: it is text.

**What a reference can reach.** The context is JSON — `build_context` round-
trips it — so resolution only ever meets dict, list, str, number, bool and
None. A dict is looked up by exact key (`type(x) is dict`, so no mapping whose
lookup runs code), a list by an in-range integer (a bool is not an index), and
anything else is `MISSING`. There is no attribute access anywhere, so nothing
on a Python object can be reached. `now` and `run` are put in the context when
it is built (`run_roots`) — the clock is read then, never while resolving.

**One pass.** `parse_template` splits the text into literal parts and
references once; `render_text` joins the resolved values in as opaque text and
never scans them again. Outside data that contains `{{ steps.x.data.secret }}`
— or `{{ now | upper }}` — arrives as those characters, and nothing it names is
read (`Law 17`: the adversary is whoever writes an inbound mail or webhook
body).
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

# ── The words ────────────────────────────────────────────────────────────────

REF_ROOT_STEPS = "steps"
REF_ROOT_ITEM = "item"
# `B1879`. This run, and when the step started. Put in the context when it is
# built (`run_roots`); a reference reads them as it reads any field.
REF_ROOT_RUN = "run"
REF_ROOT_NOW = "now"
REF_ROOTS = (REF_ROOT_STEPS, REF_ROOT_ITEM, REF_ROOT_RUN, REF_ROOT_NOW)
# What `{{ run.<key> }}` may name — a closed pair, so a typo is refused at save
# ("has a field name that cannot be read") rather than found empty at run.
RUN_KEY_ID = "id"
RUN_KEY_WORKFLOW = "workflow"
RUN_KEYS = (RUN_KEY_ID, RUN_KEY_WORKFLOW)
REF_FIELD_DATA = "data"
REF_FIELD_TEXT = "text"
REF_FIELDS = (REF_FIELD_DATA, REF_FIELD_TEXT)
# The trigger's place in `steps`. The same word as the document's reserved
# start key, which `workflow_document.START_KEY` imports from here so the two
# cannot drift (`Law 7`); no step may be called this.
START_NODE = "start"

# A step's id: the document's id rule, stated once here and imported by
# `workflow_document` (it was `_NODE_ID_RE` and `NODE_ID_MAX` there).
NODE_ID_MAX = 64
NODE_ID_RE = re.compile(r"[A-Za-z0-9_-]+")

# ── Bounds (`SLICE-CD-DESIGN` § 1.1) — what a template may hold ──────────────
REF_MAX_SEGMENTS = 16
TEMPLATE_MAX_REFS = 32
TEMPLATE_MAX_CHARS = 8000
QKEY_MAX = 128
INDEX_MAX_DIGITS = 6

_WS = " \t\r\n"
_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_KEY_MAX = 64
_INDEX_RE = re.compile(r"0|[1-9][0-9]*")
_KEY_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")

# ── `B1879`. The changes a reference may end in — a CLOSED list ──────────────
#
# The stored words: a document holds them inside its text, so they are names
# that never move once shipped (`Law 2`; `FORBIDDEN.md` Part 1 at the merge).
# Adding one is a new word here, its line in `_apply`, its words in
# `FILTER_WORDS` and the browser's copy of this tuple (`fieldPicker.js`
# `FILTERS`, which a test holds equal to this one).
FILTER_DEFAULT = "default"
FILTER_UPPER = "upper"
FILTER_LOWER = "lower"
FILTER_TRIM = "trim"
FILTER_LENGTH = "length"
FILTER_JOIN = "join"
FILTER_SPLIT = "split"
FILTER_JSON = "json"
FILTER_FROM_JSON = "from_json"
FILTER_NUMBER = "number"
FILTER_DATE = "date"
FILTER_FIRST = "first"
FILTER_LAST = "last"
FILTERS = (FILTER_DEFAULT, FILTER_UPPER, FILTER_LOWER, FILTER_TRIM, FILTER_LENGTH,
           FILTER_JOIN, FILTER_SPLIT, FILTER_JSON, FILTER_FROM_JSON, FILTER_NUMBER,
           FILTER_DATE, FILTER_FIRST, FILTER_LAST)
# Which take an argument after `:` (each also works bare, with the default
# here); every other change takes none, and one given is refused.
FILTER_ARG_DEFAULTS = {FILTER_DEFAULT: "", FILTER_JOIN: ", ", FILTER_SPLIT: ",",
                       FILTER_DATE: "%Y-%m-%d"}
# Why a change found nothing it could use, for `missing_text`. A change not
# named here cannot fail on a value that is there.
FILTER_FAILS = {
    FILTER_NUMBER: "is not a number",
    FILTER_FROM_JSON: "is not JSON",
    FILTER_DATE: "is not a date or a time",
    FILTER_FIRST: "has nothing in it",
    FILTER_LAST: "has nothing in it",
}
FILTERS_MAX = 8
FILTER_ARG_MAX = 64
# The most text `from_json` reads. A context is already capped where it is
# kept (`workflow_node_record_max_chars`, `trigger_payload_max_chars`, both at
# most 1,000,000); this is the same ceiling, stated so the cost of the change
# is bounded by this module and not by a setting somewhere else.
FROM_JSON_MAX_CHARS = 1_000_000
_FILTER_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ARG_NUMBER_RE = re.compile(r"-?(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,6})?")
# The directives `date` writes, by this module's own table (`_format_moment`):
# the platform's `strftime` is locale-dependent (%a, %b) and reads directives
# differently on Windows (%e, %-d), so a pattern means one thing everywhere.
DATE_DIRECTIVES = frozenset("YmdHMSyjIpaAbBzZ%")


class _Missing:
    """A reference that reaches nothing. Falsy, a singleton, and never equal to
    a JSON value — so "not there" and `null` stay two different answers."""

    __slots__ = ()
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self):
        return False

    def __repr__(self):
        return "MISSING"

    def __reduce__(self):  # pragma: no cover - a copy is the same answer
        return (_Missing, ())


MISSING = _Missing()

# ── Why a template cannot be read (`Law 10`: an enum, the sentence derived) ──
REF_SYNTAX = "syntax"
REF_TOO_LONG = "too_long"
REF_TOO_MANY = "too_many"
REF_TOO_DEEP = "too_deep"
REF_BAD_INDEX = "bad_index"
REF_BAD_KEY = "bad_key"
# `B1879`.
REF_BAD_FILTER = "bad_filter"
REF_BAD_FILTER_ARG = "bad_filter_arg"
REF_TOO_MANY_FILTERS = "too_many_filters"
REF_ERROR_REASONS = {
    REF_SYNTAX: "is not a reference",
    REF_TOO_LONG: f"is longer than {TEMPLATE_MAX_CHARS:,} characters, which is as long as text "
                  f"with references can be",
    REF_TOO_MANY: f"has more than {TEMPLATE_MAX_REFS} references",
    REF_TOO_DEEP: f"goes more than {REF_MAX_SEGMENTS} levels deep",
    REF_BAD_INDEX: "has a position that is not a whole number up to 999999",
    REF_BAD_KEY: "has a field name that cannot be read",
    REF_BAD_FILTER: "ends in a change a reference does not have",
    REF_BAD_FILTER_ARG: "gives a change something it does not take",
    REF_TOO_MANY_FILTERS: f"makes more than {FILTERS_MAX} changes",
}
_HOW = ("A reference reads {{ steps.<step>.data.<field> }}, {{ item.<field> }}, "
        "{{ run.id }}, {{ run.workflow }} or {{ now }}; write \\{{ for the text “{{”.")
# `B1879`. Said after a change that cannot be read: the whole closed list, as
# it is written (`default:"…"`, `join:", "`, `upper`).
_HOW_FILTERS = "A reference can end in " + ", ".join(
    f"| {name}:\"{'…' if name == FILTER_DEFAULT else FILTER_ARG_DEFAULTS[name]}\""
    if name in FILTER_ARG_DEFAULTS else f"| {name}" for name in FILTERS) + "."
_FILTER_REASONS = (REF_BAD_FILTER, REF_BAD_FILTER_ARG, REF_TOO_MANY_FILTERS)


class RefError(ValueError):
    """A template that does not parse. `reason` is a `REF_ERROR_REASONS` key,
    `at` the character offset of the `{{` it is about, `sentence` what a
    person is told."""

    def __init__(self, reason: str, at: int, sentence: str):
        super().__init__(sentence)
        self.reason = reason
        self.at = at
        self.sentence = sentence


def _error(reason: str, text: str, at: int) -> RefError:
    # `B1879`: a reference with changes is longer, so the snippet shows up to
    # 120 characters of it (an argument never holds a brace, so the first
    # `}}` is its end).
    snippet = text[at:at + 120]
    close = snippet.find("}}")
    if close >= 0:
        snippet = snippet[:close + 2]
    elif len(text) > at + 120:
        snippet += "…"
    if reason == REF_TOO_LONG or reason == REF_TOO_MANY:
        sentence = f"The text {REF_ERROR_REASONS[reason]}."
    elif reason in _FILTER_REASONS:
        sentence = f"“{snippet}” {REF_ERROR_REASONS[reason]}. {_HOW_FILTERS}"
    else:
        sentence = f"“{snippet}” {REF_ERROR_REASONS[reason]}. {_HOW}"
    return RefError(reason, at, sentence)


class Ref(NamedTuple):
    """One reference. `root` is `steps`, `item`, `run` or `now` (`B1879`);
    `node` and `field` are set for `steps` and `None` for the rest; `path` the
    segments after them — `str` keys and `int` positions; `text` the reference
    exactly as written; `filters` (`B1879`) its changes, in order, each
    `(name, argument)` with `argument` `None` when none was written. The last
    field has a default, so a reference built with five values is the same
    reference it always was."""
    root: str
    node: str | None
    field: str | None
    path: tuple
    text: str
    filters: tuple = ()


class Template(NamedTuple):
    """A text split once into literal `str` parts and `Ref` parts."""
    source: str
    parts: tuple

    @property
    def refs(self) -> tuple:
        return tuple(p for p in self.parts if isinstance(p, Ref))

    @property
    def single(self) -> Ref | None:
        """The one reference when the text is exactly one (blank around it is
        allowed), else `None`."""
        refs = self.refs
        if len(refs) != 1:
            return None
        if any(isinstance(p, str) and p.strip(_WS) for p in self.parts):
            return None
        return refs[0]


# ── Reading ──────────────────────────────────────────────────────────────────

def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in _WS:
        i += 1
    return i


def _word_at(text: str, i: int, word: str) -> bool:
    """`word` starts at `i` and ends at a boundary (not a key character)."""
    end = i + len(word)
    return text.startswith(word, i) and (end >= len(text) or text[end] not in _KEY_CHARS)


def _parse_filter_arg(text: str, i: int, at: int) -> tuple:
    """`(argument, end)` for the argument after a change's `:` — a quoted text
    of at most `FILTER_ARG_MAX` characters with no quote, backslash, brace or
    control character, or a plain number. Raises `RefError`."""
    if text.startswith('"', i):
        close = text.find('"', i + 1)
        if close < 0:
            raise _error(REF_BAD_FILTER_ARG, text, at)
        arg = text[i + 1:close]
        if (len(arg) > FILTER_ARG_MAX or any(c in arg for c in '\\{}')
                or any(ord(c) < 0x20 or ord(c) == 0x7F for c in arg)):
            raise _error(REF_BAD_FILTER_ARG, text, at)
        return arg, close + 1
    m = _ARG_NUMBER_RE.match(text, i)
    if not m or (m.end() < len(text) and text[m.end()] in _KEY_CHARS):
        raise _error(REF_BAD_FILTER_ARG, text, at)
    word = m.group(0)
    return (float(word) if "." in word else int(word)), m.end()


def _date_pattern_ok(pattern) -> bool:
    """Every `%` in a `date` pattern is followed by one of `DATE_DIRECTIVES`."""
    if not isinstance(pattern, str):
        return False
    i = 0
    while i < len(pattern):
        if pattern[i] == "%":
            if i + 1 >= len(pattern) or pattern[i + 1] not in DATE_DIRECTIVES:
                return False
            i += 2
        else:
            i += 1
    return True


def _parse_filters(text: str, i: int, at: int) -> tuple:
    """`(filters, end)` — the changes after a reference's path, each
    `(name, argument)`, from the closed list (`FILTERS`). `end` is where the
    blank before `}}` starts. Raises `RefError` for a name that is not on the
    list, an argument a change does not take, or more than `FILTERS_MAX`."""
    filters = []
    while True:
        j = _skip_ws(text, i)
        if not text.startswith("|", j):
            return tuple(filters), i
        j = _skip_ws(text, j + 1)
        m = _FILTER_NAME_RE.match(text, j)
        if not m or m.group(0) not in FILTERS:
            raise _error(REF_BAD_FILTER, text, at)
        name = m.group(0)
        j = m.end()
        arg = None
        k = _skip_ws(text, j)
        if text.startswith(":", k):
            if name not in FILTER_ARG_DEFAULTS:
                raise _error(REF_BAD_FILTER_ARG, text, at)
            arg, j = _parse_filter_arg(text, _skip_ws(text, k + 1), at)
            if name in (FILTER_JOIN, FILTER_SPLIT, FILTER_DATE) and not isinstance(arg, str):
                raise _error(REF_BAD_FILTER_ARG, text, at)
            if name == FILTER_SPLIT and arg == "":
                raise _error(REF_BAD_FILTER_ARG, text, at)
            if name == FILTER_DATE and (arg == "" or not _date_pattern_ok(arg)):
                raise _error(REF_BAD_FILTER_ARG, text, at)
        filters.append((name, arg))
        if len(filters) > FILTERS_MAX:
            raise _error(REF_TOO_MANY_FILTERS, text, at)
        i = j


def _parse_ref_at(text: str, at: int) -> tuple:
    """`(Ref, end)` for the reference whose `{{` starts at `at`, or raises
    `RefError`. `end` is the offset just past its `}}`."""
    i = _skip_ws(text, at + 2)
    node = field = None
    if _word_at(text, i, REF_ROOT_NOW):
        # `B1879`. `now` is one text: nothing follows it but changes.
        root = REF_ROOT_NOW
        i += len(REF_ROOT_NOW)
        if i < len(text) and text[i] in ".[":
            raise _error(REF_SYNTAX, text, at)
        return _finish_ref(text, at, i, root, None, None, [])
    if _word_at(text, i, REF_ROOT_RUN):
        # `B1879`. `run`, `run.id` or `run.workflow`, and nothing deeper.
        root = REF_ROOT_RUN
        i += len(REF_ROOT_RUN)
        path = []
        if text.startswith(".", i):
            m = _KEY_RE.match(text, i + 1)
            if not m:
                raise _error(REF_SYNTAX, text, at)
            if m.group(0) not in RUN_KEYS:
                raise _error(REF_BAD_KEY, text, at)
            path.append(m.group(0))
            i = m.end()
        if i < len(text) and text[i] in ".[":
            raise _error(REF_BAD_KEY, text, at)
        return _finish_ref(text, at, i, root, None, None, path)
    if text.startswith(REF_ROOT_STEPS + ".", i):
        root = REF_ROOT_STEPS
        i += len(REF_ROOT_STEPS) + 1
        m = NODE_ID_RE.match(text, i)
        if not m or len(m.group(0)) > NODE_ID_MAX:
            raise _error(REF_SYNTAX, text, at)
        node = m.group(0)
        i = m.end()
        if not text.startswith(".", i):
            raise _error(REF_SYNTAX, text, at)
        i += 1
        for word in REF_FIELDS:
            end = i + len(word)
            if text.startswith(word, i) and (end >= len(text) or text[end] not in _KEY_CHARS):
                field = word
                i = end
                break
        if field is None:
            raise _error(REF_SYNTAX, text, at)
    elif (text.startswith(REF_ROOT_ITEM, i)
          and (i + len(REF_ROOT_ITEM) >= len(text)
               or text[i + len(REF_ROOT_ITEM)] not in _KEY_CHARS)):
        root = REF_ROOT_ITEM
        i += len(REF_ROOT_ITEM)
    else:
        raise _error(REF_SYNTAX, text, at)
    path = []
    while i < len(text):
        if text[i] == ".":
            m = _KEY_RE.match(text, i + 1)
            if not m:
                raise _error(REF_SYNTAX, text, at)
            if len(m.group(0)) > _KEY_MAX:
                raise _error(REF_BAD_KEY, text, at)
            path.append(m.group(0))
            i = m.end()
        elif text[i] == "[":
            if text.startswith('"', i + 1):
                close = text.find('"', i + 2)
                if close < 0:
                    raise _error(REF_SYNTAX, text, at)
                key = text[i + 2:close]
                if (not key or len(key) > QKEY_MAX or "\\" in key
                        or any(ord(c) < 0x20 or ord(c) == 0x7F for c in key)):
                    raise _error(REF_BAD_KEY, text, at)
                if not text.startswith("]", close + 1):
                    raise _error(REF_SYNTAX, text, at)
                path.append(key)
                i = close + 2
            else:
                m = _INDEX_RE.match(text, i + 1)
                if not m or not text.startswith("]", m.end()):
                    raise _error(REF_BAD_INDEX, text, at)
                if len(m.group(0)) > INDEX_MAX_DIGITS:
                    raise _error(REF_BAD_INDEX, text, at)
                path.append(int(m.group(0)))
                i = m.end() + 1
        else:
            break
        if len(path) > REF_MAX_SEGMENTS:
            raise _error(REF_TOO_DEEP, text, at)
    return _finish_ref(text, at, i, root, node, field, path)


def _finish_ref(text: str, at: int, i: int, root, node, field, path) -> tuple:
    """The rest of a reference after its path: its changes (`B1879`), then
    blank, then `}}`."""
    filters, i = _parse_filters(text, i, at)
    i = _skip_ws(text, i)
    if not text.startswith("}}", i):
        raise _error(REF_SYNTAX, text, at)
    end = i + 2
    return Ref(root, node, field, tuple(path), text[at:end], filters), end


def parse_template(text: str) -> Template:
    """`text` split once into literal parts and references. Raises `RefError`.

    Anything containing `{{` that does not parse as a reference is refused —
    write `\\{{` for the literal text. A text with no `{{` is one literal part
    whatever its length: the length bound is on text that holds references.
    """
    if not isinstance(text, str):
        raise TypeError("a template is text")
    if "{{" not in text:
        return Template(text, (text,) if text else ())
    if len(text) > TEMPLATE_MAX_CHARS:
        raise _error(REF_TOO_LONG, text, 0)
    parts = []
    buf = []
    i = 0
    count = 0
    while True:
        j = text.find("{{", i)
        if j < 0:
            buf.append(text[i:])
            break
        if j > 0 and text[j - 1] == "\\":
            buf.append(text[i:j - 1])
            buf.append("{{")
            i = j + 2
            continue
        buf.append(text[i:j])
        ref, i = _parse_ref_at(text, j)
        count += 1
        if count > TEMPLATE_MAX_REFS:
            raise _error(REF_TOO_MANY, text, j)
        literal = "".join(buf)
        if literal:
            parts.append(literal)
        buf = []
        parts.append(ref)
    literal = "".join(buf)
    if literal:
        parts.append(literal)
    return Template(text, tuple(parts))


def single_ref(text) -> Ref | None:
    """The one reference `text` is (blank around it allowed), or `None` — for
    a text that is something else, or that does not parse."""
    if not isinstance(text, str) or "{{" not in text:
        return None
    try:
        return parse_template(text).single
    except RefError:
        return None


def refs_in(value) -> list:
    """Every reference in every text inside `value` (a str, or lists and dicts
    of them), in order. Raises `RefError` for a text that does not parse."""
    found = []
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if "{{" in item:
                found.append(parse_template(item).refs)
        elif isinstance(item, dict):
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, (list, tuple)):
            stack.extend(reversed(list(item)))
    return [ref for refs in found for ref in refs]


def references_in_text(text: str) -> tuple:
    """Every reference anywhere in `text`, escaped or not, nested or not.

    For a `never` setting, which is copied verbatim and never rendered: it is
    refused if anything in it would read as a reference, so a `\\{{ … }}` or a
    `{{ {{ … }} }}` there is caught too (fail closed). A `{{` that is not a
    reference — a Go template's `{{.Names}}`, say — is the person's own text
    and stays exactly as typed.
    """
    if not isinstance(text, str) or "{{" not in text:
        return ()
    found = []
    i = text.find("{{")
    while i >= 0:
        try:
            ref, _end = _parse_ref_at(text, i)
            found.append(ref)
        except RefError:
            # Not a reference here — the person's own `{{` (a Go template, say).
            # The question is only whether one IS; the scan moves to the next.
            pass
        i = text.find("{{", i + 1)
    return tuple(found)


# ── Resolving ────────────────────────────────────────────────────────────────

def _json_copy(value):
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def now_text(moment: datetime | None = None) -> str:
    """`B1879`. What `{{ now }}` reads: ISO 8601 in UTC to the second, with
    `Z` — `2026-11-07T08:00:00Z`."""
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_roots(run_id=None, workflow=None, now: datetime | None = None) -> dict:
    """`B1879`. The two roots a context carries besides `steps` and `item`:
    `now` (`now_text`, the clock read HERE, when the context is built — never
    while a reference resolves) and `run`, `{id, workflow}` — `None` for a
    step tested on its own, which is not part of a run."""
    return {REF_ROOT_NOW: now_text(now),
            REF_ROOT_RUN: {RUN_KEY_ID: None if run_id is None else str(run_id),
                           RUN_KEY_WORKFLOW: None if workflow is None else str(workflow)}}


def build_context(steps: dict | None = None, item=MISSING, *, run_id=None, workflow=None,
                  now: datetime | None = None) -> dict:
    """The context references resolve against, normalised by a JSON round trip.

    `steps` maps a step id (or `START_NODE`, the trigger) to `{data, text,
    status}`; `item` is the For-each item, left out when there is none.
    `B1879`: `now` and `run` too (`run_roots`)."""
    ctx = {"steps": steps or {}}
    if item is not MISSING:
        ctx["item"] = item
    ctx.update(run_roots(run_id, workflow, now))
    return _json_copy(ctx)


def _root_value(ref: Ref, ctx: dict):
    """What a reference's root reads in `ctx`, before its path."""
    if ref.root == REF_ROOT_ITEM:
        return ctx["item"] if "item" in ctx else MISSING
    if ref.root == REF_ROOT_STEPS:
        steps = ctx.get("steps")
        if type(steps) is not dict or type(ref.node) is not str or ref.node not in steps:
            return MISSING
        entry = steps[ref.node]
        if type(entry) is not dict or ref.field not in REF_FIELDS or ref.field not in entry:
            return MISSING
        return entry[ref.field]
    if ref.root == REF_ROOT_NOW:
        value = ctx.get(REF_ROOT_NOW)
        return value if type(value) is str else MISSING
    if ref.root == REF_ROOT_RUN:
        value = ctx.get(REF_ROOT_RUN)
        return value if type(value) is dict else MISSING
    return MISSING


def resolve(ref: Ref, ctx) -> object:
    """What `ref` reads in `ctx`, its changes applied (`B1879`), or `MISSING`.
    Never raises, never calls anything a value supplies."""
    value = resolve_path(ref, ctx)
    for name, arg in getattr(ref, "filters", ()) or ():
        try:
            value = _apply(name, arg, value)
        except Exception:  # noqa: BLE001 - "a reference never raises" is the contract
            return MISSING
    return value


def resolve_path(ref: Ref, ctx) -> object:
    """What `ref`'s path reads in `ctx`, before its changes, or `MISSING`."""
    if type(ctx) is not dict:
        return MISSING
    cur = _root_value(ref, ctx)
    if cur is MISSING:
        return MISSING
    for seg in ref.path:
        if type(seg) is int:
            if type(cur) is list and 0 <= seg < len(cur):
                cur = cur[seg]
            else:
                return MISSING
        elif type(seg) is str:
            if type(cur) is dict and seg in cur:
                cur = cur[seg]
            else:
                return MISSING
        else:
            return MISSING
    if cur is None or type(cur) in (str, int, float, bool, list, dict):
        return cur
    return MISSING


def as_text(value) -> str:
    """A resolved value as the text it is spliced in as: text as itself, a
    number or a yes/no as JSON, nothing (`None`, `MISSING`) as nothing, and a
    list or object as JSON — so an object cannot become keys of anything."""
    if value is MISSING or value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(value, ensure_ascii=False, default=str)


# ── `B1879`. What each change does — pure, total, at most linear ─────────────

_NUMBER_TEXT_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_WHOLE_TEXT_RE = re.compile(r"[+-]?[0-9]+")
_ISO_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def to_number(value):
    """A number, numeric text read as one, or `MISSING`. A yes/no is not a
    number; NaN and infinity are not either; a whole number stays an `int`
    (a 400-digit id stays exact). Shared with the Set step's "a number"
    (`workflow_logic`), so the change and the type read text the same way."""
    if isinstance(value, bool):
        return MISSING
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else MISSING
    if isinstance(value, str):
        text = value.strip()
        try:
            if _WHOLE_TEXT_RE.fullmatch(text):
                return int(text)
            if _NUMBER_TEXT_RE.fullmatch(text):
                number = float(text)
                return number if math.isfinite(number) else MISSING
        except ValueError:      # more digits than Python reads as an int
            return MISSING
    return MISSING


def _no_constant(word):
    raise ValueError(f"{word} is not JSON")


def read_json(value):
    """Text read as JSON, or `MISSING` for text that is not JSON (or longer
    than `FROM_JSON_MAX_CHARS`, or nested deeper than Python reads); a value
    that is not text is handed back as it is — it is JSON already. Shared
    with the Set step's "JSON" (`workflow_logic`)."""
    if value is MISSING:
        return MISSING
    if not isinstance(value, str):
        return value
    if len(value) > FROM_JSON_MAX_CHARS:
        return MISSING
    try:
        return json.loads(value, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        return MISSING


def moment_of(value):
    """An ISO date (its midnight), an ISO date and time, or seconds since
    1970, as an aware `datetime` — the offset it was written with kept, none
    read as UTC — or `None`. Shared with the If step's dates
    (`workflow_logic`)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            if not math.isfinite(value):
                return None
            return datetime.fromtimestamp(value, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _ISO_DATE_RE.match(text):
        return None
    try:
        if len(text) == 10:
            d = date.fromisoformat(text)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        moment = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")


def _offset_text(moment: datetime, colon: bool) -> str:
    offset = moment.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, mins = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}{':' if colon else ''}{mins:02d}"


def _format_moment(moment: datetime, pattern: str) -> str:
    """`pattern` with each `DATE_DIRECTIVES` directive written from `moment`,
    by this table — English names, no locale, the same on every platform.
    `%z` is `+0100`, `%Z` is `UTC` at no offset and `+01:00` otherwise."""
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c != "%" or i + 1 >= len(pattern):
            out.append(c)
            i += 1
            continue
        d = pattern[i + 1]
        i += 2
        hour12 = moment.hour % 12 or 12
        out.append({
            "Y": f"{moment.year:04d}", "m": f"{moment.month:02d}", "d": f"{moment.day:02d}",
            "H": f"{moment.hour:02d}", "M": f"{moment.minute:02d}", "S": f"{moment.second:02d}",
            "y": f"{moment.year % 100:02d}", "j": f"{moment.timetuple().tm_yday:03d}",
            "I": f"{hour12:02d}", "p": "AM" if moment.hour < 12 else "PM",
            "a": _DAYS[moment.weekday()][:3], "A": _DAYS[moment.weekday()],
            "b": _MONTHS[moment.month - 1][:3], "B": _MONTHS[moment.month - 1],
            "z": _offset_text(moment, False),
            "Z": "UTC" if not (moment.utcoffset() or timedelta(0)) else _offset_text(moment, True),
            "%": "%",
        }.get(d, "%" + d))
    return "".join(out)


def _blank(value) -> bool:
    return value is MISSING or value is None or (isinstance(value, str) and not value.strip())


def _apply(name: str, arg, value):
    """One change, `name` (one of `FILTERS`) with its argument, applied to
    `value`. `MISSING` in is `MISSING` out for every change but `default`."""
    if name == FILTER_DEFAULT:
        if _blank(value):
            return FILTER_ARG_DEFAULTS[FILTER_DEFAULT] if arg is None else arg
        return value
    if value is MISSING:
        return MISSING
    if name == FILTER_UPPER:
        return as_text(value).upper()
    if name == FILTER_LOWER:
        return as_text(value).lower()
    if name == FILTER_TRIM:
        return as_text(value).strip()
    if name == FILTER_LENGTH:
        if value is None:
            return 0
        if isinstance(value, (str, list, dict)):
            return len(value)
        return len(as_text(value))
    if name == FILTER_JOIN:
        sep = FILTER_ARG_DEFAULTS[FILTER_JOIN] if arg is None else str(arg)
        if isinstance(value, list):
            return sep.join(as_text(item) for item in value)
        return as_text(value)
    if name == FILTER_SPLIT:
        sep = FILTER_ARG_DEFAULTS[FILTER_SPLIT] if arg is None else str(arg)
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [part.strip() for part in as_text(value).split(sep) if part.strip()]
    if name == FILTER_JSON:
        return json.dumps(value, ensure_ascii=False)
    if name == FILTER_FROM_JSON:
        return read_json(value)
    if name == FILTER_NUMBER:
        return to_number(value)
    if name == FILTER_DATE:
        moment = moment_of(value)
        if moment is None:
            return MISSING
        return _format_moment(moment, FILTER_ARG_DEFAULTS[FILTER_DATE] if arg is None else arg)
    if name in (FILTER_FIRST, FILTER_LAST):
        if isinstance(value, (list, str)) and value:
            return value[0] if name == FILTER_FIRST else value[-1]
        return MISSING
    return MISSING


def missing_text(ref: Ref, ctx) -> str:
    """`B1879`. How a reference that reached nothing is named in a step's
    sentence: as written — and, when its path did read a value but one of its
    changes could not use it, which change and why ("{{ steps.a.text |
    number }} (what it read is not a number)"), so "refers to something that
    is not there" is not said of a field that is there."""
    filters = getattr(ref, "filters", ()) or ()
    if not filters:
        return ref.text
    value = resolve_path(ref, ctx)
    if value is MISSING:
        return ref.text
    for name, arg in filters:
        try:
            after = _apply(name, arg, value)
        except Exception:  # noqa: BLE001 - never raises
            after = MISSING
        if after is MISSING:
            why = FILTER_FAILS.get(name, "could not be read")
            return f"{ref.text} (what “{name}” was handed {why})"
        value = after
    return ref.text


def render_text(t: Template, ctx) -> tuple:
    """`(text, missing)` — `t` with every reference replaced by its value as
    text, in one pass; `missing` the references that reached nothing, each
    named by `missing_text` (as written; `B1879`: with the change that could
    not read it, when one could not)."""
    out = []
    missing = []
    for part in t.parts:
        if isinstance(part, Ref):
            value = resolve(part, ctx)
            if value is MISSING:
                missing.append(missing_text(part, ctx))
            out.append(as_text(value))
        else:
            out.append(part)
    return "".join(out), tuple(missing)


def render_value(t: Template, ctx) -> tuple:
    """`(value, missing)`. A template that is exactly one reference yields the
    raw JSON value (`None` when it reaches nothing); anything else is
    `render_text`'s text."""
    one = t.single
    if one is None:
        return render_text(t, ctx)
    value = resolve(one, ctx)
    if value is MISSING:
        return None, (missing_text(one, ctx),)
    return value, ()


_SLOT_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def _slot_name(ref: Ref) -> str:
    keys = [s for s in ref.path if isinstance(s, str)]
    if keys:
        last_key = max(i for i, s in enumerate(ref.path) if isinstance(s, str))
        tail = [str(s) for s in ref.path[last_key + 1:]]
        name = "_".join([keys[-1], *tail])
    elif ref.root in (REF_ROOT_ITEM, REF_ROOT_RUN, REF_ROOT_NOW):
        name = "_".join([ref.root, *(str(s) for s in ref.path)])
    else:
        name = "_".join([ref.node or "", ref.field or "", *(str(s) for s in ref.path)])
    name = _SLOT_UNSAFE.sub("_", name).strip("_")[:40]
    return name or "value"


def render_named_slots(t: Template, ctx) -> tuple:
    """`(text, slots)` for a Prompt step (`P22-09`): each reference becomes a
    named slot — "Summarise the issue titled [title]." — and `slots` is
    `[(slot, ref_text, value)]`, one per distinct reference, `value` being what
    it reads (`MISSING` when nothing). The values travel in the untrusted-
    context block, never spliced into the prompt."""
    names = {}
    taken = set()
    slots = []
    out = []
    for part in t.parts:
        if not isinstance(part, Ref):
            out.append(part)
            continue
        # `B1879`: the same field with other changes is another value.
        key = (part.root, part.node, part.field, part.path, part.filters)
        if key not in names:
            base = _slot_name(part)
            name = base
            n = 2
            while name in taken:
                name = f"{base}_{n}"
                n += 1
            taken.add(name)
            names[key] = name
            slots.append((name, part.text, resolve(part, ctx)))
        out.append(f"[{names[key]}]")
    return "".join(out), slots


# ── Writing ──────────────────────────────────────────────────────────────────

def _format_path(path) -> str:
    out = []
    for seg in path or ():
        if type(seg) is int:
            if not 0 <= seg <= 999999:
                raise ValueError(f"not a position a reference can name: {seg!r}")
            out.append(f"[{seg}]")
        elif type(seg) is str:
            if _KEY_RE.fullmatch(seg) and len(seg) <= _KEY_MAX:
                out.append(f".{seg}")
            elif (seg and len(seg) <= QKEY_MAX and '"' not in seg and "\\" not in seg
                  and not any(ord(c) < 0x20 or ord(c) == 0x7F for c in seg)):
                out.append(f'["{seg}"]')
            else:
                raise ValueError(f"not a field name a reference can name: {seg!r}")
        else:
            raise ValueError(f"not a path segment: {seg!r}")
    if len(out) > REF_MAX_SEGMENTS:
        raise ValueError("deeper than a reference can go")
    return "".join(out)


def format_ref(node_id: str, field: str, path=()) -> str:
    """The reference the picker inserts: `{{ steps.<node_id>.<field><path> }}`.
    Raises `ValueError` for anything a reference cannot name, and parses what
    it writes back, so the picker can never insert text the save refuses."""
    if (not isinstance(node_id, str) or not NODE_ID_RE.fullmatch(node_id)
            or len(node_id) > NODE_ID_MAX):
        raise ValueError(f"not a step id: {node_id!r}")
    if field not in REF_FIELDS:
        raise ValueError(f"not a field: {field!r}")
    text = f"{{{{ {REF_ROOT_STEPS}.{node_id}.{field}{_format_path(path)} }}}}"
    parse_template(text)
    return text


# ── What a value holds, for the picker ───────────────────────────────────────

FIELD_TYPE_TEXT = "text"
FIELD_TYPE_NUMBER = "number"
FIELD_TYPE_YES_NO = "yes/no"
FIELD_TYPE_LIST = "list"
FIELD_TYPE_OBJECT = "object"
FIELD_TYPE_EMPTY = "empty"
EXAMPLE_MAX_CHARS = 80


def field_type(value) -> str:
    """The word for what a value is: `answer_fields`' words, plus object and
    empty."""
    if value is None or value is MISSING:
        return FIELD_TYPE_EMPTY
    if isinstance(value, bool):
        return FIELD_TYPE_YES_NO
    if isinstance(value, (int, float)):
        return FIELD_TYPE_NUMBER
    if isinstance(value, str):
        return FIELD_TYPE_TEXT
    if isinstance(value, list):
        return FIELD_TYPE_LIST
    return FIELD_TYPE_OBJECT


def _example(value) -> str:
    if isinstance(value, (list, dict)):
        text = f"{len(value)} item{'s' if len(value) != 1 else ''}" if isinstance(value, list) \
            else f"{len(value)} field{'s' if len(value) != 1 else ''}"
    else:
        text = as_text(value)
    text = " ".join(text.split())
    return text if len(text) <= EXAMPLE_MAX_CHARS else text[:EXAMPLE_MAX_CHARS - 1] + "…"


def _nameable(key) -> bool:
    try:
        _format_path((key,))
    except ValueError:
        return False
    return True


def flatten_fields(value, max_depth: int = 4, max_fields: int = 200) -> list:
    """`[{path, type, example}]` — every field in `value` a reference can name,
    the whole value first (`path` `[]`), breadth first, at most `max_depth`
    levels and `max_fields` entries. `path` is a list of segments for
    `format_ref`; a list is described by its first item (`[0]`). A key no
    reference can name is left out rather than offered and then refused."""
    value = _json_copy(value)
    out = [{"path": [], "type": field_type(value), "example": _example(value)}]
    frontier = [((), value)]
    depth = 0
    while frontier and depth < max_depth and len(out) < max_fields:
        depth += 1
        following = []
        for path, node in frontier:
            if isinstance(node, dict):
                children = [(k, v) for k, v in node.items() if _nameable(k)]
            elif isinstance(node, list) and node:
                children = [(0, node[0])]
            else:
                children = []
            for key, child in children:
                if len(out) >= max_fields:
                    break
                child_path = (*path, key)
                out.append({"path": list(child_path), "type": field_type(child),
                            "example": _example(child)})
                following.append((child_path, child))
        frontier = following
    return out
