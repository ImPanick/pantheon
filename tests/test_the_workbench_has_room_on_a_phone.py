# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1051` — at phone width the Workbench's canvas has room, in a real browser.

Measured on the merged tree (`a97d969`, `verify-a`) at 390×844 and 768×860: the
Workbench opened as a 183px bottom sheet, `.wb-viewport` was **0px** tall, every
step was off-screen and a step's form mounted in a 0px panel. The cause is the
cascade, which only a browser computes: the phone rule `.modal-content { height:
auto !important }` beat `.workbench-modal-content`'s height, and a canvas has no
content height of its own.

So this is driven in headless Chromium (the `playwright` node package, as
`tests/test_the_command_palette_in_a_browser.py` drives it) against:

  * the real `static/style.css`, whole;
  * the real `#workbench-modal` markup, cut out of `static/index.html`;
  * the real `static/js/workbench/canvas.js` and everything it imports, served
    from `static/` through `page.route`.

Two things are stand-ins, the two the canvas takes as dependencies: the server
(three tasks, the shapes `GET /api/tasks` and the prefs door return) and the
step form (`mountPanel`, the `P22` panel contract — a Name box and a Save
button that hands the edited row to `onSaved`). The `Verify:` is the row's own:
at 390px someone opens the Workbench, sees their steps, opens one and saves it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"


def _window_markup() -> str:
    """`#workbench-modal` and everything in it, exactly as `index.html` has it."""
    html = INDEX.read_text(encoding="utf-8")
    start = html.index('<div id="workbench-modal"')
    depth, i = 0, start
    while True:
        o = html.find("<div", i)
        c = html.find("</div>", i)
        if o != -1 and o < c:
            depth, i = depth + 1, o + 4
            continue
        depth, i = depth - 1, c + 6
        if depth == 0:
            return html[start:i]


_HARNESS = r"""
import { mountCanvas } from '/static/js/workbench/canvas.js';

const tasks = [
  { id: 'a', name: 'Nightly backup', task_type: 'action', status: 'active', then_task_id: 'b', else_task_id: 'c' },
  { id: 'b', name: 'Post summary', task_type: 'llm', status: 'active', then_task_id: null, else_task_id: null },
  { id: 'c', name: 'Message me', task_type: 'llm', status: 'active', then_task_id: null, else_task_id: null },
];
window.__calls = [];
const reply = (body) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(body)) });
async function net(url, init = {}) {
  window.__calls.push((init.method || 'GET') + ' ' + url);
  if (String(url).startsWith('/api/tasks?')) {
    const edges = [];
    for (const t of tasks) {
      if (t.then_task_id) edges.push({ from: t.id, to: t.then_task_id, when: 'success', dangling: false });
      if (t.else_task_id) edges.push({ from: t.id, to: t.else_task_id, when: 'error', dangling: false });
    }
    return reply({ tasks, graph: { nodes: tasks.map((t) => ({ id: t.id, name: t.name })), edges } });
  }
  return reply({ key: 'workbench_positions', value: null });
}
function mountPanel(host, { task, onSaved }) {
  const label = document.createElement('label');
  label.textContent = 'Name ';
  const input = document.createElement('input');
  input.id = 'harness-name';
  input.value = task ? task.name : '';
  label.appendChild(input);
  const save = document.createElement('button');
  save.id = 'harness-save';
  save.type = 'button';
  save.textContent = 'Save';
  save.addEventListener('click', () => {
    const row = tasks.find((t) => t.id === task.id);
    row.name = input.value;
    onSaved({ ...row });
  });
  host.replaceChildren(label, save);
  return { destroy() { host.replaceChildren(); } };
}
document.getElementById('workbench-modal').classList.remove('hidden');
const c = mountCanvas(document.getElementById('workbench-room'), {
  fetch: net, mountPanel, describeTrigger: () => 'Daily at 02:00',
});
await c.ready;
window.__ready = true;
"""

