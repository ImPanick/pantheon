# SPDX-License-Identifier: AGPL-3.0-or-later
"""The workstation protocol, version 1 — `P20`, `D-2026-09-30-03`.

One small HTTP contract between Pantheon and the daemon inside a workstation
(`workstation/agentd.py`). It is the only thing either side knows about the
other, which is what lets the same daemon run in the container image, in a VM,
or on any machine an admin points Pantheon at (`P20-07`) without anything above
`src/workstation_client.py` noticing which.

**This file is the single statement of the contract (`Law 7`).** The daemon
imports it; Pantheon's client imports it; the tests import it. It is standard
library only and imports nothing from Pantheon, because the daemon may not
(`netagent`'s rule, enforced by a test for both packages), and a contract the
daemon had to restate would be two contracts.

WIRE RULES
==========

* JSON in, JSON out, UTF-8. Bytes (file content, screenshots) travel as
  base64 in `*_b64` fields.
* Every route except `health` needs ``Authorization: Bearer <token>``. A
  missing or wrong token is `401` with error `unauthorized`, and the answer is
  the same for both so a caller cannot tell which it got wrong.
* An error is a non-2xx status with ``{"error": <code>, "message": <sentence>}``
  where `code` is one of `ERRORS` and `message` is written for a person (it is
  shown in the tool card as it stands, so it names what to do).
* `{account}` in a path is `account_name(owner)` — never a raw Pantheon
  username. The daemon refuses any account that does not match `ACCOUNT_RE`,
  so a path segment cannot name `root`, `../`, or another system user.
* Paths inside requests are relative to the account's home, or absolute. The
  daemon resolves them and refuses one outside the home with
  `outside_home` — unless `sudo` is on for that workstation, when the agent is
  root-equivalent anyway and the jail would be a fiction (the Settings panel
  says so beside the switch).

THE ADVERSARY (`Law 17`)
========================

Content the agent reads tells it to run something. The daemon is the thing it
runs *inside*, so the daemon's job is not to judge commands — it runs what it
is given, as the account it is given — but to make sure the only things a
caller can reach are: that account's home, that account's display, and the
settings Pantheon holds a token for. It holds no Pantheon secret. The token it
checks lets a caller drive the workstation and nothing else.
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, Optional, Tuple

PROTOCOL_VERSION = 1
AGENT_NAME = "pantheon-workstation"

# ── where it listens, and how the two sides pair ──────────────────────────────
DEFAULT_PORT = 7040
# The compose service name. The overlay that starts the workstation also sets
# `URL_ENV` on Pantheon to `http://workstation:7040`, so an admin who switched
# it on has nothing to type — and nothing ships pointing anywhere, because the
# address lives in the overlay they chose to run (`D-2026-08-31-01`).
DEFAULT_HOST = "workstation"
URL_ENV = "PANTHEON_WORKSTATION_URL"
# Zero-config pairing: the daemon writes a token into a volume that only the
# two services mount, and Pantheon reads it from there. The environment
# variable overrides the file on both sides (a remote daemon has no shared
# volume, so its operator sets it).
TOKEN_ENV = "PANTHEON_WORKSTATION_TOKEN"
PAIRING_DIR_ENV = "PANTHEON_WORKSTATION_PAIRING"
DEFAULT_PAIRING_DIR = "/workstation-pairing"
TOKEN_FILENAME = "token"
TOKEN_PREFIX = "pws_"
TOKEN_ENTROPY_BYTES = 32

# ── the routes ────────────────────────────────────────────────────────────────
# name -> (method, path template). Declared, not derived: a client that
# forwards an arbitrary path is a proxy, and the client refuses a name that is
# not in this table.
ROUTES: Dict[str, Tuple[str, str]] = {
    # No token. {"ok", "agent", "protocol", "backend", "version", "sudo",
    #            "network", "screen": [w, h], "accounts": int}
    "health": ("GET", "/v1/health"),
    # Admin settings the daemon enforces itself. Body: any of {"sudo": bool}.
    # Answers the effective settings, the same shape `health` reports them in.
    "config": ("POST", "/v1/config"),
    # Makes the account, its home and its display on first use; a no-op after.
    # {} -> {"account", "home", "display", "created": bool, "sudo": bool,
    #        "screen": [w, h], "holder": "agent"|"person"}
    "ensure": ("POST", "/v1/users/{account}/ensure"),
    # The home back to the image's skeleton, the display restarted.
    # {} -> {"account", "reset": true}
    "reset": ("POST", "/v1/users/{account}/reset"),
    # {"command": str, "shell": "bash"|"python", "cwd": str|None,
    #  "timeout_s": float, "env": {str: str}, "stdin": str|None,
    #  "stream": bool}
    # -> {"stdout", "stderr", "exit_code", "timed_out", "truncated",
    #     "duration_ms", "cwd"}
    # With "stream": true the answer is `application/x-ndjson`: zero or more
    # {"type": "stdout"|"stderr", "data": str} lines, then exactly one
    # {"type": "exit", ...the fields above} line. The final line is the
    # result; the ones before it are progress.
    "exec": ("POST", "/v1/users/{account}/exec"),
    # {"path", "offset": int=0, "max_bytes": int=MAX_FILE_BYTES}
    # -> {"path", "size", "data_b64", "truncated"}
    "read": ("POST", "/v1/users/{account}/files/read"),
    # {"path", "data_b64", "append": bool=False, "make_dirs": bool=True}
    # -> {"path", "size"}
    "write": ("POST", "/v1/users/{account}/files/write"),
    # {"path", "recursive": bool=False, "max_entries": int=MAX_LIST_ENTRIES}
    # -> {"path", "entries": [{"path", "type", "size", "mtime"}], "truncated"}
    # `path` in an entry is relative to the listed directory; `type` is one
    # of ENTRY_TYPES.
    "list": ("POST", "/v1/users/{account}/files/list"),
    # Query: ?format=png|jpeg (default png)
    # -> {"mime", "data_b64", "width", "height", "digest"}
    # `digest` is a hash of the image bytes, so a viewer polling for frames
    # (`P20-05`) can skip one it already has. With ?if_none_match=<digest>
    # and an unchanged screen, the answer is `304` with no body.
    "screenshot": ("GET", "/v1/users/{account}/screenshot"),
    # {"action": one of INPUT_ACTIONS, "x", "y", "to_x", "to_y", "text",
    #  "keys", "dx", "dy", "ms", "holder": "agent"|"person"="agent",
    #  "screenshot_after": bool=False}
    # -> {"ok": true, "action"} (+ "screenshot": {...screenshot answer...}
    #     when asked for, taken after the screen settles)
    # While a person holds the display (`control`), input from the agent is
    # `409 busy`; the person's own input carries "holder": "person".
    "input": ("POST", "/v1/users/{account}/input"),
    # {"holder": "agent"|"person"} -> {"holder", "since"}. GET-less on
    # purpose: the current holder is also in `ensure`'s answer.
    "control": ("POST", "/v1/users/{account}/control"),
}

# ── what the fields may hold ──────────────────────────────────────────────────
SHELLS = ("bash", "python")
ENTRY_TYPES = ("file", "dir", "symlink", "other")
SCREENSHOT_FORMATS = ("png", "jpeg")
HOLDERS = ("agent", "person")
# Every action takes coordinates in the screenshot's own pixels; the screen is
# a fixed size, so there is no scaling for either side to get wrong.
INPUT_ACTIONS = (
    "click",          # x, y
    "double_click",   # x, y
    "triple_click",   # x, y
    "right_click",    # x, y
    "middle_click",   # x, y
    "move",           # x, y
    "drag",           # x, y -> to_x, to_y
    "mouse_down",     # x?, y?
    "mouse_up",       # x?, y?
    "scroll",         # x, y, dx, dy (in wheel clicks; +dy is down)
    "type",           # text
    "key",            # keys, xdotool syntax: "ctrl+l", "Return", "alt+Tab"
    "wait",           # ms
)
BACKENDS = ("container", "vm", "remote")
# `P20-06`. What the admin chose; where it is enforced is that row's subject.
NETWORK_MODES = ("full", "internet", "none")

# ── the bounds, stated once ───────────────────────────────────────────────────
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 800
DEFAULT_EXEC_TIMEOUT_S = 120.0
MAX_EXEC_TIMEOUT_S = 3600.0
# Per stream, in bytes, kept from the END of the output (the end is where the
# error is). The tool layer caps again at `MAX_OUTPUT_CHARS` for the model;
# this bound is what a runaway `yes` cannot exceed on the wire.
MAX_OUTPUT_BYTES = 1_000_000
MAX_FILE_BYTES = 20_000_000
MAX_LIST_ENTRIES = 5_000
# The largest request body the daemon reads: a max-size file in base64, plus
# room for the JSON around it.
MAX_BODY_BYTES = (MAX_FILE_BYTES * 4) // 3 + 64_000
MAX_TYPE_CHARS = 20_000
MAX_WAIT_MS = 30_000

# ── errors ────────────────────────────────────────────────────────────────────
# code -> HTTP status. The client maps each to its own exception text; the
# daemon never invents a code outside this table.
ERRORS: Dict[str, int] = {
    "bad_request": 400,
    "unauthorized": 401,
    "outside_home": 403,
    "not_found": 404,
    "busy": 409,          # a person holds the display (`control`)
    "too_large": 413,
    "unavailable": 503,   # no display, or the account could not be made
    "internal": 500,
}

# ── accounts ──────────────────────────────────────────────────────────────────
ACCOUNT_PREFIX = "pw-"
ACCOUNT_RE = re.compile(r"^pw-[a-z0-9-]{1,20}-[0-9a-f]{8}$")
LOCAL_OWNER_SLUG = "local"


def account_name(owner: Optional[str]) -> str:
    """The Unix account a Pantheon owner works as inside the workstation.

    Readable (the slug of the username, so `ps` in the workstation says whose
    command it is) and unambiguous (the hash of the exact username, so `Ann`
    and `ann`, or two names that slug alike, are never one account). `None`
    and `""` are the single-user owner. Always matches `ACCOUNT_RE`, always
    fits the 32 characters `useradd` allows.
    """
    raw = owner or ""
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:20].strip("-")
    slug = slug or LOCAL_OWNER_SLUG
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{ACCOUNT_PREFIX}{slug}-{digest}"


def route_path(name: str, account: Optional[str] = None) -> Tuple[str, str]:
    """`(method, path)` for a route name, refusing a name not in `ROUTES` and
    an account that does not match `ACCOUNT_RE`."""
    if name not in ROUTES:
        raise KeyError(f"no workstation route named {name!r}")
    method, template = ROUTES[name]
    if "{account}" in template:
        if not account or not ACCOUNT_RE.match(account):
            raise ValueError(f"{account!r} is not a workstation account")
        return method, template.format(account=account)
    return method, template


def error_body(code: str, message: str) -> Dict[str, str]:
    """The one shape an error takes on the wire."""
    if code not in ERRORS:
        code = "internal"
    return {"error": code, "message": message}


__all__ = [
    "ACCOUNT_PREFIX", "ACCOUNT_RE", "AGENT_NAME", "BACKENDS", "DEFAULT_EXEC_TIMEOUT_S",
    "DEFAULT_HOST", "DEFAULT_PAIRING_DIR", "DEFAULT_PORT", "ENTRY_TYPES",
    "ERRORS", "HOLDERS", "INPUT_ACTIONS", "LOCAL_OWNER_SLUG", "MAX_BODY_BYTES",
    "MAX_EXEC_TIMEOUT_S", "MAX_FILE_BYTES", "MAX_LIST_ENTRIES", "MAX_OUTPUT_BYTES",
    "MAX_TYPE_CHARS", "MAX_WAIT_MS", "NETWORK_MODES", "PAIRING_DIR_ENV", "PROTOCOL_VERSION",
    "ROUTES", "SCREEN_HEIGHT", "SCREEN_WIDTH", "SCREENSHOT_FORMATS", "SHELLS", "TOKEN_ENTROPY_BYTES",
    "TOKEN_ENV", "TOKEN_FILENAME", "TOKEN_PREFIX", "URL_ENV", "account_name", "error_body",
    "route_path",
]
