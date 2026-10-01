# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pantheon's side of the workstation — `P20-02`, `D-2026-09-30-03`.

The workstation is a separate machine (a container beside Pantheon, a VM, or
any host running `workstation/agentd.py`), and this module is the only thing in
Pantheon that talks to it. It imports the protocol rather than restating it
(`Law 7`): a route, a field bound or an error code exists once, in
`workstation/protocol.py`, and the daemon reads the same file.

**WHERE IT IS, AND THE TOKEN, WITHOUT ANYONE TYPING EITHER.** The admin setting
wins; otherwise the environment the compose overlay sets
(`PANTHEON_WORKSTATION_URL`); otherwise nothing, and the workstation is off. The
token: the setting, then `PANTHEON_WORKSTATION_TOKEN`, then the file the daemon
wrote into the pairing volume the two services share. Switching the overlay on
is the consent; nothing ships pointing anywhere (`D-2026-08-31-01`).

**WHY THE URL IS NOT PUT THROUGH THE SSRF VALIDATORS.** They guard addresses
that arrive from content. This one is an admin's setting, and every request's
path comes from `protocol.ROUTES` — the same argument `src/netagent_client.py`
makes: there is no parameter through which a model can name where a request
goes. Calls go through `src.paced_http` / the outbound limiter like every other
(a local host is paced at zero, so it costs nothing).

**NEVER RAISES ANYTHING BUT `WorkstationError`,** whose `message` is a sentence
for a person — the tool layer puts it in the card as it stands.

**A WORKSTATION ON ANOTHER MACHINE (`P20-07`).** The token is a bearer secret,
and this is the side that decides whether to send it, so the rule
`workstation/protocol.py` states above `TLS_PIN_ENV` is enforced here, before a
byte goes out: `http://` only to an address that is not globally routable (a
name only when every address it resolves to is one), and `https://` verified
— by the system's trust store, or by the certificate's SHA-256 fingerprint
when `PANTHEON_WORKSTATION_CERT_SHA256` names one, compared on the handshake
and so before the request carrying the token is written. A redirect is not
followed: a workstation never sends one, and following it is how a request
with the token in it ends up somewhere nobody configured.

**A PROXY IN THE ENVIRONMENT (`B982`).** httpx honours `HTTPS_PROXY` and
reads `NO_PROXY`'s names, not its ranges; a workstation whose address — or,
for a name, every address it resolves to — is in a range `NO_PROXY` names goes
direct, through `src.paced_http.direct_mounts`, the one place that reads them.

**A backend that starts machines.** The VM backend boots a person's machine
on first use (`workstation/vm.py`); its `health` says `backend: "vm"`, and a
client that has heard that waits `protocol.MACHINE_START_S` longer on that
person's routes before calling the workstation down. Every other backend gets
the bounds it always had, so a hung container is still reported in seconds.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import ssl
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Union
from urllib.parse import urlencode, urlsplit, urlunsplit

from workstation import protocol as P

logger = logging.getLogger(__name__)

URL_ENV = P.URL_ENV
_TIMEOUT = 30.0
# An exec's answer can take as long as the command; the daemon enforces the
# command's own timeout and this only has to outlast it.
_EXEC_GRACE_S = 15.0

account_for = P.account_name


class WorkstationError(Exception):
    """What went wrong, as a protocol code and a sentence for a person."""

    def __init__(self, code: str, message: str, status: int = 0):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def as_result(self) -> Dict[str, Any]:
        """The shape a tool handler returns, so a refusal reads like any other
        failed tool call."""
        return {"error": self.message, "exit_code": 1, "workstation_error": self.code}


class WorkstationUnreachable(WorkstationError):
    """`B978`: nothing answered at the workstation's address at all — not a
    refusal, not something else answering, not a certificate. Still the code
    `unavailable` (a subclass, so every `except WorkstationError` is as it
    was); the type lets `workstation_access.sync_config` ask whether the
    network gate in front of it is up, which is the one case it can say more."""


