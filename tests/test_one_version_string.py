# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B450` — one version string, and it is this project's.

`APP_VERSION` read `"1.0.3"` from the fork baseline until 2026-09-17. That number
is **Odysseus's**: `3f2ad23` ("chore(release): align dev version with 1.0.3",
cherry-picked from upstream `e71f8ce`) moved it from `1.0.2` two days after the
fork point, and nothing in this repository ever touched it again. Six surfaces
report it — `/api/version`, `/api/readiness`, the `pantheon_build_info` metric,
the diagnostic bundle, OTLP's `service.version` and `docker-publish.yml`'s image
tag — so a Pantheon 619 tracked rows past the fork answered *which version are
you* with the number of an upstream release it has nothing to do with. That is
not a missing answer, it is a wrong one, which is worse: nobody asks twice.

These tests hold two properties.

**There were already two, and they disagreed.** `scripts/_lib/cli.py:82` carries
`VERSION = "0.1.0"  # bumped centrally; every pantheon-* CLI reports this`, and
**twenty `scripts/pantheon-*` executables** print it through `common_parser`'s
`--version`. So `pantheon-memory --version` said `0.1.0` — this project's own
line — while `GET /api/version` said `1.0.3` — Odysseus's. One product, two
version strings, two answers, and the one nobody had noticed was the right one.
`Law 14` says find the existing one and extend it rather than build a third, so
`APP_VERSION` was aligned **to the CLI's number** rather than to a number
somebody picked. These tests pin the two together and name any third.

**Every reporter reads that string.** The reporters are driven, not read:
`_collect_build` really emits the metric, `collect_environment` really builds the
bundle's environment block, and the workflow's extraction pipeline is really run
by a shell. `Law 20` — a test that greps a file is testing the file.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Odysseus's number, spelled out so the reason this test exists survives the
# next person who wonders why a literal is pinned here.
UPSTREAM_VERSION = "1.0.3"


def _app_version() -> str:
    from src.constants import APP_VERSION
    return APP_VERSION


def test_the_version_is_not_upstreams():
    """Fails on the tree as it stood: `APP_VERSION` was exactly this."""
    assert _app_version() != UPSTREAM_VERSION, (
        "APP_VERSION is Odysseus's 1.0.3 again — a fork that reports the "
        "upstream release number answers /api/version with somebody else's "
        "identity. See CHANGELOG.md § Versions."
    )


def test_the_version_is_a_release_number_this_project_can_tag():
    v = _app_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+", v), f"not MAJOR.MINOR.PATCH: {v!r}"


def test_the_backward_compatible_shim_resolves_to_the_same_object():
    """`core.constants` is a re-export. If it ever forks again it lags, which is
    what its own docstring says happened at `APP_VERSION 0.9.1`."""
    from core.constants import APP_VERSION as shim
    assert shim == _app_version()


def test_the_metrics_surface_reports_the_constant():
    """Driven through the real collector, not read out of the source."""
    from src.metrics_export import _Out, _collect_build
    out = _Out()
    _collect_build(out)
    body = out.render() if hasattr(out, "render") else str(out.__dict__)
    assert f'version="{_app_version()}"' in body, body[-400:]


def test_the_diagnostic_bundle_reports_the_constant():
    from src.diagnostic_bundle import collect_environment
    assert collect_environment()["pantheon"] == _app_version()


