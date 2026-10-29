# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a run knows about the files it writes, and whether a `write_file`
replaces one that was there before it began. `B1660`. And whether a shell
command's `>`, `tee`, `cp` or `install` does (`B1669`, `command_replaces`), or
a program told to write over its output (`B1680`, `B1682`, `B1688`–`B1690`), or a compressor
takes away (`B1683`), with a path spelled against a variable the run knows
filled in as its shell will (`B1681`) — in the workstation, the value its
daemon reports it gives the command (`B1684`). An append replaces nothing
(`B1672`, `D-2026-10-29-03` §2). A write onto a name a link made earlier in
the command lands where the link points (`B1692`), and a converter's numbered
copies are looked for beside the name it is given (`B1693`).

A leaf: the loop makes a holder per turn and hands it to the gate
(`ToolRunSecurityContext.files`) and to each tool call (`bind_run_files`);
`write_file` notes what it made, and the gate asks `replaces`.
"""
from __future__ import annotations

import json
import logging
import os
import posixpath
import re
from contextvars import ContextVar
from typing import Any, Mapping, Optional, Tuple

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
                 carried: Optional[Mapping[str, Any]] = None, session_id: Optional[str] = None,
                 hired: bool = False):
        self.workspace = workspace or None
        self.owner = owner
        # `B1669`: the chat, whose shell keeps its folder between calls (`B962`).
        self.session_id = session_id or None
        # `B1681`: a hire's run, whose `$PANTHEON_PROJECTS` is its own folder
        # (`B1646`) — a fact of the run, so a run a card resumes, which is
        # the hire's again, knows it without carrying it.
        self.hired = bool(hired)
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
        # `B1693`. The numbered-looking files in each folder a converter
        # writes into, the first time this run looked — so the numbered
        # copies the run's own `convert` made are its own on the next pass,
        # as `kinds` makes its own `>`'s file.
        self.listed: dict = {str(k): sorted(str(n) for n in v)
                             for k, v in dict(carried.get("listed") or {}).items()
                             if isinstance(v, (list, tuple))}

    def carried(self) -> dict:
        """What a run resumed from this run's card starts with."""
        return {"made": sorted(self.made), "seen": dict(self.seen),
                "kinds": dict(self.kinds), "said": dict(self.said),
                "listed": {k: list(v) for k, v in self.listed.items()}}

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

    def shell_values(self) -> dict:
        """`B1681`. The variables a path in this run's command on this machine
        may start with, as its shell has them: `$HOME`, which the tools set to
        the agent's folder (`~`), and `$PANTHEON_PROJECTS`, by the one rule the
        shell's environment is set by (`tool_execution.projects_folder_for`)."""
        from src.tool_execution import _AGENT_WORKDIR, projects_folder_for
        from workstation.protocol import PROJECTS_ENV
        return {"HOME": _AGENT_WORKDIR,
                PROJECTS_ENV: projects_folder_for(self.owner, self.workspace, self.hired)}

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

    def numbered(self, path: str) -> Optional[list]:
        """`B1693`. The numbered-looking files in the folder at `path` on
        this machine the first time this run looked, or `None` when it
        cannot be listed."""
        key = _real(path)
        if key is None:
            return None
        if key not in self.listed:
            found = _numbered_here(key)
            if found is None:
                return None
            self.listed[key] = found
        # A name the run saw empty before it wrote there is its own.
        return [n for n in self.listed[key]
                if not self._own(os.path.join(key, n))]

    def forget(self, paths) -> None:
        """`B1692`. Drop "nothing was there" for each of `paths` on this
        machine — names a link of the command being read makes — so the run
        looks again the next time: a hard link there shares another file,
        and writing it is not writing the run's own."""
        for path in paths:
            key = _real(path)
            if key is not None and self.kinds.get(key) == NOTHING:
                del self.kinds[key]

    def _own(self, key: str) -> bool:
        """`B1693`. Whether the file at `key` is this run's: `write_file`
        made it, or the run looked and nothing was there."""
        return key in self.made or self.kinds.get(key) == NOTHING

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
        if tool_name != "write_file" or appends(content) or not self.in_workstation():
            return      # `B1672`: an append replaces nothing, wherever it is
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
                                          session_id=self.session_id, hired=self.hired)
        except Exception:  # noqa: BLE001 — unknown, and so destructive
            logger.debug("B1669: could not ask the workstation where %s writes", tool_name,
                         exc_info=True)
            station = None
        if station is None:
            return
        starts, home, kind_at, values, names_at = station
        # A copy into a folder is only known to be one once its folder is
        # looked at, so the paths are asked for in rounds; three is a copy's,
        # and (`B1692`) a link's place, its target and what is in it add to
        # them, as (`B1693`) a folder's numbered names do.
        for _round in range(_MAX_HOPS + 4):
            asked: list = []
            listing: list = []

            def kind_of(path: str, asked: list = asked) -> Optional[str]:
                key = f"{IN_WORKSTATION}::{path}"
                if key not in self.kinds:
                    asked.append(path)
                return self.kinds.get(key)

            def names_of(path: str, listing: list = listing) -> Optional[list]:
                key = f"{IN_WORKSTATION}::{path}"
                if key not in self.listed:
                    listing.append(path)
                    return None
                # A name the run saw empty before it wrote there is its own.
                return [n for n in self.listed[key] if self.kinds.get(
                    f"{IN_WORKSTATION}::{posixpath.join(path, n)}") != NOTHING]

            answer = _reading(writes, starts, home, kind_of, IN_YOUR_WORKSTATION, posixpath,
                              values, names_of)
            if not asked and not listing:
                self.said[call] = answer or ""
                # `B1692`: a name a link of this command makes is not the run's own.
                for path in _linked(writes, starts, home, posixpath, values):
                    if self.kinds.get(f"{IN_WORKSTATION}::{path}") == NOTHING:
                        del self.kinds[f"{IN_WORKSTATION}::{path}"]
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
            for path in dict.fromkeys(listing):
                try:
                    names = await names_at(path)
                except Exception:  # noqa: BLE001 — unknown, and so destructive
                    logger.debug("B1693: could not list %r in the workstation", path,
                                 exc_info=True)
                    names = None
                if names is None:
                    return
                self.listed[f"{IN_WORKSTATION}::{path}"] = _numbered_names(names)


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


