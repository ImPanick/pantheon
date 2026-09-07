# SPDX-License-Identifier: AGPL-3.0-or-later
"""H06 / H07 — a fallback written as a default argument fires on absence, not on blank.

Two rows, one defect. `resolve_task_concurrency_cap` asked "did the operator set
this?" with `get_setting(KEY, None)`, and `load_settings` merges DEFAULT_SETTINGS
on every read, so the answer was always yes and the env leg below it was
unreachable code from first boot. CardDAV asked the same question with
`settings.get(k, os.environ.get(K, ""))`, and every writer stores `""` for a
cleared field, so one press of Remove masked three env credentials permanently.

These tests are about the resolution ORDER, which is the thing that was wrong.
Where a case has a settings file, it is written through the real `save_settings`
so the materialisation that makes the bug is reproduced rather than described.
"""
import importlib
import json
import os

import pytest


@pytest.fixture
def datadir(tmp_path, monkeypatch):
    """A DATA_DIR of our own, with every module that caches a path re-imported
    against it. Without the reload the constants are already bound to the real
    data dir and the test would read the developer's own settings."""
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    import src.constants
    importlib.reload(src.constants)
    import src.settings
    importlib.reload(src.settings)
    yield tmp_path
    monkeypatch.delenv("PANTHEON_DATA_DIR", raising=False)
    importlib.reload(src.constants)
    importlib.reload(src.settings)


# ── H06: the concurrency cap's env layer ───────────────────────────────────

def _resolve(monkeypatch, cap_env, saved=None):
    import src.settings as S
    import src.task_scheduler as T
    importlib.reload(T)
    if cap_env is None:
        monkeypatch.delenv("PANTHEON_TASK_CONCURRENCY_CAP", raising=False)
    else:
        monkeypatch.setenv("PANTHEON_TASK_CONCURRENCY_CAP", str(cap_env))
    if saved is not None:
        S.save_settings(saved)
    S._invalidate_caches()
    return T.resolve_task_concurrency_cap()


def test_env_cap_wins_on_a_fresh_install_with_no_settings_file(datadir, monkeypatch):
    """The original defect, in its purest form: no file at all.

    This is the case `B20` did not describe — it blamed the first admin save —
    and it is the one that proves the env layer was dead from import."""
    import src.settings as S
    assert not os.path.exists(S.SETTINGS_FILE)
    assert _resolve(monkeypatch, 8) == (8, "PANTHEON_TASK_CONCURRENCY_CAP")


def test_env_cap_still_wins_after_an_admin_save_materialises_the_default(datadir, monkeypatch):
    """`POST /api/auth/settings` does `save_settings(load_settings())`, which
    writes all ~200 defaults to disk. A presence-only check — which is what
    `is_setting_overridden` gives — reads that as a deliberate choice and would
    leave this case broken."""
    import src.settings as S
    materialised = dict(S.DEFAULT_SETTINGS)
    assert materialised["task_concurrency_cap"] == 1
    cap, source = _resolve(monkeypatch, 8, saved=materialised)
    assert S.is_setting_overridden("task_concurrency_cap") is True, (
        "precondition: the key IS present after a save — that is the trap"
    )
    assert (cap, source) == (8, "PANTHEON_TASK_CONCURRENCY_CAP")


def test_a_deliberate_instance_setting_still_outranks_the_env(datadir, monkeypatch):
    """The documented order is instance setting → env. Fixing the detection must
    not invert it."""
    import src.settings as S
    saved = dict(S.DEFAULT_SETTINGS, task_concurrency_cap=4)
    assert _resolve(monkeypatch, 8, saved=saved) == (4, "instance setting")


def test_with_neither_layer_set_the_builtin_default_answers(datadir, monkeypatch):
    assert _resolve(monkeypatch, None) == (1, "built-in default")


def test_setting_is_explicit_needs_presence_and_a_non_default_value(datadir):
    import src.settings as S
    k = "task_concurrency_cap"
    assert S.setting_is_explicit(k) is False, "no file"
    S.save_settings(dict(S.DEFAULT_SETTINGS)); S._invalidate_caches()
    assert S.setting_is_explicit(k) is False, "present but equal to the default"
    S.save_settings(dict(S.DEFAULT_SETTINGS, **{k: 4})); S._invalidate_caches()
    assert S.setting_is_explicit(k) is True, "present and different"


