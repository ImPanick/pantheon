# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B958`, the owner's call (`D-2026-10-01-01`): the backup leaves out the keys
that re-pair on their own — the workstation token — and keeps the provider API
keys, and says so where the export is offered.

Driven through the real backup router (`GET /api/export`, `POST /api/import`)
on temp settings files, and through `workstation_client.resolve_token` for
"pairs again on its own". The one page check scopes to the card that holds the
export button before it reads a word (`Law 20`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
HAND_SET = "hand-set-token-0123456789"


@pytest.fixture
def store(tmp_path, monkeypatch):
    import src.settings as S

    sp = tmp_path / "settings.json"
    fp = tmp_path / "features.json"
    sp.write_text(json.dumps({
        "workstation_token": HAND_SET,
        "brave_api_key": "brave-key-abc",
        "github_token": "ghp_example",
        "netagent_token": "netagent-raw",
        "default_model_fallbacks": ["m1"],      # retired, kept in a backup
    }), encoding="utf-8")
    fp.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "SETTINGS_FILE", str(sp))
    monkeypatch.setattr(S, "FEATURES_FILE", str(fp))
    S._invalidate_caches()
    yield S
    S._invalidate_caches()


def _client():
    from routes.backup_routes import setup_backup_routes
    from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN

    class _Mgr:
        def load(self, **k): return []
        def load_all_for_update(self): return []
        def load_all(self): return []
        def get_all(self): return {}
        def save(self, *a, **k): return None

    app = FastAPI()
    app.include_router(setup_backup_routes(_Mgr(), _Mgr(), _Mgr()))
    c = TestClient(app)
    c.headers.update({INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN})
    return c


def _export():
    r = _client().get("/api/export")
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers["content-disposition"]
    return json.loads(r.content)


def test_the_export_leaves_out_the_workstation_token(store):
    data = _export()
    assert "workstation_token" not in data["settings"]
    assert HAND_SET not in json.dumps(data)


def test_the_export_keeps_every_key_a_restore_needs(store):
    s = _export()["settings"]
    assert s["brave_api_key"] == "brave-key-abc"
    assert s["github_token"] == "ghp_example"
    assert s["netagent_token"] == "netagent-raw", "the installer keeps only its hash"
    assert s["default_model_fallbacks"] == ["m1"]


def test_an_old_backup_does_not_blank_a_hand_set_token(store):
    """Every export before this change carried `"workstation_token": ""` — the
    merged default — and the setting outranks the pairing volume."""
    r = _client().post("/api/import", json={"settings": {
        "workstation_token": "", "brave_api_key": "restored"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert store.get_setting("workstation_token") == HAND_SET
    assert store.get_setting("brave_api_key") == "restored"
    assert body["left_alone"] == ["workstation_token"]
    assert "the workstation's pairing key" in body["message"]
    assert "pairs again on its own" in body["message"]


def test_an_old_backup_does_not_replace_the_token_with_its_own(store):
    r = _client().post("/api/import", json={"settings": {"workstation_token": "from-2026-09"}})
    assert r.status_code == 200
    assert store.get_setting("workstation_token") == HAND_SET


def test_a_new_backup_restores_without_the_key_and_says_nothing_about_it(store):
    data = _export()
    r = _client().post("/api/import", json={"settings": data["settings"]})
    assert r.status_code == 200
    body = r.json()
    assert body["left_alone"] == []
    assert body["message"] == "Imported: settings"
    assert store.get_setting("workstation_token") == HAND_SET


def test_on_a_fresh_install_the_token_comes_back_from_the_pairing_volume(store, tmp_path, monkeypatch):
    """"Re-pairs on its own", driven: a restore onto an install with no saved
    token leaves the setting empty, and the client reads the daemon's token."""
    from workstation import protocol as P
    from src import workstation_client as wc

    data = _export()
    Path(store.SETTINGS_FILE).write_text("{}", encoding="utf-8")
    store._invalidate_caches()
    pairing = tmp_path / "pairing"
    pairing.mkdir()
    (pairing / P.TOKEN_FILENAME).write_text("daemon-wrote-this\n", encoding="utf-8")
    monkeypatch.setenv(P.PAIRING_DIR_ENV, str(pairing))
    monkeypatch.delenv(P.TOKEN_ENV, raising=False)

    assert _client().post("/api/import", json={"settings": data["settings"]}).status_code == 200
    assert store.get_setting("brave_api_key") == "brave-key-abc"
    assert wc.resolve_token() == ("daemon-wrote-this", wc.SOURCE_PAIRING)


def test_only_a_key_that_pairs_again_is_withheld(store):
    """Joining the withheld set drops a key from every backup. The set is the
    labels' keys (one source), and today it is exactly the workstation token —
    a second member needs the same argument `src/settings.py` makes for it."""
    assert store.WITHHELD_SETTING_KEYS == frozenset(store.WITHHELD_SETTING_LABELS)
    assert store.WITHHELD_SETTING_KEYS == {"workstation_token"}


def _backup_card_text() -> str:
    """The words of the `.admin-card` holding `#adm-exportDataBtn`: from that
    card's opening tag to the next card or comment, tags stripped."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    at = html.index('id="adm-exportDataBtn"')
    start = html.rindex('class="admin-card"', 0, at)
    ends = [e for e in (html.find('class="admin-card"', at), html.find("<!--", at)) if e != -1]
    return " ".join(re.sub(r"<[^>]+>", " ", html[start:min(ends)]).split())


def test_the_export_says_what_the_file_holds_and_leaves_out():
    card = _backup_card_text()
    assert card and "Export Data" in card
    assert "API keys" in card and "keep it private" in card
    assert "pairing key is left out" in card
