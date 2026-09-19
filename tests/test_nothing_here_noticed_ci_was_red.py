# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B430`–`B436` — the pipeline was red all day and the repository could not tell.

Measured 2026-09-17 against `ImPanick/pantheon`: across the last forty workflow
runs, **22 failed, 8 succeeded, 9 were skipped, 1 was cancelled**, and every one
of the eight successes is a Dependabot update run or a `Container scan (Trivy)`
job that skipped its work. No `CI`, `CodeQL`, `Secret scan`, `Workflow security`
or `Dependency review` run has ever succeeded. Every failing job reports an
empty `runner_name`, an empty `steps` array and a three-to-six second duration:
**they never got a runner.** That is a billing fact about a private repository
and no change to a workflow file makes a runner appear.

The half that is ours is the second one. Five waves shipped that day, each
reporting "gate green on 22 checkers", and every one of those was a local
`.pantheon/release-gate.py --fast` run. The pipeline was red for all five and
nothing here observed it — no test, no checker, no doc — in a repository whose
whole argument is that its claims are checkable.

These tests hold the apparatus that makes that impossible to repeat:

  `B430`  a stranger can see the answer: branch-pinned status badges for every
          merge-blocking workflow, and a required check name that matches a job
          that exists
  `B431`  the local gate reads its interpreter, node version and suite argv out
          of `ci.yml` instead of remembering them
  `B433`  no trigger names a branch this repository does not have
  `B434`  a skip that claims "this change is only documentation" can prove it
  `B435`  a job that reports success did its work
  `B436`  neither syntax job keeps a second list of which files are ours

Every rule is driven by calling `.pantheon/check-ci-contract.py` over a
synthetic tree built here, so what is tested is the rule and not a sentence in
a file (`Law 20`).
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / ".pantheon" / "check-ci-contract.py"
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def contract():
    """A fresh module per test — the rules read module-level paths, and a test
    that repointed them for the next one would be the order dependence the
    testing standard forbids."""
    return _load(CHECKER, "check_ci_contract")


