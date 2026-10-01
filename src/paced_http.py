# SPDX-License-Identifier: AGPL-3.0-or-later
"""One line that is polite. `P15-06`.

The audit behind `P15` inventoried fifty modules making outbound calls and
found that pacing was the exception rather than the rule. The reason is not
carelessness: routing a call through the limiter by hand is three statements —
work out the host, acquire, and remember to feed the response back — and the
third is the one that gets forgotten, silently, because forgetting it costs
nothing until a provider starts saying 429 and nobody is listening.

So this module is the boring wrapper that makes the polite version shorter than
the impolite one:

    from src import paced_http
    r = await paced_http.get(url, headers=...)          # async
    r = paced_http.get_sync(url, headers=...)           # sync

Each call does the whole ritual: pace by the destination's policy, make the
request, and hand the response back to the limiter so a `429`, a rate-limited
`403`, or an `X-RateLimit-Remaining: 0` becomes a cooldown instead of the next
request.

WHAT THIS IS NOT FOR.

`src/outbound_fetch.py` handles USER-SUPPLIED urls: SSRF classification, DNS
pinning, per-hop re-resolution, body budgets. It is a different problem and a
much heavier one. This module is for the calls a developer wrote down — a known
third-party API, the operator's own model server — where the address is not
attacker-controlled and the only question is politeness. Sending those through
the SSRF machinery would buy nothing and cost a resolution per request.

A LOCAL HOST COSTS NOTHING HERE.

`rate_limiter.LOCAL_POLICY` paces the operator's own machines at zero, so
wrapping a call to `localhost:11434` is free (`D-2026-09-01-03`: internal comms
are not a threat model). That matters because it removes the only honest
argument for leaving a call unwrapped — "it is local, the limiter would just
slow it down". It will not.
"""
import ipaddress
import logging
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15.0


# ── `B982`: a range in `NO_PROXY` ─────────────────────────────────────────────
#
# httpx reads names and single addresses in `NO_PROXY`, not ranges: measured
# with httpx 0.28.1, `NO_PROXY=…,10.0.0.0/8,192.168.0.0/16` with `HTTPS_PROXY`
# set sent `https://10.1.2.3:7040` and `https://192.168.1.50` to the proxy (it
# turns `10.0.0.0/8` into a host pattern that no URL's host ever equals). curl
# (7.86+) and `requests` read a range as a range, for a host written as an
# address — so an operator who wrote one meant it, and on a host with a
# corporate proxy a workstation or any TLS service on the LAN was reached
# through the proxy, or not at all.
#
# The fix keeps the environment's word, not Pantheon's: a destination goes
# direct when, and only when, a proxy is configured for its scheme AND
# `NO_PROXY` names a range its address is in — read with the same
# `urllib.request.getproxies` httpx reads it with, so the two cannot disagree
# about what the variables say (`Law 7`). Nothing here decides on its own that
# a private address skips a proxy the operator configured. It is said to httpx
# in httpx's own words (`mounts={"all://<host>": None}`, its "no proxy" entry),
# so the request is still made by the same client, through this module's pacing.
#
# A host written as a NAME is not looked up here (curl's and `requests`' rule);
# a caller that has already resolved it — the workstation client, which must
# know every address of a name before it sends a token over plain http — passes
# the addresses, and the name goes direct when every one of them is in a range.

def _proxy_settings() -> Dict[str, str]:
    from urllib.request import getproxies
    try:
        return dict(getproxies())
    except Exception:  # noqa: BLE001 — an unreadable environment names no proxy
        return {}


def no_proxy_ranges() -> Tuple[Any, ...]:
    """The address ranges `NO_PROXY` (or `no_proxy`) names — the entries with a
    `/` that parse as a network; names, single addresses and `*` are httpx's."""
    out = []
    for item in str(_proxy_settings().get("no") or "").split(","):
        item = item.strip()
        if "/" not in item:
            continue
        try:
            out.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(out)