def _setting(key: str, default: Any = "") -> Any:
    try:
        from src.settings import get_setting
        return get_setting(key, default)
    except Exception:  # noqa: BLE001 — unreadable settings are "not configured"
        return default


def parse_base(raw: str) -> Optional[str]:
    """An origin (`scheme://host[:port]`) out of a string, or None. Rebuilt from
    its parts, so a value carrying a path, a query or credentials cannot
    survive by looking like a base URL (`src/netagent_client.parse_agent_base`)."""
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    if port is not None and not 1 <= port <= 65535:
        return None
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


# Where a value came from, as the Settings panel says it (`P20-02`). One word
# per layer, in the order the layers are consulted; `none` means no layer
# answered. An enum rather than a pair of booleans (`Law 10`).
SOURCE_SETTING = "setting"
SOURCE_ENVIRONMENT = "environment"
SOURCE_PAIRING = "pairing"
SOURCE_NONE = "none"


def resolve_base() -> tuple[Optional[str], str]:
    """`(origin, source)`: the address in effect and the layer it came from.

    `P20-02`. The order lives here and only here — `configured_base` is this
    function's first half — so the panel's "where it came from" and the address
    the client actually calls cannot disagree (`Law 7`). A stored value that
    does not parse falls through to the environment rather than winning; the
    settings route refuses one at the moment it is typed, so that only happens
    to a hand-edited file."""
    stored = parse_base(str(_setting("workstation_url", "") or ""))
    if stored:
        return stored, SOURCE_SETTING
    env = parse_base(os.environ.get(URL_ENV, ""))
    if env:
        return env, SOURCE_ENVIRONMENT
    return None, SOURCE_NONE


def configured_base() -> Optional[str]:
    return resolve_base()[0]


def pairing_token_path() -> Path:
    return Path(os.environ.get(P.PAIRING_DIR_ENV) or P.DEFAULT_PAIRING_DIR) / P.TOKEN_FILENAME


def resolve_token() -> tuple[str, str]:
    """`(token, source)`. The value never leaves the server: the panel is told
    the source and whether there is one, and nothing else (`P20-02`)."""
    token = str(_setting("workstation_token", "") or "").strip()
    if token:
        return token, SOURCE_SETTING
    token = (os.environ.get(P.TOKEN_ENV) or "").strip()
    if token:
        return token, SOURCE_ENVIRONMENT
    try:
        token = pairing_token_path().read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if token:
        return token, SOURCE_PAIRING
    return "", SOURCE_NONE


def configured_token() -> str:
    return resolve_token()[0]


def enabled() -> bool:
    """The admin's switch. Off by default: a workstation nobody turned on does
    nothing, even if the overlay is running."""
    return _setting("workstation_enabled", False) is True


def from_settings() -> Optional["WorkstationClient"]:
    """The configured client, or None when the workstation is off or has no
    address. A missing token is not None — it is a client whose calls say
    what is missing, because "off" and "misconfigured" are different answers."""
    if not enabled():
        return None
    base = configured_base()
    if not base:
        return None
    return WorkstationClient(base, configured_token())


ProgressCb = Callable[[str, str], Union[None, Awaitable[None]]]


# ── the wire, for a workstation on another machine (`P20-07`) ────────────────

def normalise_pin(raw: str) -> Optional[str]:
    """A SHA-256 fingerprint as 64 lowercase hex digits, from what `openssl
    x509 -fingerprint -sha256` prints (`sha256 Fingerprint=AB:CD:…`), a bare hex
    string, or either with spaces — or None when it is not one."""
    text = str(raw or "").strip().lower()
    if "=" in text:
        text = text.rsplit("=", 1)[1]
    text = text.replace(":", "").replace(" ", "")
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        return None
    return text


