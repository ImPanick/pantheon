# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1718` — talking over the agent in a voice chat interrupts it, and only
the person's words do.

The voice ducks at the first sound and pauses once the sound is long enough
to be words. When the words come back, the rest of the reply is not said and
they go to the agent: as a steer for an agent run that takes one, otherwise
after the reply in flight is stopped. What is not the person taking a turn
lets the voice go on from where it paused: a cough (too short), the agent's
own sentence come back through the speakers (an echo), "mm-hmm" (listening),
nothing at all. "Wait" stops the voice, "stop" the reply too, "hang up" the
call. A steer the run never read is not lost: it goes as the next message.
With interrupting turned off the call takes turns and does not listen while
the agent talks. With the browser's own recognition, which is not
echo-cancelled, words heard while the agent talks count only when the
echo-cancelled microphone heard the person too.

Driven (`Law 20`): `createVoiceCall` under node over
`tests/helpers/voice_call_sandbox.py`, the real `TurnDetector` fed frames
at a level; and the three text tests the call makes (`isEcho`,
`isBackchannel`, `cleanHeard`) on what Whisper and a person actually say.
"""
from __future__ import annotations

import shutil

import pytest

from tests.helpers.voice_call_sandbox import build, run

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# Talking over the voice: past the stricter onset and long enough to be
# words while the agent speaks (`TurnDetector.setStrict`), then the pause.
_OVER = "await h.frames(LOUD, 30); await h.frames(SILENT, 50); await h.T.advance(400);"


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build(tmp_path_factory.mktemp("voicebargein"))


def test_talking_over_the_reply_stops_it_and_the_words_go_next(box):
    o = run(box, """
        const h = await speaking({ transcripts: ['Actually tell me about London instead'] });
        out.before = h.vc.state.words;
        await h.frames(LOUD, 8);
        out.ducked = h.player.volume;
        await h.frames(LOUD, 20);
        out.paused = h.call.speaker.paused;
        out.hearing = h.vc.state.words;
        await h.frames(SILENT, 50); await h.T.advance(400);
        out.sent = h.sent;
        out.speaking = h.call.speaker.busy;
        const n = h.said.length;
        h.reply('text', { text: 'Here is a long answer about the history of the city and its rivers. It goes on for a while with more detail. And then more of it.' });
        await flush();
        out.restNotSaid = h.said.length === n;
        h.reply('stop'); h.setBusy(false); await flush();
        out.waitingForNext = h.vc.state.words;
        h.setBusy(true); h.reply('start'); h.reply('text', { text: 'London sits on the Thames.' }); h.reply('end', { text: 'London sits on the Thames.' });
        await flush();
        out.nextSaid = h.said.slice(n);
    """)
    assert o["before"] == "Speaking."
    assert o["ducked"] == 0.25
    assert o["paused"] is True
    assert o["hearing"] == "Hearing you."
    assert o["sent"] == [["stop"], ["queue", "Actually tell me about London instead"]]
    assert o["speaking"] is False
    assert o["restNotSaid"] is True
    assert o["waitingForNext"] == "Thinking."
    assert o["nextSaid"] == ["London sits on the Thames."]


def test_a_reply_already_written_and_still_being_said_is_talked_over_too(box):
    o = run(box, """
        const h = await speaking({ transcripts: ['Thanks, that is enough'] });
        h.reply('end', { text: 'Here is a long answer about the history of the city and its rivers. It goes on for a while with more detail.' });
        h.setBusy(false);
        await flush();
        """ + _OVER + """
        out.sent = h.sent;
        out.speaking = h.call.speaker.busy;
    """)
    assert o["sent"] == [["send", "Thanks, that is enough"]]
    assert o["speaking"] is False


def test_a_cough_lets_the_voice_go_on(box):
    o = run(box, """
        const h = await speaking();
        await h.frames(LOUD, 7);
        await h.frames(SILENT, 50);
        out.paused = h.call.speaker.paused;
        out.volume = h.player.volume;
        out.heard = h.log.filter((u) => u === '/api/stt/transcribe').length;
        out.words = h.vc.state.words;
    """)
    assert o == {"paused": False, "volume": 1, "heard": 0, "words": "Speaking."}


@pytest.mark.parametrize("came_back", [
    "Here is a long answer about the history of the city",   # its own voice
    "Mm-hmm.",                                                # listening
    "",                                                       # nothing
    "[Music]",                                                # a sound tag
])
def test_what_is_not_a_turn_lets_the_voice_go_on(box, came_back):
    o = run(box, f"""
        const h = await speaking({{ transcripts: [{came_back!r}] }});
        await h.frames(LOUD, 30);
        out.pausedWhileHeard = h.call.speaker.paused;
        await h.frames(SILENT, 50); await h.T.advance(400);
        out.sent = h.sent;
        out.resumed = h.call.speaker.busy && !h.call.speaker.paused && h.player.plays >= 2;
        out.words = h.vc.state.words;
    """)
    assert o["pausedWhileHeard"] is True
    assert o["sent"] == []
    assert o["resumed"] is True
    assert o["words"] == "Speaking."


def test_wait_stops_the_voice_and_stop_stops_the_reply(box):
    o = run(box, """
        const a = await speaking({ transcripts: ['Wait.'] });
        """ + _OVER.replace("h.", "a.") + """
        out.wait = { sent: a.sent, speaking: a.call.speaker.busy };
        const b = await speaking({ transcripts: ['Stop.'] });
        """ + _OVER.replace("h.", "b.") + """
        out.stop = { sent: b.sent, speaking: b.call.speaker.busy };
    """)
    assert o["wait"] == {"sent": [], "speaking": False}
    assert o["stop"] == {"sent": [["stop"]], "speaking": False}


@pytest.mark.parametrize("words", ["Hang up.", "End the call.", "Goodbye."])
def test_hang_up_ends_the_call(box, words):
    o = run(box, f"""
        const h = await speaking({{ transcripts: [{words!r}] }});
        """ + _OVER + """
        out.ends = h.ends;
        out.sent = h.sent;
        out.micClosed = !!h.capture.stopped;
    """)
    assert o["ends"] == [["Voice chat ended.", {"setup": False}]]
    assert o["sent"] == []
    assert o["micClosed"] is True


def test_a_correction_steers_a_run_and_its_answer_is_said(box):
    o = run(box, """
        const h = await speaking({ transcripts: ['Also check the tests folder please'], chat: { canSteer: () => true } },
          'I will look through the files now. First the config.');
        """ + _OVER + """
        out.sent = h.sent;
        out.words = h.vc.state.words;
        const n = h.said.length;
        // The step in flight finishes before the run reads the steer: it is not said.
        h.reply('text', { text: 'I will look through the files now. First the config. Now the src folder.' });
        h.reply('round');
        h.reply('steered', { count: 1 });
        h.reply('text', { text: 'Got it, I will check the tests folder too.' });
        h.reply('end', { text: 'Got it, I will check the tests folder too.' });
        h.setBusy(false);
        await flush();
        await h.playAll();
        out.said = h.said.slice(n);
        out.resent = h.sent.length;
    """)
    assert o["sent"] == [["steer", "Also check the tests folder please"]]
    assert o["words"] == "Thinking."
    assert o["said"] == ["Got it, I will check the tests folder too."]
    assert o["resent"] == 1


def test_a_steer_the_run_never_read_goes_as_the_next_message(box):
    o = run(box, """
        const h = await speaking({ transcripts: ['Use the staging database'], chat: { canSteer: () => true } });
        """ + _OVER + """
        h.reply('end', { text: 'Done.' });
        await flush();
        out.sent = h.sent;
        out.words = h.vc.state.words;
    """)
    assert o["sent"] == [["steer", "Use the staging database"], ["send", "Use the staging database"]]
    assert o["words"] == "Thinking."


def test_a_refused_steer_waits_in_the_queue(box):
    o = run(box, """
        const h = await speaking({ transcripts: ['Use the staging database'],
          chat: { canSteer: () => true, steerTurn: async () => 'queued' } });
        """ + _OVER + """
        h.reply('end', { text: 'Done.' });
        await flush();
        out.steers = h.call.steers.length;
        out.awaiting = h.call.awaitingReply;
    """)
    assert o == {"steers": 0, "awaiting": True}


def test_taking_turns_does_not_listen_while_it_talks(box):
    o = run(box, """
        const h = await speaking({ transcripts: ['Over the top', 'After it'],
          stt: { voice_chat: { enabled: true, pause: 'short', barge_in: false } } });
        await h.frames(LOUD, 30); await h.frames(SILENT, 50);
        out.paused = h.call.speaker.paused;
        out.heardWhileItTalked = h.log.filter((u) => u === '/api/stt/transcribe').length;
        h.reply('end', { text: 'Here is a long answer about the history of the city and its rivers. It goes on for a while with more detail.' });
        h.setBusy(false);
        await flush();
        await h.playAll();
        await h.talk(600); await h.T.advance(400);
        out.sent = h.sent;
    """)
    assert o["paused"] is False
    assert o["heardWhileItTalked"] == 0
    assert o["sent"] == [["send", "Over the top"]]


def test_the_browsers_recognition_counts_what_the_microphone_heard(box):
    """Chrome's recognition hears the speakers as well as the person: the
    agent's own words, recognised while it talks, are never sent as a turn."""
    o = run(box, """
        const browser = { provider: 'browser', available: true, language: 'en-GB',
          voice_chat: { enabled: true, barge_in: true } };
        const idle = setup({ stt: browser });
        await idle.vc.start();
        out.lang = idle.recs[0].lang;
        await idle.frames(SILENT, 25);
        idle.hear('What time is it in Tokyo');
        await idle.T.advance(400);
        out.idle = idle.sent;

        const echo = await speaking({ stt: browser }, 'It is nine in the morning in Tokyo. The weather there is mild.');
        echo.hear('nine in the morning in Tokyo');
        echo.hear('something else entirely different');
        await echo.T.advance(400);
        out.echo = { sent: echo.sent, speaking: echo.call.speaker.busy };

        const over = await speaking({ stt: browser }, 'It is nine in the morning in Tokyo. The weather there is mild.');
        await over.frames(LOUD, 30);
        await over.frames(SILENT, 45);
        over.hear('And what about Osaka');
        await over.T.advance(400);
        out.over = { sent: over.sent, speaking: over.call.speaker.busy };

        const none = await speaking({ stt: browser }, 'It is nine in the morning in Tokyo. The weather there is mild.');
        await none.frames(LOUD, 30);
        await none.frames(SILENT, 45);
        out.waits = none.call.speaker.paused;
        await none.T.advance(2000);
        out.goesOn = !none.call.speaker.paused;
    """)
    assert o["lang"] == "en-GB"
    assert o["idle"] == [["send", "What time is it in Tokyo"]]
    assert o["echo"] == {"sent": [], "speaking": True}
    assert o["over"] == {"sent": [["stop"], ["queue", "And what about Osaka"]], "speaking": False}
    assert o["waits"] is True
    assert o["goesOn"] is True


