# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1211` — a waiting step's two buttons say what they do, on the buttons.

**Measured before this file:** under a waiting step's card in the Workbench's
Runs, and under the notice window's card, a paragraph explained the two
buttons — *"Allow once lets this one action run, and the next one asks again.
Deny takes the step's “if it fails” way."* (`ANSWER_WORDS` in
`workflowPanels.js`, and its own copy in `workflowApprovalNotice.js`). The
UI/UX audit's § 5 asked for each button's meaning on that button; the shared
approval box (`approvalBox.js`) took no per-button title, so it could not.

Now the box takes `allowTitle` / `denyTitle`, the words are one copy
(`ANSWER_TITLES`), and both cards set them; the paragraph is gone. The skill
test's card, which passes none, is as it was.

Driven (`Law 20`): the real room, canvas, panels and source over the real
`workflowApi.js`, answered by the C-W fake server — the waiting run of
`test_a_waiting_run_opens_on_its_waiting_step_js.py`; the box itself, called.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_a_waiting_run_opens_on_its_waiting_step_js import _case, box  # noqa: E402,F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

ALLOW = "Lets this one action run. The next one asks again."
DENY_STEP = "The step takes its “if it fails” way."


def test_the_waiting_steps_buttons_carry_what_each_does_and_no_paragraph_does(box):
    o = _case(box, """
        const { r } = await room({ workflowId: 'wf1' });
        fire(r.querySelectorAll('.wf-tab').find((t) => t.dataset.tab === 'runs'), 'click');
        await settle(20);
        const card = r.querySelector('.wf-run-canvas').querySelector('.wf-record-waiting');
        out({ buttons: card.querySelectorAll('button').filter((b) => b.dataset.decision)
                .map((b) => [b.textContent, b.title]),
              notes: card.querySelectorAll('.wf-record-note').map((n) => n.textContent) });
    """)
    assert o["buttons"] == [["Deny", DENY_STEP], ["Allow once", ALLOW]]
    assert not any("Allow once lets" in n for n in o["notes"]), o["notes"]
    # What remains under the card is when nobody answering ends it.
    assert len(o["notes"]) == 1 and o["notes"][0].startswith("If nobody answers by ")


def test_a_card_given_no_titles_has_none(box):
    """The skill test's card (`skills.js`) passes no titles: as it was."""
    o = _case(box, """
        const { approvalBox, ANSWER_TITLES } = await import('../approvalBox.js');
        const plain = approvalBox(APPROVAL, {});
        const titled = approvalBox(APPROVAL, { allowTitle: ANSWER_TITLES.allow, denyTitle: ANSWER_TITLES.denyTask });
        const read = (b) => b.querySelectorAll('button').map((x) => [x.dataset.decision, x.title || '']);
        out({ plain: read(plain), titled: read(titled) });
    """)
    assert o["plain"] == [["deny", ""], ["approve", ""]]
    assert o["titled"] == [["deny", "The run ends without it."], ["approve", ALLOW]]
