"""Push the same numbers the scrape serves, to an address the operator chose.

`P16-19`, the push half of `P16-12`. The pull half covers the ordinary case:
Prometheus reaches in and asks. Push is the case pull cannot reach — Pantheon
behind NAT, or on one of `P16-16`'s parallel networks, where the collector has
no route inward. Same readings, opposite direction.

THE SHIPPED ENDPOINT IS EMPTY, AND EMPTINESS IS THE FEATURE.

`Law 16` clause 4 as the owner amended it: *"telemetry is fine, but 'phone home'
to an external destination is not allowed. if the user wants to establish their
own telemetry endpoint, they can bypass this law and do so."* So this module is
the first legitimate outbound destination in the product, and the thing that
keeps it the operator's rather than ours is not a promise in a docstring — it is
`.pantheon/check-destinations.py`, which fails the build if `otlp_endpoint`
ships with anything in it. `P16-13` armed that guard before this row existed
precisely so the answer was already no by the time somebody wrote this file.

There is no separate on/off switch, deliberately (`Law 14`). The address is the
switch: no address, no push. A second boolean beside it would be a second thing
that can disagree with the first, and the failure it enables — enabled true,
address blank, operator waiting for data — is worse than the one it prevents.

ONE SET OF COLLECTORS, TWO WIRE FORMATS.

Every number here comes from `metrics_export.collect_metrics()`, which is the
scrape's own assembler. Writing a second set of collectors for a second
transport is how two exporters start quietly disagreeing about what the system
did, and then a person has to work out which one is lying.

WHY NOT THE OPENTELEMETRY SDK.

The payload is a JSON document with about six nested keys, and it is written
out below in forty lines. The SDK brings a dependency tree, a background
processor with its own threading model, and — the part that matters here — a
constructor whose default endpoint is a real address. In a product whose stated
direction is *drop external dependence*, taking all of that to serialise a dict
is the wrong trade. `httpx` is already a dependency.

THE JSON DETAILS THAT ARE EASY TO GET WRONG, AND SILENT WHEN YOU DO.

  * `timeUnixNano` is a **uint64**, and proto3's JSON mapping renders 64-bit
    integers as **strings**. A nanosecond timestamp is ~1.8e18, far past what a
    JSON number survives intact, so emitting it unquoted is the classic OTLP
    bug: some collectors reject the batch, others truncate the timestamp and
    plot your data in 1970.
  * Every value goes out as `asDouble`. `asInt` is int64 and would need the
    same string treatment; since `P16-12` decided everything is a gauge, a
    double is both correct and one fewer place to make that mistake.
  * Attributes are a **list of `{key, value}`**, not an object. A dict is
    accepted by nothing and rejected differently by everything.
  * Samples sharing a name are **one metric with several data points**. Emitting
    them as separate metric entries is what a naive loop produces and what makes
    a collector report a duplicate.
  * Label values are **not** run through the Prometheus escaper. `json.dumps`
    escapes JSON; doing both would put a literal backslash-n into the value.

A 200 IS NOT PROOF OF DELIVERY. OTLP/HTTP answers a partially-rejected batch
with `200` and a `partialSuccess` body, so the response is read rather than
merely checked, and rejected points are counted and reported.
"""
import asyncio
import json
import logging
import random
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

# OTLP/HTTP's fixed path for metrics. An operator may give either the base or
# the full signal URL; both are common, and OTEL's own env vars distinguish them
# (`..._ENDPOINT` vs `..._METRICS_ENDPOINT`). Guessing wrong costs a 404 the
# operator has no way to see, so both are accepted.
METRICS_PATH = "/v1/metrics"

DEFAULT_INTERVAL_SECONDS = 60
MIN_INTERVAL_SECONDS = 10
JITTER_FRACTION = 0.1          # `P15-10`: nothing recurring fires on a boundary
REQUEST_TIMEOUT_SECONDS = 10.0

# A ceiling on one push. Not a policy about size — a guard against a pathological
# label cardinality turning a metrics tick into a multi-megabyte POST at whatever
# the interval is.
MAX_DATA_POINTS = 5000

