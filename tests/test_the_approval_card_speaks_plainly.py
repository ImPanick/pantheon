# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1202` (`CHAT-U-11`'s rest) — the approval card's reason and its box, in a
person's words.

The button has read *Allow for this chat* since `P23-05`. What was still the
server's long words: the reason under the card's question — the gate's own
sentence, verbatim (`P4-04`): *"External untrusted context has already
influenced this run. Tool 'web_fetch' requires a separate user-authorized
action because it can cause network_egress."* — which the UI/UX audit's § 5
wants as *It has read outside data this turn, so this needs a yes from you.*;
and the *What this can do* heading over the effects (`P7-06`), which the card's
question now says (*Let it reach the internet?*, `approvalTitle`).

Now the card says the gate's sentence as a person reads it
(`tool_approvals.card_words`): why they are asked, and nothing the question and
the list already say. The gate's sentence is untouched — it is the refusal the
model reads (`tool_execution`) — and a sentence a gate wrote for a reason of
its own (a widening, a hire, a vault login) keeps its words. The values —
decisions, scopes, the seal — are untouched (`FORBIDDEN.md` Part 2).

Driven (`Law 20`): every sentence here is the real gate's
(`ToolRunSecurityContext.decision_for`) through the real store's
`public_payload`; the box is the real `chatRenderer.js` in the card sandbox.
"""

import shutil

import pytest

from src.tool_approvals import ToolApprovalStore, card_words
from src.tool_capabilities import ToolRunSecurityContext, TrustRung, capabilities_for_action

from test_tool_effect_surfaces_js import _CARD_PREAMBLE, _card as _js_card, card_sandbox  # noqa: F401

PLAIN_TAINTED = "It has read outside data this turn, so this needs a yes from you."
PLAIN_RUNG = "This chat is set to ask before anything with an effect, so this needs a yes from you."


def _card(context, tool, content):
    decision = context.decision_for(tool, content)
    assert not decision.allowed, "the premise: the gate asks"
    pending = ToolApprovalStore().create(
        owner="alice", session_id="s", origin_run_id=context.run_id, tool_name=tool, content=content,
        workspace=None, external_untrusted_context_seen=context.external_untrusted_context_seen,
        capabilities=capabilities_for_action(tool, content), gate_decision=decision,
        taint_trail=context.taint_trail,
    )
    return decision, pending.public_payload(reason=decision.reason)


def _tainted():
    context = ToolRunSecurityContext()
    context.observe_tool_result("web_fetch", {"output": "a page", "exit_code": 0})
    return context


def test_after_outside_data_the_card_says_so_plainly_and_the_model_keeps_the_detail():
    """The row's sentence, from the real gate."""
    decision, card = _card(_tainted(), "bash", "ls -la /tmp/scratch")
    assert card["description"] == PLAIN_TAINTED
    assert "bash" in decision.reason and "execute_code" in decision.reason, \
        "the gate's own sentence — what the model reads — is untouched"
    assert card["gate"]["tainted"] is True and card["gate"]["tripped_effects"]
    # `B1670` changed this case's `rm -rf`: a call whose arguments make it
    # destructive is now named after the plain sentence, in a hire card's
    # words (`tests/test_the_ladders_card_says_what_a_call_destroys.py`).
    _decision, deleting = _card(_tainted(), "bash", "rm -rf /tmp/scratch")
    assert deleting["description"] == PLAIN_TAINTED[:-1] + " (rm deletes files)."


def test_a_strict_rung_says_its_reason_the_same_way():
    context = ToolRunSecurityContext(rung=TrustRung.ASK_EVERY_TIME)
    _decision, card = _card(context, "bash", "echo hi")
    assert card["description"] == PLAIN_RUNG
    assert "untrusted" not in card["description"].lower() and "outside data" not in card["description"]


def test_a_widening_keeps_its_own_words_after_the_plain_preamble():
    _decision, card = _card(_tainted(), "ui_control", "toggle bash on")
    assert card["description"].startswith("It has read outside data this turn. The assistant wants to ")
    assert "asks every time" in card["description"]
    _decision, clean = _card(ToolRunSecurityContext(), "ui_control", "toggle bash on")
    assert clean["description"].startswith("The assistant wants to "), clean["description"]


def test_a_sentence_written_for_another_reason_is_left_as_it_is():
    for reason in ("This agent's hire asks before network_egress: 'web_fetch' waits for your yes.",
                   "'bash' is not available to this session. Approving cannot make it available."):
        assert card_words(reason) == reason


def test_the_default_says_it_the_same_way():
    store = ToolApprovalStore()
    for tainted, said in ((True, PLAIN_TAINTED), (False, PLAIN_RUNG)):
        card = store.create(
            owner="alice", session_id="s", origin_run_id="r", tool_name="bash", content="echo hi",
            workspace=None, external_untrusted_context_seen=tainted,
            capabilities=capabilities_for_action("bash", "echo hi"),
        ).public_payload()
        assert card["description"] == said


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_effects_box_has_no_heading_the_question_already_says(card_sandbox):  # noqa: F811
    out = _js_card("""
        const card = renderAskUserCard(approvalPayload({
          description: %r,
          effect_label: 'Reaches the internet', effect_labels: ['Reaches the internet', 'Reads your private data'],
          effects: ['network_egress', 'read_private'], effect_band: 'notable',
          action: { tool: 'web_fetch', content: 'https://example.com', digest: 'abcd1234',
                    effects: ['network_egress', 'read_private'] },
        }), { root: root() });
        const box = card.querySelector('.approval-effects');
        console.log(JSON.stringify({
          question: card.querySelector('.ask-user-question').textContent,
          reason: card.querySelector('.ask-user-reason').textContent,
          heading: card.querySelector('.approval-effects-title') ? card.querySelector('.approval-effects-title').textContent : null,
          name: box.getAttribute('aria-label'), role: box.getAttribute('role'),
          rows: box.querySelectorAll('.approval-effect').length,
        }));
    """ % PLAIN_TAINTED, card_sandbox)
    assert out["question"] == "Let it reach the internet?"
    assert out["reason"] == PLAIN_TAINTED
    assert out["heading"] is None, "the box still repeats the question"
    assert out["name"] == "What this can do" and out["role"] == "group", "a screen reader still hears what it is"
    assert out["rows"] == 2
