# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which certificate a mail server has to show before it gets a password.

`B2096`. Python's `imaplib` and `smtplib` take `ssl._create_stdlib_context()`
when they are handed no context, and that context checks nothing: whoever
answers on the network path is the mail server, and the next thing the client
sends it is the account's password or OAuth token. No mail connection passed
one. Every mail connection now takes its context from here, and the rule is
split by host, the owner's choice (2026-11-07):

* **a public host** has to show a certificate that a trusted authority signed
  for that name: the system's roots and certifi's, with the hostname checked,
  the check every mail provider already passes;
* **a private host** has its first certificate pinned by SHA-256 and has to show
  the same one from then on. Private is an address in a private, loopback,
  link-local or shared range, a name with no dot (a compose service such as
  `dovecot`), or a name under a suffix no registry delegates (`.local`, `.lan`,
  `.internal`, `.home.arpa` and the like). It is read from what the person
  typed and never from DNS, because an answer from DNS is the thing an
  impostor on the path controls;
* **a certificate a person trusted from the account form** is pinned the same
  way whatever the host, which is the way out for a public name that answers
  with a self-signed certificate on the owner's own network. A mail provider's
  own hosts (`src/providers.py`) are never trusted by hand: a provider always
  shows a certificate an authority signed, so one that does not is not the
  provider.

The certificate is checked right after the handshake and before the client
sends a credential. A changed or untrusted one raises `MailCertificateError`,
which names the host, the port and the fingerprints, so a person can tell *I
replaced that certificate* from *something is answering for my server*.

The pins live in `MAIL_TLS_PINS_FILE` (`<data>/mail_tls_pins.json`), one per
owner, host and port, so one member's trust never decides another's. The file
is the only record of what a private server looked like: `check-config-writes.py`
classes it `guarded`, and a pin file that exists and cannot be read refuses
every connection to a private host, rather than starting the pins over and
trusting whatever answers next. A public host keeps the authorities' check
when the pins cannot be read, which is the check it would have with no pin.

This module decides trust and nothing else. Ports, STARTTLS and timeouts stay
with each caller, as `src/mail_auth.py` keeps them there too.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import ssl
import threading
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no flock; the thread lock still holds
    fcntl = None

logger = logging.getLogger(__name__)

#: Suffixes no registry delegates on the public internet, so a name under one
#: is a name on the owner's own network. `.corp`, `.home` and `.mail` were
#: withheld from delegation by ICANN in 2018; the rest are reserved by RFC 6761,
#: RFC 6762, RFC 8375 or ICANN's 2024 `.internal` resolution, or are the
#: conventional LAN names routers hand out.
PRIVATE_SUFFIXES = (
    ".local", ".localhost", ".localdomain", ".lan", ".home", ".home.arpa",
    ".internal", ".intranet", ".corp", ".mail", ".private", ".test",
    ".example", ".invalid",
)

_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")
_LOCK = threading.Lock()


class MailCertificateError(ssl.SSLError):
    """A mail server showed a certificate this install will not send a password to.

    `reason` is `untrusted` (a public host whose certificate no trusted
    authority signed for its name), `changed` (a pinned host that now shows a
    different certificate) or `unreadable` (the pin file exists and cannot be
    read, so a private host's pin cannot be consulted).

    An `ssl.SSLError`, so every handler that catches a failed connection
    (`OSError`, `ssl.SSLError`) catches this one too.
    """

    def __init__(self, host: str, port, *, reason: str, fingerprint: str = "",
                 pinned: str = "", detail: str = "") -> None:
        self.host = host or ""
        try:
            self.port = int(port)
        except (TypeError, ValueError):
            self.port = 0
        self.reason = reason
        self.fingerprint = fingerprint
        self.pinned = pinned
        self.detail = detail
        super().__init__(self._sentence())

    def __str__(self) -> str:
        # `ssl.SSLError.__str__` prints the args tuple when there is no
        # `strerror`, and the sentence is what every route shows.
        return self._sentence()

    def _sentence(self) -> str:
        where = f"{self.host}:{self.port}" if self.port else self.host
        if self.reason == "changed":
            return (f"The mail server at {where} showed a different certificate from the one "
                    f"this account trusts ({self.fingerprint}, not {self.pinned}). Nothing was "
                    "sent to it. If you replaced the server's certificate, trust the new one "
                    "from the account's Test; if you did not, something else is answering for it.")
        if self.reason == "unreadable":
            return (f"The mail server at {where} was not sent a password: the list of trusted "
                    f"mail certificates could not be read ({self.detail}).")
        why = f" ({self.detail})" if self.detail else ""
        return (f"The mail server at {where} showed a certificate no trusted authority signed "
                f"for that name{why}. Nothing was sent to it. If this is your own server, "
                "trust its certificate from the account's Test.")

    def as_dict(self) -> dict:
        return {
            "reason": self.reason,
            "host": self.host,
            "port": self.port,
            "fingerprint": self.fingerprint,
            "pinned": self.pinned,
        }


