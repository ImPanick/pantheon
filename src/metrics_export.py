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
    """

    def __init__(self) -> None:
        self._lines: List[str] = []
        self._declared: set = set()

    def metric(self, name: str, kind: str, help_text: str) -> None:
        if name in self._declared:
            return
        self._declared.add(name)
        self._lines.append(f"# HELP {name} {help_text}")
        self._lines.append(f"# TYPE {name} {kind}")

    def add(self, name: str, value: Any, labels: Optional[Dict[str, Any]] = None) -> None:
        self._lines.append(_line(name, value, labels))

    def render(self) -> str:
        return "\n".join(self._lines) + "\n"


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


def _collect_self_checks(out: _Out) -> None:
    """`P16-15`'s local assertions, as numbers.

    0=ok 1=attention 2=unknown 3=stuck. `unknown` sits between the two on
    purpose and is never folded into `ok`: *the check could not run* and
    *nothing is wrong* are different answers, and an alert rule written against
    `> 0` catches both.
    """
    from src.self_checks import run_self_checks
    result = run_self_checks() or {}
    out.metric("pantheon_self_check", "gauge",
               "Local self-check state: 0=ok 1=attention 2=unknown 3=stuck.")
    for check in (result.get("checks") or []):
        out.add("pantheon_self_check",
                _SELF_CHECK_VALUE.get(check.get("status"), 2),
                {"check": check.get("name") or "unknown"})


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
            from core.database import TaskRun
            n = (db.query(func.count(TaskRun.id))
                   .filter(TaskRun.status.in_(("queued", "running"))).scalar())
            out.add("pantheon_queue_depth", int(n or 0), {"queue": "task_runs"})
        except Exception as e:
            logger.debug("task_runs depth unavailable: %s", e)
    finally:
        db.close()


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
)


def render_metrics() -> str:
    """The scrape body.

    Each collector is isolated. A scrape endpoint that returns 500 because one
    subsystem is unwell is a monitoring system that goes blind exactly when it
    is needed — so a failing collector costs its own metrics and is itself
    reported, and everything else still arrives.
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
    return out.render()
