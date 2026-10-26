# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1271` — the branches only an anonymous `require_user` reached: gone, or named.

`require_user` answered `""` under auth-off, a loopback bypass or first run
until `D-2026-10-07-02` §2, and answers a person or 401 now, so every
`""`-means-everyone path became unreachable from a request. Measured, each:

  * `document_helpers._owner_session_filter(q, "")` returned every document
    and `document_folder_routes._scope("")` every owner's folders
    (`document_folders.EVERY_OWNER`): no caller hands either `""` — they pass
    what `require_privilege` / `get_current_user` returned — so both branches
    and the sentinel are gone (`Law 13`), and no person matches nothing;
  * `auth_helpers.owner_filter(q, M, "")` was a no-op: its one caller that can
    act for no person is the scheduler, for a task the owner sweep has not
    reached; it now reads the shared rows, as `webhook_routes` does for a token
    with no owner, never another person's private endpoint;
  * `require_privilege`'s `auth_mgr is None` is kept and named: the booted app
    always has a manager (asked here), and its callers are test harnesses that
    mount one router on a bare app; its `except` already fails closed (`B531`);
  * the browser's `viewerIsAdmin()` read `window._isAdmin === false` — the
    auth-off answer — as *admin*; `false` means what it says now;
  * `owner_is_admin_or_single_user` is `owner_is_admin` (`Law 10`).

Driven: the real filters on a real SQLite file, the real route helper, the
real booted app, and `ui_visibility.js` under node.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as cdb
from tests.helpers.gated_app import gated_app_probe

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'b1271.db'}",
                           connect_args={"check_same_thread": False})
    cdb.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        cdb.Document(id="d-ann", title="Ann's", owner="ann", current_content="", version_count=1),
        cdb.Document(id="d-bob", title="Bob's", owner="bob", current_content="", version_count=1),
        cdb.ModelEndpoint(id="e-ann", name="Ann's key", base_url="https://api.example/v1",
                          owner="ann", is_enabled=True),
        cdb.ModelEndpoint(id="e-shared", name="The lab box", base_url="http://10.0.0.5/v1",
                          owner=None, is_enabled=True),
    ])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_no_person_is_handed_no_document(db):
    from routes.document.document_helpers import _owner_session_filter

    q = db.query(cdb.Document)
    assert [d.id for d in _owner_session_filter(q, "").all()] == []
    assert [d.id for d in _owner_session_filter(q, None).all()] == []
    assert [d.id for d in _owner_session_filter(q, "ann").all()] == ["d-ann"]


def test_no_person_is_refused_the_folders():
    from routes.document.document_folder_routes import _scope

    for nobody in ("", None):
        with pytest.raises(HTTPException) as refused:
            _scope(nobody)
        assert refused.value.status_code == 403
    assert _scope("ann") == "ann"


def test_an_owner_filter_for_nobody_reads_the_shared_rows_only(db):
    from src.auth_helpers import owner_filter

    q = db.query(cdb.ModelEndpoint)
    assert sorted(e.id for e in owner_filter(q, cdb.ModelEndpoint, None).all()) == ["e-shared"]
    assert owner_filter(q, cdb.ModelEndpoint, "", include_shared=False).all() == []
    assert sorted(e.id for e in owner_filter(q, cdb.ModelEndpoint, "ann").all()) == [
        "e-ann", "e-shared"]


def test_the_admin_check_is_named_for_what_it_answers():
    import src.tool_security as tool_security

    assert callable(tool_security.owner_is_admin)
    assert not hasattr(tool_security, "owner_is_admin_or_single_user")
    assert tool_security.owner_is_admin(None) is False


def test_the_booted_app_always_has_a_manager_to_ask(tmp_path):
    """So `require_privilege`'s no-manager branch is a harness's, not a request's."""
    result = gated_app_probe(tmp_path, '''
RESULT["has_manager"] = getattr(app_module.app.state, "auth_manager", None) is not None
''')
    assert result["has_manager"] is True


node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@node_only
@pytest.mark.parametrize("window_says, applier_says, expected", [
    ("false", None, False),    # the auth-off reading answered true here
    ("true", None, True),
    ("undefined", None, False),
    ("false", "true", True),
    ("true", "false", False),
])
def test_the_browser_reads_a_no_as_a_no(tmp_path, window_says, applier_says, expected):
    shutil.copy(ROOT / "static" / "js" / "ui_visibility.js", tmp_path / "ui_visibility.js")
    entry = tmp_path / "case.mjs"
    entry.write_text(
        "globalThis.window = globalThis;\n"
        f"globalThis._isAdmin = {window_says};\n"
        "const V = await import('./ui_visibility.js');\n"
        + (f"V.applyToolVisibility({{ isAdmin: {applier_says}, auth: true }}, null);\n"
           if applier_says is not None else "")
        + "console.log(JSON.stringify(V.viewerIsAdmin()));\n")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) is expected
