# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-09` — a reference reads a field, and nothing else. Pure.

`D-2026-10-01-05` §2: data moves between a workflow's steps by picking a field
from a list, never by writing code. What the picker inserts is a reference,

    {{ steps.<step id>.data.<path> }}     what a step made, as data
    {{ steps.<step id>.text }}            what a step said, as text
    {{ steps.start.data.<path> }}         what the trigger handed the workflow
    {{ item.<path> }}                     the item, inside a For-each step

and this module is the only thing that reads one (`Law 7`): the save route, the
walker at run, the dry run, the picker and `workflow_slots.render_call` all ask
it. The grammar (`SLICE-CD-DESIGN` § 1.1):

    ref   := "{{" ws* path ws* "}}"
    path  := "steps" "." NODE "." FIELD seg*  |  "item" seg*
    FIELD := "data" | "text"
    seg   := "." KEY | "[" INDEX "]" | "[" '"' QKEY '"' "]"
    KEY   := [A-Za-z_][A-Za-z0-9_]{0,63}    INDEX := 0|[1-9][0-9]{0,5}
    QKEY  := 1-128 characters, no '"', no '\\', no control character
    "\\{{" is the literal text "{{"

**No calls, no arithmetic, no filters, no negative indexes, no slices** — a
reference names a place and nothing else, so there is no language here for a
hostile value to speak. Every character class is spelled out in ASCII
(`[A-Za-z]`, never `\\w` or `str.isalpha`), so a fullwidth `｛｛`, a Cyrillic
letter or a Unicode space is not part of a reference: it is text.

**What a reference can reach.** The context is JSON — `build_context` round-
trips it — so resolution only ever meets dict, list, str, number, bool and
None. A dict is looked up by exact key (`type(x) is dict`, so no mapping whose
lookup runs code), a list by an in-range integer (a bool is not an index), and
anything else is `MISSING`. There is no attribute access anywhere, so nothing
on a Python object can be reached.

**One pass.** `parse_template` splits the text into literal parts and
references once; `render_text` joins the resolved values in as opaque text and
never scans them again. Outside data that contains `{{ steps.x.data.secret }}`
arrives as those characters, and nothing it names is read (`Law 17`: the
adversary is whoever writes an inbound mail or webhook body).
"""

from __future__ import annotations

import json
import re
from typing import NamedTuple

# ── The words ────────────────────────────────────────────────────────────────

REF_ROOT_STEPS = "steps"
REF_ROOT_ITEM = "item"
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
REF_ERROR_REASONS = {
    REF_SYNTAX: "is not a reference",
    REF_TOO_LONG: f"is longer than {TEMPLATE_MAX_CHARS:,} characters, which is as long as text "
                  f"with references can be",
    REF_TOO_MANY: f"has more than {TEMPLATE_MAX_REFS} references",
    REF_TOO_DEEP: f"goes more than {REF_MAX_SEGMENTS} levels deep",
    REF_BAD_INDEX: "has a position that is not a whole number up to 999999",
    REF_BAD_KEY: "has a field name that cannot be read",
}
_HOW = ("A reference reads {{ steps.<step>.data.<field> }}; write \\{{ for the "
        "text “{{”.")


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
    snippet = text[at:at + 60]
    close = snippet.find("}}")
    if close >= 0:
        snippet = snippet[:close + 2]
    elif len(text) > at + 60:
        snippet += "…"
    if reason == REF_TOO_LONG or reason == REF_TOO_MANY:
        sentence = f"The text {REF_ERROR_REASONS[reason]}."
    else:
        sentence = f"“{snippet}” {REF_ERROR_REASONS[reason]}. {_HOW}"
    return RefError(reason, at, sentence)


class Ref(NamedTuple):
    """One reference. `root` is `steps` or `item`; `node` and `field` are set
    for `steps` and `None` for `item`; `path` the segments after them — `str`
    keys and `int` positions; `text` the reference exactly as written."""
    root: str
    node: str | None
    field: str | None
    path: tuple
    text: str


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


def _parse_ref_at(text: str, at: int) -> tuple:
    """`(Ref, end)` for the reference whose `{{` starts at `at`, or raises
    `RefError`. `end` is the offset just past its `}}`."""
    i = _skip_ws(text, at + 2)
    node = field = None
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
    i = _skip_ws(text, i)
    if not text.startswith("}}", i):
        raise _error(REF_SYNTAX, text, at)
    end = i + 2
    return Ref(root, node, field, tuple(path), text[at:end]), end


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


def build_context(steps: dict | None = None, item=MISSING) -> dict:
    """The context references resolve against, normalised by a JSON round trip.

    `steps` maps a step id (or `START_NODE`, the trigger) to `{data, text,
    status}`; `item` is the For-each item, left out when there is none."""
    ctx = {"steps": steps or {}}
    if item is not MISSING:
        ctx["item"] = item
    return _json_copy(ctx)


def resolve(ref: Ref, ctx) -> object:
    """What `ref` reads in `ctx`, or `MISSING`. Never raises, never calls."""
    if type(ctx) is not dict:
        return MISSING
    if ref.root == REF_ROOT_ITEM:
        cur = ctx["item"] if "item" in ctx else MISSING
    elif ref.root == REF_ROOT_STEPS:
        steps = ctx.get("steps")
        if type(steps) is not dict or type(ref.node) is not str or ref.node not in steps:
            return MISSING
        entry = steps[ref.node]
        if type(entry) is not dict or ref.field not in REF_FIELDS or ref.field not in entry:
            return MISSING
        cur = entry[ref.field]
    else:
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


def render_text(t: Template, ctx) -> tuple:
    """`(text, missing)` — `t` with every reference replaced by its value as
    text, in one pass; `missing` the references that reached nothing."""
    out = []
    missing = []
    for part in t.parts:
        if isinstance(part, Ref):
            value = resolve(part, ctx)
            if value is MISSING:
                missing.append(part.text)
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
        return None, (one.text,)
    return value, ()


_SLOT_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def _slot_name(ref: Ref) -> str:
    keys = [s for s in ref.path if isinstance(s, str)]
    if keys:
        last_key = max(i for i, s in enumerate(ref.path) if isinstance(s, str))
        tail = [str(s) for s in ref.path[last_key + 1:]]
        name = "_".join([keys[-1], *tail])
    elif ref.root == REF_ROOT_ITEM:
        name = "_".join([REF_ROOT_ITEM, *(str(s) for s in ref.path)])
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
        key = (part.root, part.node, part.field, part.path)
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


def format_item_ref(path=()) -> str:
    """`{{ item<path> }}`, for the step inside a For-each."""
    text = f"{{{{ {REF_ROOT_ITEM}{_format_path(path)} }}}}"
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
