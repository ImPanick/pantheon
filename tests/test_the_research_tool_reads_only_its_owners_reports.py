# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1601` — the agent's `manage_research` lists, reads and deletes only the
reports of the person it runs for.

**Measured before the fix** (`P24-27`'s audit): `src/tools/research.py`
`do_manage_research` globbed every `deep_research/*.json` and read or unlinked
any id it was handed, so a member's agent listed, read and deleted every other
person's reports — the rule the Library's own routes have held since the route
half was fixed (`routes/research/research_routes.py`: a report without the
caller as its `owner` is not there). The tool is the same door by another name.

Driven against the real function over a temp research folder: two people's
reports, and a legacy report with no owner, which the routes hide too.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from src.tools import research


@pytest.fixture()
def store(tmp_path, monkeypatch):
    d = tmp_path / "deep_research"
    d.mkdir()
    for rid, owner, query in (("ann1", "ann", "ann's question"), ("bob1", "bob", "bob's question"),
                              ("old1", None, "a report from before owners")):
        body = {"query": query, "summary": f"{query} — the answer", "sources": [], "completed_at": 1}
        if owner:
            body["owner"] = owner
        (d / f"{rid}.json").write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(research, "DEEP_RESEARCH_DIR", str(d))
    return d


def _run(args: dict, owner):
    return asyncio.run(research.do_manage_research(json.dumps(args), owner=owner))


def test_the_list_holds_only_the_callers_reports(store):
    out = _run({"action": "list"}, "ann")["output"]
    assert "ann's question" in out
    assert "bob's question" not in out and "before owners" not in out


def test_another_persons_report_is_not_found_and_not_read(store):
    out = _run({"action": "read", "id": "bob1"}, "ann")
    assert "error" in out and "not found" in out["error"]
    assert "bob's question" not in json.dumps(out)
    assert "ann's question" in _run({"action": "read", "id": "ann1"}, "ann")["output"]


def test_another_persons_report_is_not_deleted(store):
    out = _run({"action": "delete", "id": "bob1"}, "ann")
    assert "error" in out and "not found" in out["error"]
    assert (store / "bob1.json").exists()
    assert _run({"action": "delete", "id": "ann1"}, "ann")["exit_code"] == 0
    assert not (store / "ann1.json").exists()


def test_a_legacy_report_with_no_owner_is_nobodys_to_read_or_delete(store):
    for action in ("read", "delete"):
        out = _run({"action": action, "id": "old1"}, "ann")
        assert "error" in out, (action, out)
    assert (store / "old1.json").exists()


def test_with_nobody_to_scope_by_the_tool_refuses_in_a_sentence(store):
    for action in ("list", "read", "delete"):
        out = _run({"action": action, "id": "ann1"}, None)
        assert "error" in out and "person" in out["error"], (action, out)
    assert (store / "ann1.json").exists()
