# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1703` / `D-2026-10-30-01` — Auto-approve is accepted, in the browser.

The row's `Verify:`, driven in headless Chromium against the real app (its
middleware, its routes, its database, its `approvalMode.js`, `ui.js` dialog
and `agentsWindow.js`): Auto and a hire that lifts the gate are refused
without the acceptance, granted with it, and the record names the person.

  * **the chat.** A `POST` of Auto with no acceptance is refused in a
    sentence. The chip opens one dialog holding the server's warning, whose
    buttons read *Proceed to auto-approve* and *Keep asking me*; *Keep asking
    me* sends nothing, *Proceed* turns it on and the server says who accepted;
    pressing the chip again turns it off with no dialog, and ends the record.
  * **the hire.** The hire form shows the warning above an unticked *Proceed
    to auto-approve*. Summoned unticked, the hire lifts nothing and its page
    offers the same control; pressed there, its record names the person.
    Summoned ticked, it is accepted at hire. A hire sent with the id of other
    words is refused, and nothing is made.

`tests/test_auto_approve_is_a_risk_the_person_accepts.py` drives the rest.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.approval_mode import (
    AUTO_NOT_ACCEPTED_SENTENCE, AUTO_WARNING, AUTO_WARNING_CHANGED_SENTENCE, KEEP_ASKING_LABEL,
    PROCEED_LABEL,
)
from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
WHO = "consent"

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const WHO = process.argv[3];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
  await context.addInitScript(() => {
    try {
      localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
      localStorage.setItem('pantheon-hint-drag-to-snap-seen', '1');
    } catch (_) {}
  });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  const out = { errors: [] };
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  const creds = { username: WHO, password: 'consent-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const sid = (await (await page.request.post(BASE + '/api/session', { form: {
    name: 'Consent chat', endpoint_url: 'http://127.0.0.1:9/v1/chat/completions', model: 'm',
    skip_validation: '1' } })).json()).id;
  const modeUrl = BASE + '/api/session/' + encodeURIComponent(sid) + '/approval-mode';
  const mode = async () => (await page.request.get(modeUrl)).json();

  // ── the route: refused without the acceptance ──
  const bare = await page.request.post(modeUrl, { data: { mode: 'auto' } });
  out.bare = { status: bare.status(), detail: (await bare.json()).detail, after: (await mode()).auto };

  // ── the chat's chip ──
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 120000 });
  await page.waitForFunction((sid) => !!document.querySelector(
    `#session-list .list-item[data-session-id="${sid}"]`), sid);
  await page.evaluate((sid) => document.querySelector(
    `#session-list .list-item[data-session-id="${sid}"]`).click(), sid);
  await page.waitForFunction(() => {
    const c = document.getElementById('approval-mode-btn');
    return !!c && c.style.display !== 'none' && c.getBoundingClientRect().width > 0;
  });
  const dialog = () => page.evaluate(() => {
    const o = document.getElementById('styled-confirm-overlay');
    const shown = !!o && !o.classList.contains('hidden') && getComputedStyle(o).display !== 'none';
    return shown ? { message: document.getElementById('styled-confirm-msg').textContent,
                     ok: document.getElementById('styled-confirm-ok').textContent,
                     cancel: document.getElementById('styled-confirm-cancel').textContent,
                     title: document.getElementById('styled-confirm-title').textContent } : null;
  });
  const posts = [];
  page.on('request', (r) => { if (r.method() === 'POST' && r.url().includes('/approval-mode')) posts.push(r.postDataJSON()); });

  await page.click('#approval-mode-btn');
  await page.waitForSelector('#styled-confirm-ok', { state: 'visible' });
  out.dialog = await dialog();
  await page.click('#styled-confirm-cancel');
  await page.waitForTimeout(300);
  out.kept = { posts: posts.length, auto: (await mode()).auto };

  await page.click('#approval-mode-btn');
  await page.waitForSelector('#styled-confirm-ok', { state: 'visible' });
  await page.click('#styled-confirm-ok');
  await page.waitForFunction(() => !document.getElementById('chat-auto-approve-badge').hidden);
  const on = await mode();
  out.on = { posts: posts.slice(), auto: on.auto, accepted: on.accepted,
             chipPressed: await page.getAttribute('#approval-mode-btn', 'aria-pressed') };

  await page.click('#approval-mode-btn');
  await page.waitForFunction(() => document.getElementById('chat-auto-approve-badge').hidden);
  const off = await mode();
  out.off = { dialog: await dialog(), lastPost: posts[posts.length - 1], auto: off.auto, accepted: off.accepted };

  // ── the hire ──
  const wrong = await page.request.post(BASE + '/api/agents/inbox-triage/hire',
    { data: { accept_warning: '0000000000000000' } });
  out.wrong = { status: wrong.status(), detail: (await wrong.json()).detail,
                hires: (await (await page.request.get(BASE + '/api/agents')).json()).hires.length };

  await page.evaluate(async () => {
    const ag = await import('/static/js/agents/agentsWindow.js');
    await ag.openAgents({ agent: 'notes-gardener' });
  });
  await page.waitForSelector('.agents-form .agents-auto-accept-tick', { state: 'attached' });
  out.form = await page.evaluate(() => {
    const form = document.querySelector('.agents-form');
    const tick = form.querySelector('.agents-auto-accept-tick');
    return { warning: form.querySelector('.agents-after-outside').textContent,
             label: form.querySelector('.agents-auto-accept').textContent.trim(),
             checked: tick.checked, visible: tick.getBoundingClientRect().width > 0 };
  });
  // Summoned unticked: made, and lifting nothing.
  await page.click('.agents-form button[type="submit"]');
  await page.waitForSelector('.agents-auto-approve-state');
  out.unticked = await page.evaluate(() => ({
    state: document.querySelector('.agents-auto-approve-state').textContent,
    button: [...document.querySelectorAll('.agents-auto-approve button')].map((b) => b.textContent) }));
  // Accepted on its page.
  await page.click('.agents-auto-approve button');
  await page.waitForFunction(() => /^On/.test((document.querySelector('.agents-auto-approve-state') || {}).textContent || ''));
  const hires = (await (await page.request.get(BASE + '/api/agents')).json()).hires;
  const gardener = hires.find((h) => h.agent_id === 'notes-gardener');
  out.onPage = { state: await page.textContent('.agents-auto-approve-state'), accepted: gardener.auto_approve.accepted };

  // Summoned ticked: accepted at hire.
  await page.evaluate(async () => {
    const ag = await import('/static/js/agents/agentsWindow.js');
    await ag.openAgents({ agent: 'inbox-triage' });
  });
  await page.waitForSelector('.agents-form .agents-auto-accept-tick', { state: 'attached' });
  await page.check('.agents-form .agents-auto-accept-tick');
  await page.click('.agents-form button[type="submit"]');
  await page.waitForFunction(() => /^On/.test((document.querySelector('.agents-auto-approve-state') || {}).textContent || ''));
  const triage = (await (await page.request.get(BASE + '/api/agents')).json()).hires
    .find((h) => h.agent_id === 'inbox-triage');
  out.ticked = { accepted: triage.auto_approve.accepted, effects: triage.auto_approve.effects };
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def driven(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("b1703") / "consent.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, WHO], capture_output=True, text=True,
                          timeout=600, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_nothing_threw(driven):
    assert driven["errors"] == []


def test_auto_is_refused_through_the_route_without_the_acceptance(driven):
    assert driven["bare"] == {"status": 400, "detail": AUTO_NOT_ACCEPTED_SENTENCE, "after": False}


def test_the_chip_shows_the_servers_warning_with_the_rulings_control(driven):
    assert driven["dialog"] == {"message": AUTO_WARNING, "ok": PROCEED_LABEL,
                                "cancel": KEEP_ASKING_LABEL, "title": "Auto-approve"}


def test_keep_asking_me_sends_nothing(driven):
    assert driven["kept"] == {"posts": 0, "auto": False}


def test_proceed_turns_it_on_and_the_record_names_the_person(driven):
    on = driven["on"]
    assert on["auto"] is True and on["chipPressed"] == "true"
    assert on["accepted"]["by"] == WHO and on["accepted"]["at"]
    (sent,) = on["posts"]
    assert sent["mode"] == "auto" and sent["accept_warning"] == on["accepted"]["warning_id"]


def test_turning_it_off_asks_nothing_and_ends_the_acceptance(driven):
    off = driven["off"]
    assert off["dialog"] is None
    assert off["lastPost"] == {"mode": "manual"}
    assert off["auto"] is False and off["accepted"] is None


def test_a_hire_sent_with_another_warnings_id_is_refused_and_nothing_is_made(driven):
    assert driven["wrong"] == {"status": 409, "detail": AUTO_WARNING_CHANGED_SENTENCE, "hires": 0}


def test_the_hire_form_shows_the_warning_above_an_unticked_proceed(driven):
    form = driven["form"]
    assert form["warning"].startswith("Notes Gardener will do these without asking you")
    assert "can steer what it does next" in form["warning"]
    assert form["label"] == PROCEED_LABEL and form["checked"] is False and form["visible"] is True


def test_summoned_unticked_it_lifts_nothing_and_its_page_offers_the_control(driven):
    assert driven["unticked"] == {
        "state": "Off — its runs ask you after it reads something from outside.",
        "button": [PROCEED_LABEL]}


def test_accepted_on_its_page_the_record_names_the_person(driven):
    assert driven["onPage"]["state"].startswith(f"On — accepted by {WHO}")
    assert driven["onPage"]["accepted"]["by"] == WHO


def test_summoned_ticked_it_is_accepted_at_hire(driven):
    assert driven["ticked"]["accepted"]["by"] == WHO
    assert driven["ticked"]["effects"] == ["read_private", "write_private"]
