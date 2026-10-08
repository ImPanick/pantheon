# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B-NEW-1` — the attachment tray was a full-width band that hid the end of the chat.

The owner, 2026-10-08, from a phone: *"The images or attachments sent to the
chat have a massive blank space blocking view."* `#attach-strip` was a block in
the composer's column, so whatever it held came out of the chat's height —
measured on `0345288` in Chromium on the showcase world: 57px for one image,
68px for three files, 42px for the "7 files" pill, at 1440×900 and 390×844 —
with one small thumbnail at the left end of an otherwise empty band.

It is a hand of cards now (`static/js/attachHand.js`, drawn by
`fileHandler.renderAttachStrip`). What is pinned here, and why each is a defect
if it breaks:

  * **the tray is a list with a name, and each card says what it is and where**
    — *"cat.jpg, 2 of 3"* — because a fan of overlapping pictures is the one
    layout a screen reader cannot be left to guess at;
  * **later cards sit behind the first and past five they tuck behind the
    last**, with a count on the front card and a "+N" that spreads the hand —
    a seventh file must still be a card somebody can reach;
  * **a card is dealt once**: the slide-up is for the file that just arrived,
    not for every card on every redraw;
  * **click or Enter selects; right-click, Shift+F10, the menu key and a long
    press open the card's menu**, and the menu is on the Escape stack
    (`escMenuStack.js`, C-NAV) so Escape closes it before anything behind it;
  * **every action is one that already existed**, offered where it can work:
    Preview, Crop for an image the cropper can take, Save to Gallery through
    the Gallery's own route, Remove, Remove all; never an action for a file it
    cannot apply to;
  * **removing from the keyboard leaves the focus somewhere** — the next card,
    or the message box when the hand is empty;
  * **a card keeps `.thumb`**, so the send's upload still dims it and puts its
    whirlpool on it;
  * **the hand follows the chat**: the per-chat set (`B893`) draws its own
    cards, and a selection or a menu does not outlive its file;
  * and in the stylesheet, **the strip gives back the height it takes**, lets
    every pointer through but the cards', lifts a card with a transform only,
    and keeps to the palette's own tokens and the global focus ring.

The script cases drive the real `fileHandler.js` and `attachHand.js` under node;
none reads their source. The stylesheet cases resolve the rules first and
assert inside them (`Law 20`'s second option, as `tests/test_one_focus_ring_css.py`
does for this sheet).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub
from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank

ROOT = Path(__file__).resolve().parents[1]
FILE_HANDLER = ROOT / "static" / "js" / "fileHandler.js"
APP_JS = ROOT / "static" / "app.js"
STYLE = ROOT / "static" / "style.css"

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

// What a browser has and these modules reach for, on the shim's nodes: an
// ancestor test, a connected test, focus that moves `document.activeElement`,
// and `:focus-visible` for a control focused from the keyboard.
Node.prototype.contains = function (n) {
  for (let x = n; x; x = x.parentNode) if (x === this) return true;
  return false;
};
Object.defineProperty(Node.prototype, 'isConnected', {
  configurable: true,
  get() { let n = this; while (n.parentNode) n = n.parentNode; return n === document; },
});
const _focus = Node.prototype.focus;
Node.prototype.focus = function () {
  if (document.activeElement && document.activeElement !== this) document.activeElement._keyboard = false;
  _focus.call(this);
  document.activeElement = this;
};
const _matches = Node.prototype.matches;
Node.prototype.matches = function (sel) {
  if (sel === ':focus-visible') return !!this._keyboard && document.activeElement === this;
  return _matches.call(this, sel);
};
export function keyboardFocus(n) { n.focus(); n._keyboard = true; }

// The composer, as `static/index.html` ships it.
function _with(tag, id) {
  const n = document.body.appendChild(new Node(tag));
  n.setAttribute('id', id);
  return n;
}
export const strip = _with('div', 'attach-strip');
_with('div', 'context-meter').hidden = true;
_with('input', 'file-input');
export const message = _with('textarea', 'message');

URL.createObjectURL = (f) => `blob:${f && f.name}`;
URL.revokeObjectURL = () => {};

/** Every request the page made, and the answers the case scripted. */
export const posted = [];
const _answers = [];
export function answer(status, body) { _answers.push({ status, body }); }
globalThis.fetch = async (url, opts = {}) => {
  const u = String(url);
  if (u.includes('/api/upload/context-budget')) return { ok: true, status: 200, json: async () => ({}) };
  const form = opts.body && typeof opts.body.getAll === 'function'
    ? opts.body.getAll(u.includes('/api/gallery') ? 'file' : 'files').map((f) => f && f.name)
    : null;
  posted.push({ url: u, method: opts.method || 'GET', form });
  if (u.endsWith('/api/upload')) return new Promise(() => {});   // an upload still in flight
  const a = _answers.shift() || { status: 200, body: { ok: true } };
  return { ok: a.status < 400, status: a.status, json: async () => a.body };
};

