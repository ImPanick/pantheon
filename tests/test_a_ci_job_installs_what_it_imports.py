# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B855` — twenty-two checkers that had never run.

`ci.yml`'s `wiring-ratchet` job runs twenty-five steps and installed nothing.
Three of those steps hand a script to Python that imports this product on
purpose — `check-tool-surface.py` does `import src.agent_tools` inside `main()`
because a register you read with a regex is a register you are guessing about
(`Law 20`) — and that import reaches `httpx` four modules down. So the job died
at step three with `ModuleNotFoundError`, and the twenty-two steps after it
never ran. Not once, in the life of the repository.

Nothing could see it. Every one of those checkers passes on a developer's
machine and in `release-gate.py`, where the dependencies exist; the gate's own
footer has been saying for weeks that a local run is not evidence about CI's
environment. It took the first CI run that ever completed to show the X, and
the job's name — `Wiring ratchet (check-wiring.py --max 25)` — names the one
checker that was never the problem.

Rule eight of `check-ci-contract.py` is the general form: a job whose steps run
a script that imports this product must install this product's dependencies.
This file drives that rule, including against a workflow that breaks it.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / ".pantheon" / "check-ci-contract.py"


def _load():
    spec = importlib.util.spec_from_file_location("_pantheon_ci_contract", CHECKER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def contract():
    return _load()


def test_the_tree_satisfies_the_rule(contract):
    assert contract.rule_job_installs_what_it_imports() == []


def test_the_rule_is_in_the_list_main_runs(contract):
    """A rule nobody calls is the shape it exists to catch."""
    source = CHECKER.read_text(encoding="utf-8")
    body = source[source.index("rules = ["):source.index("problems = [(title")]
    assert "rule_job_installs_what_it_imports()" in body


def test_it_sees_an_import_made_inside_a_function(contract):
    """`check-tool-surface.py`'s is inside `main()`, and it still runs."""
    assert contract._imports_first_party(
        ROOT / ".pantheon" / "check-tool-surface.py") == ["src"]


def test_a_stdlib_only_checker_is_not_flagged(contract):
    assert contract._imports_first_party(ROOT / ".pantheon" / "check-wiring.py") == []


def test_grepping_a_file_is_not_running_it(contract):
    """`docker-publish.yml` reads `APP_VERSION` out of `src/constants.py`.

    A step that greps a file neither imports it nor needs its dependencies, and
    a rule that cannot tell the difference gets turned off.
    """
    grep = "v=$(grep -E '^APP_VERSION' src/constants.py | head -1)"
    assert contract._scripts_a_step_runs(grep) == []
    ran = "python3 .pantheon/check-tool-surface.py"
    assert ROOT / ".pantheon" / "check-tool-surface.py" in contract._scripts_a_step_runs(ran)


def test_it_finds_the_scripts_a_pytest_invocation_names(contract):
    text = "python3 -m pytest tests/test_no_egress_on_boot.py -q -p no:randomly"
    assert ROOT / "tests" / "test_no_egress_on_boot.py" in contract._scripts_a_step_runs(text)


def test_the_rule_fires_on_the_workflow_that_shipped(contract, monkeypatch, tmp_path):
    """The historical defect, rebuilt and measured — not remembered."""
    workflow = tmp_path / "broken.yml"
    workflow.write_text(
        "name: broken\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "jobs:\n"
        "  wiring-ratchet:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python3 .pantheon/check-tool-surface.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(contract, "workflow_files", lambda: [workflow])
    problems = contract.rule_job_installs_what_it_imports()
    assert len(problems) == 1
    assert "check-tool-surface.py" in problems[0]
    assert "pip install -r requirements.txt" in problems[0]


def test_the_install_clears_it(contract, monkeypatch, tmp_path):
    workflow = tmp_path / "fixed.yml"
    workflow.write_text(
        "name: fixed\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "jobs:\n"
        "  wiring-ratchet:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: pip install -r requirements.txt\n"
        "      - run: python3 .pantheon/check-tool-surface.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(contract, "workflow_files", lambda: [workflow])
    assert contract.rule_job_installs_what_it_imports() == []


def test_both_jobs_that_failed_now_install(contract):
    """Named, because these two are the ones that were red on 2026-09-19."""
    doc = contract.load_workflow(contract.CI)
    for key in ("wiring-ratchet", "law16-egress"):
        steps = contract.jobs(doc)[key]["steps"]
        runs = [str(s.get("run", "")) for s in steps if isinstance(s, dict)]
        assert any(contract.DEPENDENCY_INSTALL in r for r in runs), key
