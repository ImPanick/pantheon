# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P3-23` — the configuration an operator can find, versus the configuration there is.

Four sources of truth about this product's settings and no two agree: what the
code reads, what `.env.example` declares, what `docker-compose.yml` forwards,
and what `docs/setup.md` explains. An operator looks in `.env.example`.

`H08` is what the gap costs. The switch that uncaps every local agent run
(`PANTHEON_UNLIMITED_LOCAL`) appeared **nowhere** outside the module that read
it — not in the example file, not in compose, not in the docs — so the only way
to turn that behaviour off was to already know the variable's name. The fix for
that row was to document one variable. This row is the measurement that finds
the next one.

Two directions, deliberately measured two different ways:

* **undeclared** — read by app code, absent from `.env.example`. Found from
  literal `os.getenv("X")` call sites: precise about what it finds, and blind
  to `os.getenv(SOME_CONSTANT)`. Ratcheted rather than driven to zero, because
  most of the remainder is internal plumbing and writing 74 shallow entries
  would make the file worse, not better.

* **unreferenced** — declared in `.env.example` and appearing nowhere else in
  the repository. Held at **zero**, and matched by plain text across every
  tracked file rather than by the AST scan, because a false alarm here would
  send somebody deleting a variable that works. A documented knob nothing reads
  is worse than an undocumented one: an operator who sets it believes something
  changed.
