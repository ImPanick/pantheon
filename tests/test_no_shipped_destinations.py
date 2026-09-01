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