@pytest.fixture()
def fake_repo(tmp_path, contract):
    """A minimal tree the rules can be pointed at: one workflow, one README,
    one security guide. Each test breaks exactly one thing in it."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (workflows / "ci.yml").write_text(
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "  pull_request:\n"
        "jobs:\n"
        "  syntax:\n"
        "    name: Python syntax (compileall)\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: py_compile\n"
        "        run: python3 -c \"import x\"\n",
        encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "git clone https://github.com/ImPanick/pantheon.git\n"
        '<img src="https://github.com/ImPanick/pantheon/actions/workflows/'
        'ci.yml/badge.svg?branch=main" alt="CI">\n',
        encoding="utf-8")
    (tmp_path / "docs" / "security-ci.md").write_text(
        "set the branch name pattern to `main`\n"
        "add these checks by name:\n"
        "   - `Python syntax (compileall)`\n",
        encoding="utf-8")
    contract.ROOT = tmp_path
    contract.WORKFLOWS = workflows
    contract.README = tmp_path / "README.md"
    contract.SECURITY_CI = tmp_path / "docs" / "security-ci.md"
    contract.CI = workflows / "ci.yml"
    return tmp_path


def _write(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


# ── the fixture itself is clean, or every negative below proves nothing ───────


def test_the_synthetic_repo_passes_the_rules_it_is_pointed_at(contract, fake_repo):
    problems, owners = contract.rule_required_checks_exist()
    assert problems == []
    assert contract.rule_badges(owners) == []
    assert contract.rule_trigger_branches() == []
    assert contract.rule_fail_open() == []


# ── `B430` — a stranger can see the answer ───────────────────────────────────


def test_a_required_check_that_names_no_job_is_caught(contract, fake_repo):
    """Branch protection is configured by typing check names into a box. A name
    that matches no job never reports, and GitHub's answer to a required check
    that never reports is a merge button that never unlocks. Renaming a job is
    a one-word diff and it breaks this in a place nobody looks."""
    _write(fake_repo / "docs" / "security-ci.md",
           "set the branch name pattern to `main`\n"
           "add these checks by name:\n"
           "   - `Python syntax (compileall)`\n"
           "   - `A job nobody wrote`\n")
    problems, _owners = contract.rule_required_checks_exist()
    assert any("A job nobody wrote" in p for p in problems), problems


def test_a_missing_badge_is_caught(contract, fake_repo):
    _write(fake_repo / "README.md",
           "git clone https://github.com/ImPanick/pantheon.git\n")
    _problems, owners = contract.rule_required_checks_exist()
    assert any("no status badge for ci.yml" in p
               for p in contract.rule_badges(owners))


def test_an_unpinned_badge_is_caught(contract, fake_repo):
    """The trap that makes a badge worse than nothing. `badge.svg` with no
    `?branch=` reports the newest run on ANY ref — and the eight successes
    measured on 2026-09-17 were all Dependabot branches, so an unpinned badge
    would have been painted green by exactly the runs that prove nothing."""
    _write(fake_repo / "README.md",
           "git clone https://github.com/ImPanick/pantheon.git\n"
           '<img src="https://github.com/ImPanick/pantheon/actions/workflows/'
           'ci.yml/badge.svg" alt="CI">\n')
    _problems, owners = contract.rule_required_checks_exist()
    assert any("no `?branch=`" in p for p in contract.rule_badges(owners))


def test_a_badge_pinned_to_a_branch_that_does_not_exist_is_caught(contract,
                                                                  fake_repo):
    _write(fake_repo / "README.md",
           "git clone https://github.com/ImPanick/pantheon.git\n"
           '<img src="https://github.com/ImPanick/pantheon/actions/workflows/'
           'ci.yml/badge.svg?branch=dev" alt="CI">\n')
    _problems, owners = contract.rule_required_checks_exist()
    assert any("not a branch this repository has" in p
               for p in contract.rule_badges(owners))


def test_a_badge_pointing_at_somebody_elses_repository_is_caught(contract,
                                                                 fake_repo):
    """A copied badge is the classic one: it renders, it is green, and it is
    about a different project."""
    _write(fake_repo / "README.md",
           "git clone https://github.com/ImPanick/pantheon.git\n"
           '<img src="https://github.com/someone/else/actions/workflows/'
           'ci.yml/badge.svg?branch=main" alt="CI">\n')
    _problems, owners = contract.rule_required_checks_exist()
    assert any("points at someone/else" in p
               for p in contract.rule_badges(owners))


def test_the_real_readme_carries_a_pinned_badge_for_every_blocking_workflow():
    """The state of the tree, not a synthetic one. Before 2026-09-17 this
    repository had six shields.io badges and not one live status badge."""
    contract = _load(CHECKER, "check_ci_contract_real")
    _problems, owners = contract.rule_required_checks_exist()
    assert contract.rule_badges(owners) == []
    badged = {b["file"] for b in contract.badges()}
    assert "ci.yml" in badged
    assert badged >= {owners[n] for n in contract.required_checks()}
    assert all(b["branch"] in contract.BRANCHES for b in contract.badges())


# ── `B433` — no trigger names a branch that does not exist ───────────────────


def test_a_trigger_naming_a_branch_that_does_not_exist_is_caught(contract,
                                                                 fake_repo):
    text = (fake_repo / ".github" / "workflows" / "ci.yml").read_text()
    _write(fake_repo / ".github" / "workflows" / "ci.yml",
           text.replace("branches: [main]", "branches: [main, dev]"))
    problems = contract.rule_trigger_branches()
    assert any("'dev'" in p and "no such branch" in p for p in problems), problems


def test_the_branch_register_must_agree_with_the_security_guide(contract,
                                                                fake_repo):
    """`Law 13`. The register in the checker and the branch the guide tells the
    owner to protect are the only two statements in this tree about which
    branches are real, and they already disagreed once."""
    _write(fake_repo / "docs" / "security-ci.md",
           "set the branch name pattern to `trunk`\n"
           "add these checks by name:\n"
           "   - `Python syntax (compileall)`\n")
    assert any("one of the two is wrong" in p
               for p in contract.rule_trigger_branches())


@pytest.mark.parametrize("workflow", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_no_workflow_in_the_tree_triggers_on_dev(workflow):
    """The row itself. `ci.yml`, `codeql.yml` and `docker-publish.yml` all named
    `dev` and there has never been a `dev` branch — `B352` corrected the PR and
    issue templates pointing contributors at it and the workflows were missed.
    """
    contract = _load(CHECKER, "check_ci_contract_real")
    doc = contract.load_workflow(WORKFLOWS / workflow)
    for where, named in contract.trigger_branches(doc).items():
        assert "dev" not in named, f"{workflow} still triggers on {where}=dev"


def test_codeql_analyses_pull_requests_at_all():
    """The sharp end of `B433`. CodeQL's trigger read
    `pull_request: branches: [dev]`, which filters on the branch a PR merges
    INTO — so CodeQL ran on no pull request ever, while the file's own header
    says it was set up in advanced mode precisely so that it would."""
    contract = _load(CHECKER, "check_ci_contract_real")
    doc = contract.load_workflow(WORKFLOWS / "codeql.yml")
    triggers = contract._triggers(doc)
    assert "pull_request" in triggers
    branches = contract.trigger_branches(doc)
    assert "pull_request.branches" not in branches, (
        "CodeQL is filtered to pull requests targeting a particular branch "
        "again — every PR is worth analysing")


# ── `B435` — a job that reports success did its work ─────────────────────────


def test_an_undeclared_continue_on_error_job_is_caught(contract, fake_repo):
    _write(fake_repo / ".github" / "workflows" / "ci.yml",
           "name: CI\n"
           "on:\n"
           "  push:\n"
           "    branches: [main]\n"
           "jobs:\n"
           "  scan:\n"
           "    name: Image scan\n"
           "    continue-on-error: true\n"
           "    runs-on: ubuntu-latest\n"
           "    steps:\n"
           "      - run: exit 1\n")
    problems = contract.rule_fail_open()
    assert any("Image scan" in p and "continue-on-error" in p
               for p in problems), problems


def test_a_continue_on_error_job_that_says_so_in_its_name_is_allowed(contract,
                                                                     fake_repo):
    """The flag is legitimate. What is not legitimate is a reader of the Checks
    tab having no way to know — the name is all they get."""
    _write(fake_repo / ".github" / "workflows" / "ci.yml",
           "name: CI\n"
           "on:\n"
           "  push:\n"
           "    branches: [main]\n"
           "jobs:\n"
           "  scan:\n"
           "    name: Image scan (advisory)\n"
           "    continue-on-error: true\n"
           "    runs-on: ubuntu-latest\n"
           "    steps:\n"
           "      - run: exit 1\n")
    assert contract.rule_fail_open() == []


def test_an_undeclared_continue_on_error_step_is_caught(contract, fake_repo):
    _write(fake_repo / ".github" / "workflows" / "ci.yml",
           "name: CI\n"
           "on:\n"
           "  push:\n"
           "    branches: [main]\n"
           "jobs:\n"
           "  scan:\n"
           "    name: Image scan\n"
           "    runs-on: ubuntu-latest\n"
           "    steps:\n"
           "      - name: Upload results\n"
           "        continue-on-error: true\n"
           "        run: exit 1\n")
    assert any("Upload results" in p for p in contract.rule_fail_open())


def test_trivy_no_longer_reports_green_when_the_build_or_the_upload_failed():
    """The job the brief calls out. `continue-on-error` sat on the whole job,
    so a Dockerfile that would not build, or a SARIF upload that never reached
    the Security tab `docs/security-ci.md` sends the reader to, reported a
    green tick. The findings are advisory; looking is not."""
    contract = _load(CHECKER, "check_ci_contract_real")
    doc = contract.load_workflow(WORKFLOWS / "container-trivy.yml")
    for key, spec in contract.jobs(doc).items():
        assert not contract._is_true(spec.get("continue-on-error", False)), (
            f"container-trivy.yml job {key} is advisory as a whole again")
        tolerant = [s for s in spec["steps"]
                    if contract._is_true(s.get("continue-on-error", False))]
        assert len(tolerant) == 1, (
            f"{key}: exactly one step — the scan — may tolerate failure")
        assert "advisory" in str(tolerant[0].get("name", "")).lower()


def test_every_fail_open_site_in_the_tree_declares_itself():
    contract = _load(CHECKER, "check_ci_contract_real")
    assert contract.rule_fail_open() == []
    assert contract.fail_open_sites(), (
        "no `continue-on-error` anywhere — this rule now proves nothing, which "
        "is worth noticing rather than deleting")


# ── `B434` — a skip proves itself ────────────────────────────────────────────


@pytest.fixture()
def docs_only():
    return _load(ROOT / ".github" / "scripts" / "docs_only.py", "docs_only_mod")


def test_an_empty_change_set_is_not_a_documentation_change(docs_only):
    """The whole row. The shell this replaced ended in `[ -z "$non_docs" ]`, and
    an empty `changed` made that true — so a push whose `before` is the zero
    sha, a force-push whose base is gone, or any failed `git diff` skipped
    pytest and reported `Python tests (pytest)` as a success that ran no tests.
    """
    assert docs_only.is_docs_only([]) is False
    assert docs_only.is_docs_only([""]) is False
    assert docs_only.is_docs_only(["", "  "]) is False
    assert "empty" in docs_only.explain([])


def test_a_documentation_change_still_skips_the_suite(docs_only):
    """`Law 1`. The saving is real and stays."""
    assert docs_only.is_docs_only(["docs/setup.md"]) is True
    assert docs_only.is_docs_only(["README.md", "docs/security-ci.md"]) is True
    assert docs_only.is_docs_only([".github/CONTRIBUTING.md"]) is True


def test_one_non_documentation_file_runs_the_suite(docs_only):
    assert docs_only.is_docs_only(["docs/setup.md", "src/app.py"]) is False
    assert docs_only.is_docs_only([".github/workflows/ci.yml"]) is False
    assert docs_only.is_docs_only([".github/ISSUE_TEMPLATE/bug.yml"]) is False


def _run_helper(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / ".github" / "scripts" / "docs_only.py"),
         *args],
        capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin"})


def test_the_cli_prints_only_the_answer_on_stdout(tmp_path):
    """The step redirects stdout into `$GITHUB_OUTPUT`, so anything else on
    stdout becomes a step output GitHub then tries to parse. The reasoning goes
    to stderr, where the log shows it."""
    changed = tmp_path / "changed.txt"
    changed.write_text("docs/setup.md\n", encoding="utf-8")
    proc = _run_helper("--changed-from", str(changed))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["docs_only=true", "changed_count=1"]
    assert "skipping the suite" in proc.stderr


def test_an_unreadable_change_list_runs_the_suite(tmp_path):
    proc = _run_helper("--changed-from", str(tmp_path / "does-not-exist.txt"))
    assert proc.returncode == 0
    assert "docs_only=false" in proc.stdout
    assert "could not read" in proc.stderr


def test_the_helper_reads_no_environment_of_its_own():
    """`check-env-declared.py` holds this project to a register of every
    variable its code reads, and `GITHUB_OUTPUT` is GitHub's name, not ours.
    The workflow owns the redirect; this stays a function of its argument."""
    source = (ROOT / ".github" / "scripts" / "docs_only.py").read_text(
        encoding="utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    body = code.split('"""', 2)[-1]
    assert "os.environ" not in body and "getenv" not in body


