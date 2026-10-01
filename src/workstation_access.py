# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who may use the workstation, the one call every tool makes to reach it, and
what the Settings panel is told about it — `P20-02`, `D-2026-09-30-03`.

Three conditions, all of them, in this order, and a sentence for each that
fails — because a tool that silently runs somewhere else is the one outcome
this phase exists to prevent (`P20-03`: *a turn is never silently moved*):

  1. an admin switched the workstation on (`workstation_enabled`);
  2. it has an address (the setting, or the overlay's environment);
  3. the person may use it: auth is off (the single-user owner), or their
     privileges resolve `can_use_workstation` true — which every admin's do,
     because `ADMIN_PRIVILEGES` is every declared privilege (`core/auth.py`).
     One resolver for every privilege (`src.auth_helpers.resolve_privilege`,
     `Law 13`), and no fifth way of asking "is this an admin": the question
     `.pantheon/check-auth-map.py` rule C ratchets. The first version of this
     file asked it through `owner_is_admin_or_single_user` and moved that
     ratchet from 43 to 44; `get_privileges` already answers it.

`routes_tools(owner)` is the question `P20-03` asks before a shell or file tool
runs: is this turn's work done in the workstation? It is the three conditions
plus the admin's `workstation_route_tools` switch.

`ensure_ready(owner)` is what a caller does before it works there: it makes the
person's account (the daemon's `ensure`) and pushes the admin's `sudo` setting
through the protocol's `config` route when the daemon's answer differs. The
daemon enforces `sudo`; Pantheon holds the setting — and a daemon that
restarted has forgotten it, so the comparison is made on every call rather than
remembered.

**ONE PERSON, ONE ACCOUNT, WHATEVER SPELLING ARRIVES.** In no-login mode the
owner reaches here as `None`, `""` or the reserved local bucket
(`src.owner_identity.DEFAULT_LOCAL_OWNER`) depending on which route built it —
`routes/chat_routes.py` alone uses both `effective_user` and
`storage_owner_for_request`. Three spellings would be three workstation homes,
and *Reset my workstation* would reset a different one from the home the
agent's tools write to. `workstation_owner` folds them into one.

**THE TOKEN NEVER LEAVES THE SERVER.** Nothing this module returns carries it:
`settings_view` says whether there is one and which layer it came from, and the
client's error sentences name the variable, never the value.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, NamedTuple, Optional, Tuple
from urllib.parse import urlsplit

from src import workstation_client as wc
from src.workstation_client import WorkstationClient, WorkstationError
from workstation import protocol as P

logger = logging.getLogger(__name__)

PRIVILEGE = "can_use_workstation"

#: Every setting the workstation has, in the order the panel shows them. All
#: admin-only to write, all refused to the agent (`_SELF_RESTRAINT_KEYS`, and
#: the token by its suffix).
SETTING_KEYS = (
    "workstation_enabled",
    "workstation_url",
    "workstation_token",
    "workstation_tls_pin",  # `B980`
    "workstation_backend",
    "workstation_sudo",
    "workstation_network",
    "workstation_route_tools",
)
_BOOL_KEYS = ("workstation_enabled", "workstation_sudo", "workstation_route_tools")
_ENUM_KEYS = {"workstation_backend": P.BACKENDS, "workstation_network": P.NETWORK_MODES}
# It goes in an `Authorization` header, so one line of visible ASCII: a newline
# here would be a header of Pantheon's own making. The daemon mints 47
# characters (`TOKEN_PREFIX` + 32 bytes urlsafe); 512 is room for an operator's
# own scheme and no room for a pasted file.
_TOKEN_RE = re.compile(r"^[\x21-\x7e]{1,512}$")

# ── what the panel is told, as words with one reading each (`Law 10`) ────────
#
# `state` is the verdict for the person asking. `probe` says whether Pantheon
# asked the daemon and whether the answer was usable — separate, because an
# admin's *Check now* probes a workstation that is switched off, and "off" and
# "answers" are both true of it.
STATE_OFF = "off"
STATE_UNCONFIGURED = "unconfigured"
STATE_NOT_PERMITTED = "not_permitted"
STATE_DOWN = "down"
STATE_UP = "up"
STATES = (STATE_OFF, STATE_UNCONFIGURED, STATE_NOT_PERMITTED, STATE_DOWN, STATE_UP)

