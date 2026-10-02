# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engine's half of Slice B (`C1`), as `wf-api`'s tests reach it.

`/work/notes/SLICE-B-DESIGN.md` § 7 split Slice B three ways, and `wf-api`'s
tests were written against contract **C1** while `wf-engine` built it on its
own branch: this module stood in a thin fake for each half that was absent
(the three models, `src.workflow_document`, `src.workflow_runs`,
`admin_only_action_of`, `record_admin_refusal(..., action=)`).

**Since the wave C merge every half is real, so this module installs nothing.**
The fakes were removed at the merge (`integrate-c`): a second implementation
of the contract that a test would silently drive if a real half went missing
is the half-wiring `Law 13` forbids. `install` now checks that each half is
present and fails, naming the half, if one is not — the same tests drive the
real engine, the real tables and the real policy, and say so.

The four names the tests call (`models`, `create_all`, `install`, `document`)
keep their meaning, so the five test files that use them read as before.

**Wave D, the same move (`integrate-d`).** `wf-walker` coded its tests against
contracts C-R (`wf-rules`) and C-E (`wf-effects`) through stand-ins
(`tests/helpers/workflow_cd_contract.py`, now deleted) that installed only the
names a branch lacked. On the merged tree they still installed one name nobody
in the product reads (`workflow_document.PORT_CASE_PREFIX`; the real one is
`CASE_PORT_PREFIX`) and, through `wf-effects`' own stand-in
(`workflow_cr_fake.py`, deleted too), the one name whose absence broke every
palette and every run (`workflow_runs.WORKFLOW_PARALLEL_STEPS`). A stand-in
that installs on the merged tree is a test of the stand-in (`Law 20`), so
`install` now checks the wave D names exactly as it checks C1's — the names the
walker and the routes import — and fails naming the half that is missing.
"""

from __future__ import annotations

import importlib
import inspect

import core.database as cdb


def models():
    """`(Workflow, WorkflowVersion, TaskRunNode)` — the product's models."""
    return cdb.Workflow, cdb.WorkflowVersion, cdb.TaskRunNode


def create_all(engine) -> None:
    """Every table these tests touch: the product's own metadata."""
    cdb.Base.metadata.create_all(engine)


def _missing() -> list:
    """The C1 halves that are not on this tree — none since the merge."""
    import src.task_action_policy as tap
    gone = [name for name in ("Workflow", "WorkflowVersion", "TaskRunNode") if not hasattr(cdb, name)]
    for module in ("src.workflow_document", "src.workflow_runs"):
        try:
            importlib.import_module(module)
        except ImportError:
            gone.append(module)
    if not hasattr(tap, "admin_only_action_of"):
        gone.append("task_action_policy.admin_only_action_of")
    if "action" not in inspect.signature(tap.record_admin_refusal).parameters:
        gone.append("task_action_policy.record_admin_refusal(action=)")
    return gone


# The wave D names the walker, the routes and the store import (contracts C-R
# and C-E of `SLICE-CD-DESIGN` § 3, as `wf-walker` coded against them).
WAVE_D_NAMES = {
    "src.workflow_document": (
        "NODE_KIND_IF", "NODE_KIND_SWITCH", "NODE_KIND_SET", "NODE_KIND_MERGE",
        "NODE_KIND_WAIT", "NODE_KIND_FOREACH", "NODE_KIND_HTTP", "NODE_KIND_MCP",
        "NODE_KIND_SKILL", "NODE_KIND_CODE", "PORT_SUCCESS", "PORT_ERROR", "PORT_THEN",
        "PORT_OTHERWISE", "CASE_PORT_PREFIX", "ports_of", "node_needs_model",
        "WorkflowResources", "plan_lines", "start_nodes", "upstream_of"),
    "src.workflow_refs": ("parse_template", "render_text", "render_value",
                          "render_named_slots", "MISSING", "RefError"),
    "src.workflow_slots": ("RenderedCall", "render_call", "SlotError", "classify_argument"),
    "src.workflow_logic": ("choose_port", "build_set", "evaluate_condition"),
    "src.workflow_effects": ("workflow_resources", "build_palette", "available_fields",
                             "run_http_step", "run_mcp_step", "run_code_step",
                             "skill_context", "answer_instruction", "parse_answer",
                             "ai_tool_choices", "StepOutcome", "StepRefused"),
    "src.workflow_runs": ("WORKFLOW_PARALLEL_STEPS", "foreach_max_items", "wait_max_hours",
                          "workflow_approval_ttl_seconds", "start_targets", "RunState"),
}


def _missing_wave_d() -> list:
    """The wave D names that are not on this tree — none since the merge."""
    gone = []
    for module, names in WAVE_D_NAMES.items():
        try:
            mod = importlib.import_module(module)
        except ImportError:
            gone.append(module)
            continue
        gone += [f"{module}.{n}" for n in names if not hasattr(mod, n)]
    return gone


def install(monkeypatch) -> dict:
    """Nothing of C1, C-R or C-E is faked any more: fails — naming the half —
    if one is absent, rather than standing one in. Answers `{}` (nothing was
    stood in); `monkeypatch` is kept for the callers' signature."""
    gone = _missing()
    assert not gone, f"a C1 half is missing from this tree: {', '.join(gone)}"
    gone = _missing_wave_d()
    assert not gone, f"a wave D half is missing from this tree: {', '.join(gone)}"
    return {}


def document():
    """`src.workflow_document`."""
    return importlib.import_module("src.workflow_document")
