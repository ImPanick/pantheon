# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prometheus scrape output, built by hand, from data that is already local.

`P16-12`. `Law 16` clause 4 as the owner amended it: *"telemetry is fine, but
'phone home' to an external destination is not allowed. if the user wants to
establish their own telemetry endpoint, they can bypass this law and do so...
like Prometheus or Grafana."* The rule is about the destination, and a scrape
has no destination at all — Pantheon answers a question, it does not send
anything. Nothing leaves unless the operator's own Prometheus asks.

NO `prometheus_client` DEPENDENCY, DELIBERATELY.

The text exposition format is a name, optional labels, and a number. Adding a
hard dependency to produce that would be adding an external dependency to do
string formatting, in a product whose stated direction is *drop external
dependence*. The escaping rules that actually matter are label values (`\\`, `"`,
newline) and they are ten lines below.

EVERYTHING IS A GAUGE, AND THAT IS THE INTERESTING DECISION.

A Prometheus counter must be monotonic; on a decrease, Prometheus infers a
process restart and repairs the rate. But `events_retention_days` prunes at 90
days, so a `_total` sourced from that table would decline **gradually** as old
rows age out — neither a reset nor a real rate, and `rate()` over it would be
quietly wrong in a way no one would notice on a dashboard.

So the windowed numbers carry their window in the name (`_1h`) and are declared
`gauge`. That is honest about what they are: "how many in the last hour", asked
fresh each scrape. An operator who wants a true counter should count something
that is genuinely monotonic, and none of this is.

