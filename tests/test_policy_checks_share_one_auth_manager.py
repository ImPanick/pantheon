# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-15`): the policy checks ask the app's `AuthManager`.

Each of five checks built `AuthManager()` per call — `auth.json` and
`sessions.json` read, three migrations run, two INFO lines logged. Measured by
the perf audit on `9560d50`: 91 constructions in a 3.3 s seed, 20 within 14 ms
of one workflow save, while `app.py` already held one.

Now the app registers its manager and the checks ask `shared_auth_manager()`;
with nothing registered (another process, a script) they read the file as
before, and a replaced class or a stubbed `core.auth` (a test's fake) is still
what gets called. Driven:
the checks themselves, with `AuthManager.__init__` counted.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import core.auth as core_auth


@pytest.fixture()
def counted(monkeypatch, tmp_path):
    """A real manager over a temp auth file with one admin and one person, and
    a count of every `AuthManager` built from here on."""
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"users": {
        "ada": {"password_hash": "x", "is_admin": True},
        "bo": {"password_hash": "x", "is_admin": False},
    }}), encoding="utf-8")
    monkeypatch.setattr(core_auth, "DEFAULT_AUTH_PATH", str(path))
    real_init = core_auth.AuthManager.__init__
    built = []

    def init(self, auth_path=str(path)):
        built.append(auth_path)
        real_init(self, auth_path)

    monkeypatch.setattr(core_auth.AuthManager, "__init__", init)
    manager = core_auth.AuthManager(str(path))
    built.clear()
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(core_auth, "_SHARED_AUTH_MANAGER", None)
    # The checks read `core.auth` at call time; make sure it is this module
    # and not a stub another test file left behind.
    import sys
    import core
    monkeypatch.setitem(sys.modules, "core.auth", core_auth)
    monkeypatch.setattr(core, "auth", core_auth, raising=False)
    return manager, built


def _ask_every_check():
    from src.task_action_policy import owner_has_admin_task_privileges
    from src.tool_security import owner_is_admin_or_single_user
    from src.workstation_access import may_use

    answers = []
    for _ in range(5):
        answers.append((owner_has_admin_task_privileges("ada"), owner_has_admin_task_privileges("bo"),
                        owner_is_admin_or_single_user("ada"), owner_is_admin_or_single_user("bo"),
                        may_use("ada")))
    return answers


def test_with_the_apps_manager_registered_no_check_builds_one(counted):
    manager, built = counted
    assert manager.is_configured and manager.is_admin("ada") and not manager.is_admin("bo")
    core_auth.register_shared_auth_manager(manager)
    answers = _ask_every_check()
    assert built == [], f"{len(built)} AuthManager built for {len(answers) * 5} questions"
    assert answers[0][:4] == (True, False, True, False)


def test_the_daily_brief_asks_the_shared_one_too(counted):
    manager, built = counted
    core_auth.register_shared_auth_manager(manager)
    from src.builtin_actions import action_daily_brief
    try:
        asyncio.run(action_daily_brief("ada"))
    except Exception:
        pass    # the brief's own reads may fail on the test database; the count is the point
    assert built == []


def test_with_nothing_registered_each_check_reads_the_file_as_before(counted):
    manager, built = counted
    answers = _ask_every_check()
    assert len(built) >= 20, len(built)
    assert answers[0][:4] == (True, False, True, False)


def test_a_replaced_class_is_what_gets_called(counted, monkeypatch):
    manager, built = counted
    core_auth.register_shared_auth_manager(manager)

    class Fake:
        is_configured = True

        def is_admin(self, name):
            return name == "bo"

    monkeypatch.setattr(core_auth, "AuthManager", lambda *a, **k: Fake())
    from src.task_action_policy import owner_has_admin_task_privileges
    assert owner_has_admin_task_privileges("bo") is True
    assert owner_has_admin_task_privileges("ada") is False


def test_a_stubbed_core_auth_with_only_its_class_still_answers(monkeypatch):
    """Several test files install a `core.auth` carrying nothing but
    `AuthManager`; the checks must ask that, not fail on a name it lacks."""
    import sys
    import types

    stub = types.ModuleType("core.auth")

    class Admin:
        is_configured = True

        def is_admin(self, name):
            return True

    stub.AuthManager = lambda *a, **k: Admin()
    import core
    monkeypatch.setitem(sys.modules, "core.auth", stub)
    monkeypatch.setattr(core, "auth", stub, raising=False)
    from src.task_action_policy import owner_has_admin_task_privileges
    assert owner_has_admin_task_privileges("anyone") is True


def test_the_app_registers_the_manager_it_holds(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update({
        "AUTH_ENABLED": "true", "CHROMADB_CONNECT_TIMEOUT": "0.01", "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9", "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "PANTHEON_DATA_DIR": str(tmp_path), "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(repo), "PYTHON_DOTENV_DISABLED": "1",
    })
    probe = ("import app, core.auth as a; from src.auth_manager_access import shared_auth_manager; "
             "print('RESULT', a._SHARED_AUTH_MANAGER is app.app.state.auth_manager, "
             "shared_auth_manager() is app.app.state.auth_manager)")
    done = subprocess.run([sys.executable, "-c", probe], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=240)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line == "RESULT True True", (line, done.stderr[-3000:])
