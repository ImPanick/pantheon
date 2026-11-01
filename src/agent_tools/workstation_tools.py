# SPDX-License-Identifier: AGPL-3.0-or-later
"""When the workstation is on, the agent's hands are in it — `P20-03`, `D-2026-09-30-03`.

The owner's answer: *when the workstation is on, the agent's `bash`, `python` and
file tools run inside it.* This module is those nine tools, run through the
workstation client as the person the turn belongs to, in their workstation home
— and the gate that says which of them a person may use there.

**ONE DECISION, ONE PLACE.** `src/tool_execution._execute_tool_block_impl` asks
`routes(tool, owner)` once, after the refusals every tool gets and before any
path that could run on Pantheon's own machine (the `#!bg` launcher, the MCP map,
`_direct_fallback`). Traced 2026-09-30 by driving `execute_tool_block` with a spy
on each leg: all nine reach `TOOL_HANDLERS` through `_direct_fallback` today —
`bash`/`python`/`read_file`/`write_file` by way of `_call_mcp_tool`, whose built-in
servers (`bash`, `python`, `filesystem`) do not exist (`builtin_mcp._BUILTIN_SERVERS`
is `image_gen`, `rag`, `email`, and a user's server id is eight hex characters),
so it always falls back. So routing above that point covers every way in.

**NEVER A SILENT FALLBACK.** If the workstation is on and cannot be reached, or
refuses, the tool answers `WorkstationError.as_result()` — a sentence — and
nothing runs here instead. With the workstation off, or `workstation_route_tools`
off, `routes()` is false and the dispatcher runs exactly what it ran before
(`Law 1`).

**THE SAME ANSWERS.** Each tool here reuses the host tool's own parsing,
transformation and wording (`filesystem_tools`, `subprocess_tools`,
`codenav_walk`), so an `edit_file` in the workstation is the same edit with the
same diff, a `read_file` is cut at the same `MAX_READ_CHARS`, a shell result has
the same `stdout`/`stderr`/`exit_code` (`FORBIDDEN.md`) and the same
`MAX_OUTPUT_CHARS` split. Two keys are added to every result, and only here:
`ran_in: "workstation"` and `ran_as: <account>`. The tool card draws them; the
model reads them in the result's data block, which is how it learns where its
command ran.

**WHAT PERSISTS: THE FOLDER, AND NOTHING ELSE (`B962`, `D-2026-10-01-01`).**
Each call is a fresh shell, here as on Pantheon's machine, so variables,
functions and background jobs end with it; the chat's shell keeps its folder.
A `bash` call reports where it ended (`subprocess_tools._CwdReport`, a file under
`~/.cache/pantheon-run/`, one per chat) and the chat's next `bash` or `python`
starts there (`subprocess_tools.CHAT_FOLDERS`). The daemon is the authority on
which folders a command may start in — the home jail, unless `sudo` is on, the
same jail the file tools meet — and a folder it refuses, or one that is gone,
falls back to the start folder with a sentence. `cwd` in a result is the folder
the chat's shell is in afterwards: where its next command starts.

**WHERE THEY START: THE WORKSPACE (`B968`, `D-2026-10-01-01`).** With the
workstation on, the workspace picked in the composer is a folder in the
person's workstation home (`vet_workspace`, the picker's routes). The shells
start there and the file tools read a relative path as relative to it, as
here; it is where they start, not a boundary — the home jail is the boundary.
`#!bg` jobs are refused here with a sentence (see `_BACKGROUND_REFUSAL`) rather
than half-run.

**THE SENSITIVE-PATH RULE IS NOT LIFTED BY MOVING THE TOOL.** `_resolve_tool_path`
and its deny-list are `FORBIDDEN.md` Part 2. The home jail is the daemon's; the
deny-list (`.ssh`, `.gnupg`, shell rc files, keys, `.env`) is still applied here
to the path asked for and to the path the daemon resolved it to, with the same
sentence. `bash` can reach those files in the workstation, as it can here; the
file tools cannot, here or there.
"""
from __future__ import annotations

import asyncio
import collections
import errno
import hashlib
import io
import json
import logging
import os
import posixpath
import re
import shlex
import time
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional, Tuple

from src.agent_tools import codenav_walk as _codenav
from src.agent_tools import filesystem_tools as fs
from src.agent_tools import subprocess_tools as sp
from src.workstation_client import WorkstationError
from workstation import protocol as P

logger = logging.getLogger(__name__)

WORKSTATION_TOOLS: FrozenSet[str] = frozenset({
    "bash", "python", "read_file", "write_file", "edit_file", "apply_patch", "ls", "glob",
    "grep",
})

# A failure of the workstation itself, as opposed to an answer about a file.
# These come back as `WorkstationError.as_result()`; a missing file, a path out
# of the home or a directory where a file was expected is the file tool's own
# answer, worded as the host tool words it.
_STATION_FAILURES = frozenset({"off", "unconfigured", "not_permitted", "unavailable",
                               "unauthorized", "internal", "busy"})

# The environment the host shell adds to its own (`_direct_fallback`), minus
# `HOME`, which the daemon sets to the person's workstation home — and minus
# Pantheon's environment, which is the point: the workstation holds no secret.
_SHELL_ENV = {"TERM": "xterm-256color", "COLUMNS": "120", "LINES": "40"}


def run_env(workspace: Optional[str]) -> Dict[str, str]:
    """`B1646`. What a hire's run adds to a command's environment in the
    workstation: `$PANTHEON_PROJECTS` naming the folder the run works in
    (`workspace`, as the workstation names it — `tool_execution.
    run_projects_folder`) over the daemon's own, the person's whole projects
    folder (`agentd._exec_prepare`), so its runbook's `cd` goes where its file
    tools write. Empty for every other call. A name, not a key: the daemon
    still holds every path a command uses to the jail."""
    from src.tool_execution import run_projects_folder
    folder = run_projects_folder(workspace)
    return {P.PROJECTS_ENV: folder} if folder else {}

# A file is read in pieces of this size: one request covers a capped
# `read_file` (at most 4 bytes a character, `MAX_READ_CHARS` + 1 characters).
_READ_CHUNK = 1 << 18

_BACKGROUND_REFUSAL = (
    "bash: not started. Background jobs (#!bg) run in Pantheon's own container, and your "
    "commands run in your workstation, so nothing would watch this one or tell you when it "
    "ends. Run it without the #!bg line — in the workstation a long command streams its "
    "output to this card while it runs, for up to an hour — or, to leave it running after "
    "this turn, start it with `nohup <command> > ~/job.log 2>&1 &` and read ~/job.log later."
)


# ── who, and where ────────────────────────────────────────────────────────────

def _routes_tools(owner: Optional[str]) -> bool:
    from src.workstation_access import routes_tools
    return routes_tools(owner)


def routes(tool: Optional[str], owner: Optional[str]) -> bool:
    """Does this call run in the workstation? One of the nine tools, and
    `routes_tools(owner)` — the workstation on, addressed, routing not switched
    off by an admin, and the person allowed to use it."""
    return isinstance(tool, str) and tool in WORKSTATION_TOOLS and _routes_tools(owner)


#: `B985`. `get_workspace` is refused to a non-admin because on this machine it
#: discloses the absolute host path of the workspace. For a person whose tools
#: run in the workstation it answers a folder in their own workstation home, or
#: the home itself (`describe_workspace`, `B968`) — one they picked in a picker
#: they may use and that their own `ls` would show. So it is lifted with the
#: nine, for exactly the people they are lifted for, and nothing else is.
WORKSPACE_TOOL = "get_workspace"
#: `P25-03`. `git` runs where the shell runs (`git_tools._Place`): in the
#: workstation home for exactly the people the nine are lifted for.
GIT_TOOL = "git"
LOGIN_SHELL_TOOL = "shell_with_login"   # `P27-07`: runs where `git` runs
#: `B1573`. For a person the server makes no requests for, `api_call` reaches
#: their own connections only and calls them from the workstation, by `curl`
#: in their account (`integrations.execute_api_call`) — what their `bash`
#: there already reaches. Never a shared one, never from this machine.
API_CALL_TOOL = "api_call"
LIFTED_TOOLS: FrozenSet[str] = WORKSTATION_TOOLS | {WORKSPACE_TOOL, GIT_TOOL, LOGIN_SHELL_TOOL,
                                                    API_CALL_TOOL}


