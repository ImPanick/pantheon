# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2115`. Three library calls the installed versions mark deprecated.

* `core/database.py` took `declarative_base` from `sqlalchemy.ext.declarative`,
  which SQLAlchemy 2.x answers with `MovedIn20Warning` on every boot; the same
  function lives in `sqlalchemy.orm`.
* `routes/skills_routes.py`'s skill update called Pydantic v1's `.dict()`,
  which Pydantic 2 answers with `PydanticDeprecatedSince20` on every edit;
  `.model_dump()` is the same call.
* `routes/workflow/workflow_routes.py`'s `_answers` asked
  `asyncio.iscoroutinefunction`, deprecated in Python 3.14, the image's
  interpreter; `inspect` has the same function.

Each runs in a fresh interpreter with that warning, or that call, made fatal,
so the test fails on the old line and on nothing else.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _python(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                          capture_output=True, text=True, timeout=180)


def test_the_models_base_raises_no_moved_in_20_warning():
    done = _python(
        "import warnings\n"
        "from sqlalchemy.exc import MovedIn20Warning\n"
        "warnings.simplefilter('error', MovedIn20Warning)\n"
        "import core.database\n"
    )
    assert done.returncode == 0, done.stderr[-2000:]


def test_the_skill_update_route_raises_no_pydantic_v1_warning():
    # The route's own test, run with Pydantic's v1-API warning as an error.
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly",
         "-W", "error::pydantic.warnings.PydanticDeprecatedSince20",
         "tests/test_skills_routes_owner_update.py::test_update_skill_route_passes_owner_to_manager"],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout[-3000:]


def test_the_workflow_answer_wrapper_does_not_ask_asyncio():
    done = _python(
        "import asyncio\n"
        "def _gone(*a, **k): raise AssertionError('asyncio.iscoroutinefunction was called')\n"
        "asyncio.iscoroutinefunction = _gone\n"
        "import inspect\n"
        "import routes.workflow.workflow_routes as w\n"
        "async def a(): return 1\n"
        "def s(): return 2\n"
        "assert inspect.iscoroutinefunction(w._answers(a))\n"
        "assert not inspect.iscoroutinefunction(w._answers(s))\n"
        "assert w._answers(s)() == 2\n"
    )
    assert done.returncode == 0, done.stderr[-2000:]
