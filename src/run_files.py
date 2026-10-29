# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a run knows about the files it writes, and whether a `write_file`
replaces one that was there before it began. `B1660`.

A leaf: the loop makes a holder per turn and hands it to the gate
(`ToolRunSecurityContext.files`) and to each tool call (`bind_run_files`);
`write_file` notes what it made, and the gate asks `replaces`.
"""
from __future__ import annotations

import json
import logging
import os
import posixpath
from contextvars import ContextVar
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

# ── `B1660` · writing over a file that was there is an overwrite ────────────
#
# `write_file` is registered `write_workspace` and nothing else, so a call that
# replaced a file the person had — their notes, a page, a config — carried no
# `destructive`, while a shell `mv` over the same file did (`B1622`). A hire's
# `destructive: ask`/`never` and Auto's one exception (`B1341`: *"Auto runs
# everything without asking, except what cannot be undone"*) never covered it.
#
# The owner's ruling (`D-2026-10-29-02` §1), *"Only pre-existing files"*: a
# `write_file` onto a path that held a file **before the run began** carries
# `destructive` as well; a file the same run made and then rewrites is a plain
# write — an agent iterating on its own draft is not asked each pass; and where
# "was it there before the run" cannot be known, it is destructive.
#
# **The run.** A hired run, or a chat's turn — one `stream_agent_loop` — and the
# runs that resume it from an approval card, which carry this record forward
# on the card's paused turn (`PausedTurn.files`): a yes to a rewrite of the
# run's own draft is claimed by the run that resumes, and that run must read
# the call as the run that asked did, or the seal does not match.
#
# **What the run knows.** The files `write_file` made in it (`note_made`, from
# the tool, which alone knows the path was empty when it wrote). A file made
# another way — a shell's `>` or `touch`, a patch's added file, a saved
# attachment — is not on the record, so writing over it is read as writing over
# a file that was there: the cautious reading, which asks more and never less.
#
# **Where the file is.** On this machine the path is resolved as the tool will
# resolve it (the run's workspace, `_resolve_tool_path_in_workspace`) and looked
# at. In the person's workstation (`P20-03`) it cannot be looked at from the
# gate, which is not async, so the loop asks the workstation before it
# classifies the call (`look`) and the answer is kept here; a path it could not
# ask about is destructive.
#
# **The adversary (`Law 17`)** is a mistake — a model rewriting the person's
# file on its own reading of a job — and a naive injection that asks for one.
# This only ever adds `destructive`, so every gate asks more, never less; the
# post-external gate, which asks before every write once outside content is in
# the run (`FORBIDDEN.md` Part 2), is untouched.

#: Where a file the gate cannot look at lives: the person's workstation.
IN_WORKSTATION = "workstation"


class RunFiles:
    """The files this run made, and what it saw in the workstation."""

    def __init__(self, workspace: Optional[str] = None, owner: Optional[str] = None,
                 carried: Optional[Mapping[str, Any]] = None):
        self.workspace = workspace or None
        self.owner = owner
        carried = carried if isinstance(carried, Mapping) else {}
        # Keys (`key`) of the files `write_file` made in this run.
        self.made: set = set(carried.get("made") or ())
        # Workstation keys → whether a file was there when the run looked.
        self.seen: dict = {k: bool(v) for k, v in dict(carried.get("seen") or {}).items()}

    def carried(self) -> dict:
        """What a run resumed from this run's card starts with."""
        return {"made": sorted(self.made), "seen": dict(self.seen)}

    def in_workstation(self) -> bool:
        """Does this run's `write_file` run in the person's workstation?"""
        try:
            from src.agent_tools import workstation_tools
            return workstation_tools.routes("write_file", self.owner)
        except Exception:  # noqa: BLE001 — unreadable routing is read as this machine
            logger.debug("B1660: could not tell where write_file runs", exc_info=True)
            return False

    def key(self, raw_path: str, where: Optional[str] = None) -> Optional[str]:
        """The one name for `raw_path` that the tool notes and the gate asks
        about. On this machine, the path the tool will write — `None` when the
        tool refuses it (outside the workspace, a sensitive file), which writes
        nothing. In the workstation, the path as the call names it, under the
        workspace the call is given (the workstation resolves it)."""
        if where == IN_WORKSTATION:
            text = str(raw_path or "").strip()
            return f"{IN_WORKSTATION}:{self.workspace or ''}:{posixpath.normpath(text)}" if text else None
        return _local_path(raw_path, self.workspace)

    def note_made(self, raw_path: str, where: Optional[str] = None) -> None:
        key = self.key(raw_path, where)
        if key:
            self.made.add(key)

    async def look(self, tool_name: Any, content: Any) -> None:
        """`write_file` in the workstation: ask it whether the path holds a
        file, before the call is classified, and keep the answer for the run.
        Anything that goes wrong leaves the path unknown — destructive."""
        if tool_name != "write_file" or not self.in_workstation():
            return
        raw = target(content)
        key = self.key(raw, IN_WORKSTATION)
        if not key or key in self.made or key in self.seen:
            return
        try:
            from src.agent_tools.workstation_tools import held_a_file
            there = await held_a_file(raw, owner=self.owner, workspace=self.workspace)
        except Exception:  # noqa: BLE001 — unknown, and so destructive
            logger.debug("B1660: could not ask the workstation about %r", raw, exc_info=True)
            there = None
        if there is not None:
            self.seen[key] = bool(there)


