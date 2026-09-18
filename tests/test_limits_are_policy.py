# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P12-01`, `P12-03`, `P12-05b` — a limit is policy, not a constant.

Every limit in Pantheon used to be a process-wide number read from an
environment variable at import. Eight of the ten `PANTHEON_*BYTES` caps were
module constants; the four throttles were literals with no variable at all. An
operator who wanted a bigger upload for one team, or a tighter login throttle,
had no move except editing compose and rebuilding.

These tests drive the real call sites (`Law 20`), in one process, and change the
answer between two calls — because "runtime-adjustable" is a claim about the
second call, and a test that re-imports the module proves nothing about it.

Scope of the counts asserted below (`Law 5`): **distinct `PANTHEON_*BYTES`
environment names appearing in non-test, non-`.pantheon` Python.** Measured
2026-09-18: ten, in three files — eight in `src/upload_limits.py`, one in
`routes/backup_routes.py`, one in `services/tts/tts_service.py`.
"""

import asyncio
import io
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, UploadFile

import src.settings as S
import src.upload_limits as UL
import routes.backup_routes as BR

REPO = Path(__file__).resolve().parent.parent

# The ten. Key -> the environment variable that is its override.
TEN_BYTE_CAPS = {
    **{k: env for k, (env, _d) in UL.BYTE_LIMITS.items()},
    "backup_import_max_bytes": "PANTHEON_BACKUP_IMPORT_MAX_BYTES",
    "tts_cache_max_bytes": "PANTHEON_TTS_CACHE_MAX_BYTES",
}

# The four throttles `P12-05b` names, with the built-in default each keeps.
FOUR_THROTTLES = {
    "auth_login_rate_limit": 15,
    "auth_signup_rate_limit": 3,
    "auth_setup_rate_limit": 3,
    "upload_rate_limit": 60,
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A settings file of our own, and a `store(**kw)` that writes to it.

    Writes the JSON directly rather than through `save_settings` so a key can
    be absent, which is the state every one of these limits ships in.
    """
    path = tmp_path / "settings.json"
    monkeypatch.setattr(S, "SETTINGS_FILE", str(path))

    def _store(**kw):
        path.write_text(json.dumps(kw), encoding="utf-8")
        S._invalidate_caches()

    _store()
    yield _store
    S._invalidate_caches()


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data))


# ── `P12-01` · the count, re-measured rather than carried (`Law 6`) ─────────

def test_there_are_exactly_ten_byte_caps_and_each_has_a_settings_key():
    """The row said ten and admitted eleven had been one too many. Ten it is."""
    found = {}
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith(("tests/", ".pantheon/")):
            continue
        for name in re.findall(r'"(PANTHEON_[A-Z0-9_]*BYTES[A-Z0-9_]*)"',
                               path.read_text(encoding="utf-8", errors="ignore")):
            found.setdefault(name, set()).add(rel)

    assert len(found) == 10, f"the ten byte caps are now {len(found)}: {sorted(found)}"
    assert set(found) == set(TEN_BYTE_CAPS.values())
    # Eight in one file, one each in the other two — the row's own breakdown.
    by_file = {}
    for name, files in found.items():
        for rel in files:
            by_file.setdefault(rel, set()).add(name)
    assert len(by_file["src/upload_limits.py"]) == 8
    assert len(by_file["routes/backup_routes.py"]) == 1
    assert len(by_file["services/tts/tts_service.py"]) == 1

    for key in TEN_BYTE_CAPS:
        assert key in S.DEFAULT_SETTINGS, f"{key} is not settable"
        assert S.DEFAULT_SETTINGS[key] is None, (
            f"{key} must ship None — a truthy default makes every layer "
            f"beneath it unreachable (`H06`, `B20`)")


# ── `P12-01` · the chain, driven ───────────────────────────────────────────

@pytest.mark.parametrize("key", sorted(UL.BYTE_LIMITS))
def test_a_byte_cap_falls_through_role_setting_env_default(key, store, monkeypatch):
    env_name, default = UL.BYTE_LIMITS[key]
    monkeypatch.delenv(env_name, raising=False)

    assert UL.resolve_byte_limit_with_source(key) == (default, "built-in default")

    monkeypatch.setenv(env_name, "4242")
    assert UL.resolve_byte_limit_with_source(key) == (4242, env_name)

    store(**{key: 777})
    assert UL.resolve_byte_limit_with_source(key) == (777, "instance setting")

    monkeypatch.setattr(S, "role_limit", lambda k, o=None: 99 if k == key else None)
    assert UL.resolve_byte_limit_with_source(key) == (99, "role profile")


