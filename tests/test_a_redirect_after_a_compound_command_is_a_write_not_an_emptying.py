# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1679` — a redirect after a compound command writes what it printed; it
does not only empty the file.

Measured before the fix: `call_destroys('bash', 'for f in a b; do echo $f;
done > new.txt')` said *it empties new.txt* for a path that was not there, and
so did `if …; fi > x`, `{ …; } > x` and `( … ) > x`: the reader stripped the
closing word (`done`, `fi`, `}`) — or met the redirect alone after a `)` — and
read what was left as `: > list.txt`, a redirection with no command, which
`B1622` reads as emptying a file whatever was there. So a hire's
`destructive: never` refused a loop that wrote a new file, and Auto asked
before it. And `case … esac > x` was not read at all: the `esac` line, with
its redirect, was dropped.

Now each is `B1669`'s reading of a `>`: onto a path that was not there before
the run it is a plain write, onto a file that was there it is destructive and
names it. `: > log` and `> log` alone still empty the file, as `B1622` reads
them.

Driven (`Law 20`): the real reader and the run's record over a real folder,
and the real gate and dispatcher running the real shell under a hire's
`destructive: never`.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.run_files import RunFiles
from src.tool_capabilities import ToolRunSecurityContext, call_destroys
from tests.test_the_agents_hands_are_in_the_workstation import people  # noqa: F401 — fixture

THERE = "which was there before this run began"
LOOP = "for f in a b; do echo $f; done"
#: Each compound command, ending where its redirect goes.
COMPOUND = (LOOP, "if true; then echo a; fi", "{ echo a; echo b; }", "(echo a; echo b)",
            "case x in x) echo a;; esac", "while false; do :; done")


@pytest.fixture
def folder(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "list.txt").write_text("the person's list", encoding="utf-8")
    return ws


def _files(folder: Path) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}")


def test_a_redirect_after_a_compound_command_onto_a_new_path_is_a_plain_write(folder):
    for command in COMPOUND:
        assert call_destroys("bash", f"{command} > new.txt", _files(folder)) is None, command


def test_onto_a_file_that_was_there_it_is_destructive_and_says_so(folder):
    for command in COMPOUND:
        assert call_destroys("bash", f"{command} > list.txt", _files(folder)) == \
            f"a > redirect replaces list.txt, {THERE}", command


def test_a_redirect_with_no_command_still_empties_the_file(folder):
    """`B1622`'s reading of a redirection alone stands — at the top, after an
    opening word, as a case arm's command, and after an assignment."""
    for command in (": > new.txt", "> new.txt", "X=1 > new.txt", "if > new.txt; then :; fi",
                    "case y in y) > new.txt;; esac"):
        assert call_destroys("bash", command, _files(folder)) == "it empties new.txt", command


def _bash(run: ToolRunSecurityContext, folder: Path, command: str) -> dict:
    async def go():
        return await te.execute_tool_block(ToolBlock("bash", command), owner="boss",
                                           session_id=run.files.session_id, workspace=str(folder),
                                           security_context=run)
    return asyncio.run(go())[1]


def test_a_hires_never_runs_the_loop_into_a_new_file_and_refuses_it_over_the_persons(folder, people):
    """The real shell: the loop writes a new file under a `destructive: never`;
    the same loop onto the person's list is refused, naming it, and the list
    stays."""
    run = ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=_files(folder))
    made = _bash(run, folder, f"{LOOP} > new.txt")
    assert made.get("exit_code") == 0, made
    assert (folder / "new.txt").read_text(encoding="utf-8") == "a\nb\n"
    refused = _bash(run, folder, f"{LOOP} > list.txt")
    assert refused.get("blocked") is True, refused
    assert f"(a > redirect replaces list.txt, {THERE})" in refused["error"]
    assert (folder / "list.txt").read_text(encoding="utf-8") == "the person's list"