_status: Dict[str, Any] = {
    "configured": False,
    "last_success_monotonic": None,
    "last_attempt_monotonic": None,
    "consecutive_failures": 0,
    "last_error": "",
    "points_last_push": 0,
    "points_rejected": 0,
    "points_dropped": 0,
}


class OTLPNotConfigured(Exception):
    """No endpoint. Not an error — the shipped state."""


def _get(key: str, default: Any) -> Any:
    try:
        from src.settings import get_setting
        return get_setting(key, default)
    except Exception as e:                              # settings unavailable
        logger.debug("otlp: could not read %s: %s", key, e)
        return default


def endpoint_url() -> str:
    """The operator's collector, normalised, or `""`.

    Empty is the shipped state and every caller treats it as *off*. The env
    layer beneath it is genuinely reachable because the default is falsy — a
    truthy default would make `PANTHEON_OTLP_ENDPOINT` dead code, which is `H06`
    and `B20` and is why the destination-shaped keys must ship empty for two
    separate reasons rather than one.
    """
    import os
    raw = (_get("otlp_endpoint", "") or "").strip()
    if not raw:
        raw = (os.environ.get("PANTHEON_OTLP_ENDPOINT") or "").strip()
    if not raw:
        return ""
    return normalise_endpoint(raw)


def normalise_endpoint(raw: str) -> str:
    """Append the signal path unless the operator already gave it.

    Raises `ValueError` on anything that is not an absolute http(s) URL. A
    collector address that silently does not work is the failure this whole row
    exists to make visible, so a malformed one is loud at the earliest point.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("empty endpoint")
    parts = urlparse(raw)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"endpoint scheme must be http or https, got {parts.scheme!r}")
    if not parts.netloc:
        raise ValueError("endpoint has no host")
    path = parts.path or ""
    if path.endswith("/"):
        path = path[:-1]
    if not path.endswith(METRICS_PATH):
        path = path + METRICS_PATH
    return urlunparse((parts.scheme, parts.netloc, path, "", parts.query, ""))


def _headers() -> Dict[str, str]:
    """Operator-supplied headers, plus the content type.

    Values are never logged anywhere in this module: a collector that wants an
    API key wants it here, and a metrics exporter that prints its own
    credentials into the application log has moved the secret somewhere with
    weaker handling than the settings store it came from.
    """
    out = {"Content-Type": "application/json"}
    configured = _get("otlp_headers", {}) or {}
    if isinstance(configured, dict):
        for k, v in configured.items():
            name = str(k).strip()
            if name and name.lower() != "content-type":
                out[name] = str(v)
    return out


def _resource_attributes() -> List[Dict[str, Any]]:
    attrs: Dict[str, str] = {"service.name": "pantheon"}
    try:
        from src.constants import APP_VERSION
        attrs["service.version"] = str(APP_VERSION)
    except Exception:
        pass
    configured = _get("otlp_resource_attributes", {}) or {}
    if isinstance(configured, dict):
        for k, v in configured.items():
            key = str(k).strip()
            if key:
                attrs[key] = str(v)
    return [_attr(k, v) for k, v in sorted(attrs.items())]


def _attr(key: str, value: Any) -> Dict[str, Any]:
    return {"key": str(key), "value": {"stringValue": str(value)}}


def _numeric(value: Any) -> Optional[float]:
    """`None` for anything that is not a finite number.

    Deliberately not `float(value)` in a bare try: `float("nan")` succeeds and
    `NaN` is not valid JSON — `json.dumps` writes the bare token `NaN`, which is
    a parse error at the collector for the whole batch. One bad sample must cost
    one sample.
    """
    if isinstance(value, bool):
        return float(value)
    if not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v


def build_payload(samples, metadata, *, now_ns: Optional[int] = None) -> Tuple[Dict[str, Any], int, int]:
    """`(payload, points, dropped)` in OTLP/HTTP+JSON's metrics shape.

    Samples sharing a name become one metric with several data points, which is
    what the format means by a metric and what keeps a collector from reporting
    a duplicate declaration.
    """
    ts = str(int(now_ns if now_ns is not None else time.time_ns()))
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    dropped = 0
    points = 0
    for name, value, labels in samples:
        number = _numeric(value)
        if number is None:
            dropped += 1
            continue
        if points >= MAX_DATA_POINTS:
            dropped += 1
            continue
        if name not in grouped:
            grouped[name] = []
            order.append(name)
        grouped[name].append({
            "attributes": [_attr(k, v) for k, v in sorted((labels or {}).items())],
            "timeUnixNano": ts,
            "asDouble": number,
        })
        points += 1

    metrics = []
    for name in order:
        _kind, help_text = metadata.get(name, ("gauge", ""))
        metrics.append({
            "name": name,
            "description": help_text or "",
            "gauge": {"dataPoints": grouped[name]},
        })

    payload = {
        "resourceMetrics": [{
            "resource": {"attributes": _resource_attributes()},
            "scopeMetrics": [{
                "scope": {"name": "pantheon.metrics_export"},
                "metrics": metrics,
            }],
        }]
    }
    return payload, points, dropped


def _rejected_points(body: str) -> int:
    """Points the collector took a `200` on and then threw away.

    OTLP/HTTP answers a partially-rejected batch with `200 OK` and a
    `partialSuccess` body. Checking the status alone reports success for a push
    that delivered nothing, which is the exact silence this row is about.
    """
    if not body:
        return 0
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return 0
    if not isinstance(parsed, dict):
        return 0
    partial = parsed.get("partialSuccess")
    if not isinstance(partial, dict):
        return 0
    try:
        return int(partial.get("rejectedDataPoints", 0) or 0)
    except (TypeError, ValueError):
        return 0


async def push_once(*, url: str = "", client=None) -> Dict[str, Any]:
    """Assemble one reading and POST it. Returns a small result dict.

    Paced by `P15`'s limiter like every other deliberate outbound call, and
    scope-checked by it against `P16-16`'s declared networks. A metrics push on
    a timer is the recurring outbound job that phase exists for: it is the one
    request in the product guaranteed to keep firing at a fixed rate whether or
    not anybody is watching.
    """
    import httpx
    from src.rate_limiter import outbound, host_of, OutboundRateLimited

    target = url or endpoint_url()
    if not target:
        raise OTLPNotConfigured("no otlp_endpoint configured")

    from src.metrics_export import collect_metrics
    samples, metadata = collect_metrics()
    payload, points, dropped = build_payload(samples, metadata)
    _status["points_dropped"] = dropped
    if not points:
        # Nothing to say. A push of an empty batch is a request that costs the
        # collector a parse and tells it nothing.
        return {"ok": True, "points": 0, "skipped": "no data points"}

    host = host_of(target)
    _status["last_attempt_monotonic"] = time.monotonic()
    try:
        await outbound.acquire_async(host, authenticated=bool(_get("otlp_headers", {})))
    except OutboundRateLimited as e:
        _status["last_error"] = f"limiter: {e}"
        return {"ok": False, "points": 0, "error": "rate limited"}

    body = json.dumps(payload)
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = await client.post(target, content=body, headers=_headers())
    except Exception as e:
        outbound.note_failure(host)
        _status["consecutive_failures"] += 1
        _status["last_error"] = f"{type(e).__name__}: {e}"
        logger.warning("otlp push to %s failed: %s: %s", host, type(e).__name__, e)
        return {"ok": False, "points": 0, "error": type(e).__name__}
    finally:
        if owns_client:
            await client.aclose()

    status = int(getattr(response, "status_code", 0) or 0)
    headers = dict(getattr(response, "headers", {}) or {})
    outbound.observe(host, status, headers)

    text = ""
    try:
        text = response.text or ""
    except Exception:
        text = ""

    if 200 <= status < 300:
        rejected = _rejected_points(text)
        _status["consecutive_failures"] = 0
        _status["last_success_monotonic"] = time.monotonic()
        _status["points_last_push"] = points
        _status["points_rejected"] = rejected
        _status["last_error"] = f"{rejected} data point(s) rejected" if rejected else ""
        if rejected:
            logger.warning("otlp collector %s accepted %d point(s) and rejected %d",
                           host, points - rejected, rejected)
        return {"ok": True, "points": points, "rejected": rejected, "status": status}

    _status["consecutive_failures"] += 1
    _status["last_error"] = f"HTTP {status}"
    # The body may echo back a header the operator configured; only the status
    # is logged for the same reason `_headers` values never are.
    logger.warning("otlp push to %s returned HTTP %s", host, status)
    return {"ok": False, "points": 0, "status": status, "error": f"HTTP {status}"}


def _interval_seconds() -> float:
    try:
        value = float(_get("otlp_interval_seconds", DEFAULT_INTERVAL_SECONDS)
                      or DEFAULT_INTERVAL_SECONDS)
    except (TypeError, ValueError):
        value = DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, value)


def next_delay(interval: Optional[float] = None) -> float:
    """`P15-10` in miniature: never the same second twice.

    A push loop at exactly 60s is the textbook recurring job that lines up with
    every other install's push loop, and a collector shared by several of them
    sees one spike per minute instead of a flat rate.
    """
    base = _interval_seconds() if interval is None else max(MIN_INTERVAL_SECONDS, interval)
    # `P15-10` consolidated this: `src/jitter.py` is now the one place that
    # decides when a recurring job fires, and a second local implementation is
    # a second thing to find when the rule changes (`Law 14`).
    from src.jitter import jittered
    return jittered(base, fraction=JITTER_FRACTION)


async def push_loop() -> None:
    """The background task. Re-reads settings every tick.

    Sleeps first: a push in the first second of startup measures a process that
    has not done anything yet, and would make every restart look like a dip.
    Re-reading rather than capturing means turning the exporter on or off does
    not need a restart, and neither does moving it.
    """
    while True:
        try:
            await asyncio.sleep(next_delay())
        except asyncio.CancelledError:
            raise
        try:
            target = endpoint_url()
        except ValueError as e:
            _status["configured"] = False
            _status["last_error"] = str(e)
            logger.warning("otlp endpoint is not usable: %s", e)
            continue
        _status["configured"] = bool(target)
        if not target:
            continue
        try:
            await push_once(url=target)
        except asyncio.CancelledError:
            raise
        except OTLPNotConfigured:
            continue
        except Exception as e:
            _status["consecutive_failures"] += 1
            _status["last_error"] = f"{type(e).__name__}: {e}"
            logger.warning("otlp push loop error: %s: %s", type(e).__name__, e)


def status() -> Dict[str, Any]:
    """What the exporter has been doing, for the scrape to report.

    Ages rather than timestamps: `time.monotonic()` has an arbitrary origin, so
    the absolute value means nothing to a reader and the difference means
    everything. `None` for an age that has never happened — not `0`, which
    reads as *just now* and is the opposite of the truth (`B28`).
    """
    now = time.monotonic()
    last_ok = _status["last_success_monotonic"]
    last_try = _status["last_attempt_monotonic"]
    return {
        "configured": bool(_status["configured"]),
        "last_success_age_seconds": None if last_ok is None else round(now - last_ok, 1),
        "last_attempt_age_seconds": None if last_try is None else round(now - last_try, 1),
        "consecutive_failures": int(_status["consecutive_failures"]),
        "points_last_push": int(_status["points_last_push"]),
        "points_rejected": int(_status["points_rejected"]),
        "points_dropped": int(_status["points_dropped"]),
        "last_error": str(_status["last_error"]),
    }


def _reset_status_for_tests() -> None:
    _status.update({
        "configured": False,
        "last_success_monotonic": None,
        "last_attempt_monotonic": None,
        "consecutive_failures": 0,
        "last_error": "",
        "points_last_push": 0,
        "points_rejected": 0,
        "points_dropped": 0,
    })