def appends(content: Any) -> bool:
    """`B1672`. Whether a `write_file` call adds to the end of its file
    (`"append": true`), read as the tool reads it."""
    from src.agent_tools.filesystem_tools import _write_file_call
    if isinstance(content, Mapping):
        content = json.dumps(dict(content))
    return isinstance(content, str) and _write_file_call(content)[2]


def replaces(content: Any, files: Optional[RunFiles] = None) -> Optional[str]:
    """Why this `write_file` call carries `destructive` — the file it replaces,
    or why that cannot be known — or `None`: it makes a new file, rewrites one
    this run made, adds to the end of one (`B1672`), or names a path the tool
    refuses (which writes nothing).

    `files` is the run's record. Without one (a caller outside any run) the
    path is resolved as the tool would resolve it here and now, and nothing is
    known to be the run's own.

    `B1672`. The owner's ruling (`D-2026-10-29-03` §2), *"Append-only is not
    destructive"*: a write that only adds to the end of a file that was there
    keeps every byte it had, so it is a plain write wherever the file is —
    as a shell's `>>` is (`B1669`)."""
    raw = target(content)
    if not raw.strip():
        return None   # the tool refuses it: "path is required"
    if appends(content):
        return None
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
# reading. `B1681`: except a path that starts with a variable the run gives
# its shell — `$PANTHEON_PROJECTS` (a hire's own folder, else the person's
# projects folder: `tool_execution.projects_folder_for`, the rule the shell's
# environment is set by) and `$HOME` — and has nothing else filled in, which
# is filled in here as the shell will (`_named`); unquoted, a value it would
# split or glob is not known, and so is one the command sets itself
# (`shell_reading.writes_of`), and `~` once it sets `HOME`. In the workstation the gate cannot look, so the
# loop asks it before the call is classified (`look`, as `write_file`'s
# `B1660` does), and a command it could not ask about is destructive; there a
# hire's `$PANTHEON_PROJECTS` is the folder Pantheon hands its command, and a
# chat's is the daemon's own, as the daemon reports it (`B1684`,
# `workstation_tools.shell_station`). `shell_with_login` runs where
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
#
# **Through a link (`B1692`).** `ln notes.md new.md; echo x > new.md` empties
# `notes.md`: `new.md` was nothing before the run, but the `>` opens the file
# the link shares (a symbolic link: the file it names). So a write onto a name
# a link made earlier in the same command — `ln`, `ln -s`, `link`, `cp -l`/
# `-s`, `os.link`/`os.symlink` — or onto a name inside a folder one points
# at, is looked at where it lands too (`_link_ends`, `_through`), and a file
# that was there before the run makes it a replacement, worded as written
# through the link. A link whose name or target cannot be known leaves a
# write after it unknown. A write that takes a name away (`B1683`'s
# `removes`) takes the link, not its target, and is not followed.
#
# **Numbered copies (`B1693`).** A converter given several images writes
# `out-1.jpg`, `out-2.jpg` (`heif-convert`) or `out-0.png`… (ImageMagick)
# instead of the one name; how many is the input's. So the folder is listed
# — the first time the run looks, as `kinds` is (`RunFiles.listed`) — and a
# file there of the numbered shape the reading gives (`Finding.numbered`)
# makes the write unknown, and so destructive; where none is, it is a plain
# write. A folder that cannot be listed, or holds more than `_MAX_LISTED`
# names, is unknown too.

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


