# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1718` — a voice chat takes turns with the agent, and says why when it
cannot.

The call is the open chat, spoken: the person's turn is heard by the real
`TurnDetector` (`voiceCapture.js`), turned into words by the server
(`POST /api/stt/transcribe`) and sent as their next message; the reply that
`chat.js` announces (`pantheon:reply`) is split by the real `SpeechChunker`
(`speechText.js`) and said a sentence at a time while it is still being
written (`POST /api/tts/synthesize`), and the call goes back to listening.

Driven (`Law 20`): `createVoiceCall` itself, under node, over
`tests/helpers/voice_call_sandbox.py` — a clock the case moves, a microphone
fed frames at a level, the speech routes answered, an audio element told
when a sentence has played. Each case is one thing a person would notice.
"""
from __future__ import annotations

import shutil

import pytest

from tests.helpers.voice_call_sandbox import build, run

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build(tmp_path_factory.mktemp("voicecall"))


def test_a_turn_is_heard_sent_and_its_reply_said_a_sentence_at_a_time(box):
    o = run(box, """
        const h = setup({ transcripts: ['What is the weather like in Paris'] });
        await h.vc.start();
        out.ready = h.vc.state.words;
        await h.frames(SILENT, 25);
        await h.talk(800);
        await h.T.advance(400);
        out.sent = h.sent;
        out.thinking = h.vc.state.words;
        h.setBusy(true);
        h.reply('start');
        h.reply('text', { text: 'It is sunny in Paris today, with a high of twenty degrees.' });
        h.reply('text', { text: 'It is sunny in Paris today, with a high of twenty degrees. Bring sunglasses' });
        await flush();
        out.saidWhileWriting = [...h.said];
        out.speaking = h.vc.state.words;
        h.reply('end', { text: 'It is sunny in Paris today, with a high of twenty degrees. Bring sunglasses.' });
        h.setBusy(false);
        await flush();
        await h.playAll();
        out.said = h.said;
        out.after = h.vc.state.words;
        h.vc.end('Voice chat ended.');
        out.micClosed = !!h.capture.stopped;
    """)
    assert o["ready"] == "Listening."
    assert o["sent"] == [["send", "What is the weather like in Paris"]]
    assert o["thinking"] == "Thinking."
    # The first sentence is said before the reply has finished being written.
    assert o["saidWhileWriting"] == ["It is sunny in Paris today, with a high of twenty degrees."]
    assert o["speaking"] == "Speaking."
    assert o["said"] == ["It is sunny in Paris today, with a high of twenty degrees.", "Bring sunglasses."]
    assert o["after"] == "Listening."
    assert o["micClosed"] is True


def test_a_pause_inside_a_turn_does_not_end_it(box):
    """Two stretches of speech heard as one turn when the second starts while
    the first is still being turned into words."""
    o = run(box, """
        const h = setup({ transcripts: ['Can you check the logs', 'for the auth service'] });
        await h.vc.start();
        await h.frames(SILENT, 25);
        await h.frames(LOUD, 30);
        await h.frames(SILENT, 44);   // the pause ends a turn ...
        await h.frames(LOUD, 30);     // ... and they go on before it is sent
        await h.frames(SILENT, 50);
        await h.T.advance(400);
        out.sent = h.sent;
    """)
    assert o["sent"] == [["send", "Can you check the logs for the auth service"]]


def test_turns_are_heard_in_the_order_they_were_said(box):
    o = run(box, """
        const h = setup({ tts: { provider: 'disabled', available: false }, sttDelays: true });
        await h.vc.start();
        await h.frames(SILENT, 25);
        await h.frames(LOUD, 30); await h.frames(SILENT, 45);
        await h.frames(LOUD, 30); await h.frames(SILENT, 45);
        out.asked = h.pendingStt.length;
        h.pendingStt[1](h.json({ text: 'in Paris' }));
        await flush(); await h.T.advance(400);
        out.beforeFirst = [...h.sent];
        h.pendingStt[0](h.json({ text: 'What is the weather' }));
        await flush(); await h.T.advance(400);
        out.sent = h.sent;
    """)
    assert o["asked"] == 2
    assert o["beforeFirst"] == []
    assert o["sent"] == [["send", "What is the weather in Paris"]]


def test_a_muted_call_hears_nothing(box):
    o = run(box, """
        const h = setup({ transcripts: ['Hello'] });
        await h.vc.start();
        await h.frames(SILENT, 25);
        h.vc.toggleMute();
        out.muted = h.vc.state.words;
        await h.talk(600);
        out.heardWhileMuted = h.log.filter((u) => u === '/api/stt/transcribe').length;
        h.vc.toggleMute();
        await h.talk(600); await h.T.advance(400);
        out.sent = h.sent;
    """)
    assert o["muted"] == "Muted."
    assert o["heardWhileMuted"] == 0
    assert o["sent"] == [["send", "Hello"]]


def test_a_call_belongs_to_the_chat_it_started_in(box):
    o = run(box, """
        const h = setup();
        await h.vc.start();
        h.vc.sessionChanged('s1');
        out.stillOn = h.vc.active;
        h.vc.sessionChanged('s2');
        out.ends = h.ends;
        out.on = h.vc.active;
    """)
    assert o["stillOn"] is True
    assert o["ends"] == [["Voice chat ended: another chat was opened.", {"setup": False}]]
    assert o["on"] is False


def test_a_turn_no_reply_answers_says_so(box):
    o = run(box, """
        const h = setup({ transcripts: ['Hello there'] });
        await h.vc.start();
        await h.frames(SILENT, 25);
        await h.talk(600);
        await h.T.advance(400);
        out.thinking = h.vc.state.words;
        await h.T.advance(8100);
        out.after = h.vc.state.words;
        out.note = h.vc.state.note;
    """)
    assert o["thinking"] == "Thinking."
    assert o["after"] == "Listening."
    assert o["note"] == "No reply came. The chat says why."


@pytest.mark.parametrize("stt, said", [
    ({"provider": "disabled", "available": False},
     "Voice chat needs speech-to-text. Choose one in Settings → Voice → Speech to text."),
    ({"voice_chat": {"enabled": False}}, "Voice chat is turned off in Settings → Voice."),
    ({"provider": "local", "available": False,
      "unavailable_reason": "Speech-to-text needs the Whisper model, which is not downloaded."},
     "Speech-to-text needs the Whisper model, which is not downloaded."),
])
def test_a_call_that_cannot_hear_says_why_and_where_to_set_it_up(box, stt, said):
    o = run(box, f"""
        const h = setup({{ stt: {__import__('json').dumps(stt)} }});
        out.ok = await h.vc.start();
        out.ends = h.ends;
        out.micOpened = !!h.capture;
    """)
    assert o["ok"] is False
    assert o["ends"] == [[said, {"setup": True}]]
    assert o["micOpened"] is False


def test_speech_to_text_failing_mid_call_ends_it_with_the_servers_words(box):
    o = run(box, """
        const h = setup({ sttStatus: 503 });
        await h.vc.start();
        await h.frames(SILENT, 25);
        await h.talk(600);
        await h.T.advance(100);
        out.ends = h.ends;
    """)
    assert o["ends"] == [["Whisper is not installed on this server.", {"setup": True}]]


def test_a_call_with_no_voice_goes_on_in_text(box):
    o = run(box, """
        const h = setup({ tts: { provider: 'disabled', available: false }, transcripts: ['Hi'] });
        out.ok = await h.vc.start();
        out.note = h.vc.state.note;
        out.setup = h.vc.state.setup;
        await h.frames(SILENT, 25);
        await h.talk(600); await h.T.advance(400);
        out.sent = h.sent;
        h.reply('start'); h.reply('end', { text: 'Hello! How can I help?' }); await flush();
        out.asked = h.said.length;
    """)
    assert o["ok"] is True
    assert o["note"] == "Replies are shown and not said: choose a voice in Settings → Voice."
    assert o["setup"] is True
    assert o["sent"] == [["send", "Hi"]]
    assert o["asked"] == 0


def test_the_browsers_own_voice_speaks_as_settings_chose_it(box):
    """Settings → Voice → "The browser’s own": the speaker it names (a part of
    a name is enough) at the speed beside it, and nothing asked of this
    server's voice."""
    o = run(box, """
        const h = setup({ tts: { provider: 'browser', voice: 'daniel', speed: 1.25 }, synth: true });
        await h.vc.start();
        await h.frames(SILENT, 25);
        h.reply('start');
        h.reply('end', { text: 'The weather in Lisbon is warm and bright this morning, with a light breeze. Rain is expected later in the evening, so take an umbrella with you.' });
        await flush();
        out.saying = h.synth.said.map((u) => [u.text, u.rate, u.voice && u.voice.name]);
        out.words = h.vc.state.words;
        await h.playAll();
        out.said = h.synth.said.map((u) => [u.text, u.rate, u.voice && u.voice.name]);
        out.after = h.vc.state.words;
        out.server = h.said.length;
        const plain = setup({ tts: { provider: 'browser', voice: 'alloy', speed: 1 }, synth: true });
        await plain.vc.start();
        plain.reply('start'); plain.reply('end', { text: 'A voice no browser has is the browser default.' }); await flush();
        out.plain = plain.synth.said.map((u) => [u.rate, u.voice]);
    """)
    assert o["saying"] == [["The weather in Lisbon is warm and bright this morning, with a light breeze.", 1.25, "Daniel (en-GB)"]]
    assert o["words"] == "Speaking."
    assert o["said"] == [["The weather in Lisbon is warm and bright this morning, with a light breeze.", 1.25, "Daniel (en-GB)"],
                         ["Rain is expected later in the evening, so take an umbrella with you.", 1.25, "Daniel (en-GB)"]]
    assert o["after"] == "Listening."
    assert o["server"] == 0
    assert o["plain"] == [[1, None]]