def test_setting_is_explicit_is_false_for_a_key_we_do_not_ship(datadir):
    """An unknown key has no default to compare against, so it cannot be judged
    explicit — guessing would make every stray key outrank an env var."""
    import src.settings as S
    S.save_settings({"not_a_shipped_key": "x"}); S._invalidate_caches()
    assert S.setting_is_explicit("not_a_shipped_key") is False
    assert S.setting_is_explicit("not_a_shipped_key", default="") is True


def test_setting_is_explicit_needs_presence_for_a_key_that_was_never_written(datadir):
    """Where the presence half earns its keep.

    For a key in DEFAULT_SETTINGS the two halves agree, because `load_settings`
    merges the default in and an absent key therefore reads AS the default. They
    part company for a key that is neither shipped nor saved, judged against a
    caller-supplied default: `load_settings().get(k)` is None, `None != "x"` is
    true, and a value-only check would call a key nobody has ever written an
    explicit operator choice. A mutation dropping the presence check survived
    every other test here."""
    import src.settings as S
    S.save_settings({"unrelated": 1})
    S._invalidate_caches()
    assert S.setting_is_explicit("never_written", default="x") is False


def test_setting_is_explicit_accepts_none_as_a_real_default(datadir):
    """`default=None` must mean "the default is None", not "no default given" —
    which is why the sentinel is an object() and not None."""
    import src.settings as S
    S.save_settings({"k": None}); S._invalidate_caches()
    assert S.setting_is_explicit("k", default=None) is False
    S.save_settings({"k": 1}); S._invalidate_caches()
    assert S.setting_is_explicit("k", default=None) is True


# ── H07: env_backed, and the CardDAV credentials it rescues ────────────────

def test_env_backed_treats_blank_as_unset_which_get_does_not():
    """The whole row in one assertion: the idiom being replaced, beside the
    replacement, on the value the UI actually writes."""
    from src.settings import env_backed
    os.environ["_H07_PROBE"] = "from-env"
    try:
        cleared = {"k": ""}
        assert cleared.get("k", os.environ.get("_H07_PROBE", "")) == "", (
            "precondition: a dict default does not fire on a present empty string"
        )
        assert env_backed(cleared, "k", "_H07_PROBE") == "from-env"
    finally:
        del os.environ["_H07_PROBE"]


def test_env_backed_prefers_a_real_stored_value():
    from src.settings import env_backed
    os.environ["_H07_PROBE"] = "from-env"
    try:
        assert env_backed({"k": "stored"}, "k", "_H07_PROBE") == "stored"
    finally:
        del os.environ["_H07_PROBE"]


def test_env_backed_treats_whitespace_as_blank():
    from src.settings import env_backed
    os.environ["_H07_PROBE"] = "from-env"
    try:
        assert env_backed({"k": "   "}, "k", "_H07_PROBE") == "from-env"
    finally:
        del os.environ["_H07_PROBE"]


def test_env_backed_falls_to_the_caller_default_when_nothing_is_set():
    from src.settings import env_backed
    os.environ.pop("_H07_ABSENT", None)
    assert env_backed({}, "k", "_H07_ABSENT", "465") == "465"


def test_env_backed_passes_through_non_string_values():
    """`imap_port` is stored as an int and `imap_starttls` as a bool. Neither is
    blank, and coercing either to a string would break the callers that do
    `int(...)` on the result."""
    from src.settings import env_backed
    assert env_backed({"p": 993}, "p", "_H07_ABSENT") == 993
    assert env_backed({"b": False}, "b", "_H07_ABSENT") is False


