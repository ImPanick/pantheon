# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chat says it is on Auto, and switching chats does not carry it over.

`D-2026-10-09-01` §2, the browser half: *"While Auto is on the chat says so, in
a place the person cannot miss"*, and *"Turning it on is one deliberate act with
one plain sentence about what changes; it does not need a wall of warning, and
it must not be a silent toggle either."*

Every case drives the real `static/js/approvalMode.js` under node with the
shared DOM shim, against a recording `fetch` — so what is asserted is what the
module does to the real markup and sends to the real route, not a description of
it (`Law 20`).

**The adversary here is the chat you just left.** The server stores the mode per
chat, so a leak cannot come from there; it can come from a browser that draws
the chip from its own memory. Group B is that: a switch to another chat, a
switch to no chat, and an answer that arrives after the person has already moved
on.

**`B1706` changed the control these cases press.** The chip was an on/off
switch beside Plan / Web / Shell (`aria-pressed`, a click flipped the mode); it
is a chip naming the mode at the bottom right of the composer that opens a menu
of both, a check (`aria-checked`) on the current one — the owner's request for
a mode selector at the bottom of the composer. So the shim paints that markup,
a case that turned Auto on or off by clicking the chip now clicks the menu's
item for the mode, and `read()` reports the check rather than `aria-pressed`.
What each case asserts about the server, the warning and the badge is
unchanged. `tests/test_the_approval_mode_is_chosen_at_the_bottom_of_the_composer.py`
drives the menu itself in Chromium.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from src.approval_mode import (
    AUTO_NOT_ALLOWED_SENTENCE,
    AUTO_WARNING,
    KEEP_ASKING_LABEL,
    PROCEED_LABEL,
    SETTING_LABEL,
    chat_warning,
    mode_choices,
)
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.source_text import blank_text  # B290

ROOT = Path(__file__).resolve().parents[1]
APPROVAL_MODE = ROOT / "static" / "js" / "approvalMode.js"
INDEX = ROOT / "static" / "index.html"
STYLE = ROOT / "static" / "style.css"
SESSIONS = ROOT / "static" / "js" / "sessions.js"
APP = ROOT / "static" / "app.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();

/** The two surfaces, exactly as `static/index.html` ships them — `B1706`: the
 *  chip in its wrap, and the menu it opens, whose words are blank until the
 *  server's arrive. */
function el(tag, attrs, parent) {
  const n = new Node(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') n.className = v; else n.setAttribute(k, v);
  }
  if (parent) parent.appendChild(n);
  return n;
}
export function paint() {
  const wrap = el('div', { class: 'approval-mode-wrap', id: 'approval-mode-wrap' }, document.body);
  wrap.style.display = 'none';
  const chip = el('button', { class: 'input-icon-btn tool-chip approval-mode-chip', id: 'approval-mode-btn',
                              'aria-haspopup': 'menu', 'aria-expanded': 'false',
                              'aria-controls': 'approval-mode-options' }, wrap);
  chip.style.display = 'none';
  el('span', { class: 'approval-mode-chip-label', id: 'approval-mode-label' }, chip);
  const menu = el('div', { class: 'model-picker-menu approval-mode-menu hidden', id: 'approval-mode-menu' }, wrap);
  const list = el('div', { class: 'model-picker-list approval-mode-list' }, menu);
  el('div', { class: 'mp-section-label', id: 'approval-mode-menu-title' }, list);
  const options = el('div', { role: 'menu', id: 'approval-mode-options',
                              'aria-labelledby': 'approval-mode-menu-title' }, list);
  for (const mode of ['manual', 'auto']) {
    const item = el('div', { class: 'model-switch-item approval-mode-item', role: 'menuitemradio',
                             tabindex: '-1', 'aria-checked': 'false', 'data-approval-choice': mode }, options);
    const text = el('span', { class: 'approval-mode-item-text' }, item);
    el('span', { class: 'approval-mode-item-name' }, text);
    el('span', { class: 'approval-mode-item-desc' }, text);
  }

  const badge = new Node('button');
  badge.setAttribute('id', 'chat-auto-approve-badge');
  badge.className = 'chat-auto-approve-badge';
  badge.hidden = true;
  badge.textContent = 'Auto-approve';
  document.body.appendChild(badge);
  return { chip, badge, menu };
}

