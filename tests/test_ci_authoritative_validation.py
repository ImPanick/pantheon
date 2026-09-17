# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression coverage for authoritative Python CI validation."""

import re
from pathlib import Path


_WORKFLOW = (
    Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
)


def _indented_block(text: str, heading: str, indent: int) -> str:
    pattern = re.compile(
        rf"(?ms)^{' ' * indent}{re.escape(heading)}:\n"
        rf"(?P<body>(?:(?:{' ' * (indent + 2)}.*|\s*)\n)*)"
    )
    match = pattern.search(text)
    assert match is not None, f"missing {heading!r} block"
    return match.group(0)


def test_ci_runs_on_every_push_to_the_only_branch_this_repo_has():
    """`B433`. This asserted `[main, dev]` and there has never been a `dev`
    branch — the assertion pinned the defect, so the trigger could not be
    corrected without a test going red, which is how it survived `B352`'s
    sweep over the PR and issue templates that named the same branch.

    What is worth holding is the two properties either side of it: CI runs on
    the default branch, and it runs on **every** push to it. `paths-ignore`
    staying out is the real content — a required check that does not fire on a
    docs commit is a required check that hangs a pull request forever.
    """
    workflow = _WORKFLOW.read_text()
    push = _indented_block(workflow, "push", 2)

    assert re.search(r"(?m)^    branches:\s*\[main\]\s*$", push)
    assert not re.search(r"(?m)^    branches:.*\bdev\b", push)
    assert "paths-ignore:" not in push


def test_python_tests_are_authoritative():
    workflow = _WORKFLOW.read_text()
    python_tests = _indented_block(workflow, "python-tests", 2)

    assert "python -m pytest -q" in python_tests
    assert "continue-on-error:" not in python_tests


def test_the_docs_only_shortcut_cannot_report_a_pass_on_no_tests():
    """`B434`. The job skips pytest when every changed file is documentation,
    and the shell that decided it answered *yes* to an empty change set — so a
    push whose `before` is the zero sha, or any `git diff` that failed, made
    `Python tests (pytest)` report success having run nothing. Authoritative
    means the green tick is about a run that happened."""
    workflow = _WORKFLOW.read_text()
    python_tests = _indented_block(workflow, "python-tests", 2)
    code = "\n".join(line for line in python_tests.splitlines()
                     if not line.lstrip().startswith("#"))

    assert "docs_only.py" in code
    assert "non_docs" not in code
