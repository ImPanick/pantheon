# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-09`, browser half — the words the comparison puts on the screen.

`_skillDiffLines` is **executed under node** with the real source lifted out of
`static/js/skills.js`, not grepped (`Law 20`): the lines it returns are the
whole product of this row, and a test that only checked the string was present
would pass on a function that never reached it.

Why the caveat line is a test and not a comment: two runs of a sampled model
differ on their own. `temperature=0.3` in `_run_skill_test_once` and in
`_run_skill_test_job`, and no endpoint in this repo takes a seed
(`grep -n seed src/llm_core.py` → nothing). So a person looking at two
transcripts will see differences the edit did not cause, and the only defence
is that the panel says so — first, when the two texts are identical, and last,
when they are not.

The wiring assertions below use `js_function` for the reason the sibling file
records: the skill-test panel is a template string inside a card the shim
cannot parse, so the scope is resolved first and the assertion made inside it.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_a_draft_skill_is_uncatalogued_not_inactive import js_function  # noqa: E402
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILLS_JS = ROOT / "static" / "js" / "skills.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _lines(diff: dict) -> list:
    """Run the shipped `_skillDiffLines` on one payload, under node."""
    body = js_function(SKILLS_JS.read_text(encoding="utf-8"),
                       "function _skillDiffLines")
    script = textwrap.dedent("""\
        const _skillDiffLines = (diff) => {%s};
        const out = _skillDiffLines(%s);
        process.stdout.write(JSON.stringify(out));
    """) % (body, json.dumps(diff))
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _done(**over):
    d = {
        "same_text": False, "both_finished": True,
        "before_status": "done", "after_status": "done",
        "before_verdict": "needs_work", "after_verdict": "pass",
        "verdict_changed": True,
        "before_tools": ["bash"], "after_tools": ["bash"],
        "tools_added": [], "tools_removed": [], "tools_changed": False,
        "before_rounds": 2, "after_rounds": 2,
        "issues_resolved": [], "issues_introduced": [],
        "before_source": "earlier copy 0001-1.0.0",
        "after_source": "current version",
    }
    d.update(over)
    return d


def test_a_changed_verdict_is_said_in_the_first_person_of_the_edit():
    out = _lines(_done())
    assert any("verdict changed" in ln and "needs_work" in ln and "pass" in ln
               for ln in out), out


def test_an_unchanged_verdict_is_said_too_rather_than_left_blank():
    out = _lines(_done(before_verdict="pass", after_verdict="pass",
                       verdict_changed=False))
    assert any("did not change" in ln for ln in out), out


def test_identical_text_leads_with_the_noise_floor_and_not_with_the_result():
    """The control case. If the two halves ran the same bytes, every line under
    this one is the model answering twice — and a reader who meets that fact
    last has already believed the rest."""
    out = _lines(_done(same_text=True))
    assert "SAME skill text" in out[0]
    assert "not your edit" in out[0]


def test_an_unfinished_comparison_reports_waiting_and_stops():
    out = _lines(_done(both_finished=False, after_status="queued"))
    assert len(out) == 1
    assert "Not finished yet" in out[0]
    assert "current version" in out[0]
    # No verdict VALUE is claimed for a half that has not produced one — the
    # line says a verdict is missing, which is the opposite of asserting one.
    assert not any("pass" in ln or "needs_work" in ln for ln in out), out


def test_tool_changes_are_named_in_both_directions():
    out = _lines(_done(tools_changed=True, tools_added=["read_file"],
                       tools_removed=["bash"],
                       before_tools=["bash"], after_tools=["read_file"]))
    joined = " ".join(out)
    assert "now uses read_file" in joined
    assert "no longer uses bash" in joined


def test_the_same_tools_in_a_different_order_is_still_reported_as_different():
    out = _lines(_done(tools_changed=True, tools_added=[], tools_removed=[],
                       before_tools=["bash"], after_tools=["bash", "bash"]))
    assert any("different order or a different number of times" in ln for ln in out), out


def test_resolved_and_new_issues_are_both_listed():
    out = _lines(_done(issues_resolved=["step 2 is vague"],
                       issues_introduced=["metadata: tags too broad"]))
    joined = " ".join(out)
    assert "Fixed: step 2 is vague" in joined
    assert "New problem: metadata: tags too broad" in joined


