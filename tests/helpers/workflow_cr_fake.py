# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract C-R (wf-rules), faked where it is absent — `P22-13` … `P22-18` (wf-effects).

`/work/notes/SLICE-CD-DESIGN.md` § 3 splits wave D into four packages that start
together. `src/workflow_effects.py` (wf-effects) consumes wf-rules' contract C-R:
`workflow_slots.RenderedCall` (`kind, tool, content, value_paths, missing`),
`render_call`, `NODE_SLOTS`, `classify_argument`, `Slot`, `workflow_refs.
flatten_fields`/`format_ref`, `workflow_document.ports_of`/`upstream_of`/
`WorkflowResources`, and `workflow_logic.OPERATORS`. None of it was on this
branch when these tests were written, so `install(monkeypatch)` puts a module
with exactly the contract's names into `sys.modules` **only when the real one
cannot be imported** — once wf-rules merges, every test here runs against the
real module and this file installs nothing.

Where the contract names a function and not its exact answer, the fake answers
the way § 1.1–1.2 of the design describe it, and the handoff note
(`/work/notes/wf-effects.md`) lists each such choice as a merge point:

  * ``render(kind, tool, payload)`` builds a call the way § 1.2 says
    `render_call` does — the call as a dict, then `json.dumps` — so a value is
    a JSON value and never JSON structure. It is NOT `render_call`: the tests
    that use it prove the EXECUTOR's half (it dispatches what it is handed,
    verbatim); `render_call`'s half is wf-rules' tests.

Nothing here is the product.
"""
import importlib
import json
import sys
import types
from typing import Any, NamedTuple


class RenderedCall(NamedTuple):
    """C-R's `RenderedCall(kind, tool, content, value_paths, missing)`."""
    kind: str
    tool: str
    content: str
    value_paths: tuple
    missing: tuple


