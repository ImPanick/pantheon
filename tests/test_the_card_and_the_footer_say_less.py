# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-04` — CHAT-U-11 (the approval card), CHAT-U-17 (the reply footer) and
CHAT-U-18 (the stopped marker), by Doc 2 § 5's voice guide.

**What was wrong** (measured on `9560d50`, `ux-chat.md`):

  * **CHAT-U-11.** Every approval card asked "Allow this task to continue?",
    ran a ten-minute "Expires in 9m 59s" clock, printed "Approval fingerprint:
    474ce9eb…" among the sealed arguments, and put a two-line mechanism under
    each button ("Execute the sealed action and allow every otherwise-gated
    action needed to finish this request. Current tool, account, …").
  * **CHAT-U-17.** "615.32 tok/s"; "1331.59 tok/s" on a three-word reply; the
    memory pill "1 recalled".
  * **CHAT-U-18.** "[Message interrupted]" beside a bare "▸" titled Continue.

**What is pinned** (the card's markup is `DEFERRED.md` D-01 territory — no new
structure, words only, and the seal is untouched): the card asks about its
action, from the ranked effect the payload already carries; the buttons are
their labels with one shared line under them; the clock shows in its last
minute; the fingerprint is the title's tooltip. The footer says a whole
speed, none for a reply under 20 tokens, and "1 memory" (with `B61`'s
"keyword only" kept). Driven through the real `chatRenderer.js` (`Law 20`).
"""

import json
import shutil

import pytest

from test_tool_effect_surfaces_js import _card, card_sandbox  # noqa: F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.mark.parametrize("label, title", [
    ("Reads your private data", "Let it read your private data?"),
    ("Changes something outside this app", "Let it change something outside this app?"),
    ("Fetches a page through the app", "Let it fetch a page through the app?"),
    ("Runs code on this machine", "Let it run code on this machine?"),
    ("Can permanently delete or overwrite", "Let it permanently delete or overwrite?"),
    ("Asks you a question", "Let it ask you a question?"),
])
def test_the_card_asks_about_its_action(card_sandbox, label, title):
    out = _card("""
        const m = await import('./chatRenderer.js');
        console.log(JSON.stringify([
          m.approvalTitle(approvalPayload({ effect_label: %s })),
          m.approvalTitle(approvalPayload({})),
          m.approvalTitle({ question: 'Which file?', options: [] }),
        ]));
    """ % json.dumps(label), card_sandbox)
    assert out == [title, "Allow this task to continue?", "Which file?"]


def test_the_buttons_are_their_labels_and_the_scope_is_said_once(card_sandbox):
    out = _card("""
        const card = renderAskUserCard(approvalPayload({
          effect_label: 'Reads your private data',
          action: { tool: 'manage_documents', content: '{"action": "list"}', digest: '474ce9eb1f803a19' },
          expires_at: Date.now() / 1000 + 599,
        }), { root: root(), focus: false, scroll: false });
        const q = card.querySelector('.ask-user-question');
        console.log(JSON.stringify({
          title: q.textContent, tip: q.title,
          descs: card.querySelectorAll('.ask-user-option .ask-user-option-desc').length,
          optionDescs: card.querySelectorAll('.ask-user-option').map((b) => b.querySelectorAll('.ask-user-option-desc').length),
          scope: (card.querySelector('.ask-user-scope-note') || {}).textContent || null,
          action: card.querySelectorAll('.ask-user-option-desc').map((d) => d.textContent).join(' | '),
          expiryHidden: card.querySelector('.ask-user-expiry').hidden,
        }));
    """, card_sandbox)
    assert out["title"] == "Let it read your private data?"
    assert out["tip"] == "Approval fingerprint: 474ce9eb1f803a19"
    assert out["optionDescs"] == [0, 0], "a button still carries its mechanism"
    assert out["scope"] == "This task stops at the end of this request; this chat stops asking here again."
    assert "fingerprint" not in out["action"].lower()
    assert "manage_documents" in out["action"], "the sealed action is still shown verbatim"
    assert out["expiryHidden"] is True


def test_the_clock_shows_in_the_last_minute(card_sandbox):
    out = _card("""
        const m = await import('./chatRenderer.js');
        const late = m.approvalExpiryLine(Date.now() / 1000 + 42);
        const early = m.approvalExpiryLine(Date.now() / 1000 + 600);
        console.log(JSON.stringify({ late: [late.textContent, !!late.hidden], early: !!early.hidden }));
    """, card_sandbox)
    assert out["late"] == ["Expires in 42s", False]
    assert out["early"] is True


def test_a_question_card_keeps_its_option_descriptions(card_sandbox):
    out = _card("""
        const card = renderAskUserCard({ question: 'Which one?', options: [
          { label: 'A', description: 'the first' }, { label: 'B', description: 'the second' }] },
          { root: root(), focus: false, scroll: false });
        console.log(JSON.stringify({ descs: card.querySelectorAll('.ask-user-option-desc').length,
          scope: !!card.querySelector('.ask-user-scope-note') }));
    """, card_sandbox)
    assert out == {"descs": 2, "scope": False}


# ── the footer ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("metrics, label", [
    ({"tokens_per_second": 615.32, "output_tokens": 300}, "615 tok/s"),
    ({"tokens_per_second": 1331.59, "output_tokens": 3, "response_time": 0.4}, "0.4s"),
    ({"tokens_per_second": 77.69, "output_tokens": 25}, "78 tok/s"),
])
def test_the_footer_says_a_whole_speed_and_none_for_a_tiny_reply(card_sandbox, metrics, label):
    out = _card("""
        const m = await import('./chatRenderer.js');
        const wrap = document.createElement('div');
        m.displayMetrics(wrap, Object.assign({ model: 'm', input_tokens: 10 }, %s));
        const el = wrap.querySelector('.response-metrics');
        console.log(JSON.stringify(el ? el.textContent : null));
    """ % json.dumps(metrics), card_sandbox)
    assert out == label


def test_the_memory_pill_says_how_many(card_sandbox):
    out = _card("""
        const m = await import('./chatRenderer.js');
        console.log(JSON.stringify([
          m.memoryPillParts([{ type: 'recalled', engine: 'vector' }]),
          m.memoryPillParts([{ type: 'pinned' }, { type: 'recalled', engine: 'vector' }]),
          m.memoryPillParts([{ type: 'recalled', engine: 'keyword' }]),
        ]));
    """, card_sandbox)
    assert out == [["1 memory"], ["2 memories"], ["1 memory", "keyword only"]]


# ── the stopped marker ──────────────────────────────────────────────────────

def test_a_stopped_reply_says_stopped_continue_in_one_control(card_sandbox):
    out = _card("""
        const m = await import('./chatRenderer.js');
        let continued = 0;
        const box = m.buildStoppedIndicator(document, () => { continued += 1; });
        const btn = box.querySelector('.continue-btn');
        btn.listeners.click[0]();
        const none = m.buildStoppedIndicator(document, null);
        console.log(JSON.stringify({ label: btn.textContent, type: btn.type, continued,
          buttons: box.querySelectorAll('button').length, cancelled: none.textContent,
          cancelledButtons: none.querySelectorAll('button').length }));
    """, card_sandbox)
    assert out == {"label": "Stopped · Continue", "type": "button", "continued": 1, "buttons": 1,
                   "cancelled": "Stopped", "cancelledButtons": 0}


def test_a_reload_of_a_stopped_reply_draws_the_same_line(card_sandbox):
    out = _card("""
        history.childNodes = [];
        addMessage('assistant', 'Half an answer', 'm', { stopped: true });
        addMessage('assistant', '', 'm', { stopped: true, cancelled: true });
        const lines = history.querySelectorAll('.stopped-indicator').map((n) => n.textContent);
        console.log(JSON.stringify(lines));
    """.replace("history.childNodes", "(await import('./shim.js')).history.childNodes")
       .replace("history.querySelectorAll", "(await import('./shim.js')).history.querySelectorAll"),
        card_sandbox)
    assert out == ["Stopped · Continue", "Stopped"]