// The send arms a 120 s abort timer (`uploadPending`); a case that leaves an
// upload in flight must not keep node waiting for it.
const _setTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms, ...rest) => {
  const t = _setTimeout(fn, ms, ...rest);
  if (ms > 5000 && t && t.unref) t.unref();
  return t;
};

export function tick(n = 4) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
export const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** A real `File` — `FormData` and `slice().text()` need one. */
export function aFile(name, type = '', text = 'x') { return new File([text], name, { type }); }

/** An event as the browser hands it to a listener on the node itself. */
export function fire(node, type, extra = {}) {
  const ev = {
    type, target: node, detail: 1, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() {},
    ...extra,
  };
  node.dispatchEvent(ev);
  return ev;
}

const _cls = (n) => String(n.className || '').split(/\s+/).filter(Boolean);
/** The hand, read off the page the way a person (or a screen reader) meets it. */
export function hand() {
  const cards = strip.childNodes.filter((n) => _cls(n).includes('hand-card'));
  const more = strip.childNodes.find((n) => _cls(n).includes('hand-more')) || null;
  return {
    role: strip.getAttribute('role'),
    name: strip.getAttribute('aria-label'),
    classes: _cls(strip),
    last: strip.style['--hand-last'] || null,
    cards: cards.map((c) => {
      const btn = c.querySelector('.hand-card-btn');
      const img = c.querySelector('.hand-card-img');
      const glyph = c.querySelector('.hand-card-glyph');
      const count = c.querySelector('.hand-count');
      return {
        role: c.getAttribute('role'), classes: _cls(c),
        slot: c.style['--slot'], z: c.style['--z'],
        label: btn.getAttribute('aria-label'), pressed: btn.getAttribute('aria-pressed'),
        popup: btn.getAttribute('aria-haspopup'),
        img: img ? img.src : null, glyph: glyph ? glyph.textContent : null,
        count: count ? count.textContent : null,
        x: c.querySelector('.hand-card-x').getAttribute('aria-label'),
        spinner: !!c.querySelector('.thumb-upload-spinner'),
      };
    }),
    more: more ? { text: more.textContent, hidden: more.getAttribute('aria-hidden'), tab: more.tabIndex } : null,
  };
}
export const card = (i) => strip.childNodes.filter((n) => _cls(n).includes('hand-card'))[i];
export const btn = (i) => card(i).querySelector('.hand-card-btn');
export function menu() {
  const m = document.body.childNodes.find((n) => _cls(n).includes('hand-menu'));
  if (!m) return null;
  return {
    node: m, role: m.getAttribute('role'), name: m.getAttribute('aria-label'),
    items: m.childNodes.map((b) => b.dataset.action),
    labels: m.childNodes.map((b) => b.textContent),
  };
}
export function preview() {
  return document.body.childNodes.find((n) => _cls(n).includes('hand-preview')) || null;
}
export const active = () => (document.activeElement && (document.activeElement.getAttribute('aria-label')
  || document.activeElement.getAttribute('id') || document.activeElement.className)) || null;
"""

_STUBS = {
    "ui.js": ui_default_stub(
        "showToast: (m) => { toasts.push(m); }, showError: (m) => { errors.push(m); },\n"
        "  showUploadRejections: () => {}, el: (id) => document.getElementById(id),",
        exports="export const toasts = [];\nexport const errors = [];",
    ),
    "spinner.js": """
