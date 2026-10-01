# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vendor-specific model capability reader registry.

**Which readers decide anything** (`B970`, measured 2026-10-01): `ollama`
(`record_from_show_payload`, on `/api/show`) and `openrouter`
(`records_from_payload`, on the catalogue) answer
`src/chat_helpers.model_supports_vision`, with `detect_vendor` choosing which
endpoint is asked. LM Studio's answer is read by
`chat_helpers.lmstudio_supports_vision` directly: it predates these readers and
reads an explicit `vision: false` as no, which `lmstudio` reads as unknown
without a model `type`. `openai`, `google` and `generic_openai` have no
production caller — OpenAI's and Google's lists and the generic shape say
nothing about pictures (not wired, not pretended).

`llamacpp` (`B991`, 2026-10-01): `record_from_props_payload` answers
`chat_helpers.llamacpp_supports_vision` on a local llama-server's `/props` —
but only for an answer that carries `modalities.vision`, because this reader
reads a payload without it as text-only, and a server too old to report it
would otherwise take pictures away from a model the name list gets right.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.model_capability_readers import generic_openai, google, llamacpp, lmstudio, ollama, openai, openrouter
from src.model_capability_readers.base import (
    ModelCapabilityRecord,
    VENDOR_ANTHROPIC,
    VENDOR_GENERIC_OPENAI,
    VENDOR_GOOGLE,
    VENDOR_HUGGINGFACE,
    VENDOR_LLAMACPP,
    VENDOR_LMSTUDIO,
    VENDOR_OLLAMA,
    VENDOR_OPENAI,
    VENDOR_OPENROUTER,
    VENDOR_SGLANG,
    VENDOR_UNKNOWN,
    VENDOR_VLLM,
    detect_vendor,
    stable_model_id_for,
)


READER_MODULES = {
    VENDOR_GENERIC_OPENAI: generic_openai,
    VENDOR_OPENAI: openai,
    VENDOR_OPENROUTER: openrouter,
    VENDOR_GOOGLE: google,
    VENDOR_LLAMACPP: llamacpp,
    VENDOR_OLLAMA: ollama,
    VENDOR_LMSTUDIO: lmstudio,
}


PLACEHOLDER_VENDOR_IDS = frozenset(
    {
        VENDOR_ANTHROPIC,
        VENDOR_HUGGINGFACE,
        VENDOR_SGLANG,
        VENDOR_VLLM,
    }
)


def reader_for_vendor(vendor: Any):
    vendor_id = str(vendor or "").strip().lower().replace("-", "_")
    return READER_MODULES.get(vendor_id, generic_openai)


def records_from_payload(
    payload: Mapping[str, Any],
    *,
    vendor: str | None = None,
    base_url: str = "",
    endpoint_kind: str = "",
    endpoint_id: str = "",
) -> tuple[ModelCapabilityRecord, ...]:
    vendor_id = vendor or detect_vendor(base_url, endpoint_kind)
    reader = reader_for_vendor(vendor_id)
    if reader is generic_openai:
        record_vendor = vendor_id if vendor_id not in {VENDOR_UNKNOWN, ""} else VENDOR_GENERIC_OPENAI
        return reader.records_from_payload(
            payload,
            vendor_id=record_vendor,
            endpoint_id=endpoint_id,
            base_url=base_url,
        )
    return reader.records_from_payload(payload, endpoint_id=endpoint_id, base_url=base_url)


__all__ = [
    "ModelCapabilityRecord",
    "PLACEHOLDER_VENDOR_IDS",
    "READER_MODULES",
    "VENDOR_ANTHROPIC",
    "VENDOR_GENERIC_OPENAI",
    "VENDOR_GOOGLE",
    "VENDOR_HUGGINGFACE",
    "VENDOR_LLAMACPP",
    "VENDOR_LMSTUDIO",
    "VENDOR_OLLAMA",
    "VENDOR_OPENAI",
    "VENDOR_OPENROUTER",
    "VENDOR_SGLANG",
    "VENDOR_UNKNOWN",
    "VENDOR_VLLM",
    "detect_vendor",
    "reader_for_vendor",
    "records_from_payload",
    "stable_model_id_for",
]
