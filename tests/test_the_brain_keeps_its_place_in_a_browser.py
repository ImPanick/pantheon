# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-02` in a real browser — the owner's walk and the Brain's leak, measured.

The app booted out of process (`tests/test_the_command_palette_in_a_browser.py`'s
`app_url`), driven by headless Chromium through Playwright:

  * **the owner's example** — Brain → RAG → Skills, then close Skills: on
    `32df791` the Brain switched itself to a Skills launcher card (233 px) and
    the window covered it; closing Skills landed on that card, not on RAG, and
    the Brain reopened on it. Now the Brain stays on RAG under the window and is
    on RAG when it closes. (`← Brain` in the Skills header is `P23-01`'s half
    of C-NAV; on a tree without it the walk still lands on RAG.)
  * **one height** — 690 → 133 → 384 → 702 px by tab on `32df791`; RAG's drop
    zone sat under the chat composer (`elementFromPoint` answered `#message`).
  * **real tabs** — `role=tab`, ArrowRight moves.
  * **`PERF-M-3`** — six Brain opens with 30 memories add no `document`
    listener (CDP `DOMDebugger.getEventListeners`, the audit's own method; it
    measured +402 for 67 memories on `32df791`).
  * **`PERF-M-8`** — the Brain's seven switches are not read one key at a time.