def lifted_tools(owner: Optional[str]) -> FrozenSet[str]:
    """The part of the non-admin blocklist that does not apply to this person.

    `P20-03`: `bash`, `python` and the file tools are refused to a non-admin
    because on this machine they reach the process holding every secret
    (`tool_security.NON_ADMIN_BLOCKED_REASONS`). Routed to the workstation they
    reach the person's own workstation home instead, which is what
    `can_use_workstation` grants — so those nine are lifted for someone
    `routes_tools` says yes to, and `get_workspace` with them (`B985`: it then
    answers about that home). `manage_bg_jobs` stays refused: it still acts on
    this machine."""
    return LIFTED_TOOLS if _routes_tools(owner) else frozenset()


# ── the bridge from a worker thread to the client ─────────────────────────────

class _WorkstationIOError(OSError):
    """A workstation answer inside code written against files: an `OSError`,
    so the shared host code treats it as one, carrying the answer itself so the
    tool can put the workstation's own sentence in front of the person."""

    def __init__(self, error: WorkstationError):
        super().__init__(error.message)
        self.error = error


class _Station:
    """One call's workstation: the client, the account, and the event loop the
    client's coroutines run on (the shared file code runs in a worker thread
    and reaches back here)."""

    def __init__(self, client, account: str, loop: asyncio.AbstractEventLoop,
                 progress_cb: Optional[Callable[[Dict], Awaitable[None]]] = None,
                 *, workspace: Optional[str] = None, chat: Optional[Tuple] = None):
        self.client = client
        self.account = account
        self.loop = loop
        self.progress_cb = progress_cb
        self.failure: Optional[WorkstationError] = None
        self._home: Optional[str] = None
        # `B968`: the folder the tools start in, when one was picked.
        self.workspace = workspace or None
        # `B1646`: in a hire's run, `$PANTHEON_PROJECTS` naming the folder it
        # works in (`run_env`); empty leaves the daemon's own.
        self.run_env: Dict[str, str] = {}
        # `B962`: the chat this call belongs to, for its shell's folder, and
        # whether the daemon holds commands to the home (`sudo` off).
        self.chat = chat
        self.jailed = True
        # `B977`: the network mode holding this workstation's commands, from
        # the sync before the call (`workstation_access.network_held`).
        self.network: Optional[str] = None
        # `B1021`: the rules' refusal count from that same sync — the gate's
        # (`network_gate.refused`) or the daemon's own (`network_refused`) —
        # and which of the two to ask again after a command.
        self.refused_before: Optional[int] = None
        self.refused_by: Optional[str] = None

    async def home(self) -> str:
        if self._home is None:
            self._home = str((await self.client.ensure(self.account))["home"])
        return self._home


    def at(self, raw_path: Any) -> Any:
        """`B968`: a relative path as the daemon should be handed it — under
        the workspace when one is picked, as a relative path is the
        workspace's on Pantheon's machine. `~` and absolute paths are left as
        they are; the daemon resolves and jails every path either way."""
        if not self.workspace or raw_path is None:
            return raw_path
        text = str(raw_path).strip()
        if not text or text.startswith("/") or text == "~" or text.startswith("~/"):
            return raw_path
        return posixpath.join(self.workspace, text)

    async def shown(self, raw_path: str) -> str:
        """A path as the host's messages show one — absolute — for a path the
        daemon could not resolve because nothing is there."""
        return _absolute(await self.home(), raw_path, self.workspace)

    def call(self, coro_fn: Callable[[], Awaitable[Dict]]) -> Dict:
        """Run one client call from a worker thread. A `WorkstationError` comes
        out as `_WorkstationIOError`, and one that is the workstation failing
        (not a file answer) is remembered so the tool can answer with it."""
        try:
            return asyncio.run_coroutine_threadsafe(coro_fn(), self.loop).result()
        except WorkstationError as e:
            if e.code in _STATION_FAILURES:
                self.failure = e
            raise _WorkstationIOError(e) from e

    def text_opener(self, path: str, errors: Optional[str]) -> Callable[[], io.TextIOWrapper]:
        """An `open_text()` for the shared readers: `open(path, "r", encoding=
        "utf-8", errors=...)`'s own stack — a `TextIOWrapper` over a
        `BufferedReader` — over a raw layer that fetches the file's bytes from
        the workstation as they are needed. Same decoding, same universal
        newlines, same line iteration, because it is the same code."""
        station = self

        class _Raw(io.RawIOBase):
            def __init__(self):
                super().__init__()
                self.pos = 0

            def readable(self):
                return True

            def _fetch(self, want: int) -> bytes:
                got = station.call(lambda: station.client.read(
                    station.account, path, offset=self.pos, max_bytes=want))["data"]
                self.pos += len(got)
                return got

            def readinto(self, b):
                got = self._fetch(min(len(b), _READ_CHUNK * 4))
                b[:len(got)] = got
                return len(got)

            def readall(self):
                # `f.read()` of a whole file lands here; the base class would
                # ask 8 KiB at a time, one request each.
                chunks = []
                while True:
                    got = self._fetch(_READ_CHUNK * 16)
                    if not got:
                        return b"".join(chunks)
                    chunks.append(got)

        def _open():
            return io.TextIOWrapper(io.BufferedReader(_Raw(), buffer_size=_READ_CHUNK),
                                    encoding="utf-8", errors=errors)
        return _open


# ── paths ─────────────────────────────────────────────────────────────────────

def _absolute(home: str, raw: str, base: Optional[str] = None) -> str:
    """`raw` as an absolute path in the workstation: `~` is the home, and a
    relative path is `base`'s — the workspace (`B968`) — or else the home's, as
    the daemon reads them. Normalised, not resolved — the daemon resolves (and
    jails) every path it is handed."""
    text = str(raw).strip()
    if text == "~" or text.startswith("~/"):
        text = home + text[1:]
    elif not text.startswith("/"):
        text = posixpath.join(base or home, text)
    return posixpath.normpath(text)


def _sensitive(path: str) -> bool:
    from src.tool_execution import _is_sensitive_path
    # The workstation's paths are POSIX; the rule splits on this machine's
    # separator, so a Windows host still sees `.ssh` as a component.
    return _is_sensitive_path(path.replace("/", os.sep))


def _sensitive_message(raw_path: str) -> str:
    # The sentence `_resolve_tool_path` gives for the same path, so the model
    # meets one wording for one rule wherever the tool ran. A test holds them equal.
    return (f"path '{raw_path}' is inside a sensitive directory "
            f"(e.g. .ssh, .gnupg) or matches a sensitive filename")


def _path_refusal(tool: str, raw_path: str) -> Optional[Dict[str, Any]]:
    """Refuse an empty path or a sensitive one before the workstation is asked."""
    if raw_path is None or not str(raw_path).strip():
        return {"error": f"{tool}: path is required", "exit_code": 1}
    if _sensitive(str(raw_path).strip()):
        return {"error": f"{tool}: {_sensitive_message(raw_path)}", "exit_code": 1}
    return None


async def _stat_file(st: _Station, raw_path: str) -> Dict:
    """The file's resolved path and size, without its bytes — the daemon's `read`
    with `max_bytes=0`, which also applies the home jail."""
    return await st.client.read(st.account, raw_path, max_bytes=0)


async def _is_dir(st: _Station, raw_path: str) -> bool:
    try:
        await st.client.list(st.account, raw_path, max_entries=0)
        return True
    except WorkstationError:
        return False


def _file_answer(tool: str, e: WorkstationError) -> Dict[str, Any]:
    """A workstation answer about a file, worded as the host tool words it."""
    if e.code in _STATION_FAILURES:
        return e.as_result()
    return {"error": f"{tool}: {e.message}", "exit_code": 1}


# ── the shells ────────────────────────────────────────────────────────────────

# The daemon's answers that mean "not this folder" for an exec's `cwd`: it is
# not a directory there, or outside the home jail, or the account cannot enter it.
_FOLDER_REFUSALS = frozenset({"not_found", "outside_home", "forbidden"})

