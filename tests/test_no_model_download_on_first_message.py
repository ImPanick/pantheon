# SPDX-License-Identifier: AGPL-3.0-or-later
"""The last zero-configuration leak: a model fetched on the first chat message.

`build_embedding_lanes` returns lanes in preference order -- custom (a local
HTTP embedding server) then fastembed. fastembed is documented in
`embeddings.py` as the "zero config fallback", and until 2026-09-01 it was built
**unconditionally**: the `try` around it was not conditional on the custom lane
failing. `FastEmbedClient.__init__` fetches ~90MB of ONNX from HuggingFace when
the model is absent, and `fastembed` is a hard requirement so the path is never
skipped.

Net effect: a fresh install answering its first message downloaded a model from
a third party -- with a local embedding server already running and answering.
A fallback that always runs is not a fallback.
"""
import sys
import types

import pytest

from src import embedding_lanes as el


@pytest.fixture
def spy(monkeypatch):
    """Record whether the real embedding client -- the thing that downloads --
    was ever constructed.

    Stubbing `_build_fastembed_client` would be the obvious move and it tests
    nothing: that function *is* the gate. Stub what it builds instead, so the
    gate runs for real.
    """
    built = []

    class _Tripwire:
        def __init__(self, *a, **k):
            built.append(True)

        def get_sentence_embedding_dimension(self):
            return 384

    fake = types.ModuleType("src.embeddings")
    fake.FastEmbedClient = _Tripwire
    monkeypatch.setitem(sys.modules, "src.embeddings", fake)
    return built


def test_nothing_is_downloaded_without_permission(spy, monkeypatch):
    """`Law 16`: refuse and say why, rather than reach out uninvited."""
    monkeypatch.setattr(el, "fastembed_model_is_cached", lambda: False)
    monkeypatch.setattr(el, "model_download_allowed", lambda: False)

    with pytest.raises(el.ModelDownloadNotPermitted) as caught:
        el._build_fastembed_client()

    assert spy == [], "a model was fetched with no permission"
    msg = str(caught.value)
    assert "EMBEDDING_URL" in msg and "allow_model_download" in msg, (
        f"the refusal must name both remedies: {msg}"
    )


def test_an_already_cached_model_is_used_freely(spy, monkeypatch):
    """Cached costs no network, so permission is irrelevant -- use it."""
    monkeypatch.setattr(el, "fastembed_model_is_cached", lambda: True)
    monkeypatch.setattr(el, "model_download_allowed", lambda: False)

    el._build_fastembed_client()
    assert spy == [True]


def test_permission_allows_the_fetch(spy, monkeypatch):
    """The capability is not removed -- it is asked for."""
    monkeypatch.setattr(el, "fastembed_model_is_cached", lambda: False)
    monkeypatch.setattr(el, "model_download_allowed", lambda: True)

    el._build_fastembed_client()
    assert spy == [True]


def test_a_refusal_degrades_the_lane_list_rather_than_raising(monkeypatch):
    """Zero lanes is a supported state -- memory and RAG both handle it.

    The gate lives in `_build_fastembed_client`, not in the lane assembler, so
    a caller holding a real client is unaffected. That placement is load-bearing
    and cost a red suite to learn: fourteen existing tests stub the builder to
    check dimension separation, legacy backfill and dual-write, and none of them
    downloads anything. Gating the assembler refused lanes in tests that were
    never going to fetch.
    """
    import src.chroma_client  # noqa: F401

    monkeypatch.setattr(el, "_build_custom_client",
                        lambda: (_ for _ in ()).throw(RuntimeError("no server")))
    monkeypatch.setattr(
        el, "_build_fastembed_client",
        lambda: (_ for _ in ()).throw(el.ModelDownloadNotPermitted("nope")),
    )
    monkeypatch.setattr(el, "get_chroma_client", lambda: object(), raising=False)
    monkeypatch.setattr(sys.modules["src.chroma_client"], "get_chroma_client",
                        lambda: object(), raising=False)

    assert el.build_embedding_lanes("t") == []


def test_permission_ships_off():
    """`Law 16`, and `B90` moved the shipped value from `False` to `None`.

    Off is still off — `bool(None)` is `False`. The third value exists because a
    stored `False` and the shipped default were the same byte, so an operator
    who turned this gate off could not outrank `PANTHEON_ALLOW_MODEL_DOWNLOAD`:
    measured 2026-09-15, stored `False`, effective `True`."""
    from src.settings import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["allow_model_download"] is None
    assert bool(DEFAULT_SETTINGS["allow_model_download"]) is False


def test_the_env_fallback_is_reachable(monkeypatch):
    """It is reachable *because the default is falsy*.

    `H06` found the same shape dead in `resolve_task_concurrency_cap`, where the
    shipped default is `1` -- truthy, so the `or` never falls through and the
    env layer is unreachable code. The distinction is the default's truthiness,
    not the pattern, and it is worth knowing before copying either.
    """
    monkeypatch.setenv("PANTHEON_ALLOW_MODEL_DOWNLOAD", "1")
    assert el.model_download_allowed() is True
    monkeypatch.setenv("PANTHEON_ALLOW_MODEL_DOWNLOAD", "0")
    assert el.model_download_allowed() is False


def test_the_cache_probe_never_constructs_the_thing_it_is_probing_for(monkeypatch):
    """Asking fastembed "is the model there?" makes it fetch the model.

    That is the whole reason the probe looks for the file on disk instead. If it
    ever starts building a TextEmbedding to find out, the check has become the
    download it exists to avoid -- and it would still return the right answer,
    which is what makes the regression invisible without this test.
    """
    built = []

    class _Tripwire:
        def __init__(self, *a, **k):
            built.append(True)

    fake = types.ModuleType("fastembed")
    fake.TextEmbedding = _Tripwire
    monkeypatch.setitem(sys.modules, "fastembed", fake)

    el.fastembed_model_is_cached()
    assert built == [], "the cache probe constructed a TextEmbedding, which downloads"


def test_the_probe_reads_the_configured_cache_directory(tmp_path, monkeypatch):
    """And it answers on evidence, not on hope."""
    from src import constants

    monkeypatch.setattr(constants, "FASTEMBED_CACHE_DIR", str(tmp_path))
    assert el.fastembed_model_is_cached() is False

    nested = tmp_path / "models" / "minilm"
    nested.mkdir(parents=True)
    (nested / "model.onnx").write_bytes(b"\x00")
    assert el.fastembed_model_is_cached() is True