/** `B1706`. Press the menu's item for a mode — what a person's click does. */
export function choose(mode) {
  document.querySelector(`[data-approval-choice="${mode}"]`).dispatchEvent({ type: 'click' });
}

export function read() {
  const chip = document.getElementById('approval-mode-btn');
  const badge = document.getElementById('chat-auto-approve-badge');
  const items = document.querySelectorAll('.approval-mode-item');
  const checked = items.filter((i) => i.getAttribute('aria-checked') === 'true')
    .map((i) => i.getAttribute('data-approval-choice'));
  return {
    chipShown: chip.style.display !== 'none',
    chipActive: chip.classList.contains('active'),
    checked: checked.length === 1 ? checked[0] : checked,
    chipName: chip.getAttribute('aria-label'),
    chipLabel: document.getElementById('approval-mode-label').textContent,
    menuOpen: !document.getElementById('approval-mode-menu').classList.contains('hidden'),
    heading: document.getElementById('approval-mode-menu-title').textContent,
    items: items.map((i) => ({
      mode: i.getAttribute('data-approval-choice'),
      name: i.querySelector('.approval-mode-item-name').textContent,
      line: i.querySelector('.approval-mode-item-desc').textContent,
      shown: i.style.display !== 'none',
    })),
    badgeShown: !badge.hidden,
    badgeText: badge.textContent,
  };
}

/** A recording `fetch`: what the module asked for, and what it was told. */
export const sent = [];
export function serve(plan) {
  globalThis.fetch = async (url, opts) => {
    const method = (opts && opts.method) || 'GET';
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    sent.push({ url, method, body });
    const answer = plan(url, method, body);
    return {
      ok: answer.status < 400,
      status: answer.status,
      json: async () => answer.body,
    };
  };
}

export const said = { confirms: [], toasts: [] };
export function installUi({ answer = true } = {}) {
  globalThis.window.uiModule = {
    styledConfirm: async (message, opts) => {
      said.confirms.push({ message, opts: opts || {} });
      return answer;
    },
    showToast: (message) => { said.toasts.push(String(message)); },
  };
}
"""

_PREAMBLE = (
    "import { document, paint, read, serve, sent, installUi, said, choose } from './shim.js';\n"
    "const approvalMode = (await import('./approvalMode.js')).default;\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(
        tmp_path_factory.mktemp("approvalmode"), APPROVAL_MODE, _SHIM, {}
    )


def _case(sandbox, script: str) -> dict:
    return _run(sandbox, _PREAMBLE, script)


#: `B1703`. What `GET …/approval-mode` says about the warning, from the
#: server's own module — the browser shows these and holds no copy.
_WARNING_FIELDS = json.dumps({
    "warning": chat_warning()["text"], "warning_id": chat_warning()["id"],
    "proceed_label": PROCEED_LABEL, "keep_asking_label": KEEP_ASKING_LABEL,
})

#: `B1706`. What `GET …/approval-mode` says for the composer's mode menu —
#: the setting's name and each mode's words — from the server's own module.
_MENU_FIELDS = json.dumps({"setting_label": SETTING_LABEL, "modes": mode_choices()})

_SERVE_ALLOWED = """
    serve((url, method, body) => {
      if (method === 'GET') return { status: 200, body: { mode: 'manual', auto: false, may_set: true,
                                                          ...%s, ...%s } };
      return { status: 200, body: { mode: body.mode, auto: body.mode === 'auto' } };
    });
""" % (_WARNING_FIELDS, _MENU_FIELDS)

#: The same, for a chat already on Auto.
_SERVE_ON = """
    serve((url, method, body) => {
      if (method === 'GET') return { status: 200, body: { mode: 'auto', auto: true, may_set: true,
                                                          ...%s, ...%s } };
      return { status: 200, body: { mode: body.mode, auto: body.mode === 'auto' } };
    });
