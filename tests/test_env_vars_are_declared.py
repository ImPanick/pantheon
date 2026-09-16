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

`B20` adds a third, and it is the gap both of the above leave open: a variable
can be declared, forwarded by compose, explained in the docs AND read by a line
that cannot execute. Both directions above said yes about
`PANTHEON_TASK_CONCURRENCY_CAP` for the whole time it was dead code.

* **unreachable** — read beneath a settings key whose shipped default is truthy
  (`H06`), or left off `env_backed` beside siblings that use it (`H07`). Held
  at **zero** in both halves, and zero today: these are ratchets against the
  reintroduction of two defects that have each already shipped once.
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
    module.SETTINGS_SOURCE = root / "src" / "settings.py"
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
    """`B98` took this from 74 to 71. It stood at 74 while the real count was
    72, and documenting `PANTHEON_SINGLE_USER` in the switches block took it to
    71 — three names of slack is three undocumented variables a change could add
    with nothing saying so. The number is read out of the checker rather than
    written twice here, so the ratchet cannot be lowered in one file only."""
    import re
    ci = (_REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    match = re.search(r"check-env-declared\.py --max (\d+)", ci)
    assert match, "CI must pin the ceiling explicitly"
    ceiling = int(match.group(1))
    assert _run("--max", str(ceiling)).returncode == 0
    assert f"UNDECLARED {ceiling} (max {ceiling})" in _run().stdout, (
        "the ceiling must equal the real count, not sit above it")


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


# ── `B20`: the third direction — can the variable do anything once read? ─────
#
# `H06` and `H07` are the two ways a declared, forwarded, documented variable
# still does nothing. Neither of the directions above can see either: the first
# asks whether `.env.example` mentions the name, the second whether anything in
# the tree mentions it. Both said yes about `PANTHEON_TASK_CONCURRENCY_CAP`
# while it was dead code on every install this product has ever had.


def _settings(**defaults) -> str:
    body = ",\n    ".join(f"{k!r}: {v!r}" for k, v in defaults.items())
    return f"DEFAULT_SETTINGS = {{\n    {body},\n}}\n"


def test_an_env_read_beneath_a_truthy_shipped_default_is_reported(fixture_repo):
    # `H06` in miniature: `get_setting` merges DEFAULT_SETTINGS on every read,
    # so it cannot return None, so the `or` never evaluates its right-hand side.
    mod = fixture_repo(
        'import os\n'
        'from src.settings import get_setting\n'
        'def cap():\n'
        '    return get_setting("task_concurrency_cap", None) or os.getenv("PANTHEON_TASK_CONCURRENCY_CAP")\n',
        "PANTHEON_TASK_CONCURRENCY_CAP=8\n",
        extra={"src/settings.py": _settings(task_concurrency_cap=1)},
    )
    found = mod.unreachable(mod.shipped_defaults())
    assert len(found) == 1, found
    assert "PANTHEON_TASK_CONCURRENCY_CAP" in found[0]
    assert "cannot run" in found[0]


def test_the_same_read_beneath_a_falsy_default_is_not_reported(fixture_repo):
    # The distinction the whole rule turns on, and the reason six other pairs in
    # this tree are correct as written. `github_token` ships `""`, so the `or`
    # falls through exactly as the author intended.
    mod = fixture_repo(
        'import os\n'
        'from src.settings import get_setting\n'
        'def tok():\n'
        '    return get_setting("github_token", "") or os.getenv("PANTHEON_GITHUB_TOKEN")\n',
        "PANTHEON_GITHUB_TOKEN=x\n",
        extra={"src/settings.py": _settings(github_token="")},
    )
    assert mod.unreachable(mod.shipped_defaults()) == []


def test_asking_setting_is_explicit_clears_the_finding(fixture_repo):
    # `H06`'s actual fix. The default is still truthy; what changed is that the
    # scope now asks whether the operator chose the value instead of assuming a
    # non-None answer means they did.
    mod = fixture_repo(
        'import os\n'
        'from src.settings import get_setting, setting_is_explicit\n'
        'def cap():\n'
        '    if setting_is_explicit("task_concurrency_cap"):\n'
        '        return get_setting("task_concurrency_cap", None)\n'
        '    return os.getenv("PANTHEON_TASK_CONCURRENCY_CAP")\n',
        "PANTHEON_TASK_CONCURRENCY_CAP=8\n",
        extra={"src/settings.py": _settings(task_concurrency_cap=1)},
    )
    assert mod.unreachable(mod.shipped_defaults()) == []


def test_the_rule_resolves_the_constant_the_real_defect_was_spelled_with(fixture_repo):
    # `src/task_scheduler.py` reads `os.getenv(TASK_CONCURRENCY_CAP_ENV)`. A rule
    # built on `literal_reads` — which is deliberately blind to that — would not
    # have caught the one defect it exists for.
    mod = fixture_repo(
        'import os\n'
        'from src.settings import get_setting\n'
        'CAP_ENV = "PANTHEON_TASK_CONCURRENCY_CAP"\n'
        'def cap():\n'
        '    return get_setting("task_concurrency_cap", None) or os.getenv(CAP_ENV)\n',
        "PANTHEON_TASK_CONCURRENCY_CAP=8\n",
        extra={"src/settings.py": _settings(task_concurrency_cap=1)},
    )
    assert "PANTHEON_TASK_CONCURRENCY_CAP" not in mod.literal_reads(), (
        "precondition: the UNDECLARED scan cannot see this spelling"
    )
    assert len(mod.unreachable(mod.shipped_defaults())) == 1


def test_the_undeclared_ratchet_does_not_move_because_the_new_rule_sees_more(fixture_repo):
    # `Law 1`. The ceiling an operator reads off `ci.yml` is a number about
    # `literal_reads`. Resolving constants for the new rule must not quietly
    # raise it — which is why this is a second walk and not a widening.
    mod = fixture_repo(
        'import os\nNAME = "INDIRECT_SETTING"\nx = os.getenv(NAME)\n',
        "# INDIRECT_SETTING=1\n",
        extra={"src/settings.py": _settings(unrelated=1)},
    )
    assert "INDIRECT_SETTING" not in mod.literal_reads()


def test_a_key_whose_default_is_not_a_literal_is_never_flagged(fixture_repo):
    # Under-reporting is the right direction for a hard rule: a checker that
    # guessed at a value it cannot evaluate would fail a build over its guess.
    #
    # `B90` made this a sentinel rather than `None`. A literal `None` in
    # DEFAULT_SETTINGS became meaningful — it is the tri-state a stored `False`
    # needs to mean *no* — so "ships None" and "could not be read" stopped being
    # the same fact and this rule needed to tell them apart. The sentinel is
    # deliberately NOT falsy: it was written falsy first and a mutation removing
    # the explicit guard survived, because the guard was resting on `__bool__`
    # rather than on anything the code said.
    mod = fixture_repo(
        'import os\n'
        'from src.settings import get_setting\n'
        'def f():\n'
        '    return get_setting("computed", None) or os.getenv("PANTHEON_COMPUTED")\n',
        "PANTHEON_COMPUTED=1\n",
        extra={"src/settings.py": 'DEFAULT_SETTINGS = {\n    "computed": build_it(),\n}\n'},
    )
    assert mod.shipped_defaults() == {"computed": mod.UNREADABLE}
    assert mod.shipped_defaults()["computed"] is not None, (
        "unknown is not None, or the tri-state rule fires on every computed default"
    )
    assert mod.unreachable(mod.shipped_defaults()) == []


def test_one_field_left_off_env_backed_beside_its_siblings_is_reported(fixture_repo):
    # `H07` converted ten fields of the legacy mail config and left the
    # eleventh, so `IMAP_STARTTLS` was honoured by one resolver and ignored by
    # the other on the same host.
    mod = fixture_repo(
        'from src.settings import env_backed\n'
        'def cfg(settings):\n'
        '    return {\n'
        '        "imap_host": env_backed(settings, "imap_host", "IMAP_HOST"),\n'
        '        "imap_user": env_backed(settings, "imap_user", "IMAP_USER"),\n'
        '        "imap_starttls": settings.get("imap_starttls", True),\n'
        '    }\n',
        "IMAP_HOST=x\n",
        extra={"src/settings.py": _settings(unrelated=1)},
    )
    found = mod.mixed_layers()
    assert len(found) == 1, found
    assert "imap_starttls" in found[0]
    assert "2 siblings" in found[0]


def test_a_dict_where_every_field_is_env_backed_is_not_reported(fixture_repo):
    mod = fixture_repo(
        'from src.settings import env_backed\n'
        'def cfg(settings):\n'
        '    return {\n'
        '        "imap_host": env_backed(settings, "imap_host", "IMAP_HOST"),\n'
        '        "imap_user": env_backed(settings, "imap_user", "IMAP_USER"),\n'
        '    }\n',
        "IMAP_HOST=x\n",
        extra={"src/settings.py": _settings(unrelated=1)},
    )
    assert mod.mixed_layers() == []


def test_the_rule_follows_the_one_line_alias_the_real_call_site_uses(fixture_repo):
    # `routes/email_helpers.py` spells it `_v = lambda k, e, d="": env_backed(...)`.
    # Without following that, the ten converted fields look like no fields at
    # all and the eleventh looks like the only one there is.
    mod = fixture_repo(
        'from src.settings import env_backed\n'
        'def cfg(settings):\n'
        '    _v = lambda k, e, d="": env_backed(settings, k, e, d)\n'
        '    return {\n'
        '        "imap_host": _v("imap_host", "IMAP_HOST"),\n'
        '        "imap_port": int(_v("imap_port", "IMAP_PORT", "993")),\n'
        '        "imap_starttls": settings.get("imap_starttls", True),\n'
        '    }\n',
        "IMAP_HOST=x\n",
        extra={"src/settings.py": _settings(unrelated=1)},
    )
    found = mod.mixed_layers()
    assert len(found) == 1 and "imap_starttls" in found[0], found


def test_a_dict_with_no_env_backed_field_at_all_is_not_reported(fixture_repo):
    # Most dicts in this tree read settings and have no environment layer by
    # design. The finding is a sibling left behind, not a settings read.
    mod = fixture_repo(
        'def cfg(settings):\n'
        '    return {"a": settings.get("a"), "b": settings.get("b", True)}\n',
        "# NOTHING=1\n",
        extra={"src/settings.py": _settings(unrelated=1)},
    )
    assert mod.mixed_layers() == []


def test_both_new_rules_are_clean_against_the_real_tree():
    proc = _run()
    assert proc.returncode == 0, proc.stdout
    assert "UNREACHABLE 0 (max 0)" in proc.stdout
    assert "MIXED 0 (max 0)" in proc.stdout


def test_a_key_read_twice_in_one_dict_is_not_reported_for_its_plain_read(fixture_repo):
    # A field that already goes through `env_backed` somewhere in the dict has
    # its environment layer; a second, plain read of the same key is a different
    # question being asked (which layer answered?), not a field left behind.
    # `routes/contacts/contacts_routes._carddav_sources` does exactly this.
    mod = fixture_repo(
        'from src.settings import env_backed\n'
        'def cfg(settings):\n'
        '    return {\n'
        '        "value": env_backed(settings, "imap_host", "IMAP_HOST"),\n'
        '        "source": "settings" if settings.get("imap_host") else "environment",\n'
        '    }\n',
        "IMAP_HOST=x\n",
        extra={"src/settings.py": _settings(unrelated=1)},
    )
    assert mod.mixed_layers() == []


def _fixture_that_only_fails_on_the_rule_under_test(fixture_repo, python, env_example, defaults):
    """`main()` runs every rule. A fixture that trips a second one passes for the
    wrong reason — so this reads every NOT_OURS name, which is what the
    stale-exemption rule needs, and declares exactly what it reads."""
    exemptions = _load(_REPO).NOT_OURS
    preamble = "import os\n" + "".join(f"os.getenv({n!r})\n" for n in exemptions)
    mod = fixture_repo(preamble + python, env_example,
                       extra={"src/settings.py": defaults})
    assert sorted(set(mod.NOT_OURS) - set(mod.literal_reads())) == [], (
        "the fixture must satisfy the stale rule, or it masks the one under test"
    )
    assert mod.unreferenced(mod.declared()) == []
    return mod


def test_an_unreachable_env_layer_fails_the_run_and_not_only_the_report(
        fixture_repo, monkeypatch, capsys):
    # `failed = False` on this branch leaves the finding printed and the exit
    # code green. A checker nobody's CI can fail is a comment.
    mod = _fixture_that_only_fails_on_the_rule_under_test(
        fixture_repo,
        'from src.settings import get_setting\n'
        'def cap():\n'
        '    return get_setting("task_concurrency_cap", None) or os.getenv("PANTHEON_TASK_CONCURRENCY_CAP")\n',
        "PANTHEON_TASK_CONCURRENCY_CAP=8\n",
        _settings(task_concurrency_cap=1),
    )
    monkeypatch.setattr(sys, "argv", ["check-env-declared.py"])
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "UNREACHABLE 1 (max 0)" in out
    assert "PANTHEON_TASK_CONCURRENCY_CAP" in out


def test_a_field_left_off_env_backed_fails_the_run_and_not_only_the_report(
        fixture_repo, monkeypatch, capsys):
    mod = _fixture_that_only_fails_on_the_rule_under_test(
        fixture_repo,
        'from src.settings import env_backed\n'
        'def cfg(settings):\n'
        '    return {\n'
        '        "imap_host": env_backed(settings, "imap_host", "IMAP_HOST"),\n'
        '        "imap_starttls": settings.get("imap_starttls", True),\n'
        '    }\n',
        "IMAP_HOST=x\n",
        _settings(unrelated=1),
    )
    monkeypatch.setattr(sys, "argv", ["check-env-declared.py"])
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "MIXED 1 (max 0)" in out
    assert "imap_starttls" in out


# ── `B91` / `B90`: the spelling rule, and the tri-state it protects ──────────
#
# `B91` counted 38 environment booleans judged by 10 incompatible rules, so
# `PANTHEON_STARTUP_WARMUPS=1` was on while `IMAP_STARTTLS=1` was off in one
# process. The rule went inside this checker rather than into a nineteenth file
# for the same reason `B20`'s did: this walker already exists (`Law 14`), and
# "can this variable do anything?" and "does this variable mean what the next
# module thinks it means?" are one operator question from two sides.


def test_an_inline_truthiness_comparison_on_an_env_read_is_reported(fixture_repo):
    mod = fixture_repo(
        'import os\n'
        'def warm():\n'
        '    return os.getenv("PANTHEON_STARTUP_WARMUPS", "").lower() == "true"\n',
        "PANTHEON_STARTUP_WARMUPS=1\n",
    )
    found = mod.spellings()
    assert len(found) == 1, found
    assert "PANTHEON_STARTUP_WARMUPS" in found[0]


@pytest.mark.parametrize("comparison", [
    '.lower() == "true"',
    '.lower() in ("1", "true", "yes")',
    '.lower() in ("1", "true", "yes", "on")',
    '.lower() not in ("0", "false", "no")',
    '.lower() not in ("0", "false", "no", "off", "")',
    '!= "0"',
    '== "false"',
])
def test_every_one_of_the_measured_spellings_is_caught(fixture_repo, comparison):
    # These are the real shapes, transcribed from the sites `B91` counted. A
    # rule that caught only the one everybody writes would have left six.
    mod = fixture_repo(
        f'import os\n'
        f'def f():\n'
        f'    return os.getenv("SOME_FLAG", ""){comparison}\n',
        "SOME_FLAG=1\n",
    )
    assert len(mod.spellings()) == 1, comparison


def test_a_comparison_that_is_not_about_truthiness_is_left_alone(fixture_repo):
    # `TERM == "dumb"`, `PANTHEON_SCRIPT_HOST in ("", "localhost")`, a duration,
    # a hostname. The first draft of this rule fired on all of them, which is
    # how a checker becomes noise nobody reads.
    mod = fixture_repo(
        'import os\n'
        'def f():\n'
        '    a = os.environ.get("TERM") == "dumb"\n'
        '    b = os.environ.get("PANTHEON_SCRIPT_HOST", "") in ("", "localhost")\n'
        '    c = os.environ.get("PANTHEON_POLL_EVERY", "") == "1d"\n'
        '    return a, b, c\n',
        "TERM=x\nPANTHEON_SCRIPT_HOST=x\nPANTHEON_POLL_EVERY=x\n",
    )
    assert mod.spellings() == []


def test_a_truthiness_comparison_on_something_that_is_not_the_environment_is_left_alone(
        fixture_repo):
    # 16 of the 33 `.lower() == "true"` sites in this tree parse an HTTP form
    # field, a model-emitted tool argument or a line of skill frontmatter.
    # `B91` counted them in its "50 sites" and they are a different question
    # with a different trust boundary — unifying them would be `Law 14`.
    mod = fixture_repo(
        'def handler(form, body):\n'
        '    a = str(form.get("plan_mode", "")).lower() == "true"\n'
        '    b = str(body.get("shared")).strip().lower() in ("true", "1", "yes")\n'
        '    return a, b\n',
        "",
    )
    assert mod.spellings() == []


def test_a_site_may_keep_its_own_rule_by_saying_why(fixture_repo):
    mod = fixture_repo(
        'import os\n'
        'def bypass():\n'
        '    # env-spelling: widening this turns an auth bypass on for every host\n'
        '    # already carrying LOCALHOST_BYPASS=1, where it does nothing today.\n'
        '    return os.getenv("LOCALHOST_BYPASS", "false").lower() == "true"\n',
        "LOCALHOST_BYPASS=false\n",
    )
    assert mod.spellings() == []
    assert mod.exempt_spellings() and "auth bypass" in mod.exempt_spellings()[0]


def test_the_exemption_is_found_above_a_comment_block_of_any_length(fixture_repo):
    # A fixed lookback window sized to today's longest reason is a trap for
    # tomorrow's. The real holds run to six lines.
    reason = "\n".join(f"    # line {n}" for n in range(12))
    mod = fixture_repo(
        'import os\n'
        'def f():\n'
        '    # env-spelling: held, and the reason is long\n'
        f'{reason}\n'
        '    return os.getenv("SOME_FLAG", "").lower() == "true"\n',
        "SOME_FLAG=1\n",
    )
    assert mod.spellings() == []


def test_the_exemption_does_not_reach_across_real_code(fixture_repo):
    # An exemption that leaks down the file silences sites nobody meant to hold.
    mod = fixture_repo(
        'import os\n'
        'def held():\n'
        '    # env-spelling: this one only\n'
        '    return os.getenv("A_FLAG", "").lower() == "true"\n'
        'def not_held():\n'
        '    return os.getenv("B_FLAG", "").lower() == "true"\n',
        "A_FLAG=1\nB_FLAG=1\n",
    )
    found = mod.spellings()
    assert len(found) == 1 and "B_FLAG" in found[0], found


def test_env_flags_itself_is_not_reported_for_defining_the_vocabulary(fixture_repo):
    mod = fixture_repo(
        "x = 1\n", "",
        extra={"src/env_flags.py":
               'import os\n'
               'def env_flag(name, default=False):\n'
               '    return os.environ.get(name, "").strip().lower() in ("1", "true")\n'},
    )
    assert mod.spellings() == []


def test_calling_the_helper_clears_the_finding(fixture_repo):
    mod = fixture_repo(
        'from src.env_flags import env_flag\n'
        'def warm():\n'
        '    return env_flag("PANTHEON_STARTUP_WARMUPS", False)\n',
        "PANTHEON_STARTUP_WARMUPS=1\n",
    )
    assert mod.spellings() == []


def test_the_helper_does_not_hide_the_variable_from_the_undeclared_scan(fixture_repo):
    # The trap this rule could have set for itself. Adopting `env_flag` at 22
    # sites took `literal_reads` from 143 names to 121 before the scan learned
    # the helper — twelve of them undeclared, so the ratchet would have fallen
    # by hiding variables rather than by documenting them.
    mod = fixture_repo(
        'from src.env_flags import env_flag\n'
        'x = env_flag("WANTED", False)\n',
        "",
    )
    assert "WANTED" in mod.literal_reads()


def test_env_backed_names_its_variable_in_the_third_argument_and_the_scan_reads_it(
        fixture_repo):
    # `H07` moved three CardDAV fields onto `env_backed` and this scan stopped
    # seeing two of them — `CARDDAV_URL` and `CARDDAV_USERNAME` were undeclared
    # and invisible for that whole time. Found while closing `B91`.
    mod = fixture_repo(
        'from src.settings import env_backed, env_backed_flag\n'
        'def cfg(s):\n'
        '    return (env_backed(s, "carddav_url", "CARDDAV_URL"),\n'
        '            env_backed_flag(s, "metrics_enabled", "PANTHEON_METRICS_ENABLED"))\n',
        "",
    )
    assert {"CARDDAV_URL", "PANTHEON_METRICS_ENABLED"} <= set(mod.literal_reads())


def test_an_env_read_beside_a_tri_state_key_is_reported(fixture_repo):
    # `B90` in miniature. `allow_model_download` ships `None` so that a stored
    # `False` can mean *no*; `bool(get_setting(K, False))` flattens that back
    # into the absence it was made distinguishable from, and the `or` beneath it
    # then wins. Measured 2026-09-15: stored `False`, effective `True`.
    mod = fixture_repo(
        'import os\n'
        'from src.settings import get_setting\n'
        'def allowed():\n'
        '    return bool(get_setting("allow_model_download", False)) or bool(\n'
        '        os.environ.get("PANTHEON_ALLOW_MODEL_DOWNLOAD"))\n',
        "PANTHEON_ALLOW_MODEL_DOWNLOAD=0\n",
        extra={"src/settings.py": _settings(allow_model_download=None)},
    )
    found = mod.unreachable(mod.shipped_defaults())
    assert len(found) == 1, found
    assert "env_backed_flag" in found[0], "and it names the tool that answers"


def test_env_backed_flag_clears_the_tri_state_finding(fixture_repo):
    mod = fixture_repo(
        'from src.settings import env_backed_flag, load_settings\n'
        'def allowed():\n'
        '    return env_backed_flag(load_settings(), "allow_model_download",\n'
        '                           "PANTHEON_ALLOW_MODEL_DOWNLOAD")\n',
        "PANTHEON_ALLOW_MODEL_DOWNLOAD=0\n",
        extra={"src/settings.py": _settings(allow_model_download=None)},
    )
    assert mod.unreachable(mod.shipped_defaults()) == []


def test_a_key_the_settings_file_does_not_ship_is_still_never_flagged(fixture_repo):
    # The `None` rule had to be told apart from "no such key", which
    # `defaults.get(key)` also answers `None` for. A sentinel does it; without
    # one, every unknown key would be flagged as tri-state.
    mod = fixture_repo(
        'import os\n'
        'from src.settings import get_setting\n'
        'def f():\n'
        '    return get_setting("not_a_shipped_key", False) or os.getenv("NOT_A_SHIPPED_KEY")\n',
        "NOT_A_SHIPPED_KEY=1\n",
        extra={"src/settings.py": _settings(unrelated=1)},
    )
    assert mod.unreachable(mod.shipped_defaults()) == []


def test_the_spelling_rule_is_clean_against_the_real_tree():
    proc = _run()
    assert proc.returncode == 0, proc.stdout
    assert "SPELLING 0 (max 0," in proc.stdout


def test_every_held_site_in_the_real_tree_states_a_reason():
    mod = _load(_REPO)
    held = mod.exempt_spellings()
    assert held, "the hold list is not empty and the checker can enumerate it"
    for entry in held:
        reason = entry.split(" ", 1)[1]
        assert len(reason) > 30, f"an exemption with no reason is a silenced finding: {entry}"


def test_an_inline_spelling_fails_the_run_and_not_only_the_report(
        fixture_repo, monkeypatch, capsys):
    mod = _fixture_that_only_fails_on_the_rule_under_test(
        fixture_repo,
        'import os\n'
        'def f():\n'
        '    return os.getenv("SOME_FLAG", "").lower() == "true"\n',
        "SOME_FLAG=1\n",
        _settings(unrelated=1),
    )
    monkeypatch.setattr(sys, "argv", ["check-env-declared.py"])
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "SPELLING 1 (max 0" in out
    assert "SOME_FLAG" in out
