# SPDX-License-Identifier: AGPL-3.0-or-later
"""`D-2026-10-09-01` §4 — on a phone, everything that decides what a turn does.

The owner, 2026-10-09: *"on mobile there's no way to change between agent and
chat mode. (Screenshot attached) - need more controls for the mobile side."*

**What was wrong, measured in Chromium with touch emulation on `a5ee5f8`.**
`.chat-input-bar` is `container-type: inline-size` and its container query drops
`.mode-toggle` below a 340 px bar. A 360×800 phone makes that bar **exactly
340 px**, so the toggle resolved to `display: none` and the composer row held
`^`, Plan, Web, Shell and send — the owner's screenshot. Nothing replaced it:
the `^` menu is *Attach files / Documents / RAG / Workspace / Prompt*, the
slash catalogue's `/toggle` offered web, bash, rag, research, doc and sidebar
and no mode, and no palette row names it. So the mode could not be reached at
all. At 390×844 the bar is 370 px: the toggle was on screen at **34 px** tall
and the model picker at **22 px**, both under the 44 px a thumb needs, and the
context wheel was `hidden` until a turn had run.

What is pinned here, by driving the code:

  * **the control is replaced, not merely dropped** — the same container query
    that hides the segmented toggle shows `#turn-chip`, and the chip SAYS the
    mode with nothing opened, so a person can see they are in Agent mode at a
    glance;
  * **one sheet holds the turn** — mode, the chat's approval mode
    (`D-2026-10-09-01` §2, the slot the sibling lane fills), model, the context
    reading, Plan, Web, Shell and the persona, each row with its current value;
  * **it keeps no state of its own** (`Law 7`): every row reads the composer's
    own controls and every change clicks them, so a change made anywhere else
    shows here and the mutual exclusions written once still run;
  * **a reading nobody has taken says so** rather than reading 0% (`Law 10`),
    and a control the page is not showing is not drawn;
  * **one back stack**: opening registers one `escMenuStack` entry, and
    `dismissTopMenu()` — what Escape and the phone's Back both call
    (`backStack.onPopState`) — closes exactly it;
  * **a thumb's target**: the chip and every row are at least 44 px, the typing
    area is not made smaller, and the new rules add no `var(--accent)`, no ring
    of their own and no motion under `prefers-reduced-motion`;
  * **a typed path too**: `/toggle mode` reaches the same buttons.

Mutation evidence is recorded in `/work/notes/fx8-mobile.md`.
"""

import json
import re
import shutil
import subprocess
import textwrap
from html.parser import HTMLParser
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.js_source import js_function
from tests.helpers.source_text import blank

ROOT = Path(__file__).resolve().parents[1]
TURN_SHEET = ROOT / "static" / "js" / "turnSheet.js"
SLASH = ROOT / "static" / "js" / "slashCommands.js"
INDEX = ROOT / "static" / "index.html"
STYLE = ROOT / "static" / "style.css"
CSS = blank(STYLE)

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the stylesheet, resolved rule by rule ───────────────────────────────────
# A stylesheet cannot be driven under node, so this follows `Law 20`'s second
# option in the shape `tests/test_one_focus_ring_css.py` set for this file:
# find the rule first, then assert inside it.

def _rules(css: str):
    """`(selector, body)` for every rule, at-rules walked into."""
    out, i, n = [], 0, len(css)
    while i < n:
        brace = css.find("{", i)
        if brace < 0:
            break
        selector = css[i:brace].strip()
        depth, j = 1, brace + 1
        while j < n and depth:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        body = css[brace + 1:j - 1]
        if selector.startswith("@") and "{" in body:
            out.extend((f"{selector} {{ {sel}", sub) for sel, sub in _rules(body))
        else:
            out.append((selector, body))
        i = j
    return out


ALL_RULES = _rules(CSS)


