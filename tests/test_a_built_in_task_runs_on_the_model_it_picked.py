# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2100`. A built-in task's Model choice was saved and shown, and ignored.

The task form offers Model for every type of task and the list shows
"model: ...", but `TaskScheduler._execute_action` passed an action only its
owner, name, progress callback and prompt, and the model-backed actions asked
`resolve_task_candidates`, which had no per-task choice: the Background Tasks
model from Settings always won. Now a model-backed action whose task names a
model runs on that model only (the pick checked by `_usable_route`, the check a
Prompt task gets), a pick no endpoint lists any more fails the run with a
sentence instead of falling back to the default, and the Settings switch
`task_model_over_task_choice` puts the Background Tasks model back over every
pick. An action that calls no model, and a task that names none, keep the chain.

Driven (`Law 20`): the real `_execute_action` and the real resolvers over a real
SQLite file of endpoints, with the action itself replaced by one that asks the
resolver every model-backed action asks.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.helpers.walker_harness import make_db

MODEL_BACKED = "check_email_urgency"


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import core.database as cdb
    import src.builtin_actions as ba
    import src.endpoint_resolver as er
    import src.settings as settings_mod
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "models.db")
    monkeypatch.setattr(er, "SessionLocal", factory)
    monkeypatch.setattr(er, "resolve_url", lambda url: url)
    db = factory()
    db.add(cdb.ModelEndpoint(id="ep-task", name="task", is_enabled=True,
                             base_url="http://127.0.0.1:9/task/v1", endpoint_kind="local",
                             cached_models='["task-model"]'))
    db.add(cdb.ModelEndpoint(id="ep-picked", name="picked", is_enabled=True,
                             base_url="http://127.0.0.1:9/picked/v1", endpoint_kind="local",
                             cached_models='["picked-model"]'))
    db.commit()
    db.close()
    settings = {"task_endpoint_id": "ep-task", "task_model": "task-model"}
    monkeypatch.setattr(settings_mod, "load_settings", lambda: settings)

    asked = []

    async def action(owner, **_kwargs):
        from src.task_endpoint import resolve_task_candidates
        asked.append([model for _url, model, _h in resolve_task_candidates(owner=owner or None)])
        return "done", True

    assert MODEL_BACKED in ba.MODEL_BACKED_ACTIONS
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, MODEL_BACKED, action)
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", action)
    return TaskScheduler(None), settings, asked


def _task(action=MODEL_BACKED, model=None):
    return SimpleNamespace(id="t", owner=None, name="Email Tags", action=action,
                           prompt="", model=model, endpoint_url=None)


async def test_a_task_that_picked_a_model_runs_on_it_and_only_it(world):
    s, _settings, asked = world
    node = await s._execute_action(_task(model="picked-model"))
    assert node.status != "error", node.payload
    assert asked == [["picked-model"]], "the pick is the only candidate, never the default"


async def test_a_task_that_names_no_model_keeps_the_background_chain(world):
    s, _settings, asked = world
    await s._execute_action(_task(model=None))
    assert asked and asked[0][0] == "task-model"


async def test_a_pick_no_endpoint_lists_fails_with_a_sentence_and_runs_nothing(world):
    s, _settings, asked = world
    node = await s._execute_action(_task(model="gone-model"))
    assert node.status == "error"
    assert "gone-model isn't listed by any endpoint now" in str(node.payload), node.payload
    assert asked == [], "nothing runs on the default in its place"


async def test_the_settings_switch_puts_the_background_model_over_every_pick(world):
    s, settings, asked = world
    settings["task_model_over_task_choice"] = True
    await s._execute_action(_task(model="picked-model"))
    assert asked and asked[0][0] == "task-model"


async def test_an_action_that_calls_no_model_is_not_pinned(world):
    s, _settings, asked = world
    await s._execute_action(_task(action="tidy_sessions", model="gone-model"))
    assert asked and asked[0][0] == "task-model", "a non-model action is not refused over a model"


def test_the_switch_is_declared_off_and_drawn_in_the_scheduled_task_card():
    from pathlib import Path
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["task_model_over_task_choice"] is False
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    card = html[html.rfind('<div class="admin-card"', 0, html.index('id="set-taskEndpoint"')):]
    card = card[:card.index('id="set-taskModelMsg"')]
    assert 'id="set-taskModelOverTasks"' in card
