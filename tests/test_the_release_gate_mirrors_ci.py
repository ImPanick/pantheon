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