#: `B1693`. Past this many names a folder holds, its numbered names are not
#: looked through — the workstation's own bound on a listing
#: (`workstation.protocol.MAX_LIST_ENTRIES`), here too, so a folder reads the
#: same in either place.
_MAX_LISTED = 5_000


def _numbered_names(files) -> list:
    """`B1693`. The names among `files` that end as a numbered copy's does
    (`shell_reading.NUMBERED_TAIL`) — the only ones a shape is matched
    against, so the run keeps no more than those."""
    from src.shell_reading import NUMBERED_TAIL
    return sorted(n for n in files if NUMBERED_TAIL.search(n))


def _numbered_here(path: str) -> Optional[list]:
    """`B1693`. The numbered-looking files in the folder at `path` on this
    machine, now — `None` when it cannot be listed, or holds more than
    `_MAX_LISTED` names. A link to a file is a file: a write goes through."""
    files = []
    try:
        with os.scandir(path) as entries:
            for count, entry in enumerate(entries, start=1):
                if count > _MAX_LISTED:
                    return None
                if entry.is_file():
                    files.append(entry.name)
    except (OSError, ValueError):
        return None
    return _numbered_names(files)


def _place(text: str, base: str, home: str, paths=os.path) -> str:
    """Where a path a command names is, from `base`."""
    if text == "~" or text.startswith("~/"):
        return paths.normpath(home + text[1:])
    return paths.normpath(paths.join(base, text))


#: `B1681`. What makes an unquoted variable's value more than one path: the
#: shell splits it at a space and globs a `*`, `?` or `[`.
_SPLITS = re.compile(r"[\s*?\[]")


def _named(f, values: Optional[Mapping[str, str]]) -> Optional[str]:
    """`B1681`. The path `f` names as the shell will see it — as written, or
    with the variable it starts with (`f.var`) filled in from `values`, the
    run's own (`RunFiles.shell_values`) — or `None` when it cannot be known:
    filled in some other way, a variable the run does not know or that is
    empty, or an unquoted value the shell would split or glob."""
    if not f.known:
        return None
    if not f.var:
        return f.path
    value = (values or {}).get(f.var)
    if not value or (f.split and _SPLITS.search(value)):
        return None
    for lead in ("${%s}" % f.var, "$" + f.var):
        if f.path.startswith(lead):
            return value + f.path[len(lead):]
    return None


def _folders(writes, starts, home: str, paths=os.path,
             values: Optional[Mapping[str, str]] = None) -> Optional[list]:
    """Every folder the command could be in when it writes: where it starts,
    and wherever its `cd`s could take it, in any order — `None` when a `cd`
    goes somewhere filled in when it runs, or there are too many to look at."""
    moves = [_named(f, values) for f in writes if f.kind == "chdir" and not f.far]
    if any(m is None for m in moves):
        return None
    folders = list(dict.fromkeys(starts))
    for _ in moves:
        grown = list(dict.fromkeys(folders + [_place(m, b, home, paths)
                                              for b in folders for m in moves]))
        if len(grown) > _MAX_FOLDERS:
            return None
        if len(grown) == len(folders):
            break
        folders = grown
    return folders


