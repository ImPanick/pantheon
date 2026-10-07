# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-6`): the Forge opens on the rows it has.

`GET /api/hwfit/models?refresh_catalog=1` ran the HuggingFace catalog refresh
inline — up to 40 sequential requests — and the Forge waited on it. Measured on
`32df791`: 8,102 ms the first time, 1,768 ms after, against 98 ms without the
refresh; the Forge asks for it after every paint from its cache, and the
mlx-community half had no floor, so each ask went to the host again.

Now the refresh runs in a thread, one at a time and at most once per five
minutes; the answer carries the cached rows and the refresh's state; the Forge
follows `GET /api/hwfit/catalog-refresh` and draws once more when it is done.
Driven: the real route handler with the refresh slowed down, and the Forge's
follow-up under node with fake timers.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from routes.hwfit_routes import setup_hwfit_routes
from tests.helpers.js_source import js_definition

_REPO = Path(__file__).resolve().parents[1]


def _route(path: str):
    for route in setup_hwfit_routes().routes:
        if getattr(route, "path", "").endswith(path) and "GET" in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"hwfit {path} route not found")


@pytest.fixture()
def slow_refresh(monkeypatch):
    import services.hwfit.models as models
    import src.model_hubs as model_hubs

    # `B1229`: the refresh starts only with the Forge's switch for Hugging Face
    # on (`tests/test_the_forge_reaches_hugging_face_only_when_an_admin_says.py`).
    monkeypatch.setattr(model_hubs, "allowed", lambda: True)

    calls = []
    release = threading.Event()

    def refresh(force=False):
        calls.append(force)
        release.wait(5)
        return {"mlx_community": 3, "hf_collections": 4}

    monkeypatch.setattr(models, "refresh_dynamic_catalogs", refresh)
    monkeypatch.setattr(models, "_refresh_state", {"state": "idle"})
    yield models, calls, release
    release.set()


def _until(predicate, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_the_list_answers_while_the_refresh_runs(slow_refresh):
    models, calls, release = slow_refresh
    start = time.monotonic()
    payload = _route("/models")(limit=50, refresh_catalog=True)
    elapsed = time.monotonic() - start
    assert elapsed < 1.5, f"the list waited {elapsed:.1f}s on the refresh"
    assert payload["models"], "no cached rows came back"
    assert payload["catalog_refresh"]["state"] == "running"
    assert _until(lambda: calls == [True])
    release.set()
    assert _until(lambda: models.catalog_refresh_status()["state"] == "done")
    status = _route("/catalog-refresh")()
    assert status["refreshed"] == {"mlx_community": 3, "hf_collections": 4}


def test_one_refresh_at_a_time_and_not_again_for_five_minutes(slow_refresh):
    models, calls, release = slow_refresh
    handler = _route("/models")
    for _ in range(3):
        assert handler(limit=5, refresh_catalog=True)["catalog_refresh"]["state"] == "running"
    release.set()
    assert _until(lambda: models.catalog_refresh_status()["state"] == "done")
    again = handler(limit=5, refresh_catalog=True)["catalog_refresh"]
    assert again["state"] == "done"
    assert calls == [True], f"{len(calls)} refreshes for four asks"


def test_a_failed_refresh_is_said_and_the_rows_stay(slow_refresh, monkeypatch):
    models, calls, release = slow_refresh

    def broken(force=False):
        raise RuntimeError("huggingface.co said 429")

    monkeypatch.setattr(models, "refresh_dynamic_catalogs", broken)
    payload = _route("/models")(limit=5, refresh_catalog=True)
    assert payload["models"]
    assert _until(lambda: models.catalog_refresh_status()["state"] == "failed")
    assert "429" in models.catalog_refresh_status()["error"]


_FOLLOW = r"""
let now = 0;
const timers = [];
globalThis.Date = { now: () => now };
globalThis.setInterval = (fn, ms) => { const t = { fn, ms, at: now + ms }; timers.push(t); return t; };
globalThis.clearInterval = (t) => { const i = timers.indexOf(t); if (i >= 0) timers.splice(i, 1); };
globalThis.document = { getElementById: () => ({}) };
const answers = __ANSWERS__;
const asked = [];
globalThis.fetch = async (url) => { asked.push(url); const a = answers.shift() || { state: 'running' }; return { ok: true, json: async () => a }; };
const redraws = [];
const _hwfitFetch = (fresh, opts) => { redraws.push({ fresh, opts }); };
__FN__
(async () => {
  _followCatalogRefresh(__START__);
  _followCatalogRefresh(__START__);          // a second answer while following
  for (let i = 0; i < 80 && timers.length; i++) {
    const t = timers[0]; now = t.at; t.at += t.ms; await t.fn(); await Promise.resolve();
  }
  console.log(JSON.stringify({ asked: asked.length, redraws, left: timers.length }));
})();
"""


def _follow(tmp_path, start, answers):
    src = (_REPO / "static/js/cookbook-hwfit.js").read_text(encoding="utf-8")
    consts = "const _CATALOG_FOLLOW_MS = 2000;\nconst _CATALOG_FOLLOW_FOR_MS = 120000;\nlet _catalogFollowTimer = null;\n"
    fn = consts + js_definition(src, src.index("function _followCatalogRefresh("))
    script = tmp_path / "follow.cjs"
    script.write_text(_FOLLOW.replace("__FN__", fn).replace("__START__", json.dumps(start))
                      .replace("__ANSWERS__", json.dumps(answers)), encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_the_forge_draws_once_more_when_the_refresh_is_done(tmp_path):
    out = _follow(tmp_path, {"state": "running"},
                  [{"state": "running"}, {"state": "running"}, {"state": "done"}])
    assert out["asked"] == 3
    assert out["redraws"] == [{"fresh": False, "opts": {"keepPrevious": True, "afterCatalogRefresh": True}}]
    assert out["left"] == 0


def test_nothing_to_follow_when_no_refresh_is_running(tmp_path):
    out = _follow(tmp_path, {"state": "done"}, [])
    assert out == {"asked": 0, "redraws": [], "left": 0}


def test_a_failed_refresh_draws_nothing_new(tmp_path):
    out = _follow(tmp_path, {"state": "running"}, [{"state": "failed", "error": "429"}])
    assert out["redraws"] == [] and out["left"] == 0