# `B962`. A home path, per workstation and account, so the start folder of a
# chat with no workspace is known without asking the daemon on every call.
# `list` with no path answers the home without starting a desktop (`ensure`
# would). The home of an account does not move while its daemon runs.
# `B1661`: while ITS daemon runs — so it is remembered per run of the daemon
# (`health`'s `run`), not per address. A daemon reinstalled or replaced at the
# address Pantheon knows has its homes where it keeps them, and was handed the
# old one's as every command's folder, refused *outside your home* until
# Pantheon restarted; the suite met it when a daemon was started on a port an
# earlier test's had freed. A client that has not asked `health` cannot say
# which daemon it reached, so it asks for the home; a daemon older than `run`
# answers "" and is remembered by its address, as before.
_HOMES: Dict[Tuple[str, str, str], str] = {}


async def _home_path(client, account: str) -> str:
    run = getattr(client, "daemon_run", None)
    if run is None:
        return str((await client.list(account, None, max_entries=0))["path"])
    key = (str(getattr(client, "base", "")), run, account)
    if key not in _HOMES:
        if len(_HOMES) >= 512:
            _HOMES.pop(next(iter(_HOMES)), None)
        _HOMES[key] = str((await client.list(account, None, max_entries=0))["path"])
    return _HOMES[key]


class _StationReport(sp._CwdReport):
    """`subprocess_tools._CwdReport`, written in the person's workstation home —
    one file per chat, overwritten by each of its `bash` calls — and read back
    through the protocol's `read`, as the person."""

    def __init__(self, chat: Tuple):
        name = "shell-cwd-" + hashlib.sha256(repr(chat).encode("utf-8")).hexdigest()[:16]
        self.path = f"~/.cache/pantheon-run/{name}"
        super().__init__(f'"$HOME"/.cache/pantheon-run/{name}')

    async def read(self, st: "_Station") -> Optional[str]:
        try:
            got = await st.client.read(st.account, self.path, max_bytes=65536)
        except WorkstationError:
            return None
        return self.parse(got.get("data") or b"")


def _refused_sentence(folder: str, code: str, workspace: Optional[str], ran_in: str) -> str:
    if folder == workspace:
        return (f"The workspace {folder} is not a folder in your workstation any more, so "
                f"this command started in {ran_in}.")
    if code == "not_found":
        return sp.gone_sentence(folder, ran_in)
    return (f"This chat's shell was in {folder}, which the workstation does not let it use "
            f"now, so this command started in {ran_in}.")


async def _shell(st: _Station, tool: str, shell: str, command: str, timeout: float) -> Dict:
    if not str(command or "").strip():
        # An empty script does nothing and exits 0 — what `bash -c ""` and
        # `python -c ""` answer here. The daemon refuses an empty command, so
        # the answer is given without asking it.
        return sp._shell_result(tool, "", "", 0, False, timeout)
    started = time.time()
    tail: "collections.deque" = collections.deque(maxlen=sp.PROGRESS_TAIL_LINES)
    partial = {"stdout": "", "stderr": ""}

    # `B962`/`B968`. The folder this chat's shell is in, else the workspace,
    # else the home; each tried in turn if the daemon refuses the one before.
    notes: list = []
    start = held = home = None
    if st.chat is not None:
        home = await _home_path(st.client, st.account)
        start = st.workspace or home
        held, said = sp.CHAT_FOLDERS.recall(st.chat, start)
        notes += [said] if said else []
    report = _StationReport(st.chat) if (st.chat is not None and shell == "bash") else None
    scrub = report.scrub if report else (lambda text: text)

    def on_output(kind: str, text: str) -> None:
        # Whole lines only, as the host's `readline` reader sees them.
        kind = "stderr" if kind == "stderr" else "stdout"
        *complete, partial[kind] = (partial[kind] + text).split("\n")
        for line in complete:
            tail.append(sp._tail_line(scrub(line), "err" if kind == "stderr" else "out"))

    emitter = (asyncio.create_task(sp._progress_emitter(st.progress_cb, started, tail))
               if st.progress_cb else None)
    refused = []
    try:
        tries = list(dict.fromkeys(c for c in (held, st.workspace) if c)) + [None]
        for cwd in tries:
            try:
                r = await st.client.exec(st.account, report.wrap(command) if report else command,
                                         shell=shell, cwd=cwd, timeout_s=timeout,
                                         env={**_SHELL_ENV, **st.run_env},
                                         on_output=on_output if st.progress_cb else None)
                break
            except WorkstationError as e:
                # Refused before anything ran (`agentd._exec_prepare` checks the
                # folder first), so the next folder is a first try, not a rerun.
                if cwd is None or e.code not in _FOLDER_REFUSALS:
                    raise
                if cwd == held:
                    sp.CHAT_FOLDERS.forget(st.chat)
                refused.append((cwd, e.code))
    finally:
        if emitter is not None:
            emitter.cancel()
            try:
                await emitter
            except (asyncio.CancelledError, Exception):
                pass
    stdout = scrub(str(r.get("stdout") or ""))
    stderr = scrub(str(r.get("stderr") or ""))
    result = sp._shell_result(tool, stdout, stderr, r.get("exit_code"),
                              bool(r.get("timed_out")), timeout)
    ran_in = str(r.get("cwd") or "")
    notes += [_refused_sentence(folder, code, st.workspace, ran_in) for folder, code in refused]
    if ran_in:
        result["cwd"] = ran_in
    if report is not None and ran_in:
        result["cwd"] = _end_folder(st.chat, start, ran_in, await report.read(st), notes,
                                    home=home if st.jailed else None)
    if r.get("truncated"):
        # The daemon keeps the END of each stream past `MAX_OUTPUT_BYTES`
        # (the end is where the error is); the host keeps it all and cuts the
        # start. Said, so a reader of the output knows its head is missing.
        from workstation.protocol import MAX_OUTPUT_BYTES
        result["note"] = (f"The workstation keeps the last {MAX_OUTPUT_BYTES:,} bytes of each "
                          "stream; the start of this output was dropped there.")
    said = network_refusal_note(st.network, stdout, stderr,
                                command=command)   # `B1011`: the command too
    if said is None:
        # `B1021`: nothing in the output shows a refusal — `nc -u` swallows
        # its EPERM and exits 0 — so ask the one witness, the rules' counter.
        said = silent_refusal_note(st.network, st.refused_before, await _refused_now(st))
    notes.append(said)
    return sp.add_note(result, *notes)


# ── a connection the network mode refused (`B977`) ───────────────────────────
#
# Under *internet* or *none* the gate's rules refuse at once (`reject with icmpx
# admin-prohibited`, `workstation/netrules.py`), and what a program prints then
# names no policy. Measured 2026-10-01 in the image under the real rules: Python,
# bash's `/dev/tcp` and `curl -v` say *No route to host* (EHOSTUNREACH, errno
# 113); **curl 8.5 and git over http say only *Couldn't connect to server***;
# under *none* a name does not resolve either — *Could not resolve host* (curl,
# git), *Temporary failure in name resolution* (Python, getent). An agent reading
# those debugs a network that is working as an admin set it. So a result whose
# output shows one of them, from a workstation whose mode is held, says the mode.
# Not read as one: *Network is unreachable*, which the rules never cause (no
# route at all). A UDP send's *Operation not permitted* — which a file permission
# error also says — is read only where the output tells the two apart (`B1011`,
# below).
_REFUSED_RE = re.compile(r"No route to host|Couldn't connect to server|EHOSTUNREACH")
_UNRESOLVED_RE = re.compile(r"Could not resolve host|Temporary failure in name resolution|"
                            r"Temporary failure resolving|unable to resolve host address")
# An address the refusal names: dotted IPv4, or IPv6 in brackets — and not the
# one after "from", which `curl -v` prints for the workstation's own end.
_ADDRESS_RE = re.compile(r"(?<!from )(?<![\w.:])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])"
                         r"|(?<!from )\[([0-9A-Fa-f:.]+)\]")

NETWORK_NONE_NOTE = (
    "This workstation has no network: an admin set its network mode to none, so every "
    "connection out of it is refused at once and names do not resolve. That is the setting, "
    "not a fault to debug — ask an admin if the work needs the network.")
NETWORK_PRIVATE_NOTE = (
    "{address} is a private address, and this workstation's network mode is internet only "
    "(an admin's setting): it refuses your local network and every other private address at "
    "once. That is the setting, not a fault to debug — ask an admin if the work needs it.")
NETWORK_INTERNET_NOTE = (
    "This workstation's network mode is internet only (an admin's setting): it refuses your "
    "local network and every other private address at once, which shows as \"No route to "
    "host\" or \"Couldn't connect to server\". If this connection was to one, that is the "
    "setting, not a fault to debug.")

