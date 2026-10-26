# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B900` — the allow-rule chooser on a card for a widening promises nothing
the gate does not do.

On the `allow_listed` rung a `P7-02` card — the assistant asking to give itself
more reach (`ui_control` turning on Shell access, `manage_settings` raising a
limit the person set) — still offered *"Anything beginning with 'toggle'"* and
*"Anything ui_control does — … whatever it passes to it"*
(`trustLadder.allowRuleWording`). Both rules are real and still cover what
`ui_control` does otherwise, but neither covers a widening, which asks every
time — so the chooser on that card, and *"whatever it passes to it"* in the
list under the ladder, said what the gate does not do. The card's own
sentence, directly above the chooser, says *"it asks every time"*.

Now the payload says when its action widens (`gate.widening`, derived in
`public_payload` by the gate's own question `self_escalation_for`, never
stored), the card offers no chooser on such a card, and the two wider rules'
sentences name the exception, so they are true of every tool wherever they are
read.

Driven: the real `PendingToolApproval.public_payload` for the payload; the
real `chatRenderer.js` and `trustLadder.js` in the allow-rule sandbox
`tests/test_trust_ladder_js.py` builds (its fixture, preamble and helpers,
imported) for the card.
"""

import json
import time

import pytest

from src.tool_approvals import PendingToolApproval
from test_trust_ladder_js import _LOAD_CARD, _ON_RUNG, _allow, allow_sandbox  # noqa: F401


def _payload(tool: str, content: str) -> dict:
    now = time.time()
    return PendingToolApproval(
        approval_id="ap-1", owner="ada", session_id="s1", origin_run_id="r1",
        tool_name=tool, content=content, workspace="", document_id="",
        document_version=None, document_digest="", external_untrusted_context_seen=False,
        effects=(), result_integrity="trusted", digest="0" * 64,
        created_at=now, expires_at=now + 600,
    ).public_payload()


@pytest.mark.parametrize("tool, content, widening", [
    ("ui_control", "toggle bash on", True),
    ("ui_control", "toggle bash off", False),
    ("ui_control", "set_theme dark", False),
    ("bash", "git status --short", False),
])
def test_the_payload_says_when_its_action_widens(tool, content, widening):
    from src.tool_capabilities import self_escalation_for
    assert (self_escalation_for(tool, content) is not None) is widening, "the premise"
    assert _payload(tool, content)["gate"]["widening"] is widening


_WIDENING = "{ tool: 'ui_control', content: 'toggle bash on', digest: 'abcd1234', effects: ['admin_change'] }"
_NARROWING = "{ tool: 'ui_control', content: 'toggle bash off', digest: 'abcd1234', effects: ['admin_change'] }"


def _card(sandbox, action: str, widening: bool) -> dict:
    return _allow("""
        %s
        %s
        const card = renderAskUserCard(approvalPayload({ action: %s, gate: { widening: %s } }), { root: root() });
        console.log(JSON.stringify({ rule: describeAllowRule(card), text: card.readable }));
    """ % (_ON_RUNG, _LOAD_CARD, action, json.dumps(widening)), sandbox)


def test_a_widening_card_offers_no_stop_asking_chooser(allow_sandbox):  # noqa: F811
    """The row's `Verify:`."""
    out = _card(allow_sandbox, _WIDENING, True)
    assert out["rule"] is None, out["rule"]
    assert "stop asking" not in out["text"].lower()


def test_the_wider_rules_name_the_exception_wherever_they_are_read(allow_sandbox):  # noqa: F811
    """On a card that does not widen — `ui_control` switching something off —
    the chooser is offered, and its two wider scopes no longer claim
    *whatever it passes to it* without the exception the gate keeps. The list
    under the ladder phrases a stored rule with the same function."""
    out = _card(allow_sandbox, _NARROWING, False)
    scopes = {s["match"]: s["sentence"] for s in out["rule"]["scopes"]}
    assert set(scopes) == {"exact", "prefix", "any"}
    for kind in ("prefix", "any"):
        assert "except a change that gives it more reach, which asks every time" in scopes[kind], scopes[kind]
    assert "more reach" not in scopes["exact"], "the exact rule never covered a widening; it says nothing of one"
