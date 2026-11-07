# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pin the mlx_image_server caller-chosen-model regression.

Background: scripts/mlx_image_server.py used to resolve the model per request
(``req.model or _args.model``) instead of serving the model the process was
launched with. ``_is_hidream`` is a substring test and ``_snapshot_path``
accepts either a local directory or a Hugging Face repo id, so a caller could
name any directory / repo and the HiDream branch would then run
``<model>/scripts/hidream_o1/generate_hidream_o1_mlx.py`` under
``sys.executable``. The server has no auth, and the Forge binds it to
``0.0.0.0`` whenever it is serving to a remote host, so that was reachable
code execution.

The fix pins both request paths to ``_args.model``, matching
scripts/diffusion_server.py. Ported from upstream Odysseus d0d8edf5 (security
advisory); the test logic is upstream's, adapted so no test can start a real
``mflux-generate`` or reach Hugging Face.
"""

import argparse
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "mlx_image_server.py"

_BASE_URL = "http://127.0.0.1"


def _load_module():
    """Fresh import of the server module. It pulls in no heavy runtime (mlx /
    torch imports all live inside the request handlers), so the real module is
    imported rather than AST-extracted."""
    spec = importlib.util.spec_from_file_location("mlx_image_server_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server(monkeypatch):
    """Server module launched with a pinned, non-HiDream model."""
    module = _load_module()
    module._args = argparse.Namespace(
        model="mlx-community/pinned-model",
        host="127.0.0.1",
        port=8100,
        steps=0,
        width=512,
        height=512,
        base_model="",
        lora_style="",
        lora_paths=[],
        lora_scales=[],
        vlm_model="",
    )
    # A pinned non-HiDream model must end in the "mflux-generate not found"
    # branch, never in a real subprocess that would try to download the model.
    monkeypatch.setattr(module, "_resolve_cli", lambda name: "")
    return module


def _client(module):
    from fastapi.testclient import TestClient

    return TestClient(module.app, base_url=_BASE_URL)


def _plant_hidream_model_dir(tmp_path: Path) -> tuple[Path, Path]:
    """A directory that satisfies _is_hidream() and carries the script the
    HiDream branch executes. The script writes a marker so the test can tell
    whether it ran."""
    model_dir = tmp_path / "hidream-planted"
    generator = model_dir / "scripts" / "hidream_o1"
    generator.mkdir(parents=True)
    marker = model_dir / "executed.txt"
    (generator / "generate_hidream_o1_mlx.py").write_text(
        f"open({str(marker)!r}, 'w').write('ran')\n", encoding="utf-8"
    )
    return model_dir, marker


def test_generate_does_not_run_code_from_a_caller_named_model_dir(server, tmp_path):
    """The regression: naming a local directory as the model must not execute
    the generator script inside it."""
    model_dir, marker = _plant_hidream_model_dir(tmp_path)

    _client(server).post(
        "/v1/images/generations",
        json={"model": str(model_dir), "prompt": "x", "size": "64x64"},
    )

    assert not marker.exists(), (
        "code inside the caller-named model directory ran; the request model "
        "must not select the generator"
    )


def test_generate_does_not_fetch_a_caller_named_repo(server, monkeypatch, tmp_path):
    """The remote half of the same defect: the caller's string must never reach
    the Hugging Face downloader."""
    downloaded = []
    stub = types.ModuleType("huggingface_hub")

    def _snapshot_download(repo, *args, **kwargs):
        downloaded.append(repo)
        return str(tmp_path / "absent")

    stub.snapshot_download = _snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", stub)

    _client(server).post(
        "/v1/images/generations",
        json={"model": "attacker-account/hidream-anything", "prompt": "x"},
    )

    assert "attacker-account/hidream-anything" not in downloaded


def test_edits_does_not_run_code_from_a_caller_named_model_dir(server, tmp_path, monkeypatch):
    """/v1/images/edits resolved the model the same way and must be pinned too.
    A "lama" name reaches the inpaint bridge, so the caller's model string is
    what picks the branch here."""
    model_dir = tmp_path / "lama-planted"
    model_dir.mkdir()
    called = []
    monkeypatch.setattr(server, "_run_inpaint_bridge", lambda *a, **kw: called.append(a))
    monkeypatch.setattr(server, "_run_ddcolor_bridge", lambda *a, **kw: called.append(a))

    resp = _client(server).post(
        "/v1/images/edits",
        data={"model": str(model_dir), "prompt": "x"},
        files={"image": ("i.png", b"not-a-real-png", "image/png")},
    )

    assert not called, "caller-supplied model selected the edit branch"
    assert resp.status_code == 422, "pinned non-edit model should be refused"


def test_pinned_hidream_model_is_still_served(server, tmp_path):
    """Behaviour preservation: pinning must not break a server that was actually
    launched with a HiDream model."""
    model_dir, marker = _plant_hidream_model_dir(tmp_path)
    server._args.model = str(model_dir)

    _client(server).post("/v1/images/generations", json={"model": "", "prompt": "x"})

    assert marker.exists(), "the model this server was launched with must still run"
