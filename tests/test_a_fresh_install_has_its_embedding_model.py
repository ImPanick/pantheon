# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1712`. A fresh Docker install searches memory and documents by meaning.

The image builds the default fastembed model into `/opt/pantheon/seed-models`
(`Dockerfile`, `BAKE_MODELS`), and `docker/entrypoint.sh`'s `seed_model_cache`
copies it into the data volume's cache when that holds no model. Before, the
in-process index had no model on a fresh install, Pantheon would not fetch one
(`allow_model_download`), and memory and RAG fell back to keywords — measured:
*"VectorRAG init failed: No embedding lanes available"* at first boot.

The entrypoint's seeding lines are run here for real in `sh`, against
temporary folders standing in for the image's seed and the data volume.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = (ROOT / "docker" / "entrypoint.sh").read_text()
DOCKERFILE = (ROOT / "Dockerfile").read_text()
COMPOSE = (ROOT / "docker-compose.yml").read_text()

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")


def _seeding_block() -> str:
    start = ENTRYPOINT.index("seed_model_cache() {")
    guard = ENTRYPOINT.index('if [ "${FASTEMBED_MODEL:-', start)
    end = ENTRYPOINT.index("\nfi\n", guard) + len("\nfi\n")
    return ENTRYPOINT[start:end]


def _run(tmp_path, *, model=None, seed_model="sentence-transformers/all-MiniLM-L6-v2"):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PUID": str(os.getuid()),
        "PGID": str(os.getgid()),
        "PANTHEON_SEED_MODELS": str(tmp_path / "seed"),
        "PANTHEON_FASTEMBED_SEED_MODEL": seed_model,
        "FASTEMBED_CACHE_PATH": str(tmp_path / "cache"),
    }
    if model is not None:
        env["FASTEMBED_MODEL"] = model
    return subprocess.run(["sh", "-c", _seeding_block()], env=env,
                          capture_output=True, text=True, timeout=30)


def _seed(tmp_path):
    snap = tmp_path / "seed" / "fastembed" / "models--qdrant--all-MiniLM-L6-v2-onnx" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "model.onnx").write_bytes(b"onnx")
    (snap / "tokenizer.json").write_text("{}")
    return snap


def test_an_empty_cache_is_seeded_from_the_image(tmp_path):
    _seed(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    copied = list((tmp_path / "cache").rglob("model.onnx"))
    assert len(copied) == 1 and copied[0].read_bytes() == b"onnx"
    assert "Seeded" in result.stderr


def test_a_cache_that_has_a_model_is_left_alone(tmp_path):
    _seed(tmp_path)
    own = tmp_path / "cache" / "models--mine" / "model.onnx"
    own.parent.mkdir(parents=True)
    own.write_bytes(b"mine")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert [p.read_bytes() for p in (tmp_path / "cache").rglob("*.onnx")] == [b"mine"]


def test_another_chosen_model_is_not_seeded(tmp_path):
    # Any .onnx counts as cached, so a seed of the wrong model would let
    # fastembed fetch the chosen one without anybody allowing it.
    _seed(tmp_path)
    result = _run(tmp_path, model="BAAI/bge-small-en-v1.5")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "cache").exists()


def test_an_image_built_without_models_seeds_nothing(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "cache").exists()


def test_the_image_bakes_the_model_the_app_and_compose_load():
    from src.embeddings import _DEFAULT_FASTEMBED_MODEL

    baked = re.search(r"^ARG FASTEMBED_SEED_MODEL=(\S+)$", DOCKERFILE, re.M)
    assert baked and baked.group(1) == _DEFAULT_FASTEMBED_MODEL
    assert f"FASTEMBED_MODEL=${{FASTEMBED_MODEL:-{_DEFAULT_FASTEMBED_MODEL}}}" in COMPOSE
    assert f'"${{FASTEMBED_MODEL:-{_DEFAULT_FASTEMBED_MODEL}}}"' in ENTRYPOINT


def test_the_seed_lives_outside_every_bind_mount():
    seed = re.search(r"PANTHEON_SEED_MODELS=(\S+)", DOCKERFILE).group(1)
    assert not seed.startswith(("/app/data", "/app/.cache", "/app/logs", "/app/.local"))


def test_seeding_runs_before_the_ownership_repair():
    assert ENTRYPOINT.index("seed_model_cache \"") < ENTRYPOINT.index(
        'for dir in /app/data /app/logs /app/.ssh /app/.local; do')
