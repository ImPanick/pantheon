# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stand-ins for contracts **C-R** (`wf-rules`) and **C-E** (`wf-effects`) on the
`wf-walker` branch, where those halves are not merged yet (`P22-WAVE-D.md`:
"code to the contracts exactly, fake where absent, say so").

`install(monkeypatch)` puts in place ONLY what the real modules do not have:
for each name in `C_R` / `C_E`, if the real module (`src.workflow_document`,
`src.workflow_refs`, `src.workflow_slots`, `src.workflow_logic`,
`src.workflow_effects`) already exports it, the real one is used and nothing is
faked. On the merged tree it installs nothing; it answers the list of names it
stood in for, which each test prints into its own failure message so a run
says which half was real.

Each stand-in implements the design's rule (`SLICE-CD-DESIGN` § 1.1–1.3, § 2's
`NODE_SLOTS` table, § 3's `C-E` signatures) as plainly as possible — enough for
the walker's own tests to drive the walker, never a second implementation the
product reads: nothing under `src/` or `routes/` imports this file.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import types
from typing import Any, NamedTuple

# ── the names the walker and routes import (the contracts, as coded against) ──

C_R_DOCUMENT = (
    "NODE_KIND_IF", "NODE_KIND_SWITCH", "NODE_KIND_SET", "NODE_KIND_MERGE",
    "NODE_KIND_WAIT", "NODE_KIND_FOREACH", "NODE_KIND_HTTP", "NODE_KIND_MCP",
    "NODE_KIND_SKILL", "NODE_KIND_CODE", "PORT_SUCCESS", "PORT_ERROR", "PORT_THEN",
    "PORT_OTHERWISE", "PORT_CASE_PREFIX", "ports_of", "node_needs_model",
    "WorkflowResources", "plan_lines",
)
C_R_MODULES = {
    "src.workflow_refs": ("parse_template", "render_text", "render_value",
                          "render_named_slots", "MISSING", "RefError"),
    "src.workflow_slots": ("RenderedCall", "render_call", "SlotError", "classify_argument"),
    "src.workflow_logic": ("choose_port", "build_set", "evaluate_condition"),
}
C_E = ("workflow_resources", "build_palette", "available_fields", "run_http_step",
       "run_mcp_step", "run_code_step", "skill_context", "answer_instruction",
       "parse_answer", "ai_tool_choices", "StepOutcome", "StepRefused")

NEW_KINDS = ("if", "switch", "set", "merge", "wait", "foreach", "http", "mcp", "skill", "code")
SLICE_B_KINDS = ("llm", "research", "action", "run_task")

# What a test can look at.
CODE_CALLS: list = []
FAKE_MCP_TOOLS: dict = {}
FAKE_SKILLS: dict = {}


# ── workflow_refs (§ 1.1) ─────────────────────────────────────────────────────

class _Missing:
    def __repr__(self):
        return "MISSING"


MISSING = _Missing()


class RefError(ValueError):
    def __init__(self, reason, at=0, sentence=""):
        super().__init__(sentence or reason)
        self.reason, self.at, self.sentence = reason, at, sentence or reason


class Ref(NamedTuple):
    text: str
    head: tuple       # ("steps", node, field) or ("item",)
    segs: tuple


class Template(NamedTuple):
    parts: tuple      # str | Ref


_REF = re.compile(r"(?<!\\)\{\{(.*?)\}\}", re.S)
_SEG = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]{0,63})|\[(0|[1-9][0-9]{0,5})\]|\[\"([^\"\\]{0,128})\"\]")
_NODE = r"[A-Za-z0-9_-]{1,64}"


def _parse_ref(inner: str, at: int) -> Ref:
    path = inner.strip()
    m = re.match(rf"^steps\.({_NODE})\.(data|text)", path)
    if m:
        head, rest = ("steps", m.group(1), m.group(2)), path[m.end():]
    elif path.startswith("item"):
        head, rest = ("item",), path[len("item"):]
    else:
        raise RefError("bad_ref", at, f"“{{{{{inner}}}}}” is not a reference.")
    segs, pos = [], 0
    while pos < len(rest):
        sm = _SEG.match(rest, pos)
        if not sm:
            raise RefError("bad_ref", at, f"“{{{{{inner}}}}}” is not a reference.")
        segs.append(sm.group(1) if sm.group(1) is not None
                    else int(sm.group(2)) if sm.group(2) is not None else sm.group(3))
        pos = sm.end()
    if len(segs) > 16:
        raise RefError("too_deep", at, "A reference has more than 16 parts.")
    return Ref("{{" + inner + "}}", head, tuple(segs))


