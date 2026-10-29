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
# `B1478`, `D-2026-10-25-04` §3. Both local backends side by side
# (`docker/workstation-both.yml`): the VM backend's address and pairing folder,
# set on Pantheon by that overlay. Which of the two Pantheon talks to is
# Settings → Workstation → Backend.
VM_URL_ENV = "PANTHEON_WORKSTATION_VM_URL"
VM_PAIRING_DIR_ENV = "PANTHEON_WORKSTATION_VM_PAIRING"
TOKEN_FILENAME = "token"
TOKEN_PREFIX = "pws_"
TOKEN_ENTROPY_BYTES = 32

# ── the shared projects folder, `B1417` ───────────────────────────────────────
# Where the folder Pantheon makes projects in is mounted inside the workstation
# (`docker/workstation.yml`: `./data/projects:/projects`), so the agent can run
# and test what it builds in the one place that is safe to run it.
#
# The daemon's jail admits it beside each account's home — and only when it is
# a real directory, so a workstation started without the mount answers exactly
# as it did before. It is one more place an agent may work, never a door to
# anything Pantheon holds: the mount is a subdirectory of Pantheon's data, and a
# subdirectory bind exposes nothing above it.
PROJECTS_DIR = "/projects"
PROJECTS_DIR_ENV = "PANTHEON_WORKSTATION_PROJECTS"
#
# `B1424`. **One folder per person under it, never one folder for everyone.**
# The owner, 2026-10-22: *"per-user scoped and instanced. No overlaps, no shared
# events. Admins should be able to see and access other users' projects."* A
# person's folder is `PROJECTS_DIR/<project_folder(owner)>` in the workstation
# and `<data>/projects/<project_folder(owner)>` on Pantheon — the same name on
# both sides because both read it from here. The jail admits a person's own
# folder; an account the admin list names (`config`'s `admins`) is admitted to
# the whole of `PROJECTS_DIR`. Every command a person runs sees its own folder
# as `$PROJECTS_ENV` — and, in a workstation with nothing mounted there, the
# folder it would be, which is not there (`B1643`: never unset, so a `cd
# "$PANTHEON_PROJECTS"/'<folder>'` fails instead of landing in `/<folder>`).
PROJECTS_ENV = "PANTHEON_PROJECTS"

# ── a workstation on another machine (`P20-07`, added) ────────────────────────
# The token is a bearer secret: whoever reads it off the wire drives every
# person's account, and with `sudo` on (the default) is root there. The
# adversary is anyone on the path between Pantheon and the daemon (`Law 17`).
# So the rule, enforced by the CLIENT — the side that holds the token and
# decides whether to send it:
#
#   * `http://` only to an address that is not globally routable — loopback,
#     the private ranges, link-local, a tailnet's 100.64.0.0/10, IPv6 ULA —
#     and for a name, only when every address it resolves to is one. That is
#     the compose network, a LAN and a VPN: the reach between the operator's
#     own boxes the owner ruled normal (`D-2026-09-01-03`), and the same
#     posture as the network agent (`P17-01`).
#   * Anything else is `https://` or nothing: the client refuses before a
#     byte is sent, with a sentence.
#   * `https://` is verified, never skipped. A certificate a system trust
#     store already accepts (a real one) needs nothing more. A self-signed
#     one — what `workstation/install.py` makes — is trusted by its SHA-256
#     fingerprint in `TLS_PIN_ENV`, compared on the handshake, before the
#     request (and so the token) is written.
TLS_PIN_ENV = "PANTHEON_WORKSTATION_CERT_SHA256"

