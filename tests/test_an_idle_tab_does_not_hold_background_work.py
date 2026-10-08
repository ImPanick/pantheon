# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-11`, contract C-IDLE): a tab left open is not a person.

The page beat `POST /api/activity/heartbeat` every 15 s while visible, and every
beat refreshed the gate's 45 s "browser active" window. Measured by the perf
audit on `9560d50`: 6 beats in 90 s of a visible, untouched tab. With
`BACKGROUND_TASK_MAX_WAIT_SECONDS=0` (the default) `wait_for_interactive_quiet`
waits for ever, so the background inbox check never looked, and every tick of
`_check_due_tasks` moved a due scheduled run 15 minutes on (`B1094`) — a tab on
a second monitor meant no 08:00 run and no mail all day.

C-IDLE: the interval beat carries `{"idle": true}` and the gate ignores it; a
beat from a key, a pointer, a scroll, focus or the tab coming forward still
counts. Driven: the page's own heartbeat function under node, the route's own
code (`on_heartbeat`) against the real gate and the real scheduler, and the
real route in the real app.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import textwrap
from datetime import timedelta
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition

from test_a_background_run_waits_for_idle_with_its_trigger import (  # noqa: F401
    _scheduler, _seed, _task, _until, gate, task_db, ig, ts, ScheduledTask,
)

_REPO = Path(__file__).resolve().parents[1]
IDLE = b'{"idle": true}'


# ── the page ────────────────────────────────────────────────────────────────

