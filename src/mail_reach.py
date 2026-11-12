# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which mail servers a mail account may connect to — `B2102`.

The account form's Test, every saved account's inbox check and send, and the
agent's mail tools connect to an IMAP or SMTP host and port a person typed.
Until `B2102` any member could type `127.0.0.1` and a port, or an address on
the LAN, and tell an open port from a closed one by the answer: `B2032` took
the banner out of it and `B1921` took the wait, but *refused*, *timed out* and
*did not answer like an IMAP server* still differ. The owner's ruling: fix it.

**Who the adversary is** (`Law 17`): a member who can sign in and type a host.
Not an admin, who already holds the shell, and not the agent, which never
chooses an account's host — it connects to accounts people saved.

**What a mail account may reach.** One question, `reach_for(*owners)`, asked of
everyone a connection is made for — the account's owner and the person asking —
and the narrowest answer wins:

* **never, for anyone:** link-local (`169.254/16`, `fe80::/10`), the cloud
  metadata hosts (`outbound_fetch.CLOUD_METADATA_NETWORKS`, `B1924`'s one list,
  and the `metadata` names), multicast, reserved, unspecified and `0/8` — the
  addresses `outbound_fetch._always_blocked` refuses every fetch, loopback aside;
* **only with `can_reach_private_mail`** (`core/auth.py`; every admin holds it,
  and an admin may grant it to a member in Settings → Users): the private
  ranges (RFC 1918, Tailscale's CGNAT `100.64/10`, ULA `fc00::/7`,
  `outbound_fetch`'s `_LAN_NETWORKS` plus whatever CPython calls private), and
  any port;
* **only for an admin:** this machine — loopback and every address this host
  answers on. The grant was the key to both until the 2026-11-11 audit, so a
  member granted it for the house mail server could aim an account at
  `127.0.0.1` on any port: Pantheon's own database, model servers, the
  Android worker. An admin already holds the shell;
* **everyone else:** a public address, on a mail port (`MAIL_PORTS`).

An account nobody owns (`owner` empty: a row from before accounts had owners,
or the `IMAP_HOST` / `settings.json` mailbox) is the install's own and asks
nothing — but whoever asks for it is asked, so a member reaching a legacy row
through its mailbox gets a member's reach.

**Resolve once, check every address, connect to the address checked.** `dial`
resolves the name once, refuses the whole host when ANY address it resolved to
is refused, and connects to the checked addresses as literals, so a name that
answers a public address to the check and `127.0.0.1` to the connect (DNS
rebinding) is never connected to the second. The name stays what TLS sees:
`pinned` hands imaplib and smtplib a socket for the address and leaves
`self.host` / `self._host` the typed name, which both libraries pass as
`server_hostname` (SNI and the authority check), and `src/mail_tls.py` decides
pinning from the typed name as it always has (`B2096`).

**One sentence for a refused host** (`REFUSED_SENTENCE`), whatever listens
there, because nothing is connected to: the refusal comes before the socket.

This module decides reach and nothing else; certificates stay with
`src/mail_tls.py`, sign-in with `src/mail_auth.py`, ports' TLS with each caller.
"""
from __future__ import annotations

import functools
import imaplib
import ipaddress
import logging
import smtplib
import socket
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from src.outbound_fetch import CLOUD_METADATA_NETWORKS, _always_blocked, _in_lan

logger = logging.getLogger(__name__)

#: The privilege that opens this machine, the private ranges and any port.
#: Declared in `core/auth.py`'s `DEFAULT_PRIVILEGES` (off; admins hold it).
PRIVILEGE = "can_reach_private_mail"

#: IMAP (143 STARTTLS, 993 implicit TLS) and SMTP (25 relay, 465 implicit TLS,
#: 587 submission). Pantheon speaks no POP.
MAIL_PORTS = frozenset({25, 143, 465, 587, 993})

#: The one answer for a host or port a mail account may not reach. Fixed, with
#: nothing in it from the host, the port or the reason, so it reads the same
#: whatever does or does not listen there.
REFUSED_SENTENCE = (
    "Pantheon will not connect this mail account to that server. A mail account "
    "reaches a public mail server on a mail port (143, 993, 25, 465 or 587); a "
    "server on this machine or a private network, or another port, only where an "
    "admin has allowed it."
)

#: Names refused before any lookup, whoever asks.
_METADATA_NAMES = frozenset({"metadata", "metadata.google.internal"})
#: Names that are this machine without a lookup.
_LOOPBACK_NAMES = frozenset({"localhost", "ip6-localhost", "ip6-loopback"})

#: NAT64's well-known prefix (RFC 6052): the last 32 bits are an IPv4 address.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class MailHostRefused(OSError):
    """A mail host or port this account may not reach. Nothing was connected to.

    An `OSError`, so every handler that catches a failed mail connection
    catches this one; `str()` is `REFUSED_SENTENCE` and nothing else. `why`
    is for the log, never for the person.
    """

    def __init__(self, host: str = "", port=None, why: str = "") -> None:
        super().__init__(REFUSED_SENTENCE)
        self.host = host or ""
        self.port = port
        self.why = why

    def __str__(self) -> str:
        return REFUSED_SENTENCE


@dataclass(frozen=True)
class Reach:
    """What a connection may reach. `private`: the private ranges and any
    port; without it, public addresses on `MAIL_PORTS`. `machine`: this
    machine too (loopback and this host's own addresses), only with
    `private`."""
    private: bool = False
    machine: bool = False


MEMBER = Reach(private=False)
#: A member an admin granted `PRIVILEGE` to.
LAN = Reach(private=True, machine=False)
#: An admin, or the install's own account.
PRIVATE = Reach(private=True, machine=True)


# ---------------------------------------------------------------------------
# Who may reach what
# ---------------------------------------------------------------------------

def _holds(owner: str) -> bool:
    """`owner` holds `PRIVILEGE`, resolved the way every privilege is
    (`src.auth_helpers.resolve_privilege`), as `workstation_access.may_use`
    asks it. An unanswerable question is a no."""
    try:
        from src.auth_manager_access import shared_auth_manager
        auth = shared_auth_manager()
        if not getattr(auth, "is_configured", False):
            return False
        from src.auth_helpers import resolve_privilege
        privs = auth.get_privileges(owner) or {}
        return resolve_privilege(privs if isinstance(privs, dict) else {}, PRIVILEGE) is True
    except Exception as exc:  # noqa: BLE001 — a no, said in the log
        logger.warning("could not resolve %s for %r: %s", PRIVILEGE, owner, exc)
        return False


def _is_admin(owner: str) -> bool:
    """`owner` is an admin (`src.tool_security.owner_is_admin`, which answers
    no for anything it cannot answer)."""
    from src.tool_security import owner_is_admin
    return owner_is_admin(owner)


def reach_for(*owners: Optional[str]) -> Reach:
    """The narrowest reach of everyone named: an account's owner and whoever
    asks for it. An empty name is the install's own account and narrows
    nothing; any named person without `PRIVILEGE` makes it `MEMBER`, and any
    who holds it but is not an admin makes it `LAN`."""
    reach = PRIVATE
    for owner in owners:
        name = str(owner or "").strip()
        if not name:
            continue
        if not _holds(name):
            return MEMBER
        if not _is_admin(name):
            reach = LAN
    return reach


# ---------------------------------------------------------------------------
# What an address is
# ---------------------------------------------------------------------------

_NEVER, _MACHINE, _PRIVATE, _PUBLIC = 3, 2, 1, 0


def _embedded(addr: ipaddress._BaseAddress) -> List[ipaddress._BaseAddress]:
    """`addr`, and any IPv4 address it carries (mapped, 6to4, Teredo, NAT64),
    each judged, the strictest answer winning."""
    out = [addr]
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            out.append(addr.ipv4_mapped)
        if addr.sixtofour is not None:
            out.append(addr.sixtofour)
        if addr.teredo is not None:
            out.extend(addr.teredo)
        if addr in _NAT64:
            out.append(ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF))
    return out


def _kind_of_one(addr: ipaddress._BaseAddress) -> int:
    if addr.is_loopback:
        return _MACHINE
    if _always_blocked(addr):   # link-local, metadata, multicast, reserved, unspecified, 0/8
        return _NEVER
    if _in_lan(addr) or addr.is_private:
        return _PRIVATE
    return _PUBLIC


def _kind(addr: ipaddress._BaseAddress) -> int:
    return max(_kind_of_one(a) for a in _embedded(addr))


_HOST_ADDRESSES: dict = {"at": 0.0, "set": frozenset()}
_HOST_ADDRESSES_TTL = 60.0
_HOST_ADDRESSES_LOCK = threading.Lock()


def _host_addresses() -> frozenset:
    """Every address this host answers on (`netagent.observe._addresses`, the
    one place that lists them), cached for a minute."""
    now = time.monotonic()
    with _HOST_ADDRESSES_LOCK:
        if now - _HOST_ADDRESSES["at"] < _HOST_ADDRESSES_TTL:
            return _HOST_ADDRESSES["set"]
    found = set()
    try:
        from netagent.observe import _addresses
        for raw in _addresses():
            try:
                found.add(ipaddress.ip_address(str(raw).split("%", 1)[0]))
            except ValueError:
                continue
    except Exception:  # noqa: BLE001 — a host that cannot list itself keeps loopback's refusal
        logger.debug("could not list this host's addresses", exc_info=True)
    value = frozenset(found)
    with _HOST_ADDRESSES_LOCK:
        _HOST_ADDRESSES.update(at=now, set=value)
    return value


def _is_this_host(addr: ipaddress._BaseAddress) -> bool:
    mine = _host_addresses()
    return any(a in mine for a in _embedded(addr))


def _address_refusal(addr: ipaddress._BaseAddress, reach: Reach) -> Optional[str]:
    """Why `addr` is refused under `reach` (for the log), or None."""
    kind = _kind(addr)
    if kind == _NEVER:
        return f"{addr} is never reached (link-local, metadata, multicast or reserved)"
    if reach.machine:
        return None
    if kind == _MACHINE:
        return f"{addr} is this machine"
    if _is_this_host(addr):
        return f"{addr} is one of this machine's own addresses"
    if reach.private:
        return None
    if kind == _PRIVATE:
        return f"{addr} is on a private network"
    return None


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def _port(port) -> int:
    try:
        number = int(port)
    except (TypeError, ValueError, OverflowError):
        return 0
    return number if 1 <= number <= 65535 else 0


def _name(host) -> str:
    name = str(host or "").strip().rstrip(".").lower()
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    return name


def _literal(name: str) -> Optional[ipaddress._BaseAddress]:
    try:
        return ipaddress.ip_address(name.split("%", 1)[0])
    except ValueError:
        return None


def _typed_refusal(host, port, reach: Reach) -> Tuple[str, int, Optional[str]]:
    """The checks that need no lookup: the port, the names that are this
    machine or a metadata service, and an address typed as one."""
    name, number = _name(host), _port(port)
    if not name:
        return name, number, "no host"
    if not number:
        return name, number, f"port {port!r} is not a port"
    if not reach.private and number not in MAIL_PORTS:
        return name, number, f"port {number} is not a mail port"
    if name in _METADATA_NAMES:
        return name, number, f"{name} is a cloud metadata name"
    if not reach.machine and (name in _LOOPBACK_NAMES or name.endswith(".localhost")):
        return name, number, f"{name} is this machine"
    addr = _literal(name)
    if addr is not None:
        return name, number, _address_refusal(addr, reach)
    return name, number, None


def refusal(host, port, reach: Reach) -> Optional[str]:
    """`REFUSED_SENTENCE` when `host:port`, as typed, is refused under `reach`,
    else None. No lookup: what an account save asks before it stores a host.
    A name is judged by what it resolves to when it is connected to (`dial`)."""
    name, number, why = _typed_refusal(host, port, reach)
    if why:
        logger.info("mail host %s:%s refused as typed: %s", name, number or port, why)
        return REFUSED_SENTENCE
    return None


def check(host, port, reach: Reach) -> List[Tuple[int, tuple]]:
    """Resolve `host` once and return the `(family, sockaddr)` pairs a
    connection may use. Raises `MailHostRefused` when the port or any address
    the name resolved to is refused, and `socket.gaierror` when it does not
    resolve (that sentence names the host and says nothing of a port)."""
    name, number, why = _typed_refusal(host, port, reach)
    if why:
        logger.info("mail host %s:%s refused: %s", name, number or port, why)
        raise MailHostRefused(name, number or port, why)
    infos = socket.getaddrinfo(name.split("%", 1)[0] if _literal(name) else name,
                               number, 0, socket.SOCK_STREAM)
    picked: List[Tuple[int, tuple]] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        addr = _literal(str(sockaddr[0]))
        if addr is None:
            continue
        why = _address_refusal(addr, reach)
        if why:
            # One refused address refuses the name: a host that answers both a
            # public and a private address is a host that can be steered.
            logger.info("mail host %s:%s refused: %s", name, number, why)
            raise MailHostRefused(name, number, why)
        if (family, sockaddr) not in picked:
            picked.append((family, sockaddr))
    if not picked:
        raise socket.gaierror(socket.EAI_NONAME, f"No address was found for {name}")
    return picked


def dial(host, port, timeout, reach: Optional[Reach], source_address=None) -> socket.socket:
    """`socket.create_connection`, for a mail server: `check` first, then a
    connection to the checked addresses only, in the order they resolved."""
    if timeout is not None and not timeout:
        raise ValueError("Non-blocking socket (timeout=0) is not supported")
    reach = reach if isinstance(reach, Reach) else MEMBER
    error: Optional[BaseException] = None
    for family, sockaddr in check(host, port, reach):
        address = (sockaddr[0], sockaddr[1])
        try:
            if timeout is None:
                return socket.create_connection(address, source_address=source_address)
            return socket.create_connection(address, timeout, source_address)
        except OSError as exc:
            error = exc
    assert error is not None
    raise error


# ---------------------------------------------------------------------------
# imaplib and smtplib, connected through `dial`
# ---------------------------------------------------------------------------

#: The libraries' own classes, bound at import: a test puts stand-ins in for
#: `imaplib.IMAP4` and `smtplib.SMTP`, and a stand-in is not the library.
_IMAP4, _IMAP4_SSL = imaplib.IMAP4, imaplib.IMAP4_SSL
_SMTP, _SMTP_SSL = smtplib.SMTP, smtplib.SMTP_SSL

@functools.lru_cache(maxsize=None)
def _pinned_class(cls):
    """A subclass of `cls` whose socket comes from `dial`, or None when `cls`
    is not imaplib's or smtplib's (a stand-in that opens no socket of its own)."""
    if isinstance(cls, type) and issubclass(cls, _IMAP4):
        class PinnedIMAP(cls):  # type: ignore[misc, valid-type]
            def __init__(self, *args, _mail_reach: Reach, **kwargs):
                self._mail_reach = _mail_reach
                super().__init__(*args, **kwargs)

            def _create_socket(self, timeout):
                sys.audit("imaplib.open", self, self.host, self.port)
                sock = dial(self.host, self.port, timeout, self._mail_reach)
                if isinstance(self, _IMAP4_SSL):
                    # `self.host` is the typed name: SNI and the hostname check.
                    return self.ssl_context.wrap_socket(sock, server_hostname=self.host)
                return sock

        # The library's class with its socket pinned: it keeps its name.
        PinnedIMAP.__name__, PinnedIMAP.__qualname__ = cls.__name__, cls.__qualname__
        return PinnedIMAP
    if isinstance(cls, type) and issubclass(cls, _SMTP):
        class PinnedSMTP(cls):  # type: ignore[misc, valid-type]
            def __init__(self, *args, _mail_reach: Reach, **kwargs):
                self._mail_reach = _mail_reach
                super().__init__(*args, **kwargs)

            def _get_socket(self, host, port, timeout):
                sock = dial(host, port, timeout, self._mail_reach, self.source_address)
                if isinstance(self, _SMTP_SSL):
                    # `self._host` is the typed name: SNI and the hostname check.
                    return self.context.wrap_socket(sock, server_hostname=self._host)
                return sock

        PinnedSMTP.__name__, PinnedSMTP.__qualname__ = cls.__name__, cls.__qualname__
        return PinnedSMTP
    return None


def pinned(cls, reach: Optional[Reach]):
    """`cls` (imaplib's `IMAP4` / `IMAP4_SSL`, smtplib's `SMTP` / `SMTP_SSL`),
    connected through `dial` under `reach` — called as `cls` is called.

    Every mail connection Pantheon opens takes its class from here. A class
    that is neither library's is handed back as it is: it is a stand-in that
    opens no socket, and nothing else is ever passed.
    """
    klass = _pinned_class(cls)
    if klass is None:
        return cls
    return functools.partial(klass, _mail_reach=reach if isinstance(reach, Reach) else MEMBER)


def first_refusal(reach: Reach, pairs: Iterable[Tuple[object, object]]) -> Optional[str]:
    """`refusal` over `(host, port)` pairs, skipping an empty host (an account
    with no SMTP, say): the sentence for the first refused, or None."""
    for host, port in pairs:
        if not str(host or "").strip():
            continue
        said = refusal(host, port, reach)
        if said:
            return said
    return None