export default {
  create: () => ({ createElement: () => document.createElement('span'), start(){}, stop(){} }),
};
""",
}

_PREAMBLE = (
    "import { document, strip, message, posted, answer, tick, wait, aFile, fire, hand,"
    " card, btn, menu, preview, active, keyboardFocus } from './shim.js';\n"
    "import { toasts, errors } from './ui.js';\n"
    "import { _openMenuCount, dismissTopMenu } from './escMenuStack.js';\n"
    "const fh = await import('./fileHandler.js');\n"
    "const H = await import('./attachHand.js');\n"
    "let _chat = 'chat-a';\n"
    "fh.setSessionResolver(() => _chat);\n"
    "const add = (...fs) => fh.addFiles(fs, { skipCrop: true });\n"
    "const say = (o) => console.log(JSON.stringify(o));\n"
)

CAT, NOTES, PIER = ("aFile('cat.jpg', 'image/jpeg')", "aFile('notes.md', 'text/markdown', '# Launch')",
                    "aFile('pier.png', 'image/png')")


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("attachhand"), FILE_HANDLER, _SHIM, _STUBS)


def _drive(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


# ── the hand ────────────────────────────────────────────────────────────────

@needs_node
def test_one_file_is_one_named_card_in_a_named_list(sandbox):
    out = _drive(sandbox, f"""
        await add({CAT});
        say(hand());
    """)
    assert out["role"] == "list" and out["name"] == "Attachments", (
        "the tray is not a list with a name — a screen reader meets a row of "
        "unlabelled buttons"
    )
    assert "attach-hand" in out["classes"], "the stylesheet's hand never applies"
    [c] = out["cards"]
    assert c["role"] == "listitem"
    assert c["label"] == "cat.jpg, 1 of 1", c["label"]
    assert c["img"] == "blob:cat.jpg", "an image card shows no thumbnail"
    assert c["popup"] == "menu" and c["pressed"] == "false"
    assert c["x"] == "Remove cat.jpg"
    assert "thumb" in c["classes"], (
        "the card lost `.thumb` — `uploadPending` finds the chips to dim and "
        "spin by that class"
    )
    assert c["count"] is None and out["more"] is None


@needs_node
def test_later_cards_sit_behind_the_first_with_a_count_on_it(sandbox):
    out = _drive(sandbox, f"""
        await add({CAT}, {NOTES}, {PIER});
        say(hand());
    """)
    cards = out["cards"]
    assert [c["label"] for c in cards] == [
        "cat.jpg, 1 of 3", "notes.md, 2 of 3", "pier.png, 3 of 3"]
    assert [c["slot"] for c in cards] == ["0", "1", "2"], "the hand is not fanned"
    assert [int(c["z"]) for c in cards] == [3, 2, 1], (
        "the first file is not in front — later cards must sit behind it"
    )
    assert [c["count"] for c in cards] == ["3", None, None], "the count is not on the front card alone"
    assert cards[1]["img"] is None and cards[1]["glyph"] == "MD", (
        "a file with no picture shows its type"
    )


@needs_node
def test_past_five_the_rest_tuck_behind_and_plus_n_spreads_the_hand(sandbox):
    out = _drive(sandbox, """
        await add(...[1, 2, 3, 4, 5, 6, 7].map((i) => aFile(`f${i}.txt`, 'text/plain')));
        const folded = hand();
        fire(strip.childNodes.find((n) => String(n.className).includes('hand-more')), 'click');
        const spread = hand();
        fh.removePending(6); fh.removePending(5);
        const five = hand();
        say({ folded, spread, five, state: H.handState() });
    """)
    folded, spread, five = out["folded"], out["spread"], out["five"]
    assert [c["slot"] for c in folded["cards"]] == ["0", "1", "2", "3", "4", "4", "4"], (
        "past five, the rest must wait behind the fifth"
    )
    assert ["hand-card-tucked" in c["classes"] for c in folded["cards"]] == [False] * 5 + [True, True]
    assert folded["more"] == {"text": "+2", "hidden": "true", "tab": -1}, folded["more"]
    assert folded["last"] == "4"
    assert "hand-open" in spread["classes"] and [c["slot"] for c in spread["cards"]] == [
        str(i) for i in range(7)], "+N did not spread the hand"
    assert spread["more"]["text"] == "−"
    assert [c["label"] for c in spread["cards"]][-1] == "f7.txt, 7 of 7", (
        "a tucked card is not a reachable card"
    )
    assert five["more"] is None and "hand-open" not in five["classes"], (
        "five cards fit the fan; the spread must not outlive the overflow"
    )


@needs_node
def test_a_card_is_dealt_once_not_on_every_redraw(sandbox):
    out = _drive(sandbox, f"""
        await add({CAT});
        const first = hand().cards.map((c) => c.classes.includes('hand-card-new'));
        await add({NOTES});
        const second = hand().cards.map((c) => c.classes.includes('hand-card-new'));
        say({{ first, second }});
    """)
    assert out["first"] == [True], "a new card does not slide up"
    assert out["second"] == [False, True], (
        "the card already in the hand slid up again when the next one arrived"
    )


# ── selecting ───────────────────────────────────────────────────────────────

@needs_node
def test_a_click_selects_one_card_and_a_second_click_or_a_touch_elsewhere_lets_go(sandbox):
    out = _drive(sandbox, f"""
        await add({CAT}, {NOTES});
        const pressed = () => hand().cards.map((c) => c.pressed);
        fire(btn(0), 'click'); const one = pressed();
        fire(btn(1), 'click'); const other = pressed();
        fire(btn(1), 'click'); const off = pressed();
        fire(btn(0), 'click');
        fire(document, 'pointerdown', {{ target: message }});
        const away = pressed();
        fire(btn(1), 'click');
        fire(document, 'pointerdown', {{ target: btn(0) }});
        const inside = pressed();
        say({{ one, other, off, away, inside,
              selectedClass: hand().cards.map((c) => c.classes.includes('is-selected')) }});
    """)
    assert out["one"] == ["true", "false"]
    assert out["other"] == ["false", "true"], "two cards selected at once"
    assert out["off"] == ["false", "false"], "a second click does not let the card go"
    assert out["away"] == ["false", "false"], "touching the message box left the card up"
    assert out["inside"] == ["false", "true"], "a touch on the hand itself let the card go"
    assert out["selectedClass"] == [False, True]


# ── the menu ────────────────────────────────────────────────────────────────

@needs_node
def test_right_click_opens_the_cards_menu_and_escape_closes_it_first(sandbox):
    out = _drive(sandbox, f"""
        await add({CAT}, {NOTES});
        const ev = fire(btn(0), 'contextmenu');
        const opened = menu();
        const stack = _openMenuCount();
        const selected = hand().cards[0].pressed;
        const closedByEscape = dismissTopMenu();
        say({{ prevented: ev.defaultPrevented, role: opened && opened.role, name: opened && opened.name,
              items: opened && opened.items, labels: opened && opened.labels, stack, selected,
              closedByEscape, after: menu(), stackAfter: _openMenuCount(), cards: hand().cards.length }});
    """)
    assert out["prevented"], "the browser's own menu would open over the card's"
    assert out["role"] == "menu" and out["name"] == "cat.jpg"
    assert out["items"] == ["preview", "crop", "gallery", "remove", "remove-all"], out["items"]
    assert out["labels"] == ["Preview", "Crop", "Save to Gallery", "Remove", "Remove all"]
    assert out["selected"] == "true", "the card a menu is for is not the selected card"
    assert out["stack"] == 1, "the menu is not on the Escape stack — Escape would close the window behind it"
    assert out["closedByEscape"] is True and out["after"] is None and out["stackAfter"] == 0
    assert out["cards"] == 2, "Escape on the menu took a card with it"


@needs_node
def test_the_menu_offers_only_what_applies(sandbox):
    out = _drive(sandbox, """
        const ui = await import('./ui_visibility.js');
        await add(aFile('notes.md', 'text/markdown'));
        fire(btn(0), 'contextmenu'); const doc = menu().items; dismissTopMenu();
        await add(aFile('loop.gif', 'image/gif'), aFile('scan.bmp', 'image/bmp'));
        fire(btn(1), 'contextmenu'); const gif = menu().items; dismissTopMenu();
        fire(btn(2), 'contextmenu'); const bmp = menu().items; dismissTopMenu();
        ui.applyToolVisibility({ ui: { 'tool-gallery': false } }, null);
        await add(aFile('pier.png', 'image/png'));
        fire(btn(3), 'contextmenu'); const hidden = menu().items; dismissTopMenu();
        fh.clearPending();
        await add(aFile('solo.png', 'image/png'));
        ui.applyToolVisibility({ ui: {} }, null);
        fire(btn(0), 'contextmenu'); const solo = menu().items; dismissTopMenu();
        say({ doc, gif, bmp, hidden, solo });
    """)
    assert out["doc"] == ["preview", "remove"], "a document was offered a picture's actions"
    assert out["gif"] == ["preview", "gallery", "remove", "remove-all"], (
        "the cropper cannot take a GIF and must not be offered for one"
    )
    assert out["bmp"] == ["preview", "crop", "remove", "remove-all"], (
        "the Gallery refuses .bmp (`IMAGE_EXTS`); offering Save to Gallery promises a failure"
    )
    assert "gallery" not in out["hidden"], "Save to Gallery shown with the Gallery switched off"
    assert out["solo"] == ["preview", "crop", "gallery", "remove"], "Remove all offered for one file"


@needs_node
def test_shift_f10_and_the_menu_key_open_it_from_the_keyboard_with_the_focus_inside(sandbox):
    out = _drive(sandbox, f"""
        await add({CAT}, {NOTES});
        keyboardFocus(btn(1));
        const ev = fire(btn(1), 'keydown', {{ key: 'F10', shiftKey: true }});
        await tick();
        const first = {{ name: menu() && menu().name, active: active(), prevented: ev.defaultPrevented }};
        dismissTopMenu();
        const back = active();
        keyboardFocus(btn(0));
        fire(btn(0), 'keydown', {{ key: 'ContextMenu' }});
        await tick();
        const second = {{ name: menu() && menu().name, active: active() }};
        say({{ first, back, second, stack: _openMenuCount() }});
    """)
    assert out["first"]["prevented"] and out["first"]["name"] == "notes.md", out["first"]
    assert out["first"]["active"] == "hand-menu-item", (
        "a menu opened from the keyboard leaves the focus on the card — Tab walks away from it"
    )
    assert out["back"] == "notes.md, 2 of 2", "Escape did not give the focus back to the card"
    assert out["second"] == {"name": "cat.jpg", "active": "hand-menu-item"}
    assert out["stack"] == 1


@needs_node
def test_a_long_press_opens_the_menu_and_the_click_that_ends_it_is_not_a_tap(sandbox):
    out = _drive(sandbox, f"""
        await add({CAT}, {NOTES});
        fire(btn(1), 'pointerdown', {{ pointerType: 'touch', clientX: 10, clientY: 10 }});
        await wait(H.LONG_PRESS_MS + 60);
        const opened = menu() && menu().name;
        fire(btn(1), 'pointerup');
        fire(btn(1), 'click');
        const afterClick = {{ menu: menu() && menu().name, pressed: hand().cards[1].pressed }};
        dismissTopMenu();
        fire(btn(0), 'pointerdown', {{ pointerType: 'touch', clientX: 10, clientY: 10 }});
        fire(btn(0), 'pointermove', {{ clientX: 10, clientY: 40 }});
        await wait(H.LONG_PRESS_MS + 60);
        const scrolled = menu();
        fire(btn(0), 'pointerdown', {{ pointerType: 'mouse', clientX: 10, clientY: 10 }});
        await wait(H.LONG_PRESS_MS + 60);
        const mouse = menu();
        fire(btn(0), 'pointerup'); fire(btn(0), 'click');
        say({{ opened, afterClick, scrolled, mouse, tap: hand().cards.map((c) => c.pressed) }});
    """)
    assert out["opened"] == "notes.md", "a long press on a phone opens nothing"
    assert out["afterClick"] == {"menu": "notes.md", "pressed": "true"}, (
        "lifting the finger counted as a tap: it closed the menu or let the card go"
    )
    assert out["scrolled"] is None, "a finger that moved (a scroll) opened the menu"
    assert out["mouse"] is None, "a mouse held down opened the menu — that is right-click's job"
    assert out["tap"] == ["true", "false"], "a tap after a long press was swallowed"


# ── acting ──────────────────────────────────────────────────────────────────

@needs_node
def test_remove_by_x_by_delete_and_from_the_menu_and_the_focus_lands_somewhere(sandbox):
    out = _drive(sandbox, f"""
        await add({CAT}, {NOTES}, {PIER}, aFile('deck.pdf', 'application/pdf'));
        const x = card(0).querySelector('.hand-card-x');
        fire(x, 'click');
        const afterX = hand().cards.map((c) => c.label);
        keyboardFocus(btn(1));
        const del = fire(btn(1), 'keydown', {{ key: 'Delete' }});
        const afterDelete = {{ cards: hand().cards.map((c) => c.label), active: active(), prevented: del.defaultPrevented }};
        keyboardFocus(btn(0));
        fire(btn(0), 'keydown', {{ key: 'ContextMenu' }});
        await tick();
        const item = menu().node.childNodes.find((b) => b.dataset.action === 'remove');
        fire(item, 'click', {{ detail: 0 }});
        const afterMenu = {{ cards: hand().cards.map((c) => c.label), active: active(), menu: menu() }};
        keyboardFocus(btn(0));
        fire(btn(0), 'keydown', {{ key: 'Backspace' }});
        say({{ afterX, afterDelete, afterMenu, last: active(), pending: fh.getPendingCount(),
              stack: _openMenuCount() }});
    """)
    assert out["afterX"] == ["notes.md, 1 of 3", "pier.png, 2 of 3", "deck.pdf, 3 of 3"]
    assert out["afterDelete"]["prevented"], "Backspace/Delete would also reach the page"
    assert out["afterDelete"]["cards"] == ["notes.md, 1 of 2", "deck.pdf, 2 of 2"]
    assert out["afterDelete"]["active"] == "deck.pdf, 2 of 2", (
        "the focus went with the removed card — the next card should have it"
    )
    assert out["afterMenu"]["cards"] == ["deck.pdf, 1 of 1"] and out["afterMenu"]["menu"] is None
    assert out["afterMenu"]["active"] == "deck.pdf, 1 of 1"
    assert out["last"] == "message", "the last card removed left the focus nowhere"
    assert out["pending"] == 0 and out["stack"] == 0


@needs_node
def test_remove_all_and_a_menu_never_outlives_its_file(sandbox):
    out = _drive(sandbox, f"""
        await add({CAT}, {NOTES}, {PIER});
        fire(btn(2), 'contextmenu');
        const item = menu().node.childNodes.find((b) => b.dataset.action === 'remove-all');
        fire(item, 'click');
        const all = {{ pending: fh.getPendingCount(), cards: hand().cards.length, menu: menu() }};
        await add({CAT});
        fire(btn(0), 'contextmenu');
        const before = _openMenuCount();
        fh.clearPending();
        say({{ all, before, menuAfter: menu(), stack: _openMenuCount(), state: H.handState() }});
    """)
    assert out["all"] == {"pending": 0, "cards": 0, "menu": None}
    assert out["before"] == 1
    assert out["menuAfter"] is None and out["stack"] == 0, (
        "the files went (a send, a clear) and their menu stayed open on the Escape stack"
    )
    assert out["state"]["selected"] == -1


@needs_node
def test_preview_shows_it_large_on_the_escape_stack_and_gives_the_focus_back(sandbox):
    out = _drive(sandbox, f"""
        await add({CAT}, aFile('notes.md', 'text/markdown', '# Launch notes\\n- ship it'));
        keyboardFocus(btn(0));
        fire(btn(0), 'keydown', {{ key: 'ContextMenu' }});
        await tick();
        fire(menu().node.childNodes.find((b) => b.dataset.action === 'preview'), 'click', {{ detail: 0 }});
        const p = preview();
        const img = p && p.querySelector('.hand-preview-img');
        const image = {{ role: p && p.getAttribute('role'), modal: p && p.getAttribute('aria-modal'),
                        name: p && p.getAttribute('aria-label'), src: img && img.src,
                        active: active(), stack: _openMenuCount() }};
        dismissTopMenu();
        const back = {{ gone: !preview(), active: active() }};
        fire(btn(1), 'dblclick');
        await tick(6);
        const doc = preview();
        const text = doc.querySelector('.hand-preview-text');
        const meta = doc.querySelector('.hand-preview-meta');
        const read = {{ text: text && text.textContent, meta: meta && meta.textContent }};
        fire(doc.querySelector('.hand-preview-close'), 'click');
        say({{ image, back, read, closed: !preview(), stack: _openMenuCount() }});
    """)
    img = out["image"]
    assert img["role"] == "dialog" and img["modal"] == "true" and img["name"] == "cat.jpg"
    assert img["src"] == "blob:cat.jpg", "Preview did not show the picture"
    assert img["active"] == "Close", "the focus stayed behind the preview"
    assert img["stack"] == 1, "the preview is not on the Escape stack"
    assert out["back"] == {"gone": True, "active": "cat.jpg, 1 of 2"}, out["back"]
    assert out["read"]["text"] == "# Launch notes\n- ship it", "a text file's preview does not show its text"
    assert out["read"]["meta"].startswith("Text"), out["read"]["meta"]
    assert out["closed"] and out["stack"] == 0


@needs_node
def test_save_to_gallery_uses_the_gallerys_own_route_and_says_what_happened(sandbox):
    out = _drive(sandbox, f"""
        await add({PIER});
        const save = async () => {{
          fire(btn(0), 'contextmenu');
          fire(menu().node.childNodes.find((b) => b.dataset.action === 'gallery'), 'click');
          await tick(6);
        }};
        answer(200, {{ ok: true, id: 'g1' }}); await save();
        answer(200, {{ ok: false, duplicate: true }}); await save();
        answer(403, {{ detail: 'Gallery is switched off for everyone.' }}); await save();
        say({{ posted: posted.filter((p) => p.url.includes('gallery')), toasts, errors,
              still: fh.getPendingCount() }});
    """)
    assert out["posted"] == [
        {"url": "/api/gallery/upload", "method": "POST", "form": ["pier.png"]}] * 3, out["posted"]
    assert out["toasts"] == ["Saved to the Gallery.", "Already in the Gallery."]
    assert out["errors"] == ["Gallery is switched off for everyone."], (
        "a refusal must be the server's sentence (`readRefusal`, C-ERR)"
    )
    assert out["still"] == 1, "saving to the Gallery took the file out of the message"


@needs_node
def test_the_send_still_dims_and_spins_every_card(sandbox):
    out = _drive(sandbox, f"""
        await add({CAT}, {NOTES});
        fh.uploadPending({{ sessionId: 'chat-a' }});
        await tick();
        say({{ spinning: hand().cards.map((c) => c.spinner), uploading: strip.className.includes('attach-uploading'),
              posted: posted.filter((p) => p.url.endsWith('/api/upload')) }});
    """)
    assert out["uploading"], out
    assert out["spinning"] == [True, True], (
        "the cards lost the upload's whirlpool — a file being sent looks stuck"
    )
    assert out["posted"][0]["form"] == ["cat.jpg", "notes.md"]


@needs_node
def test_the_hand_follows_the_chat_and_a_selection_does_not(sandbox):
    out = _drive(sandbox, f"""
        await add({CAT}, {NOTES});
        fire(btn(1), 'click');
        _chat = 'chat-b'; fh.syncSession();
        const inB = hand();
        await add({PIER});
        const inB2 = hand().cards.map((c) => c.label);
        _chat = 'chat-a'; fh.syncSession();
        const backInA = hand();
        say({{ inB: inB.cards.length, inB2, backInA: backInA.cards.map((c) => [c.label, c.pressed]) }});
    """)
    assert out["inB"] == 0, "chat A's cards are in chat B's hand (`B893`)"
    assert out["inB2"] == ["pier.png, 1 of 1"]
    assert out["backInA"] == [["cat.jpg, 1 of 2", "false"], ["notes.md, 2 of 2", "false"]], (
        "chat A's cards did not come back, or came back still selected from before the switch"
    )


# ── the drop ────────────────────────────────────────────────────────────────

_DROP = r"""
const strip = { listeners: {}, style: {}, addEventListener(t, f) { (this.listeners[t] ||= []).push(f); } };
const chatContainer = { listeners: {}, style: {}, addEventListener(t, f) { (this.listeners[t] ||= []).push(f); } };
const added = [];
const toasts = [];
let hidden = 0;
const fileHandlerModule = { addFiles: async (fs) => { added.push(fs.map((f) => f.name)); } };
const uiModule = { showToast: (m) => toasts.push(m) };
const _hideDropHighlight = () => { hidden += 1; };
new Function('attachStrip', 'chatContainer', 'fileHandlerModule', 'uiModule', '_hideDropHighlight',
  STRIP + ';\n' + CONTAINER + ';')(strip, chatContainer, fileHandlerModule, uiModule, _hideDropHighlight);
