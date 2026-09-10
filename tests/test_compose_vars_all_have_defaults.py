# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B63` — every compose variable must ship a default, or every command warns.

Found during the 2026-09-10 rebuild. `docker compose` printed

    warning: The "PANTHEON_TTS_CACHE_MAX_BYTES" variable is not set.
             Defaulting to a blank string.

on **every single command** — `ps`, `build`, `up`, all of them. One variable of
roughly sixty was written `${VAR}` where the rest are `${VAR:-something}`.

The behaviour underneath is already correct and that is worth stating plainly:
compose sets the name to an *empty string* rather than leaving it unset, so
`os.getenv(name, default)` returns `""` and the Python default never fires —
`int("")` raises. `services/tts/tts_service.py` already catches that and falls
back to 500 MB, so nothing crashed. This is the **inverse** of `H06`/`B20`,
where a truthy default made the env layer dead code; here a present-but-empty
env value makes the *code's* default dead. Worth a test either way, because the
next such variable will not necessarily have someone's try/except waiting.

The real cost was the warning. A tool that prints a warning on every invocation
teaches its operator to stop reading warnings, and the next one will be real.
"""

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_COMPOSE = sorted(_REPO.glob("docker-compose*.yml"))

# `${VAR}` with no `:-` and no `-` fallback.
_NO_DEFAULT = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def test_there_are_compose_files_to_check():
    # Without this the sweep below passes by finding nothing.
    assert _COMPOSE, "no docker-compose files found"


@pytest.mark.parametrize("path", _COMPOSE, ids=lambda p: p.name)
def test_every_variable_has_a_default(path):
    text = path.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    bare = sorted(set(_NO_DEFAULT.findall(code)))
    assert not bare, (
        f"{path.name}: {bare} have no `:-` default, so compose warns on every "
        "command and sets them to an empty string — which is *present* and "
        "therefore beats any default the code has"
    )


def test_the_tts_cache_limit_keeps_its_number_in_one_place():
    """`Law 13`. The fix is `${VAR:-}` and not `${VAR:-524288000}` on purpose:
    the number belongs to the code that uses it, and writing it into three
    compose files would be three more places to change it."""
    service = (_REPO / "services" / "tts" / "tts_service.py").read_text(encoding="utf-8")
    assert "500 * 1024 * 1024" in service, "the TTS default moved; this test names its home"
    for path in _COMPOSE:
        # Comments stripped: the fix's own comment explains why the number is
        # *not* written here, and a naive substring test fails on the prose
        # documenting the very rule it checks (`Law 20`, third time this week).
        code = "\n".join(ln for ln in path.read_text(encoding="utf-8").splitlines()
                         if not ln.lstrip().startswith("#"))
        assert "524288000" not in code, f"{path.name} now carries the TTS cache number too"


def test_an_empty_env_value_still_lands_on_the_documented_default(monkeypatch):
    """The behaviour the warning was hiding, pinned so it stays true.

    Compose exports the name with an empty value, so `os.getenv(name, default)`
    hands back `""` and `int("")` raises. Something has to catch that, and the
    something is easy to delete during a tidy-up because it looks defensive
    rather than load-bearing."""
    import os

    monkeypatch.setenv("PANTHEON_TTS_CACHE_MAX_BYTES", "")
    assert os.getenv("PANTHEON_TTS_CACHE_MAX_BYTES", 500 * 1024 * 1024) == "", (
        "an empty env value is present, so it beats the default — this is the whole bug")
    with pytest.raises(ValueError):
        int(os.getenv("PANTHEON_TTS_CACHE_MAX_BYTES", 500 * 1024 * 1024))

    service = (_REPO / "services" / "tts" / "tts_service.py").read_text(encoding="utf-8")
    guarded = re.search(
        r"try:\s*\n\s*self\.max_cache_bytes = int\(os\.getenv\(\s*\n?\s*"
        r'"PANTHEON_TTS_CACHE_MAX_BYTES".*?\n\s*except ValueError:',
        service, re.S)
    assert guarded, (
        "the ValueError guard in tts_service is gone — with compose exporting an "
        "empty string, that guard is what keeps the 500 MB default reachable")
