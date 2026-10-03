# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-22` — an MCP server built in its author's workstation: made, checked
and tried there from the browser, and — once an admin registers it through the
existing admin route — run there through a relay (`D-2026-10-02-02` §3).

**Where it runs, and why it is a relay.** `D-2026-10-01-05` §3 puts code a
person writes in that person's own workstation account (`P20`), and declined
"Pantheon's own process": a non-admin's code must not run as the app user once
an admin registers it. A registered stdio server is a process Pantheon starts
(`McpManager.connect_server`), so the registration names *this file* run as a
script — a small MCP server on Pantheon's side (it has the `mcp` SDK) whose
`tools/list` and `tools/call` each run the person's `server.py` **in the
person's workstation account**, through the workstation protocol's existing
`exec` (`workstation_for` → `sync_config` → `client.exec`, the Code step's path,
`P22-18`). No workstation code runs as Pantheon, and there is no new network
path: it is the daemon Pantheon already talks to, over the route it already
uses. The costs the owner accepted are said where a person reads them
(`mcp_scaffold.render_workstation_readme`): a short process start per call, no
state between calls, tools down while the workstation is, and the server
running in its author's account when someone else's agent calls it.

**Nothing typed is ever spliced into code (`P22-18`'s rule).** Every exec here
runs one fixed program, `PROBE_HARNESS`, with `shell="python"`; everything it
needs — the server's folder name, what to do, the tool, its arguments, a
timeout — arrives as JSON on stdin. The harness checks the folder name again
against `_NAME_RE`'s pattern, builds the path from `~` itself, starts
`server.py` as a child, speaks the MCP handshake, prints one JSON line and kills
the child. The source a person writes is a *file in their home*, written
through the protocol's `write` and jailed to that home by the daemon.

**Registration is the admin route's and nobody else's.** No function here and
no scaffold route writes an `McpServer` row. `ws_registration` hands back the
fields for `POST /api/mcp/servers` (`require_admin`), which the browser fills
into the existing *Add MCP Server* form; the agent's `manage_mcp` refuses them
(`sys.executable` is an interpreter with a `/` in it — `_validate_mcp_command`,
`FORBIDDEN.md` Part 2, untouched), and `app_api`'s `/api/mcp/servers`
blocklist refuses the loopback.

**A registration pins the code (`integrate-e`).** An admin approves one
program; `--sha256` is the fingerprint of the server's folder's code as it was
then (`PROBE_HARNESS`'s `fingerprint`: every file Python could load as code
there, and every symlink). Before each list or call the harness reads the
fingerprint again and, if it moved, starts nothing — the relay answers
`CHANGED_SINCE_REGISTERED`. Changing the code is the dev loop and stays
allowed (a person's own edit in the panel; while it is registered, only a
person's — `PUT /api/mcp/scaffold/{name}` refuses the assistant's loopback);
it takes the server off the air until an admin registers it again, which
re-pins through the admin route. The residue, said where it is decided: the
pin covers the folder, not what the account's own Python loads from
elsewhere (its user site-packages) — the author's environment, which
`D-2026-10-02-02` §3 accepted along with the author's account.

**The relay's flags are the registration, not the caller's.** `--owner`,
`--server` and `--sha256` are argv an admin saved; nothing a tool call carries can change
which account or folder the relay acts for — the call's name and arguments
ride stdin to the harness as data. Pantheon's environment is never forwarded:
the relay inherits it (`P8-42`) and sends none of it to the workstation.

Stored words (`FORBIDDEN.md` Part 1 at the merge — they live in `mcp_servers`
rows): this module's path `src/workstation_mcp.py`, its flags `--owner`,
`--server` and `--sha256`, and the workstation folder `~/mcp-servers/`.

Public surface:

    WS_FOLDER, RELAY_PATH, OWNER_FLAG, SERVER_FLAG, PROBE_HARNESS
    workstation_why(owner)              None, or the sentence Build is greyed with
    ws_list(owner)                      the servers in ~/mcp-servers/, with their last check
    ws_create(owner, name, tools, d)    write one; refuses to overwrite
    ws_read_source / ws_write_source    server.py, through the protocol's read/write
    ws_verify(owner, name)              start it there, list its tools: {started, tools, error}
    ws_try(owner, name, tool, args)     call one tool there: {ok, stdout, stderr, exit_code, …}
    ws_fingerprint(owner, name)         the fingerprint of its code, as the harness reads it
    ws_registration(owner, name, pin)   the admin route's fields — the relay, pinned to `pin`
    relay_target(command, args)         whose server a registration relays to, and its pin
    ws_send(owner, name)                B1130: send it to the admins — its code and pin, one walk
    sent_waiting(rows) / sent_mine(o)   what waits for an admin; this person's waiting sends
    sent_for_admin(id)                  one, as an admin reviews it: code, fields, still as sent?
    sent_remove(id, by=, is_admin=)     an admin dismisses it, or its sender withdraws it
    main(argv)                          the relay itself (run as a script)
"""
from __future__ import annotations

import os
import sys

if __name__ == "__main__":
    # The relay is started as `python <app>/src/workstation_mcp.py`, so the
    # interpreter put `<app>/src` first on the path, where `src.*` cannot be
    # found and a module there could shadow a package's. The app root goes in
    # its place before anything below imports.
    _HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE]
    sys.path.insert(0, os.path.dirname(_HERE))

import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: The folder under the person's workstation home that built servers live in.
#: Stored, through the relay's `--server`, in every registration.
WS_FOLDER = "mcp-servers"
#: This file, as the registration names it. Stored in `mcp_servers.args`.
RELAY_PATH = os.path.abspath(__file__)
OWNER_FLAG = "--owner"
SERVER_FLAG = "--server"
#: `integrate-e` (the integrator's call on `B1129`): the
#: fingerprint of the server's code as it was when an admin registered it
#: (`PROBE_HARNESS`'s `fingerprint`). Stored in `mcp_servers.args`; the relay
#: runs nothing whose code no longer matches it.
PIN_FLAG = "--sha256"
_PIN_RE_TEXT = r"^[0-9a-f]{64}$"

SERVER_FILENAME = "server.py"
README_FILENAME = "README.md"
#: A person's source is a small program, not a data file.
MAX_SOURCE_BYTES = 256 * 1024

#: How long the harness waits on the server, by what it was asked. A check
#: starts it and lists; a call may do real work. The exec's own bound is this
#: plus `_EXEC_MARGIN_S`, so the harness answers before the daemon kills it.
CHECK_TIMEOUT_S = 20.0
CALL_TIMEOUT_S = 60.0
MAX_CALL_TIMEOUT_S = 120.0
_EXEC_MARGIN_S = 15.0


# ── the one program every exec runs ──────────────────────────────────────────
#
# Standard library only (the workstation has `python3`, not Pantheon's
# packages). Read top to bottom it is: read the job from stdin, check the
# folder name, find `~/mcp-servers/<slug>/server.py`, start it, initialize,
# list or call, print one JSON line, stop it. Its answer is always one JSON
# object on the last line of stdout; `_probe` reads nothing else.

PROBE_HARNESS = r'''
import hashlib, json, os, queue, re, signal, subprocess, sys, threading, time

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
PIN = re.compile(r"^[0-9a-f]{64}$")
FOLDER = "mcp-servers"
TAIL = 4000
MAX_TEXT = 200000
# What Python can load as code from the server's folder: its own source, a
# sibling module or package, compiled bytecode (in __pycache__ or beside its
# source) and extension modules. The fingerprint covers every one of them.
CODE = (".py", ".pyc", ".pyo", ".so", ".pyd")
MAX_FILE = 16 * 1024 * 1024
# B1130: what an admin is shown of a build sent for registration. One source
# file at most what the panel's editor opens (MAX_SOURCE_BYTES); all of them,
# as JSON, well inside the exec's 1,000,000-byte output, which keeps the tail.
SHOW_FILE = 256 * 1024
SHOW_ENCODED = 640 * 1024
SHOW_ENTRIES = 200


def fingerprint(folder, keep=None):
    """sha256 over every file Python could load as code from the folder, and
    every symlink in it, by path. The registration pins this
    (`integrate-e`): a server whose code changed after an admin registered it
    is not run. `keep` (B1130): a list each pinned entry is appended to, with
    the very bytes hashed, so what an admin is shown is what this pins."""
    h = hashlib.sha256()
    for root, dirs, files in os.walk(folder):
        rel = os.path.relpath(root, folder)
        dirs.sort()
        walk = []
        for d in dirs:
            path = os.path.join(root, d)
            if os.path.islink(path):
                name, target = os.path.normpath(os.path.join(rel, d)), os.readlink(path)
                h.update(("link\0%s\0%s\n" % (name, target)).encode("utf-8", "replace"))
                if keep is not None:
                    keep.append({"path": name, "kind": "link", "target": target})
            else:
                walk.append(d)
        dirs[:] = walk
        for f in sorted(files):
            path = os.path.join(root, f)
            name = os.path.normpath(os.path.join(rel, f))
            if os.path.islink(path):
                target = os.readlink(path)
                h.update(("link\0%s\0%s\n" % (name, target)).encode("utf-8", "replace"))
                if keep is not None:
                    keep.append({"path": name, "kind": "link", "target": target})
            if not f.endswith(CODE):
                continue
            data = None
            try:
                with open(path, "rb") as fh:
                    data = fh.read(MAX_FILE)
                digest = hashlib.sha256(data).hexdigest()
            except OSError:
                digest = "unreadable"
            h.update(("file\0%s\0%s\n" % (name, digest)).encode("utf-8", "replace"))
            if keep is not None:
                keep.append({"path": name, "kind": "source" if f.endswith(".py") else "compiled",
                             "sha256": digest, "data": data})
    return h.hexdigest()


def snapshot(folder):
    """B1130. The fingerprint and, from the same bytes in the same walk, every
    entry it covers: a source file's text when it can be shown whole, else why
    not; a compiled file's size; a link's target."""
    keep = []
    digest = fingerprint(folder, keep)
    if len(keep) > SHOW_ENTRIES:
        return digest, None
    files, shown = [], 0
    for entry in keep:
        data = entry.pop("data", None)
        if data is not None:
            entry["bytes"] = len(data)
        if entry["kind"] == "source":
            if data is None:
                entry["unshown"] = "unreadable"
            elif len(data) > SHOW_FILE:
                entry["unshown"] = "too_large"
            else:
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    entry["unshown"] = "not_utf8"
                else:
                    size = len(json.dumps(text))
                    if shown + size > SHOW_ENCODED:
                        entry["unshown"] = "too_large"
                    else:
                        entry["text"] = text
                        shown += size
        files.append(entry)
    return digest, files


def say(answer):
    sys.stdout.write(json.dumps(answer) + "\n")
    sys.stdout.flush()


class Stopped(Exception):
    pass


class Late(Exception):
    pass


def main():
    try:
        job = json.loads(sys.stdin.read() or "null")
    except ValueError:
        job = None
    if not isinstance(job, dict):
        return say({"started": False, "error": "The check was not handed a job."})
    slug, action = job.get("slug"), job.get("action")
    if not isinstance(slug, str) or not SLUG.match(slug):
        return say({"started": False, "error": "That is not a server's folder name."})
    if action not in ("list", "call", "digest", "snapshot"):
        return say({"started": False, "error": "The check was asked to do something it does not do."})
    pin = job.get("pin")
    if pin is not None and (not isinstance(pin, str) or not PIN.match(pin)):
        return say({"started": False, "error": "That is not a fingerprint of a server's code."})
    tool, arguments = job.get("tool"), job.get("arguments")
    if action == "call" and (not isinstance(tool, str) or not tool or len(tool) > 128):
        return say({"started": False, "error": "Say which tool to call."})
    if not isinstance(arguments, dict):
        arguments = {}
    try:
        limit = max(1.0, min(float(job.get("timeout") or 20), 120.0))
    except (TypeError, ValueError):
        limit = 20.0
    folder = os.path.join(os.path.expanduser("~"), FOLDER, slug)
    source = os.path.join(folder, "server.py")
    if not os.path.isfile(source):
        return say({"started": False, "missing": True,
                    "error": "There is no server.py in ~/" + FOLDER + "/" + slug + "."})
    mtime = os.path.getmtime(source)
    if action == "snapshot":
        digest, files = snapshot(folder)
        if files is None:
            return say({"started": False, "digest": digest, "mtime": mtime, "too_many": True})
        return say({"started": False, "digest": digest, "mtime": mtime, "files": files})
    digest = fingerprint(folder)
    if action == "digest":
        return say({"started": False, "digest": digest, "mtime": mtime})
    if pin is not None and pin != digest:
        # Registered with other code than is here now: nothing starts.
        return say({"started": False, "pin_mismatch": True, "digest": digest, "mtime": mtime,
                    "error": "Its code has changed since it was registered."})
    began = time.monotonic()
    # `-B`: nothing this starts writes bytecode into the folder, so the
    # fingerprint above only moves when somebody changes the code.
    child = subprocess.Popen([sys.executable, "-B", "-u", source], cwd=folder, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True)
    lines, err = queue.Queue(), []

    def read_out():
        for raw in iter(child.stdout.readline, b""):
            lines.put(raw)
        lines.put(None)

    def read_err():
        for raw in iter(lambda: child.stderr.read(4096), b""):
            err.append(raw)

    for target in (read_out, read_err):
        threading.Thread(target=target, daemon=True).start()
    deadline = began + limit

    def send(message):
        child.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        child.stdin.flush()

    def wait(ident):
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise Late()
            try:
                raw = lines.get(timeout=left)
            except queue.Empty:
                raise Late()
            if raw is None:
                raise Stopped()
            try:
                message = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("id") == ident:
                return message

    answer = {"started": False}
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "pantheon-workstation-check", "version": "1"}}})
        hello = wait(1)
        if "error" in hello:
            raise Stopped()
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        if action == "list":
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        else:
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                  "params": {"name": tool, "arguments": arguments}})
        reply = wait(2)
        answer = {"started": True}
        if "error" in reply:
            problem = reply.get("error")
            answer["rpc_error"] = str(problem.get("message") if isinstance(problem, dict) else problem)
        elif action == "list":
            found = (reply.get("result") or {}).get("tools")
            answer["tools"] = [t for t in (found if isinstance(found, list) else [])
                               if isinstance(t, dict) and isinstance(t.get("name"), str)][:64]
        else:
            result = reply.get("result") or {}
            parts = []
            for part in result.get("content") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
                elif isinstance(part, dict):
                    parts.append("[" + str(part.get("type") or "content") + "]")
            text = "\n".join(parts)
            answer["text"] = text[:MAX_TEXT]
            answer["text_truncated"] = len(text) > MAX_TEXT
            answer["is_error"] = result.get("isError") is True
    except Stopped:
        answer = {"started": False, "error": "It stopped before it answered."}
    except Late:
        answer = {"started": False, "timed_out": True,
                  "error": "It did not answer within %g seconds." % limit}
    except (BrokenPipeError, OSError):
        answer = {"started": False, "error": "It stopped before it answered."}
    finally:
        try:
            child.stdin.close()
        except OSError:
            pass
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        child.wait()
    time.sleep(0.05)
    answer["stderr"] = b"".join(err).decode("utf-8", "replace")[-TAIL:]
    answer["server_exit"] = child.returncode
    answer["duration_ms"] = int((time.monotonic() - began) * 1000)
    answer["mtime"] = mtime
    answer["digest"] = digest
    say(answer)


main()
'''


class BuildError(ValueError):
    """A refusal a person reads: what is wrong and what would be right."""


# ── who, and whether ──────────────────────────────────────────────────────────

def workstation_why(owner: Optional[str], *, auth_manager: Any = None) -> Optional[str]:
    """`None` when this person may build a server in their workstation, else
    the sentence *Build an MCP server* is greyed with — the same three
    conditions `workstation_for` asks before every call, and the same
    sentences (`OFF_SENTENCE`, `UNCONFIGURED_SENTENCE`, `NOT_PERMITTED_SENTENCE`),
    which is the Code step's rule (`workflow_effects.workstation_why`)."""
    from src.workstation_access import workstation_for
    from src.workstation_client import WorkstationError
    try:
        workstation_for(owner, auth_manager=auth_manager)
    except WorkstationError as exc:
        return exc.message
    return None


async def _station(owner: Optional[str], auth_manager: Any = None):
    """`(client, account)`, with the admin's settings pushed first — the
    daemon enforces what it was last told (`B987`)."""
    from src.workstation_access import sync_config, workstation_for
    client, account = workstation_for(owner, auth_manager=auth_manager)
    await sync_config(client)
    return client, account


def _folder(slug: str) -> str:
    return f"~/{WS_FOLDER}/{slug}"


def _slug(name: Any) -> str:
    from src.mcp_scaffold import ScaffoldError, normalise_server_name
    try:
        return normalise_server_name(name)
    except ScaffoldError as exc:
        raise BuildError(str(exc)) from None


# ── the last check, per person and server ─────────────────────────────────────
#
# What the list says about each server without starting it: `works`, `broken`,
# `changed` (edited since it was last checked) or `never` — one word each
# (`Law 10`). Kept in this process only: after a restart every server reads
# `never` until it is checked again, which is true.
CHECK_WORKS = "works"
CHECK_BROKEN = "broken"
CHECK_CHANGED = "changed"
CHECK_NEVER = "never"
_LAST_CHECK: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _remember(account: str, slug: str, result: Dict[str, Any], mtime: Any) -> None:
    _LAST_CHECK[(account, slug)] = {"at": time.time(), "mtime": mtime,
                                    "started": bool(result.get("started")),
                                    "tools": list(result.get("tools") or [])}


def _checked(account: str, slug: str, mtime: Any) -> Tuple[str, List[str]]:
    seen = _LAST_CHECK.get((account, slug))
    if not seen:
        return CHECK_NEVER, []
    if mtime is not None and seen.get("mtime") is not None and \
            abs(float(mtime) - float(seen["mtime"])) > 1e-6:
        return CHECK_CHANGED, list(seen["tools"])
    return (CHECK_WORKS if seen["started"] else CHECK_BROKEN), list(seen["tools"])


# ── the probe ─────────────────────────────────────────────────────────────────

async def _probe(client, account: str, job: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    """Run `PROBE_HARNESS` once as `account` with `job` on stdin, and read its
    one-line answer. A harness that could not answer (it is always the same
    program, so this is the workstation's trouble) comes back as `started:
    False` with the reason, never as an exception."""
    res = await client.exec(account, PROBE_HARNESS, shell="python",
                            stdin=json.dumps(job), timeout_s=timeout + _EXEC_MARGIN_S)
    lines = [ln for ln in str(res.get("stdout") or "").splitlines() if ln.strip()]
    try:
        answer = json.loads(lines[-1]) if lines else None
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        tail = str(res.get("stderr") or "").strip()[-600:]
        why = ("It ran longer than the workstation allows and was stopped."
               if res.get("timed_out") else "The check could not run in the workstation.")
        return {"started": False, "error": why + (f" {tail}" if tail else ""), "stderr": ""}
    return answer


# ── listing, making, reading, writing ─────────────────────────────────────────

async def ws_list(owner: Optional[str], *, auth_manager: Any = None) -> List[Dict[str, Any]]:
    """`[{name, tools, modified, checked}]` for every `~/mcp-servers/<name>/`
    holding a `server.py`. Nothing is started: `tools` and `checked` are the
    last check's, in this process."""
    from src.workstation_client import WorkstationError
    client, account = await _station(owner, auth_manager)
    try:
        listed = await client.list(account, f"~/{WS_FOLDER}", recursive=True, max_entries=2000)
    except WorkstationError as exc:
        if exc.code == "not_found":
            return []  # nothing built yet: the ordinary first state
        raise
    from src.mcp_scaffold import _NAME_RE
    out: List[Dict[str, Any]] = []
    for entry in listed.get("entries") or []:
        path = str(entry.get("path") or "")
        parts = path.split("/")
        if len(parts) != 2 or parts[1] != SERVER_FILENAME or entry.get("type") != "file":
            continue
        if not _NAME_RE.match(parts[0]):
            continue  # a folder the person made by hand that no door could name
        mtime = entry.get("mtime")
        state, tools = _checked(account, parts[0], mtime)
        out.append({"name": parts[0], "tools": tools, "modified": mtime, "checked": state})
    return sorted(out, key=lambda s: s["name"])


async def ws_create(owner: Optional[str], name: Any, tools: Optional[Sequence[Any]] = None,
                    description: Any = "", *, auth_manager: Any = None) -> Dict[str, Any]:
    """Write `~/mcp-servers/<slug>/{server.py, README.md}` in this person's
    workstation. The name, tools and description pass the CLI's own rules
    (`mcp_scaffold.validated_request`); the source is the one template. Never
    overwrites — the only thing that could destroy is code somebody wrote."""
    from src.mcp_scaffold import (CHECK_HINT_WORKSTATION, ScaffoldError, render_server_py,
                                  render_workstation_readme, validated_request)
    from src.workstation_client import WorkstationError
    try:
        slug, wanted, text = validated_request(name, tools, description)
    except ScaffoldError as exc:
        raise BuildError(str(exc)) from None
    client, account = await _station(owner, auth_manager)
    try:
        listed = await client.list(account, f"~/{WS_FOLDER}")
        taken = {str(e.get("path")) for e in listed.get("entries") or []}
    except WorkstationError as exc:
        if exc.code != "not_found":
            raise
        taken = set()
    if slug in taken:
        raise BuildError(
            f"{slug!r} already exists in your workstation (~/{WS_FOLDER}/{slug}). Nothing was "
            "changed — this never overwrites a server, because the only thing that could "
            "destroy is code you wrote. Pick another name, or open that one.")
    await client.write(account, f"{_folder(slug)}/{SERVER_FILENAME}",
                       render_server_py(slug, wanted, text, check_hint=CHECK_HINT_WORKSTATION))
    registration = ws_registration(owner, slug, await _fingerprint(client, account, slug))
    refusal = agent_refusal(registration)
    await client.write(account, f"{_folder(slug)}/{README_FILENAME}",
                       render_workstation_readme(slug, wanted, text, registration, refusal))
    return {"name": slug, "tools": wanted, "description": text,
            "registration": registration, "agent_refusal": refusal}


async def _fingerprint(client, account: str, slug: str) -> str:
    answer = await _probe(client, account, {"slug": slug, "action": "digest",
                                            "timeout": CHECK_TIMEOUT_S}, CHECK_TIMEOUT_S)
    digest = answer.get("digest")
    if not isinstance(digest, str) or not re.match(_PIN_RE_TEXT, digest):
        raise BuildError(answer.get("error") or f"There is no server called {slug!r} in your "
                                                "workstation.")
    return digest


async def ws_fingerprint(owner: Optional[str], name: Any, *, auth_manager: Any = None) -> str:
    """`integrate-e`. The fingerprint of this server's code as it is now —
    what a registration pins (`PIN_FLAG`). Read by the harness, in the
    author's account, the one place it is computed."""
    slug = _slug(name)
    client, account = await _station(owner, auth_manager)
    return await _fingerprint(client, account, slug)


async def ws_read_source(owner: Optional[str], name: Any, *, auth_manager: Any = None) -> str:
    from src.workstation_client import WorkstationError
    slug = _slug(name)
    client, account = await _station(owner, auth_manager)
    try:
        got = await client.read(account, f"{_folder(slug)}/{SERVER_FILENAME}",
                                max_bytes=MAX_SOURCE_BYTES + 1)
    except WorkstationError as exc:
        if exc.code == "not_found":
            raise BuildError(f"There is no server called {slug!r} in your workstation.") from None
        raise
    data = got.get("data") or b""
    if got.get("truncated") or len(data) > MAX_SOURCE_BYTES:
        raise BuildError(f"{SERVER_FILENAME} is larger than {MAX_SOURCE_BYTES // 1024} KiB, so it "
                         "is not opened here. Edit it in your workstation.")
    return data.decode("utf-8", errors="replace")


async def ws_write_source(owner: Optional[str], name: Any, source: Any, *,
                          auth_manager: Any = None) -> Dict[str, Any]:
    """Replace an existing server's `server.py`. Only an existing one: a new
    server is made by `ws_create`, which is the door with the rules."""
    if not isinstance(source, str) or not source.strip():
        raise BuildError("The source is the text of server.py, and it is empty.")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise BuildError(f"server.py is at most {MAX_SOURCE_BYTES // 1024} KiB here.")
    await ws_read_source(owner, name, auth_manager=auth_manager)  # it exists, and is ours
    slug = _slug(name)
    client, account = await _station(owner, auth_manager)
    await client.write(account, f"{_folder(slug)}/{SERVER_FILENAME}", source)
    return {"saved": True}


# ── checking and trying ───────────────────────────────────────────────────────

def _tool_offer(tool: Dict[str, Any]) -> Dict[str, Any]:
    """One tool as *Try* draws it — with the read/write verdict a registered
    server's row shows (`McpManager.readonly_verdict`, the one place it is
    decided: `P8-48`). Without it the badge fell back to "writes" with a
    sentence about the name that was false for `get_forecast` (measured in the
    drive, 2026-10-02)."""
    from src.mcp_manager import readonly_verdict
    schema = tool.get("inputSchema")
    annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else None
    name = str(tool.get("name"))
    is_readonly, source = readonly_verdict({"name": name, "annotations": annotations})
    return {"name": name,
            "description": str(tool.get("description") or ""),
            "input_schema": schema if isinstance(schema, dict) else {"type": "object"},
            "annotations": annotations, "is_readonly": is_readonly, "readonly_source": source}


def changed_since_registered(slug: str) -> str:
    """What the relay answers for a server whose code moved since an admin
    registered it (`integrate-e`)."""
    return (f"“{slug}” was changed after an admin registered it, so it was not run: the admin "
            f"approved the code as it was then. An admin registers it again to run the new code "
            f"(its author presses Register under Build an MCP server — an admin's own fills the form, "
            f"anyone else's is sent to the admins — then an admin saves it).")


async def ws_verify(owner: Optional[str], name: Any, *, timeout: float = CHECK_TIMEOUT_S,
                    auth_manager: Any = None, pin: Optional[str] = None) -> Dict[str, Any]:
    """Start the server in this person's workstation, complete the handshake,
    list its tools, stop it. `verify_server`'s shape — `{started, tools,
    error}` — plus `offers` (each tool's description and input schema, which
    *Try* builds its form from) and `stderr` (what it printed). Never raises
    for a server that does not work: that is the answer. `pin` — the relay's
    registered fingerprint: code that no longer matches it is not started."""
    slug = _slug(name)
    client, account = await _station(owner, auth_manager)
    job = {"slug": slug, "action": "list", "timeout": timeout}
    if pin is not None:
        job["pin"] = pin
    answer = await _probe(client, account, job, timeout)
    if answer.get("pin_mismatch"):
        return {"started": False, "tools": [], "error": changed_since_registered(slug),
                "offers": [], "stderr": "", "changed_since_registered": True}
    offers = [_tool_offer(t) for t in answer.get("tools") or []] if answer.get("started") else []
    error = answer.get("error") or answer.get("rpc_error")
    if answer.get("started") and answer.get("rpc_error"):
        error = f"It started, and refused to list its tools: {answer['rpc_error']}"
    result = {"started": bool(answer.get("started")) and not answer.get("rpc_error"),
              "tools": sorted(o["name"] for o in offers),
              "error": None if answer.get("started") and not answer.get("rpc_error") else error,
              "offers": offers, "stderr": str(answer.get("stderr") or "")}
    if not answer.get("missing"):
        _remember(account, slug, result, answer.get("mtime"))
    return result


async def ws_try(owner: Optional[str], name: Any, tool: Any, arguments: Any, *,
                 timeout: float = CALL_TIMEOUT_S, auth_manager: Any = None,
                 pin: Optional[str] = None) -> Dict[str, Any]:
    """Call one tool in this person's workstation and hand back what it said,
    in the envelope `POST /api/mcp/servers/{id}/call` answers with — `ok`,
    `stdout`, `stderr`, `exit_code`, `duration_ms`, `timed_out`, `error` — so
    one *Try* panel draws both. The tool's own words are `stdout` (or `stderr`
    when it says it failed, as `McpManager.call_tool` maps `isError`); what the
    server printed while it ran is `printed`."""
    slug = _slug(name)
    if not isinstance(tool, str) or not tool.strip():
        raise BuildError("Say which tool to try.")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise BuildError('The arguments are a JSON object, e.g. {"text": "Oslo"}.')
    try:
        seconds = max(1.0, min(float(timeout), MAX_CALL_TIMEOUT_S))
    except (TypeError, ValueError):
        seconds = CALL_TIMEOUT_S
    client, account = await _station(owner, auth_manager)
    job = {"slug": slug, "action": "call", "tool": tool.strip(), "arguments": arguments,
           "timeout": seconds}
    if pin is not None:
        job["pin"] = pin
    answer = await _probe(client, account, job, seconds)
    if answer.get("pin_mismatch"):
        return {"ok": False, "stdout": "", "stderr": "", "exit_code": 1, "duration_ms": None,
                "timed_out": False, "error": changed_since_registered(slug), "printed": "",
                "changed_since_registered": True}
    printed = str(answer.get("stderr") or "")
    duration = answer.get("duration_ms")
    if not answer.get("started"):
        return {"ok": False, "stdout": "", "stderr": "", "exit_code": 1,
                "duration_ms": duration, "timed_out": bool(answer.get("timed_out")),
                "error": answer.get("error") or "It did not start.", "printed": printed}
    if answer.get("rpc_error"):
        return {"ok": False, "stdout": "", "stderr": str(answer["rpc_error"]), "exit_code": 1,
                "duration_ms": duration, "timed_out": False,
                "error": f"It refused the call: {answer['rpc_error']}", "printed": printed}
    failed = answer.get("is_error") is True
    text = str(answer.get("text") or "")
    return {"ok": not failed, "stdout": "" if failed else text, "stderr": text if failed else "",
            "exit_code": 1 if failed else 0, "duration_ms": duration, "timed_out": False,
            "error": None, "printed": printed,
            "truncated": bool(answer.get("text_truncated"))}


# ── registration: the relay, through the admin route ──────────────────────────

def _owner_word(owner: Optional[str]) -> str:
    """The relay's `--owner`: the Pantheon user the workstation knows this
    person as, or the single-user owner's reserved word — never empty, so the
    form's one-box-per-argument editor has nothing to drop."""
    from src.owner_identity import DEFAULT_LOCAL_OWNER
    from src.workstation_access import workstation_owner
    return workstation_owner(owner) or DEFAULT_LOCAL_OWNER


def ws_registration(owner: Optional[str], name: Any, pin: str) -> Dict[str, Any]:
    """Exactly what `POST /api/mcp/servers` wants for a relayed server — the
    shape `mcp_scaffold.registration_for` returns, so one form fills from
    either. `--owner` is derived from whoever asked, never read from a body:
    a person can only ever hand an admin a registration for their own
    account. `pin` is `ws_fingerprint`'s answer — the code the admin is
    approving (`PIN_FLAG`)."""
    from src.workbench_rooms import ADD_MCP_SERVER_PATH
    if not isinstance(pin, str) or not re.match(_PIN_RE_TEXT, pin):
        raise BuildError("A registration pins the server's code; its fingerprint is missing.")
    slug = _slug(name)
    return {
        "where": f"{ADD_MCP_SERVER_PATH} (administrators only)",
        "route": "POST /api/mcp/servers",
        "name": slug,
        "transport": "stdio",
        "command": sys.executable or "python3",
        "args": [RELAY_PATH, OWNER_FLAG, _owner_word(owner), SERVER_FLAG, slug, PIN_FLAG, pin],
        "env": {},
    }


def relay_target(command: Any, args: Any) -> Optional[Dict[str, str]]:
    """`{owner, server, pin}` when a registration (`mcp_servers.command`/`args`)
    is this relay, else `None` — so a route can ask whether a person's server
    is registered without a second copy of the flags."""
    if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
        return None
    if os.path.basename(args[0]) != os.path.basename(RELAY_PATH):
        return None
    flags = {}
    rest = args[1:]
    for i in range(0, len(rest) - 1, 2):
        flags[rest[i]] = rest[i + 1]
    if OWNER_FLAG not in flags or SERVER_FLAG not in flags:
        return None
    return {"owner": flags[OWNER_FLAG], "server": flags[SERVER_FLAG],
            "pin": flags.get(PIN_FLAG) or ""}


def registered_as(rows: Sequence[Any], owner: Optional[str], name: Any) -> List[Any]:
    """The `mcp_servers` rows that relay to this person's server `name`."""
    slug = _slug(name)
    word = _owner_word(owner)
    out = []
    for row in rows:
        try:
            args = json.loads(getattr(row, "args", None) or "[]")
        except ValueError:
            continue
        target = relay_target(getattr(row, "command", None), args)
        if target and target["owner"] == word and target["server"] == slug:
            out.append(row)
    return out


def agent_refusal(registration: Dict[str, Any]) -> str:
    """Why the assistant cannot register it — asked of the rule itself
    (`mcp_scaffold.refusal_on_the_agent_path`, which asks
    `_validate_mcp_command`), not restated."""
    from src.mcp_scaffold import refusal_on_the_agent_path
    return refusal_on_the_agent_path(registration)


# ── sent for registration (B1130) ─────────────────────────────────────────────
#
# A person who is not an admin sends a build to the admins; an admin sees the
# list, reads the code, and presses Register, which fills the existing Add MCP
# Server form — `POST /api/mcp/servers`, `require_admin`, is still the only way
# a server is registered, and the build stays in its author's workstation.
#
# **The adversary (`Law 17`):** the person's assistant — text it read steering
# it — or the person, sending a build. Its aim: an admin registers something
# other than what the admin was shown. Three ways, each closed here:
#
#   * *another account or another command.* A send carries the server's NAME
#     and nothing else. Whose it is comes from the session (`require_user`),
#     and the fields an admin's form is filled with are computed by Pantheon
#     when the admin asks (`ws_registration`: this install's interpreter, this
#     file, the stored owner and folder) — never stored as text someone sent.
#   * *other code than was shown.* The code an admin reads and the fingerprint
#     the form pins come out of ONE walk of the folder (`PROBE_HARNESS`'s
#     `snapshot`: the same bytes hashed and returned), and are stored together;
#     the admin is shown that stored copy, every file the fingerprint covers —
#     sources whole, compiled files and links named as unreadable. Once
#     registered, the relay runs those bytes or nothing (`PIN_FLAG`). A change
#     since the send is said when the admin opens it.
#   * *code that reads one way and runs another.* A source that cannot be shown
#     whole and plain is not sent: larger than the panel opens, not UTF-8, a
#     coding line naming another codec (Python would decode it otherwise than
#     it is displayed), or a bidirectional control character (text that is
#     drawn in an order other than the one Python reads — CVE-2021-42574).
#
# Only a person sends, and only a person reads the list or takes one off it
# (`routes/mcp/mcp_routes.py`, `request_is_a_person`): the agent's loopback
# carries a token `require_admin` accepts outright, so an assistant could
# otherwise send in its person's name and read everyone's sends.
#
# Residue, said where it is decided: the harness runs in the author's own
# account with that account's Python (`agentd.py` starts `python3 -u`), so
# whatever loads before it there — the account's user site-packages — runs
# first. The pin's own residue (`integrate-e`) is the same fact.

SENT_FILE = "mcp_builds_sent.json"
#: Builds one person may have waiting at once — one entry per server, a send
#: replacing that server's last.
MAX_SENT_PER_PERSON = 20
#: The answer to "is the code there still what was sent?" (`Law 10`).
NOW_AS_SENT, NOW_CHANGED, NOW_UNKNOWN = "as_sent", "changed", "unknown"

_SENT_LOCK = threading.Lock()
_CODING_RE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")
# Explicit embeddings and overrides, isolates, and the marks (U+200E/F, U+061C),
# spelled as escapes: a literal one in this file is what it refuses.
_BIDI = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200e\u200f\u061c")
_UNSHOWN_WORDS = {
    "too_large": "is larger than can be shown to an admin here",
    "not_utf8": "is not UTF-8 text, so it cannot be shown as Python reads it",
    "unreadable": "could not be read",
}


def _sent_path() -> str:
    from src.constants import DATA_DIR
    return os.path.join(DATA_DIR, SENT_FILE)


def _sent_load() -> List[Dict[str, Any]]:
    try:
        with open(_sent_path(), encoding="utf-8") as fh:
            entries = json.load(fh)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        logger.warning("The builds sent for registration could not be read (%s); none are shown.", exc)
        return []
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def _sent_save(entries: List[Dict[str, Any]]) -> None:
    path = _sent_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entries, fh)
    os.replace(tmp, path)


def _shown_files(slug: str, answer: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The snapshot's entries as an admin is shown them, or a refusal saying
    which file cannot be shown and why — nothing is sent that an admin could
    not read in full."""
    if answer.get("too_many"):
        raise BuildError(f"{slug!r} holds more code files and links than can be shown to an "
                         "admin, so it was not sent.")
    files = answer.get("files")
    if not isinstance(files, list):
        raise BuildError(answer.get("error") or "Its code could not be read, so it was not sent.")
    out = []
    for f in files:
        if not isinstance(f, dict) or not isinstance(f.get("path"), str):
            raise BuildError("Its code could not be read, so it was not sent.")
        path, kind = f["path"], f.get("kind")
        if kind == "source":
            unshown = f.get("unshown")
            if unshown or not isinstance(f.get("text"), str):
                raise BuildError(f"{path} {_UNSHOWN_WORDS.get(unshown, 'could not be read')}, so "
                                 "it was not sent: an admin is shown every line before registering it.")
            text = f["text"]
            for line in text.splitlines()[:2]:
                found = _CODING_RE.match(line)
                if found and found.group(1).lower().replace("_", "-") not in (
                        "utf-8", "utf8", "utf-8-sig", "ascii", "us-ascii"):
                    raise BuildError(f"{path} names its own encoding ({found.group(1)}), so Python "
                                     "would not read it as it is shown. It was not sent; take the "
                                     "coding line out.")
            for number, line in enumerate(text.splitlines(), 1):
                if any(ch in _BIDI for ch in line):
                    raise BuildError(f"{path} line {number} holds a character that changes the "
                                     "direction text is drawn in, so it would not read as it runs. "
                                     "It was not sent; take it out.")
            out.append({"path": path, "kind": "source", "bytes": f.get("bytes"),
                        "sha256": f.get("sha256"), "text": text})
        elif kind == "compiled":
            out.append({"path": path, "kind": "compiled", "bytes": f.get("bytes"),
                        "sha256": f.get("sha256")})
        elif kind == "link":
            out.append({"path": path, "kind": "link", "target": str(f.get("target") or "")})
        else:
            raise BuildError("Its code could not be read, so it was not sent.")
    return out


def _sent_summary(entry: Dict[str, Any], *, with_files: bool = False) -> Dict[str, Any]:
    """A stored send as the routes hand it out. `registration` is the admin
    route's fields pinned to the code that was sent, made here by
    `ws_registration` from the stored owner, folder and fingerprint — the one
    place they are made, never text someone sent. Raises `BuildError` for an
    entry it cannot make them from."""
    out = {k: entry.get(k) for k in ("id", "owner", "server", "sent_at", "tools")}
    out["pin"] = entry.get("pin")
    out["registration"] = ws_registration(entry.get("owner"), entry.get("server"), entry.get("pin"))
    files = entry.get("files") or []
    if with_files:
        out["files"] = files
    else:
        out["files"] = [{k: f.get(k) for k in ("path", "kind", "bytes", "target") if k in f}
                        for f in files]
    return out


async def ws_send(owner: Optional[str], name: Any, *, auth_manager: Any = None) -> Dict[str, Any]:
    """Send this person's server to the admins: read its code and fingerprint
    in one walk, start it once against that fingerprint (the tools an admin is
    told about are that code's), and keep the copy. Replaces this server's
    earlier send. Writes nothing in the workstation and registers nothing.
    The route lets only a person call it."""
    slug = _slug(name)
    client, account = await _station(owner, auth_manager)
    answer = await _probe(client, account, {"slug": slug, "action": "snapshot",
                                            "timeout": CHECK_TIMEOUT_S}, CHECK_TIMEOUT_S)
    if answer.get("missing"):
        raise BuildError(f"There is no server called {slug!r} in your workstation.")
    digest = answer.get("digest")
    if not isinstance(digest, str) or not re.match(_PIN_RE_TEXT, digest):
        raise BuildError(answer.get("error") or "Its code could not be read, so it was not sent.")
    files = _shown_files(slug, answer)
    check = await ws_verify(owner, slug, auth_manager=auth_manager, pin=digest)
    if check.get("changed_since_registered"):
        raise BuildError("It changed while it was being sent, so it was not sent. Send it again.")
    if not check["started"]:
        raise BuildError(f"It did not start, so it was not sent: {check['error']}")
    word = _owner_word(owner)
    entry = {"id": uuid.uuid4().hex, "owner": owner, "owner_word": word,
             "server": slug, "pin": digest, "files": files,
             "tools": [{"name": o["name"], "description": o["description"]} for o in check["offers"]],
             "sent_at": time.time()}
    with _SENT_LOCK:
        entries = [e for e in _sent_load()
                   if not (e.get("owner_word") == word and e.get("server") == slug)]
        if sum(1 for e in entries if e.get("owner_word") == word) >= MAX_SENT_PER_PERSON:
            raise BuildError(f"You have {MAX_SENT_PER_PERSON} servers waiting for an admin already. "
                             "Withdraw one, or wait for them to be registered.")
        entries.append(entry)
        _sent_save(entries)
    from src.workbench_rooms import ADD_MCP_SERVER_PATH
    return {**_sent_summary(entry), "where": ADD_MCP_SERVER_PATH}


def _registered_pins(rows: Sequence[Any]) -> Dict[Tuple[str, str], set]:
    pins: Dict[Tuple[str, str], set] = {}
    for row in rows:
        try:
            args = json.loads(getattr(row, "args", None) or "[]")
        except ValueError:
            continue
        target = relay_target(getattr(row, "command", None), args)
        if target:
            pins.setdefault((target["owner"], target["server"]), set()).add(target["pin"])
    return pins


def sent_waiting(rows: Sequence[Any]) -> List[Dict[str, Any]]:
    """The builds waiting for an admin, newest first. One registered with the
    very code that was sent has been handled and leaves the list (and the
    store); one registered before with other code says so (`registered_before`),
    because Register then registers it again rather than adding a second row."""
    pins = _registered_pins(rows)
    with _SENT_LOCK:
        entries = _sent_load()
        kept = [e for e in entries
                if e.get("pin") not in pins.get((e.get("owner_word"), e.get("server")), set())]
        if len(kept) != len(entries):
            _sent_save(kept)
    out = []
    for e in sorted(kept, key=lambda x: x.get("sent_at") or 0, reverse=True):
        try:
            summary = _sent_summary(e)
        except BuildError as exc:
            # Only `ws_send` writes the store; an entry that is not its shape
            # was edited by hand, and is not offered for registration.
            logger.warning("A build sent for registration is unreadable (%s); it is not listed.", exc)
            continue
        summary["registered_before"] = bool(pins.get((e.get("owner_word"), e.get("server"))))
        out.append(summary)
    return out


def sent_mine(owner: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """This person's waiting sends, by server — what their own cards say."""
    word = _owner_word(owner)
    return {e["server"]: {"id": e.get("id"), "sent_at": e.get("sent_at"), "pin": e.get("pin")}
            for e in _sent_load() if e.get("owner_word") == word and isinstance(e.get("server"), str)}


def _sent_entry(sent_id: Any) -> Dict[str, Any]:
    entry = next((e for e in _sent_load() if e.get("id") == sent_id), None) \
        if isinstance(sent_id, str) else None
    if entry is None:
        raise BuildError("That build is not waiting for an admin any more — it was registered, "
                         "withdrawn or sent again.")
    return entry


async def sent_for_admin(sent_id: Any, *, auth_manager: Any = None) -> Dict[str, Any]:
    """One waiting build as an admin reviews it: the code as it was sent, the
    admin route's fields pinned to exactly that code, and whether the code in
    the author's workstation is still it (`now`)."""
    from src.workstation_client import WorkstationError
    entry = _sent_entry(sent_id)
    out = _sent_summary(entry, with_files=True)
    try:
        current = await ws_fingerprint(entry.get("owner"), entry["server"], auth_manager=auth_manager)
    except (WorkstationError, BuildError) as exc:
        out["now"], out["now_why"] = NOW_UNKNOWN, getattr(exc, "message", None) or str(exc)
    else:
        out["now"] = NOW_AS_SENT if current == entry["pin"] else NOW_CHANGED
        out["now_why"] = None
    return out


def sent_remove(sent_id: Any, *, by: Optional[str], is_admin: bool) -> Dict[str, Any]:
    """Take a build off the list: an admin dismissing it, or its sender
    withdrawing it. Nobody else."""
    with _SENT_LOCK:
        entries = _sent_load()
        entry = _sent_entry(sent_id)
        if not is_admin and _owner_word(by) != entry.get("owner_word"):
            raise PermissionError("Only an admin, or the person who sent it, takes it off the list.")
        _sent_save([e for e in entries if e.get("id") != sent_id])
    return {"removed": True, "server": entry.get("server")}


# ── the relay ─────────────────────────────────────────────────────────────────

def _relay_args(argv: Sequence[str]):
    import argparse

    from src.mcp_scaffold import _NAME_RE
    parser = argparse.ArgumentParser(
        prog="workstation_mcp",
        description=("Relay for an MCP server built in a person's Pantheon workstation: each "
                     "tools/list and tools/call runs ~/mcp-servers/<server>/server.py in that "
                     "person's workstation account. Registered by an admin; started by Pantheon."))
    parser.add_argument(OWNER_FLAG, required=True, dest="owner",
                        help="the Pantheon user whose workstation the server lives in")
    parser.add_argument(SERVER_FLAG, required=True, dest="server",
                        help="the folder under ~/mcp-servers/")
    parser.add_argument(PIN_FLAG, required=True, dest="pin",
                        help="the fingerprint of the code an admin registered; other code is not run")
    args = parser.parse_args(list(argv))
    if not re.match(_PIN_RE_TEXT, args.pin or ""):
        parser.error(f"{PIN_FLAG} is the 64-character fingerprint Register shows")
    if not _NAME_RE.match(args.server or ""):
        parser.error(f"{SERVER_FLAG} must be a server's folder name (lowercase letters, digits "
                     "and dashes)")
    if not str(args.owner or "").strip():
        parser.error(f"{OWNER_FLAG} names the person whose workstation it is")
    return args


def _relay_text(result: Dict[str, Any]) -> Tuple[str, bool]:
    if result.get("ok"):
        return str(result.get("stdout") or ""), False
    return str(result.get("stderr") or result.get("error") or "It failed."), True


def build_relay(owner: str, slug: str, pin: str):
    """The relay's SDK server: `tools/list` and `tools/call`, each one probe in
    `owner`'s workstation, each refused unless the code there still has the
    fingerprint the admin registered (`pin`). Built separately from `main` so a
    test can drive it in-process as well as through `McpManager.connect_server`."""
    import mcp.types as types
    from mcp.server.lowlevel import Server

    from src.workstation_client import WorkstationError

    server = Server(f"{slug} (in a workstation)")

    @server.list_tools()
    async def _list_tools() -> List[Any]:
        try:
            found = await ws_verify(owner, slug, pin=pin)
        except WorkstationError as exc:
            raise RuntimeError(exc.message) from None
        if found.get("changed_since_registered"):
            raise RuntimeError(found["error"])
        if not found["started"]:
            raise RuntimeError(f"{slug} did not start in the workstation: {found['error']}")
        return [types.Tool(name=o["name"], description=o["description"],
                           inputSchema=o["input_schema"]) for o in found["offers"]]

    # `validate_input=False`: the server in the workstation enforces its own
    # schema, as every MCP server does (`D-2026-09-27-02`); a second judge
    # here would refuse what the server itself might accept.
    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: Dict[str, Any]):
        try:
            result = await ws_try(owner, slug, name, arguments or {}, pin=pin)
        except WorkstationError as exc:
            result = {"ok": False, "error": exc.message}
        except BuildError as exc:
            result = {"ok": False, "error": str(exc)}
        text, failed = _relay_text(result)
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                    isError=failed)

    return server


async def _serve(owner: str, slug: str, pin: str) -> None:
    from mcp.server.stdio import stdio_server
    server = build_relay(owner, slug, pin)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """The relay's whole body: `python src/workstation_mcp.py --owner <user>
    --server <name> --sha256 <fingerprint>`, started by `McpManager.connect_server` from an admin's
    registration."""
    import asyncio
    args = _relay_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    asyncio.run(_serve(args.owner, args.server, args.pin))
    return 0


__all__ = [
    "BuildError", "CALL_TIMEOUT_S", "CHECK_BROKEN", "CHECK_CHANGED", "CHECK_NEVER",
    "CHECK_TIMEOUT_S", "CHECK_WORKS", "MAX_SOURCE_BYTES", "OWNER_FLAG", "PROBE_HARNESS",
    "PIN_FLAG", "RELAY_PATH", "SERVER_FLAG", "WS_FOLDER", "agent_refusal", "build_relay",
    "changed_since_registered", "main", "registered_as", "relay_target", "workstation_why",
    "ws_create", "ws_fingerprint", "ws_list", "ws_read_source", "ws_registration", "ws_try",
    "ws_verify", "ws_write_source",
    "MAX_SENT_PER_PERSON", "NOW_AS_SENT", "NOW_CHANGED", "NOW_UNKNOWN", "sent_for_admin",
    "sent_mine", "sent_remove",
    "sent_waiting", "ws_send",
]


if __name__ == "__main__":
    sys.exit(main())
