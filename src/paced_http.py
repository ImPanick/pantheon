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
from typing import Any, Optional

_DEFAULT_TIMEOUT = 15.0


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
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
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
        client = httpx.Client(timeout=timeout, follow_redirects=True)
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
