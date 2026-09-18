# SPDX-License-Identifier: AGPL-3.0-or-later
import sys
import types
from unittest.mock import MagicMock
from tests.helpers.fresh_import import drop_for_fresh_import


def _load_module(monkeypatch):
    db_stub = types.ModuleType("core.database")
    db_stub.EditorDraft = MagicMock()
    db_stub.SessionLocal = MagicMock()
    monkeypatch.setitem(sys.modules, "core.database", db_stub)
    drop_for_fresh_import(monkeypatch, "routes.editor_draft_routes")

    import routes.editor_draft_routes as mod

    return mod


def test_load_payload_rejects_non_object_json(monkeypatch):
    mod = _load_module(monkeypatch)

    assert mod._load_payload("[]") == {}
    assert mod._load_payload('"draft"') == {}
    assert mod._load_payload("{bad json") == {}
    assert mod._load_payload('{"layers": []}') == {"layers": []}
