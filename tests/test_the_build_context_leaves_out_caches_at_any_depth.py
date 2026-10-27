# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1587` — `.dockerignore`'s caches and outputs are kept out of the build
context wherever they sit, not only at the top of the checkout.

Docker's `*` does not cross a `/`, so `__pycache__/` and `*.pyc` matched the
top level and nothing below it: `B447`'s harness measured 382 untracked
`__pycache__/*.pyc` files from an ordinary checkout going into the context,
and from there into the image (`COPY . .`). The measurement here is the same
one — the real Docker CLI sends its context to a stand-in for the daemon that
keeps it — over a context laid out like a checkout that has been run, with
the repository's own `.dockerignore`.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests.test_the_deploy_manifest_is_what_docker_sends import (  # noqa: F401
    _context_docker_sends,
    needs_docker_cli,
    pd,
)

ROOT = Path(__file__).resolve().parents[1]

#: What running a checkout leaves behind, below the top level.
_LEFT_BEHIND = [
    "src/__pycache__/app.cpython-312.pyc",
    "src/agent_tools/__pycache__/tools.cpython-312.pyc",
    "library/pantheon/__pycache__/x.cpython-312.opt-1.pyc",
    "src/stray.pyc",
    "src/stray.pyo",
    "services/whisper/node_modules/x/index.js",
    "src/pantheon.egg-info/PKG-INFO",
    "services/worker/worker.log",
    "src/run.error.log",
    "src/cache/state.db",
    "services/x/index.sqlite",
    "services/x/index.sqlite3",
]
#: What must still ship: the app, and the editor's `build/` modules that a
#: `**/build/` line would have taken with it.
_SHIPS = [
    "app.py",
    "src/agent_tools/tools.py",
    "static/js/editor/build/toolbar.js",
    "library/ecc/skills/x/SKILL.md",
    "src/build.py",
    "src/dbutil.py",
]


@needs_docker_cli
def test_no_cache_or_output_below_the_top_goes_into_the_context(tmp_path, pd):
    context = tmp_path / "ctx"
    for name in _LEFT_BEHIND + _SHIPS:
        (context / name).parent.mkdir(parents=True, exist_ok=True)
        (context / name).write_text(name)
    shutil.copyfile(ROOT / ".dockerignore", context / ".dockerignore")
    (context / "Dockerfile").write_text("FROM scratch\nCOPY . /app\n")
    sent = _context_docker_sends(context)
    assert not [p for p in sent if "__pycache__" in p.split("/")], sorted(sent)
    assert sorted(set(_LEFT_BEHIND) & sent) == [], "these went into the image"
    assert sorted(set(_SHIPS) - sent) == [], "these did not"
    # The deploy's own reading of the file agrees with Docker's, file by file.
    patterns = pd.read_dockerignore(context)
    for name in _LEFT_BEHIND + _SHIPS:
        assert pd.dockerignored(name, patterns) == (name not in sent), name


def test_the_rules_keep_caches_out_at_any_depth_without_docker(pd):
    """The same answer from the deploy's reading of the file, so a machine with
    no Docker CLI still runs the regression."""
    patterns = pd.read_dockerignore()
    for name in _LEFT_BEHIND:
        assert pd.dockerignored(name, patterns), f"{name} goes into the image"
    for name in _SHIPS:
        assert not pd.dockerignored(name, patterns), f"{name} is left out of the image"


@needs_docker_cli
def test_this_checkout_sends_no_pycache(tmp_path):
    """`Verify:` no `__pycache__` path in the context the CLI sends for this
    checkout, as it is (it has been run; its tests import its modules)."""
    left = []
    for here, dirs, _ in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in {"venv", ".venv", ".git", "node_modules"}]
        left += [here for d in dirs if d == "__pycache__"]
    if not left:
        pytest.skip("this checkout has no __pycache__ to leave out")
    sent = _context_docker_sends(ROOT)
    assert not [p for p in sent if "__pycache__" in p.split("/")][:5]