""" % (_WARNING_FIELDS, _MENU_FIELDS)


# ── A. the chat says so, and turning it on is one deliberate act ────────────


def test_a_chat_in_manual_approve_shows_no_banner(sandbox):
    """A chat that asks says nothing — there is nothing to say (Doc 2 § 5
    rule 2: do not describe what is on screen)."""
    out = _case(sandbox, """
        paint();
        %s
        await approvalMode.load('chat-a');
        console.log(JSON.stringify(read()));
    """ % _SERVE_ALLOWED)

    assert out["chipShown"] is True, "the switch is reachable"
    assert out["chipActive"] is False
    assert out["checked"] == "manual"   # `B1706`: was `aria-pressed="false"`
    assert out["badgeShown"] is False


def test_the_chip_names_the_mode_and_the_menu_says_the_servers_words(sandbox):
    """`B1706`. *"a compact chip naming the current mode"*, and a menu headed
    with the setting's name, listing both modes with one line each — every
    word the server's (`setting_label`, `modes`), none of them the page's."""
    out = _case(sandbox, """
        const { chip } = paint();
        %s
        approvalMode.init(() => 'chat-a');
        await approvalMode.load('chat-a');
        const closed = read();
        chip.dispatchEvent({ type: 'click' });
        console.log(JSON.stringify({ closed, open: read() }));
    """ % _SERVE_ALLOWED)

    manual, auto = mode_choices()
    assert out["closed"]["chipLabel"] == manual["short_label"] == "Manual"
    assert out["closed"]["chipName"] == f"{SETTING_LABEL}: {manual['label']}"
    assert out["closed"]["menuOpen"] is False
    opened = out["open"]
    assert opened["menuOpen"] is True, "the chip opens its menu"
    assert opened["heading"] == SETTING_LABEL
    assert opened["items"] == [
        {"mode": m["mode"], "name": m["label"], "line": m["description"], "shown": True}
        for m in (manual, auto)]
    assert opened["checked"] == "manual"


def test_a_server_that_sends_no_menu_words_gets_no_chip(sandbox):
    """`B1706`, `Law 15`. A menu of blank rows is a dead control, and the
    page will not write its own words in their place (`Law 7`)."""
    out = _case(sandbox, """
        paint();
        serve(() => ({ status: 200, body: { mode: 'manual', auto: false, may_set: true, ...%s } }));
        await approvalMode.load('chat-a');
        console.log(JSON.stringify(read()));
    """ % _WARNING_FIELDS)
    assert out["chipShown"] is False
    assert out["chipLabel"] == "" and {i["name"] for i in out["items"]} == {""}


def test_turning_auto_on_asks_once_and_sends_back_the_warning_accepted(sandbox):
    """*"one deliberate act"*, and *"it must not be a silent toggle either"*.
    One confirm, and its words are the server's own, read from `GET`, so the
    two cannot drift (`Law 7`).

    `B1703` / `D-2026-10-30-01` changed what the one act is: it was one
    sentence and *Turn on*; it is the warning that names the risk — what the
    agent reads can steer what it does next — accepted with *Proceed to
    auto-approve*, whose id goes back with the write for the server to record.
    Still short (Doc 2 § 5: not a wall)."""
    out = _case(sandbox, """
        paint();
        %s
        installUi({ answer: true });
        approvalMode.init(() => 'chat-a');
        await approvalMode.load('chat-a');
        choose('auto');   // `B1706`: the menu's item, not a chip that flips
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({
          ui: read(), confirms: said.confirms, toasts: said.toasts, sent,
        }));
    """ % _SERVE_ALLOWED)

    assert len(out["confirms"]) == 1, "asked once, not twice and not never"
    confirm = out["confirms"][0]
    assert confirm["message"] == AUTO_WARNING
    # A warning that names the risk, and not a wall of one.
    assert "can steer what it does next" in confirm["message"]
    assert len(confirm["message"]) < 400
    assert confirm["opts"]["confirmText"] == PROCEED_LABEL == "Proceed to auto-approve"
    assert confirm["opts"]["cancelText"] == KEEP_ASKING_LABEL == "Keep asking me"

    assert out["ui"]["chipActive"] is True
    assert out["ui"]["checked"] == "auto" and out["ui"]["chipLabel"] == "Auto"
    assert out["ui"]["badgeShown"] is True
    assert out["sent"][-1] == {
        "url": "/api/session/chat-a/approval-mode", "method": "POST",
        "body": {"mode": "auto", "accept_warning": chat_warning()["id"]},
    }


def test_saying_no_to_the_question_changes_nothing(sandbox):
    """A deliberate act is one a person can decline — and `B1706`, declining
    leaves the menu's check on Manual approve."""
    out = _case(sandbox, """
        paint();
        %s
        installUi({ answer: false });
        approvalMode.init(() => 'chat-a');
        await approvalMode.load('chat-a');
        choose('auto');
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ ui: read(), posts: sent.filter((s) => s.method === 'POST') }));
    """ % _SERVE_ALLOWED)

    assert out["posts"] == [], "nothing was asked of the server"
    assert out["ui"]["chipActive"] is False
    assert out["ui"]["checked"] == "manual" and out["ui"]["chipLabel"] == "Manual"
    assert out["ui"]["badgeShown"] is False


