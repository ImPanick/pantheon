# SPDX-License-Identifier: AGPL-3.0-or-later
import ast
import json
import subprocess
from pathlib import Path

import pytest

from routes.cookbook_helpers import _diagnose_serve_output


def test_cuda_oom_returns_diagnosis():
    out = "torch.cuda.OutOfMemoryError: CUDA out of memory."
    result = _diagnose_serve_output(out)
    assert result is not None
    assert "memory" in result["message"].lower()
    assert any(s["op"] == "replace" for s in result["suggestions"])


def test_port_in_use_returns_diagnosis():
    out = "OSError: [Errno 98] Address already in use"
    result = _diagnose_serve_output(out)
    assert result is not None
    assert "port" in result["message"].lower()
    assert result["suggestions"][0]["flag"] == "--port"


def test_vllm_not_installed_returns_diagnosis():
    out = "No module named vllm"
    result = _diagnose_serve_output(out)
    assert result is not None
    assert "vLLM" in result["message"]
    assert result["suggestions"][0]["package"] == "vllm"


def test_gated_model_returns_diagnosis():
    out = "403 Forbidden\nAccess to model is restricted"
    result = _diagnose_serve_output(out)
    assert result is not None
    assert "gated" in result["message"].lower() or "unauthorized" in result["message"].lower()


def test_traceback_fallback_fires_without_startup_success():
    out = "Traceback (most recent call last):\n  File 'serve.py', line 1\nRuntimeError: bad config"
    result = _diagnose_serve_output(out)
    assert result is not None
    assert "traceback" in result["message"].lower()


def test_traceback_suppressed_when_server_started():
    out = (
        "Traceback (most recent call last):\n  File 'x.py'\nValueError: ...\n"
        "Application startup complete."
    )
    result = _diagnose_serve_output(out)
    assert result is None


def test_clean_output_returns_none():
    out = "INFO: Application startup complete.\nINFO: Uvicorn running on http://0.0.0.0:8000"
    assert _diagnose_serve_output(out) is None


def test_empty_input_returns_none():
    assert _diagnose_serve_output("") is None
    assert _diagnose_serve_output(None) is None


def test_trust_remote_code_pattern():
    out = "Please pass trust_remote_code=True when loading this model."
    result = _diagnose_serve_output(out)
    assert result is not None
    assert "--trust-remote-code" in result["suggestions"][0]["arg"]


def test_no_gguf_found_pattern():
    out = "No GGUF found on this host for model qwen/qwen2-7b"
    result = _diagnose_serve_output(out)
    assert result is not None
    assert "GGUF" in result["message"]


# ── B1929: a serve on an NVIDIA driver too old for its build is diagnosed as the driver ──
#
# PyPI's torch and vLLM builds now target CUDA 13, which needs NVIDIA driver 580
# or newer. On an older driver torch stops with "The NVIDIA driver on your system
# is too old" and vLLM's own kernels with "CUDA driver version is insufficient
# for CUDA runtime version". Neither had a diagnosis, so the serve read as a bare
# traceback. And the Forge's status route (`/api/cookbook/tasks/status`, which the
# agent's serve status reads) never used this helper: `setup_cookbook_routes`
# kept an older copy of it that shadowed the import, without the helper's
# ModelOpt, mflux and MLX bridge entries. It also captured the tmux pane without
# -J, so a line tmux had wrapped at the pane's 80 columns split the very words
# the diagnosis looks for. Ported from upstream Odysseus a797cee0 (#6727/#6728).

ROOT = Path(__file__).resolve().parents[1]

TORCH_ON_AN_OLD_DRIVER = (
    # vLLM 0.31 from PyPI ships torch cu130; on driver 570 (CUDA 12.8) the engine dies here.
    "(EngineCore pid=1) ERROR [core.py:1433]     self.driver_worker.init_device()\n"
    "(EngineCore pid=1) ERROR [core.py:1433] RuntimeError: The NVIDIA driver on your system is too old "
    "(found version 12080). Please update your GPU driver by downloading and installing a new version\n"
    "Traceback (most recent call last):\n"
    "RuntimeError: Engine core initialization failed. See root cause above. Failed core proc(s): {}\n"
)
VLLM_KERNELS_ON_AN_OLD_DRIVER = (
    # torch moved to cu128, but the vLLM wheel's own kernels still need CUDA 13.
    "RuntimeError: get_cuda_view_from_cpu_tensor, /workspace/csrc/libtorch_stable/cuda_view.cu:38, "
    "cudaHostGetDevicePointer failed: CUDA driver version is insufficient for CUDA runtime version\n"
    "Traceback (most recent call last):\n"
)
MODELOPT_LM_HEAD = (
    "ValueError: There is no module or parameter named 'lm_head.input_scale' in Qwen3ForCausalLM\n"
)
DRIVER = "The installed PyTorch/vLLM build needs a newer NVIDIA driver than this server has."
MODELOPT = "vLLM cannot load this ModelOpt LM-head quantized checkpoint with the current runtime."


