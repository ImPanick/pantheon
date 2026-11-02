# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-30` — `ledger_table`: the finance agents' table.

The audit (`P24-28`) named Bookkeeper, Invoicing, AP & Bills, Budget vs
Actuals, Cash-flow Forecaster, Tax Prep and Payroll Prep and said why none
could ship: Pantheon had no place for a row of money — a document is prose, a
note is a reminder, a file is the person's own. `core.database.LedgerEntry`
is that place and `ledger_table` the tool over it: add, list, sum, update,
delete, import; amounts positive, `kind` saying which way the money goes.

The gate reads its actions from the one table (`tool_capabilities`): list and
sum are private reads, add/update/import private writes, delete destructive.
The eval harness seeds a world's `ledger` and checks it after a run.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from src.agents import evals as E


def _call(**args) -> dict:
    from src.tools.ledger import do_ledger_table
    return asyncio.run(do_ledger_table(json.dumps(args), owner=E.EVAL_OWNER))


def test_a_line_is_added_listed_summed_updated_and_deleted():
    with E.isolated():
        added = _call(action="add", kind="bill", amount="1,200.00", counterparty="Hetzner",
                      category="hosting", date="2026-11-01", due="2026-11-15", memo="November servers")
        assert added["exit_code"] == 0 and added["id"]
        assert "open" in json.dumps(_call(action="list")), "a bill starts open"
        _call(action="add", kind="income", amount=3000, counterparty="Acme", category="sales", date="2026-11-03")
        _call(action="add", kind="expense", amount=49.99, counterparty="Figma", category="software", date="2026-11-04")
        listed = _call(action="list", kind="expense")
        assert listed["count"] == 1 and "Figma" in listed["results"]
        summed = _call(action="sum", group_by="category")
        assert summed["groups"]["hosting"]["total"] == 1200.0 and summed["groups"]["sales"]["net"] == 3000.0
        assert summed["groups"]["hosting"]["net"] == 0.0, "an open bill has not moved cash yet"
        paid = _call(action="update", id=added["id"][:8], status="paid")
        assert paid["exit_code"] == 0
        assert _call(action="sum", group_by="category")["groups"]["hosting"]["net"] == -1200.0
        by_month = _call(action="sum", group_by="month")
        assert by_month["groups"]["2026-11"]["count"] == 3
        gone = _call(action="delete", id=added["id"][:8])
        assert gone["exit_code"] == 0 and _call(action="list")["count"] == 2


def test_import_takes_many_rows_and_refuses_the_bad_ones_by_number():
    with E.isolated():
        out = _call(action="import", rows=[
            {"date": "2026-10-01", "kind": "expense", "amount": 10, "counterparty": "A"},
            {"date": "2026-10-02", "kind": "wages", "amount": 10},
            {"date": "2026-10-03", "kind": "income", "amount": "lots"},
            {"date": "2026-10-04", "kind": "payroll", "amount": 2500, "counterparty": "Dana"},
        ])
        assert out["imported"] == 2 and len(out["refused"]) == 2
        assert out["refused"][0].startswith("row 2:") and "kind is one of" in out["refused"][0]
        assert out["refused"][1].startswith("row 3:") and "amount is a number" in out["refused"][1]
        assert _call(action="list", **{"from": "2026-10-01", "to": "2026-10-31"})["count"] == 2


def test_refusals_are_sentences_and_a_bad_date_or_negative_amount_is_one():
    with E.isolated():
        assert "kind is one of" in _call(action="add", amount=5)["error"]
        assert "amount is required" in _call(action="add", kind="expense")["error"]
        assert "positive" in _call(action="add", kind="expense", amount=-5)["error"]
        assert "YYYY-MM-DD" in _call(action="add", kind="expense", amount=5, date="next tuesday")["error"]
        assert "not found" in _call(action="update", id="nope", status="paid")["error"]
        assert "Unknown action" in _call(action="explode")["error"]
        assert _call(action="list")["count"] == 0, "nothing refused was written"


