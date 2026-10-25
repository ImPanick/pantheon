# SPDX-License-Identifier: AGPL-3.0-or-later
"""SSRF-guarded synchronous HTTP fetching primitives.

This module owns outbound URL classification, one-resolution-per-hop DNS
pinning, redirects, and response-body budgets.  It deliberately has no search
or content-extraction dependencies so callers outside search can reuse the
same transport boundary.
"""

from __future__ import annotations

import ipaddress
import socket
import ssl
from typing import Callable, Iterable, Optional, cast
from urllib.parse import urljoin, urlparse

import httpcore
import httpx

from src.constants import WEB_FETCH_HARD_MAX_BYTES, WEB_FETCH_SOFT_MAX_BYTES


_PRIVATE_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

# `P16-20` (`D-2026-10-25-02`). The local network the agent may be allowed to
# reach: private ranges and Tailscale's CGNAT (`100.64/10`, which CPython calls
# "shared", not "private", so it is named here on purpose). Loopback is NOT in
# this set — reaching this machine's own ports is a different question
# (`FORBIDDEN.md` Part 2), and stays blocked whatever the LAN setting says.
_LAN_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fc00::/7"),
)


def _lan_reach_on() -> bool:
    """`agent_lan_reach` (default on): whether this install lets fetches reach
    the LAN. Off for a shared box that should stay on the public internet. On a
    read failure it defaults on — local-first is the shipped intent, and a
    transient settings hiccup should not break LAN fetches that are the norm."""
    try:
        from src.settings import get_setting
        from src.env_flags import tool_arg_truthy
        return tool_arg_truthy(get_setting("agent_lan_reach", True), default=True)
    except Exception:
        return True


def _in_lan(addr: ipaddress._BaseAddress) -> bool:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return any(addr in net for net in _LAN_NETWORKS)


def _always_blocked(addr: ipaddress._BaseAddress) -> bool:
    """What no setting lets a fetch reach: loopback, link-local (cloud
    metadata), multicast, reserved and the unspecified address."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
        or addr in ipaddress.ip_network("0.0.0.0/8")
    )


def _is_private_address(addr: ipaddress._BaseAddress, *, allow_lan: Optional[bool] = None) -> bool:
    """Whether a fetch must be refused this address. `allow_lan` defaults to the
    `agent_lan_reach` setting; pass it explicitly to classify without a read.

    Loopback and metadata are always refused. The LAN is refused only when LAN
    reach is off — the owner's authorization (`D-2026-10-25-02`) is exactly that
    an agent may read a router page or a LAN service by URL, so with it on a
    private LAN IP is reachable and a public IP always was."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if _always_blocked(addr):
        return True
    if _in_lan(addr) or addr.is_private:
        if allow_lan is None:
            allow_lan = _lan_reach_on()
        return not allow_lan
    return False


def _resolve_hostname_ips(hostname: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except Exception:
        return []
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0]))
        except Exception:
            continue
    return out


def _public_http_url(
    url: str,
    *,
    resolver: Callable[[str], list[ipaddress._BaseAddress]] | None = None,
) -> bool:
    resolver = resolver or _resolve_hostname_ips
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").strip()
        if not host:
            return False
        lower = host.lower()
        # Always off, whatever the LAN setting: this machine itself and the
        # cloud-metadata names. `.local`, `.lan`, `.internal`, `.intranet` are
        # NOT pre-blocked any more (`P16-20`) — a name on the person's own LAN
        # is exactly what they want reached; it is judged by the address it
        # resolves to, so a name that resolves to loopback or does not resolve
        # at all is still refused.
        if lower in ("localhost", "metadata", "metadata.google.internal") or lower.endswith(".localhost"):
            return False
        allow_lan = _lan_reach_on()
        try:
            addrs = [ipaddress.ip_address(host)]
        except ValueError:
            addrs = resolver(host)
        if not addrs or any(_is_private_address(a, allow_lan=allow_lan) for a in addrs):
            return False
        return _untrusted_refusal(host, addrs) is None
    except Exception:
        return False