def test_the_publish_workflow_extracts_the_same_string():
    """`docker-publish.yml` tags the image with whatever this pipeline prints.

    Run it, rather than asserting that the file contains a pattern: the failure
    this guards against is a comment or a second assignment changing what
    `head -1` picks, and only running it can see that.
    """
    workflow = (ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(encoding="utf-8")
    m = re.search(r"\$\((grep -E '\^APP_VERSION'.*?)\)\s*$", workflow, re.M)
    assert m, "docker-publish.yml no longer extracts APP_VERSION — update this test"
    proc = subprocess.run(["bash", "-c", m.group(1)], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == _app_version(), (
        f"the workflow would tag the image {proc.stdout.strip()!r} while the app "
        f"reports {_app_version()!r}"
    )


# --- the two declarations, and the ratchet ---------------------------------

# The application's own version, in the two places that report it to a person.
APP_DECL = "src/constants.py"          # the HTTP surface, the metric, the image tag
CLI_DECL = "scripts/_lib/cli.py"       # `pantheon-* --version`, via common_parser

# A version that is deliberately NOT this application's. Each of these declares
# the version of an artefact it fetches, and `.pantheon/check-vendored-versions.py`
# is the checker that owns those numbers. Named rather than pattern-excluded: an
# exemption nobody can enumerate is an exemption that grows.
VENDOR_DECLS = {
    "scripts/fetch-pyodide.py",        # the Pyodide release to download
    "scripts/fetch-swagger-ui.py",     # the Swagger UI release to download
}

_SKIP_DIRS = (
    "static/lib/", "library/", "licenses/", "node_modules/", "docs/",
    ".pantheon/", "tests/", "data/",
)
# `Law 20` — strip comments before asserting on source text, or a note *about*
# the old version reads as a second declaration of it.
_PY_COMMENT = re.compile(r"(?m)^\s*#.*$")
_DECL = re.compile(r"""(?mx)
    ^ \s*
    (?: APP_VERSION | __version__ | VERSION )
    \s* [:=] \s* ["']\d+\.\d+""")
_VALUE = re.compile(r"""(?mx)
    ^ \s* (?: APP_VERSION | VERSION ) \s* = \s* ["'] (?P<v> [^"']+ ) ["']""")


def _tracked(*globs: str) -> list[str]:
    out = subprocess.run(["git", "ls-files", *globs], cwd=str(ROOT),
                         capture_output=True, text=True)
    return [f for f in out.stdout.split()
            if f and not any(f.startswith(d) for d in _SKIP_DIRS)]


def _declared_in(rel: str) -> str:
    src = _PY_COMMENT.sub("", (ROOT / rel).read_text(encoding="utf-8"))
    m = _VALUE.search(src)
    assert m, f"{rel} no longer declares a version"
    return m.group("v")


def test_the_cli_and_the_http_surface_report_the_same_version():
    """Fails on the tree as it stood — `0.1.0` against `1.0.3`.

    Twenty `scripts/pantheon-*` executables print `cli.VERSION` through
    `common_parser`'s `--version`. A product that answers its own version two
    ways has no version, and the answer a person is most likely to quote is
    whichever one they asked first.
    """
    assert _declared_in(CLI_DECL) == _app_version(), (
        f"`pantheon-* --version` says {_declared_in(CLI_DECL)!r} and "
        f"`GET /api/version` says {_app_version()!r}. One product, one number "
        f"— bump both or neither (`Law 14`)."
    )


def test_no_third_module_declares_a_version():
    hits = [rel for rel in _tracked("*.py")
            if _DECL.search(_PY_COMMENT.sub(
                "", (ROOT / rel).read_text(encoding="utf-8", errors="replace")))]
    expected = sorted({APP_DECL, CLI_DECL} | VENDOR_DECLS)
    assert sorted(hits) == expected, (
        f"the version declarations moved (`Law 14`): {sorted(hits)} against "
        f"{expected}. Two of these are the application's and are pinned to each "
        f"other; the rest declare a vendored artefact and belong to "
        f"check-vendored-versions.py. A third application version is the defect."
    )


@pytest.mark.parametrize("rel", ["pyproject.toml", "package.json"])
def test_the_packaging_files_declare_no_version_of_their_own(rel):
    """Both are places a version is habitually added, and both would become a
    second source the moment one is. `pyproject.toml` carries a comment saying
    so; this is what makes the comment true."""
    src = (ROOT / rel).read_text(encoding="utf-8")
    if rel.endswith(".toml"):
        src = _PY_COMMENT.sub("", src)
        assert not re.search(r"(?m)^\s*version\s*=\s*[\"']\d", src), src
    else:
        import json
        assert "version" not in json.loads(src)
