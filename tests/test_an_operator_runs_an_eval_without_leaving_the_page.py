# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B490` — the eval harness has a door.

`P14-03` built `src/evals.py` and `routes/diagnostics_routes.py` served
`GET /api/diagnostics/evals` and `POST /api/diagnostics/evals/{name}/run`, and
nothing under `static/` called either; suites lived in the `eval_suites`
setting with no editor, and the run ids a case is made of were shown on no
page. The row's `Verify:` — *an operator saves a set of cases and runs them
without leaving the UI, and the result shows the pass rate, the skipped count
and `grading`* — is driven twice:

  * the real app (`tests/helpers/gated_app.py`): two recorded runs appear in
    `GET /api/diagnostics/runs`, a suite saved through `POST /api/auth/settings`
    is listed and run, and the answer carries `pass_rate`, `skipped`, `grading`
    (the replay itself is the seam: no model is called);
  * the panel (`static/js/evalsPanel.js`) under node: it lists the runs, saves a
    case into a suite through the settings door (keeping the suites already
    there), and draws a run's pass rate, skipped count and grading.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.gated_app import gated_app_probe

ROOT = Path(__file__).resolve().parent.parent

_PROBE = r'''
from src import events as ev
import src.replay as rp

admin, member = client(ADMIN), client(MEMBER)
ids = []
for _ in range(2):
    ev._turn_started.set(None)        # a new turn, as a new request would be
    ev.mark_turn_start()
    ev.record_run_config(sampling={"temperature": 0.2}, owner=ADMIN)
    ids.append(ev.current_run_id())
good, gone = ids

runs = admin.get("/api/diagnostics/runs").json()
RESULT["runs"] = [r["run_id"] for r in runs["runs"]]
RESULT["member_runs"] = member.get("/api/diagnostics/runs").status_code

bad = [admin.post("/api/auth/settings", json={"eval_suites": v}).status_code
       for v in ({"name": "x"}, [{"cases": []}], [{"name": "a"}, {"name": "a"}])]
RESULT["bad"] = bad

suite = {"name": "smoke", "cases": [
    {"run_id": good, "label": "harbour", "expect": {"contains": ["tide"]}},
    {"run_id": gone, "label": "gone", "expect": {"contains": ["x"]}}]}
RESULT["saved"] = admin.post("/api/auth/settings", json={"eval_suites": [suite]}).status_code
RESULT["listed"] = admin.get("/api/diagnostics/evals").json()

def plan(run_id):
    if run_id == gone:
        return {"run_id": run_id, "runnable": False, "drift": ["the chat was deleted"]}
    return {"run_id": run_id, "runnable": True, "drift": []}

async def replay(run_id, model=None):
    return {"run_id": None, "output": "the harbour master logs every tide", "error": None}

rp.rerun_plan, rp.replay = plan, replay
r = admin.post("/api/diagnostics/evals/smoke/run")
RESULT["run"] = [r.status_code, r.json()]
RESULT["member_run"] = member.post("/api/diagnostics/evals/smoke/run").status_code
'''


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("b490"), _PROBE)


def test_recent_runs_are_listed_for_an_admin(probe):
    assert len(probe["runs"]) == 2
    assert probe["member_runs"] == 403


def test_a_malformed_save_is_refused_rather_than_shown_as_nothing(probe):
    assert probe["bad"] == [400, 400, 400]


def test_a_saved_suite_is_listed_and_runs_with_its_numbers(probe):
    assert probe["saved"] == 200
    (listed,) = probe["listed"]["suites"]
    assert listed == {"name": "smoke", "cases": 2, "problems": []}
    status, result = probe["run"]
    assert status == 200
    assert result["pass_rate"] == 1.0 and result["passed"] == 1
    assert result["skipped"] == 1
    assert result["grading"] == "deterministic"
    assert result["headline"].startswith("smoke: 1/1 passed · 1 skipped (could not be reproduced)")
    assert probe["member_run"] == 403


# ── the panel ───────────────────────────────────────────────────────────────