_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const [ROOT, MARKUP, HARNESS] = process.argv.slice(2).map((p, i) => i === 0 ? p : fs.readFileSync(p, 'utf8'));
const TYPES = { '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.woff2': 'font/woff2' };

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = {};
  for (const [w, h] of [[390, 844], [768, 860], [1400, 860]]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.route('http://wb.test/**', (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === '/') {
        return route.fulfill({ contentType: 'text/html', body:
          '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">'
          + '<link rel="stylesheet" href="/static/style.css"></head><body>' + MARKUP
          + '<script type="module" src="/harness.js"></script></body></html>' });
      }
      if (url.pathname === '/harness.js') return route.fulfill({ contentType: 'text/javascript', body: HARNESS });
      const file = path.join(ROOT, decodeURIComponent(url.pathname));
      if (url.pathname.startsWith('/static/') && fs.existsSync(file)) {
        return route.fulfill({ path: file, contentType: TYPES[path.extname(file)] || 'application/octet-stream' });
      }
      return route.fulfill({ status: 404, body: '' });
    });
    await page.goto('http://wb.test/');
    await page.waitForFunction(() => window.__ready === true, null, { timeout: 15000 });
    await page.waitForTimeout(250);
    const box = (sel) => page.evaluate((sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
    }, sel);
    const rec = { window: await box('#workbench-modal .modal-content'), viewport: await box('.wb-viewport') };
    // Every step, and whether its middle is inside the canvas and is the step
    // there — the thing a person sees, not a box that happens to overlap.
    rec.steps = await page.evaluate(() => {
      const v = document.querySelector('.wb-viewport').getBoundingClientRect();
      return [...document.querySelectorAll('.wb-node')].map((n) => {
        const r = n.getBoundingClientRect();
        const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        const hit = document.elementFromPoint(cx, cy);
        return { title: n.querySelector('.wb-node-title').textContent,
                 inside: cx >= v.left && cx <= v.right && cy >= v.top && cy <= v.bottom,
                 seen: !!hit && n.contains(hit) };
      });
    });
    // Open one by clicking where a person would, then edit and save it. On the
    // old tree the step is off the canvas and something else takes the click,
    // which is recorded rather than waited out.
    rec.clicked = await page.click('.wb-node[data-task-id="b"] .wb-node-title', { timeout: 3000 })
      .then(() => true, () => false);
    await page.waitForSelector('#harness-name', { timeout: 3000 }).catch(() => null);
    rec.panel = await box('.wb-panel');
    rec.nameBox = await page.evaluate(() => {
      const i = document.getElementById('harness-name');
      if (!i) return null;
      const r = i.getBoundingClientRect();
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return { h: Math.round(r.height), seen: hit === i };
    });
    if (rec.nameBox && rec.nameBox.seen) {
      await page.fill('#harness-name', 'Post the summary');
      await page.click('#harness-save');
      await page.waitForFunction(() => document.querySelector('.wb-say-text').textContent.startsWith('Saved'),
        null, { timeout: 3000 }).catch(() => null);
    }
    rec.after = await page.evaluate(() => ({
      said: document.querySelector('.wb-say-text').textContent,
      panelHidden: document.querySelector('.wb-panel').hidden,
      title: document.querySelector('.wb-node[data-task-id="b"] .wb-node-title').textContent,
    }));
    rec.scroll = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
    rec.errors = errors;
    out[w] = rec;
    await page.close();
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    d = tmp_path_factory.mktemp("wb-phone")
    script, markup, harness = d / "phone.cjs", d / "markup.html", d / "harness.js"
    script.write_text(_SCRIPT, encoding="utf-8")
    markup.write_text(_window_markup(), encoding="utf-8")
    harness.write_text(_HARNESS, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), str(ROOT), str(markup), str(harness)],
                          capture_output=True, text=True, timeout=180, cwd=str(d))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return {int(k): v for k, v in json.loads(proc.stdout.strip().splitlines()[-1]).items()}


@pytest.mark.parametrize("width", [390, 768])
def test_at_phone_width_the_window_is_full_height_and_the_canvas_has_room(measured, width):
    got = measured[width]
    assert got["errors"] == []
    # Measured before the fix: a 183px sheet and a 0px canvas.
    assert got["window"]["h"] >= 800, got["window"]
    assert got["viewport"]["h"] >= 500, got["viewport"]


@pytest.mark.parametrize("width", [390, 768])
def test_at_phone_width_every_step_is_on_the_canvas_where_a_person_can_see_it(measured, width):
    steps = measured[width]["steps"]
    assert [s["title"] for s in steps] == ["Nightly backup", "Post summary", "Message me"]
    for s in steps:
        assert s["inside"] and s["seen"], s


@pytest.mark.parametrize("width", [390, 768])
def test_at_phone_width_a_step_opens_and_saves(measured, width):
    got = measured[width]
    assert got["clicked"] is True, "the step could not be clicked where it is drawn"
    assert got["panel"]["h"] >= 500, got["panel"]
    assert got["nameBox"] == {"h": got["nameBox"]["h"], "seen": True} and got["nameBox"]["h"] > 0
    assert got["after"] == {"said": "Saved Post the summary.", "panelHidden": True,
                            "title": "Post the summary"}


@pytest.mark.parametrize("width", [390, 768, 1400])
def test_no_width_scrolls_the_page_sideways(measured, width):
    assert measured[width]["scroll"]["sw"] == measured[width]["scroll"]["cw"]


def test_a_desktop_window_keeps_its_own_size(measured):
    """Not touched by the phone rule: `min(780px, 88vh)` at 860px tall."""
    got = measured[1400]
    assert got["window"]["h"] == round(min(780, 0.88 * 860)), got["window"]
    assert all(s["inside"] and s["seen"] for s in got["steps"]), got["steps"]
    assert got["after"]["said"] == "Saved Post the summary."