Skipped, with the reason, where node, the `playwright` package or its Chromium
is not installed.
"""

import json
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

_BRAIN_KEYS = ["memory_enabled", "skills_enabled", "auto_memory", "auto_skills",
               "auto_approve_skills", "skill_min_confidence", "skill_max_injected"]

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const KEYS = JSON.parse(process.argv[3]);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
  await context.addInitScript(() => {
    try {
      localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
      localStorage.setItem('pantheon-hint-drag-to-snap-seen', '1');
    } catch (_) {}
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  const creds = { username: 'brainwalk', password: 'brain-walk-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  for (let i = 0; i < 30; i++) {
    await page.request.post(BASE + '/api/memory/add', { data: { text: 'Walk fact number ' + i, category: 'fact' } });
  }
  const prefGets = [];
  page.on('request', (r) => { if (r.method() === 'GET' && /\/api\/prefs(\/|$)/.test(r.url())) prefGets.push(r.url().replace(BASE, '')); });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);

  const cdp = await context.newCDPSession(page);
  const docListeners = async () => {
    const { result } = await cdp.send('Runtime.evaluate', { expression: 'document' });
    const { listeners } = await cdp.send('DOMDebugger.getEventListeners', { objectId: result.objectId });
    return listeners.filter((l) => l.type === 'click').length;
  };
  const tab = () => page.evaluate(() => { const t = document.querySelector('#memory-modal .memory-tab.active'); return t && t.dataset.memoryTab; });
  const shown = (sel) => page.evaluate((s) => { const e = document.querySelector(s); if (!e) return false;
    const cs = getComputedStyle(e); const r = e.getBoundingClientRect();
    return !e.classList.contains('hidden') && cs.display !== 'none' && r.width > 0 && r.height > 0; }, sel);
  const rect = (sel) => page.evaluate((s) => { const r = document.querySelector(s).getBoundingClientRect();
    return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; }, sel);

  // PERF-M-3: six opens.
  await page.evaluate(() => document.getElementById('tool-memory-btn').click());
  await page.waitForSelector('#memory-list .memory-item', { timeout: 20000 });
  await page.click('#close-memory-modal'); await page.waitForTimeout(400);
  const before = await docListeners();
  for (let i = 0; i < 6; i++) {
    await page.evaluate(() => document.getElementById('tool-memory-btn').click());
    await page.waitForTimeout(500);
    await page.click('#close-memory-modal'); await page.waitForTimeout(400);
  }
  out.listeners = { before, after: await docListeners() };
  out.prefGets = prefGets.slice();

  // One height; RAG reachable; real tabs.
  await page.evaluate(() => document.getElementById('tool-memory-btn').click());
  await page.waitForTimeout(600);
  out.heights = {};
  for (const t of ['browse', 'rag', 'add', 'settings']) {
    await page.click('#memory-tab-' + t); await page.waitForTimeout(250);
    out.heights[t] = await rect('#memory-modal .memory-modal-content');
  }
  await page.click('#memory-tab-rag'); await page.waitForTimeout(250);
  out.ragHit = await page.evaluate(() => { const z = document.getElementById('rag-upload-zone').getBoundingClientRect();
    const hit = document.elementFromPoint(z.x + z.width / 2, z.y + z.height / 2); return hit && hit.id; });
  out.roles = await page.evaluate(() => [...document.querySelectorAll('#memory-modal [role="tab"]')].map((t) => t.dataset.memoryTab));
  await page.focus('#memory-tab-rag'); await page.keyboard.press('ArrowRight'); await page.waitForTimeout(150);
  out.arrow = { tab: await tab(), focus: await page.evaluate(() => document.activeElement.id) };

  // The owner's walk.
  await page.click('#memory-tab-rag'); await page.waitForTimeout(200);
  await page.click('#memory-skills-door'); await page.waitForTimeout(900);
  out.door = { skills: await shown('#skills-modal'), brain: await shown('#memory-modal'), tab: await tab(),
               z: await page.evaluate(() => [getComputedStyle(document.getElementById('memory-modal')).zIndex,
                                             getComputedStyle(document.getElementById('skills-modal')).zIndex]) };
  await page.click('#close-skills-modal'); await page.waitForTimeout(700);
  out.closed = { skills: await shown('#skills-modal'), brain: await shown('#memory-modal'), tab: await tab(),
                 rag: await shown('#memory-panel-rag'),
                 onTop: await page.evaluate(() => { const r = document.querySelector('#memory-modal .modal-header').getBoundingClientRect();
                   const hit = document.elementFromPoint(r.x + 40, r.y + r.height / 2); return !!(hit && hit.closest('#memory-modal')); }) };
  await page.click('#close-memory-modal'); await page.waitForTimeout(500);
  await page.evaluate(() => document.getElementById('tool-memory-btn').click()); await page.waitForTimeout(600);
  out.reopen = await tab();

  await context.close();
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def walked(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("brain-walk") / "walk.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, json.dumps(_BRAIN_KEYS)], capture_output=True,
                          text=True, timeout=400, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_six_brain_opens_add_no_document_listener(walked):
    got = walked["listeners"]
    assert got["after"] == got["before"], f"+{got['after'] - got['before']} document click listeners"


def test_the_brains_switches_are_not_read_one_key_at_a_time(walked):
    one_key = [u for u in walked["prefGets"] if any(u.endswith("/api/prefs/" + k) for k in _BRAIN_KEYS)]
    assert one_key == [], one_key


def test_the_brain_keeps_one_height_and_rag_is_reachable(walked):
    heights = walked["heights"]
    assert len({tuple(r) for r in heights.values()}) == 1, heights
    assert heights["browse"][3] >= 600, heights
    assert walked["ragHit"] == "rag-upload-zone"


def test_the_brains_tabs_are_tabs(walked):
    assert walked["roles"] == ["browse", "rag", "add", "settings"]
    assert walked["arrow"] == {"tab": "add", "focus": "memory-tab-add"}


def test_brain_rag_skills_and_back_lands_on_rag(walked):
    door, closed = walked["door"], walked["closed"]
    assert door["skills"] is True and door["brain"] is True
    assert door["tab"] == "rag", "opening Skills moved the Brain off RAG"
    assert int(door["z"][1]) > int(door["z"][0]), "Skills did not open over the Brain"
    assert closed == {"skills": False, "brain": True, "tab": "rag", "rag": True, "onTop": True}
    assert walked["reopen"] == "rag"


def test_nothing_threw(walked):
    assert walked["errors"] == []