def test_turning_auto_off_is_one_click_with_no_question(sandbox):
    """Putting a gate back is never the move that needs confirming."""
    out = _case(sandbox, """
        paint();
        %s
        installUi({ answer: false });
        approvalMode.init(() => 'chat-a');
        await approvalMode.load('chat-a');
        const on = read();
        choose('manual');
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ on, off: read(), confirms: said.confirms, sent }));
    """ % _SERVE_ON)

    assert out["on"]["chipActive"] is True and out["on"]["badgeShown"] is True
    assert out["on"]["checked"] == "auto" and out["on"]["chipLabel"] == "Auto"
    assert out["confirms"] == [], "no question on the way out"
    assert out["off"]["chipActive"] is False
    assert out["off"]["checked"] == "manual" and out["off"]["chipLabel"] == "Manual"
    assert out["off"]["badgeShown"] is False
    assert out["sent"][-1]["body"] == {"mode": "manual"}


def test_choosing_the_mode_the_chat_is_in_asks_and_sends_nothing(sandbox):
    """`B1706`. A menu lists both modes, so the current one can be chosen:
    that is not a change, so it is neither a question nor a write."""
    out = _case(sandbox, """
        paint();
        %s
        installUi({ answer: true });
        approvalMode.init(() => 'chat-a');
        await approvalMode.load('chat-a');
        choose('manual');
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ confirms: said.confirms, posts: sent.filter((s) => s.method === 'POST') }));
    """ % _SERVE_ALLOWED)
    assert out == {"confirms": [], "posts": []}


def test_the_badge_is_a_way_out_as_well_as_a_statement(sandbox):
    """A person who notices the banner should not have to find the chip."""
    out = _case(sandbox, """
        const { badge } = paint();
        serve((url, method, body) => {
          if (method === 'GET') return { status: 200, body: { mode: 'auto', auto: true, may_set: true } };
          return { status: 200, body: { mode: body.mode, auto: body.mode === 'auto' } };
        });
        installUi({ answer: false });
        approvalMode.init(() => 'chat-a');
        await approvalMode.load('chat-a');
        badge.dispatchEvent({ type: 'click' });
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ ui: read(), sent }));
    """)

    assert out["ui"]["badgeShown"] is False
    assert out["sent"][-1]["body"] == {"mode": "manual"}


def test_the_chip_and_the_badge_never_disagree(sandbox):
    """One state, two surfaces (`Law 7`). Over every transition this control
    has, the chip's pressed state and the badge's visibility are one fact."""
    out = _case(sandbox, """
        paint();
        %s
        installUi({ answer: true });
        approvalMode.init(() => 'chat-a');
        const seen = [];
        const snap = () => { const r = read(); seen.push([r.chipActive, r.checked, r.chipLabel, r.badgeShown]); };
        await approvalMode.load('chat-a'); snap();
        choose('auto');
        await new Promise((r) => setTimeout(r, 0)); snap();
        choose('manual');
        await new Promise((r) => setTimeout(r, 0)); snap();
        console.log(JSON.stringify(seen));
    """ % _SERVE_ALLOWED)

    # `B1706`: the chip's word and the menu's check join the chip's on-state
    # and the badge as one fact (it was `aria-pressed`).
    assert out == [[False, "manual", "Manual", False], [True, "auto", "Auto", True],
                   [False, "manual", "Manual", False]]