PROBE_OK = "ok"
PROBE_FAILED = "failed"
PROBE_NOT_CHECKED = "not_checked"

# Whether the person's home was there before this look. `made_now` because the
# only way the protocol can answer "does it exist" is `ensure`, which makes it:
# the answer is honest about having been the thing that made it.
HOME_KEPT = "kept"
HOME_MADE_NOW = "made_now"
HOME_UNKNOWN = "unknown"
# `B959` (`P20-07`). Protocol v1 now answers "does it exist" without making it
# (the `account` route), so the status asks that and makes nothing: `kept` when
# the home is there, `none` when it is not yet — it is made the first time the
# person or their agent works there — and `unknown` from a daemon older than
# the route. `made_now` is no longer said by the status; it stays declared
# because a stored answer or a caller may still carry it (`Law 1`).
HOME_NONE = "none"

OFF_SENTENCE = ("The workstation is switched off. An admin turns it on in "
                "Settings → Workstation.")
# The same state, said to the person who can change it: what off costs.
ADMIN_OFF_SENTENCE = ("The workstation is off. Nothing calls it, and the agent's shell, "
                      "Python and file tools run inside Pantheon as they always have.")
UNCONFIGURED_SENTENCE = ("The workstation is on but has no address. Start it with the "
                         "workstation overlay, or set its address in Settings → Workstation.")
NOT_PERMITTED_SENTENCE = ("Your account may not use the workstation. An admin can allow it "
                          "in Settings → Users.")
UP_SENTENCE = "The workstation is answering."

# `B956`. What undoes root: a new container on the same volumes. Turning `sudo`
# off rewrites the daemon's rule from then on and cannot take back a setuid
# shell, a cron entry or a root process an agent already left outside the
# homes — no daemon can, because the agent had root. Recreating the container
# keeps every home and account, the uid registry and the sudo choice (measured
# in `P20-01`'s end-to-end test). Pantheon holds no Docker socket and cannot
# run it, so the panel shows it to copy. The service name is the protocol's
# (`DEFAULT_HOST`, the compose service the overlay defines), and the overlay is
# switched on through `COMPOSE_FILE`, so the bare command finds it.
RECREATE_COMMAND = f"docker compose up -d --force-recreate {P.DEFAULT_HOST}"

# The status probe is a person waiting on a panel, not a command: a daemon that
# has not answered in this long is down as far as they are concerned. `ensure`
# can make an account and start a display, which is why it is not two seconds.
_STATUS_TIMEOUT_S = 10.0


# ── who ───────────────────────────────────────────────────────────────────────

def workstation_owner(owner: Optional[str]) -> Optional[str]:
    """The owner the workstation knows this person as. `None` is the
    single-user owner: auth switched off, or any spelling of nobody."""
    from src.owner_identity import DEFAULT_LOCAL_OWNER, auth_disabled, normalize_owner
    if auth_disabled():
        return None
    name = normalize_owner(owner)
    if name is None or name.lower() == DEFAULT_LOCAL_OWNER.lower():
        return None
    return name


def account_of(owner: Optional[str]) -> str:
    """The Unix account this person works as (`protocol.account_name`)."""
    return wc.account_for(workstation_owner(owner))


def may_use(owner: Optional[str], *, auth_manager: Any = None) -> bool:
    """The privilege, resolved the way every privilege is.

    `auth_manager` is the app's own when a route asks (`request.app.state`);
    a tool asks without one and gets the manager over the shipped auth file,
    which is what the first version of this function did."""
    try:
        from src.owner_identity import auth_disabled, normalize_owner
        if auth_disabled():
            return True
        name = normalize_owner(owner)
        if not name:
            return False
        if auth_manager is None:
            from core.auth import AuthManager
            auth_manager = AuthManager()
        if not getattr(auth_manager, "is_configured", False):
            # Auth is on and nobody has set it up: nobody is an admin yet, and
            # the workstation is a shell. The same answer the pre-setup window
            # gets from every other server-execution gate.
            return False
        from src.auth_helpers import resolve_privilege
        privs = auth_manager.get_privileges(name) or {}
        return resolve_privilege(privs if isinstance(privs, dict) else {}, PRIVILEGE) is True
    except Exception as e:  # noqa: BLE001 — an unanswerable question is a no
        logger.warning("could not resolve %s for %r: %s", PRIVILEGE, owner, e)
        return False