// A drop on a card: the card has no handler of its own, so the event reaches
// the strip and then, unless something stops it, the container it sits in.
let stopped = false;
const ev = { dataTransfer: { files: [{ name: 'brief.pdf' }] }, preventDefault() {},
             stopPropagation() { stopped = true; } };
for (const host of [strip, chatContainer]) {
  if (stopped) break;
  for (const f of host.listeners.drop || []) await f(ev);
}
console.log(JSON.stringify({ added, toasts, hidden }));
"""


@needs_node
def test_a_file_dropped_on_a_card_is_added_once(tmp_path):
    """The drag-and-drop path still feeds the hand, and once.

    `#attach-strip` sits inside `#chat-container`, and both answer a drop with
    `addFiles`; the strip's did not stop the event, so a file dropped on an
    attachment was added twice — driven in Chromium on `0345288` (a chip) and
    on the hand (a card) alike. Both real handlers, cut out of `app.js`."""
    src = APP_JS.read_text(encoding="utf-8")
    strip = js_definition(src, src.index("attachStrip.addEventListener('drop'"))
    container = js_definition(src, src.index("chatContainer.addEventListener('drop'"))
    script = tmp_path / "drop.mjs"
    script.write_text("const STRIP = %s;\nconst CONTAINER = %s;\n%s" % (
        json.dumps(strip), json.dumps(container), _DROP))
    proc = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["added"] == [["brief.pdf"]], f"one drop added {out['added']}"
    assert out["toasts"] == ["Added 1 file to chat"], out["toasts"]
    assert out["hidden"] == 1, "the container's drop highlight is left on"


# ── the stylesheet ──────────────────────────────────────────────────────────

_MARK = "`B-NEW-1` (fx5-cards) — the composer's attachments are a hand of cards."


def _section():
    """The hand's block of `static/style.css`, comments blanked, offsets kept."""
    raw = STYLE.read_text(encoding="utf-8")
    start = raw.index(_MARK)
    return blank(STYLE)[start:]