# ── B. the adversary: the chat you just left ────────────────────────────────


def test_switching_chats_does_not_carry_auto_across(sandbox):
    """Chat A is on Auto; opening chat B must not draw A's state.

    The leak the server cannot have — the mode is a column — but a browser
    that drew the chip from its own memory would invent.
    """
    out = _case(sandbox, """
        paint();
        serve((url, method, body) => {
          const auto = url.includes('chat-a');
          return { status: 200, body: { mode: auto ? 'auto' : 'manual', auto, may_set: true } };
        });
        await approvalMode.load('chat-a');
        const a = read();
        await approvalMode.load('chat-b');
        const b = read();
        console.log(JSON.stringify({ a, b, mode: approvalMode.currentMode() }));
    """)

    assert out["a"]["chipActive"] is True and out["a"]["badgeShown"] is True
    assert out["b"]["chipActive"] is False, "chat B asks"
    assert out["b"]["badgeShown"] is False
    assert out["mode"] == "manual"


def test_a_new_chat_with_no_id_yet_shows_manual_approve(sandbox):
    """The welcome screen, before the first message. There is no row to read,
    so it is the install default and not the last chat's state."""
    out = _case(sandbox, """
        paint();
        serve((url, method, body) => ({ status: 200, body: { mode: 'auto', auto: true, may_set: true } }));
        await approvalMode.load('chat-a');
        const before = read();
        await approvalMode.load(null);
        console.log(JSON.stringify({ before, after: read(), gets: sent.length }));
    """)

    assert out["before"]["badgeShown"] is True
    assert out["after"]["badgeShown"] is False
    assert out["gets"] == 1, "and no request was made for a chat that does not exist"


def test_an_answer_that_arrives_after_the_person_moved_on_is_dropped(sandbox):
    """Chat A's answer lands while chat B is open. Drawing it would be the
    cross-chat leak arriving by race rather than by memory."""
    out = _case(sandbox, """
        paint();
        let release;
        const held = new Promise((r) => { release = r; });
        globalThis.fetch = async (url) => {
          if (url.includes('chat-a')) {
            await held;
            return { ok: true, status: 200, json: async () => ({ mode: 'auto', auto: true, may_set: true }) };
          }
          return { ok: true, status: 200, json: async () => ({ mode: 'manual', auto: false, may_set: true }) };
        };
        const slow = approvalMode.load('chat-a');
        await approvalMode.load('chat-b');
        release();
        await slow;
        console.log(JSON.stringify({ ui: read(), mode: approvalMode.currentMode() }));
    """)

    assert out["mode"] == "manual"
    assert out["ui"]["chipActive"] is False
    assert out["ui"]["badgeShown"] is False


def test_the_mode_is_never_written_to_browser_storage():
    """The one place a per-chat mode could become a per-device mode.

    `Law 20`: read of the module's source because the claim is about what the
    module does NOT do, and a sandbox can only show that one path did not.
    """
    source = APPROVAL_MODE.read_text(encoding="utf-8")
    # Comments out, because the module's own docstring says the words it must
    # not *call* — a grep over prose would pass for the wrong reason, and
    # `Law 20` says a test that greps a file tests the file.
    #
    # Through the suite's one blanker, not a pair of regexes (`B290`, and
    # `tests/test_one_comment_blanker.py` is the tripwire that caught this
    # file's first draft): `/\*.*?\*/` cannot tell a comment from a string, so
    # a `'/*'` anywhere in the module eats everything to the next `*/` and the
    # assertion below passes because the text it searched is gone. `blank_text`
    # keeps offsets and leaves string bodies alone, so a `window['localStorage']`
    # is still found.
    code = blank_text(source, "js")
    for api in ("localStorage", "sessionStorage", "indexedDB", "document.cookie",
                "Storage.set", "saveToggleState"):
        assert api not in code, api


