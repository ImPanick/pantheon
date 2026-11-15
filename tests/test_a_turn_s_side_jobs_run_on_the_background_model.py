# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2136`: what a chat turn sets off beside its answer runs on the background
model, whatever model that is, and as background work.

The owner, 2026-11-15: *"Pantheon should have a background model (extremely
lightweight) that already does this, no?... We just need to ensure that its
being model agnostic."* Measured on `fix/agent-lean-turn` before this: the
title, saved-memory and skill extraction jobs read the Background Tasks
setting and then the chat's own model, so a Utility model an admin set was
passed over; and every one of their calls went to a local server as
foreground work, never giving way to the person's next request.
"""
from __future__ import annotations

import asyncio

import pytest

from src import llm_core, task_endpoint


def _settings(monkeypatch, table):
    monkeypatch.setattr(task_endpoint, "resolve_endpoint",
                        lambda prefix, *a, owner=None, **k: table.get(prefix, (None, None, None)))


def test_the_background_tasks_model_comes_first(monkeypatch):
    _settings(monkeypatch, {"task": ("http://t/v1", "task-m", {}), "utility": ("http://u/v1", "util-m", {})})
    assert task_endpoint.resolve_side_job_endpoint("http://chat/v1", "chat-m", {})[1] == "task-m"


def test_then_the_utility_model(monkeypatch):
    _settings(monkeypatch, {"utility": ("http://u/v1", "util-m", {})})
    assert task_endpoint.resolve_side_job_endpoint("http://chat/v1", "chat-m", {})[1] == "util-m"


def test_with_neither_set_the_chat_s_own_model(monkeypatch):
    _settings(monkeypatch, {})
    assert task_endpoint.resolve_side_job_endpoint("http://chat/v1", "chat-m", {"a": "b"}) == (
        "http://chat/v1", "chat-m", {"a": "b"})


def test_a_call_inside_background_work_is_made_as_background():
    assert llm_core._gate_workload(None) == "foreground"
    with llm_core.background_workload():
        assert llm_core._gate_workload(None) == "background"
        assert llm_core._gate_workload("foreground") == "foreground", "a caller that names one keeps it"
    assert llm_core._gate_workload(None) == "foreground"


def test_the_extraction_jobs_run_as_background(monkeypatch):
    from routes import chat_helpers
    seen = []

    async def job():
        seen.append(llm_core._DEFAULT_WORKLOAD.get())

    monkeypatch.setattr(chat_helpers, "_is_session_stream_active", lambda sid: False)
    asyncio.run(chat_helpers._run_extraction_jobs_sequentially("s", [("memory", job()), ("skill", job())]))
    assert seen == ["background", "background"]


def test_a_job_that_gives_way_drops_the_rest_without_leaking_them(monkeypatch):
    from routes import chat_helpers
    ran = []

    async def preempted():
        raise asyncio.CancelledError

    async def later():
        ran.append("later")

    monkeypatch.setattr(chat_helpers, "_is_session_stream_active", lambda sid: False)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(chat_helpers._run_extraction_jobs_sequentially(
            "s", [("memory", preempted()), ("skill", later())]))
    assert ran == []
