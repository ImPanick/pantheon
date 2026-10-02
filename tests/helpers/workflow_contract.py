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


def install(monkeypatch) -> dict:
    """Nothing of C1 is faked any more: fails — naming the half — if a C1 half
    is absent, rather than standing one in.

    Wave D (`wf-walker`): the walker and the routes now import contracts C-R
    and C-E, which `wf-rules` and `wf-effects` build on their own branches, so
    on `wf-walker` alone `tests/helpers/workflow_cd_contract.install` stands in
    for the names those halves do not have yet — and on the merged tree it
    installs nothing. Answers what it stood in for."""
    from tests.helpers import workflow_cd_contract
    gone = _missing()
    assert not gone, f"a C1 half is missing from this tree: {', '.join(gone)}"
    return {"wave_d": workflow_cd_contract.install(monkeypatch)}


def document():
    """`src.workflow_document`."""
    return importlib.import_module("src.workflow_document")
