# SPDX-License-Identifier: AGPL-3.0-or-later
"""A workflow is a file you can hand someone — `P22-24` (`SLICE-EF-DESIGN` § 1.6).

    {"pantheon_workflow": 1, "name": "…", "exported_at": "…",
     "trigger":  TRIGGER_FIELDS — no webhook token, no status,
     "graph":    version_graph(graph) less every endpoint_url, model,
                 character_id and crew_member_id, header VALUES blanked,
     "requires": {"integrations": [{"ref", "name", "preset"}],
                  "mcp_tools": [{"ref", "server", "tool", "input_schema"}],
                  "skills": [name], "tasks": [{"ref", "name"}], "workstation": bool}}

**Never in the file:** the webhook token; a pinned sample (real data from a
run) and an `unchecked` mark (`version_graph`); an endpoint URL (this
install's address — a LAN leak, and a destination); an Integration's key or
base URL (an Integration is only ever referred to by id, with its name and
preset); MCP env; an HTTP header's value (names kept, values blanked, and the
import lists them). Last, a scan for the low-false-positive shapes
`diagnostic_bundle` redacts (`_KNOWN_PREFIX`) and `Bearer …` refuses the
export, naming the step and the field — mistake prevention, not a control: the
person typed it (`Law 17`).

**Import** (`import_file`) is the file's adversary's door — whoever wrote the
file (§ 5.3). Refused whole: over 1 MiB, an unknown `pantheon_workflow`, a
graph `parse_graph` refuses, and any refusal of the document rule but a
missing resource. What this install is missing (an Integration, an MCP tool, a
skill, a task, the workstation, an AI tool) is rebound by name where it can be
— an Integration by preset then name, an MCP tool by server and tool name, a
skill by name, a task by name — and otherwise checked against a STAND-IN, so
every other rule (references, `never` slots, loops, merges, kinds, actions, the
admin gate) is still asked. A file's schema cannot widen a slot:
`classify_argument` decides by a name allowlist, and a schema can only narrow.
What is still missing goes into the step's `unchecked.needs` and the reply's
`missing` sentences. Then `create_from_document(origin="imported")` — off,
every step marked, a fresh webhook token minted, nothing read from the file
but its document and when it starts.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace

# The fields that belong to the install a step was made on — the same four the
# drafter never sets (`workflow_assist.INSTALL_FIELDS`, one list, `Law 7`).
from src.workflow_assist import INSTALL_FIELDS

# Stored in every file (`FORBIDDEN.md` Part 1 at the merge): the key, and the
# version this Pantheon reads.
FILE_KEY = "pantheon_workflow"
FILE_VERSION = 1
FILE_MAX_BYTES = 1024 * 1024

NOT_A_FILE = "This is not a Pantheon workflow file."
FILE_TOO_BIG = "The file is larger than 1 MiB, so it was not read. Nothing was saved."
# A Run task step whose task this install does not have points at this
# instead — an id no task can have — so the rule is asked of everything else,
# and the step says which task to pick (`needs`). The file's id is never kept:
# an id that happened to be one of the importer's own tasks would run it.
MISSING_TASK_ID = "not-on-this-install"
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")


def _secret_shape(text) -> bool:
    from src.diagnostic_bundle import _KNOWN_PREFIX
    return isinstance(text, str) and bool(_KNOWN_PREFIX.search(text) or _BEARER_VALUE.search(text))


def _inner(node: dict):
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    step = config.get("step") if isinstance(config.get("step"), dict) else None
    return step


def _steps(node: dict) -> list:
    """The step itself and, for a For-each, the step it repeats."""
    out = [node]
    inner = _inner(node)
    if inner is not None:
        out.append(inner)
    return out


def _clean_config(config: dict, label: str, notes: list) -> dict:
    """A step's settings as a file carries them: no install field, header
    values blanked — and the For-each's step the same."""
    out = json.loads(json.dumps(config or {}))
    dropped = sorted(k for k in out if k in INSTALL_FIELDS)
    for key in dropped:
        out.pop(key, None)
    if dropped and notes is not None:
        notes.append(f"“{label}”: {', '.join(dropped)} {'was' if len(dropped) == 1 else 'were'} "
                     f"left out — {'it belongs' if len(dropped) == 1 else 'they belong'} to the "
                     f"install the workflow was made on.")
    headers = out.get("headers")
    if isinstance(headers, list):
        out["headers"] = [dict(h, value="") if isinstance(h, dict) else h for h in headers]
    step = out.get("step")
    if isinstance(step, dict) and isinstance(step.get("config"), dict):
        step["config"] = _clean_config(step["config"], label, notes)
    return out