WHAT IS NOT HERE. Liveness probes (`collect_service_health`) make real network
calls to every configured provider. At a 15-second scrape that is a few thousand
requests an hour to other people's machines, which is `P15` undone by the
telemetry that was supposed to watch it. Liveness stays where a person asks for
it, on the diagnostics panel.
"""
import logging
import time
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Window for the event-derived numbers. One hour is long enough to be non-zero
# on a quiet install and short enough that "now" still means now.
WINDOW_SECONDS = 3600
_WINDOW_LABEL = "1h"

_SELF_CHECK_VALUE = {"ok": 0, "attention": 1, "unknown": 2, "stuck": 3}


def _escape(value: Any) -> str:
    """Prometheus label-value escaping: backslash, quote, newline. That is all
    the format requires, and inventing more would corrupt legitimate values."""
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _line(name: str, value: Any, labels: Optional[Dict[str, Any]] = None) -> str:
    if labels:
        rendered = ",".join(f'{k}="{_escape(v)}"' for k, v in sorted(labels.items()))
        return f"{name}{{{rendered}}} {value}"
    return f"{name} {value}"


class _Out:
    """Accumulates lines and emits HELP/TYPE exactly once per metric name.

    Prometheus tolerates a repeated HELP but a duplicated TYPE for one name is a
    parse error in strict scrapers, and the natural way to write this — emit the
    header beside each value — produces exactly that as soon as a metric has two
    label sets.

    Since `P16-19` it also keeps the values in structured form. That is the
    whole of what the push exporter needed: the collectors below are the only
    thing that knows where a number comes from, and writing a second set of
    them for a second wire format is how two exporters start disagreeing about
    what the system did. The text lines are still built here as they always
    were, so the scrape body is byte-for-byte what it was before.
    """

    def __init__(self) -> None:
        self._lines: List[str] = []
        self._declared: set = set()
        self._meta: Dict[str, Tuple[str, str]] = {}
        self._samples: List[Tuple[str, Any, Dict[str, Any]]] = []

    def metric(self, name: str, kind: str, help_text: str) -> None:
        if name in self._declared:
            return
        self._declared.add(name)
        self._meta[name] = (kind, help_text)
        self._lines.append(f"# HELP {name} {help_text}")
        self._lines.append(f"# TYPE {name} {kind}")

    def add(self, name: str, value: Any, labels: Optional[Dict[str, Any]] = None) -> None:
        self._samples.append((name, value, dict(labels or {})))
        self._lines.append(_line(name, value, labels))

    def render(self) -> str:
        return "\n".join(self._lines) + "\n"

    def samples(self) -> List[Tuple[str, Any, Dict[str, Any]]]:
        return list(self._samples)

    def metadata(self) -> Dict[str, Tuple[str, str]]:
        return dict(self._meta)


def _event_window(db, Event, kind: str, since):
    return db.query(Event).filter(Event.kind == kind, Event.ts >= since)


def _collect_events(out: _Out) -> None:
    """Everything the `P14` table knows, grouped in SQL rather than in Python."""
    from sqlalchemy import func
    from core.database import SessionLocal, Event, utcnow_naive

    since = utcnow_naive() - timedelta(seconds=WINDOW_SECONDS)
    db = SessionLocal()
    try:
        out.metric(f"pantheon_llm_rounds_{_WINDOW_LABEL}", "gauge",
                   "Model rounds in the last hour, by model and outcome.")
        rows = (db.query(Event.model, Event.outcome, func.count(Event.id))
                  .filter(Event.kind == "llm_round", Event.ts >= since)
                  .group_by(Event.model, Event.outcome).all())
        for model, outcome, n in rows:
            out.add(f"pantheon_llm_rounds_{_WINDOW_LABEL}", int(n or 0),
                    {"model": model or "unknown", "outcome": outcome or "ok"})

        out.metric(f"pantheon_llm_tokens_{_WINDOW_LABEL}", "gauge",
                   "Tokens in the last hour, by model and direction.")
        rows = (db.query(Event.model,
                         func.coalesce(func.sum(Event.input_tokens), 0),
                         func.coalesce(func.sum(Event.output_tokens), 0))
                  .filter(Event.kind == "llm_round", Event.ts >= since)
                  .group_by(Event.model).all())
        for model, in_t, out_t in rows:
            label = {"model": model or "unknown"}
            out.add(f"pantheon_llm_tokens_{_WINDOW_LABEL}", int(in_t or 0),
                    {**label, "direction": "input"})
            out.add(f"pantheon_llm_tokens_{_WINDOW_LABEL}", int(out_t or 0),
                    {**label, "direction": "output"})

        # Turn latency, not round latency — it includes tool calls and retries,
        # which is what `P14-02` measures and what an operator watching a
        # dashboard actually cares about. Named so nobody has to guess.
        out.metric(f"pantheon_turn_duration_ms_{_WINDOW_LABEL}", "gauge",
                   "Turn duration in ms over the last hour (request in to "
                   "totals accumulated; includes tool calls and retries).")
        row = (db.query(func.avg(Event.duration_ms), func.max(Event.duration_ms),
                        func.count(Event.duration_ms))
                 .filter(Event.kind == "llm_round", Event.ts >= since,
                         Event.duration_ms.isnot(None)).one())
        if row and (row[2] or 0):
            out.add(f"pantheon_turn_duration_ms_{_WINDOW_LABEL}",
                    round(float(row[0] or 0), 1), {"stat": "mean"})
            out.add(f"pantheon_turn_duration_ms_{_WINDOW_LABEL}",
                    int(row[1] or 0), {"stat": "max"})
            out.add(f"pantheon_turn_duration_ms_{_WINDOW_LABEL}",
                    int(row[2] or 0), {"stat": "samples"})

        out.metric(f"pantheon_tool_calls_{_WINDOW_LABEL}", "gauge",
                   "Tool calls in the last hour, by tool and outcome. "
                   "outcome=error means the tool returned a failure; "
                   "outcome=exception means it raised.")
        rows = (db.query(Event.name, Event.outcome, func.count(Event.id))
                  .filter(Event.kind == "tool_call", Event.ts >= since)
                  .group_by(Event.name, Event.outcome).all())
        for name, outcome, n in rows:
            out.add(f"pantheon_tool_calls_{_WINDOW_LABEL}", int(n or 0),
                    {"tool": name or "unknown", "outcome": outcome or "ok"})

        out.metric(f"pantheon_retrieval_{_WINDOW_LABEL}", "gauge",
                   "Retrievals in the last hour, by store and outcome. "
                   "outcome=unavailable means the store was down; "
                   "outcome=empty means it answered with nothing.")
        rows = (db.query(Event.name, Event.outcome, func.count(Event.id))
                  .filter(Event.kind == "retrieval", Event.ts >= since)
                  .group_by(Event.name, Event.outcome).all())
        for name, outcome, n in rows:
            out.add(f"pantheon_retrieval_{_WINDOW_LABEL}", int(n or 0),
                    {"store": name or "unknown", "outcome": outcome or "ok"})

        out.metric(f"pantheon_approvals_{_WINDOW_LABEL}", "gauge",
                   "Tool approvals in the last hour. outcome=expired is a "
                   "question nobody answered.")
        rows = (db.query(Event.outcome, func.count(Event.id))
                  .filter(Event.kind == "approval", Event.ts >= since)
                  .group_by(Event.outcome).all())
        for outcome, n in rows:
            out.add(f"pantheon_approvals_{_WINDOW_LABEL}", int(n or 0),
                    {"outcome": outcome or "unknown"})

        out.metric("pantheon_events_rows", "gauge",
                   "Rows in the events table. Bounded by events_retention_days.")
        out.add("pantheon_events_rows", int(db.query(func.count(Event.id)).scalar() or 0))
    finally:
        db.close()


# Self-check results, cached. See `_cached_self_checks`.
SELF_CHECK_TTL_SECONDS = 60
_self_check_cache: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)
_self_check_lock = None


def _cached_self_checks() -> Dict[str, Any]:
    """`run_self_checks()`, at most once a minute.

    **This cache is not an optimisation, it is a correctness fix.**
    `embedding_availability` calls `get_embedding_client()`, which performs a
    real HTTP health check against the configured embedding server. The
    process-level latch in `embeddings.py` only suppresses that after a
    FAILURE — on a healthy install the probe runs on every call.

    Uncached, a 15-second Prometheus scrape would send **240 requests an hour**
    to the operator's embedding server, forever, as a side effect of being
    monitored. That is the exact defect this module refuses liveness probing to
    avoid, arriving one layer down where it is much harder to see.

    Sixty seconds is chosen against the scrape, not the data: none of these
    checks changes second to second, and a state up to a minute stale is fine
    for an alert rule. The panel in Settings is unaffected — it calls
    `run_self_checks` directly, and a person looking at a screen is a bounded
    number of calls.
    """
    global _self_check_cache, _self_check_lock
    import threading
    if _self_check_lock is None:
        _self_check_lock = threading.Lock()

    fetched_at, cached = _self_check_cache
    now = time.monotonic()
    if cached is not None and now - fetched_at < SELF_CHECK_TTL_SECONDS:
        return cached

    with _self_check_lock:
        fetched_at, cached = _self_check_cache
        now = time.monotonic()
        if cached is not None and now - fetched_at < SELF_CHECK_TTL_SECONDS:
            return cached
        from src.self_checks import run_self_checks
        result = run_self_checks() or {}
        _self_check_cache = (time.monotonic(), result)
        return result


def _collect_self_checks(out: _Out) -> None:
    """`P16-15`'s local assertions, as numbers.

    0=ok 1=attention 2=unknown 3=stuck. `unknown` sits between the two on
    purpose and is never folded into `ok`: *the check could not run* and
    *nothing is wrong* are different answers, and an alert rule written against
    `> 0` catches both.
    """
    result = _cached_self_checks()
    out.metric("pantheon_self_check", "gauge",
               "Local self-check state: 0=ok 1=attention 2=unknown 3=stuck.")
    for check in (result.get("checks") or []):
        out.add("pantheon_self_check",
                _SELF_CHECK_VALUE.get(check.get("status"), 2),
                {"check": check.get("name") or "unknown"})
    # How old the numbers above are. A cached reading that does not say it is
    # cached is a reading an operator will misread as live.
    out.metric("pantheon_self_check_age_seconds", "gauge",
               f"Age of the cached self-check result (TTL "
               f"{SELF_CHECK_TTL_SECONDS}s). These probe real subsystems, so "
               f"they are not re-run on every scrape.")
    out.add("pantheon_self_check_age_seconds",
            round(max(0.0, time.monotonic() - _self_check_cache[0]), 1))


def _collect_outbound(out: _Out) -> None:
    """`P15`'s limiter. A host in cooldown is the reason a feature looks broken."""
    from src.rate_limiter import outbound
    snapshot = outbound.snapshot() or {}
    out.metric("pantheon_outbound_cooldown_seconds", "gauge",
               "Seconds remaining before this host may be called again.")
    out.metric("pantheon_outbound_consecutive_429", "gauge",
               "Consecutive rate-limit responses seen from this host.")
    for host, state in snapshot.items():
        if not isinstance(state, dict):
            continue
        out.add("pantheon_outbound_cooldown_seconds",
                round(float(state.get("blocked_for", 0) or 0), 2), {"host": host})
        out.add("pantheon_outbound_consecutive_429",
                int(state.get("consecutive_429", 0) or 0), {"host": host})