# ── a send the network mode refused (`B1011`) ────────────────────────────────
#
# Measured 2026-10-01 under the gate's real *internet* rules (`netrules.ruleset`
# loaded with nft into a fresh network namespace with a default route; kernel
# 6.18, Python 3.11, bash 5.2, OpenBSD netcat 1.226 — Ubuntu's): a UDP send to a
# refused address fails at once with EPERM, and
#
# * **Python** quotes the send — `s.sendto(b'x', ('192.168.1.1', 161))` — above
#   `PermissionError: [Errno 1] Operation not permitted`, and nothing after it.
#   A file operation's EPERM ends with the file's name (`…not permitted:
#   '/path'`); a send's never does, and the line above it is a send. Both read,
#   so `os.chown` and `os.kill` (no name, not a send) are not taken for one.
#   mDNS's `224.0.0.251` is refused the same way (`224.0.0.0/3`).
# * **bash** `echo hi > /dev/udp/192.168.1.1/161` prints `bash: line 1: echo:
#   write error: Operation not permitted` — word for word what a write a file
#   refuses prints. Read as a send only when the command itself writes to
#   `/dev/udp/`, and the address is the command's.
# * **`nc -u`** prints nothing and exits 0, with or without `-v`: nothing in the
#   result shows a refusal, so nothing is said (filed — only the gate's own
#   counters could tell it).
#
# A send to a public address is never the gate's (it refuses only `excluded`
# ones), so one that failed this way was somebody else's and is left alone.
_PY_EPERM_RE = re.compile(r"^(?:PermissionError|OSError): \[Errno 1\] Operation not permitted\s*$")
_PY_SEND_RE = re.compile(r"\.(?:sendto|sendall|sendmsg|send)\(")
_WRITE_EPERM_RE = re.compile(r"write error: Operation not permitted")
_DEV_UDP_RE = re.compile(r"/dev/udp/([^/\s'\"]+)/\d+")

NETWORK_SEND_NOTE = (
    "{address} is {kind}, and this workstation's network mode is internet only (an admin's "
    "setting): it refuses every send to your local network, multicast and every other private "
    "address at once. Here that shows as \"Operation not permitted\" — the setting, not a file "
    "permission or a fault to debug. Ask an admin if the work needs it.")
NETWORK_SEND_INTERNET_NOTE = (
    "This workstation's network mode is internet only (an admin's setting): it refuses every "
    "send to your local network, multicast and every other private address at once, which "
    "shows as \"Operation not permitted\". If this send was to one, that is the setting, not a "
    "file permission or a fault to debug.")


# ── a refusal nothing printed (`B1021`) ──────────────────────────────────────
#
# Measured 2026-10-26 under the gate's real *internet* rules (`netrules.ruleset`
# loaded into a fresh network namespace with a default route; OpenBSD netcat
# 1.226): `echo hi | nc -u -w1 192.168.1.1 161` prints nothing and exits 0, with
# or without `-v` — the kernel's EPERM is swallowed — while the counter on the
# rule that refused it went 0 → 1. So the counts the gate (and the daemon's own
# rules) report either side of a routed command are the one witness. **Racy, and
# said so**: a second command in flight on the same workstation counts too.
NETWORK_SILENT_NOTE = (
    "Nothing in this command's output says so, but this workstation's network rules refused "
    "{n} send{s} or connection{s} while it ran. Its network mode is {mode} (an admin's "
    "setting){scope}. A program that prints nothing and succeeds — `nc -u` does — may have "
    "had its packets refused: that is the setting, not \"nothing answered\". (Another "
    "command running on this workstation at the same time counts too.)")


def silent_refusal_note(mode: Optional[str], before: Optional[int],
                        after: Optional[int]) -> Optional[str]:
    """`B1021`: the sentence for a command whose output shows no refusal while
    the rules' counter rose during it, or None — no narrowing mode, a count not
    read on either side, or no rise. A count that FELL means the rules were
    reloaded meanwhile (a new mode starts the count again), and says nothing."""
    if mode not in ("internet", "none"):
        return None
    if not isinstance(before, int) or not isinstance(after, int) or after <= before:
        return None
    n = after - before
    scope = (": it refuses your local network, multicast and every other private address"
             if mode == "internet" else ": it refuses every connection out")
    return NETWORK_SILENT_NOTE.format(n=n, s="" if n == 1 else "s",
                                      mode="internet only" if mode == "internet" else "none",
                                      scope=scope)


def refusals_from(daemon: Optional[Dict]) -> tuple:
    """`(count, by)` from one synced daemon answer: the gate's count when a
    gate holds the mode, the daemon's own when its accounts table does."""
    daemon = daemon or {}
    gate = daemon.get("network_gate")
    if isinstance(gate, dict):
        n = gate.get("refused")
        return (n if isinstance(n, int) else None), "gate"
    if daemon.get("network_enforcement") == "accounts":
        n = daemon.get("network_refused")
        return (n if isinstance(n, int) else None), "accounts"
    return None, None


async def _refused_now(st) -> Optional[int]:
    """The count after the command, from whoever reported it before."""
    if st.refused_before is None or st.network not in ("internet", "none"):
        return None
    try:
        if st.refused_by == "gate":
            from src.workstation_client import gate_for
            gate = gate_for(st.client)
            n = (await gate.health()).get("refused") if gate is not None else None
        else:
            n = (await st.client.health()).get("network_refused")
    except WorkstationError:
        return None
    return n if isinstance(n, int) else None


def _refused_sends(text: str, command: str):
    """`B1011`: `(found, addresses)` — whether the output shows a send refused
    with EPERM in a shape a file error never has, and the addresses it went to
    where the output (Python) or the command (bash's `/dev/udp`) names them."""
    import ipaddress
    found, named = False, []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _PY_EPERM_RE.match(line.strip()):
            continue
        # The source line the traceback quotes for the frame that raised: the
        # nearest indented line above, past Python 3.11's `^^^^` markers.
        quoted = next((ln for ln in reversed(lines[:i])
                       if ln.startswith("    ") and ln.strip().strip("^~ ")), "")
        if _PY_SEND_RE.search(quoted):
            found = True
            named += _addresses([quoted])
    if _WRITE_EPERM_RE.search(text):
        for host in _DEV_UDP_RE.findall(command or ""):
            found = True
            try:
                named.append(str(ipaddress.ip_address(host.strip("[]"))))
            except ValueError:
                continue   # a name: where it went is not known here
    return found, named


def _send_kind(address: str) -> str:
    import ipaddress
    return ("a multicast address" if ipaddress.ip_address(address).is_multicast
            else "a private address")


def network_refusal_note(mode: Optional[str], *outputs: str,
                         command: str = "") -> Optional[str]:
    """The sentence for a command whose output shows a connection — or, `B1011`,
    a send — refused the way the network mode `mode` refuses one, or None —
    when no narrowing mode is held, when nothing in the output is such a
    refusal, or when every address the refusal names is one the mode lets
    through (the refusal was somebody else's). `command`, what ran: read only
    for where a bash `/dev/udp/` write was sent."""
    if mode not in ("internet", "none"):
        return None
    text = "\n".join(o for o in outputs if o)
    lines = [ln for ln in text.splitlines() if _REFUSED_RE.search(ln)]
    sent, sent_to = _refused_sends(text, command)
    if mode == "none":
        return NETWORK_NONE_NOTE if lines or sent or _UNRESOLVED_RE.search(text) else None
    from workstation import netrules
    # The address the refusal names, where it names one (curl, git, bash);
    # else the output's (a Python traceback quotes the line with the address
    # above the error that has none).
    named = (_addresses(lines) or _addresses(text.splitlines())) if lines else []
    private = [a for a in named if netrules.excluded(a)]
    if private:
        return NETWORK_PRIVATE_NOTE.format(address=private[0])
    # `B1011`: a refused send. A refused address named beats a sentence that
    # can only say "if" — whichever of the two kinds of refusal names it — and a
    # connection refused at a public address (somebody else's) leaves a send in
    # the same output still to read.
    private = [a for a in sent_to if netrules.excluded(a)] if sent else []
    if private:
        return NETWORK_SEND_NOTE.format(address=private[0], kind=_send_kind(private[0]))
    if lines and not named:
        return NETWORK_INTERNET_NOTE
    if sent and not sent_to:
        return NETWORK_SEND_INTERNET_NOTE
    return None


