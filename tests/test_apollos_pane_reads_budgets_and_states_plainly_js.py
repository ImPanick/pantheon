# SPDX-License-Identifier: AGPL-3.0-or-later
"""What Apollo's pane says, worked out: `static/js/apolloPaneModel.js`.

The pane draws only what these return, so each sentence a person reads in it
is asserted here: a budget in tokens people read (12k, 2M) with the paid-only
cap said plainly, a budget typed back in the same words, the Activity list
newest first with how many more, What Apollo knows split stated above
inferred, and the Computer card's words for the workstation's state.

Driven under node: the real module, imported as it ships (it has no imports).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODEL = (ROOT / "static" / "js" / "apolloPaneModel.js").as_uri()

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _eval(expr: str):
    script = f"const M = await import({json.dumps(MODEL)});\nconsole.log(JSON.stringify({expr}));\n"
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_budget_is_read_back_in_the_words_it_was_typed():
    assert _eval("['250k', '2M', '1.5m', '40,000', ' 12 000 ', '', 'lots', '-5'].map(M.parseBudget)") == [
        {"ok": True, "value": 250000}, {"ok": True, "value": 2000000}, {"ok": True, "value": 1500000},
        {"ok": True, "value": 40000}, {"ok": True, "value": 12000}, {"ok": True, "value": None},
        {"ok": False, "value": None}, {"ok": False, "value": None},
    ]


def test_the_budget_line_says_the_cap_counts_only_paid_models():
    lines = _eval("""[
      M.budgetLine({ spent_tokens: 12000, budget_tokens: 100000, budget_limit: 100000 }),
      M.budgetLine({ spent_tokens: 0, budget_tokens: null, budget_limit: 2000000 }),
      M.budgetLine({ spent_tokens: 500, budget_tokens: null, budget_limit: null }),
    ]""")
    assert lines == [
        "12k of 100k tokens on paid models. Local models run uncapped.",
        "0 of 2M tokens on paid models (the admin cap). Local models run uncapped.",
        "500 tokens on paid models, no limit set. Local models run uncapped.",
    ]


def test_activity_is_newest_first_with_how_many_more():
    got = _eval("""M.activityRows([
      { id: 'old', updated_at: '2026-11-20T00:00:00Z' },
      { id: 'new', updated_at: '2026-11-22T00:00:00Z' },
      { id: 'mid', updated_at: '2026-11-21T00:00:00Z' },
    ], { limit: 2 })""")
    assert [r["id"] for r in got["rows"]] == ["new", "mid"]
    assert got["more"] == 1


def test_needs_you_and_outputs_pick_their_own_tasks():
    got = _eval("""({
      needs: M.needsYou([{ id: 'a', state: 'working' }, { id: 'b', state: 'needs_you', updated_at: '2' },
                         { id: 'c', state: 'needs_you', updated_at: '1' }]).map((t) => t.id),
      outs: M.outputs([{ id: 'd', state: 'done', outcome: 'Filed it.', title: 'D' },
                       { id: 'e', state: 'done', outcome: '' }, { id: 'f', state: 'working', outcome: 'x' }]),
    })""")
    assert got["needs"] == ["c", "b"]
    assert got["outs"] == [{"id": "d", "title": "D", "outcome": "Filed it."}]


def test_what_apollo_knows_puts_what_you_said_first():
    got = _eval("""M.knowsGroups([
      { id: 1, basis: 'inferred', since: 3 }, { id: 2, basis: 'stated', since: 1 }, { id: 3, basis: 'stated', since: 5 },
    ])""")
    assert [l["id"] for l in got["stated"]] == [3, 2]
    assert [l["id"] for l in got["inferred"]] == [1]


def test_the_run_button_says_start_run_again_or_nothing():
    assert _eval("""[
      M.runVerb({ lead_agent: 'r', hire_id: null, state: 'waiting' }),
      M.runVerb({ lead_agent: 'r', hire_id: 'h', state: 'done' }),
      M.runVerb({ lead_agent: 'r', hire_id: 'h', state: 'working' }),
      M.runVerb({ lead_agent: null, state: 'waiting' }),
    ]""") == ["Start", "Run again", "", ""]


def test_the_computer_card_names_the_workstations_state():
    got = _eval("['up', 'down', 'off', 'unconfigured', 'not_permitted'].map((s) => M.computerCard({ state: s }))")
    assert [(c["label"], c["opens"]) for c in got] == [
        ("Running", True), ("Stopped", True), ("Off", False),
        ("Not set up", False), ("Not available to you", False),
    ]


def test_the_header_tone_follows_the_servers_state():
    assert _eval("""[
      M.headline({ status: { state: 'needs_you', words: 'Needs you on 2' } }),
      M.headline({ status: { state: 'working', words: 'Working on 1' } }),
      M.headline(null),
    ]""") == [{"words": "Needs you on 2", "tone": "needs"},
              {"words": "Working on 1", "tone": "working"},
              {"words": "Idle", "tone": "idle"}]


def test_a_task_chat_shows_what_was_said_and_skips_hidden_lines():
    got = _eval("""M.chatEntries([
      { role: 'user', content: 'Saturdays only', metadata: { _db_id: 7 } },
      { role: 'assistant', content: [{ type: 'text', text: 'Two are open.' }] },
      { role: 'assistant', content: 'internal', metadata: { hidden: true } },
      { role: 'tool', content: 'raw' },
      { role: 'assistant', content: '   ' },
    ]).map((e) => [e.role, e.text])""")
    assert got == [["user", "Saturdays only"], ["assistant", "Two are open."]]


def test_a_stream_is_read_line_by_line_and_keeps_its_unfinished_tail():
    got = _eval("""M.sseEvents('data: {"delta":"Hi"}\\n\\ndata: [DONE]\\ndata: not json\\ndata: {"del')""")
    assert got == {"events": [{"delta": "Hi"}], "rest": 'data: {"del'}


def test_an_approval_is_read_from_the_stream_and_from_saved_history():
    got = _eval("""[
      M.approvalOf({ type: 'ask_user', data: { kind: 'tool_approval', approval_id: 'a1', question: 'Allow?',
        options: [{ label: 'Allow for this task', value: 'approve_task' }, { label: 'Deny', value: 'deny' }] } }),
      M.approvalOf({ type: 'ask_user', data: { kind: 'question', approval_id: 'a2', options: [{ label: 'x', value: 'y' }] } }),
      M.approvalOf({ delta: 'hi' }),
      M.pendingApproval([
        { role: 'assistant', content: 'Allow?', metadata: { tool_events: [{ ask_user: { kind: 'tool_approval', approval_id: 'a3',
          question: 'Allow?', options: [{ label: 'Deny', value: 'deny' }] } }] } },
      ]),
      M.pendingApproval([
        { role: 'assistant', content: 'Allow?', metadata: { tool_events: [{ ask_user: { kind: 'tool_approval', approval_id: 'a4',
          resolved: true, options: [{ label: 'Deny', value: 'deny' }] } }] } },
      ]),
      M.pendingApproval([
        { role: 'assistant', content: 'Allow?', metadata: { tool_events: [{ ask_user: { kind: 'tool_approval', approval_id: 'a5',
          options: [{ label: 'Deny', value: 'deny' }] } }] } },
        { role: 'user', content: 'never mind' },
      ]),
    ]""")
    assert got[0] == {"id": "a1", "question": "Allow?", "options": [
        {"label": "Allow for this task", "decision": "approve_task"}, {"label": "Deny", "decision": "deny"}]}
    assert got[1] is None and got[2] is None
    assert got[3]["id"] == "a3"
    # Answered, or talked past: nothing waits.
    assert got[4] is None and got[5] is None


def test_the_phone_card_names_the_phone_and_says_why_it_is_not_there():
    got = _eval("""[
      M.phoneCard({ state: 'on', device: 'p9', devices: [{ id: 'p9', name: 'Pixel 9' }] }),
      M.phoneCard({ state: 'unavailable', why: 'This server has no KVM.' }),
      M.phoneCard(null),
    ]""")
    assert got[0] == {"label": "Running", "state": "on", "name": "Pixel 9", "sentence": "", "opens": True}
    assert got[1]["label"] == "Not available" and got[1]["sentence"] == "This server has no KVM."
    assert got[1]["opens"] is False and got[2]["name"] == "Phone"