def _collect_queue_depth(out: _Out) -> None:
    """Queue depth, read at scrape time rather than sampled into the event log.

    `P14-02` deliberately did not write these as events: a depth is a
    point-in-time reading, and storing a sample of it every time it changes is
    a worse version of asking for it. This is where it is asked for.

    `agent_draft` is `H01` in gauge form — a year of agent-composed mail sat
    staged and invisible because nothing ever put a number in front of anyone.
    """
    from sqlalchemy import func
    from core.database import SessionLocal
    out.metric("pantheon_queue_depth", "gauge",
               "Items waiting. agent_mail is H01's staged-drafts queue.")
    db = SessionLocal()
    try:
        try:
            from core.database import ChatMessage
            n = (db.query(func.count(ChatMessage.id))
                   .filter(ChatMessage.role == "agent_draft").scalar())
            out.add("pantheon_queue_depth", int(n or 0), {"queue": "agent_mail"})
        except Exception as e:
            logger.debug("agent_mail depth unavailable: %s", e)
        try:
            # `B78`: this re-typed `("queued", "running")` inline while the one
            # constant the vocabulary exports sat in the same import. A metric
            # named "queue depth" that learns a new in-flight status later than
            # the scheduler does reports a number that is quietly wrong.
            from core.database import TaskRun, TASK_RUN_ACTIVE_STATUSES
            n = (db.query(func.count(TaskRun.id))
                   .filter(TaskRun.status.in_(TASK_RUN_ACTIVE_STATUSES)).scalar())
            out.add("pantheon_queue_depth", int(n or 0), {"queue": "task_runs"})
        except Exception as e:
            logger.debug("task_runs depth unavailable: %s", e)
    finally:
        db.close()


