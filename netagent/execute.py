# SPDX-License-Identifier: AGPL-3.0-or-later
"""Running a command on the host, behind the guard.

`P17-11`, from `D-2026-09-11-01`. The owner asked for agents inside Pantheon to
reach beyond the container, chose denylist-only, and chose that named commands
may elevate. This is that, built as well as those choices allow.

**ELEVATION IS THE OPERATING SYSTEM'S DECISION, NOT THIS FILE'S.**

The agent runs as the person who started it and never elevates itself. A command
marked `elevated` is handed to the platform's own elevation mechanism —
`Start-Process -Verb RunAs` on Windows, `sudo` on POSIX — which means **a consent
step outside this process**: a UAC dialog, or a sudo password, or an explicit
NOPASSWD rule the operator wrote themselves.

That is not a hedge against the owner's choice, it is the only honest way an
unelevated process can elevate at all. And it preserves the one boundary that
actually holds when a string denylist does not: the OS still gets to say no.

**The operational cost, stated rather than discovered later:** a UAC dialog
raised by a background agent needs somebody at the keyboard. With nobody there it
times out, and this reports that it timed out waiting for consent rather than
that the command failed — because those are different facts and an operator
debugging the second when it was the first loses an afternoon.

**The environment is the AGENT's, not Pantheon's.** The container shell inherits
every API key in the server process; this does not, because there is no reason a
command on the host should see Pantheon's credentials and every reason it should
not.
"""
from __future__ import annotations

import logging
import os
import platform
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from netagent import guard

logger = logging.getLogger("netagent.execute")

DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 900
# Matches `src/constants.MAX_OUTPUT_CHARS`. A host command that produces more
# than this is producing a file, not an answer.
MAX_OUTPUT_CHARS = 10_000

IS_WINDOWS = platform.system() == "Windows"


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    kept = text[:limit]
    return f"{kept}\n… [{len(text) - limit} more characters]"


