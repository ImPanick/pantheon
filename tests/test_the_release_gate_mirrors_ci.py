# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P10-10` — the full regression as one command, and it must not drift from CI.

Every checker and the suite have been run by hand before each commit in this
project. That works right up until the run somebody is tired during: **a gate
you have to remember is a gate that is sometimes not there.**

The property that matters is not that the script runs things — it is that the
list of things comes out of `.github/workflows/ci.yml` rather than a copy.
A ceiling in two files is a ceiling that will eventually disagree with itself,
and the disagreement gets discovered by a push that fails after a local run said
everything was fine (`Law 13`).

It earned its place on the first run: `check-tracker.py` had existed for weeks
and CI never ran it, so a roadmap that lies about its own arithmetic — the exact
defect `B44` and `B48` are about, and one the checker caught again on
2026-09-10 — has been pushable this whole time.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_GATE = _REPO / ".pantheon" / "release-gate.py"
_CI = _REPO / ".github" / "workflows" / "ci.yml"

sys.path.insert(0, str(_REPO / ".pantheon"))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("release_gate", _GATE)
release_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_gate)


def _ci_checkers() -> set[str]:
    text = _CI.read_text(encoding="utf-8")
    return set(re.findall(r"python3?\s+\.pantheon/check-([\w-]+)\.py", text))


# ── the list comes from CI, not from a copy ───────────────────────────────────


def test_the_checkers_are_read_out_of_the_workflow():
    from_gate = {name for name, _argv in release_gate._checkers_from_ci()}
    assert from_gate == _ci_checkers()
    assert from_gate, "no checkers parsed — the workflow format changed"


def test_the_ceilings_come_from_ci_too():
    """A ratchet is a number, and a number copied is a number that drifts. The
    gate must run `--max 402`, not `--max` whatever it remembers."""
    argv = dict(release_gate._checkers_from_ci())
    text = _CI.read_text(encoding="utf-8")
    for name, args in argv.items():
        for flag in [a for a in args if a.startswith("--")]:
            i = args.index(flag)
            value = args[i + 1] if i + 1 < len(args) else ""
            assert f"{flag} {value}" in text, (
                f"{name} runs `{flag} {value}` locally and CI does not")


def test_no_checker_is_hardcoded_in_the_script():
    # The failure this prevents: someone adds a checker to the script, CI never
    # learns about it, and the gate becomes a *different* gate that passes.
    code = "\n".join(ln for ln in _GATE.read_text(encoding="utf-8").splitlines()
                     if not ln.lstrip().startswith("#"))
    body = code[code.index("def main("):]
    for name in _ci_checkers():
        assert f"check-{name}" not in body, f"{name} is named in main() — read it from CI"


def test_a_checker_ci_does_not_run_is_reported_rather_than_hidden():
    """The gap finder, and the reason `check-tracker` is now in CI. A checker on
    disk that CI does not run is either a hole in CI or a file nobody deleted,
    and quietly including it in the local gate would hide both."""
    extra = release_gate._extra_checkers(_ci_checkers())
    assert extra == [], (
        f"{[n for n, _ in extra]} exist but CI does not run them — add them to "
        "ci.yml or delete them")


def test_every_checker_on_disk_is_in_ci():
    on_disk = {p.stem.replace("check-", "") for p in _REPO.glob(".pantheon/check-*.py")}
    assert on_disk == _ci_checkers(), (
        f"CI and the .pantheon directory disagree: {on_disk ^ _ci_checkers()}")


# ── what it does with results ─────────────────────────────────────────────────


def test_an_advisory_step_cannot_fail_the_gate():
    """`P3-20`: a ratchet on a number nobody has calibrated is worse than none.
    The retrieval eval is a report, and reports do not block pushes."""
    assert "retrieval eval" in release_gate.ADVISORY


def test_a_failing_checker_does_fail_the_gate():
    ok, _secs, _tail = release_gate._run("x", [sys.executable, "-c", "import sys; sys.exit(3)"])
    assert ok is False


def test_a_passing_checker_passes():
    ok, _secs, tail = release_gate._run("x", [sys.executable, "-c", "print('fine')"])
    assert ok is True and tail == "fine"


def test_a_missing_binary_is_a_failure_and_not_a_crash():
    ok, _secs, tail = release_gate._run("x", ["definitely-not-a-real-binary-xyz"])
    assert ok is False and tail


# ── it says what it does not cover ────────────────────────────────────────────


