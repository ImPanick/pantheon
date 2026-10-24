# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-16` / `P24-17` / `P24-18` — an agent's evaluation set runs in a world
of its own, and the hall's fit badge reads what was measured.

The real harness (`src.agents.evals`): the real scheduler from
`_execute_task`, the hire's run plan, the real agent loop, the real effects
gate (with `D-2026-10-24-01`/`-02` in it), parking and its answer route, the
contract check and the report — inside an isolated SQLite file and data folder.
Only the model is the case's own script, and only what would reach outside
(mail, the web, a shell elsewhere) is answered by the case's world.

**Measured before this file, on `75d11b2`:** there was no harness; and the
first cases it ran found three defects, each closed beside it — a hire's draft
limit counted none of the loop's own spelling of a draft (`B1433`), a hire's
project was never used (`B1434`), and a notes or tasks listing was written into
every model's answer (`B1435`) — and the two rulings an unattended agent needed
to run at all (`D-2026-10-24-01`, `-02`).
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from src.agents import evals as E
from src.agents import fit as F
from src.agents.catalogue import catalogue, get_agent

STARRED = ("inbox-triage", "morning-brief", "topic-watcher", "site-builder", "server-health")


# ── the file ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("agent", STARRED)
def test_each_starred_agent_ships_a_set_its_lint_accepts_and_a_sample(agent):
    m = get_agent(None, agent)
    cases = E.load_evals(m)
    assert 4 <= len(cases) <= E.MAX_CASES
    import os
    sample = json.load(open(os.path.join(E.agent_dir(m), "sample.json"), encoding="utf-8"))
    assert sample["from"] == "its evaluation, with a scripted model" and sample["answer"]


@pytest.mark.parametrize("change,words", [
    (lambda c: c.update(checks=[{"vibes": 1}]), "a check Pantheon cannot run"),
    (lambda c: c.update(inputs={"nope": 1}), "inputs the agent does not ask for"),
    (lambda c: c.update(world={"internet": True}), "world has keys nothing reads"),
    (lambda c: c.update(answers=["approve"]), "an answer is approve_task or deny"),
    (lambda c: c.update(script=[{"call": ["web_search"]}]), "not \\[tool, \\{args\\}\\]"),
    (lambda c: c.update(id="Bad Id"), "lower-case words"),
])
def test_a_set_that_does_not_read_says_why(change, words):
    m = get_agent(None, "topic-watcher")
    case = json.loads(json.dumps(E.load_evals(m)[0]))
    change(case)
    with pytest.raises(E.EvalRefused, match=words):
        E.lint_evals({"cases": [case]}, m)
    with pytest.raises(E.EvalRefused, match="1 to 10 cases"):
        E.lint_evals({"cases": [E.load_evals(m)[0]] * 11}, m)


# ── the runs ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("agent", STARRED)
def test_every_case_passes_against_its_script(agent):
    """CI's half of § 8: the plumbing — compile, gate, effects, parking,
    contract, report — on every commit, with no model at all."""
    m = get_agent(None, agent)
    results = asyncio.run(E.run_agent(m))
    failed = {r.case: [c for c in r.checks if not c["ok"]] for r in results if not r.passed}
    assert not failed, failed


def test_a_model_that_says_done_and_did_nothing_fails():
    m = get_agent(None, "inbox-triage")
    case = dict(E.load_evals(m)[0], script=[{"say": "Done, all sorted."}, {"say": "Done."}])
    (r,) = asyncio.run(E.run_agent(m, cases=[case]))
    assert r.passed is False and r.status == "error"
    assert any(c["check"].startswith("a document titled") and not c["ok"] for c in r.checks)
    only_own = dict(case, checks=[{"not_called": "send_email"}])
    (r,) = asyncio.run(E.run_agent(m, cases=[only_own]))
    assert r.passed is False, "its own checks held, and the file's contract did not: it did not deliver"


def test_the_world_answers_nothing_it_does_not_hold():
    w = E.World({"shell": [{"match": "uptime", "output": "up 3 days"}]})
    assert json.loads(w.answer("bash", '{"command": "uptime"}')[1]["output"])["output"] == "up 3 days"
    out = json.loads(w.answer("bash", '{"command": "curl https://evil.example"}')[1]["output"])
    assert out["exit_code"] == 127 and "no machine" in out["error"]
    assert "404 in this world" in w.answer("web_fetch", '{"url": "https://x.example"}')[1]["output"]
    w.answer("send_email", '{"to": "a@b.c"}')
    assert w.sent == [{"tool": "send_email", "to": "a@b.c"}]
    assert w.answer("create_document", "x") is None, "Pantheon's own stores are the real ones"


