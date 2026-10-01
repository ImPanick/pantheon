# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Ubuntu workstation's system — `P20-01`, `D-2026-09-30-03`.

`agentd.py` answers the protocol; this is how its `System` and `Screen` work on
the Ubuntu image (`workstation/Dockerfile`): **one Unix account and one X
display per person**, `sudo` as a switch, and a home that survives the
container. Standard library only and nothing from Pantheon, like the rest of
the package — a test enforces both.

ACCOUNTS
========

`account_name(owner)` (the protocol's) is the Unix name. The uid is the hard
part: homes live in a volume and `/etc/passwd` does not, so after a container
restart the files in `/home/pw-ann-…` are owned by a *number* that no longer
has a name. The account is made again on the next `ensure`, and it must get the
same number or the person's own files are somebody else's.

**The number comes from a registry kept inside the homes volume**
(`<homes>/.pantheon-workstation/accounts.json`, root 0600), not from a hash of
the name. A hash is stable, but 40,000 uids reach a 1% chance of two people
colliding at 29 people, and a collision needs a registry to settle anyway — at
which point the hash is a second source of truth beside it (`Law 7`). The
registry is the one; allocation is the lowest free uid in `UID_MIN..UID_MAX`
that is not in the file, not in `/etc/passwd` or `/etc/group`, and not
reserved (the pairing group, below). If the file is lost or unreadable it is
rebuilt from the owners of the homes themselves, which record the same fact,
before anything is allocated — a lost registry must never renumber a person.

An entry is believed only if its name is an account name and its uid is inside
the range. With `sudo` on an agent is root and can edit the file; the range
check is what stops such an edit from surviving a later `sudo` off as uid 0.

THE HOME, AND THE DAEMON THAT IS ROOT
=====================================

The daemon runs as root (it makes accounts). Every file operation it performs
for an account — `read`, `write`, `list`, the script `exec` runs — is done
**with that account's filesystem identity** (`acting_as`: `setfsuid`/`setfsgid`
on the request's own thread, supplementary groups dropped at start). The jail
in `agentd.resolve` checks a path once; a root daemon writing to that path a
moment later can be walked out of the home by an agent swapping a directory
for a symlink in between, and `chown`ing what it wrote would then hand the
agent any file on the system. Acting as the account makes the race worthless:
the kernel checks each open as the account, so the worst a swap achieves is
what the account could do anyway. With `sudo` on, operations run as root —
the agent is root-equivalent then, and the jail is lifted by the protocol.

THE DISPLAY
===========

`Xvfb` runs **as the account**, with `-displayfd` (the server picks a free
number, so an account squatting another's number only moves it along) and an
MIT cookie in the account's own `~/.Xauthority` (0600) — measured 2026-09-30 in
the image: a second account without the cookie is refused (*Authorization
required*). JWM draws a tray with a Terminal and a Firefox button and opens one
terminal (`skel/.jwmrc`). The display starts on the first `ensure` or the
first screenshot or input, not on every command: a person who only uses the
shell does not pay for a desktop.

**The grabber is `scrot`, measured** (2026-09-30, 1280x800 JWM desktop, three
runs each): scrot PNG 64-70 ms and JPEG q75 20-24 ms; `xwd` plus a
standard-library XWD-to-PNG converter 70-75 ms for PNG and no JPEG at all;
ImageMagick `import` 111-138 ms PNG, 64-80 ms JPEG. Installed size: scrot and
imlib2 0.9 MB, `x11-apps` (for `xwd`) 2.4 MB, ImageMagick with the Ghostscript
it pulls in about 64 MB. So both formats are real; neither is faked by MIME.
`scrot -` cannot be used: it opens `/dev/stdout` by path, and a pipe the root
daemon made is not the account's to open (measured: *access to stdout failed*).
The frame is written into the account's private runtime directory and read
back by the same process that wrote it.

`xdotool` sends input. Not with `--sync`: `mousemove --sync` to where the
pointer already is waits forever in the packaged 3.20160805 (measured), and
XTest events from one connection are processed in order anyway.

SUDO
====

One rule in `/etc/sudoers.d/pantheon-workstation`, for the group every account
is in, written by the daemon (never baked into the image) and validated with
`visudo -c` before it replaces the old file. The choice is kept in the homes
volume so a restart does not quietly change it. **Turning sudo off does not
undo what a root-equivalent agent already did** outside its home while it was
on; recreating the container does (`docker compose up -d --force-recreate
workstation`) — homes are in the volume and survive it.
"""
from __future__ import annotations

import contextlib
import ctypes
import grp
import json
import logging
import os
import pwd
import secrets
import select
import shutil
import signal
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from workstation import protocol as P
from workstation.agentd import Screen, System, WorkstationError

logger = logging.getLogger("pantheon.workstation.ubuntu")

UID_MIN = 20_000
UID_MAX = 59_999
AGENTS_GROUP = "pantheon-agents"
AGENTS_GID = 19_999
STATE_DIRNAME = ".pantheon-workstation"
SUDOERS_PATH = Path("/etc/sudoers.d/pantheon-workstation")
X_SOCKET_DIR = Path("/tmp/.X11-unix")
RUNTIME_ROOT = Path("/run/user")
SHELL = "/bin/bash"
SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
XAUTH_NAME = b"MIT-MAGIC-COOKIE-1"
_FAMILY_WILD = 0xFFFF
_DISPLAY_START_S = 10.0
_INPUT_TIMEOUT_S = 15.0
_JPEG_QUALITY = 75


# ── the uid registry ──────────────────────────────────────────────────────────

def _id_in_use(uid: int) -> bool:
    """A uid or gid the system already gives to something else."""
    for lookup in (pwd.getpwuid, grp.getgrgid):
        try:
            lookup(uid)
            return True
        except KeyError:
            pass  # no such uid or gid: this lookup says the number is free
    return False


class AccountRegistry:
    """account name -> uid, kept in the homes volume (module docstring)."""

    def __init__(self, path: Path, homes: Path, *, lo: int = UID_MIN, hi: int = UID_MAX,
                 reserved: Iterable[int] = (),
                 id_in_use: Callable[[int], bool] = _id_in_use,
                 owner_of: Callable[[Path], int] = lambda p: p.lstat().st_uid) -> None:
        self.path = Path(path)
        self.homes = Path(homes)
        self.lo, self.hi = lo, hi
        self.reserved = {int(r) for r in reserved}
        self._id_in_use = id_in_use
        self._owner_of = owner_of
        self._lock = threading.Lock()
        self._map: Optional[Dict[str, int]] = None

    def _valid(self, name: object, uid: object) -> bool:
        return (isinstance(name, str) and bool(P.ACCOUNT_RE.match(name))
                and isinstance(uid, int) and not isinstance(uid, bool)
                and self.lo <= uid <= self.hi and uid not in self.reserved)

    def _clean(self, pairs: Iterable[Tuple[object, object]]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        taken: set = set()
        for name, uid in sorted(pairs, key=lambda kv: str(kv[0])):
            if not self._valid(name, uid):
                logger.warning("ignoring registry entry %r -> %r: not an account in range", name, uid)
                continue
            if uid in taken:
                logger.warning("ignoring registry entry %r -> %r: uid already given", name, uid)
                continue
            out[str(name)] = int(uid)  # type: ignore[arg-type]
            taken.add(uid)
        return out

    def _from_homes(self) -> Dict[str, int]:
        pairs = []
        try:
            entries = sorted(self.homes.iterdir())
        except OSError:
            return {}
        for home in entries:
            if P.ACCOUNT_RE.match(home.name) and home.is_dir() and not home.is_symlink():
                try:
                    pairs.append((home.name, self._owner_of(home)))
                except OSError:
                    continue
        return self._clean(pairs)

    def _load(self) -> Dict[str, int]:
        if self._map is not None:
            return self._map
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            entries = raw.get("accounts") if isinstance(raw, dict) else None
            if not isinstance(entries, dict):
                raise ValueError("no accounts table")
            self._map = self._clean((k, (v or {}).get("uid") if isinstance(v, dict) else None)
                                    for k, v in entries.items())
        except FileNotFoundError:
            self._map = self._from_homes()
            if self._map:
                self._save()
        except (OSError, ValueError) as e:
            logger.warning("the account registry at %s is unreadable (%s); rebuilding it from "
                           "the owners of the homes", self.path, e)
            self._map = self._from_homes()
            self._save()
        return self._map

    def _save(self) -> None:
        assert self._map is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        body = json.dumps({"version": 1, "accounts": {
            name: {"uid": uid} for name, uid in sorted(self._map.items())}}, indent=1)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def accounts(self) -> List[str]:
        with self._lock:
            return sorted(self._load())

    def get(self, account: str) -> Optional[int]:
        with self._lock:
            return self._load().get(account)

    def uid_for(self, account: str) -> int:
        """The account's uid: the recorded one, the one its home already has,
        or the lowest free one — recorded before it is returned."""
        if not P.ACCOUNT_RE.match(account or ""):
            raise WorkstationError("bad_request", f"“{account}” is not a workstation account.")
        with self._lock:
            known = self._load()
            if account in known:
                return known[account]
            used = set(known.values())
            home = self.homes / account
            uid: Optional[int] = None
            try:
                if home.is_dir() and not home.is_symlink():
                    owner = self._owner_of(home)
                    if self._valid(account, owner) and owner not in used:
                        uid = owner  # its files already say whose they are
            except OSError:
                pass
            if uid is None:
                uid = next((n for n in range(self.lo, self.hi + 1)
                            if n not in used and n not in self.reserved
                            and not self._id_in_use(n)), None)
            if uid is None:
                raise WorkstationError("unavailable", "The workstation has no free account "
                                                      "numbers left.")
            known[account] = uid
            self._save()
            return uid


# ── sudo ──────────────────────────────────────────────────────────────────────

def sudoers_text(on: bool) -> str:
    """The whole of the daemon's sudoers file. Written in both states, so
    reading it says which one the workstation is in."""
    head = ("# Written by the Pantheon workstation daemon (P20-01). Do not edit: it is\n"
            "# rewritten whenever an admin changes Settings -> Workstation -> sudo.\n")
    if on:
        return head + f"%{AGENTS_GROUP} ALL=(ALL:ALL) NOPASSWD: ALL\n"
    return head + "# sudo is off: workstation accounts may not use it.\n"


def write_sudoers(on: bool, path: Path = SUDOERS_PATH, *,
                  validate: Optional[Callable[[Path], bool]] = None) -> None:
    """Replace the file atomically. The temporary name has a dot in it, and
    sudo's `#includedir` skips any name with a dot, so a half-written file is
    never read."""
    path = Path(path)
    tmp = path.with_name("." + path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o440)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(sudoers_text(on))
    os.chmod(tmp, 0o440)
    check = validate if validate is not None else _visudo_ok
    if not check(tmp):
        tmp.unlink(missing_ok=True)
        raise WorkstationError("internal", "The sudo rule did not validate; nothing was changed.")
    os.replace(tmp, path)


def _visudo_ok(path: Path) -> bool:
    visudo = shutil.which("visudo")
    if not visudo:
        return True  # nothing to check with; the content is a constant above
    return subprocess.run([visudo, "-c", "-q", "-f", str(path)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


# ── acting as an account (module docstring: THE HOME, AND THE DAEMON) ─────────

_libc = None


def _fs_ids(uid: int, gid: int) -> None:
    """Set this thread's filesystem uid and gid. `setfsuid` is per thread in
    Linux and glibc does not broadcast it, so another request's thread is
    untouched; each call is checked, because the syscall reports failure only
    by not changing anything."""
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL(None, use_errno=True)
    _libc.setfsgid(gid)
    _libc.setfsuid(uid)
    if _libc.setfsuid(0xFFFFFFFF) != uid or _libc.setfsgid(0xFFFFFFFF) != gid:
        raise WorkstationError("internal", "The workstation could not act as the account.")


@contextlib.contextmanager
def fs_identity(uid: int, gid: int) -> Iterator[None]:
    """Filesystem access as `uid:gid` on this thread, then back to root."""
    _fs_ids(uid, gid)
    try:
        yield
    finally:
        _fs_ids(0, 0)


def kill_processes(uid: int, *, proc: Path = Path("/proc"),
                   kill: Callable[[int, int], None] = os.kill, rounds: int = 50,
                   pause: float = 0.05) -> int:
    """SIGKILL every live process whose real, effective or saved uid is `uid`,
    until none is left. Read from `/proc`, so it needs no `pkill` in the image
    and a test can hand it a fake one. Zombies are skipped: they are already
    dead and only their parent can clear them."""
    killed = 0
    for _ in range(rounds):
        found = []
        try:
            entries = list(proc.iterdir())
        except OSError:
            return killed
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                status = (entry / "status").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            uids: List[int] = []
            state = ""
            for line in status.splitlines():
                if line.startswith("Uid:"):
                    uids = [int(x) for x in line.split()[1:4] if x.isdigit()]
                elif line.startswith("State:"):
                    state = line.split()[1] if len(line.split()) > 1 else ""
            if uid in uids and state not in ("Z", "X"):
                found.append(int(entry.name))
        if not found:
            return killed
        for pid in found:
            try:
                kill(pid, signal.SIGKILL)
                killed += 1
            except (ProcessLookupError, PermissionError):
                # Gone between the read and the kill, or not ours to kill; the
                # next round reads /proc again and finds what is left.
                pass
        time.sleep(pause)
    return killed


# ── the X display ─────────────────────────────────────────────────────────────

def xauthority_entry(cookie: bytes, display: str = "") -> bytes:
    """One `.Xauthority` record: FamilyWild, so it matches however a client
    names the host, and an empty display number, which matches any — measured
    in the image with both the server (`-auth`) and a client (`xdotool`)."""
    def field(b: bytes) -> bytes:
        return struct.pack(">H", len(b)) + b
    return (struct.pack(">H", _FAMILY_WILD) + field(b"") + field(display.encode("ascii"))
            + field(XAUTH_NAME) + field(cookie))


def xdotool_argv(action: Dict) -> Tuple[List[str], Optional[bytes]]:
    """`(argv, stdin)` for one input action `agentd` has already validated.
    Coordinates are the screenshot's own pixels; the screen is the protocol's
    fixed size, so nothing is scaled."""
    name = action["action"]
    # A pause after moving and a held press, not `xdotool click`: its press
    # and release arrive together, and JWM's tray and GTK (Firefox) drop most
    # of them — measured 2026-09-30 on the tray's Terminal button: `click` 1
    # of 10 (and 1-3 of 6 with pauses before it), a 30-50 ms hold 10 of 10.
    move = lambda: ["mousemove", str(action["x"]), str(action["y"]), "sleep", _SETTLE]  # noqa: E731
    buttons = {"click": ("1", 1), "double_click": ("1", 2), "triple_click": ("1", 3),
               "right_click": ("3", 1), "middle_click": ("2", 1)}
    if name in buttons:
        button, times = buttons[name]
        presses: List[str] = []
        for n in range(times):
            # 80 ms apart keeps a triple click well inside GTK's 400 ms.
            presses += (["sleep", "0.08"] if n else []) + _press(button)
        return ["xdotool", *move(), *presses], None
    if name == "move":
        return ["xdotool", *move()[:3]], None
    if name == "drag":
        return ["xdotool", *move(), "mousedown", "1", "sleep", "0.1",
                "mousemove", str(action["to_x"]), str(action["to_y"]), "sleep", "0.1",
                "mouseup", "1"], None
    if name in ("mouse_down", "mouse_up"):
        pre = move() if "x" in action and "y" in action else []
        return ["xdotool", *pre, "mousedown" if name == "mouse_down" else "mouseup", "1"], None
    if name == "scroll":
        argv = ["xdotool", *move()]
        # X wheel buttons: 4 up, 5 down, 6 left, 7 right. `+dy` is down.
        for delta, neg, pos in ((action["dy"], "4", "5"), (action["dx"], "6", "7")):
            if delta:
                argv += ["click", "--repeat", str(abs(delta)), "--delay", "30",
                         pos if delta > 0 else neg]
        return argv, None
    if name == "type":
        text = action["text"]
        # Read from stdin, so text that starts with "-" is typed, not parsed.
        # 12 ms a key is xdotool's default; long text goes faster so the
        # protocol's largest (20,000 characters) finishes in about 20 s.
        delay = max(1, min(12, 20_000 // max(1, len(text))))
        return ["xdotool", "type", "--delay", str(delay), "--file", "-"], text.encode("utf-8")
    if name == "key":
        return ["xdotool", "key", "--clearmodifiers", "--delay", "40", *action["keys"].split()], None
    raise WorkstationError("bad_request", f"“{name}” is not something the display does.")


def read_display_number(fd: int, timeout: float) -> str:
    """What `Xvfb -displayfd` says, read up to its newline. The server writes
    the number and the newline in two calls and treats a failed second write
    as fatal, so closing the pipe after the first read killed the display it
    had just started (measured 2026-09-30: "Cannot write display number to
    fd 6", intermittently, one start in several)."""
    deadline = time.monotonic() + timeout
    got = b""
    while b"\n" not in got and len(got) < 32:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        ready, _, _ = select.select([fd], [], [], left)
        if not ready:
            break
        chunk = os.read(fd, 32)
        if not chunk:
            break
        got += chunk
    return got.decode("ascii", "replace").strip()


_SETTLE = "0.05"
_HOLD = "0.05"


def _press(button: str) -> List[str]:
    return ["mousedown", button, "sleep", _HOLD, "mouseup", button]


class XDisplay(Screen):
    """One account's display: Xvfb, JWM and what JWM starts, all as the
    account. Started lazily, restarted if it died."""

    def __init__(self, system: "UbuntuSystem", account: str) -> None:
        self.system = system
        self.account = account
        self.number: Optional[int] = None
        self._procs: List[subprocess.Popen] = []
        self._lock = threading.Lock()

    @property
    def name(self) -> Optional[str]:
        return f":{self.number}" if self.number is not None and self.running() else None

    def running(self) -> bool:
        return bool(self._procs) and self._procs[0].poll() is None

    def auth_path(self) -> Path:
        return self.system.home(self.account) / ".Xauthority"

    def start(self) -> str:
        with self._lock:
            if self.running() and self.number is not None:
                return f":{self.number}"
            if self._procs:
                # Said, because a display that keeps stopping is otherwise a
                # mystery: -9 or -15 here means something outside the daemon
                # killed it.
                logger.warning("display :%s for %s had stopped (exit %s); starting it again",
                               self.number, self.account, self._procs[0].returncode)
            self._stop_locked()
            prefix, env = self.system.run_as(self.account, with_display=False)
            auth = self.auth_path()
            uid = self.system.uid(self.account)
            try:
                with fs_identity(uid, uid):
                    fd = os.open(auth, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                                 0o600)
                    with os.fdopen(fd, "wb") as f:
                        f.write(xauthority_entry(secrets.token_bytes(16)))
            except OSError as e:
                raise WorkstationError("unavailable", f"The display's key could not be written to "
                                                      f"{auth}: {e.strerror or e}.")
            read_fd, write_fd = os.pipe()
            try:
                xvfb = subprocess.Popen(
                    [*prefix, "Xvfb", "-displayfd", str(write_fd), "-screen", "0",
                     f"{P.SCREEN_WIDTH}x{P.SCREEN_HEIGHT}x24", "-nolisten", "tcp",
                     "-auth", str(auth), "-noreset", "-dpi", "96"],
                    env=env, cwd=str(self.system.home(self.account)), pass_fds=(write_fd,),
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    start_new_session=True)
            except OSError as e:
                os.close(read_fd)
                os.close(write_fd)
                raise WorkstationError("unavailable", f"The display could not be started: {e}.")
            os.close(write_fd)
            try:
                text = read_display_number(read_fd, _DISPLAY_START_S)
            finally:
                os.close(read_fd)
            if not text.isdigit():
                why = _stop(xvfb, collect=True)
                raise WorkstationError("unavailable", "The display did not start"
                                       + (f": {why}" if why else "."))
            if xvfb.stderr is not None:
                # Nothing reads it after start-up; a full pipe would stall Xvfb.
                threading.Thread(target=_drain, args=(xvfb.stderr, f"Xvfb {self.account}"),
                                 daemon=True).start()
            self.number = int(text)
            self._procs = [xvfb]
            _, denv = self.system.run_as(self.account)
            # A session bus of the account's own, so a second Firefox launch
            # finds the first one (without it: "Firefox is already running").
            session = ["dbus-run-session", "--"] if shutil.which("dbus-run-session") else []
            try:
                self._procs.append(subprocess.Popen(
                    [*prefix, *session, "jwm"], env=denv, cwd=str(self.system.home(self.account)),
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True))
            except OSError as e:
                logger.warning("window manager for %s did not start: %s", self.account, e)
            else:
                waited = self._wait_for_wm(prefix, denv)
                logger.debug("window manager for %s ready after %.2f s", self.account, waited)
            logger.info("display :%s started for %s", self.number, self.account)
            return f":{self.number}"

    def _wait_for_wm(self, prefix: List[str], env: Dict[str, str], limit: float = 3.0) -> float:
        """Until the window manager has taken the screen, so the first click
        after a start lands on a tray rather than a bare root window —
        measured 2026-09-30: an input sent as the display started missed the
        tray every time. The probe is the EWMH desktop count, which the root
        window has only once a manager set it: `xdotool get_num_desktops`
        fails before JWM and answers 1 about 100 ms after it starts."""
        started = time.monotonic()
        while time.monotonic() - started < limit:
            probe = subprocess.run([*prefix, "xdotool", "get_num_desktops"],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   cwd=str(self.system.home(self.account)))
            if probe.returncode == 0:
                time.sleep(0.2)  # the tray is drawn just after the check window
                break
            time.sleep(0.05)
        return time.monotonic() - started

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        for proc in reversed(self._procs):
            _stop(proc)
        self._procs = []
        self.number = None

    def _run(self, argv: Sequence[str], stdin: Optional[bytes], timeout: float) -> bytes:
        """Run an X client as the account on this display. If the server
        stopped between starting and using it, start it once more — once."""
        for attempt in (1, 2):
            display = self.start()
            prefix, env = self.system.run_as(self.account, with_display=False)
            env.update(DISPLAY=display, XAUTHORITY=str(self.auth_path()))
            try:
                done = subprocess.run([*prefix, *argv], env=env, input=stdin,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      cwd=str(self.system.home(self.account)), timeout=timeout)
            except subprocess.TimeoutExpired:
                raise WorkstationError("unavailable", "The display did not answer in time.")
            except OSError as e:
                raise WorkstationError("unavailable", f"The display could not be reached: {e}.")
            if done.returncode == 0:
                return done.stdout
            if attempt == 1 and not self.running():
                continue
            why = done.stderr.decode("utf-8", "replace").strip().splitlines()
            raise WorkstationError("unavailable", "The display refused that"
                                   + (f": {why[-1]}" if why else "."))
        raise WorkstationError("unavailable", "The display keeps stopping.")  # pragma: no cover

    def grab(self, fmt: str) -> Tuple[bytes, str]:
        ext, mime, quality = (("jpg", "image/jpeg", ["-q", str(_JPEG_QUALITY)]) if fmt == "jpeg"
                              else ("png", "image/png", []))
        runtime = self.system.runtime_dir(self.account)
        target = runtime / f"pantheon-screen-{secrets.token_hex(6)}.{ext}"
        # One process, as the account, writes the frame into its own 0700
        # runtime directory and hands the bytes back (`scrot -` cannot write
        # to a pipe the root daemon made — module docstring).
        script = 'scrot -o -z "$@" "$F" && cat "$F"; rc=$?; rm -f "$F"; exit $rc'
        data = self._run(["env", f"F={target}", "sh", "-c", script, "sh", *quality], None, 20.0)
        if not data:
            raise WorkstationError("unavailable", "The display gave back an empty picture.")
        return data, mime

    def send(self, action: Dict) -> None:
        argv, stdin = xdotool_argv(action)
        timeout = 60.0 if action["action"] == "type" else _INPUT_TIMEOUT_S
        self._run(argv, stdin, timeout)


def _drain(stream, label: str = "") -> None:
    """Read a child's stderr to the end so a full pipe never stalls it, and
    keep what it says in the daemon's log at debug level."""
    try:
        for line in iter(stream.readline, b""):
            logger.debug("%s: %s", label, line.decode("utf-8", "replace").rstrip())
    except (OSError, ValueError):
        pass  # the pipe was closed under us by `_stop`: the child is gone


def _stop(proc: subprocess.Popen, *, collect: bool = False) -> str:
    """End a process group; with `collect`, what it said on stderr."""
    for sig, wait in ((signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0)):
        if proc.poll() is not None:
            break
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass  # already exited; `wait` below reaps it either way
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            continue
    if collect and proc.stderr is not None:
        try:
            lines = proc.stderr.read().decode("utf-8", "replace").strip().splitlines()
            return lines[-1] if lines else ""
        except (OSError, ValueError):
            return ""
    return ""


# ── the system ────────────────────────────────────────────────────────────────

class UbuntuSystem(System):
    """A Unix account and an X display per person (module docstring)."""

    backend = "container"

    def __init__(self, homes: Path = Path("/home"), *, skeleton: Path = Path("/etc/skel"),
                 sudo_default: bool = True, network: str = "full",
                 reserved_ids: Iterable[int] = (), sudoers_path: Path = SUDOERS_PATH,
                 runtime_root: Path = RUNTIME_ROOT, prepare: bool = True) -> None:
        super().__init__()
        self.homes = Path(homes)
        self.skeleton = Path(skeleton)
        self.network = network if network in P.NETWORK_MODES else "full"
        self.state_dir = self.homes / STATE_DIRNAME
        self.sudoers_path = Path(sudoers_path)
        self.runtime_root = Path(runtime_root)
        self.registry = AccountRegistry(self.state_dir / "accounts.json", self.homes,
                                        reserved=reserved_ids)
        self._accounts_lock = threading.Lock()
        self._ready: set = set()
        self._displays: Dict[str, XDisplay] = {}
        self._acting = threading.local()
        self.sudo = self._persisted_sudo(sudo_default)
        if prepare:
            self.prepare()

    # -- start-up ---------------------------------------------------------------

    def prepare(self) -> None:
        """What the machine needs before the first request: the agents' group,
        the X socket directory, no supplementary groups on the daemon (so a
        thread acting as an account has only that account's groups), and the
        sudo rule the persisted setting says."""
        if os.geteuid() != 0:
            raise WorkstationError("unavailable", "The Ubuntu workstation runs as root: it makes "
                                                  "an account for each person.")
        self.homes.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.state_dir, 0o700)
        try:
            grp.getgrnam(AGENTS_GROUP)
        except KeyError:
            _run_root(["groupadd", "-g", str(AGENTS_GID), AGENTS_GROUP])
        X_SOCKET_DIR.mkdir(parents=True, exist_ok=True)
        os.chown(X_SOCKET_DIR, 0, 0)
        os.chmod(X_SOCKET_DIR, 0o1777)
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        os.setgroups([])
        write_sudoers(self.sudo, self.sudoers_path)

    def _settings_path(self) -> Path:
        return self.state_dir / "settings.json"

    def _persisted_sudo(self, default: bool) -> bool:
        try:
            value = json.loads(self._settings_path().read_text(encoding="utf-8")).get("sudo")
        except (OSError, ValueError, AttributeError):
            return bool(default)
        return value if isinstance(value, bool) else bool(default)

    # -- the System interface ---------------------------------------------------

    def home(self, account: str) -> Path:
        return self.homes / account

    def accounts(self) -> List[str]:
        return self.registry.accounts()

    def uid(self, account: str) -> int:
        uid = self.registry.get(account)
        if uid is None:
            raise WorkstationError("not_found", f"There is no workstation account {account}.")
        return uid

    def ensure(self, account: str) -> Dict:
        home = self.home(account)
        with self._accounts_lock:
            if account in self._ready and home.is_dir():
                return {"home": str(home), "display": self._display_name(account),
                        "created": False}
            uid = self.registry.uid_for(account)
            self._unix_account(account, uid)
            created = not os.path.lexists(home)
            if created:
                self._fill_home(home, uid)
            else:
                # The home itself is the daemon's to keep right; what is in it
                # is the person's, and is not walked. (Linux cannot chmod a
                # symlink; a home that is one is left for `reset` to replace.)
                os.chown(home, uid, uid, follow_symlinks=False)
                if not home.is_symlink():
                    os.chmod(home, 0o700)
            self.runtime_dir(account)
            self._ready.add(account)
        return {"home": str(home), "display": self._display_name(account), "created": created}

    def wake(self, account: str) -> Optional[str]:
        try:
            return self.screen(account).start()
        except Exception as e:  # noqa: BLE001 — `System.wake`: never takes `ensure` down
            logger.warning("display for %s did not start: %s", account,
                           getattr(e, "message", None) or e)
            return None

    def reset(self, account: str) -> None:
        self.ensure(account)
        display = self._displays.get(account)
        had_display = bool(display and display.running())
        if display:
            display.stop()
        uid = self.uid(account)
        with self._accounts_lock:
            kill_processes(uid)
            home = self.home(account)
            if os.path.lexists(home):
                try:
                    if home.is_symlink():
                        home.unlink()
                    else:
                        shutil.rmtree(home)
                except OSError as e:
                    raise WorkstationError("unavailable", f"The home could not be cleared: {e}.")
            self._fill_home(home, uid)
            runtime = self.runtime_root / str(uid)
            shutil.rmtree(runtime, ignore_errors=True)
            self.runtime_dir(account)
        if had_display:
            self.wake(account)

    def run_as(self, account: str, *, with_display: bool = True) -> Tuple[List[str], Dict[str, str]]:
        uid = self.uid(account)
        home = str(self.home(account))
        env = {
            "HOME": home, "USER": account, "LOGNAME": account, "SHELL": SHELL,
            "PATH": f"{home}/.local/bin:{SYSTEM_PATH}",
            "LANG": "C.UTF-8", "TERM": "xterm-256color",
            "XDG_RUNTIME_DIR": str(self.runtime_root / str(uid)),
        }
        display = self._display_name(account) if with_display else None
        if display:
            env["DISPLAY"] = display
            env["XAUTHORITY"] = f"{home}/.Xauthority"
        # setpriv: a plain exec as the account with its groups (so the sudo
        # rule for `pantheon-agents` applies) — no PAM session, no shell in
        # between. Deliberately not `--no-new-privs`: that would break sudo.
        return ["setpriv", f"--reuid={uid}", f"--regid={uid}", "--init-groups", "--"], env

    @contextlib.contextmanager
    def acting_as(self, account: str) -> Iterator[None]:
        if self.sudo:
            yield  # root-equivalent by the admin's choice; the jail is lifted too
            return
        uid = self.uid(account)
        self._acting.account = account
        try:
            with fs_identity(uid, uid):
                yield
        finally:
            self._acting.account = None

    def own(self, account: str, paths: Iterable[Path]) -> None:
        if getattr(self._acting, "account", None) == account:
            return  # made as the account already; a chown here could be raced
        uid = self.registry.get(account)
        if uid is None:
            return
        home = os.path.realpath(self.home(account))
        for p in paths:
            real = os.path.realpath(p)
            # With sudo on (the only way here) a file outside the home was
            # written as root on purpose, like `sudo tee`, and stays root's.
            if real == home or real.startswith(home + os.sep):
                try:
                    os.chown(p, uid, uid, follow_symlinks=False)
                except OSError as e:
                    # Said, not swallowed: the file stays root's, which the
                    # account (sudo is on to be here) can still fix itself.
                    logger.warning("could not give %s to %s: %s", p, account, e)

    def set_sudo(self, on: bool) -> None:
        on = bool(on)
        write_sudoers(on, self.sudoers_path)
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._settings_path()
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"sudo": on}, f)
        os.replace(tmp, path)
        self.sudo = on
        logger.info("sudo is now %s for workstation accounts", "on" if on else "off")

    def screen(self, account: str) -> Screen:
        self.uid(account)
        # setdefault, not check-then-set: two first requests at once (a
        # screenshot and an `ensure`) must share one display, never start two.
        # Making an XDisplay starts nothing, so the loser's costs nothing.
        return self._displays.setdefault(account, XDisplay(self, account))

    # -- helpers ----------------------------------------------------------------

    def runtime_dir(self, account: str) -> Path:
        uid = self.uid(account)
        path = self.runtime_root / str(uid)
        path.mkdir(mode=0o700, exist_ok=True)
        os.chown(path, uid, uid, follow_symlinks=False)
        os.chmod(path, 0o700)
        return path

    def _display_name(self, account: str) -> Optional[str]:
        display = self._displays.get(account)
        return display.name if display else None

    def _unix_account(self, account: str, uid: int) -> None:
        try:
            existing = pwd.getpwnam(account)
        except KeyError:
            existing = None
        if existing is not None:
            if existing.pw_uid != uid:
                raise WorkstationError("unavailable", f"{account} exists with a different number "
                                                      "than its home; nothing was changed.")
            return
        try:
            grp.getgrnam(account)
        except KeyError:
            _run_root(["groupadd", "-g", str(uid), account])
        _run_root(["useradd", "-u", str(uid), "-g", str(uid), "-G", AGENTS_GROUP, "-M",
                   "-d", str(self.home(account)), "-s", SHELL, "-c", "Pantheon workstation",
                   account])

    def _fill_home(self, home: Path, uid: int) -> None:
        if self.skeleton.is_dir():
            shutil.copytree(self.skeleton, home, symlinks=True)
        else:
            home.mkdir(parents=True)
        # Root made it, from the image's own skeleton, before the account has
        # a process that could race the walk.
        for root, dirs, files in os.walk(home):
            for name in dirs + files:
                os.chown(os.path.join(root, name), uid, uid, follow_symlinks=False)
        os.chown(home, uid, uid)
        os.chmod(home, 0o700)


def _run_root(argv: List[str]) -> None:
    done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode != 0:
        why = done.stderr.decode("utf-8", "replace").strip()
        raise WorkstationError("unavailable", f"{argv[0]} failed: {why or done.returncode}.")


__all__ = ["AGENTS_GID", "AGENTS_GROUP", "AccountRegistry", "UID_MAX", "UID_MIN",
           "UbuntuSystem", "XDisplay", "fs_identity", "kill_processes", "read_display_number",
           "sudoers_text", "write_sudoers", "xauthority_entry", "xdotool_argv"]
