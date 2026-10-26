# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B453` — the version answers *which release line*; the build says *which commit*.

`GET /api/version` returned `{"version": "0.2.0"}` and a hundred different
commits returned exactly that, because nothing in the tree carried a commit a
running instance could report: `.git` is not in the image, so the sha has to be
stamped at build time and read at runtime. Now the `Dockerfile` takes it as a
build argument, the publish workflow passes `github.sha`, `pantheon deploy run`
passes the checkout's HEAD, and the app reports it beside the version — `null`
when nothing stamped it. One version string still (`test_one_version_string.py`).

Driven: the real app booted out of process with and without the stamp, the
real `build_commit`, the deploy script's real `cmd_run` against its Docker
stand-in, and the publish workflow and `Dockerfile` read as the build reads them.
"""
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.helpers.gated_app import gated_app_probe
from tests.test_the_deploy_script_fails_when_the_deploy_failed import (  # noqa: F401
    FakeDocker, _clean_probe, _run, pd,
)

ROOT = Path(__file__).resolve().parents[1]
SHA = "0123456789abcdef0123456789abcdef01234567"

_PROBE = r'''
import os
c = TestClient(app_module.app)
RESULT["stamped"] = c.get("/api/version").json()
os.environ.pop("PANTHEON_BUILD_COMMIT", None)
RESULT["unstamped"] = c.get("/api/version").json()
os.environ["PANTHEON_BUILD_COMMIT"] = "main"
RESULT["not_a_commit"] = c.get("/api/version").json()
from src.diagnostic_bundle import collect_environment
os.environ["PANTHEON_BUILD_COMMIT"] = "abc1234"
RESULT["bundle"] = collect_environment().get("pantheon_commit")
'''


@pytest.fixture(scope="module")
def answered(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("commit"), _PROBE,
                           {"PANTHEON_BUILD_COMMIT": SHA.upper()}, accounts=False)


def test_a_stamped_build_reports_its_commit_beside_the_version(answered):
    from src.constants import APP_VERSION
    assert answered["stamped"] == {"version": APP_VERSION, "commit": SHA}


def test_an_unstamped_build_says_so_rather_than_guessing(answered):
    from src.constants import APP_VERSION
    assert answered["unstamped"] == {"version": APP_VERSION, "commit": None}
    # A branch name is not a commit; it reads as unstamped too.
    assert answered["not_a_commit"]["commit"] is None


def test_the_diagnostic_bundle_carries_it(answered):
    assert answered["bundle"] == "abc1234"


def test_the_image_takes_the_commit_as_a_build_argument():
    """The final stage declares it, after the app's code, so a new commit does
    not rebuild the dependency layers."""
    lines = [l.strip() for l in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.strip().startswith("#")]
    final = lines[max(i for i, l in enumerate(lines) if l.startswith("FROM ")):]
    arg = final.index('ARG PANTHEON_BUILD_COMMIT=""')
    env = final.index("ENV PANTHEON_BUILD_COMMIT=${PANTHEON_BUILD_COMMIT}")
    assert final.index("COPY . .") < arg < env


def test_the_published_image_is_stamped_with_the_commit_it_was_built_from():
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(encoding="utf-8"))
    steps = [s for job in flow["jobs"].values() for s in job.get("steps", [])]
    build = next(s for s in steps if "docker/build-push-action" in str(s.get("uses", "")))
    assert "PANTHEON_BUILD_COMMIT=${{ github.sha }}" in build["with"]["build-args"].splitlines()


def test_a_deploy_stamps_its_build_with_the_checkout(pd, monkeypatch):  # noqa: F811
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                          capture_output=True, text=True).stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{40}", head)
    assert pd.checkout_commit(ROOT) == head
    docker = FakeDocker(probe=_clean_probe(), logs="Application startup complete\n")
    try:
        _run(pd, monkeypatch, docker, ["run"])
    except SystemExit:
        pass  # the probe's verdict is not this test's question; the build call is
    build = next(c for c in docker.calls if c[:2] == ["compose", "build"])
    assert build == ["compose", "build", "--build-arg", f"PANTHEON_BUILD_COMMIT={head}", "pantheon"]


def test_no_checkout_builds_unstamped(pd, tmp_path):  # noqa: F811
    assert pd.checkout_commit(tmp_path) == ""
