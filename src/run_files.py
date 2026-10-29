# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a run knows about the files it writes, and whether a `write_file`
replaces one that was there before it began. `B1660`. And whether a shell
command's `>`, `tee`, `cp` or `install` does (`B1669`, `command_replaces`).

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
# another way — a shell's `touch`, a patch's added file, a saved attachment — is
# not on the record, so writing over it is read as writing over a file that was
# there: the cautious reading, which asks more and never less. (`B1669`: a path
# a command's `>`, `tee` or `cp` names is — what the run saw there the first
# time it looked, `kinds` — so a file the run's own `>` made is its own to
# either tool.)
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

#: `B1669`. The tools whose commands run in the chat's shell folder — on this
#: machine, or in the workstation — so the run can look where they write.
SHELL_TOOLS = frozenset({"bash", "python"})
#: `B1669`. What is at a path: a file, a folder, or nothing.
FILE, FOLDER, NOTHING = "file", "folder", "none"


class RunFiles:
    """The files this run made, and what it saw in the workstation."""

    def __init__(self, workspace: Optional[str] = None, owner: Optional[str] = None,
                 carried: Optional[Mapping[str, Any]] = None, session_id: Optional[str] = None):
        self.workspace = workspace or None
        self.owner = owner
        # `B1669`: the chat, whose shell keeps its folder between calls (`B962`).
        self.session_id = session_id or None
        carried = carried if isinstance(carried, Mapping) else {}
        # Keys (`key`) of the files `write_file` made in this run.
        self.made: set = set(carried.get("made") or ())
        # Workstation keys → whether a file was there when the run looked.
        self.seen: dict = {k: bool(v) for k, v in dict(carried.get("seen") or {}).items()}
        # `B1669`. What was at each path a shell command writes over the first
        # time this run looked (`FILE`, `FOLDER`, `NOTHING`), so "there before
        # this run began" is what was there before the run touched it: a file
        # the run's own `>` made is its own draft on the next pass.
        self.kinds: dict = {k: str(v) for k, v in dict(carried.get("kinds") or {}).items()}
        # `B1669`. In the workstation, each command's answer as the run worked
        # it out there (`look`): the sentence, or "" for nothing replaced.
        self.said: dict = {k: str(v) for k, v in dict(carried.get("said") or {}).items()}

    def carried(self) -> dict:
        """What a run resumed from this run's card starts with."""
        return {"made": sorted(self.made), "seen": dict(self.seen),
                "kinds": dict(self.kinds), "said": dict(self.said)}

    def in_workstation(self, tool: str = "write_file") -> bool:
        """Does this run's `tool` run in the person's workstation?"""
        try:
            from src.agent_tools import workstation_tools
            return workstation_tools.routes(tool, self.owner)
        except Exception:  # noqa: BLE001 — unreadable routing is read as this machine
            logger.debug("B1660: could not tell where %s runs", tool, exc_info=True)
            return False

    def shell_starts(self) -> list:
        """`B1669`. Where this run's next command on this machine starts: the
        folder its chat's shell was left in (`B962`), and the folder a shell
        starts in when none is held — the run's workspace, else the agent's
        own (`subprocess_tools.host_start_folder`, asked without moving it).
        Both, because a held folder that is gone starts the command in the
        other."""
        from src.agent_tools.subprocess_tools import CHAT_FOLDERS, chat_key
        from src.tool_execution import _AGENT_WORKDIR
        start = self.workspace or _AGENT_WORKDIR
        held = CHAT_FOLDERS.peek(chat_key("host", self.owner, self.session_id), start)
        return list(dict.fromkeys(f for f in (held, start) if f))

    def kind(self, path: str) -> Optional[str]:
        """`B1669`. What was at `path` on this machine the first time this run
        looked — a file `write_file` made is the run's own — or `None` when it
        cannot be looked at."""
        key = _real(path)
        if key is None:
            return None
        if key in self.made:
            return NOTHING
        if key not in self.kinds:
            found = _kind_here(key)
            if found is None:
                return None
            self.kinds[key] = found
        return self.kinds[key]

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
        Anything that goes wrong leaves the path unknown — destructive.
        `B1669`: and a shell command there, at each path it writes over."""
        if tool_name in SHELL_TOOLS:
            await self._look_at_command(tool_name, content)
            return
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

    async def _look_at_command(self, tool_name: str, content: Any) -> None:
        """`B1669`. A shell command in the workstation: work out there what it
        writes over — from where its shell starts (`B962`), at each path the
        reading names — and keep the answer for the run (`said`). A path asked
        about once keeps its first answer (`kinds`); a workstation that cannot
        be asked leaves the command unknown — destructive."""
        from src.tool_capabilities import command_writes
        writes = command_writes(tool_name, content)
        if not writes or not self.in_workstation(tool_name):
            return
        call = call_key(tool_name, content)
        if call in self.said:
            return
        try:
            from src.agent_tools.workstation_tools import shell_station
            station = await shell_station(owner=self.owner, workspace=self.workspace,
                                          session_id=self.session_id)
        except Exception:  # noqa: BLE001 — unknown, and so destructive
            logger.debug("B1669: could not ask the workstation where %s writes", tool_name,
                         exc_info=True)
            station = None
        if station is None:
            return
        starts, home, kind_at = station
        # A copy into a folder is only known to be one once its folder is
        # looked at, so the paths are asked for in rounds; three is a copy's.
        for _round in range(4):
            asked: list = []

            def kind_of(path: str, asked: list = asked) -> Optional[str]:
                key = f"{IN_WORKSTATION}::{path}"
                if key not in self.kinds:
                    asked.append(path)
                return self.kinds.get(key)

            answer = _reading(writes, starts, home, kind_of, IN_YOUR_WORKSTATION, posixpath)
            if not asked:
                self.said[call] = answer or ""
                return
            for path in dict.fromkeys(asked):
                try:
                    found = await kind_at(path)
                except Exception:  # noqa: BLE001 — unknown, and so destructive
                    logger.debug("B1669: could not ask the workstation about %r", path,
                                 exc_info=True)
                    found = None
                if found is None:
                    return
                self.kinds[f"{IN_WORKSTATION}::{path}"] = found


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
    if files is not None and (path in files.made or files.kinds.get(path) == NOTHING):
        # Made by this run's `write_file`, or (`B1669`) empty when the run
        # first looked at it for a command's `>`: the run's own file.
        return None
    try:
        if not os.path.exists(path) or os.path.isdir(path):
            # Nothing there, or a folder (`open(…, "w")` refuses it): nothing replaced.
            return None
    except OSError:
        return f"it cannot be known whether {shown} was there before this run began"
    return f"write_file replaces {shown}, which was there before this run began"


# ── `B1669` · a shell writing over a file that was there ────────────────────
#
# `bash 'echo x > notes.md'` and `bash 'cp new.md notes.md'` were `execute_code`
# alone, while `write_file notes.md` over the same file carried `destructive`
# (`B1660`) and so did `mv` (`B1622`): the owner's principle (`D-2026-10-29-02`
# §1) is that replacing a file that was there before the run is destructive
# whatever tool does it. `src/shell_reading.py` names what a command writes
# over — a `>` (not `>>`), `tee` without `-a`, `cp`/`install` onto a path —
# and where it moves (`cd`); this decides whether each was there.
#
# **Where.** A command on this machine starts where its chat's shell was left
# (`B962`) or in the run's workspace (`RunFiles.shell_starts`); a relative path
# is looked for there and wherever its `cd`s could take it, in any order (the
# reading cannot tell which `cd` ran — one in a subshell, one that failed —
# so every folder it could be in is looked at, which asks more, never less).
# `~` is the shell's home (`$HOME`, which the tools set to the agent's folder).
# A path or a `cd` filled in when it runs, or one on the far side of an `ssh`
# or a `docker exec`, cannot be known — destructive, the ruling's cautious
# reading. In the workstation the gate cannot look, so the loop asks it before
# the call is classified (`look`, as `write_file`'s `B1660` does), and a
# command it could not ask about is destructive. `shell_with_login` runs where
# its logins' command runs, in a folder of its own `cwd`: not looked at.
#
# **When.** "Before this run began" is what the run saw the first time it
# looked at a path (`kinds`, carried to the run a card resumes): the gate
# looks before the call runs, so a file the run's own `>` made is its own
# draft on the next pass, as a `write_file` draft is. A file something else of
# the run made before the run looked at it — a build's output — reads as there.
#
# Python's `open(path, "w")` is not read (`src/shell_reading.py` says why);
# its `subprocess` commands are.

IN_YOUR_WORKSTATION = " in your workstation"
_ON_THE_FAR_SIDE = " on the far side"
#: Past this many folders a command could be in, where it writes is unknown.
_MAX_FOLDERS = 32


def call_key(tool_name: Any, content: Any) -> str:
    """One name for one call, for what the run worked out about it."""
    if isinstance(content, Mapping):
        content = json.dumps(dict(content), sort_keys=True, default=str)
    return f"{tool_name}\n{content if isinstance(content, str) else ''}"


def _real(path: str) -> Optional[str]:
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return None


def _kind_here(path: str) -> Optional[str]:
    """What is at `path` on this machine, now."""
    try:
        if os.path.isdir(path):
            return FOLDER
        return FILE if os.path.isfile(path) else NOTHING
    except (OSError, ValueError):
        return None


def _place(text: str, base: str, home: str, paths=os.path) -> str:
    """Where a path a command names is, from `base`."""
    if text == "~" or text.startswith("~/"):
        return paths.normpath(home + text[1:])
    return paths.normpath(paths.join(base, text))


def _folders(writes, starts, home: str, paths=os.path) -> Optional[list]:
    """Every folder the command could be in when it writes: where it starts,
    and wherever its `cd`s could take it, in any order — `None` when a `cd`
    goes somewhere filled in when it runs, or there are too many to look at."""
    moves = [f for f in writes if f.kind == "chdir" and not f.far]
    if any(not f.known for f in moves):
        return None
    folders = list(dict.fromkeys(starts))
    for _ in moves:
        grown = list(dict.fromkeys(folders + [_place(f.path, b, home, paths)
                                              for b in folders for f in moves]))
        if len(grown) > _MAX_FOLDERS:
            return None
        if len(grown) == len(folders):
            break
        folders = grown
    return folders


def _reading(writes, starts, home: str, kind_of, where: str = "", paths=os.path) -> Optional[str]:
    """Why these writes carry `destructive` — the first file one replaces,
    else the first whose being there cannot be known — or `None`. `kind_of`
    answers what was there (`FILE`, `FOLDER`, `NOTHING`, or `None`: unknown)."""
    folders = _folders(writes, starts, home, paths)
    unknown: Optional[str] = None

    def cannot(shown: str, at: str = where) -> str:
        return f"it cannot be known whether {shown}{at} was there before this run began"

    for f in writes:
        if f.kind != "writes":
            continue
        if f.far:
            unknown = unknown or cannot(f.path, _ON_THE_FAR_SIDE)
            continue
        relative = not (paths.isabs(f.path) or f.path == "~" or f.path.startswith("~/"))
        if not f.known or (relative and folders is None):
            unknown = unknown or cannot(f.path)
            continue
        for place in ([_place(f.path, "", home, paths)] if not relative else
                      [_place(f.path, b, home, paths) for b in folders]):
            found = kind_of(place)
            if found is None:
                unknown = unknown or cannot(f.path)
                continue
            into = f.into or (("folder" if found == FOLDER else "file") if f.sources else "")
            if into != "folder":
                # A redirect or `tee` replaces a file; a copy onto a name
                # replaces a file, or (`-T`) merges into a folder.
                if found == FILE or (found == FOLDER and into == "file"):
                    return f"{f.why} replaces {f.path}{where}, which was there before this run began"
                continue
            for source, spelled in f.sources:
                if not spelled:
                    unknown = unknown or cannot(f.path)
                    continue
                name = source.rstrip("/")
                name = name.lstrip("/") if f.parents else paths.basename(name)
                if not name:
                    continue
                inside = paths.join(place, name)
                found = kind_of(inside)
                if found is None:
                    unknown = unknown or cannot(paths.join(f.path, name))
                elif found != NOTHING:
                    return (f"{f.why} replaces {paths.join(f.path, name)}{where}, which was there "
                            f"before this run began")
    return unknown


def command_replaces(tool_name: Any, writes, content: Any = None,
                     files: Optional[RunFiles] = None) -> Optional[str]:
    """`B1669`. Why this shell or Python call carries `destructive` for what
    it writes over — the file it replaces, or why that cannot be known — or
    `None`. `writes` is the reading's (`shell_reading.writes_of`); `files` the
    run's record. Without one (a caller outside any run) the command is read
    as starting where a command would start here and now, and nothing is the
    run's own."""
    writes = tuple(writes or ())
    first = next((f for f in writes if f.kind == "writes"), None)
    if first is None:
        return None
    files = files if isinstance(files, RunFiles) else None
    if tool_name not in SHELL_TOOLS:
        return f"it cannot be known whether {first.path} was there before this run began"
    if files is not None and files.in_workstation(tool_name):
        said = files.said.get(call_key(tool_name, content))
        if said is None:
            return (f"it cannot be known whether {first.path}{IN_YOUR_WORKSTATION} was there "
                    f"before this run began")
        return said or None
    from src.tool_execution import _AGENT_WORKDIR, agent_cwd
    if files is None:
        return _reading(writes, [agent_cwd()], _AGENT_WORKDIR, _kind_here)
    return _reading(writes, files.shell_starts(), _AGENT_WORKDIR, files.kind)


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
