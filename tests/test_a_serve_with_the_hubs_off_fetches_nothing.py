# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1259` — with the Forge's hub switch off, serving a model that is not on
disk does not let the engine fetch it.

The owner, 2026-10-07 (`D-2026-10-07-02` §1): *"With the Forge's hub switch
off, serving a model that is not on disk does not let the engine fetch it."*
`B1229` gated every lookup and download; a serve still fetched — measured on
`fcd559e` (the base), with `forge_model_hubs` off, `POST /api/model/serve`
wrote and launched the script for `llama-server -hf <repo>` and `ollama pull`,
and a `vllm serve <repo>` script carried nothing to keep the engine off the
hub, so a repo id not in the cache was downloaded.

Driven (`Law 20`): the real `/api/model/serve` route on a real router, with
the launch itself replaced (nothing is spawned) and the switch read from a
real settings file; the offline lines the route writes are run in `bash` under
a home with and without the model in its Hugging Face cache.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.model_hubs as model_hubs

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="bash not on PATH")


class _Manager:
    is_configured = True

    def is_admin(self, user):
        return user == "ada"


@pytest.fixture
def forge(tmp_path, monkeypatch):
    import routes.cookbook_routes as cookbook_routes
    import src.constants
    import src.settings

    settings_file = str(tmp_path / "settings.json")
    monkeypatch.setattr(src.constants, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(src.settings, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(cookbook_routes, "COOKBOOK_STATE_FILE", str(tmp_path / "cookbook_state.json"))
    monkeypatch.setattr(cookbook_routes, "TMUX_LOG_DIR", tmp_path / "tmux")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    src.settings._invalidate_caches()
    launched = []

    async def have(binary, *a, **k):
        return True

    class _Proc:
        returncode = 1
        stderr = SimpleNamespace(read=lambda: _done(b"launch stopped by the test"))

        async def wait(self):
            return 1

    async def _done(value):
        return value

    async def spawn(cmd, **kw):
        launched.append(cmd)
        return _Proc()

    monkeypatch.setattr(cookbook_routes, "_binary_available", have)
    monkeypatch.setattr(cookbook_routes.asyncio, "create_subprocess_shell", spawn)

    app = FastAPI()
    app.state.auth_manager = _Manager()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = "ada"
        return await call_next(request)

    app.include_router(cookbook_routes.setup_cookbook_routes())
    client = TestClient(app, raise_server_exceptions=False)

    class Forge:
        log_dir = tmp_path / "tmux"

        def hubs(self, on):
            s = src.settings.load_settings()
            s["forge_model_hubs"] = on
            src.settings.save_settings(s)

        def serve(self, repo_id, cmd):
            return client.post("/api/model/serve", json={"repo_id": repo_id, "cmd": cmd}).json()

        def scripts(self):
            return sorted(self.log_dir.glob("*_run.sh")) if self.log_dir.exists() else []

        @property
        def launched(self):
            return launched

    yield Forge()
    src.settings._invalidate_caches()


@pytest.mark.parametrize("cmd", [
    "llama-server -hf Qwen/Qwen3-8B-GGUF --host 0.0.0.0 --port 8080",
    "llama-server --hf-repo Qwen/Qwen3-8B-GGUF --hf-file q4.gguf --port 8080",
    "ollama pull qwen2.5:7b",
    "ollama run qwen2.5:7b",
])
def test_a_serve_that_exists_to_fetch_is_refused_before_a_script(forge, cmd):
    forge.hubs(False)
    repo = "qwen2.5:7b" if cmd.startswith("ollama") else "Qwen/Qwen3-8B-GGUF"
    out = forge.serve(repo, cmd)
    assert out == {"ok": False, "error": model_hubs.OFF_SENTENCE, "hubs_off": True}
    assert forge.scripts() == [] and forge.launched == []


def test_with_the_switch_on_the_same_serve_is_not_refused(forge):
    forge.hubs(True)
    out = forge.serve("Qwen/Qwen3-8B-GGUF", "llama-server -hf Qwen/Qwen3-8B-GGUF --port 8080")
    assert out.get("hubs_off") is None and out["error"] == "launch stopped by the test"
    assert len(forge.launched) == 1
    assert "HF_HUB_OFFLINE" not in forge.scripts()[0].read_text()


def _offline_block(script: Path, cmd: str, repo: str) -> str:
    """The lines the route wrote for the switch, taken from the script it
    wrote — present, in order, and nothing else of the script run."""
    lines = model_hubs.offline_runner_lines(cmd, repo)
    text = script.read_text()
    block = "\n".join(lines)
    assert block in text, "the serve script does not carry the offline lines"
    return block


def _run(block: str, home: Path) -> subprocess.CompletedProcess:
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        ["bash", "-c", 'PANTHEON_PREFLIGHT_EXIT=""\n' + block +
         '\necho "HF_HUB_OFFLINE=$HF_HUB_OFFLINE TRANSFORMERS_OFFLINE=$TRANSFORMERS_OFFLINE '
         'EXIT=$PANTHEON_PREFLIGHT_EXIT"'],
        capture_output=True, text=True, env=env, timeout=20)


def test_a_vllm_serve_runs_offline_and_stops_on_a_model_not_on_disk(forge, tmp_path):
    forge.hubs(False)
    cmd = "vllm serve Qwen/Qwen3-8B --host 0.0.0.0 --port 8000"
    out = forge.serve("Qwen/Qwen3-8B", cmd)
    assert out["error"] == "launch stopped by the test"       # it was launched, not refused
    block = _offline_block(forge.scripts()[0], cmd, "Qwen/Qwen3-8B")

    empty_home = tmp_path / "home-empty"
    empty_home.mkdir()
    ran = _run(block, empty_home)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [
        "Qwen/Qwen3-8B is not on this machine. " + model_hubs.OFF_SENTENCE,
        "HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 EXIT=1",
    ]

    cached_home = tmp_path / "home-cached"
    (cached_home / ".cache" / "huggingface" / "hub" / "models--Qwen--Qwen3-8B").mkdir(parents=True)
    ran = _run(block, cached_home)
    assert ran.stdout.splitlines() == ["HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 EXIT="]


def test_a_model_served_from_a_path_on_disk_is_not_checked_against_the_hub(forge):
    forge.hubs(False)
    cmd = "llama-server --model /srv/models/qwen3-8b-q4.gguf --port 8080"
    forge.serve("qwen3-8b-q4", cmd)
    text = forge.scripts()[0].read_text()
    assert "export HF_HUB_OFFLINE=1" in text
    assert "is not on this machine" not in text


def test_with_the_switch_on_a_vllm_serve_is_as_before(forge):
    forge.hubs(True)
    forge.serve("Qwen/Qwen3-8B", "vllm serve Qwen/Qwen3-8B --port 8000")
    text = forge.scripts()[0].read_text()
    assert "HF_HUB_OFFLINE" not in text and "is not on this machine" not in text


def test_a_pip_install_is_not_a_model_fetch(forge):
    """Installing an engine is not serving a model: the switch is about hubs."""
    forge.hubs(False)
    out = forge.serve("vllm", "python3 -m pip install vllm")
    assert out.get("hubs_off") is None
    assert "HF_HUB_OFFLINE" not in forge.scripts()[0].read_text()