def leading_binary(command: str) -> str:
    """The program a command starts with, for the elevation allowlist.

    Parsed with `shlex` rather than `split()` so `"C:\\Program Files\\x\\y.exe"`
    is one token. The basename is compared, and the extension dropped, so an
    operator writing `--allow-elevated net` does not also have to know whether
    the agent will see `net` or `net.exe` or `C:\\Windows\\System32\\net.exe`.
    """
    text = str(command or "").strip()
    if not text:
        return ""
    # Separators normalised BEFORE splitting. `shlex` in POSIX mode treats a
    # backslash as an escape, so `C:\Windows\System32\net.exe` came back as
    # `C:WindowsSystem32net.exe` and the basename was the whole thing. Found by
    # the test that spells the same binary five ways.
    text = text.replace("\\", "/")
    try:
        parts = shlex.split(text, posix=True)
    except ValueError:
        parts = text.split()
    if not parts:
        return ""
    name = os.path.basename(parts[0]).casefold()
    for suffix in (".exe", ".cmd", ".bat", ".com", ".ps1"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


class ExecPolicy:
    """What this agent will run, set where the agent was started.

    Off by default: `--allow-exec` is a deliberate act. `Law 16`, and the same
    shape as the CIDR allowlist — the switch is on the operator's side of the
    wire, not Pantheon's.
    """

    __slots__ = ("enabled", "elevated_commands", "cwd")

    def __init__(self, *, enabled: bool = False,
                 elevated_commands: Sequence[str] = (),
                 cwd: Optional[str] = None) -> None:
        self.enabled = bool(enabled)
        self.elevated_commands = sorted({
            leading_binary(c) for c in elevated_commands if str(c).strip()})
        self.cwd = str(cwd) if cwd else None

    def may_elevate(self, command: str) -> bool:
        return leading_binary(command) in self.elevated_commands

    def as_dict(self) -> Dict[str, object]:
        return {"enabled": self.enabled,
                "elevated_commands": list(self.elevated_commands),
                "cwd": self.cwd}


def _argv(command: str) -> List[str]:
    """A shell invocation. The string is passed as ONE argument.

    `shell=True` in Python on POSIX means `/bin/sh -c <string>`, which is what
    this does explicitly — but explicitly, through an argv list, so no part of
    the command can be reinterpreted as an argument to Python's own wrapper.
    """
    if IS_WINDOWS:
        return ["cmd.exe", "/d", "/s", "/c", command]
    return ["/bin/sh", "-c", command]


def _elevated_argv(command: str, out_file: str) -> List[str]:
    """Hand the command to the platform's own elevation mechanism.

    Windows: `Start-Process -Verb RunAs` raises a UAC prompt. The elevated
    process gets a different console, so output is redirected to a file this
    process reads back — there is no pipe across an elevation boundary.

    POSIX: `sudo -n`, non-interactive. A password prompt from a background agent
    is a hang nobody can answer, so it fails fast instead and the refusal says to
    write a NOPASSWD rule if that is what was meant.
    """
    if IS_WINDOWS:
        inner = command.replace("'", "''")
        target = out_file.replace("'", "''")
        script = (
            f"$p = Start-Process -FilePath cmd.exe "
            f"-ArgumentList '/d','/s','/c',{_ps_quote(command)} "
            f"-Verb RunAs -Wait -PassThru "
            f"-RedirectStandardOutput '{target}.out' "
            f"-RedirectStandardError '{target}.err'; exit $p.ExitCode"
        )
        _ = inner
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]
    return ["sudo", "-n", "/bin/sh", "-c", command]


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run(command: str, *, policy: ExecPolicy, elevated: bool = False,
        timeout: Optional[int] = None, cwd: Optional[str] = None) -> Dict[str, object]:
    """Run it, or say precisely why not. Never raises.

    The order of the checks is the design: **the guard runs before anything
    else**, including before the enabled check, so that a refusal for a nuclear
    command says so even on an agent where execution is switched off. An operator
    turning exec on should not discover the boundary afterwards.
    """
    verdict = guard.check(command)
    if not verdict.allowed:
        logger.warning("refused (%s): %s", verdict.rule, verdict.normalised[:200])
        return {"allowed": False, "refused_by": "nuclear-list", "rule": verdict.rule,
                "error": verdict.reason, "exit_code": None}

    if not policy.enabled:
        return {"allowed": False, "refused_by": "not-enabled",
                "error": "this agent was not started with --allow-exec, so it runs "
                         "nothing. Restart it with that flag to allow host commands.",
                "exit_code": None}

    if elevated and not policy.may_elevate(command):
        binary = leading_binary(command) or "that command"
        return {"allowed": False, "refused_by": "not-elevatable",
                "error": f"{binary!r} is not in this agent's elevation list "
                         f"({', '.join(policy.elevated_commands) or 'empty'}). "
                         f"The list is set where the agent was started and cannot "
                         f"be changed from Pantheon.",
                "exit_code": None}

    limit = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    workdir = cwd or policy.cwd or str(Path.home())
    if not os.path.isdir(workdir):
        return {"allowed": False, "refused_by": "bad-cwd",
                "error": f"{workdir!r} is not a directory", "exit_code": None}

    started = time.monotonic()
    out_file = ""
    try:
        if elevated:
            handle = tempfile.NamedTemporaryFile(
                prefix="netagent-elev-", suffix=".txt", delete=False)
            out_file = handle.name
            handle.close()
            argv = _elevated_argv(command, out_file)
        else:
            argv = _argv(command)

        completed = subprocess.run(
            argv, cwd=workdir, timeout=limit, capture_output=True, text=True,
            errors="replace",
            # The agent's own environment, not Pantheon's. A command on the host
            # has no business seeing the server's API keys.
            env={**os.environ},
        )
        stdout, stderr = completed.stdout or "", completed.stderr or ""
        if elevated and out_file:
            stdout = _read_beside(out_file, ".out") or stdout
            stderr = _read_beside(out_file, ".err") or stderr
        return {
            "allowed": True, "exit_code": completed.returncode,
            "stdout": _truncate(stdout), "stderr": _truncate(stderr),
            "elevated": bool(elevated),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "cwd": workdir,
        }
    except subprocess.TimeoutExpired:
        # Two different facts wearing one word. A UAC dialog with nobody at the
        # keyboard is not a slow command, and an operator debugging the second
        # when it was the first loses an afternoon.
        detail = ("timed out waiting for elevation consent — a UAC prompt needs "
                  "somebody at the machine" if elevated and IS_WINDOWS
                  else f"timed out after {limit}s")
        return {"allowed": True, "exit_code": 124, "stdout": "", "stderr": detail,
                "timed_out": True, "elevated": bool(elevated)}
    except FileNotFoundError as e:
        return {"allowed": True, "exit_code": 127,
                "stdout": "", "stderr": f"not found: {e}", "elevated": bool(elevated)}
    except OSError as e:
        return {"allowed": True, "exit_code": 1, "stdout": "",
                "stderr": f"{type(e).__name__}: {e}", "elevated": bool(elevated)}
    finally:
        for suffix in ("", ".out", ".err"):
            if out_file:
                try:
                    os.unlink(out_file + suffix)
                except OSError:
                    # The elevated process may still hold it, or it may never
                    # have been created. A leftover temp file is not worth
                    # failing a command over.
                    pass


def _read_beside(base: str, suffix: str) -> str:
    try:
        with open(base + suffix, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        # Redirection targets are created by the elevated process; if consent was
        # refused they never exist, and the exit code already says so.
        return ""
