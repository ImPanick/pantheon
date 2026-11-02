# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1742` — the job that runs `check-ledger.py` checks out the whole history.

`check-ledger.py` holds the ledger's passing count to being dated and pinned to
a commit (`B1405`), and asks git whether that commit exists. The job that runs
it checked out one commit, so the answer was *no* on every run from the day the
pin was written (2026-10-18) until this test: the step went red, and the
fourteen steps after it never ran in CI. A checker that is right locally and
wrong in CI for a reason that is neither the tree nor the checker is `B855`'s
shape again, and this pins the one line that decides it.
"""
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _jobs() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def _runs_check_ledger(job: dict) -> bool:
    return any("check-ledger.py" in str(step.get("run", ""))
               for step in job.get("steps", []))


def _checkout_steps(job: dict) -> list[dict]:
    return [step for step in job.get("steps", [])
            if str(step.get("uses", "")).startswith("actions/checkout@")]


def test_one_job_runs_the_ledger_checker():
    """The rule below is about that job; it has to exist to be held to it."""
    jobs = [name for name, job in _jobs().items() if _runs_check_ledger(job)]
    assert jobs, "no CI job runs .pantheon/check-ledger.py"


def test_the_job_that_checks_the_ledger_fetches_the_whole_history():
    """`git cat-file -e <pin>` can only say yes when the pin was fetched."""
    for name, job in _jobs().items():
        if not _runs_check_ledger(job):
            continue
        checkouts = _checkout_steps(job)
        assert checkouts, f"{name}: runs check-ledger.py with no checkout step"
        for step in checkouts:
            depth = (step.get("with") or {}).get("fetch-depth")
            assert depth == 0, (
                f"{name}: actions/checkout fetches depth {depth!r}; "
                "check-ledger.py asks git for the commit the passing count is "
                "pinned at, and a one-commit checkout never has it (`B1742`)")


def test_the_pinned_commit_is_in_this_clone_or_the_check_says_so():
    """What the step asks of CI, asked of this clone, so the rule is not only
    about a file: the pin resolves here, or the checker's own message names it.
    A shallow local clone is allowed to fail this half — CI is not."""
    import re
    import subprocess

    claims = (ROOT / ".pantheon" / "ledger" / "claims.py").read_text(encoding="utf-8")
    pin = re.search(r"when the suite was last run whole — \d{4}-\d\d-\d\d, at `([0-9a-f]{7,40})`", claims)
    assert pin, "the tests claim no longer pins the passing count to a commit"
    seen = subprocess.run(["git", "cat-file", "-e", pin.group(1) + "^{commit}"],
                          cwd=ROOT, capture_output=True, timeout=30)
    shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"],
                             cwd=ROOT, capture_output=True, text=True, timeout=30)
    if shallow.stdout.strip() == "true" and seen.returncode != 0:
        import pytest
        pytest.skip(f"shallow clone without {pin.group(1)}; CI fetches depth 0 (`B1742`)")
    assert seen.returncode == 0, f"{pin.group(1)} is pinned and not in this full clone"