def test_taking_turns_turns_the_browsers_recognition_off_while_it_talks(box):
    o = run(box, """
        const h = await speaking({ stt: { provider: 'browser', available: true,
          voice_chat: { enabled: true, barge_in: false } } });
        out.offWhileItTalks = h.call.hearing.rec === null && h.recs[0].aborted === 1;
        h.vc.interrupt(); await flush();
        await h.T.advance(300);
        out.backOn = h.call.hearing.rec !== null && h.recs.length === 2;
    """)
    assert o == {"offWhileItTalks": True, "backOn": True}


def test_the_text_tests_on_what_people_and_whisper_say(box):
    o = run(box, """
        out.backchannel = ['Mm-hmm.', 'mhm', 'Uh-huh.', 'Okay.', 'Yeah, right.', 'I see.', 'Got it!',
                           'yes', 'no', 'Okay, do it', 'right now'].map((t) => VC.isBackchannel(t));
        out.echo = [
          ['Here is a long answer', ['Here is a long answer about the history of the city.']],
          ['I want the red one please', ['Do you want the blue one or the red one?']],
          ['stop', ['You can stop the build now.']],
          ['Tell me more', []],
        ].map(([heard, spoken]) => VC.isEcho(heard, spoken));
        out.clean = ['[Music]', 'Thanks for watching!', '(upbeat music)', '♪ ♪', 'Hello [laughter] there', ' Thank you. ']
          .map((t) => VC.cleanHeard(t));
    """)
    assert o["backchannel"] == [True] * 7 + [False] * 4
    assert o["echo"] == [True, False, False, False]
    assert o["clean"] == ["", "", "", "", "Hello there", "Thank you."]
