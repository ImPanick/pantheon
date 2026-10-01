# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import os
import secrets
import shlex
import signal
import sys
import tempfile
import time
import collections
from typing import Any, Optional, Callable, Awaitable, List, Tuple, Dict
from core.platform_compat import IS_WINDOWS, find_bash, kill_process_tree
from src.constants import MAX_OUTPUT_CHARS

DEFAULT_BASH_TIMEOUT = 60 * 60     # 1 hour
DEFAULT_PYTHON_TIMEOUT = 60 * 60

PROGRESS_INTERVAL_S = 2.0
PROGRESS_TAIL_LINES = 12


def split_streams(stdout: str, stderr: str, *, limit: int = MAX_OUTPUT_CHARS) -> Dict[str, str]:
    """`P4-19`. One result carrying stdout and stderr, neither able to bury the other.

    The two streams were joined into a single blob and then truncated as one,
    which meant **a failing command with chatty output lost its error message
    entirely** — measured: 12,000 characters of stdout and the `ValueError` on
    the end is gone at a 10,000-character cap, from the card and from the
    model's context alike. The row's summary ("the user only sees stderr when
    stdout is empty") is that, with the mechanism found.

    So stderr gets a reserved share of the budget rather than the leftovers. A
    quarter, because an error message is short and decisive where stdout is
    long and often noise: the reserve is only spent when there is an error to
    spend it on, and stdout keeps the whole budget whenever stderr is empty.
    The merged `output` therefore still fits the same cap it always did — this
    reallocates the budget rather than widening it.

    `output` stays exactly the shape every reader already expects, including
    the `STDERR:` marker the model has been trained on in this prompt; `stdout`
    and `stderr` are added beside it so a card can show them apart (`Law 1`).
    """
    from src.tool_execution import _truncate

    err = (stderr or "").rstrip()
    out = (stdout or "").rstrip()
    reserve = max(0, limit // 4)
    err_budget = min(len(err), reserve) if err else 0
    err_text = _truncate(err, reserve) if err else ""
    out_text = _truncate(out, max(0, limit - err_budget))
    merged = (out_text + "\nSTDERR: " + err_text).strip() if err_text else out_text
    return {
        "output": merged or "(no output)",
        "stdout": out_text,
        "stderr": err_text,
    }


async def _create_bash_subprocess(command: str, **kwargs):
    """Start the agent shell with Bash semantics on every supported OS.

    ``asyncio.create_subprocess_shell`` delegates to ``cmd.exe`` on native
    Windows.  That contradicts the Bash tool contract and makes POSIX commands
    such as ``pwd``, ``ls -la``, and ``cat`` unreliable even when the launcher
    has found Git Bash.  Pass the selected workspace as a structural ``cwd``
    argument; Git Bash inherits that native Windows directory and exposes it
    using its normal ``/c/...`` representation.
    """
    if IS_WINDOWS:
        bash = find_bash()
        if not bash:
            raise RuntimeError(
                "Git Bash is required for the Bash tool on Windows; "
                "install Git for Windows and restart Pantheon"
            )
        return await asyncio.create_subprocess_exec(bash, "-c", command, **kwargs)
    # `B961`. This was `create_subprocess_shell` unconditionally: `/bin/sh -c`,
    # which is dash on the Debian image (measured by `P20-03`: `[[ 1 == 1 ]]`
    # exits 127, `echo {a,b}` prints `{a,b}`) under a tool named and described
    # as bash. Now bash wherever there is one, as Windows already did; `sh` only
    # where there is none, and `BashTool` says so in the result (`NO_BASH_NOTE`).
    bash = find_bash()
    if bash:
        return await asyncio.create_subprocess_exec(bash, "-c", command, **kwargs)
    return await asyncio.create_subprocess_shell(command, **kwargs)


NO_BASH_NOTE = ("bash is not installed where Pantheon runs, so this command ran in sh: "
                "bash-only syntax such as [[ ]], {a,b} and arrays is not available there.")


# ── `B964`: a command and everything it started stop together ───────────────

def own_process_group() -> Dict[str, Any]:
    """Keyword arguments that start a command as the leader of its own process
    group (POSIX), so a timeout or a cancel can stop what it started as well —
    the workstation daemon's rule (`agentd._kill_group`). On Windows the tree
    is found by parent instead (`taskkill /T`), so nothing is needed here."""
    return {} if IS_WINDOWS else {"start_new_session": True}


def kill_tree(proc) -> None:
    """Stop a command and its children: the process group on POSIX, the
    process tree on Windows (`core.platform_compat.kill_process_tree`).

    `B964`: this was `proc.kill()`, which stopped the shell and left the rest —
    measured by `P20-03`, `echo before; sleep 30` under a 1 s timeout left
    `sleep` alive holding the pipes. A process started without its own group
    has no group of its own number, so `killpg` answers `ProcessLookupError`
    rather than reaching Pantheon's group; the plain kill then still happens."""
    if IS_WINDOWS:
        kill_process_tree(getattr(proc, "pid", None))
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass


# ── `B962`: each chat's shell keeps its folder, and nothing else ─────────────
#
# The owner's call (`D-2026-10-01-01`): *keep the working folder per chat, on
# both machines; environment resets.* So every call is still a fresh shell —
# variables, functions, options and background jobs end with it, as they always
# have — started in the folder the chat's last shell ended in.
#
# That replaces the tmux shell this module carried (`P0-31`'s adoption logic
# with it). It was never reached from an agent turn: `_call_mcp_tool` called
# `_direct_fallback` without a session, in the fork's first commit as in
# `a633efc` (`B962`, measured by `P20-03`: `cd /` then `pwd` printed the
# workspace), so no chat ever had one and none can be orphaned by its removal.
# It also kept what the owner chose to reset — the environment — and there is
# no tmux in the workstation, so keeping it would have been a second way to do
# one thing (`Law 14`) held dead by a switch (`Law 13`).

class _ChatFolders:
    """Where each chat's shell is between calls: `key -> (start, folder)`.

    `start` is the folder the chat's calls start in when nothing is held — the
    workspace, or the default folder — so picking another workspace moves the
    shell there rather than leaving it somewhere the person no longer meant.
    A shell that ends in its start folder holds nothing. Capped, because a
    long-lived process should not grow a map keyed by every chat it served,
    and in memory: a restart of Pantheon starts each chat's shell in its start
    folder again."""

    def __init__(self, cap: int = 512):
        self._cap = cap
        self._held: "collections.OrderedDict[Tuple, Tuple[str, str]]" = collections.OrderedDict()

    def recall(self, key: Optional[Tuple], start: str) -> Tuple[Optional[str], Optional[str]]:
        """`(folder, sentence)`: the folder held for this chat, or None — with
        a sentence when one was held under a different start folder."""
        if key is None or key not in self._held:
            return None, None
        held_start, folder = self._held[key]
        if held_start != start:
            del self._held[key]
            return None, (f"The workspace changed, so this chat's shell starts in {start} "
                          f"(it was in {folder}).")
        self._held.move_to_end(key)
        return folder, None

    def keep(self, key: Optional[Tuple], start: str, folder: Optional[str]) -> None:
        if key is None:
            return
        if not folder or folder == start:
            self._held.pop(key, None)
            return
        self._held[key] = (start, folder)
        self._held.move_to_end(key)
        while len(self._held) > self._cap:
            self._held.popitem(last=False)

    def forget(self, key: Optional[Tuple]) -> None:
        if key is not None:
            self._held.pop(key, None)

    def clear(self) -> None:
        self._held.clear()


CHAT_FOLDERS = _ChatFolders()


def chat_key(machine: str, who: Optional[str], session_id: Optional[str]) -> Optional[Tuple]:
    """The chat a call belongs to, on one machine; None for a call outside a
    chat, whose shell then always starts in the start folder, as before."""
    if not session_id:
        return None
    return (machine, str(who or ""), str(session_id))


def gone_sentence(folder: str, start: str) -> str:
    return (f"This chat's shell was in {folder}, which is no longer there, "
            f"so this command started in {start}.")


def add_note(result: Dict, *sentences: Optional[str]) -> Dict:
    """Append sentences to a result's `note`, the one field the model reads
    about where and how a command ran (`P20-03` uses it for truncation)."""
    said = [s for s in ([result.get("note")] + list(sentences)) if s]
    if said:
        result["note"] = " ".join(said)
    return result


class _CwdReport:
    """How a fresh shell tells Pantheon the folder it ended in.

    An `EXIT` trap, set on the same line as the command so the line numbers in
    the person's own error messages do not move, writes a per-call nonce and
    `pwd -P` to a file Pantheon reads afterwards. It runs on `exit N`, on a
    `set -e` failure and at the end, and keeps the command's exit status
    (measured in bash and dash). It writes nothing when the command replaces
    the shell (`exec`) or sets its own `EXIT` trap; the folder is then unknown
    and the chat keeps the one it had. `{ set +x; }` keeps an `xtrace` the
    command switched on from printing the trap. Where bash quotes a line back
    in a syntax error, the prefix is removed from the output (`scrub`) — it is
    one line and carries the nonce, so nothing else can match it."""

    VAR = "__pantheon_cwd_report"

    def __init__(self, target_expr: str, *, windows: bool = False):
        self.nonce = secrets.token_hex(8)
        # Git Bash's `pwd -W` is the folder as Windows names it (`C:/…`); not
        # measured here (no Windows in this sandbox) — a shell that cannot run
        # it writes nothing, and the chat keeps its folder as before.
        pwd = "command pwd -W" if windows else "command pwd -P"
        body = ('{ set +x; } 2>/dev/null; { command printf "%s\\n" ' + self.nonce + "; "
                + pwd + '; } 2>/dev/null >| "$' + self.VAR + '" || :')
        self.prefix = f"{self.VAR}={target_expr}; trap {shlex.quote(body)} EXIT; "

    def wrap(self, command: str) -> str:
        return self.prefix + command

    def scrub(self, text: str) -> str:
        return text.replace(self.prefix, "") if text else text

    def parse(self, data: bytes) -> Optional[str]:
        head, sep, rest = bytes(data or b"").partition(b"\n")
        if not sep or head != self.nonce.encode("ascii"):
            return None
        if rest.endswith(b"\n"):
            rest = rest[:-1]
        return os.fsdecode(rest) or None


class _HostReport(_CwdReport):
    """The report file on Pantheon's own machine: a private temporary file,
    removed after the call."""

    def __init__(self):
        fd, self.path = tempfile.mkstemp(prefix="pantheon-shell-cwd-")
        os.close(fd)
        shown = self.path.replace("\\", "/") if IS_WINDOWS else self.path
        super().__init__(shlex.quote(shown), windows=IS_WINDOWS)

    def read(self) -> Optional[str]:
        try:
            with open(self.path, "rb") as f:
                return self.parse(f.read(65536))
        except OSError:
            return None

    def discard(self) -> None:
        try:
            os.unlink(self.path)
        except OSError:
            pass


def _host_refusal(folder: str) -> Optional[str]:
    """Why the shell may not start in `folder` on this machine, or None.

    `B962`: the shell itself is not sandboxed (`THREAT_MODEL.md` Known Gap 1),
    but the folder a chat's next command starts in is held to the rule the file
    tools follow here — `_resolve_tool_path`: inside the workspace when one is
    bound, inside the allowed roots when not, never a sensitive folder — so a
    `cd ~/.ssh` (or a prompt injection's `cd /`) does not become where every
    later command starts."""
    from src.tool_execution import _is_sensitive_path, _resolve_tool_path, get_active_workspace
    if not os.path.isdir(folder):
        return "gone"
    if _is_sensitive_path(folder):
        return "a sensitive folder (such as .ssh) the file tools refuse"
    try:
        _resolve_tool_path(folder)
    except ValueError:
        ws = get_active_workspace()
        return (f"outside the workspace ({ws})" if ws
                else "outside the folders Pantheon's file tools may use")
    return None


def host_start_folder(key: Optional[Tuple], start: str) -> Tuple[str, List[str]]:
    """The folder this chat's next host command starts in, and what to say."""
    folder, said = CHAT_FOLDERS.recall(key, start)
    notes = [said] if said else []
    if folder:
        why = _host_refusal(folder)
        if why:
            CHAT_FOLDERS.forget(key)
            notes.append(gone_sentence(folder, start) if why == "gone" else
                         f"This chat's shell was in {folder}, {why}, so this command started "
                         f"in {start}.")
            folder = None
    return folder or start, notes


def host_end_folder(key: Optional[Tuple], start: str, ran_in: str,
                    ended_in: Optional[str], notes: List[str]) -> str:
    """Record where the chat's shell ended; answer where its next call starts."""
    if ended_in is None:
        # Unknown (the command replaced the shell, or set its own EXIT trap):
        # the chat keeps the folder this call started in.
        return ran_in
    real = os.path.realpath(ended_in)
    if real == os.path.realpath(start):
        CHAT_FOLDERS.forget(key)
        return start
    why = _host_refusal(real)
    if why is None:
        CHAT_FOLDERS.keep(key, start, real)
        return real
    CHAT_FOLDERS.forget(key)
    if why != "gone":
        notes.append(f"The shell ended in {real}, {why}, so the next command starts in {start}.")
    return start


def _tail_line(decoded: str, label: str) -> str:
    """One line of a running command's live tail: stderr lines marked `! `."""
    return f"! {decoded}" if label == "err" else decoded


async def _progress_emitter(progress_cb: Callable[[Dict], Awaitable[None]], started: float,
                         tail: "collections.deque") -> None:
    """The `tool_progress` beat of a running command: after `PROGRESS_INTERVAL_S`
    and every interval after, the elapsed time and the last lines of output.
    Shared by the command running here and the one running in the workstation
    (`P20-03`), so a card cannot tell the two apart while it waits."""
    await asyncio.sleep(PROGRESS_INTERVAL_S)
    while True:
        try:
            await progress_cb({
                "elapsed_s": round(time.time() - started, 1),
                "tail": "\n".join(list(tail)),
            })
        except Exception:
            pass
        await asyncio.sleep(PROGRESS_INTERVAL_S)


def _shell_result(tool: str, stdout: str, stderr: str, rc: Optional[int], timed_out: bool,
                  timeout: float) -> Dict:
    """What `bash` and `python` answer once the command is over."""
    if timed_out:
        # `P4-19`: `output` too. This branch returned the two streams and no
        # merged view, so a killed command drew a card with nothing in it —
        # the one case where what it managed to print matters most.
        return {"error": f"{tool}: timed out after {timeout}s — process killed",
                "exit_code": 124, **split_streams(stdout, stderr)}
    return {**split_streams(stdout, stderr), "exit_code": rc or 0}


def _bash_command(content) -> str:
    """The command text of a `bash` call, which may arrive as its argument object."""
    if isinstance(content, dict):
        content = str(content.get("command") or content.get("cmd") or content.get("code") or "")
    return content


async def _run_subprocess_streaming(
    proc: asyncio.subprocess.Process,
    *,
    timeout: float,
    progress_cb: Optional[Callable[[Dict], Awaitable[None]]] = None,
    scrub: Optional[Callable[[str], str]] = None,
) -> Tuple[str, str, Optional[int], bool]:
    """Wait for a command, streaming its last lines to `progress_cb`.

    `B964`: on a timeout and on a cancel, `kill_tree` stops the command and
    everything it started (it was started by `own_process_group`), so nothing
    of it outlives the call or holds the pipes the readers are waiting on.
    `scrub` is applied to each line before it is kept (`_CwdReport.scrub`)."""
    started = time.time()
    stdout_full: list[str] = []
    stderr_full: list[str] = []
    tail = collections.deque(maxlen=PROGRESS_TAIL_LINES)

    async def _reader(stream, full_buf, label: str):
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip("\n")
            if scrub is not None:
                decoded = scrub(decoded)
            full_buf.append(decoded)
            tail.append(_tail_line(decoded, label))

    rd_out = asyncio.create_task(_reader(proc.stdout, stdout_full, "out"))
    rd_err = asyncio.create_task(_reader(proc.stderr, stderr_full, "err"))
    prog_task = asyncio.create_task(_progress_emitter(progress_cb, started, tail)) if progress_cb else None

    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        try:
            kill_tree(proc)
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except Exception:
            pass
    except asyncio.CancelledError:
        try:
            kill_tree(proc)
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except Exception:
            pass
        for t in (rd_out, rd_err):
            t.cancel()
        if prog_task is not None:
            prog_task.cancel()
        raise
    finally:
        if prog_task is not None and not prog_task.done():
            prog_task.cancel()
            try:
                await prog_task
            except (asyncio.CancelledError, Exception):
                pass
        for t in (rd_out, rd_err):
            try:
                await asyncio.wait_for(t, timeout=1)
            except Exception:
                pass

    return (
        "\n".join(stdout_full),
        "\n".join(stderr_full),
        proc.returncode,
        timed_out,
    )

class BashTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import agent_cwd
        content = _bash_command(content)
        progress_cb = ctx.get("progress_cb")
        _subproc_env = ctx.get("subproc_env")
        # `B962`. The chat this call belongs to keeps its shell's folder; a call
        # outside a chat starts where every call started before.
        key = chat_key("host", ctx.get("owner"), ctx.get("session_id"))
        start = agent_cwd()
        cwd, notes = host_start_folder(key, start)
        report = _HostReport() if key else None
        try:
            try:
                proc = await _create_bash_subprocess(
                    report.wrap(content) if report else content,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=_subproc_env,
                    cwd=cwd,
                    **own_process_group(),
                )
            except RuntimeError as e:
                return {"error": f"bash: {e}", "exit_code": 1}
            stdout, stderr, rc, timed_out = await _run_subprocess_streaming(
                proc,
                timeout=DEFAULT_BASH_TIMEOUT,
                progress_cb=progress_cb,
                scrub=report.scrub if report else None,
            )
            result = _shell_result("bash", stdout, stderr, rc, timed_out, DEFAULT_BASH_TIMEOUT)
            if not IS_WINDOWS and not find_bash():
                notes.append(NO_BASH_NOTE)
            if key:
                result["cwd"] = host_end_folder(key, start, cwd, report.read(), notes)
            return add_note(result, *notes)
        finally:
            if report is not None:
                report.discard()

class PythonTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import agent_cwd
        progress_cb = ctx.get("progress_cb")
        _subproc_env = ctx.get("subproc_env")
        # `B962`. Python starts in the folder the chat's shell is in, and does
        # not move it: an `os.chdir` inside a script is the script's business.
        key = chat_key("host", ctx.get("owner"), ctx.get("session_id"))
        cwd, notes = host_start_folder(key, agent_cwd())
        proc = await asyncio.create_subprocess_exec(
            (sys.executable or "python"), "-I", "-c", content,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_subproc_env,
            cwd=cwd,
            **own_process_group(),
        )
        stdout, stderr, rc, timed_out = await _run_subprocess_streaming(
            proc,
            timeout=DEFAULT_PYTHON_TIMEOUT,
            progress_cb=progress_cb,
        )
        result = _shell_result("python", stdout, stderr, rc, timed_out, DEFAULT_PYTHON_TIMEOUT)
        if key:
            result["cwd"] = cwd
        return add_note(result, *notes)