def _real(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def install(monkeypatch) -> dict:
    """Install the fakes that are needed; answer `{module: "real"|"fake"}`.

    Each name is installed only where the real module does not have it, so a
    half-merged tree is driven against every real name it has.
    """
    said = {}
    slots = _real("src.workflow_slots")
    if slots is None:
        slots = types.ModuleType("src.workflow_slots")
        for name in _SLOTS_NAMES:
            setattr(slots, name, globals()[name])
        monkeypatch.setitem(sys.modules, "src.workflow_slots", slots)
        said["src.workflow_slots"] = "fake"
    else:
        said["src.workflow_slots"] = "real"
    for modname, fakes in (("src.workflow_refs", _REFS), ("src.workflow_logic", _LOGIC)):
        mod = _real(modname)
        if mod is None:
            mod = types.ModuleType(modname)
            for name, value in fakes.items():
                setattr(mod, name, value)
            monkeypatch.setitem(sys.modules, modname, mod)
            said[modname] = "fake"
        else:
            said[modname] = "real"
    # Modules that exist on this branch and gain names in wave D: wf-rules'
    # document rule and wf-walker's limit readers.
    for modname, fakes in (("src.workflow_document", _DOCUMENT), ("src.workflow_runs", _RUNS)):
        mod = importlib.import_module(modname)
        missing = {k: v for k, v in fakes.items() if not hasattr(mod, k)}
        if modname == "src.workflow_document" and "ports_of" in missing:
            missing["NODE_KINDS"] = NODE_KINDS        # Slice B's four, widened with the rest
        for name, value in missing.items():
            monkeypatch.setattr(mod, name, value, raising=False)
        said[modname] = "fake" if missing else "real"
    return said


def rendered_call_type():
    """The `RenderedCall` the executors will accept (the real one when present)."""
    return sys.modules["src.workflow_slots"].RenderedCall


def render(kind: str, tool: str, payload: Any, *, missing=()) -> Any:
    """A call as § 1.2 says `render_call` builds one: a dict, `json.dumps`ed."""
    return rendered_call_type()(kind, tool, json.dumps(payload), (), tuple(missing))


# ── The fakes, in the contract's names (§ 1.1–1.3 of the design) ─────────────

from typing import NamedTuple as _NT  # noqa: E402


class Slot(_NT):
    mapping: str
    carry: Any
    why: str


class _Rule(_NT):
    name: str


MAPPING_VALUE, MAPPING_NEVER = "value", "never"
WHY_WHERE = "fake: where it goes"
WHY_WHAT = "fake: what runs"
WHY_WHEN = "fake: when"
WHY_NOT_TEXT = "fake: not text a person reads"
BY_ENTRY_NAME, BY_SCHEMA, BY_PARAM, INNER = (_Rule("by_entry_name"), _Rule("by_schema"),
                                             _Rule("by_param"), _Rule("inner"))
_V_CTX, _V_IN = Slot("value", "context", ""), Slot("value", "inline", "")
_N_WHERE, _N_WHAT, _N_WHEN = (Slot("never", None, WHY_WHERE), Slot("never", None, WHY_WHAT),
                              Slot("never", None, WHY_WHEN))
_N_TEXT = Slot("never", None, WHY_NOT_TEXT)
NODE_SLOTS = {
    "llm": {"prompt": _V_CTX, "model": _N_WHAT, "endpoint_url": _N_WHERE, "output_target": _N_WHERE,
            "tools": _N_WHAT, "answer_fields": _N_WHAT},
    "research": {"prompt": _V_IN, "model": _N_WHAT, "output_target": _N_WHERE},
    "action": {"action": _N_WHAT, "prompt": BY_PARAM, "output_target": _N_WHERE},
    "run_task": {"task_id": _N_WHAT},
    "if": {"conditions[].left": _V_IN, "conditions[].right": _V_IN, "conditions[].op": _N_WHAT},
    "switch": {"cases[].conditions[].left": _V_IN, "cases[].label": _N_WHAT},
    "set": {"fields[].name": _N_WHAT, "fields[].value": _V_IN},
    "merge": {"mode": _N_WHAT},
    "wait": {"mode": _N_WHEN, "time": _N_WHEN},
    "foreach": {"list": _V_IN, "on_error": _N_WHAT, "step": _N_WHAT, "step.config": INNER},
    "http": {"integration": _N_WHERE, "method": _N_WHERE, "path": _N_WHERE, "headers": _N_WHERE,
             "query[].value": BY_ENTRY_NAME, "body[].value": BY_ENTRY_NAME},
    "mcp": {"tool": _N_WHAT, "args": _N_TEXT, "args.*": BY_SCHEMA},
    "skill": {"skill": _N_WHAT, "prompt": _V_CTX},
    "code": {"language": _N_WHAT, "source": _N_WHAT, "input[].value": _V_IN},
}
_WORDS = {"text", "message", "msg", "body", "content", "subject", "title", "summary", "description",
          "details", "note", "notes", "comment", "caption", "reply", "answer", "markdown", "html",
          "md", "plain"}


def classify_argument(name, schema):
    """§ 1.2's allowlist, as the design states it."""
    import re
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        return _N_TEXT
    parts = [p.lower() for chunk in re.split(r"[_-]+", name) if chunk
             for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+", chunk)]
    if not parts or any(p not in _WORDS for p in parts):
        return _N_TEXT
    if not isinstance(schema, dict) or schema.get("type") not in ("string", "number", "integer",
                                                                   "boolean"):
        return _N_TEXT
    if schema.get("format") is not None:
        return _N_WHERE
    return _V_IN


_SLOTS_NAMES = ("RenderedCall", "Slot", "MAPPING_VALUE", "MAPPING_NEVER", "WHY_WHERE", "WHY_WHAT",
                "WHY_WHEN", "WHY_NOT_TEXT", "BY_ENTRY_NAME", "BY_SCHEMA", "BY_PARAM", "INNER",
                "NODE_SLOTS", "classify_argument")


def _field_type(value):
    if value is None or value == "" or value == [] or value == {}:
        return "empty"
    if isinstance(value, bool):
        return "yes/no"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    return "list" if isinstance(value, list) else "object"


def _example(value):
    if isinstance(value, (dict, list)):
        return None
    return value if not isinstance(value, str) else value[:80]


def flatten_fields(value, max_depth=4, max_fields=200):
    out = [{"path": [], "type": _field_type(value), "example": _example(value)}]
    frontier, depth = [((), value)], 0
    while frontier and depth < max_depth and len(out) < max_fields:
        depth += 1
        nxt = []
        for path, node in frontier:
            kids = (list(node.items()) if isinstance(node, dict)
                    else [(0, node[0])] if isinstance(node, list) and node else [])
            for key, child in kids:
                out.append({"path": [*path, key], "type": _field_type(child),
                            "example": _example(child)})
                nxt.append(((*path, key), child))
        frontier = nxt
    return out


def format_ref(node_id, field, path=()):
    import re
    if not isinstance(node_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", node_id):
        raise ValueError(node_id)
    tail = ""
    for seg in path:
        if isinstance(seg, int):
            tail += f"[{seg}]"
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", str(seg)):
            tail += f".{seg}"
        else:
            raise ValueError(seg)
    return f"{{{{ steps.{node_id}.{field}{tail} }}}}"


_REFS = {"flatten_fields": flatten_fields, "format_ref": format_ref}
_LOGIC = {"OPERATORS": ("equals", "contains", "is_empty", "greater_than", "less_than", "one_of"),
          "OPERATOR_WORDS": {"equals": "is", "contains": "contains", "is_empty": "is empty",
                             "greater_than": "is more than", "less_than": "is less than",
                             "one_of": "is one of"}}

NODE_KINDS = ("llm", "research", "action", "run_task", "if", "switch", "set", "merge", "wait",
              "foreach", "http", "mcp", "skill", "code")


def ports_of(node):
    if node == "start":
        return ("success",)
    kind = node.get("kind") if isinstance(node, dict) else None
    if kind == "if":
        return ("then", "otherwise")
    if kind == "switch":
        cases = (node.get("config") or {}).get("cases") or []
        return tuple(f"case:{c['id']}" for c in cases if isinstance(c, dict)) + ("otherwise",)
    if kind in ("set", "merge", "wait"):
        return ("success",)
    return ("success", "error") if kind in NODE_KINDS else ()


def upstream_of(g, node_id):
    feeds = {}
    for e in g.get("edges") or ():
        if e["from"] != "start":
            feeds.setdefault(e["to"], set()).add(e["from"])
    found, frontier = set(), [node_id]
    while frontier:
        nxt = []
        for cur in frontier:
            for pred in feeds.get(cur, ()):
                if pred not in found:
                    found.add(pred)
                    nxt.append(pred)
        frontier = nxt
    return frozenset(found)


class WorkflowResources(_NT):
    """wf-rules' fields (read on its branch, 2026-10-02; not copied)."""
    integrations: Any = None
    mcp_tools: Any = None
    skills: frozenset = frozenset()
    ai_tools: frozenset = frozenset()
    workstation_why: Any = "Pantheon could not check your workstation"
    foreach_max_items: int = 50
    wait_max_hours: int = 168


_DOCUMENT = {"ports_of": ports_of, "upstream_of": upstream_of,
             "WorkflowResources": WorkflowResources}
_RUNS = {"foreach_max_items": lambda owner=None: 50, "wait_max_hours": lambda: 168,
         "WORKFLOW_PARALLEL_STEPS": 4}
