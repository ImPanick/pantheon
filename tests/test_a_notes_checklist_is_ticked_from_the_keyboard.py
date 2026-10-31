# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1551` — a note's checklist item is ticked from the keyboard.

`P10-01`'s `Verify:` names *a note's checkbox* among the controls Tab lands on
and the one ring draws on; `B662`'s browser pass found it was not a control at
all. The three done controls — a card's `.note-check-dot`, the Today view's
`.note-check-dot` and the edit form's `.note-cl-dot` — were `<span>`s with a
click handler and nothing else: no tab stop, no role, no key.

Driven in Chromium against the real app (`Law 20`): a checklist note and a
goal are made through the API, the Notes window is opened from its rail
button, and on each of the three surfaces —

  * real Tab presses land on each item's done control;
  * it is `role="checkbox"` with an `aria-checked` that tells the truth, and is
    named for its item;
  * keyboard focus draws the one ring (`--focus-ring`, its width and offset);
  * Space and Enter tick it — on the card and in Today the server is told, in
    the form the row is marked — and in Today, whose row is re-drawn, the
    caret goes to the goal's next step instead of to `<body>`.

The form's text box took every Tab for indentation, including the ones that
could not indent any further, so a keyboard that entered an item's text could
not leave it: the remaining done controls were unreachable. At the edge the
key now moves focus (Shift+Tab at no indent walks back through the list and
changes nothing); where it can indent, it still does.

