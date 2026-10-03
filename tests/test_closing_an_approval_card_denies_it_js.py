# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-01` (CHAT-M-17) — × on a tool approval is its Deny.

Measured on `9560d50`: × on an approval card took the card away
(`chatRenderer.js`, `card.remove()`) and nothing else — the approval stayed
pending on the server for its 10-minute expiry, nothing on screen said a
decision was owed, and a typed follow-up started a turn that asked again. A
window's × closes it; on a question that holds a run, closing it is answering
no. The Back model's rule (`D-2026-10-03-01` §2) is that closing a layer
leaves nothing half-open behind it.

Driven: the real `renderAskUserCard` in the card sandbox of
`tests/test_tool_effect_surfaces_js.py` (fixture and payload imported, not
copied). A plain question's × still only dismisses it.
"""

from test_tool_effect_surfaces_js import _card, card_sandbox  # noqa: F401  (fixture)


def test_the_x_on_an_approval_is_its_deny(card_sandbox):
    o = _card("""
        const { Node } = await import('./dom.js');
        if (!Node.prototype.click) Node.prototype.click = function () {
          this.dispatchEvent({ type: 'click', target: this, currentTarget: this,
                               stopPropagation() {}, preventDefault() {} }); };
        const seen = [];
        document.addEventListener('pantheon:tool-approval', (e) => seen.push(e.detail));
        const host = root();
        const card = renderAskUserCard(approvalPayload(), { root: host, focus: false, scroll: false });
        const x = card.querySelector('.ask-user-close');
        const label = x.getAttribute('aria-label');
        x.click();
        console.log(JSON.stringify({ label, seen: seen.map((d) => [d.approval_id, d.decision]),
                                     gone: !host.childNodes.includes(card) }));
    """, card_sandbox)
    assert o["label"] == "Deny"
    assert o["seen"] == [["ap-1", "deny"]], "× sent no answer, or not the Deny"
    assert o["gone"] is True


def test_the_x_on_a_question_only_dismisses_it(card_sandbox):
    o = _card("""
        const { Node } = await import('./dom.js');
        if (!Node.prototype.click) Node.prototype.click = function () {
          this.dispatchEvent({ type: 'click', target: this, currentTarget: this,
                               stopPropagation() {}, preventDefault() {} }); };
        const seen = [];
        document.addEventListener('pantheon:tool-approval', (e) => seen.push(e.detail));
        const host = root();
        const card = renderAskUserCard({ question: 'Which colour?', options: [{ label: 'Red' }, { label: 'Blue' }] },
                                       { root: host, focus: false, scroll: false });
        const x = card.querySelector('.ask-user-close');
        const label = x.getAttribute('aria-label');
        x.click();
        console.log(JSON.stringify({ label, seen: seen.length, gone: !host.childNodes.includes(card) }));
    """, card_sandbox)
    assert o == {"label": "Dismiss question", "seen": 0, "gone": True}
