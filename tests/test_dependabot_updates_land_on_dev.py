# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2210` — Dependabot's pull requests go where they can merge, and nothing
that holds a dependency is outside every watcher.

The owner, 2026-11-24: *"Need all dependencies at the newest version and the
platform made compatible with current and future updates."* Dependabot is the
"future updates" half, and on that day it was answering into a branch nobody
merges into: every entry in `.github/dependabot.yml` named no `target-branch`,
so each update opened against the default branch, `main`, while work lands on
`dev`. Eight such pull requests (#63-#68, #92, #93) were open and stranded.

Three rules:

  1. every update entry names `target-branch: dev`;
  2. every tracked directory holding a manifest Dependabot can read — a
     Dockerfile (by any of its spellings), a compose file, an npm
     `package.json` with dependencies, a pinned `requirements*.txt` — has an
     entry of that ecosystem for that directory, unless the reason it cannot
     is written in `UNWATCHABLE` below;
  3. the vendored libraries under `static/lib/`, which no ecosystem reads, have
     their own weekly watcher: `vendored-freshness.yml` runs on a schedule and
     runs the script that fails on a library behind upstream.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
FRESHNESS = ROOT / ".github" / "workflows" / "vendored-freshness.yml"

# A directory whose manifest Dependabot cannot move, and why. Each is a fact
# about the manifest, so the day it stops being true the entry is wrong and the
# rule should be re-run by deleting the line.
UNWATCHABLE = {
    # `FROM python@sha256:…` with no tag: Dependabot's docker updater needs a
    # tag to compare, and a bare digest has none to move to.
    ("docker", "/workstation/native_android"):
        "Dockerfile.radio names its base by digest alone",
}


def _entries() -> list[dict]:
    return yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))["updates"]


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def _dir(path: str) -> str:
    parent = str(Path(path).parent)
    return "/" if parent == "." else "/" + parent


def _needed() -> set[tuple[str, str]]:
    """`(ecosystem, directory)` for every tracked manifest Dependabot reads."""
    needed = set()
    for path in _tracked():
        name = Path(path).name
        if path.startswith(("tests/", "static/lib/", "website/")):
            continue
        if re.search(r"dockerfile|containerfile", name, re.I):
            needed.add(("docker", _dir(path)))
        elif re.fullmatch(r"docker-compose[^/]*\.ya?ml|compose\.ya?ml", name):
            needed.add(("docker-compose", _dir(path)))
        elif name == "package.json":
            manifest = json.loads((ROOT / path).read_text(encoding="utf-8"))
            if manifest.get("dependencies") or manifest.get("devDependencies"):
                needed.add(("npm", _dir(path)))
        elif re.fullmatch(r"requirements[^/]*\.txt", name):
            needed.add(("pip", _dir(path)))
    return needed


def test_every_update_lands_on_dev():
    """Rule 1. `main` takes releases from `dev` and nothing else, so an update
    opened against it has no path to land."""
    wrong = [f"{e['package-ecosystem']} {e['directory']}: "
             f"target-branch={e.get('target-branch')!r}"
             for e in _entries() if e.get("target-branch") != "dev"]
    assert _entries(), "dependabot.yml lists no updates"
    assert not wrong, "these Dependabot entries do not target dev:\n" + "\n".join(wrong)


def test_every_manifest_directory_has_a_watcher():
    """Rule 2. A manifest in a directory no entry names is a dependency that
    never moves — the shape `B320` found for pip and this generalises."""
    have = {(e["package-ecosystem"], e["directory"]) for e in _entries()}
    missing = sorted(_needed() - have - set(UNWATCHABLE))
    assert not missing, (
        "manifests Dependabot is not watching (add an entry with target-branch: "
        f"dev, or say in UNWATCHABLE why it cannot): {missing}")


def test_an_unwatchable_reason_is_still_true():
    """`UNWATCHABLE` is an excuse written beside its fact; when the fact moves,
    the excuse must go so rule 2 applies again."""
    radio = (ROOT / "workstation" / "native_android" / "Dockerfile.radio").read_text()
    first = next(line for line in radio.splitlines() if line.startswith("FROM "))
    assert re.match(r"FROM [^:\s]+@sha256:", first), (
        "Dockerfile.radio's base has a tag now — drop its UNWATCHABLE line and "
        "add a docker entry for /workstation/native_android")


def test_the_vendored_libraries_have_a_weekly_watcher():
    """Rule 3. No Dependabot ecosystem reads `static/lib/`; this workflow is the
    only thing that notices a vendored library falling behind."""
    wf = yaml.safe_load(FRESHNESS.read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)  # PyYAML reads a bare `on:` as True
    assert on.get("schedule"), "vendored-freshness.yml no longer runs on a schedule"
    steps = [s.get("run", "") for job in wf["jobs"].values() for s in job["steps"]]
    assert any("vendored-freshness.py" in run for run in steps), steps


def test_the_scheduled_freshness_run_reads_dev():
    """A schedule always runs from the default branch, `main`, which holds the
    last release. The bumps land on `dev`, so a watcher reading `main` stays red
    for a week after the fix has landed and teaches people to ignore it."""
    text = FRESHNESS.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    checkout = next(s for job in wf["jobs"].values() for s in job["steps"]
                    if str(s.get("uses", "")).startswith("actions/checkout@"))
    ref = str((checkout.get("with") or {}).get("ref", ""))
    assert "schedule" in ref and "'dev'" in ref, (
        f"the scheduled run checks out the default branch, not dev: ref={ref!r}")
