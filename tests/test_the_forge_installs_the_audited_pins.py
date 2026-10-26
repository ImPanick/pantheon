# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B373` — the Forge's Real-ESRGAN install is the closure CI audits.

The Install button used to run `pip install realesrgan`: an unpinned resolve,
on the user's machine, after CI, of a dependency tree no scanner saw — and the
one path by which a `basicsr` other than the audited 1.4.2 could land in a
deployment. The catalog row (`GET /api/cookbook/packages`) is what the button
installs: `static/js/cookbook.js:_installDep` splits the row's `pip` on
whitespace and shell-quotes each token into `python -m pip install …`. So the
row is driven through the real route here, and its tokens are compared with what
`.pantheon/audit-dependencies.py` hands pip-audit — both read the build script,
so the test fails if either side grows its own copy.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _audit_module():
    spec = importlib.util.spec_from_file_location(
        "audit_dependencies_b373", ROOT / ".pantheon" / "audit-dependencies.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _client():
    pytest.importorskip("starlette.testclient")
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from routes.shell_routes import setup_shell_routes

    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(is_configured=True, is_admin=lambda u: u == "ada")

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = "ada"
        return await call_next(request)

    app.include_router(setup_shell_routes())
    return TestClient(app, raise_server_exceptions=False)


def _realesrgan_row():
    r = _client().get("/api/cookbook/packages")
    assert r.status_code == 200, r.text
    rows = [p for p in r.json()["packages"] if p["name"] == "realesrgan"]
    assert len(rows) == 1, r.json()
    return rows[0]


def test_the_install_button_installs_exactly_what_the_audit_audits():
    row = _realesrgan_row()
    tokens = row["pip"].split()
    assert tokens, row
    assert all("==" in t for t in tokens), (
        f"every token the Install button hands pip must be an exact pin: {tokens}")
    assert sorted(tokens) == sorted(_audit_module().realesrgan_pins())
    assert "basicsr==1.4.2" in tokens  # the accepted-risk register's version
    assert tokens[0].startswith("realesrgan==")


def test_a_pinned_row_does_not_offer_an_update_it_cannot_make():
    """`pip install -U` of an exact pin reinstalls the same pin. The route asks
    this of an *installed* row, so it is asked of the served row directly."""
    from routes.shell_routes import _package_pip_update_status

    status = _package_pip_update_status(_realesrgan_row(), {"dists": {"realesrgan": "0.3.0"}})
    assert status.available is False
    assert "pinned" in status.note.lower()


def test_without_the_build_script_the_row_refuses_to_install_unpinned(monkeypatch, tmp_path):
    from routes import shell_routes
    from src import forge_pins

    monkeypatch.setattr(forge_pins, "WHEEL_SCRIPT", tmp_path / "absent.sh")
    row = shell_routes._realesrgan_package()
    assert row["pip"] == "", row
    assert row["kind"] == "system"
    assert "will not install it unpinned" in row["desc"]