def _decl(body: str, prop: str):
    m = re.search(rf"(?:^|[{{;])\s*{re.escape(prop)}\s*:\s*([^;}}]+)", body, re.M)
    return m.group(1).strip() if m else None


def _rules_for(selector_fragment: str, at: str = ""):
    return [(sel, body) for sel, body in ALL_RULES
            if selector_fragment in sel and at in sel]


def _phone_start():
    text = STYLE.read_text(encoding="utf-8")
    return text, text.index("`D-2026-10-09-01` §4 — the phone's turn controls")


def _phone_block():
    """The one appended block this row wrote, by its marker — comments and all."""
    text, start = _phone_start()
    return text[start:]


def _phone_code():
    """The same block with its comments blanked (`B290`), offsets preserved, so
    a word the comment uses to say it is NOT reached for cannot pass for a
    declaration that reaches for it."""
    _text, start = _phone_start()
    return CSS[start:]


def test_the_query_that_drops_the_toggle_shows_the_chip_in_its_place():
    """The hole the owner fell into: a control removed with nothing in its
    place. Resolved from the one container query that removes it."""
    dropping = [(sel, body) for sel, body in ALL_RULES
                if ".mode-toggle" in sel and "chatbar" in sel
                and _decl(body, "display") == "none !important"]
    assert len(dropping) == 1, f"expected one query to drop the toggle, found {dropping}"
    sel = dropping[0][0]
    width = int(re.search(r"max-width:\s*(\d+)px", sel).group(1))
    # 390×844 makes a 370px bar and 360×800 makes a 340px one (both measured
    # 2026-10-09), so a threshold that only answers the narrower phone leaves
    # the wider one with a 34px toggle.
    assert width >= 370, (
        f"the toggle is replaced only below {width}px, so a 390px phone's "
        "370px bar keeps the 34px segmented control")
    showing = [body for s, body in ALL_RULES
               if ".turn-chip" in s and f"max-width: {width}px" in s]
    assert showing, "the query that drops the toggle does not show the chip"
    assert any(_decl(b, "display") not in (None, "none") for b in showing), (
        "the chip is not given a display in the query that drops the toggle")


def test_the_chip_is_hidden_wherever_the_toggle_is_not():
    base = [body for sel, body in ALL_RULES
            if sel.strip() == ".turn-chip" and "@" not in sel]
    assert base, ".turn-chip has no unconditional rule"
    assert _decl(base[0], "display") == "none", (
        "the chip must be off until the bar is narrow, or the desktop grows a "
        "second mode control")


@pytest.mark.parametrize("selector,prop", [
    (".turn-chip", "min-height"),
    (".turn-row", "min-height"),
    (".turn-sheet-close", "min-height"),
])
def test_what_a_thumb_presses_is_at_least_forty_four_pixels(selector, prop):
    rules = [body for sel, body in ALL_RULES if sel.strip() == selector]
    assert rules, f"{selector} has no rule"
    value = _decl(rules[0], prop)
    assert value and int(re.match(r"(\d+)", value).group(1)) >= 44, (
        f"{selector} is {value}, under the 44px a thumb needs")


def test_the_segmented_control_in_a_row_is_grown_rather_than_redrawn():
    """`Law 7` / `Law 14`: the sheet's Agent/Chat control is the composer's own
    `.mode-toggle`, given a thumb's height — not a second look."""
    rules = [body for sel, body in ALL_RULES if ".turn-seg .mode-toggle-btn" in sel]
    assert rules, "the sheet draws its own segmented button instead of reusing one"
    assert int(re.match(r"(\d+)", _decl(rules[0], "min-height")).group(1)) >= 44


def test_the_typing_area_is_not_made_smaller_to_fit_any_of_this():
    block = _phone_code()
    for victim in ("#message", ".chat-input-top", "textarea"):
        assert victim not in block, (
            f"the phone block touches {victim}; the row was to take room from "
            "chrome, never from the typing area")