def test_it_admits_the_half_it_cannot_do():
    """`P10-10` asks for a manual pass over every surface as well. A gate that
    printed "passed" without saying so would be claiming a coverage it has not
    got, which is the class of quiet lie `B61` was about."""
    out = subprocess.run([sys.executable, str(_GATE), "--list"],
                         capture_output=True, text=True, cwd=str(_REPO), timeout=120)
    assert out.returncode == 0
    source = _GATE.read_text(encoding="utf-8")
    assert "manual pass over every surface" in source


def test_list_mode_changes_nothing_and_exits_clean():
    out = subprocess.run([sys.executable, str(_GATE), "--list"],
                         capture_output=True, text=True, cwd=str(_REPO), timeout=120)
    assert out.returncode == 0
    assert "checkers read from" in out.stdout
    assert "pytest" in out.stdout


@pytest.mark.parametrize("flag", ["--fast", "--list"])
def test_the_documented_flags_exist(flag):
    out = subprocess.run([sys.executable, str(_GATE), "--help"],
                         capture_output=True, text=True, cwd=str(_REPO), timeout=60)
    assert flag in out.stdout


def test_node_check_skips_rather_than_fails_without_node(monkeypatch):
    # CI has node; a contributor's laptop might not. Refusing to run the whole
    # gate over a missing optional tool is how a gate stops being used.
    monkeypatch.setattr(release_gate.shutil, "which", lambda _n: None)
    ok, detail = release_gate._node_check(["static/js/notes.js"])
    assert ok is True and "skipped" in detail


def test_node_check_actually_parses_the_modules():
    if not release_gate.shutil.which("node"):
        pytest.skip("node not on PATH")
    ok, detail = release_gate._node_check(["static/js/notes.js", "static/js/memory.js"])
    assert ok is True, detail
    assert "2 modules parse" in detail


def test_vendored_bundles_are_left_alone():
    """They are not ours to parse, and some are minified past what node will
    accept without a module hint. A gate that fails on somebody else's code is
    a gate that gets switched off."""
    files = release_gate._js_files()
    assert files, "no JS files found"
    assert not [f for f in files if "/lib/" in f]


# --- `B10`: the check that checked nothing -----------------------------------


def test_node_check_rejects_a_module_that_does_not_parse():
    """The negative case, which had no test and is the whole point of the gate.

    Everything above proves `_node_check` says yes to good files. Nothing
    proved it says no — and for most of this fork's life the CI step that
    shared its name said yes to literally any text.

    **The probe lives in `static/`, not `static/js/`, and that is the whole
    test.** `static/js/package.json` declares `{"type": "module"}`, so a file
    there parses as ESM however you invoke node — a probe placed inside it
    passes whether or not the gate pipes. `static/` is governed by the root
    `package.json`, which declares no type: it is where `static/app.js` lives
    and the only place the defect is visible. A mutation run found this; the
    first version of this test put the probe in `static/js/` and could not
    tell the fixed gate from the broken one.
    """
    if not release_gate.shutil.which("node"):
        pytest.skip("node not on PATH")
    broken = _REPO / "static" / "_b10_probe_not_javascript.js"
    broken.write_text("import x from './app.js';\nconst broken = ;\n",
                      encoding="utf-8")
    try:
        ok, detail = release_gate._node_check([str(broken.relative_to(_REPO))])
    finally:
        broken.unlink()
    assert ok is False, detail
    assert "_b10_probe" in detail


def test_passing_a_path_to_node_check_is_what_made_it_a_no_op(tmp_path):
    """Pins the mechanism, so nobody 'simplifies' the piping back out.

    `node --check <path>` resolves module type from the nearest `package.json`.
    The repo root declares no `"type"`, so anything outside `static/js/` parses
    as CommonJS — and node's module-syntax detection retries the failed parse
    as ESM and does not re-check, which passes ANY text containing an `import`.
    This test builds that layout in a temp directory and shows both answers.
    """
    if not release_gate.shutil.which("node"):
        pytest.skip("node not on PATH")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    garbage = tmp_path / "app.js"
    garbage.write_text("import x from './nowhere.js';\nthis is not javascript ( [ {\n",
                       encoding="utf-8")

    by_path = subprocess.run(["node", "--check", str(garbage)],
                             capture_output=True, text=True, cwd=str(tmp_path))
    piped = subprocess.run(["node", "--input-type=module", "--check"],
                           input=garbage.read_text(encoding="utf-8"),
                           capture_output=True, text=True, cwd=str(tmp_path))

    assert by_path.returncode == 0, "node started rejecting this — re-read B10"
    assert piped.returncode != 0, "the piped form must still catch it"