def parse_template(text) -> Template:
    if isinstance(text, Template):
        return text
    text = "" if text is None else str(text)
    parts, pos = [], 0
    for m in _REF.finditer(text):
        if m.start() > pos:
            parts.append(text[pos:m.start()].replace("\\{{", "{{"))
        parts.append(_parse_ref(m.group(1), m.start()))
        pos = m.end()
    if pos < len(text):
        parts.append(text[pos:].replace("\\{{", "{{"))
    return Template(tuple(parts))


def resolve(ref: Ref, ctx: dict):
    if ref.head[0] == "item":
        if "item" not in ctx:
            return MISSING
        value = ctx["item"]
    else:
        step = (ctx.get("steps") or {}).get(ref.head[1])
        if not isinstance(step, dict) or ref.head[2] not in step:
            return MISSING
        value = step[ref.head[2]]
    for seg in ref.segs:
        if isinstance(seg, int) and not isinstance(seg, bool):
            if not isinstance(value, list) or not 0 <= seg < len(value):
                return MISSING
            value = value[seg]
        else:
            if not isinstance(value, dict) or seg not in value:
                return MISSING
            value = value[seg]
    return value


def _as_text(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str)


def render_text(t, ctx) -> tuple:
    t = parse_template(t)
    out, missing = [], []
    for part in t.parts:
        if isinstance(part, Ref):
            value = resolve(part, ctx)
            if value is MISSING:
                missing.append(part.text)
                continue
            out.append(_as_text(value))
        else:
            out.append(part)
    return "".join(out), missing


def render_value(t, ctx) -> tuple:
    t = parse_template(t)
    refs = [p for p in t.parts if isinstance(p, Ref)]
    if len(t.parts) == 1 and refs:
        value = resolve(refs[0], ctx)
        return value, ([refs[0].text] if value is MISSING else [])
    return render_text(t, ctx)


def render_named_slots(t, ctx) -> tuple:
    t = parse_template(t)
    out, named, used = [], [], set()
    for part in t.parts:
        if not isinstance(part, Ref):
            out.append(part)
            continue
        base = next((str(s) for s in reversed(part.segs) if isinstance(s, str)),
                    part.head[-1])
        name, n = base, 2
        while name in used:
            name, n = f"{base}_{n}", n + 1
        used.add(name)
        out.append(f"[{name}]")
        named.append((name, part.text, resolve(part, ctx)))
    return "".join(out), named


def _refs_in(value) -> list:
    if isinstance(value, str):
        try:
            return [p for p in parse_template(value).parts if isinstance(p, Ref)]
        except RefError:
            return [Ref(value, ("bad",), ())]
    if isinstance(value, list):
        return [r for v in value for r in _refs_in(v)]
    if isinstance(value, dict):
        return [r for v in value.values() for r in _refs_in(v)]
    return []


# ── workflow_slots (§ 1.2) ────────────────────────────────────────────────────

class RenderedCall(NamedTuple):
    kind: str
    tool: str
    content: str
    value_paths: tuple
    missing: tuple


class SlotError(ValueError):
    def __init__(self, sentence, field=""):
        super().__init__(sentence)
        self.sentence, self.field = sentence, field


CONTENT_WORDS = {"text", "message", "msg", "body", "content", "subject", "title", "summary",
                 "description", "details", "note", "notes", "comment", "caption", "reply",
                 "answer", "markdown", "html"}
FORMAT_WORDS = {"text", "html", "markdown", "md", "plain"}
_BAD_FORMATS = {"uri", "uri-reference", "iri", "email", "idn-email", "hostname",
                "idn-hostname", "ipv4", "ipv6", "uri-template"}


def classify_argument(name, schema) -> str:
    parts = [p for p in re.split(r"[_\-]|(?<=[a-z])(?=[A-Z])", str(name or "")) if p]
    if not parts or not all(p.lower() in CONTENT_WORDS | FORMAT_WORDS for p in parts):
        return "never"
    schema = schema if isinstance(schema, dict) else {}
    if schema.get("type") not in ("string", "number", "integer", "boolean"):
        return "never"
    if schema.get("format") in _BAD_FORMATS:
        return "never"
    return "value"


def _never(value, what):
    if _refs_in(value) or (isinstance(value, str) and "{{" in value):
        raise SlotError(f"“{what}” is where it goes or what runs, so it cannot be filled "
                        f"from another step.", field=what)
    return value


