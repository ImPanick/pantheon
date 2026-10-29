# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1658` — the Workshop tells the drafting model what each tool's calls can
carry, so a drafted table decides every row its hire form will draw.

*Describe it* and *Build it by talking* (`src/agents/workshop.py`) hand the
model a palette — every tool with its effects — and the rule *"Name every
effect of every tool you chose."* The palette read each tool's registration
(`capabilities_for_tool`), so `bash` was `execute_code` alone. A shell call
that deletes is `destructive` (`B1622`) and one that reaches the network is
`network_egress` (`B1652`), and the hire form draws both rows
(`hires.tool_effects`, `B1629`) — so a draft that did exactly what it was told
left both to the cautious default, decided by nobody. **Measured on
`43eb2626`:** the palette's `bash` was `["execute_code"]`, and 21 of the 90
selectable tools' entries were narrower than their rows on the form — `bash`
and `python` (`destructive`, `network_egress`), `host_shell`, `shell_with_login`,
and every `manage_*` tool's delete and private read.

Now the palette is the form's rows (`hires.tool_effects`), and the rule says
to name those and no other (`B1659` refuses a row no call can trip).

Driven (`Law 20`): the real `/api/agents/draft`, `/api/agents/own` and
`/api/agents/{id}` routes on a real SQLite file, with the model stood in by a
function that reads the palette it was sent and does what the rules say.
"""

from __future__ import annotations

import json

from src.agents import hires as H
from src.agents import workshop as W
from src.agents.catalogue import get_agent

from tests.test_a_hire_compiles_to_tasks import call, client  # noqa: F401  (fixture)
from tests.test_a_workflow_is_kept_as_one_document import (  # noqa: F401  (fixtures)
    admins, sched, wf_db,
)

# What the stand-in model decides for each effect it is told a tool has: a
# local shell job runs code, asks before it deletes, and never reaches out.
_DECIDES = {"execute_code": "allow", "destructive": "ask", "network_egress": "never",
            "read_workspace": "allow", "write_workspace": "allow"}


def _palette(messages):
    sent = next(m["content"] for m in messages if m["content"].startswith("The palette:\n"))
    return json.loads(sent.split("The palette:\n", 1)[1].split("\n\n", 1)[0])


def _shell_agent(palette):
    """A model that follows the rules: the tool it chose, and every effect the
    palette lists for it, decided."""
    bash = next(t for t in palette["tools"] if t["name"] == "bash")
    return {"id": "log-sweeper", "name": "Log Sweeper", "tagline": "Sweeps old logs out of the project.",
            "section": palette["sections"][0], "inputs": [],
            "triggers": [{"on": "hand"}], "tools": ["bash"],
            "delivers": [{"kind": "answer", "must_contain": ["Swept"]}],
            "effects": {e: _DECIDES.get(e, "ask") for e in bash["effects"]},
            "budget": {"runs_per_day": 1}, "memory": "none",
            "runbook": ["Run bash to list the log files older than a week in the project.",
                        "Write the answer under the heading Swept, naming each one, and stop."]}


def _model(seen):
    async def fake(owner, messages, *, max_tokens):
        seen.append(messages)
        return _shell_agent(_palette(messages)), None
    return fake


# ── the row's `Verify:` ─────────────────────────────────────────────────────

def test_the_palettes_bash_names_what_its_calls_carry():
    bash = next(t for t in W.palette()["tools"] if t["name"] == "bash")
    assert bash["effects"] == H.tool_effects("bash")
    assert {"execute_code", "destructive", "network_egress"} <= set(bash["effects"])


def test_a_drafted_shell_agents_table_decides_them_and_its_form_draws_its_rules(client, monkeypatch):
    import src.workflow_assist as wa
    seen = []
    monkeypatch.setattr(wa, "ask_for_json", _model(seen))
    drafted = call(client, "POST", "/api/agents/draft",
                   json={"description": "Sweep old logs out of my project when I ask."})
    assert drafted.status_code == 200 and drafted.json()["ok"] is True, drafted.text
    text = drafted.json()["text"]
    table = W.check(text).effects
    assert (table["destructive"], table["network_egress"]) == ("ask", "never"), table

    saved = call(client, "POST", "/api/agents/own", json={"text": text})
    assert saved.status_code == 200, saved.text
    page = call(client, "GET", "/api/agents/log-sweeper").json()
    assert page["effects"] == {"destructive": "ask", "execute_code": "allow", "network_egress": "never"}, \
        "every row the form draws is the table's own rule — none fell to the default"
    assert get_agent("alice", "log-sweeper").source == "own"


def test_talking_it_through_is_told_the_same(client, monkeypatch):
    import src.workflow_assist as wa
    seen = []

    async def fake(owner, messages, *, max_tokens):
        seen.append(messages)
        return {"reply": "Built.", "ready": True, "agent": _shell_agent(_palette(messages))}, None

    monkeypatch.setattr(wa, "ask_for_json", fake)
    got = call(client, "POST", "/api/agents/interview",
               json={"messages": [{"role": "user", "content": "sweep my logs"}]}).json()
    assert got["proposal"]["ok"] is True, got
    assert got["proposal"]["summary"]["asks_before"] == ["destructive"]
    assert got["proposal"]["summary"]["never"] == ["network_egress"]
    assert "Name every effect the palette lists" in seen[0][0]["content"]


# ── the palette is the form's rows, for every tool ──────────────────────────

def test_every_tool_in_the_palette_lists_its_rows_on_the_hire_form():
    for tool in W.palette()["tools"]:
        assert tool["effects"] == H.tool_effects(tool["name"]), tool["name"]


def test_a_table_that_names_what_the_palette_lists_passes_its_check():
    """What the palette tells a draft to name is never what the check then
    refuses (`B1659`), for any one tool it lists."""
    template = W.render(_shell_agent({"tools": [{"name": "bash", "effects": []}],
                                      "sections": [W.palette()["sections"][0]]}))
    refused = {}
    for tool in W.palette()["tools"]:
        effects = "{" + ", ".join(f"{e}: ask" for e in tool["effects"]) + "}"
        text = (template.replace("tools: [bash]", f"tools: [{tool['name']}]")
                .replace("effects: {}", f"effects: {effects}"))
        try:
            W.check(text)
        except Exception as e:  # noqa: BLE001 — collected and named below
            refused[tool["name"]] = str(e)
    assert refused == {}