def _untrusted_refusal(host: str, addrs) -> Optional[str]:
    """`D-2026-10-25-03`. A network the person marked untrusted is listed for
    the agent but never connected to on its behalf — checked against the name
    and every address it resolved to. None when nothing is declared untrusted."""
    try:
        from src.networks import untrusted_refusal
    except ImportError:
        return None
    return untrusted_refusal(host, *[str(a) for a in addrs])


def _refuse_untrusted(host: str, addrs) -> None:
    refusal = _untrusted_refusal(host, addrs)
    if refusal:
        raise httpx.RequestError(f"Blocked: {refusal}")


def _resolve_public_ips(
    url: str,
    *,
    resolver: Callable[[str], list[ipaddress._BaseAddress]] | None = None,
) -> list[ipaddress._BaseAddress]:
    resolver = resolver or _resolve_hostname_ips
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise httpx.RequestError(f"Blocked non-public URL: {url}")
    host = (parsed.hostname or "").strip().lower()
    # `P16-16` — network scope, before anything else looks at this host.
    # No-op with nothing declared or no scope in force.
    try:
        from src.networks import host_allowed, network_for, current_scope
        if not host_allowed(host):
            where = network_for(host)
            raise httpx.RequestError(
                f"Blocked by network scope: {host} is in "
                f"{'network ' + repr(where) if where else 'no declared network'}, "
                f"and this run is scoped to {sorted(current_scope() or [])}"
            )
    except ImportError:
        pass
    if host in ("localhost", "metadata", "metadata.google.internal"):
        raise httpx.RequestError(f"Blocked non-public hostname: {host}")
    try:
        ip = ipaddress.ip_address(host)
        if _is_private_address(ip):
            raise httpx.RequestError(f"Blocked non-public IP literal: {host}")
        _refuse_untrusted(host, [ip])
        return [ip]
    except httpx.RequestError:
        raise
    except ValueError:
        pass
    addrs = resolver(host)
    if not addrs or any(_is_private_address(a) for a in addrs):
        raise httpx.RequestError(f"Blocked non-public URL: {url}")
    _refuse_untrusted(host, addrs)
    return addrs


class _PinnedBackend(httpcore.NetworkBackend):
    """Network backend that connects to a pre-resolved IP."""

    def __init__(self, ip: ipaddress._BaseAddress):
        self._ip = str(ip)
        self._real = httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        return self._real.connect_tcp(
            self._ip, port, timeout, local_address, socket_options
        )

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return self._real.connect_unix_socket(path, timeout, socket_options)

    def sleep(self, seconds: float) -> None:
        return self._real.sleep(seconds)


_HTTPCORE_TO_HTTPX_EXC = {
    httpcore.ConnectError: httpx.ConnectError,
    httpcore.ConnectTimeout: httpx.ConnectTimeout,
    httpcore.LocalProtocolError: httpx.LocalProtocolError,
    httpcore.NetworkError: httpx.NetworkError,
    httpcore.PoolTimeout: httpx.PoolTimeout,
    httpcore.ProtocolError: httpx.ProtocolError,
    httpcore.ProxyError: httpx.ProxyError,
    httpcore.ReadError: httpx.ReadError,
    httpcore.ReadTimeout: httpx.ReadTimeout,
    httpcore.RemoteProtocolError: httpx.RemoteProtocolError,
    httpcore.TimeoutException: httpx.TimeoutException,
    httpcore.UnsupportedProtocol: httpx.UnsupportedProtocol,
    httpcore.WriteError: httpx.WriteError,
    httpcore.WriteTimeout: httpx.WriteTimeout,
}


class _PinnedTransport(httpx.BaseTransport):
    """Transport that pins every TCP connect to a pre-resolved IP."""

    def __init__(self, ip: ipaddress._BaseAddress, *, http2: bool = False):
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(),
            http1=True,
            http2=http2,
            network_backend=_PinnedBackend(ip),
        )

    def __enter__(self):
        self._pool.__enter__()
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None) -> None:
        self._pool.__exit__(exc_type, exc_value, traceback)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        httpcore_req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            httpcore_resp = self._pool.handle_request(httpcore_req)
            content = b"".join(cast(Iterable[bytes], httpcore_resp.stream))
        except Exception as exc:
            mapped = _HTTPCORE_TO_HTTPX_EXC.get(type(exc))
            if mapped is not None:
                raise mapped(str(exc)) from exc
            raise

        return httpx.Response(
            status_code=httpcore_resp.status,
            headers=httpcore_resp.headers,
            content=content,
            extensions=httpcore_resp.extensions,
        )

    def close(self) -> None:
        self._pool.close()