# ── the routes ────────────────────────────────────────────────────────────────
# name -> (method, path template). Declared, not derived: a client that
# forwards an arbitrary path is a proxy, and the client refuses a name that is
# not in this table.
ROUTES: Dict[str, Tuple[str, str]] = {
    # No token. {"ok", "agent", "protocol", "backend", "version", "sudo",
    #            "network", "screen": [w, h], "accounts": int}
    # `P20-06`, added: "network_in_force" (a mode, or null when nothing here
    # enforces one), "network_enforcement" (one of NETWORK_ENFORCEMENT, for what
    # THIS daemon holds — a gate answers for itself) and
    # "root_can_change_network" (CAP_NET_ADMIN is in this machine's bounding
    # set, so root here could rewrite any rule in its network namespace,
    # including a gate's that it shares).
    # `B1642`, added: "projects_root" — the folder each person's projects
    # folder is in here (`PROJECTS_DIR`, or where `PROJECTS_DIR_ENV` says) —
    # and "projects_mounted" (bool), whether anything is there. A person's
    # folder is "projects_root"/`project_folder(owner)`, mounted or not.
    "health": ("GET", "/v1/health"),
    # Admin settings the daemon enforces itself. Body: any of {"sudo": bool,
    # "network": one of NETWORK_MODES (`P20-06`, added),
    # "admins": [account, ...] — the accounts admitted to every person's
    # projects folder (`B1424`, added)}.
    # Answers the effective settings, the same shape `health` reports them in.
    "config": ("POST", "/v1/config"),
    # Makes the account, its home and its display on first use; a no-op after.
    # {} -> {"account", "home", "display", "created": bool, "sudo": bool,
    #        "screen": [w, h], "holder": "agent"|"person",
    #        "projects": the person's own projects folder or null (`B1424`, added)}
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
    # `B959`, added by `P20-07`: whether this account's home exists, asked
    # WITHOUT making it — every other account route runs `ensure` first, so
    # until this route a panel that only looked made an account (and, on the
    # Ubuntu backend, a Unix user and a desktop). Never `ensure`s, never
    # starts anything. -> {"account", "exists": bool, "home": str|None}
    # A daemon older than this answers `404 not_found`; a caller reads that
    # as "cannot tell", never as "does not exist".
    "account": ("GET", "/v1/users/{account}"),
    # `B984`, added: the machine's clock, so the VM backend's host can keep each
    # of its machines to its own time over the one channel it has to them (no
    # NTP server, no pool — `Law 16`). Needs the token.
    #   {} -> {"time": float}                 this daemon's clock, epoch seconds
    #   {"step_s": float} -> {"time": float}  the clock stepped by that much first
    # Only a daemon started with `--backend vm` — one of the VM host's own
    # machines — steps its clock; any other answers `unavailable`, and a step
    # that is not a finite number of seconds within MAX_CLOCK_STEP_S is
    # `bad_request`.
    "clock": ("POST", "/v1/clock"),
    # `P25-05`, added: the person's own browser — Firefox in this account,
    # driven over WebDriver BiDi (`workstation/browser.py`).
    #   {"action": one of BROWSER_ACTIONS, ...its fields, "holder": "agent"|"person"="agent"}
    #   -> {"ok": true, "action", "url", "title", "tabs": [{"tab", "url", "current"}]}
    #      `read` adds {"text", "cut", "elements": [{"ref", "tag", "label", "type"?, "href"?}]};
    #      `frame` is {"mime", "data_b64", "digest", "width", "height", "url", "title", "tabs",
    #      "activity": [{"id", "seq", "at", "who", "action", "label", "x"?, "y"?,
    #                    "phase": "doing"|"done"|"failed"}], "seq"} — what the browser did
    #      after "since" (`P25-07`, added) — or `304` when "if_none_match" names the frame
    #      the caller has and nothing was done since. Asking for frames is watching: while
    #      someone watches, the agent's hand waits a moment before it acts.
    # While a person holds the screen, the agent's actions are `409 busy`
    # (`input`'s rule: the browser is on that screen). A daemon older than
    # this answers `404 not_found`.
    "browser": ("POST", "/v1/users/{account}/browser"),
    # `P27-04`, added. The account's whole set of names and pinned certificates:
    # {"map": {name: address}, "pins": [{"origin", "pem"}]}
    # -> {"proxy": "http://127.0.0.1:N" | null, "ca_file": path | null, "names": [...],
    #     "pins": int, "digest", "changed": bool}. A change restarts the browser.
    "names": ("POST", "/v1/users/{account}/names"),
    # `P16-20`, added (`D-2026-10-25-02`), trimmed (`D-2026-10-25-03`): what
    # network the workstation is on, and whether it can reach one host
    # (`workstation/netcheck.py`), as the account, within its network mode.
    #   {"action": one of NETWORK_ACTIONS, ...}
    #   interfaces {} -> {"interfaces": [{name, up, addresses:[{ip, cidr, family}]}], "ip_available"}
    #   reach {host, port, timeout_ms?, deny?: [{name, cidrs}]} -> {"host", "address", "port",
    #         "result": "connected"|"refused"|"no answer", "via_gateway", "took_ms"}
    # Which hosts may be reached is Pantheon's, decided before the call
    # (`src/networks.py`): a run's scope, and a network marked untrusted, whose
    # ranges ride along as `deny` and are checked after the name resolves here.
    "network": ("POST", "/v1/users/{account}/network"),
}

