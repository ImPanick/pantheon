# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scrape answers; it never sends (`P16-12`).

`Law 16` clause 4, as the owner amended it: telemetry is fine, phoning home is
not. A **pull** satisfies that by its shape rather than by a promise — there is
no destination in this code and no place to put one.

The interesting tests here are not "does it produce output". They are:

  - everything is a `gauge`, and that is a decision. A Prometheus counter must
    be monotonic; `events_retention_days` prunes at 90 days, so a `_total` from
    that table would decline GRADUALLY — neither a reset nor a real rate — and
    `rate()` over it would be quietly wrong forever.
  - `# TYPE` appears exactly once per metric name. Emitting it beside each value
    is the natural way to write this and produces a parse error in strict
    scrapers the moment a metric has two label sets.
  - a failing collector must not fail the scrape. A monitoring endpoint that
    500s because one subsystem is unwell goes blind exactly when it is needed.
"""
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as core_db
from core.database import Base
from src import events as ev
from src import metrics_export as mx

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/m.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", maker)
    monkeypatch.setattr(ev, "_last_prune", 0.0)
    yield maker
    engine.dispose()


def parse(text):
    """A minimal exposition parser: (name, labels, value) plus declared types."""
    samples, types, helps = [], {}, {}
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("# TYPE "):
            _, _, name, kind = line.split(" ", 3)
            assert name not in types, f"# TYPE emitted twice for {name}"
            types[name] = kind
            continue
        if line.startswith("# HELP "):
            _, _, name, rest = line.split(" ", 3)
            helps[name] = rest
            continue
        assert not line.startswith("#"), f"unknown comment line: {line}"
        m = re.fullmatch(r'([a-zA-Z_:][a-zA-Z0-9_:]*)(\{.*\})? (-?[0-9.eE+]+)', line)
        assert m, f"unparseable sample: {line!r}"
        samples.append((m.group(1), m.group(2) or "", float(m.group(3))))
    return samples, types, helps


def seed():
    ev._turn_started.set(None)
    ev.mark_turn_start()
    ev.record_llm_round("s", {"input_tokens": 120, "output_tokens": 40,
                              "model": "qwen", "endpoint_label": "Local"})
    ev.record_llm_round("s", {"input_tokens": 0, "output_tokens": 0, "model": "qwen"},
                        outcome="error")
    ev.record_event("tool_call", name="shell", outcome="ok", duration_ms=42)
    ev.record_event("tool_call", name="shell", outcome="error", duration_ms=8)
    ev.record_event("retrieval", name="rag", outcome="empty",
                    detail={"asked": 5, "returned": 0})
    ev.record_event("approval", name="shell", outcome="expired")


# --- the format -----------------------------------------------------------

def test_output_is_valid_exposition_format():
    seed()
    samples, types, helps = parse(mx.render_metrics())
    assert samples, "no samples produced"
    for name, _, _ in samples:
        assert name in types, f"{name} has no # TYPE"
        assert name in helps, f"{name} has no # HELP"


def test_type_is_declared_exactly_once_per_metric():
    seed()
    text = mx.render_metrics()
    assert text.count("pantheon_tool_calls_1h{") >= 2, "seed did not produce two label sets"
    parse(text)   # raises on a duplicate TYPE
    assert text.count("# TYPE pantheon_tool_calls_1h ") == 1


def test_the_header_guard_holds_when_a_collector_declares_inside_a_loop():
    """`_Out.metric` de-duplicates, and today no collector calls it twice — so
    removing the guard breaks nothing and the test above passes either way.

    It is kept because the shape it protects against is the natural mistake:
    declaring the metric beside each value, inside the loop. A duplicated
    `# TYPE` for one name is a parse error in strict scrapers, so the guard is
    tested directly on the unit rather than through a collector that happens not
    to make the mistake yet.
    """
    out = mx._Out()
    for value in (1, 2, 3):
        out.metric("pantheon_thing", "gauge", "declared inside the loop")
        out.add("pantheon_thing", value, {"i": value})
    text = out.render()
    assert text.count("# TYPE pantheon_thing ") == 1
    parse(text)


def test_everything_is_a_gauge():
    """Not an oversight. Retention pruning makes an all-time counter decline
    gradually as rows age out — which Prometheus reads as neither a counter
    reset nor a real rate, and `rate()` over it is wrong in a way nobody
    notices on a dashboard."""
    seed()
    _, types, _ = parse(mx.render_metrics())
    assert types, "no types declared"
    assert set(types.values()) == {"gauge"}, types


def test_windowed_metrics_carry_their_window_in_the_name():
    """`pantheon_llm_rounds` would read as all-time. It is not."""
    seed()
    samples, _, _ = parse(mx.render_metrics())
    windowed = [n for n, _, _ in samples if n.startswith(
        ("pantheon_llm_", "pantheon_tool_calls", "pantheon_retrieval", "pantheon_approvals"))]
    assert windowed
    for name in windowed:
        assert name.endswith("_1h"), f"{name} does not say what window it covers"
        assert not name.endswith("_total"), f"{name} claims to be a counter"


def test_label_values_are_escaped():
    ev.record_event("tool_call", name='we"ird\\name', outcome="ok")
    text = mx.render_metrics()
    assert 'we\\"ird\\\\name' in text
    parse(text)   # and it still parses


# --- the numbers are right ------------------------------------------------

def test_the_numbers_match_what_happened():
    seed()
    samples, _, _ = parse(mx.render_metrics())
    got = {(n, lbl): v for n, lbl, v in samples}
    assert got[("pantheon_llm_rounds_1h", '{model="qwen",outcome="ok"}')] == 1
    assert got[("pantheon_llm_rounds_1h", '{model="qwen",outcome="error"}')] == 1
    assert got[("pantheon_llm_tokens_1h", '{direction="input",model="qwen"}')] == 120
    assert got[("pantheon_tool_calls_1h", '{outcome="error",tool="shell"}')] == 1
    assert got[("pantheon_retrieval_1h", '{outcome="empty",store="rag"}')] == 1
    assert got[("pantheon_approvals_1h", '{outcome="expired"}')] == 1


def test_queue_depth_is_read_at_scrape_time():
    """P14-02 deliberately did not write these as events: a depth is a
    point-in-time reading, and storing a sample of it is a worse version of
    asking. This is where it is asked."""
    samples, _, _ = parse(mx.render_metrics())
    queues = {lbl for n, lbl, _ in samples if n == "pantheon_queue_depth"}
    assert '{queue="agent_mail"}' in queues   # H01, as a number in front of someone
    assert '{queue="task_runs"}' in queues


def test_self_check_unknown_is_not_folded_into_ok():
    """"The check could not run" and "nothing is wrong" are different answers.
    An alert on `> 0` has to catch both."""
    assert mx._SELF_CHECK_VALUE["ok"] == 0
    assert mx._SELF_CHECK_VALUE["unknown"] > 0
    assert mx._SELF_CHECK_VALUE["stuck"] > mx._SELF_CHECK_VALUE["attention"]


# --- the scrape must not become a load generator --------------------------

def test_repeated_scrapes_do_not_re_probe_the_embedding_server(monkeypatch):
    """The defect this caught, stated plainly.

    `run_self_checks` → `embedding_availability` → `get_embedding_client()`,
    which performs a real HTTP health check against the operator's embedding
    server. The latch in `embeddings.py` only suppresses that after a FAILURE —
    on a healthy install the probe runs every call.

    Uncached, a 15-second scrape sends 240 requests an hour to that server
    forever, as a side effect of being monitored. Exactly what this module
    refuses liveness probing to avoid, one layer down.
    """
    calls = []
    monkeypatch.setattr("src.self_checks.run_self_checks",
                        lambda: calls.append(1) or {"checks": []})
    monkeypatch.setattr(mx, "_self_check_cache", (0.0, None))

    for _ in range(20):        # five minutes of 15-second scrapes
        mx.render_metrics()

    assert len(calls) == 1, (
        f"{len(calls)} self-check runs for 20 scrapes; each one probes the "
        f"embedding server over HTTP")


def test_the_cache_expires(monkeypatch):
    """Cached is not frozen. A self-check state that never refreshes is worse
    than one a minute old — it is a dashboard reporting the state at boot.

    Counted across the TTL boundary. The first version of this asserted that
    the cache timestamp was non-zero, which is true after the FIRST fetch and
    stays true forever: raising the TTL to a billion seconds passed it cleanly.
    """
    calls = []
    monkeypatch.setattr("src.self_checks.run_self_checks",
                        lambda: calls.append(1) or {"checks": []})
    clock = {"t": 1000.0}
    monkeypatch.setattr(mx.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(mx, "_self_check_cache", (0.0, None))

    mx._cached_self_checks()
    mx._cached_self_checks()
    assert len(calls) == 1, "the cache did not hold within its TTL"

    clock["t"] += mx.SELF_CHECK_TTL_SECONDS + 1
    mx._cached_self_checks()
    assert len(calls) == 2, "the cache never expires; the numbers freeze at boot"


def test_the_ttl_is_short_enough_to_be_a_cache_and_not_a_freeze():
    """A minute is chosen against the scrape interval. An hour would make the
    self-check gauges decorative."""
    assert 15 <= mx.SELF_CHECK_TTL_SECONDS <= 300


def test_the_scrape_says_how_stale_the_cached_checks_are(monkeypatch):
    """A cached reading that does not say it is cached is one an operator will
    misread as live."""
    monkeypatch.setattr("src.self_checks.run_self_checks", lambda: {"checks": []})
    monkeypatch.setattr(mx, "_self_check_cache", (0.0, None))
    samples, types, _ = parse(mx.render_metrics())
    names = {n for n, _, _ in samples}
    assert "pantheon_self_check_age_seconds" in names
    assert types["pantheon_self_check_age_seconds"] == "gauge"


def test_no_collector_other_than_self_checks_touches_the_network(monkeypatch):
    """A guard on the whole module, not just the one that was wrong.

    Every collector runs with sockets stubbed out; anything that reaches for the
    network fails its collector, and `pantheon_scrape_collector_failed` reports
    which. The self-check collector is exempted only because its probe is
    behind the TTL cache above.
    """
    import socket

    def refuse(*a, **kw):
        raise AssertionError("a metrics collector opened a socket")

    monkeypatch.setattr(mx, "_cached_self_checks", lambda: {"checks": []})
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)

    samples, _, _ = parse(mx.render_metrics())
    failed = {lbl: v for n, lbl, v in samples if n == "pantheon_scrape_collector_failed"}
    assert failed, "no collectors ran — the test would be vacuous"
    assert all(v == 0 for v in failed.values()), f"a collector reached the network: {failed}"


# --- resilience -----------------------------------------------------------

def test_a_failing_collector_does_not_fail_the_scrape(monkeypatch):
    """A monitoring endpoint that 500s because one subsystem is unwell goes
    blind exactly when it is needed."""
    def boom(out):
        raise RuntimeError("subsystem is unwell")
    monkeypatch.setattr(mx, "_COLLECTORS",
                        (("events", boom), ("build", mx._collect_build)))
    text = mx.render_metrics()
    samples, _, _ = parse(text)
    names = {n for n, _, _ in samples}
    assert "pantheon_build_info" in names, "one bad collector took the whole scrape down"
    got = {lbl: v for n, lbl, v in samples if n == "pantheon_scrape_collector_failed"}
    assert got['{collector="events"}'] == 1
    assert got['{collector="build"}'] == 0


def test_an_empty_database_still_produces_a_valid_scrape():
    """A fresh install scrapes cleanly. A monitoring endpoint that only works
    once there is data is one nobody trusts on day one."""
    samples, types, _ = parse(mx.render_metrics())
    assert samples and set(types.values()) == {"gauge"}


# --- Law 16 ---------------------------------------------------------------

def _module_code():
    """Imports, called names and non-docstring literals of metrics_export.

    Parsed rather than grepped. The first version of these tests searched the
    file text with `#`-lines removed, and failed on the module's own DOCSTRING —
    which explains at length why `requests`, `service_health` and
    `prometheus_client` are absent. A test that a comment can break is a test
    that a comment can also satisfy.
    """
    import ast
    tree = ast.parse((ROOT / "src" / "metrics_export.py").read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)

    imports, names, literals = set(), set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
            imports.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                literals.append(node.value)
    return imports, names, literals


def test_the_ast_helper_actually_sees_the_code():
    """Guards the three tests below from passing because the parser returned
    nothing — the tautology a helper like this invites."""
    imports, names, literals = _module_code()
    assert "logging" in imports and "time" in imports
    assert "render_metrics" in names or "_Out" in names
    assert any("pantheon_" in s for s in literals)


def test_the_exporter_has_no_destination_and_makes_no_outbound_call():
    imports, names, literals = _module_code()
    for banned in ("httpx", "requests", "aiohttp", "urllib", "socket"):
        assert not any(i == banned or i.startswith(banned + ".") for i in imports), \
            f"{banned} imported by a module that must only answer"
    assert not any("://" in s for s in literals), \
        f"a URL literal in the exporter: {[s for s in literals if '://' in s]}"


def test_no_liveness_probing_on_the_hot_path():
    """`collect_service_health` makes real network calls to every configured
    provider. At a 15-second scrape that is thousands of outbound requests an
    hour to other people's machines — P15 undone by the telemetry meant to
    watch it."""
    imports, names, _ = _module_code()
    assert "collect_service_health" not in names
    assert not any("service_health" in i for i in imports)


def test_no_prometheus_client_dependency():
    """The exposition format is a name, labels and a number. Taking a hard
    dependency to do string formatting, in a product whose stated direction is
    'drop external dependence', would be the wrong trade."""
    imports, _, _ = _module_code()
    assert not any("prometheus" in i for i in imports)
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "prometheus" not in reqs.lower()


# --- the route ------------------------------------------------------------

def test_metrics_ship_off_and_the_env_layer_is_reachable():
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["metrics_enabled"] is False
    src = (ROOT / "routes" / "diagnostics_routes.py").read_text(encoding="utf-8")
    assert "PANTHEON_METRICS_ENABLED" in src


def test_a_disabled_endpoint_is_indistinguishable_from_one_that_does_not_exist():
    """404, not 403: "off" should look like "never built"."""
    code = _metrics_handler_code()
    gate = code.split("api_token")[0]
    assert "404" in gate
    assert "403" not in gate


def _metrics_handler_code():
    """The scrape handler with its docstring removed.

    That docstring explains the scope gate in prose, so a plain substring search
    for "metrics:read" passed with the gate deleted — the same trap that broke
    the three Law 16 tests above, here on a security control. Parsed instead.
    """
    import ast
    src = (ROOT / "routes" / "diagnostics_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == "prometheus_metrics":
            body = list(node.body)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)):
                body = body[1:]          # drop the docstring
            return "\n".join(ast.unparse(n) for n in body)
    raise AssertionError("prometheus_metrics handler not found")


def test_the_route_is_authenticated_two_ways_and_scope_gated():
    code = _metrics_handler_code()
    assert "render_metrics" in code, "wrong function — the test would be vacuous"
    assert "metrics:read" in code, "no scope gate in the handler body"
    assert "require_admin(request)" in code, "no browser-session path"
    assert "403" in code, "a token without the scope is not refused"


def test_the_scope_exists_and_is_read_only():
    src = (ROOT / "routes" / "api_token_routes.py").read_text(encoding="utf-8")
    assert '"metrics:read"' in src
    from routes.api_token_routes import ALLOWED_SCOPES
    assert "metrics:read" in ALLOWED_SCOPES
    assert "metrics:write" not in ALLOWED_SCOPES


def test_registered_in_all_five_places():
    assert "metrics_enabled" in (ROOT / "src" / "settings.py").read_text(encoding="utf-8")
    assert "PANTHEON_METRICS_ENABLED" in (ROOT / ".env.example").read_text(encoding="utf-8")
    for f in ("docker-compose.yml", "docker-compose.gpu-amd.yml", "docker-compose.gpu-nvidia.yml"):
        assert "PANTHEON_METRICS_ENABLED" in (ROOT / f).read_text(encoding="utf-8"), f


# ---------------------------------------------------------------------------
# `P16-19` — the second wire format reads the same collectors
# ---------------------------------------------------------------------------

def test_the_structured_reading_and_the_text_reading_are_the_same_reading():
    """`P16-19` pushes what `P16-12` serves. If the two ever drift, an operator
    running both sees two dashboards disagreeing about what the system did and
    has to work out which one is lying.

    Asserted by re-rendering the text FROM the samples and comparing to the
    text the module produced — not by counting lines, which any two lists of
    the same length would satisfy.
    """
    out = mx._assemble()
    text = out.render()
    samples, metadata = out.samples(), out.metadata()

    value_lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert len(samples) == len(value_lines)
    for (name, value, labels), line in zip(samples, value_lines):
        assert mx._line(name, value, labels) == line

    # Every emitted name is declared, and every declaration is a gauge — the
    # push serialises `gauge` unconditionally, so a counter appearing here
    # would be silently mislabelled at the collector.
    for name, _v, _l in samples:
        assert name in metadata, f"{name} emitted without a HELP/TYPE declaration"
        assert metadata[name][0] == "gauge"


def test_out_hands_out_a_copy_rather_than_its_live_accumulator():
    """Tested on the unit, not through `collect_metrics`.

    `_assemble()` builds a fresh `_Out` per call, so a caller mutating what
    `collect_metrics()` returned could never corrupt the *next* call — a test
    written at that level passes with the copy removed and proves nothing. The
    hazard is one level down: `_Out` is now the shared accumulator between two
    renderers, and a caller that holds one and edits `samples()` would silently
    change what `render()` emits.
    """
    out = mx._Out()
    out.metric("m", "gauge", "help")
    out.add("m", 1, {"a": "b"})
    baseline = out.render()

    out.samples().append(("injected", 99, {}))
    out.metadata()["injected"] = ("counter", "")

    assert out.render() == baseline
    assert [n for n, _, _ in out.samples()] == ["m"]
    assert "injected" not in out.metadata()


def test_the_push_exporters_own_health_is_on_the_SCRAPE():
    """When the push is failing, the pushed copy of this metric is exactly the
    one that does not arrive. A pull endpoint is where you find out that the
    pull endpoint is not the problem."""
    body = mx.render_metrics()
    assert "pantheon_otlp_configured 0" in body
    assert "pantheon_otlp_consecutive_failures" in body


def test_a_never_successful_push_reports_no_age_at_all():
    """`B28`: a `0` age reads as *a second ago*, which is the opposite of
    *never*, and an alert on staleness would never fire."""
    from src import otlp_export
    otlp_export._reset_status_for_tests()
    body = mx.render_metrics()
    assert "# TYPE pantheon_otlp_last_success_age_seconds gauge" in body
    values = [ln for ln in body.splitlines()
              if ln.startswith("pantheon_otlp_last_success_age_seconds")]
    assert values == [], f"an age was reported before any push succeeded: {values}"