def test_the_world_leaves_the_install_as_it_found_it(tmp_path):
    import core.database as cdb
    import src.constants as constants
    import os
    before = (cdb.SessionLocal, constants.DATA_DIR)
    gate = os.environ.get("BACKGROUND_TASK_FOREGROUND_GATE")
    with E.isolated() as (factory, data):
        assert cdb.SessionLocal is factory and constants.DATA_DIR == data
        import types
        late = types.ModuleType("src._late_in_world")
        late.SessionLocal, late.DATA_DIR = cdb.SessionLocal, constants.DATA_DIR
        sys.modules[late.__name__] = late
    try:
        assert (cdb.SessionLocal, constants.DATA_DIR) == before
        assert os.environ.get("BACKGROUND_TASK_FOREGROUND_GATE") == gate, "the world's gate setting outlived it"
        assert (late.SessionLocal, late.DATA_DIR) == before, "a module first imported in the world got the world's names"
    finally:
        sys.modules.pop("src._late_in_world", None)


# ── proof rows and the badge ────────────────────────────────────────────────

def _row(**kw):
    m = get_agent(None, "topic-watcher")
    row = {"agent": m.id, "version": m.version, "model": "openai/gpt-oss-20b@q4_k_m", "runs": 10,
           "cases": {"a": {"passed": 5, "of": 5}, "b": {"passed": 4, "of": 5}},
           "pass_rate": 0.9, "median_minutes": 2.0, "at": "2026-10-24T00:00:00Z", "failures": {}}
    row.update(kw)
    return m, row


@pytest.mark.parametrize("a,b", [("openai/gpt-oss-20b", "gpt-oss-20b:latest"), ("qwen3-coder@q4_k_m", "Qwen3-Coder"),
                                 ("Llama-3.1-8B-Instruct-Q4_K_M", "llama-3.1-8b-instruct")])
def test_a_model_family_ignores_where_it_is_served_and_its_quantisation(a, b):
    assert F.family(a) == F.family(b)


def test_the_badge_is_what_was_measured():
    m, row = _row()
    assert F.fit(m, "gpt-oss-20b", rows=[row])["words"] == "Runs well"
    assert F.fit(m, "gpt-oss-20b", rows=[dict(row, median_minutes=99)])["words"] == "Runs, slowly"
    assert F.fit(m, "gpt-oss-20b", rows=[dict(row, cases={"a": {"passed": 3, "of": 5}})])["words"] == \
        "Needs a bigger model"
    assert F.fit(m, "qwen3-coder", rows=[row])["badge"] == "not-measured", "another family is not measured"
    assert F.fit(m, "gpt-oss-20b", rows=[dict(row, version="0.9.0")])["badge"] == "not-measured", \
        "a row for another version of the file measures that file"
    newer = dict(row, cases={"a": {"passed": 1, "of": 5}}, at="2026-10-25T00:00:00Z")
    assert F.fit(m, "gpt-oss-20b", rows=[row, newer])["badge"] == "needs-bigger", "the newest row decides"


def test_a_proof_row_counts_each_case():
    m = get_agent(None, "topic-watcher")
    ok = E.CaseResult(m.id, "a", True, "success", [{"check": "x", "ok": True, "detail": ""}], 1.0, [])
    bad = E.CaseResult(m.id, "a", False, "error", [{"check": "x", "ok": False, "detail": ""}], 3.0, [])
    row = E.proof_row(m, "gpt-oss-20b", [ok, ok, bad])
    assert row["cases"] == {"a": {"passed": 2, "of": 3}} and row["failures"] == {"x": 1}
    assert row["pass_rate"] == round(2 / 3, 3) and row["median_minutes"] == 1.0


def test_the_install_rows_are_read_from_its_own_file(tmp_path):
    m, row = _row()
    (tmp_path / F.PROOFS_FILE).write_text(json.dumps(row) + "\nnot json\n")
    assert F._install_rows(str(tmp_path)) == [row]


def test_a_proof_run_names_both_endpoint_and_model(capsys):
    assert E.main(["topic-watcher", "--endpoint", "http://x/v1"]) == 2
    assert "names both" in capsys.readouterr().out


# ── the hall ────────────────────────────────────────────────────────────────

from tests.test_a_team_is_hired_in_one_go import client  # noqa: E402,F401
from tests.test_a_workflow_is_kept_as_one_document import admins, sched, wf_db  # noqa: E402,F401
from tests.test_a_hire_compiles_to_tasks import call  # noqa: E402


def test_the_hall_carries_each_agents_fit_and_its_page_the_sample(client, monkeypatch, tmp_path):
    import src.agents.fit as fit_mod
    m, row = _row()
    monkeypatch.setattr(fit_mod, "model_for", lambda owner: "gpt-oss-20b")
    monkeypatch.setattr(fit_mod, "_install_rows", lambda data_dir=None: [row])
    data = call(client, "GET", "/api/agents").json()
    fits = {a["id"]: a["fit"] for a in data["agents"]}
    assert data["fit_model"] == "gpt-oss-20b"
    assert fits["topic-watcher"]["words"] == "Runs well" and fits["morning-brief"]["words"] == "Not measured"
    page = call(client, "GET", "/api/agents/morning-brief").json()
    assert page["eval_cases"] == 4 and page["sample"]["case"] == "an-ordinary-day"
    assert page["fit"]["badge"] == "not-measured"