# ── Export ───────────────────────────────────────────────────────────────────

def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def export_file(db, wf, trigger) -> dict:
    """The file a workflow becomes. Raises `WorkflowRefused` (400) when a
    step's text looks like a key or a token, naming the step and field."""
    from src import workflow_store as store
    from src.workflow_document import TRIGGER_FIELDS, field_words, version_graph
    from src.workflow_effects import workflow_resources
    from src.workflow_slots import config_leaves, path_text
    from src.workflow_store import WorkflowRefused

    graph = version_graph(store.stored_graph(wf))
    resources = workflow_resources(wf.owner)
    tasks_by_id, _crew = store.owner_rows(db, wf.owner)
    integrations, tools, skills, tasks, workstation = {}, {}, [], {}, False
    for node in store.nodes_of(graph):
        node["config"] = _clean_config(node.get("config") or {}, node.get("label"), None)
        for step in _steps(node):
            kind = step.get("kind")
            config = step.get("config") or {}
            if kind == "http" and isinstance(config.get("integration"), str):
                ref = config["integration"]
                info = (resources.integrations or {}).get(ref) or {}
                integrations[ref] = {"ref": ref, "name": str(info.get("name") or ref),
                                     "preset": str(info.get("preset") or "")}
            elif kind == "mcp" and isinstance(config.get("tool"), str):
                ref = config["tool"]
                info = (resources.mcp_tools or {}).get(ref) or {}
                server, _, tool = ref[len("mcp__"):].partition("__") if ref.startswith("mcp__") \
                    else ("", "", ref)
                tools[ref] = {"ref": ref, "server": str(info.get("server_name") or server),
                              "tool": str(info.get("name") or tool),
                              "input_schema": info.get("input_schema") or {}}
            elif kind == "skill" and isinstance(config.get("skill"), str):
                if config["skill"] not in skills:
                    skills.append(config["skill"])
            elif kind == "run_task" and isinstance(config.get("task_id"), str):
                ref = config["task_id"]
                task = tasks_by_id.get(ref)
                tasks[ref] = {"ref": ref, "name": getattr(task, "name", None) or ref}
            elif kind == "code":
                workstation = True
    for node in store.nodes_of(graph):
        for path, text in config_leaves(node.get("config") or {}):
            if _secret_shape(text):
                raise WorkflowRefused(
                    400, f"“{node.get('label')}”, {field_words(node, path)}, holds something "
                         f"that looks like a key or a token, so the workflow was not exported. "
                         f"Keep it in the Integration (or take it out), then export again.",
                    reason="secret_shape", node_ids=(node.get("id"),), field=path_text(path))
    start = {}
    if trigger is not None:
        for key in TRIGGER_FIELDS:
            value = getattr(trigger, key, None)
            if value is not None:
                start[key] = _iso(value)
    if _secret_shape(wf.name) or any(_secret_shape(v) for v in start.values()):
        raise WorkflowRefused(400, "The workflow's name or its start holds something that "
                                   "looks like a key or a token, so it was not exported.",
                              reason="secret_shape")
    return {
        FILE_KEY: FILE_VERSION,
        "name": wf.name,
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                       .replace("+00:00", "Z"),
        "trigger": start,
        "graph": graph,
        "requires": {"integrations": list(integrations.values()),
                     "mcp_tools": list(tools.values()), "skills": skills,
                     "tasks": list(tasks.values()), "workstation": workstation},
    }


def file_name(name) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(name or "")).strip("-").lower()[:60] or "workflow"
    return f"{slug}.workflow.json"


# ── Import ───────────────────────────────────────────────────────────────────

class Imported(SimpleNamespace):
    """`wf`, `trigger`, `notes`, `missing`, `destinations`."""


