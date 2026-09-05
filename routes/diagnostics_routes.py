"""Diagnostics routes — /api/db/stats, /api/rag/stats, /api/test/youtube, /api/test-research."""

import logging
import os
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Form, Request

from services.youtube.youtube_handler import extract_youtube_id, extract_transcript_async
from core.constants import DEFAULT_HOST, DATA_DIR
from core.middleware import require_admin

logger = logging.getLogger(__name__)


def _issue_tracker_url() -> str:
    """Where "report this" points. A setting, not a constant.

    `D-2026-09-01-01` says the people running this include companies making it
    their own private stack. Their bug reports belong in their tracker, not in
    the upstream repo, and hardcoding one address decides that for them. The
    default is Pantheon's own issues page because that is the honest default for
    a fork of this project — and it is a **link the person clicks**, never a
    request this server makes. Nothing here fetches it.
    """
    try:
        from src.settings import get_setting
        configured = str(get_setting("issue_tracker_url", "") or "").strip()
    except Exception:
        configured = ""
    if configured:
        return configured
    # The env layer is REACHABLE here only because the default is falsy.
    # `get_setting` merges DEFAULT_SETTINGS on every read, so beneath a truthy
    # default this line could never run — that is `H06`/`B20`, and `P16-05` hit
    # the same shape from the other side. The distinction is truthiness, not the
    # pattern.
    return (os.environ.get("PANTHEON_ISSUE_TRACKER_URL") or "").strip()


