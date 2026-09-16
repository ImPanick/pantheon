# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B95` — three settings an operator could only change by hand-writing JSON.

`metrics_enabled`, `searxng_widen_engines` and `allow_model_download` had no
field, no toggle and no label anywhere in `static/` — measured 2026-09-15 by
grepping every `.js` and `.html` in the tree for all three names, zero hits. The
only writer was `POST /api/auth/settings`, which accepts any key in
`DEFAULT_SETTINGS` and is reachable from a terminal and not from the product.

**This is the second half of why `B90` was never reported.** The switch could
not be beaten by an environment variable *and* could not be reached by a person.
`B90` fixed the first half.

It is not "add three checkboxes". All three ship `None` (`D-2026-09-15-01`) so a
stored `False` can mean *no* rather than *unset*, which means a control has to
express **three** states — and a two-state checkbox writing `false` on first
paint would put on disk, for every operator who opens the panel, exactly the
choice nobody made that `B90` was filed to remove.

Everything here drives the real route functions and the real resolver. The two
pure pieces of the panel are run in node out of `static/js/settings.js` rather
than read (`Law 20`). Nothing reloads `src.constants` or `src.settings`
(`B18`, `B130`).
"""
import asyncio
import importlib
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException

_REPO = Path(__file__).resolve().parent.parent
_HARNESS = _REPO / "tests" / "harness" / "env_backed_flag_panel.js"


@pytest.fixture
def datadir(tmp_path, monkeypatch):
    """A `DATA_DIR` of our own, by rebinding the names that matter rather than
    reloading the modules that hold them.

    Reloading `src.constants` poisons the 41 modules that import from it by
    value, and a reload has no correct teardown — the lesson `B130` paid five
    failures in two files for, and the same fixture shape
    `tests/test_env_flag_vocabulary.py` settled on.
    """
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    import src.constants
    import src.settings

    settings_file = os.path.join(str(tmp_path), "settings.json")
    features_file = os.path.join(str(tmp_path), "features.json")
    monkeypatch.setattr(src.constants, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(src.constants, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(src.constants, "FEATURES_FILE", features_file)
    monkeypatch.setattr(src.settings, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(src.settings, "FEATURES_FILE", features_file)
    src.settings._invalidate_caches()
    src.settings._warned_stored_no.clear()
    yield tmp_path
    src.settings._invalidate_caches()


class _AdminManager:
    """The smallest auth manager the settings routes actually use."""
    is_configured = True

    def get_username_for_token(self, token):
        return "ada" if token else None

    def is_admin(self, user):
        return user == "ada"


class _Request:
    def __init__(self, body=None, signed_in=True):
        from routes.auth_routes import SESSION_COOKIE
        self.cookies = {SESSION_COOKIE: "t"} if signed_in else {}
        self._body = body or {}

    async def json(self):
        return self._body


def _routes():
    """The real settings endpoints, pulled off the real router."""
    root = str(_REPO / "core")
    core = sys.modules.get("core")
    if core is None:
        core = types.ModuleType("core")
        sys.modules["core"] = core
    core.__path__ = [root]
    from routes.auth_routes import setup_auth_routes
    router = setup_auth_routes(_AdminManager())
    found = {}
    for route in router.routes:
        found[getattr(route, "path", "")] = route.endpoint
    return found


def _get_flags():
    return asyncio.run(_routes()["/api/auth/settings/flag-sources"](_Request()))["flags"]


def _post(body):
    return asyncio.run(_routes()["/api/auth/settings"](_Request(body)))


KEYS = ("allow_model_download", "searxng_widen_engines", "metrics_enabled")


# ── The registry, and that it describes the real resolvers ────────────────

def test_the_registry_holds_exactly_the_tri_state_keys():
    """`B90` made three keys tri-state; the panel has to enumerate them, and an
    enumeration that lived in JavaScript would be the layering rule in a second
    place (`Law 13`)."""
    from src.settings import DEFAULT_SETTINGS, ENV_BACKED_FLAGS
    assert set(ENV_BACKED_FLAGS) == set(KEYS)
    for key, (env_name, default) in ENV_BACKED_FLAGS.items():
        assert DEFAULT_SETTINGS[key] is None, key
        assert isinstance(env_name, str) and env_name
        assert default is False


def test_the_registry_names_the_variable_each_resolver_actually_reads(datadir, monkeypatch):
    """Not a transcription check — each variable is set to `1` on its own and
    the real resolver is asked. A registry that named the wrong variable would
    show the panel a layer nothing consults."""
    import services.search.providers as P
    import src.embedding_lanes as EL
    import src.settings as S
    resolvers = {
        "allow_model_download": EL.model_download_allowed,
        "searxng_widen_engines": P._widen_engines_allowed,
        "metrics_enabled": lambda: S.env_backed_flag(
            S.load_settings(), "metrics_enabled", "PANTHEON_METRICS_ENABLED"),
    }
    for key, (env_name, _) in S.ENV_BACKED_FLAGS.items():
        for other, (other_env, _) in S.ENV_BACKED_FLAGS.items():
            monkeypatch.delenv(other_env, raising=False)
        monkeypatch.setenv(env_name, "1")
        S._invalidate_caches()
        assert resolvers[key]() is True, f"{env_name} does not answer for {key}"


# ── Which layer is answering ──────────────────────────────────────────────

def test_nothing_anywhere_is_answered_by_the_default(datadir, monkeypatch):
    from src.settings import ENV_BACKED_FLAGS, env_backed_flag_report
    for _, (env_name, _) in ENV_BACKED_FLAGS.items():
        monkeypatch.delenv(env_name, raising=False)
    report = env_backed_flag_report({})
    for key in KEYS:
        assert report[key]["source"] == "default"
        assert report[key]["effective"] is False
        assert report[key]["env_set"] is False


def test_a_variable_on_this_host_is_reported_as_the_environment(datadir, monkeypatch):
    """The sentence the panel could not say before. A compose file forwarding
    `${PANTHEON_ALLOW_MODEL_DOWNLOAD:-0}` makes *unset* a different state from
    *unset with nothing underneath*, and a panel that shows an empty control
    without saying so is telling an operator their `Law 16` gate is shut."""
    from src.settings import env_backed_flag_report
    monkeypatch.setenv("PANTHEON_ALLOW_MODEL_DOWNLOAD", "1")
    report = env_backed_flag_report({})
    assert report["allow_model_download"]["source"] == "environment"
    assert report["allow_model_download"]["effective"] is True
    assert report["allow_model_download"]["env_says"] is True


def test_a_stored_choice_is_reported_as_settings_and_says_what_is_underneath(
        datadir, monkeypatch):
    """`B90`'s own cost, made visible. A stored `False` beats a truthy variable —
    that is the fix — so the operator deciding whether to hand the answer back
    needs to be told what the variable says."""
    from src.settings import env_backed_flag_report
    monkeypatch.setenv("PANTHEON_ALLOW_MODEL_DOWNLOAD", "1")
    report = env_backed_flag_report({"allow_model_download": False})
    row = report["allow_model_download"]
    assert row["source"] == "settings"
    assert row["effective"] is False
    assert row["env_set"] is True and row["env_says"] is True


def test_the_source_is_derived_from_the_same_resolution_as_the_value(
        datadir, monkeypatch):
    """A second copy of the layering rule beside the first is how `B90`
    happened (`Law 13`). Driven over every combination that exists."""
    from src.settings import env_backed_flag, env_backed_flag_source
    for stored in (None, True, False, "true", "false", "nonsense"):
        for env in (None, "1", "0", "nonsense"):
            if env is None:
                monkeypatch.delenv("PANTHEON_METRICS_ENABLED", raising=False)
            else:
                monkeypatch.setenv("PANTHEON_METRICS_ENABLED", env)
            settings = {} if stored is None else {"metrics_enabled": stored}
            value = env_backed_flag(settings, "metrics_enabled",
                                    "PANTHEON_METRICS_ENABLED")
            source = env_backed_flag_source(settings, "metrics_enabled",
                                            "PANTHEON_METRICS_ENABLED")
            assert source in ("settings", "environment", "default")
            if source == "settings":
                assert stored is not None and stored != "nonsense"
            if source == "environment":
                assert env in ("1", "0")
                assert value is (env == "1")
            if source == "default":
                assert value is False


# ── A person can set each to yes, to no, and back to unset ────────────────

def test_a_person_can_set_each_of_the_three_to_yes_no_and_unset(datadir):
    """The row's `Verify:`, driven end to end through the real routes. Before
    `B95` there was no route that could report the third state and no control
    that could select it; `null` on the way in and `null` on the way out is what
    makes *unset* something an operator can choose rather than only inherit."""
    import src.settings as S
    for key in KEYS:
        _post({key: True})
        assert S.load_settings()[key] is True
        assert _get_flags()[key]["source"] == "settings"

        _post({key: False})
        assert S.load_settings()[key] is False
        assert _get_flags()[key]["source"] == "settings"

        _post({key: None})
        assert S.load_settings()[key] is None
        assert _get_flags()[key]["source"] in ("environment", "default")
        assert json.load(open(S.SETTINGS_FILE, encoding="utf-8"))[key] is None


def test_the_stored_no_survives_a_later_save_of_something_else(datadir):
    """`POST /api/auth/settings` writes every shipped default back, so a panel
    that saved an unrelated field used to be able to overwrite this one. It
    writes `null` for the untouched keys, and `null` is not a choice."""
    import src.settings as S
    _post({"allow_model_download": False})
    _post({"agent_email_confirm": True})
    assert S.load_settings()["allow_model_download"] is False
    assert S.load_settings()["metrics_enabled"] is None


def test_a_string_in_a_tri_state_slot_is_refused_at_the_door(datadir):
    """The `P17-09` shape, on the group of keys where one is a `Law 16` gate: a
    value stored cleanly, read as *unset* by `env_truthy`, and echoed back with
    a 200 would leave the panel showing a choice nothing is honouring."""
    import src.settings as S
    for bad in ("maybe", "true", 1, [], {}):
        with pytest.raises(HTTPException) as caught:
            _post({"allow_model_download": bad})
        assert caught.value.status_code == 400
        assert "allow_model_download" in str(caught.value.detail)
    assert S.load_settings()["allow_model_download"] is None


def test_the_report_needs_an_admin(datadir):
    with pytest.raises(HTTPException) as caught:
        asyncio.run(_routes()["/api/auth/settings/flag-sources"](
            _Request(signed_in=False)))
    assert caught.value.status_code == 403


# ── The control itself ────────────────────────────────────────────────────

def _node(mode, payload=None):
    out = subprocess.run(["node", str(_HARNESS), mode], cwd=_REPO, input=payload,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_panel_has_a_control_for_every_key_in_the_registry():
    """The measurement the row is named for, as a ratchet: zero of the three had
    a control anywhere in `static/`. A fourth tri-state key added to the
    registry with no label fails here rather than shipping unreachable."""
    from src.settings import ENV_BACKED_FLAGS
    assert _node("labels") == sorted(ENV_BACKED_FLAGS)


def test_the_panel_says_which_layer_is_answering():
    """Run, not read. The three sentences are the only place the source ever
    reaches a person, and the environment one has to name the variable —
    "unset" is not an answer an operator can act on without it."""
    lines = _node("lines", json.dumps([
        {"source": "default", "effective": False, "env_set": False,
         "env_says": None, "env_name": "PANTHEON_ALLOW_MODEL_DOWNLOAD"},
        {"source": "environment", "effective": True, "env_set": True,
         "env_says": True, "env_name": "PANTHEON_ALLOW_MODEL_DOWNLOAD"},
        {"source": "settings", "effective": False, "env_set": True,
         "env_says": True, "env_name": "PANTHEON_ALLOW_MODEL_DOWNLOAD"},
        {"source": "settings", "effective": True, "env_set": False,
         "env_says": None, "env_name": "PANTHEON_ALLOW_MODEL_DOWNLOAD"},
    ]))
    default_line, env_line, overridden, plain = lines
    assert "default" in default_line and "PANTHEON_ALLOW_MODEL_DOWNLOAD" in default_line
    assert "environment" in env_line and "PANTHEON_ALLOW_MODEL_DOWNLOAD" in env_line
    assert "on" in env_line
    # The case `B90` is about: a stored no beating a set variable, said out loud.
    assert "wins" in overridden and "PANTHEON_ALLOW_MODEL_DOWNLOAD" in overridden
    assert "off" in overridden
    assert "PANTHEON_ALLOW_MODEL_DOWNLOAD" not in plain, (
        "with nothing in the environment there is no second layer to mention")


def test_the_control_offers_three_states_and_not_two():
    """`B90` arriving from the front end is the failure this prevents: a
    two-state checkbox has to write `false` for *unset*, which manufactures a
    stored choice for every operator who opens the panel.

    Run rather than read. The mapping is a round trip — every value the API can
    send has an option, and every option has a value the API accepts — so a
    collapse to `stored ? 'on' : 'off'` shows up here and not in somebody's
    settings file. `undefined` maps to *unset* as well as `null`, because a
    non-admin read scrubs keys out and a missing key is not a stored no."""
    states = _node("states")
    assert states["selected"] == ["on", "off", "unset", "unset"]
    assert states["stored"] == [True, False, None]


def test_the_card_the_control_is_built_into_exists_in_the_panel():
    """The row's measurement was that no control existed in `static/` at all, so
    the markup the JavaScript fills is part of the fix. This is the one
    assertion here that is about a file, and it is about markup rather than
    about behaviour (`Law 20`)."""
    html = (_REPO / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="settings-envflags-rows"' in html
    assert 'data-settings-panel="system"' in html
