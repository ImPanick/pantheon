# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2175`: functions that were written twice with the same body are one now.

Each pair below had the same AST in two modules (the Nov 14 pipeline review's
list, re-audited on `ba5c65c4`, plus Apollo's two tool parsers). One copy is
the definition; the other module imports it under its old name, so every
caller, and every test that patches the name, keeps working.

Kept on purpose, and why (`D-2026-11-24-02`): `local_browser.may_use` and
`workstation_access.may_use` share a body but read different privileges
(`can_use_browser`, `can_use_workstation`); `core.middleware.runs_instance`
and `workstation_routes._caller_runs_instance` are left while open PRs #85 and
#89 change `workstation_routes.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_apollos_two_tools_read_their_arguments_one_way():
    from src.apollo import fleet_tool, tool

    assert fleet_tool.parse is tool.parse
    assert fleet_tool.parse("status") == {"action": "status"}
    assert fleet_tool.parse('{"action": "hand_off"}') == {"action": "hand_off"}
    assert fleet_tool.parse("[1]") == {} and fleet_tool.parse("") == {}


def test_the_lan_setting_is_read_one_way():
    from src import outbound_fetch
    from src.agent_tools import network_tools

    assert network_tools.lan_reach_on is outbound_fetch._lan_reach_on


def test_the_mlx_shim_rule_is_written_once():
    from routes import model_routes
    from src import endpoint_resolver

    assert model_routes._filter_mlx_deepseek_v4_repo_when_shimmed is \
        endpoint_resolver._filter_mlx_deepseek_v4_repo_when_shimmed
    assert model_routes._is_mlx_deepseek_v4_shim_id is endpoint_resolver._is_mlx_deepseek_v4_shim_id
    shim = "/home/a/.cache/pantheon/mlx-shims/deepseek-v4-flash"
    ids = ["mlx-community/DeepSeek-V4-Flash-4bit", shim, "other"]
    assert model_routes._filter_mlx_deepseek_v4_repo_when_shimmed(ids) == [shim, "other"]
    assert model_routes._filter_mlx_deepseek_v4_repo_when_shimmed(ids[:1]) == ids[:1]


def test_background_tasks_are_held_by_one_helper():
    from routes import chat_helpers
    from src import background_tasks, builtin_mcp

    assert chat_helpers._spawn_bg is builtin_mcp._spawn_bg is background_tasks.spawn_tracked
    assert builtin_mcp._BG_TASKS is background_tasks.BACKGROUND_TASKS


@pytest.mark.parametrize("argv, flag, value, after", [
    (["serve", "--port", "1"], "--port", "2", ["serve", "--port", "2"]),
    (["serve", "--port=1"], "--port", "2", ["serve", "--port=2"]),
    (["serve", "--port"], "--port", "2", ["serve", "--port", "2"]),
    (["serve"], "--port", "2", ["serve", "--port", "2"]),
    (["serve", "--porty", "1"], "--port", "2", ["serve", "--porty", "1", "--port", "2"]),
])
def test_setting_a_serve_flag_reads_as_it_did(argv, flag, value, after):
    from routes.cookbook_helpers import set_argv_flag

    set_argv_flag(argv, flag, value)
    assert argv == after


def test_neither_serve_normaliser_writes_its_own_set_flag_loop():
    for rel in ("routes/cookbook_helpers.py", "routes/cookbook_routes.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "set_flag":
                assert not any(isinstance(n, ast.For) for n in ast.walk(node)), (
                    f"{rel}:{node.lineno} writes set_flag's loop again; call set_argv_flag")