def render_call(node, ctx, *, mcp_schema=None) -> RenderedCall:
    kind = node.get("kind")
    config = node.get("config") or {}
    paths, missing = [], []

    def value_of(raw):
        if isinstance(raw, str) and "{{" in raw:
            value, gone = render_value(raw, ctx)
            missing.extend(gone)
            return None if value is MISSING else value
        return raw

    if kind == "http":
        for key in ("integration", "method", "path", "headers"):
            _never(config.get(key), key)
        query, body = {}, {}
        for where, out in (("query", query), ("body", body)):
            for entry in config.get(where) or ():
                key = entry.get("key")
                if classify_argument(key, {"type": "string"}) == "value":
                    value = value_of(entry.get("value"))
                    out[key] = value if isinstance(value, (str, int, float, bool)) or value is None \
                        else json.dumps(value, default=str)
                    paths.append(f"{where}.{key}")
                else:
                    out[key] = _never(entry.get("value"), f"{where}.{key}")
        content = json.dumps({"integration": config.get("integration"),
                              "method": config.get("method") or "GET",
                              "path": config.get("path") or "/", "query": query,
                              "body": body, "structured": True})
        return RenderedCall("http", "api_call", content, tuple(paths), tuple(missing))
    if kind == "mcp":
        tool = _never(config.get("tool"), "tool")
        props = ((mcp_schema or {}).get("properties") or {}) if isinstance(mcp_schema, dict) else {}
        args = {}
        for name, raw in (config.get("args") or {}).items():
            schema = props.get(name) or {}
            if classify_argument(name, schema) == "value":
                value = value_of(raw)
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, default=str)
                if schema.get("type") in ("integer", "number") and isinstance(value, str):
                    value = float(value) if schema["type"] == "number" else int(value)
                args[name] = value
                paths.append(f"args.{name}")
            else:
                args[name] = _never(raw, f"args.{name}")
        return RenderedCall("mcp", tool, json.dumps(args), tuple(paths), tuple(missing))
    raise SlotError(f"a {kind} step makes no call")


# ── workflow_logic (P22-10) ───────────────────────────────────────────────────

def _cmp(left, op, right):
    if op == "is_empty":
        return left in (None, "", [], {}) or left is MISSING
    if left is MISSING:
        return False
    if op == "equals":
        return str(left).strip().lower() == str(right).strip().lower()
    if op == "contains":
        if isinstance(left, (list, dict)):
            return right in left
        return str(right).strip().lower() in str(left).strip().lower()
    try:
        a, b = float(left), float(right)
    except (TypeError, ValueError):
        return False
    return a > b if op == "greater_than" else a < b if op == "less_than" else False


def evaluate_condition(cond, ctx) -> bool:
    left = cond.get("left")
    if isinstance(left, str) and "{{" in left:
        left, _missing = render_value(left, ctx)
    return _cmp(left, cond.get("op") or "equals", cond.get("right"))


def _holds(block, ctx) -> bool:
    conds = block.get("conditions") or ()
    results = [evaluate_condition(c, ctx) for c in conds]
    return (any(results) if block.get("join") == "any" else all(results)) if results else False


def choose_port(node, ctx) -> str:
    config = node.get("config") or {}
    if node.get("kind") == "switch":
        for case in config.get("cases") or ():
            if _holds(case, ctx):
                return f"case:{case.get('id')}"
        return "otherwise"
    return "then" if _holds(config, ctx) else "otherwise"


def build_set(node, ctx) -> tuple:
    data, missing = {}, []
    for field in (node.get("config") or {}).get("fields") or ():
        raw = field.get("value")
        if isinstance(raw, str) and "{{" in raw:
            value, gone = render_value(raw, ctx)
            missing.extend(gone)
            data[field.get("name")] = None if value is MISSING else value
        else:
            data[field.get("name")] = raw
    return data, missing


# ── workflow_document additions (§ 1.3) ───────────────────────────────────────

class WorkflowResources(NamedTuple):
    integrations: dict = {}
    mcp_tools: dict = {}
    skills: tuple = ()
    ai_tools: tuple = ()
    workstation: Any = None
    foreach_max_items: int = 50


class FakeRefusal(NamedTuple):
    reason: str
    node_ids: tuple
    sentence: str
    field: str = ""


def ports_of(node) -> tuple:
    kind = node.get("kind")
    if kind == "if":
        return ("then", "otherwise")
    if kind == "switch":
        return tuple(f"case:{c.get('id')}" for c in (node.get("config") or {}).get("cases") or ()) \
            + ("otherwise",)
    if kind in ("set", "merge", "wait"):
        return ("success",)
    return ("success", "error")


