# SPDX-License-Identifier: AGPL-3.0-or-later
"""The push half of the metrics story (`P16-19`).

These tests are about the two things that make a metrics exporter fail
*silently*, because a loud failure would not need a test:

  * the JSON encoding, where a wrong type is accepted by `json.dumps` and
    rejected — or worse, misread — by the collector; and
  * the shipped address, where the only correct value is nothing at all.

Several assert on the AST rather than on substrings. The module explains at
length why the OpenTelemetry SDK is absent and what `partialSuccess` means, and
a substring search for `partialSuccess` or `opentelemetry` finds the prose
explaining their absence — the trap that hid a deleted scope gate in `P16-12`
and cost two surviving mutations.
"""
import ast
import asyncio
import json
import math
import pathlib

import pytest

from src import otlp_export as ox

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE = ROOT / "src" / "otlp_export.py"


@pytest.fixture(autouse=True)
def _clean_status():
    ox._reset_status_for_tests()
    yield
    ox._reset_status_for_tests()


def _tree():
    return ast.parse(MODULE.read_text(encoding="utf-8"))


def _code_strings(tree):
    """Every string literal that is NOT a docstring.

    `ast.get_docstring` only covers module/class/function heads, which is
    exactly the set of places this module's explanations live.
    """
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


# --------------------------------------------------------------------------
# The address
# --------------------------------------------------------------------------

def test_the_shipped_endpoint_is_empty():
    """`Law 16` clause 4. `check-destinations.py` enforces it at build time;
    this asserts it at the value, so a refactor of the checker cannot make the
    defect invisible."""
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["otlp_endpoint"] == ""


def test_no_endpoint_means_no_push(monkeypatch):
    monkeypatch.setattr(ox, "_get", lambda k, d: "" if k == "otlp_endpoint" else d)
    monkeypatch.delenv("PANTHEON_OTLP_ENDPOINT", raising=False)
    assert ox.endpoint_url() == ""
    with pytest.raises(ox.OTLPNotConfigured):
        asyncio.run(ox.push_once())


def test_the_env_layer_is_reachable_beneath_the_empty_default(monkeypatch):
    """`H06`/`B20`: `get_setting` merges `DEFAULT_SETTINGS` on every read, so an
    env fallback under a TRUTHY default is dead code. Under this falsy one it is
    reachable, and that is the second reason the key must ship empty."""
    monkeypatch.setattr(ox, "_get", lambda k, d: "" if k == "otlp_endpoint" else d)
    monkeypatch.setenv("PANTHEON_OTLP_ENDPOINT", "http://collector.lan:4318")
    assert ox.endpoint_url() == "http://collector.lan:4318/v1/metrics"


@pytest.mark.parametrize("given,expected", [
    ("http://c.lan:4318", "http://c.lan:4318/v1/metrics"),
    ("http://c.lan:4318/", "http://c.lan:4318/v1/metrics"),
    ("http://c.lan:4318/v1/metrics", "http://c.lan:4318/v1/metrics"),
    ("https://c.lan/otel", "https://c.lan/otel/v1/metrics"),
    ("https://c.lan/otel/v1/metrics/", "https://c.lan/otel/v1/metrics"),
])
def test_the_signal_path_is_appended_exactly_once(given, expected):
    """Both spellings are common — OTEL's own env vars distinguish base from
    signal URL — and appending unconditionally gives `/v1/metrics/v1/metrics`,
    a 404 the operator has no way to see from inside Pantheon."""
    assert ox.normalise_endpoint(given) == expected


@pytest.mark.parametrize("bad", ["", "   ", "otel.lan:4318", "ftp://c.lan/x",
                                 "file:///etc/passwd", "https://"])
def test_a_malformed_endpoint_is_refused_loudly(bad):
    with pytest.raises(ValueError):
        ox.normalise_endpoint(bad)


def test_the_loop_survives_a_malformed_endpoint(monkeypatch):
    """A bad address must not kill the task. If it did, fixing the typo in
    Settings would need a restart — and the operator would be watching a loop
    that is not running while believing it is."""
    monkeypatch.setattr(ox, "endpoint_url", lambda: (_ for _ in ()).throw(ValueError("nope")))
    ticks = {"n": 0}

    async def _sleep(_):
        ticks["n"] += 1
        if ticks["n"] > 2:
            raise asyncio.CancelledError
    monkeypatch.setattr(ox.asyncio, "sleep", _sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ox.push_loop())
    assert ticks["n"] == 3            # it kept going rather than dying on tick 1
    assert ox.status()["configured"] is False