def _requires(data) -> dict:
    out = data.get("requires") if isinstance(data.get("requires"), dict) else {}

    def entries(key):
        items = out.get(key) if isinstance(out.get(key), list) else []
        return [i for i in items if isinstance(i, dict) and isinstance(i.get("ref"), str)]
    return {"integrations": {i["ref"]: i for i in entries("integrations")},
            "mcp_tools": {i["ref"]: i for i in entries("mcp_tools")},
            "tasks": {i["ref"]: i for i in entries("tasks")}}


def _text(value) -> str:
    return " ".join(str(value or "").split())[:120]


def import_file(db, owner, data) -> Imported:
    """`P22-24`. A workflow file, made a workflow of this person's — switched
    off, every step marked `imported` with what it still `needs`. Raises
    `WorkflowRefused`, writing nothing, for anything but a missing resource."""
    from src import workflow_store as store
    from src.workflow_document import (
        DocumentError, ORIGIN_IMPORTED, UNCHECKED_KEY, WORKFLOW_TASK_TYPE, WorkflowResources,
        destination_lines, parse_graph,
    )
    from src.workflow_effects import workflow_resources
    from src.workflow_store import WorkflowRefused

    if not isinstance(data, dict) or FILE_KEY not in data:
        raise WorkflowRefused(400, NOT_A_FILE)
    try:
        size = len(json.dumps(data, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        raise WorkflowRefused(400, NOT_A_FILE) from None
    if size > FILE_MAX_BYTES:
        raise WorkflowRefused(413, FILE_TOO_BIG)
    version = data.get(FILE_KEY)
    if isinstance(version, bool) or version != FILE_VERSION:
        raise WorkflowRefused(400, f"This workflow file is version {_text(version)}; this Pantheon "
                                   f"reads version {FILE_VERSION}. Nothing was saved.")
    raw = data.get("graph")
    if isinstance(raw, dict) and isinstance(raw.get("nodes"), list):
        raw = dict(raw)
        raw["nodes"] = [{k: v for k, v in n.items() if k not in (UNCHECKED_KEY, "pinned")}
                        if isinstance(n, dict) else n for n in raw["nodes"]]
    try:
        graph = parse_graph(raw)
    except DocumentError as err:
        raise store._document_error_refusal(err) from None
    requires = _requires(data)
    real = workflow_resources(owner)
    tasks_by_id, crew_ids = store.owner_rows(db, owner)
    notes, missing = [], []
    needs = {}
    integrations = dict(real.integrations or {})
    mcp_tools = dict(real.mcp_tools or {})
    skills = set(real.skills or ())
    ai_tools = set(real.ai_tools or ())
    rows = dict(tasks_by_id)
    workstation_why = real.workstation_why
    own_tasks = {t.name: t.id for t in tasks_by_id.values()
                 if (t.task_type or "llm") != WORKFLOW_TASK_TYPE and t.name}

    def need(node, entry, sentence):
        needs.setdefault(node["id"], []).append({k: str(v)[:300] for k, v in entry.items() if v})
        if sentence not in missing:
            missing.append(sentence)

    for node in graph["nodes"]:
        node["config"] = _clean_config(node.get("config") or {}, node["label"], notes)
        called = f"“{node['label']}”"
        for step in _steps(node):
            kind = step.get("kind")
            config = step.get("config") if isinstance(step.get("config"), dict) else {}
            step["config"] = config
            inner = "" if step is node else "step.config."
            if kind == "http" and isinstance(config.get("integration"), str):
                ref = config["integration"]
                said = requires["integrations"].get(ref) or {"name": ref, "preset": ""}
                name, preset = _text(said.get("name") or ref), _text(said.get("preset"))
                found = [i for i, info in integrations.items() if info.get("enabled", True)
                         and preset and str(info.get("preset") or "") == preset]
                found = [i for i in found if str(integrations[i].get("name") or "").lower()
                         == name.lower()] or found
                found = found or [i for i, info in integrations.items() if info.get("enabled", True)
                                  and str(info.get("name") or "").lower() == name.lower()]
                if found:
                    config["integration"] = found[0]
                else:
                    integrations[ref] = {"id": ref, "name": name, "preset": preset, "enabled": True}
                    need(node, {"field": f"{inner}integration", "name": name, "preset": preset},
                         f"{called} uses an Integration called “{name}”"
                         + (f" ({preset})" if preset else "")
                         + ". Add it in Integrations, then pick it on the step.")
                for index, header in enumerate(config.get("headers") or ()):
                    if isinstance(header, dict) and header.get("name") and not header.get("value"):
                        need(node, {"field": f"{inner}headers[{index}].value",
                                    "name": str(header["name"])},
                             f"{called} sends the header “{_text(header['name'])}”, and a file "
                             f"never carries its value. Type it on the step.")
            elif kind == "mcp" and isinstance(config.get("tool"), str):
                ref = config["tool"]
                said = requires["mcp_tools"].get(ref) or {}
                server, tool = _text(said.get("server")), _text(said.get("tool") or ref)
                found = [q for q, info in mcp_tools.items()
                         if str(info.get("server_name") or "").lower() == server.lower()
                         and str(info.get("name") or "") == tool]
                if found:
                    config["tool"] = found[0]
                else:
                    schema = said.get("input_schema") if isinstance(said.get("input_schema"), dict) \
                        else {}
                    mcp_tools[ref] = {"input_schema": schema, "disabled": False,
                                      "is_readonly": None, "server_name": server, "name": tool}
                    need(node, {"field": f"{inner}tool", "name": f"{server} · {tool}",
                                "server": server, "tool": tool},
                         f"{called} calls the tool “{tool}” on an MCP server called "
                         f"“{server or 'unknown'}”. Connect that server, then pick the tool on "
                         f"the step.")
            elif kind == "skill" and isinstance(config.get("skill"), str):
                if config["skill"] not in skills:
                    skills.add(config["skill"])
                    need(node, {"field": f"{inner}skill", "name": config["skill"]},
                         f"{called} follows a skill called “{_text(config['skill'])}”. Add a "
                         f"skill with that name in Skills, then pick it on the step.")
            elif kind == "run_task" and "task_id" in config:
                ref = config.get("task_id")
                said = requires["tasks"].get(ref) if isinstance(ref, str) else None
                name = _text((said or {}).get("name") or ref)
                if name in own_tasks:
                    config["task_id"] = own_tasks[name]
                else:
                    config["task_id"] = MISSING_TASK_ID
                    rows[MISSING_TASK_ID] = SimpleNamespace(
                        id=MISSING_TASK_ID, owner=owner, task_type="llm", action=None, name=name)
                    need(node, {"field": f"{inner}task_id", "name": name},
                         f"{called} runs a task called “{name}”, which you do not have. Pick one "
                         f"of your tasks on the step.")
            elif kind == "code" and workstation_why:
                need(node, {"field": f"{inner}language", "name": "workstation"},
                     f"{called} runs code in your workstation, which cannot run it now: "
                     f"{workstation_why}")
            if kind == "llm" and isinstance(config.get("tools"), list):
                for tool in config["tools"]:
                    if isinstance(tool, str) and tool not in ai_tools:
                        ai_tools.add(tool)
                        need(node, {"field": f"{inner}tools", "name": tool},
                             f"{called} may use the tool “{_text(tool)}”, which you cannot use "
                             f"here. Change its tools on the step.")
    resources = WorkflowResources(
        integrations=integrations, mcp_tools=mcp_tools, skills=frozenset(skills),
        ai_tools=frozenset(ai_tools), workstation_why=None,
        foreach_max_items=real.foreach_max_items, wait_max_hours=real.wait_max_hours)
    check_rows = (rows, crew_ids)
    store.check_document(db, graph, owner=owner, own_task_id=None, rows=check_rows,
                         resources=resources)
    trigger_fields = data.get("trigger") if isinstance(data.get("trigger"), dict) else {}
    wf, trigger, said = store.create_from_document(
        db, owner=owner, name=_text(data.get("name")) or None, graph=graph,
        trigger_fields=trigger_fields, origin=ORIGIN_IMPORTED, needs=needs,
        resources=resources, rows=check_rows)
    destinations = destination_lines(store.stored_graph(wf), resources)
    return Imported(wf=wf, trigger=trigger, notes=said + notes, missing=missing,
                    destinations=destinations)
