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


def test_get_setting_merges_the_shipped_defaults_onto_whatever_was_saved(datadir):
    """Half the premise, and the half `H06` turns on.

    A settings file holding one key still answers every other key with the
    shipped default, so `get_setting(K, None)` cannot return None and a
    fallback written below it never runs. Driven against a file that exists and
    is missing the key, which is the case `test_..._no_settings_file` cannot
    reach."""
    import src.settings as S
    S.save_settings({"agent_max_rounds": 42})
    S._invalidate_caches()
    assert S.get_setting("task_concurrency_cap", None) == 1, (
        "the merge is why the env leg below this read was unreachable"
    )
    assert S.is_setting_overridden("task_concurrency_cap") is False, (
        "and the raw file is the only place that can tell you it was never set"
    )


def test_one_admin_save_materialises_every_shipped_default(datadir, monkeypatch):
    """The other half, driven through `POST /api/auth/settings` itself.

    The route is the thing that materialises, so asserting the property against
    `save_settings(load_settings())` in the test proves the idiom and not the
    endpoint. The count is asserted against `DEFAULT_SETTINGS` rather than a
    number: `H06` and `src/settings.py` both carried "~200" for a dict that
    holds 89, and `B20` re-drove it.
    """
    import asyncio
    import json
    import types
    import routes.auth_routes as auth_routes
    import src.settings as S

    class _AdminOnly:
        def get_username_for_token(self, token):
            return "admin" if token == "admin-session" else None

        def is_admin(self, username):
            return username == "admin"

    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)
    router = auth_routes.setup_auth_routes(_AdminOnly())
    endpoint = next(r.endpoint for r in router.routes
                    if r.path == "/api/auth/settings" and "POST" in r.methods)

    class _Request(types.SimpleNamespace):
        async def json(self):
            return {"agent_max_rounds": 42}

    assert not os.path.exists(S.SETTINGS_FILE), "precondition: nothing saved yet"
    asyncio.run(endpoint(_Request(cookies={auth_routes.SESSION_COOKIE: "admin-session"})))
    S._invalidate_caches()

    on_disk = json.load(open(S.SETTINGS_FILE, encoding="utf-8"))
    assert set(on_disk) == set(S.DEFAULT_SETTINGS), (
        "one key was sent and every shipped default landed on disk"
    )
    assert [k for k in S.DEFAULT_SETTINGS if not S.is_setting_overridden(k)] == [], (
        "every key is now 'present', which is why presence is not the signal"
    )
    assert S.setting_is_explicit("task_concurrency_cap") is False, (
        "and why the two-signal version is"
    )


def test_env_cap_still_wins_after_an_admin_save_materialises_the_default(datadir, monkeypatch):
    """`POST /api/auth/settings` does `save_settings(load_settings())`, which
    writes every shipped default to disk. A presence-only check — which is what
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
    for k, v in {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "su",
                 "SMTP_PASSWORD": "sp", "IMAP_HOST": "imap.example.com",
                 "IMAP_USER": "iu", "IMAP_PASSWORD": "ip",
                 "EMAIL_FROM": "me@example.com", "SMTP_PORT": "2465",
                 "IMAP_PORT": "2993", "SMTP_SECURITY": "starttls"}.items():
        monkeypatch.setenv(k, v)
    E._save_settings({k: "" for k in (
        "smtp_host", "smtp_user", "smtp_password", "smtp_port", "smtp_security",
        "imap_host", "imap_user", "imap_password", "imap_port", "email_from")})
    cfg = E._get_email_config()
    # `B20`. Every field this test blanks is now asserted. It blanked eight and
    # asserted four, so a mutation putting `imap_password` back on the raw idiom
    # — the exact credential loss `H07` is about — survived the whole file. The
    # ten the row claims are ten only if ten are checked.
    assert cfg["smtp_host"] == "smtp.example.com"
    assert cfg["smtp_user"] == "su"
    assert cfg["smtp_password"] == "sp"
    assert cfg["smtp_port"] == 2465
    assert cfg["smtp_security"] == "starttls"
    assert cfg["imap_host"] == "imap.example.com"
    assert cfg["imap_user"] == "iu"
    assert cfg["imap_password"] == "ip"
    assert cfg["imap_port"] == 2993
    assert cfg["from_address"] == "me@example.com"


# ── B20: the eleventh field ────────────────────────────────────────────────
#
# `H07` names ten latent email fields and fixes ten. The dict has eleven.
# `imap_starttls` stayed on `settings.get(k, True)`, so `IMAP_STARTTLS` reached
# `mcp_servers/email_server.py:312` and not `routes/email_helpers.py` — one
# variable, one host, one mailbox, two answers. These drive the real resolver.


def _legacy_mail(tmp_path, monkeypatch, stored=None, **env):
    """The legacy flat-key path of `_get_email_config`, with a data dir of our
    own. No `email_accounts` row exists here, which is what sends the resolver
    down the branch under test."""
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    import src.constants, src.settings
    importlib.reload(src.constants)
    importlib.reload(src.settings)
    import routes.email_helpers as E
    importlib.reload(E)
    for k in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD", "IMAP_STARTTLS", "IMAP_PORT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "u")
    monkeypatch.setenv("IMAP_PASSWORD", "p")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    E._save_settings(stored if stored is not None else {})
    return E


def test_imap_starttls_reaches_the_environment_like_its_ten_siblings(tmp_path, monkeypatch):
    """The live defect. Measured before the fix: this resolver answered True
    while `mcp_servers/email_server.py` answered False for the same variable, so
    `_imap_connect` opened a plaintext socket and called STARTTLS on a server
    the operator had just said does not offer it."""
    E = _legacy_mail(tmp_path, monkeypatch, IMAP_STARTTLS="false")
    assert E._get_email_config()["imap_starttls"] is False


def test_imap_starttls_is_not_fooled_by_the_string_false(tmp_path, monkeypatch):
    """`env_backed` returns the environment value as the string it is, and
    `bool("false")` is True. Converting this field without coercing would have
    been the same defect wearing the fix's clothes."""
    E = _legacy_mail(tmp_path, monkeypatch, IMAP_STARTTLS="false")
    value = E._get_email_config()["imap_starttls"]
    assert isinstance(value, bool), f"a raw {value!r} would reach _imap_connect"
    assert bool("false") is True, "precondition: this is the trap being avoided"
    assert value is False


