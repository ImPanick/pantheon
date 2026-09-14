# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B18` — six test files stub `src.agent_tools` and the full suite never noticed.

The row said running `tests/test_agent_loop.py` first broke about 51 tests in
six other files. **That premise was wrong about the cause and low about the
cost.** `test_agent_loop.py` cleans up after itself (`:18-51`) and breaks
nothing; measured today, prepending it changes the failure set by zero tests.

The real poisoners are six files that replace `sys.modules["src.agent_tools"]`
with a bare `MagicMock` at MODULE scope, guarded on `if mod not in
sys.modules`, and never restore it. A mock there is not one broken import:
`src/agent_loop.py:64-76`, `src/tool_parsing.py:16` and `src/tool_schemas.py:17`
bind `TOOL_TAGS`, `ToolBlock` and `parse_tool_blocks` **by value** at import,
so the mock is baked into three more modules for the rest of the process.

**The full suite is green for one accidental reason.** Collection imports every
test module before the first test runs, and
`tests/test_a_refused_call_leaves_a_trace.py` sorts first in root collection
order and imports the real `src.agent_tools` — which makes every `if mod not in
sys.modules` guard downstream dead code. Any subset re-arms all six: a shard, a
`-k`, a `--lf`, a hand-written file list.

And a subset did not merely fail. With `parse_tool_blocks` a mock the agent
loop's exit condition is never satisfied, and `src/agent_loop.py:4134` lifts a
caller's explicit `max_rounds=2` to 100,000 for a local endpoint — so twelve
tests in `test_external_context_tool_gate.py` ran to that cap and the process
was OOM-killed at 6 GB. The row counted 51 failures; what was actually there
was 6 failures and 12 runaway processes.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# The six files that stub `src.agent_tools` at module scope, and two victims.
POISONERS = (
    "tests/test_tool_output_prompt_injection.py",
    "tests/test_prompt_injection_audit.py",
)
VICTIMS = (
    "tests/test_tool_path_confinement.py",
    "tests/test_tool_approvals.py",
)


def test_agent_tools_is_the_real_module_during_this_session():
    """The invariant, stated where a reader will look for it.

    A stub has no `__file__`. This is an observation about the loaded object,
    not a search of anybody's source (`Law 20`).
    """
    module = sys.modules["src.agent_tools"]
    assert getattr(module, "__file__", None), "src.agent_tools is a stub"


@pytest.mark.parametrize("name", [
    "src.agent_tools", "src.tool_parsing", "src.tool_schemas",
    "core.models", "core.database", "src.database",
])
def test_no_watched_module_is_a_stub(name):
    module = sys.modules.get(name)
    if module is None:
        pytest.skip(f"{name} not loaded in this selection")
    assert getattr(module, "__file__", None), f"{name} is a stub"


def test_the_values_the_mock_used_to_replace_are_real_objects():
    """`TOOL_TAGS` and friends are bound by value, so checking the module is
    not enough — the bindings are what a mock actually poisons."""
    from src import agent_loop, tool_parsing
    assert isinstance(agent_loop.TOOL_TAGS, (set, frozenset))
    assert isinstance(tool_parsing.TOOL_TAGS, (set, frozenset))
    assert callable(agent_loop.parse_tool_blocks)
    assert isinstance(agent_loop.MAX_AGENT_ROUNDS, int)


def test_the_guard_fires_on_a_stub_rather_than_letting_it_through():
    """Exercise the hook itself, with a stub planted and then removed.

    Without this, the pre-import is a line nobody would notice going missing —
    which is how the six poisoners got there in the first place.
    """
    import types

    import conftest

    planted = types.ModuleType("src.tool_parsing")  # a module with no __file__
    real = sys.modules["src.tool_parsing"]
    sys.modules["src.tool_parsing"] = planted
    try:
        with pytest.raises(pytest.UsageError) as caught:
            conftest.pytest_collection_finish(session=None)
        assert "src.tool_parsing" in str(caught.value)
        assert "B18" in str(caught.value)
    finally:
        sys.modules["src.tool_parsing"] = real

    # And it stays quiet when everything is real.
    conftest.pytest_collection_finish(session=None)


def test_a_two_file_subset_is_the_same_suite_as_the_whole():
    """The row's actual subject, run as a subprocess because that is the only
    way to observe a collection-order defect from inside a session that has
    already collected."""
    selection = list(POISONERS) + list(VICTIMS)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", *selection],
        cwd=str(ROOT), capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert " failed" not in result.stdout