def _rules(css):
    """(selector, declarations, enclosing at-rule or '') for each innermost rule."""
    out = []
    for m in re.finditer(r"(@[^{};]+)\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}|([^{}@]+)\{([^{}]*)\}", css):
        if m.group(1):
            for r in re.finditer(r"([^{}]+)\{([^{}]*)\}", m.group(2)):
                out.append((" ".join(r.group(1).split()), r.group(2), " ".join(m.group(1).split())))
        else:
            out.append((" ".join(m.group(3).split()), m.group(4), ""))
    return out


def _decls(body):
    return {k.strip(): v.strip() for k, v in
            (d.split(":", 1) for d in body.split(";") if ":" in d)}


def _rule(selector, at=""):
    found = [_decls(b) for s, b, a in _rules(_section()) if s == selector and a == at]
    assert found, f"no `{selector}` rule{' in ' + at if at else ''} in the hand's block"
    merged = {}
    for d in found:
        merged.update(d)
    return merged


def test_the_extractor_reads_the_hands_block():
    """Every case below is vacuous against a parser that returns nothing."""
    rules = _rules(_section())
    assert len(rules) > 30, len(rules)
    assert any(a.startswith("@media (hover: hover)") for _, _, a in rules)
    assert any(a.startswith("@starting-style") for _, _, a in rules)


