# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2212` — the branch-protection steps say what the owner chose.

The owner, 2026-11-24 (`D-2026-11-24-04`): *"Branch protection. only on
main."* `docs/security-ci.md` §1 is the page the operator follows, and on that
day it said to add the rule a second time for `dev`, listed nine checks of the
twelve the owner wants required, called `Python tests (pytest)` advisory, and
told the operator to require Code Owners' review — a rule nobody can meet when
every pull request comes from the owner's own account, because GitHub does not
let an author approve their own pull request.

`.pantheon/check-ci-contract.py` rule 1 already holds each listed name to a real
job; this holds the list, the branch and the review settings to the ruling.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "security-ci.md"

OWNER_CHOSE = [
    "Python syntax (compileall)",
    "Python lint (ruff, names that crash)",
    "JS syntax (node --check)",
    "Python tests (pytest)",
    "Wiring ratchet (check-wiring.py --max 0)",
    "Law 16 — no egress on a fresh install",
    "gitleaks",
    "actionlint",
    "zizmor (Actions SAST)",
    "hadolint (Dockerfile lint)",
    "dependency-review (PR gate)",
    "pip-audit (blocking)",
]


def _contract():
    spec = importlib.util.spec_from_file_location(
        "_contract_b2212", ROOT / ".pantheon" / "check-ci-contract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _section() -> str:
    text = DOC.read_text(encoding="utf-8")
    body = text.split("### 1. Require the blocking checks before merging", 1)[1]
    return body.split("\n### 2.", 1)[0]


def test_the_required_checks_are_the_twelve_the_owner_chose():
    assert _contract().required_checks() == OWNER_CHOSE


def test_every_required_check_names_a_job_that_reports():
    problems, _owners = _contract().rule_required_checks_exist()
    assert not problems, problems


def test_main_is_the_only_branch_protected():
    contract = _contract()
    assert contract.documented_protected_branch() == "main"
    section = _section()
    assert "second time for\n   `dev`" not in section and "same rule\n   a second time" not in section
    assert "Add no rule for `dev`" in section, section[:1200]


def test_a_pull_request_with_no_required_approval_and_no_code_owners():
    section = " ".join(_section().split())
    assert "**Require a pull request before merging**" in section
    assert "**Required approvals** set to **0**" in section
    assert "Leave **Require review from Code Owners** off" in section
    assert "Also enable **Require a pull request before merging** and **Require review from Code Owners**" not in section


def test_admins_not_enforced_and_no_force_push_or_deletion():
    section = " ".join(_section().split())
    assert "admins are not enforced" in section
    assert "**Allow force pushes** and **Allow deletions** **off**" in section


def test_pytest_is_no_longer_called_advisory():
    section = _section()
    assert "Leave pytest" not in section
