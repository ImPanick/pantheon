# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2174`: the "only a person" refusals have one definition each.

`ONLY_A_PERSON_ANSWERS` was defined twice with different words —
`src/auth_helpers.py` (`B1926`, a chat's card) and `src/workflow_store.py`
(`B1870`, a waiting step) — and `routes/task/task_routes.py` imported both,
the second shadowing the first. The merge that met them kept both sentences on
purpose (ROADMAP, the `B1870`/`B1926` note): a task run's and a workflow step's
door say where the person answers. So the step's sentence takes its own name,
`ONLY_A_PERSON_ANSWERS_A_STEP`, and each name has one definition.

Five routes (designs, networks, vault, agents, git) each wrote their own
`ONLY_A_PERSON` with the same tail; they are built from
`auth_helpers.only_a_person_can` now. Four keep their words exactly; the design
studio's gains "can" ("changes their design systems" → "can change their
design systems"), the one that had drifted from the others.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _top_level_assignments(name_prefix: str) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for root in ("src", "routes", "core", "services", "mcp_servers"):
        for path in (REPO / root).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.startswith(name_prefix):
                            seen.setdefault(target.id, []).append(path.relative_to(REPO).as_posix())
    return seen


def test_each_answer_refusal_name_is_defined_once():
    seen = _top_level_assignments("ONLY_A_PERSON_ANSWERS")
    assert seen == {
        "ONLY_A_PERSON_ANSWERS": ["src/auth_helpers.py"],
        "ONLY_A_PERSON_ANSWERS_A_STEP": ["src/workflow_store.py"],
    }, seen


def test_the_task_and_workflow_doors_say_where_the_person_answers():
    from src.auth_helpers import ONLY_A_PERSON_ANSWERS
    from src.workflow_store import ONLY_A_PERSON_ANSWERS_A_STEP

    assert ONLY_A_PERSON_ANSWERS == (
        "Only you can answer this, from Pantheon itself — not an API token and not your assistant.")
    assert ONLY_A_PERSON_ANSWERS_A_STEP == (
        "Only you can answer a step that is waiting for your yes, from the notification or the "
        "Workbench — not an API token and not your assistant.")


ROUTE_SENTENCES = {
    "routes.person_network_routes":
        "Only a person signed in to Pantheon can change their networks — not an API token or the assistant.",
    "routes.vault_mine_routes":
        "Only a person signed in to Pantheon can change, reveal or unlock their vault — "
        "not an API token or the assistant.",
    "routes.agent_routes":
        "Only a person signed in to Pantheon can summon, change or dismiss an agent — "
        "not an API token or the assistant.",
    "routes.git_routes":
        "Only a person signed in to Pantheon can change their git identity or tokens — "
        "not an API token or the assistant.",
    "routes.design_routes":
        "Only a person signed in to Pantheon can change their design systems — "
        "not an API token or the assistant.",
}


def test_each_routes_refusal_reads_as_it_did():
    import importlib

    for module, sentence in ROUTE_SENTENCES.items():
        assert importlib.import_module(module).ONLY_A_PERSON == sentence, module


def test_each_routes_refusal_is_built_from_the_one_template():
    for module in ROUTE_SENTENCES:
        path = REPO / (module.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        value = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "ONLY_A_PERSON" for t in node.targets))
        assert isinstance(value, ast.Call) and ast.unparse(value.func) == "only_a_person_can", module
