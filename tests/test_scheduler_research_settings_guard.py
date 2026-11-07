# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1796`. One research setting that was not a number stopped every scheduled research.

`TaskScheduler._execute_research_task` read `research_max_tokens`,
`research_extraction_timeout_seconds` and `research_extraction_concurrency`
with a bare `int()`. The Settings page and the agent's `manage_settings` store
only numbers, but `POST /api/auth/settings` stores a key it has no rule for as
it was sent, a restored backup is not type-checked, and `settings.json` can be
edited by hand: one `"lots"`, `null` or `1e309` there raised in every scheduled
research and every workflow research step, with nothing naming the setting.
The research panel read the timeout and the concurrency through
`_bounded_int`, which missed the `OverflowError` of infinity, and the token
budget with a bare `int()` inside the try whose fallback quietly ran the
lesser engine.

Now both read the three through `research_run_settings`: a value that is not a
usable number is its default (16384, 90, 3, as `DEFAULT_SETTINGS` has them),
and a number outside the Settings page's own range is held to it, as the panel
already held two of the three. Ported from upstream Odysseus 268636c9 (#6473,
issue #5049); upstream's cases are below, with Pantheon's defaults, driven
through the real scheduler and the real panel rather than a helper.
"""
from __future__ import annotations

import json

import pytest

from tests.helpers.walker_harness import make_db

pytestmark = pytest.mark.asyncio

KEYS = ("research_max_tokens", "research_extraction_timeout_seconds",
        "research_extraction_concurrency")
DEFAULTS = (16384, 90, 3)
VALID = (4096, 45, 2)
INFINITY = json.loads("1e309")   # what `json.loads` makes of a too-large number


class _Researcher:
    """`DeepResearcher`, answering at once and keeping what it was built with."""

    built = []
    findings = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _Researcher.built.append(kwargs)

    async def research(self, prompt, **_kw):
        return f"# Report\n\nWhat I found about {prompt}."

    def get_stats(self):
        return {"rounds": 1}


def _stored(monkeypatch, values):
    """`get_setting` with *values* saved over `DEFAULT_SETTINGS`, as the store
    merges them; any other key is read from the store itself."""
    import src.settings as settings
    real = settings.get_setting

    def get_setting(key, default=None):
        if key in values:
            return values[key]
        if key in KEYS:
            return settings.DEFAULT_SETTINGS[key]
        return real(key, default)

    monkeypatch.setattr(settings, "get_setting", get_setting)


def _numbers(kwargs):
    return (kwargs["max_report_tokens"], kwargs["extraction_timeout"],
            kwargs["extraction_concurrency"])


def _cases():
    cases = []
    for bad in ("invalid", None, INFINITY, -INFINITY):
        for index, key in enumerate(KEYS):
            values = dict(zip(KEYS, VALID))
            values[key] = bad
            expected = list(VALID)
            expected[index] = DEFAULTS[index]
            cases.append(pytest.param(values, tuple(expected), id=f"{key}={bad!r}"))
    cases += [
        pytest.param(dict(zip(KEYS, ("4096", "45", "2"))), VALID, id="numeric-strings"),
        pytest.param(dict(zip(KEYS, (2048, 120, 6))), (2048, 120, 6), id="valid-ints"),
        pytest.param({}, DEFAULTS, id="unset"),
        # Outside the Settings page's own ranges: held to them, as the panel holds them.
        pytest.param(dict(zip(KEYS, (100, 5, 50))), (1024, 15, 12), id="out-of-range"),
    ]
    return cases


@pytest.mark.parametrize("values,expected", _cases())
async def test_a_scheduled_research_runs_whatever_its_settings_hold(monkeypatch, tmp_path, values, expected):
    import core.session_manager as sm_mod
    import src.deep_research as deep_research
    import src.research_handler as research_handler
    from core.database import ScheduledTask
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "research.db")
    monkeypatch.setattr(sm_mod, "SessionLocal", factory)
    monkeypatch.setattr(deep_research, "DeepResearcher", _Researcher)
    monkeypatch.setattr(research_handler, "RESEARCH_DATA_DIR", tmp_path / "research")
    _Researcher.built = []
    _stored(monkeypatch, values)
    scheduler = TaskScheduler(sm_mod.SessionManager())

    db = factory()
    try:
        task = ScheduledTask(id="rs", owner="alice", name="Weekly look", task_type="research",
                             prompt="local inference servers", status="active",
                             model="scripted", endpoint_url="http://127.0.0.1:9/v1")
        db.add(task)
        db.commit()
        report = await scheduler._execute_research_task(task, db, run_id="r1")
    finally:
        db.close()

    assert report.startswith("# Report")
    assert [_numbers(kwargs) for kwargs in _Researcher.built] == [expected]


@pytest.mark.parametrize("key,value", [("research_max_tokens", "lots")]
                         + [(key, INFINITY) for key in KEYS])
async def test_the_research_panel_builds_its_researcher_whatever_its_settings_hold(
        monkeypatch, tmp_path, key, value):
    """A bad token budget sent the panel's run to its fallback engine, and an
    infinite timeout or concurrency did the same, past `_bounded_int`."""
    import src.deep_research as deep_research
    import src.research_handler as research_handler

    monkeypatch.setattr(research_handler, "RESEARCH_DATA_DIR", tmp_path / "research")
    monkeypatch.setattr(deep_research, "DeepResearcher", _Researcher)
    _Researcher.built = []
    fell_back = []

    async def _probe(endpoint, model, headers=None):
        return None

    async def _fallback(self, *args, **kwargs):
        fell_back.append(args[-1] if args else kwargs)
        return "fallback"

    monkeypatch.setattr(research_handler.ResearchHandler, "_probe_endpoint", staticmethod(_probe))
    monkeypatch.setattr(research_handler.ResearchHandler, "_fallback_research", _fallback)
    _stored(monkeypatch, {key: value})

    handler = research_handler.ResearchHandler()
    await handler.call_research_service("local inference servers", "http://127.0.0.1:9/v1", "scripted")

    assert fell_back == [], fell_back
    expected = list(DEFAULTS)
    assert [_numbers(kwargs) for kwargs in _Researcher.built] == [tuple(expected)]
