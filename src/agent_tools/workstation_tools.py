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

**WHAT DOES NOT PERSIST, MEASURED.** Today's `bash` in an agent turn keeps
nothing between calls: the tmux-backed persistent shell is reached only with a
`session_id`, and `_call_mcp_tool` calls `_direct_fallback` without one, so every
call is a fresh `bash -c` in the workspace (driven: `cd /` then `pwd` prints the
workspace). The workstation keeps that contract — each call starts in the home —
and reports `cwd`. `#!bg` jobs are refused here with a sentence (see
`_BACKGROUND_REFUSAL`) rather than half-run.

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
import io
import json
import logging
import os
import posixpath
import shlex
import time
from typing import Any, Awaitable, Callable, Dict, FrozenSet, Optional, Tuple

from src.agent_tools import codenav_walk as _codenav
from src.agent_tools import filesystem_tools as fs
from src.agent_tools import subprocess_tools as sp
from src.workstation_client import WorkstationError

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


def lifted_tools(owner: Optional[str]) -> FrozenSet[str]:
    """The part of the non-admin blocklist that does not apply to this person.

    `P20-03`: `bash`, `python` and the file tools are refused to a non-admin
    because on this machine they reach the process holding every secret
    (`tool_security.NON_ADMIN_BLOCKED_REASONS`). Routed to the workstation they
    reach the person's own workstation home instead, which is what
    `can_use_workstation` grants — so those nine, and nothing else, are lifted
    for someone `routes_tools` says yes to. `manage_bg_jobs` and `get_workspace`
    stay refused: both still act on this machine."""
    return WORKSTATION_TOOLS if _routes_tools(owner) else frozenset()


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
                 progress_cb: Optional[Callable[[Dict], Awaitable[None]]] = None):
        self.client = client
        self.account = account
        self.loop = loop
        self.progress_cb = progress_cb
        self.failure: Optional[WorkstationError] = None
        self._home: Optional[str] = None

    async def home(self) -> str:
        if self._home is None:
            self._home = str((await self.client.ensure(self.account))["home"])
        return self._home

    async def shown(self, raw_path: str) -> str:
        """A path as the host's messages show one — absolute — for a path the
        daemon could not resolve because nothing is there."""
        return _absolute(await self.home(), raw_path)

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

def _absolute(home: str, raw: str) -> str:
    """`raw` as an absolute path in the workstation: `~` and relative paths are
    the home's, as the daemon reads them. Normalised, not resolved — the daemon
    resolves (and jails) every path it is handed."""
    text = str(raw).strip()
    if text == "~" or text.startswith("~/"):
        text = home + text[1:]
    elif not text.startswith("/"):
        text = posixpath.join(home, text)
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

async def _shell(st: _Station, tool: str, shell: str, command: str, timeout: float) -> Dict:
    if not str(command or "").strip():
        # An empty script does nothing and exits 0 — what `bash -c ""` and
        # `python -c ""` answer here. The daemon refuses an empty command, so
        # the answer is given without asking it.
        return sp._shell_result(tool, "", "", 0, False, timeout)
    started = time.time()
    tail: "collections.deque" = collections.deque(maxlen=sp.PROGRESS_TAIL_LINES)
    partial = {"stdout": "", "stderr": ""}

    def on_output(kind: str, text: str) -> None:
        # Whole lines only, as the host's `readline` reader sees them.
        kind = "stderr" if kind == "stderr" else "stdout"
        *complete, partial[kind] = (partial[kind] + text).split("\n")
        for line in complete:
            tail.append(sp._tail_line(line, "err" if kind == "stderr" else "out"))

    emitter = (asyncio.create_task(sp._progress_emitter(st.progress_cb, started, tail))
               if st.progress_cb else None)
    try:
        r = await st.client.exec(st.account, command, shell=shell, timeout_s=timeout,
                                 env=dict(_SHELL_ENV),
                                 on_output=on_output if st.progress_cb else None)
    finally:
        if emitter is not None:
            emitter.cancel()
            try:
                await emitter
            except (asyncio.CancelledError, Exception):
                pass
    stdout = str(r.get("stdout") or "")
    stderr = str(r.get("stderr") or "")
    result = sp._shell_result(tool, stdout, stderr, r.get("exit_code"),
                              bool(r.get("timed_out")), timeout)
    if r.get("cwd"):
        result["cwd"] = r["cwd"]
    if r.get("truncated"):
        # The daemon keeps the END of each stream past `MAX_OUTPUT_BYTES`
        # (the end is where the error is); the host keeps it all and cuts the
        # start. Said, so a reader of the output knows its head is missing.
        from workstation.protocol import MAX_OUTPUT_BYTES
        result["note"] = (f"The workstation keeps the last {MAX_OUTPUT_BYTES:,} bytes of each "
                          "stream; the start of this output was dropped there.")
    return result


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
        path = (await _stat_file(st, raw_path))["path"]
    except WorkstationError as e:
        if e.code == "not_found":
            shown = await st.shown(raw_path)
            if await _is_dir(st, raw_path):
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
    raw_path, body = fs._write_file_args(content)
    refused = _path_refusal("write_file", raw_path)
    if refused:
        return refused
    old = ""
    try:
        existing = (await _stat_file(st, raw_path))["path"]
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
        written = await st.client.write(st.account, existing or raw_path, body)
    except WorkstationError as e:
        if e.code == "bad_request" and await _is_dir(st, raw_path):
            # The answer `open(path, "w")` gives here, word for word.
            shown = await st.shown(raw_path)
            why = IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), shown)
            return {"error": f"write_file: {shown}: {why}", "exit_code": 1}
        return _file_answer("write_file", e)
    return fs._write_result(written["path"], old, body)


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
        path = (await _stat_file(st, raw_path))["path"]
    except WorkstationError as e:
        if e.code == "not_found":
            shown = await st.shown(raw_path)
            if await _is_dir(st, raw_path):
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
        path = _absolute(self.home, raw)
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
        root = (await st.client.list(st.account, raw or None, max_entries=0))["path"]
    except WorkstationError as e:
        if e.code != "not_found":
            return None, _file_answer(tool, e)
        if not file_ok:
            return None, {"error": f"{tool}: {await st.shown(raw)}: not a directory", "exit_code": 1}
        try:
            root = (await _stat_file(st, raw))["path"]
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
                             ) -> Tuple[str, Dict]:
    """Run one of `WORKSTATION_TOOLS` in the person's workstation: `(desc, result)`."""
    from src.tool_execution import _split_bg_marker
    from src.workstation_access import account_of as account_for, sync_config, workstation_for

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
        await sync_config(client)
    except WorkstationError as e:
        return desc, _where(e.as_result(), account_for(owner))
    st = _Station(client, account, asyncio.get_running_loop(), progress_cb)
    try:
        result = await _HANDLERS[tool](content, st)
    except WorkstationError as e:
        result = e.as_result()
    except Exception as e:  # noqa: BLE001 — the same catch `_direct_fallback` gives the host tools
        logger.warning("workstation %s failed: %s", tool, type(e).__name__)
        result = {"error": f"{tool}: {e}", "exit_code": 1}
    if tool == "edit_file":
        desc = result.get("output") or result.get("error") or "edit_file"
    return desc, _where(result, account)


__all__ = ["WORKSTATION_TOOLS", "lifted_tools", "routes", "run_in_workstation"]
