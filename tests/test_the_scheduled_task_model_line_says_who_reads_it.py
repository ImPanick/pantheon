# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1197` — Settings → *Model for scheduled tasks* says which work reads it,
and the order it falls back in, as measured on the callers.

**Measured** (this file drives each): a Prompt task that names no model —
`_execute_llm_task` → `TaskScheduler._usable_route` → `_resolve_defaults` →
`resolve_task_endpoint` — takes this setting, then Utility, then the default
chat model; so do the built-in actions and the e-mail pollers
(`resolve_task_candidates` with no fallback, or with its own first candidate).
That is what the line said since `P23-05`. What it did not say: a task that
names a model (or whose crew member does) runs on that, and a **Research** task
never reads this setting — `_execute_research_task` asks the Research Model
(`resolve_endpoint("research")`: Research, then Utility, then the default) — so
"What background and scheduled work runs on" was false for every scheduled
Research task. The line says both now.

Driven (`Law 20`): the real resolvers over a real SQLite file of endpoints and
the real settings reader (its file stood in), and the line read out of the
card it is in (`static/index.html`, the `set-taskEndpoint` card).
"""
from __future__ import annotations

import asyncio
import re
from html import unescape
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers.walker_harness import make_db

ROOT = Path(__file__).resolve().parents[1]


class _Resolved(Exception):
    """Raised by the stand-in for `_usable_route` once a run has resolved."""


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import core.database as cdb
    import src.endpoint_resolver as er
    import src.settings as settings_mod
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "models.db")
    monkeypatch.setattr(er, "SessionLocal", factory)
    monkeypatch.setattr(er, "resolve_url", lambda url: url)
    db = factory()
    for name in ("task", "utility", "default", "research"):
        db.add(cdb.ModelEndpoint(id=f"ep-{name}", name=name, is_enabled=True,
                                 base_url=f"http://127.0.0.1:9/{name}/v1", endpoint_kind="local",
                                 cached_models=f'["{name}-model"]'))
    db.commit()
    db.close()
    settings = {}
    monkeypatch.setattr(settings_mod, "load_settings", lambda: settings)

    def configure(**pairs):
        settings.clear()
        for prefix in pairs:
            settings[f"{prefix}_endpoint_id"] = f"ep-{prefix}"
            settings[f"{prefix}_model"] = f"{prefix}-model"
    return factory, TaskScheduler(None), configure


def _prompt_task_model(factory, s):
    """What `_execute_llm_task` runs a Prompt task that names no model on."""
    db = factory()
    try:
        task = SimpleNamespace(owner=None, task_type="llm", endpoint_url=None, model=None)
        return s._usable_route(db, task, None, None)[1]
    finally:
        db.close()


def _research_task_model(factory, s, monkeypatch):
    """What `_execute_research_task` resolves for a Research task that names
    no model — its own code, stopped at the hand-off to `_usable_route`."""
    seen = {}

    def stop(db, task, endpoint_url, model):
        seen["model"] = model
        raise _Resolved()
    monkeypatch.setattr(s, "_usable_route", stop)
    db = factory()
    try:
        task = SimpleNamespace(id="r", owner=None, name="Weekly scan", task_type="research",
                               endpoint_url=None, model=None, prompt="What changed?",
                               session_id=None, crew_member_id=None)
        with pytest.raises(_Resolved):
            asyncio.run(s._execute_research_task(task, db, run_id=None))
    finally:
        db.close()
    return seen["model"]


def test_a_prompt_task_naming_no_model_reads_this_then_utility_then_chat(world):
    factory, s, configure = world
    configure(task=1, utility=1, default=1)
    assert _prompt_task_model(factory, s) == "task-model"
    configure(utility=1, default=1)
    assert _prompt_task_model(factory, s) == "utility-model"
    configure(default=1)
    assert _prompt_task_model(factory, s) == "default-model"


def test_the_background_chain_reads_the_same_order(world):
    """The built-in actions and the e-mail pollers ask `resolve_task_candidates`."""
    from src.task_endpoint import resolve_task_candidates
    _factory, _s, configure = world
    configure(task=1, utility=1, default=1)
    assert resolve_task_candidates()[0][1] == "task-model"
    configure(utility=1, default=1)
    assert resolve_task_candidates()[0][1] == "utility-model"
    configure(default=1)
    assert resolve_task_candidates()[0][1] == "default-model"


def test_a_research_task_reads_the_research_model_not_this(world, monkeypatch):
    factory, s, configure = world
    configure(task=1, research=1, default=1)
    assert _research_task_model(factory, s, monkeypatch) == "research-model"
    configure(task=1, utility=1, default=1)
    assert _research_task_model(factory, s, monkeypatch) == "utility-model", (
        "an unset Research Model falls to Utility, never to the scheduled-task model")


def _card_line() -> str:
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    at = html.index('id="set-taskEndpoint"')
    card = html.rfind('<div class="admin-card"', 0, at)
    sub = re.search(r'<div class="admin-toggle-sub"[^>]*>(.*?)</div>', html[card:at], re.S)
    return " ".join(unescape(sub.group(1)).split())


def test_the_line_says_what_was_measured():
    line = _card_line()
    assert "when a task names no model of its own" in line, line
    assert "a Research task uses the Research Model" in line, line
    assert "Leave both empty to use the utility model, or the chat model if none is set." in line
