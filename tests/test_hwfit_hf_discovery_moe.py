# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1970`. A mixture-of-experts model from a Hugging Face collection was
rated as a dense one.

HW Fit builds a row for each model in the collections the Forge follows, once
an admin turns its Hugging Face switch on. A MoE row needs its active size,
the "-A3B" in "Qwen3-30B-A3B": the speed estimate runs on it, and the
llama.cpp expert offload and the Quality profile key off `is_moe`. The name is
the only place that size is written, and the parser read the name only when
Hugging Face sent no `numParameters`, which it sends for nearly every model.
So a 30B-A3B row came out dense, its estimate about eight times too slow.

The name is read every time now, and Hugging Face's total still wins over the
name's. A name's active size counts only below the row's total, so a small
draft model named after its 30B-A3B target stays dense.

From upstream Odysseus b88154ec (#6729), whose three cases are here; the
total guard and the draft model are Pantheon's.
"""
from services.hwfit.hf_discovery import _entry_from_collection_item

_SOURCE = {"owner": "Qwen", "provider": "Qwen"}
_COLLECTION = {"title": "Qwen3.6"}


def _item(repo_id, num_params):
    item = {"id": repo_id, "type": "model", "pipeline_tag": "text-generation"}
    if num_params is not None:
        item["numParameters"] = num_params
    return item


def _entry(repo_id, num_params):
    return _entry_from_collection_item(_COLLECTION, _item(repo_id, num_params), _SOURCE)


def test_a_moe_row_keeps_its_active_size_when_hugging_face_gives_its_total():
    entry = _entry("Qwen/Qwen3.6-35B-A3B", 35_951_822_704)
    assert entry["parameters_raw"] == 35_951_822_704
    assert entry["is_moe"] is True
    assert entry["active_parameters"] == 3_000_000_000
    # Without a count from Hugging Face the name gives both, as before.
    entry = _entry("Qwen/Qwen3-Coder-30B-A3B-Instruct", None)
    assert entry["parameters_raw"] == 30_000_000_000
    assert entry["is_moe"] is True
    assert entry["active_parameters"] == 3_000_000_000


def test_a_row_is_moe_only_when_its_name_gives_an_active_size_below_its_total():
    entry = _entry("Qwen/Qwen-AgentWorld-35B-A3B", 35_951_822_704)
    assert (entry["is_moe"], entry["active_parameters"]) == (True, 3_000_000_000)
    # A dense model keeps Hugging Face's count and no MoE fields.
    entry = _entry("Qwen/Qwen3.6-27B", 27_781_427_952)
    assert entry["parameters_raw"] == 27_781_427_952
    assert "is_moe" not in entry and "active_parameters" not in entry
    # A 522M draft model named after its 30B-A3B target is not a MoE model
    # with 3B of its 0.5B active.
    entry = _entry("RedHatAI/Qwen3-30B-A3B-Instruct-2507-speculator.eagle3", 522_152_832)
    assert entry["parameters_raw"] == 522_152_832
    assert "is_moe" not in entry and "active_parameters" not in entry
