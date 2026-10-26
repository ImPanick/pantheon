# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1260` — with the hubs off, the Forge's Image list was empty after a restart.

`services/hwfit/image_models.IMAGE_MODEL_REGISTRY` is empty by design, and the
rows fetched from Hugging Face's image collections lived only in that module's
memory (`_HF_COLLECTION_CACHE`) — while the LLM catalog beside it is written to
`data/hwfit/*.json`. So with the switch off, the Image type showed what this
process had fetched, else nothing. Now a fetch keeps its rows in
`data/hwfit/image_collection_models.json` (`hf_discovery`'s cache shape), and
off — or when every collection fails — those rows answer.

Driven through the real `/api/hwfit/image-models` handler with `B1229`'s world
(`datadir`, the limiter spy `asked`, the socket tripwire `no_egress`): the one
request function, `_hf_get_json`, answers from a recorded collection while the
switch is on, and the restart is the in-memory cache emptied.
"""
from __future__ import annotations

import json

import pytest

import services.hwfit.image_models as image_models
from tests.test_no_egress_on_boot import no_egress  # noqa: F401 — the socket tripwire
from tests.test_the_forge_reaches_hugging_face_only_when_an_admin_says import (  # noqa: F401
    _hwfit,
    _switch,
    asked,
    datadir,
    direct,
)

_COLLECTION = {
    "title": "FLUX.2",
    "items": [{"id": "black-forest-labs/FLUX.2-klein-4B", "type": "model",
               "pipeline_tag": "text-to-image"}],
}


@pytest.fixture
def collections(monkeypatch):
    """`_hf_get_json` — the one request in `image_models` — answering from a
    recorded collection, and counting how often it is asked."""
    calls = []

    def _get(url, *, timeout=2.5):
        calls.append(url)
        return _COLLECTION if url.endswith("/black-forest-labs/flux2") else None

    monkeypatch.setattr(image_models, "_hf_get_json", _get)
    monkeypatch.setattr(image_models, "_HF_COLLECTION_CACHE", {"ts": 0.0, "models": []})
    return calls


def _restart(monkeypatch):
    monkeypatch.setattr(image_models, "_HF_COLLECTION_CACHE", {"ts": 0.0, "models": []})


def _listed():
    return [m["id"] for m in _hwfit("/image-models")(sort="fit")["models"]]


def test_rows_fetched_while_on_are_the_list_after_a_restart_with_the_hubs_off(
        datadir, collections, monkeypatch):
    """The row's case: on once, then a restart, then off."""
    _switch(True)
    assert _listed() == ["black-forest-labs/FLUX.2-klein-4B"]
    kept = json.loads((datadir / "hwfit" / "image.json").read_text())
    assert [m["id"] for m in kept["models"]] == ["black-forest-labs/FLUX.2-klein-4B"]

    _restart(monkeypatch)
    _switch(False)
    collections.clear()
    assert _listed() == ["black-forest-labs/FLUX.2-klein-4B"]
    assert collections == [], "the list was read from disk, not fetched"


def test_off_with_kept_rows_reaches_no_one(datadir, direct, asked, no_egress):  # noqa: F811
    """`Law 16`: the kept rows are read, and nothing leaves the machine — the
    limiter is asked for no host and no socket is opened."""
    (datadir / "hwfit").mkdir(parents=True, exist_ok=True)
    (datadir / "hwfit" / "image.json").write_text(json.dumps({"models": [
        image_models._collection_item_to_model(_COLLECTION["items"][0], "FLUX.2")]}))
    _switch(False)
    assert _listed() == ["black-forest-labs/FLUX.2-klein-4B"]
    assert asked == [] and no_egress == []


def test_a_fetch_that_finds_nothing_does_not_wipe_the_kept_rows(datadir, collections, monkeypatch):
    _switch(True)
    _listed()
    _restart(monkeypatch)
    monkeypatch.setattr(image_models, "_hf_get_json", lambda url, *, timeout=2.5: None)
    assert _listed() == ["black-forest-labs/FLUX.2-klein-4B"], "the kept rows answer"
    kept = json.loads((datadir / "hwfit" / "image.json").read_text())
    assert kept["models"], "an empty fetch was written over them"


def test_off_with_nothing_kept_is_still_empty(datadir):
    """An install that never had the hubs on has nothing to show, as before;
    the Forge's line says why (`B1229`)."""
    _switch(False)
    assert _listed() == []
