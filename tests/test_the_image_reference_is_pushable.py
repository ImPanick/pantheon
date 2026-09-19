# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B853` — the container image has never been pushed, and nothing said so.

The first CI run this repository ever completed built the arm64 image
successfully — 31.7 seconds of layers exported, manifest and config written —
and then died on the push:

    failed to parse ref "ghcr.io/ImPanick/pantheon": invalid reference format:
    repository name (ImPanick/pantheon) must be lowercase

`github.repository` carries the owner's capitalisation exactly as they typed it,
and GHCR refuses a reference with a capital in the repository part. Actions
expressions have no `lower()`, so the workflow-level `env:` could not fix it;
only a shell step writing to `$GITHUB_ENV` can.

**This pairs with `B461`.** That row found that every image ever built on the
Windows deployment host carried CRLF Python source. Nobody could tell, because
the publish step has never once succeeded — the two defects were hiding each
other, and it took a CI run that actually executed to separate them.

The test is about the property, not the spelling: every reference the workflow
constructs must be lowercase by the time it is used, and it must be *derived*
from the repository rather than written down, because a fork of this fork has a
different owner and a literal would send its images here.
"""
import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/docker-publish.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _lowercasing_steps(job: dict) -> list[dict]:
    return [s for s in job.get("steps", [])
            if isinstance(s.get("run"), str)
            and "IMAGE_NAME=" in s["run"]
            and "GITHUB_ENV" in s["run"]]


def test_every_job_that_names_the_image_lowercases_it_first():
    """A job that uses the reference without lowercasing it cannot push."""
    wf = _workflow()
    body = WORKFLOW.read_text(encoding="utf-8")
    for name, job in wf["jobs"].items():
        uses_image = any(
            "IMAGE_NAME" in yaml.safe_dump(step) for step in job.get("steps", []))
        if not uses_image:
            continue
        fixes = _lowercasing_steps(job)
        assert fixes, (
            f"job {name!r} builds a reference out of IMAGE_NAME and never "
            "lowercases it — GHCR refuses a repository name with a capital in "
            "it, which is how this image was never once pushed")
        first_run = next(i for i, s in enumerate(job["steps"])
                         if s in fixes)
        assert first_run == 0, (
            f"job {name!r} lowercases IMAGE_NAME at step {first_run}, after "
            "something has already read it; `$GITHUB_ENV` only affects steps "
            "that come after the one that writes it")
    assert body.count("GITHUB_REPOSITORY,,") >= 2


def test_the_image_name_is_derived_and_not_written_down():
    """A literal owner here sends a fork's images to this repository."""
    body = WORKFLOW.read_text(encoding="utf-8")
    for line in body.splitlines():
        if line.lstrip().startswith("#"):
            continue
        # The rest of the line, not the next token: `${{ github.repository }}`
        # has spaces inside it and `\S+` stops at the first one, which made the
        # first version of this test report the literal `'${{'`.
        m = re.search(r"IMAGE_NAME\s*[:=]\s*(.+)$", line)
        if not m:
            continue
        value = m.group(1).strip()
        assert ("github.repository" in value
                or "GITHUB_REPOSITORY" in value
                or "env.IMAGE_NAME" in value), (
            f"IMAGE_NAME is set to the literal {value!r}; a fork of this fork "
            "would push its images to this repository")


def test_the_registry_is_lowercase_too():
    """The half that was always right, kept right."""
    wf = _workflow()
    registry = wf.get("env", {}).get("REGISTRY", "")
    assert registry and registry == registry.lower(), registry