class BodyTooLargeError(Exception):
    """The server declared a body larger than the hard fetch ceiling."""

    def __init__(self, url: str, declared_bytes: int):
        self.url = url
        self.declared_bytes = declared_bytes
        super().__init__(
            f"response body is {declared_bytes:,} bytes, over the "
            f"{WEB_FETCH_HARD_MAX_BYTES:,}-byte hard cap"
        )


class _CappedFetch:
    """Result of a size-capped streaming GET."""

    __slots__ = (
        "status_code",
        "headers",
        "content",
        "truncated",
        "declared_bytes",
        "encoding",
        "url",
    )

    def __init__(
        self,
        status_code,
        headers,
        content,
        truncated,
        declared_bytes,
        encoding,
        url,
    ):
        self.status_code = status_code
        self.headers = headers
        self.content = content
        self.truncated = truncated
        self.declared_bytes = declared_bytes
        self.encoding = encoding
        self.url = url

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", self.url)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code} for {self.url}",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )


def _get_public_url(
    url: str,
    headers: dict,
    timeout: int,
    max_redirects: int = 5,
    max_bytes: int | None = None,
    *,
    resolve_public_ips: Callable[[str], list[ipaddress._BaseAddress]] | None = None,
    transport_factory: Callable[[ipaddress._BaseAddress], httpx.BaseTransport] | None = None,
) -> _CappedFetch:
    """Capped streaming GET with SSRF-guarded, DNS-pinned redirects."""
    resolve_public_ips = resolve_public_ips or _resolve_public_ips
    transport_factory = transport_factory or _PinnedTransport
    try:
        from src.runtime_limits import unlimited as _unlimited
        _no_cap = _unlimited()
    except Exception:
        _no_cap = False
    _ceiling = (1 << 62) if _no_cap else WEB_FETCH_HARD_MAX_BYTES
    _default = (1 << 62) if _no_cap else WEB_FETCH_SOFT_MAX_BYTES
    cap = min(max_bytes or _default, _ceiling)
    current = url
    for _ in range(max_redirects + 1):
        ips = resolve_public_ips(current)
        req_headers = dict(headers or {})
        req_headers["Accept-Encoding"] = "identity"

        with httpx.Client(
            headers=req_headers,
            timeout=timeout,
            follow_redirects=False,
            transport=transport_factory(ips[0]),
        ) as client:
            with client.stream("GET", current) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        return _CappedFetch(
                            response.status_code,
                            response.headers,
                            b"",
                            False,
                            None,
                            response.encoding,
                            str(response.url),
                        )
                    current = urljoin(str(response.url), location)
                    continue

                enc = (response.headers.get("content-encoding") or "").strip().lower()
                if enc and enc != "identity":
                    raise httpx.RequestError(
                        f"Refusing compressed response (Content-Encoding: {enc}) after "
                        "requesting identity: cannot bound decoded body size",
                        request=httpx.Request("GET", current),
                    )

                declared = None
                raw_len = response.headers.get("content-length")
                if raw_len and raw_len.isdigit():
                    declared = int(raw_len)

                if declared is not None and declared > _ceiling:
                    raise BodyTooLargeError(current, declared)

                chunks = []
                read = 0
                truncated = False
                for chunk in response.iter_bytes():
                    read += len(chunk)
                    if read > cap:
                        keep = cap - (read - len(chunk))
                        if keep > 0:
                            chunks.append(chunk[:keep])
                        truncated = True
                        break
                    chunks.append(chunk)

                return _CappedFetch(
                    response.status_code,
                    response.headers,
                    b"".join(chunks),
                    truncated,
                    declared,
                    response.encoding,
                    str(response.url),
                )

    raise httpx.RequestError(
        "Too many redirects", request=httpx.Request("GET", current)
    )