def test_the_role_layer_is_present_and_empty_until_p11_02():
    """`P11-02` slots in here rather than rewriting the chain.

    The hook has to exist and has to answer "nothing" for every key today, or
    the layer is a plan rather than a place.
    """
    for key in list(TEN_BYTE_CAPS) + list(FOUR_THROTTLES):
        assert S.role_limit(key) is None
        assert S.role_limit(key, "someone") is None


def test_a_stored_default_shaped_value_still_wins_over_the_environment(store, monkeypatch):
    """The keys ship `None`, so storing the same number as the default is a
    choice the store can hold — which `setting_is_explicit` alone cannot do for
    a key that ships its default (`B90`, applied to an integer)."""
    monkeypatch.setenv("PANTHEON_ICS_MAX_BYTES", "4242")
    store(ics_max_bytes=UL.BYTE_LIMITS["ics_max_bytes"][1])
    value, source = UL.resolve_byte_limit_with_source("ics_max_bytes")
    assert source == "instance setting"
    assert value == UL.BYTE_LIMITS["ics_max_bytes"][1]


def test_a_cap_can_never_be_stored_as_off(store):
    """`FORBIDDEN.md` Part 2. A cap of zero rejects every upload while reading
    as a configured limit; `minimum=1` is why there is no such value."""
    store(gallery_upload_max_bytes=0)
    assert UL.resolve_byte_limit("gallery_upload_max_bytes") == 1
    store(gallery_upload_max_bytes=-5)
    assert UL.resolve_byte_limit("gallery_upload_max_bytes") == 1


def test_a_cap_that_will_not_parse_falls_through_rather_than_raising(store, monkeypatch):
    monkeypatch.delenv("PANTHEON_ICS_MAX_BYTES", raising=False)
    store(ics_max_bytes="fifty megabytes")
    assert UL.resolve_byte_limit_with_source("ics_max_bytes") == \
        (UL.BYTE_LIMITS["ics_max_bytes"][1], "built-in default")


# ── `P12-03` · the eight that were read at import ──────────────────────────

IMPORT_TIME_CONSTANTS = {
    "gallery_upload_max_bytes": (UL, "GALLERY_UPLOAD_MAX_BYTES"),
    "gallery_transform_upload_max_bytes": (UL, "GALLERY_TRANSFORM_UPLOAD_MAX_BYTES"),
    "memory_import_max_bytes": (UL, "MEMORY_IMPORT_MAX_BYTES"),
    "personal_upload_max_bytes": (UL, "PERSONAL_UPLOAD_MAX_BYTES"),
    "email_compose_upload_max_bytes": (UL, "EMAIL_COMPOSE_UPLOAD_MAX_BYTES"),
    "stt_max_audio_bytes": (UL, "STT_MAX_AUDIO_BYTES"),
    "ics_max_bytes": (UL, "ICS_MAX_BYTES"),
    "backup_import_max_bytes": (BR, "BACKUP_IMPORT_MAX_BYTES"),
}


def test_eight_of_the_ten_were_read_at_import_and_are_the_set_below():
    """The row's other number, re-measured. Eight import-time, one at instance
    init (TTS), one per call (chat)."""
    assert len(IMPORT_TIME_CONSTANTS) == 8
    assert set(IMPORT_TIME_CONSTANTS) | {"tts_cache_max_bytes", "chat_upload_max_bytes"} \
        == set(TEN_BYTE_CAPS)
    for key, (mod, name) in IMPORT_TIME_CONSTANTS.items():
        assert isinstance(getattr(mod, name), int), f"{name} left {mod.__name__}"


@pytest.mark.parametrize("key", sorted(k for k in IMPORT_TIME_CONSTANTS
                                       if k in UL.BYTE_LIMITS))
def test_an_import_time_cap_now_changes_without_a_reimport(key, store, monkeypatch):
    """The whole of `P12-03` in one assertion pair: the constant does not move,
    and the answer does."""
    mod, name = IMPORT_TIME_CONSTANTS[key]
    monkeypatch.delenv(UL.BYTE_LIMITS[key][0], raising=False)
    before = getattr(mod, name)
    assert UL.resolve_byte_limit(key) == before

    store(**{key: 4096})

    assert getattr(mod, name) == before, "the import-time snapshot must not move"
    assert UL.resolve_byte_limit(key) == 4096


