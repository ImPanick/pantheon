# SPDX-License-Identifier: AGPL-3.0-or-later
"""Centralized upload byte-limits (issue #3364).

Every per-route upload limit lives in ``src.upload_limits`` as a module-level
constant read through the validated ``read_byte_limit_env``. These tests pin:
- the default values (unchanged from the prior per-route literals),
- env-overridability for each one,
- that an invalid env value fails fast (validation), and
- that the routes import the constant from upload_limits rather than redefining
  it locally (no scattered raw getenv / hardcoded literal).
"""

import importlib
from pathlib import Path

import pytest

import src.upload_limits as upload_limits

REPO = Path(__file__).resolve().parent.parent

# const name -> (env var, default bytes)
_LIMITS = {
    "GALLERY_UPLOAD_MAX_BYTES": ("PANTHEON_GALLERY_UPLOAD_MAX_BYTES", 100 * 1024 * 1024),
    "GALLERY_TRANSFORM_UPLOAD_MAX_BYTES": ("PANTHEON_GALLERY_TRANSFORM_UPLOAD_MAX_BYTES", 25 * 1024 * 1024),
    "MEMORY_IMPORT_MAX_BYTES": ("PANTHEON_MEMORY_IMPORT_MAX_BYTES", 10 * 1024 * 1024),
    "PERSONAL_UPLOAD_MAX_BYTES": ("PANTHEON_PERSONAL_UPLOAD_MAX_BYTES", 25 * 1024 * 1024),
    "EMAIL_COMPOSE_UPLOAD_MAX_BYTES": ("PANTHEON_EMAIL_COMPOSE_UPLOAD_MAX_BYTES", 25 * 1024 * 1024),
    "STT_MAX_AUDIO_BYTES": ("PANTHEON_STT_MAX_AUDIO_BYTES", 25 * 1024 * 1024),
    "ICS_MAX_BYTES": ("PANTHEON_ICS_MAX_BYTES", 10 * 1024 * 1024),
}


def _reload_clean(monkeypatch):
    """Reload upload_limits with all the limit env vars unset."""
    for env, _ in _LIMITS.values():
        monkeypatch.delenv(env, raising=False)
    return importlib.reload(upload_limits)


@pytest.fixture(autouse=True)
def _restore_module():
    # Ensure later tests see the env-default module, not a test-mutated reload.
    yield
    importlib.reload(upload_limits)


@pytest.mark.parametrize("name,env,default", [(n, e, d) for n, (e, d) in _LIMITS.items()])
def test_default_value(monkeypatch, name, env, default):
    mod = _reload_clean(monkeypatch)
    assert getattr(mod, name) == default


@pytest.mark.parametrize("name,env,default", [(n, e, d) for n, (e, d) in _LIMITS.items()])
def test_env_override(monkeypatch, name, env, default):
    for e, _ in _LIMITS.values():
        monkeypatch.delenv(e, raising=False)
    monkeypatch.setenv(env, "4242")
    mod = importlib.reload(upload_limits)
    assert getattr(mod, name) == 4242


@pytest.mark.parametrize("env", [e for e, _ in _LIMITS.values()])
def test_invalid_env_fails_fast(monkeypatch, env):
    for e, _ in _LIMITS.values():
        monkeypatch.delenv(e, raising=False)
    monkeypatch.setenv(env, "not-an-int")
    with pytest.raises(ValueError, match=env):
        importlib.reload(upload_limits)


@pytest.mark.parametrize("env", [e for e, _ in _LIMITS.values()])
def test_non_positive_env_rejected(monkeypatch, env):
    for e, _ in _LIMITS.values():
        monkeypatch.delenv(e, raising=False)
    monkeypatch.setenv(env, "0")
    with pytest.raises(ValueError, match="greater than 0"):
        importlib.reload(upload_limits)


def test_routes_import_from_upload_limits_not_local_defs():
    """Routes must import the constant, not redefine it via raw getenv / literal."""
    forbidden = {
        "routes/gallery/gallery_routes.py": [
            'int(os.getenv("PANTHEON_GALLERY_UPLOAD_MAX_BYTES"',
            'int(os.getenv("PANTHEON_GALLERY_TRANSFORM_UPLOAD_MAX_BYTES"',
        ],
        "routes/memory/memory_routes.py": ['int(os.getenv("PANTHEON_MEMORY_IMPORT_MAX_BYTES"'],
        "routes/personal_routes.py": ['os.getenv("PANTHEON_PERSONAL_UPLOAD_MAX_BYTES"'],
        "routes/email_routes.py": ["EMAIL_COMPOSE_UPLOAD_MAX_BYTES = 25 * 1024 * 1024"],
        "routes/stt_routes.py": ["STT_MAX_AUDIO_BYTES = 25 * 1024 * 1024"],
        "routes/calendar_routes.py": ["_ICS_MAX_BYTES = 10 * 1024 * 1024"],
    }
    for path, needles in forbidden.items():
        text = (REPO / path).read_text(encoding="utf-8")
        for needle in needles:
            assert needle not in text, f"{path} still defines limit locally: {needle}"

    # And each gets its cap from upload_limits. `P12-03` moved the routes off
    # the import-time constants and onto `resolve_byte_limit("<key>")`, which
    # re-reads role profile → instance setting → env → built-in default on every
    # request; the property this half of the test protects — the number is not
    # defined locally — is unchanged, so the assertion names the key instead of
    # the constant. The keys are checked against the registry rather than being
    # a second list of strings (`Law 13`).
    keys = {
        "routes/gallery/gallery_routes.py": "gallery_upload_max_bytes",
        "routes/memory/memory_routes.py": "memory_import_max_bytes",
        "routes/personal_routes.py": "personal_upload_max_bytes",
        "routes/email_routes.py": "email_compose_upload_max_bytes",
        "routes/stt_routes.py": "stt_max_audio_bytes",
        "routes/calendar_routes.py": "ics_max_bytes",
    }
    for path, key in keys.items():
        text = (REPO / path).read_text(encoding="utf-8")
        assert "from src.upload_limits import" in text
        assert key in upload_limits.BYTE_LIMITS, f"{key!r} left the registry"
        assert f'resolve_byte_limit("{key}")' in text, (
            f"{path} no longer resolves {key} through src.upload_limits")
