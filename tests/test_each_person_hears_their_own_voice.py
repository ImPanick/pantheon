# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1730` — each person hears the voice they chose, everywhere Pantheon
speaks to them; `B1728` — a fresh install speaks with "Automatic", the best
voice the server has.

The owner, 2026-11-01, on the switch that makes the agent say its replies:
*"This should be a "Conversation" switch not speak replies aloud - we make it
personal-able"*. So the switch and the voice are each person's own
preferences (`PUT /api/prefs/conversation`, `/api/prefs/conversation_voice`),
and the voice service speaks to each person in theirs
(`services/tts/personal_voice.py`, `TTSService._resolve`): Conversation, the
read-aloud button and a voice chat all ask `POST /api/tts/synthesize`, which
reads who is asking. An admin's part is the server's voice (Settings → Voice),
which everyone who chose none hears, and whether this server speaks at all.

"Automatic" (`auto`, the default) is Chatterbox while its GPU sidecar answers,
else Kokoro on this server's processor, else Piper (`AUTO_ORDER`).

Driven (`Law 20`) through the real routes behind the real auth manager's
sessions (`tests/test_the_workstation_is_admin_controlled.py`'s fixtures), the
real `TTSService` and settings file, the real preference store, the real
Chatterbox sidecar over HTTP (`tests/helpers/chatterbox_sidecar.py`) and the
real `KokoroEngine`. The stand-ins are the models themselves: Kokoro's ONNX
session and phonemes, Piper's voice, and Chatterbox's network.
"""
from __future__ import annotations

import base64
import json
import sys
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers.chatterbox_sidecar import URL, Clock, Sidecar, wav_info
from tests.test_kokoro_speaks_on_the_processor import _Session, _voices_file
from tests.test_piper_asks_before_it_downloads import VOICE as PIPER_VOICE, _Piper, _bake
from tests.test_the_workstation_is_admin_controlled import (  # noqa: F401  (fixtures)
    ADMIN, ALLOWED, PLAIN, auth, datadir,
)

CY, BOB = ALLOWED, PLAIN   # two members; ADMIN is the admin


def _settings(**values):
    import src.settings as S
    with open(S.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(values, f)
    S._invalidate_caches()


class _World:
    def __init__(self, app, auth, side, clock, sessions, phonemes, piper, kokoro_model, seed):
        self.app, self.auth, self.side, self.clock = app, auth, side, clock
        self.sessions, self.phonemes, self.piper = sessions, phonemes, piper
        self.kokoro_model, self.seed = kokoro_model, seed

    def person(self, name):
        from routes.auth_routes import SESSION_COOKIE
        client = TestClient(self.app)
        client.cookies.set(SESSION_COOKIE, self.auth.tokens[name])
        return client

    def chatterbox(self, up: bool):
        """The sidecar started or stopped, and half a minute gone by, so
        Pantheon has asked it again."""
        self.side.up = up
        self.clock.now += 31

    def warmed(self):
        for t in threading.enumerate():
            if t.name == "tts-warm-kokoro":
                t.join(5)
        return len(self.sessions)


@pytest.fixture
def world(auth, datadir, monkeypatch, tmp_path):
    import routes.prefs_routes as prefs
    import services.tts.tts_service as T
    from routes.auth_routes import SESSION_COOKIE
    from routes.tts_routes import setup_tts_routes
    from services.tts import kokoro_cpu as K

    monkeypatch.setattr(prefs, "PREFS_FILE", str(tmp_path / "user_prefs.json"))
    seed = tmp_path / "seed"
    monkeypatch.setenv("PANTHEON_SEED_MODELS", str(seed))
    monkeypatch.delenv("PANTHEON_ALLOW_MODEL_DOWNLOAD", raising=False)

    # Piper, installed, with the voice the image bakes.
    piper = _Piper()
    monkeypatch.setitem(sys.modules, "piper", piper.module)
    _bake(seed / "piper")

    # Kokoro's two files where the image bakes them, at the sizes expected,
    # spoken through the real engine with a stand-in for the model.
    folder = seed / "kokoro"
    folder.mkdir(parents=True)
    model = folder / K.KOKORO_MODEL
    model.write_bytes(b"onnx")
    voices = _voices_file(folder / K.KOKORO_VOICES)
    monkeypatch.setattr(K, "KOKORO_FILES", {K.KOKORO_MODEL: ("-", model.stat().st_size),
                                            K.KOKORO_VOICES: ("-", voices.stat().st_size)})
    phonemes = []
    monkeypatch.setattr(K, "phonemize", lambda text, language="en-us": (
        phonemes.append((text, language)), ["hˈaɪ."])[1])
    sessions = []

    def session(path):
        sessions.append(_Session(path))
        return sessions[-1]
    monkeypatch.setattr(T, "KokoroEngine", lambda: K.KokoroEngine(session_factory=session))

    # Chatterbox's sidecar, up, where the NVIDIA overlay points Pantheon.
    side = Sidecar(tmp_path / "chatterbox-voices").wait_loaded()
    clock = Clock()
    monkeypatch.setenv("PANTHEON_CHATTERBOX_URL", URL)
    monkeypatch.setattr(T, "ChatterboxClient", lambda: side.client(clock))

    service = T.TTSService(cache_dir=str(tmp_path / "tts-cache"))
    app = FastAPI()

    @app.middleware("http")
    async def _authenticate(request, call_next):
        request.state.current_user = auth.get_username_for_token(request.cookies.get(SESSION_COOKIE))
        return await call_next(request)

    app.include_router(setup_tts_routes(service))
    app.include_router(prefs.setup_prefs_routes())
    return _World(app, auth, side, clock, sessions, phonemes, piper, model, seed)


def _say(client, text, **body):
    return client.post("/api/tts/synthesize", json={"text": text, "format": "audio", **body})


def _keep(client, voice):
    r = client.put("/api/prefs/conversation_voice", json={"value": voice})
    assert r.status_code == 200, r.text
    return r.json()["value"]


# ── "Automatic" ──


def test_a_fresh_install_speaks_with_chatterbox_then_kokoro_then_piper(world, monkeypatch):
    bob = world.person(BOB)
    stats = bob.get("/api/tts/stats?for=server").json()
    assert (stats["chosen"], stats["provider"], stats["voice"], stats["available"]) == (
        "auto", "chatterbox", "default", True), "no settings file: Automatic, and the GPU's voice"
    assert stats["device"] == "cuda (Stand-in GPU)" and stats["model"] == "Chatterbox Turbo"
    r = _say(bob, "First.")
    assert r.status_code == 200 and r.headers["X-Pantheon-Voice"] == "chatterbox/default"
    assert world.side.model.generated == [("First.", "built-in")]

    world.chatterbox(up=False)
    stats = bob.get("/api/tts/stats?for=server").json()
    assert (stats["provider"], stats["voice"], stats["model"]) == ("kokoro", "af_heart", "Kokoro")
    assert stats["labels"]["af_heart"] == "Heart · American English, woman" and len(stats["voices"]) == 41
    r = _say(bob, "Second.")
    assert r.status_code == 200 and r.headers["X-Pantheon-Voice"] == "kokoro/af_heart"
    assert wav_info(r.content)["rate"] == 24000

    world.kokoro_model.unlink()
    r = _say(bob, "Third.")
    assert r.status_code == 200 and r.headers["X-Pantheon-Voice"] == f"piper/{PIPER_VOICE}"
    assert world.piper.said[-1][:2] == (f"{PIPER_VOICE}.onnx", "Third.")

    for path in (world.seed / "piper").iterdir():
        path.unlink()
    stats = bob.get("/api/tts/stats?for=server").json()
    assert (stats["provider"], stats["available"]) == ("auto", False)
    assert "Speaking with Kokoro needs its model (about 350 MB)" in stats["unavailable_reason"]
    assert "Download models from the internet" in stats["unavailable_reason"]
    r = _say(bob, "Fourth.")
    assert r.status_code == 503 and r.json()["detail"]["message"] == stats["unavailable_reason"]

    monkeypatch.setitem(sys.modules, "piper", None)   # and the voice packages not installed at all
    reason = bob.get("/api/tts/stats?for=server").json()["unavailable_reason"]
    assert "requirements-voice.txt" in reason, reason


def test_automatic_never_speaks_with_the_browsers_voices_on_its_own(world):
    from services.tts.tts_service import AUTO_ORDER
    assert AUTO_ORDER == ("chatterbox", "kokoro", "piper")
    assert "browser" not in AUTO_ORDER, "in Chrome those are Google's online voices (`B1564`)"


@pytest.mark.parametrize(("before", "now"), [
    ({}, "auto"),
    ({"tts_provider": "disabled"}, "auto"),
    ({"tts_enabled": True, "tts_provider": "disabled"}, "auto"),
    ({"tts_enabled": False, "tts_provider": "disabled"}, "disabled"),
    ({"tts_provider": "piper"}, "piper"),
    ({"tts_provider": "browser", "tts_voice": "Daniel"}, "browser"),
], ids=["nothing-saved", "the-old-default", "the-old-default-with-speech-on", "speech-turned-off",
        "piper-chosen", "the-browsers-chosen"])
def test_a_settings_file_written_before_automatic_reads_as_it_meant(datadir, before, now):
    """"disabled" with speech on was the old default written down by a save
    of the whole dict, never a choice: no page could choose a voice before
    `B1718`, and its "None" saves `tts_enabled: false`."""
    from services.tts.tts_service import TTSService
    import src.settings as S
    _settings(**before)
    assert S.load_settings()["tts_provider"] == now
    assert TTSService(cache_dir=str(datadir / "c")).get_stats()["chosen"] == now


def test_with_no_settings_file_at_all_the_voice_is_automatic(datadir):
    import os
    import src.settings as S
    assert not os.path.exists(S.SETTINGS_FILE)
    S._invalidate_caches()
    assert S.load_settings()["tts_provider"] == S.DEFAULT_SETTINGS["tts_provider"] == "auto"


# ── Each person's own ──


def test_each_person_hears_the_voice_they_chose_and_the_rest_hear_the_servers(world):
    cy, bob = world.person(CY), world.person(BOB)
    kept = _keep(cy, {"engine": "kokoro", "voice": " bf_emma ", "speed": 1.25})
    assert kept == {"engine": "kokoro", "voice": "bf_emma", "speed": 1.25}

    r = _say(cy, "Hello, Cy.")
    assert r.status_code == 200 and r.headers["X-Pantheon-Voice"] == "kokoro/bf_emma"
    feed = world.sessions[0].feeds[-1]
    assert feed["speed"].tolist() == [1.25], "at the speed Cy chose"
    assert feed["style"][0][0] == 100 + len("hˈaɪ.") - 1, "in Emma's own styles"
    assert world.phonemes[-1] == ("Hello, Cy.", "en-gb-x-rp"), "with Emma's own accent"

    r = _say(bob, "Hello, Bob.")
    assert r.status_code == 200 and r.headers["X-Pantheon-Voice"] == "chatterbox/default"
    assert world.side.model.generated[-1] == ("Hello, Bob.", "built-in"), "Bob chose none: the server's"

    mine = cy.get("/api/tts/stats").json()
    assert (mine["provider"], mine["voice"], mine["speed"], mine["available"]) == ("kokoro", "bf_emma", 1.25, True)
    assert mine["personal"] == {"engine": "kokoro", "voice": "bf_emma", "speed": 1.25}
    assert "personal_reason" not in mine
    assert cy.get("/api/tts/stats?for=server").json()["provider"] == "chatterbox", "the admin card's own"
    theirs = bob.get("/api/tts/stats").json()
    assert theirs["provider"] == "chatterbox" and "personal" not in theirs

    b64 = cy.post("/api/tts/synthesize", json={"text": "In a call.", "format": "base64"}).json()["audio"]
    assert wav_info(base64.b64decode(b64))["rate"] == 24000 and world.phonemes[-1][1] == "en-gb-x-rp"


def test_a_voice_that_cannot_speak_here_now_falls_back_to_the_servers_and_says_why(world):
    cy = world.person(CY)
    _keep(cy, {"engine": "chatterbox", "voice": "default"})
    assert _say(cy, "On the GPU.").headers["X-Pantheon-Voice"] == "chatterbox/default"
    world.chatterbox(up=False)
    r = _say(cy, "The GPU is gone.")
    assert r.status_code == 200 and r.headers["X-Pantheon-Voice"] == "kokoro/af_heart", (
        "the server's voice, not silence")
    stats = cy.get("/api/tts/stats").json()
    assert stats["provider"] == "kokoro" and stats["personal"]["engine"] == "chatterbox"
    assert stats["personal_reason"].startswith("Chatterbox is not running."), stats["personal_reason"]
    world.chatterbox(up=True)
    assert _say(cy, "The GPU is back.").headers["X-Pantheon-Voice"] == "chatterbox/default"


def test_a_voice_name_an_engine_does_not_have_is_its_own_default(world):
    cy = world.person(CY)
    _keep(cy, {"engine": "kokoro", "voice": "Grandad"})
    assert _say(cy, "Who?").headers["X-Pantheon-Voice"] == "kokoro/af_heart"
    _keep(cy, {"engine": "piper", "voice": PIPER_VOICE, "speed": 2})
    r = _say(cy, "Quickly.")
    assert r.headers["X-Pantheon-Voice"] == f"piper/{PIPER_VOICE}"
    assert world.piper.said[-1] == (f"{PIPER_VOICE}.onnx", "Quickly.", 0.5), "twice as fast is half the length"


def test_the_browsers_own_voices_are_the_pages_to_speak(world):
    cy = world.person(CY)
    _keep(cy, {"engine": "browser", "voice": "Samantha"})
    stats = cy.get("/api/tts/stats").json()
    assert (stats["provider"], stats["voice"], stats["available"]) == ("browser", "Samantha", True)
    r = _say(cy, "Said by the page.")
    assert r.status_code == 500
    assert r.json()["detail"]["message"] == "This voice is the browser's own: the page speaks it, not this server."
    r = _say(cy, "A preview.", engine="browser", voice="Samantha")
    assert r.status_code == 400
    assert r.json()["detail"]["message"] == "The browser's own voices speak in the browser, not on this server."
    assert world.side.model.generated == [] and world.sessions == [], "nothing was spoken on the server"


def test_hear_it_plays_a_voice_without_keeping_it(world):
    cy = world.person(CY)
    _keep(cy, {"engine": "kokoro", "voice": "bf_emma"})
    r = _say(cy, "How does Heart sound?", engine="kokoro", voice="af_heart", speed=0.9)
    assert r.status_code == 200 and r.headers["X-Pantheon-Voice"] == "kokoro/af_heart"
    assert world.sessions[0].feeds[-1]["speed"].tolist() == [pytest.approx(0.9)]
    assert cy.get("/api/prefs/conversation_voice").json()["value"]["voice"] == "bf_emma", "kept as it was"
    # The admin's Voice page hears the server's voice, whatever the admin chose for themself.
    admin = world.person(ADMIN)
    _keep(admin, {"engine": "kokoro", "voice": "bf_emma"})
    assert _say(admin, "The server's voice.", engine="").headers["X-Pantheon-Voice"] == "chatterbox/default"
    assert _say(cy, "Not a voice.", engine="local").status_code == 400


def test_the_switch_and_the_voice_are_each_persons_own(world):
    cy, bob = world.person(CY), world.person(BOB)
    assert cy.put("/api/prefs/conversation", json={"value": True}).json() == {"key": "conversation", "value": True}
    _keep(cy, {"engine": "kokoro", "voice": "bf_emma"})
    assert cy.get("/api/prefs/conversation").json()["value"] is True
    assert bob.get("/api/prefs/conversation").json()["value"] is None
    assert bob.get("/api/prefs/conversation_voice").json()["value"] is None
    assert bob.put("/api/prefs/conversation", json={"value": False}).status_code == 200
    assert cy.get("/api/prefs/conversation").json()["value"] is True, "Bob's off is Bob's"


@pytest.mark.parametrize(("key", "value", "said"), [
    ("conversation", "yes", "Conversation is on (true) or off (false)."),
    ("conversation", 1, "Conversation is on (true) or off (false)."),
    ("conversation_voice", "kokoro", "Your voice is an object of engine, voice and speed."),
    ("conversation_voice", {"engine": "local"}, "is not a voice you can choose"),
    ("conversation_voice", {"engine": "endpoint:abc"}, "is not a voice you can choose"),
    ("conversation_voice", {"engine": "kokoro", "voice": "x" * 121}, "That voice's name is not one."),
    ("conversation_voice", {"engine": "kokoro", "voice": 7}, "That voice's name is not one."),
    ("conversation_voice", {"engine": "kokoro", "speed": 3}, "Speed is between 0.5× and 2×."),
    ("conversation_voice", {"engine": "kokoro", "speed": True}, "Speed is a number, like 1 or 1.25."),
    ("conversation_voice", {"engine": "kokoro", "speed": "fast"}, "Speed is a number, like 1 or 1.25."),
])
def test_what_a_person_keeps_is_held_to_its_shape(world, key, value, said):
    cy = world.person(CY)
    before = cy.get(f"/api/prefs/{key}").json()["value"]
    r = cy.put(f"/api/prefs/{key}", json={"value": value})
    assert r.status_code == 400 and said in r.json()["detail"], r.text
    assert cy.get(f"/api/prefs/{key}").json()["value"] == before


def test_none_is_the_servers_voice_and_a_hand_written_value_is_never_an_error(world, tmp_path):
    cy = world.person(CY)
    assert _keep(cy, {}) is None and _keep(cy, None) is None
    assert _keep(cy, {"engine": "", "voice": "", "speed": 1.5}) == {"engine": "", "voice": "", "speed": 1.5}
    world.chatterbox(up=False)
    _say(cy, "At my speed.")
    assert world.sessions[0].feeds[-1]["speed"].tolist() == [1.5], "the server's voice at my own speed"
    # A value written by hand, or by an older build, is the server's voice.
    import routes.prefs_routes as prefs
    store = json.loads(open(prefs.PREFS_FILE, encoding="utf-8").read())
    store["_users"][CY]["conversation_voice"] = {"engine": "a-voice-that-is-not", "speed": "fast"}
    with open(prefs.PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f)
    r = _say(cy, "Still speaking.")
    assert r.status_code == 200 and r.headers["X-Pantheon-Voice"] == "kokoro/af_heart"


# ── What a person may choose ──


def test_the_voices_on_offer_say_which_speak_here_and_why_not(world):
    world.chatterbox(up=False)
    offer = world.person(BOB).get("/api/tts/voices").json()
    assert offer["off"] is False
    assert offer["server"] == {"chosen": "auto", "provider": "kokoro", "voice": "af_heart",
                               "label": "Kokoro, Heart · American English, woman", "available": True}
    engines = {e["id"]: e for e in offer["engines"]}
    assert list(engines) == ["kokoro", "chatterbox", "piper"]
    kokoro = engines["kokoro"]
    assert (kokoro["available"], kokoro["reason"], kokoro["default"]) == (True, None, "af_heart")
    assert len(kokoro["voices"]) == 41 and kokoro["voices"][0] == {
        "id": "af_heart", "label": "Heart · American English, woman", "language": "American English",
        "gender": "woman"}
    assert {v["language"] for v in kokoro["voices"]} == {
        "American English", "British English", "Spanish", "French", "Hindi", "Italian", "Brazilian Portuguese"}
    assert engines["chatterbox"]["available"] is False and engines["chatterbox"]["voices"] == []
    assert engines["chatterbox"]["reason"].startswith("Chatterbox is not running.")
    assert engines["chatterbox"]["where"] == "on this server's GPU"
    assert engines["piper"]["available"] is True
    assert engines["piper"]["voices"] == [{"id": PIPER_VOICE, "label": PIPER_VOICE}]

    world.chatterbox(up=True)
    offer = world.person(BOB).get("/api/tts/voices").json()
    assert offer["server"]["provider"] == "chatterbox" and offer["server"]["label"] == "Chatterbox"
    chatterbox = {e["id"]: e for e in offer["engines"]}["chatterbox"]
    assert chatterbox["available"] is True and chatterbox["voices"] == [{"id": "default", "label": "Chatterbox"}]


def test_speech_turned_off_is_off_for_everyone_whatever_they_chose(world):
    cy = world.person(CY)
    _keep(cy, {"engine": "kokoro", "voice": "bf_emma"})
    _settings(tts_enabled=False, tts_provider="disabled")
    assert _say(cy, "Anyone there?").status_code == 503
    assert cy.get("/api/tts/stats").json()["available"] is False
    offer = cy.get("/api/tts/voices").json()
    assert offer["off"] is True and offer["engines"] == []
    assert "an admin chose “None” in Settings → Voice" in offer["reason"]
    assert world.sessions == [] and world.side.model.generated == []


# ── Conversation on: the voice is ready for the first reply ──


def test_conversation_on_loads_the_voice_before_the_first_reply(world):
    bob = world.person(BOB)
    world.chatterbox(up=False)        # the server's voice is Kokoro, which takes a moment to load
    assert bob.get("/api/tts/stats").json()["voice_loaded"] is False
    assert world.warmed() == 0, "Conversation off: nothing is loaded for nobody"
    assert bob.put("/api/prefs/conversation", json={"value": True}).status_code == 200
    bob.get("/api/tts/stats")
    assert world.warmed() == 1, "on: loaded now, in the background"
    assert bob.get("/api/tts/stats").json()["voice_loaded"] is True


def test_a_voice_call_asks_for_the_voice_to_be_loaded_as_it_starts(world):
    world.chatterbox(up=False)
    cy = world.person(CY)
    cy.get("/api/tts/stats?warm=1")
    assert world.warmed() == 1
