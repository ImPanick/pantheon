# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B585` — every number a document quotes for a ratchet is the one `ci.yml` holds.

`Law 13` in `.pantheon/AGENTS.md` — inside the law against carrying numbers —
said *"The number is **124** unresolved element-id targets"* while the checker
printed 40, and then said **40** while `ci.yml` pinned `--max 0`. The checker was
right each time and the governing document was the copy that went stale, which
is `Law 6`'s own exhibit appearing in `Law 13`'s text.

Rule nine of `.pantheon/check-ci-contract.py` recomputes the copies the way
`check-tracker.py` recomputes the status table. This file drives it: over the
real tree, and over a scratch repository whose documents disagree with its CI.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / ".pantheon" / "check-ci-contract.py"


def _load():
    spec = importlib.util.spec_from_file_location("_pantheon_ci_contract_b585", CHECKER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def contract():
    return _load()


CI_YML = """\
jobs:
  wiring-ratchet:
    name: Wiring ratchet (check-wiring.py --max 3)
    steps:
      - name: check-wiring
        run: python3 .pantheon/check-wiring.py --max 3
      - name: check-outbound
        run: python3 .pantheon/check-outbound.py --max 109 --max-env 51
"""


def _repo(tmp_path: Path, files: dict) -> Path:
    for rel, text in {".github/workflows/ci.yml": CI_YML, **files}.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _point_at(contract, monkeypatch, root: Path):
    monkeypatch.setattr(contract, "ROOT", root)
    monkeypatch.setattr(contract, "CI", root / ".github" / "workflows" / "ci.yml")


def test_the_tree_holds_no_stale_copy(contract):
    assert contract.rule_ratchet_values_live_in_ci() == []


def test_the_rule_is_in_the_list_main_runs():
    """Driven through the CLI: a rule `main()` never calls is the shape every
    rule here exists to catch."""
    proc = subprocess.run([sys.executable, str(CHECKER)], cwd=ROOT,
                          capture_output=True, text=True, timeout=300)
    # `B438` added rule 10 (the suite's interpreter), so the count is 10 —
    # and this rule's own title is in the list either way.
    assert "10 rules" in proc.stdout, proc.stdout


def test_the_law_13_sentence_as_it_stood_fails(contract, monkeypatch, tmp_path):
    """The row's own state: the governing document quotes a count CI does not
    hold. The fault names the file, the line, both numbers and the row."""
    root = _repo(tmp_path, {
        ".pantheon/AGENTS.md":
            "intro\n`python3 .pantheon/check-wiring.py` counts it. The number is **40** "
            "unresolved element-id\n",
    })
    _point_at(contract, monkeypatch, root)
    problems = contract.rule_ratchet_values_live_in_ci()
    assert problems == [
        ".pantheon/AGENTS.md:2 quotes check-wiring.py --max as 40; ci.yml holds 3. "
        "Write it without the number and point at ci.yml, which is where CI reads "
        "it (`B585`)"], problems


def test_an_invocation_copy_must_carry_cis_number(contract, monkeypatch, tmp_path):
    """A docstring's usage line is a copy too: `--max-routes 37` beside a CI
    that holds 29 was in two route modules. The matching value and the
    number-free spelling are both fine."""
    root = _repo(tmp_path, {
        "routes/a.py": '"""ceiling (`check-outbound.py --max 96`)"""\n',
        "routes/b.py": '"""ceiling (`check-outbound.py --max 109 --max-env 50`)"""\n',
        "routes/c.py": '"""ceiling (`check-outbound.py --max N`, in ci.yml)"""\n',
        "routes/d.py": '"""ceiling (`check-outbound.py --max 109 --max-env 51`)"""\n',
    })
    _point_at(contract, monkeypatch, root)
    problems = contract.rule_ratchet_values_live_in_ci()
    assert [p.split(" quotes ")[0] for p in problems] == ["routes/a.py:1", "routes/b.py:1"], problems
    assert "check-outbound.py --max as 96; ci.yml holds 109" in problems[0]
    assert "check-outbound.py --max-env as 50; ci.yml holds 51" in problems[1]


def test_a_record_of_what_was_true_then_is_not_a_copy(contract, monkeypatch, tmp_path):
    """The tracker, the changelog, a dated run record and a test's fixture all
    quote old ceilings on purpose; the rule is about claims of what is true
    now."""
    root = _repo(tmp_path, {
        ".pantheon/ROADMAP.md": "it was `check-wiring.py --max 124`\n",
        "CHANGELOG.md": "The number is **78** unresolved.\n",
        ".pantheon/runs/wiring-run-01.md": "python3 .pantheon/check-wiring.py --max 2\n",
        "tests/test_x.py": 'REPRO = "check-wiring.py --max 124"\n',
    })
    _point_at(contract, monkeypatch, root)
    assert contract.rule_ratchet_values_live_in_ci() == []


def test_a_job_name_and_its_step_are_one_ceiling(contract, monkeypatch, tmp_path):
    """`B585` found `--max 40` in both the job name and the step. Two copies
    inside ci.yml are the same defect one file over."""
    root = _repo(tmp_path, {})
    ci = root / ".github" / "workflows" / "ci.yml"
    ci.write_text(CI_YML.replace("(check-wiring.py --max 3)", "(check-wiring.py --max 40)"),
                  encoding="utf-8")
    _point_at(contract, monkeypatch, root)
    problems = contract.rule_ratchet_values_live_in_ci()
    assert any("ci.yml states 2 values for check-wiring.py --max (3, 40)" in p
               for p in problems), problems