def node_needs_model(node) -> bool:
    kind = node.get("kind")
    if kind in ("llm", "research", "skill"):
        return True
    if kind == "foreach":
        inner = (node.get("config") or {}).get("step") or {}
        return node_needs_model(inner) if inner else False
    return False


def plan_lines(node, resources=None) -> list:
    return [f"Would run the {node.get('kind')} step “{node.get('label')}”."]


_NEVER_FIELDS = {
    "http": ("integration", "method", "path", "headers"),
    "mcp": ("tool",),
    "code": ("language", "source", "timeout_seconds"),
    "skill": ("skill", "model", "endpoint_url", "output_target"),
    "llm": ("model", "endpoint_url", "character_id", "crew_member_id", "max_steps",
            "output_target", "tools", "answer_fields"),
    "research": ("model", "endpoint_url", "output_target"),
    "action": ("action", "prompt", "output_target"),
    "run_task": ("task_id",),
    "wait": ("mode", "minutes", "time", "tz"),
    "merge": ("mode",),
    "foreach": ("on_error",),
}


def _fake_validate(real):
    def validate_document(graph, *, resources=None, **kw):
        nodes = list(graph.get("nodes") or ())
        plain = (all(n.get("kind") in SLICE_B_KINDS for n in nodes)
                 and not any(e.get("from") == "start" for e in graph.get("edges") or ())
                 and not any(_refs_in(n.get("config")) for n in nodes))
        if plain:
            return real(graph, **kw)
        ids = {n["id"] for n in nodes}
        for n in nodes:
            if n.get("kind") not in SLICE_B_KINDS + NEW_KINDS:
                return FakeRefusal("bad_kind", (n["id"],), f"“{n['label']}” is a {n.get('kind')!r} step.")
            config = n.get("config") or {}
            for key in _NEVER_FIELDS.get(n.get("kind"), ()):
                if _refs_in(config.get(key)):
                    return FakeRefusal("mapped_never", (n["id"],),
                                       f"“{n['label']}”: {key} is where it goes or what runs, "
                                       f"so it cannot be filled from another step.", field=key)
            if n.get("kind") == "mcp":
                props = ((FAKE_MCP_TOOLS.get(config.get("tool")) or {}).get("input_schema") or {}
                         ).get("properties") or {}
                for name, raw in (config.get("args") or {}).items():
                    if _refs_in(raw) and classify_argument(name, props.get(name)) == "never":
                        return FakeRefusal("mapped_never", (n["id"],),
                                           f"“{n['label']}”: {name} cannot be filled from "
                                           f"another step.", field=f"args.{name}")
        for e in graph.get("edges") or ():
            if (e["from"] != "start" and e["from"] not in ids) or e["to"] not in ids:
                return FakeRefusal("bad_edge", (), "An arrow does not join two steps.")
        return None
    validate_document._contract_fake = True
    return validate_document


# ── workflow_effects (C-E) ────────────────────────────────────────────────────

class StepOutcome(NamedTuple):
    status: str
    text: str
    data: Any = None
    result: Any = None


class StepRefused(Exception):
    def __init__(self, sentence):
        super().__init__(sentence)
        self.sentence = sentence


def workflow_resources(owner):
    return WorkflowResources(mcp_tools=dict(FAKE_MCP_TOOLS))


def build_palette(owner) -> dict:
    return {"kinds": [{"kind": k, "word": k, "group": "steps", "hint": "", "ports": [],
                       "available": True, "why": "", "slots": {}} for k in SLICE_B_KINDS + NEW_KINDS],
            "integrations": [], "mcp_tools": [], "skills": [], "ai_tools": [],
            "workstation": {"available": False, "why": "off"},
            "limits": {"foreach_max_items": 50, "wait_max_hours": 168, "parallel_steps": 4},
            "operators": []}


def available_fields(db, wf, trigger, graph, node_id) -> dict:
    return {"sources": [{"node_id": "start", "label": "Start", "kind": "start",
                         "origin": "declared", "at": None, "fields": []}]}


async def _dispatch(call, owner, security_context, exact_approval):
    from src.agent_tools import ToolBlock
    from src.tool_execution import execute_tool_block

    desc, result = await execute_tool_block(
        ToolBlock(call.tool, call.content), session_id="", owner=owner,
        security_context=security_context, exact_approval=exact_approval)
    ok = isinstance(result, dict) and result.get("exit_code") in (0, None) \
        and not result.get("blocked") and not result.get("error")
    text = (result.get("stdout") or result.get("output") or result.get("error") or "") \
        if isinstance(result, dict) else str(result)
    return StepOutcome("success" if ok else "error", str(text), None, result)


