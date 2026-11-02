# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1738`, `B1739`. The message box's three helpers.

Panick (2026-11-01): typing `/` or `@` brought up no list. `/` is where the
skills are looked up, `@` is where an agent is summoned, and when a reply is
done the next most valuable step should already be in the box for Tab.

What it was: `/` opened a popup of slash *commands*, with the skills appended
after every command (a bare `/` showed fourteen commands and no skill), and
Enter on a half-typed name sent the half-typed name. `@` did nothing at all.
Nothing offered a next step.

The halves here: `src/next_step.py` run for real (the prompt it builds and the
answer it keeps), and the real app booted out of process and driven in
Chromium with real keys against a stand-in OpenAI-compatible model, so the
popups, the summon, the request and the ghost are the shipped ones.
"""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src import next_step as ns

from test_the_command_palette_in_a_browser import NODE as PW_NODE, _SKIP as PW_SKIP  # noqa: E402
from test_the_command_palette_in_a_browser import app_url  # noqa: E402,F401  (fixture)


# ── the prompt and the answer ───────────────────────────────────────────────

def test_the_prompt_reads_the_last_exchange_and_skips_tool_rows():
    history = [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "Help me plan a parser"},
        {"role": "tool", "content": "lots of tool output"},
        {"role": "assistant", "content": "Tokenise, build the tree, validate."},
    ]
    msgs = ns.build_messages(history)
    assert msgs[0]["content"] == ns.SYSTEM_PROMPT
    body = msgs[1]["content"]
    assert "Person: Help me plan a parser" in body
    assert "Assistant: Tokenise, build the tree, validate." in body
    assert "tool output" not in body and "you are helpful" not in body


def test_no_prompt_until_the_assistant_has_answered():
    assert ns.build_messages([]) is None
    assert ns.build_messages([{"role": "user", "content": "hi"}]) is None


def test_a_long_chat_is_cut_to_its_newest_messages():
    history = []
    for i in range(30):
        history.append({"role": "user", "content": f"question {i} " + "x" * 3000})
        history.append({"role": "assistant", "content": f"answer {i} " + "y" * 3000})
    rows = ns.tail(history)
    assert len(rows) <= ns.TAIL_MESSAGES
    assert rows[-1][0] == "assistant"
    assert sum(len(t) for _, t in rows) <= ns.TAIL_CHARS + ns.PER_MESSAGE_CHARS + 1
    # The end of a long reply is kept, which is where it says what is open.
    assert rows[-1][1].endswith("y" * 50)


def test_the_answer_is_one_clean_sentence():
    assert ns.clean('"Write the tests next."') == "Write the tests next."
    assert ns.clean("<think>hmm, what next</think>\nNext step: Ship it to staging.") == "Ship it to staging."
    assert ns.clean("- Add a retry to the fetch.\n- Also log it.") == "Add a retry to the fetch."
    assert ns.clean("NONE") == "" and ns.clean("none.") == ""
    assert ns.clean("<think>still thinking and cut off") == ""
    assert ns.clean("") == "" and ns.clean(None) == ""
    long = "Do this " * 60
    assert len(ns.clean(long)) <= ns.MAX_CHARS + 1


# ── in a real browser, against the real app ─────────────────────────────────

SUGGESTION = "Write the unit tests for the parser next, starting with the empty-input case."
REPLY = "Here is a plan for your parser: tokenise, then build the tree, then validate."


class _StandIn(BaseHTTPRequestHandler):
    """An OpenAI-compatible model: a streamed reply for the chat, and the
    suggestion for the call whose system prompt is `next_step`'s."""
    calls = []

    def log_message(self, *a):
        pass

    def _json(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._json({"object": "list", "data": [{"id": "stand-in-7b", "object": "model"}]})
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        system = next((m.get("content") for m in body.get("messages") or [] if m.get("role") == "system"), "")
        asks_next = str(system or "") == ns.SYSTEM_PROMPT
        type(self).calls.append({"next_step": asks_next, "stream": bool(body.get("stream"))})
        text = SUGGESTION if asks_next else REPLY
        if not body.get("stream"):
            return self._json({"id": "x", "object": "chat.completion", "model": "stand-in-7b",
                               "choices": [{"index": 0, "finish_reason": "stop",
                                            "message": {"role": "assistant", "content": text}}],
                               "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for word in text.split(" "):
            chunk = {"id": "x", "object": "chat.completion.chunk", "model": "stand-in-7b",
                     "choices": [{"index": 0, "delta": {"content": word + " "}, "finish_reason": None}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        end = {"id": "x", "object": "chat.completion.chunk", "model": "stand-in-7b",
               "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        self.wfile.write(f"data: {json.dumps(end)}\n\ndata: [DONE]\n\n".encode())


@pytest.fixture(scope="module")
def stand_in():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StandIn)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


_DRIVE = r"""
const { chromium } = require('playwright');
const [BASE, MODEL] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 860 } })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  const creds = { username: 'boxer', password: 'boxer-pass-123' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: creds });
  await page.request.post(BASE + '/api/model-endpoints', { multipart: { name: 'Stand-in', base_url: MODEL } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 60000 });
  await page.waitForTimeout(2500);
  const out = { errors };
  const rows = (id) => page.evaluate((id) => {
    const p = document.getElementById(id);
    if (!p || p.style.display !== 'block') return null;
    return [...p.querySelectorAll('.slash-ac-row')].map((r) => ({
      token: r.querySelector('.slash-ac-token').textContent, skill: r.classList.contains('slash-ac-skill') }));
  }, id);

  await page.click('#message');
  await page.keyboard.type('/');
  await page.waitForTimeout(800);
  out.slash = await rows('slash-autocomplete');
  await page.keyboard.type('qa-a-ch');
  await page.waitForTimeout(300);
  await page.keyboard.press('Enter');
  await page.waitForTimeout(300);
  out.slashEnter = await page.inputValue('#message');

  await page.fill('#message', '');
  await page.keyboard.type('@');
  await page.waitForTimeout(1500);
  out.at = await rows('agent-mention-popup');
  await page.keyboard.type('code revi');
  await page.waitForTimeout(400);
  out.atFiltered = await rows('agent-mention-popup');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(500);
  out.afterPick = await page.evaluate(() => ({
    box: document.getElementById('message').value,
    summoned: JSON.parse(localStorage.getItem('pantheon-summoned-agent') || 'null'),
    agentMode: document.getElementById('mode-agent-btn').classList.contains('active'),
  }));
  await page.evaluate(() => { document.getElementById('summon-indicator-btn')?.click(); document.getElementById('mode-chat-btn')?.click(); });

  await page.fill('#message', '');
  await page.keyboard.type('write to me at someone@example');
  await page.waitForTimeout(500);
  out.emailOpens = !!(await rows('agent-mention-popup'));

  await page.fill('#message', '');
  await page.keyboard.type('Help me plan a parser');
  await page.keyboard.press('Enter');
  out.ghost = null;
  for (let i = 0; i < 60 && !out.ghost; i++) {
    await page.waitForTimeout(250);
    out.ghost = await page.evaluate(() => {
      const g = document.getElementById('next-step-ghost');
      return g && g.style.display === 'block' ? g.querySelector('.next-step-words').textContent : null;
    });
  }
  out.placeholderHidden = await page.evaluate(() => document.getElementById('message').classList.contains('next-step-on'));
  await page.focus('#message');
  await page.keyboard.press('Tab');
  await page.waitForTimeout(200);
  out.afterTab = await page.evaluate(() => ({ box: document.getElementById('message').value, focus: document.activeElement.id }));
  await page.keyboard.press('Tab');
  await page.waitForTimeout(200);
  out.secondTabFocus = await page.evaluate(() => document.activeElement.id);
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(PW_NODE is None, reason=PW_SKIP or "")
def test_the_three_helpers_in_the_real_box(app_url, stand_in, tmp_path):  # noqa: F811
    script = tmp_path / "drive.js"
    script.write_text(_DRIVE, encoding="utf-8")
    proc = subprocess.run([PW_NODE, str(script), app_url, stand_in],
                          capture_output=True, text=True, timeout=240)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["errors"] == []

    # `/`: skills first, then the commands.
    assert out["slash"] and out["slash"][0]["skill"], out["slash"]
    skills = [r for r in out["slash"] if r["skill"]]
    assert {"/qa-a-change", "/test-a-web-page", "/build-a-web-page"} <= {r["token"] for r in skills}
    first_command = next(i for i, r in enumerate(out["slash"]) if not r["skill"])
    assert all(r["skill"] for r in out["slash"][:first_command])
    assert all(not r["skill"] for r in out["slash"][first_command:])
    # Enter on a half-typed name takes the highlighted skill; nothing is sent.
    assert out["slashEnter"] == "/qa-a-change "

    # `@`: the hall, narrowed as the person types; Enter summons.
    assert out["at"] and len(out["at"]) > 5
    assert out["atFiltered"][0]["token"] == "Code Reviewer"
    assert out["afterPick"]["summoned"]["id"] == "code-reviewer"
    assert out["afterPick"]["agentMode"] is True
    assert out["afterPick"]["box"] == ""
    assert out["emailOpens"] is False

    # The next step: drawn after the reply, taken whole by Tab, and Tab is
    # the focus key again once nothing is on offer (`B948`).
    assert out["ghost"] == SUGGESTION
    assert out["placeholderHidden"] is True
    assert out["afterTab"] == {"box": SUGGESTION, "focus": "message"}
    assert out["secondTabFocus"] != "message"
    assert any(c["next_step"] for c in _StandIn.calls)
