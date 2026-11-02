# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plan mode gathers the person's vision before it plans.

The owner, 2026-10-31: *"with the plan mode — we also need to ensure the LLM has
enough information to actually draft a plan... if it doesn't — it needs to query
the user for more information to build the plan off of... gather the users
vision — form the plan that makes it reality."*

Three halves, each pinned here:

  * **the check** — `PLAN_MODE_DIRECTIVE` names what a plan rests on (outcome,
    done, limits, taste) and orders questions instead of a plan built on a
    guess, read off the real assembled system text;
  * **the brief** — `ask_user` with `questions` puts several questions on one
    card, each with optional suggestions and always a line for the person's own
    words, and their answers come back as one message that repeats each
    question beside its answer;
  * **no Execute on a question** — a plan-mode turn that asked instead of
    planning has no checklist, and the chat no longer offers to execute its
    text as if it were the plan; a plan's `Goal:` line stays with its steps.

The card itself is driven in Chromium against the real app, in both tones and at
phone width.
"""

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from test_an_agent_that_asks_is_the_defect import _patch_common, _run, _system_text, HANDBACK

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _ask(args):
    from src.agent_tools.interaction_tools import AskUserTool
    return asyncio.run(AskUserTool().execute(json.dumps(args), None))


# ── the check ───────────────────────────────────────────────────────────────

def test_plan_mode_is_told_what_a_plan_rests_on_and_to_ask_for_what_is_missing(monkeypatch):
    _patch_common(monkeypatch)
    requests, _ = _run(monkeypatch, [HANDBACK], plan_mode=True)
    system = _system_text(requests[-1])
    assert "PLAN MODE" in system
    assert "CHECK YOU HAVE ENOUGH TO PLAN FROM" in system
    for part in ("THE OUTCOME", "DONE", "THE LIMITS", "THEIR TASTE"):
        assert part in system, part
    # The brief is how it asks, and asking is not a reflex.
    assert "`ask_user` with `questions`" in system
    assert "do not ask for the sake of asking" in system
    # A plan carries the vision it was built from.
    assert "`Goal: ...`" in system
    # The ruling this extends still stands: look before asking.
    assert "Look first, then ask, then plan." in system


def test_a_turn_without_plan_mode_is_not_told_to_gather_a_vision(monkeypatch):
    _patch_common(monkeypatch)
    requests, _ = _run(monkeypatch, [HANDBACK])
    assert "CHECK YOU HAVE ENOUGH TO PLAN FROM" not in _system_text(requests[-1])


def test_the_native_schema_offers_questions_and_no_longer_requires_options():
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    schema = next(s for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "ask_user")
    params = schema["function"]["parameters"]
    assert params["required"] == ["question"]
    item = params["properties"]["questions"]["items"]
    assert item["required"] == ["question"]
    assert {"question", "options", "multi", "placeholder"} <= set(item["properties"])


# ── the brief ───────────────────────────────────────────────────────────────

def test_a_brief_is_one_card_of_several_questions():
    desc, result = _ask({
        "question": "A few things before I plan the dashboard.",
        "questions": [
            {"question": "Who reads it?", "options": [{"label": "Just me"}, {"label": "My team"}]},
            {"question": "What should it show first?"},
            "By when do you need it?",
        ],
    })
    assert result["exit_code"] == 0
    aq = result["ask_user"]
    assert aq["kind"] == "brief"
    assert aq["question"] == "A few things before I plan the dashboard."
    assert [q["question"] for q in aq["questions"]] == [
        "Who reads it?", "What should it show first?", "By when do you need it?"]
    assert [q["id"] for q in aq["questions"]] == ["q1", "q2", "q3"]
    assert aq["questions"][0]["options"] == [
        {"label": "Just me", "description": ""}, {"label": "My team", "description": ""}]
    assert aq["questions"][1]["options"] == []
    # The model is told what it asked, so it does not ask it again.
    assert "Who reads it?" in result["output"] and "Awaiting their answers." in result["output"]
    assert desc == "ask_user: 3 question(s)"


def test_a_brief_holds_five_and_says_so_when_it_drops_more():
    _, result = _ask({"question": "", "questions": [f"Question {i}?" for i in range(1, 8)]})
    aq = result["ask_user"]
    assert len(aq["questions"]) == 5
    assert aq["question"] == "A few things before I plan this."
    assert "2 more question(s) were not shown" in result["output"]


def test_a_brief_with_nothing_to_ask_is_refused_in_the_models_own_channel():
    _, result = _ask({"question": "Before I plan", "questions": [{"question": "  "}, 7]})
    assert result["exit_code"] == 1 and "ask_user" not in result
    assert "at least one entry" in result["error"]


def test_the_single_question_card_is_unchanged():
    _, result = _ask({"question": "Which one?", "options": ["A", "B"], "questions": []})
    assert result["ask_user"] == {"question": "Which one?", "multi": False,
                                  "options": [{"label": "A", "description": ""},
                                              {"label": "B", "description": ""}]}
    _, refused = _ask({"question": "Which one?", "options": ["A"]})
    assert refused["exit_code"] == 1


# ── no Execute on a question; the Goal line stays with the plan ─────────────

_PLAN_JS = r"""
const pw = await import(%s);
console.log(JSON.stringify({
  goal: pw.extractPlanText("Sure.\n\nGoal: a dashboard my team reads on Mondays\n\n- [ ] Sketch it\n- [ ] Build it"),
  boldGoal: pw.extractPlanText("**Goal:** ship it\n- [ ] one"),
  noGoal: pw.extractPlanText("Here you go.\n- [ ] one"),
  question: pw.hasPlanSteps("Before I plan this: who reads it?"),
  plan: pw.hasPlanSteps("Goal: x\n- [ ] one"),
  steps: pw.parsePlan("Goal: x\n- [ ] one\n- [x] two").map((s) => s.text),
}));
"""


@pytest.mark.skipif(NODE is None, reason="node binary not on PATH")
def test_a_question_is_not_a_plan_and_a_goal_stays_with_its_steps(tmp_path):
    script = tmp_path / "plan.mjs"
    script.write_text(_PLAN_JS % json.dumps(str(ROOT / "static" / "js" / "planWindow.js")))
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["goal"] == "Goal: a dashboard my team reads on Mondays\n\n- [ ] Sketch it\n- [ ] Build it"
    assert out["boldGoal"].startswith("**Goal:** ship it")
    assert out["noGoal"] == "- [ ] one"
    assert out["question"] is False and out["plan"] is True
    assert out["steps"] == ["one", "two"]


def test_the_chat_offers_execute_only_on_a_turn_that_planned():
    src = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    at = src.index("_attachPlanActions(footerTarget, accumulated)")
    gate = src[src.rindex("if (_endToggles.plan_mode", 0, at):at]
    assert "!holder.dataset.askedUser" in gate
    assert "planWindow.hasPlanSteps(accumulated)" in gate
    assert "holder.dataset.askedUser = '1'" in src


# ── the card, in a browser ──────────────────────────────────────────────────

USER, PASSWORD = "brief", "brief-pass-1"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    data = tmp_path_factory.mktemp("plan-brief")
    port = _free_port()
    env = dict(os.environ, PANTHEON_DATA_DIR=str(data), APP_PORT=str(port), APP_BIND="127.0.0.1",
               PANTHEON_DISABLE_MCP="1", AUTH_ENABLED="true", LOCALHOST_BYPASS="false")
    env.pop("DATABASE_URL", None)
    log = open(data / "app.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 120
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
                pytest.fail("the app did not answer /login within 120 s")
            time.sleep(0.5)
        yield url
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


_SCRIPT = r"""
const { chromium } = require('playwright');
const [BASE, USER, PASSWORD, SHOTS] = process.argv.slice(2);
const BRIEF = {
  kind: 'brief', question: 'A few things before I plan the dashboard.', options: [], multi: false,
  questions: [
    { id: 'q1', question: 'Who will read it?', multi: false,
      options: [{ label: 'Just me', description: '' }, { label: 'My team', description: 'Shared link' }] },
    { id: 'q2', question: 'Which numbers matter most?', multi: true,
      options: [{ label: 'Revenue' }, { label: 'Signups' }, { label: 'Churn' }] },
    { id: 'q3', question: 'Anything it must not touch?', options: [], placeholder: 'e.g. the billing tables' },
  ],
};
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [], tones: {} };
  await (await browser.newContext()).request.post(BASE + '/api/auth/setup',
    { data: { username: USER, password: PASSWORD } });
  const open = async (w, h, theme) => {
    const phone = w < 500;
    const context = await browser.newContext({ viewport: { width: w, height: h }, isMobile: phone, hasTouch: phone });
    await context.addInitScript(() => {
      try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    });
    await context.request.post(BASE + '/api/auth/login', { data: { username: USER, password: PASSWORD, remember: true } });
    const page = await context.newPage();
    page.on('pageerror', (e) => out.errors.push(String(e)));
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    if (theme) {
      await page.evaluate(async (t) => { const m = await import('/static/js/theme.js'); m.applyColors(m.THEMES[t]); }, theme);
    }
    await page.waitForTimeout(600);
    await page.evaluate(async (brief) => {
      const r = await import('/static/js/chatRenderer.js');
      window.__sent = [];
      r.renderAskUserCard(brief, { onSubmit: (a) => { window.__sent.push(a.text); return true; }, focus: false });
    }, BRIEF);
    await page.waitForSelector('.ask-brief');
    await page.waitForTimeout(700);
    return { page, context };
  };

  for (const tone of ['dark', 'light']) {
    const { page, context } = await open(1280, 900, tone === 'light' ? 'light' : 'dark');
    const card = await page.$('.ask-brief');
    out.tones[tone] = await page.evaluate(() => {
      const c = document.querySelector('.ask-brief');
      const cs = (sel) => getComputedStyle(c.querySelector(sel));
      return {
        tone: document.documentElement.dataset.ckTone,
        items: c.querySelectorAll('.ask-brief-item').length,
        pills: c.querySelectorAll('.ask-brief-option').length,
        lead: c.querySelector('.ask-user-question').textContent,
        leadFont: cs('.ask-user-question').fontFamily,
        radius: getComputedStyle(c).borderTopLeftRadius,
        sendDisabled: c.querySelector('.ask-brief-send').disabled,
        count: c.querySelector('.ask-brief-count').textContent,
        leadSize: cs('.ask-user-question').fontSize,
        // The two buttons stay side by side; the count may sit above them in a narrow column.
        actionsOneRow: (() => { const [a, b] = c.querySelectorAll('.ask-brief-actions > button');
          return Math.abs(a.getBoundingClientRect().top - b.getBoundingClientRect().top) < 1; })(),
      };
    });
    await card.screenshot({ path: `${SHOTS}/brief-${tone}.png` });
    await page.screenshot({ path: `${SHOTS}/page-${tone}.png` });
    await context.close();
  }

  // answering: one pill, two pills on the multi question, words on the open one
  const { page, context } = await open(1280, 900);
  await page.click('.ask-brief-item:nth-child(1) .ask-brief-option:nth-child(2)');
  await page.click('.ask-brief-item:nth-child(1) .ask-brief-option:nth-child(1)');
  await page.click('.ask-brief-item:nth-child(2) .ask-brief-option:nth-child(1)');
  await page.click('.ask-brief-item:nth-child(2) .ask-brief-option:nth-child(3)');
  out.answered = await page.evaluate(() => ({
    pressed: [...document.querySelectorAll('.ask-brief-option[aria-pressed="true"]')].map((b) => b.textContent),
    lit: [...document.querySelectorAll('.ask-brief-item.answered')].length,
    count: document.querySelector('.ask-brief-count').textContent,
  }));
  await page.fill('.ask-brief-item:nth-child(3) .ask-brief-own', 'the <b>billing</b> tables');
  await page.press('.ask-brief-item:nth-child(3) .ask-brief-own', 'Enter');
  out.sent = await page.evaluate(() => ({ sent: window.__sent, gone: !document.querySelector('.ask-brief') }));
  await context.close();

  // a phone: the card and its foot fit, nothing scrolls sideways
  const phone = await open(390, 844);
  out.phone = await phone.page.evaluate(() => {
    const c = document.querySelector('.ask-brief');
    const r = c.getBoundingClientRect();
    return { pageWidth: document.documentElement.scrollWidth, viewport: window.innerWidth,
             inside: r.left >= 0 && r.right <= window.innerWidth + 0.5,
             footFits: c.querySelector('.ask-brief-foot').scrollWidth <= c.querySelector('.ask-brief-foot').clientWidth + 1,
             actionsOneRow: (() => { const [a, b] = c.querySelectorAll('.ask-brief-actions > button');
               return Math.abs(a.getBoundingClientRect().top - b.getBoundingClientRect().top) < 1; })() };
  });
  await (await phone.page.$('.ask-brief')).screenshot({ path: `${SHOTS}/brief-phone.png` });
  await phone.page.click('.ask-brief-skip');
  out.skipped = await phone.page.evaluate(() => window.__sent);
  await phone.context.close();

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