def _local_path(raw_path: Any, workspace: Optional[str]) -> Optional[str]:
    """The path `WriteFileTool` writes for `raw_path` in this workspace, or
    `None` when it refuses the path — its own resolver, asked the same way."""
    from src.tool_execution import _resolve_tool_path, _resolve_tool_path_in_workspace
    try:
        if workspace:
            return _resolve_tool_path_in_workspace(workspace, raw_path)
        return _resolve_tool_path(raw_path)
    except (ValueError, TypeError, OSError):
        return None


def target(content: Any) -> str:
    """The path a `write_file` call names, read as the tool reads it."""
    from src.agent_tools.filesystem_tools import _write_file_args
    if isinstance(content, Mapping):
        content = json.dumps(dict(content))
    if not isinstance(content, str):
        return ""
    return _write_file_args(content)[0]


def replaces(content: Any, files: Optional[RunFiles] = None) -> Optional[str]:
    """Why this `write_file` call carries `destructive` — the file it replaces,
    or why that cannot be known — or `None`: it makes a new file, rewrites one
    this run made, or names a path the tool refuses (which writes nothing).

    `files` is the run's record. Without one (a caller outside any run) the
    path is resolved as the tool would resolve it here and now, and nothing is
    known to be the run's own."""
    raw = target(content)
    if not raw.strip():
        return None   # the tool refuses it: "path is required"
    shown = raw.strip()
    files = files if isinstance(files, RunFiles) else None
    if files is not None and files.in_workstation():
        key = files.key(raw, IN_WORKSTATION)
        if key in files.made:
            return None
        there = files.seen.get(key)
        if there is False:
            return None
        if there is True:
            return f"write_file replaces {shown} in your workstation, which was there before this run began"
        return (f"it cannot be known whether {shown} in your workstation was there before this "
                f"run began")
    path = files.key(raw) if files is not None else _local_path(raw, None)
    if path is None:
        return None
    if files is not None and path in files.made:
        return None
    try:
        if not os.path.exists(path) or os.path.isdir(path):
            # Nothing there, or a folder (`open(…, "w")` refuses it): nothing replaced.
            return None
    except OSError:
        return f"it cannot be known whether {shown} was there before this run began"
    return f"write_file replaces {shown}, which was there before this run began"


# The holder for the tool call about to run — `B1415`'s shape: each call runs
# in a copy of the loop's context, so a mutable holder is what the next call
# (and the gate, which holds the same object) sees.
_run_files: ContextVar = ContextVar("pantheon_run_files", default=None)


def bind_run_files(holder: Optional[RunFiles]) -> None:
    """Bind the run's file record for the tool call about to run."""
    _run_files.set(holder)


def note_made(raw_path: str, where: Optional[str] = None) -> None:
    """`write_file` made `raw_path`: it was not there, and now this run's
    writing over it is a plain write. Nothing outside a run."""
    holder = _run_files.get()
    if holder is not None:
        holder.note_made(raw_path, where)
