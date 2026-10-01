# SPDX-License-Identifier: AGPL-3.0-or-later
"""The daemon inside a workstation — `P20-01`, `D-2026-09-30-03`.

It answers `workstation/protocol.py` and nothing else. Standard library only,
nothing imported from Pantheon (`netagent`'s rule, and a test enforces it for
this package too): the same file runs in the container image, in a VM, or on
any machine an admin points Pantheon at.

**WHAT IT IS FOR, AND WHAT IT IS NOT.** It runs what it is given, as the
account it is given, in that account's home and on that account's display. It
does not judge commands — an agent that may use a shell may use a shell, and a
filter here would be a list of the attacks somebody thought of. Its job is the
boundary around the command: the token, the account name, the home jail, the
byte bounds, the timeout, and who holds the mouse.

**TWO LAYERS.** The HTTP layer here (routes, token, bounds, jail, exec,
files, control) is the same for every backend. What differs — how an account
is made, how a command runs *as* it, where its screen is — is a `System`:

  * `SingleUserSystem` (here): every account is a directory under one root and
    every command runs as the daemon's own user. What a remote machine runs
    when its operator does not want accounts made on it, and what the tests
    drive, so the tests exercise this file and not a copy of it.
  * `UbuntuSystem` (`workstation/ubuntu.py`, `P20-01`): a Unix account per
    person, an X display per person, `sudo` as a switch.

**EVERY FILE OPERATION HAPPENS INSIDE `System.acting_as`** (`P20-01`). On a
backend whose daemon is root, that is the account's own filesystem identity:
`resolve` checks a path once, and a root daemon that then opens it can be led
out of the home by a directory swapped for a symlink in between. Acting as the
account, the kernel checks every open as the account, so a race wins nothing.

A screen is its own small interface (`grab`, `send`) so a system without one
answers `unavailable` with a sentence rather than a stack trace.
"""
from __future__ import annotations

import base64
import collections
import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import select
import shutil
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from workstation import protocol as P

logger = logging.getLogger("pantheon.workstation")

VERSION = "1.0.0"
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
# xdotool key syntax: names joined by `+`, several combos separated by spaces.
_KEYS_RE = re.compile(r"^[A-Za-z0-9_+\-]{1,64}( [A-Za-z0-9_+\-]{1,64}){0,15}$")
_ROUTE_RE = re.compile(r"^/v1/users/(?P<account>[^/]+)/(?P<rest>[a-z/]+)$")
_ACCOUNT_PATH_RE = re.compile(r"^/v1/users/(?P<account>[^/]+)$")  # `B959`


