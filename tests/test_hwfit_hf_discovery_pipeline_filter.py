# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1971`. HW Fit ranked image, video and vision models as LLMs.

The Hugging Face collections the Forge follows mix in models no LLM engine
serves: vision encoders, a time-series forecaster, image and video
generators. HW Fit's collection parser kept all of them, so zai-org/CogView4-6B
(text-to-image) became a "general" row offered for vLLM and SGLang. The
bundled mlx-community catalog, which the ranking reads whether or not the
Hugging Face switch is on, holds twenty more (Lens, Boogu-Image,
LongCat-Video, SigLIP2 and others), listed on every Apple Silicon host as
general MLX LLMs.

The parser now skips a model whose pipeline tag is one of seven non-LLM tags,
and get_models applies the same test to every cached and bundled row it
reads, so a cache written before this and the bundled file are covered too.
The bundled file keeps its rows, as the offline source; the Image list has its
own registry and is untouched.

From upstream Odysseus 63feb227 (#6731), whose cases are here. The get_models
filter is Pantheon's: upstream had emptied its bundled catalogs, so its parser
was the whole of its catalog.
"""
import json
from pathlib import Path

from services.hwfit import hf_discovery
from services.hwfit import models as hwfit_models
from services.hwfit.hf_discovery import _entry_from_collection_item

_SOURCE = {"owner": "google", "provider": "Google"}
_COLLECTION = {"title": "collection"}
_BUNDLED_MLX = (Path(hwfit_models.__file__).resolve().parent
                / "data" / "mlx_community_models.json")

# The seven tags no engine the Forge runs serves as an LLM.
_NON_LLM_TAGS = {
    "time-series-forecasting", "zero-shot-image-classification", "image-classification",
    "image-feature-extraction", "text-to-image", "image-to-video", "text-to-video",
}
_NOT_LLMS = [
    ("google/timesfm-3.0-pytorch", "time-series-forecasting"),
    ("google/siglip2-base-patch16-224", "zero-shot-image-classification"),
    ("moonshotai/MoonViT-SO-400M", "image-feature-extraction"),
    ("zai-org/CogView4-6B", "text-to-image"),
    ("zai-org/CogVideoX-5b-I2V", "image-to-video"),
    ("zai-org/CogVideoX1.5-5B", "text-to-video"),
    ("google/vit-huge-patch14-224-in21k", " Image-Classification "),
]
_SERVABLE = [
    ("google/gemma-4-12B-it", "image-text-to-text"),
    ("Qwen/Qwen3.6-27B", "text-generation"),
    ("Qwen/Qwen3-Embedding-4B", "feature-extraction"),
    ("NousResearch/DeepHermes-Egregore-v2-RLAIF-8b-Atropos", "reinforcement-learning"),
    ("Qwen/Qwen3-Next-80B-A3B-Instruct", ""),
    # A tag that is not a string is no tag, not a reason to fail the page.
    ("Qwen/Qwen3-8B", 7),
]


def _offered(repo_id, tag, num_params):
    item = {"id": repo_id, "type": "model", "pipeline_tag": tag, "numParameters": num_params}
    return _entry_from_collection_item(_COLLECTION, item, _SOURCE) is not None


def test_a_collection_model_that_no_llm_engine_serves_gets_no_llm_row():
    assert [m for m in _NOT_LLMS if _offered(*m, 1_000_000_000)] == []
    assert [m for m in _SERVABLE if not _offered(*m, 4_000_000_000)] == []


def test_the_llm_ranking_reads_no_such_model_from_a_cache_or_the_bundled_file(monkeypatch):
    monkeypatch.setattr(hwfit_models, "_models_cache", None)
    monkeypatch.setattr(hf_discovery, "load_cached_hf_collection_models", lambda: [
        {"name": "zai-org/CogView4-6B", "pipeline_tag": "text-to-image",
         "parameters_raw": 6_000_000_000, "use_case": "general"},
        {"name": "example-org/Chat-9B", "pipeline_tag": "text-generation",
         "parameters_raw": 9_000_000_000, "use_case": "general"},
    ])
    monkeypatch.setattr(hf_discovery, "load_cached_mlx_community_models", lambda: [])
    rows = hwfit_models.get_models()
    names = {r["name"] for r in rows}
    offending = [r["name"] for r in rows
                 if str(r.get("pipeline_tag") or "").strip().lower() in _NON_LLM_TAGS]
    assert offending == []
    assert "zai-org/CogView4-6B" not in names
    assert "mlx-community/Lens-3.8B-4bit" not in names
    # What is an LLM stays, from the cache and from the bundled file.
    assert "example-org/Chat-9B" in names
    bundled = json.loads(_BUNDLED_MLX.read_text(encoding="utf-8"))
    text_rows = [r["name"] for r in bundled if r.get("pipeline_tag") == "text-generation"]
    assert text_rows and set(text_rows) <= names
    # The file itself is not edited: it is still the offline source.
    assert any(r["name"] == "mlx-community/Lens-3.8B-4bit" for r in bundled)