def _addresses(lines) -> list:
    import ipaddress
    out = []
    for ln in lines:
        for a, b in _ADDRESS_RE.findall(ln):
            try:
                out.append(str(ipaddress.ip_address(a or b)))
            except ValueError:
                continue
    return out


def _end_folder(chat: Tuple, start: str, ran_in: str, ended_in: Optional[str],
                notes: list, *, home: Optional[str]) -> str:
    """`subprocess_tools.host_end_folder` for the workstation: record where the
    chat's shell ended, answer where its next call starts.

    Held to the rules the file tools meet there: the home jail when the daemon
    applies one (`home`, given while `sudo` is off), and the sensitive-folder
    rule this side applies on top. The daemon checks the jail again when the
    folder is next used, so a `sudo` switched off in between is still caught."""
    if ended_in is None:
        return ran_in
    if ended_in == start:
        sp.CHAT_FOLDERS.forget(chat)
        return start
    why = None
    if home is not None and not within(ended_in, home):
        why = "outside your workstation home"
    elif _sensitive(ended_in):
        why = "a sensitive folder (such as .ssh) the file tools refuse"
    if why:
        sp.CHAT_FOLDERS.forget(chat)
        notes.append(f"The shell ended in {ended_in}, {why}, so the next command starts in "
                     f"{start}.")
        return start
    sp.CHAT_FOLDERS.keep(chat, start, ended_in)
    return ended_in


async def _bash(content: Any, st: _Station) -> Dict:
    return await _shell(st, "bash", "bash", sp._bash_command(content), sp.DEFAULT_BASH_TIMEOUT)


async def _python(content: Any, st: _Station) -> Dict:
    # `-I` is not carried over: on this machine it keeps Pantheon's own
    # environment out of the child; in the workstation there is none to keep
    # out, and the person's `pip install --user` packages should import.
    return await _shell(st, "python", "python", content, sp.DEFAULT_PYTHON_TIMEOUT)


# ── the file tools ────────────────────────────────────────────────────────────

async def _read_file(content: str, st: _Station) -> Dict:
    raw_path, offset, limit = fs._read_file_args(content)
    refused = _path_refusal("read_file", raw_path)
    if refused:
        return refused
    try:
        path = (await _stat_file(st, st.at(raw_path)))["path"]
    except WorkstationError as e:
        if e.code == "not_found":
            shown = await st.shown(raw_path)
            if await _is_dir(st, st.at(raw_path)):
                return {"error": f"read_file: {shown}: is a directory (use ls)", "exit_code": 1}
            return {"error": f"read_file: {shown}: not found", "exit_code": 1}
        return _file_answer("read_file", e)
    if _sensitive(path):
        return {"error": f"read_file: {_sensitive_message(raw_path)}", "exit_code": 1}
    try:
        data = await asyncio.to_thread(fs._read_text, st.text_opener(path, "replace"),
                                       offset, limit, fs._read_cap())
    except _WorkstationIOError as e:
        return _file_answer("read_file", e.error)
    return {"output": data, "exit_code": 0}


async def _write_file(content: str, st: _Station) -> Dict:
    raw_path, body, append = fs._write_file_call(content)
    refused = _path_refusal("write_file", raw_path)
    if refused:
        return refused
    old = ""
    try:
        existing = (await _stat_file(st, st.at(raw_path)))["path"]
    except WorkstationError as e:
        if e.code in _STATION_FAILURES or e.code == "outside_home":
            return _file_answer("write_file", e)
        existing = None   # not there yet, or not a file: the diff shows it new
    if existing is not None:
        if _sensitive(existing):
            return {"error": f"write_file: {_sensitive_message(raw_path)}", "exit_code": 1}
        # The host rule (`_previous_text`): unreadable as UTF-8 text is "".
        old = await asyncio.to_thread(fs._previous_text, st.text_opener(existing, None))
        if st.failure is not None:
            return st.failure.as_result()
    try:
        # `B1672`: an append the daemon makes itself (`"append"`, in its
        # protocol from the start), keeping every byte the file had.
        written = await st.client.write(st.account, existing or st.at(raw_path), body,
                                        append=append)
    except WorkstationError as e:
        if e.code == "bad_request" and await _is_dir(st, st.at(raw_path)):
            # The answer `open(path, "w")` gives here, word for word.
            shown = await st.shown(raw_path)
            why = IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), shown)
            return {"error": f"write_file: {shown}: {why}", "exit_code": 1}
        return _file_answer("write_file", e)
    if existing is None:
        # `B1660`: nothing was there, so this run made it — its next write
        # over it is a plain write (`src/run_files.py`).
        from src.run_files import IN_WORKSTATION, note_made
        note_made(raw_path, IN_WORKSTATION)
    return fs._write_result(written["path"], old, body, append)


async def held_a_file(raw_path: str, *, owner: Optional[str],
                      workspace: Optional[str] = None) -> Optional[bool]:
    """`B1660`. Does `raw_path` hold a file in this person's workstation, as
    `write_file` there would find it? `True`, `False`, or `None` when the
    workstation could not say (down, off, not this person's) — which the gate
    reads as destructive (`src/run_files.py`).

    Asked as `_write_file` asks it, through the same folder rule
    (`station_folder`) and the same stat, and answered as it answers: a path
    it refuses before asking writes nothing, and anything but a station that
    could not answer is "not there yet, or not a file" — a new file."""
    from src.workstation_access import sync_config, workstation_for
    if _path_refusal("write_file", raw_path):
        return False
    try:
        client, account = workstation_for(owner)
        daemon = await sync_config(client)
    except WorkstationError:
        return None
    folder, _said = station_folder(owner, account, workspace, daemon)
    if folder and _sensitive(folder):
        folder = None
    st = _Station(client, account, asyncio.get_running_loop(), workspace=folder)
    try:
        await _stat_file(st, st.at(raw_path))
    except WorkstationError as e:
        # Outside the home `_write_file` refuses (nothing written); anything
        # else it reads as "not there yet, or not a file" and makes one.
        return None if e.code in _STATION_FAILURES else False
    return True


async def shell_station(*, owner: Optional[str], workspace: Optional[str] = None,
                        session_id: Optional[str] = None, hired: bool = False):
    """`B1669`. Where this person's next `bash` or `python` command in their
    workstation starts, and a way to ask what is at a path there:
    `(starts, home, kind_at, values, names_at, link_at)`, or `None` when
    the workstation cannot be asked — which the gate reads as destructive
    (`src/run_files.py`). `names_at(path)` (`B1693`): the files in a folder,
    for the numbered copies a converter may write over; `link_at(path)`
    (`B1696`): whether what is there is a symbolic link, for a copy that
    keeps one.

    Asked as `_shell` asks it: the folder the chat's shell was left in
    (`B962`, read without moving it) and the folder a command starts in when
    none is held — the workspace as the workstation names it
    (`station_folder`), else the home. `kind_at(path)` is `"file"`,
    `"folder"`, `"none"`, or `None` when the workstation could not say (down,
    or a path outside what it lets this person look at).

    `values` (`B1681`): the variables a path in the command may start with,
    as its shell there has them — `$HOME`, and in a hire's run (`hired`)
    `$PANTHEON_PROJECTS`, which Pantheon sets itself (`run_env`) to the
    folder the run works in. `B1684`: any other run's — a chat's — is the
    daemon's own, which it reports (`account`'s `projects_env`, the rule
    `agentd._exec_prepare` gives it by) rather than Pantheon guessing it from
    `projects_folder`; from a daemon that does not report it, a path spelled
    against it stays unknown."""
    from src.run_files import FILE, FOLDER, NOTHING
    from src.workstation_access import sync_config, workstation_for
    try:
        client, account = workstation_for(owner)
        daemon = await sync_config(client)
        home = await _home_path(client, account)
    except WorkstationError:
        return None
    folder, _said = station_folder(owner, account, workspace, daemon)
    if folder and _sensitive(folder):
        folder = None
    start = folder or home
    held = sp.CHAT_FOLDERS.peek(sp.chat_key("workstation", account, session_id), start)
    # The daemon reads a relative folder from the home.
    start = start if start.startswith("/") else posixpath.join(home, start)
    st = _Station(client, account, asyncio.get_running_loop(), workspace=folder)

    async def kind_at(path: str) -> Optional[str]:
        try:
            await _stat_file(st, path)
            return FILE
        except WorkstationError as e:
            if e.code in _STATION_FAILURES or e.code in ("outside_home", "forbidden"):
                return None
        return FOLDER if await _is_dir(st, path) else NOTHING

    async def names_at(path: str) -> Optional[List[str]]:
        """`B1693`. The files in the folder at `path` — a link counts, a
        write goes through it — or `None`: not listed whole, or not at all."""
        try:
            listing = await st.client.list(st.account, path)
        except WorkstationError:
            return None
        if listing.get("truncated"):
            return None
        return [str(e.get("path") or "") for e in listing.get("entries") or ()
                if e.get("type") in ("file", "symlink")]

    async def link_at(path: str) -> Optional[str]:
        """`B1696`. Whether what is at `path` is a symbolic link, as its
        folder's listing says: `""` when it is not, or nothing is (there is
        no such folder); `None` when it is one — the daemon does not give a
        link's text — or that could not be said."""
        parent, name = posixpath.split(path.rstrip("/"))
        if not name:
            return ""                   # the root: a folder
        try:
            listing = await st.client.list(st.account, parent or "/")
        except WorkstationError as e:
            return "" if e.code == "not_found" else None
        for entry in listing.get("entries") or ():
            if entry.get("path") == name:
                return None if entry.get("type") == "symlink" else ""
        return None if listing.get("truncated") else ""

    from src.tool_execution import run_projects_folder
    values = {"HOME": home}
    projects = run_projects_folder(folder, hired) or await _given_projects(client, account)
    if projects:
        values[P.PROJECTS_ENV] = projects   # what `run_env`, or the daemon, hands the command
    return (list(dict.fromkeys(f for f in (held, start) if f)), home, kind_at, values, names_at,
            link_at)