def _collect_otlp(out: _Out) -> None:
    """The push exporter's own health (`P16-19`).

    It belongs on the SCRAPE rather than only in the pushed batch, and that is
    the whole reason it exists: when the push is failing, the pushed copy of
    this metric is exactly the one that does not arrive. A pull endpoint is
    where you find out that the pull endpoint is not the problem.

    `pantheon_otlp_last_success_age_seconds` is absent, not zero, when a push
    has never succeeded. Zero would read as *just now*, which is `B28` — a
    "never" wearing the costume of a "just happened".
    """
    from src.otlp_export import status as otlp_status
    st = otlp_status()
    out.metric("pantheon_otlp_configured", "gauge",
               "1 when a collector address is set. 0 is the shipped state.")
    out.add("pantheon_otlp_configured", 1 if st.get("configured") else 0)
    out.metric("pantheon_otlp_consecutive_failures", "gauge",
               "Pushes that have failed in a row. 0 after any success.")
    out.add("pantheon_otlp_consecutive_failures", int(st.get("consecutive_failures", 0) or 0))
    out.metric("pantheon_otlp_points_last_push", "gauge",
               "Data points in the most recent accepted push.")
    out.add("pantheon_otlp_points_last_push", int(st.get("points_last_push", 0) or 0))
    out.metric("pantheon_otlp_points_rejected", "gauge",
               "Points the collector answered 200 for and then discarded.")
    out.add("pantheon_otlp_points_rejected", int(st.get("points_rejected", 0) or 0))
    age = st.get("last_success_age_seconds")
    out.metric("pantheon_otlp_last_success_age_seconds", "gauge",
               "Seconds since the last accepted push. Absent if never.")
    if age is not None:
        out.add("pantheon_otlp_last_success_age_seconds", age)


def _collect_build(out: _Out) -> None:
    try:
        from src.constants import APP_VERSION
    except Exception:
        APP_VERSION = "unknown"
    out.metric("pantheon_build_info", "gauge",
               "Always 1. The version is in the label.")
    out.add("pantheon_build_info", 1, {"version": APP_VERSION})


_COLLECTORS = (
    ("build", _collect_build),
    ("events", _collect_events),
    ("self_checks", _collect_self_checks),
    ("outbound", _collect_outbound),
    ("queue_depth", _collect_queue_depth),
    ("otlp", _collect_otlp),
)


def _assemble() -> _Out:
    """Run every collector once, in isolation, and return what they produced.

    Each collector is isolated. A scrape endpoint that returns 500 because one
    subsystem is unwell is a monitoring system that goes blind exactly when it
    is needed — so a failing collector costs its own metrics and is itself
    reported, and everything else still arrives.

    `P16-19` pushes the same numbers to an operator's collector. The metric
    names below still say `scrape` on that path, and that is deliberate: one
    number should have one name. Renaming it for the second transport would
    give an operator running both a dashboard that silently halves.
    """
    out = _Out()
    started = time.monotonic()
    failed = []
    for name, collector in _COLLECTORS:
        try:
            collector(out)
        except Exception as e:
            failed.append(name)
            logger.debug("metrics collector %s failed: %s: %s", name, type(e).__name__, e)
    out.metric("pantheon_scrape_collector_failed", "gauge",
               "1 when a collector raised during this scrape.")
    for name, _ in _COLLECTORS:
        out.add("pantheon_scrape_collector_failed", 1 if name in failed else 0,
                {"collector": name})
    out.metric("pantheon_scrape_duration_seconds", "gauge",
               "How long this scrape took to assemble.")
    out.add("pantheon_scrape_duration_seconds", round(time.monotonic() - started, 4))
    return out


def render_metrics() -> str:
    """The scrape body (`P16-12`)."""
    return _assemble().render()


def collect_metrics() -> Tuple[List[Tuple[str, Any, Dict[str, Any]]],
                               Dict[str, Tuple[str, str]]]:
    """The same reading, structured, for a transport that is not text.

    `(samples, metadata)` — samples are `(name, value, labels)` in emission
    order, metadata maps a name to `(kind, help)`. `P16-19` is the only caller.
    """
    out = _assemble()
    return out.samples(), out.metadata()