def test_the_new_rules_carry_no_accent_and_no_ring_of_their_own():
    """The palettes are protected (`D-2026-09-14-03`) and there is one focus
    ring (`P10-01`): this block may not define either."""
    block = _phone_code()
    assert "--accent" not in block, "the phone block reaches for the accent"
    assert not re.search(r"(?:^|[{;])\s*outline\s*:", block, re.M), (
        "the phone block writes an outline; the global `:focus-visible` ring "
        "is the one ring")
    assert ":focus-visible" not in block, (
        "a focus rule of its own — the census in test_one_focus_ring_css.py "
        "pins the count")


def test_reduced_motion_stops_the_rise_and_the_switches():
    block = _phone_code()
    start = block.index("@media (prefers-reduced-motion: reduce)")
    reduced = block[start:]
    for name in (".turn-sheet", ".turn-switch"):
        assert name in reduced, f"{name} still moves under reduced motion"
    assert "0.01ms" in reduced, (
        "`P1-12`: 0.01ms, not `none` — a transition that never runs never "
        "sends `transitionend`")


# ── the module, driven ──────────────────────────────────────────────────────

class _Outer(HTMLParser):
    """The outer HTML of one element, by id, from the shipped page."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "source", "track", "wbr", "path", "circle", "line", "polyline",
            "rect", "ellipse", "polygon"}

    def __init__(self, wanted):
        super().__init__(convert_charrefs=False)
        self.wanted, self.depth, self.parts, self.done = wanted, 0, [], False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if not self.depth and d.get("id") == self.wanted:
            self.depth = 1
            self.parts.append(self.get_starttag_text())
            return
        if self.depth and not self.done:
            self.parts.append(self.get_starttag_text())
            if tag not in self.VOID and not self.get_starttag_text().endswith("/>"):
                self.depth += 1

    def handle_startendtag(self, tag, attrs):
        if self.depth and not self.done:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if not self.depth or self.done:
            return
        self.parts.append(f"</{tag}>")
        self.depth -= 1
        if not self.depth:
            self.done = True

    def handle_data(self, data):
        if self.depth and not self.done:
            self.parts.append(data)

    def handle_entityref(self, name):
        if self.depth and not self.done:
            self.parts.append(f"&{name};")


def _outer(element_id: str) -> str:
    p = _Outer(element_id)
    p.feed(INDEX.read_text(encoding="utf-8"))
    assert p.done, f"#{element_id} not found whole in static/index.html"
    return "".join(p.parts)


def _page_markup() -> str:
    """The shipped composer controls the sheet drives, plus the sheet itself.

    Read out of `static/index.html` rather than written here, so a row renamed
    on the page fails this file instead of passing against a copy.
    """
    sheet = _outer("turn-sheet-layer")
    chip = _outer("turn-chip")
    parts = [chip, sheet]
    # The composer's own controls. Their ids are the contract this module
    # drives; taking them from the page keeps the two in step.
    for cid in ("mode-agent-btn", "mode-chat-btn", "plan-toggle-btn", "web-toggle-btn",
                "bash-toggle-btn", "character-indicator-btn", "model-picker-wrap",
                "agent-limits-hint", "overflow-preset-btn"):
        parts.append(_outer(cid))
    parts.append('<span id="chat-context-pill" hidden>'
                 '<span id="chat-context-pill-label">0%</span></span>')
    return "".join(parts)


_SHIM = """
import { installDom, installHtmlParsing } from './dom.js';
export const document = installDom();
installHtmlParsing();
export function seed(markup) {
  document.body.innerHTML = markup;
  // The page's own starting state: Agent is the active mode, Shell is hidden
  // in Chat mode, the persona chip and the context wheel are not shown yet.
  const agent = document.getElementById('mode-agent-btn');
  agent.classList.add('active');
  document.getElementById('character-indicator-btn').style.display = 'none';
  document.getElementById('chat-context-pill').hidden = true;
  const hint = document.getElementById('agent-limits-hint');
  hint.hidden = true;
  return document;
}
/** A browser's click, as far as this file needs one: the capture-phase
 *  listeners on `document` run BEFORE the control's own handler. The shim
 *  dispatches to one node and stops, so without this the sheet's
 *  outside-click guard could not be driven at all. */