def test_the_workflow_asks_the_helper_rather_than_deciding_in_shell():
    """`Law 13` and `Law 20` in one. The decision must exist in one place that
    the tests above can call; a second copy in shell is what rotted."""
    contract = _load(CHECKER, "check_ci_contract_real")
    assert contract.rule_skip_proves_itself() == []
    doc = contract.load_workflow(WORKFLOWS / "ci.yml")
    script = contract._job_script(doc, "python-tests")
    # `Law 20`: the comment above the step explains the shell it replaced, so
    # the assertion is on what the step RUNS, with the commentary stripped.
    code = "\n".join(line for line in script.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "docs_only.py" in code
    assert "non_docs" not in code, "the shell that decided this is back"
    assert "grep -Ev" not in code


def test_the_rule_catches_a_helper_that_says_yes_to_nothing(contract, fake_repo,
                                                            monkeypatch):
    """The rule calls the helper rather than reading it, so a helper that
    regresses is caught by the checker and not only by the tests above."""
    helper = fake_repo / ".github" / "scripts"
    helper.mkdir(parents=True)
    _write(helper / "docs_only.py",
           "def is_docs_only(changed):\n"
           "    return not [p for p in changed if not p.endswith('.py')]\n")
    text = contract.CI.read_text(encoding="utf-8")
    _write(contract.CI, text + "        # docs_only.py\n")
    problems = contract.rule_skip_proves_itself()
    assert any("empty change set is documentation" in p for p in problems), problems


# ── `B436` — one list of which files are ours ────────────────────────────────


def test_ci_byte_compiles_every_python_file_that_is_ours():
    """`B10`'s Python half. `compileall app.py core routes src services scripts
    tests` missed 51 of 1,429 tracked `.py` files on 2026-09-17 — including all
    22 checkers the same workflow then runs, `launcher.py`, and every module
    under `companion/`, `mcp_servers/` and `netagent/`."""
    contract = _load(CHECKER, "check_ci_contract_real")
    assert contract.rule_one_file_list() == []
    gate = contract._load_gate()
    tracked = subprocess.run(["git", "ls-files", "*.py"], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=120)
    ours = {f for f in tracked.stdout.split() if f}
    assert set(gate._python_files()) == ours
    for expected in (".pantheon/check-ci-contract.py", "launcher.py",
                     ".github/scripts/docs_only.py"):
        assert expected in ours


def test_neither_syntax_job_keeps_its_own_glob():
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    contract = _load(CHECKER, "check_ci_contract_real")
    doc = contract.load_workflow(WORKFLOWS / "ci.yml")
    for job in ("python-syntax", "node-syntax"):
        script = contract._job_script(doc, job)
        assert "release-gate.py" in script, f"{job} built its own list again"
    assert "compileall -q app.py" not in ci


def test_the_rule_catches_a_syntax_job_that_lists_files_by_hand(contract,
                                                                fake_repo):
    _write(contract.CI,
           "name: CI\n"
           "on:\n"
           "  push:\n"
           "    branches: [main]\n"
           "jobs:\n"
           "  python-syntax:\n"
           "    name: Python syntax (compileall)\n"
           "    runs-on: ubuntu-latest\n"
           "    steps:\n"
           "      - run: python -m compileall -q app.py core tests\n"
           "  node-syntax:\n"
           "    name: JS syntax (node --check)\n"
           "    runs-on: ubuntu-latest\n"
           "    steps:\n"
           "      - run: node --check static/app.js\n")
    problems = contract.rule_one_file_list()
    assert any("python-syntax" in p for p in problems), problems
    assert any("node-syntax" in p for p in problems), problems


# ── the checker as a command ─────────────────────────────────────────────────


def _rules_the_checker_runs() -> int:
    """How many rules `main()` actually puts in its list.

    `B861`. This was the literal `7`, and rule eight (`B855`) turned it red —
    the same shape `B651` names: a test may assert that two numbers agree, it
    may not carry one of them. The count is read out of the checker's own
    `rules = [...]`, so adding rule nine needs no edit here and REMOVING one
    still fails the header comparison below.
    """
    import ast

    tree = ast.parse(CHECKER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "rules" for t in node.targets)
                and isinstance(node.value, ast.List)):
            return len(node.value.elts)
    raise AssertionError("check-ci-contract.py no longer builds a `rules` list")


