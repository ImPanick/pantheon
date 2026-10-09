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
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from src.approval_mode import (
    AUTO_LABEL,
    AUTO_NOT_ALLOWED_SENTENCE,
    AUTO_TURN_ON_SENTENCE,
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

/** The two surfaces, exactly as `static/index.html` ships them. */
export function paint() {
  const chip = new Node('button');
  chip.setAttribute('id', 'approval-mode-btn');
  chip.className = 'input-icon-btn tool-indicator tool-chip';
  chip.title = 'Auto-approve';
  chip.setAttribute('aria-pressed', 'false');
  chip.style.display = 'none';
  const label = new Node('span');
  label.className = 'tool-chip-label';
  label.textContent = 'Auto-approve';
  chip.appendChild(label);
  document.body.appendChild(chip);

  const badge = new Node('button');
  badge.setAttribute('id', 'chat-auto-approve-badge');
  badge.className = 'chat-auto-approve-badge';
  badge.hidden = true;
  badge.textContent = 'Auto-approve';
  document.body.appendChild(badge);
  return { chip, badge };
}

export function read() {
  const chip = document.getElementById('approval-mode-btn');
  const badge = document.getElementById('chat-auto-approve-badge');
  return {
    chipShown: chip.style.display !== 'none',
    chipActive: chip.classList.contains('active'),
    chipPressed: chip.getAttribute('aria-pressed'),
    chipTitle: chip.title,
    chipLabel: chip.querySelector('.tool-chip-label').textContent,
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
    "import { document, paint, read, serve, sent, installUi, said } from './shim.js';\n"
    "const approvalMode = (await import('./approvalMode.js')).default;\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(
        tmp_path_factory.mktemp("approvalmode"), APPROVAL_MODE, _SHIM, {}
    )


def _case(sandbox, script: str) -> dict:
    return _run(sandbox, _PREAMBLE, script)


_SERVE_ALLOWED = """
    serve((url, method, body) => {
      if (method === 'GET') return { status: 200, body: { mode: 'manual', auto: false, may_set: true } };
      return { status: 200, body: { mode: body.mode, auto: body.mode === 'auto' } };
    });
"""


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
    assert out["chipPressed"] == "false"
    assert out["badgeShown"] is False


def test_turning_auto_on_asks_once_with_one_plain_sentence(sandbox):
    """*"one deliberate act with one plain sentence"*, and *"it must not be a
    silent toggle either"*. One confirm, one sentence, and the sentence is the
    server's own copy so the two cannot drift (`Law 7`)."""
    out = _case(sandbox, """
        const { chip } = paint();
        %s
        installUi({ answer: true });
        approvalMode.init(() => 'chat-a');
        await approvalMode.load('chat-a');
        chip.dispatchEvent({ type: 'click' });
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({
          ui: read(), confirms: said.confirms, toasts: said.toasts, sent,
        }));
    """ % _SERVE_ALLOWED)

    assert len(out["confirms"]) == 1, "asked once, not twice and not never"
    confirm = out["confirms"][0]
    assert confirm["message"] == AUTO_TURN_ON_SENTENCE
    # One sentence of consequence and one question. Not a wall of warning.
    assert confirm["message"].count(".") <= 1
    assert len(confirm["message"]) < 220
    assert confirm["opts"]["confirmText"] == "Turn on"
    assert confirm["opts"]["cancelText"] == "Keep asking me"

    assert out["ui"]["chipActive"] is True
    assert out["ui"]["chipPressed"] == "true"
    assert out["ui"]["badgeShown"] is True
    assert out["sent"][-1] == {
        "url": "/api/session/chat-a/approval-mode", "method": "POST",
        "body": {"mode": "auto"},
    }


def test_saying_no_to_the_question_changes_nothing(sandbox):
    """A deliberate act is one a person can decline."""
    out = _case(sandbox, """
        const { chip } = paint();
        %s
        installUi({ answer: false });
        approvalMode.init(() => 'chat-a');
        await approvalMode.load('chat-a');
        chip.dispatchEvent({ type: 'click' });
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ ui: read(), posts: sent.filter((s) => s.method === 'POST') }));
    """ % _SERVE_ALLOWED)

    assert out["posts"] == [], "nothing was asked of the server"
    assert out["ui"]["chipActive"] is False
    assert out["ui"]["badgeShown"] is False


def test_turning_auto_off_is_one_click_with_no_question(sandbox):
    """Putting a gate back is never the move that needs confirming."""
    out = _case(sandbox, """
        const { chip } = paint();
        serve((url, method, body) => {
          if (method === 'GET') return { status: 200, body: { mode: 'auto', auto: true, may_set: true } };
          return { status: 200, body: { mode: body.mode, auto: body.mode === 'auto' } };
        });
        installUi({ answer: false });
        approvalMode.init(() => 'chat-a');
        await approvalMode.load('chat-a');
        const on = read();
        chip.dispatchEvent({ type: 'click' });
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ on, off: read(), confirms: said.confirms, sent }));
    """)

    assert out["on"]["chipActive"] is True and out["on"]["badgeShown"] is True
    assert out["confirms"] == [], "no question on the way out"
    assert out["off"]["chipActive"] is False
    assert out["off"]["badgeShown"] is False
    assert out["sent"][-1]["body"] == {"mode": "manual"}


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
        const { chip } = paint();
        %s
        installUi({ answer: true });
        approvalMode.init(() => 'chat-a');
        const seen = [];
        const snap = () => { const r = read(); seen.push([r.chipActive, r.chipPressed, r.badgeShown]); };
        await approvalMode.load('chat-a'); snap();
        chip.dispatchEvent({ type: 'click' });
        await new Promise((r) => setTimeout(r, 0)); snap();
        chip.dispatchEvent({ type: 'click' });
        await new Promise((r) => setTimeout(r, 0)); snap();
        console.log(JSON.stringify(seen));
    """ % _SERVE_ALLOWED)

    assert out == [[False, "false", False], [True, "true", True], [False, "false", False]]


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
    """`Law 13` — nothing half-wired. `setCurrentSessionId` is the one place
    that knows which chat is open, so it is the one place that reads this."""
    source = SESSIONS.read_text(encoding="utf-8")
    body = source[source.index("export function setCurrentSessionId"):]
    body = body[: body.index("\n}")]
    assert "approvalModeModule.load(id)" in body
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
        const { chip } = paint();
        serve((url, method, body) => {
          if (method === 'GET') return { status: 200, body: { mode: 'manual', auto: false, may_set: true } };
          return { status: 403, body: { detail: %s } };
        });
        installUi({ answer: true });
        approvalMode.init(() => 'chat-a');
        await approvalMode.load('chat-a');
        chip.dispatchEvent({ type: 'click' });
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ ui: read(), toasts: said.toasts }));
    """ % json.dumps(AUTO_NOT_ALLOWED_SENTENCE))

    assert out["toasts"] == [AUTO_NOT_ALLOWED_SENTENCE]
    assert out["ui"]["chipActive"] is False, "the chip stays where the server left it"
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
        const { chip } = paint();
        %s
        installUi({ answer: true });
        approvalMode.init(() => null);
        await approvalMode.load(null);
        chip.style.display = '';
        chip.dispatchEvent({ type: 'click' });
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ toasts: said.toasts, posts: sent.filter((s) => s.method === 'POST') }));
    """ % _SERVE_ALLOWED)

    assert out["posts"] == []
    assert len(out["toasts"]) == 1
    assert "per chat" in out["toasts"][0]


# ── D. the markup and the stylesheet ship what the module drives ───────────


def test_the_shipped_markup_holds_both_surfaces():
    """The ids `fx8-mobile` is told to drive, in the page they are on."""
    html = INDEX.read_text(encoding="utf-8")
    chip = re.search(r'<button[^>]*id="approval-mode-btn"[^>]*>', html)
    assert chip, "the composer chip is not in the page"
    assert "tool-chip" in chip.group(0), "it must sit in the composer strip"
    assert "tool-indicator" in chip.group(0), "and carry the strip's on-state"
    assert 'aria-pressed="false"' in chip.group(0)
    assert 'style="display:none;"' in chip.group(0), (
        "hidden until the server says this person may set it"
    )
    assert f">{AUTO_LABEL}</span>" in html, "the chip is labelled, not an icon alone"

    badge = re.search(r'<button[^>]*id="chat-auto-approve-badge"[^>]*>', html)
    assert badge, "the header badge is not in the page"
    assert "hidden" in badge.group(0)
    # It belongs to the chat's own header, beside the chat's name.
    top = html[html.index('<div class="chat-top-bar">'):]
    assert 'id="chat-auto-approve-badge"' in top[: top.index("</div>    </div>")]


def test_the_badge_has_a_style_that_survives_every_palette():
    """Themes are protected (`D-2026-09-14-03`): every colour term is a theme
    token or a mix with one, and `--accent` is not reached for — the chip's
    on-state is `var(--red)` and the badge has to match it."""
    css = STYLE.read_text(encoding="utf-8")
    start = css.index(".chat-auto-approve-badge {")
    block = css[start: css.index("}", start)]
    colours = re.findall(r"var\(--[a-z-]+\)", block)
    assert colours, "the block defines no colour at all"
    assert set(colours) <= {"var(--red)"}, colours
    assert "[hidden] { display: none; }" in css[start: start + 900]
