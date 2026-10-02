# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-10` — decide and reshape: If, Switch, Set. Pure, and no language.

`D-2026-10-01-05` §2: data moves by picking a field, with simple logic — a
closed list of six operators and two ways to join them, evaluated with no model
and no expression language. A condition is three settings a person picks or
types — a field (`left`), an operator (`op`), a value (`right`) — and nothing
in it is ever run as code. The semantics are written once, here:

  * **text** compares trimmed and without regard to case;
  * **numbers** compare as numbers, numeric text included ("12" equals 12.0);
  * **yes/no** equals `true`/`false`/`yes`/`no` written as text;
  * `greater_than` and `less_than` also order ISO dates and times;
  * `contains` is a substring of text, a member of a list, a key of an object;
  * `is_empty` is null, a missing field, blank text, `[]` and `{}`;
  * `one_of` takes a list, or text split on commas and new lines;
  * a type mismatch is false, and **no operator ever raises**.

If and Switch have no error port: a condition cannot fail, it can only be
false. Switch takes the FIRST case that matches, else `otherwise`.

`Accepted residual (SLICE-CD-DESIGN § 1.6, said aloud)`: routing on content
lets whoever wrote the content choose which of the AUTHOR'S branches runs.
That is what routing on content means; the branches are the author's.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

from src.workflow_refs import (
    MISSING,
    RefError,
    as_text,
    parse_template,
    render_value,
)

# ── Stored words (`FORBIDDEN.md` Part 1 at the merge) ────────────────────────
OP_EQUALS = "equals"
OP_CONTAINS = "contains"
OP_IS_EMPTY = "is_empty"
OP_GREATER_THAN = "greater_than"
OP_LESS_THAN = "less_than"
OP_ONE_OF = "one_of"
OPERATORS = (OP_EQUALS, OP_CONTAINS, OP_IS_EMPTY, OP_GREATER_THAN, OP_LESS_THAN, OP_ONE_OF)
JOIN_ALL = "all"
JOIN_ANY = "any"
JOINS = (JOIN_ALL, JOIN_ANY)
# The words the editor's select shows, one per operator — the palette ships
# them (`GET /api/workflows/palette` → `operators: [{op, word}]`).
OPERATOR_WORDS = {
    OP_EQUALS: "is",
    OP_CONTAINS: "contains",
    OP_IS_EMPTY: "is empty",
    OP_GREATER_THAN: "is more than",
    OP_LESS_THAN: "is less than",
    OP_ONE_OF: "is one of",
}
JOIN_WORDS = {JOIN_ALL: "all of these", JOIN_ANY: "any of these"}
# Operators that read no `right`.
UNARY_OPERATORS = (OP_IS_EMPTY,)

_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_WHOLE_RE = re.compile(r"[+-]?[0-9]+")
_YES = frozenset({"true", "yes"})
_NO = frozenset({"false", "no"})
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


# ── One comparison ───────────────────────────────────────────────────────────

def _number(value):
    """A number, numeric text as a number, or `None`. A whole number stays an
    `int` — Python compares an int with a float exactly, so a 400-digit
    integer in a webhook body orders correctly instead of overflowing
    `float()`."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if value == value else None  # NaN is not a number here
    if isinstance(value, str):
        text = value.strip()
        try:
            if _WHOLE_RE.fullmatch(text):
                return int(text)
            if _NUMBER_RE.fullmatch(text):
                return float(text)
        except ValueError:  # more digits than Python will read as an int
            return None
    return None


def _moment(value):
    """An ISO date or date-time as an aware UTC datetime, or `None`. A date is
    its midnight; a time with no zone is read as UTC."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _ISO_DATE.match(text):
        return None
    try:
        if len(text) == 10:
            d = date.fromisoformat(text)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        moment = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _fold(text: str) -> str:
    return text.strip().casefold()


def _equals(left, right) -> bool:
    if left is MISSING or right is MISSING:
        return False
    a, b = _number(left), _number(right)
    if a is not None and b is not None:
        return a == b
    if isinstance(left, bool) or isinstance(right, bool):
        if isinstance(left, bool) and isinstance(right, bool):
            return left == right
        flag, text = (left, right) if isinstance(left, bool) else (right, left)
        if isinstance(text, str):
            word = _fold(text)
            return (word in _YES) if flag else (word in _NO)
        return False
    if isinstance(left, str) and isinstance(right, str):
        return _fold(left) == _fold(right)
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (list, dict)) and type(left) is type(right):
        return left == right
    return False


def _contains(left, right) -> bool:
    if left is MISSING or right is MISSING or right is None:
        return False
    if isinstance(left, str):
        needle = _fold(as_text(right))
        # "contains nothing" is not a test anyone means: a blank value never
        # matches, rather than routing everything one way.
        return bool(needle) and needle in left.casefold()
    if isinstance(left, list):
        return any(_equals(item, right) for item in left)
    if isinstance(left, dict):
        if not isinstance(right, str) or not right.strip():
            return False
        return any(isinstance(k, str) and _fold(k) == _fold(right) for k in left)
    return False


def _is_empty(left) -> bool:
    if left is MISSING or left is None:
        return True
    if isinstance(left, str):
        return not left.strip()
    if isinstance(left, (list, dict)):
        return len(left) == 0
    return False


