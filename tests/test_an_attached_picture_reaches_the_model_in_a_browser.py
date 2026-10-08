# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx5-vision `B-NEW-1` — an attached picture reaches the model, driven end to end.

The owner, 2026-10-08, from a phone: *"attaching an image to the chat, doesnt
actually feed said image to the LLM … It shows the attached image but the LLM
literally says 'there's no image'."* (`/work/notes/owner-shots/bug1-image-not-seen.jpg`:
`gemma-4-26b-a4…`, Agent mode, two messages, the thumbnail still in the
composer while the reply streamed.)

`Law 20`: nothing between the person and the model's socket is faked.
`capture.Server` boots this checkout's `app.py` on a throwaway data directory
with authentication on; a headless Chromium signs in as the admin and does what
a person does — picks the model, attaches with the file picker (the phone's
cropper answered *Original*), pastes, drops, presses Enter or Steer now; the
real page uploads, sends and draws. The model is the showcase's scripted
stand-in (`demo_model.DemoModel`) under the owner's model's name, keeping every
request it is sent, and the assertions are about those requests: an OpenAI
`image_url` part whose bytes are the file's bytes. Its scripted answer says how
many pictures it got, so the reply on screen says it too.

**Red on `0345288`**, measured with this file: every first message of a new
chat (picker, paste, drop, two pictures; Chat 1440 and Agent 390) sent no
picture and left the thumbnail; a model the name list does not know was sent
none; a refusal read *"The model didn't answer (HTTP 400)."*; a steer with a
picture steered without it. A second message in an existing chat was fine —
that case guards the ordinary path.
"""
from __future__ import annotations

import hashlib
import base64
import io
import json
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "scripts" / "showcase"
sys.path.insert(0, str(SHOWCASE))

import demo_model  # noqa: E402
import seed  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

VISION = "gemma-4-26b-a4b"        # the owner's model, as an endpoint lists it
UNKNOWN = "text-box-7b"           # a name the list does not know; its server says nothing
REFUSING = "text-only-3b"         # a server that cannot see, and says so
REFUSAL = (400, "image input is not supported - hint: if this is unexpected, "
                "you may need to provide the mmproj")


def _say(ctx):
    n = len(ctx.get("images") or [])
    return "Sent no picture." if not n else f"Sent {n} picture{'s' if n != 1 else ''}."


_LONG = " ".join(["Working through the plan one step at a time."] * 14)
_PLAN = {"plan": "- [ ] look\n- [ ] answer"}
WORDS = {
    "a": "A: what is in this image?",
    "b": "B: what is in this image?",
    "p": "P: what is in this pasted image?",
    "q": "Q: describe both pictures.",
    "d0": "D: hello there.",
    "d": "D: and what is in this image?",
    "i0": "I: hello there.",
    "i": "I: and this one?",
    "r": "R: what is this?",
    "m0": "M: hello there.",
    "m": "M: is anything attached?",
    "l2": "L: steer, look at this picture.",
}
SCRIPT = [{"key": k, "title": "Pictures", "turns": [{"user": w, "steps": [{"say": _say}]}]}
          for k, w in WORDS.items()]
SLOW = "L: make a careful plan, then look."
SCRIPT.append({"key": "l", "title": "Slow", "turns": [{"user": SLOW,
               "steps": [{"think": _LONG, "call": "update_plan", "args": _PLAN},
                         {"think": _LONG, "call": "update_plan", "args": _PLAN},
                         {"say": "Planned."}]}]})


def _pictures():
    from PIL import Image, ImageDraw
    cat = Image.new("RGB", (320, 240), (40, 30, 25))
    ImageDraw.Draw(cat).ellipse((80, 50, 240, 200), fill=(150, 90, 40))
    b1 = io.BytesIO()
    cat.save(b1, "JPEG", quality=85)
    sq = Image.new("RGB", (200, 200), (20, 120, 200))
    ImageDraw.Draw(sq).rectangle((50, 50, 150, 150), fill=(250, 250, 250))
    b2 = io.BytesIO()
    sq.save(b2, "PNG")
    return b1.getvalue(), b2.getvalue()


_DRIVE = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const C = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = {};
const COLOURS = { dark: { bg: '#282c34', fg: '#9cdef2', panel: '#111111', border: '#355a66', red: '#e06c75' },
                  light: { bg: '#f0ebe3', fg: '#5a5248', panel: '#faf6f0', border: '#d4cdc2', red: '#c47d5a' } };

async function open(browser, mode, size, theme) {
  const phone = size[0] < 500;
  const ctx = await browser.newContext({ viewport: { width: size[0], height: size[1] }, isMobile: phone,
    hasTouch: phone, serviceWorkers: 'block' });
  await ctx.addInitScript((a) => {
    try {
      localStorage.setItem('pantheon-theme', a.theme);
      localStorage.setItem('pantheon-hint-drag-to-snap-seen', '1');
      localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
      localStorage.setItem('pantheon-toggles', JSON.stringify({ mode: a.mode }));
    } catch (_) {}
  }, { theme: JSON.stringify({ name: theme, colors: COLOURS[theme] }), mode });
  const r = await ctx.request.post(C.base + '/api/auth/login',
    { data: { username: C.user, password: C.password, remember: true } });
  if (!r.ok()) throw new Error('login ' + r.status());
  const page = await ctx.newPage();
  page.__errors = [];
  page.on('pageerror', (e) => page.__errors.push(String(e.message || e)));
  await page.goto(C.base + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);
  return { ctx, page };
}

async function pick(page, model) {
  await page.evaluate(() => document.activeElement && document.activeElement.blur && document.activeElement.blur());
  await page.waitForTimeout(300);
  try { await page.click('#model-picker-btn', { timeout: 4000 }); }
  catch (_) { await page.evaluate(() => document.getElementById('model-picker-btn').click()); }
  await page.waitForTimeout(1000);
  await page.locator('.model-switch-item', { hasText: model }).first().click();
  await page.waitForTimeout(1000);
}

async function attach(page, paths) {
  await page.setInputFiles('#file-input', paths);
  for (let i = 0; i < 6; i++) {   // a phone crops each picture first: keep the original
    await page.waitForTimeout(600);
    const keep = page.locator('.attach-crop-overlay .attach-crop-btn[data-action="original"]').first();
    if (await keep.isVisible().catch(() => false)) { await keep.click(); continue; }
    break;
  }
  await page.waitForTimeout(400);
}

async function carry(page, files, how) {
  await page.evaluate(({ files, how }) => {
    const dt = new DataTransfer();
    for (const f of files) {
      const bin = Uint8Array.from(atob(f.b64), (c) => c.charCodeAt(0));
      dt.items.add(new File([bin], f.name, { type: f.mime }));
    }
    if (how === 'paste') {
      const ta = document.getElementById('message');
      ta.focus();
      ta.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
    } else {
      const zone = document.getElementById('chat-container');
      zone.dispatchEvent(new DragEvent('dragover', { dataTransfer: dt, bubbles: true, cancelable: true }));
      zone.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
    }
  }, { files, how });
  await page.waitForTimeout(900);
}

const lastReply = (page) => page.evaluate(() => {
  const err = [...document.querySelectorAll('.reply-error-text')].pop();
  const body = [...document.querySelectorAll('.msg-ai .body')].pop();
  return (err ? 'ERROR ' + err.textContent : '') || (body ? body.textContent.trim() : '');
});

async function send(page, text, until = /Sent (no|\d+) picture|^ERROR /, ms = 30000) {
  const before = await page.evaluate(() => document.querySelectorAll('.msg-ai').length);
  await page.fill('#message', text);
  await page.press('#message', 'Enter');
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    await page.waitForTimeout(400);
    const n = await page.evaluate(() => document.querySelectorAll('.msg-ai').length);
    if (n > before && until.test(await lastReply(page))) break;
  }
  await page.waitForTimeout(900);
}

const state = (page) => page.evaluate(() => {
  const user = [...document.querySelectorAll('.msg-user')].pop();
  return {
    tray: document.querySelectorAll('#attach-strip .thumb').length,
    bubblePictures: user ? user.querySelectorAll('.attach-image-preview img, .attach-card').length : 0,
    toasts: [...document.querySelectorAll('.toast, .error-toast, .ui-toast')].map((t) => t.textContent.trim()),
  };
});

async function scenario(browser, name, { mode = 'chat', size = [1440, 900], theme = 'dark' }, body) {
  const { ctx, page } = await open(browser, mode, size, theme);
  const o = {};
  try { Object.assign(o, (await body(page)) || {}); } catch (e) { o.crash = String(e && e.message || e); }
  o.reply = await lastReply(page).catch(() => '');
  Object.assign(o, await state(page).catch(() => ({})));
  o.errors = page.__errors;
  out[name] = o;
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const cat = { b64: C.catB64, name: 'cat.jpg', mime: 'image/jpeg' };
  const square = { b64: C.squareB64, name: 'square.png', mime: 'image/png' };

  await scenario(browser, 'a', { mode: 'chat' }, async (page) => {
    await pick(page, C.vision);
    await attach(page, C.cat);
    await send(page, C.words.a);
  });
  await scenario(browser, 'b', { mode: 'agent', size: [390, 844], theme: 'light' }, async (page) => {
    await pick(page, C.vision);
    await attach(page, C.cat);
    await send(page, C.words.b);
  });
  await scenario(browser, 'p', { mode: 'agent' }, async (page) => {
    await pick(page, C.vision);
    await carry(page, [cat], 'paste');
    await send(page, C.words.p);
  });
  await scenario(browser, 'q', { mode: 'chat' }, async (page) => {
    await pick(page, C.vision);
    await carry(page, [cat, square], 'drop');
    await send(page, C.words.q);
  });
  await scenario(browser, 'd', { mode: 'agent' }, async (page) => {
    await pick(page, C.vision);
    await send(page, C.words.d0);
    await attach(page, C.cat);
    await send(page, C.words.d);
  });
  await scenario(browser, 'i', { mode: 'chat' }, async (page) => {
    await pick(page, C.vision);
    await send(page, C.words.i0);
    await pick(page, C.unknown);
    await attach(page, C.cat);
    await send(page, C.words.i);
  });
  await scenario(browser, 'r', { mode: 'chat' }, async (page) => {
    await pick(page, C.refusing);
    await attach(page, C.cat);
    await send(page, C.words.r);
  });
  await scenario(browser, 'm', { mode: 'chat' }, async (page) => {
    await pick(page, C.vision);
    await send(page, C.words.m0);
    await attach(page, C.cat);
    const before = await state(page);
    await page.locator('#sidebar-new-chat-btn').first().click();
    await page.waitForTimeout(1200);
    const inNew = await state(page);
    await send(page, C.words.m);
    return { trayBefore: before.tray, trayInNew: inNew.tray };
  });
  await scenario(browser, 'l', { mode: 'agent' }, async (page) => {
    await pick(page, C.vision);
    await page.fill('#message', C.words.l);
    await page.press('#message', 'Enter');
    await page.waitForSelector('.steer-bar-btn', { timeout: 20000 });
    await attach(page, C.cat);
    await page.fill('#message', C.words.l2);
    await page.locator('.steer-bar-btn').first().click();
    await page.waitForTimeout(800);
    const steered = await state(page);
    const t0 = Date.now();
    while (Date.now() - t0 < 60000) {
      await page.waitForTimeout(500);
      if (/Sent (no|\d+) picture/.test(await lastReply(page))) break;
    }
    await page.waitForTimeout(800);
    return { toastsAtSteer: steered.toasts };
  });

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(tmp_path_factory):
    import capture
    import httpx

    work = tmp_path_factory.mktemp("fx5vision")
    data = work / "data"
    data.mkdir()
    server = capture.Server(sys.executable, data, capture._free_port(), extra_env={
        "PANTHEON_DISABLE_MCP": "1",
        # The drive attaches nine times in a few minutes from one address.
        "PANTHEON_UPLOAD_BURST_LIMIT": "100"})
    try:
        server.start(timeout=150)
    except RuntimeError as e:
        server.stop()
        pytest.fail(f"{e}\n{server.log_path.read_text(encoding='utf-8', errors='replace')[-3000:]}")
    cat, square = _pictures()
    (work / "cat.jpg").write_bytes(cat)
    logs = {VISION: [], UNKNOWN: [], REFUSING: []}
    try:
        client = httpx.Client(base_url=server.base, timeout=180)
        password = secrets.token_urlsafe(18)
        seed.setup_admin(client, password)
        with demo_model.DemoModel(log=logs[VISION], conversations=SCRIPT, model_id=VISION,
                                  pace=0.02) as vision, \
                demo_model.DemoModel(log=logs[UNKNOWN], conversations=SCRIPT, model_id=UNKNOWN) as unknown, \
                demo_model.DemoModel(log=logs[REFUSING], conversations=SCRIPT, model_id=REFUSING,
                                     refuse_images=REFUSAL) as refusing:
            for name, m in (("Vision box", vision), ("Text box", unknown), ("Blind box", refusing)):
                seed._ok(client.post("/api/model-endpoints", data={
                    "name": name, "base_url": m.base_url, "supports_tools": "true",
                    "require_models": "true"}), name)
            config = {
                "base": server.base, "user": seed.PERSON["username"], "password": password,
                "vision": VISION, "unknown": UNKNOWN, "refusing": REFUSING, "words": {**WORDS, "l": SLOW},
                "cat": str(work / "cat.jpg"),
                "catB64": base64.b64encode(cat).decode(), "squareB64": base64.b64encode(square).decode(),
            }
            (work / "config.json").write_text(json.dumps(config))
            (work / "drive.cjs").write_text(_DRIVE)
            proc = subprocess.run([NODE, str(work / "drive.cjs"), str(work / "config.json")],
                                  capture_output=True, text=True, timeout=600, cwd=ROOT)
            assert proc.returncode == 0, proc.stderr[-3000:]
            seen = json.loads(proc.stdout.strip().splitlines()[-1])
        yield {"seen": seen, "logs": logs,
               "sha": {"cat": hashlib.sha256(cat).hexdigest(), "square": hashlib.sha256(square).hexdigest()}}
    finally:
        server.stop()


def _asked(drive, key, model=VISION):
    """The streamed requests the model was sent for this scenario's words."""
    return [e for e in drive["logs"][model] if e["stream"] and e["conv"] == key]