# ── what the fields may hold ──────────────────────────────────────────────────
SHELLS = ("bash", "python")
ENTRY_TYPES = ("file", "dir", "symlink", "other")
SCREENSHOT_FORMATS = ("png", "jpeg")
HOLDERS = ("agent", "person")
# `P16-20` / `D-2026-10-25-03`. The network actions (`workstation/netcheck.py`):
# one connection per `reach`, no ranges.
NETWORK_ACTIONS = ("interfaces", "reach")
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
# `P25-05`. What the browser route does (`ROUTES["browser"]`): open a url,
# read the page (its text and numbered elements), click an element by its
# number or a point, type (into an element, and Enter with "submit"), press
# keys, scroll, go back, forward or reload, list tabs, open, switch to or close
# one, and a frame of the page for the person's window.
# `P27-06`, added: `login` {"origins", "label", "username", "secret", "otp"} fills
# the open page's sign-in form from a saved login, refused unless the page's
# origin is one of `origins`; answers {"filled": ["user name", "password", …],
# "still_asking": bool} and never a value. Only Pantheon's server sends it.
BROWSER_ACTIONS = ("open", "read", "click", "type", "press", "scroll", "back", "forward",
                   "reload", "tabs", "tab_new", "tab_switch", "tab_close", "frame", "login",
                   "note_add", "note_edit", "note_remove", "notes", "note_done", "notes_sent",
                   "inspect", "point")
# `P25-10` / `P25-11`, added. inspect {ref | pointed | selector | x, y | nothing: the page}
#   -> {"ok", "action", "title", "url", "element": {tag, selector, role, text, box, styles,
#      on_background, children, href?, src?, alt?, natural?} | "page": {…counted…},
#      "pointed"?, "elsewhere"?}. point {x, y | page: true} (a person's only)
#   -> {"ok", "action", "pointed": {page, url, title, anchor, facts, page_facts, at}, …state}.
#   Any agent action may carry "why": a sentence the window shows (`P25-12`).
# `P26-01` … `P26-03`, added. Notes pinned to the open page's elements:
#   note_add {x, y, text} · note_edit {note, text?, shapes?} · note_remove {note}
#   (a person's only) · notes {all?} · note_done {note | notes, said?, declined?}
#   · notes_sent {notes}. Each answers {"ok", "action", "url", "notes": [{"id", "n",
#   "page", "anchor": {"selector", "tag", "role", "text"}, "at", "text", "shapes",
#   "status": "open"|"sent"|"done"|"declined", "said", "lost"?, "box"?, "where"?}]}.
NOTE_ACTIONS = ("note_add", "note_edit", "note_remove", "notes", "note_done", "notes_sent")
BACKENDS = ("container", "vm", "remote")
# What an admin may choose: a backend, or `auto` — the VM where this install has
# one on KVM, else the container (`D-2026-10-25-04` §4). `auto` is a choice, not
# something a daemon reports; `BACKENDS` stays the daemon's vocabulary.
BACKEND_CHOICES = ("auto",) + BACKENDS
# ── what the machine is (`P20-07`, added) ─────────────────────────────────────
# `health`, for a caller with the token, also answers
#   "machine": {"virtualization": str, "accel": "kvm"|"tcg"|None}
# `virtualization` is systemd-detect-virt's word for what the daemon runs on
# ("none" on bare metal, "kvm", "qemu", "docker", "vmware", …, or "unknown"
# when it cannot be told). For a QEMU guest it is also the speed answer:
# "kvm" is hardware-accelerated and "qemu" is QEMU emulating the CPU in
# software (TCG) — slow, and said rather than left for a person to wonder.
# `accel` restates exactly that in one of `ACCELS`, and is None for anything
# that is not a QEMU guest. The VM backend's host answers "image" there too:
# one of `MACHINE_IMAGE_STATES`, whether the Ubuntu image every person's
# machine starts from is ready (`workstation/vm.py`).
ACCELS = ("kvm", "tcg")
MACHINE_IMAGE_STATES = ("ready", "preparing", "failed")
# `B979`, added. The VM backend's host powers off a machine nobody has used for
# a while and caps how many run (`workstation/vm.py`). Its `health`, for a
# caller with the token, also answers
#   "machines": {"running": int, "max_running": int|None, "idle_stop_s": float|None}
# (None: no cap / never stopped for being unused), and its `account` route adds
#   "machine": one of MACHINE_STATES
# for a person whose machine exists — whether it is up, or powered off with its
# disk kept until their next call boots it. No other backend says either.
MACHINE_STATES = ("running", "stopped")
# `B1661`, added. `health`, for a caller with the token, also answers
#   "run": str
# made when the daemon starts and new at every start. An address is not a
# daemon: one reinstalled or replaced at the address Pantheon knows — or, in a
# test run, started on a port an earlier one freed — is another daemon, with
# its homes where it keeps them. Pantheon remembers an account's home per run
# (`src/agent_tools/workstation_tools._home_path`), not per address.
# `P20-06`. What the admin chose; where it is enforced is that row's subject.
NETWORK_MODES = ("full", "internet", "none")

