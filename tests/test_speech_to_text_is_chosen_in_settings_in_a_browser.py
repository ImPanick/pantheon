# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1564` — Settings → AI Defaults offers speech-to-text, every provider, and
the browser's own works where the browser has it.

`D-2026-10-29-01` §3, the owner: *"Allow for both local + browser. All
options available."* — an endpoint the operator runs, local Whisper behind the
model-download switch (`B1565`), and the browser's Web Speech API, which in
Chrome sends the audio to Google, offered with that sentence beside it.

**Measured on the tree before this row:** AI Defaults had no speech-to-text
card at all (`initSttSettings` returned on the missing
`#set-sttProviderSelect`), so `stt_provider` could be set only by hand; and with
`browser` set, a recording in a browser whose recognition hands its last words
over after `stop()` — as Chrome's does — came back as "No speech detected" and
an attached file, because the transcript was read the moment it was asked for.
A browser with no recognition at all (Firefox) ended the same way, saying
nothing about why.

Driven (`Law 20`) in the real app (`app_url` boots `app.py`), in headless
Chromium with a fake microphone: the card as an admin draws it; each provider
chosen, saved, read back from the server (`GET /api/auth/settings`,
`GET /api/stt/stats`) and still chosen after a reload; the browser's sentence
on its option and in the note under the list, where it is chosen; a member's
save refused at the route. Then the microphone in the chat: the browser's own
(a stand-in `webkitSpeechRecognition` that answers the way Chrome's does,
because Chrome's would send the audio to Google), the browser without one,
one whose service cannot be reached, and an endpoint (the scripted model's
`/audio/transcriptions`), through `POST /api/stt/transcribe`.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

import demo_model  # noqa: E402

HEARD = "the fake browser heard this"
SPOKEN_TO_THE_ENDPOINT = "the endpoint heard this"

_SCRIPT = r"""
const { chromium } = require('playwright');
const [BASE, EP_URL] = process.argv.slice(2);
const HEARD = %(heard)s;
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox',
    '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
  const out = { errors: [], chosen: {}, server: {}, reloaded: {}, mic: {} };
  const admin = { username: 'boss', password: 'boss-pass-123' };
  const member = { username: 'mira', password: 'mira-pass-123' };
  const setup = await browser.newContext();
  await setup.request.post(BASE + '/api/auth/setup', { data: admin });
  await setup.request.post(BASE + '/api/auth/login', { data: { ...admin, remember: true } });
  await setup.request.post(BASE + '/api/auth/users', { data: { ...member, is_admin: false } });
  const added = await setup.request.post(BASE + '/api/model-endpoints',
    { form: { name: 'Box', base_url: EP_URL, supports_tools: 'true' } });
  out.endpoint = (await added.json()).id;
  // The admin's own requests between the drives. A keep-alive socket the
  // server closed while the page worked answers ECONNRESET to the next one,
  // so each is asked again on that; all of them are idempotent.
  const api = async (method, path, data) => {
    for (let tries = 1; ; tries++) {
      try {
        const res = await setup.request[method](BASE + path, data ? { data } : undefined);
        return method === 'get' ? await res.json() : res.status();
      } catch (e) {
        if (tries >= 3 || !/ECONNRESET|socket hang up/.test(String(e))) throw e;
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
    }
  };
  const read = async () => {
    const s = await api('get', '/api/auth/settings');
    const stats = await api('get', '/api/stt/stats');
    return { enabled: s.stt_enabled, provider: s.stt_provider, model: s.stt_model,
             language: s.stt_language, stats_provider: stats.provider,
             unavailable: stats.unavailable_reason || '' };
  };

  const pageIn = async (context) => {
    const page = await context.newPage();
    page.setDefaultTimeout(120000);
    page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true);
    return page;
  };
  const contextFor = async (who, init) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 860 },
                                               permissions: ['microphone'] });
    await context.addInitScript(() => {
      try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    });
    if (init) await context.addInitScript(init);
    await context.request.post(BASE + '/api/auth/login', { data: { ...who, remember: true } });
    return context;
  };
  // The card, as a person reaches it: the gear, then AI Defaults; drawn once
  // it has read what is saved (its note says something) and the switch the
  // local choice is behind.
  const openCard = async (page) => {
    await page.click('#user-bar-settings');
    await page.click('#settings-modal .settings-nav-item[data-settings-tab="ai"]');
    await page.waitForSelector('[data-settings-panel="ai"]:not(.hidden) #set-sttProviderSelect', { state: 'visible' });
    await page.waitForFunction(() => (document.getElementById('set-sttProviderNote') || {}).textContent);
    // Every word the card's message says, kept: "Saved" clears itself after
    // two seconds, which a loaded machine can spend between two polls.
    await page.evaluate(() => {
      window.__sttSaid = [];
      const msg = document.getElementById('set-sttSettingsMsg');
      new MutationObserver(() => { if (msg.textContent) window.__sttSaid.push(msg.textContent); })
        .observe(msg, { childList: true, characterData: true, subtree: true });
    });
  };
  const saved = async (page) => {
    await page.waitForFunction(() => window.__sttSaid.length > 0);
    const said = await page.evaluate(() => window.__sttSaid.splice(0));
    if (!said.includes('Saved')) out.errors.push('the card said ' + JSON.stringify(said));
  };
  const card = (page) => page.evaluate(() => {
    const sel = document.getElementById('set-sttProviderSelect');
    const note = document.getElementById('set-sttProviderNote');
    const row = sel.closest('.settings-row').getBoundingClientRect();
    const box = note.getBoundingClientRect();
    return {
      heading: sel.closest('.admin-card').querySelector('h2').textContent.trim(),
      value: sel.value,
      options: [...sel.options].map((o) => [o.value, o.textContent]),
      note: [...note.children].map((n) => n.textContent),
      describedBy: sel.getAttribute('aria-describedby'),
      gap: Math.round(box.top - row.bottom),
      noteShown: box.height > 0,
      modelShown: getComputedStyle(document.getElementById('set-sttModelRow')).display !== 'none',
      recognition: !!(window.SpeechRecognition || window.webkitSpeechRecognition),
    };
  });

  // ── The card: each provider chosen, saved, and chosen after a reload ──
  const ctx = await contextFor(admin);
  let page = await pageIn(ctx);
  await openCard(page);
  out.fresh = await card(page);
  for (const choice of ['local', 'browser', 'endpoint:' + out.endpoint, 'disabled']) {
    await page.selectOption('#set-sttProviderSelect', choice);
    await saved(page);
    if (choice === 'local') {
      await page.waitForFunction(() => /not installed|not downloaded/.test(
        document.getElementById('set-sttProviderNote').textContent));
    }
    out.chosen[choice] = await card(page);
    out.server[choice] = await read();
    await page.close();
    page = await pageIn(ctx);
    await openCard(page);
    if (choice === 'local') {
      await page.waitForFunction(() => /Downloading its model/.test(
        document.getElementById('set-sttProviderNote').textContent));
    }
    out.reloaded[choice] = await card(page);
  }
  // The language, which the browser's recognition is given too.
  await page.selectOption('#set-sttProviderSelect', 'browser');
  await saved(page);
  await page.fill('#set-sttLangInput', 'en-GB');
  await page.press('#set-sttLangInput', 'Tab');
  await page.waitForFunction(async () => {
    const s = await (await fetch('/api/auth/settings')).json();
    return s.stt_language === 'en-GB';
  });
  out.server.language = await read();
  await ctx.close();

  // ── A member may not set it: the route the card saves through ──
  const asMember = await contextFor(member);
  out.memberSave = (await asMember.request.post(BASE + '/api/auth/settings',
    { data: { stt_enabled: true, stt_provider: 'local' } })).status();
  await asMember.close();
  out.afterMember = await read();

  // ── The microphone in the chat ──
  const record = async (context, name) => {
    const page = await pageIn(context);
    // Every toast, kept in the page: each is read by the step that waits on it.
    await page.evaluate(() => {
      window.__said = [];
      const toast = document.getElementById('toast');
      new MutationObserver(() => { if (toast.textContent) window.__said.push(toast.textContent); })
        .observe(toast, { childList: true, subtree: true, characterData: true });
    });
    await page.waitForFunction(() => {
      const b = document.querySelector('.send-btn');
      return b && b.dataset.mode === 'mic';
    });
    await page.click('.send-btn');
    // Recording, or the sentence that says why not — never a wait on a state
    // a refused microphone leaves within one frame.
    await page.waitForFunction(() => window.__said.some((s) =>
      /^(Recording|This browser has no speech|Microphone|No microphone)/.test(s)));
    await page.waitForTimeout(1200);
    if (await page.evaluate(() => document.querySelector('.send-btn').dataset.mode === 'recording')) {
      await page.click('.send-btn');
    }
    await page.waitForFunction(() => document.querySelector('.send-btn').dataset.mode !== 'recording');
    await page.waitForFunction(() => document.getElementById('message').value
      || (window.fileHandlerModule && window.fileHandlerModule.getPendingCount() > 0)
      || window.__said.some((s) => /^Microphone|^No microphone/.test(s)));
    await page.waitForTimeout(300);
    out.mic[name] = await page.evaluate(() => ({
      message: document.getElementById('message').value,
      attached: window.fileHandlerModule.getPendingCount(),
      lang: window.__fakeLang === undefined ? null : window.__fakeLang,
      said: window.__said.slice(),
    }));
    await page.close();
  };
  // Chrome's order: the last final result after `stop()`, then `end`.
  const chromeLike = (heard) => {
    class Recognition {
      start() { window.__fakeLang = this.lang; }
      stop() {
        setTimeout(() => {
          if (heard === null) {
            if (this.onerror) this.onerror({ error: 'network' });
          } else {
            const result = [{ transcript: heard }];
            result.isFinal = true;
            if (this.onresult) this.onresult({ resultIndex: 0, results: [result] });
          }
          setTimeout(() => { if (this.onend) this.onend(); }, 50);
        }, 300);
      }
    }
    window.SpeechRecognition = Recognition;
    window.webkitSpeechRecognition = Recognition;
  };
  const noRecognition = () => {
    for (const name of ['SpeechRecognition', 'webkitSpeechRecognition']) {
      try { Object.defineProperty(window, name, { value: undefined, configurable: true, writable: true }); } catch (_) {}
    }
  };

  let c = await contextFor(admin, `(${chromeLike})(${JSON.stringify(HEARD)})`);
  await record(c, 'browser');
  await c.close();
  c = await contextFor(admin, `(${chromeLike})(null)`);
  await record(c, 'unreachable');
  await c.close();
  c = await contextFor(admin, `(${noRecognition})()`);
  const bare = await pageIn(c);
  await openCard(bare);
  out.withoutRecognition = await card(bare);
  await bare.close();
  await record(c, 'none');
  await c.close();

  await api('post', '/api/auth/settings',
    { stt_enabled: true, stt_provider: 'endpoint:' + out.endpoint, stt_model: 'whisper-1' });
  c = await contextFor(admin);
  await record(c, 'endpoint');
  await c.close();

  await setup.close();
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("stt-pw") / "stt.cjs"
    script.write_text(_SCRIPT % {"heard": json.dumps(HEARD)}, encoding="utf-8")
    log: list = []
    with demo_model.DemoModel(log=log, transcript=SPOKEN_TO_THE_ENDPOINT) as model:
        proc = subprocess.run([NODE, str(script), app_url, model.base_url],
                              capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stderr[-3000:] + proc.stdout[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    out["transcribed"] = [e for e in log if e.get("transcription")]
    return out


GOOGLE = "In Chrome, the audio goes to Google"


def test_ai_defaults_has_a_speech_to_text_card_offering_every_provider(drive):
    """The row's `Verify:`, as the owner ruled it: all options available."""
    fresh = drive["fresh"]
    assert fresh["heading"] == "Speech to Text"
    values = [v for v, _ in fresh["options"]]
    assert values == ["disabled", "local", "browser", "endpoint:" + drive["endpoint"]], values
    assert fresh["value"] == "disabled", "a fresh install is off (`Law 16`)"
    assert drive["errors"] == [], drive["errors"]


def test_the_browser_choice_says_where_the_audio_goes_where_it_is_chosen(drive):
    browser_option = dict(drive["fresh"]["options"])["browser"]
    assert "in Chrome, the audio goes to Google" in browser_option, browser_option
    chosen = drive["chosen"]["browser"]
    assert chosen["note"][0].startswith(GOOGLE), chosen["note"]
    assert chosen["describedBy"] == "set-sttProviderNote"
    assert chosen["noteShown"] and 0 <= chosen["gap"] <= 24, "the sentence is under the list it explains"
    for other in ("local", "disabled", "endpoint:" + drive["endpoint"]):
        assert not any(GOOGLE in line for line in drive["chosen"][other]["note"]), other


def test_each_provider_saves_and_is_still_chosen_after_a_reload(drive):
    endpoint = "endpoint:" + drive["endpoint"]
    for choice in ("local", "browser", endpoint, "disabled"):
        server = drive["server"][choice]
        assert server["provider"] == choice, server
        assert server["enabled"] is (choice != "disabled"), server
        assert server["stats_provider"] == choice, "the chat's microphone reads this"
        assert drive["reloaded"][choice]["value"] == choice, (choice, drive["reloaded"][choice])
    assert drive["server"][endpoint]["model"] == "whisper-1"
    assert drive["server"]["local"]["model"] == "base"
    assert drive["chosen"]["local"]["modelShown"] and not drive["chosen"]["browser"]["modelShown"]


def test_local_whisper_says_the_switch_it_is_behind_and_why_it_is_not_running(drive):
    note = " ".join(drive["reloaded"]["local"]["note"])
    assert "Whisper runs on this server" in note
    assert "Downloading its model: " in note, note
    # faster-whisper is not installed where the suite runs; the gate's own
    # sentence when it is (`B1565`, `tests/test_local_whisper_asks_before_it_downloads.py`).
    said = drive["server"]["local"]["unavailable"]
    assert said and said in note, (said, note)


def test_a_member_may_not_set_it(drive):
    assert drive["memberSave"] == 403
    assert drive["afterMember"]["provider"] == "browser", "the refused save changed nothing"


def test_the_browsers_own_recognition_fills_the_message_box(drive):
    """The end to end the row asks for. The last words arrive after `stop()`;
    the recorder waits for them now."""
    mic = drive["mic"]["browser"]
    assert mic["message"] == HEARD, mic
    assert mic["attached"] == 0, "nothing attached: the words were heard"
    assert mic["lang"] == "en-GB", "the language Settings holds reached the recognition"
    assert not any("No speech detected" in s for s in mic["said"]), mic["said"]


def test_a_browser_without_recognition_says_so_on_the_card_and_at_the_microphone(drive):
    plain = ("This browser has no speech recognition of its own, so a recording is "
             "attached to the message as a sound file instead.")
    bare = drive["withoutRecognition"]
    assert bare["recognition"] is False
    assert bare["value"] == "browser" and plain in bare["note"], bare["note"]
    mic = drive["mic"]["none"]
    assert any(s.startswith(plain) for s in mic["said"]), mic["said"]
    assert mic["attached"] == 1 and mic["message"] == "", mic


def test_a_recognition_service_that_cannot_be_reached_is_said(drive):
    mic = drive["mic"]["unreachable"]
    assert any(s.startswith("The browser’s speech recognition could not reach its service "
                            "(in Chrome, Google’s). The recording is attached instead.")
               for s in mic["said"]), mic["said"]
    assert mic["attached"] == 1, mic


def test_an_endpoint_transcribes_through_the_server(drive):
    mic = drive["mic"]["endpoint"]
    assert mic["message"] == SPOKEN_TO_THE_ENDPOINT, mic
    assert drive["transcribed"], "the endpoint's /audio/transcriptions was asked"
    # The language was set as the browser takes it (`en-GB`); an endpoint, as
    # Whisper, takes the ISO 639-1 code and refuses the tag.
    assert [t["language"] for t in drive["transcribed"]] == ["en"]