def test_the_chat_switch_reads_the_mode_for_the_chat_being_opened():
    """`Law 13` — nothing half-wired.

    `B1703` found this case green while the wiring was not: it asserted the
    read inside `setCurrentSessionId`, and opening a chat from the list
    (`selectSession`) sets `currentSessionId` itself and never calls that, so
    in Chromium the chip stayed hidden on every chat opened from the list
    (`Law 20`: the grep found the right line in a function the path does not
    take). Now every assignment of `currentSessionId` in `sessions.js` is
    followed by the read — and `tests/test_auto_approve_is_accepted_in_a_browser.py`
    opens a chat from the list in the real app and presses the chip."""
    source = SESSIONS.read_text(encoding="utf-8")
    code = blank_text(source, "js")
    sites = [m.end() for m in re.finditer(r"(?<!let )\bcurrentSessionId = [^;=]+;", code)]
    assert len(sites) >= 5, sites
    for end in sites:
        # Past a blanked comment, as in `setCurrentSessionId`; before the
        # next statement block could be another function's.
        after = code[end: end + 1000]
        assert "approvalModeModule.load(" in after[: after.find("\n}") if "\n}" in after else None], (
            code[end - 80: end + 200])
    assert "import approvalModeModule from './approvalMode.js'" in source

    app = APP.read_text(encoding="utf-8")
    assert "approvalModeModule.init(" in app
    assert "import approvalModeModule from './js/approvalMode.js'" in app


# ── C. no dead control, and the refusal is the server's own sentence ───────


def test_a_person_without_the_privilege_is_shown_no_switch(sandbox):
    """`Law 15`: an admin has not granted `can_auto_approve`, so there is no
    control here to discover and no explaining to do."""
    out = _case(sandbox, """
        paint();
        serve(() => ({ status: 200, body: { mode: 'manual', auto: false, may_set: false } }));
        await approvalMode.load('chat-a');
        console.log(JSON.stringify(read()));
    """)

    assert out["chipShown"] is False
    assert out["badgeShown"] is False


def test_a_refused_write_shows_the_servers_sentence_and_leaves_the_chip(sandbox):
    """Doc 2 § 5 rule 7. The server is the only thing that knows which of the
    four refusals it was, so the browser shows what it said rather than
    guessing."""
    out = _case(sandbox, """
        paint();
        serve((url, method, body) => {
          if (method === 'GET') return { status: 200, body: { mode: 'manual', auto: false, may_set: true,
                                                              ...%s, ...%s } };
          return { status: 403, body: { detail: %s } };
        });
        installUi({ answer: true });
        approvalMode.init(() => 'chat-a');
        await approvalMode.load('chat-a');
        choose('auto');
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ ui: read(), toasts: said.toasts }));
    """ % (_WARNING_FIELDS, _MENU_FIELDS, json.dumps(AUTO_NOT_ALLOWED_SENTENCE)))

    assert out["toasts"] == [AUTO_NOT_ALLOWED_SENTENCE]
    assert out["ui"]["chipActive"] is False, "the chip stays where the server left it"
    assert out["ui"]["checked"] == "manual"
    assert out["ui"]["badgeShown"] is False


def test_an_unreachable_server_reads_as_manual_approve(sandbox):
    """The safe reading of *"I do not know whether this chat asks"* is that it
    does."""
    out = _case(sandbox, """
        paint();
        serve((url, method, body) => ({ status: 200, body: { mode: 'auto', auto: true, may_set: true } }));
        await approvalMode.load('chat-a');
        const on = read();
        globalThis.fetch = async () => { throw new Error('offline'); };
        await approvalMode.load('chat-b');
        console.log(JSON.stringify({ on, off: read() }));
    """)

    assert out["on"]["badgeShown"] is True
    assert out["off"]["badgeShown"] is False


def test_a_chat_with_no_id_says_what_to_do_instead_of_failing_quietly(sandbox):
    """`Law 15`. Clicking the chip before the chat exists explains why, in one
    line that names the scope."""
    out = _case(sandbox, """
        paint();
        %s
        installUi({ answer: true });
        approvalMode.init(() => null);
        await approvalMode.load(null);
        choose('auto');   // `B1706`: the menu's Auto-approve
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ toasts: said.toasts, posts: sent.filter((s) => s.method === 'POST') }));
    """ % _SERVE_ALLOWED)

    assert out["posts"] == []
    assert len(out["toasts"]) == 1
    assert "per chat" in out["toasts"][0]


# ── D. the markup and the stylesheet ship what the module drives ───────────