def test_the_checker_passes_on_this_tree_and_says_what_it_looked_at():
    proc = subprocess.run([sys.executable, str(CHECKER)], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PROBLEMS 0" in proc.stdout
    rules = _rules_the_checker_runs()
    assert rules >= 7, "a rule was deleted, not added"
    assert f"{rules} rules" in proc.stdout, (
        f"the header does not count the rules it runs ({rules}): {proc.stdout}")


def test_list_mode_prints_the_inventory_and_changes_nothing():
    proc = subprocess.run([sys.executable, str(CHECKER), "--list"], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0
    assert "ImPanick/pantheon" in proc.stdout
    assert "required checks" in proc.stdout
    assert "fail-open sites" in proc.stdout


def test_the_checker_is_stdlib_only():
    """The `wiring-ratchet` job installs nothing before it runs the checkers, so
    a checker that imports PyYAML is a checker that cannot run in the CI it is
    about (`Law 16` for the offline gate, and plain fact for the workflow)."""
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path=[p for p in sys.path if 'site-packages' "
         "not in p and 'dist-packages' not in p]; "
         "import importlib.util as u; "
         f"s=u.spec_from_file_location('c', {str(CHECKER)!r}); "
         "m=u.module_from_spec(s); s.loader.exec_module(m); print('ok')"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_the_yaml_subset_reads_every_workflow_in_the_tree():
    """It is a parser, so it gets a test that parses the real inputs. A rule
    that silently reads nothing is the failure mode of every checker in this
    directory (`check-tracker.py`'s own regex, 2026-08-31)."""
    contract = _load(CHECKER, "check_ci_contract_real")
    files = contract.workflow_files()
    assert len(files) >= 10
    for path in files:
        doc = contract.load_workflow(path)
        assert contract.jobs(doc), f"{path.name} parsed to no jobs"
        for name in contract.job_names(doc):
            assert name.strip()


def test_the_checker_is_in_ci_so_the_gate_runs_it():
    """The loop that makes this whole file load-bearing: `release-gate.py`
    reads its checker list out of `ci.yml`, so a checker added to the workflow
    is a checker the local gate runs from the next commit."""
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "python3 .pantheon/check-ci-contract.py" in ci
    gate = _load(ROOT / ".pantheon" / "release-gate.py", "release_gate_contract")
    assert "ci-contract" in {name for name, _argv in gate._checkers_from_ci()}