async def test_the_backup_import_route_honours_a_stored_cap(store, monkeypatch):
    """Driven through `POST /api/import` itself, with nothing monkeypatched but
    the settings file — so this fails if the route keeps reading the constant.
    """
    from tests.test_backup_import_cap_behind_the_admin_gate import (
        _import_endpoint, _StreamedRequest)
    monkeypatch.delenv("PANTHEON_BACKUP_IMPORT_MAX_BYTES", raising=False)
    assert BR._backup_import_max_bytes() == BR.BACKUP_IMPORT_MAX_BYTES

    store(backup_import_max_bytes=64)

    assert BR.BACKUP_IMPORT_MAX_BYTES != 64, "the import-time snapshot must not move"
    endpoint = _import_endpoint()
    req = _StreamedRequest([b"x" * 4096], user="root", admins=("root",))
    with pytest.raises(HTTPException) as exc:
        await endpoint(req)
    assert exc.value.status_code == 413
    assert "64 bytes" in exc.value.detail


def test_the_tts_cache_cap_changes_without_a_new_instance(store, monkeypatch, tmp_path):
    """The one cap that was read at instance init. One object, two answers, and
    the eviction that answer drives."""
    from services.tts.tts_service import TTSService
    monkeypatch.delenv("PANTHEON_TTS_CACHE_MAX_BYTES", raising=False)
    cache = tmp_path / "tts"
    service = TTSService(cache_dir=str(cache))
    assert service._cache_limit_bytes() == service.max_cache_bytes

    for i in range(4):
        (cache / f"{i}.wav").write_bytes(b"x" * 100)
    service._enforce_cache_limit()
    assert len(list(cache.glob("*.wav"))) == 4, "400 bytes is under the shipped cap"

    store(tts_cache_max_bytes=150)

    assert service._cache_limit_bytes() == 150
    assert service.max_cache_bytes != 150, "the init-time value is the floor, not the answer"
    service._enforce_cache_limit()
    assert len(list(cache.glob("*.wav"))) < 4, "the new cap must evict"


def test_a_stored_chat_cap_is_honoured_by_the_next_upload(store, monkeypatch, tmp_path):
    """The `P12-03` claim at the place a person meets it: one handler, two
    uploads, a different answer, no restart."""
    from src.upload_handler import UploadHandler
    monkeypatch.delenv("PANTHEON_CHAT_UPLOAD_MAX_BYTES", raising=False)
    handler = UploadHandler(base_dir=str(tmp_path), upload_dir=str(tmp_path / "up"))

    assert handler.effective_max_upload_size() == handler.max_upload_size

    store(chat_upload_max_bytes=4)

    with pytest.raises(HTTPException) as exc:
        handler.save_upload(_upload("big.txt", b"abcde"), client_ip="10.0.0.9")
    assert exc.value.status_code == 400
    assert exc.value.detail == "File size exceeds 4 bytes limit"
    assert handler.max_upload_size != 4, "the boot-time value is the floor, not the answer"


# ── `P12-05b` · the throttles ──────────────────────────────────────────────

def test_the_four_throttle_values_are_no_longer_literals():
    """Each of the four has a settings key shipping `None`, and none of them is
    one of the ten byte caps."""
    for key, _default in FOUR_THROTTLES.items():
        assert key in S.DEFAULT_SETTINGS
        assert S.DEFAULT_SETTINGS[key] is None
    assert not set(FOUR_THROTTLES) & set(TEN_BYTE_CAPS)


def _login_endpoint():
    from routes.auth_routes import setup_auth_routes
    auth_manager = MagicMock()
    auth_manager.verify_password.return_value = False
    router = setup_auth_routes(auth_manager)
    for route in router.routes:
        if getattr(route, "path", "") == "/api/auth/login" \
                and "POST" in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError("POST /api/auth/login is not registered")


def _attempt(endpoint) -> int:
    """One login attempt from one IP. Returns the HTTP status it produced."""
    from routes.auth_routes import LoginRequest
    request = SimpleNamespace(
        cookies={}, client=SimpleNamespace(host="203.0.113.7"),
        headers={}, url=SimpleNamespace(scheme="http"))
    try:
        asyncio.run(endpoint(body=LoginRequest(username="someone", password="hunter2xx"),
                             request=request, response=MagicMock()))
    except HTTPException as exc:
        return exc.status_code
    return 200