# ── the network mode in force (`P20-06`, additive) ────────────────────────────
#
# THE ADVERSARY (`Law 17`, named in `D-2026-09-30-03`): content the agent reads
# steers it into running code that reaches devices on the owner's network. With
# `sudo` on (the default) that code is root inside the workstation, so a rule
# root can change is not enforcement. Who holds the mode is therefore reported,
# never assumed — one word, not a pair of booleans (`Law 10`):
#
#   gate      rules in the network namespace's owner: a separate container
#             (`workstation/gate.py`) that the workstation shares a network with
#             and cannot reach into. They hold for every process in the
#             workstation, root included — measured 2026-10-01: root there
#             cannot change them (no CAP_NET_ADMIN) or write around them (no
#             CAP_NET_RAW, which the overlay drops; with it, a raw frame got a
#             SYN-ACK from a blocked LAN host past the rules).
#   accounts  rules the daemon itself holds, for workstation accounts only
#             (`meta skuid` over the account uid range). They hold while `sudo`
#             is off; an account with `sudo` is root and can delete them. What a
#             VM or another machine running `--system ubuntu` can do.
#   none      nothing enforces a mode: the workstation has whatever network its
#             machine gives it.
#   hypervisor  (`B992`, added) the VM backend's host holds it outside each
#             person's machine: QEMU starts the machine's network with
#             `restrict=on`, so nothing it sends is routed out or to the host
#             but the one forwarded port. Root in the machine cannot change it.
#             `none` only — user-mode networking cannot filter by destination,
#             so *internet* on that backend is `accounts`, held in each machine.
NETWORK_ENFORCEMENT = ("gate", "accounts", "none", "hypervisor")

# What *internet* excludes: every address that is not on the public internet —
# private and shared ranges (the LAN, Docker's own networks, CGNAT/Tailscale),
# loopback, link-local (and the 169.254.169.254 metadata service in it),
# documentation and benchmarking ranges, 6to4 (which tunnels to any IPv4 address,
# a LAN one included), multicast and reserved. One list, both sides read it
# (`Law 7`); `tests/test_the_workstation_network_is_the_one_chosen.py` checks it
# covers every range the standard library calls not global, and adds only
# multicast and the deprecated site-local range on top.
# Loopback inside the workstation itself stays open in every mode — a dev server
# on localhost is the workstation talking to itself.
INTERNET_EXCLUDED_V4 = (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
    "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24", "192.168.0.0/16", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/3",
)
INTERNET_EXCLUDED_V6 = (
    "::/127", "::ffff:0:0/96", "64:ff9b:1::/48", "100::/64", "2001::/23", "2001:db8::/32",
    "2002::/16", "3fff::/20", "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8",
)

# The network gate (`workstation/gate.py`): its own port beside the daemon's, in
# the network namespace the two share, and its own token in its own volume —
# one the workstation does not mount, so root in the workstation cannot read it
# and tell the gate to open up. The overlay sets `GATE_URL_ENV` on Pantheon;
# without it there is no gate, and the daemon's own report is all there is.
GATE_AGENT_NAME = "pantheon-workstation-net"
GATE_PORT = 7041
GATE_URL_ENV = "PANTHEON_WORKSTATION_NET_URL"
GATE_PAIRING_DIR_ENV = "PANTHEON_WORKSTATION_NET_PAIRING"
DEFAULT_GATE_PAIRING_DIR = "/workstation-net-pairing"
GATE_ROUTES: Dict[str, Tuple[str, str]] = {
    # No token. {"ok", "agent": GATE_AGENT_NAME, "protocol", "mode",
    #            "enforcement": "gate", "self_test", "applied_at", "refused"}
    # `B1021`, added: "refused" — packets the rules refused since the mode was
    # written (an int, or null when nft cannot be asked).
    # `mode` is read back from the kernel's own table after it was written,
    # not remembered; `self_test` is one of GATE_SELF_TESTS.
    "health": ("GET", "/v1/network"),
    # {"mode": one of NETWORK_MODES} -> the health answer, after the rules are
    # in force. Needs the gate's token.
    "mode": ("POST", "/v1/network"),
}
# `refused`: a connection to a test address the mode excludes (192.0.2.1, a
# documentation address that is never a real host) was refused by the rules
# just written — measured, at the moment they were applied. `not_needed`: the
# mode is `full`, and there is nothing to refuse.
GATE_SELF_TESTS = ("refused", "not_needed")

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
# Wheel clicks per scroll, each way (`B973`, found by `P20-04`: the bound was a
# literal in the daemon, so the tool's schema could not state it).
MAX_SCROLL_CLICKS = 50
MAX_WAIT_MS = 30_000
# `P25-05`. The agent browser's page, in CSS pixels: the screen's size, so a
# frame and a screenshot read the same.
BROWSER_WIDTH = SCREEN_WIDTH
BROWSER_HEIGHT = SCREEN_HEIGHT
# `P20-07`, added. How much longer than its own bound a per-account route may
# take when the backend has to start that person's machine before it can
# answer — the VM backend boots one on first use and after a reset
# (`workstation/vm.py`). A caller waits this long on top before calling the
# workstation down. The VM host itself refuses to wait longer and answers
# `unavailable` with a sentence instead.
MACHINE_START_S = 600.0
# `B984`, added: the largest step a `clock` request may ask for, either way
# (ten years — a machine whose clock is wrong by more was never set at all).
MAX_CLOCK_STEP_S = 10 * 366 * 86400.0