def test_torch_on_an_nvidia_driver_too_old_for_it_is_diagnosed_as_the_driver():
    result = _diagnose_serve_output(TORCH_ON_AN_OLD_DRIVER)
    assert result["message"] == DRIVER
    assert any("cu129" in s["label"] for s in result["suggestions"])
    assert any("580" in s["label"] for s in result["suggestions"])
    # Advice only: nothing the agent would run or change on its own.
    assert {s["op"] for s in result["suggestions"]} == {"manual"}


def test_vllm_kernels_on_a_cuda_runtime_newer_than_the_driver_are_diagnosed_as_the_driver():
    assert _diagnose_serve_output(VLLM_KERNELS_ON_AN_OLD_DRIVER)["message"] == DRIVER


def test_the_forge_routes_keep_no_copy_of_the_serve_diagnosis():
    source = (ROOT / "routes" / "cookbook_routes.py").read_text(encoding="utf-8")
    copies = [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_diagnose_serve_output"
    ]
    assert copies == []


def _as_tmux_prints_it(text, *, joined):
    """A detached tmux session's pane is 80 columns wide: a longer line goes onto
    the next rows, and `capture-pane -J` joins those rows back into the line."""
    if joined:
        return text
    rows = []
    for line in text.split("\n"):
        rows.extend([line[i:i + 80] for i in range(0, len(line), 80)] or [""])
    return "\n".join(rows)


def _status_of_a_serve_whose_pane_holds(text, host, tmp_path, monkeypatch):
    """The real status route's worker, over one running serve whose tmux pane
    holds `text`; only tmux, and ssh in front of it, are stand-ins."""
    import routes.cookbook_routes as cookbook_routes

    state = tmp_path / "forge-state.json"
    state.write_text(json.dumps({"tasks": [{
        "sessionId": "serve-ab12cd34", "type": "serve", "status": "running",
        "name": "Qwen3-8B", "remoteHost": host,
        "payload": {"repo_id": "Qwen/Qwen3-8B", "_cmd": "vllm serve Qwen/Qwen3-8B --port 8000"},
    }]}), encoding="utf-8")
    monkeypatch.setattr(cookbook_routes, "COOKBOOK_STATE_FILE", str(state))
    monkeypatch.setattr(cookbook_routes, "IS_WINDOWS", False)
    calls = []

    def _run(argv, *args, **kwargs):
        calls.append(argv)
        words = argv[-1].split() if argv[0] == "ssh" else argv
        if "has-session" in words:
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        if "capture-pane" in words:
            return subprocess.CompletedProcess(argv, 0, _as_tmux_prints_it(text, joined="-J" in words), "")
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(subprocess, "run", _run)
    handler = next(r.endpoint for r in cookbook_routes.setup_cookbook_routes().routes
                   if getattr(r, "path", "") == "/api/cookbook/tasks/status")
    code = handler.__code__
    worker = handler.__closure__[code.co_freevars.index("_cookbook_tasks_status_sync")].cell_contents
    # No orphan sweep: no server is configured, and its thread is not the question.
    sweep = worker.__closure__[worker.__code__.co_freevars.index("_maybe_sweep_orphans")].cell_contents
    sweep.__closure__[sweep.__code__.co_freevars.index("_orphan_sweep_inflight")].cell_contents[0] = True
    (task,) = worker()["tasks"]
    return task, calls


@pytest.mark.parametrize("host", ["", "gpu-box"], ids=["local", "over ssh"])
@pytest.mark.parametrize("text, message", [
    (TORCH_ON_AN_OLD_DRIVER, DRIVER),
    (VLLM_KERNELS_ON_AN_OLD_DRIVER, DRIVER),
    (MODELOPT_LM_HEAD, MODELOPT),
], ids=["torch on an old driver", "vLLM kernels on an old driver", "a ModelOpt lm_head checkpoint"])
def test_the_status_route_diagnoses_a_serve_from_its_joined_pane_with_the_shared_helper(
        text, message, host, tmp_path, monkeypatch):
    task, calls = _status_of_a_serve_whose_pane_holds(text, host, tmp_path, monkeypatch)
    assert task["diagnosis"]["message"] == message
    assert task["status"] == "error"
    (capture,) = [argv for argv in calls if "capture-pane" in " ".join(argv)]
    assert (capture[0] == "ssh") == bool(host)
