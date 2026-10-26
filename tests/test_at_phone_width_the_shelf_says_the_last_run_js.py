# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1172` — at phone width the Automations shelf says the open workflow's
last run beside its select.

**Measured before this file** (`w10-wb`, dark and light at 390): the shelf is
a select whose options read "Parks on a wait (light-390) (On)"; the row's
"Last run: Waiting" — what `B1108` keeps current — is drawn only in the list,
and the list is `display: none` under `@media (max-width: 768px)`. So at 390
a run's state was read in the Runs tab alone.

Driven (`Law 20`): the real room (`workflowRoom.js`), canvas and panels in
node, over the faked workflow layer of `test_the_automations_room_js.py`; the
phone rules are found in `static/style.css` with the suite's one rule walker
(`tests/helpers/css_rules.py`) and asserted inside the media query.
"""
from __future__ import annotations

import copy
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_the_automations_room_js import _WORLD, _case, box  # noqa: E402,F401
from tests.helpers.css_rules import css_rules, decl  # noqa: E402
from tests.helpers.source_text import blank  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PHONE = "@media (max-width: 768px)"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_PICK = """
const pickOf = (root) => {
  const label = root.querySelector('.wf-shelf-pick');
  const last = label.querySelector('.wf-shelf-pick-last');
  return { text: last ? last.textContent : null, tone: last ? last.dataset.tone : null,
           afterSelect: !!last && [...label.children].indexOf(last) === [...label.children].indexOf(label.querySelector('.wf-shelf-select')) + 1,
           value: label.querySelector('.wf-shelf-select').value };
};
"""


def test_the_open_workflow_s_last_run_is_said_beside_the_select(box):
    o = _case(box, _PICK + """
        const { root } = await room();
        const onTasks = pickOf(root);
        await openW(root);
        out({ onTasks, open: pickOf(root),
              row: root.querySelectorAll('.wf-shelf-item').find((b) => b.dataset.key === 'w1')
                .querySelector('.wf-shelf-last').textContent });
    """)
    assert o["onTasks"]["text"] == "", "Tasks and chains has no last run of its own"
    assert o["open"] == {"text": "Last run: Failed", "tone": "error", "afterSelect": True, "value": "w1"}
    assert o["open"]["text"] == o["row"], "the select's words are the row's"


def test_a_workflow_that_has_not_run_says_so(box):
    world = copy.deepcopy(_WORLD)
    world["workflows"][0]["last_run"] = None
    o = _case(box, _PICK + """
        const { root } = await room();
        await openW(root);
        out(pickOf(root));
    """, world)
    assert (o["text"], o["tone"]) == ("Not run yet", "none")


def test_it_follows_the_run_as_the_row_does(box):
    """`B1108` keeps the row current from the Runs list; the words beside the
    select are drawn from the same row, so they move with it."""
    o = _case(box, _PICK + """
        const { root } = await room();
        await openW(root);
        const before = pickOf(root).text;
        W.runs.unshift({ id: 'r3', task_id: 'tw1', status: 'waiting', started_at: '2026-09-30T09:00:00Z',
                         steps: [] });
        fire(root.querySelectorAll('.wf-tab').find((t) => t.textContent === 'Runs'), 'click');
        await settle(20);
        out({ before, after: pickOf(root).text });
    """)
    assert o["before"] == "Last run: Failed"
    assert o["after"] == "Last run: Waiting"


def test_the_words_are_drawn_at_phone_width_where_the_list_is_not():
    rules = css_rules(blank(ROOT / "static" / "style.css"))

    def display(selector, *, phone):
        found = [decl(body, "display") for sel, body in rules
                 if sel.split("{")[-1].strip() == selector and (PHONE in sel) == phone
                 and "@" not in sel.replace(PHONE, "")]
        return [d for d in found if d]

    assert display(".wf-shelf-pick-last", phone=False) == ["none"], "a desktop row says it already"
    assert display(".wf-shelf-pick-last", phone=True) == ["inline"]
    assert display(".wf-shelf-pick-last:empty", phone=True) == ["none"]
    # …because the list is what is hidden there.
    phone_list = [body for sel, body in rules if PHONE in sel and ".wf-shelf-list" in sel]
    assert any(decl(body, "display") == "none" for body in phone_list)