function browserish(node) {
  node.click = () => {
    const ev = new Event('click');
    ev.target = node;
    document.dispatchEvent(ev);
    node.dispatchEvent(ev);
  };
  return node;
}

/** Wire the composer's real behaviour, in miniature: the two mode buttons and
 *  the three tool chips each own their `.active`, as `app.js` does. */
export function wireComposer(calls) {
  const agent = document.getElementById('mode-agent-btn');
  const chat = document.getElementById('mode-chat-btn');
  const setMode = (m) => {
    calls.push('mode:' + m);
    agent.classList.toggle('active', m === 'agent');
    chat.classList.toggle('active', m === 'chat');
    agent.setAttribute('aria-pressed', String(m === 'agent'));
    chat.setAttribute('aria-pressed', String(m === 'chat'));
    document.getElementById('bash-toggle-btn').style.display = m === 'chat' ? 'none' : '';
  };
  browserish(agent).addEventListener('click', () => setMode('agent'));
  browserish(chat).addEventListener('click', () => setMode('chat'));
  for (const id of ['plan-toggle-btn', 'web-toggle-btn', 'bash-toggle-btn']) {
    const b = browserish(document.getElementById(id));
    b.addEventListener('click', () => {
      calls.push('tool:' + id);
      b.classList.toggle('active', !b.classList.contains('active'));
    });
  }
  for (const id of ['model-picker-btn', 'chat-context-pill', 'overflow-preset-btn']) {
    const b = document.getElementById(id);
    if (b) browserish(b).addEventListener('click', () => calls.push('open:' + id));
  }
  setMode('agent');
  calls.length = 0;
  return calls;
}
export function say(value) { console.log(JSON.stringify(value)); }
export const tick = () => new Promise((r) => setTimeout(r, 0));
"""

_PREAMBLE = (
    "import { document, seed, wireComposer, say, tick } from './shim.js';\n"
    "const sheet = await import('./turnSheet.js');\n"
    "const stack = await import('./escMenuStack.js');\n"
    "const MARKUP = " + json.dumps("__MARKUP__") + ";\n"
    "const calls = [];\n"
    "seed(MARKUP); wireComposer(calls);\n"
    "const el = (id) => document.getElementById(id);\n"
    "const tap = (id) => { const n = el(id); const ev = new Event('click');\n"
    "  ev.target = n; document.dispatchEvent(ev); n.dispatchEvent(ev); };\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("turnsheet"), TURN_SHEET, _SHIM, {})


@pytest.fixture(scope="module")
def preamble():
    return _PREAMBLE.replace(json.dumps("__MARKUP__"), json.dumps(_page_markup()))


def _case(sandbox, preamble, script):
    return _run(sandbox, preamble, script)


def test_the_chip_says_the_mode_before_anything_is_opened(sandbox, preamble):
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      const first = {text: el('turn-chip-mode').textContent,
                     label: el('turn-chip').getAttribute('aria-label'),
                     open: sheet.isOpen(document)};
      tap('mode-chat-btn');
      say({first, after: {text: el('turn-chip-mode').textContent,
                          label: el('turn-chip').getAttribute('aria-label')}});
    """)
    assert out["first"] == {"text": "Agent", "label": "This turn: Agent mode", "open": False}
    # A mode change made anywhere else reaches the chip: the state is the
    # page's, not a copy the sheet keeps.
    assert out["after"] == {"text": "Chat", "label": "This turn: Chat mode"}