def test_a_call_ended_while_the_browser_asks_for_the_microphone_lets_go_of_it(box):
    """The permission prompt can stay up as long as the person leaves it. A
    call ended meanwhile closes the microphone the browser gives it after,
    rather than leaving it open (the browser's light on) with no call."""
    o = run(box, """
        const h = setup({ holdMic: true });
        const started = h.vc.start();
        await flush();
        out.asking = h.vc.state.words;
        h.vc.end('Voice chat ended.');
        h.capture.allow();
        out.started = await started;
        out.closed = !!h.capture.released;
        out.active = h.vc.active;
    """)
    assert o["asking"] == "Starting."
    assert o["started"] is False
    assert o["closed"] is True
    assert o["active"] is False


def test_the_microphone_asked_for_and_then_stopped_is_closed_when_it_comes(box):
    """`VoiceCapture` itself: stopped before `getUserMedia` answered, it stops
    the tracks it is then given and builds nothing on them."""
    o = run(box, """
        let allow;
        const tracks = [];
        let contexts = 0;
        globalThis.window = { isSecureContext: true, AudioContext: class { constructor() { contexts += 1; } } };
        Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: {
          getUserMedia: () => new Promise((r) => { allow = r; }) } } });
        const cap = new CAP.VoiceCapture({});
        const started = cap.start();
        cap.stop();
        const track = { stopped: false, stop() { this.stopped = true; }, addEventListener() {} };
        tracks.push(track);
        allow({ getTracks: () => tracks, getAudioTracks: () => tracks });
        await started;
        out.stopped = tracks.map((t) => t.stopped);
        out.contexts = contexts;
    """)
    assert o["stopped"] == [True]
    assert o["contexts"] == 0