#: `B1692`. Past this many links one after another, where a write lands is
#: not followed further.
_MAX_HOPS = 8


def _inside(source: str, parents: bool, paths=os.path) -> str:
    """The name a copy (or a link) gives `source` inside a folder: its last
    part, or (`--parents`) its whole path."""
    name = source.rstrip("/")
    return name.lstrip("/") if parents else paths.basename(name)


def _link_ends(f, folders, home: str, paths, values, kind_of) -> list:
    """`B1692`. Each name the link finding `f` makes, and where it points:
    `(at, to, link, target)` — the link's place and its target's, as the
    command shows them — with `at` `None` when the name cannot be known (any
    write after it may be onto it), and `to` `None` when what it points at
    cannot. A name made in a folder (`into`) is the target's name there; one
    that may or may not be a folder (`ln a b`, `b` there or not) is read as
    both, unless `b` was a folder, where it is only the one inside."""
    def rooted(text: str) -> bool:
        return paths.isabs(text) or text == "~" or text.startswith("~/")

    named = _named(f, values)
    ends: list = []
    # Where the command could be when it makes the link (`None`: unknown).
    for b in (folders if folders is not None else [None]):
        place = (None if named is None or (b is None and not rooted(named))
                 else _place(named, b or "", home, paths))
        for target, spelled in f.sources:
            inner = _inside(target, f.parents, paths)
            within = inner if f.path in (".", "./") else paths.join(f.path, inner)
            if place is None:
                ats = [(None, f.path)]
            elif f.into == "folder":
                ats = [(paths.join(place, inner), within)] if inner else []
            elif f.into == "file" or not inner:
                ats = [(place, f.path)]
            else:
                ats = [(paths.join(place, inner), within)]
                if kind_of(place) != FOLDER:
                    ats.insert(0, (place, f.path))
            for at, link in ats:
                # A symbolic link names its target from its own folder; a
                # hard one, from where the command runs.
                start = (paths.dirname(at) if at is not None else None) if f.beside else b
                if not spelled or (start is None and not rooted(target)):
                    to = None
                else:
                    to = _place(target, start or "", home, paths)
                ends.append((at, to, link, target or f.path))
    return list(dict.fromkeys(ends))


def _through(place: str, links: list, paths=os.path) -> list:
    """`B1692`. Where a write at `place` lands through the links made
    before it: `(where, the target as shown, the link, sure)` — through a
    link at `place` or a folder above it, and on through any link there.
    `sure` is False through a link whose name cannot be known, which `place`
    may or may not be; `where` is `None` when a target cannot be known."""
    out: list = []
    frontier = [(place, None, True)]
    seen = {place}
    for _ in range(_MAX_HOPS):
        grown = []
        for q, first, sure in frontier:
            for at, to, link, target in links:
                if at is None:
                    rest = ""                   # it may be this very name
                elif q == at:
                    rest = ""
                elif q.startswith(at.rstrip(paths.sep) + paths.sep):
                    rest = q[len(at.rstrip(paths.sep)) + 1:]
                else:
                    continue
                shown = paths.join(target, rest) if rest else target
                hop = (None if to is None else paths.normpath(paths.join(to, rest) if rest else to),
                       shown, first or link, sure and at is not None)
                if hop[0] is None:
                    out.append(hop)
                elif hop[0] not in seen:
                    seen.add(hop[0])
                    out.append(hop)
                    grown.append((hop[0], hop[2], hop[3]))
        frontier = grown
        if not frontier:
            break
    return out