def test_the_strip_gives_the_chat_back_the_height_it_takes():
    """The defect itself: a negative top margin equal to the height, so the
    chat's column is as tall with attachments as without; transparent, and
    pointers pass through it to the chat except where a card is."""
    strip = _rule(".attach-strip.attach-hand")
    assert strip["height"] == "var(--hand-h)"
    assert strip["margin-top"] == "calc(-1 * var(--hand-h))", (
        "the strip takes its height out of the chat again"
    )
    assert strip["min-height"] == "0" and strip["padding"] == "0", (
        "`.attach-strip`'s own min-height/padding would add a band back"
    )
    assert strip["background"] == "transparent"
    assert strip["pointer-events"] == "none", "the empty part of the strip blocks the chat behind it"
    card = _rule(".attach-hand .hand-card")
    assert card["pointer-events"] == "auto" and card["position"] == "absolute"
    # Out-ranks `.attach-strip.attach-uploading .thumb { position: relative }`.
    sending = _rule(".attach-strip.attach-hand.attach-uploading .hand-card")
    assert sending["position"] == "absolute"


def test_a_card_lifts_with_a_transform_and_nothing_reflows():
    lifted = [(s, _decls(b), a) for s, b, a in _rules(_section()) if s.endswith(".hand-card-lift")
              and (":hover" in s or "focus-within" in s or "is-selected" in s)]
    assert len(lifted) >= 2, lifted
    for sel, decls, _ in lifted:
        assert set(decls) == {"transform"}, f"`{sel}` moves the card with {sorted(decls)}"
        assert "translateY(" in decls["transform"], sel
    hover = [a for s, _, a in _rules(_section()) if s == ".attach-hand .hand-card:hover > .hand-card-lift"]
    assert hover == ["@media (hover: hover)"], "a tapped card on a phone would stay up"


