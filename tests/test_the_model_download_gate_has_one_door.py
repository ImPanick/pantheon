# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B723` — the `Law 16` gate held on one of two constructions.

The owner's words: *"we drop external dependence. i dont want things that'll may
route to external services unless the user (or sysadmin) explicitly links it."*
`src/embedding_lanes.py` enforced that before building a FastEmbed client, and
`src/embeddings.py::get_embedding_client` built the same client on the fallback
path with no check at all — the path taken whenever the HTTP embedding API is
unreachable, which is a fresh install with no embedding server configured. So
the first RAG, memory or tool probe on a new box fetched ~90MB from HuggingFace
without anybody being asked.

The tests here drive the real functions rather than reading them (`Law 20`), and
the last one is the one that stops a third door being opened.
"""
import ast
import pathlib

import pytest

import src.embedding_lanes as lanes

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def _no_model(monkeypatch):
    """A machine with no cached model and no permission — the default install."""
    monkeypatch.setattr(lanes, "fastembed_model_is_cached", lambda: False)
    monkeypatch.setattr(lanes, "model_download_allowed", lambda: False)


def test_the_gate_refuses_when_nothing_is_cached_and_nobody_consented(_no_model):
    with pytest.raises(lanes.ModelDownloadNotPermitted):
        lanes.ensure_fastembed_download_permitted()


def test_a_cached_model_costs_no_network_so_it_is_allowed(monkeypatch):
    monkeypatch.setattr(lanes, "fastembed_model_is_cached", lambda: True)
    monkeypatch.setattr(lanes, "model_download_allowed", lambda: False)
    lanes.ensure_fastembed_download_permitted()   # must not raise


def test_explicit_consent_is_enough_on_its_own(monkeypatch):
    monkeypatch.setattr(lanes, "fastembed_model_is_cached", lambda: False)
    monkeypatch.setattr(lanes, "model_download_allowed", lambda: True)
    lanes.ensure_fastembed_download_permitted()   # must not raise


def test_the_lane_builder_asks_before_it_constructs(_no_model, monkeypatch):
    """The door that was already gated, kept gated."""
    built = []

    class _Boom:
        def __init__(self, *a, **k):
            built.append(1)

    monkeypatch.setattr("src.embeddings.FastEmbedClient", _Boom, raising=False)
    with pytest.raises(lanes.ModelDownloadNotPermitted):
        lanes._build_fastembed_client()
    assert built == [], "the client was constructed before the gate was consulted"


def test_the_fallback_path_asks_too(_no_model, monkeypatch):
    """`B723` itself: `get_embedding_client` falls back to FastEmbed whenever the
    HTTP embedding API is down, which is the default install, and it used to
    construct the client with no check."""
    import src.embeddings as emb

    built = []

    class _Boom:
        def __init__(self, *a, **k):
            built.append(1)

        def get_sentence_embedding_dimension(self):
            return 384

    class _DeadHttp:
        def __init__(self, *a, **k):
            raise RuntimeError("no embedding server here")

    monkeypatch.setattr(emb, "FastEmbedClient", _Boom, raising=False)
    monkeypatch.setattr(emb, "EmbeddingClient", _DeadHttp, raising=False)
    monkeypatch.setattr(emb, "_http_embed_down", False, raising=False)

    client = emb.get_embedding_client()

    assert built == [], "the fallback constructed a FastEmbed client unasked"
    assert client is None, (
        "a refused download must answer `None`, the same as any other "
        "unavailable client — the callers already handle that")


def test_the_gate_is_written_once_and_not_once_per_caller():
    """`Law 13`. Two constructions and one check is how this defect existed; a
    third construction that does not call the gate is the same defect again.

    Driven off the parsed source rather than a grep: every `FastEmbedClient(...)`
    call in non-test Python must be inside a function that also calls
    `ensure_fastembed_download_permitted`.
    """
    offenders = []
    for path in sorted(ROOT.glob("src/**/*.py")) + sorted(ROOT.glob("services/**/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
            constructs = any(
                isinstance(c.func, ast.Name) and c.func.id == "FastEmbedClient"
                for c in calls)
            if not constructs:
                continue
            asks = any(
                isinstance(c.func, ast.Name)
                and c.func.id == "ensure_fastembed_download_permitted"
                for c in calls)
            if not asks:
                offenders.append(f"{path.relative_to(ROOT)}:{fn.lineno} {fn.name}")
    assert not offenders, (
        "a FastEmbed client is constructed without asking the `Law 16` gate: "
        + ", ".join(offenders))