def test_the_shipped_markup_holds_both_surfaces():
    """The ids `fx8-mobile` is told to drive, in the page they are on.

    `B1706` moved the chip and changed what it is: from an `aria-pressed`
    toggle labelled *Auto-approve* in the Plan / Web / Shell strip (it carried
    `.tool-indicator` for that strip's clear X) to a menu button at the right
    of the composer's bottom row, whose word and whose menu's words arrive from
    the server — so the page ships the spans empty."""
    html = blank_text(INDEX.read_text(encoding="utf-8"), "html")
    chip = re.search(r'<button[^>]*id="approval-mode-btn"[^>]*>', html)
    assert chip, "the composer chip is not in the page"
    assert "tool-chip" in chip.group(0), "the composer's chip, and its on-state"
    assert 'aria-haspopup="menu"' in chip.group(0) and 'aria-expanded="false"' in chip.group(0)
    assert "aria-pressed" not in chip.group(0), "a menu button, not a toggle"
    assert 'style="display:none;"' in chip.group(0), (
        "hidden until the server says this person may set it"
    )
    # 2026-11-01: the deck. Send moved into the box's own row above the deck
    # (`.chat-input-actions`), so the deck's right-hand group is the slice from
    # `.chat-input-right` to the deck's end, not "up to the send button".
    box = html[html.index('<div class="chat-input-box">'):html.index('<div class="chat-input-bottom"')]
    assert 'class="send-btn' in box, "Send is in the box, with +, dictation and the call"
    assert 'id="approval-mode-btn"' not in box, "the selector is on the deck, not in the box"
    bottom = html[html.index('<div class="chat-input-bottom"'):]
    left = bottom[: bottom.index('<div class="chat-input-right">')]
    right = bottom[bottom.index('<div class="chat-input-right">'):]
    assert 'id="approval-mode-btn"' not in left, "the old chip is still in the strip"
    assert 'id="approval-mode-btn"' in right[: right.index('<form id="chat-form"')], (
        "the selector is at the bottom right of the composer, on the deck")
    items = re.findall(r'<div[^>]*role="menuitemradio"[^>]*data-approval-choice="([a-z]+)"[^>]*>', html)
    assert items == ["manual", "auto"], items
    for name in ("approval-mode-item-name", "approval-mode-item-desc"):
        assert re.findall(rf'<span class="{name}">([^<]*)</span>', html) == ["", ""], (
            "the menu's words are the server's, not the page's")

    badge = re.search(r'<button[^>]*id="chat-auto-approve-badge"[^>]*>', html)
    assert badge, "the header badge is not in the page"
    assert "hidden" in badge.group(0)
    # It belongs to the chat's own header, beside the chat's name.
    top = html[html.index('<div class="chat-top-bar">'):]
    assert 'id="chat-auto-approve-badge"' in top[: top.index("</div>    </div>")]


def test_the_badge_has_a_style_that_survives_every_palette():
    """Themes are protected (`D-2026-09-14-03`): every colour term is a theme
    token or a mix with one, and `--accent` is not reached for — the chip's
    on-state is `var(--red)` and the badge has to match it.

    `B1552` moved the on-state's label to `--chip-on-fg` (the red, lifted per
    palette to 4.5:1 on its tint, `theme.js`), falling back to `var(--red)`;
    the badge's label is the same declaration as the chip's, which is the
    "has to match" this case is for, asserted rather than implied."""
    css = STYLE.read_text(encoding="utf-8")
    start = css.index(".chat-auto-approve-badge {")
    block = css[start: css.index("}", start)]
    colours = re.findall(r"var\(--[a-z-]+\)", block)
    assert colours, "the block defines no colour at all"
    assert set(colours) <= {"var(--red)"}, colours
    label = re.search(r"(?:^|[;{\s])color\s*:\s*([^;]+);", block).group(1).strip()
    chip_at = css.index(".tool-chip.active {")
    chip = re.search(r"(?:^|[;{\s])color\s*:\s*([^;]+);", css[chip_at: css.index("}", chip_at)]).group(1).strip()
    assert label == chip == "var(--chip-on-fg, var(--red))", (label, chip)
    assert "[hidden] { display: none; }" in css[start: start + 900]