# --------------------------------------------------------------------------
# The JSON encoding
# --------------------------------------------------------------------------

SAMPLES = [
    ("pantheon_llm_rounds_1h", 3, {"model": "kimi", "outcome": "ok"}),
    ("pantheon_llm_rounds_1h", 1, {"model": "kimi", "outcome": "error"}),
    ("pantheon_build_info", 1, {"version": "1.0.2"}),
]
META = {
    "pantheon_llm_rounds_1h": ("gauge", "Model rounds in the last hour."),
    "pantheon_build_info": ("gauge", "Always 1."),
}


def _points(payload, name):
    metrics = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    for m in metrics:
        if m["name"] == name:
            return m["gauge"]["dataPoints"]
    raise AssertionError(f"{name} not in payload")


def test_the_timestamp_is_a_STRING_because_it_is_a_uint64():
    """THE classic OTLP/JSON bug. proto3's JSON mapping renders 64-bit integers
    as strings; a nanosecond timestamp is ~1.8e18, past what a JSON number
    survives. Emitted unquoted, some collectors reject the batch and others
    truncate it and plot the data in 1970 — and `json.dumps` is happy either
    way, so nothing local ever complains."""
    payload, _, _ = ox.build_payload(SAMPLES, META, now_ns=1_756_000_000_123_456_789)
    for point in _points(payload, "pantheon_llm_rounds_1h"):
        assert isinstance(point["timeUnixNano"], str)
        assert point["timeUnixNano"] == "1756000000123456789"
    # And it survives a JSON round trip with every digit intact, which is the
    # property a bare number would lose.
    again = json.loads(json.dumps(payload))
    assert _points(again, "pantheon_build_info")[0]["timeUnixNano"] == "1756000000123456789"


def test_values_go_out_as_asDouble_not_asInt():
    """`asInt` is int64 and would need the same string treatment. Since
    `P16-12` decided everything is a gauge, a double is correct and is one fewer
    place to make the 64-bit mistake."""
    payload, _, _ = ox.build_payload(SAMPLES, META)
    for point in _points(payload, "pantheon_llm_rounds_1h"):
        assert "asInt" not in point
        assert isinstance(point["asDouble"], float)


def test_samples_sharing_a_name_become_ONE_metric_with_several_points():
    """The naive loop emits one metric entry per sample, which collectors report
    as a duplicate declaration and which makes the series unusable."""
    payload, points, _ = ox.build_payload(SAMPLES, META)
    metrics = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    names = [m["name"] for m in metrics]
    assert names.count("pantheon_llm_rounds_1h") == 1
    assert len(_points(payload, "pantheon_llm_rounds_1h")) == 2
    assert points == 3


def test_attributes_are_a_list_of_key_value_not_an_object():
    payload, _, _ = ox.build_payload(SAMPLES, META)
    point = _points(payload, "pantheon_build_info")[0]
    assert isinstance(point["attributes"], list)
    assert point["attributes"] == [{"key": "version", "value": {"stringValue": "1.0.2"}}]


def test_label_values_are_not_run_through_the_prometheus_escaper():
    """`_escape` exists for the text format. Applying it here as well would put
    a literal backslash-n into a JSON string that `json.dumps` was going to
    escape correctly on its own — the value arrives at the collector wrong, and
    it still parses."""
    payload, _, _ = ox.build_payload(
        [("m", 1, {"note": 'a "quoted"\nline'})], {"m": ("gauge", "")})
    value = _points(payload, "m")[0]["attributes"][0]["value"]["stringValue"]
    assert value == 'a "quoted"\nline'
    assert "\\n" not in value
    assert json.loads(json.dumps(payload))["resourceMetrics"][0]["scopeMetrics"][0] \
        ["metrics"][0]["gauge"]["dataPoints"][0]["attributes"][0]["value"]["stringValue"] == value


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"),
                                 "twelve", None, object()])
