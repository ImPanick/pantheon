# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1805`. A category filter outlived its last memory and emptied the Brain's list.

The Brain's category chips (`buildCategoryChips` in `static/js/memory.js`) are
drawn again from the memories on every load, but the chosen category was never
checked against them. Choose *project*, delete or recategorise the last project
memory, and the reload drew the chips without *project*, kept the hidden filter
on, and listed nothing: "No matches." with no chip lit. When the last memory of
all went, the empty Brain said "No matches." rather than "No memories yet.",
and the old filter came back with the next memory.

Now a chosen category that nothing is in any more falls back to *all*, in the
same redraw, which is the rule `B710` already applies to the status row beside
it. Ported from upstream Odysseus a6e92943 (#6918), which has no test. These
drive the real module through `B710`'s Brain harness (`Law 20`).
"""
import json
import shutil

import pytest

from tests.test_a_proposal_is_visible_before_it_binds import _run, sandbox  # noqa: F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

FACT = {"id": "m1", "text": "Lives in Leeds", "category": "fact", "timestamp": 1760000000}
PROJECT = {"id": "m2", "text": "Ships the beta in May", "category": "project",
           "timestamp": 1760000100}
PROJECT_TWO = {"id": "m3", "text": "The beta needs a changelog", "category": "project",
               "timestamp": 1760000200}

#: Load a store, choose `project`, then load what the store holds afterwards.
_NARROW_THEN_RELOAD = """
    const host = () => document.getElementById('memory-category-filters');
    const seen = () => ({
      rows: rows().map((r) => r.id),
      chips: host().querySelectorAll('button').map((b) => [b.dataset.cat, b.className]),
      list: document.getElementById('memory-list').readable,
    });
    page();
    store(%s);
    await brain.loadMemories();
    await settle();
    click(host().querySelectorAll('button').find((b) => b.dataset.cat === 'project'));
    await settle();
    const narrowed = seen();
    store(%s);
    await brain.loadMemories();
    await settle();
    const after = seen();
    store(%s);
    await brain.loadMemories();
    await settle();
    console.log(JSON.stringify({ narrowed, after, next: seen() }));
"""


def _narrow_then_reload(sandbox, before, after, then=None):  # noqa: F811
    return _run(sandbox, _NARROW_THEN_RELOAD % (
        json.dumps(before), json.dumps(after), json.dumps(after if then is None else then)))


@pytest.mark.parametrize("left", [
    [FACT],
    [FACT, {**PROJECT, "category": "fact"}],
], ids=["deleted", "recategorised"])
def test_when_the_chosen_category_s_last_memory_goes_the_rest_are_listed(sandbox, left):  # noqa: F811
    out = _narrow_then_reload(sandbox, [FACT, PROJECT], left)

    assert out["narrowed"]["rows"] == ["m2"]
    assert sorted(out["after"]["rows"]) == sorted(m["id"] for m in left), out["after"]["list"]
    assert out["after"]["chips"][0] == ["all", "memory-cat-chip active"], out["after"]["chips"]
    assert "No matches" not in out["after"]["list"]


def test_when_the_last_memory_of_all_goes_the_brain_says_it_is_empty(sandbox):  # noqa: F811
    out = _narrow_then_reload(sandbox, [PROJECT], [], then=[FACT, PROJECT_TWO])

    assert "No memories yet" in out["after"]["list"], out["after"]["list"]
    assert "No matches" not in out["after"]["list"], "an empty store is not a filtered one"
    assert sorted(out["next"]["rows"]) == ["m1", "m3"], "the old filter came back with the next memory"
    assert out["next"]["chips"][0] == ["all", "memory-cat-chip active"]


def test_a_chosen_category_that_still_has_memories_stays_chosen(sandbox):  # noqa: F811
    out = _narrow_then_reload(sandbox, [FACT, PROJECT, PROJECT_TWO], [FACT, PROJECT])

    assert out["after"]["rows"] == ["m2"]
    assert ["project", "memory-cat-chip active"] in out["after"]["chips"]
    assert ["all", "memory-cat-chip"] in out["after"]["chips"]