async def _given_projects(client, account: str) -> Optional[str]:
    """`B1684`. The folder the daemon gives this person's every command as
    `$PANTHEON_PROJECTS` when Pantheon hands it none (`run_env`), as the
    daemon reports it — or `None` from one that does not say (older than the
    report; a VM machine that is not running) or cannot be asked."""
    try:
        seen = await client.account(account)
    except WorkstationError:
        return None
    given = (seen or {}).get("projects_env")
    return given if isinstance(given, str) and given.startswith("/") else None


async def _edit_file(content: str, st: _Station) -> Dict:
    raw_path, old, new, replace_all = fs._edit_file_args(content)
    if not raw_path:
        return {"error": "edit_file: path required", "exit_code": 1}
    if _sensitive(raw_path):
        return {"error": f"edit_file: {_sensitive_message(raw_path)}", "exit_code": 1}
    refused = fs._edit_args_error(old, new)
    if refused:
        return refused
    try:
        path = (await _stat_file(st, st.at(raw_path)))["path"]
    except WorkstationError as e:
        if e.code == "not_found":
            shown = await st.shown(raw_path)
            if await _is_dir(st, st.at(raw_path)):
                return {"error": f"edit_file: {shown}: not an editable text file", "exit_code": 1}
            return {"error": f"edit_file: {shown}: not found (use write_file to create it)",
                    "exit_code": 1}
        return _file_answer("edit_file", e)
    if _sensitive(path):
        return {"error": f"edit_file: {_sensitive_message(raw_path)}", "exit_code": 1}

    def _read_strict() -> str:
        with st.text_opener(path, None)() as f:
            return f.read()

    try:
        original = await asyncio.to_thread(_read_strict)
    except UnicodeDecodeError:
        return {"error": f"edit_file: {path}: not an editable text file", "exit_code": 1}
    except _WorkstationIOError as e:
        return _file_answer("edit_file", e.error)
    # The same transformation the host runs (`Law 14`), then one write.
    updated, status = fs._replace_exact(original, old, new, replace_all)
    if status == "ok":
        try:
            await st.client.write(st.account, path, updated)
        except WorkstationError as e:
            return _file_answer("edit_file", e)
    return fs._edit_result(path, original, updated, status, old)


class _WorkstationFiles:
    """`filesystem_tools._HostFiles`' six operations, against the workstation.
    Called from a worker thread by `_run_patch`, so a patch is prepared whole —
    every file read and every hunk matched — before anything is written, in the
    workstation exactly as here."""

    def __init__(self, st: _Station, home: str):
        self.st = st
        self.home = home

    def resolve(self, raw: str) -> str:
        if raw is None or not str(raw).strip():
            raise ValueError("path is required")
        if _sensitive(str(raw).strip()):
            raise ValueError(_sensitive_message(raw))
        path = _absolute(self.home, raw, self.st.workspace)
        if _sensitive(path):
            raise ValueError(_sensitive_message(raw))
        return path

    def _probe(self, fn) -> bool:
        try:
            self.st.call(fn)
            return True
        except _WorkstationIOError as e:
            if e.error.code == "not_found":
                return False
            raise

    def isfile(self, path: str) -> bool:
        return self._probe(lambda: self.st.client.read(self.st.account, path, max_bytes=0))

    def exists(self, path: str) -> bool:
        return self.isfile(path) or self._probe(
            lambda: self.st.client.list(self.st.account, path, max_entries=0))

    def read_text(self, path: str) -> str:
        with self.st.text_opener(path, None)() as f:
            return f.read()

    def write_text(self, path: str, text: str) -> None:
        self.st.call(lambda: self.st.client.write(self.st.account, path, text))

    def remove(self, path: str) -> None:
        # The protocol has no delete; `rm` runs as the person, on a path the
        # daemon has just resolved inside the home (`isfile` above).
        r = self.st.call(lambda: self.st.client.exec(
            self.st.account, f"rm -f -- {shlex.quote(path)}", timeout_s=60))
        if r.get("exit_code") != 0:
            raise OSError(str(r.get("stderr") or "").strip() or f"could not remove {path}")


async def _apply_patch(content: str, st: _Station) -> Dict:
    patch_text = fs._patch_text(content)
    if not patch_text.strip():
        return {"error": "apply_patch: patch_text required", "exit_code": 1}
    home = await st.home()
    result = await asyncio.to_thread(fs._run_patch, patch_text, _WorkstationFiles(st, home))
    if st.failure is not None:
        return st.failure.as_result()
    return result


async def _search_root(st: _Station, tool: str, raw: str, *, file_ok: bool) -> Tuple[Optional[str], Optional[Dict]]:
    """`_resolve_search_root` for the workstation: `(root, None)` or `(None, answer)`.
    Empty is the home, as empty is the workspace here; the daemon applies the jail."""
    raw = (raw or "").strip()
    if raw and _sensitive(raw):
        return None, {"error": f"{tool}: {_sensitive_message(raw)}", "exit_code": 1}
    try:
        # Empty is the workspace when one is picked (`B968`), else the home.
        root = (await st.client.list(st.account, st.at(raw) if raw else st.workspace,
                                     max_entries=0))["path"]
    except WorkstationError as e:
        if e.code != "not_found":
            return None, _file_answer(tool, e)
        if not file_ok:
            return None, {"error": f"{tool}: {await st.shown(raw)}: not a directory", "exit_code": 1}
        try:
            root = (await _stat_file(st, st.at(raw)))["path"]
        except WorkstationError as e2:
            if e2.code != "not_found":
                return None, _file_answer(tool, e2)
            # Nothing there: the host searches a missing root, finds nothing,
            # and says so under the path it was given.
            root = await st.shown(raw)
    if _sensitive(root):
        return None, {"error": f"{tool}: {_sensitive_message(raw)}", "exit_code": 1}
    return root, None


async def _ls(content: str, st: _Station) -> Dict:
    from src.tool_execution import _truncate
    raw_path = fs._ls_args(content)
    root, refused = await _search_root(st, "ls", raw_path, file_ok=False)
    if refused:
        return refused
    listing = await st.client.list(st.account, root)
    rows = [(e.get("type") == "dir", str(e.get("path") or ""),
             0 if e.get("type") == "dir" else int(e.get("size") or 0))
            for e in listing.get("entries") or () if not str(e.get("path") or "").startswith(".")]
    text = fs._ls_text(root, rows)
    if listing.get("truncated"):
        # A bound the host does not have: the daemon lists 5,000 entries at
        # most, so a larger directory's count here is a floor, and says so.
        from workstation.protocol import MAX_LIST_ENTRIES
        text += f"\n  ... [the workstation lists the first {MAX_LIST_ENTRIES:,} entries only]"
    return {"output": _truncate(text), "exit_code": 0}


