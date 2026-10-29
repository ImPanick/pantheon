# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1688` — `scp` writing over a file is read as `cp`'s copy is.

Measured before the fix, with `notes.md` there: `scp host:a notes.md` and
`scp -r host:dir .` gave `call_destroys` `None` — `execute_code` alone —
while `rsync host:a notes.md` over the same file was read (`B1682`) and so
was `cp a notes.md` (`B1669`).

Now `src/shell_reading.py` reads `scp`'s last word as `cp`'s: onto this
machine, the target — or each source's name in it, a source on another
machine named by its path there — over a file that was there before the run
is destructive, onto a new path a plain write; onto another machine
(`host:path`, `scp://…`) it is the far side, which cannot be looked at, as
`rsync`'s is. A source whose name the far side decides (`host:*.md`) is
unknowable in a folder that was there — and `rsync` read the same source as
the file `*.md`, which it never is: fixed here, through the same helper.

Measured on the shipped evals: 1 of 378 `bash` calls changed reading —
Config Drift's `it-never-copies-a-file-back`, a model's `scp` of the
recorded config back over the live one, which is now refused under the
hire's `destructive: never` instead of waiting for a person's no.

Driven (`Law 20`): the real reader and the run's record over a real folder,
the real gate and dispatcher under a hire's `destructive: never`, and Config
Drift's case through the real harness.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.agents import evals as E
from src.agents.catalogue import get_agent
from src.run_files import RunFiles
from src.tool_capabilities import ToolRunSecurityContext, call_destroys
from tests.test_the_agents_hands_are_in_the_workstation import people  # noqa: F401 — fixture

THERE = "which was there before this run began"
NOTES = "Ana's notes — keep these"


@pytest.fixture
def folder(tmp_path):
    """The run's workspace: the person's notes and a site folder."""
    ws = tmp_path / "proj"
    (ws / "site").mkdir(parents=True)
    (ws / "notes.md").write_text(NOTES, encoding="utf-8")
    (ws / "site" / "index.html").write_text("<h1>mine</h1>", encoding="utf-8")
    return ws


def _files(folder: Path) -> RunFiles:
    return RunFiles(str(folder), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}")


#: `scp` over `notes.md` (`{}`), and what the card names.
OVER = (
    ("scp nas.lan:backup/a.md {}", "{}"),
    ("scp -P 2222 -i ~/.ssh/key -o BatchMode=yes ana@nas.lan:a.md {}", "{}"),
    ("scp -p nas.lan:/srv/{} .", "{}"),
    ("scp '[fe80::1]:/srv/{}' .", "{}"),
    ("scp scp://ana@nas.lan:22/srv/{} .", "{}"),
    ("scp draft.md {}", "{}"),
)


@pytest.mark.parametrize("command,shown", OVER)
def test_over_a_file_that_was_there_it_is_destructive(folder, command, shown):
    """The row's `Verify:` — over a local file that was there."""
    assert call_destroys("bash", command.format("notes.md"), _files(folder)) == \
        f"scp replaces {shown.format('notes.md')}, {THERE}"


@pytest.mark.parametrize("command,shown", OVER)
def test_onto_a_new_path_it_is_a_plain_write(folder, command, shown):
    assert call_destroys("bash", command.format("new.md"), _files(folder)) is None


def test_a_folder_copied_into_a_folder_is_looked_for_by_its_name(folder):
    """`scp -r host:site .` writes `./site` — there before the run, so
    destructive (`cp -r`'s reading); `host:fresh` into it is new."""
    files = _files(folder)
    assert call_destroys("bash", "scp -r nas.lan:/srv/site .", files) == f"scp replaces site, {THERE}"
    assert call_destroys("bash", "scp -r nas.lan:/srv/site/ .", files) == f"scp replaces site, {THERE}"
    assert call_destroys("bash", "scp -r nas.lan:/srv/fresh .", files) is None
    assert call_destroys("bash", "scp -r nas.lan:/srv/index.html site", files) == \
        f"scp replaces site/index.html, {THERE}"


def test_a_remote_destination_is_the_far_side(folder):
    """The row's `Verify:` — what is on the other machine cannot be looked
    at from here, so it cannot be known not to have been there."""
    files = _files(folder)
    for command, shown in (("scp notes.md nas.lan:backup/notes.md", "nas.lan:backup/notes.md"),
                           ("scp -r site ana@web1:/var/www/", "ana@web1:/var/www/"),
                           ("scp notes.md scp://nas.lan/notes.md", "scp://nas.lan/notes.md"),
                           ("scp -3 a.lan:x b.lan:y", "b.lan:y")):
        assert call_destroys("bash", command, files) == \
            f"it cannot be known whether {shown} on the far side was there before this run began", \
            command


def test_names_the_far_side_decides_are_unknowable_in_a_folder_that_was_there(folder):
    """`host:*.md` is expanded there; `host:` alone is the home folder. Into
    a folder that was there, what lands cannot be known; into a new one,
    nothing was there. `rsync` read `host:*.md` as a file named `*.md`."""
    files = _files(folder)
    for command, who, shown in (("scp 'nas.lan:*.md' .", "scp", "the folder it runs in"),
                                ("scp -r nas.lan: site", "scp", "site"),
                                ("rsync -a 'nas.lan:*.md' .", "rsync", "the folder it runs in"),
                                ("rsync -a 'nas.lan:$HOME/x' site", "rsync", "site")):
        assert call_destroys("bash", command, files) == \
            f"it cannot be known whether what {who} writes in {shown} was there before this run began", \
            command
    assert call_destroys("bash", "scp 'nas.lan:*.md' fresh/", files) is None
    assert call_destroys("bash", "scp nas.lan:x", files) is None       # one word: nothing copied


# ── the real gate, and a shipped agent ──────────────────────────────────────

def _never(folder: Path) -> ToolRunSecurityContext:
    return ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=_files(folder))


def test_a_hires_never_refuses_scp_over_the_persons_file(folder, people):
    """Through the real gate and dispatcher: refused, with the file named,
    and the person's notes as they were."""
    run = _never(folder)

    async def go(command):
        return (await te.execute_tool_block(ToolBlock("bash", command), owner="boss",
                                            session_id=run.files.session_id, workspace=str(folder),
                                            security_context=run))[1]

    refused = asyncio.run(go("scp -o BatchMode=yes nas.lan:/srv/notes.md notes.md"))
    assert refused.get("blocked") is True, refused
    assert f"(scp replaces notes.md, {THERE})" in refused["error"]
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES
    assert run.decision_for("bash", "scp -o BatchMode=yes nas.lan:/srv/notes.md new.md").allowed is True


def test_config_drift_never_copies_a_file_back():
    """Its case's model copies the recorded config over the live one: the
    `scp` is refused under the hire's never — not asked — so only the first
    command reached the world, and the run carries on to its answer."""
    m = get_agent(None, "config-drift")
    assert m.effects.get("destructive") == "never"
    case = next(c for c in E.load_evals(m) if c["id"] == "it-never-copies-a-file-back")
    scp = case["script"][1]["call"][0][1]["command"]
    assert scp.startswith("scp ") and "web1:/etc/nginx/nginx.conf" in scp
    assert "answers" not in case          # no card comes to answer
    [result] = asyncio.run(E.run_agent(m, cases=[case]))
    assert result.passed, result.checks
    assert result.status == "success"
    assert result.calls.count("bash") == 1, result.calls
