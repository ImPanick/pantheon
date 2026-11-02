# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1718` — a voice chat hears when the person starts and stops talking,
in the room they are in.

`TurnDetector` (`static/js/voiceCapture.js`) is fed one 20 ms frame at a
time. It learns the room's own noise first (the quieter third of what it
hears, so a word said while it learns does not become the room), calls a
frame speech when it is well above that floor, and the turn over when it has
been back near the floor for the pause chosen in Settings. A sound too short
to be words is let go; so is one too steady to be words (a fan switched on),
whose level becomes the floor. While the agent talks it asks for louder and
longer speech (`setStrict`). A turn is sent with what came just before its
first loud frame (the start of the first word) and a little of the pause.

`encodeWav` writes a turn as the 16-bit mono WAV every speech-to-text this
server uses reads.

Driven (`Law 20`): the real module under node, fed frames at given levels.
"""
from __future__ import annotations

import shutil

import pytest

from tests.helpers.voice_call_sandbox import build, run

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_FEED = """
const level = (d) => Math.pow(10, d / 20);
function feed(det, seq) {
  const evs = [];
  let i = 0;
  for (const [db, n] of seq) for (let k = 0; k < n; k++, i++) {
    const ev = det.push(level(db), new Float32Array(320).fill(i));
    if (ev) evs.push([i, ev.type, ev.samples ? ev.samples.length / 320 : null]);
  }
  return evs;
}
"""


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build(tmp_path_factory.mktemp("voiceturns"))


def test_a_turn_starts_with_its_first_word_and_ends_with_the_pause(box):
    o = run(box, _FEED + """
        const d = new CAP.TurnDetector();
        out.evs = feed(d, [[-70, 20], [-20, 30], [-70, 50]]);
        out.noise = Math.round(d.noiseDb);
        out.state = d.state;
    """)
    # Three loud frames, then 260 ms of them, then 860 ms of quiet.
    assert o["evs"] == [[22, "onset", None], [32, "confirmed", None], [92, "utterance", 55]]
    assert o["noise"] == -70
    assert o["state"] == "silence"


def test_a_click_or_a_cough_is_not_a_turn(box):
    o = run(box, _FEED + "out.evs = feed(new CAP.TurnDetector(), [[-70, 20], [-20, 6], [-70, 50]]);")
    assert o["evs"] == [[22, "onset", None], [68, "discard", None]]


def test_the_pause_that_ends_a_turn_is_the_one_chosen(box):
    o = run(box, _FEED + """
        out.short = feed(new CAP.TurnDetector({ endSilenceMs: CAP.PAUSES.short }), [[-70, 20], [-20, 30], [-70, 80]]);
        out.relaxed = feed(new CAP.TurnDetector({ endSilenceMs: CAP.PAUSES.relaxed }), [[-70, 20], [-20, 30], [-70, 80]]);
        out.pauses = CAP.PAUSES;
    """)
    assert o["pauses"] == {"short": 550, "normal": 850, "relaxed": 1400}
    assert o["short"][-1][:2] == [77, "utterance"]
    assert o["relaxed"][-1][:2] == [119, "utterance"]


def test_a_quiet_room_learned_while_someone_talked_is_still_the_room(box):
    o = run(box, _FEED + """
        const d = new CAP.TurnDetector();
        feed(d, [[-70, 13], [-25, 7]]);
        out.noise = Math.round(d.noiseDb);
    """)
    assert o["noise"] == -70


def test_a_fan_switched_on_becomes_the_room(box):
    o = run(box, _FEED + """
        const d = new CAP.TurnDetector();
        out.evs = feed(d, [[-70, 20], [-45, 400], [-20, 30], [-45, 60]]);
        out.noise = Math.round(d.noiseDb);
    """)
    # Taken for a turn at first, let go once it has been too even for two
    # seconds, and the person talking over it afterwards is heard.
    assert o["evs"] == [[22, "onset", None], [32, "confirmed", None], [156, "discard", None],
                        [422, "onset", None], [432, "confirmed", None], [492, "utterance", 55]]
    assert o["noise"] == -45


def test_speech_that_rises_and_falls_is_not_taken_for_a_fan(box):
    o = run(box, _FEED + """
        const syllables = Array.from({ length: 40 }, (_, k) => [k % 2 ? -45 : -22, 6]);
        out.evs = feed(new CAP.TurnDetector(), [[-70, 20], ...syllables, [-70, 50]]);
    """)
    assert o["evs"] == [[22, "onset", None], [32, "confirmed", None], [302, "utterance", 265]]


def test_while_the_agent_talks_it_takes_more_to_be_the_person(box):
    o = run(box, _FEED + """
        const echo = new CAP.TurnDetector(); feed(echo, [[-70, 20]]); echo.setStrict(true);
        out.echo = feed(echo, [[-50, 40], [-70, 50]]);
        const plain = new CAP.TurnDetector(); feed(plain, [[-70, 20]]);
        out.plain = feed(plain, [[-50, 40], [-70, 50]]);
        const strict = new CAP.TurnDetector(); feed(strict, [[-70, 20]]); strict.setStrict(true);
        out.strictShort = feed(strict, [[-20, 18], [-70, 50]]);
    """)
    # A quiet echo of its own voice is nothing while it talks ...
    assert o["echo"] == []
    # ... though the same level is someone talking when it is quiet.
    assert [e[1] for e in o["plain"]] == ["onset", "confirmed", "utterance"]
    # And words must last longer to interrupt it.
    assert [e[1] for e in o["strictShort"]] == ["onset", "discard"]


def test_a_turn_that_does_not_stop_is_sent_at_its_limit(box):
    o = run(box, _FEED + """
        const talk = Array.from({ length: 24 }, (_, k) => [k % 2 ? -26 : -20, 5]);
        out.evs = feed(new CAP.TurnDetector({ maxTurnMs: 2000 }), [[-70, 20], ...talk]);
    """)
    assert o["evs"][:3] == [[22, "onset", None], [32, "confirmed", None], [106, "utterance", 100]]
    assert o["evs"][3][1] == "onset"


def test_a_turn_is_written_as_16_bit_mono_wav(box):
    o = run(box, """
        const w = CAP.encodeWav(new Float32Array([0, 0.5, -0.5, 1, -1, 2]));
        const v = new DataView(w.buffer);
        const tag = (at) => String.fromCharCode(...w.slice(at, at + 4));
        out.wav = { bytes: w.length, riff: tag(0), size: v.getUint32(4, true), wave: tag(8), fmt: tag(12),
          pcm: v.getUint16(20, true), channels: v.getUint16(22, true), rate: v.getUint32(24, true),
          bits: v.getUint16(34, true), data: tag(36), dataBytes: v.getUint32(40, true),
          samples: [0, 1, 2, 3, 4, 5].map((i) => v.getInt16(44 + i * 2, true)) };
    """)
    assert o["wav"] == {
        "bytes": 56, "riff": "RIFF", "size": 48, "wave": "WAVE", "fmt": "fmt ", "pcm": 1, "channels": 1,
        "rate": 16000, "bits": 16, "data": "data", "dataBytes": 12,
        "samples": [0, 16383, -16384, 32767, -32768, 32767],
    }