async def _walk_in_workstation(st: _Station, args: Dict) -> Dict:
    """Run `codenav_walk`'s text in the workstation's own Python, as the person."""
    from src.tool_execution import _SENSITIVE_BASENAMES_CF, _SENSITIVE_FILE_PATTERNS_CF
    payload = dict(args, skip_dirs=sorted(fs._CODENAV_SKIP_DIRS),
                   sensitive_basenames_cf=sorted(_SENSITIVE_BASENAMES_CF),
                   sensitive_patterns_cf=sorted(_SENSITIVE_FILE_PATTERNS_CF))
    r = await st.client.exec(st.account, _codenav.workstation_program(), shell="python",
                             stdin=json.dumps(payload))
    if r.get("exit_code") != 0:
        why = (str(r.get("stderr") or "").strip().splitlines() or ["no output"])[-1]
        tool = args.get("op")
        if r.get("timed_out"):
            return {"err": f"{tool}: timed out"}
        return {"err": f"{tool}: the search in the workstation failed ({why})"}
    try:
        return json.loads(r.get("stdout") or "")
    except ValueError:
        return {"err": f"{args.get('op')}: the workstation's answer was not readable"}


async def _glob(content: str, st: _Station) -> Dict:
    from src.tool_execution import _SENSITIVE_BASENAMES
    args = fs._codenav_json_args(content)
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        return {"error": "glob: pattern is required", "exit_code": 1}
    root, refused = await _search_root(st, "glob", str(args.get("path", "")), file_ok=False)
    if refused:
        return refused
    got = await _walk_in_workstation(st, {
        "op": "glob", "root": root, "pattern": pattern, "max_hits": fs._CODENAV_MAX_HITS,
        "sensitive_dirs": sorted(_SENSITIVE_BASENAMES)})
    return fs._glob_result(got.get("paths"), got.get("err"), pattern, root)


async def _grep(content: str, st: _Station) -> Dict:
    from src.tool_execution import _SENSITIVE_FILE_PATTERNS
    args = fs._codenav_json_args(content)
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        return {"error": "grep: pattern is required", "exit_code": 1}
    ignore_case, glob_pat, max_hits = fs._grep_options(args)
    root, refused = await _search_root(st, "grep", str(args.get("path", "")), file_ok=True)
    if refused:
        return refused
    got = await _walk_in_workstation(st, {
        "op": "grep", "root": root, "pattern": pattern, "ignore_case": ignore_case,
        "glob": glob_pat, "max_hits": max_hits, "max_line": fs._CODENAV_MAX_LINE,
        "sensitive_file_patterns": list(_SENSITIVE_FILE_PATTERNS)})
    return fs._grep_result(got.get("lines"), got.get("err"), pattern, root, max_hits)


_HANDLERS: Dict[str, Callable[[Any, _Station], Awaitable[Dict]]] = {
    "bash": _bash, "python": _python, "read_file": _read_file, "write_file": _write_file,
    "edit_file": _edit_file, "apply_patch": _apply_patch, "ls": _ls, "glob": _glob,
    "grep": _grep,
}
assert set(_HANDLERS) == WORKSTATION_TOOLS


# ── the entry point ───────────────────────────────────────────────────────────

def _describe(tool: str, content: Any) -> str:
    """The dispatcher's own `desc` for these tools, so the model's `### …`
    header reads the same wherever the call ran."""
    first_line = str(content or "").split("\n")[0][:80]
    if tool == "apply_patch":
        return f"{tool}: {first_line}" if first_line else tool
    return f"{tool}: {first_line}"


def _where(result: Dict, account: str) -> Dict:
    out = dict(result)
    out["ran_in"] = "workstation"
    out["ran_as"] = account
    return out


async def run_in_workstation(tool: str, content: Any, *, owner: Optional[str],
                             session_id: Optional[str] = None,
                             progress_cb: Optional[Callable[[Dict], Awaitable[None]]] = None,
                             workspace: Optional[str] = None,
                             ) -> Tuple[str, Dict]:
    """Run one of `WORKSTATION_TOOLS` in the person's workstation: `(desc, result)`.

    `workspace` is the folder picked in the composer — a folder in the
    person's workstation home (`B968`); `session_id` is the chat, whose shell
    keeps its folder between calls (`B962`)."""
    from src.tool_execution import _split_bg_marker
    from src.workstation_access import account_of as account_for
    from src.workstation_access import network_held, sync_config, workstation_for

    desc = _describe(tool, content)
    if tool == "bash" and session_id and isinstance(content, str):
        # Where the dispatcher would launch a `#!bg` job on this machine.
        is_bg, bg_cmd = _split_bg_marker(content)
        if is_bg and bg_cmd:
            return desc, _where({"error": _BACKGROUND_REFUSAL, "exit_code": 1},
                                account_for(owner))
    try:
        client, account = workstation_for(owner)
        # The admin's `sudo` pushed to a daemon that restarted and forgot it
        # (`P20-02`'s handoff), before the command it governs. Not the whole
        # `ensure_ready`: `ensure` also starts a desktop (~18 MiB a person,
        # measured in `P20-01`), and `exec` and the file routes make the account
        # without one, so a person who only uses the shell does not pay for it.
        daemon = await sync_config(client)
    except WorkstationError as e:
        return desc, _where(e.as_result(), account_for(owner))
    # `B1642`: a hire's projects folder, as the workstation names it.
    workspace, said = station_folder(owner, account, workspace, daemon)
    there, mounted = projects_folder(daemon, account)
    if (not said and there and not mounted and tool in ("bash", "python")
            and P.PROJECTS_ENV in str(content or "")):
        said = no_projects_sentence(there)   # `B1643`: the `cd` that cannot go there
    if workspace and _sensitive(workspace):
        # Vetted when it was picked (`vet_workspace`); held to the rule again
        # here, as `_resolve_tool_path` holds a host workspace to it.
        workspace = None
    st = _Station(client, account, asyncio.get_running_loop(), progress_cb,
                  workspace=workspace, chat=sp.chat_key("workstation", account, session_id))
    # `B1646`: a hire's run's folder, as the workstation names it, is its
    # `$PANTHEON_PROJECTS` — none when nothing is mounted (`B1643` says why).
    st.run_env = run_env(workspace)
    st.jailed = (daemon or {}).get("sudo") is not True
    st.network = network_held(daemon)   # `B977`
    st.refused_before, st.refused_by = refusals_from(daemon)   # `B1021`
    try:
        result = await _HANDLERS[tool](content, st)
    except WorkstationError as e:
        result = e.as_result()
    except Exception as e:  # noqa: BLE001 — the same catch `_direct_fallback` gives the host tools
        logger.warning("workstation %s failed: %s", tool, type(e).__name__)
        result = {"error": f"{tool}: {e}", "exit_code": 1}
    if tool == "edit_file":
        desc = result.get("output") or result.get("error") or "edit_file"
    if said:
        sp.add_note(result, said)
    return desc, _where(result, account)


# ── the workspace, with the workstation on (`B968`) ──────────────────────────

def within(path: str, home: str) -> bool:
    return path == home or path.startswith(home.rstrip("/") + "/")


def projects_folder(daemon: Optional[Dict], account: str) -> Tuple[Optional[str], bool]:
    """`B1642`. The person's projects folder as their workstation names it —
    `projects_root/<name>`, the daemon's own report (`health`) and the folder
    it gives every command as `$PANTHEON_PROJECTS` — and whether anything is
    mounted there. `(None, False)` from a daemon older than the report."""
    root = (daemon or {}).get("projects_root")
    if not isinstance(root, str) or not root.startswith("/"):
        return None, False
    return (posixpath.join(root, P.project_folder_of(account)),
            (daemon or {}).get("projects_mounted") is True)


def own_reach(home: str, daemon: Optional[Dict], account: str) -> Tuple[str, ...]:
    """`B1642`/`B1647`. The folders of the person's own a tool Pantheon runs in
    their workstation is pointed at: their home, and their own projects folder
    when one is mounted (`B1417` — the daemon's jail admits it beside the home,
    and a hire's run works there). Never another person's folder, never the
    root every person's folder is in. `vet_workspace` and `git`'s place
    (`git_tools._Place`) ask this one question."""
    projects, mounted = projects_folder(daemon, account)
    return (home,) + ((projects,) if projects is not None and mounted else ())