def test_the_hand_keeps_to_the_palette_and_the_global_focus_ring():
    css = _section()
    assert "--accent" not in css, "the hand reaches for the accent (`P1-01`)"
    assert ":focus-visible" not in css and not re.search(r"(?:^|[;{\s])outline\s*:", css), (
        "the hand paints a focus ring of its own; the global one is the ring"
    )
    tokens = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    palette = {"--bg", "--fg", "--panel", "--border", "--red"}
    own = {t for t in tokens if t.startswith("--hand-") or t in ("--slot", "--z")}
    assert tokens - own <= palette, f"colours outside the five: {sorted(tokens - own - palette)}"


def test_reduced_motion_deals_the_hand_without_the_slide():
    still = [s for s, b, a in _rules(_section())
             if a == "@media (prefers-reduced-motion: reduce)"
             and _decls(b).get("transition-duration") == "0.01ms"]
    assert any(".hand-card" in s for s in still), still
    dealt = _rule(".attach-hand .hand-card.hand-card-new", "@starting-style")
    assert dealt["translate"] == "0 28px" and dealt["opacity"] == "0"
    # The starting style is overridden by order, so the reduced rule must come
    # after it in the sheet and carry the same weight.
    landed = _rule(".attach-hand .hand-card.hand-card-new", "@media (prefers-reduced-motion: reduce)")
    assert landed == {"translate": "none", "opacity": "1"}, (
        "under reduced motion a new card still starts 28px low and invisible"
    )
    order = [a for s, _, a in _rules(_section()) if s == ".attach-hand .hand-card.hand-card-new"]
    assert order == ["@starting-style", "@media (prefers-reduced-motion: reduce)"], order