class WorkstationError(Exception):
    """An answer the caller should read: a protocol error code and a sentence."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code if code in P.ERRORS else "internal"
        self.message = message


# ── tokens ────────────────────────────────────────────────────────────────────

def mint_token() -> str:
    return P.TOKEN_PREFIX + secrets.token_urlsafe(P.TOKEN_ENTROPY_BYTES)


def load_or_create_token(pairing_dir: Optional[Path]) -> str:
    """The token this daemon checks: the environment's if set, else the one in
    the pairing volume, else a new one written there for Pantheon to read.

    The raw value is in the file, not a hash, and that is the design rather
    than a lapse: zero-config pairing means Pantheon reads it from a volume
    that only the two services mount. A remote daemon has no such volume, so
    its operator sets `PANTHEON_WORKSTATION_TOKEN` on both sides.
    """
    env = (os.environ.get(P.TOKEN_ENV) or "").strip()
    if env:
        return env
    if pairing_dir is None:
        raise WorkstationError("unavailable", "No token: set PANTHEON_WORKSTATION_TOKEN "
                                              "or give the daemon a pairing directory.")
    path = Path(pairing_dir) / P.TOKEN_FILENAME
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if existing:
        return existing
    Path(pairing_dir).mkdir(parents=True, exist_ok=True)
    token = mint_token()
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    os.replace(tmp, path)
    return token


def bearer(header: str) -> str:
    scheme, _, value = (header or "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


# ── screens ───────────────────────────────────────────────────────────────────

class Screen:
    """A display: `grab` a picture of it, `send` it one validated action."""

    width = P.SCREEN_WIDTH
    height = P.SCREEN_HEIGHT

    def grab(self, fmt: str) -> Tuple[bytes, str]:  # pragma: no cover - interface
        raise NotImplementedError

    def send(self, action: Dict) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class NoScreen(Screen):
    """What a system without a display answers. Said, never faked."""

    def __init__(self, why: str):
        self.why = why

    def grab(self, fmt: str) -> Tuple[bytes, str]:
        raise WorkstationError("unavailable", self.why)

    def send(self, action: Dict) -> None:
        raise WorkstationError("unavailable", self.why)


# ── systems ───────────────────────────────────────────────────────────────────

class System:
    """How accounts, commands and screens work on one backend."""

    backend = "remote"
    network = "full"

    def __init__(self) -> None:
        self.sudo = False

    def ensure(self, account: str) -> Dict:  # pragma: no cover - interface
        raise NotImplementedError

    def reset(self, account: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def home(self, account: str) -> Path:  # pragma: no cover - interface
        raise NotImplementedError

    def accounts(self) -> List[str]:  # pragma: no cover - interface
        raise NotImplementedError

    def run_as(self, account: str) -> Tuple[List[str], Dict[str, str]]:
        """`(argv prefix, base environment)` for a command run as `account`."""
        raise NotImplementedError  # pragma: no cover - interface

    def own(self, account: str, paths: Iterable[Path]) -> None:
        """Give paths the daemon created to the account (a no-op for one user)."""

    def acting_as(self, account: str):
        """A context in which the daemon's file operations are the account's
        (module docstring). One user: the daemon already is it."""
        return contextlib.nullcontext()

    def wake(self, account: str) -> Optional[str]:
        """Bring up what the account's session has beyond its home — its
        display — and name it. Called by `ensure`, not by every command, so a
        person who only uses the shell does not pay for a desktop. A failure
        here is reported by the screen when it is used, never by `ensure`: a
        broken display must not take the shell down with it."""
        return None

    def set_sudo(self, on: bool) -> None:
        self.sudo = bool(on)

    def screen(self, account: str) -> Screen:
        return NoScreen("This workstation has no display.")

    def has_home(self, account: str) -> bool:
        """Whether the account's home is there — looked at, never made
        (`B959`). Every system keeps homes at `home(account)`, so one answer
        serves them all; a home that is a symlink is not counted, because
        `ensure` would not have made one (`reset` replaces it)."""
        home = self.home(account)
        return home.is_dir() and not home.is_symlink()


class SingleUserSystem(System):
    """Every account is a directory under `root`; every command runs as the
    daemon's own user with `HOME` set to it. No accounts are made on the
    machine, so there is no `sudo` to grant — the switch only lifts the jail."""

    backend = "remote"

    def __init__(self, root: Path, *, screen_factory: Optional[Callable[[str], Screen]] = None,
                 skeleton: Optional[Path] = None, backend: str = "remote",
                 network: str = "full") -> None:
        super().__init__()
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.skeleton = Path(skeleton) if skeleton else None
        self._screen_factory = screen_factory
        self._screens: Dict[str, Screen] = {}
        self.backend = backend if backend in P.BACKENDS else "remote"
        self.network = network if network in P.NETWORK_MODES else "full"

    def home(self, account: str) -> Path:
        return self.root / account

    def accounts(self) -> List[str]:
        return sorted(p.name for p in self.root.iterdir() if P.ACCOUNT_RE.match(p.name))

    def ensure(self, account: str) -> Dict:
        home = self.home(account)
        created = not home.exists()
        if created:
            if self.skeleton and self.skeleton.is_dir():
                shutil.copytree(self.skeleton, home, symlinks=True)
            else:
                home.mkdir(parents=True)
        return {"home": str(home), "display": None, "created": created}

    def reset(self, account: str) -> None:
        home = self.home(account)
        if home.exists():
            shutil.rmtree(home)
        self._screens.pop(account, None)
        self.ensure(account)

    def run_as(self, account: str) -> Tuple[List[str], Dict[str, str]]:
        home = str(self.home(account))
        env = {
            "HOME": home,
            "USER": account,
            "LOGNAME": account,
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "TERM": "xterm-256color",
        }
        return [], env

    def screen(self, account: str) -> Screen:
        if self._screen_factory is None:
            return NoScreen("This workstation has no display: it runs commands and files only.")
        if account not in self._screens:
            self._screens[account] = self._screen_factory(account)
        return self._screens[account]


# ── the parts every backend shares ────────────────────────────────────────────

class _Tail:
    """The last `limit` bytes of a stream, and whether anything was dropped."""

    def __init__(self, limit: int):
        self.limit = limit
        self.chunks: collections.deque = collections.deque()
        self.size = 0
        self.truncated = False

    def add(self, data: bytes) -> None:
        self.chunks.append(data)
        self.size += len(data)
        while self.size > self.limit and self.chunks:
            extra = self.size - self.limit
            head = self.chunks[0]
            if len(head) <= extra:
                self.chunks.popleft()
                self.size -= len(head)
            else:
                self.chunks[0] = head[extra:]
                self.size -= extra
            self.truncated = True

    def text(self) -> str:
        return b"".join(self.chunks).decode("utf-8", errors="replace")


class Workstation:
    """The protocol's behaviour, independent of HTTP, so tests can call it and
    the handler stays a thin translation."""

    def __init__(self, system: System, token: str):
        self.system = system
        self.token = token
        self._holders: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    # -- auth and accounts ------------------------------------------------------

    def authorised(self, header: str) -> bool:
        raw = bearer(header)
        return bool(raw) and hmac.compare_digest(raw.encode(), self.token.encode())

    @staticmethod
    def check_account(account: str) -> str:
        if not P.ACCOUNT_RE.match(account or ""):
            raise WorkstationError("bad_request", f"“{account}” is not a workstation account.")
        return account

    def health(self, authorised: bool) -> Dict:
        out = {"ok": True, "agent": P.AGENT_NAME, "protocol": P.PROTOCOL_VERSION,
               "backend": self.system.backend, "version": VERSION}
        if authorised:
            out.update(self.settings())
            out["accounts"] = len(self.system.accounts())
        return out

    def account(self, account: str) -> Dict:
        """`B959`: whether the home exists, without making it. Deliberately
        not `ensure`: nothing is made, started or woken."""
        exists = self.system.has_home(account)
        return {"account": account, "exists": exists,
                "home": str(self.system.home(account)) if exists else None}

    def settings(self) -> Dict:
        return {"sudo": self.system.sudo, "network": self.system.network,
                "screen": [P.SCREEN_WIDTH, P.SCREEN_HEIGHT]}

    def config(self, body: Dict) -> Dict:
        if "sudo" in body:
            if not isinstance(body["sudo"], bool):
                raise WorkstationError("bad_request", "“sudo” is true or false.")
            self.system.set_sudo(body["sudo"])
        return self.settings()

    def holder(self, account: str) -> Dict:
        with self._lock:
            return dict(self._holders.get(account) or {"holder": "agent", "since": None})

    def ensure(self, account: str) -> Dict:
        made = self.system.ensure(account)
        display = self.system.wake(account) or made.get("display")
        return {"account": account, "home": made["home"], "display": display,
                "created": bool(made.get("created")), "sudo": self.system.sudo,
                "screen": [P.SCREEN_WIDTH, P.SCREEN_HEIGHT],
                "holder": self.holder(account)["holder"]}

    def reset(self, account: str) -> Dict:
        self.system.reset(account)
        with self._lock:
            self._holders.pop(account, None)
        return {"account": account, "reset": True}

    def control(self, account: str, body: Dict) -> Dict:
        who = body.get("holder")
        if who not in P.HOLDERS:
            raise WorkstationError("bad_request", "“holder” is “agent” or “person”.")
        with self._lock:
            rec = {"holder": who, "since": time.time()}
            self._holders[account] = rec
            return dict(rec)

    # -- paths ------------------------------------------------------------------

    def resolve(self, account: str, raw: Optional[str], *, default_home: bool = True) -> Path:
        """A request path, resolved, and refused if it leaves the home — unless
        `sudo` is on, when the agent is root-equivalent and a jail is fiction."""
        home = self.system.home(account)
        if raw is None or str(raw).strip() == "":
            if default_home:
                return home
            raise WorkstationError("bad_request", "A path is needed.")
        raw = str(raw)
        if "\x00" in raw:
            raise WorkstationError("bad_request", "A path cannot contain a NUL byte.")
        if raw == "~" or raw.startswith("~/"):
            candidate = home / raw[2:]
        else:
            p = Path(raw)
            candidate = p if p.is_absolute() else home / p
        real = Path(os.path.realpath(candidate))
        if not self.system.sudo:
            home_real = Path(os.path.realpath(home))
            if real != home_real and home_real not in real.parents:
                raise WorkstationError(
                    "outside_home",
                    f"{raw} is outside your workstation home ({home}). Work inside it, or ask an "
                    "admin to turn sudo on for the workstation.")
        return real

    # -- exec -------------------------------------------------------------------

    def _exec_prepare(self, account: str, body: Dict):
        command = body.get("command")
        if not isinstance(command, str) or not command.strip():
            raise WorkstationError("bad_request", "“command” is the text to run.")
        shell = body.get("shell") or "bash"
        if shell not in P.SHELLS:
            raise WorkstationError("bad_request", f"“shell” is one of {', '.join(P.SHELLS)}.")
        try:
            timeout = float(body.get("timeout_s") or P.DEFAULT_EXEC_TIMEOUT_S)
        except (TypeError, ValueError):
            raise WorkstationError("bad_request", "“timeout_s” is a number of seconds.")
        timeout = max(1.0, min(timeout, P.MAX_EXEC_TIMEOUT_S))
        env_in = body.get("env") or {}
        if not isinstance(env_in, dict) or not all(
                isinstance(k, str) and _ENV_KEY_RE.match(k) and isinstance(v, str)
                for k, v in env_in.items()):
            raise WorkstationError("bad_request", "“env” maps variable names to text.")
        stdin = body.get("stdin")
        if stdin is not None and not isinstance(stdin, str):
            raise WorkstationError("bad_request", "“stdin” is text.")
        self.system.ensure(account)
        prefix, env = self.system.run_as(account)
        env = {**env, **env_in}
        with self.system.acting_as(account):
            cwd = self.resolve(account, body.get("cwd"))
            if not cwd.is_dir():
                raise WorkstationError("not_found",
                                       f"{body.get('cwd')} is not a directory in the workstation.")
            # The script goes through a file, not `-c`: one argument is capped
            # at 128 KiB by the kernel, and a heredoc that writes a file is longer.
            scratch = self.system.home(account) / ".cache" / "pantheon-run"
            scratch.mkdir(parents=True, exist_ok=True)
            self.system.own(account, [scratch.parent, scratch])
            suffix = ".py" if shell == "python" else ".sh"
            script = scratch / f"{secrets.token_hex(8)}{suffix}"
            script.write_text(command, encoding="utf-8")
            self.system.own(account, [script])
        interpreter = ["python3", "-u"] if shell == "python" else ["bash"]
        argv = [*prefix, *interpreter, str(script)]
        return argv, env, cwd, timeout, stdin, script

    def exec(self, account: str, body: Dict,
             on_chunk: Optional[Callable[[str, str], None]] = None,
             prepared: Optional[Tuple] = None,
             caller_gone: Optional[Callable[[], bool]] = None) -> Dict:
        argv, env, cwd, timeout, stdin, script = prepared or self._exec_prepare(account, body)
        started = time.monotonic()
        out, err = _Tail(P.MAX_OUTPUT_BYTES), _Tail(P.MAX_OUTPUT_BYTES)
        timed_out = False
        try:
            proc = subprocess.Popen(
                argv, cwd=str(cwd), env=env, start_new_session=True,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            self._discard(account, script)
            raise WorkstationError("unavailable", f"The command could not be started: {e}.")

        # `B965` (found by `P20-03`): a caller that went away (a stopped turn) left
        # its command running — a chatty one blocked on a full pipe until its
        # own timeout, an hour for `bash`. Now a failed write, or the caller's
        # socket closing while the command is quiet, kills the process group.
        gone = threading.Event()

        def pump(stream, tail: _Tail, label: str) -> None:
            for chunk in iter(lambda: stream.read1(65536), b""):
                tail.add(chunk)
                if on_chunk is not None and not gone.is_set():
                    try:
                        on_chunk(label, chunk.decode("utf-8", errors="replace"))
                    except OSError:
                        gone.set()
                        _kill_group(proc)

        readers = [threading.Thread(target=pump, args=(proc.stdout, out, "stdout"), daemon=True),
                   threading.Thread(target=pump, args=(proc.stderr, err, "stderr"), daemon=True)]
        for t in readers:
            t.start()
        if stdin is not None:
            try:
                proc.stdin.write(stdin.encode("utf-8"))
                proc.stdin.close()
            except OSError:
                # The command exited without reading its input (a broken
                # pipe). Its exit code and output are the answer, not this.
                pass
        deadline = started + timeout
        while True:
            try:
                proc.wait(timeout=max(0.0, min(0.5, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    timed_out = True
                    _kill_group(proc)
                    break
                if gone.is_set() or (caller_gone is not None and caller_gone()):
                    gone.set()
                    _kill_group(proc)
                    break
        for t in readers:
            t.join(timeout=5)
        self._discard(account, script)
        code = proc.returncode if proc.returncode is not None else -9
        return {"stdout": out.text(), "stderr": err.text(),
                "exit_code": 124 if timed_out else code, "timed_out": timed_out,
                "truncated": out.truncated or err.truncated,
                "duration_ms": int((time.monotonic() - started) * 1000), "cwd": str(cwd)}

    def _discard(self, account: str, script: Path) -> None:
        with self.system.acting_as(account):
            script.unlink(missing_ok=True)

    # -- files ------------------------------------------------------------------

    def read(self, account: str, body: Dict) -> Dict:
        self.system.ensure(account)
        offset = _int(body.get("offset"), 0, "offset")
        max_bytes = min(_int(body.get("max_bytes"), P.MAX_FILE_BYTES, "max_bytes"), P.MAX_FILE_BYTES)
        with self.system.acting_as(account):
            path = self.resolve(account, body.get("path"), default_home=False)
            if not path.is_file():
                raise WorkstationError("not_found", f"There is no file at {body.get('path')}.")
            size = path.stat().st_size
            with open(path, "rb") as f:
                f.seek(max(0, offset))
                data = f.read(max(0, max_bytes))
        return {"path": str(path), "size": size, "data_b64": base64.b64encode(data).decode(),
                "truncated": max(0, offset) + len(data) < size}

    def write(self, account: str, body: Dict) -> Dict:
        self.system.ensure(account)
        try:
            data = base64.b64decode(str(body.get("data_b64") or ""), validate=True)
        except (ValueError, TypeError):
            raise WorkstationError("bad_request", "“data_b64” is not base64.")
        if len(data) > P.MAX_FILE_BYTES:
            raise WorkstationError("too_large", f"A file is at most {P.MAX_FILE_BYTES:,} bytes.")
        with self.system.acting_as(account):
            return self._write(account, body, data)

    def _write(self, account: str, body: Dict, data: bytes) -> Dict:
        path = self.resolve(account, body.get("path"), default_home=False)
        if path.is_dir():
            raise WorkstationError("bad_request", f"{body.get('path')} is a directory.")
        made: List[Path] = []
        if body.get("make_dirs", True):
            parent = path.parent
            missing = []
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            path.parent.mkdir(parents=True, exist_ok=True)
            made.extend(reversed(missing))
        elif not path.parent.is_dir():
            raise WorkstationError("not_found", f"The folder for {body.get('path')} does not exist.")
        with open(path, "ab" if body.get("append") else "wb") as f:
            f.write(data)
        self.system.own(account, [*made, path])
        return {"path": str(path), "size": path.stat().st_size}

    def list(self, account: str, body: Dict) -> Dict:
        self.system.ensure(account)
        with self.system.acting_as(account):
            return self._list(account, body)

    def _list(self, account: str, body: Dict) -> Dict:
        root = self.resolve(account, body.get("path"))
        if not root.is_dir():
            raise WorkstationError("not_found", f"{body.get('path') or '~'} is not a directory.")
        limit = min(_int(body.get("max_entries"), P.MAX_LIST_ENTRIES, "max_entries"),
                    P.MAX_LIST_ENTRIES)
        entries: List[Dict] = []
        truncated = False
        walker = os.walk(root) if body.get("recursive") else [(str(root), None, None)]
        for dirpath, _dirs, _files in walker:
            names = sorted(os.listdir(dirpath)) if _dirs is None else sorted(_dirs + _files)
            for name in names:
                if len(entries) >= limit:
                    truncated = True
                    break
                full = Path(dirpath) / name
                try:
                    st = full.lstat()
                except OSError:
                    continue
                kind = ("symlink" if os.path.islink(full) else "dir" if full.is_dir()
                        else "file" if full.is_file() else "other")
                entries.append({"path": str(full.relative_to(root)), "type": kind,
                                "size": st.st_size, "mtime": st.st_mtime})
            if truncated:
                break
        return {"path": str(root), "entries": entries, "truncated": truncated}

    # -- the screen -------------------------------------------------------------

    def screenshot(self, account: str, fmt: str = "png") -> Dict:
        if fmt not in P.SCREENSHOT_FORMATS:
            raise WorkstationError("bad_request", f"format is one of {', '.join(P.SCREENSHOT_FORMATS)}.")
        self.system.ensure(account)
        screen = self.system.screen(account)
        data, mime = screen.grab(fmt)
        return {"mime": mime, "data_b64": base64.b64encode(data).decode(),
                "width": screen.width, "height": screen.height,
                "digest": hashlib.sha256(data).hexdigest()[:16]}

    def input(self, account: str, body: Dict) -> Dict:
        action = _validated_action(body)
        who = body.get("holder") or "agent"
        if who not in P.HOLDERS:
            raise WorkstationError("bad_request", "“holder” is “agent” or “person”.")
        if who == "agent" and self.holder(account)["holder"] == "person":
            raise WorkstationError(
                "busy", "A person has taken over this workstation's screen. Wait for them to hand "
                        "it back, or ask them what they need.")
        self.system.ensure(account)
        if action["action"] == "wait":
            time.sleep(action["ms"] / 1000)
        else:
            self.system.screen(account).send(action)
        out: Dict = {"ok": True, "action": action["action"]}
        if body.get("screenshot_after"):
            time.sleep(0.3)
            out["screenshot"] = self.screenshot(account)
        return out


def _int(value, default: int, name: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkstationError("bad_request", f"“{name}” is a whole number.")
    return value


def _validated_action(body: Dict) -> Dict:
    """One input action, every field checked against the protocol's bounds, so
    a screen implementation is handed nothing it has to distrust."""
    name = body.get("action")
    if name not in P.INPUT_ACTIONS:
        raise WorkstationError("bad_request", f"“action” is one of {', '.join(P.INPUT_ACTIONS)}.")
    out: Dict = {"action": name}

    def coord(key: str, limit: int, required: bool) -> None:
        v = body.get(key)
        if v is None:
            if required:
                raise WorkstationError("bad_request", f"“{name}” needs “{key}”.")
            return
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < limit:
            raise WorkstationError("bad_request",
                                   f"“{key}” is a pixel from 0 to {limit - 1}.")
        out[key] = v

    if name in ("click", "double_click", "triple_click", "right_click", "middle_click",
                "move", "drag", "scroll"):
        coord("x", P.SCREEN_WIDTH, True)
        coord("y", P.SCREEN_HEIGHT, True)
    if name in ("mouse_down", "mouse_up"):
        coord("x", P.SCREEN_WIDTH, False)
        coord("y", P.SCREEN_HEIGHT, False)
    if name == "drag":
        coord("to_x", P.SCREEN_WIDTH, True)
        coord("to_y", P.SCREEN_HEIGHT, True)
    if name == "scroll":
        for k in ("dx", "dy"):
            v = body.get(k, 0)
            if isinstance(v, bool) or not isinstance(v, int) or abs(v) > P.MAX_SCROLL_CLICKS:
                raise WorkstationError("bad_request", f"“{k}” is wheel clicks, -{P.MAX_SCROLL_CLICKS} to "
                                                      f"{P.MAX_SCROLL_CLICKS}.")
            out[k] = v
        if out["dx"] == 0 and out["dy"] == 0:
            raise WorkstationError("bad_request", "A scroll needs “dx” or “dy”.")
    if name == "type":
        text = body.get("text")
        if not isinstance(text, str) or not text:
            raise WorkstationError("bad_request", "“type” needs “text”.")
        if len(text) > P.MAX_TYPE_CHARS:
            raise WorkstationError("too_large", f"At most {P.MAX_TYPE_CHARS:,} characters at a time.")
        out["text"] = text
    if name == "key":
        keys = body.get("keys")
        if not isinstance(keys, str) or not _KEYS_RE.match(keys):
            raise WorkstationError("bad_request",
                                   "“keys” is xdotool key syntax, such as “ctrl+l” or “Return”.")
        out["keys"] = keys
    if name == "wait":
        ms = body.get("ms", 1000)
        if isinstance(ms, bool) or not isinstance(ms, int) or not 0 <= ms <= P.MAX_WAIT_MS:
            raise WorkstationError("bad_request", f"“ms” is 0 to {P.MAX_WAIT_MS}.")
        out["ms"] = ms
    return out


def _os_error(e: OSError) -> WorkstationError:
    where = f" ({e.filename})" if getattr(e, "filename", None) else ""
    if isinstance(e, PermissionError):
        return WorkstationError("forbidden", f"The workstation account may not do that{where}: "
                                             f"{e.strerror or 'permission denied'}.")
    if isinstance(e, FileNotFoundError):
        return WorkstationError("not_found", f"Nothing is there{where}.")
    if isinstance(e, (IsADirectoryError, NotADirectoryError, FileExistsError)):
        return WorkstationError("bad_request", f"{e.strerror or 'That path is the wrong kind'}{where}.")
    logger.warning("filesystem error: %s", e)
    return WorkstationError("internal", f"The workstation's filesystem said: "
                                        f"{e.strerror or type(e).__name__}{where}.")


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        # SIGKILL cannot be caught; a process still here is in uninterruptible
        # I/O and the kernel will reap it. The caller already reports a timeout.
        pass


# ── HTTP ──────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = f"{P.AGENT_NAME}/{VERSION}"
    sys_version = ""
    station: Workstation  # bound by `make_server`

    def log_message(self, fmt, *args):  # noqa: A003
        # Never the Authorization header; the default line does not include it
        # and a new log line here must not either.
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, payload: Optional[Dict]) -> None:
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _fail(self, e: WorkstationError) -> None:
        self._send(P.ERRORS[e.code], P.error_body(e.code, e.message))

    def _body(self) -> Dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise WorkstationError("bad_request", "Content-Length is not a number.")
        if length > P.MAX_BODY_BYTES:
            raise WorkstationError("too_large", "The request is larger than the workstation reads.")
        if length <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise WorkstationError("bad_request", "The request body is not JSON.")
        if not isinstance(data, dict):
            raise WorkstationError("bad_request", "The request body is a JSON object.")
        return data

    def _dispatch(self, method: str) -> None:
        parts = urlsplit(self.path)
        path = parts.path.rstrip("/")
        authorised = self.station.authorised(self.headers.get("Authorization", ""))
        try:
            if method == "GET" and path == P.ROUTES["health"][1]:
                self._send(200, self.station.health(authorised))
                return
            if not authorised:
                # Before the route lookup, so a caller without the token cannot
                # map the routes by comparing 401 against 404.
                raise WorkstationError("unauthorized", "The workstation token is missing or wrong.")
            if method == "POST" and path == P.ROUTES["config"][1]:
                self._send(200, self.station.config(self._body()))
                return
            # `B959`: the account itself, looked at and not made.
            bare = _ACCOUNT_PATH_RE.match(path)
            if bare and method == P.ROUTES["account"][0]:
                self._send(200, self.station.account(self.station.check_account(
                    bare.group("account"))))
                return
            m = _ROUTE_RE.match(path)
            if not m:
                raise WorkstationError("not_found", "No such workstation route.")
            account = self.station.check_account(m.group("account"))
            name = next((n for n, (verb, tmpl) in P.ROUTES.items()
                         if verb == method and tmpl.endswith("/" + m.group("rest"))
                         and "{account}" in tmpl), None)
            if name is None:
                raise WorkstationError("not_found", "No such workstation route.")
            if name == "screenshot":
                q = parse_qs(parts.query)
                shot = self.station.screenshot(account, (q.get("format") or ["png"])[0])
                if (q.get("if_none_match") or [""])[0] == shot["digest"]:
                    self._send(304, None)
                    return
                self._send(200, shot)
                return
            body = self._body()
            if name == "exec" and body.get("stream"):
                self._stream_exec(account, body)
                return
            handler = {"ensure": lambda: self.station.ensure(account),
                       "reset": lambda: self.station.reset(account),
                       "control": lambda: self.station.control(account, body),
                       "exec": lambda: self.station.exec(account, body),
                       "read": lambda: self.station.read(account, body),
                       "write": lambda: self.station.write(account, body),
                       "list": lambda: self.station.list(account, body),
                       "input": lambda: self.station.input(account, body)}[name]
            self._send(200, handler())
        except WorkstationError as e:
            self._fail(e)
        except ConnectionError:
            # The caller hung up before the answer; there is nobody to tell.
            logger.info("workstation route %s: the caller went away", path)
        except OSError as e:
            # What the filesystem said, as the protocol says it: a file the
            # account may not touch is not a daemon failure.
            self._fail(_os_error(e))
        except Exception as e:  # noqa: BLE001 — the caller gets a sentence, the log gets the trace
            logger.exception("workstation route %s failed", path)
            self._fail(WorkstationError("internal", f"The workstation failed: {type(e).__name__}."))

    def _stream_exec(self, account: str, body: Dict) -> None:
        # Validated before the 200, so a bad request is still a plain error.
        prepared = self.station._exec_prepare(account, body)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        lock = threading.Lock()

        def line(obj: Dict) -> None:
            with lock:
                self.wfile.write(json.dumps(obj).encode("utf-8") + b"\n")
                self.wfile.flush()

        try:
            result = self.station.exec(account, body, prepared=prepared,
                                       on_chunk=lambda kind, data: line({"type": kind, "data": data}),
                                       caller_gone=self._caller_gone)
            line({"type": "exit", **result})
        except WorkstationError as e:
            line({"type": "exit", **P.error_body(e.code, e.message), "exit_code": 1})
        except (BrokenPipeError, ConnectionResetError):
            logger.info("exec stream closed by the caller")

    def _caller_gone(self) -> bool:
        """Whether the caller closed its end. Nothing more is ever sent on an
        exec stream's request side, so a readable socket that reads as empty
        is the caller hanging up — seen without writing anything to it."""
        try:
            ready, _, _ = select.select([self.connection], [], [], 0)
            if not ready:
                return False
            return self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")


def make_server(system: System, token: str, *, bind: str = "0.0.0.0",
                port: int = P.DEFAULT_PORT) -> ThreadingHTTPServer:
    station = Workstation(system, token)
    handler = type("BoundHandler", (Handler,), {"station": station})
    httpd = ThreadingHTTPServer((bind, port), handler)
    httpd.daemon_threads = True
    httpd.station = station  # type: ignore[attr-defined]
    return httpd


__all__ = ["Handler", "NoScreen", "Screen", "SingleUserSystem", "System", "VERSION",
           "Workstation", "WorkstationError", "bearer", "load_or_create_token",
           "make_server", "mint_token"]
