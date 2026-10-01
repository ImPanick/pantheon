# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-04` (`B803`) gave `manage_tasks` a `dry_run` action in the function
schema. A model on the fenced-block channel reads `TOOL_SECTIONS` instead,
whose `manage_tasks` line listed `list|create|edit|delete|pause|resume|run` —
so on that channel the action did not exist — and agent-mode retrieval ranks
tools on `tool_index.BUILTIN_TOOL_DESCRIPTIONS`, which did not name it either
(filed by `wb-graph`, closed at the merge). This holds them to the schema, read
from the live objects the agent loop serves, not from any file's text
(`Law 20`)."""
import re

from src.agent_loop import TOOL_SECTIONS
from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS


def _schema_actions() -> list[str]:
    for schema in FUNCTION_TOOL_SCHEMAS:
        fn = schema.get("function") or {}
        if fn.get("name") == "manage_tasks":
            return list(fn["parameters"]["properties"]["action"]["enum"])
    raise AssertionError("manage_tasks is not in FUNCTION_TOOL_SCHEMAS")


def test_the_text_mode_line_names_every_action_the_schema_offers():
    line = TOOL_SECTIONS["manage_tasks"]
    m = re.search(r'"action":\s*"([a-z_|]+)"', line)
    assert m, line
    offered = m.group(1).split("|")
    assert offered == _schema_actions(), (offered, _schema_actions())


def test_dry_run_is_among_them_and_retrieval_can_find_it():
    assert "dry_run" in _schema_actions()
    assert "dry_run" in BUILTIN_TOOL_DESCRIPTIONS["manage_tasks"]