def test_the_spellings_models_reach_for_land_on_the_same_actions():
    from src.tool_capabilities import _ACTION_ALIASES
    from src.tools.ledger import _ACTION_ALIASES as tool_aliases
    assert dict(_ACTION_ALIASES["ledger_table"]) == tool_aliases, "the gate and the tool read one table"
    with E.isolated():
        assert _call(action="record", kind="expense", amount=1, date="2026-01-01")["exit_code"] == 0
        assert _call(action="totals")["count"] == 1
        assert _call(action="show")["count"] == 1


def test_one_persons_ledger_is_not_anothers():
    from src.tools.ledger import do_ledger_table
    with E.isolated():
        asyncio.run(do_ledger_table(json.dumps({"action": "add", "kind": "income", "amount": 9, "date": "2026-01-01"}), owner="ada"))
        assert asyncio.run(do_ledger_table(json.dumps({"action": "list"}), owner="bob"))["count"] == 0
        assert asyncio.run(do_ledger_table(json.dumps({"action": "list"}), owner="ada"))["count"] == 1


def test_the_gate_reads_its_actions():
    from src.tool_capabilities import ToolEffect, capabilities_for_action
    reads = capabilities_for_action("ledger_table", json.dumps({"action": "sum"})).effects
    writes = capabilities_for_action("ledger_table", json.dumps({"action": "add", "kind": "expense", "amount": 1})).effects
    gone = capabilities_for_action("ledger_table", json.dumps({"action": "delete", "id": "x"})).effects
    bare = capabilities_for_action("ledger_table", "{}").effects
    assert reads == {ToolEffect.READ_PRIVATE} and bare == {ToolEffect.READ_PRIVATE}, "list is the default"
    assert ToolEffect.WRITE_PRIVATE in writes and ToolEffect.DESTRUCTIVE not in writes
    assert ToolEffect.DESTRUCTIVE in gone


def test_it_is_in_every_register_an_agent_tool_needs():
    from src.tool_policy import selectable_tool_names
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    from src.agent_tools import TOOL_TAGS
    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS
    from src.agent_loop import TOOL_SECTIONS
    from src.tool_security import _PLAN_MODE_KNOWN_MUTATORS
    assert "ledger_table" in selectable_tool_names()
    assert any(s["function"]["name"] == "ledger_table" for s in FUNCTION_TOOL_SCHEMAS)
    assert "ledger_table" in TOOL_TAGS and "ledger_table" in BUILTIN_TOOL_DESCRIPTIONS
    assert "ledger_table" in TOOL_SECTIONS and "ledger_table" in _PLAN_MODE_KNOWN_MUTATORS


def test_a_world_seeds_a_ledger_and_a_check_reads_it():
    from core.database import LedgerEntry
    with E.isolated() as (factory, data):
        db = factory()
        E._seed(db, E.EVAL_OWNER, {"ledger": [
            {"date": "2026-11-01", "kind": "bill", "amount": 120.5, "counterparty": "Hetzner", "category": "hosting",
             "due": "2026-11-15"}]}, data)
        assert db.query(LedgerEntry).filter(LedgerEntry.owner == E.EVAL_OWNER).count() == 1
        listed = _call(action="list", kind="bill", status="open")
        assert listed["count"] == 1 and "Hetzner" in listed["results"]
        got = E._check("ledger", {"contains": ["Hetzner", "open"], "lacks": ["void"], "count": 1},
                       db=db, owner=E.EVAL_OWNER, answer="", status="ok", world=E.World({}), notebook="",
                       project_root=data)
        assert got["ok"], got
        bad = E._check("ledger", {"contains": ["Linode"], "count": 2}, db=db, owner=E.EVAL_OWNER, answer="",
                       status="ok", world=E.World({}), notebook="", project_root=data)
        assert not bad["ok"] and "Linode" in bad["detail"] and "not 2" in bad["detail"]
        db.close()
