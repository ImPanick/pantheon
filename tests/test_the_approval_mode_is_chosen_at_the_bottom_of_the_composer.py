# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1706` — a chat's approval mode is chosen at the bottom of the composer.

The owner, 2026-10-30, with a screenshot of another product's composer (a
small chip at its bottom right naming the permission mode, which opens a menu
of two modes, each with one line, the current one checked): *"So we have the
similar of what you have then? … Only use for reference and creativity path.
Not a direct copy.. But that's at the bottom of the chat - we need something
like that."*

**Measured before this change, on `2c6b9697`:** the approval mode was an on/off
chip labelled *Auto-approve* in the Plan / Web / Shell strip at the bottom
left — `aria-pressed`, a click flipped it — with no word for the mode it was
in when it was off, nothing naming the other mode, and no line saying what
either does. `GET …/approval-mode` served the Auto warning's words and the
chip's one label, and nothing for a selector to say.

**The adversary (`Law 17`) is the same one `B1703` names** — the author of what
the agent reads — so nothing here moves a gate: choosing Auto-approve runs the
accepted-warning flow unchanged (*Proceed to auto-approve*, opening on *Keep
asking me*, recorded by the server), and Manual approve takes effect at once.
What this row adds is the surface: a chip naming the mode (the server's word),
a menu headed with the setting's name listing both modes with the server's one
line each, a check on the current one (`menuitemradio`, `aria-checked`), the
model picker's menu and keys rather than a second popover (`Law 14`), and the
old chip gone from the strip (`Law 7`).

Driven (`Law 20`): the real `GET` handler for the words; and, in headless
Chromium against the real app (its routes, its database, `approvalMode.js`,
`ui.js`'s dialog, `turnSheet.js`), the chip, the menu, the mouse path, the
keyboard path, a click outside, the warning, a phone-width bar, a person
without the privilege, and every palette's contrast on everything the
selector paints. `tests/test_a_chat_decides_whether_it_asks_in_the_browser.py`
drives the module's state under node.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from src import approval_mode as am
from tests.helpers.signed_in import ADMIN, MEMBER
from tests.helpers.source_text import blank
from tests.test_a_workflow_is_kept_as_one_document import wf_db  # noqa: F401  (fixture)
from tests.test_auto_approve_is_a_risk_the_person_accepts import (  # noqa: F401  (fixtures)
    chat_routes, people,
)
from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"


# ── the words are the server's ──────────────────────────────────────────────


def test_the_menu_s_words_are_served_by_the_approval_mode_read(chat_routes):
    """`Law 10`, `Law 7`: the setting's name and each mode's name, chip word
    and one line come from `src/approval_mode.py` through the existing `GET`,
    in the order the menu lists them. Fails on `2c6b9697`: no such fields."""
    got = chat_routes.get(chat_routes.chat())
    assert got["setting_label"] == am.SETTING_LABEL == "Approval mode"
    assert got["modes"] == [
        {"mode": "manual", "label": "Manual approve", "short_label": "Manual",
         "description": am.MODE_CHOICES[0]["description"]},
        {"mode": "auto", "label": am.AUTO_LABEL, "short_label": "Auto",
         "description": am.MODE_CHOICES[1]["description"]},
    ]
    # One line each, naming a consequence; Auto's ends where its warning does,
    # because it is true (`B1341`) and the menu is where a person decides.
    for mode in got["modes"]:
        assert mode["description"] and "\n" not in mode["description"]
        assert len(mode["description"]) < 120, mode
    assert got["modes"][1]["description"].endswith(
        "A step that deletes or overwrites something still asks.")
    assert am.AUTO_WARNING.endswith("A step that deletes or overwrites something still asks.")


def test_a_person_who_may_not_set_it_is_told_so_beside_the_words(chat_routes):
    """The words are the install's; `may_set` is the person's (`Law 15`: the
    browser hides the chip on it)."""
    sid = chat_routes.chat(owner=MEMBER)
    got = chat_routes.get(sid, who=MEMBER)
    assert got["may_set"] is False and got["modes"] == am.mode_choices()
    assert chat_routes.get(chat_routes.chat())["may_set"] is True


def test_the_served_words_are_copies():
    """A caller that edits what it was served cannot change what the next
    caller reads."""
    first = am.mode_choices()
    first[0]["label"] = "changed"
    assert am.mode_choices()[0]["label"] == "Manual approve"


def test_the_model_picker_and_the_approval_menu_share_one_set_of_keys():
    """`Law 14`: one popover pattern. The model picker's arrow-key walk moved
    to `pickerKeys.js` and both menus import it; neither keeps a copy. Read as
    import statements and function definitions — the shape, not a word in a
    comment (`Law 20`)."""
    for name in ("modelPicker.js", "approvalMode.js"):
        code = blank(JS / name)
        assert re.search(r"^import \{ handlePickerKeydown \} from './pickerKeys\.js';", code, re.M), name
        assert not re.search(r"function\s+_?handlePickerKeydown\s*\(", code), f"{name} keeps its own copy"
    assert "handlePickerKeydown(e, listEl, '.model-switch-item', _close)" in blank(JS / "modelPicker.js")


# ── driven in Chromium against the real app ─────────────────────────────────

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const OWNER = { username: 'ada', password: 'ada-pass-1234' };
const MEMBER = { username: 'bob', password: 'bob-pass-1234' };
let step = 'start';   // which part failed, said on the way out
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const fresh = async (opts) => {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block', ...(opts || {}) });
    await ctx.addInitScript(() => {
      try {
        localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
        localStorage.setItem('pantheon-hint-drag-to-snap-seen', '1');
      } catch (_) {}
    });
    const page = await ctx.newPage();
    page.setDefaultTimeout(60000);
    page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
    return page;
  };
  // A member may not name a raw endpoint (`Choose a registered model
  // endpoint`); a chat with none is still a chat with a mode.
  const chatFor = async (page, name, raw = true) => (await (await page.request.post(BASE + '/api/session', { form: {
    name, ...(raw ? { endpoint_url: 'http://127.0.0.1:9/v1/chat/completions' } : {}), model: 'm',
    skip_validation: '1' } })).json()).id;
  const openChat = async (page, sid) => {
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 120000 });
    await page.waitForFunction((sid) => !!document.querySelector(
      `#session-list .list-item[data-session-id="${sid}"]`), sid);
    const read = page.waitForResponse((r) => r.url().includes('/approval-mode') && r.request().method() === 'GET');
    await page.evaluate((sid) => document.querySelector(
      `#session-list .list-item[data-session-id="${sid}"]`).click(), sid);
    await read;
    await page.waitForTimeout(300);
  };

  // ── the owner, an admin: may set it ──
  const page = await fresh();
  await page.request.post(BASE + '/api/auth/setup', { data: OWNER });
  await page.request.post(BASE + '/api/auth/login', { data: { ...OWNER, remember: true } });
  await page.request.post(BASE + '/api/auth/users', { data: { ...MEMBER, is_admin: false } });
  const sid = await chatFor(page, 'Mode chat');
  const modeUrl = BASE + '/api/session/' + encodeURIComponent(sid) + '/approval-mode';
  const mode = async () => (await page.request.get(modeUrl)).json();
  out.served = await mode();
  const posts = [];
  page.on('request', (r) => { if (r.method() === 'POST' && r.url().includes('/approval-mode')) posts.push(r.postDataJSON()); });
  await openChat(page, sid);
  await page.waitForFunction(() => {
    const c = document.getElementById('approval-mode-btn');
    return !!c && c.getBoundingClientRect().width > 0;
  });

  const chip = () => page.evaluate(() => {
    const c = document.getElementById('approval-mode-btn');
    const menu = document.getElementById('approval-mode-menu');
    const a = document.activeElement;
    return {
      text: c.textContent.trim(), name: c.getAttribute('aria-label'), active: c.classList.contains('active'),
      haspopup: c.getAttribute('aria-haspopup'), expanded: c.getAttribute('aria-expanded'),
      open: !menu.classList.contains('hidden') && !menu.classList.contains('closing')
            && getComputedStyle(menu).display !== 'none',
      checked: [...document.querySelectorAll('[data-approval-choice]')]
        .filter((i) => i.getAttribute('aria-checked') === 'true').map((i) => i.dataset.approvalChoice),
      focus: a ? (a.id || (a.dataset && a.dataset.approvalChoice) || a.tagName) : null,
      ring: a && a !== document.body ? getComputedStyle(a).outlineStyle : null,
      kb: [...document.querySelectorAll('[data-approval-choice].kb-active')].map((i) => i.dataset.approvalChoice),
      badge: !document.getElementById('chat-auto-approve-badge').hidden,
    };
  });
  const dialog = () => page.evaluate(() => {
    const o = document.getElementById('styled-confirm-overlay');
    const shown = !!o && !o.classList.contains('hidden') && getComputedStyle(o).display !== 'none';
    return shown ? { message: document.getElementById('styled-confirm-msg').textContent,
                     ok: document.getElementById('styled-confirm-ok').textContent,
                     cancel: document.getElementById('styled-confirm-cancel').textContent,
                     focus: document.activeElement && document.activeElement.id } : null;
  });
  // The menu rises over 0.2 s (`picker-roll-up`). A click on a row still
  // moving misses it, and Playwright then retries by force-scrolling — which
  // slides `.chat-container` (`overflow: hidden` over the wider scenery)
  // sideways, so every later click lands somewhere else. So each open settles
  // before a row is pressed, as a person's second click does.
  const settle = () => page.waitForTimeout(350);
  const openMenu = async () => { await page.click('#approval-mode-btn'); await settle(); };

  // Where it is, and what it says shut.
  out.place = await page.evaluate(() => {
    const c = document.getElementById('approval-mode-btn');
    const bar = document.querySelector('.chat-input-bar').getBoundingClientRect();
    const r = c.getBoundingClientRect();
    return { inRight: !!c.closest('.chat-input-right'), inStrip: !!c.closest('.chat-input-left'),
             stripHasOne: !!document.querySelector('.chat-input-left #approval-mode-btn'),
             lowerHalf: r.top > bar.top + bar.height / 2, rightHalf: r.left > bar.left + bar.width / 2 };
  });
  out.shut = await chip();

  // ── the mouse: open, read, click outside ──
  step = 'the mouse';
  await page.click('#approval-mode-btn');
  await settle();
  out.opened = await chip();
  out.menu = await page.evaluate(() => ({
    heading: document.getElementById('approval-mode-menu-title').textContent,
    labelledBy: document.getElementById('approval-mode-options').getAttribute('aria-labelledby'),
    role: document.getElementById('approval-mode-options').getAttribute('role'),
    items: [...document.querySelectorAll('#approval-mode-options [data-approval-choice]')].map((i) => ({
      mode: i.dataset.approvalChoice, role: i.getAttribute('role'), checked: i.getAttribute('aria-checked'),
      name: i.querySelector('.approval-mode-item-name').textContent,
      line: i.querySelector('.approval-mode-item-desc').textContent,
      tick: getComputedStyle(i.querySelector('.approval-mode-item-check')).visibility,
      shown: i.getBoundingClientRect().height > 0 })),
    reusesPicker: document.getElementById('approval-mode-menu').classList.contains('model-picker-menu')
      && !!document.querySelector('#approval-mode-menu .model-picker-list .mp-section-label')
      && document.querySelectorAll('#approval-mode-menu .model-switch-item').length === 2,
  }));
  const bar = await page.$('.chat-input-bar');
  const box = await bar.boundingBox();
  await page.mouse.click(box.x + 4, box.y + 4);
  await settle();
  out.outside = await chip();

  // ── Auto-approve: the warning, opening on Keep asking me ──
  step = 'Auto-approve';
  await openMenu();
  await page.click('[data-approval-choice="auto"]');
  await page.waitForSelector('#styled-confirm-ok', { state: 'visible' });
  out.warning = await dialog();
  await page.keyboard.press('Enter');
  await settle();
  out.kept = { posts: posts.length, auto: (await mode()).auto, ui: await chip() };

  await openMenu();
  await page.click('[data-approval-choice="auto"]');
  await page.waitForSelector('#styled-confirm-ok', { state: 'visible' });
  await page.click('#styled-confirm-ok');
  await page.waitForFunction(() => !document.getElementById('chat-auto-approve-badge').hidden);
  await settle();
  const on = await mode();
  out.on = { posts: posts.slice(), auto: on.auto, accepted: on.accepted, ui: await chip() };

  // ── Manual approve: at once, no question ──
  step = 'Manual approve';
  await openMenu();
  await page.click('[data-approval-choice="manual"]');
  await page.waitForFunction(() => document.getElementById('chat-auto-approve-badge').hidden);
  await settle();
  const off = await mode();
  out.off = { dialog: await dialog(), lastPost: posts[posts.length - 1], auto: off.auto,
              accepted: off.accepted, ui: await chip() };

  // ── the keyboard ──
  step = 'the keyboard';
  await page.focus('#approval-mode-btn');
  await page.keyboard.press('Enter');
  await settle();
  out.kb = { open: await chip() };
  await page.keyboard.press('ArrowDown');
  out.kb.down = await chip();
  await page.keyboard.press('ArrowDown');
  out.kb.wrap = await chip();
  await page.keyboard.press('ArrowUp');
  out.kb.up = await chip();
  await page.keyboard.press('Escape');
  await settle();
  out.kb.escape = await chip();
  await page.keyboard.press(' ');
  await settle();
  out.kb.space = await chip();
  await page.keyboard.press('Tab');
  await settle();
  out.kb.tab = await chip();
  // Auto from the keyboard: the warning, and Proceed.
  await page.focus('#approval-mode-btn');
  await page.keyboard.press('Enter');
  await settle();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await page.waitForSelector('#styled-confirm-ok', { state: 'visible' });
  out.kb.warning = await dialog();
  await page.click('#styled-confirm-ok');
  await page.waitForFunction(() => !document.getElementById('chat-auto-approve-badge').hidden);
  await settle();
  out.kb.on = { auto: (await mode()).auto, ui: await chip() };
  // Manual from the keyboard: Space on it, no question, focus back on the chip.
  await page.focus('#approval-mode-btn');
  await page.keyboard.press('Enter');
  await settle();
  out.kb.reopened = await chip();
  await page.keyboard.press('ArrowUp');
  await page.keyboard.press(' ');
  await page.waitForFunction(() => document.getElementById('chat-auto-approve-badge').hidden);
  await settle();
  out.kb.off = { dialog: await dialog(), auto: (await mode()).auto, ui: await chip() };

  // ── every palette: what the selector paints, measured where it is painted ──
  step = 'every palette';
  // Three passes over all of them, because a pointer cannot be in three
  // places: away from everything (the chip off and on, the heading, both
  // rows — one of them the focused, keyboard-highlighted one), on the chip,
  // and on a row. Each thing is measured on the ground it is painted on,
  // read from the page rather than assumed: the composer (and the composer
  // in plan mode) under the chip's own background, and the menu's panel under
  // a row's own background.
  await page.addStyleTag({ content: '*, *::before, *::after { transition: none !important; animation: none !important; }' });
  await page.click('#approval-mode-btn');
  await settle();
  const sweep = (where) => page.evaluate(async (where) => {
    const tm = await import('/static/js/theme.js');
    const cv = document.createElement('canvas'); cv.width = cv.height = 1;
    const cx = cv.getContext('2d', { willReadFrequently: true });
    const rgba = (css) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = css; cx.fillRect(0, 0, 1, 1);
      const d = cx.getImageData(0, 0, 1, 1).data; return { c: [d[0], d[1], d[2]], a: d[3] / 255 }; };
    const over = (top, under) => top.c.map((v, i) => v * top.a + under[i] * (1 - top.a));
    const lum = (rgb) => { const [r, g, b] = rgb.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
    const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    const ink = (node, ground) => ratio(over(rgba(getComputedStyle(node).color), ground), ground);
    const chipEl = document.getElementById('approval-mode-btn');
    const label = document.getElementById('approval-mode-label');
    const barEl = document.querySelector('.chat-input-bar');
    const menu = document.getElementById('approval-mode-menu');
    const heading = document.getElementById('approval-mode-menu-title');
    const items = [...document.querySelectorAll('[data-approval-choice]')];
    const res = {};
    for (const name of Object.keys(tm.THEMES)) {
      tm.applyColors(tm.THEMES[name]);
      const worst = {};
      const note = (k, r) => { worst[k] = Math.min(worst[k] === undefined ? Infinity : worst[k], r); };
      const chipStates = where === 'chip' ? ['hover'] : where === 'away' ? ['off', 'on'] : [];
      for (const plan of [false, true]) {
        document.body.classList.toggle('plan-mode-active', plan);
        const ground = rgba(getComputedStyle(barEl).backgroundColor).c;
        for (const state of chipStates) {
          chipEl.classList.toggle('active', state === 'on');
          note('chip-' + state, ink(label, over(rgba(getComputedStyle(chipEl).backgroundColor), ground)));
        }
      }
      document.body.classList.remove('plan-mode-active');
      chipEl.classList.remove('active');
      const panel = rgba(getComputedStyle(menu).backgroundColor).c;
      if (where === 'away') note('heading', ink(heading, panel));
      if (where !== 'chip') {
        const rows = where === 'row' ? items.filter((i) => i.matches(':hover')) : items;
        for (const row of rows) {
          const g = over(rgba(getComputedStyle(row).backgroundColor), panel);
          const k = where === 'row' ? '-hover' : '';
          note('name' + k, ink(row.querySelector('.approval-mode-item-name'), g));
          note('line' + k, ink(row.querySelector('.approval-mode-item-desc'), g));
        }
      }
      res[name] = worst;
    }
    return res;
  }, where);
  await page.mouse.move(2, 2);
  out.highlight = await page.evaluate(() => {
    const kb = document.querySelector('[data-approval-choice].kb-active');
    return { kb: kb && kb.dataset.approvalChoice, focused: document.activeElement === kb,
             ring: kb ? getComputedStyle(kb).outlineStyle : null };
  });
  const passes = [await sweep('away')];
  await page.hover('#approval-mode-btn');
  passes.push(await sweep('chip'));
  await page.hover('[data-approval-choice="auto"]');
  passes.push(await sweep('row'));
  out.palettes = {};
  for (const pass of passes) {
    for (const [name, row] of Object.entries(pass)) {
      out.palettes[name] = out.palettes[name] || {};
      for (const [k, v] of Object.entries(row)) out.palettes[name][k] = Math.round(v * 100) / 100;
    }
  }

  // ── a phone: the bar keeps its room, and the sheet's row is the way in ──
  step = 'a phone';
  const phone = await fresh({ viewport: { width: 360, height: 800 }, hasTouch: true, isMobile: true });
  await phone.request.post(BASE + '/api/auth/login', { data: { ...OWNER, remember: true } });
  const psid = await chatFor(phone, 'Phone chat');
  const pmode = async () => (await phone.request.get(BASE + '/api/session/' + encodeURIComponent(psid) + '/approval-mode')).json();
  await openChat(phone, psid);
  out.phone = await phone.evaluate(() => {
    const bottom = document.querySelector('.chat-input-bottom');
    return { pageWidth: document.documentElement.scrollWidth, viewport: window.innerWidth,
             rowFits: bottom.scrollWidth <= bottom.clientWidth + 1,
             wrap: getComputedStyle(document.getElementById('approval-mode-wrap')).display,
             turnChip: getComputedStyle(document.getElementById('turn-chip')).display };
  });
  await phone.tap('#turn-chip');
  await phone.waitForSelector('#turn-approval-auto', { state: 'visible' });
  await phone.tap('#turn-approval-auto');
  await phone.waitForSelector('#styled-confirm-ok', { state: 'visible' });
  await phone.tap('#styled-confirm-ok');
  await phone.waitForFunction(() => !document.getElementById('turn-chip-approval').hidden);
  out.phone.on = (await pmode()).auto;
  await phone.tap('#turn-chip');
  await phone.waitForSelector('#turn-approval-manual', { state: 'visible' });
  await phone.tap('#turn-approval-manual');
  await phone.waitForFunction(() => document.getElementById('turn-chip-approval').hidden);
  await phone.waitForTimeout(300);
  out.phone.off = (await pmode()).auto;
  out.phone.askedOnTheWayOut = await phone.evaluate(() => {
    const o = document.getElementById('styled-confirm-overlay');
    return !!o && !o.classList.contains('hidden') && getComputedStyle(o).display !== 'none';
  });

  // ── a person without the privilege: no chip, no row ──
  step = 'a person without the privilege';
  const member = await fresh();
  await member.request.post(BASE + '/api/auth/login', { data: { ...MEMBER, remember: true } });
  const msid = await chatFor(member, 'Member chat', false);
  await openChat(member, msid);
  out.member = await member.evaluate(() => ({
    chip: document.getElementById('approval-mode-btn').style.display,
    wrap: getComputedStyle(document.getElementById('approval-mode-wrap')).display,
    row: document.getElementById('turn-row-approval').hidden,
    badge: document.getElementById('chat-auto-approve-badge').hidden,
  }));
  out.member.maySet = (await (await member.request.get(BASE + '/api/session/' + encodeURIComponent(msid) + '/approval-mode')).json()).may_set;

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error('at step: ' + step); console.error(e); process.exit(1); });
"""

pytestmark_browser = pytest.mark.skipif(NODE is None, reason=_SKIP or "")


@pytest.fixture(scope="module")
def driven(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("b1706") / "selector.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=600, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytestmark_browser
def test_nothing_threw(driven):
    assert driven["errors"] == []


@pytestmark_browser
def test_the_chip_is_at_the_bottom_right_of_the_composer_and_names_the_mode(driven):
    assert driven["place"] == {"inRight": True, "inStrip": False, "stripHasOne": False,
                               "lowerHalf": True, "rightHalf": True}
    shut = driven["shut"]
    assert shut["text"] == "Manual" and shut["name"] == "Approval mode: Manual approve"
    assert (shut["haspopup"], shut["expanded"], shut["open"]) == ("menu", "false", False)
    assert shut["active"] is False and shut["badge"] is False


@pytestmark_browser
def test_the_menu_says_the_servers_words_with_the_check_on_the_current_mode(driven):
    served = driven["served"]
    assert driven["opened"]["open"] is True and driven["opened"]["expanded"] == "true"
    menu = driven["menu"]
    assert menu["heading"] == served["setting_label"] == am.SETTING_LABEL
    assert menu["role"] == "menu" and menu["labelledBy"] == "approval-mode-menu-title"
    assert [(i["mode"], i["name"], i["line"]) for i in menu["items"]] == [
        (m["mode"], m["label"], m["description"]) for m in served["modes"]]
    assert [(i["role"], i["checked"], i["tick"], i["shown"]) for i in menu["items"]] == [
        ("menuitemradio", "true", "visible", True), ("menuitemradio", "false", "hidden", True)]
    assert menu["reusesPicker"] is True, "the model picker's menu, not a second popover"
    # The mode this chat is in takes the focus, so the keys start from it.
    assert driven["opened"]["focus"] == "manual" and driven["opened"]["kb"] == ["manual"]


@pytestmark_browser
def test_a_click_outside_closes_it(driven):
    assert driven["outside"]["open"] is False and driven["outside"]["expanded"] == "false"


@pytestmark_browser
def test_choosing_auto_shows_the_warning_opening_on_keep_asking_me(driven):
    assert driven["warning"] == {"message": am.AUTO_WARNING, "ok": am.PROCEED_LABEL,
                                 "cancel": am.KEEP_ASKING_LABEL, "focus": "styled-confirm-cancel"}
    kept = driven["kept"]
    assert (kept["posts"], kept["auto"]) == (0, False), "Enter on the warning accepted it"
    assert kept["ui"]["checked"] == ["manual"] and kept["ui"]["text"] == "Manual", (
        "declining left the menu off Manual approve")


@pytestmark_browser
def test_proceed_turns_it_on_and_the_chip_and_the_check_follow(driven):
    on = driven["on"]
    assert on["auto"] is True and on["accepted"]["by"] == ADMIN
    (sent,) = on["posts"]
    assert sent == {"mode": "auto", "accept_warning": am.chat_warning()["id"]}
    ui = on["ui"]
    assert (ui["text"], ui["name"], ui["active"], ui["checked"], ui["badge"]) == (
        "Auto", "Approval mode: Auto-approve", True, ["auto"], True)


@pytestmark_browser
def test_choosing_manual_turns_it_off_with_no_question(driven):
    off = driven["off"]
    assert off["dialog"] is None and off["lastPost"] == {"mode": "manual"}
    assert off["auto"] is False and off["accepted"] is None
    ui = off["ui"]
    assert (ui["text"], ui["active"], ui["checked"], ui["badge"], ui["open"]) == (
        "Manual", False, ["manual"], False, False)


@pytestmark_browser
def test_the_keyboard_opens_walks_chooses_and_closes_it(driven):
    kb = driven["kb"]
    assert kb["open"]["open"] is True and kb["open"]["focus"] == "manual"
    # Where the keyboard is, said by the one ring (`B662`), not a tint.
    assert kb["open"]["ring"] == "solid" and kb["down"]["ring"] == "solid"
    assert (kb["down"]["focus"], kb["down"]["kb"]) == ("auto", ["auto"])
    assert kb["wrap"]["focus"] == "manual", "Arrow keys wrap, as the model picker's do"
    assert kb["up"]["focus"] == "auto"
    assert kb["escape"]["open"] is False and kb["escape"]["focus"] == "approval-mode-btn", (
        "Escape closes it and gives the focus back to the chip")
    assert kb["space"]["open"] is True, "Space on the chip opens it"
    assert kb["tab"]["open"] is False, "Tab leaves the menu by closing it"
    assert kb["warning"]["message"] == am.AUTO_WARNING and kb["warning"]["focus"] == "styled-confirm-cancel"
    assert kb["on"]["auto"] is True and kb["on"]["ui"]["checked"] == ["auto"]
    assert kb["reopened"]["focus"] == "auto", "it opens on the mode the chat is in"
    off = kb["off"]
    assert off["dialog"] is None and off["auto"] is False and off["ui"]["checked"] == ["manual"]
    assert off["ui"]["open"] is False and off["ui"]["focus"] == "approval-mode-btn"


@pytestmark_browser
def test_everything_it_paints_reads_on_every_palette(driven):
    """WCAG AA, 4.5:1, on the ground each thing is painted on: the chip's word
    off, under the pointer and on (over the composer and the composer in plan
    mode), the heading, and each row's name and line at rest, focused and
    under the pointer. Contrast is function, not beauty.

    This failed on the selector's first draft, which wore the composer's and
    the picker's highlights as they are: `retrowave` and `cute` measured 4.24
    and 4.40 for the word under the pointer (`.input-icon-btn:hover`'s
    `--fg`), 4.18 and 4.19 with the menu open (`.input-icon-btn.expanded`),
    and 3.96 and 4.17 for a row's name under the keyboard's 14% red tint."""
    palettes = driven["palettes"]
    assert len(palettes) >= 23, sorted(palettes)
    assert driven["highlight"]["kb"] == "manual" and driven["highlight"]["focused"] is True
    under = {(name, what): r for name, row in palettes.items() for what, r in row.items() if r < 4.5}
    assert not under, under
    assert set(next(iter(palettes.values()))) == {
        "chip-off", "chip-hover", "chip-on", "heading", "name", "line", "name-hover", "line-hover"}


@pytestmark_browser
def test_a_phone_keeps_its_row_and_reaches_the_mode_through_the_sheet(driven):
    phone = driven["phone"]
    assert phone["pageWidth"] <= phone["viewport"] == 360, "the page scrolls sideways at 360px"
    assert phone["rowFits"] is True, "the composer's bottom row overflows at 360px"
    assert phone["wrap"] == "none" and phone["turnChip"] != "none"
    assert phone["on"] is True, "the sheet's Auto did not reach the warning and the server"
    assert phone["off"] is False and phone["askedOnTheWayOut"] is False


@pytestmark_browser
def test_a_person_without_the_privilege_has_no_selector(driven):
    assert driven["member"] == {"chip": "none", "wrap": "none", "row": True, "badge": True,
                                "maySet": False}