# ── errors ────────────────────────────────────────────────────────────────────
# code -> HTTP status. The client maps each to its own exception text; the
# daemon never invents a code outside this table.
ERRORS: Dict[str, int] = {
    "bad_request": 400,
    "unauthorized": 401,
    "outside_home": 403,
    # `P20-01`, added: the path is inside the home (or the jail is lifted) and
    # the account itself may not touch it — a file it made read-only, a
    # directory it cannot search. Not `outside_home`: that answer would send a
    # person looking for the wrong fix (`Law 10`).
    "forbidden": 403,
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


def project_folder(owner: Optional[str]) -> str:
    """`B1424`. The name of a person's own projects folder — their account
    name without its prefix: readable, and as unambiguous as the account."""
    return account_name(owner)[len(ACCOUNT_PREFIX):]


def project_folder_of(account: str) -> str:
    """The same name, from an account name the daemon was handed."""
    if not ACCOUNT_RE.match(account or ""):
        raise ValueError(f"{account!r} is not a workstation account")
    return account[len(ACCOUNT_PREFIX):]


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
    # `P20-07`, added.
    "ACCELS", "BACKEND_CHOICES", "MACHINE_IMAGE_STATES", "MACHINE_START_S", "TLS_PIN_ENV",
    "VM_PAIRING_DIR_ENV", "VM_URL_ENV",
    # `B979`, added.
    "MACHINE_STATES",
    # `B984`, added.
    "MAX_CLOCK_STEP_S",
    "ACCOUNT_PREFIX", "ACCOUNT_RE", "AGENT_NAME", "BACKENDS", "DEFAULT_EXEC_TIMEOUT_S",
    "DEFAULT_HOST", "DEFAULT_PAIRING_DIR", "DEFAULT_PORT", "ENTRY_TYPES",
    "ERRORS", "HOLDERS", "INPUT_ACTIONS", "LOCAL_OWNER_SLUG", "MAX_BODY_BYTES",
    "MAX_EXEC_TIMEOUT_S", "MAX_FILE_BYTES", "MAX_LIST_ENTRIES", "MAX_OUTPUT_BYTES",
    "MAX_SCROLL_CLICKS", "MAX_TYPE_CHARS", "MAX_WAIT_MS", "NETWORK_ACTIONS", "NETWORK_MODES", "PAIRING_DIR_ENV", "PROTOCOL_VERSION",
    "PROJECTS_DIR", "PROJECTS_DIR_ENV", "PROJECTS_ENV", "ROUTES", "SCREEN_HEIGHT", "SCREEN_WIDTH", "SCREENSHOT_FORMATS", "SHELLS", "TOKEN_ENTROPY_BYTES",
    "TOKEN_ENV", "TOKEN_FILENAME", "TOKEN_PREFIX", "URL_ENV", "account_name", "error_body",
    "project_folder", "project_folder_of",
    "route_path",
    # `P20-06`, added
    "DEFAULT_GATE_PAIRING_DIR", "GATE_AGENT_NAME", "GATE_PAIRING_DIR_ENV", "GATE_PORT",
    "GATE_ROUTES", "GATE_SELF_TESTS", "GATE_URL_ENV", "INTERNET_EXCLUDED_V4",
    "INTERNET_EXCLUDED_V6", "NETWORK_ENFORCEMENT",
]