Found on the way: the form wired its checklist only for `todo`, and the
agent's note tool writes `checklist` — so on an agent-made list the form's
dot, ×, Enter and Tab did nothing, by mouse or key. Both types are driven.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await context.newPage();
  const out = { errors: [] };
  page.on('pageerror', (e) => out.errors.push(String((e && e.stack) || e)));
  const creds = { username: 'ticker', password: 'ticker-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const made = async (body) => {
    const r = await page.request.post(BASE + '/api/notes', { data: body });
    if (!r.ok()) throw new Error('could not make a note: ' + r.status() + ' ' + await r.text());
    return (await r.json()).id;
  };
  const listId = await made({ title: 'Groceries', note_type: 'todo',
    items: [{ id: 'i1', text: 'Milk', done: false }, { id: 'i2', text: 'Eggs', done: false }] });
  // The type the agent's note tool writes.
  const packId = await made({ title: 'Packing', note_type: 'checklist',
    items: [{ id: 'p1', text: 'Socks', done: false }, { id: 'p2', text: 'Charger', done: false }] });
  const goalId = await made({ title: 'Ship it', note_type: 'goal',
    items: [{ id: 'g1', text: 'Step one', done: false }, { id: 'g2', text: 'Step two', done: false }] });
  const items = async (id) => {
    const r = await page.request.get(BASE + '/api/notes');
    const all = await r.json();
    const list = Array.isArray(all) ? all : (all.notes || []);
    return (list.find((n) => n.id === id) || {}).items || [];
  };

  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(800);
  // The cockpit's rail is the desktop door to Notes (its Tools list lives in the phone drawer).
  await page.click('#rail-notes');
  await page.waitForSelector('.note-card .note-check-dot', { timeout: 30000 });
  await page.waitForTimeout(400);

  // What the focused element is, and the ring it draws against the one the
  // palette asks for — once it has finished drawing (`.note-cl-dot` carries
  // `transition: all`, so its ring eases in over 150 ms).
  const here = () => page.evaluate(async () => {
    const a = document.activeElement;
    if (a && a.getAnimations) await Promise.all(a.getAnimations().map((x) => x.finished.catch(() => null)));
    const probe = document.createElement('i');
    probe.style.cssText = 'position:absolute;color:var(--focus-ring)';
    document.body.appendChild(probe);
    const root = getComputedStyle(document.documentElement);
    const want = { color: getComputedStyle(probe).color,
                   width: root.getPropertyValue('--focus-ring-width').trim(),
                   offset: root.getPropertyValue('--focus-ring-offset').trim() };
    probe.remove();
    const cs = a ? getComputedStyle(a) : null;
    return {
      tag: a ? a.tagName : null, cls: a ? String(a.className || '') : null,
      role: a ? a.getAttribute('role') : null, checked: a ? a.getAttribute('aria-checked') : null,
      label: a ? a.getAttribute('aria-label') : null,
      visible: a ? a.matches(':focus-visible') : false,
      ring: cs ? { style: cs.outlineStyle, width: cs.outlineWidth, offset: cs.outlineOffset,
                   color: cs.outlineColor } : null,
      want,
    };
  });
  // Tab until a done control named `label` has the focus, or give up.
  const tabTo = async (label, key = 'Tab', limit = 40) => {
    const seen = [];
    for (let i = 0; i < limit; i++) {
      await page.keyboard.press(key);
      const h = await here();
      seen.push(h.role === 'checkbox' ? 'checkbox:' + h.label : (h.tag + '.' + (h.cls || '').split(' ')[0]));
      if (h.role === 'checkbox' && h.label === label) return { reached: true, presses: i + 1, seen };
    }
    return { reached: false, seen };
  };

  // ── The card ───────────────────────────────────────────────────────────
  out.card = {};
  await page.evaluate((id) => {
    const t = document.querySelector(`.note-card[data-note-id="${id}"] .note-card-title`);
    t.setAttribute('tabindex', '-1'); t.focus();
  }, listId);
  out.card.toMilk = await tabTo('Milk');
  out.card.milk = await here();
  await page.keyboard.press('Space');
  await page.waitForTimeout(500);
  out.card.afterSpace = { here: await here(), server: (await items(listId)).map((i) => i.done),
                          rowDone: await page.evaluate((id) =>
                            document.querySelector(`.note-card[data-note-id="${id}"] .note-checkbox`).classList.contains('done'), listId) };
  await page.keyboard.press('Enter');
  await page.waitForTimeout(500);
  out.card.afterEnter = { here: await here(), server: (await items(listId)).map((i) => i.done) };
  out.card.toEggs = await tabTo('Eggs');
  out.card.eggs = await here();

  // ── Today ──────────────────────────────────────────────────────────────
  out.today = {};
  await page.click('.notes-label-chip-today');
  await page.waitForSelector('.notes-today-row .note-check-dot', { timeout: 10000 });
  await page.focus('.notes-label-chip-today');
  out.today.toStep = await tabTo('Step one');
  out.today.step = await here();
  await page.keyboard.press('Space');
  await page.waitForFunction(() => {
    const d = document.querySelector('.notes-today-row .note-check-dot');
    return d && d.getAttribute('aria-label') === 'Step two';
  }, null, { timeout: 10000 }).catch(() => null);   // measured below either way
  await page.waitForTimeout(200);
  out.today.afterSpace = { here: await here(), server: (await items(goalId)).map((i) => i.done) };
  await page.click('.notes-label-chip-today');   // back to every note
  await page.waitForSelector('.note-card .note-check-dot', { timeout: 10000 });

  // ── The form, for a list a person made (`todo`) and one the agent made
  // (`checklist`, which the form drew and never wired) ──────────────────
  const formRun = async (id, first, second) => {
    const f = {};
    await page.click(`.note-card[data-note-id="${id}"] .note-card-title`);
    await page.waitForSelector('.note-cl-row .note-cl-dot', { timeout: 10000 });
    await page.waitForTimeout(300);
    await page.focus('.note-form .note-form-title');
    f.toFirst = await tabTo(first);
    f.first = await here();
    await page.keyboard.press('Space');
    f.afterSpace = { here: await here(),
      rowDone: await page.evaluate(() => document.querySelector('.note-cl-row').classList.contains('done')) };
    await page.keyboard.press('Enter');
    f.afterEnter = await here();
    // The whole list walked backwards from "+ Add" with Shift+Tab: each
    // done control in turn, through each text box, indenting nothing.
    await page.keyboard.press('Tab');
    f.inText = await here();
    await page.focus('.note-form .note-cl-add');
    f.backToSecond = await tabTo(second, 'Shift+Tab');
    f.second = await here();
    f.backToFirst = await tabTo(first, 'Shift+Tab');
    f.indents = await page.evaluate(() =>
      [...document.querySelectorAll('.note-cl-row')].map((r) => r.dataset.indent));
    // Tab inside a text box that CAN indent still indents.
    await page.focus('.note-cl-row:nth-child(2) .note-cl-text');
    await page.keyboard.press('Tab');
    f.indentStill = await page.evaluate(() => ({
      indent: document.querySelector('.note-cl-row:nth-child(2)').dataset.indent,
      focus: document.activeElement.className }));
    await page.click('.note-form .note-form-cancel');
    await page.waitForSelector('.note-card .note-check-dot', { timeout: 10000 });
    await page.waitForTimeout(300);
    return f;
  };
  out.form = { todo: await formRun(listId, 'Milk', 'Eggs'),
               checklist: await formRun(packId, 'Socks', 'Charger') };
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("note-ticks")
    script = d / "ticks.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _is_the_ring(h):
    return (h["visible"] and h["ring"]["style"] == "solid"
            and h["ring"]["width"] == h["want"]["width"]
            and h["ring"]["offset"] == h["want"]["offset"]
            and h["ring"]["color"] == h["want"]["color"])