def test_the_gate_checks_every_js_file_that_is_ours():
    """`Law 13`. CI kept its own list and it had already drifted — CI's loop
    named 173 files and never `static/sw.js`, which the gate has always
    checked. There is one list now and this is the shape of it."""
    files = set(release_gate._js_files())
    tracked = subprocess.run(["git", "ls-files", "*.js", "*.mjs"],
                             cwd=str(_REPO), capture_output=True, text=True)
    ours = {f for f in tracked.stdout.split()
            if f and not f.startswith("static/lib/") and not f.startswith("library/")}
    assert files == ours, sorted(ours ^ files)
    assert "static/app.js" in files
    assert "static/sw.js" in files


def test_ci_does_not_keep_a_second_list_of_js_files():
    """Read as data, not grepped for a nice sentence: the step must not build
    its own glob. If it does, the two lists will disagree again."""
    step = _CI.read_text(encoding="utf-8").split(
        "- name: node --check", 1)[1].split("- name:", 1)[0]
    assert "release-gate.py" in step
    assert "static/js/**" not in step


# --- `B431`: the list came from CI and nothing else did ----------------------
#
# Measured 2026-09-17. The checker list was read out of the workflow and every
# other decision about *how* a step runs was a copy or an accident:
#
#   suite        gate `pytest -q -p no:randomly`, CI `pytest -q` — so five waves
#                of "the suite passed" were evidence about a FIXED TEST ORDER
#                that CI does not use
#   retrieval    gate `retrieval_eval.py`, CI `retrieval_eval.py --verbose`
#   python       CI pins 3.11; the gate ran on whatever was on PATH
#   node         CI pins 20; measured here on 22, silently
#
# These pin the direction of the fix: every one of those values is read out of
# the workflow, so the two cannot disagree without `ci.yml` changing.


def test_the_suite_argv_comes_from_ci_and_not_from_memory():
    args = release_gate.ci_suite_args()
    text = _CI.read_text(encoding="utf-8")
    assert args, "the gate has no suite invocation to mirror"
    assert f"pytest {' '.join(args)}" in text, (
        f"the gate would run `pytest {' '.join(args)}` and ci.yml does not")


def test_the_gate_does_not_quietly_disable_a_plugin_ci_leaves_on():
    """The concrete divergence. `-p no:randomly` fixes collection order, which
    makes a local run reproducible and makes it evidence about a different run
    from the one CI does. If CI wants it, CI says so and the gate inherits it."""
    args = release_gate.ci_suite_args()
    text = _CI.read_text(encoding="utf-8")
    if "no:randomly" in " ".join(args):
        assert "no:randomly" in text
    else:
        assert "no:randomly" not in " ".join(args)


def test_a_targeted_pytest_run_in_ci_is_not_mistaken_for_the_suite():
    """`law16-egress` runs two named files. Taking its argv would have made the
    gate's "suite" two tests wide and still call itself the suite."""
    args = release_gate.ci_suite_args()
    assert not [a for a in args if a.startswith("tests/")]


def test_the_advisory_step_runs_with_the_flags_ci_gives_it():
    argv = release_gate.ci_advisory_argv()
    assert argv[0].endswith("retrieval_eval.py")
    assert " ".join(argv) in _CI.read_text(encoding="utf-8")


@pytest.mark.parametrize("tool,derive", [
    ("python", lambda: release_gate.ci_python_version()),
    ("node", lambda: release_gate.ci_node_version()),
])
def test_the_pinned_toolchain_is_read_from_the_workflow(tool, derive):
    version = derive()
    assert version, f"ci.yml pins no {tool} version the gate can read"
    assert re.search(rf"^\s*{tool}-version:\s*[\"']?{re.escape(version)}",
                     _CI.read_text(encoding="utf-8"), re.M)


def test_every_derived_value_changes_when_the_workflow_does(tmp_path, monkeypatch):
    """The test that makes the four above mean anything.

    A mutation run found it: replacing `ci_python_version()`'s body with
    `return "3.11"` and `ci_node_version()`'s with `return "20"` survived every
    other test in this file, because the hardcoded answers are the right ones
    *today*. That is the whole `Law 13` defect — a value copied is a value that
    is correct until the day it is not — so the property has to be that the
    answer follows the workflow, which only a different workflow can show.
    """
    other = tmp_path / "ci.yml"
    other.write_text(
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        "      - uses: actions/setup-python@x\n"
        "        with:\n"
        "          python-version: \"3.99\"\n"
        "      - uses: actions/setup-node@x\n"
        "        with:\n"
        "          node-version: \"99\"\n"
        "      - run: python3 .pantheon/retrieval_eval.py --json\n"
        "      - run: python -m pytest -q --maxfail=7\n",
        encoding="utf-8")
    monkeypatch.setattr(release_gate, "WORKFLOW", other)

    assert release_gate.ci_python_version() == "3.99"
    assert release_gate.ci_node_version() == "99"
    assert release_gate.ci_suite_args() == ["-q", "--maxfail=7"]
    assert release_gate.ci_advisory_argv() == [".pantheon/retrieval_eval.py",
                                               "--json"]