def _playwright_missing() -> str:
    if NODE is None:
        return "node binary not on PATH"
    probe = subprocess.run([NODE, "-e", "require('playwright')"], capture_output=True, cwd=str(ROOT))
    return "" if probe.returncode == 0 else "playwright is not installed"


_SKIP = _playwright_missing()
browser = pytest.mark.skipif(bool(_SKIP), reason=_SKIP)


@pytest.fixture(scope="module")
def driven(app_url, tmp_path_factory):
    work = tmp_path_factory.mktemp("brief-browser")
    shots = Path(os.environ.get("PANTHEON_SHOTS_DIR") or work)
    script = work / "brief.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, USER, PASSWORD, str(shots)],
                          capture_output=True, text=True, timeout=600, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@browser
def test_nothing_threw(driven):
    assert driven["errors"] == []


@browser
def test_the_brief_is_drawn_as_the_cockpit_draws_a_card_in_both_tones(driven):
    for tone, card in driven["tones"].items():
        assert card["tone"] == tone, card
        assert card["items"] == 3 and card["pills"] == 5
        assert card["lead"] == "A few things before I plan the dashboard."
        assert "Instrument Serif" in card["leadFont"]
        assert card["radius"] == "20px"
        assert card["leadSize"] == "22px" and card["actionsOneRow"] is True
        assert card["sendDisabled"] is True and card["count"] == "0 of 3 answered"


@browser
def test_answers_come_back_as_one_message_question_beside_answer(driven):
    answered = driven["answered"]
    # A single-choice question keeps the last pick; the multi one keeps both.
    assert answered["pressed"] == ["Just me", "Revenue", "Churn"]
    assert answered["lit"] == 2 and answered["count"] == "2 of 3 answered"
    sent = driven["sent"]
    assert sent["gone"] is True
    assert sent["sent"] == [
        "Here is what I have in mind:\n"
        "1. Who will read it?\n   → Just me\n"
        "2. Which numbers matter most?\n   → Revenue; Churn\n"
        "3. Anything it must not touch?\n   → the <b>billing</b> tables"
    ]


@browser
def test_on_a_phone_the_card_fits_and_plan_with_what_you_have_is_there(driven):
    phone = driven["phone"]
    assert phone["pageWidth"] <= phone["viewport"]
    assert phone["inside"] and phone["footFits"] and phone["actionsOneRow"]
    assert driven["skipped"] == [
        "Plan with what you have. Use your judgement on anything I left open, and say what you assumed."]