def test_the_chip_opens_the_sheet_and_one_escape_stack_entry(sandbox, preamble):
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      tap('turn-chip');
      const opened = {open: sheet.isOpen(document), menus: stack._openMenuCount(),
                      expanded: el('turn-chip').getAttribute('aria-expanded')};
      // What Escape and the phone's Back both call (`backStack.onPopState`).
      const peeled = stack.dismissTopMenu();
      say({opened, peeled, closed: !sheet.isOpen(document),
           menus: stack._openMenuCount(),
           expanded: el('turn-chip').getAttribute('aria-expanded')});
    """)
    assert out["opened"] == {"open": True, "menus": 1, "expanded": "true"}
    assert out["peeled"] is True and out["closed"] is True
    assert out["menus"] == 0, "the Escape stack still holds the sheet after Back"
    assert out["expanded"] == "false"


def test_a_click_the_sheet_makes_itself_is_not_an_outside_click(sandbox, preamble):
    """The rows drive the composer's buttons, which sit outside the sheet, and
    the dismissal wrapper listens on `document` in the capture phase. Without
    the guard the first row tapped shut the sheet under the thumb."""
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      tap('turn-chip');
      await tick();
      tap('turn-mode-chat');
      const afterRow = sheet.isOpen(document);
      // A real tap landing outside still closes it.
      const ev = new Event('click'); ev.target = el('mode-agent-btn');
      document.dispatchEvent(ev);
      say({afterRow, afterOutside: sheet.isOpen(document)});
    """)
    assert out["afterRow"] is True, "a row of the sheet closed the sheet"
    assert out["afterOutside"] is False, "a tap outside no longer closes the sheet"


def test_pressing_the_chip_again_closes_the_sheet(sandbox, preamble):
    """The outside-click listener is in the capture phase, so the chip has to
    count as inside: otherwise it closed the sheet and the chip's own handler
    opened it straight back, and the sheet could never be put away from the
    control that opened it."""
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      tap('turn-chip');
      const first = sheet.isOpen(document);
      await tick();   // the outside-click listener is attached a tick later
      tap('turn-chip');
      say({first, second: sheet.isOpen(document),
           menus: stack._openMenuCount(),
           expanded: el('turn-chip').getAttribute('aria-expanded')});
    """)
    assert out == {"first": True, "second": False, "menus": 0, "expanded": "false"}


def test_the_mode_row_drives_the_composers_own_buttons(sandbox, preamble):
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      tap('turn-chip');
      const seen = [];
      tap('turn-mode-chat');
      seen.push({calls: calls.slice(), chip: el('turn-chip-mode').textContent,
                 agent: el('turn-mode-agent').getAttribute('aria-checked'),
                 chat: el('turn-mode-chat').getAttribute('aria-checked'),
                 composer: el('mode-chat-btn').classList.contains('active')});
      calls.length = 0;
      tap('turn-mode-agent');
      seen.push({calls: calls.slice(), chip: el('turn-chip-mode').textContent,
                 agent: el('turn-mode-agent').getAttribute('aria-checked'),
                 chat: el('turn-mode-chat').getAttribute('aria-checked'),
                 composer: el('mode-agent-btn').classList.contains('active')});
      say(seen);
    """)
    assert out[0] == {"calls": ["mode:chat"], "chip": "Chat", "agent": "false",
                      "chat": "true", "composer": True}
    assert out[1] == {"calls": ["mode:agent"], "chip": "Agent", "agent": "true",
                      "chat": "false", "composer": True}