def direct_mounts(url: str, *, addresses: Iterable[str] = ()) -> Dict[str, None]:
    """httpx `mounts` that send `url`'s host direct, when a proxy is configured
    for its scheme and `NO_PROXY` puts its address in a range; `{}` otherwise
    (the environment decides, as it always did). `addresses`: what a name was
    resolved to, by a caller that resolved it."""
    try:
        parts = urlsplit(str(url))
        host = parts.hostname or ""
    except ValueError:
        return {}
    settings = _proxy_settings()
    if not host or not (settings.get(parts.scheme) or settings.get("all")):
        return {}
    ranges = no_proxy_ranges()
    if not ranges:
        return {}
    try:
        ips = [ipaddress.ip_address(host)]
        literal = True
    except ValueError:
        literal = False
        ips = []
        for a in addresses:
            try:
                ips.append(ipaddress.ip_address(str(a).split("%", 1)[0]))
            except ValueError:
                return {}
    if not ips or not all(any(ip in net for net in ranges) for ip in ips):
        return {}
    pattern = f"[{host}]" if literal and ips[0].version == 6 else host
    return {f"all://{pattern}": None}


# ── `B1013`: an entry in `NO_PROXY` httpx cannot read ─────────────────────────
#
# Measured with httpx 0.28.1: `NO_PROXY=localhost,fd00::/8` (`no_proxy` unset or
# the same) makes `httpx.Client()` and `httpx.AsyncClient()` raise `InvalidURL:
# Invalid port: ':'` at construction — `get_environment_proxies` turns `fd00::/8`
# into the pattern `all://[fd00::/8]`, which its own URL parser refuses — whether
# or not a proxy is set. So every client that reads the environment failed:
# model calls, the workstation, `httpx.get`, the MCP SDK's own clients. A single
# IPv6 address is read fine (`::1` becomes `all://[::1]`): the sandbox this was
# measured in has `::1` and `::` in its `NO_PROXY`, and its clients build.
#
# So httpx's reader is wrapped once, at start (`guard_environment_reader`): what
# it returns passes through `readable_environment_proxies`, which keeps every
# proxy and every entry httpx can parse, and leaves out a no-proxy entry its own
# `URLPattern` refuses — said by name in the log. Nothing the operator wrote is
# dropped: the environment itself is untouched (a command in the agent's shell,
# curl, still reads the range), and `no_proxy_ranges` reads `urllib`, not httpx,
# so `direct_mounts` still sends an address in that range direct. What httpx
# loses is a pattern it could never have matched: it reads no range as a range
# (`B982`).

_HTTPX_READER = None   # httpx's own `get_environment_proxies`, wrapped
_SAID: set = set()


def _httpx_reader():
    from httpx import _utils
    return _HTTPX_READER or _utils.get_environment_proxies


def _unreadable(key: str) -> bool:
    from httpx._utils import URLPattern
    try:
        URLPattern(key)
    except Exception:  # noqa: BLE001 — whatever httpx refuses, it refuses at construction
        return True
    return False


def _entry(key: str) -> str:
    """The `NO_PROXY` entry a pattern came from, as written there."""
    host = key.split("://", 1)[-1]
    return host[1:-1] if host.startswith("[") and host.endswith("]") else host


def readable_environment_proxies() -> Dict[str, Optional[str]]:
    """httpx's reading of the environment's proxies, less any no-proxy entry
    httpx's own URL parser refuses (`B1013`). Installed in httpx's place by
    `guard_environment_reader`."""
    out: Dict[str, Optional[str]] = {}
    for key, proxy in _httpx_reader()().items():
        if proxy is None and _unreadable(key):
            if key not in _SAID:
                _SAID.add(key)
                logger.warning("NO_PROXY entry %r is one httpx cannot read; it is kept from "
                               "httpx (B1013), not from the environment.", _entry(key))
            continue
        out[key] = proxy
    return out


def _unreadable_keys() -> list:
    return [key for key, proxy in _httpx_reader()().items()
            if proxy is None and _unreadable(key)]


def unreadable_no_proxy() -> Tuple[str, ...]:
    """The `NO_PROXY` entries httpx cannot read, as written there."""
    return tuple(_entry(key) for key in _unreadable_keys())


