# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B438` — the suite runs on the interpreter the image ships, or the CI
contract says why it does not.

`ci.yml` ran the whole suite on 3.11; the image is `python:3.14-slim`; and
`dependency-review.yml` already argued, in a comment, that the interpreter is
not cosmetic here — `requirements-optional.txt` gates packages on
`python_version`, so the installed set depends on it. A green suite was
evidence about a dependency set the product does not install, and nothing
said so.

Moving the suite is not a one-line bump (every `python-version` in `ci.yml` is
one value the release gate mirrors, rule 5) and has not been measured: no run
of the suite on 3.14 exists. So `check-ci-contract.py` rule 10 holds the
answer instead — each job that runs pytest pins the image's Python or carries
a reason in `SUITE_ON_ANOTHER_PYTHON`, keyed by both versions so a bump on
either side turns the reason stale. Driven through the checker's own function.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / ".pantheon" / "check-ci-contract.py"


@pytest.fixture
def contract():
    spec = importlib.util.spec_from_file_location("_pantheon_ci_contract_b438", CHECKER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_tree_holds(contract):
    assert contract.image_python() == "3.14"
    assert set(contract.suite_jobs()) == {"ci.yml:python-tests", "ci.yml:law16-egress"}
    assert contract.rule_suite_runs_where_the_image_runs() == []


def test_a_suite_on_another_python_with_no_reason_fails(contract, monkeypatch):
    """The tree before `B438`: 3.11 against 3.14, and nothing said why."""
    monkeypatch.setattr(contract, "SUITE_ON_ANOTHER_PYTHON", {})
    problems = contract.rule_suite_runs_where_the_image_runs()
    assert len(problems) == 2
    assert all("image ships 3.14" in p and "B438" in p for p in problems)


def test_bumping_the_image_makes_the_reason_stale(contract, monkeypatch):
    monkeypatch.setattr(contract, "image_python", lambda: "3.15")
    problems = contract.rule_suite_runs_where_the_image_runs()
    assert problems and all("re-measure" in p for p in problems)


def test_a_suite_that_moved_takes_its_excuse_with_it(contract, monkeypatch):
    monkeypatch.setattr(contract, "suite_jobs",
                        lambda: {"ci.yml:python-tests": "3.14", "ci.yml:law16-egress": "3.14"})
    problems = contract.rule_suite_runs_where_the_image_runs()
    assert len(problems) == 2 and all("remove the entry" in p for p in problems)


def test_the_rule_runs_in_main(contract, monkeypatch, capsys):
    monkeypatch.setattr(contract, "rule_suite_runs_where_the_image_runs", lambda: ["planted"])
    monkeypatch.setattr(sys, "argv", ["check-ci-contract.py"])
    assert contract.main() == 1
    assert "planted" in capsys.readouterr().out