def test_a_value_that_is_not_a_finite_number_costs_one_sample_not_the_batch(bad):
    """`NaN` is the interesting one: `float("nan")` succeeds, and `json.dumps`
    writes the bare token `NaN`, which is not valid JSON and fails the parse for
    every other point in the push."""
    payload, points, dropped = ox.build_payload(
        [("good", 1, {}), ("bad", bad, {})], {"good": ("gauge", "")})
    assert points == 1 and dropped == 1
    body = json.dumps(payload)
    assert "NaN" not in body and "Infinity" not in body
    json.loads(body)


def test_the_batch_is_capped(monkeypatch):
    monkeypatch.setattr(ox, "MAX_DATA_POINTS", 5)
    payload, points, dropped = ox.build_payload(
        [("m", i, {"i": str(i)}) for i in range(12)], {"m": ("gauge", "")})
    assert points == 5 and dropped == 7
    assert len(_points(payload, "m")) == 5


def test_resource_carries_service_name_and_version(monkeypatch):
    monkeypatch.setattr(ox, "_get", lambda k, d: {"deployment": "lab"} if k == "otlp_resource_attributes" else d)
    payload, _, _ = ox.build_payload(SAMPLES, META)
    attrs = {a["key"]: a["value"]["stringValue"]
             for a in payload["resourceMetrics"][0]["resource"]["attributes"]}
    assert attrs["service.name"] == "pantheon"
    assert "service.version" in attrs
    assert attrs["deployment"] == "lab"


# --------------------------------------------------------------------------
# The push
# --------------------------------------------------------------------------

class _Resp:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class _Client:
    def __init__(self, response=None, boom=None):
        self._response = response or _Resp()
        self._boom = boom
        self.calls = []

    async def post(self, url, content=None, headers=None):
        self.calls.append({"url": url, "content": content, "headers": headers})
        if self._boom:
            raise self._boom
        return self._response

    async def aclose(self):
        pass


def _stub_metrics(monkeypatch, samples=SAMPLES, meta=META):
    import src.metrics_export as me
    monkeypatch.setattr(me, "collect_metrics", lambda: (samples, meta))


def test_a_push_posts_json_to_the_signal_url(monkeypatch):
    _stub_metrics(monkeypatch)
    client = _Client()
    result = asyncio.run(ox.push_once(url="http://c.lan:4318/v1/metrics", client=client))
    assert result["ok"] and result["points"] == 3
    assert client.calls[0]["url"] == "http://c.lan:4318/v1/metrics"
    assert client.calls[0]["headers"]["Content-Type"] == "application/json"
    json.loads(client.calls[0]["content"])


def test_a_200_with_partialSuccess_is_not_a_success(monkeypatch):
    """OTLP/HTTP answers a partly-rejected batch with `200 OK` and a
    `partialSuccess` body. Reading only the status reports delivery for a push
    that delivered nothing, which is the silence this row exists to break."""
    _stub_metrics(monkeypatch)
    body = json.dumps({"partialSuccess": {"rejectedDataPoints": "2",
                                          "errorMessage": "bad name"}})
    result = asyncio.run(ox.push_once(url="http://c.lan:4318/v1/metrics",
                                      client=_Client(_Resp(200, body))))
    assert result["rejected"] == 2
    assert ox.status()["points_rejected"] == 2
    assert "rejected" in ox.status()["last_error"]


@pytest.mark.parametrize("body", ["", "not json", "[]", '{"partialSuccess": 5}',
                                  '{"partialSuccess": {"rejectedDataPoints": "x"}}'])
def test_a_body_that_is_not_a_partial_success_report_reads_as_zero(body):
    assert ox._rejected_points(body) == 0


def test_a_failed_push_is_counted_and_a_later_success_clears_it(monkeypatch):
    _stub_metrics(monkeypatch)
    url = "http://c.lan:4318/v1/metrics"
    asyncio.run(ox.push_once(url=url, client=_Client(_Resp(503))))
    asyncio.run(ox.push_once(url=url, client=_Client(_Resp(503))))
    assert ox.status()["consecutive_failures"] == 2
    assert ox.status()["last_success_age_seconds"] is None
    asyncio.run(ox.push_once(url=url, client=_Client(_Resp(200))))
    assert ox.status()["consecutive_failures"] == 0
    assert ox.status()["last_success_age_seconds"] is not None