def _linked(writes, starts, home: str, paths=os.path,
            values: Optional[Mapping[str, str]] = None) -> list:
    """`B1692`. Every place a link the command makes may have its name —
    what the run must not keep as "nothing was there": once the command has
    run, a hard link there shares the person's file, and writing that name
    in a later command writes theirs. (A symbolic one is looked at through
    to its target already: the run's record is kept by real path.)"""
    folders = _folders(writes, starts, home, paths, values)
    places = []
    for f in writes:
        if f.kind != "links" or f.far:
            continue
        named = _named(f, values)
        if named is None:
            continue
        rooted = paths.isabs(named) or named == "~" or named.startswith("~/")
        for b in (folders if folders is not None else [""] if rooted else []):
            place = _place(named, b, home, paths)
            places.append(place)
            for target, _spelled in f.sources:
                inner = _inside(target, f.parents, paths)
                if inner and f.into != "file":
                    places.append(paths.join(place, inner))
    return list(dict.fromkeys(places))


def _reading(writes, starts, home: str, kind_of, where: str = "", paths=os.path,
             values: Optional[Mapping[str, str]] = None, names_of=None) -> Optional[str]:
    """Why these writes carry `destructive` — the first file one replaces,
    else the first whose being there cannot be known — or `None`. `kind_of`
    answers what was there (`FILE`, `FOLDER`, `NOTHING`, or `None`: unknown);
    `values` (`B1681`) the variables a path may start with; `names_of`
    (`B1693`) the numbered names that were in a folder (`None`: unknown).

    `B1692`. A write onto a name a link made earlier in the command — `ln
    notes.md new.md; echo x > new.md` — writes the file the link points at,
    so that is looked at too, the way the name itself is; not a write that
    takes a name away (`B1683`'s `removes`), which takes the link."""
    folders = _folders(writes, starts, home, paths, values)
    unknown: Optional[str] = None
    links: list = []

    def cannot(shown: str, at: str = where) -> str:
        return f"it cannot be known whether {shown}{at} was there before this run began"

    for f in writes:
        if f.kind == "links":
            if not f.far:       # on another machine: its writes there are the far side's
                links.extend(_link_ends(f, folders, home, paths, values, kind_of))
            continue
        if f.kind != "writes":
            continue
        if f.far:
            unknown = unknown or cannot(f.path, _ON_THE_FAR_SIDE)
            continue
        named = _named(f, values)
        relative = named is not None and not (
            paths.isabs(named) or named == "~" or named.startswith("~/"))
        if named is None or (relative and folders is None):
            unknown = unknown or (_beside(f, where) if f.numbered else cannot(f.path))
            continue
        for place in ([_place(named, "", home, paths)] if not relative else
                      [_place(named, b, home, paths) for b in folders]):
            hops = [(place, f.path, None, True)]
            if not f.removes and links:
                hops += _through(place, links, paths)
            for at, shown, link, sure in hops:
                said = _land(f, at, shown, link, sure, kind_of, names_of, where, paths)
                if said is None:
                    continue
                if said[0]:
                    return said[1]
                unknown = unknown or said[1]
    return unknown


def _beside(f, where: str, shown: str = "") -> str:
    """`B1693`. What a program writes beside its output, when the input
    holds several images, cannot be looked at."""
    if f.into == "folder":
        shown = shown or ("the folder it runs in" if f.path in (".", "./") else f.path)
        return (f"it cannot be known whether what {f.why} writes in {shown}{where} was there "
                f"before this run began")
    return (f"it cannot be known whether what {f.why} writes beside {shown or f.path}{where} "
            f"was there before this run began")