def test_an_admin_changing_the_login_limit_is_honoured_by_the_next_attempt(store):
    """`P12-05b`'s `Verify:` line, driven end to end.

    One router, built once, never rebuilt — so a pass here is a statement about
    a running process and not about an import.
    """
    store(auth_login_rate_limit=2)
    endpoint = _login_endpoint()

    assert _attempt(endpoint) == 401
    assert _attempt(endpoint) == 401
    assert _attempt(endpoint) == 429, "the third attempt must be refused at a limit of 2"

    store(auth_login_rate_limit=4)

    assert _attempt(endpoint) == 401, "raising the limit must be honoured with no restart"
    assert _attempt(endpoint) == 401
    assert _attempt(endpoint) == 429


def test_the_shipped_login_limit_is_still_fifteen_a_minute(store):
    """`Law 1`. Nothing stored means exactly what it meant before this row."""
    endpoint = _login_endpoint()
    assert [_attempt(endpoint) for _ in range(15)] == [401] * 15
    assert _attempt(endpoint) == 429


def test_a_login_throttle_cannot_be_switched_off(store):
    """`FORBIDDEN.md` Part 2 — the auth rate limiters never lift. The number is
    policy; the limiter is not, and there is no zero."""
    store(auth_login_rate_limit=0)
    endpoint = _login_endpoint()
    assert _attempt(endpoint) == 401
    assert _attempt(endpoint) == 429


def test_the_signup_and_setup_throttles_resolve_through_the_same_layers(store):
    from src.rate_limiter import RateLimiter
    limiter = RateLimiter(max_requests=3, window_seconds=300,
                          limit_key="auth_signup_rate_limit",
                          window_key="auth_signup_rate_window_seconds")
    assert limiter.effective() == (3, 300)
    store(auth_signup_rate_limit=9, auth_signup_rate_window_seconds=30)
    assert limiter.effective() == (9, 30)


def test_a_stored_upload_throttle_is_honoured_by_the_next_upload(store, tmp_path):
    from src.upload_handler import UploadHandler
    handler = UploadHandler(base_dir=str(tmp_path), upload_dir=str(tmp_path / "up"))
    assert handler.effective_upload_rate_limit() == handler.upload_rate_limit

    store(upload_rate_limit=1)
    assert handler.effective_upload_rate_limit() == 1

    handler.save_upload(_upload("one.txt", b"hello"), client_ip="198.51.100.4")
    with pytest.raises(HTTPException) as exc:
        handler.save_upload(_upload("two.txt", b"hello"), client_ip="198.51.100.4")
    assert exc.value.status_code == 429


def test_the_two_declared_upload_rate_limits_agree(tmp_path):
    """`P12-05b`'s reconciliation, pinned so it cannot drift apart again.

    `src/config.py` declared 5 and `UploadHandler` set 60. Nothing reads
    `SecurityConfig`'s fields — `app.py` hands `config` to
    `setup_search_routes`, which never looks at it — so 60 is the only one of
    the two that has ever executed, and 5 was an unreachable declaration.
    """
    from src.config import config
    from src.upload_handler import UploadHandler
    handler = UploadHandler(base_dir=str(tmp_path), upload_dir=str(tmp_path / "up"))
    assert config.security.upload_rate_limit == handler.upload_rate_limit == 60
    assert config.security.upload_rate_window == handler.upload_rate_window
    assert config.security.max_concurrent_uploads == handler.max_concurrent_uploads


def test_the_agent_may_read_the_auth_throttles_and_may_not_write_them(store):
    """A throttle prompt injection can raise is not a throttle.

    `FORBIDDEN.md` Part 2 lists the auth rate limiters as a control against
    credential stuffing, and declaring a key hands it to the agent as well as
    to the person — `DEFAULT_SETTINGS` is the allowlist for both.
    """
    from src.agent_tools.admin_tools import do_manage_settings
    out = asyncio.run(do_manage_settings(json.dumps(
        {"action": "set", "key": "auth_login_rate_limit", "value": 9999})))
    # The house shape for a self-restraint refusal is a sentence, not an error
    # code — what matters is that nothing moved.
    assert "guessing passwords" in out.get("response", "")
    assert S.load_settings().get("auth_login_rate_limit") is None
    assert S.resolve_limit("auth_login_rate_limit", 15, minimum=1) == (15, "built-in default")

    ok = asyncio.run(do_manage_settings(json.dumps(
        {"action": "get", "key": "auth_login_rate_limit"})))
    assert "error" not in ok

    # Capacity is not an auth gate: a byte cap stays writable on purpose.
    out = asyncio.run(do_manage_settings(json.dumps(
        {"action": "set", "key": "gallery_upload_max_bytes", "value": 12345})))
    assert out.get("exit_code") == 0, out
    assert UL.resolve_byte_limit("gallery_upload_max_bytes") == 12345