def configured_pin() -> tuple[Optional[str], bool]:
    """`(pin, set)`: the pinned fingerprint, and whether the variable was set
    at all — so a value that is not a fingerprint is refused with a sentence
    rather than quietly falling back to the trust store."""
    raw = (os.environ.get(P.TLS_PIN_ENV) or "").strip()
    return (normalise_pin(raw) if raw else None), bool(raw)


def cert_fingerprint(der: bytes) -> str:
    return hashlib.sha256(der or b"").hexdigest()


class CertificatePinMismatch(ssl.SSLCertVerificationError):
    """The workstation presented a certificate other than the pinned one."""

    def __init__(self, got: str):
        super().__init__(f"certificate sha256 {got} is not the pinned one")
        self.got = got


def _pinned_context(pin: str) -> ssl.SSLContext:
    """A client context that trusts exactly one certificate: the one whose
    SHA-256 is `pin`. The chain and the name are not consulted — an exact
    certificate is a stronger statement than either, which is SSH's host-key
    model — and the comparison runs inside the handshake (`do_handshake`, the
    method every TLS stack calls until it completes), so a certificate that
    does not match fails the connection before the request is written."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    def _check(obj) -> None:
        got = cert_fingerprint(obj.getpeercert(binary_form=True) or b"")
        if not hmac.compare_digest(got, pin):
            raise CertificatePinMismatch(got)

    class _PinnedObject(ssl.SSLObject):
        def do_handshake(self):
            super().do_handshake()
            _check(self)

    class _PinnedSocket(ssl.SSLSocket):
        def do_handshake(self, block=False):
            super().do_handshake(block)
            _check(self)

    ctx.sslobject_class = _PinnedObject
    ctx.sslsocket_class = _PinnedSocket
    return ctx


def _not_global(host: str) -> Optional[bool]:
    """True/False for an IP literal, None for a name."""
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    # `is_global`, not `is_private`: a tailnet's 100.64.0.0/10 is neither
    # private nor global, and `check-destinations.py` learnt that once already.
    return not ip.is_global


class WorkstationClient:
    """One workstation, one token. Every method is one route in `ROUTES`."""

    def __init__(self, base: str, token: str, *, timeout: float = _TIMEOUT):
        parsed = parse_base(base)
        if not parsed:
            raise WorkstationError("bad_request", f"{base!r} is not a workstation address.")
        self.base = parsed
        self.token = token or ""
        self.timeout = timeout
        # `P20-07`: learnt from this workstation's own `health`.
        self._starts_machines = False
        self._verify: Any = None
        # `B982`: httpx `mounts` that keep this workstation off an environment
        # proxy when `NO_PROXY` names its address by range (`paced_http.
        # direct_mounts`), worked out with `_verify`, once.
        self._mounts: Dict[str, None] = {}

    # -- the wire (`P20-07`) ----------------------------------------------------

    async def _wire(self) -> Any:
        """What httpx is given as `verify`, once the address has passed the
        rule in the module docstring; a `WorkstationError` when it has not."""
        if self._verify is not None:
            return self._verify
        parts = urlsplit(self.base)
        host = parts.hostname or ""
        if parts.scheme == "https":
            pin, pin_set = configured_pin()
            if pin_set and pin is None:
                raise WorkstationError(
                    "bad_request",
                    f"{P.TLS_PIN_ENV} is not a SHA-256 fingerprint. It is the line "
                    "workstation/install.py printed, such as AB:CD:…:EF (64 hex digits).")
            self._mounts = await self._direct(host, parts.port or 443)  # `B982`
            self._verify = _pinned_context(pin) if pin else True
            return self._verify
        verdict = _not_global(host)
        addresses: Any = None
        if verdict is None:
            try:
                infos = await asyncio.get_running_loop().getaddrinfo(
                    host, parts.port or 80, type=0, proto=0)
            except OSError as e:
                raise WorkstationUnreachable(
                    "unavailable", f"The workstation at {self.base} did not answer "
                                   f"({type(e).__name__}). Is it running?") from e
            addresses = {info[4][0] for info in infos}
            verdict = bool(addresses) and all(_not_global(a) for a in addresses)
        if not verdict:
            raise WorkstationError(
                "bad_request",
                f"Pantheon will not send the workstation's token to {host} over plain http: it is "
                "a public address, and anyone on the way could read the token and drive the "
                f"workstation. Use https:// (workstation/install.py sets it up and prints the "
                f"{P.TLS_PIN_ENV} line), or reach it over a private network or VPN.")
        self._mounts = await self._direct(host, parts.port or 80, addresses)  # `B982`
        self._verify = True
        return self._verify

    async def _direct(self, host: str, port: int, addresses: Any = None) -> Dict[str, None]:
        """`B982`. `paced_http.direct_mounts` for this workstation: a name is
        looked up only when `NO_PROXY` has a range to look it up for (and the
        plain-http rule above has usually looked already); a lookup that fails
        leaves the environment to decide, as it always did."""
        from src import paced_http
        if not paced_http.no_proxy_ranges():
            return {}
        if addresses is None and _not_global(host) is None:
            try:
                infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=0, proto=0)
                addresses = {info[4][0] for info in infos}
            except OSError:
                addresses = ()
        return paced_http.direct_mounts(self.base, addresses=addresses or ())

    def _http(self, timeout: float, verify: Any):
        import httpx
        return httpx.AsyncClient(timeout=timeout, verify=verify, follow_redirects=False,
                                 mounts=self._mounts or None)  # `B982`

    def _unreachable(self, e: BaseException) -> WorkstationError:
        """The sentence for a request that never got an answer — and for a
        certificate, which one it was and what to do."""
        return self._certificate_refused(e) or WorkstationUnreachable(
            "unavailable",
            f"The workstation at {self.base} did not answer ({type(e).__name__}). "
            "Is it running?")

    def _certificate_refused(self, e: BaseException) -> Optional[WorkstationError]:
        """The sentence when the connection failed on the certificate, found
        anywhere in the chain httpx and its transport wrap it in; else None."""
        seen, cause = set(), e
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, CertificatePinMismatch):
                return WorkstationError(
                    "unavailable",
                    f"The workstation at {self.base} presented a certificate (sha256 "
                    f"{cause.got}) that is not the one {P.TLS_PIN_ENV} names, so Pantheon sent "
                    "nothing. If the workstation was reinstalled, use the fingerprint its "
                    "installer printed; if it was not, something else is answering there.")
            if isinstance(cause, ssl.SSLCertVerificationError):
                return WorkstationError(
                    "unavailable",
                    f"The workstation at {self.base} presented a certificate Pantheon cannot "
                    f"verify ({getattr(cause, 'verify_message', None) or cause}), so it sent "
                    f"nothing. For the certificate workstation/install.py made, set "
                    f"{P.TLS_PIN_ENV} to the fingerprint it printed.")
            cause = cause.__cause__ or cause.__context__
        return None

    def _grace(self, name: str, account: Optional[str]) -> float:
        if account and name != "account" and self._starts_machines:
            return P.MACHINE_START_S
        return 0.0

    # -- plumbing ---------------------------------------------------------------

    def _url(self, name: str, account: Optional[str] = None, query: Optional[Dict] = None):
        method, path = P.route_path(name, account)
        url = f"{self.base}{path}"
        if query:
            url += "?" + urlencode({k: v for k, v in query.items() if v is not None})
        return method, url

    def _headers(self) -> Dict[str, str]:
        if not self.token:
            raise WorkstationError(
                "unauthorized",
                "Pantheon has no token for the workstation. It is read from the pairing volume the "
                "workstation shares with Pantheon, or set in Settings → Workstation.")
        return {"Authorization": f"Bearer {self.token}"}

    @staticmethod
    def _error_from(response) -> WorkstationError:
        status = getattr(response, "status_code", 0)
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            body = {}
        code = body.get("error") if isinstance(body, dict) else None
        message = body.get("message") if isinstance(body, dict) else None
        if status == 401:
            return WorkstationError(
                "unauthorized",
                "The workstation refused Pantheon's token. If it was set by hand, it must match "
                "the workstation's PANTHEON_WORKSTATION_TOKEN.", status)
        if code in P.ERRORS and message:
            return WorkstationError(code, str(message), status)
        return WorkstationError("internal", f"The workstation answered {status}.", status)

    async def _call(self, name: str, account: Optional[str] = None, body: Optional[Dict] = None,
                    *, query: Optional[Dict] = None, timeout: Optional[float] = None,
                    allow_304: bool = False) -> Optional[Dict]:
        method, url = self._url(name, account, query)
        headers = self._headers() if name != "health" else (
            {"Authorization": f"Bearer {self.token}"} if self.token else {})
        verify = await self._wire()  # `P20-07`: before the token goes anywhere
        wait = (timeout or self.timeout) + self._grace(name, account)
        try:
            from src import paced_http
            kwargs: Dict[str, Any] = {"headers": headers, "timeout": wait,
                                      "authenticated": True}
            if method == "POST":
                kwargs["json"] = body or {}
            async with self._http(wait, verify) as http:
                response = await paced_http.request(method, url, client=http, **kwargs)
        except WorkstationError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.info("workstation unreachable at %s: %s", self.base, type(e).__name__)
            raise self._unreachable(e) from e
        if allow_304 and response.status_code == 304:
            return None
        if response.status_code != 200:
            raise self._error_from(response)
        try:
            payload = response.json()
        except Exception as e:  # noqa: BLE001
            raise WorkstationError("internal", "The workstation answered with something that is "
                                               "not JSON.") from e
        if not isinstance(payload, dict):
            raise WorkstationError("internal", "The workstation's answer was not an object.")
        return payload

    # -- the routes -------------------------------------------------------------

    async def health(self) -> Dict:
        payload = await self._call("health")
        if payload.get("agent") != P.AGENT_NAME:
            # Something answered on that port, and it is not a workstation.
            raise WorkstationError(
                "unavailable", f"Something answered at {self.base}, but it is not a Pantheon "
                               "workstation.")
        if payload.get("protocol") != P.PROTOCOL_VERSION:
            raise WorkstationError(
                "unavailable", f"The workstation speaks protocol {payload.get('protocol')}; this "
                               f"Pantheon speaks {P.PROTOCOL_VERSION}. Update the older one.")
        self._starts_machines = payload.get("backend") == "vm"  # `P20-07`
        return payload

    async def account(self, account: str) -> Dict:
        """`B959` (`P20-07`): `{"account", "exists", "home"}` — whether this
        person's home is there, without making it. A daemon older than the
        route answers `not_found` for the route itself; that comes back as
        `exists: None` — "cannot tell" — never as "does not exist"."""
        try:
            return await self._call("account", account)
        except WorkstationError as e:
            if e.status == 404:
                return {"account": account, "exists": None, "home": None}
            raise

    async def config(self, **settings: Any) -> Dict:
        return await self._call("config", body=settings)

    async def ensure(self, account: str) -> Dict:
        return await self._call("ensure", account)

    async def reset(self, account: str) -> Dict:
        return await self._call("reset", account, timeout=120.0)

    async def control(self, account: str, holder: str) -> Dict:
        return await self._call("control", account, {"holder": holder})

    async def exec(self, account: str, command: str, *, shell: str = "bash",
                   cwd: Optional[str] = None, timeout_s: float = P.DEFAULT_EXEC_TIMEOUT_S,
                   env: Optional[Dict[str, str]] = None, stdin: Optional[str] = None,
                   on_output: Optional[ProgressCb] = None) -> Dict:
        """Run a command as `account`. With `on_output`, the output is streamed
        to it as `(kind, text)` while the command runs; the return value is the
        same either way."""
        body: Dict[str, Any] = {"command": command, "shell": shell, "timeout_s": timeout_s}
        if cwd:
            body["cwd"] = cwd
        if env:
            body["env"] = env
        if stdin is not None:
            body["stdin"] = stdin
        wait = min(float(timeout_s), P.MAX_EXEC_TIMEOUT_S) + _EXEC_GRACE_S
        if on_output is None:
            return await self._call("exec", account, body, timeout=wait)
        return await self._stream_exec(account, dict(body, stream=True), on_output, wait)

    async def _stream_exec(self, account: str, body: Dict, on_output: ProgressCb,
                           wait: float) -> Dict:
        import inspect

        import httpx

        from src.paced_http import _host, _observe
        from src.rate_limiter import outbound

        method, url = self._url("exec", account)
        host = _host(url)
        verify = await self._wire()  # `P20-07`
        wait += self._grace("exec", account)
        await outbound.acquire_async(host, authenticated=True)
        result: Optional[Dict] = None
        try:
            async with httpx.AsyncClient(timeout=wait, verify=verify, follow_redirects=False,
                                         mounts=self._mounts or None) as client:  # `B982`
                async with client.stream(method, url, json=body, headers=self._headers()) as r:
                    _observe(host, r)
                    if r.status_code != 200:
                        await r.aread()
                        raise self._error_from(r)
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if event.get("type") == "exit":
                            result = {k: v for k, v in event.items() if k != "type"}
                            continue
                        out = on_output(str(event.get("type")), str(event.get("data") or ""))
                        if inspect.isawaitable(out):
                            await out
        except WorkstationError:
            raise
        except Exception as e:  # noqa: BLE001
            outbound.note_failure(host)
            refused = self._certificate_refused(e)
            if refused is not None:  # `P20-07`: it never connected, so nothing ran
                raise refused from e
            raise WorkstationError(
                "unavailable", f"The workstation at {self.base} stopped answering while the "
                               f"command ran ({type(e).__name__}).") from e
        if result is None:
            raise WorkstationError("internal", "The workstation ended the command without a result.")
        if result.get("error") in P.ERRORS and "stdout" not in result:
            raise WorkstationError(result["error"], str(result.get("message") or ""))
        return result

    async def read(self, account: str, path: str, *, offset: int = 0,
                   max_bytes: Optional[int] = None) -> Dict:
        """`{"path", "size", "data": bytes, "truncated"}`."""
        body: Dict[str, Any] = {"path": path, "offset": offset}
        if max_bytes is not None:
            body["max_bytes"] = max_bytes
        payload = await self._call("read", account, body, timeout=120.0)
        payload["data"] = base64.b64decode(payload.pop("data_b64", "") or "")
        return payload

    async def write(self, account: str, path: str, data: Union[bytes, str], *,
                    append: bool = False, make_dirs: bool = True) -> Dict:
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        if len(raw) > P.MAX_FILE_BYTES:
            raise WorkstationError("too_large", f"A file is at most {P.MAX_FILE_BYTES:,} bytes.")
        return await self._call("write", account, {
            "path": path, "data_b64": base64.b64encode(raw).decode(),
            "append": bool(append), "make_dirs": bool(make_dirs)}, timeout=120.0)

    async def list(self, account: str, path: Optional[str] = None, *, recursive: bool = False,
                   max_entries: Optional[int] = None) -> Dict:
        body: Dict[str, Any] = {"recursive": bool(recursive)}
        if path:
            body["path"] = path
        if max_entries is not None:
            body["max_entries"] = max_entries
        return await self._call("list", account, body)

    async def screenshot(self, account: str, *, fmt: str = "png",
                         if_none_match: Optional[str] = None) -> Optional[Dict]:
        """The screen, or None when `if_none_match` names the frame already held."""
        return await self._call("screenshot", account,
                                query={"format": fmt, "if_none_match": if_none_match},
                                allow_304=True)

    async def input(self, account: str, action: str, *, holder: str = "agent",
                    screenshot_after: bool = False, **fields: Any) -> Dict:
        if action not in P.INPUT_ACTIONS:
            raise WorkstationError("bad_request",
                                   f"“{action}” is not one of {', '.join(P.INPUT_ACTIONS)}.")
        body = {"action": action, "holder": holder, "screenshot_after": bool(screenshot_after),
                **{k: v for k, v in fields.items() if v is not None}}
        return await self._call("input", account, body, timeout=P.MAX_WAIT_MS / 1000 + _TIMEOUT)


# ── the network gate (`P20-06`) ───────────────────────────────────────────────
#
# The container the workstation shares its network with, holding the admin's
# network mode where the workstation's root cannot reach (`workstation/gate.py`).
# It exists only where the overlay says so: `GATE_URL_ENV` on Pantheon, and its
# token in a volume the workstation never mounts. No setting names it — an admin
# who points `workstation_url` somewhere else has pointed away from this gate,
# and `gate_for` (below) is what notices.

def gate_token_path() -> Path:
    return (Path(os.environ.get(P.GATE_PAIRING_DIR_ENV) or P.DEFAULT_GATE_PAIRING_DIR)
            / P.TOKEN_FILENAME)


def resolve_gate() -> tuple[Optional[str], str]:
    """`(origin, token)` of the network gate the overlay set, or `(None, "")`."""
    base = parse_base(os.environ.get(P.GATE_URL_ENV, ""))
    if not base:
        return None, ""
    try:
        token = gate_token_path().read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    return base, token


def gate_for(client: "WorkstationClient") -> Optional["NetGateClient"]:
    """The gate in front of THIS workstation, or None. Only when the gate's
    host is the workstation's host: a gate in front of some other machine
    says nothing about this one, and claiming its rules for it would be the
    panel saying something the system does not keep."""
    base, token = resolve_gate()
    if not base:
        return None
    if urlsplit(base).hostname != urlsplit(client.base).hostname:
        return None
    return NetGateClient(base, token, timeout=client.timeout)


class NetGateClient(WorkstationClient):
    """The gate's two routes (`protocol.GATE_ROUTES`), with the workstation
    client's plumbing — pacing, errors as sentences, the token never in one."""

    def _url(self, name: str, account: Optional[str] = None, query: Optional[Dict] = None):
        if name not in P.GATE_ROUTES:
            raise KeyError(f"no network gate route named {name!r}")
        method, path = P.GATE_ROUTES[name]
        return method, f"{self.base}{path}"

    def _headers(self) -> Dict[str, str]:
        if not self.token:
            raise WorkstationError(
                "unauthorized",
                "Pantheon has no token for the workstation's network gate. It is read from the "
                "gate's pairing volume, which the workstation overlay mounts into Pantheon.")
        return {"Authorization": f"Bearer {self.token}"}

    @staticmethod
    def _error_from(response) -> WorkstationError:
        if getattr(response, "status_code", 0) == 401:
            return WorkstationError("unauthorized", "The workstation's network gate refused "
                                                    "Pantheon's token.", 401)
        return WorkstationClient._error_from(response)

    async def health(self) -> Dict:
        payload = await self._call("health")
        if payload.get("agent") != P.GATE_AGENT_NAME:
            raise WorkstationError("unavailable", f"Something answered at {self.base}, but it is "
                                                  "not the workstation's network gate.")
        return payload

    async def set_mode(self, mode: str) -> Dict:
        payload = await self._call("mode", body={"mode": mode})
        return payload


__all__ = ["CertificatePinMismatch", "NetGateClient", "SOURCE_ENVIRONMENT", "SOURCE_NONE",
           "SOURCE_PAIRING", "SOURCE_SETTING", "URL_ENV", "WorkstationClient", "WorkstationError",
           "WorkstationUnreachable",  # `B978`, added
           "account_for", "cert_fingerprint", "configured_base", "configured_pin", "configured_token",
           "enabled", "from_settings", "gate_for", "gate_token_path", "normalise_pin",
           "pairing_token_path", "parse_base", "resolve_base", "resolve_gate", "resolve_token"]
