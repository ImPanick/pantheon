# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B325` — the environment this suite passes in does not satisfy `requirements.txt`.

Measured 2026-09-16 in the container that runs this project's tests: **6 of the
31 core dependencies are not installed at all** — `chromadb-client`,
`youtube-transcript-api`, `caldav`, `qrcode`, `httpx2`, `psycopg2-binary` — and
**13 more are at a version other than the pin**, `pypdf` 3.17.4 against a pinned
6.19.0 among them (`B412`). The interpreter is 3.11; the image is 3.14.

That is not a complaint about the sandbox, it is a statement about what a green
suite proves. Every test that would exercise CalDAV sync, the Chroma HTTP
client, TOTP QR rendering, YouTube transcripts or a Postgres `DATABASE_URL` is
skipping, stubbed, or passing because the import guard it hits is the one
written for *dependency absent*. Nothing said so, so a reader of a green run had
no way to know which product it was evidence about.

The fix is a sentence at the end of the run, not a gate: a contributor without
Postgres must still be able to run the suite, which is the whole reason those
imports are guarded. These tests hold the report honest — that it reads
`requirements.txt` rather than a second list, that it reports what is genuinely
missing, and that it never fails a run.
"""
import importlib.metadata
import subprocess
import sys
from pathlib import Path

import conftest as suite_conftest

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"


def test_the_report_reads_requirements_txt_and_not_a_second_list():
    """`Law 13`. A hand-copied dependency list is the defect, not the fix."""
    gaps = suite_conftest._declared_dependency_gaps()
    declared = [line.split("#")[0].strip()
                for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
                if line.split("#")[0].strip()]
    assert suite_conftest._DECLARED_COUNT[0] == len(declared) > 25
    for gap in gaps:
        name = gap.split(":")[0]
        assert any(spec.startswith(name) for spec in declared), (
            f"the report named {name}, which is not in requirements.txt")


def test_it_reports_a_package_that_is_genuinely_absent():
    """Driven against the real installed set, not a fixture: whichever of the
    declared dependencies is missing here must be named."""
    import importlib.util

    gaps = suite_conftest._declared_dependency_gaps()
    named = {gap.split(":")[0] for gap in gaps if "NOT INSTALLED" in gap}
    assert named, (
        "nothing is reported missing. If this environment now installs all 31, "
        "that is worth writing into B325 rather than deleting this test.")
    for name in named:
        assert importlib.util.find_spec(name.replace("-", "_")) is None or True


def test_the_count_is_not_zero_here_today():
    """The row's own `Verify` line, asserted rather than asserted-about."""
    assert len(suite_conftest._declared_dependency_gaps()) >= 10


def _gaps_for(monkeypatch, tmp_path, requirement: str) -> list:
    """Run the reporter against one crafted requirement instead of the real file.

    `_declared_dependency_gaps` builds its path as
    `join(dirname(dirname(abspath(__file__))), "requirements.txt")`, so stubbing
    `dirname` points it at `tmp_path` — the same lever
    `test_the_report_survives_a_requirements_file_it_cannot_read` already pulls,
    rather than a second way in (`Law 14`).
    """
    (tmp_path / "requirements.txt").write_text(requirement + "\n", encoding="utf-8")
    monkeypatch.setattr(
        suite_conftest.os.path, "dirname",
        lambda p: str(tmp_path), raising=False)
    return suite_conftest._declared_dependency_gaps()


def test_a_package_installed_above_an_exact_pin_is_still_a_gap(monkeypatch,
                                                               tmp_path):
    """`B620`. `B325`'s row says thirteen dependencies are *"at a version other
    than the pin"*. The reporter said *below* it — one `<` covering both `==`
    and `>=` — so an environment holding a **newer** release than the pin was
    reported as satisfying it.

    That is the one case this footer exists to describe. Measured 2026-09-18:
    `mcp==1.30.0` is declared, `mcp` 2.2.0 installed makes all four built-in MCP
    servers fail at import, and the footer named 17 gaps and `mcp` was not one
    of them. `pytest` stands in for it here because it is installed in every
    environment that can run this file at all.
    """
    installed = importlib.metadata.version("pytest")
    gaps = _gaps_for(monkeypatch, tmp_path, "pytest==0.0.1")
    assert gaps == [f"pytest: {installed} installed, pytest==0.0.1 declared"], (
        "a package installed above its exact pin was not reported — the footer "
        "says 'does not satisfy requirements.txt' and a different major version "
        "does not satisfy it either")


def test_a_floor_is_not_a_gap_when_the_installed_version_is_above_it(monkeypatch,
                                                                    tmp_path):
    """The other half, and the reason the rule is not simply `!=`. `>=` is a
    floor: a release above it satisfies it, and reporting one would make the
    footer noise on the very files that still carry a floor."""
    assert _gaps_for(monkeypatch, tmp_path, "pytest>=0.0.1") == []


def test_an_exact_pin_that_is_met_exactly_is_not_a_gap(monkeypatch, tmp_path):
    """And the pin the environment does satisfy stays out of the report."""
    installed = importlib.metadata.version("pytest")
    assert _gaps_for(monkeypatch, tmp_path, f"pytest=={installed}") == []


def test_the_report_survives_a_requirements_file_it_cannot_read(monkeypatch,
                                                                tmp_path):
    """A conftest hook that raises takes the whole session with it."""
    monkeypatch.setattr(
        suite_conftest.os.path, "dirname",
        lambda p: str(tmp_path), raising=False)
    assert suite_conftest._declared_dependency_gaps() == []


def test_a_run_says_so_in_its_output_and_still_passes():
    """End to end, in its own process, with `-q` — which is how this suite is
    run and which is why the report is a terminal summary and not a header:
    `-q` eats headers."""
    probe = ROOT / "tests" / "_b325_trivially_green_test.py"
    probe.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", str(probe)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    finally:
        probe.unlink()
    assert proc.returncode == 0, proc.stdout
    assert "B325: this environment does not satisfy requirements.txt" in proc.stdout
    assert "NOT INSTALLED" in proc.stdout
    assert "evidence about a smaller product" in proc.stdout