def test_the_pages_own_timers_are_called_as_themselves(box):
    """Without timers passed in, the call uses the page's. Chrome refuses a
    timer called as a method of another object ("Illegal invocation"), which
    the first word a call heard did; here the page's timers refuse it too."""
    o = run(box, """
        const own = { setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout,
                      setInterval: globalThis.setInterval, clearInterval: globalThis.clearInterval };
        for (const k of Object.keys(own)) {
          globalThis[k] = function (...a) {
            if (this !== undefined && this !== globalThis) throw new TypeError('Illegal invocation');
            return own[k](...a);
          };
        }
        const sent = [];
        const json = (body) => ({ ok: true, status: 200, json: async () => body });
        const vc = VC.createVoiceCall({
          chat: { sendTurn: (t) => { sent.push(t); return 'sent'; }, queueTurn: () => true, stopReply() {},
                  isBusy: () => false, sessionId: () => 's1', canSteer: () => false },
          fetch: async (url) => json(url === '/api/stt/stats'
            ? { provider: 'local', available: true, model_loaded: true, voice_chat: { enabled: true } }
            : { provider: 'disabled' }),
          events: new EventTarget(),
          media: { Capture: class { async start() {} stop() {} }, Audio: null },
        });
        out.started = await vc.start();
        let threw = null;
        try { vc._heard('What time is it'); } catch (e) { threw = String(e); }
        out.threw = threw;
        await new Promise((r) => own.setTimeout(r, 900));
        out.sent = sent;
        vc.end('Voice chat ended.');
    """)
    assert o["started"] is True
    assert o["threw"] is None
    assert o["sent"] == ["What time is it"]