def test_a_finished_comparison_of_different_text_ends_with_what_not_to_read():
    out = _lines(_done())
    assert "sampled" in out[-1]
    assert "verdict, the tools and the round count" in out[-1]


def test_no_tool_at_all_is_a_stated_outcome_and_not_an_empty_line():
    out = _lines(_done(before_tools=[], after_tools=[], tools_changed=False))
    assert any("Neither run used a tool" in ln for ln in out), out


# ── the three doors, resolved in scope ──────────────────────────────────────

def test_the_test_panel_offers_the_comparison_with_the_task_already_typed():
    """`P8-00`. The person is already looking at the task box; the comparison
    that matters is the one against the task they just wrote."""
    body = js_function(SKILLS_JS.read_text(encoding="utf-8"),
                       "async function _testSkill")
    assert "skill-test-compare" in body
    assert "_compareSkill(card, name, (taskEl && taskEl.value.trim()) || '')" in body


def test_saving_an_edit_offers_to_show_what_the_edit_changed():
    body = js_function(SKILLS_JS.read_text(encoding="utf-8"),
                       "async function _saveSkillEdit")
    assert "See what changed" in body
    assert "_compareSkill(null, name)" in body


def test_the_comparison_refuses_politely_when_there_is_nothing_to_compare():
    body = js_function(SKILLS_JS.read_text(encoding="utf-8"),
                       "async function _compareSkill")
    assert "no earlier copy of this skill yet" in body
    # And it says how to get one, rather than leaving a dead end.
    assert "Edit and save it once" in body


def test_the_gate_card_is_built_once_and_used_by_both_surfaces():
    """`Law 14`. Two sets of Allow/Deny buttons that could drift is exactly the
    shape this phase keeps finding."""
    src = SKILLS_JS.read_text(encoding="utf-8")
    assert src.count("function _skillApprovalBox") == 1
    assert src.count("'Allow once'") == 1
    assert src.count("/test-approval") == 1
    for scope in ("function _renderTestLog", "function _renderDiffHalf"):
        assert "_skillApprovalBox(" in js_function(src, scope), scope


# ── the panel itself, built and read back ───────────────────────────────────

_SIGS = [
    ("_skillDiffLines", "function _skillDiffLines", "diff"),
    ("_skillApprovalBox", "function _skillApprovalBox",
     "approval, name, { onAnswered, onError } = {}"),
    ("_renderDiffHalf", "function _renderDiffHalf",
     "title, source, log, approval, verdict, card, name, refresh"),
    ("_renderSkillDiff", "function _renderSkillDiff",
     "host, status, card, name, refresh"),
]


def _panel(sandbox, status):
    """Build the real comparison panel under the DOM shim and read it back.

    The four functions are reconstructed from the shipped source with their
    declared parameter lists, and each declaration is asserted to be present
    verbatim first — so a renamed parameter fails here rather than being
    silently re-declared into something that still passes.
    """
    src = SKILLS_JS.read_text(encoding="utf-8")
    parts = []
    for _name, sig, params in _SIGS:
        assert f"{sig}({params})" in src, f"{sig} signature moved"
        parts.append(f"function {sig.split()[-1]}({params}) {{{js_function(src, sig)}}}")
    (sandbox / "dom.mjs").write_text(_DOM)
    preamble = "import { installDom } from './dom.mjs';\ninstallDom();\n"
    return _run(sandbox, preamble, """
        const API = '';
        %s
        const host = document.createElement('div');
        _renderSkillDiff(host, %s, null, 'packer', () => {});
        const last = host.children[host.children.length - 1];
        const cols = (last && last.children.length === 2) ? last : null;
        console.log(JSON.stringify({
          head: host.children[0].textContent,
          lines: host.children.slice(1, cols ? -1 : undefined).map(n => n.textContent),
          before: cols ? cols.children[0].readable : '',
          after: cols ? cols.children[1].readable : '',
        }));
    """ % ("\n".join(parts), json.dumps(status)))


