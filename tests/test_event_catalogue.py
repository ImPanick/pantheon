# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-30` — one catalogue of trigger events, and the one that was fired and never listed.

Before this there were two enumerations — the `/meta/events` route and the
`manage_tasks` tool schema — plus five loose strings in `HOUSEKEEPING_DEFAULTS`
and two more in the email MCP server. `document_updated` was fired in
production by one of those loose sites and appeared in neither enumeration, so
no task could ever trigger on it: the picker did not offer it and the tool
schema rejected it.

The rule this file holds is the one a merge is for: **an event that can be
fired is an event that can be chosen.** It is checked by walking the tree for
`fire_event("…")` call sites rather than against a list written here, because a
list written here is the sixth spelling (`Law 13`, `Law 14`).
"""

import ast
import subprocess
from pathlib import Path

import pytest

from src.event_bus import EVENT_CATALOGUE, EVENT_NAMES, DEFAULT_TRIGGER_COUNT

ROOT = Path(__file__).resolve().parent.parent


def _fired_event_names() -> set[str]:
    """Every literal name handed to `fire_event(...)` in tracked source."""
    files = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT,
        capture_output=True, text=True, check=True).stdout.split()
    names: set[str] = set()
    for rel in files:
        if rel.startswith("tests/") or rel.startswith(".pantheon/"):
            continue
        try:
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            fname = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if fname != "fire_event":
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                names.add(arg.value)
            elif isinstance(arg, ast.Name):
                # A module constant — resolve it through the registry, which is
                # where every such constant is defined.
                import src.event_bus as eb
                value = getattr(eb, arg.id, None)
                if isinstance(value, str):
                    names.add(value)
    return names


def test_every_event_the_product_fires_can_be_triggered_on():
    fired = _fired_event_names()
    assert fired, "found no fire_event call sites — the walk is broken, not the tree"
    unlistable = fired - set(EVENT_NAMES)
    assert not unlistable, (
        "fired in production and in no catalogue, so nothing can trigger on it: "
        f"{sorted(unlistable)}"
    )


def test_document_updated_is_in_the_catalogue():
    """Named, because it is the one the row is about."""
    assert "document_updated" in EVENT_NAMES


def test_the_catalogue_entries_are_all_usable():
    seen = set()
    for entry in EVENT_CATALOGUE:
        assert entry["name"] and entry["description"], entry
        assert entry["name"] not in seen, f"duplicate: {entry['name']}"
        seen.add(entry["name"])


def test_the_seven_stored_names_are_unchanged():
    """`FORBIDDEN.md` Part 1: these are stored in `trigger_event`. Renaming one
    silently disables every task using it. Adding an eighth is fine."""
    assert {
        "session_created", "message_sent", "document_created", "memory_added",
        "research_completed", "email_received", "skill_added",
    } <= set(EVENT_NAMES)


def test_the_tool_schema_reads_the_registry():
    """`manage_tasks` is the model's way in. Its enum was the second copy."""
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

    schema = next(
        s for s in FUNCTION_TOOL_SCHEMAS
        if s["function"]["name"] == "manage_tasks"
    )
    enum = schema["function"]["parameters"]["properties"]["trigger_event"]["enum"]
    assert list(enum) == list(EVENT_NAMES)


def test_the_housekeeping_defaults_name_the_registry_not_a_string():
    """The five loose spellings. Checked as values, so a rename cannot pass."""
    from src.task_scheduler import HOUSEKEEPING_DEFAULTS

    used = {
        d["trigger_event"] for d in HOUSEKEEPING_DEFAULTS.values()
        if d.get("trigger_event")
    }
    assert used, "no event-triggered housekeeping defaults left to check"
    assert used <= set(EVENT_NAMES)


@pytest.mark.asyncio
async def test_the_meta_route_serves_the_registry():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import routes.task_routes as task_routes

    router = task_routes.setup_task_routes(MagicMock())
    events = next(
        r.endpoint for r in router.routes
        if getattr(r, "path", None) == "/api/tasks/meta/events"
    )
    out = await events(SimpleNamespace(state=SimpleNamespace(current_user=None)))
    assert [e["name"] for e in out["events"]] == list(EVENT_NAMES)


def test_an_event_task_fires_every_event_by_default():
    """`P8-31`. One is the default because it is what the word `trigger` means
    to anyone arriving from a workflow tool."""
    assert DEFAULT_TRIGGER_COUNT == 1
