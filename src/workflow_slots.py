# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-09` / `P22-17` — may outside data fill this slot? The one place that
answers (`Law 7`). Pure.

`D-2026-10-01-05` §4: a step the author configured runs without a card when
outside data fills only its `value` slots; destination, command, recipient, URL
and host slots can never be mapped. **The adversary (`Law 17`)** is whoever
writes an inbound mail or webhook body, and through a model's output whoever
steered it: their bytes may reach a `value` slot; they must never choose the
tool, the destination, a recipient, a URL, a host or a command.

So every setting of every kind of step declares `value` or `never`, here:

  * `NODE_SLOTS[kind][field]` — the static fields (`SLICE-CD-DESIGN` § 2's
    table). A field nobody declared is `never` (`slot_for` fails closed).
  * an action's parameter declares its own mapping on the parameter
    (`builtin_actions._prompt_param(..., mapping=MAPPING_NEVER)`), read by
    `action_param_slots`; an action prompt with no declared parameter (the
    email actions' account JSON) is `never`.
  * an MCP argument or an HTTP query/body key is classified by
    `classify_argument` against an **allowlist** of words that only ever name
    text a person reads — anything else is `never`. Names are written by the
    author (HTTP) or the server's schema (MCP), never by outside data, so
    classifying on a name is classifying on trusted input.

The save routes, the walker at run, the dry run and the palette all ask this
module; the browser is handed its answers and derives nothing.

`render_call` builds a deterministic step's call as a dict and `json.dumps` it,
so a filled value is a dict value and can never become JSON structure; a
`never` slot is copied verbatim, and a reference found in one raises
`SlotError` — defence in depth for a document written straight to the
database, after the save already refused it.
"""

from __future__ import annotations

import json
import re
from typing import NamedTuple

from src.workflow_refs import (
    MISSING,
    RefError,
    as_text,
    parse_template,
    references_in_text,
    render_text,
    render_value,
)

# ── Stored words (`FORBIDDEN.md` Part 1 at the merge) ────────────────────────
MAPPING_VALUE = "value"
MAPPING_NEVER = "never"
MAPPINGS = (MAPPING_VALUE, MAPPING_NEVER)

# How a `value` reaches what uses it. INLINE: it becomes part of a
# deterministic call (an HTTP body, an MCP argument, a Set field, a condition,
# Code's stdin). CONTEXT: it reaches a model only inside the untrusted-context
# block, never spliced into the prompt (`render_named_slots`).
CARRY_INLINE = "inline"
CARRY_CONTEXT = "context"
CARRIES = (CARRY_INLINE, CARRY_CONTEXT)

# The sentence a `never` field shows, one per category (§ 1.2), plus the
# classifier's: it cannot say WHICH of the three a name it does not know is,
# only that it is not on the list of words for text a person reads (`Law 10`).
WHY_WHERE = ("This says where the step's work goes, so it only takes what you type "
             "here, never a value from another step.")
WHY_WHAT = ("This decides what the step does, so it only takes what you type here, "
            "never a value from another step.")
WHY_WHEN = ("This decides when the step runs, so it only takes what you type here, "
            "never a value from another step.")
WHY_NOT_TEXT = ("Only words a person reads can come from another step. This could be "
                "an address, a name or a command, so it only takes what you type here.")
WHYS = (WHY_WHERE, WHY_WHAT, WHY_WHEN, WHY_NOT_TEXT)


class Slot(NamedTuple):
    """What a setting may be filled with. `mapping` is a `MAPPINGS` word,
    `carry` a `CARRIES` word for a `value` slot and `None` for `never`, `why`
    the sentence a `never` field shows (empty for `value`)."""
    mapping: str
    carry: str | None
    why: str


VALUE_CONTEXT = Slot(MAPPING_VALUE, CARRY_CONTEXT, "")
VALUE_INLINE = Slot(MAPPING_VALUE, CARRY_INLINE, "")
NEVER_WHERE = Slot(MAPPING_NEVER, None, WHY_WHERE)
NEVER_WHAT = Slot(MAPPING_NEVER, None, WHY_WHAT)
NEVER_WHEN = Slot(MAPPING_NEVER, None, WHY_WHEN)
NEVER_NOT_TEXT = Slot(MAPPING_NEVER, None, WHY_NOT_TEXT)
# A setting no table names. Fail closed.
UNDECLARED = NEVER_WHAT


class _Rule(NamedTuple):
    """A field whose slot is decided per entry rather than by the table."""
    name: str


# `query[i].value` / `body[i].value`: classified by `query[i].name`.
BY_ENTRY_NAME = _Rule("by_entry_name")
# `args.<name>`: classified by the name against the MCP tool's input schema.
BY_SCHEMA = _Rule("by_schema")
# An action's `prompt`: the declaration on the action's parameter.
BY_PARAM = _Rule("by_param")
# A For-each's `step.config`: the inner step's own kind's slots.
INNER = _Rule("inner")

# ── The table (`SLICE-CD-DESIGN` § 2) ───────────────────────────────────────
#
# Keys are field patterns: `.` between keys, `[]` for any position in a list,
# `*` for any key of a map. A path is answered by the LONGEST declared pattern
# that is a prefix of it, so `answer_fields` covers every key inside it.
_LLM = {
    "prompt": VALUE_CONTEXT,
    "model": NEVER_WHAT,
    "endpoint_url": NEVER_WHERE,
    "character_id": NEVER_WHAT,
    "crew_member_id": NEVER_WHAT,
    "max_steps": NEVER_WHAT,
    "output_target": NEVER_WHERE,
    "tools": NEVER_WHAT,
    "answer_fields": NEVER_WHAT,
}
_CONDITION = {
    "left": VALUE_INLINE,
    "right": VALUE_INLINE,
    "op": NEVER_WHAT,
}
NODE_SLOTS = {
    "llm": _LLM,
    "research": {
        "prompt": VALUE_INLINE,
        "model": NEVER_WHAT,
        "endpoint_url": NEVER_WHERE,
        "output_target": NEVER_WHERE,
    },
    "action": {
        "action": NEVER_WHAT,
        "prompt": BY_PARAM,
        "output_target": NEVER_WHERE,
    },
    "run_task": {
        "task_id": NEVER_WHAT,
    },
    "if": {
        "conditions": NEVER_WHAT,
        **{f"conditions[].{k}": v for k, v in _CONDITION.items()},
        "join": NEVER_WHAT,
    },
    "switch": {
        "cases": NEVER_WHAT,
        "cases[].id": NEVER_WHAT,
        "cases[].label": NEVER_WHAT,
        "cases[].join": NEVER_WHAT,
        "cases[].conditions": NEVER_WHAT,
        **{f"cases[].conditions[].{k}": v for k, v in _CONDITION.items()},
    },
    "set": {
        "fields": NEVER_WHAT,
        "fields[].name": NEVER_WHAT,
        "fields[].value": VALUE_INLINE,
    },
    "merge": {
        "mode": NEVER_WHAT,
    },
    "wait": {
        "mode": NEVER_WHEN,
        "minutes": NEVER_WHEN,
        "time": NEVER_WHEN,
        "tz": NEVER_WHEN,
    },
    "foreach": {
        "list": VALUE_INLINE,
        "on_error": NEVER_WHAT,
        "step": NEVER_WHAT,
        "step.config": INNER,
    },
    "http": {
        "integration": NEVER_WHERE,
        "method": NEVER_WHERE,
        "path": NEVER_WHERE,
        "headers": NEVER_WHERE,
        "query": NEVER_WHERE,
        "query[].name": NEVER_WHERE,
        "query[].value": BY_ENTRY_NAME,
        "body": NEVER_WHERE,
        "body[].name": NEVER_WHERE,
        "body[].value": BY_ENTRY_NAME,
        "body_mode": NEVER_WHAT,
    },
    "mcp": {
        "tool": NEVER_WHAT,
        "args": NEVER_NOT_TEXT,
        "args.*": BY_SCHEMA,
    },
    "skill": {
        "skill": NEVER_WHAT,
        "prompt": VALUE_CONTEXT,
        "model": NEVER_WHAT,
        "endpoint_url": NEVER_WHERE,
        "max_steps": NEVER_WHAT,
        "output_target": NEVER_WHERE,
    },
    "code": {
        "language": NEVER_WHAT,
        "source": NEVER_WHAT,
        "timeout_seconds": NEVER_WHEN,
        "input": NEVER_WHAT,
        "input[].name": NEVER_WHAT,
        "input[].value": VALUE_INLINE,
    },
}


def _pattern(text: str) -> tuple:
    """`"cases[].conditions[].left"` → `("cases", "[]", "conditions", "[]", "left")`."""
    out = []
    for key in text.split("."):
        lists = 0
        while key.endswith("[]"):
            key = key[:-2]
            lists += 1
        if key:
            out.append(key)
        out.extend(["[]"] * lists)
    return tuple(out)


_PATTERNS = {kind: sorted(((_pattern(p), rule) for p, rule in table.items()),
                          key=lambda pr: -len(pr[0]))
             for kind, table in NODE_SLOTS.items()}


def declared_fields(kind: str) -> frozenset:
    """The top-level settings `NODE_SLOTS` declares for `kind`."""
    return frozenset(p[0] for p, _ in _PATTERNS.get(kind, ()))


def _matches(pattern: tuple, path: tuple) -> bool:
    if len(pattern) > len(path):
        return False
    for want, got in zip(pattern, path):
        if want == "[]":
            if type(got) is not int:
                return False
        elif want == "*":
            if type(got) is not str:
                return False
        elif want != got:
            return False
    return True


# ── Action parameters ────────────────────────────────────────────────────────

def action_param_slots(action: str | None) -> dict:
    """`{param name: Slot}` for a built-in action, read off the parameter's own
    `mapping` (`builtin_actions._prompt_param`). A parameter that declares no
    mapping, or declares a word that is not one, is `never` (fail closed)."""
    from src.builtin_actions import BUILTIN_ACTION_META

    out = {}
    for param in (BUILTIN_ACTION_META.get(action or "") or {}).get("params") or ():
        mapping = param.get("mapping")
        out[param.get("name")] = (VALUE_INLINE if mapping == MAPPING_VALUE else NEVER_WHAT)
    return out


def _action_prompt_slot(action: str | None) -> Slot:
    from src.builtin_actions import BUILTIN_ACTION_META

    params = [p for p in (BUILTIN_ACTION_META.get(action or "") or {}).get("params") or ()
              if p.get("source") == "prompt"]
    if len(params) != 1:
        # No declared parameter (the email actions read account JSON out of
        # `prompt`), or more than one sharing it: never.
        return NEVER_WHAT
    return action_param_slots(action).get(params[0].get("name"), NEVER_WHAT)


# ── The classifier ───────────────────────────────────────────────────────────
#
# An ALLOWLIST. A name is split on snake, kebab and camel boundaries and EVERY
# part must be one of these words; a name with any other character, an empty
# part, a digit or a word not here is `never`. So `to`, `chat_id`, `channel`,
# `url`, `host`, `path`, `command`, `query`, `action`, `id` — and every name
# nobody thought of — are `never` without being listed (§ 5.2 holds that by
# fuzzing). Only the words below can carry outside data.
CONTENT_WORDS = frozenset({
    "text", "message", "msg", "body", "content", "subject", "title", "summary",
    "description", "details", "note", "notes", "comment", "caption", "reply",
    "answer", "markdown", "html",
})
FORMAT_WORDS = frozenset({"text", "html", "markdown", "md", "plain"})
ARGUMENT_WORDS = CONTENT_WORDS | FORMAT_WORDS
ARGUMENT_TYPES = ("string", "number", "integer", "boolean")
# A string `format` that names an address — a destination, however the name
# reads. Any OTHER format is `never` too (fail closed); these are the ones that
# get the "where it goes" sentence.
ADDRESS_FORMATS = frozenset({
    "uri", "uri-reference", "iri", "iri-reference", "email", "idn-email",
    "hostname", "idn-hostname", "ipv4", "ipv6", "uri-template",
})
_NAME_CHARS = re.compile(r"[A-Za-z0-9_-]{1,64}")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
# The schema a key with no schema is read as: an HTTP query or body value is
# text in the request.
TEXT_SCHEMA = {"type": "string"}


def name_parts(name) -> tuple:
    """`name` split on `_`, `-` and camel-case boundaries, lower-cased — or
    `()` for anything that is not plain ASCII letters, digits, `_` and `-`."""
    if not isinstance(name, str) or not _NAME_CHARS.fullmatch(name):
        return ()
    parts = []
    for chunk in re.split(r"[_-]+", name):
        if not chunk:
            continue
        pieces = _CAMEL.findall(chunk)
        if "".join(pieces) != chunk:
            return ()
        parts.extend(p.lower() for p in pieces)
    return tuple(parts)


def _schema_types(schema) -> tuple:
    kind = schema.get("type")
    if isinstance(kind, str):
        return (kind,)
    if isinstance(kind, list) and all(isinstance(k, str) for k in kind):
        return tuple(kind)
    return ()


def classify_argument(name, schema) -> Slot:
    """May outside data fill the argument `name`, whose JSON schema is
    `schema`? Fails closed: `value` only when every part of the name is in
    `ARGUMENT_WORDS`, the type is text, a number or a yes/no, and the schema
    names no `format`. Everything else is `never` — any object, any list, any
    address format, any schema that is missing or not an object."""
    parts = name_parts(name)
    if not parts or any(p not in ARGUMENT_WORDS for p in parts):
        return NEVER_NOT_TEXT
    if not isinstance(schema, dict):
        return NEVER_NOT_TEXT
    types = [t for t in _schema_types(schema) if t != "null"]
    if not types or any(t not in ARGUMENT_TYPES for t in types):
        return NEVER_NOT_TEXT
    fmt = schema.get("format")
    if fmt is not None:
        return NEVER_WHERE if fmt in ADDRESS_FORMATS else NEVER_NOT_TEXT
    return VALUE_INLINE


# ── Which slot a setting is ──────────────────────────────────────────────────

def _entry_name(config: dict, path: tuple):
    try:
        return config[path[0]][path[1]]["name"]
    except (KeyError, IndexError, TypeError):
        return None


def slot_for(node: dict, path, *, mcp_schema=None) -> Slot:
    """The `Slot` for the setting at `path` (a tuple of keys and positions
    under `config`) in `node`. A path the table does not declare is `never`.
    `mcp_schema` is an MCP step's tool `input_schema`; without it every
    argument is `never`."""
    path = tuple(path)
    kind = node.get("kind") if isinstance(node, dict) else None
    config = (node.get("config") if isinstance(node, dict) else None) or {}
    if not path:
        return UNDECLARED
    for pattern, rule in _PATTERNS.get(kind, ()):
        if not _matches(pattern, path):
            continue
        if isinstance(rule, Slot):
            return rule
        if rule is BY_PARAM:
            return _action_prompt_slot(config.get("action") if isinstance(config, dict) else None)
        if rule is BY_ENTRY_NAME:
            return classify_argument(_entry_name(config, path), TEXT_SCHEMA)
        if rule is BY_SCHEMA:
            props = mcp_schema.get("properties") if isinstance(mcp_schema, dict) else None
            prop = props.get(path[1]) if isinstance(props, dict) else None
            return classify_argument(path[1], prop)
        if rule is INNER:
            inner = config.get("step") if isinstance(config, dict) else None
            if not isinstance(inner, dict) or inner.get("kind") == "foreach":
                return UNDECLARED
            return slot_for(inner, path[len(pattern):], mcp_schema=mcp_schema)
        return UNDECLARED
    return UNDECLARED


def path_text(path) -> str:
    """`("conditions", 0, "left")` → `conditions[0].left` — the `field` a
    refusal names, so the panel can put the sentence on that field."""
    out = ""
    for seg in path:
        if type(seg) is int:
            out += f"[{seg}]"
        else:
            out += f".{seg}" if out else str(seg)
    return out


def config_leaves(value, path=()):
    """`(path, text)` for every text inside a step's settings, in order."""
    if isinstance(value, str):
        yield tuple(path), value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from config_leaves(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from config_leaves(item, (*path, index))


# ── A deterministic step's call (`P22-17`, the Run half) ────────────────────

SLOT_MAX_CHARS = 20_000
CALL_MAX_BYTES = 64 * 1024
CALL_KINDS = ("http", "mcp", "code", "action")
API_CALL_TOOL = "api_call"


class SlotError(ValueError):
    """A call that may not be made as configured. `sentence` is what the step
    log says; `field` the setting it is about (`path_text`)."""

    def __init__(self, sentence: str, field: str = ""):
        super().__init__(sentence)
        self.sentence = sentence
        self.field = field


class RenderedCall(NamedTuple):
    """One deterministic step's call, built by `render_call` and nothing else
    (`tool_capabilities.authored_call_context` refuses any other type). `tool`
    is the tool name (`api_call`, `mcp__…`), the action key, or Code's
    language; `content` the exact text dispatched (for Code: the stdin JSON);
    `value_paths` the settings outside data filled; `missing` the references
    that reached nothing."""
    kind: str
    tool: str | None
    content: str
    value_paths: tuple
    missing: tuple


_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_YES = frozenset({"true", "yes"})
_NO = frozenset({"false", "no"})


def _coerce(value, schema, label: str):
    """`value` as the schema's type, or `SlotError`. Text is `as_text` (an
    object or list arrives as a JSON string, never as keys); a number or a
    yes/no must parse; an `enum` must hold it. `schema` `None` is Code's
    stdin, which is data handed to the author's own code, not a call's
    structure: the JSON value as it is."""
    if schema is None:
        return value
    types = [t for t in _schema_types(schema) if t != "null"] or ["string"]
    if value is None and "null" in _schema_types(schema):
        return None
    if "string" in types:
        out = as_text(value)
    elif "number" in types or "integer" in types:
        if isinstance(value, bool):
            out = None
        elif isinstance(value, (int, float)):
            out = value
        elif isinstance(value, str) and _NUMBER_RE.fullmatch(value.strip()):
            text = value.strip()
            out = float(text) if any(c in text for c in ".eE") else int(text)
        else:
            out = None
        if out is not None and "number" not in types:
            out = int(out) if float(out).is_integer() else None
        if out is None:
            raise SlotError(f"“{label}” needs a number, and it was handed "
                            f"“{as_text(value)[:40]}”.", label)
    elif "boolean" in types:
        if isinstance(value, bool):
            out = value
        elif isinstance(value, str) and value.strip().lower() in _YES | _NO:
            out = value.strip().lower() in _YES
        else:
            raise SlotError(f"“{label}” needs yes or no, and it was handed "
                            f"“{as_text(value)[:40]}”.", label)
    else:
        raise SlotError(f"“{label}” cannot take a value from another step.", label)
    enum = schema.get("enum") if isinstance(schema, dict) else None
    if isinstance(enum, list) and out not in enum:
        raise SlotError(f"“{label}” must be one of {', '.join(as_text(e) for e in enum[:8])}.",
                        label)
    return out


class _Renderer:
    def __init__(self, node: dict, ctx):
        self.node = node
        self.ctx = ctx
        self.value_paths = []
        self.missing = []

    def never(self, path: tuple, value):
        """A `never` slot: the author's value, verbatim — refused if anything
        in it reads as a reference."""
        for leaf_path, text in config_leaves(value, path):
            if references_in_text(text):
                raise SlotError(f"“{path_text(leaf_path)}” only takes what you typed, and it "
                                f"holds a reference, so nothing was sent.",
                                path_text(leaf_path))
        return json.loads(json.dumps(value)) if isinstance(value, (dict, list)) else value

    def fill(self, path: tuple, raw, schema):
        """A `value` slot: its references resolved in one pass, then coerced."""
        label = path_text(path)
        if isinstance(raw, str):
            try:
                template = parse_template(raw)
            except RefError as exc:
                raise SlotError(f"“{label}”: {exc.sentence}", label) from None
            if template.refs:
                self.value_paths.append(label)
            value, missing = render_value(template, self.ctx)
            self.missing.extend(missing)
        elif isinstance(raw, (dict, list)):
            value = self._fill_nested(path, raw)
        else:
            value = raw
        out = _coerce(value, schema, label)
        if isinstance(out, str) and len(out) > SLOT_MAX_CHARS:
            raise SlotError(f"“{label}” would be {len(out):,} characters; a step takes at "
                            f"most {SLOT_MAX_CHARS:,} in one setting.", label)
        return out

    def _fill_nested(self, path, raw):
        if isinstance(raw, dict):
            return {k: self._fill_nested((*path, k), v) for k, v in raw.items()}
        if isinstance(raw, list):
            return [self._fill_nested((*path, i), v) for i, v in enumerate(raw)]
        if isinstance(raw, str):
            try:
                template = parse_template(raw)
            except RefError as exc:
                raise SlotError(f"“{path_text(path)}”: {exc.sentence}", path_text(path)) from None
            if template.refs:
                self.value_paths.append(path_text(path))
            text, missing = render_text(template, self.ctx)
            self.missing.extend(missing)
            return text
        return raw

    def entries(self, key: str, *, schema_for_name):
        """An HTTP `query`/`body`, or Code's `input`: `[{name, value}]` → a
        dict, each value's slot decided by its name."""
        config = self.node.get("config") or {}
        out = {}
        for index, entry in enumerate(config.get(key) or ()):
            if not isinstance(entry, dict):
                raise SlotError(f"“{key}” has an entry that is not a name and a value.", key)
            name = self.never((key, index, "name"), entry.get("name"))
            if not isinstance(name, str) or not name:
                raise SlotError(f"“{key}” has an entry with no name.", key)
            slot = slot_for(self.node, (key, index, "value"))
            raw = entry.get("value")
            if slot.mapping == MAPPING_VALUE:
                out[name] = self.fill((key, index, "value"), raw, schema_for_name(name))
            else:
                out[name] = self.never((key, index, "value"), raw)
        return out


def render_call(node: dict, ctx, *, mcp_schema=None) -> RenderedCall:
    """The call a deterministic step (`CALL_KINDS`) makes, with its `value`
    slots filled from `ctx` (`workflow_refs.build_context`). Raises
    `SlotError` for anything that may not be sent — a reference in a `never`
    slot, a value of the wrong type, a slot or call over its cap.

    The call is a dict, dumped once: a value is a dict value and can never
    become JSON structure. `never` slots are the author's, verbatim."""
    kind = node.get("kind") if isinstance(node, dict) else None
    config = (node.get("config") if isinstance(node, dict) else None) or {}
    r = _Renderer(node, ctx)
    if kind == "http":
        call = {
            "integration": r.never(("integration",), config.get("integration")),
            "method": r.never(("method",), config.get("method") or "GET"),
            "path": r.never(("path",), config.get("path") or "/"),
        }
        headers = {}
        for index, entry in enumerate(config.get("headers") or ()):
            entry = r.never(("headers", index), entry)
            if isinstance(entry, dict) and entry.get("name"):
                headers[entry["name"]] = as_text(entry.get("value"))
        if headers:
            call["headers"] = headers
        params = r.entries("query", schema_for_name=lambda _n: TEXT_SCHEMA)
        if params:
            call["params"] = params
        r.never(("body_mode",), config.get("body_mode"))
        body = r.entries("body", schema_for_name=lambda _n: TEXT_SCHEMA)
        if body:
            call["body"] = body
        # `P22-13`: `do_api_call` hands the parsed body back as data.
        call["structured"] = True
        tool = API_CALL_TOOL
    elif kind == "mcp":
        tool = r.never(("tool",), config.get("tool"))
        if not isinstance(tool, str) or not tool:
            raise SlotError("The step names no tool.", "tool")
        props = mcp_schema.get("properties") if isinstance(mcp_schema, dict) else None
        props = props if isinstance(props, dict) else {}
        args = config.get("args") or {}
        if not isinstance(args, dict):
            raise SlotError("“args” is not a set of named arguments.", "args")
        call = {}
        for name, raw in args.items():
            slot = slot_for(node, ("args", name), mcp_schema=mcp_schema)
            if slot.mapping == MAPPING_VALUE:
                call[name] = r.fill(("args", name), raw, props.get(name))
            else:
                call[name] = r.never(("args", name), raw)
    elif kind == "code":
        for key in ("language", "source", "timeout_seconds"):
            r.never((key,), config.get(key))
        tool = config.get("language")
        call = r.entries("input", schema_for_name=lambda _n: None)
    elif kind == "action":
        tool = r.never(("action",), config.get("action"))
        r.never(("output_target",), config.get("output_target"))
        if slot_for(node, ("prompt",)).mapping == MAPPING_VALUE:
            prompt = r.fill(("prompt",), config.get("prompt"), TEXT_SCHEMA)
        else:
            prompt = r.never(("prompt",), config.get("prompt"))
        content = prompt if isinstance(prompt, str) else ""
        return RenderedCall("action", tool, content, tuple(dict.fromkeys(r.value_paths)),
                            tuple(dict.fromkeys(r.missing)))
    else:
        raise SlotError(f"A {kind!r} step does not make a call.", "")
    content = json.dumps(call, ensure_ascii=False)
    if len(content.encode("utf-8")) > CALL_MAX_BYTES:
        raise SlotError(f"The call would be larger than {CALL_MAX_BYTES // 1024} KiB.", "")
    return RenderedCall(kind, tool, content, tuple(dict.fromkeys(r.value_paths)),
                        tuple(dict.fromkeys(r.missing)))


__all__ = [
    "MAPPING_VALUE", "MAPPING_NEVER", "MAPPINGS", "CARRY_INLINE", "CARRY_CONTEXT",
    "CARRIES", "WHY_WHERE", "WHY_WHAT", "WHY_WHEN", "WHY_NOT_TEXT", "WHYS", "Slot",
    "NODE_SLOTS", "CONTENT_WORDS", "FORMAT_WORDS", "ARGUMENT_WORDS", "ADDRESS_FORMATS",
    "classify_argument", "action_param_slots", "slot_for", "declared_fields",
    "path_text", "config_leaves", "name_parts", "SlotError", "RenderedCall",
    "render_call", "SLOT_MAX_CHARS", "CALL_MAX_BYTES", "MISSING",
]