def workstation_for(owner: Optional[str], *, auth_manager: Any = None
                    ) -> Tuple[WorkstationClient, str]:
    """`(client, account)` for this person, or a `WorkstationError` saying which
    condition failed and who can change it.

    **A caller that reads files or runs commands through the client pushes the
    admin's settings first** — `sync_config(client)`, or `ensure_ready`, which
    does it — because the daemon enforces what it was last *told*: the home
    jail follows `sudo`, the network follows the mode, and a daemon that
    restarted has forgotten both. Nothing here does it for the caller, since
    asking is a round trip and not every caller works there (`B987`). Who does:
    the routed tools (`run_in_workstation`, every call), `computer`
    (`ensure_ready`), the panel (`status_for`) and the workspace picker's two
    routes (`routes/workspace_routes.py`, since `B987`). Who does not, and
    why: the screen window's routes (`P20-05`) — a screenshot, a click and who
    holds the mouse are none of them a file or a command, and neither the jail
    nor the network applies to them — and `vet_workspace`/`describe_workspace`,
    which judge a folder by the home whatever the jail (`B968`)."""
    if not wc.enabled():
        raise WorkstationError("off", OFF_SENTENCE)
    client = wc.from_settings()
    if client is None:
        raise WorkstationError("unconfigured", UNCONFIGURED_SENTENCE)
    if not may_use(owner, auth_manager=auth_manager):
        raise WorkstationError("not_permitted", NOT_PERMITTED_SENTENCE)
    return client, account_of(owner)


def routes_tools(owner: Optional[str], *, auth_manager: Any = None) -> bool:
    """Does this person's shell and file work run in the workstation?

    True when the workstation is on, has an address, the admin has not
    switched routing off, and the person may use it. When the workstation is
    on but DOWN this is still true — the tool then reports it down rather than
    running in Pantheon's container instead."""
    if not route_tools_wanted():
        return False
    return (wc.enabled() and wc.configured_base() is not None
            and may_use(owner, auth_manager=auth_manager))


# ── the admin's settings, read ────────────────────────────────────────────────

def _setting(key: str) -> Any:
    try:
        from src.settings import DEFAULT_SETTINGS, get_setting
        return get_setting(key, DEFAULT_SETTINGS.get(key))
    except Exception:  # noqa: BLE001 — unreadable settings are the shipped defaults
        return _DEFAULTS.get(key)


# The shipped answers, for the one case the settings module cannot be read.
# `src.settings.DEFAULT_SETTINGS` is the source; this is the fallback's copy
# and `tests/test_the_workstation_is_admin_controlled.py` pins the two equal.
_DEFAULTS = {"workstation_sudo": True, "workstation_route_tools": True,
             "workstation_network": "full", "workstation_backend": "container"}


def _bool(key: str) -> bool:
    value = _setting(key)
    return value if isinstance(value, bool) else bool(_DEFAULTS.get(key))


def sudo_wanted() -> bool:
    return _bool("workstation_sudo")


def route_tools_wanted() -> bool:
    return _bool("workstation_route_tools")


def network_setting() -> str:
    value = _setting("workstation_network")
    return value if value in P.NETWORK_MODES else _DEFAULTS["workstation_network"]


def backend_setting() -> str:
    value = _setting("workstation_backend")
    return value if value in P.BACKENDS else _DEFAULTS["workstation_backend"]