def test_a_transport_exception_does_not_escape(monkeypatch):
    _stub_metrics(monkeypatch)
    result = asyncio.run(ox.push_once(url="http://c.lan:4318/v1/metrics",
                                      client=_Client(boom=OSError("no route"))))
    assert result["ok"] is False
    assert ox.status()["consecutive_failures"] == 1


def test_an_empty_reading_is_not_pushed_at_all(monkeypatch):
    """A push of zero data points costs the collector a parse and tells it
    nothing. It also must not be recorded as a success, or a dead exporter
    looks healthy."""
    _stub_metrics(monkeypatch, samples=[], meta={})
    client = _Client()
    result = asyncio.run(ox.push_once(url="http://c.lan:4318/v1/metrics", client=client))
    assert result["points"] == 0 and client.calls == []
    assert ox.status()["last_success_age_seconds"] is None


def test_never_pushed_reads_as_absent_not_as_just_now():
    """`B28` in a new costume: a `0` age means *a second ago*, which is the
    opposite of *never*, and an alert on staleness would never fire."""
    st = ox.status()
    assert st["last_success_age_seconds"] is None
    assert st["last_attempt_age_seconds"] is None


# --------------------------------------------------------------------------
# The limiter, the headers, and what the module refuses to contain
# --------------------------------------------------------------------------

def test_the_push_is_paced_by_the_outbound_limiter(monkeypatch):
    """`P15`. Also `P16-16` for free: the limiter's `acquire` calls
    `require_host` before it paces, so an out-of-scope collector is refused
    without this module knowing what a network is."""
    _stub_metrics(monkeypatch)
    seen = []
    from src import rate_limiter

    async def _acquire(host, **kw):
        seen.append(host)
        return 0.0
    monkeypatch.setattr(rate_limiter.outbound, "acquire_async", _acquire)
    observed = []
    monkeypatch.setattr(rate_limiter.outbound, "observe",
                        lambda h, s, hd=None, **kw: observed.append((h, s)))
    asyncio.run(ox.push_once(url="http://c.lan:4318/v1/metrics", client=_Client(_Resp(200))))
    assert seen == ["c.lan"]
    assert observed == [("c.lan", 200)]


def test_a_rate_limited_collector_skips_the_tick_rather_than_raising(monkeypatch):
    _stub_metrics(monkeypatch)
    from src import rate_limiter

    async def _acquire(host, **kw):
        raise rate_limiter.OutboundRateLimited(host, 30.0, "cooling off")
    monkeypatch.setattr(rate_limiter.outbound, "acquire_async", _acquire)
    client = _Client()
    result = asyncio.run(ox.push_once(url="http://c.lan:4318/v1/metrics", client=client))
    assert result["ok"] is False and client.calls == []


def test_operator_headers_are_sent_and_cannot_override_the_content_type(monkeypatch):
    monkeypatch.setattr(ox, "_get",
                        lambda k, d: {"X-Api-Key": "s3cret", "content-type": "text/plain"}
                        if k == "otlp_headers" else d)
    headers = ox._headers()
    assert headers["X-Api-Key"] == "s3cret"
    assert headers["Content-Type"] == "application/json"
    assert "text/plain" not in json.dumps(headers)


def test_header_values_are_never_logged(monkeypatch, caplog):
    """A metrics exporter that prints its own credentials into the application
    log has moved the secret somewhere handled less carefully than the settings
    store it came from."""
    _stub_metrics(monkeypatch)
    monkeypatch.setattr(ox, "_get",
                        lambda k, d: {"X-Api-Key": "s3cret-token-value"} if k == "otlp_headers" else d)
    with caplog.at_level("DEBUG"):
        asyncio.run(ox.push_once(url="http://c.lan:4318/v1/metrics",
                                 client=_Client(_Resp(401, "unauthorized: s3cret-token-value"))))
        asyncio.run(ox.push_once(url="http://c.lan:4318/v1/metrics",
                                 client=_Client(boom=OSError("connect failed"))))
    assert "s3cret-token-value" not in caplog.text
    assert ox.status()["consecutive_failures"] == 2


