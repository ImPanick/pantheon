# SPDX-License-Identifier: AGPL-3.0-or-later
"""No address ships pre-filled — armed before there is a hole to guard.

`P16-13`. `P16-12` will build the first legitimate place in this codebase for an
outbound metrics URL, and therefore the first place a well-meant default could
land: a "community stats" endpoint, a "public demo collector", or an SDK whose
constructor already has a hosted URL in it and whose docs call that the
quickstart. The check exists first so the answer is already no.

These tests are about the CHECKER, not the tree — the tree passing proves
nothing on its own. Each one breaks the guard or the tree in a specific way and
asserts the guard notices.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-destinations.py"


def run(cwd=ROOT):
    return subprocess.run([sys.executable, str(cwd / ".pantheon" / "check-destinations.py"),
                           "--quiet"], cwd=cwd, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    dst = tmp_path / "repo"
    (dst / ".pantheon").mkdir(parents=True)
    (dst / "src").mkdir()
    shutil.copy2(CHECKER, dst / ".pantheon" / "check-destinations.py")
    shutil.copy2(ROOT / ".env.example", dst / ".env.example")
    for f in ROOT.glob("docker-compose*.yml"):
        shutil.copy2(f, dst / f.name)
    # A stand-in settings module: the real one imports half the app, and the
    # checker only ever reads DEFAULT_SETTINGS.
    (dst / "src" / "__init__.py").write_text("")
    (dst / "src" / "settings.py").write_text(
        'DEFAULT_SETTINGS = {"issue_tracker_url": "", "search_url": "", "theme": "dark"}\n'
    )
    return dst


def test_the_real_tree_ships_no_destination():
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr


def test_fixture_baseline_passes(repo):
    """Every mutation below is measured against this passing."""
    r = run(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_collector_url_in_env_example_fails(repo):
    with (repo / ".env.example").open("a") as f:
        f.write("\nPANTHEON_TELEMETRY_URL=https://collect.newvendor-metrics.io/v1/traces\n")
    r = run(repo)
    assert r.returncode == 1 and "DESTINATION" in r.stdout


def test_a_default_hidden_inside_a_compose_expansion_fails(repo):
    """Compose defaults are inside `${VAR:-default}`, and must still be seen.

    What makes this bind is not clever `${…}` parsing — an earlier version of
    the checker grew a regex for that, the regex changed no result, and it was
    deleted. It is that compose's `- KEY=value` list-item shape is stripped
    before the assignment match. Mutating that one `lstrip` is what turns this
    test red, which is the honest account of what it covers.
    """
    p = repo / "docker-compose.yml"
    p.write_text(p.read_text() + "\n      - X_OTLP=${X_OTLP:-https://community-stats.demo.dev/v1}\n")
    r = run(repo)
    assert r.returncode == 1, "a default inside ${VAR:-...} slipped through"
    assert "community-stats.demo.dev" in r.stdout


def test_a_truthy_destination_shaped_setting_fails(repo):
    (repo / "src" / "settings.py").write_text(
        'DEFAULT_SETTINGS = {"issue_tracker_url": "https://github.com/x/y/issues"}\n')
    r = run(repo)
    assert r.returncode == 1 and "PREFILLED" in r.stdout


def test_a_url_nested_deep_in_a_default_fails(repo):
    (repo / "src" / "settings.py").write_text(
        'DEFAULT_SETTINGS = {"cfg": {"a": {"b": "https://sneaky-collector.net/ingest"}}}\n')
    r = run(repo)
    assert r.returncode == 1 and "sneaky-collector.net" in r.stdout


def test_a_collector_sdk_host_in_code_fails(repo):
    (repo / "src" / "thing.py").write_text("# dsn https://x@o1.ingest.sentry.io/1\n")
    r = run(repo)
    assert r.returncode == 1 and "COLLECTOR" in r.stdout


# --- the other half: it must not fire on things that are fine --------------

def test_local_and_private_addresses_pass(repo):
    """Over-firing is not safe, it is a guard people learn to route around."""
    with (repo / ".env.example").open("a") as f:
        f.write("\nA_URL=http://localhost:8080\nB_URL=http://192.168.1.50:7000\n"
                "C_URL=http://host.docker.internal:11434/v1\n"
                "D_URL=http://ollama.lan:11434\nE_URL=http://100.83.1.4:8091\n")
    r = run(repo)
    assert r.returncode == 0, r.stdout


def test_documentation_links_in_prose_do_not_fire(repo):
    """`.env.example` legitimately links to Google's OAuth docs and quotes a
    Gmail scope spelled as a URL. Neither is a default; both fired at first."""
    with (repo / ".env.example").open("a") as f:
        f.write("\n# See https://developers.google.com/identity/protocols/oauth2\n"
                "#   Add scopes: https://mail.google.com/ and email.\n")
    r = run(repo)
    assert r.returncode == 0, r.stdout


def test_a_commented_out_assignment_is_still_checked(repo):
    """The narrowing above must not also excuse `# KEY=https://…`, which is
    precisely where a shipped default would hide."""
    with (repo / ".env.example").open("a") as f:
        f.write("\n# PANTHEON_OTLP_ENDPOINT=https://collector.somevendor.io/v1\n")
    r = run(repo)
    assert r.returncode == 1, "a commented-out default was not checked"


def test_tailnet_addresses_count_as_local(repo):
    """100.64.0.0/10 is RFC 6598 — `is_private` reports False for it, and that
    exact mistake was made once already in the Law 16 egress guard."""
    with (repo / ".env.example").open("a") as f:
        f.write("\nNTFY_BASE_URL=http://100.101.102.103:8091\n")
    r = run(repo)
    assert r.returncode == 0, r.stdout


def test_the_allowlist_ships_empty():
    """An entry is a decision, not an exemption, and there are none to make."""
    src = CHECKER.read_text(encoding="utf-8")
    body = src[src.index("ALLOWED = {"):src.index("}", src.index("ALLOWED = {"))]
    assert "://" not in body and "." not in body.replace("# ", "")


# --- `D-2026-10-02-04` §2: one named shipped default, and where it can hide ---

_OFFER = "https://github.com/ImPanick/pantheon"


def _checker_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_check_destinations_named", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_one_named_default_is_the_source_offer_the_code_ships():
    """The exception names a setting, its variable and one exact address —
    never a host — and the address is the one the code actually defaults to,
    imported rather than restated."""
    from src.source_link import DEFAULT_SOURCE_URL
    module = _checker_module()
    assert set(module.SHIPPED_DEFAULTS) == {("source_url", _OFFER),
                                            ("PANTHEON_SOURCE_URL", _OFFER)}
    assert DEFAULT_SOURCE_URL == _OFFER
    assert all("D-2026-10-02-04" in why for why in module.SHIPPED_DEFAULTS.values())
    assert module.ALLOWED == {}, "a host allowlist entry would excuse every key"


def test_the_real_tree_ships_the_offer_where_the_checker_reads_it():
    """Seen twice — the code's default and `.env.example`'s commented line — so
    the checker is reading the default, not passing because it never saw it."""
    r = subprocess.run([sys.executable, str(CHECKER)], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    assert "named defaults 2 (of 2 names)" in r.stdout, r.stdout


def test_the_offer_under_another_name_fails(repo):
    with (repo / ".env.example").open("a") as f:
        f.write(f"\n# PANTHEON_ISSUE_TRACKER_URL={_OFFER}\n")
    r = run(repo)
    assert r.returncode == 1 and "github.com" in r.stdout, r.stdout


def test_another_address_under_the_named_variable_fails(repo):
    with (repo / ".env.example").open("a") as f:
        f.write("\n# PANTHEON_SOURCE_URL=https://collect.newvendor-metrics.io/src\n")
    r = run(repo)
    assert r.returncode == 1 and "newvendor-metrics.io" in r.stdout, r.stdout


def test_a_default_beneath_a_stored_setting_is_read(repo):
    """`env_backed`'s fourth argument is where a filled default sits while
    `DEFAULT_SETTINGS` stays empty — a constant or a literal, it is judged."""
    (repo / "src" / "stats.py").write_text(
        "from src.settings import env_backed\n"
        "STATS = 'https://stats.newvendor-metrics.io/v1'\n"
        "def a(s): return env_backed(s, 'stats_url', 'PANTHEON_STATS_URL', STATS)\n"
        "def b(s): return env_backed(s, 'beacon_url', 'X_BEACON', "
        "default='https://beacon.other-vendor.dev/i')\n")
    r = run(repo)
    assert r.returncode == 1, r.stdout
    assert "stats.newvendor-metrics.io" in r.stdout and "beacon.other-vendor.dev" in r.stdout


def test_the_named_default_beneath_its_own_setting_passes_and_nowhere_else(repo):
    (repo / "src" / "offer.py").write_text(
        "from src.settings import env_backed\n"
        f"OFFER = '{_OFFER}'\n"
        "def a(s): return env_backed(s, 'source_url', 'PANTHEON_SOURCE_URL', OFFER)\n")
    assert run(repo).returncode == 0, run(repo).stdout
    (repo / "src" / "offer.py").write_text(
        "from src.settings import env_backed\n"
        f"OFFER = '{_OFFER}'\n"
        "def a(s): return env_backed(s, 'source_url', 'SOMEONE_ELSES_URL', OFFER)\n")
    r = run(repo)
    assert r.returncode == 1 and "SOMEONE_ELSES_URL" in r.stdout, r.stdout