def _pictures_in_turn(entry):
    """The pictures in the person's latest message of a request, as sha256s,
    decoded from the `image_url` parts themselves."""
    msgs = entry["messages"]
    last_user = max(i for i, m in enumerate(msgs) if m.get("role") == "user")
    return [i["sha256"] for i in demo_model.images_sent(msgs) if i["message"] == last_user]


def _ok(drive, key):
    seen = drive["seen"][key]
    assert not seen.get("crash"), seen
    assert seen["errors"] == [], seen["errors"]
    return seen


# ── the owner's report: a new chat, a picture, the first message ────────────

def test_a_new_chats_first_message_sends_its_picture_in_chat_mode(drive):
    seen = _ok(drive, "a")
    asked = _asked(drive, "a")
    assert asked, "the model was never asked"
    assert _pictures_in_turn(asked[0]) == [drive["sha"]["cat"]], (
        "the model was sent no picture — the owner's report"
    )
    assert seen["reply"] == "Sent 1 picture."
    assert seen["tray"] == 0, "the composer kept a thumbnail the send had not taken"
    assert seen["bubblePictures"] == 1, "the person's message does not show the picture it sent"


def test_on_a_phone_in_agent_mode_as_the_owner_sent_it(drive):
    seen = _ok(drive, "b")
    asked = _asked(drive, "b")
    assert asked and all(_pictures_in_turn(e) == [drive["sha"]["cat"]] for e in asked)
    assert seen["reply"] == "Sent 1 picture." and seen["tray"] == 0 and seen["bubblePictures"] == 1