def settings_view() -> Dict[str, Any]:
    """What an admin's panel is shown. The token is `token_present` and
    `token_source` — never the value, not even to an admin."""
    base, base_source = wc.resolve_base()
    token, token_source = wc.resolve_token()
    stored_url = _setting("workstation_url")
    pin, pin_source, _raw = wc.resolve_pin()
    stored_pin = _setting("workstation_tls_pin")
    stored_pin = stored_pin if isinstance(stored_pin, str) else ""
    return {
        "enabled": wc.enabled(),
        "url": base or "",
        "url_source": base_source,
        "url_setting": stored_url if isinstance(stored_url, str) else "",
        "token_present": bool(token),
        "token_source": token_source,
        # `B980`. The certificate pinned for an `https://` address: the
        # fingerprint in force as the installer prints it, where it came from,
        # and what is stored here (shown — a certificate's hash is no secret).
        "tls_pin": wc.display_pin(pin),
        "tls_pin_source": pin_source,
        "tls_pin_setting": wc.display_pin(stored_pin) or stored_pin,
        "backend": backend_setting(),
        "sudo": sudo_wanted(),
        "network": network_setting(),
        "route_tools": route_tools_wanted(),
        "backends": list(P.BACKENDS),
        "network_modes": list(P.NETWORK_MODES),
        # `B956`. Shown beside `sudo` when the workstation is the container.
        "recreate_command": RECREATE_COMMAND,
    }


def validate_setting(key: str, value: Any) -> Any:
    """The value to store for one workstation key, or `ValueError` with a
    sentence saying what is wrong and what would be right.

    Refused at the door rather than stored and ignored — `P17-09`'s lesson,
    and `netagent_url`'s check applied to this address: a value the client
    would drop leaves an admin with a configured-looking workstation that
    never answers and nothing saying why. The address is stored as the origin
    the client will actually call, so the stored value and the effective one
    are the same string."""
    if key in _BOOL_KEYS:
        if not isinstance(value, bool):
            raise ValueError(f"{key} is true or false.")
        return value
    if key in _ENUM_KEYS:
        allowed = _ENUM_KEYS[key]
        if not isinstance(value, str) or value.strip().lower() not in allowed:
            raise ValueError(f"{key} is one of: {', '.join(allowed)}.")
        return value.strip().lower()
    if key == "workstation_url":
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("workstation_url is text: an address such as "
                             "http://workstation:7040, or empty.")
        text = value.strip()
        if not text:
            return ""
        origin = wc.parse_base(text)
        try:
            parts = urlsplit(text)
        except ValueError:
            parts = None
        if not origin or parts is None or parts.path not in ("", "/") \
                or parts.query or parts.fragment:
            raise ValueError(
                "workstation_url must be a plain http(s) address such as "
                "http://workstation:7040 — no path, no query string, and no "
                "credentials in it. Leave it empty to use the address the "
                "workstation overlay sets.")
        return origin
    if key == "workstation_token":
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("workstation_token is text, or empty to use the pairing volume.")
        text = value.strip()
        if text and not _TOKEN_RE.match(text):
            raise ValueError("workstation_token is one line of visible characters, at most "
                             "512, with no spaces.")
        return text
    if key == "workstation_tls_pin":
        # `B980`. Stored as the 64 hex digits the client compares, from any
        # spelling `normalise_pin` reads; empty leaves it to the environment.
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("workstation_tls_pin is text: a certificate's SHA-256 "
                             "fingerprint, or empty.")
        text = value.strip()
        if not text:
            return ""
        pin = wc.normalise_pin(text)
        if pin is None:
            raise ValueError(
                "workstation_tls_pin is the SHA-256 fingerprint of the workstation's "
                "certificate — the line workstation/install.py printed, such as AB:CD:…:EF "
                f"(64 hex digits) — or empty to use {P.TLS_PIN_ENV}.")
        return pin
    raise KeyError(key)


# ── the daemon, made ready ────────────────────────────────────────────────────

