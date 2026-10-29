# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1672` — a write that only adds to the end of a file is a plain write, so
Receipt Collector's unattended sweeps finish.

Measured before the fix: Receipt Collector kept its ledger by reading it and
`write_file`-ing the whole of it back with the new rows. The ledger was there
before the run, so that write carried `destructive` (`B1660`), and its table's
`destructive: ask` — a shipped `allow` is forbidden (`test_the_roster_is_shipped`)
— parked every sweep after the first on a card: its eval case
`the-ledger-only-grows` answered `approve_task`. `write_file` had no way to
add to a file; its kit has no shell, and a shell's `>>` would cost its seal
(`execute_code` is a way out, `runtime.SEALING_EFFECTS`) and ask before every
command once it has read a mail.

The owner's ruling (`D-2026-10-29-03` §2), *"Append-only is not
destructive"*: a write that only adds to the end of a file that was there — a
shell `>>`, or an append mode — is a plain write. So `write_file` takes
`"append": true` (`filesystem_tools._write_file_call`, the one reading the
tool, the workstation's and the gate share): the body goes on the end and
every byte the file had stays, on this machine (`open(…, "a")`) and in the
workstation (the daemon's own `append`, in its protocol from the start). The
gate reads it as replacing nothing (`run_files.replaces`). Receipt Collector
appends its new rows (1.3.0 → 1.4.0), and its sweep asks nothing.

Driven (`Law 20`): the real gate and dispatcher running the real `write_file`,
the model's native call as the loop turns it into a block, the real
workstation daemon, and Receipt Collector's sweeps through the real
evaluation harness — scheduler, loop, gate and the approval route.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.agents import evals as E
from src.agents.catalogue import get_agent
from src.run_files import RunFiles, bind_run_files
from src.tool_capabilities import ToolRunSecurityContext, call_destroys, capabilities_for_action
from src.tool_parsing import _raw_openai_tool_call_to_block
from src.tool_schemas import function_call_to_tool_block
from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _call, _home, _on, people, settings, ws,
)

NOTES = "Ana's notes — keep these\n"


def _write(path: str, text: str, append: bool = False) -> str:
    args = {"path": path, "content": text}
    if append:
        args["append"] = True
    return json.dumps(args)


@pytest.fixture
def folder(tmp_path):
    ws_ = tmp_path / "proj"
    ws_.mkdir()
    (ws_ / "notes.md").write_text(NOTES, encoding="utf-8")
    return ws_


def _effects(content: str, files: RunFiles) -> set:
    return {e.value for e in capabilities_for_action("write_file", content, files=files).effects}


def test_an_append_onto_a_file_that_was_there_replaces_nothing(folder):
    files = RunFiles(str(folder), "boss")
    assert _effects(_write("notes.md", "more\n", append=True), files) == {"write_workspace"}
    assert call_destroys("write_file", _write("notes.md", "more\n", append=True), files) is None
    assert _effects(_write("notes.md", "gone\n"), files) == {"write_workspace", "destructive"}, \
        "a whole write over it is still a replacement (`B1660`)"


def _run_write(run: ToolRunSecurityContext, folder: Path, content: str) -> dict:
    async def go():
        bind_run_files(run.files)
        return await te.execute_tool_block(ToolBlock("write_file", content), owner="boss",
                                           workspace=str(folder), security_context=run)
    return asyncio.run(go())[1]


def _never(files: RunFiles) -> ToolRunSecurityContext:
    """A hire's `destructive: never`, each call in a run of its own so a tool
    result before it (`FORBIDDEN.md` Part 2's gate) does not stand in front."""
    return ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=files)


def test_a_hires_never_appends_and_every_byte_the_file_had_stays(folder, people):
    files = RunFiles(str(folder), "boss")
    added = _run_write(_never(files), folder, _write("notes.md", "a line more\n", append=True))
    assert added.get("exit_code") == 0, added
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES + "a line more\n"
    assert added["output"].startswith("Added 12 bytes to the end of ")
    assert added["diff"]["added"] == 1 and added["diff"]["removed"] == 0, added["diff"]
    assert added["diff"]["text"].endswith("\n Ana's notes — keep these\n+a line more")
    refused = _run_write(_never(files), folder, _write("notes.md", "gone\n"))
    assert refused.get("blocked") is True and "never allows destructive" in refused["error"], refused
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES + "a line more\n"
    made = _run_write(_never(files), folder, _write("log.txt", "first\n", append=True))
    assert made.get("exit_code") == 0 and (folder / "log.txt").read_text(encoding="utf-8") == "first\n"


def test_the_models_native_call_reaches_the_tool_as_an_append(folder, people):
    """The loop turns a native call into a block (`function_call_to_tool_block`,
    and a raw call leaked into text, `tool_parsing`): an append rides as the
    JSON the tool reads it from; a plain write keeps its old shape."""
    block = function_call_to_tool_block(
        "write_file", json.dumps({"path": "notes.md", "content": "more\n", "append": True}))
    assert json.loads(block.content) == {"path": "notes.md", "content": "more\n", "append": True}
    plain = function_call_to_tool_block("write_file", json.dumps({"path": "a.md", "content": "x"}))
    assert plain.content == "a.md\nx"
    # A raw call leaked into the model's text is turned into a block the same way.
    leaked = _raw_openai_tool_call_to_block({"function": {"name": "write_file", "arguments": json.dumps(
        {"path": "notes.md", "content": "more\n", "append": True})}})
    assert leaked.content == block.content
    assert _run_write(_never(RunFiles(str(folder), "boss")), folder,
                      block.content).get("exit_code") == 0
    assert (folder / "notes.md").read_text(encoding="utf-8") == NOTES + "more\n"


