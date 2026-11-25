# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one DNS-pinned HTTP transport every SSRF-guarded fetch sends through.

`B2170`. Four modules carried their own copy of this: the agent's `web_fetch`
(`src/outbound_fetch.py`, sync), webhook delivery (`src/webhook_manager.py`,
async), an integration's `api_call` (`src/integrations.py`, async) and the
skill importer (`services/memory/skill_importer.py`, sync). They had drifted:
two verified certificates against certifi's bundle (or `SSL_CERT_FILE` when
set), two against the system's store, so with no `SSL_CERT_FILE` a CA that only
one of the two stores held verified for half the product and failed for the
other half — a corporate CA installed in the system store let webhooks and
fetches through and refused integrations. The owner's pick (`D-2026-11-24-02`): one
trust store for all of them, certifi plus `SSL_CERT_FILE` / `SSL_CERT_DIR` —
the same trust the default `httpx` client builds — and one transport.

What the transport holds (`FORBIDDEN.md` Part 2, "the five SSRF validators +
pinned-IP transports"): the TCP connect goes only to addresses the caller's
SSRF check already approved, in order, within one shared connect budget. The
request URL passes through unchanged, so TLS SNI and the ``Host`` header stay
the original hostname; only the socket destination is pinned, which closes the
DNS-rebinding window between the check and the connect. HTTP/1.1 unless a
caller asks for HTTP/2.
"""

from __future__ import annotations

import ipaddress
import time
from typing import Iterable, List, Optional, Sequence, Union, cast

import httpcore
import httpx

Address = ipaddress._BaseAddress
Addresses = Union[Address, Sequence[Address]]


def pinned_trust():
    """The trust every pinned transport verifies against: what `httpx`'s own
    default client builds with `trust_env` on — `SSL_CERT_FILE` when set, else
    `SSL_CERT_DIR`, else certifi's bundle — and never the system store alone,
    which is what `ssl.create_default_context()` would give. Never
    `verify=False`."""
    return httpx.create_ssl_context()


# httpcore raises its own exception hierarchy; map the ones a request can
# surface back to their httpx equivalents so callers' `except httpx.*` blocks
# (and `sanitize_error`) behave exactly as they would with the default
# transport. Looked up by exact type.
HTTPCORE_TO_HTTPX_EXC = {
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


def _addresses(ips: Addresses) -> List[Address]:
    """One approved address or several, in order."""
    if isinstance(ips, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return [ips]
    return list(ips)


def _address_list(ips: Addresses) -> List[str]:
    """The approved addresses as connect targets, in order."""
    return [str(ip) for ip in _addresses(ips)]


def _no_address() -> httpcore.ConnectError:
    return httpcore.ConnectError("no validated address available")


def _core_request(request: httpx.Request) -> httpcore.Request:
    return httpcore.Request(
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


def _mapped(exc: Exception) -> Optional[Exception]:
    mapped = HTTPCORE_TO_HTTPX_EXC.get(type(exc))
    return mapped(str(exc)) if mapped is not None else None


class PinnedBackend(httpcore.NetworkBackend):
    """Sync network backend that connects only to the pre-validated IPs, in
    order. Every address came out of the caller's one SSRF resolution, so moving
    to the next after a connect failure is not re-resolution — it is ordinary
    multi-address fallback within the set the guard approved. One shared
    connect budget: N dead addresses cannot stretch the connect to N × timeout."""

    def __init__(self, ips: Addresses):
        self._ips = _address_list(ips)
        self._real = httpcore.SyncBackend()

    def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                    local_address: str | None = None, socket_options=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        last_exc: Optional[Exception] = None
        for ip in self._ips:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                return self._real.connect_tcp(ip, port, remaining, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_exc = exc
                if deadline is not None and time.monotonic() >= deadline:
                    break
        raise last_exc if last_exc is not None else _no_address()

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return self._real.connect_unix_socket(path, timeout, socket_options)

    def sleep(self, seconds: float) -> None:
        return self._real.sleep(seconds)


class PinnedAsyncBackend(httpcore.AsyncNetworkBackend):
    """`PinnedBackend`, for an async pool."""

    def __init__(self, ips: Addresses):
        self._ips = _address_list(ips)
        self._real = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None,
                          socket_options=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        last_exc: Optional[Exception] = None
        for ip in self._ips:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                return await self._real.connect_tcp(ip, port, remaining, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_exc = exc
                if deadline is not None and time.monotonic() >= deadline:
                    break
        raise last_exc if last_exc is not None else _no_address()

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return await self._real.connect_unix_socket(path, timeout, socket_options)

    async def sleep(self, seconds: float) -> None:
        return await self._real.sleep(seconds)


class PinnedTransport(httpx.BaseTransport):
    """Sync httpx transport pinned to pre-resolved IP(s). Uses only public
    `httpcore` / `httpx` APIs. `max_bytes` caps the body while it streams; over
    it, `too_large(max_bytes)` is raised (a subclass names its own error)."""

    def __init__(self, ips: Addresses, *, http2: bool = False, max_bytes: Optional[int] = None):
        self._pinned_ips = _addresses(ips)
        self._max_bytes = max_bytes
        self._pool = httpcore.ConnectionPool(
            ssl_context=pinned_trust(),
            http1=True,
            http2=http2,
            network_backend=PinnedBackend(ips),
        )

    def too_large(self, limit: int) -> Exception:
        return httpx.DecodingError(f"download larger than {limit:,} bytes")

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        core_response = None
        try:
            core_response = self._pool.handle_request(_core_request(request))
            stream = cast(Iterable[bytes], core_response.stream)
            if self._max_bytes is None:
                content = b"".join(stream)
            else:
                chunks, got = [], 0
                for chunk in stream:
                    got += len(chunk)
                    if got > self._max_bytes:
                        raise self.too_large(self._max_bytes)
                    chunks.append(chunk)
                content = b"".join(chunks)
        except Exception as exc:
            mapped = _mapped(exc)
            if mapped is not None:
                raise mapped from exc
            raise
        finally:
            if core_response is not None:
                core_response.close()
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            content=content,
            extensions=core_response.extensions,
        )

    def close(self) -> None:
        self._pool.close()


class PinnedAsyncTransport(httpx.AsyncBaseTransport):
    """Async httpx transport pinned to pre-resolved IP(s); HTTP/1.1."""

    def __init__(self, ips: Addresses):
        self._pinned_ips = _addresses(ips)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=pinned_trust(),
            http1=True,
            http2=False,
            network_backend=PinnedAsyncBackend(ips),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            core_resp = await self._pool.handle_async_request(_core_request(request))
            content = b"".join([chunk async for chunk in core_resp.aiter_stream()])
            await core_resp.aclose()
        except Exception as exc:
            mapped = _mapped(exc)
            if mapped is not None:
                raise mapped from exc
            raise
        return httpx.Response(
            status_code=core_resp.status,
            headers=core_resp.headers,
            content=content,
            extensions=core_resp.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()