def test_the_tool_rows_flip_the_composers_own_chips(sandbox, preamble):
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      tap('turn-chip');
      tap('turn-row-plan'); tap('turn-row-web');
      say({calls: calls.slice(),
           plan: {row: el('turn-row-plan').getAttribute('aria-checked'),
                  chip: el('plan-toggle-btn').classList.contains('active')},
           web: {row: el('turn-row-web').getAttribute('aria-checked'),
                 chip: el('web-toggle-btn').classList.contains('active')}});
    """)
    assert out["calls"] == ["tool:plan-toggle-btn", "tool:web-toggle-btn"]
    assert out["plan"] == {"row": "true", "chip": True}
    assert out["web"] == {"row": "true", "chip": True}


def test_a_control_the_page_is_not_showing_is_not_drawn(sandbox, preamble):
    """Shell is hidden in Chat mode (`applyModeToToggles`), so its row goes
    with it rather than offering a switch that does nothing."""
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      tap('turn-chip');
      tap('turn-mode-chat');
      const inChat = {hidden: el('turn-row-shell').hidden,
                      flipped: sheet.flipSwitch(document, 'turn-row-shell'),
                      calls: calls.slice()};
      calls.length = 0;
      tap('turn-mode-agent');
      say({inChat, inAgent: {hidden: el('turn-row-shell').hidden,
                             flipped: sheet.flipSwitch(document, 'turn-row-shell')}});
    """)
    assert out["inChat"]["hidden"] is True
    assert out["inChat"]["flipped"] is False, "a hidden control was flipped anyway"
    assert out["inChat"]["calls"] == ["mode:chat"], "Shell was clicked while hidden"
    assert out["inAgent"] == {"hidden": False, "flipped": True}


def test_a_reading_nobody_has_taken_says_so(sandbox, preamble):
    """`Law 10`. The context wheel is `hidden` until a turn has run; 0% there
    would read as "costs nothing"."""
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      const before = {value: el('turn-value-context').textContent,
                      disabled: !!el('turn-row-context').disabled};
      el('chat-context-pill').hidden = false;
      el('chat-context-pill-label').textContent = '44%';
      sheet.paint(document);
      say({before, after: {value: el('turn-value-context').textContent,
                           disabled: !!el('turn-row-context').disabled}});
    """)
    assert out["before"] == {"value": "Not measured yet", "disabled": True}
    assert out["after"] == {"value": "44%", "disabled": False}


def test_each_row_carries_the_value_the_page_holds(sandbox, preamble):
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      el('model-picker-label').textContent = 'scripted-demo';
      el('character-indicator-btn').style.display = '';
      el('character-indicator-name').textContent = 'Hermes';
      sheet.paint(document);
      say({model: el('turn-value-model').textContent,
           persona: el('turn-value-persona').textContent,
           read: sheet.readTurn(document)});
    """)
    assert out["model"] == "scripted-demo"
    assert out["persona"] == "Hermes"
    assert out["read"]["mode"] == "agent"
    assert out["read"]["persona"] == "Hermes"


def test_the_mode_row_mirrors_the_sentence_the_desktop_shows(sandbox, preamble):
    """`P7-10`'s limits sentence is dropped below a 660px bar. The row reads it
    off that element rather than writing it a second time (`Law 7`)."""
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      const silent = {hidden: el('turn-mode-help').hidden,
                      text: el('turn-mode-help').textContent};
      el('agent-limits-hint').hidden = false;
      el('agent-limits-hint').textContent = 'Up to 20 steps';
      sheet.paint(document);
      const said = {hidden: el('turn-mode-help').hidden,
                    text: el('turn-mode-help').textContent};
      tap('turn-mode-chat');
      say({silent, said, inChat: {hidden: el('turn-mode-help').hidden}});
    """)
    assert out["silent"] == {"hidden": True, "text": ""}
    assert out["said"] == {"hidden": False, "text": "Up to 20 steps"}
    assert out["inChat"]["hidden"] is True, "a sentence about Agent mode shown in Chat"


def test_a_row_that_opens_something_hands_off_and_closes_first(sandbox, preamble):
    """The model picker and the context breakdown already exist; the sheet
    opens theirs rather than drawing a second one. The click waits a tick — the
    tap that reached the row is still propagating, and these menus close
    themselves on a document click outside them."""
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      tap('turn-chip');
      tap('turn-row-model');
      const sameTick = {open: sheet.isOpen(document), calls: calls.slice()};
      await tick();
      say({sameTick, afterTick: calls.slice()});
    """)
    assert out["sameTick"] == {"open": False, "calls": []}
    assert out["afterTick"] == ["open:model-picker-btn"]