def test_the_interval_is_floored_and_jittered(monkeypatch):
    """`P15-10`: nothing recurring fires on an exact boundary. A push loop at
    exactly 60s lines up with every other install's, and a shared collector sees
    a spike a minute instead of a flat rate."""
    monkeypatch.setattr(ox, "_get", lambda k, d: 1 if k == "otlp_interval_seconds" else d)
    assert ox._interval_seconds() == ox.MIN_INTERVAL_SECONDS
    monkeypatch.setattr(ox, "_get", lambda k, d: 60 if k == "otlp_interval_seconds" else d)
    delays = {round(ox.next_delay(), 6) for _ in range(50)}
    assert len(delays) > 1, "no jitter — every install pushes on the same second"
    assert all(60 <= d <= 66 for d in delays)


@pytest.mark.parametrize("bad", ["", None, "soon", [], {}])
def test_a_nonsense_interval_falls_back_rather_than_crashing_the_loop(monkeypatch, bad):
    monkeypatch.setattr(ox, "_get", lambda k, d: bad if k == "otlp_interval_seconds" else d)
    assert ox._interval_seconds() == ox.DEFAULT_INTERVAL_SECONDS


def test_the_module_does_not_import_the_opentelemetry_sdk():
    """Asserted on the AST, not on a grep: the module's docstring explains at
    length why the SDK is absent, so a substring search finds the word either
    way. That trap hid a deleted scope gate in `P16-12`."""
    imported = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "opentelemetry" not in imported
    assert "httpx" in imported


def test_the_module_contains_no_absolute_url(monkeypatch):
    """Not one address, anywhere in the code — the constants are a path and
    a set of numbers. Checked over non-docstring literals so the explanation
    above is not what makes this pass."""
    for literal in _code_strings(_tree()):
        assert "://" not in literal, f"{literal!r} is an address"


def test_every_name_the_module_imports_actually_exists():
    """The `B32`/`B33` family: an import inside a `try/except` that names a
    function nobody wrote fails silently forever, and the feature simply never
    runs. `resolve_endpoint_for_model` and `SkillManager` were both invented
    this way, both inside guards."""
    import importlib
    tree = _tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(("src.", "core.")):
            module = importlib.import_module(node.module)
            for alias in node.names:
                assert hasattr(module, alias.name), \
                    f"{node.module}.{alias.name} does not exist (line {node.lineno})"