def _is_the_control(h, label, checked):
    return h["role"] == "checkbox" and h["label"] == label and h["checked"] == checked


def test_nothing_threw(measured):
    assert measured["errors"] == []


def test_a_cards_items_are_tab_stops_ticked_by_space_and_enter(measured):
    card = measured["card"]
    assert card["toMilk"]["reached"], card["toMilk"]["seen"]
    assert _is_the_control(card["milk"], "Milk", "false"), card["milk"]
    assert _is_the_ring(card["milk"]), card["milk"]
    after = card["afterSpace"]
    assert _is_the_control(after["here"], "Milk", "true") and after["rowDone"], after
    assert after["server"] == [True, False], "Space did not reach the server"
    assert _is_the_control(card["afterEnter"]["here"], "Milk", "false"), card["afterEnter"]
    assert card["afterEnter"]["server"] == [False, False], "Enter did not untick it"
    assert card["toEggs"]["reached"], card["toEggs"]["seen"]
    assert _is_the_control(card["eggs"], "Eggs", "false") and _is_the_ring(card["eggs"])


def test_todays_step_is_a_tab_stop_and_the_caret_follows_the_goal(measured):
    today = measured["today"]
    assert today["toStep"]["reached"], today["toStep"]["seen"]
    assert _is_the_control(today["step"], "Step one", "false") and _is_the_ring(today["step"])
    after = today["afterSpace"]
    assert after["server"] == [True, False], after
    assert _is_the_control(after["here"], "Step two", "false"), (
        "after the tick re-drew the row the caret is not on the goal's next step", after["here"])


@pytest.mark.parametrize("kind,first,second", [("todo", "Milk", "Eggs"),
                                                ("checklist", "Socks", "Charger")])
def test_the_forms_items_are_tab_stops_and_its_text_box_lets_a_no_op_tab_go(measured, kind, first, second):
    form = measured["form"][kind]
    assert form["toFirst"]["reached"], form["toFirst"]["seen"]
    assert _is_the_control(form["first"], first, "false") and _is_the_ring(form["first"])
    assert _is_the_control(form["afterSpace"]["here"], first, "true") and form["afterSpace"]["rowDone"]
    assert _is_the_control(form["afterEnter"], first, "false"), form["afterEnter"]
    assert "note-cl-text" in form["inText"]["cls"], form["inText"]
    assert form["backToSecond"]["reached"], form["backToSecond"]["seen"]
    assert _is_the_control(form["second"], second, "false") and _is_the_ring(form["second"])
    assert form["backToFirst"]["reached"], (
        f"Shift+Tab never left {first}'s text box", form["backToFirst"]["seen"])
    assert form["indents"] == ["0", "0"], "walking the list re-indented it"


@pytest.mark.parametrize("kind", ["todo", "checklist"])
def test_tab_still_indents_where_it_can(measured, kind):
    still = measured["form"][kind]["indentStill"]
    assert still["indent"] == "1" and "note-cl-text" in still["focus"], still