def test_a_pasted_picture_on_the_first_message(drive):
    seen = _ok(drive, "p")
    asked = _asked(drive, "p")
    assert asked and _pictures_in_turn(asked[0]) == [drive["sha"]["cat"]]
    assert seen["tray"] == 0


def test_two_dropped_pictures_on_the_first_message_in_order(drive):
    seen = _ok(drive, "q")
    asked = _asked(drive, "q")
    assert asked and _pictures_in_turn(asked[0]) == [drive["sha"]["cat"], drive["sha"]["square"]]
    assert seen["reply"] == "Sent 2 pictures." and seen["tray"] == 0


def test_a_second_message_in_agent_mode_still_sends_its_picture(drive):
    """The ordinary path, green before and after."""
    seen = _ok(drive, "d")
    asked = _asked(drive, "d")
    assert asked and _pictures_in_turn(asked[0]) == [drive["sha"]["cat"]]
    assert _pictures_in_turn(_asked(drive, "d0")[0]) == []
    assert seen["reply"] == "Sent 1 picture."


# ── what decides whether the model gets it (`B-NEW-2`) ──────────────────────

def test_after_switching_to_a_model_nothing_knows_about_it_is_sent_the_picture(drive):
    seen = _ok(drive, "i")
    asked = _asked(drive, "i", model=UNKNOWN)
    assert asked, "the switch did not reach the other model"
    assert _pictures_in_turn(asked[0]) == [drive["sha"]["cat"]], (
        "the picture was swapped for words on a guess from the model's name"
    )
    assert seen["reply"] == "Sent 1 picture."