def guard_environment_reader() -> Tuple[str, ...]:
    """Put `readable_environment_proxies` where httpx reads the environment from
    (once; again is a no-op), and say at start which entries it keeps from httpx.
    Called by `app.py` before anything builds a client. Returns those entries."""
    global _HTTPX_READER
    try:
        from httpx import _client, _utils
    except ImportError:
        return ()
    if not callable(getattr(_client, "get_environment_proxies", None)):
        # A different httpx: say so, rather than pretend the guard is in place.
        logger.warning("httpx has no get_environment_proxies to guard (B1013); an IPv6 range "
                       "in NO_PROXY may stop every client from being built.")
        return ()
    if _HTTPX_READER is None:
        _HTTPX_READER = _utils.get_environment_proxies
    _client.get_environment_proxies = readable_environment_proxies
    keys = _unreadable_keys()
    left_out = tuple(_entry(key) for key in keys)
    if any(key not in _SAID for key in keys):
        _SAID.update(keys)
        logger.warning(
            "NO_PROXY holds %s, which httpx cannot read (an IPv6 range): kept from httpx so "
            "its clients can be built (B1013). Where Pantheon reads NO_PROXY ranges itself "
            "(paced_http.direct_mounts) an address in it still goes direct; a command in a "
            "shell reads NO_PROXY as it is.",
            ", ".join(left_out))
    return left_out


def _host(url: str) -> str:
    from src.rate_limiter import host_of
    return host_of(url)


def _observe(host: str, response) -> None:
    """Feed the response back. A 200 is how a host says the cooldown is over,
    so this runs on success as well as failure — that is the half that gets
    dropped when the ritual is written out by hand."""
    from src.rate_limiter import outbound
    try:
        status = int(getattr(response, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return
    headers = {}
    try:
        headers = dict(getattr(response, "headers", {}) or {})
    except Exception:
        headers = {}
    body_hint = ""
    if status in (403, 429):
        # Only read the body when the status suggests a limit: GitHub's primary
        # rate limit is a 403 whose BODY is the only place it says so, and
        # reading every response's text to find that would materialise bodies
        # this module has no other reason to touch.
        try:
            body_hint = (response.text or "")[:200]
        except Exception:
            body_hint = ""
    outbound.observe(host, status, headers, body_hint=body_hint)


async def request(method: str, url: str, *, authenticated: bool = False,
                  timeout: float = _DEFAULT_TIMEOUT, client=None, **kwargs) -> Any:
    """Paced async request. Raises `OutboundRateLimited` when the host is blocked."""
    import httpx
    from src.rate_limiter import outbound

    host = _host(url)
    await outbound.acquire_async(host, authenticated=authenticated)
    owns = client is None
    if owns:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                   mounts=direct_mounts(url) or None)  # `B982`
    try:
        response = await client.request(method, url, **kwargs)
    except Exception:
        # A transport failure is not a rate limit, but hammering a host that is
        # refusing connections is its own kind of impolite.
        outbound.note_failure(host)
        raise
    finally:
        if owns:
            await client.aclose()
    _observe(host, response)
    return response


async def get(url: str, **kwargs) -> Any:
    return await request("GET", url, **kwargs)


async def post(url: str, **kwargs) -> Any:
    return await request("POST", url, **kwargs)


def request_sync(method: str, url: str, *, authenticated: bool = False,
                 timeout: float = _DEFAULT_TIMEOUT, client=None, **kwargs) -> Any:
    """Paced sync request, for the `asyncio.to_thread` call sites."""
    import httpx
    from src.rate_limiter import outbound

    host = _host(url)
    outbound.acquire(host, authenticated=authenticated)
    owns = client is None
    if owns:
        client = httpx.Client(timeout=timeout, follow_redirects=True,
                              mounts=direct_mounts(url) or None)  # `B982`
    try:
        response = client.request(method, url, **kwargs)
    except Exception:
        outbound.note_failure(host)
        raise
    finally:
        if owns:
            client.close()
    _observe(host, response)
    return response


def get_sync(url: str, **kwargs) -> Any:
    return request_sync("GET", url, **kwargs)


def post_sync(url: str, **kwargs) -> Any:
    return request_sync("POST", url, **kwargs)
