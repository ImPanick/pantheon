# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1477` — Stop force-kills a model server that ignored the stop signal.

`_tmuxForceKill` and `_tmuxIsAliveCheck` in `static/js/cookbookRunning.js` were
written for "the Stop-all escalation" — vLLM can ignore SIGINT during model
init, and a stuck CUDA context can outlive `tmux kill-session` — and nothing
called them. Stop (and *Stop all*, which presses each task's Stop) now runs
`_stopTaskEscalating`: graceful first, then a check, then the force-kill only
if the session is still there; and a task still alive after that keeps its
card instead of being reported stopped.

Driven under node: the real `_stopTaskEscalating`, cut out of the file, over a
stubbed `/api/shell/exec` that answers the alive-check as a host would.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
RUNNING = ROOT / "static" / "js" / "cookbookRunning.js"

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _drive(alive_answers, *, windows=False):
    src = RUNNING.read_text(encoding="utf-8")
    body = js_function(src, "async function _stopTaskEscalating(task)")
    script = f"""
const sent = [];
const answers = {json.dumps(alive_answers)};
globalThis.fetch = async (url, opts) => {{
  const cmd = JSON.parse(opts.body).command;
  sent.push(cmd);
  const stdout = cmd === 'CHECK' ? (answers.shift() || 'DEAD') : '';
  return {{ ok: true, json: async () => ({{ stdout, exit_code: 0 }}) }};
}};
const _tmuxGracefulKill = () => 'GRACEFUL';
const _tmuxForceKill = () => 'FORCE';
const _tmuxIsAliveCheck = () => {'null' if windows else "'CHECK'"};
async function _stopTaskEscalating(task) {body}
_stopTaskEscalating({{ sessionId: 'serve-1' }}).then((how) => console.log(JSON.stringify({{ how, sent }})));
"""
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_node
def test_a_server_that_stopped_is_not_force_killed():
    got = _drive(["DEAD"])
    assert got == {"how": "stopped", "sent": ["GRACEFUL", "CHECK"]}


@needs_node
def test_a_server_that_ignored_the_signal_is_force_killed():
    got = _drive(["ALIVE", "DEAD"])
    assert got == {"how": "forced", "sent": ["GRACEFUL", "CHECK", "FORCE", "CHECK"]}


@needs_node
def test_a_server_that_survives_the_force_kill_is_said_to_be_alive():
    got = _drive(["ALIVE", "ALIVE"])
    assert got["how"] == "alive"


@needs_node
def test_windows_has_no_check_because_its_stop_already_forces():
    got = _drive([], windows=True)
    assert got == {"how": "stopped", "sent": ["GRACEFUL"]}


def test_stop_uses_it_and_keeps_a_card_that_is_still_alive():
    src = RUNNING.read_text(encoding="utf-8")
    assert src.count("_stopTaskEscalating(task)") >= 1
    i = src.index("const how = await _stopTaskEscalating(task);")
    after = src[i:i + 700]
    assert "how === 'alive'" in after and "return;" in after
    assert after.index("return;") < after.index("_animateOutThenRemove(el, task.sessionId)")