async def run_http_step(call, *, owner, security_context, exact_approval=None):
    return await _dispatch(call, owner, security_context, exact_approval)


async def run_mcp_step(call, *, owner, security_context, exact_approval=None):
    return await _dispatch(call, owner, security_context, exact_approval)


async def run_code_step(node, input_obj, *, owner, timeout):
    config = node.get("config") or {}
    CODE_CALLS.append({"source": config.get("source"), "stdin": json.dumps(input_obj),
                       "owner": owner})
    return StepOutcome("success", json.dumps({"ok": True}), {"ok": True}, None)


def skill_context(owner, name):
    from src.prompt_security import untrusted_context_message
    if name not in FAKE_SKILLS:
        raise StepRefused(f"There is no skill called “{name}”.")
    return ([untrusted_context_message(f"the skill “{name}”", FAKE_SKILLS[name])],
            f"Followed the skill “{name}”")


def answer_instruction(fields) -> str:
    return "Answer as JSON with these fields: " + ", ".join(f["name"] for f in fields)


def parse_answer(text, fields):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None, "no JSON object"
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None, "not JSON"
    missing = [f["name"] for f in fields if f["name"] not in data]
    return (None, "missing " + ", ".join(missing)) if missing else (data, None)


def ai_tool_choices(owner) -> list:
    return []


# ── install ───────────────────────────────────────────────────────────────────

def _module_with(name: str, names: tuple, source: dict, monkeypatch) -> list:
    """`name` as a module carrying every one of `names`: the real module's where
    it has them, these stand-ins where it does not. Answers what was faked."""
    try:
        real = importlib.import_module(name)
    except ImportError:
        real = None
    faked = [n for n in names if real is None or not hasattr(real, n)]
    if not faked:
        return []
    if real is None:
        mod = types.ModuleType(name)
        mod.__dict__.update({n: source[n] for n in source})
        monkeypatch.setitem(sys.modules, name, mod)
        parent = importlib.import_module(name.rsplit(".", 1)[0])
        monkeypatch.setattr(parent, name.rsplit(".", 1)[1], mod, raising=False)
    else:
        for n in faked:
            monkeypatch.setattr(real, n, source[n], raising=False)
    return [f"{name}.{n}" for n in faked]


def install(monkeypatch) -> list:
    """Stand in for the C-R / C-E names the real modules lack. Answers which."""
    import src.workflow_document as wd

    faked = []
    values = {
        "NODE_KIND_IF": "if", "NODE_KIND_SWITCH": "switch", "NODE_KIND_SET": "set",
        "NODE_KIND_MERGE": "merge", "NODE_KIND_WAIT": "wait", "NODE_KIND_FOREACH": "foreach",
        "NODE_KIND_HTTP": "http", "NODE_KIND_MCP": "mcp", "NODE_KIND_SKILL": "skill",
        "NODE_KIND_CODE": "code", "PORT_SUCCESS": "success", "PORT_ERROR": "error",
        "PORT_THEN": "then", "PORT_OTHERWISE": "otherwise", "PORT_CASE_PREFIX": "case:",
        "ports_of": ports_of, "node_needs_model": node_needs_model,
        "WorkflowResources": WorkflowResources, "plan_lines": plan_lines,
    }
    for name in C_R_DOCUMENT:
        if not hasattr(wd, name):
            monkeypatch.setattr(wd, name, values[name], raising=False)
            faked.append(f"src.workflow_document.{name}")
    if not hasattr(wd, "WorkflowResources") or faked:
        # The real rule does not know the new kinds or `resources` yet.
        import inspect
        if "resources" not in inspect.signature(wd.validate_document).parameters:
            monkeypatch.setattr(wd, "validate_document", _fake_validate(wd.validate_document))
            faked.append("src.workflow_document.validate_document(resources=)")
    if "llm" in wd.NODE_CONFIG_FIELDS and "tools" not in wd.NODE_CONFIG_FIELDS["llm"]:
        fields = dict(wd.NODE_CONFIG_FIELDS)
        fields["llm"] = fields["llm"] + ("tools", "answer_fields")
        monkeypatch.setattr(wd, "NODE_CONFIG_FIELDS", fields)
    here = sys.modules[__name__].__dict__
    for module, names in C_R_MODULES.items():
        faked += _module_with(module, names, {n: here[n] for n in names}
                              | {"Template": Template, "Ref": Ref, "resolve": resolve},
                              monkeypatch)
    faked += _module_with("src.workflow_effects", C_E, {n: here[n] for n in C_E}, monkeypatch)
    return faked
