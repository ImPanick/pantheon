# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-27` — a case that breaks while its world is being set up leaves no
part of that world behind.

Found running the measured-agent tests beside this slice's harness change.
`run_case` patches the install into a world — the tool executor, the
loopback guard on every HTTP client, the admin checks, the model call —
before its `try`, and undoes them only in that `try`'s `finally`. A case that
broke in between (here, a model spy with the old one-argument signature)
raised with every patch still in place: every later case in the process, and
every later test, ran half inside a dead world — HTTP refused "in the world's
words", `search_hf_models` answered from a hub nobody gave. Now the setup is
undone whatever breaks.

And the scripted model is called as it always was, with the script alone:
the world's projects folder is put into the script's calls before it.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from src.agents import evals as E
from src.agents.catalogue import get_agent
import src.tool_execution as tool_execution


def test_a_case_that_breaks_in_setup_undoes_its_world(monkeypatch):
    real_impl = tool_execution._execute_tool_block_impl
    real_send = httpx.AsyncClient.send

    def broken(script):
        raise RuntimeError("the model could not be made")

    monkeypatch.setattr(E, "scripted_model", broken)
    m = get_agent(None, "topic-watcher")
    with pytest.raises(RuntimeError, match="could not be made"):
        asyncio.run(E.run_agent(m, cases=[E.load_evals(m)[0]]))
    assert tool_execution._execute_tool_block_impl is real_impl, "the world's tool executor outlived its case"
    assert httpx.AsyncClient.send is real_send, "the world's loopback guard outlived its case"


def test_the_scripted_model_is_made_from_the_script_alone(monkeypatch):
    """A spy written for `scripted_model(script)` still works, and a call's
    `$WORLD_PROJECTS` reaches the model as the world's projects folder."""
    made = []
    real = E.scripted_model

    def spying(script):
        made.append(script)
        return real(script)

    monkeypatch.setattr(E, "scripted_model", spying)
    m = get_agent(None, "rag-builder")
    case = {"id": "drive", "world": {"files": {"docs/a.md": "x"}, "rag": {}},
            "inputs": {"folder": "docs", "questions": "Anything?"},
            "script": [{"call": [["manage_rag", {"action": "add_directory", "directory": "$WORLD_PROJECTS/docs"}]]},
                       {"say": "Done."}],
            "checks": [{"called": "manage_rag"}]}
    asyncio.run(E.run_agent(m, cases=[case]))
    (script,) = made
    folder = script[0]["call"][0][1]["directory"]
    assert E.WORLD_PROJECTS not in folder and folder.endswith("/docs"), folder