def is_private_host(host: str) -> bool:
    """Is `host`, as the person typed it, on their own network?"""
    name = (host or "").strip().rstrip(".").lower()
    if not name:
        return False
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    try:
        addr = ipaddress.ip_address(name.split("%", 1)[0])
    except ValueError:
        addr = None
    if addr is not None:
        if getattr(addr, "ipv4_mapped", None) is not None:
            addr = addr.ipv4_mapped
        shared = isinstance(addr, ipaddress.IPv4Address) and addr in ipaddress.ip_network("100.64.0.0/10")
        return bool(addr.is_private or addr.is_loopback or addr.is_link_local or shared)
    if name == "localhost" or "." not in name:
        return True
    return name.endswith(PRIVATE_SUFFIXES)


def is_provider_host(host: str) -> bool:
    """A host one of `src/providers.py`'s mail providers serves."""
    from src import providers
    name = providers.normalize_host(host)
    for record in providers.PROVIDERS.values():
        mail = getattr(record, "mail", None)
        if mail is not None and (name in mail.imap_hosts or name in mail.smtp_hosts):
            return True
    return False


def fingerprint(der: bytes) -> str:
    """`sha256:` and the hex digest of a certificate's DER bytes."""
    return "sha256:" + hashlib.sha256(der).hexdigest()


def is_fingerprint(value) -> bool:
    return isinstance(value, str) and _FINGERPRINT.fullmatch(value) is not None


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

def _pins_path() -> Path:
    from src.constants import MAIL_TLS_PINS_FILE
    return Path(MAIL_TLS_PINS_FILE)


def _key(host: str, port) -> str:
    return f"{(host or '').strip().rstrip('.').lower()}:{int(port or 0)}"


def _read_pins() -> dict:
    """The pin file as a dict; `{}` when there is none yet.

    Raises `ValueError` or `OSError` for a file that exists and cannot be read.
    Callers turn that into a refusal: an unreadable record of trust is not an
    empty one.
    """
    path = _pins_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("the file does not hold an object")
    return data


