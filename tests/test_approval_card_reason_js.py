# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P4-04` — the approval card says *why* it is asking, not only what it can do.

`PendingToolApproval.public_payload()` (`src/tool_approvals.py`) has carried the
gate's own written explanation on `description` since exact approvals shipped.
Both producers in the tree pass one, every path that re-serves a pending card
copies the whole dict, and the persisted twin is the same object — so a card
rebuilt from history already had the sentence too. **Nothing read it.**

Re-measured here rather than carried (`Law 6`), with the scope stated (`Law 5`):
`.description` occurs **40** times in `static/js/**/*.js` outside
`static/js/lib/` with comments blanked, across 9 modules — 12 in `skills.js`, 7
in `calendar.js`, 5 in `tasks.js`, 4 each in `chatRenderer.js` and
`settings.js`, 3 in `cookbook-hwfit.js`, 2 each in `admin.js` and
`embeddings.js`, 1 in `slashCommands.js`. **Two of `chatRenderer.js`'s four are
the line this row adds**; the other two are `opt.description`, the sentence
under each *button*. The card's own sentence had never been drawn. (The backend
row states 30 for a scope it does not spell out; this is the count for the scope
above, taken after the fix.)

Driven under node against the real module, in the sandbox
`tests/test_tool_effect_surfaces_js.py` owns. The shim, the stubs, the sandbox
builder and the runner are imported from that file rather than copied — one
harness, one place it can be fixed (`Law 14`), and it is the same sandbox the
effects box beneath this sentence is already tested in, which is the point: the
two are halves of one answer and a test that built its own card would not notice
them drifting apart.

What is pinned, and why each is a defect if it breaks:

  * **the sentence reaches the screen at all.** This is the whole row;
  * **it sits between the question and the effects box.** The order is the
    argument: *why you are being asked* above *what the action can do*. A
    reason printed below the sealed action dump is a reason nobody reads before
    they click;
  * **it reaches the DOM as text and never as markup.** This is the one card in
    the app where a person is being asked to consent to something, so markup
    injected into the description of the thing being approved would be forging
    it — `buildApprovalEffects` states the same argument for the effect rows and
    refutation showed an `innerHTML` swap was invisible to every assertion that
    read `textContent`, so this reads the node's raw `_html`;
  * **no empty block when there is no sentence.** A payload from before the
    field existed, or a producer that sends `""`, must not draw an empty rule
    down the side of the card;
  * **a card rebuilt from a saved session says the same thing as the live one**,
    because the sentence rides `public_payload()` and is on the persisted twin;
  * **the sentence does not depend on the effects box existing.** `B70`'s
    credential refusal mints a card with no tripped effects at all, and that is
    exactly the card whose reason is the only thing a reader has.