# ── Where a person actually sets one ───────────────────────────────────────

def _settings_endpoint():
    from routes.auth_routes import setup_auth_routes
    auth_manager = MagicMock()
    auth_manager.get_username_for_token.return_value = "admin"
    auth_manager.is_admin.return_value = True
    router = setup_auth_routes(auth_manager)
    for route in router.routes:
        if getattr(route, "path", "") == "/api/auth/settings" \
                and "POST" in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError("POST /api/auth/settings is not registered")


def _post_settings(endpoint, body):
    request = SimpleNamespace(cookies={"pantheon_session": "t"})

    async def _json():
        return body
    request.json = _json
    return asyncio.run(endpoint(request=request))


def test_an_admin_sets_a_limit_through_the_settings_store_that_already_exists(store, tmp_path, monkeypatch):
    """`Law 14`. No second settings system: the same admin-gated route that
    already writes every other setting writes these."""
    import src.settings as SS
    monkeypatch.setattr("core.atomic_io.atomic_write_json",
                        lambda path, data, **kw: Path(path).write_text(
                            json.dumps(data), encoding="utf-8"))
    endpoint = _settings_endpoint()

    out = _post_settings(endpoint, {"gallery_upload_max_bytes": 5_000_000,
                                    "auth_login_rate_limit": 4})
    assert out["gallery_upload_max_bytes"] == 5_000_000
    assert out["auth_login_rate_limit"] == 4
    SS._invalidate_caches()
    assert UL.resolve_byte_limit("gallery_upload_max_bytes") == 5_000_000


def test_the_route_clamps_rather_than_storing_a_number_it_will_not_honour(store, monkeypatch):
    """The stored value and the effective value must be the same number, or the
    panel lies about itself — the reasoning `otlp_interval_seconds` carries."""
    monkeypatch.setattr("core.atomic_io.atomic_write_json",
                        lambda path, data, **kw: Path(path).write_text(
                            json.dumps(data), encoding="utf-8"))
    endpoint = _settings_endpoint()
    out = _post_settings(endpoint, {"auth_login_rate_limit": 0,
                                    "gallery_upload_max_bytes": -1})
    assert out["auth_login_rate_limit"] == 1
    assert out["gallery_upload_max_bytes"] == 1


def test_null_is_how_a_limit_is_unset_again(store, monkeypatch):
    """`null` means "let the environment or the built-in default answer". A
    two-state field cannot express that, which is why these ship `None`."""
    monkeypatch.setattr("core.atomic_io.atomic_write_json",
                        lambda path, data, **kw: Path(path).write_text(
                            json.dumps(data), encoding="utf-8"))
    import src.settings as SS
    endpoint = _settings_endpoint()
    _post_settings(endpoint, {"ics_max_bytes": 4096})
    SS._invalidate_caches()
    assert UL.resolve_byte_limit("ics_max_bytes") == 4096

    _post_settings(endpoint, {"ics_max_bytes": None})
    SS._invalidate_caches()
    assert UL.resolve_byte_limit_with_source("ics_max_bytes") == \
        (UL.BYTE_LIMITS["ics_max_bytes"][1], "built-in default")


def test_a_limit_that_is_not_a_number_is_refused_at_the_door(store, monkeypatch):
    """`P17-09`'s lesson: a value stored and then silently ignored is worse
    than a refusal, because the operator believes they set a rule."""
    monkeypatch.setattr("core.atomic_io.atomic_write_json",
                        lambda path, data, **kw: Path(path).write_text(
                            json.dumps(data), encoding="utf-8"))
    endpoint = _settings_endpoint()
    with pytest.raises(HTTPException) as exc:
        _post_settings(endpoint, {"ics_max_bytes": "ten megabytes"})
    assert exc.value.status_code == 400