async def sync_config(client: WorkstationClient) -> Dict[str, Any]:
    """The daemon's health, with its effective settings, after the admin's
    `sudo` has been pushed if it differed.

    This is also the token check, without a call of its own. `health` answers
    anyone and tells only a caller with the token what `sudo` is, so with the
    token missing or refused `sudo` is absent, "absent" differs from the
    admin's `True` or `False`, and the push goes out — to `config`, which needs
    the token and refuses in the client's own sentence saying which of the two
    it was. (The first version asked `config` first as a separate step; the
    mutation run showed the two paths were the same path.)

    `P20-06`: the admin's network mode goes the same way — to the daemon, which
    holds it for accounts where its machine lets it, and to the network gate
    in front of it when the overlay put one there (`wc.gate_for`), whose answer
    rides back as `network_gate`. A gate that is there and does not take the
    mode is an error, like a refused `sudo`: every tool call comes through
    here, and a command must not run under a wider network than the admin set
    because the gate was not listening.

    `B978`: when nothing answers at the workstation's address and the gate in
    front of it does, the sentence says the one thing that brings it back
    (`GATE_UP_SENTENCE`) instead of asking whether it is running."""
    try:
        daemon = await client.health()
    except wc.WorkstationUnreachable as e:
        if not await _gate_answers(client):
            raise
        raise WorkstationError("unavailable", GATE_UP_SENTENCE) from e
    want = sudo_wanted()
    if daemon.get("sudo") is not want:
        daemon.update(await client.config(sudo=want))
    mode = network_setting()
    if daemon.get("network") != mode:
        daemon.update(await client.config(network=mode))
    gate = wc.gate_for(client)
    if gate is not None:
        held = await gate.health()
        if held.get("mode") != mode:
            held = await gate.set_mode(mode)
        daemon["network_gate"] = held
    return daemon


# `B978`. The workstation runs in its network gate's namespace (`P20-06`), and
# a gate that is *recreated* takes that namespace with it: the workstation exits
# (its namespace watch) and cannot restart into a container that no longer
# exists, so it stays down until compose recreates it — measured 2026-10-01,
# `docker compose up -d --force-recreate workstation-net`, and `docker compose up
# -d` brought it back. Fail-closed, as it should be. The gate still answers at
# the same address (it owns the name), which is how this case is told apart
# from a workstation that is simply not there. A plain gate *restart* heals
# itself within its restart policy and may show this for those seconds; the
# command is harmless then. Pantheon holds no Docker socket, so it is said, not done.
GATE_UP_SENTENCE = ("The workstation's network gate is running and the workstation is not. "
                    "Run docker compose up -d where you start Pantheon to bring it back.")


async def _gate_answers(client: WorkstationClient) -> bool:
    """Whether the network gate in front of `client`'s workstation answers its
    open `health` — asked only once the workstation itself did not answer."""
    gate = wc.gate_for(client)
    if gate is None:
        return False
    try:
        await gate.health()
    except WorkstationError:
        return False
    return True


# ── the network mode, as it is (`P20-06`) ─────────────────────────────────────
#
# One word for the panel (`Law 10`), worked out here so the browser only says
# it. The admin's choice, what is in force, who holds it and whether root in the
# workstation can lift it — and the remedy is part of the word, because "not
# enforced" on a container that only needs recreating and on a machine that can
# never enforce one are different things to do.
NETWORK_UNRESTRICTED = "unrestricted"      # full chosen; nothing narrower in force
NETWORK_ENFORCED = "enforced"              # held by the gate: root included
NETWORK_ENFORCED_SUDO_OFF = "enforced_sudo_off"  # held for accounts; sudo is off
NETWORK_LIFTABLE = "liftable"              # held for accounts; sudo is on
NETWORK_NEEDS_RECREATE = "needs_recreate"  # a container started without its gate
NETWORK_NOT_ENFORCED = "not_enforced"      # a machine that holds no mode
NETWORK_PENDING = "pending"                # a mode is held, and it is not the chosen one
NETWORK_UNKNOWN = "unknown"                # not asked, or it did not answer
NETWORK_STATES = (NETWORK_UNRESTRICTED, NETWORK_ENFORCED, NETWORK_ENFORCED_SUDO_OFF,
                  NETWORK_LIFTABLE, NETWORK_NEEDS_RECREATE, NETWORK_NOT_ENFORCED,
                  NETWORK_PENDING, NETWORK_UNKNOWN)


