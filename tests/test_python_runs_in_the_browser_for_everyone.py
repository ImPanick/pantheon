# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1474`, `D-2026-10-25-04` §1 — a Python block runs for everyone.

The *Run* button on a Python block sent the code to `/api/shell/exec`, which is
an admin's, so for everyone else it did nothing useful — while Pyodide sat
vendored at `static/lib/pyodide/` (13 MB) with `runPython` uncalled since v1.0.
The owner: *"Let users run."* An admin keeps the server run; everyone else runs
the block in their own browser.

Not in the app's page. The old `runPython` loaded Pyodide into it, where a block
could `import js` and act as the person in this app. It runs in
`/python-sandbox` — served and framed with `sandbox allow-scripts`, so
an opaque origin — on a Worker that frame starts, because Chromium runs a
sandboxed frame on its parent's thread and an in-frame `while True` froze the
whole app before the timeout could fire. A run that overstays is stopped by
removing the frame.

Driven, not read (`Law 20`): the real app out of process, the real
`codeRunner.js` in headless Chromium, each case run through `runPython`.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, _free_port  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
USER, PASSWORD = "runner", "runner-pass-1"

CASES = [
    ["hello", "print(sum(range(10)))"],
    ["error", "raise ValueError('boom')"],
    ["cookie", "import js\nprint(repr(js.document.cookie))"],
    ["storage", "import js\ntry:\n    js.localStorage.setItem('x', '1'); print('storage ok')\n"
                "except Exception as e:\n    print('no storage')"],
    ["api", "import js\nx = js.XMLHttpRequest.new()\nx.open('GET', BASE + '/api/auth/me', False)\n"
            "try:\n    x.send(); print('status', x.status)\nexcept Exception as e:\n    print('refused')"],
    ["loop", "while True: pass"],
    ["after", "print('again', 6 * 7)"],
]


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    data = tmp_path_factory.mktemp("pyrun")
    port = _free_port()
    env = dict(os.environ, PANTHEON_DATA_DIR=str(data), APP_PORT=str(port), APP_BIND="127.0.0.1",
               PANTHEON_DISABLE_MCP="1", AUTH_ENABLED="true", LOCALHOST_BYPASS="false")
    env.pop("DATABASE_URL", None)
    log = open(data / "app.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 120
        while True:
            if proc.poll() is not None:
                log.flush()
                pytest.fail("the app exited during start-up:\n"
                            + (data / "app.log").read_text(encoding="utf-8")[-3000:])
            try:
                with urllib.request.urlopen(url + "/login", timeout=2) as res:
                    if res.status == 200:
                        break
            except (urllib.error.URLError, OSError):
                pass
            if time.monotonic() > deadline:
                pytest.fail("the app did not answer /login within 120 s")
            time.sleep(0.5)
        yield url
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()


_SCRIPT = r"""
const { chromium } = require('playwright');
const [BASE, USER, PASSWORD, CASES_JSON] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext();
  await ctx.request.post(BASE + '/api/auth/setup', { data: { username: USER, password: PASSWORD } });
  await ctx.request.post(BASE + '/api/auth/login', { data: { username: USER, password: PASSWORD, remember: true } });
  const out = { headers: {} };
  for (const path of ['/python-sandbox', '/static/lib/pyodide/pyodide.js', '/static/js/codeRunner.js']) {
    const r = await ctx.request.get(BASE + path);
    out.headers[path] = r.headers();
  }
  const page = await ctx.newPage();
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  const cases = JSON.parse(CASES_JSON).map(([k, code]) => [k, code.replace('BASE', JSON.stringify(BASE))]);
  out.runs = await page.evaluate(async (cases) => {
    const m = await import('/static/js/codeRunner.js');
    const res = {};
    for (const [k, code] of cases) {
      const panel = document.createElement('div');
      document.body.appendChild(panel);
      const t0 = Date.now();
      await m.runPython(code, panel);
      res[k] = { text: panel.querySelector('pre') ? panel.querySelector('pre').textContent : panel.textContent,
                 ms: Date.now() - t0 };
    }
    return res;
  }, cases);
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):
    script = tmp_path_factory.mktemp("pyrun-js") / "run.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, USER, PASSWORD, json.dumps(CASES)],
                          capture_output=True, text=True, timeout=400, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_block_runs_and_says_what_it_printed(measured):
    assert measured["runs"]["hello"]["text"].strip() == "45"
    err = measured["runs"]["error"]["text"]
    assert "ValueError: boom" in err and "Traceback" in err


def test_the_block_cannot_reach_the_person_or_this_app(measured):
    runs = measured["runs"]
    assert "AttributeError" in runs["cookie"]["text"], "a worker has no document, so no cookie"
    assert runs["storage"]["text"].strip() == "no storage"
    assert runs["api"]["text"].strip() == "refused", "an opaque origin cannot read this app's API"


def test_a_block_that_never_ends_is_stopped_and_the_next_one_runs(measured):
    loop = measured["runs"]["loop"]
    assert "timed out" in loop["text"] and loop["ms"] < 20000, loop
    assert measured["runs"]["after"]["text"].strip() == "again 42"


def test_the_frame_is_an_opaque_origin_and_only_the_runtime_is_shared(measured):
    h = measured["headers"]
    csp = h["/python-sandbox"]["content-security-policy"]
    for part in ("sandbox allow-scripts", "worker-src blob:", "default-src 'none'", "frame-ancestors 'self'"):
        assert part in csp, csp
    assert h["/static/lib/pyodide/pyodide.js"].get("access-control-allow-origin") == "*"
    assert "access-control-allow-origin" not in h["/static/js/codeRunner.js"], \
        "only the vendored runtime is readable from the sandbox"


def test_an_admin_runs_on_the_server_and_everyone_else_in_the_browser():
    src = (ROOT / "static" / "js" / "codeRunner.js").read_text(encoding="utf-8")
    block = src[src.index("export function runPythonBlock"):]
    block = block[:block.index("\n}\n")]
    assert "window._isAdmin === true" in block and "runServer(code, panel, 'python')" in block
    assert "return runPython(code, panel)" in block
    run = src[src.index("export function run(btn)"):]
    assert "runPythonBlock(code, panel)" in run[:run.index("\n}\n")]
    doc = (ROOT / "static" / "js" / "document.js").read_text(encoding="utf-8")
    assert "codeRunnerModule.runPythonBlock(code, outputPanel)" in doc