def no_projects_sentence(folder: str) -> str:
    """`B1643`. Why a command that works in the person's projects folder in
    the workstation cannot: nothing is mounted where it goes."""
    return (f"Your projects folder, {folder}, is not in this workstation: nothing is mounted at "
            f"{posixpath.dirname(folder)}, so ${P.PROJECTS_ENV} names a folder that is not there "
            "and a command cannot go into it. An admin mounts Pantheon's projects folder there "
            "(Pantheon's docker-compose.yml mounts it as /projects).")


def station_folder(owner: Optional[str], account: str, workspace: Optional[str],
                   daemon: Optional[Dict]) -> Tuple[Optional[str], Optional[str]]:
    """`B1642`. A workspace as the person's workstation names it, and the
    sentence to add when the folder it names is not there.

    A hire's run works in its projects folder (`runtime.workspace_for`: the
    person's `<data>/projects/<name>`, or its project inside it), named as
    Pantheon's machine names it. In the workstation the same folder is
    `projects_folder` — the overlay mounts one as the other — so the hire's
    shell starts there and its file tools read a relative path from there,
    where its runbook's `cd "$PANTHEON_PROJECTS"/…` goes. They read it from the
    home: `write_file` of `My Site/index.html` wrote `~/My Site/index.html`
    and the folder the runbook served stayed empty. Any other workspace was
    picked in the workstation (`vet_workspace`) and is its name already. With
    nothing mounted the run starts in the home, as it did, and says why; a
    daemon that does not report its projects folder is answered as before."""
    if not workspace:
        return None, None
    from src.tool_execution import projects_root
    here = os.path.realpath(projects_root(owner, create=False))
    folder = os.path.realpath(workspace)
    if folder != here and not folder.startswith(here + os.sep):
        return workspace, None
    there, mounted = projects_folder(daemon, account)
    if there is None:
        return None, None
    if not mounted:
        return None, no_projects_sentence(there) + " This ran in your workstation home instead."
    rel = os.path.relpath(folder, here)
    return (there if rel == os.curdir else posixpath.join(there, *rel.split(os.sep))), None


async def workspace_in_workstation(owner: Optional[str], workspace: Optional[str]) -> Optional[str]:
    """`B1642`. A hire's workspace for its whole run — its prompt's "Active
    workspace", its tool calls, its approvals — as the person's workstation
    names it, where their tools run there; otherwise, or when the workstation
    cannot name it now (down, or nothing mounted), as it was: each call then
    names it again, or says why it cannot (`run_in_workstation`)."""
    from src.workstation_access import routes_tools, workstation_for
    if not workspace or not routes_tools(owner):
        return workspace
    try:
        client, account = workstation_for(owner)
        named, said = station_folder(owner, account, workspace, await client.health())
    except WorkstationError:
        return workspace
    return named if named and not said else workspace


async def vet_workspace(owner: Optional[str], raw: Optional[str]) -> Optional[str]:
    """`tool_execution.vet_workspace` for the workstation: the canonical path
    of a folder in the person's workstation home, or None — not a folder there,
    outside the home, or a sensitive folder. Asked when the picker sets one,
    when a chat sends one, and when an approved action replays one (the three
    places the host's is asked). Raises `WorkstationError` when the workstation
    itself cannot answer, so a caller can tell "no" from "down".

    The home, not the jail: with `sudo` on the daemon resolves `/etc` too, and
    the owner's call is *a folder in my workstation home*. `B1642`: or in the
    person's own projects folder there — where a hire's run works, and where
    its approved action is replayed (`station_folder`) — which the jail admits
    beside the home (`B1417`); never another person's."""
    return (await _vetted(owner, raw))[0]


async def sealed_workspace_holds(owner: Optional[str], sealed: str) -> bool:
    """`tool_execution._sealed_workspace_holds` for the workstation: whether
    the folder an approved action was sealed with is still, canonically, the
    folder it names there. `B1642`: a hire's is named as Pantheon names it, so
    it is compared as the workstation names it (`station_folder`)."""
    path, named = await _vetted(owner, sealed)
    return path is not None and path == named


async def _vetted(owner: Optional[str], raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """`(canonical path or None, the folder asked about as the workstation
    names it)` — `vet_workspace`'s answer and what it was asked."""
    text = (raw or "").strip()
    if not text:
        return None, None
    from src.workstation_access import workstation_for
    client, account = workstation_for(owner)
    daemon = await client.health()
    named, _said = station_folder(owner, account, text, daemon)
    if not named:
        return None, None
    try:
        path = str((await client.list(account, named, max_entries=0))["path"])
    except WorkstationError as e:
        if e.code in _STATION_FAILURES:
            raise
        return None, named
    home = await _home_path(client, account)
    mine = any(within(path, folder) for folder in own_reach(home, daemon, account))
    if not mine or _sensitive(path):
        return None, named
    return path, named


async def workspace_named(owner: Optional[str], raw: Optional[str]) -> Optional[str]:
    """`B986`: the workspace a path named in a chat message means, in the
    person's workstation — the folder itself, or the folder of a file there —
    held to `vet_workspace`'s rules (a folder in the home, not a sensitive one),
    or None. Raises `WorkstationError` when the workstation itself cannot
    answer, as `vet_workspace` does.

    The message is the person's own words, and what it can bind is a folder of
    their own home: the same reach as the picker, which they may use."""
    folder = await vet_workspace(owner, raw)
    if folder or not (raw or "").strip():
        return folder
    from src.workstation_access import workstation_for
    client, account = workstation_for(owner)
    try:
        # A file: the daemon resolves it (`~`, symlinks, the jail) without
        # reading a byte, and its folder is what is bound.
        path = str((await client.read(account, raw.strip(), max_bytes=0))["path"])
    except WorkstationError as e:
        if e.code in _STATION_FAILURES:
            raise
        return None
    return await vet_workspace(owner, posixpath.dirname(path))


async def describe_workspace(owner: Optional[str], workspace: Optional[str]) -> Dict:
    """`get_workspace`'s answer when the person's tools run in the workstation:
    the same question, answered about the machine the tools work on."""
    said = None
    if workspace:
        # `B1642`: a hire's projects folder, as the workstation names it.
        try:
            from src.workstation_access import workstation_for
            client, account = workstation_for(owner)
            workspace, said = station_folder(owner, account, workspace, await client.health())
        except WorkstationError as e:
            return e.as_result()
    if workspace:
        return {"output": f"{workspace}\n(In your workstation. The shell and file tools start in "
                          "this folder and read relative paths from it; it is where they start, "
                          "not a boundary.)", "exit_code": 0}
    projects = None
    try:
        from src.workstation_access import workstation_for
        client, account = workstation_for(owner)
        where = f"your workstation home ({await _home_path(client, account)})"
        # `B1424`. Where a new project goes: this person's own folder, which
        # Pantheon sees too. `ensure` makes it and names it.
        projects = (await client.ensure(account)).get("projects")
    except WorkstationError:
        where = "your workstation home"
    out = (f"No workspace is set. The shell and file tools run in your workstation and "
           f"start in {where}; relative paths are relative to it.")
    if projects:
        out += (f" New projects go in your projects folder, {projects} (also "
                f"${P.PROJECTS_ENV} in every command) — make a folder of their own there, "
                "for example {}/my-project. It is yours alone, and Pantheon sees it."
                .format(projects))
    answer = {"output": out, "exit_code": 0}
    if projects:
        answer["projects_root"] = projects
    return sp.add_note(answer, said)


__all__ = ["WORKSTATION_TOOLS", "describe_workspace", "lifted_tools", "routes",
           "run_in_workstation", "vet_workspace",
           "LIFTED_TOOLS", "WORKSPACE_TOOL", "network_refusal_note",  # `B985`, `B977`
           "NETWORK_SEND_NOTE", "NETWORK_SEND_INTERNET_NOTE",  # `B1011`, added
           "NETWORK_SILENT_NOTE", "silent_refusal_note", "refusals_from",  # `B1021`, added
           "workspace_named",  # `B986`
           "projects_folder", "station_folder", "no_projects_sentence",  # `B1642`, `B1643`
           "workspace_in_workstation", "sealed_workspace_holds",  # `B1642`
           "own_reach", "run_env"]  # `B1647`, `B1646`