def _carddav(monkeypatch, tmp_path, stored=None, **env):
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    import src.constants, src.settings
    importlib.reload(src.constants)
    importlib.reload(src.settings)
    from routes.contacts import contacts_routes as C
    importlib.reload(C)
    for k in ("CARDDAV_URL", "CARDDAV_USERNAME", "CARDDAV_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    if stored is not None:
        C._save_settings(stored)
    return C


def test_carddav_env_credentials_survive_the_remove_button(tmp_path, monkeypatch):
    """The live defect. `static/js/settings.js:3598` PUTs three empty strings on
    Remove, and the reader's `.get(k, env)` took them as real values — so an
    operator's env credentials were unreachable from that moment on, with
    nothing in `settings.json` that looks wrong."""
    C = _carddav(
        monkeypatch, tmp_path,
        stored={"carddav_url": "", "carddav_username": "", "carddav_password": ""},
        CARDDAV_URL="https://dav.example.com",
        CARDDAV_USERNAME="alice",
        CARDDAV_PASSWORD="s3cret",
    )
    cfg = C._get_carddav_config()
    assert cfg == {
        "url": "https://dav.example.com",
        "username": "alice",
        "password": "s3cret",
    }
    assert C._carddav_configured(cfg) is True


def test_carddav_stored_credentials_still_outrank_the_environment(tmp_path, monkeypatch):
    from src.secret_storage import encrypt
    C = _carddav(monkeypatch, tmp_path, CARDDAV_URL="https://env.example.com")
    C._save_settings({
        "carddav_url": "https://stored.example.com",
        "carddav_username": "bob",
        "carddav_password": encrypt("stored-pw"),
    })
    cfg = C._get_carddav_config()
    assert cfg["url"] == "https://stored.example.com"
    assert cfg["username"] == "bob"
    assert cfg["password"] == "stored-pw", "a stored password must be decrypted"


def test_carddav_env_password_is_not_run_through_decrypt(tmp_path, monkeypatch):
    """The boundary the original expressed as `if password and key in settings`.
    An env password is plaintext; decrypting it would corrupt it or raise. The
    original guard was right and became `if "" and ...` the moment a writer
    stored a blank, which is how the bug hid."""
    called = []
    import src.secret_storage as SS
    monkeypatch.setattr(SS, "decrypt", lambda v: called.append(v) or "WRONG")
    C = _carddav(monkeypatch, tmp_path,
                 stored={"carddav_password": ""},
                 CARDDAV_PASSWORD="plaintext-from-env")
    assert C._get_carddav_config()["password"] == "plaintext-from-env"
    assert called == [], "decrypt must not be called on an environment value"


def test_carddav_sources_says_which_layer_answered(tmp_path, monkeypatch):
    """Remove cannot unset a process environment variable. If the field
    repopulates with the env value and the panel cannot say why, that reads as a
    failed delete — so the endpoint reports the layer."""
    C = _carddav(monkeypatch, tmp_path,
                 stored={"carddav_url": "https://stored.example.com"},
                 CARDDAV_USERNAME="alice")
    assert C._carddav_sources() == {
        "carddav_url": "settings",
        "carddav_username": "environment",
        "carddav_password": "",
    }


def test_legacy_email_config_falls_back_to_env_on_blank(tmp_path, monkeypatch):
    """The ten latent fields. No writer creates these flat keys today, so this
    is a guard against the reintroduction rather than a fix for a live failure —
    which is exactly why it needs a test: nothing else would notice."""
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    import src.constants, src.settings
    importlib.reload(src.constants)
    importlib.reload(src.settings)
    import routes.email_helpers as E
    importlib.reload(E)
    for k, v in {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "u",
                 "SMTP_PASSWORD": "p", "IMAP_HOST": "imap.example.com",
                 "IMAP_USER": "u", "IMAP_PASSWORD": "p",
                 "EMAIL_FROM": "me@example.com", "SMTP_PORT": "2465"}.items():
        monkeypatch.setenv(k, v)
    E._save_settings({k: "" for k in (
        "smtp_host", "smtp_user", "smtp_password", "imap_host",
        "imap_user", "imap_password", "email_from", "smtp_port")})
    cfg = E._get_email_config()
    assert cfg["smtp_host"] == "smtp.example.com"
    assert cfg["imap_host"] == "imap.example.com"
    assert cfg["from_address"] == "me@example.com"
    assert cfg["smtp_port"] == 2465