def _land(f, at: Optional[str], shown: str, link: Optional[str], sure: bool, kind_of, names_of,
          where: str, paths=os.path) -> Optional[Tuple[bool, str]]:
    """What the write `f` finds at `at` — `shown` as the command names it,
    reached through `link` (`B1692`) or not: `(True, why)` for a file it
    replaces that was there, `(False, why)` when that cannot be known, or
    `None`."""
    does, does_in = ("removes", "removes") if f.removes else ("replaces", "writes")
    there = "which was there before this run began"

    def over(name: str) -> Tuple[bool, str]:
        if link is None:
            return True, f"{f.why} {does} {name}{where}, {there}"
        said = f"{f.why} writes through the link {link} over {name}{where}, {there}"
        return (True, said) if sure else (False, f"it cannot be known whether {said}")

    def cannot(name: str) -> Tuple[bool, str]:
        if link is None:
            return False, f"it cannot be known whether {name}{where} was there before this run began"
        return False, (f"it cannot be known whether {name}{where}, where the link {link} points, "
                       f"was there before this run began")

    if at is None:
        return cannot(shown)            # where the link points cannot be known
    found = kind_of(at)
    if f.numbered:
        # `B1693`: the names it gives each of several images, in this folder.
        if found is None:
            return False, _beside(f, where, shown)
        if found != FOLDER:
            return None                 # no folder: nothing numbered was there
        names = names_of(at) if names_of is not None else None
        if names is None:
            return False, _beside(f, where, shown)
        hit = next((n for n in names if re.fullmatch(f.numbered, n)), None)
        if hit is None:
            return None
        inside = hit if shown in (".", "./") else paths.join(shown, hit)
        if link is None:
            return False, f"it cannot be known whether {f.why} writes over {inside}{where}, {there}"
        return False, (f"it cannot be known whether {f.why} writes through the link {link} over "
                       f"{inside}{where}, {there}")
    if found is None:
        return cannot(shown)
    into = f.into or (("folder" if found == FOLDER else "file") if f.sources else "")
    if into != "folder":
        # A redirect or `tee` replaces a file; a copy onto a name replaces a
        # file, or (`-T`) merges into a folder.
        if found == FILE or (found == FOLDER and into == "file"):
            return over(shown)
        return None
    if found != FOLDER:
        # `B1680`: into a folder that is not there (an archive makes it; a
        # copy refuses) — nothing in it was there to replace.
        return None
    unknown: Optional[Tuple[bool, str]] = None
    for source, spelled in f.sources:
        if not spelled:
            # `B1680`: an archive's members, which the command does not
            # name, into a folder that was there.
            folder = "the folder it runs in" if shown in (".", "./") else shown
            unknown = unknown or (cannot(shown) if source else (False, (
                f"it cannot be known whether what {f.why} {does_in} in {folder}{where} was "
                f"there before this run began")))
            continue
        name = _inside(source, f.parents, paths)
        if not name:
            continue
        inside = paths.join(shown, name) if shown != "." else name
        found = kind_of(paths.join(at, name))
        if found is None:
            unknown = unknown or cannot(inside)
        elif found != NOTHING:
            return over(inside)
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
    files = files if isinstance(files, RunFiles) else None
    if tool_name not in SHELL_TOOLS:
        if first is None:
            return None
        if first.numbered:
            return _beside(first, "")
        return f"it cannot be known whether {first.path} was there before this run began"
    if files is not None and files.in_workstation(tool_name):
        said = files.said.get(call_key(tool_name, content))
        if first is None:
            return None         # its links are forgotten where it was looked at (`look`)
        if said is None:
            if first.numbered:
                return _beside(first, IN_YOUR_WORKSTATION)
            return (f"it cannot be known whether {first.path}{IN_YOUR_WORKSTATION} was there "
                    f"before this run began")
        return said or None
    from src.tool_execution import _AGENT_WORKDIR, agent_cwd, projects_env
    spelled = any(f.var for f in writes)    # `B1681`: a path starts with a variable
    if files is None:
        if first is None:
            return None
        return _reading(writes, [agent_cwd()], _AGENT_WORKDIR, _kind_here,
                        values={"HOME": _AGENT_WORKDIR, **projects_env()} if spelled else None,
                        names_of=_numbered_here)
    values = files.shell_values() if spelled else None
    said = None if first is None else _reading(writes, files.shell_starts(), _AGENT_WORKDIR,
                                               files.kind, values=values, names_of=files.numbered)
    forget_links(tool_name, writes, files)
    return said


def forget_links(tool_name: Any, writes, files: Optional[RunFiles]) -> None:
    """`B1692`. A name a link of this command makes is not the run's own:
    the run's record drops "nothing was there" for it on this machine (in
    the workstation, `look` does), so a later write onto it is looked at
    again — asked whether or not the command itself asks (`ln -f`)."""
    if not isinstance(files, RunFiles) or tool_name not in SHELL_TOOLS:
        return
    writes = tuple(writes or ())
    if not any(f.kind == "links" for f in writes) or files.in_workstation(tool_name):
        return
    from src.tool_execution import _AGENT_WORKDIR
    values = files.shell_values() if any(f.var for f in writes) else None
    files.forget(_linked(writes, files.shell_starts(), _AGENT_WORKDIR, os.path, values))


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
