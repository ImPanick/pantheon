# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1398`. The prompt registers are not a place to keep notes.

`fx11-ids` closed `B1297` — 137 unmapped lane ids in comments, down to zero —
and `tokenize` + `ast` found that **one of the 175 sites was not a comment at
all**. It was the last sentence of `TOOL_SECTIONS["web_search"]`:

    web_search is one quick query.  (`B1304`: this sentence used to name that
    tool, on every turn, whether or not the request carried it.)

Every character of `TOOL_SECTIONS` is shipped to the model as that tool's own
prose, so 104 characters of Pantheon's defect history reached the model on
every turn that carried web search — with nothing in the tree to read it
(`_PROMISED_TOOL_RE` cannot match a `B` id). It is noise on a strong model and
an instruction to interpret on a weak one, and neither is what a tool
description is for (`Law 10`).

Driving the property rather than the instance (`Law 20`, `Law 14`): the
registers the model reads may not carry a tracker id, a lane name or a
`Law`/phase reference, whatever a future note-leaving commit intends. The
place for that record is a `#` comment beside the register, which is where
this one now lives.
"""

from __future__ import annotations

import re

import pytest

import src.agent_loop as al
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS


#: A tracker id (`B1304`, `P23-06`, `H09`, `D-2026-10-09-01`), a lane name
#: (`fx11-ids`, `ws-shell`), or a Law reference. Each is a thing the project
#: says to itself. Word-bounded, so ordinary prose and a model name like
#: `pantheon-qwen3-8b` do not match.
PROJECT_TALK = re.compile(
    r"(?<![A-Za-z0-9_])("
    r"B-NEW"
    r"|B\d{2,4}"
    r"|P\d{1,2}-\d{2}[a-z]?"
    r"|H\d{2}"
    r"|D-\d{4}-\d{2}-\d{2}-\d{2}"
    r"|fx\d{0,2}-[a-z]+"
    r"|Law \d{1,2}"
    r")(?![A-Za-z0-9_])"
)


def _hits(text: str) -> list:
    return sorted({m.group(1) for m in PROJECT_TALK.finditer(str(text or ""))})


def test_no_tool_section_sends_the_model_a_tracker_id():
    """The register the fenced route reads, every entry."""
    offenders = {
        name: _hits(prose)
        for name, prose in al.TOOL_SECTIONS.items()
        if _hits(prose)
    }
    assert offenders == {}, offenders


def test_no_domain_rule_block_sends_the_model_a_tracker_id():
    """The per-domain rules blocks ship the same way."""
    rules = getattr(al, "_DOMAIN_RULES", None) or getattr(al, "DOMAIN_RULES", None)
    if rules is None:
        pytest.skip("this tree keeps the domain rules under another name")
    offenders = {d: _hits(t) for d, t in rules.items() if _hits(t)}
    assert offenders == {}, offenders


def test_no_function_schema_sends_the_model_a_tracker_id():
    """The register the native route reads — descriptions and every nested
    parameter description, because the model is sent the whole object."""
    def walk(node, path="") -> list:
        found = []
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("description", "title") and isinstance(v, str):
                    for hit in _hits(v):
                        found.append((path + "." + k, hit))
                else:
                    found.extend(walk(v, path + "." + str(k)))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                found.extend(walk(v, f"{path}[{i}]"))
        return found

    offenders = []
    for schema in FUNCTION_TOOL_SCHEMAS:
        name = (schema.get("function") or {}).get("name", "?")
        offenders.extend((name, where, hit) for where, hit in walk(schema))
    assert offenders == [], offenders


def test_the_assembled_prompt_carries_none_of_it():
    """End to end, on the prompt the product actually builds — so a register
    this file does not know about cannot carry one in either."""
    for compact in (False, True):
        prompt = al._assemble_prompt(set(al.TOOL_SECTIONS), set(), compact=compact)
        assert _hits(prompt) == [], (compact, _hits(prompt))


def test_the_pattern_is_not_vacuous():
    """The guard has to be able to see the sentence it was written for, or the
    four assertions above pass for the wrong reason (`Law 20`)."""
    shipped = ("web_search is one quick query.  (`B1304`: this sentence used to "
               "name that tool, on every turn, whether or not the request "
               "carried it.)")
    assert _hits(shipped) == ["B1304"], _hits(shipped)
    assert _hits("(`B-NEW`: a lane's own key)") == ["B-NEW"]
    assert _hits("P23-06 closed it") == ["P23-06"]
    assert _hits("found by fx11-ids") == ["fx11-ids"]
    # And it does not fire on prose a tool description legitimately carries.
    for innocent in ("pass time_filter (\"day\", \"week\", \"month\", or \"year\")",
                     "use scripts/mlx_image_server.py --model <repo> --port 8100",
                     "serve with pantheon-qwen3-8b or B2B-sized batches",
                     "HTTP 404, HTTP 500, exit_code 127"):
        assert _hits(innocent) == [], (innocent, _hits(innocent))