def test_in_the_workstation_the_daemon_appends_and_nothing_is_asked(ws, settings, people):
    """The daemon's own append keeps the file; the gate needs to ask the
    workstation nothing — an append replaces nothing wherever it is."""
    _on(settings, ws)
    home = _home(ws, "ann")
    home.mkdir(parents=True, exist_ok=True)
    (home / "notes.md").write_text(NOTES, encoding="utf-8")
    files = RunFiles(None, "ann")
    assert files.in_workstation()
    run = ToolRunSecurityContext(hire_never_effects=frozenset({"destructive"}), files=files,
                                 approval_gate_bypassed=True)
    content = _write("notes.md", "from the run\n", append=True)
    asyncio.run(files.look("write_file", content))
    assert files.seen == {}, "nothing to ask"

    async def go():
        bind_run_files(files)
        return await te.execute_tool_block(ToolBlock("write_file", content), owner="ann",
                                           security_context=run)
    added = asyncio.run(go())[1]
    assert added.get("ran_in") == "workstation" and added.get("exit_code") == 0, added
    assert (home / "notes.md").read_text(encoding="utf-8") == NOTES + "from the run\n"
    assert run.decision_for("write_file", _write("notes.md", "gone\n")).allowed is False


# ── Receipt Collector, through the real harness ─────────────────────────────

@pytest.fixture
def cards(monkeypatch):
    """Every approval card the run makes: its tool and its sentence."""
    from src.tool_approvals import ToolApprovalStore
    made = []
    create = ToolApprovalStore.create

    def keep(self, *args, **kwargs):
        pending = create(self, *args, **kwargs)
        made.append((kwargs.get("tool_name"), getattr(kwargs.get("gate_decision"), "reason", None)))
        return pending

    monkeypatch.setattr(ToolApprovalStore, "create", keep)
    return made


def _collector():
    return get_agent(None, "receipt-collector")


def _case(case_id: str) -> dict:
    return copy.deepcopy(next(c for c in E.load_evals(_collector()) if c["id"] == case_id))


LEDGER = "date,merchant,amount,currency,reference,file,uid\n2026-10-02,Bakery,50.00,GBP,#77,,r0\n"
ROWS = ("2026-10-25,Coffee Co,4.50,GBP,#8812,,r1\n"
        "2026-10-26,Hostly,12.00,USD,INV-42,receipts/invoice-42.pdf,r2\n")


def _two_receipts() -> dict:
    """The row's `Verify:`: a sweep that adds two receipts to a ledger that
    was there — the shipped case's two mails, onto its ledger of one row."""
    two = _case("two-receipts-start-a-ledger")
    grows = _case("the-ledger-only-grows")
    script = [step for step in two["script"] if "say" not in step]
    ls_at = next(i for i, s in enumerate(script) if s["call"][0][0] == "ls")
    script.insert(ls_at + 1, {"call": [["read_file", {"path": "money/ledger.csv"}]]})
    write = next(s for s in script if s["call"][0][0] == "write_file")
    write["call"][0][1] = {"path": "money/ledger.csv", "content": ROWS, "append": True}
    say = next(step for step in two["script"] if "say" in step)
    return {"id": "two-receipts-onto-a-ledger-that-was-there",
            "about": "B1672: two rows appended to a ledger that was there, nothing asked.",
            "inputs": two["inputs"], "world": {**two["world"], "files": grows["world"]["files"]},
            "script": script + [say],
            "checks": [{"file": {"path": "money/ledger.csv", "contains": [LEDGER + ROWS]}},
                       {"status": "success"}]}


def _run(case: dict):
    (result,) = asyncio.run(E.run_agent(_collector(), cases=[case]))
    return result


def test_a_sweep_that_adds_two_receipts_finishes_unattended(cards):
    result = _run(_two_receipts())
    assert result.passed, result.checks
    assert result.status == "success"
    assert cards == [], "an append asks nothing"
    assert result.calls.count("write_file") == 1


def test_its_shipped_case_the_ledger_only_grows_asks_nothing(cards):
    case = _case("the-ledger-only-grows")
    assert "answers" not in case, "the case answers no card"
    result = _run(case)
    assert result.passed, result.checks
    assert cards == []


def test_the_control_a_whole_rewrite_of_the_ledger_still_waits_for_a_yes(cards):
    """Its table still asks before a replacement: the same sweep writing the
    whole ledger back parks on the card naming it, and with no one to answer
    the ledger is as it was."""
    case = _two_receipts()
    write = next(s for s in case["script"] if "call" in s and s["call"][0][0] == "write_file")
    write["call"][0][1] = {"path": "money/ledger.csv", "content": LEDGER + ROWS}
    result = _run(case)
    assert not result.passed
    assert result.status != "success"
    assert cards == [("write_file", "This agent's hire asks before destructive: 'write_file' waits "
                                    "for your yes (write_file replaces money/ledger.csv, which was "
                                    "there before this run began).")]