def test_a_model_that_cannot_see_says_so_in_the_chat(drive):
    seen = _ok(drive, "r")
    asked = _asked(drive, "r", model=REFUSING)
    assert asked and _pictures_in_turn(asked[0]) == [drive["sha"]["cat"]]
    assert seen["reply"] == f"ERROR {REFUSING} refused the picture (HTTP 400).", seen["reply"]


# ── the strip shows what the send will take ─────────────────────────────────

def test_new_chat_does_not_show_the_last_chats_picture(drive):
    seen = _ok(drive, "m")
    assert seen["trayBefore"] == 1
    assert seen["trayInNew"] == 0, (
        "New chat kept drawing the last chat's picture over an empty composer"
    )
    asked = _asked(drive, "m")
    assert asked and _pictures_in_turn(asked[0]) == []
    assert seen["reply"] == "Sent no picture."


def test_steer_now_with_a_picture_sends_it_after_the_run(drive):
    """`B-NEW-3`: the message waits in the queue with its picture."""
    seen = _ok(drive, "l")
    assert any("A picture can't steer a running reply" in t for t in seen["toastsAtSteer"]), seen
    asked = _asked(drive, "l2")
    assert asked, "the queued message never went"
    assert _pictures_in_turn(asked[0]) == [drive["sha"]["cat"]]
    assert seen["reply"] == "Sent 1 picture." and seen["tray"] == 0
