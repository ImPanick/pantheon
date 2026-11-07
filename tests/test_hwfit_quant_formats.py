# SPDX-License-Identifier: AGPL-3.0-or-later
from services.hwfit.fit import analyze_model, rank_models
from services.hwfit.models import (
    get_models,
    infer_quantization_from_name,
    is_prequantized,
)


def _dual_5060ti_system():
    return {
        "has_gpu": True,
        "backend": "cuda",
        "gpu_name": "NVIDIA GeForce RTX 5060 Ti",
        "gpu_vram_gb": 31.0,
        "gpu_count": 2,
        "available_ram_gb": 128.0,
        "total_ram_gb": 128.0,
    }


def test_infers_native_hf_quant_formats_from_repo_names():
    cases = {
        "txn545/Qwen3.5-122B-A10B-NVFP4": "NVFP4",
        "some/model-MXFP4": "MXFP4",
        "some/model-NF4": "NF4",
        "some/model-FP4": "FP4",
        "some/model-W4A16": "W4A16",
        "some/model-W8A8": "W8A8",
        "some/model-W8A16": "W8A16",
        "some/model-INT4": "INT4",
        "some/model-8bit": "INT8",
    }
    assert {name: infer_quantization_from_name(name) for name in cases} == cases


def test_nvfp4_catalog_quant_is_preserved():
    catalog = {m["name"]: m for m in get_models()}
    model = catalog["txn545/Qwen3.5-122B-A10B-NVFP4"]

    assert model["quantization"] == "NVFP4"
    assert is_prequantized(model)


def test_nvfp4_search_result_is_not_gguf_or_cpu_offload():
    catalog = {m["name"]: m for m in get_models()}
    model = catalog["txn545/Qwen3.5-122B-A10B-NVFP4"]

    fit = analyze_model(model, _dual_5060ti_system())
    assert fit["quant"] == "NVFP4"
    assert fit["run_mode"] != "cpu_offload"

    results = rank_models(
        _dual_5060ti_system(),
        search="Qwen3.5-122B-A10B-NVFP4",
        limit=10,
    )
    hit = next(r for r in results if r["name"] == "txn545/Qwen3.5-122B-A10B-NVFP4")
    assert hit["quant"] == "NVFP4"
    assert hit["run_mode"] != "cpu_offload"


def test_selected_gguf_quant_is_strict_not_lower_quant_fallback():
    model = {
        "name": "local/Huge-GGUF",
        "provider": "local",
        "parameter_count": "100B",
        "parameters_raw": 100_000_000_000,
        "quantization": "Q4_K_M",
        "context_length": 4096,
    }

    system = _dual_5060ti_system()
    system["available_ram_gb"] = 80.0
    system["total_ram_gb"] = 80.0
    fit = analyze_model(model, system, target_quant="Q8_0")

    assert fit["quant"] == "Q8_0"
    assert fit["run_mode"] == "no_fit"


# ── `B1984` ──────────────────────────────────────────────────────────────────

_NATIVE_AWQ = {
    "name": "example/Model-8B-AWQ",
    "provider": "example",
    "parameter_count": "8.0B",
    "parameters_raw": 8_000_000_000,
    "quantization": "AWQ-4bit",
    "format": "awq",
    "context_length": 32768,
    "use_case": "General purpose text generation",
}


def _q4_awq_view(monkeypatch, system):
    """The models the Forge's "Q4 / AWQ" filter (`quant=Q4_K_M`) lists for
    `system`, with one native AWQ model in the catalog."""
    monkeypatch.setattr("services.hwfit.fit.get_models", lambda: [dict(_NATIVE_AWQ)])
    return [row["name"] for row in rank_models(system, quant="Q4_K_M")]


def test_one_nvidia_gpu_is_shown_native_awq_models_under_q4_awq(monkeypatch):
    """`B1984`. The Q4 view swapped in AWQ-4bit for a native AWQ model only
    with two or more GPUs, so a Linux server with one NVIDIA GPU, which vLLM
    and SGLang serve AWQ on, saw none under the filter named "Q4 / AWQ". Two
    GPUs see them as before; a host with no GPU, or an AMD GPU on Vulkan,
    still sees none, since nothing it runs serves AWQ (upstream's fix, which
    dropped the GPU count, listed them there too)."""
    one_nvidia = {"has_gpu": True, "backend": "cuda", "gpu_name": "NVIDIA GeForce RTX 4090",
                  "gpu_vram_gb": 24.0, "gpu_count": 1, "available_ram_gb": 64.0, "total_ram_gb": 64.0}
    assert _q4_awq_view(monkeypatch, one_nvidia) == [_NATIVE_AWQ["name"]]
    assert _q4_awq_view(monkeypatch, _dual_5060ti_system()) == [_NATIVE_AWQ["name"]]
    no_gpu = {"has_gpu": False, "backend": "cpu_x86", "gpu_name": None, "gpu_vram_gb": None,
              "gpu_count": 0, "available_ram_gb": 64.0, "total_ram_gb": 64.0}
    amd_on_vulkan = {**one_nvidia, "backend": "vulkan", "gpu_name": "AMD Radeon 780M"}
    assert _q4_awq_view(monkeypatch, no_gpu) == []
    assert _q4_awq_view(monkeypatch, amd_on_vulkan) == []