def setup_diagnostics_routes(
    rag_manager,
    rag_available: bool,
    research_handler,
    memory_vector=None,
) -> APIRouter:
    router = APIRouter(tags=["diagnostics"])

    @router.get("/api/diagnostics/services")
    async def get_service_health(request: Request) -> Dict[str, Any]:
        """Consolidated degraded-state report for ChromaDB, SearXNG, email,
        ntfy, and provider endpoints. Non-intrusive probes — safe to poll."""
        require_admin(request)
        from src.service_health import collect_service_health
        return await collect_service_health(rag_manager, memory_vector)

    @router.get("/api/diagnostics/self-check")
    async def get_self_check(request: Request) -> Dict[str, Any]:
        """What is quietly wrong on this machine.

        Distinct from `/services` above, which asks *can I reach X* — liveness.
        This asks *is something accumulating, or has something quietly stopped*.
        `H01` is why both exist: the mail server was reachable the whole time a
        year of agent-written email sat staged and invisible. Liveness said green.

        Local only, cheap, safe to poll.
        """
        require_admin(request)
        from src.self_checks import run_self_checks
        return run_self_checks()

    @router.get("/metrics")
    async def prometheus_metrics(request: Request):
        """Prometheus scrape endpoint (`P16-12`).

        `/metrics` rather than `/api/metrics`: it is the one place convention
        beats this app's own prefix, because it is what an operator will type
        and what every scrape example already assumes.

        **This endpoint answers; it never sends.** There is no destination
        anywhere in it and no place for one — `Law 16` clause 4 is satisfied by
        the shape of a pull, not by a policy about a push. `.pantheon/
        check-destinations.py` fails the build if an address ever appears.

        Authenticated, because aggregate usage is still the operator's business
        and this is reachable on whatever address Pantheon is bound to. An API
        token with `metrics:read` is the intended credential — Prometheus sends
        it natively via `authorization: credentials:` — and an admin browser
        session works too, so a person can just open the URL and look.

        Off by default (`metrics_enabled`). A monitoring endpoint nobody
        configured is attack surface nobody asked for.
        """
        from fastapi.responses import PlainTextResponse
        from src.settings import get_setting

        enabled = bool(get_setting("metrics_enabled", False)) or (
            (os.environ.get("PANTHEON_METRICS_ENABLED") or "").strip().lower()
            in ("1", "true", "yes", "on")
        )
        if not enabled:
            # 404 rather than 403: a disabled endpoint should be indistinguishable
            # from one that was never built.
            raise HTTPException(404, "Metrics endpoint is disabled")

        if getattr(request.state, "api_token", False):
            scopes = set(getattr(request.state, "api_token_scopes", []) or [])
            if "metrics:read" not in scopes:
                raise HTTPException(403, "API token missing required scope: metrics:read")
        else:
            require_admin(request)

        from src.metrics_export import render_metrics
        return PlainTextResponse(
            render_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @router.get("/api/diagnostics/usage")
    async def get_usage(request: Request, days: int = 30,
                        owner: str = "") -> Dict[str, Any]:
        """What has actually been used, over time (`P14-01`).

        The question the running counters on a session row could never answer:
        they hold a conversation's lifetime total and discard the time it
        happened at. This reads the events table.

        Deliberately minimal — `P14-05` builds the per-model, per-owner views
        this phase is really for. It exists now so `P14-01` ships with a reader
        rather than a write-only table. Finished work with no door is the whole
        `H` series, and a measurement phase should not open by adding another.
        """
        require_admin(request)
        from src.events import usage_summary, usage_over_time
        days = max(1, min(days, 365))
        result = usage_summary(days=days, owner=owner or None)
        # `P14-05` — the same call carries the time series, because a caller
        # that has to make two requests to draw one chart will eventually draw
        # it from one of them.
        result["over_time"] = usage_over_time(days=days, owner=owner or None)
        return result

    @router.get("/api/diagnostics/receipt/{run_id}")
    async def get_receipt(request: Request, run_id: str) -> Dict[str, Any]:
        """Everything one turn did (`P4-25`).

        Assembled from rows that already exist — the config `P4-25` had to add,
        plus the rounds, tool calls, retrievals and approvals `P14-01` and
        `P14-02` were already writing. It is a range scan on `run_id`, not a
        second store (`Law 14`).

        No message content: a receipt says which model, which tools, which
        skills, how many rounds and what they cost. That is what makes it
        portable (`P4-27`) — a receipt you cannot hand to someone is not one.
        """
        require_admin(request)
        from src.events import receipt
        return receipt(run_id)

    @router.get("/api/diagnostics/rerun/{run_id}")
    async def get_rerun_plan(request: Request, run_id: str) -> Dict[str, Any]:
        """What it would take to re-run this receipt, and what has moved (`P4-26`).

        Read-only. It costs no model call, which is the point of having it
        separate: *"same inputs, same configuration"* is a claim, and someone
        should be able to check it before spending a request on it.
        """
        require_admin(request)
        from src.replay import rerun_plan, describe
        plan = rerun_plan(run_id)
        return {**plan, "summary": describe(plan)}

    @router.post("/api/diagnostics/rerun/{run_id}")
    async def do_rerun(request: Request, run_id: str, model: str = "") -> Dict[str, Any]:
        """Re-run it. Same inputs, same configuration, **new run** (`P4-26`).

        POST because it spends a model call. `model` overrides the recorded one,
        which is the whole point for *"is the new model better"* — and it is
        recorded as **deliberate** drift, so `P4-28` can tell a choice from an
        accident.

        The replay does not touch the session. It is a diagnostic, not a
        conversation: appending its output would change the thing being measured
        and put a machine-generated turn in front of the person next time they
        scrolled up.
        """
        require_admin(request)
        from src.replay import replay
        return await replay(run_id, model=model or None)

    @router.get("/api/diagnostics/evals")
    async def list_evals(request: Request) -> Dict[str, Any]:
        """The suites, and whether each one would run (`P14-03`).

        Validated here so a typo costs a page load rather than a set of model
        calls — an unknown check would otherwise never run, and the suite would
        pass for the wrong reason.
        """
        require_admin(request)
        from src.evals import load_suites, validate_suite
        return {"suites": [
            {"name": s.get("name"), "cases": len(s.get("cases") or []),
             "problems": validate_suite(s)}
            for s in load_suites()
        ]}

    @router.post("/api/diagnostics/evals/{name}/run")
    async def run_eval(request: Request, name: str, model: str = "") -> Dict[str, Any]:
        """Replay every case and score it. POST — it spends a model call each.

        `model` runs the whole suite against a different one, which is the
        question the harness exists for: *did that change help.*
        """
        require_admin(request)
        from src.evals import run_suite
        return await run_suite(name, model=model or None)

    @router.get("/api/diagnostics/bundle")
    async def get_diagnostic_bundle(
        request: Request, note: str = "", log_limit: int = 120
    ) -> Dict[str, Any]:
        """A bug report, assembled locally, redacted, and sent nowhere.

        `P16-14`. This endpoint **builds** — it does not transmit. There is no
        collector URL here and there is no place for one; the response goes to
        the browser that asked, the person reads and edits it, and they choose
        a destination per incident or choose none. That is what makes it
        `Law 16`-clean rather than merely low-volume.

        `note` is the person's own description, echoed back through the same
        redactor as everything else — they may paste a path or an endpoint into
        it without thinking, and a redactor that trusts one field is a redactor
        with a hole in it.
        """
        require_admin(request)
        from src.diagnostic_bundle import build_bundle, render_markdown
        bundle = build_bundle(note=note, log_limit=log_limit)
        return {
            "status": "success",
            "bundle": bundle,
            "markdown": render_markdown(bundle),
            "issue_url": _issue_tracker_url(),
        }

    @router.get("/api/diagnostics/logs")
    async def get_diagnostics_logs(request: Request, limit: int = 200) -> Dict[str, Any]:
        require_admin(request)
        limit = max(1, min(limit, 1000))
        try:
            log_file = os.path.join(DATA_DIR, "logs", "app.log")
            if not os.path.exists(log_file):
                return {"status": "success", "logs": []}

            # Safe tail read of the log file (max 5MB via rotation)
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            tail_lines = lines[-limit:] if len(lines) > limit else lines
            tail_lines = [line.rstrip('\r\n') for line in tail_lines]

            return {
                "status": "success",
                "logs": tail_lines
            }
        except Exception as e:
            logger.error(f"Diagnostics logs retrieval error: {e}")
            raise HTTPException(500, f"Failed to retrieve logs: {str(e)}")

    @router.get("/api/db/stats")
    async def get_database_stats(request: Request) -> Dict[str, Any]:
        require_admin(request)
        try:
            from core.database import get_detailed_stats
            return get_detailed_stats()
        except Exception as e:
            logger.error(f"DB stats error: {e}")
            raise HTTPException(500, "Failed to retrieve database statistics")

    @router.get("/api/rag/stats")
    async def get_rag_stats(request: Request) -> Dict[str, Any]:
        require_admin(request)
        if rag_available and rag_manager:
            return rag_manager.get_stats()
        return {"error": "RAG system not available"}

    @router.get("/api/test/youtube")
    async def test_youtube(request: Request, url: str) -> Dict[str, Any]:
        require_admin(request)
        try:
            video_id = extract_youtube_id(url)
            if not video_id:
                return {"error": "Invalid YouTube URL"}

            data = await extract_transcript_async(url, video_id)
            return {
                "video_id": video_id,
                "transcript_success": data.get("success", False),
                "transcript_length": len(data.get("transcript", "")) if data.get("success") else 0,
                "transcript_preview": (data.get("transcript", "")[:500] + "...")
                    if data.get("success") and len(data.get("transcript", "")) > 500
                    else data.get("transcript", ""),
                "error": data.get("error") if not data.get("success") else None,
            }
        except Exception as e:
            return {"error": str(e)}

    @router.post("/api/test-research")
    async def test_research(request: Request, query: str = Form("What is machine learning?")) -> Dict[str, Any]:
        require_admin(request)
        try:
            endpoint = f"http://{DEFAULT_HOST}:8000/v1/chat/completions"
            model = "gpt-oss-120b"
            result = await research_handler.call_research_service(query, endpoint, model)
            return {
                "status": "success",
                "query": query,
                "result_preview": result[:200] + "..." if len(result) > 200 else result,
                "result_length": len(result),
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "query": query}

    return router