_PAGE = r"""
const beats = [];
let now = 1_000_000;
let tick = null;
const listeners = {};
const on = (target) => (type, fn) => { (listeners[target + ':' + type] ||= []).push(fn); };
globalThis.Date = { now: () => now };
globalThis.window = { addEventListener: on('window') };
globalThis.document = { visibilityState: 'visible', addEventListener: on('document') };
// Node 22 has a read-only global `navigator`; plain assignment is ignored.
Object.defineProperty(globalThis, 'navigator', { configurable: true,
  value: { sendBeacon(url, blob) { beats.push({ url, blob }); return true; } } });
globalThis.setInterval = (fn, ms) => { tick = { fn, ms }; return 1; };
globalThis.fetch = () => Promise.reject(new Error('sendBeacon answered'));
__FN__
const fire = (key) => (listeners[key] || []).forEach(fn => fn());
const steps = [];
const step = async (name, act) => {
  const before = beats.length;
  act();
  const sent = [];
  for (const b of beats.slice(before)) sent.push(await b.blob.text());
  steps.push({ name, sent });
};
(async () => {
  await step('load', () => initForegroundActivityHeartbeat());
  await step('interval, untouched', () => { now += 15000; tick.fn(); });
  await step('a key 1 s later', () => { now += 1000; fire('window:keydown'); });
  await step('another key 5 s later', () => { now += 5000; fire('window:keydown'); });
  await step('interval 9 s after the key', () => { now += 9000; tick.fn(); });
  await step('interval, untouched again', () => { now += 15000; tick.fn(); });
  await step('focus', () => { now += 500; fire('window:focus'); });
  await step('hidden interval', () => { document.visibilityState = 'hidden'; now += 30000; tick.fn(); });
  await step('tab comes forward', () => { document.visibilityState = 'visible'; fire('document:visibilitychange'); });
  console.log(JSON.stringify({ interval: tick.ms, url: beats[0] && beats[0].url, steps }));
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def page_beats(tmp_path_factory) -> dict:
    src = (_REPO / "static" / "app.js").read_text(encoding="utf-8")
    fn = js_definition(src, src.index("function initForegroundActivityHeartbeat("))
    script = tmp_path_factory.mktemp("beats") / "beats.cjs"
    script.write_text(_PAGE.replace("__FN__", fn), encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    out["by"] = {s["name"]: s["sent"] for s in out["steps"]}
    return out


def test_the_page_says_idle_on_the_interval_and_present_on_input(page_beats):
    by = page_beats["by"]
    assert page_beats["url"] == "/api/activity/heartbeat"
    assert by["load"] == ["{}"]
    assert by["interval, untouched"] == ['{"idle":true}']
    assert by["interval, untouched again"] == ['{"idle":true}']
    assert by["focus"] == ["{}"]
    assert by["tab comes forward"] == ["{}"]


def test_an_idle_beat_does_not_swallow_the_key_a_person_comes_back_with(page_beats):
    by = page_beats["by"]
    assert by["a key 1 s later"] == ["{}"]
    # The 12 s gap still spaces a person's beats out …
    assert by["another key 5 s later"] == []
    # … and a person who beat recently needs no idle beat on top.
    assert by["interval 9 s after the key"] == []


def test_a_hidden_tab_sends_nothing(page_beats):
    assert page_beats["by"]["hidden interval"] == []


# ── the gate ────────────────────────────────────────────────────────────────


def test_only_the_word_idle_is_idle():
    assert ig.heartbeat_says_idle(IDLE) is True
    assert ig.heartbeat_says_idle('{"idle":true}') is True
    # A person, as every beat meant before this row: an older cached page
    # sends `{}`, and nothing that is not exactly `true` is idle.
    for body in (b"", b"{}", b'{"idle": false}', b'{"idle": "yes"}', b"not json", b"[true]", None):
        assert ig.heartbeat_says_idle(body) is False, body


@pytest.mark.asyncio
async def test_an_idle_beat_leaves_the_gate_quiet_and_a_person_does_not(gate):
    stopped = []

    async def stop(reason=""):
        stopped.append(reason)

    assert await ig.on_heartbeat(IDLE, stop) == {"ok": True, "idle": True}
    assert ig.has_foreground_activity() is False
    # The inbox check's wait: answered at once, nothing waited for.
    assert await asyncio.wait_for(ig.wait_for_interactive_quiet("inbox"), 1) is False
    await asyncio.sleep(0)
    assert stopped == [], "an idle beat stopped background work"

    assert await ig.on_heartbeat(b"{}", stop) == {"ok": True}
    assert ig.has_foreground_activity() is True
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ig.wait_for_interactive_quiet("inbox"), 0.3)
    for _ in range(5):
        await asyncio.sleep(0)
    assert stopped == ["browser heartbeat"]


# ── the scheduler: the row's `Verify:` ──────────────────────────────────────


def _morning(now):
    return ScheduledTask(id="morning", owner="alice", name="Morning digest",
                         prompt="What came in overnight?", task_type="llm",
                         trigger_type="schedule", schedule="daily", status="active",
                         output_target="session", next_run=now - timedelta(minutes=1))


@pytest.mark.asyncio
async def test_a_tab_left_open_and_idle_does_not_stop_the_0800_run(task_db, gate, monkeypatch):
    monkeypatch.setattr(ts, "dispatch_hold", lambda *a, **k: 0)
    now = ts._utcnow()
    _seed(task_db, _morning(now))
    ran = []
    s = _scheduler(ran)
    # The tab is open, nobody touches it: the page beats on its interval.
    for _ in range(3):
        await ig.on_heartbeat(IDLE, s.stop_background_tasks_for_foreground)
    await s._check_due_tasks()
    await _until(lambda: ran, "the 08:00 run ran")
    assert [task_id for task_id, _ in ran] == ["morning"]


@pytest.mark.asyncio
async def test_a_person_at_the_tab_still_holds_a_due_run_back(task_db, gate, monkeypatch):
    """Unchanged (`Law 1`): a person using Pantheon still defers the run —
    which `B1094` says is moved 15 minutes with nothing said, a separate row."""
    monkeypatch.setattr(ts, "dispatch_hold", lambda *a, **k: 0)
    now = ts._utcnow()
    _seed(task_db, _morning(now))
    ran = []
    s = _scheduler(ran)
    await ig.on_heartbeat(b"{}", s.stop_background_tasks_for_foreground)
    await s._check_due_tasks()
    for _ in range(50):
        await asyncio.sleep(0)
    assert ran == []
    assert _task(task_db, "morning").next_run > now + timedelta(minutes=14)


# ── the real route ──────────────────────────────────────────────────────────

_ROUTE_PROBE = textwrap.dedent(
    """
    import json
    import app as app_module
    from tests.helpers.signed_in import sign_in
    import src.interactive_gate as ig
    from fastapi.testclient import TestClient
    out = {}
    with TestClient(app_module.app) as client:
        sign_in(app_module, client)  # the install's admin: there is always authentication (`D-2026-10-07-02` §2)
        r = client.post("/api/activity/heartbeat", content=b'{"idle":true}',
                        headers={"Content-Type": "application/json"})
        out["idle"] = [r.status_code, r.json(), ig._LAST_BROWSER_ACTIVITY > 0]
        r = client.post("/api/activity/heartbeat", content=b"{}",
                        headers={"Content-Type": "application/json"})
        out["person"] = [r.status_code, r.json(), ig._LAST_BROWSER_ACTIVITY > 0]
    print("RESULT " + json.dumps(out))
    """
)


def test_the_route_is_the_gates_answer(tmp_path):
    env = os.environ.copy()
    env.update({
        "CHROMADB_CONNECT_TIMEOUT": "0.01", "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9", "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "PANTHEON_DATA_DIR": str(tmp_path), "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(_REPO), "PYTHON_DOTENV_DISABLED": "1",
        "BACKGROUND_TASK_FOREGROUND_GATE": "true",
    })
    done = subprocess.run([sys.executable, "-c", _ROUTE_PROBE], cwd=_REPO, env=env,
                          capture_output=True, text=True, timeout=240)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, done.stderr[-4000:]
    out = json.loads(line[len("RESULT "):])
    assert out["idle"] == [200, {"ok": True, "idle": True}, False]
    assert out["person"] == [200, {"ok": True}, True]
