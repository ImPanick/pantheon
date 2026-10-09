# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx7-dup (`B-NEW-4`) — one typed message, one row, one copy in the prompt.

The owner's own export holds their message twice
(`/work/notes/owner-shots/2026-10-09-osrs-chat-export.md`, lines 1 and 4) and
the model's reasoning for the next turn reads it twice — *"Second section:
Research: … Third section: Repeat of research request"*.

Nothing but a browser shows why. The number that was wrong was a count of
`.msg` elements in `#chat-history`, and the reason it was wrong is that an
agent turn is drawn as **two** `.msg` for one saved reply: a holder that is
hidden when its round only thought, and the `.msg-continuation` bubble the
turn's footer sits under (`B-NEW-2`). No sandbox draws a chat; only the real
renderer does. So this file boots the real app against a **recording**
OpenAI-compatible model and drives Retry and Edit in headless Chromium, then
reads three things and compares them: what was typed, what is in
`chat_messages`, and what is in the recorded request's `messages`.

Measured on `3b40a4e` with this chat: 6 `.msg` for 4 rows, the last user bubble
at DOM index 3 and row index 2, so Retry's `keep_count = 3` kept the message it
was asked to drop — after which the resend stored a second copy, the live chat
still drew one bubble (`_hideUserBubble`), a reload drew two, and the request
carried the person's words twice. Edit stored the old text *and* the new one.

Driven by hand on port 8782 while this lane was built; the fixture takes free
ports so it can run beside the suite. Skipped, with the reason, where node,
the `playwright` package or its Chromium is not installed.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SID = "fx7-dup-browser"
MODEL = "recorder-1"
CREDS = {"username": "dupprobe", "password": "dup-probe-pass-1"}

RESEARCH = ("Research: Find out the ins and outs of the new Oldschool RuneScape Raids "
            "releasing on October 20th... its called the fractured archive.")
FOLLOWUP = "Why are you searching for game content on imdb .. and old navy clothing store? Wtf"
EDITED = "Why did you search imdb? Try the OSRS wiki."


def _browser():
    node = shutil.which("node")
    if not node:
        return None, "node binary not on PATH"
    probe = subprocess.run(
        [node, "-e",
         "const { chromium } = require('playwright');"
         "const fs = require('fs');"
         "const p = chromium.executablePath();"
         "process.stdout.write(fs.existsSync(p) ? p : '');"],
        capture_output=True, text=True, timeout=60)
    if probe.returncode != 0:
        return None, "the playwright node package is not installed"
    if not probe.stdout.strip():
        return None, "playwright has no Chromium downloaded"
    return node, None