def _status():
    return {"diff": {
        "task": "pack a box", "model": "m1",
        "same_text": False, "both_finished": True,
        "before_status": "done", "after_status": "done",
        "before_verdict": "needs_work", "after_verdict": "pass",
        "before_summary": "step 2 was guesswork", "after_summary": "clean run",
        "verdict_changed": True,
        "before_tools": ["bash"], "after_tools": ["bash"],
        "tools_added": [], "tools_removed": [], "tools_changed": False,
        "before_rounds": 1, "after_rounds": 1,
        "issues_resolved": [], "issues_introduced": [],
        "before_source": "earlier copy 0001-1.0.0",
        "after_source": "current version",
        "before_log": [{"type": "say", "text": "I guessed at step two."}],
        "after_log": [{"type": "say", "text": "I followed step two exactly."}],
        "before_approval": None, "after_approval": None,
    }}


def test_each_half_is_drawn_in_its_own_column_with_its_own_source(tmp_path):
    out = _panel(tmp_path, _status())
    assert "earlier copy 0001-1.0.0" in out["before"]
    assert "I guessed at step two." in out["before"]
    assert "needs_work" in out["before"] and "step 2 was guesswork" in out["before"]
    assert "current version" in out["after"]
    assert "I followed step two exactly." in out["after"]
    assert "pass" in out["after"] and "clean run" in out["after"]
    # The two halves do not bleed into each other — a swap here would be a
    # silent lie about which text produced which run.
    assert "I followed step two exactly." not in out["before"]
    assert "I guessed at step two." not in out["after"]


def test_the_panel_states_the_one_task_and_the_one_model(tmp_path):
    out = _panel(tmp_path, _status())
    assert "Same task, same model (m1): pack a box" == out["head"]


def test_a_half_that_is_waiting_draws_its_own_gate_card(tmp_path):
    st = _status()
    st["diff"]["both_finished"] = False
    st["diff"]["before_status"] = "awaiting_approval"
    st["diff"]["before_verdict"] = None
    st["diff"]["before_approval"] = {
        "approval_id": "appr-1",
        "question": "Allow this exact action once?",
        "action": {"tool": "bash", "content": "rm -rf /tmp/x",
                   "effects": ["filesystem_write"]},
    }
    out = _panel(tmp_path, st)
    assert "Allow this exact action once?" in out["before"]
    assert "rm -rf /tmp/x" in out["before"]
    assert "filesystem_write" in out["before"]
    assert "Allow once" in out["before"] and "Deny" in out["before"]
    # The other half has no card of its own to answer.
    assert "Allow once" not in out["after"]


def test_before_it_starts_the_panel_says_so_rather_than_drawing_an_empty_grid(tmp_path):
    out = _panel(tmp_path, {})
    assert out["head"] == "Starting comparison…"


def test_the_plain_test_panel_still_draws_the_gate_card_from_the_same_builder(tmp_path):
    """The extraction that gave the comparison its gate card must not have
    taken the one the plain test panel has always drawn. Driven: build
    `_renderTestLog` under the shim with a paused job and read the card back."""
    src = SKILLS_JS.read_text(encoding="utf-8")
    sig = "function _renderTestLog(logEl, verdictEl, job, card, name)"
    assert sig in src, "the test-log renderer signature moved"
    approval_box = (
        "function _skillApprovalBox(approval, name, { onAnswered, onError } = {}) {"
        + js_function(src, "function _skillApprovalBox") + "}"
    )
    render = sig + "{" + js_function(src, "function _renderTestLog") + "}"
    (tmp_path / "dom.mjs").write_text(_DOM)
    out = _run(tmp_path, "import { installDom } from './dom.mjs';\ninstallDom();\n", """
        const API = '';
        const _testSkill = () => {};
        const _renderTestVerdict = () => {};
        %s
        %s
        const logEl = document.createElement('div');
        const job = {
          status: 'awaiting_approval',
          log: [{ type: 'say', text: 'thinking' }],
          approval: {
            approval_id: 'appr-1',
            question: 'Allow this exact action once?',
            action: { tool: 'bash', content: 'rm -rf /tmp/x' },
          },
        };
        _renderTestLog(logEl, document.createElement('div'), job, null, 'packer');
        console.log(JSON.stringify({ text: logEl.readable }));
    """ % (approval_box, render))
    assert "Allow this exact action once?" in out["text"]
    assert "rm -rf /tmp/x" in out["text"]
    assert "Allow once" in out["text"] and "Deny" in out["text"]