"""

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CHECKER = _REPO / ".pantheon" / "check-env-declared.py"


def _load(root: Path):
    spec = importlib.util.spec_from_file_location("env_declared_checker", _CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    module.ENV_EXAMPLE = root / ".env.example"
    return module


@pytest.fixture
def fixture_repo(tmp_path):
    def build(python: str, env_example: str, extra: dict | None = None):
        (tmp_path / "app.py").write_text(python, encoding="utf-8")
        (tmp_path / ".env.example").write_text(env_example, encoding="utf-8")
        for name, text in (extra or {}).items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
        return _load(tmp_path)
    return build


# ── what counts as a read ─────────────────────────────────────────────────────


@pytest.mark.parametrize("source", [
    'import os\nx = os.getenv("WANTED")\n',
    'import os\nx = os.getenv("WANTED", "fallback")\n',
    'import os\nx = os.environ.get("WANTED")\n',
    'import os\nx = os.environ["WANTED"]\n',
    'import os\nx = os.environ.pop("WANTED", None)\n',
    'from os import getenv\nx = getenv("WANTED")\n',
])
def test_every_spelling_of_reading_the_environment_counts(fixture_repo, source):
    # The row carried three different counts because it was measured with grep.
    # Each of these is a real read and each is spelled differently in this tree.
    mod = fixture_repo(source, "")
    assert "WANTED" in mod.literal_reads()


def test_a_declared_variable_is_not_reported(fixture_repo):
    mod = fixture_repo('import os\nx = os.getenv("WANTED")\n', "WANTED=1\n")
    assert set(mod.literal_reads()) - set(mod.declared()) == set()


def test_a_commented_declaration_still_declares(fixture_repo):
    # Almost every entry in the real file is commented out — that is the file's
    # whole style, and reading only uncommented lines would report nearly all
    # of them as missing.
    mod = fixture_repo('import os\nx = os.getenv("WANTED")\n', "# WANTED=1\n")
    assert "WANTED" in mod.declared()


def test_tests_and_the_checker_directory_are_not_scanned(fixture_repo):
    mod = fixture_repo(
        "x = 1\n", "",
        extra={"tests/test_a.py": 'import os\nos.getenv("ONLY_IN_TESTS")\n',
               ".pantheon/thing.py": 'import os\nos.getenv("ONLY_IN_PANTHEON")\n'},
    )
    assert set(mod.literal_reads()) == set()


# ── the direction held at zero ────────────────────────────────────────────────


def test_a_documented_knob_nothing_uses_is_reported(fixture_repo):
    mod = fixture_repo("x = 1\n", "# GHOST_SETTING=1\n")
    assert mod.unreferenced(mod.declared()) == ["GHOST_SETTING"]


def test_a_dead_knob_fails_the_run_and_not_only_the_report(fixture_repo, monkeypatch, capsys):
    # `failed = False` on this branch leaves the message printed and the exit
    # code green — a check nobody notices is off. Asserted through `main()`
    # rather than through the helper it calls.
    # The fixture reads every NOT_OURS name, so the stale-exemption rule is
    # satisfied and the dead-knob branch is the only thing that can fail the
    # run. Without this the two rules mask each other and the test passes for
    # the wrong reason — which is exactly what it is here to rule out.
    exemptions = _load(_REPO).NOT_OURS
    reads = "import os\n" + "".join(f'os.getenv({n!r})\n' for n in exemptions)
    mod = fixture_repo(reads, "# GHOST_SETTING=1\n")
    monkeypatch.setattr(sys, "argv", ["check-env-declared.py"])
    assert mod.unreferenced(mod.declared()) == ["GHOST_SETTING"]
    assert sorted(set(mod.NOT_OURS) - set(mod.literal_reads())) == [], (
        "the fixture must satisfy the stale rule, or it masks the one under test"
    )
    assert mod.main() == 1
    assert "GHOST_SETTING" in capsys.readouterr().out


def test_a_knob_read_indirectly_is_not_reported(fixture_repo):
    # The reason this direction is a text match and not the AST scan: the real
    # tree reads several variables through a constant, and calling those dead
    # would send somebody deleting a setting that works.
    mod = fixture_repo(
        'import os\nNAME = "INDIRECT_SETTING"\nx = os.getenv(NAME)\n',
        "# INDIRECT_SETTING=1\n",
    )
    assert "INDIRECT_SETTING" not in mod.literal_reads(), "the AST scan cannot see this"
    assert mod.unreferenced(mod.declared()) == [], "and the text match can"


def test_a_knob_only_docker_compose_consumes_is_not_reported(fixture_repo):
    mod = fixture_repo(
        "x = 1\n", "# APP_DATA_DIR=./data\n",
        extra={"docker-compose.yml": "services:\n  app:\n    volumes:\n      - ${APP_DATA_DIR}:/data\n"},
    )
    assert mod.unreferenced(mod.declared()) == []


# ── against the real tree ─────────────────────────────────────────────────────


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_CHECKER), *args],
                          cwd=str(_REPO), capture_output=True, text=True, timeout=180)


def test_nothing_declared_in_the_real_file_is_dead():
    proc = _run()
    assert proc.returncode == 0, proc.stdout
    assert "UNREFERENCED 0 (max 0)" in proc.stdout


def test_the_ceiling_matches_what_ci_holds():
    ci = (_REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "check-env-declared.py --max 74" in ci
    assert _run("--max", "74").returncode == 0


def test_the_ratchet_bites():
    proc = _run("--max", "0")
    assert proc.returncode == 1
    assert "only comes down" in proc.stdout


def test_the_exemption_list_cannot_go_stale():
    # An exemption that outlives its call site hides the next variable that
    # needs looking at. Proved by adding one nothing reads.
    original = _CHECKER.read_text(encoding="utf-8")
    try:
        _CHECKER.write_text(
            original.replace(
                'NOT_OURS = {',
                'NOT_OURS = {\n    "NOBODY_READS_THIS": "a name invented by a test",',
                1,
            ),
            encoding="utf-8",
        )
        proc = _run()
        assert proc.returncode == 1
        assert "NOBODY_READS_THIS" in proc.stdout
    finally:
        _CHECKER.write_text(original, encoding="utf-8")
    assert _run().returncode == 0


# ── the entries this row added ────────────────────────────────────────────────


HARDENING = [
    "CARDDAV_BLOCK_PRIVATE_IPS",
    "EMBEDDING_BLOCK_PRIVATE_IPS",
    "IMAGE_BLOCK_PRIVATE_IPS",
    "INTEGRATION_API_BLOCK_PRIVATE_IPS",
    "REMINDER_WEBHOOK_BLOCK_PRIVATE_IPS",
    "PANTHEON_ALLOW_PRIVATE_CALDAV",
]


@pytest.mark.parametrize("name", HARDENING)
def test_the_network_hardening_switches_are_findable(name):
    # `FORBIDDEN.md` Part 2 names the five SSRF validators as controls that
    # never lift. These are the switches that make them *stricter* still, and
    # an operator exposing Pantheon to people they do not trust had no way to
    # discover that they exist.
    text = (_REPO / ".env.example").read_text(encoding="utf-8")
    assert re.search(rf"^\s*#?\s*{name}=", text, re.M), f"{name} is still undocumented"


def test_the_hardening_section_says_which_way_the_defaults_point():
    # Getting this backwards in the docs is worse than silence: an operator who
    # believes private addresses are blocked when they are not will expose
    # something. Law 17 is why they are not.
    text = (_REPO / ".env.example").read_text(encoding="utf-8")
    section = text[text.index("Network hardening"):text.index("Search providers")]
    assert "Law 17" in section
    # The sentence wraps in the file, so match the parts, not the line.
    for phrase in ("loopback", "link-local", "metadata", "never lifts"):
        assert phrase in section, f"the section no longer says {phrase!r}"
    for name in HARDENING[:5]:
        assert f"# {name}=false" in section, f"{name} must show its real default"
    assert "# PANTHEON_ALLOW_PRIVATE_CALDAV=0" in section, (
        "the one that ships tight rather than permissive"
    )


@pytest.mark.parametrize("name", [
    "DATA_BRAVE_API_KEY", "GOOGLE_API_KEY", "GOOGLE_PSE_CX",
    "TAVILY_API_KEY", "SERPER_API_KEY", "SEARXNG_GENERAL_ENGINES",
])
def test_the_search_provider_keys_are_findable(name):
    text = (_REPO / ".env.example").read_text(encoding="utf-8")
    assert re.search(rf"^\s*#?\s*{name}=", text, re.M), f"{name} is still undocumented"


@pytest.mark.parametrize("name", HARDENING + [
    "DATA_BRAVE_API_KEY", "GOOGLE_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY",
])
def test_each_documented_switch_is_one_the_code_actually_reads(name):
    # The failure mode on the other side of this row: documenting a variable
    # that does nothing. Every name added above is checked against a real read.
    mod = _load(_REPO)
    assert name in mod.literal_reads(), f"{name} is documented and nothing reads it"