@contextmanager
def _pins_locked():
    """The thread lock, and across processes (the app and the agent's mail
    server both pin) an advisory lock on a sidecar file."""
    with _LOCK:
        if fcntl is None:
            yield
            return
        path = _pins_path()
        lock_path = path.with_name(path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _unreadable(host: str, port, exc: BaseException) -> MailCertificateError:
    logger.error("mail TLS pins at %s could not be read: %s", _pins_path(), exc)
    return MailCertificateError(host, port, reason="unreadable",
                                detail=f"{exc.__class__.__name__}: {exc}")


def pinned(owner: str, host: str, port) -> str | None:
    """The fingerprint `owner` trusts for `host:port`, or `None`.

    Raises `MailCertificateError(reason="unreadable")` when the pin file cannot
    be read.
    """
    key = _key(host, port)
    try:
        mine = _read_pins().get(owner or "") or {}
        if not isinstance(mine, dict):
            raise ValueError("an owner's entry is not an object")
        entry = mine.get(key)
    except (OSError, ValueError) as exc:
        raise _unreadable(host, port, exc) from exc
    if isinstance(entry, dict) and is_fingerprint(entry.get("sha256")):
        return entry["sha256"]
    return None


def _write_pin(owner: str, host: str, port, value: str, how: str,
               *, replace: bool) -> str:
    """Record `value` for `host:port`; returns the fingerprint that stands.

    With `replace=False` (a first sight) a pin another connection recorded in
    the meantime wins, so two first connections cannot pin two certificates.
    """
    from core.atomic_io import atomic_write_json
    if not is_fingerprint(value):
        raise ValueError(f"not a certificate fingerprint: {value!r}")
    with _pins_locked():
        try:
            pins = _read_pins()
        except (OSError, ValueError) as exc:
            raise _unreadable(host, port, exc) from exc
        mine = pins.setdefault(owner or "", {})
        if not isinstance(mine, dict):
            raise _unreadable(host, port, ValueError("an owner's entry is not an object"))
        current = mine.get(_key(host, port))
        if (not replace and isinstance(current, dict)
                and is_fingerprint(current.get("sha256"))):
            return current["sha256"]
        mine[_key(host, port)] = {
            "sha256": value,
            "how": how,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        pins_path = str(_pins_path())
        atomic_write_json(pins_path, pins, indent=2, preserve_unreadable=True)
    return value


def trust(owner: str, host: str, port, value: str) -> None:
    """A person trusted the certificate with fingerprint `value` for `host:port`.

    Raises `ValueError` with a sentence for a request the account form should
    not have made: no host, a port out of range, a value that is not a
    fingerprint, or a mail provider's own host.
    """
    name = (host or "").strip().rstrip(".").lower()
    if not name or len(name) > 253 or any(ch.isspace() for ch in name):
        raise ValueError("Name the mail server's host.")
    try:
        number = int(port)
    except (TypeError, ValueError):
        number = 0
    if not 1 <= number <= 65535:
        raise ValueError("The port must be a number from 1 to 65535.")
    if not is_fingerprint(value):
        raise ValueError("That is not a certificate fingerprint.")
    if is_provider_host(name):
        raise ValueError(f"{name} belongs to a mail provider, whose real certificate is "
                         "always signed by an authority, so a certificate it did not sign "
                         "is not trusted by hand.")
    _write_pin(owner, name, number, value, "trusted", replace=True)
    logger.info("mail certificate for %s trusted by hand: %s", _key(name, number), value)


# ---------------------------------------------------------------------------
# Contexts and the check after the handshake
# ---------------------------------------------------------------------------

def _authority_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        logger.warning("certifi is not installed; mail certificates are checked "
                       "against the system's roots alone")
    else:
        ctx.load_verify_locations(cafile=certifi.where())
    return ctx


def _pinning_context() -> ssl.SSLContext:
    """No authority check: the certificate is compared with its pin instead,
    in `check_server`, before a credential is sent. A context of its own, not
    `create_default_context()`'s with its checks switched off."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def context_for(owner: str, host: str, port) -> ssl.SSLContext:
    """The context a mail connection to `host:port` opens its TLS with."""
    if is_private_host(host):
        return _pinning_context()
    try:
        pin = pinned(owner, host, port)
    except MailCertificateError:
        # A public host keeps the check it would have with no pin at all.
        return _authority_context()
    return _pinning_context() if pin else _authority_context()


def _checked_by_authorities(sock: ssl.SSLSocket) -> bool:
    ctx = getattr(sock, "context", None)
    return bool(ctx is not None and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname)


def check_server(sock, owner: str, host: str, port) -> None:
    """Call once the TLS handshake is done and before any credential is sent.

    A plain socket is left alone: a connection the account set to no TLS has
    no certificate to check. A handshake whose context checked an authority's
    signature for the name has been checked. Otherwise the certificate is
    compared with the pin, a private host's first one is pinned, and a public
    host with no pin is refused.
    """
    if not isinstance(sock, ssl.SSLSocket) or _checked_by_authorities(sock):
        return
    pin = pinned(owner, host, port)
    der = sock.getpeercert(binary_form=True)
    if not der:
        raise MailCertificateError(host, port, reason="untrusted",
                                   detail="the server sent no certificate")
    seen = fingerprint(der)
    if pin is None:
        if not is_private_host(host):
            raise MailCertificateError(host, port, reason="untrusted", fingerprint=seen,
                                       detail="no authority checked it")
        standing = _write_pin(owner, host, port, seen, "first seen", replace=False)
        if standing == seen:
            logger.info("mail certificate for %s pinned on first sight: %s",
                        _key(host, port), seen)
            return
        pin = standing
    if seen != pin:
        raise MailCertificateError(host, port, reason="changed",
                                   fingerprint=seen, pinned=pin)


def check_connection(conn, owner: str, host: str, port) -> None:
    """`check_server` on an `imaplib` or `smtplib` connection, closing it
    first when it is refused."""
    try:
        check_server(getattr(conn, "sock", None), owner, host, port)
    except MailCertificateError:
        close_quietly(conn)
        raise


@contextmanager
def handshake(host: str, port):
    """Say a failed authority check as `MailCertificateError`."""
    try:
        yield
    except MailCertificateError:
        raise
    except ssl.SSLCertVerificationError as exc:
        detail = getattr(exc, "verify_message", "") or str(exc)
        raise MailCertificateError(host, port, reason="untrusted", detail=detail) from exc


def close_quietly(conn) -> None:
    """Close a connection a credential must not follow. `IMAP4.shutdown()`
    closes the socket (its `close()` is the IMAP command), and `smtplib`'s
    `close()` closes it without a QUIT."""
    for name in ("shutdown", "close"):
        closer = getattr(conn, name, None)
        if closer is None:
            continue
        try:
            closer()
        except OSError:
            logger.debug("closing the refused mail connection raised", exc_info=True)
        return


# ---------------------------------------------------------------------------
# What the account form's Test says about a refused server
# ---------------------------------------------------------------------------

def peek(kind: str, host: str, port, *, tls: str, timeout: float = 5.0) -> str:
    """The fingerprint `host:port` shows now, read over a connection that
    sends no credential, so the account form can offer to trust it.

    `kind` is `imap` or `smtp`; `tls` is `ssl` (TLS from the first byte) or
    `starttls`.
    """
    import imaplib
    import smtplib

    ctx = _pinning_context()
    port = int(port)
    conn = None
    try:
        if kind == "imap" and tls == "ssl":
            conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=timeout)
        elif kind == "imap":
            conn = imaplib.IMAP4(host, port, timeout=timeout)
            conn.starttls(ssl_context=ctx)
        elif tls == "ssl":
            conn = smtplib.SMTP_SSL(host, port, context=ctx, timeout=timeout)
        else:
            conn = smtplib.SMTP(host, port, timeout=timeout)
            conn.starttls(context=ctx)
        der = conn.sock.getpeercert(binary_form=True)
        return fingerprint(der) if der else ""
    finally:
        if conn is not None:
            close_quietly(conn)


def offer(exc: BaseException, kind: str, host: str, port, *, tls: str | None) -> dict | None:
    """The `certificate` the account form's Test returns beside a refusal, or
    `None` when `exc` is not one.

    `trustable` says whether the form offers *Trust this certificate*: for a
    certificate that was untrusted or changed, with a fingerprint read, on a
    host no mail provider serves.
    """
    found, hops = exc, 0
    while found is not None and not isinstance(found, MailCertificateError) and hops < 8:
        found, hops = found.__cause__ or found.__context__, hops + 1
    if not isinstance(found, MailCertificateError):
        return None
    out = found.as_dict()
    out["trustable"] = False
    if found.reason not in ("untrusted", "changed") or not tls or is_provider_host(host):
        return out
    seen = found.fingerprint
    if not seen:
        try:
            seen = peek(kind, host, port, tls=tls)
        except Exception as peek_exc:  # the refusal is the answer; the offer is extra
            logger.info("could not read the certificate %s:%s shows: %s", host, port, peek_exc)
            seen = ""
    out["fingerprint"] = seen
    out["trustable"] = is_fingerprint(seen)
    return out