def test_the_approval_slot_stays_shut_until_its_control_exists(sandbox, preamble):
    """`D-2026-10-09-01` §2 is the sibling lane's. With no control on the page
    — and with one an admin has not granted, which is drawn `display: none` —
    this row shows nothing rather than inventing an approval state."""
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      const without = {hidden: el('turn-row-approval').hidden,
                       read: sheet.readTurn(document).approval,
                       set: sheet.setApproval(document, 'auto'),
                       flag: el('turn-chip-approval').hidden};
      // The chip exists but the person may not set it: `approvalMode.render`
      // draws `display: none` until an admin grants `can_auto_approve`.
      const chip = document.createElement('button');
      chip.id = 'approval-mode-btn';
      chip.setAttribute('aria-pressed', 'false');
      chip.style.display = 'none';
      document.body.appendChild(chip);
      sheet.paint(document);
      say({without, ungranted: {hidden: el('turn-row-approval').hidden,
                                read: sheet.readTurn(document).approval}});
    """)
    assert out["without"] == {"hidden": True, "read": None, "set": False, "flag": True}
    assert out["ungranted"] == {"hidden": True, "read": None}


def test_the_approval_row_presses_the_chats_own_control(sandbox, preamble):
    """The shape `fx8-approval` shipped: `#approval-mode-btn` plus
    `window.approvalModeModule`, whose own comment calls it *"the same door
    `fx8-mobile` drives"*. The row presses that chip — it never writes an
    approval state of its own — and the sheet gets out of the way, because
    turning Auto on asks one question first."""
    out = _case(sandbox, preamble, """
      let auto = false;
      const presses = [];
      const chip = document.createElement('button');
      chip.id = 'approval-mode-btn';
      chip.setAttribute('aria-pressed', 'false');
      chip.addEventListener('click', () => {
        presses.push('toggle');
        auto = !auto;
        chip.setAttribute('aria-pressed', auto ? 'true' : 'false');
        chip.classList.toggle('active', auto);
      });
      document.body.appendChild(chip);
      window.approvalModeModule = { isAuto: () => auto };
      sheet.initTurnSheet(document);
      const manualFirst = {hidden: el('turn-row-approval').hidden,
                           auto: el('turn-approval-auto').getAttribute('aria-checked'),
                           manual: el('turn-approval-manual').getAttribute('aria-checked'),
                           flag: el('turn-chip-approval').hidden,
                           label: el('turn-chip').getAttribute('aria-label')};
      tap('turn-chip');
      tap('turn-approval-auto');
      const sameTick = {presses: presses.slice(), open: sheet.isOpen(document)};
      await tick();
      const after = {presses: presses.slice(),
                     auto: el('turn-approval-auto').getAttribute('aria-checked'),
                     flag: el('turn-chip-approval').hidden,
                     label: el('turn-chip').getAttribute('aria-label')};
      // Pressing the mode it is already in asks the chip for nothing.
      tap('turn-chip');
      tap('turn-approval-auto');
      await tick();
      say({manualFirst, sameTick, after, idle: presses.slice()});
    """)
    assert out["manualFirst"] == {"hidden": False, "auto": "false", "manual": "true",
                                  "flag": True, "label": "This turn: Agent mode"}
    # The sheet is out of the way before the control is pressed.
    assert out["sameTick"] == {"presses": [], "open": False}
    # Auto is the state a person must not miss: it is on the chip, unopened.
    assert out["after"] == {"presses": ["toggle"], "auto": "true", "flag": False,
                            "label": "This turn: Agent mode, Auto approval"}
    assert out["idle"] == ["toggle"], "the row pressed the chip to set the mode it was in"


def test_every_control_that_decides_a_turn_has_a_row(sandbox, preamble):
    """The decision's list, against the sheet the page ships."""
    wanted = {"turn-row-mode", "turn-row-approval", "turn-row-model",
              "turn-row-context", "turn-row-plan", "turn-row-web",
              "turn-row-shell", "turn-row-persona"}
    markup = _outer("turn-sheet-layer")
    found = set(re.findall(r'id="(turn-row-[a-z]+)"', markup))
    assert wanted <= found, f"missing rows: {sorted(wanted - found)}"