def test_imap_starttls_stays_on_when_neither_layer_says_otherwise(tmp_path, monkeypatch):
    """`Law 1`. Every operator who has not set the variable had True and keeps
    True — the change is reachable only to somebody who typed the name."""
    E = _legacy_mail(tmp_path, monkeypatch)
    assert E._get_email_config()["imap_starttls"] is True


def test_imap_starttls_env_on_is_honoured_too(tmp_path, monkeypatch):
    E = _legacy_mail(tmp_path, monkeypatch, IMAP_STARTTLS="true")
    assert E._get_email_config()["imap_starttls"] is True


@pytest.mark.parametrize("stored,expected", [(True, True), (False, False)])
def test_a_stored_imap_starttls_still_outranks_the_environment(
        tmp_path, monkeypatch, stored, expected):
    """The documented order for this layer pair is stored value → environment →
    default, the same one the other ten fields follow. A stored ``False`` is a
    real value and not an absence — `env_backed` is what makes that distinction
    and it is why a plain `or` would have been wrong here."""
    E = _legacy_mail(tmp_path, monkeypatch, stored={"imap_starttls": stored},
                     IMAP_STARTTLS="true" if not stored else "false")
    assert E._get_email_config()["imap_starttls"] is expected


def test_the_starttls_coercion_matches_the_other_resolver_of_the_variable(tmp_path, monkeypatch):
    """Two resolvers of one variable must agree about every spelling, not only
    about `false`. Accepting `1` at one of them and not the other would have
    replaced a silent disagreement about `false` with a silent disagreement
    about `1`.

    **The agreement is unchanged; what it is measured against is.** `B20` wrote
    this line as a transcription of `mcp_servers/email_server.py`'s rule —
    `raw.strip().lower() == "true"`, copied by hand — because there was nothing
    to call. `B91` gave both resolvers `env_flags.env_flag`, so the comparison
    is now against the shared rule, and a transcription that could go stale
    without either resolver moving is gone. `IMAP_STARTTLS=1` moves from *off*
    to *on* at both together; the direction is toward TLS, and neither can drift
    from the other again because there is only one rule.
    """
    import os
    import routes.email_helpers as E
    from src.env_flags import env_flag
    for raw in ("true", "TRUE", " true ", "false", "1", "0", "yes", "on", "off", ""):
        monkeypatch.setenv("IMAP_STARTTLS", raw)
        sibling = env_flag("IMAP_STARTTLS", False)    # what email_server.py now calls
        assert E._starttls(raw) is sibling, raw
        assert os.environ["IMAP_STARTTLS"] == raw, "precondition: the env holds the spelling"


def test_the_starttls_coercion_keeps_a_stored_bool_and_spells_an_env_string(tmp_path, monkeypatch):
    """Both halves of the branch, because a mutation deleting either one has to
    fail here. A stored value arrives typed and is believed; an environment
    value arrives as a string and is judged on its spelling — and `bool("false")`
    is True, which is why the string half cannot be the `bool()` one."""
    import routes.email_helpers as E
    assert E._starttls(True) is True
    assert E._starttls(False) is False, "a stored False is a choice, not an absence"
    assert E._starttls("false") is False, "and a string is not judged by truthiness"
    assert E._starttls("True") is True, "the string half must not depend on repr casing"
