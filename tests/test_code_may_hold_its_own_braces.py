# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1882` (`picker-clipped-and-never-false-alarm`, the server's half) — a Code step's source may hold `{{` of its own, written `\{{`.

A setting only a person types (`never`) is refused at save when anything in
it reads as a reference (`workflow_refs.references_in_text`, fail closed).
For a Code step's source that refused real code with no way out: a Python
f-string's `f"{{item}}"` (the text `{item}`) reads as a reference to the
item. So there, and only there, `\{{` is the text `{{`: the reference after
it is passed over at save and at run, and the backslash is taken out before
the code runs (`unescape_references`) — what the gate is asked about, what an
Allow seals and what the workstation runs are the same text. The field says
so in its sentence (`workflow_slots.WHY_CODE`), and the palette marks the
slot (`escape: true`) so the browser's warning reads it the same way.

Who is the adversary (`Law 17`): a value from outside that reaches code. It
still cannot: the escape only makes a reference NOT a reference — nothing is
ever filled in a source — and every other `never` setting (an address, a
command, a recipient) still refuses `\{{ … }}` as before.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests.test_a_destination_is_never_mapped import after_fetch, step  # noqa: E402

from src import workflow_document as wd  # noqa: E402
from src import workflow_refs as wr  # noqa: E402
from src import workflow_slots as ws  # noqa: E402

# `{{item}}` is a reference (`item` is one of the grammar's roots); a
# `{{name}}` is not one and was never refused.
F_STRING = 'item = "Ada"\nprint(f"\\{{item}} is {item}")\n'
RUNS_AS = 'item = "Ada"\nprint(f"{{item}} is {item}")\n'


def _escapes(text):
    return [r.text for r in wr.references_in_text(text, escapes=True)]


# ── The escape, read ─────────────────────────────────────────────────────────

def test_a_reference_after_a_backslash_is_passed_over_only_when_asked():
    text = 'print(f"\\{{item}}")'
    assert [r.text for r in wr.references_in_text(text)] == ["{{item}}"]   # fail closed, as ever
    assert _escapes(text) == []


@pytest.mark.parametrize("text,found", [
    ('print(f"\\{{item}} {{ steps.a.data.x }}")', ["{{ steps.a.data.x }}"]),
    ("\\{{ item }} and {{ item }}", ["{{ item }}"]),
    ("{{ item }}\\{{ item }}", ["{{ item }}"]),
    ("docker ps --format '{{.Names}}'", []),
    ("a\\b {{ now | upper }}", ["{{ now | upper }}"]),
])
def test_only_the_reference_right_after_the_backslash_is_passed_over(text, found):
    assert _escapes(text) == found


@pytest.mark.parametrize("text,runs", [
    (F_STRING, RUNS_AS),
    ("\\{{ steps.a.data.x | default:\"x\" }}", "{{ steps.a.data.x | default:\"x\" }}"),
    ("a \\{{item}} b \\{{item}}", "a {{item}} b {{item}}"),
    # Not before a reference: the backslash is the code's own and stays.
    ("echo \\{{.Names}}", "echo \\{{.Names}}"),
    ('re.compile("\\{{2}")', 're.compile("\\{{2}")'),
    ("x = '\\\\n'", "x = '\\\\n'"),
])
def test_the_backslash_is_taken_out_only_before_a_reference(text, runs):
    assert wr.unescape_references(text) == runs


def test_source_with_no_escape_runs_exactly_as_it_was_typed():
    for text in ("print(1)", "echo '{{.Names}}'", "", None, 'a\\b'):
        assert wr.unescape_references(text) == text


# ── At save ──────────────────────────────────────────────────────────────────

def _code(source):
    return step("c", "code", language="python", source=source)


def test_an_escaped_f_string_in_a_code_steps_source_saves():
    assert after_fetch(_code(F_STRING)) is None


def test_the_same_f_string_unescaped_is_refused_with_how_to_write_it():
    refusal = after_fetch(_code(RUNS_AS))
    assert refusal is not None and refusal.reason == wd.REFUSE_MAPPED_NEVER
    assert refusal.field == "source"
    assert ws.WHY_CODE in refusal.sentence
    assert "write \\{{ there" in refusal.sentence and "taken out before it runs" in refusal.sentence


