# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1381`: a skill whose `requires_toolsets` names a tool with no prompt
section reaches the prompt's skill index.

`_build_base_prompt` handed `SkillsManager.index_for` the turn's
`active_toolsets` as `TOOL_SECTIONS.keys()` minus the cap, and `index_for`
drops a skill whose requirements are not wholly inside that list. Thirteen
register names (measured on `0bd089d`; more since) have no section — `ls`,
`grep`, `glob`, `host_shell`, `api_call`, … — so a skill declaring
`requires_toolsets: [ls, grep, read_file]`, an ordinary file-sweep procedure,
was saved, listed in the Skills window and indexed for nobody, in silence.

The gate now reads the callable register (`selectable_tool_names()`),
filtered by the turn's cap — so nothing widens past what the turn may call.
Driven through the real `_build_base_prompt` and a real skill store.
"""
import src.agent_loop as agent_loop
import src.constants as constants
from services.memory.skills import SkillsManager


def _store(tmp_path):
    sm = SkillsManager(str(tmp_path))
    sm.add_skill(
        name="folder-sweep",
        description="Sweep a folder for a pattern and read what matched.",
        category="files",
        when_to_use="When asked to find something across the files in a folder.",
        procedure=["List the folder.", "Grep for the pattern.", "Read the matches."],
        requires_toolsets=["ls", "grep", "read_file"],
        status="published",
        source="user",
        owner=None,
    )
    return sm


def _index_block(monkeypatch, tmp_path, disabled):
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path))
    _prompt, block = agent_loop._build_base_prompt(
        disabled_tools=set(disabled),
        mcp_mgr=None,
        needs_admin=False,
        relevant_tools={"ls", "grep", "read_file", "ask_user"},
        compact=False,
        owner=None,
    )
    return block


def test_the_premise_ls_and_grep_have_no_prompt_section():
    assert "ls" not in agent_loop.TOOL_SECTIONS
    assert "grep" not in agent_loop.TOOL_SECTIONS


def test_a_file_sweep_skill_is_in_the_index_a_turn_is_given(monkeypatch, tmp_path):
    _store(tmp_path)
    block = _index_block(monkeypatch, tmp_path, disabled=())
    assert "folder-sweep" in block, block[:600]


def test_a_turn_that_cannot_call_grep_is_still_not_given_it(monkeypatch, tmp_path):
    """The gate did not open: the cap still decides (`FORBIDDEN.md` Part 2)."""
    _store(tmp_path)
    block = _index_block(monkeypatch, tmp_path, disabled={"grep"})
    assert "folder-sweep" not in block