def _order(left, right):
    """`(a, b)` comparable as numbers or as moments, or `None`."""
    a, b = _number(left), _number(right)
    if a is not None and b is not None:
        return a, b
    a, b = _moment(left), _moment(right)
    if a is not None and b is not None:
        return a, b
    return None


def _choices(right) -> list:
    if isinstance(right, list):
        return right
    if isinstance(right, str):
        return [part.strip() for part in re.split(r"[,\n]", right) if part.strip()]
    return [] if right is None or right is MISSING else [right]


def compare(op: str, left, right=None) -> bool:
    """Does `left op right` hold? Never raises; an unknown operator is false."""
    try:
        if op == OP_EQUALS:
            return _equals(left, right)
        if op == OP_CONTAINS:
            return _contains(left, right)
        if op == OP_IS_EMPTY:
            return _is_empty(left)
        if op in (OP_GREATER_THAN, OP_LESS_THAN):
            pair = _order(left, right)
            if pair is None:
                return False
            return pair[0] > pair[1] if op == OP_GREATER_THAN else pair[0] < pair[1]
        if op == OP_ONE_OF:
            if left is MISSING:
                return False
            return any(_equals(left, choice) for choice in _choices(right))
    except Exception:  # noqa: BLE001 - "operators never throw" is the contract
        return False
    return False


# ── A condition, a group, a step ─────────────────────────────────────────────

def operand(value, ctx):
    """A condition's `left` or `right` as the value it compares: text is a
    template (a field picked, or typed text, or both) rendered against `ctx`
    — a template that is one reference is that field's raw value; a list's
    texts each likewise; a number, yes/no or null is itself."""
    if isinstance(value, str):
        try:
            template = parse_template(value)
        except RefError:
            return MISSING
        rendered, missing = render_value(template, ctx)
        if template.single is not None and missing:
            # A field that is not there is MISSING — empty, and equal to
            # nothing — which a real `null` is not.
            return MISSING
        return rendered
    if isinstance(value, list):
        return [operand(item, ctx) for item in value]
    if isinstance(value, dict):
        return json.loads(json.dumps(value, default=str))
    return value


def evaluate_condition(condition: dict, ctx) -> bool:
    """One `{left, op, right}`, against `ctx` (`workflow_refs.build_context`)."""
    if not isinstance(condition, dict):
        return False
    op = condition.get("op")
    if op not in OPERATORS:
        return False
    left = operand(condition.get("left"), ctx)
    right = None if op in UNARY_OPERATORS else operand(condition.get("right"), ctx)
    return compare(op, left, right)


def evaluate_group(conditions, join: str | None, ctx) -> bool:
    """`all` (the default) or `any` of `conditions`. An empty group is false:
    a branch nobody gave a test is never taken by accident."""
    conditions = [c for c in (conditions or ()) if isinstance(c, dict)]
    if not conditions:
        return False
    results = (evaluate_condition(c, ctx) for c in conditions)
    return any(results) if join == JOIN_ANY else all(results)


PORT_THEN = "then"
PORT_OTHERWISE = "otherwise"
CASE_PORT_PREFIX = "case:"


def case_port(case_id: str) -> str:
    return f"{CASE_PORT_PREFIX}{case_id}"


def choose_port(node: dict, ctx) -> str:
    """The port an If or Switch step leaves by: If → `then` / `otherwise`;
    Switch → `case:<id>` of the first case that matches, else `otherwise`."""
    kind = node.get("kind")
    config = node.get("config") or {}
    if kind == "if":
        return PORT_THEN if evaluate_group(config.get("conditions"), config.get("join"), ctx) \
            else PORT_OTHERWISE
    if kind == "switch":
        for case in config.get("cases") or ():
            if isinstance(case, dict) and evaluate_group(case.get("conditions"),
                                                         case.get("join"), ctx):
                return case_port(case.get("id"))
        return PORT_OTHERWISE
    raise ValueError(f"a {kind!r} step does not choose a way")


def build_set(node: dict, ctx) -> tuple:
    """`(data, missing)` — a Set step's object: each field's name (typed by the
    author) and its value, a picked field's raw value or typed text rendered,
    a typed number or yes/no as itself. `missing` the references that reached
    nothing; their fields are `null`."""
    data = {}
    missing = []
    for field in (node.get("config") or {}).get("fields") or ():
        if not isinstance(field, dict) or not isinstance(field.get("name"), str):
            continue
        value = field.get("value")
        if isinstance(value, str):
            rendered, miss = render_value(parse_template(value), ctx)
            missing.extend(miss)
            data[field["name"]] = rendered
        else:
            data[field["name"]] = json.loads(json.dumps(value, default=str))
    return data, tuple(dict.fromkeys(missing))


def describe_condition(condition: dict) -> str:
    """A condition in words, references shown as written — for the dry run's
    plan, which never shows a value (`workflow_document.plan_lines`)."""
    if not isinstance(condition, dict):
        return "(not a condition)"
    op = condition.get("op")
    left = as_text(condition.get("left")) or "(nothing)"
    if op in UNARY_OPERATORS:
        return f"{left} {OPERATOR_WORDS.get(op, op)}"
    right = condition.get("right")
    right = ", ".join(as_text(r) for r in right) if isinstance(right, list) else as_text(right)
    return f"{left} {OPERATOR_WORDS.get(op, op)} “{right}”"