def test_a_voice_that_fails_twice_leaves_the_call_in_text(box):
    o = run(box, """
        const h = setup();
        await h.vc.start();
        await h.frames(SILENT, 25);
        h.reply('start');
        h.reply('end', { text: 'The first sentence is here and it is quite long indeed, long enough. The second sentence is here and it is also long enough to stand. The third sentence follows and is long too, so it stands alone.' });
        await flush();
        h.player.onerror(); await flush();
        out.once = h.vc.state.note;
        h.player.onerror(); await flush();
        out.twice = h.vc.state.note;
        out.speaking = h.call.speaker.busy;
        const before = h.said.length;
        h.reply('start'); h.reply('end', { text: 'Another reply.' }); await flush();
        out.askedAgain = h.said.length > before;
        out.on = h.vc.active;
    """)
    assert o["once"] == "A sentence was not said: the audio would not play."
    assert o["twice"] == "Replies are shown and not said: the audio would not play."
    assert o["speaking"] is False
    assert o["askedAgain"] is False
    assert o["on"] is True


def test_a_hiccup_is_forgotten_once_a_sentence_is_said(box):
    o = run(box, """
        const h = setup();
        await h.vc.start();
        await h.frames(SILENT, 25);
        h.reply('start');
        h.reply('end', { text: 'The first sentence is here and it is quite long indeed, long enough. The second sentence is here and it is also long enough to stand. The third sentence follows and is long too, so it stands alone. The fourth one is here as well and long.' });
        await flush();
        h.player.onerror(); await flush();
        h.player.finish(); await flush();
        h.player.onerror(); await flush();
        out.silenced = h.call.speaker.silenced;
    """)
    assert o["silenced"] is False


def test_a_question_is_said_with_its_choices(box):
    o = run(box, """
        const h = await speaking({}, 'Let me check. I found three branches.');
        h.reply('ask', { kind: 'question', question: 'Which branch should I use?', options: ['main', 'dev', 'staging'] });
        h.reply('end', { text: 'Which branch should I use?' });
        h.setBusy(false);
        await flush();
        await h.playAll();
        out.said = h.said;
        out.after = h.vc.state.words;
    """)
    assert o["said"] == ["Let me check.", "I found three branches.",
                         "Which branch should I use? You can say main, dev or staging."]
    assert o["after"] == "Listening."


def test_an_approval_is_never_given_by_voice(box):
    o = run(box, """
        const h = await speaking({ transcripts: ['Yes approve it'] }, 'I will clean the build folder.');
        h.reply('ask', { kind: 'tool_approval', question: 'Run rm -rf build?', options: ['Approve', 'Deny'] });
        h.reply('end', { text: 'Allow this task to continue?' });
        h.setBusy(false);
        await flush();
        await h.playAll();
        out.said = h.said;
        out.waiting = h.vc.state.words;
        out.note = h.vc.state.note;
        await h.talk(600); await h.T.advance(400);
        out.heard = h.log.filter((u) => u === '/api/stt/transcribe').length;
        out.sent = h.sent;
        h.vc.approvalAnswered();
        out.answered = h.vc.state.words;
        h.setBusy(true); h.reply('start'); await flush();
        out.noteAfter = h.vc.state.note;
    """)
    assert o["said"] == ["I will clean the build folder.", "I need your approval in the chat to go on."]
    assert o["waiting"] == "Waiting for you."
    assert o["note"] == "Approve or deny on the card in the chat. The call goes on after."
    assert o["heard"] == 0
    assert o["sent"] == []
    assert o["answered"] == "Thinking."
    assert o["noteAfter"] == ""


def test_a_reply_in_another_chat_is_not_said_in_this_one(box):
    o = run(box, """
        const h = setup();
        await h.vc.start();
        h.reply('start', { sessionId: 's2' });
        h.reply('end', { sessionId: 's2', text: 'Not for this call.' });
        await flush();
        out.said = h.said;
    """)
    assert o["said"] == []