NODE, _SKIP = _browser()
pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Recorder:
    """An OpenAI-compatible model that keeps every request it was sent.

    `Law 16`: loopback only, and it answers one short line, so what the cases
    read is Pantheon's own prompt assembly and nothing a model decided.
    """

    def __init__(self):
        self.requests: list = []
        self._lock = threading.Lock()
        recorder = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _json(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.rstrip("/").endswith("/models"):
                    self._json({"object": "list", "data": [{"id": MODEL, "object": "model"}]})
                    return
                self._json({"error": "not found"}, 404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    payload = {}
                with recorder._lock:
                    recorder.requests.append(payload)
                if not payload.get("stream"):
                    self._json({"id": "c-" + uuid.uuid4().hex[:8], "object": "chat.completion",
                                "model": MODEL,
                                "choices": [{"index": 0, "finish_reason": "stop",
                                             "message": {"role": "assistant", "content": "Done."}}],
                                "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                                          "total_tokens": 2}})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                cid = "c-" + uuid.uuid4().hex[:8]
                for delta, finish in (({"role": "assistant", "content": ""}, None),
                                      ({"content": "Done."}, None),
                                      ({}, "stop")):
                    frame = {"id": cid, "object": "chat.completion.chunk",
                             "created": int(time.time()), "model": MODEL,
                             "choices": [{"index": 0, "delta": delta,
                                          "finish_reason": finish}]}
                    self.wfile.write(b"data: " + json.dumps(frame).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        self.port = _free_port()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def typed_copies(self, text: str) -> list:
        """How many times `text` appears in each recorded request's messages."""
        def flat(content):
            if isinstance(content, list):
                return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            return str(content or "")
        with self._lock:
            payloads = list(self.requests)
        return [sum(1 for m in (p.get("messages") or []) if text[:40] in flat(m.get("content")))
                for p in payloads]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# Two agent turns, seeded before the app starts so no model has to do rounds:
# `round_thinking` is the metadata the chat route saves for a multi-round reply
# (`_thinking_record`), and it is what makes the renderer draw a holder and a
# `.msg-continuation` bubble — two `.msg` for one row.
_SEED = r'''
import json, sys, uuid
from datetime import datetime, timedelta
sys.path.insert(0, sys.argv[1])
from core.database import SessionLocal, Session as DbSession, ChatMessage as DbChatMessage, init_db

SID, OWNER, URL, MODEL = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
RESEARCH, FOLLOWUP = sys.argv[6], sys.argv[7]
init_db()
db = SessionLocal()
t0 = datetime(2026, 10, 9, 9, 0, 0)
try:
    db.add(DbSession(id=SID, name="OSRS raids", owner=OWNER, headers={},
                     endpoint_url=URL, model=MODEL, message_count=4))
    # The record a real two-round agent turn saves, copied field for field from
    # one this lane drove on 8782: the first round only thought and called a
    # tool, the second said the words. `round_texts[0] == ""` is why the first
    # bubble is hidden, and `r > 0` is why the second carries
    # `msg-continuation` (`chatRenderer.js:4157`).
    meta = json.dumps({
        "model": MODEL,
        "round_thinking": ["Plan the search."],
        "thinking": "Plan the search.",
        "round_texts": ["", "Done."],
        "round_models": [MODEL, MODEL],
        "tool_events": [{"round": 1, "model": MODEL, "tool": "web_search",
                         "desc": "web_search: fractured archive osrs raid",
                         "command": "fractured archive osrs raid",
                         "full_command": "fractured archive osrs raid",
                         "status": "ok", "exit_code": 0,
                         "output": "No search results found."}],
    })
    rows = [("user", RESEARCH, None), ("assistant", "Done.", meta),
            ("user", FOLLOWUP, None), ("assistant", "Done.", meta)]
    for n, (role, content, m) in enumerate(rows):
        db.add(DbChatMessage(id=str(uuid.uuid4()), session_id=SID, role=role,
                             content=content, meta_data=m,
                             timestamp=t0 + timedelta(minutes=n)))
    db.commit()
    print(4)
finally:
    db.close()
'''


@pytest.fixture(scope="module")
def chat_app(tmp_path_factory):
    recorder = _Recorder()
    data = tmp_path_factory.mktemp("dup-app")
    chat_url = recorder.base.rstrip("/") + "/chat/completions"
    env = dict(os.environ, PANTHEON_DATA_DIR=str(data), APP_BIND="127.0.0.1",
               PANTHEON_DISABLE_MCP="1",
               DATABASE_URL=f"sqlite:///{data / 'app.db'}")
    seeder = data / "seed.py"
    seeder.write_text(_SEED, encoding="utf-8")
    seeded = subprocess.run(
        [sys.executable, "-I", str(seeder), str(ROOT), SID, CREDS["username"],
         chat_url, MODEL, RESEARCH, FOLLOWUP],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert seeded.returncode == 0, seeded.stderr[-2000:]
    assert seeded.stdout.strip().splitlines()[-1] == "4", seeded.stdout

    port = _free_port()
    env["APP_PORT"] = str(port)
    log = open(data / "app.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 180
        while True:
            if proc.poll() is not None:
                log.flush()
                pytest.fail("the app exited during start-up:\n"
                            + (data / "app.log").read_text(encoding="utf-8")[-3000:])
            try:
                with urllib.request.urlopen(url + "/login", timeout=2) as res:
                    if res.status == 200:
                        break
            except (urllib.error.URLError, OSError):
                pass
            if time.monotonic() > deadline:
                pytest.fail("the app did not answer /login within 180 s")
            time.sleep(0.5)
        yield url, recorder, data
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()
        recorder.stop()


_SCRIPT = r"""
const { chromium } = require('playwright');
const [BASE, SID, MODEL_BASE, ACTION, EDITED] = process.argv.slice(2);
const out = { errors: [], posted: [] };
const creds = { username: 'dupprobe', password: 'dup-probe-pass-1' };

const snap = (page) => page.evaluate(async (sid) => {
  const box = document.getElementById('chat-history');
  const msgs = Array.from(box.querySelectorAll('.msg'));
  const r = await fetch(`/api/history/${sid}?limit=200`, { credentials: 'same-origin' });
  const j = await r.json();
  const arr = Array.isArray(j) ? j : (j.messages || j.history || []);
  return { msgEls: msgs.length,
           classes: msgs.map((m) => m.className),
           rows: arr.map((m) => m.role + '|' + String(m.content || '').replace(/\s+/g, ' ')) };
}, SID);

async function idle(page) {
  const t0 = Date.now(); let quiet = 0;
  while (Date.now() - t0 < 180000) {
    const st = await page.evaluate(async (sid) => {
      let active = null;
      try { active = !!(await (await fetch(`/api/chat/stream_status/${sid}`,
        { credentials: 'same-origin' })).json()).active; } catch (_) {}
      const box = document.getElementById('chat-history');
      const btn = document.querySelector('.send-btn');
      return { active, streaming: box ? box.querySelectorAll('.msg.streaming').length : 0,
               mode: btn ? btn.dataset.mode : '' };
    }, SID);
    if (!st.active && !st.streaming && st.mode !== 'streaming' && st.mode !== 'pending') quiet++;
    else quiet = 0;
    if (quiet >= 4) return;
    await page.waitForTimeout(600);
  }
  out.errors.push('the chat never went idle');
}

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  page.on('request', (r) => {
    if (/\/api\/session\/[^/]+\/truncate/.test(r.url())) {
      out.posted.push(JSON.parse(r.postData() || '{}'));
    }
  });
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  // The endpoint the seeded chat already points at, so the model is one the
  // endpoint listed (`D-2026-10-07-02` §1) and the turn is allowed to run.
  await page.request.post(BASE + '/api/model-endpoints', {
    form: { name: 'Recorder', base_url: MODEL_BASE, supports_tools: 'false',
            require_models: 'true' } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 60000 });
  await page.waitForTimeout(1200);
  await page.evaluate(async (sid) => { await window.sessionModule.selectSession(sid); }, SID);
  await page.waitForTimeout(2500);

  out.before = await snap(page);
  out.math = await page.evaluate(() => {
    const box = document.getElementById('chat-history');
    const all = Array.from(box.querySelectorAll('.msg'));
    const users = all.filter((m) => m.classList.contains('msg-user'));
    return { domIndexOfNewestUser: all.indexOf(users[users.length - 1]) };
  });

  if (ACTION === 'retry') {
    // What *Retry* on a failed reply does: `_retryLastTurn`.
    await page.evaluate(() => {
      const box = document.getElementById('chat-history');
      const users = Array.from(box.querySelectorAll('.msg-user'))
        .filter((e) => !e.classList.contains('msg-user-queued'));
      window.chatModule.resendUserMessage(users[users.length - 1], { replaceFromHere: true });
    });
  } else {
    await page.evaluate(() => {
      const box = document.getElementById('chat-history');
      const users = Array.from(box.querySelectorAll('.msg-user'));
      window.chatModule.editUserMessage(users[users.length - 1]);
    });
    await page.waitForTimeout(700);
    await page.evaluate((edited) => {
      document.querySelector('.edit-textarea').value = edited;
      document.querySelector('.edit-save-btn').click();
    }, EDITED);
  }
  await page.waitForTimeout(2500);
  await idle(page);
  out.live = await snap(page);

  // What a person sees next time they open the chat, which is what the export
  // reads as well (`B-NEW-1`: the export is the server's history now).
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 60000 });
  await page.waitForTimeout(1200);
  await page.evaluate(async (sid) => { await window.sessionModule.selectSession(sid); }, SID);
  await page.waitForTimeout(2500);
  out.reloaded = await snap(page);

  await browser.close();
  process.stdout.write(JSON.stringify(out));
})().catch((e) => {
  out.fatal = String((e && e.stack) || e);
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
});
"""


def _drive(chat_app, action: str) -> dict:
    url, recorder, data = chat_app
    script = data / f"drive-{action}.js"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), url, SID, recorder.base, action, EDITED],
                          cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "fatal" not in out, out["fatal"]
    assert out["errors"] == [], out["errors"]
    return out


@pytest.fixture(scope="module")
def retried(chat_app):
    _url, recorder, _data = chat_app
    before = len(recorder.requests)
    out = _drive(chat_app, "retry")
    out["copies"] = recorder.typed_copies(FOLLOWUP)[before:]
    return out


@pytest.fixture(scope="module")
def edited(chat_app):
    return _drive(chat_app, "edit")


# ── the premise: the chat is drawn with more bubbles than it has rows ───────

def test_an_agent_turn_is_two_bubbles_and_one_row(retried):
    """The drift the arithmetic died on, and it must stay true or this file
    stops testing the chat the owner had. Four rows, six `.msg`: each reply's
    holder (hidden — its round only thought) and the `.msg-continuation` bubble
    its footer sits under."""
    before = retried["before"]
    assert len(before["rows"]) == 4, before["rows"]
    assert before["msgEls"] == 6, before["classes"]
    assert sum(1 for c in before["classes"] if "msg-continuation" in c) == 2
    assert retried["math"]["domIndexOfNewestUser"] == 3, \
        "the newest user bubble is the 4th `.msg` and the 3rd row — the old keep_count"


# ── Retry: saved once, sent once ───────────────────────────────────────────

def test_retry_leaves_one_copy_of_the_message_it_resent(retried):
    rows = [r for r in retried["live"]["rows"] if r.startswith("user|")]
    assert sum(1 for r in rows if FOLLOWUP[:40] in r) == 1, rows
    assert len(retried["live"]["rows"]) == 4, retried["live"]["rows"]


def test_retry_asks_for_the_message_and_not_for_a_bubble_count(retried):
    assert len(retried["posted"]) == 1, retried["posted"]
    sent = retried["posted"][0]
    assert "keep_count" not in sent
    assert sent["from_user_message"]["index_from_end"] == 0
    assert sent["from_user_message"]["text"].startswith(FOLLOWUP[:30])


def test_the_model_is_sent_the_persons_words_once(retried):
    """The half of the defect the owner's model complained about: *"Third
    section: Repeat of research request"*. Every request the resend produced
    carries the typed message exactly once."""
    assert retried["copies"], "the resend reached the model"
    assert max(retried["copies"]) == 1, retried["copies"]


def test_a_reload_draws_one_bubble_per_typed_message(retried):
    """One bubble while the turn is on screen was never the test:
    `_hideUserBubble` suppresses the resend's own bubble, so the second copy
    only showed itself on the next open — and in the export."""
    classes = retried["reloaded"]["classes"]
    assert sum(1 for c in classes if "msg-user" in c) == 2, classes
    rows = [r for r in retried["reloaded"]["rows"] if r.startswith("user|")]
    assert len(rows) == 2 and sum(1 for r in rows if FOLLOWUP[:40] in r) == 1, rows


# ── Edit: the edited message replaces the message, it does not join it ─────

def test_an_edited_message_replaces_the_one_it_edited(edited):
    rows = [r for r in edited["reloaded"]["rows"] if r.startswith("user|")]
    assert any(EDITED[:30] in r for r in rows), rows
    assert not any(FOLLOWUP[:40] in r for r in rows), \
        "the text the person replaced is still in the chat"
    assert len(rows) == 2, rows
