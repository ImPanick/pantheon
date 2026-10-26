# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1479`, `D-2026-10-25-04` §2 — a default pair comes from one layer.

`get_user_setting` answers key by key, so a person who had picked an endpoint
but no model was handed their endpoint with the install's model — a name their
endpoint may not serve. `get_user_setting_pair` reads the endpoint and its model
together: the person's own when they picked an endpoint, else the admin's
Default. The composer and `endpoint_resolver` both read it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src.settings as S

ROOT = Path(__file__).resolve().parents[1]
GLOBAL = {"default_endpoint_id": "admin-ep", "default_model": "admin-model"}


@pytest.fixture
def prefs(monkeypatch):
    store = {}
    import routes.prefs_routes as pr
    monkeypatch.setattr(pr, "_load_for_user", lambda user: store.get(user, {}))
    return store


def test_no_pick_is_the_admins_default(prefs):
    assert S.get_user_setting_pair("default_endpoint_id", "default_model", "bob", GLOBAL) == \
        ("admin-ep", "admin-model")


def test_a_pick_is_the_persons_whole_pair(prefs):
    prefs["bob"] = {"default_endpoint_id": "bob-ep", "default_model": "bob-model"}
    assert S.get_user_setting_pair("default_endpoint_id", "default_model", "bob", GLOBAL) == \
        ("bob-ep", "bob-model")


def test_never_the_persons_endpoint_with_the_installs_model(prefs):
    prefs["bob"] = {"default_endpoint_id": "bob-ep"}
    assert S.get_user_setting_pair("default_endpoint_id", "default_model", "bob", GLOBAL) == ("bob-ep", "")


def test_a_key_that_is_not_per_person_is_the_installs(prefs):
    prefs["bob"] = {"naming_endpoint_id": "bob-ep"}
    settings = {"naming_endpoint_id": "admin-ep", "naming_model": "m"}
    assert S.get_user_setting_pair("naming_endpoint_id", "naming_model", "bob", settings) == ("admin-ep", "m")


def test_the_switch_is_retired_and_both_readers_use_the_rule():
    assert "share_defaults_with_users" not in S.DEFAULT_SETTINGS
    routes = (ROOT / "routes" / "model_routes.py").read_text(encoding="utf-8")
    resolver = (ROOT / "src" / "endpoint_resolver.py").read_text(encoding="utf-8")
    assert 'settings.get("share_defaults_with_users"' not in routes
    assert "get_user_setting_pair" in routes and "get_user_setting_pair" in resolver
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "adm-shareDefaultsToggle" not in html