def test_the_sheet_is_a_dialog_a_screen_reader_can_name(sandbox, preamble):
    out = _case(sandbox, preamble, """
      sheet.initTurnSheet(document);
      tap('turn-chip');
      const d = el('turn-sheet');
      say({role: d.getAttribute('role'),
           labelledby: d.getAttribute('aria-labelledby'),
           title: el('turn-sheet-title').textContent,
           chip: {haspopup: el('turn-chip').getAttribute('aria-haspopup'),
                  controls: el('turn-chip').getAttribute('aria-controls')},
           modeGroup: el('turn-mode-seg').getAttribute('role'),
           modeRadio: el('turn-mode-agent').getAttribute('role'),
           switchRole: el('turn-row-plan').getAttribute('role')});
    """)
    assert out["role"] == "dialog"
    assert out["labelledby"] == "turn-sheet-title" and out["title"] == "This turn"
    assert out["chip"] == {"haspopup": "dialog", "controls": "turn-sheet"}
    assert out["modeGroup"] == "radiogroup" and out["modeRadio"] == "radio"
    assert out["switchRole"] == "switch"


# ── the typed path ──────────────────────────────────────────────────────────

_SLASH_PREAMBLE = (
    "import { document, seed, wireComposer, say } from './shim.js';\n"
    "const MARKUP = " + json.dumps("__MARKUP__") + ";\n"
    "const calls = [];\n"
    "seed(MARKUP); wireComposer(calls);\n"
    "const said = [];\n"
    "function slashReply(t) { said.push(t); }\n"
    "__CMD__\n"
)


def _slash_source() -> str:
    body = js_function(SLASH.read_text(encoding="utf-8"),
                       "async function _cmdToggleMode")
    return "async function _cmdToggleMode(args) " + body


def test_the_slash_command_reaches_the_same_buttons(sandbox, preamble):
    preamble = (_SLASH_PREAMBLE
                .replace(json.dumps("__MARKUP__"), json.dumps(_page_markup()))
                .replace("__CMD__", _slash_source()))
    out = _run(sandbox, preamble, """
      const seen = [];
      await _cmdToggleMode([]);            // toggles away from Agent
      seen.push({calls: calls.slice(), said: said.slice()});
      calls.length = 0; said.length = 0;
      await _cmdToggleMode(['agent']);
      seen.push({calls: calls.slice(), said: said.slice()});
      calls.length = 0; said.length = 0;
      await _cmdToggleMode(['sideways']);  // not a mode
      seen.push({calls: calls.slice(), said: said.slice()});
      say(seen);
    """)
    assert out[0] == {"calls": ["mode:chat"], "said": ["Chat mode."]}
    assert out[1] == {"calls": ["mode:agent"], "said": ["Agent mode."]}
    assert out[2]["calls"] == [], "a word that is not a mode changed the mode"
    assert out[2]["said"] == ['Mode is agent or chat, not "sideways".']


def test_the_catalogue_offers_it_where_the_other_toggles_are():
    """It was the one turn control with no typed path: `/toggle` listed web,
    bash, rag, research, doc and sidebar and nothing for the mode."""
    source = SLASH.read_text(encoding="utf-8")
    start = source.index("const COMMANDS = {")
    toggle = source.index("  toggle: {", start)
    block = source[toggle:source.index("\n  },", toggle)]
    assert "'mode':" in block, "/toggle has no mode subcommand"
    assert "_cmdToggleMode" in block, "the mode subcommand is wired to something else"
