# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1700` — in the workstation, a file the run wrote inside a folder it
copied with `cp -a`/`-r` is still its own afterwards.

Measured before the fix: `cp -a template proj && echo x > proj/README.md`
ran with no card, and then `echo y > proj/README.md` was refused under a
hire's never — *a > redirect replaces proj/README.md in your workstation,
which was there before this run began* — though the run had made that file
itself. `B1696`'s `_linked` dropped every name under a deep copy from the
run's record (the cautious reading: the daemon says whether a name is a
link, not its text), where on this machine, whose record is kept by real
path, only a name a copied link points through is ever looked at again.

Now (`src/run_files.py`, `_copies_linked`): under a folder a copy makes, of
the names the run holds as its own (`RunFiles._held_in_workstation`), only
those whose own source has a symbolic link on the way (`_copied`, every
step asked of the daemon in one round) are dropped — as on this machine. A
name whose source is a link, or sits under one, is still looked at again.

Driven (`Law 20`): the real workstation daemon running real `cp` and `bash`
under a hire's never, through the real gate and dispatcher; and the same
commands on this machine, for parity.
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid

import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.run_files import RunFiles
from src.tool_capabilities import ToolRunSecurityContext, call_destroys
from tests.test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _home, _on, people, settings, ws,
)

NOTES = "Ana's notes — keep these"
THERE = "which was there before this run began"


def _template(root) -> None:
    """A template folder: a page, a link to the person's notes, and a link
    to a folder holding a page."""
    (root / "notes.md").write_text(NOTES, encoding="utf-8")
    (root / "shared").mkdir()
    (root / "shared" / "style.css").write_text("body {}", encoding="utf-8")
    t = root / "template"
    t.mkdir()
    (t / "README.md").write_text("# a template", encoding="utf-8")
    (t / "notes").symlink_to("../notes.md")
    (t / "assets").symlink_to("../shared")


def test_in_the_workstation_the_runs_own_file_in_a_copy_stays_its_own(ws, settings, people):
    """The row's `Verify:`: `cp -a template proj && echo x > proj/README.md`,
    then `echo y > proj/README.md`, runs with no card in the workstation —
    and a name in the copy whose source is a link, or under one, the run
    had found nothing at, is looked at again and refused."""
    _on(settings, ws)
    files = RunFiles(None, "ann", session_id=f"s-{uuid.uuid4().hex[:8]}")
    assert files.in_workstation("bash")
    run = ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=files,
                                 approval_gate_bypassed=True)
    home = _home(ws, "ann")
    home.mkdir(parents=True, exist_ok=True)
    _template(home)

    def bash(command: str) -> dict:
        async def go():
            await files.look("bash", command)
            return (await te.execute_tool_block(ToolBlock("bash", command), owner="ann",
                                                session_id=files.session_id,
                                                security_context=run))[1]
        return asyncio.run(go())

    # Looked at before the copy, nothing there: the run's own, if it writes them.
    for name in ("proj/notes", "proj/assets/style.css"):
        asyncio.run(files.look("bash", f"echo draft > {name}"))

    first = bash("cp -a template proj && echo x > proj/README.md")
    assert first.get("exit_code") == 0, first
    again = bash("echo y > proj/README.md")
    assert again.get("exit_code") == 0, again
    assert (home / "proj" / "README.md").read_text(encoding="utf-8") == "y\n"

    for name, target in (("proj/notes", "proj/notes"), ("proj/assets/style.css",
                                                         "proj/assets/style.css")):
        refused = bash(f"echo gone > {name}")
        assert refused.get("blocked") is True, (name, refused)
        assert f"(a > redirect replaces {target} in your workstation, {THERE})" in refused["error"]
    assert (home / "notes.md").read_text(encoding="utf-8") == NOTES
    assert (home / "shared" / "style.css").read_text(encoding="utf-8") == "body {}"


def test_on_this_machine_the_same_commands_read_the_same(tmp_path):
    """Parity: the run's record on this machine, kept by real path, keeps
    the file it wrote in its copy and looks again at a name a copied link
    points through."""
    _template(tmp_path)
    files = RunFiles(str(tmp_path), "boss", session_id=f"s-{uuid.uuid4().hex[:8]}")
    for name in ("proj/notes", "proj/assets/style.css"):
        assert call_destroys("bash", f"echo draft > {name}", files) is None
    first = "cp -a template proj && echo x > proj/README.md"
    assert call_destroys("bash", first, files) is None
    subprocess.run(["bash", "-c", first], cwd=tmp_path, check=True, timeout=30)
    assert call_destroys("bash", "echo y > proj/README.md", files) is None
    assert call_destroys("bash", "echo gone > proj/notes", files) == \
        f"a > redirect replaces proj/notes, {THERE}"
    assert call_destroys("bash", "echo gone > proj/assets/style.css", files) == \
        f"a > redirect replaces proj/assets/style.css, {THERE}"
