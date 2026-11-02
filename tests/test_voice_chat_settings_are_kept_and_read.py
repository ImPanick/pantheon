# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1718` — the voice chat's settings: an admin sets them in Settings →
Voice, a value the voice chat could not read is refused at the door, and the
speech-to-text status says them to whoever asks.

Four keys: `voice_chat_enabled` (the call button beside Send; on as shipped,
because it does nothing until pressed and a press with nothing set up says
where to set it), `voice_chat_pause` (how long a silence ends a turn, the
three `static/js/voiceCapture.js` knows), `voice_chat_barge_in` (talking over
the agent stops it; off is taking turns) and `tts_read_aloud` (the read-aloud
button under each reply, off as shipped, because choosing a voice for voice
chat must not bring it under every reply by itself; an install that had a voice
chosen before the switch existed keeps its button).

`GET /api/stt/stats` carries the first three as `voice_chat`: it is what the
call button and a starting call already read, so neither asks twice, and a
member who may not read the admin's settings still gets them.

Driven (`Law 20`) through the real settings route behind the real auth
manager (`tests/test_the_workstation_is_admin_controlled.py`'s fixtures) and
the real `STTService` reading the settings file the route wrote.
"""
from __future__ import annotations

import pytest

from tests.test_the_workstation_is_admin_controlled import (  # noqa: F401  (fixtures)
    ADMIN, PLAIN, app, as_user, auth, datadir, stored,
)

KEYS = ("voice_chat_enabled", "voice_chat_pause", "voice_chat_barge_in", "tts_read_aloud")


def _voice_chat():
    from services.stt.stt_service import STTService
    return STTService().get_stats()["voice_chat"]


def test_as_shipped_voice_chat_is_on_and_read_aloud_is_off(app):
    assert [stored(k) for k in KEYS] == [True, "normal", True, False]
    assert _voice_chat() == {"enabled": True, "pause": "normal", "barge_in": True}


def test_an_admin_sets_each_and_the_status_says_it(app):
    admin = as_user(app, ADMIN)
    r = admin.post("/api/auth/settings", json={"voice_chat_enabled": False, "voice_chat_pause": " Relaxed ",
                                               "voice_chat_barge_in": False, "tts_read_aloud": True})
    assert r.status_code == 200, r.text
    assert [stored(k) for k in KEYS] == [False, "relaxed", False, True], "the pause is stored as it is read"
    assert _voice_chat() == {"enabled": False, "pause": "relaxed", "barge_in": False}


def test_a_member_may_not_set_them(app):
    r = as_user(app, PLAIN).post("/api/auth/settings", json={"voice_chat_enabled": False})
    assert r.status_code == 403
    assert stored("voice_chat_enabled") is True


@pytest.mark.parametrize("key, value, said", [
    ("voice_chat_pause", "slow", "voice_chat_pause must be one of: short, normal, relaxed"),
    ("voice_chat_pause", 2, "voice_chat_pause must be one of: short, normal, relaxed"),
    ("voice_chat_enabled", "false", "voice_chat_enabled must be true or false"),
    ("voice_chat_barge_in", 0, "voice_chat_barge_in must be true or false"),
    ("tts_read_aloud", "yes", "tts_read_aloud must be true or false"),
])
def test_a_value_the_voice_chat_could_not_read_is_refused(app, key, value, said):
    """A string `"false"` would store, read as on, and switch nothing off."""
    before = stored(key)
    r = as_user(app, ADMIN).post("/api/auth/settings", json={key: value})
    assert r.status_code == 400 and r.json()["detail"] == said
    assert stored(key) == before


def _write_older_file(before):
    """A settings file as an install wrote it before `tts_read_aloud` existed."""
    import json

    import src.settings as S
    with open(S.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(before, f)
    S._invalidate_caches()


@pytest.mark.parametrize("before, kept", [
    ({"tts_enabled": True, "tts_provider": "endpoint:ep1"}, True),
    ({"tts_provider": "browser"}, True),
    ({"tts_enabled": False, "tts_provider": "piper"}, False),
    ({"tts_provider": "disabled"}, False),
    ({}, False),
    ({"tts_provider": "piper", "tts_read_aloud": False}, False),
], ids=["a-voice-chosen", "the-browsers-voice", "speech-switched-off", "no-voice", "nothing-saved",
        "already-answered"])
def test_an_install_that_had_read_aloud_keeps_its_button(app, before, kept):
    """Read-aloud had no switch: its button showed under every reply whenever
    a voice was chosen. An install upgraded with a voice chosen keeps it."""
    _write_older_file(before)
    assert stored("tts_read_aloud") is kept


def test_choosing_a_voice_for_voice_chat_does_not_bring_read_aloud_with_it(app):
    """The first save writes the answer down, so a voice chosen after it is a
    voice for the call, and the button stays as it was until it is switched."""
    _write_older_file({"tts_provider": "disabled"})
    admin = as_user(app, ADMIN)
    assert admin.post("/api/auth/settings", json={"tts_provider": "piper"}).status_code == 200
    assert stored("tts_provider") == "piper" and stored("tts_read_aloud") is False
    assert admin.post("/api/auth/settings", json={"tts_read_aloud": True}).status_code == 200
    assert stored("tts_read_aloud") is True


def test_a_pause_written_by_hand_that_is_not_one_reads_as_normal(app):
    """The settings file can be edited by hand or by an agent; the status
    answers a pause the call knows."""
    import src.settings as S
    saved = S.load_settings()
    saved["voice_chat_pause"] = "forever"
    saved["voice_chat_enabled"] = "no"
    S.save_settings(saved)
    assert _voice_chat()["pause"] == "normal"
    assert _voice_chat()["enabled"] is True, "only a stored false turns it off"