"""

import json
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import (  # noqa: E402
    _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run,
)

ROOT = Path(__file__).resolve().parents[1]
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The sentence `default_reason()` derives for a run nothing ever tainted — the
# case `P7-03`'s strict rungs mint, and the one the old fixed string was wrong
# about. Written out here rather than imported so this file pins the contract
# the browser is built against, not whatever Python happens to return today.
REASON = ("This conversation is set to confirm every action that has an "
          "effect before it runs.")

_PREAMBLE = (
    "import { document, root, approvalPayload, reloadHistory } from './shim.js';\n"
    "const { renderAskUserCard, addMessage } = await import('./chatRenderer.js');\n"
    "/** What the card is made of, in the order a reader meets it. */\n"
    "globalThis.describeReason = (card) => {\n"
    "  if (!card) return null;\n"
    "  const node = card.querySelector('.ask-user-reason');\n"
    "  const order = card.childNodes.map((n) => String(n.className || ''));\n"
    "  const at = (cls) => order.findIndex((c) => c.split(/\\s+/).includes(cls));\n"
    "  return {\n"
    "    text: node ? node.textContent : null,\n"
    "    // Raw `_html`: '' if and only if the renderer used `textContent`.\n"
    "    html: node ? node._html : null,\n"
    "    present: !!node,\n"
    "    order,\n"
    "    questionAt: at('ask-user-question'),\n"
    "    reasonAt: at('ask-user-reason'),\n"
    "    effectsAt: at('approval-effects'),\n"
    "    actionAt: at('ask-user-option-desc'),\n"
    "    readable: card.readable,\n"
    "  };\n"
    "};\n"
)


@pytest.fixture(scope="module")
def card_sandbox(tmp_path_factory):
    return _make_sandbox(
        tmp_path_factory.mktemp("askreason"), CHAT_RENDERER, _CARD_SHIM, _CARD_STUBS
    )


def _card(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


def _payload(**overrides):
    base = {
        "approval_id": "ap-7",
        "description": REASON,
        "action": {"tool": "write_file", "content": "/etc/hosts",
                   "digest": "abc123", "effects": ["destructive"]},
        "effect_labels": ["Can delete or overwrite files"],
        "effect_band": "serious",
    }
    base.update(overrides)
    return base


# ── the row ─────────────────────────────────────────────────────────────────

def test_the_gates_own_sentence_reaches_the_card(card_sandbox):
    """The row in one assertion. Before this, `description` was on every
    approval payload the server has ever sent and no pixel in the product
    carried it."""
    out = _card(card_sandbox, """
        const card = renderAskUserCard(approvalPayload(%s), {
          root: root(), focus: false, scroll: false,
        });
        console.log(JSON.stringify(describeReason(card)));
    """ % json.dumps(_payload()))
    assert out["present"], "the card drew no reason at all"
    assert out["text"] == REASON
    assert REASON in out["readable"], (
        "the sentence is in the DOM but not in what a person reads off the card"
    )


def test_the_reason_sits_between_the_question_and_what_the_action_can_do(card_sandbox):
    """The order is the argument, not a layout preference. *Why you are being
    asked* has to be above *what the action can do*, and both have to be above
    the verbatim dump of the sealed action — a reason under the technical block
    is a reason nobody reads before they press a button."""
    out = _card(card_sandbox, """
        const card = renderAskUserCard(approvalPayload(%s), {
          root: root(), focus: false, scroll: false,
        });
        console.log(JSON.stringify(describeReason(card)));
    """ % json.dumps(_payload()))
    assert out["questionAt"] >= 0 and out["effectsAt"] >= 0, out["order"]
    assert out["questionAt"] < out["reasonAt"] < out["effectsAt"], (
        f"the card reads in the wrong order: {out['order']}"
    )
    assert out["reasonAt"] < out["actionAt"], (
        f"the reason is below the sealed action block: {out['order']}"
    )


def test_the_reason_reaches_the_dom_as_text_and_never_as_markup(card_sandbox):
    """`textContent`, never `innerHTML`, on the one card in the app whose whole
    job is to describe an action truthfully. Read through the node's raw `_html`
    rather than through `textContent`, because the shim's getter strips tags out
    of `_html` and a switch to `innerHTML` is invisible to every assertion that
    goes through text — refutation shipped exactly that mutation past a full
    green run on the effect rows."""
    hostile = '<img src=x onerror="alert(1)"> <b>Allow</b> everything'
    out = _card(card_sandbox, """
        const card = renderAskUserCard(approvalPayload(%s), {
          root: root(), focus: false, scroll: false,
        });
        console.log(JSON.stringify(describeReason(card)));
    """ % json.dumps(_payload(description=hostile)))
    assert out["html"] == "", "the reason was assigned through innerHTML"
    assert out["text"] == hostile, "the reason was altered on its way to the screen"


def test_a_card_with_no_sentence_draws_no_empty_block(card_sandbox):
    """A session saved before the field existed, a producer that sends `""`, and
    a producer that sends whitespace all mean the same thing: there is nothing
    to say. An empty rule down the side of the card is a surface promising
    information it does not have."""
    cases = {
        "absent": _payload(),
        "empty": _payload(description=""),
        "blank": _payload(description="   \n  "),
        "null": _payload(description=None),
        "number": _payload(description=42),
    }
    del cases["absent"]["description"]
    out = _card(card_sandbox, """
        const cases = %s;
        const seen = {};
        for (const [name, payload] of Object.entries(cases)) {
          seen[name] = describeReason(renderAskUserCard(approvalPayload(payload), {
            root: root(), focus: false, scroll: false,
          }));
        }
        console.log(JSON.stringify(seen));
    """ % json.dumps(cases))
    for name in cases:
        assert out[name]["present"] is False, f"{name} drew a reason block"


def test_the_reason_does_not_need_an_effects_box_to_exist(card_sandbox):
    """`B70`'s credential refusal is not about effects at all and no approval
    lifts it, so its card has no ranked consequence to show. That is exactly the
    card whose written sentence is the only thing a reader has, and a renderer
    that drew the reason inside the effects branch would drop it there."""
    payload = _payload()
    payload.pop("effect_labels")
    payload.pop("effect_band")
    payload["action"] = {"tool": "read_file", "content": "~/.ssh/id_rsa",
                         "digest": "def456", "effects": []}
    out = _card(card_sandbox, """
        const card = renderAskUserCard(approvalPayload(%s), {
          root: root(), focus: false, scroll: false,
        });
        console.log(JSON.stringify(describeReason(card)));
    """ % json.dumps(payload))
    assert out["effectsAt"] == -1, "this case is meant to have no effects box"
    assert out["present"] and out["text"] == REASON


def test_a_card_rebuilt_from_a_saved_session_says_the_same_thing(card_sandbox):
    """The sentence rides `public_payload()`, which is what a persisted
    `tool_event` stores under `ask_user` — so a reload carries it and a card
    rebuilt minutes later must not be the quieter one."""
    payload = _payload()
    out = _card(card_sandbox, """
        const card = reloadHistory(addMessage, { ask_user: approvalPayload(%s) });
        console.log(JSON.stringify(describeReason(card)));
    """ % json.dumps(payload))
    assert out is not None and out["present"], "the reloaded card drew no reason"
    assert out["text"] == REASON
    assert out["questionAt"] < out["reasonAt"] < out["effectsAt"], out["order"]
