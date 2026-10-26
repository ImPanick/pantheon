# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1476` — `serve_model` launches a model by name.

The launch-planning helpers in `src/tools/cookbook.py` (match a saved preset,
choose an engine from the model's metadata and the host, build a first command)
arrived with no caller; the model had to write every serve command itself. Now
`serve_model` with a `repo_id` and no `cmd` uses a saved preset for that model on
that host when there is one — a command that worked — and otherwise plans one.
A given `cmd` is used as given, as before.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import src.tools.cookbook as cb


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def world(monkeypatch):
    state = {"presets": [], "info": {}, "servers": {"default_host": "", "hosts": []}, "posted": []}

    async def presets():
        return state["presets"]

    async def info(repo_id):
        return state["info"] or {"repo_id": repo_id, "error": "the model hubs are off"}

    async def servers():
        return state["servers"]

    async def env_for_host(host):
        return {}

    async def ensure(**kw):
        return {"added": True, "endpoint_id": "ep-1"}

    async def register(**kw):
        return True

    class _Resp:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            state["posted"].append(json)
            return _Resp({"ok": True, "session_id": "s-1"})

    import httpx
    monkeypatch.setattr(cb, "_cookbook_presets", presets)
    monkeypatch.setattr(cb, "_cookbook_hf_model_info", info)
    monkeypatch.setattr(cb, "_cookbook_servers", servers)
    monkeypatch.setattr(cb, "_cookbook_env_for_host", env_for_host)
    monkeypatch.setattr(cb, "_ensure_served_endpoint", ensure)
    monkeypatch.setattr(cb, "_cookbook_register_task", register)
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return state


def test_a_saved_preset_for_the_model_is_what_launches(world, monkeypatch):
    world["presets"] = [{"name": "Qwen3 8B fast", "model": "Qwen/Qwen3-8B", "host": "",
                         "cmd": "vllm serve Qwen/Qwen3-8B --port 8001 --max-model-len 32768"}]
    seen = {}

    async def preset(content, owner=None):
        seen["args"] = json.loads(content)
        return {"output": "launched", "exit_code": 0}

    monkeypatch.setattr(cb, "do_serve_preset", preset)
    out = _run(cb.do_serve_model(json.dumps({"repo_id": "Qwen/Qwen3-8B", "local": True})))
    assert out["exit_code"] == 0 and seen["args"] == {"name": "Qwen3 8B fast"}
    assert world["posted"] == [], "the preset path launches, not a planned command"


@pytest.mark.parametrize("repo, info, engine, starts", [
    ("Qwen/Qwen3-8B", {}, "vllm", "vllm serve Qwen/Qwen3-8B "),
    ("unsloth/Qwen3-8B-GGUF", {"tags": ["gguf"], "siblings": ["Qwen3-8B-Q4_K_M.gguf"]},
     "llama.cpp", "llama-server -hf unsloth/Qwen3-8B-GGUF -hfr Qwen3-8B-Q4_K_M.gguf"),
    ("black-forest-labs/FLUX.1-dev", {"tags": ["diffusers"]}, "diffusers",
     "python3 scripts/diffusion_server.py --model black-forest-labs/FLUX.1-dev"),
])
def test_no_preset_plans_a_first_command(world, repo, info, engine, starts):
    world["info"] = info
    plan = _run(cb._cookbook_plan_launch(repo, "", port=8005))
    assert plan["engine"] == engine and plan["cmd"].startswith(starts)
    assert "--port 8005" in plan["cmd"]
    out = _run(cb.do_serve_model(json.dumps({"repo_id": repo, "local": True, "port": 8005})))
    assert out["exit_code"] == 0, out
    assert world["posted"][-1]["cmd"] == plan["cmd"]
    assert "planned for" in out["output"] and plan["cmd"] in out["output"]


def test_metadata_that_cannot_be_had_is_said_not_refused(world):
    plan = _run(cb._cookbook_plan_launch("Qwen/Qwen3-8B", ""))
    assert plan["cmd"].startswith("vllm serve Qwen/Qwen3-8B") and plan["warning"]
    out = _run(cb.do_serve_model(json.dumps({"repo_id": "Qwen/Qwen3-8B", "local": True})))
    assert "chosen from the name alone" in out["output"]


def test_a_given_command_is_used_as_given(world):
    out = _run(cb.do_serve_model(json.dumps({"repo_id": "Qwen/Qwen3-8B", "local": True,
                                             "cmd": "vllm serve Qwen/Qwen3-8B --port 9000"})))
    assert out["exit_code"] == 0 and world["posted"][-1]["cmd"] == "vllm serve Qwen/Qwen3-8B --port 9000"
    assert "planned for" not in out["output"]


def test_the_schema_says_the_command_is_optional():
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    schema = next(t["function"] for t in FUNCTION_TOOL_SCHEMAS if t["function"]["name"] == "serve_model")
    assert schema["parameters"]["required"] == ["repo_id"]
    assert "port" in schema["parameters"]["properties"]