def test_an_interpreter_that_is_not_cis_is_reported_rather_than_enforced(monkeypatch):
    """Refusing to run over a wrong node is how a gate stops being used
    (`P10-10`). Saying nothing is how five waves shipped against a red
    pipeline. It is a line in the report, and only that."""
    monkeypatch.setattr(release_gate, "ci_node_version", lambda: "20")
    monkeypatch.setattr(release_gate, "_node_version", lambda: "22.22.2")
    diverged = release_gate.environment_divergence()
    assert any("node 22.22.2" in d and "CI pins 20" in d for d in diverged)
    monkeypatch.setattr(release_gate, "_node_version", lambda: "20.19.0")
    assert not [d for d in release_gate.environment_divergence() if "node" in d]


def test_an_interpreter_two_minors_from_cis_is_reported(monkeypatch):
    """The one that matters most, because `dependency-review.yml` pins 3.14 with
    a comment explaining that the interpreter decides which dependencies the
    image installs — while the suite runs on 3.11 (`B438`)."""
    monkeypatch.setattr(release_gate, "ci_python_version", lambda: "3.14")
    monkeypatch.setattr(release_gate, "ci_node_version", lambda: None)
    diverged = release_gate.environment_divergence()
    assert any("CI pins 3.14" in d for d in diverged), diverged


def test_a_patch_level_difference_is_not_a_divergence(monkeypatch):
    """`3.11.15` and `3.11.9` are the same claim. A gate that cried about a
    patch release would be a gate people learn to ignore."""
    monkeypatch.setattr(
        release_gate, "ci_python_version",
        lambda: f"{sys.version_info.major}.{sys.version_info.minor}.0")
    monkeypatch.setattr(release_gate, "ci_node_version", lambda: None)
    assert release_gate.environment_divergence() == []


def test_a_matching_toolchain_produces_no_noise(monkeypatch):
    monkeypatch.setattr(release_gate, "ci_python_version",
                        lambda: f"{sys.version_info.major}.{sys.version_info.minor}")
    monkeypatch.setattr(release_gate, "ci_node_version", lambda: None)
    assert release_gate.environment_divergence() == []


# --- `B432`: a green run that says what it is not evidence about -------------


def test_fast_says_the_suite_did_not_run_where_a_reader_will_see_it():
    """The row. Every gate run on 2026-09-17 was `--fast`, and the only
    difference in the output between "22 checkers passed" and "22 checkers and
    9,580 tests passed" was the words `Safe to push` at the end of one line."""
    out = subprocess.run([sys.executable, str(_GATE), "--list", "--fast"],
                         capture_output=True, text=True, cwd=str(_REPO), timeout=120)
    assert out.returncode == 0
    assert "NOT RUN   the suite" in out.stdout
    lines = release_gate.not_covered(fast=True, node_skipped=False)
    assert any(line.startswith("NOT RUN") and "suite" in line for line in lines)


def test_a_full_run_does_not_claim_the_suite_was_skipped():
    lines = release_gate.not_covered(fast=False, node_skipped=False)
    assert not [l for l in lines if "the suite" in l]


def test_the_gate_names_the_workflows_it_does_not_run():
    """It mirrors `ci.yml` and nothing else, while a push also sets off the
    secret scan, the workflow-security audit, the dependency review and the
    container scan — four gates `docs/security-ci.md` calls merge-blocking.
    Reading the directory rather than listing them means one added tomorrow is
    named the day it lands."""
    others = release_gate.workflows_not_run_here()
    assert "ci.yml" not in others
    for blocking in ("secret-scan.yml", "workflow-security.yml",
                     "dependency-review.yml", "container-scan.yml"):
        assert blocking in others
    assert "vendored-freshness.yml" not in others, (
        "a schedule-only workflow is not something your push set off")
    assert any("workflows a push also sets off" in line
               for line in release_gate.not_covered(True, False))


def test_a_skipped_node_check_is_not_reported_as_a_pass(monkeypatch):
    """`node not on PATH` printed the same `ok` as a run that parsed 219
    modules. It is a legitimate skip and it is not a pass."""
    lines = release_gate.not_covered(fast=False, node_skipped=True)
    assert any("node --check" in line and line.startswith("NOT RUN")
               for line in lines)


def test_every_run_admits_the_manual_pass():
    for fast in (True, False):
        assert any("manual pass over every surface" in line
                   for line in release_gate.not_covered(fast, False))