def test_an_escape_does_not_open_any_other_typed_only_setting():
    escaped = "\\{{ steps.fetch.data.x }}"
    for node, field in [
        (step("h", "http", integration="miniflux", method="GET", path="/v1/" + escaped), "path"),
        (step("m", "mcp", tool="mcp__chat__send_message", args={"channel": escaped, "text": "hi"}),
         "args.channel"),
        (step("a", "action", action="ssh_command", prompt="echo " + escaped), "prompt"),
        (step("c", "code", language="python", source="print(1)", timeout_seconds=30,
              input=[{"name": escaped, "value": "v"}]), "input[0].name"),
    ]:
        refusal = after_fetch(node)
        assert refusal is not None and refusal.reason == wd.REFUSE_MAPPED_NEVER, (field, refusal)
        assert refusal.field == field


def test_the_code_slot_is_the_one_that_takes_the_escape():
    assert ws.NODE_SLOTS["code"]["source"] == ws.NEVER_CODE
    assert ws.NEVER_CODE.mapping == ws.MAPPING_NEVER and ws.NEVER_CODE.why == ws.WHY_CODE
    assert ws.WHY_CODE in ws.WHYS
    others = [(kind, path) for kind, table in ws.NODE_SLOTS.items() for path, slot in table.items()
              if slot == ws.NEVER_CODE and (kind, path) != ("code", "source")]
    assert others == []


def test_the_palette_marks_the_code_source_as_taking_the_escape():
    from tests.helpers.workflow_cw_fake import real_palette
    kinds = {k["kind"]: k for k in real_palette()["kinds"]}
    assert kinds["code"]["slots"]["source"] == {"mapping": "never", "why": ws.WHY_CODE, "escape": True}
    marked = [(k, p) for k, entry in kinds.items() for p, s in (entry.get("slots") or {}).items()
              if s.get("escape")]
    assert marked == [("code", "source")]


def test_render_call_passes_an_escaped_source_and_still_refuses_a_bare_one():
    ctx = {"steps": {"fetch": {"data": {"x": "rm -rf ~"}, "text": ""}}}
    call = ws.render_call({"id": "c", "kind": "code", "config": {
        "language": "python", "source": F_STRING, "timeout_seconds": 30, "input": []}}, ctx)
    assert json.loads(call.content) == {}
    with pytest.raises(ws.SlotError):
        ws.render_call({"id": "c", "kind": "code", "config": {
            "language": "python", "source": RUNS_AS, "timeout_seconds": 30, "input": []}}, ctx)
    with pytest.raises(ws.SlotError):
        ws.render_call({"id": "c", "kind": "code", "config": {
            "language": "\\{{ steps.fetch.data.x }}", "source": "x", "timeout_seconds": 30}}, ctx)


# ── At run: the code that runs is the code that was asked about ─────────────

from tests.test_a_step_you_configured_runs import _strict, station, world  # noqa: E402,F401
from tests.helpers.walker_harness import (  # noqa: E402
    client_for, node, records_of, runs_of, seed_workflow, settle,
)


async def test_an_escaped_f_string_runs_with_its_braces_and_is_sealed_as_it_runs(world, station,
                                                                               monkeypatch):
    """The real walker and the real workstation daemon: the source runs with
    `\\{{` as `{{` — Python prints `{item} is Ada` — and at the strict rung
    the card shows, and an Allow seals and runs, that same text once."""
    w, execs = world, station
    source = 'import json\nitem = "Ada"\nprint(json.dumps({"said": f"\\{{item}} is {item}"}))\n'
    runs = 'import json\nitem = "Ada"\nprint(json.dumps({"said": f"{{item}} is {item}"}))\n'
    seed_workflow(w.factory, [node("code", "Say", "code", language="python", source=source)],
                  owner="alice")
    await w.s._execute_task("wf")
    [run] = runs_of(w.factory, "wf")
    assert run["status"] == "success", run
    assert [e["command"] for e in execs] == [runs]
    [rec] = records_of(w.factory, run["id"])
    assert rec["output"]["data"] == {"said": "{item} is Ada"}

    execs.clear()
    _strict(monkeypatch)
    await w.s._execute_task("wf")
    run = runs_of(w.factory, "wf")[1]
    assert run["status"] == "waiting" and execs == []
    card = records_of(w.factory, run["id"])[0]["waiting"]["approval"]
    assert card["action"]["content"] == runs
    async with client_for(w.app) as client:
        res = await client.post(f"/api/workflows/w-wf/runs/{run['id']}/answer",
                                headers={"x-test-user": "alice"},
                                json={"node_id": "code", "approval_id": card["approval_id"],
                                      "decision": "approve_task"})
    assert res.status_code == 200
    await settle(w.s)
    assert [e["command"] for e in execs] == [runs]
    assert runs_of(w.factory, "wf")[1]["status"] == "success"
