# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1124` — a skill card shows its name however many pills share the card.

**Measured before the fix** (Chromium, the showcase world, this tree): a skill
in a duplicate group, written by a teacher and audited, carries four pills —
`uncatalogued`, `audit`, `duplicate #1`, `lower-priority` — and the cluster
they sit in was 358px wide and could neither shrink nor move
(`.skill-card-right { flex-shrink: 0 }`), while the name column was `min-width:
0`. So on a 342px card (the Skills window at 390px) and a 370px one (the
Workbench's Skills room at 440px) **every such card's name box was 0px wide**:
the card had no name. The window and the room alike — the card header's
layout, not the room.

**Now** the header wraps and the name keeps 10rem (or the whole card): the
cluster moves under the name. A one-pill card still fits on one line at 390px,
and a wide card is one row, as before.

Driven, not read (`Law 20`): the real app booted out of process on a data
directory whose skills are planted through `SkillsManager` before it starts
(the store the app reads), signed in, the Skills window opened through the
Brain's own tab; the real `skills.js` draws the cards and the real
`static/style.css` lays them out in headless Chromium. Measured: each card's
name box, and how much of the name's own text is drawn inside it.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, _free_port  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
USER, PASSWORD = "cards", "cards-pass-1"
FOUR = ("both-places-clear-the-office-print-queue", "both-places-clear-the-office-print-queue-again",
        "both-places-clear-the-office-print-queue-copy")


def _plant(data: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from services.memory.skills import SkillsManager

    sm = SkillsManager(str(data))
    for i, name in enumerate(FOUR):
        sm.add_skill(name=name, description="Clear a jammed office print queue and restart the spooler",
                     category="office", tags=["printer", "spooler"],
                     when_to_use="When the office printer queue is stuck",
                     procedure=["Stop the spooler", "Delete the queued jobs", "Start the spooler"],
                     owner=USER, status="draft", source="teacher-escalation" if i % 2 == 0 else "user",
                     teacher_model="big-teacher" if i % 2 == 0 else None, confidence=0.5 + i / 10)
        sm.set_audit(name, "pass", by_teacher=(i % 2 == 0), worker_model="worker",
                     teacher_model="big-teacher" if i % 2 == 0 else "", owner=USER)
    sm.add_skill(name="tidy", description="A short one", category="files", tags=["files"],
                 when_to_use="Short", procedure=["Do it"], owner=USER, status="published", source="user")


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    data = tmp_path_factory.mktemp("skill-cards")
    _plant(data)
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
const [BASE, USER, PASSWORD] = process.argv.slice(2);
const MEASURE = () => [...document.querySelectorAll('#skills-list .skill-card[data-skill-name]')].map((c) => {
  const nameEl = c.querySelector('.skill-card-name');
  const n = nameEl.getBoundingClientRect();
  const right = c.querySelector('.skill-card-right').getBoundingClientRect();
  const range = document.createRange(); range.selectNodeContents(nameEl);
  const drawn = [...range.getClientRects()].reduce((s, r) =>
    s + Math.max(0, Math.min(r.right, n.right) - Math.max(r.left, n.left)), 0);
  const text = [...range.getClientRects()].reduce((s, r) => s + r.width, 0);
  return { name: c.dataset.skillName, card: Math.round(c.getBoundingClientRect().width),
           pills: c.querySelectorAll('.skill-card-right .memory-cat-badge').length,
           nameBox: Math.round(n.width), drawn: Math.round(drawn), text: Math.round(text),
           clipped: nameEl.scrollHeight > nameEl.clientHeight + 1,
           pillsBesideName: right.top < n.bottom - 1,
           clusterInside: right.right <= c.getBoundingClientRect().right + 0.5
             && [...c.querySelectorAll('.skill-card-right > *')].every((p) =>
               p.getBoundingClientRect().right <= c.getBoundingClientRect().right + 0.5) };
});
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  await (await browser.newContext()).request.post(BASE + '/api/auth/setup',
    { data: { username: USER, password: PASSWORD } });
  for (const [w, h] of [[400, 860], [390, 844], [1400, 860]]) {
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
    await page.waitForTimeout(1200);
    // The Brain, by its own door, then its Skills tab — the Skills window.
    await page.evaluate(() => document.getElementById('tool-memory-btn').click());
    await page.waitForSelector("[data-memory-tab='skills']", { state: 'attached', timeout: 30000 });
    await page.evaluate(() => document.querySelector("[data-memory-tab='skills']").click());
    await page.waitForSelector('#skills-list .skill-card', { timeout: 30000 });
    await page.waitForTimeout(800);
    out[w] = await page.evaluate(MEASURE);
    await context.close();
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):
    d = tmp_path_factory.mktemp("skill-cards-js")
    script = d / "cards.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, USER, PASSWORD], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _cards(measured, width):
    return {c["name"]: c for c in measured[str(width)]}


@pytest.mark.parametrize("width", [400, 390])
def test_a_card_with_four_pills_shows_its_name_at_phone_width(measured, width):
    assert measured["errors"] == []
    cards = _cards(measured, width)
    four = [c for c in cards.values() if c["pills"] >= 4]
    assert four, f"the premise: some card carries four pills ({cards})"
    for c in four:
        assert c["nameBox"] >= 150, c
        assert c["drawn"] == c["text"] > 0, f"the name is not all drawn inside its box: {c}"
        assert not c["clipped"], c
        assert c["clusterInside"] is True, f"the pills run past the card: {c}"


def test_a_one_pill_card_keeps_one_line_at_phone_width(measured):
    tidy = _cards(measured, 390)["tidy"]
    assert tidy["pills"] == 1 and tidy["pillsBesideName"] is True, tidy


def test_a_wide_card_is_one_row_as_before(measured):
    for c in _cards(measured, 1400).values():
        assert c["pillsBesideName"] is True, c
        assert c["drawn"] == c["text"] > 0, c