def network_view(chosen: str, daemon: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """`{"chosen", "in_force", "enforcement", "state"}` from one synced daemon
    answer (`sync_config`'s), or `unknown` without one."""
    out: Dict[str, Any] = {"chosen": chosen, "in_force": None, "enforcement": None,
                           "state": NETWORK_UNKNOWN}
    if not daemon:
        return out
    gate = daemon.get("network_gate")
    root_can = daemon.get("root_can_change_network") is True
    if isinstance(gate, dict):
        # The gate's rules sit in a namespace the workstation shares: they hold
        # against its root only while that root cannot rewrite them.
        in_force, by, holds_against_root = gate.get("mode"), "gate", not root_can
    elif daemon.get("network_enforcement") == "accounts":
        in_force, by, holds_against_root = daemon.get("network_in_force"), "accounts", False
    elif daemon.get("network_enforcement") == "hypervisor":
        # `B992`: the VM backend's host, outside every machine (`restrict=on`).
        in_force, by, holds_against_root = daemon.get("network_in_force"), "hypervisor", True
    else:
        in_force, by, holds_against_root = None, "none", False
    out.update(in_force=in_force if in_force in P.NETWORK_MODES else None, enforcement=by)
    if chosen == "full" and out["in_force"] in (None, "full"):
        state = NETWORK_UNRESTRICTED
    elif by == "none":
        state = (NETWORK_NEEDS_RECREATE if daemon.get("backend") == "container"
                 else NETWORK_NOT_ENFORCED)
    elif out["in_force"] != chosen:
        state = NETWORK_PENDING
    elif holds_against_root:
        state = NETWORK_ENFORCED
    else:
        sudo = daemon.get("sudo")
        state = NETWORK_ENFORCED_SUDO_OFF if sudo is False else NETWORK_LIFTABLE
    out["state"] = state
    return out


def network_held(daemon: Optional[Dict[str, Any]]) -> Optional[str]:
    """`B977`: the mode actually holding this workstation's commands, from one
    synced answer — the gate's rules or the daemon's own — or None when
    nothing holds one (no gate on a container, a machine that cannot, nobody
    asked). What a refused connection is explained by, so never the setting
    alone: a mode that is chosen and not held refuses nothing."""
    view = network_view(network_setting(), daemon)
    return view["in_force"] if view["enforcement"] in ("gate", "accounts") else None


class Ready(NamedTuple):
    client: WorkstationClient
    account: str
    daemon: Dict[str, Any]
    home: Dict[str, Any]


async def ensure_ready(owner: Optional[str], *, auth_manager: Any = None) -> Ready:
    """The workstation, ready for this person: the three conditions, the
    admin's `sudo` in force on the daemon, and the person's account made.
    Raises `WorkstationError` — a sentence — for anything that stops that."""
    client, account = workstation_for(owner, auth_manager=auth_manager)
    daemon = await sync_config(client)
    home = await client.ensure(account)
    return Ready(client, account, daemon, home)


async def reset_home(owner: Optional[str], *, auth_manager: Any = None) -> Dict[str, Any]:
    """This person's home back to the image's, and nobody else's. There is no
    parameter naming whose: the account is derived from the caller."""
    client, account = workstation_for(owner, auth_manager=auth_manager)
    # Asked first, so a reset aimed at something that is not a workstation — a
    # router's admin page on the configured port — is refused in a sentence
    # that says so, rather than "the workstation answered 501".
    await client.health()
    return await client.reset(account)


def _daemon_view(daemon: Dict[str, Any]) -> Dict[str, Any]:
    """The daemon's own answer, in the fields the panel shows."""
    keep = ("agent", "protocol", "backend", "version", "sudo", "network", "screen", "accounts",
            "machine",   # `P20-07`: what it runs on, and for a VM whether it is emulated
            "machines")  # `B979`: on the VM backend, how many run and when one stops
    return {k: daemon.get(k) for k in keep if k in daemon}


async def status_for(owner: Optional[str], *, is_admin: bool, auth_manager: Any = None,
                     probe_when_off: bool = False) -> Dict[str, Any]:
    """Everything the Settings panel says, for the person asking.

    A person without the privilege learns whether it is on and that they may
    not use it, and nothing is probed on their behalf. An admin also gets
    `settings` (`settings_view`, no token). `probe_when_off` is the admin's
    *Check now*: it asks a workstation that is switched off whether it would
    answer, so an admin can start the overlay, check, and then turn it on."""
    enabled = wc.enabled()
    base, _source = wc.resolve_base()
    permitted = may_use(owner, auth_manager=auth_manager)
    out: Dict[str, Any] = {
        "enabled": enabled,
        "is_admin": bool(is_admin),
        "may_use": permitted,
        "state": STATE_OFF,
        "sentence": OFF_SENTENCE,
        "probe": PROBE_NOT_CHECKED,
        "daemon": None,
        "error": None,
        "you": None,
        "checked_at": time.time(),
        # `P20-06`: replaced by what the daemon said once it answers. Nothing
        # for a person who may not use it — the admin's choice is not theirs.
        "network": network_view(network_setting(), None) if (permitted or is_admin) else None,
    }
    if is_admin:
        out["settings"] = settings_view()
    if permitted:
        out["you"] = {"account": account_of(owner), "home": None, "home_state": HOME_UNKNOWN}

    if not enabled and is_admin:
        out["sentence"] = ADMIN_OFF_SENTENCE
    if not enabled and not (probe_when_off and is_admin and base):
        return out
    if not permitted and not is_admin:
        out.update(state=STATE_NOT_PERMITTED, sentence=NOT_PERMITTED_SENTENCE)
        return out
    if not base:
        out.update(state=STATE_UNCONFIGURED, sentence=UNCONFIGURED_SENTENCE)
        return out

    client = WorkstationClient(base, wc.configured_token(), timeout=_STATUS_TIMEOUT_S)
    try:
        daemon = await sync_config(client)
        out["daemon"] = _daemon_view(daemon)
        out["network"] = network_view(network_setting(), daemon)
        if enabled and permitted:
            # `B959`: looked at, not made — opening the panel makes no account.
            seen = await client.account(out["you"]["account"])
            exists = seen.get("exists")
            out["you"].update(home=seen.get("home") if exists else None,
                              home_state=(HOME_KEPT if exists is True else HOME_NONE
                                          if exists is False else HOME_UNKNOWN))
            if seen.get("machine") in P.MACHINE_STATES:
                # `B979`: on the VM backend, whether the person's machine is up
                # or powered off until their next call — looked at, not booted.
                out["you"]["machine"] = seen["machine"]
    except WorkstationError as e:
        out.update(probe=PROBE_FAILED, error={"code": e.code, "message": e.message})
        if enabled:
            out.update(state=STATE_DOWN, sentence=e.message)
        return out
    out["probe"] = PROBE_OK
    if enabled:
        out.update(state=STATE_UP, sentence=UP_SENTENCE)
    return out


__all__ = [
    "ADMIN_OFF_SENTENCE", "HOME_KEPT", "HOME_MADE_NOW", "HOME_NONE", "HOME_UNKNOWN",
    "NOT_PERMITTED_SENTENCE", "OFF_SENTENCE",
    "PRIVILEGE", "PROBE_FAILED", "PROBE_NOT_CHECKED", "PROBE_OK", "RECREATE_COMMAND", "Ready",
    "SETTING_KEYS",
    "STATES", "STATE_DOWN", "STATE_NOT_PERMITTED", "STATE_OFF", "STATE_UNCONFIGURED",
    "STATE_UP", "UNCONFIGURED_SENTENCE", "UP_SENTENCE", "account_of", "backend_setting",
    "ensure_ready", "may_use", "network_setting", "reset_home", "route_tools_wanted",
    "routes_tools", "settings_view", "status_for", "sudo_wanted", "sync_config",
    "validate_setting", "workstation_for", "workstation_owner",
    # `P20-06`
    "NETWORK_ENFORCED", "NETWORK_ENFORCED_SUDO_OFF", "NETWORK_LIFTABLE", "NETWORK_NEEDS_RECREATE",
    "NETWORK_NOT_ENFORCED", "NETWORK_PENDING", "NETWORK_STATES", "NETWORK_UNKNOWN",
    "NETWORK_UNRESTRICTED", "network_view",
    # `B977`, `B978`
    "GATE_UP_SENTENCE", "network_held",
]