_CASE = """
import { installDom } from './dom.js';
const document = installDom();
const posted = [];
let stored = %(stored)s;
const RUNS = { runs: [
  { run_id: 'r-new', ts: '2026-10-26T20:00:00Z', chat: 'Harbour notes', model: 'qwen3', owner: 'ada' },
  { run_id: 'r-old', ts: '2026-10-25T09:00:00Z', chat: '', model: '', owner: 'ada' } ] };
const RUN = { suite: 'smoke', model: null, passed: 3, failed: 1, skipped: 2, total: 6,
  pass_rate: 0.75, grading: 'deterministic', problems: [],
  headline: 'smoke: 3/4 passed · 2 skipped (could not be reproduced)',
  cases: [{ run_id: 'r-new', label: 'harbour', status: 'failed',
            checks: [{ check: 'contains', passed: false, detail: 'tide' }], why: 'the tool schema changed' },
          { run_id: 'r-old', label: 'old', status: 'skipped', reason: 'the chat was deleted' }] };
globalThis.fetch = async (url, init = {}) => {
  const ok = (body) => ({ ok: true, status: 200, json: async () => body });
  if (url === '/api/diagnostics/runs?limit=30') return ok(RUNS);
  if (url === '/api/diagnostics/evals') return ok({ suites: stored.map((s) => ({ name: s.name, cases: s.cases.length, problems: [] })) });
  if (url === '/api/auth/settings' && (init.method || 'GET') === 'GET') return ok({ eval_suites: stored });
  if (url === '/api/auth/settings') { const b = JSON.parse(init.body); posted.push(b); stored = b.eval_suites; return ok({}); }
  if (url.startsWith('/api/diagnostics/evals/')) { posted.push({ run: url, method: init.method }); return ok(RUN); }
  throw new Error('unexpected ' + url);
};
const mk = (tag, id) => { const n = document.body.appendChild(document.createElement(tag)); n.setAttribute('id', id); return n; };
for (const id of ['evals-list', 'evals-result', 'evals-build-msg']) mk('div', id);
for (const id of ['evals-model', 'evals-suite-name', 'evals-contains', 'evals-not-contains', 'evals-max-failures']) mk('input', id);
const sel = mk('select', 'evals-run');
mk('button', 'evals-add-case');
// The shim's select keeps a value; a picked option's label is read from it.
Object.defineProperty(sel, 'selectedOptions', { get() { return sel.childNodes.filter((o) => o.value === sel.value); } });
const panel = await import('./evalsPanel.js');
await panel.open();
const out = { options: sel.childNodes.map((o) => [o.value, o.textContent]) };
%(then)s
out.posted = posted;
out.list = document.getElementById('evals-list').textContent;
out.result = document.getElementById('evals-result').textContent;
out.msg = document.getElementById('evals-build-msg').textContent;
out.facts = document.getElementById('evals-result').querySelectorAll('dd').map((d) => [d.className, d.textContent]);
console.log(JSON.stringify(out));
"""


def _drive(tmp_path, stored, then=""):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    from test_tool_effect_surfaces_js import _DOM

    (tmp_path / "dom.js").write_text(_DOM)
    for name in ("evalsPanel.js", "appConfig.js"):
        shutil.copy(ROOT / "static" / "js" / name, tmp_path / name)
    (tmp_path / "case.mjs").write_text(_CASE % {"stored": json.dumps(stored), "then": then})
    out = subprocess.run(["node", str(tmp_path / "case.mjs")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_panel_offers_the_recent_runs_by_what_a_person_recognises(tmp_path):
    out = _drive(tmp_path, [])
    assert out["options"] == [["r-new", "2026-10-26 20:00 · Harbour notes · qwen3"],
                              ["r-old", "2026-10-25 09:00 · a chat"]]
    assert "No suites yet" in out["list"]


def test_a_case_is_saved_into_its_suite_through_the_settings_door(tmp_path):
    keep = [{"name": "other", "cases": [{"run_id": "r-x", "expect": {"no_error": True}}]}]
    out = _drive(tmp_path, keep, then="""
document.getElementById('evals-suite-name').value = 'smoke';
sel.value = 'r-new';
document.getElementById('evals-contains').value = 'tide, harbour';
document.getElementById('evals-max-failures').value = '0';
await panel.addCase();
""")
    (saved,) = out["posted"]
    assert saved["eval_suites"][0] == keep[0]          # the suite already there survives
    smoke = saved["eval_suites"][1]
    assert smoke == {"name": "smoke", "cases": [{
        "run_id": "r-new", "label": "2026-10-26 20:00 · Harbour notes · qwen3",
        "expect": {"contains": ["tide", "harbour"], "max_tool_failures": 0}}]}
    assert out["msg"] == "Saved — smoke has 1 case."
    assert "smoke" in out["list"] and "1 case" in out["list"]


def test_a_run_shows_the_pass_rate_the_skipped_count_and_how_it_was_graded(tmp_path):
    out = _drive(tmp_path, [{"name": "smoke", "cases": [{"run_id": "r-new"}]}], then="""
document.getElementById('evals-model').value = 'llama3';
await panel.runSuite('smoke');
""")
    assert out["posted"] == [{"run": "/api/diagnostics/evals/smoke/run?model=llama3", "method": "POST"}]
    facts = dict(out["facts"])
    assert facts["evals-pass-rate"] == "75% (3/4)"
    assert facts["evals-skipped"] == "2"
    assert facts["evals-graded"] == "deterministic"
    assert "failed — harbour: contains tide (the tool schema changed)" in out["result"]
    assert "skipped — old: the chat was deleted" in out["result"]
