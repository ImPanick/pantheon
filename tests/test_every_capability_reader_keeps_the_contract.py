# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2160`. `base.CapabilityReader` declares what a vendor reader is — a
`vendor` and a `records_from_payload(payload, *, endpoint_id, base_url)` —
and nothing held a reader to it: the registry was an untyped dict and the
Protocol had no reference. The registry is typed by it now, and this test
holds every registered reader to it, by calling each one."""
from __future__ import annotations

import inspect
import typing

import src.model_capability_readers as registry
from src.model_capability_readers.base import CapabilityReader, ModelCapabilityRecord


def test_the_registry_is_declared_as_readers():
    hints = typing.get_type_hints(registry)
    assert hints["READER_MODULES"] == dict[str, CapabilityReader]


def test_every_reader_has_its_vendor_and_answers_a_payload():
    assert registry.READER_MODULES
    for key, reader in registry.READER_MODULES.items():
        assert reader.vendor == key, f"{reader.__name__} says it is {reader.vendor!r}"
        params = inspect.signature(reader.records_from_payload).parameters
        assert {"endpoint_id", "base_url"} <= set(params), reader.__name__
        assert params["endpoint_id"].kind is inspect.Parameter.KEYWORD_ONLY
        out = reader.records_from_payload({}, endpoint_id="ep", base_url="http://127.0.0.1:1")
        assert isinstance(out, tuple), reader.__name__
        assert all(isinstance(r, ModelCapabilityRecord) for r in out), reader.__name__


def test_an_unknown_vendor_reads_as_the_generic_reader():
    assert registry.reader_for_vendor("no-such-vendor") is registry.READER_MODULES["generic_openai"]