def test_the_startup_wiring_is_present_and_names_a_real_function():
    """A background loop nobody starts is `Law 15` — finished work with no door.
    Parsed, so the comment above the line explaining the loop is not what makes
    this pass."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "src.otlp_export":
            names.update(a.asname or a.name for a in node.names)
    assert names, "app.py never imports the exporter"
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert names & called, f"imported {names} but never called any of them"
    assert hasattr(ox, "push_loop")


# --------------------------------------------------------------------------
# The door: a setting that does nothing must not answer as though it did
# --------------------------------------------------------------------------
#
# These call the real handler. An earlier version asserted on the AST that the
# handler imports `normalise_endpoint`, and the mutation `if key ==
# "otlp_endpoint":` → `if False:` SURVIVED it — the import is still in the tree,
# inside the branch that no longer runs. Presence in the source is not
# reachability, and that is the third time that family has caught me (`B32`,
# `B33`, and the `P16-12` docstring greps).
#
# The harness is the one `test_trust_rung_gate.py` already built for this
# endpoint, for the same defect: a 400-shaped mistake answered with a 200.


class _AdminOnly:
    def get_username_for_token(self, token):
        return "admin" if token == "admin-session" else None

    def is_admin(self, username):
        return username == "admin"


def _settings_route(monkeypatch, store):
    import types
    import routes.auth_routes as auth_routes

    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)
    monkeypatch.setattr(auth_routes, "_load_settings", lambda: dict(store))

    def _save(updated):
        store.clear()
        store.update(updated)

    monkeypatch.setattr(auth_routes, "_save_settings", _save)
    router = auth_routes.setup_auth_routes(_AdminOnly())
    endpoint = next(r.endpoint for r in router.routes
                    if r.path == "/api/auth/settings" and "POST" in r.methods)

    class _AdminRequest(types.SimpleNamespace):
        def __init__(self, body):
            super().__init__(cookies={auth_routes.SESSION_COOKIE: "admin-session"},
                             _body=body)

        async def json(self):
            return self._body

    return endpoint, _AdminRequest


def _store():
    from src.settings import DEFAULT_SETTINGS
    return dict(DEFAULT_SETTINGS)


@pytest.mark.parametrize("bad", [
    "otel.lan:4318",          # no scheme — the commonest way to write it
    "ftp://otel.lan/v1",      # a scheme, wrong one
    "https://",               # a scheme and nothing else
    "just some text",
])
def test_a_bad_endpoint_is_refused_at_the_door_not_swallowed_by_the_loop(monkeypatch, bad):
    """The push loop only logs a warning and carries on. A typo accepted here is
    a 200, the operator's value echoed back, and a collector that never receives
    anything — the operator has no way to tell that from a quiet install."""
    from fastapi import HTTPException
    store = _store()
    endpoint, request_for = _settings_route(monkeypatch, store)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(endpoint(request_for({"otlp_endpoint": bad})))
    assert refused.value.status_code == 400
    assert "otlp_endpoint" in str(refused.value.detail)
    # Refused *and not stored*: a 400 that wrote the value anyway is the same
    # defect wearing a different status code.
    assert store["otlp_endpoint"] == ""


def test_a_good_endpoint_is_stored(monkeypatch):
    store = _store()
    endpoint, request_for = _settings_route(monkeypatch, store)
    asyncio.run(endpoint(request_for({"otlp_endpoint": "  http://otel.lan:4318  "})))
    assert store["otlp_endpoint"] == "http://otel.lan:4318"


def test_clearing_the_endpoint_turns_the_exporter_off_again(monkeypatch):
    """Empty is the shipped state AND the off switch, so the door must keep
    accepting it. A validator that refused the empty string would make the
    exporter impossible to turn back off from Settings."""
    store = _store()
    store["otlp_endpoint"] = "http://otel.lan:4318"
    endpoint, request_for = _settings_route(monkeypatch, store)
    asyncio.run(endpoint(request_for({"otlp_endpoint": ""})))
    assert store["otlp_endpoint"] == ""


def test_the_stored_interval_and_the_effective_interval_are_the_same_number(monkeypatch):
    """The exporter floors the interval itself. Without the clamp at the door
    the settings page would show a `1` that is really a `10`."""
    store = _store()
    endpoint, request_for = _settings_route(monkeypatch, store)
    asyncio.run(endpoint(request_for({"otlp_interval_seconds": 1})))
    assert store["otlp_interval_seconds"] == ox.MIN_INTERVAL_SECONDS
    asyncio.run(endpoint(request_for({"otlp_interval_seconds": 999999})))
    assert store["otlp_interval_seconds"] == 86400


@pytest.mark.parametrize("bad", [["X-Api-Key", "v"], "X-Api-Key: v", 7,
                                 {"X-Api-Key": {"nested": 1}}])
def test_a_header_map_that_is_not_a_map_is_refused_rather_than_ignored(monkeypatch, bad):
    """`_headers()` skips a non-dict, so accepting one is a 200 followed by a
    collector that never gets its auth header — the enum defect again."""
    from fastapi import HTTPException
    store = _store()
    endpoint, request_for = _settings_route(monkeypatch, store)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(endpoint(request_for({"otlp_headers": bad})))
    assert refused.value.status_code == 400
    assert store["otlp_headers"] == {}


def test_header_values_are_normalised_to_strings(monkeypatch):
    store = _store()
    endpoint, request_for = _settings_route(monkeypatch, store)
    asyncio.run(endpoint(request_for({"otlp_headers": {"X-Tenant": 42}})))
    assert store["otlp_headers"] == {"X-Tenant": "42"}


def test_the_validator_the_door_calls_accepts_empty_and_rejects_nonsense():
    """The unit behind the wiring above."""
    assert ox.normalise_endpoint("http://c.lan:4318").endswith("/v1/metrics")
    for bad in ("otel.lan:4318", "ftp://c.lan", "not a url"):
        with pytest.raises(ValueError):
            ox.normalise_endpoint(bad)
