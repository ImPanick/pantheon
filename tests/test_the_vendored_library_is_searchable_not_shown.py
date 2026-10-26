# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B869` / `B868`, the owner's call (`D-2026-10-26-01` §8) — the 286 vendored
ECC skills stay out of the model's default catalogue; they remain searchable
and viewable.

**Measured before this file:** they were out only by coincidence — every ECC
file parses as a `draft` at `confidence: 0.8` under the shipped `0.85` floor —
so a sync that marked them `published` would have put all 286 in every prompt.
"""

from __future__ import annotations

from services.memory.skills import VENDORED_LIBRARY, SkillsManager

SKILL = """---
name: {name}
description: Make a web page readable to a screen reader, step by step
status: {status}
confidence: 0.99
tags: [accessibility, a11y]
---
1. Check the headings.
"""


def _store(tmp_path, status):
    lib = tmp_path / "ecc" / "skills"
    (lib / "a11y-audit").mkdir(parents=True)
    (lib / "a11y-audit" / "SKILL.md").write_text(SKILL.format(name="a11y-audit", status=status))
    return SkillsManager(str(tmp_path / "data"), library_root=str(lib))


def test_a_vendored_skill_is_never_in_the_catalogue_even_marked_published(tmp_path):
    for status in ("draft", "published"):
        store = _store(tmp_path / status, status)
        assert [s["library"] for s in store.load_active(owner="ada")] == [VENDORED_LIBRARY]
        assert store.index_for(owner="ada") == [], status
        assert store.injectable_skills(owner="ada") == [], status


def test_it_is_still_found_by_a_search_and_opened_by_name(tmp_path):
    store = _store(tmp_path, "published")
    hits = store.get_relevant_skills("accessibility screen reader", skills=store.load_active(owner="ada"),
                                     threshold=0.0)
    assert [h["name"] for h in hits] == ["a11y-audit"]
    assert "Check the headings" in (store.read_skill_md("a11y-audit", owner="ada", include_library=True) or "")


def test_the_shipped_store_shows_the_model_no_vendored_skill():
    """Against what actually ships: the first-party skills may be in the
    catalogue; none of the vendored ones are."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        store = SkillsManager(d)
        vendored = {s["name"] for s in store.load_active(owner="ada") if s.get("library") == VENDORED_LIBRARY}
        assert len(vendored) > 100, "the vendored library ships"
        shown = {s["name"] for s in store.index_for(owner="ada")}
        assert not (shown & vendored)
