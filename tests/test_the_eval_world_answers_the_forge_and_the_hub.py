# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-27` — the evaluation world answers the Forge and the hub, and never
reads the machine it runs on.

Found bringing the AI Engineering section to the bar. `list_served_models`
asks the install's own Forge route (refused in a world, `B1602`) and then
scans **this machine's** `/proc` for model servers: a case's answer depended
on whatever the computer running the evaluation was serving — the one thing
`P24-16` says a case never reads. `list_cached_models` asked the install's
cache route, was refused, and answered "No cached models found" — a claim
about a disk nobody looked at. `search_hf_models` was refused outright. So
Model Steward and Benchmark Runner could not be measured.

A world now has `served` (the Forge's model servers), `cached` (what is on
disk, by host) and `hub` (Hugging Face search results, by words in the
query). They are answered where the tools ask — the install's Forge routes —
so each tool's own code says them in its own words; and no world scans the
host's processes. Driven through the real harness and the real tools.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from src.agents import evals as E
from src.agents.catalogue import get_agent
import src.tool_execution as tool_execution


def _spy(monkeypatch):
    seen = []
    real = tool_execution._execute_tool_block_impl

    async def spy(block, *a, **kw):
        out = await real(block, *a, **kw)
        seen.append((block.tool_type, json.dumps(out[1] if isinstance(out, tuple) else out, ensure_ascii=False)))
        return out

    monkeypatch.setattr(tool_execution, "_execute_tool_block_impl", spy)
    return seen


def _run(world, calls, monkeypatch, agent="model-steward"):
    seen = _spy(monkeypatch)
    m = get_agent(None, agent)
    case = {"id": "drive", "world": world, "answers": ["approve_task"] * len(calls),
            "script": [{"call": [c]} for c in calls] + [{"say": "Done."}],
            "checks": [{"called": calls[0][0]}]}
    (r,) = asyncio.run(E.run_agent(m, cases=[case]))
    return {t: out for t, out in seen}, r


def _the_host_serves_something(monkeypatch):
    """The machine running the evaluation is serving a model."""
    import src.tools.cookbook as cookbook
    monkeypatch.setattr(cookbook, "_scan_running_model_processes",
                        lambda: [{"model": "HOST-ONLY-MODEL", "status": "running", "external": True, "pid": 4242}])


def test_served_models_are_the_worlds_never_the_hosts(monkeypatch):
    _the_host_serves_something(monkeypatch)
    out, r = _run({"served": [{"model": "Qwen/Qwen3-8B", "status": "ready", "remote": "gpu1", "session_id": "qwen3"}]},
                  [["list_served_models", {}]], monkeypatch)
    said = out["list_served_models"]
    assert "Qwen/Qwen3-8B: ready (gpu1, session: qwen3)" in said, said
    assert "HOST-ONLY-MODEL" not in said, "the case read the processes of the machine it ran on"
    assert r.loopback == [], r.loopback


def test_a_world_with_no_servers_serves_nothing(monkeypatch):
    _the_host_serves_something(monkeypatch)
    out, _ = _run({}, [["list_served_models", {}]], monkeypatch)
    assert "No model servers currently running" in out["list_served_models"], out
    assert "HOST-ONLY-MODEL" not in out["list_served_models"]


def test_cached_models_are_listed_by_host(monkeypatch):
    out, _ = _run({"cached": [{"repo_id": "Qwen/Qwen3-8B", "size": "16.4GB"},
                              {"repo_id": "meta-llama/Llama-3.1-8B-Instruct", "size": "16.1GB", "host": "gpu1"}]},
                  [["list_cached_models", {}]], monkeypatch)
    said = out["list_cached_models"]
    assert "Qwen/Qwen3-8B" in said and "Llama-3.1-8B-Instruct" in said and "gpu1" in said, said
    assert "No cached models found" not in said


def test_nothing_cached_is_said_without_asking_the_install(monkeypatch):
    out, r = _run({}, [["list_cached_models", {}]], monkeypatch)
    assert "No cached models found" in out["list_cached_models"], out
    assert r.loopback == [], "the case asked the install's own routes"


def test_the_hub_answers_from_the_world(monkeypatch):
    out, r = _run({"hub": {"qwen3": [{"repo_id": "Qwen/Qwen3-8B-2510", "downloads": 51234, "size_gb": 16.4}]}},
                  [["search_hf_models", {"query": "qwen3 8b"}]], monkeypatch)
    said = out["search_hf_models"]
    assert "Qwen/Qwen3-8B-2510 (~16.4GB, 51234 downloads)" in said, said
    nothing, _ = _run({"hub": {"qwen3": []}}, [["search_hf_models", {"query": "mistral"}]], monkeypatch)
    assert "No models found for query: 'mistral'" in nothing["search_hf_models"], nothing


def test_without_a_hub_the_hub_is_still_refused(monkeypatch):
    seen = []
    real = E.World.answer

    def spy(self, tool, content):
        out = real(self, tool, content)
        if out is not None:
            seen.append((tool, out[1]["output"]))
        return out

    monkeypatch.setattr(E.World, "answer", spy)
    _run({}, [["search_hf_models", {"query": "qwen3"}]], monkeypatch)
    assert any("This world has no search_hf_models" in o for t, o in seen if t == "search_hf_models"), seen


@pytest.mark.parametrize("key, value", [
    ("served", [{"model": "m", "status": "ready"}]),
    ("cached", [{"repo_id": "a/b"}]),
    ("hub", {"qwen": [{"repo_id": "a/b"}]}),
])
def test_a_world_lints_the_forge_keys(key, value):
    m = get_agent(None, "model-steward")
    assert E.lint_evals({"cases": [{"id": "a-case", "world": {key: value}, "checks": [{"status": "success"}]}]}, m)


@pytest.mark.parametrize("key, value", [
    ("served", [{"status": "ready"}]),
    ("cached", ["a/b"]),
    ("hub", [{"repo_id": "a/b"}]),
])
def test_a_malformed_forge_key_is_refused_in_a_sentence(key, value):
    m = get_agent(None, "model-steward")
    with pytest.raises(E.EvalRefused) as exc:
        E.lint_evals({"cases": [{"id": "a-case", "world": {key: value}, "checks": [{"status": "success"}]}]}, m)
    assert key in exc.value.sentence
