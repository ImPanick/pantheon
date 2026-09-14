# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B06` — the approved plan reached the backend once and never again.

`chat.js` held the approved plan in a module-level `let`, appended it to the
first turn's form and then blanked it. Every continuation turn — the
`Continue ▸` button that appears on `rounds_exhausted`, and any follow-up the
user simply types — sent no `approved_plan` at all.

**The row's `Verify` line passes today and always did**, which is the finding
worth keeping. It asks that *"a plan run that takes four rounds has the
checklist in the verifier's instruction on all four"*. "Round" in this codebase
means a tool iteration inside one HTTP request (`agent_loop.py`'s
`for round_num in range(1, max_rounds + 1)`), and `_verifier_instruction` is
built once per request **above** that loop and never reassigned inside it. So
the stated Verify was satisfied by a defect-free property, and implementing it
would have ticked the row on a passing observation. The defect is about
**turns**.

And the verifier is the smallest part of what was lost — it is opt-in and off
by default. Three other things went with it on turn two:

  * **The pinned plan.** `build_active_plan_note` returns `""`, so nothing is
    injected. That function's own docstring states the contract the frontend
    was breaking: *"Sent back by the frontend each turn so a long plan on a
    weak model survives history truncation — the agent can always re-read it."*
  * **Agent-mode forcing** at the send site.
  * **Tool schemas on Pantheon-finetuned local models** — three
    `route_mcp_schemas` branches in `agent_loop.py` carry `and not
    approved_plan`, so a continuation turn with a document open ran with none.

It was also a second plan store, and the only one that did not survive a
reload: the plan itself lives in `localStorage` via `planWindow`.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "harness" / "approved_plan_per_turn.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not on PATH"
)


def _run(mode: str) -> dict:
    result = subprocess.run(
        ["node", str(HARNESS), mode],
        capture_output=True, text=True, cwd=str(ROOT), timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_plan_is_sent_on_every_turn_not_just_the_first():
    """Run the real send block twice against one closure and look at turn two.

    This is the row's actual subject, stated as the row should have stated it.
    """
    out = _run("executing")
    assert out["turn1_has_plan"] is True
    assert out["turn2_has_plan"] is True, (
        "turn two sent no approved_plan — the agent has lost the checklist it "
        "is executing, and build_active_plan_note will return empty"
    )


def test_agent_mode_is_still_forced_on_the_second_turn():
    out = _run("executing")
    assert out["turn1_mode"] == "agent"
    assert out["turn2_mode"] == "agent"


def test_a_finished_or_cleared_plan_stops_being_sent():
    """The opposite failure, and it is a real one: a plan that keeps going out
    after it is done leaks into unrelated later messages."""
    out = _run("idle")
    assert out["turn1_has_plan"] is False
    assert out["turn2_has_plan"] is False


def test_there_is_one_plan_store_and_chat_js_does_not_hold_a_copy():
    """`Law 13`. The module-level copy was the only one that did not survive a
    reload. Read as code rather than text — comments naming the old variable
    are the record of why it went, not a second copy of it."""
    import re

    source = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    code = re.sub(r"(?m)^\s*//.*$", "", source)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    assert "_pendingApprovedPlan" not in code


def test_the_executing_predicate_is_not_a_second_copy_of_the_binding_rule():
    """`Law 14`. `planWindow.isExecuting()` IS what tool binding consults; it
    was that function's private body and is now exported once."""
    import re

    source = (ROOT / "static" / "js" / "planWindow.js").read_text(encoding="utf-8")
    assert "export function isExecuting()" in source
    body = source.split("function bindingAllowed()", 1)[1].split("}", 1)[0]
    assert "isExecuting()" in body, (
        "bindingAllowed has grown its own copy of the rule again"
    )
    assert len(re.findall(r"_meta\.approvedAt \|\| isPlanModeOn\(\)", source)) == 1
