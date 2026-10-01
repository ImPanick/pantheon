# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1012` — `host_shell`'s description says what a container never reaches.

It said: *"its filesystem, its services, its network stack. `bash` cannot reach
any of that, because it runs inside the container."* Measured 2026-10-01 on
Docker Desktop 29.7.2 for Windows (`B975`; `D-2026-10-01-03` accepted it): a
container reaches the router and the host's own LAN-facing services (`:445`).
So a model told `bash` cannot reach the host's services reaches for the host
agent — or gives up — for a connection its own shell makes.

What a bridged container never reaches is the machine itself: its files beyond
what is mounted into the container, its processes and services, its own network
configuration. That is what every description a model reads now names, and each
says that a connection over the network is something `bash` can often make.

These read the description objects the model is sent — the native schema and the
tool index, and the fenced prompt's section if one is ever added — not the files
(`Law 20`: the prose *is* the product here, so the assertion is scoped to it).
"""
from __future__ import annotations

import re

import pytest


def _descriptions() -> dict:
    from src.agent_loop import TOOL_SECTIONS
    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    found = {}
    schemas = [s["function"]["description"] for s in FUNCTION_TOOL_SCHEMAS
               if s.get("function", {}).get("name") == "host_shell"]
    for i, text in enumerate(schemas):
        found[f"schema-{i}"] = text
    if "host_shell" in BUILTIN_TOOL_DESCRIPTIONS:
        found["index"] = BUILTIN_TOOL_DESCRIPTIONS["host_shell"]
    if "host_shell" in TOOL_SECTIONS:
        found["section"] = TOOL_SECTIONS["host_shell"]
    return found


def _sentences(text: str):
    return [s for s in re.split(r"(?<=[.;])\s+", text) if s.strip()]


def test_the_model_reads_it_in_two_places_and_both_are_checked():
    assert {"schema-0", "index"} <= set(_descriptions())


@pytest.mark.parametrize("where", sorted(_descriptions()))
def test_nothing_a_bridged_container_reaches_is_said_to_be_out_of_reach(where):
    text = _descriptions()[where]
    # Every sentence that says what `bash` cannot do, and the list it points at.
    cannot = [s for s in _sentences(text) if "`bash`" in s and "cannot" in s]
    assert cannot, where
    for sentence in cannot:
        # "Reach" is the network claim the measurement refuted; the host's
        # services and "network stack" are what a container on Docker Desktop
        # does reach (by connecting to them).
        assert "cannot reach" not in sentence, (where, sentence)
    assert "network stack" not in text, where


@pytest.mark.parametrize("where", sorted(_descriptions()))
def test_what_it_names_is_the_machine_itself(where):
    text = _descriptions()[where].lower()
    assert "beyond what is mounted into the container" in text, where
    assert "processes" in text, where
    assert "network configuration" in text, where


@pytest.mark.parametrize("where", sorted(_descriptions()))
def test_a_connection_over_the_network_is_left_to_bash(where):
    text = _descriptions()[where]
    can = [s for s in _sentences(text) if "`bash` can" in s]
    assert can and "over the network" in " ".join(can + [text]), where
    assert "Docker Desktop" in " ".join(can), where
