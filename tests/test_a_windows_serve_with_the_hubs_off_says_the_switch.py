# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1267` — a Windows serve with the hubs off said the engine's error, not the switch's.

`B1259`'s bash lines stop a serve before the engine starts when the repo it
names is not in the Hugging Face cache, with *"<repo> is not on this
machine."* and the switch's sentence. `model_hubs.offline_powershell_lines()`
gave a Windows script the three `*_OFFLINE` variables only, so the fetch was
still refused (by `huggingface_hub`) but the person read the engine's offline
traceback. Now the PowerShell lines carry the same check, over the same three
cache locations in the same order.

Driven through the real `/api/model/serve` route with `platform: windows` and a
remote host (`B1259`'s fixture: the launch is replaced, the switch is read from
a real settings file), and the `.ps1` it writes is read back. No PowerShell is
installed where this was written, so the script itself runs only where `pwsh`
is on the PATH (the last test); the sentence's spelling is checked by
expanding it the way PowerShell does.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

import src.model_hubs as model_hubs
from tests.test_a_serve_with_the_hubs_off_fetches_nothing import forge  # noqa: F401

_REPO = "Qwen/Qwen3-8B-GGUF"
_CMD = f"python -m llama_cpp.server --model {_REPO} --port 8080"


def _serve_windows(forge, repo_id, cmd):
    out = forge.serve_json({"repo_id": repo_id, "cmd": cmd, "platform": "windows",
                            "remote_host": "ada@winbox"})
    scripts = sorted(forge.log_dir.glob("*_run.ps1"))
    return out, scripts


@pytest.fixture
def windows_forge(forge, monkeypatch):
    import routes.cookbook_routes as cookbook_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from tests.test_a_serve_with_the_hubs_off_fetches_nothing import _Manager

    app = FastAPI()
    app.state.auth_manager = _Manager()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = "ada"
        return await call_next(request)

    app.include_router(cookbook_routes.setup_cookbook_routes())
    client = TestClient(app, raise_server_exceptions=False)
    forge.serve_json = lambda body: client.post("/api/model/serve", json=body).json()
    return forge


def _expand(ps_double_quoted: str) -> str:
    """What PowerShell prints for one of `_ps_text`'s strings."""
    assert ps_double_quoted.startswith('"') and ps_double_quoted.endswith('"')
    body = ps_double_quoted[1:-1]
    body = re.sub(r"\$\(\[char\]0x([0-9A-F]{4})\)", lambda m: chr(int(m.group(1), 16)), body)
    return re.sub(r"`(.)", r"\1", body)


def test_a_windows_serve_of_a_hub_repo_carries_the_cache_check(windows_forge):
    windows_forge.hubs(False)
    out, scripts = _serve_windows(windows_forge, _REPO, _CMD)
    assert out.get("hubs_off") is None, out                  # launched, not refused
    assert len(scripts) == 1
    text = scripts[0].read_bytes().decode("utf-8")
    block = "\r\n".join(model_hubs.offline_powershell_lines(_CMD, _REPO))
    assert block in text, "the .ps1 does not carry the offline lines with the check"
    # The check comes before the engine is started.
    assert text.index("Test-Path -LiteralPath") < text.index(_CMD)
    assert "Join-Path $_panHub 'models--Qwen--Qwen3-8B-GGUF'" in block
    assert "=== Process exited with code 1 ===" in block and "exit 1" in block


def test_the_three_cache_locations_are_the_bash_lines_order():
    """`HF_HUB_CACHE`, else `HF_HOME\\hub`, else `~\\.cache\\huggingface\\hub` —
    the order `offline_runner_lines` reads them in."""
    ps = next(line for line in model_hubs.offline_powershell_lines(_CMD, _REPO)
              if line.startswith("$_panHub"))
    bash = next(line for line in model_hubs.offline_runner_lines(_CMD, _REPO)
                if line.startswith("_pan_hub="))
    def order(line):
        return list(dict.fromkeys(re.findall(r"HF_HUB_CACHE|HF_HOME|\.cache", line)))

    assert order(ps) == order(bash) == ["HF_HUB_CACHE", "HF_HOME", ".cache"]


def test_the_sentence_reads_the_same_under_any_code_page():
    """The `.ps1` is UTF-8 without a BOM, which Windows PowerShell 5.1 reads as
    ANSI: the line itself is ASCII, and expands to the switch's sentence."""
    said = next(line.strip()[len("Write-Host "):]
                for line in model_hubs.offline_powershell_lines(_CMD, _REPO)
                if "is not on this machine" in line)
    said.encode("ascii")
    assert _expand(said) == f"{_REPO} is not on this machine. {model_hubs.OFF_SENTENCE}"


def test_a_model_served_from_a_path_on_disk_is_not_checked(windows_forge):
    windows_forge.hubs(False)
    cmd = r"python -m llama_cpp.server --model C:\models\Qwen3-8B-GGUF\q4.gguf --port 8080"
    _, scripts = _serve_windows(windows_forge, _REPO, cmd)
    text = scripts[0].read_bytes().decode("utf-8")
    assert "$env:HF_HUB_OFFLINE = '1'" in text
    assert "is not on this machine" not in text


def test_with_the_switch_on_nothing_is_added(windows_forge):
    windows_forge.hubs(True)
    _, scripts = _serve_windows(windows_forge, _REPO, _CMD)
    text = scripts[0].read_bytes().decode("utf-8")
    assert "HF_HUB_OFFLINE" not in text and "is not on this machine" not in text


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell (pwsh) not on PATH")
def test_the_lines_stop_a_serve_of_a_repo_not_on_disk(tmp_path):
    block = "\n".join(model_hubs.offline_powershell_lines(_CMD, _REPO)) + "\nWrite-Host 'went on'"

    def run(home: Path):
        return subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", block],
                              capture_output=True, text=True, timeout=60,
                              env={"HOME": str(home), "PATH": "/usr/bin:/bin"})

    empty = tmp_path / "empty"
    empty.mkdir()
    ran = run(empty)
    assert ran.returncode == 1
    assert ran.stdout.splitlines()[0] == f"{_REPO} is not on this machine. {model_hubs.OFF_SENTENCE}"

    cached = tmp_path / "cached"
    (cached / ".cache" / "huggingface" / "hub" / "models--Qwen--Qwen3-8B-GGUF").mkdir(parents=True)
    ran = run(cached)
    assert ran.returncode == 0 and ran.stdout.strip() == "went on"
