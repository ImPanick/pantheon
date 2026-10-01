# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1071` — the style observer's record is not drawn as a blank memory card.

`P13-17` keeps a `kind: "style"` record in the memory store — *not a memory*,
in that row's words — and `GET /api/memory` lists it beside the memories so the
Brain can edit and delete it by id. Before a profile forms (`style.observed` <
`style.needed`) its text is `""`. Measured by `showcase` on the seeded demo:
`static/js/memory.js` drew it among the memories as an empty card reading only
*style · auto · 5m ago*, counted it (*8 memories* over seven) and gave it a
*style* chip.

`B820` says the Brain "renders none of it"; it rendered the record, empty, and
renders it with its text once a profile forms — which stays, because until
`B820`'s panel that card is the one place the profile can be read, corrected
or deleted (`Law 1`).

Driven on the real `memory.js` under node, in the sandbox
`tests/test_the_brain_says_it_is_loading.py` builds (the workshop shim, the
shipped `esc`, a MutationObserver the case plays the browser's part for).
"""

import json
import shutil

import pytest

from test_the_brain_says_it_is_loading import _LOADING_STUBS, _PREAMBLE  # noqa: E402
from test_the_workshop_surfaces_js import _SHIM, _index_ids, MEMORY_JS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The record as `src/memory.py:observe_style` writes it before a profile forms.
_UNFORMED = """
const UNFORMED = { id: 'sty', text: '', kind: 'style', category: 'style', source: 'auto',
                   timestamp: 9, style: { messages: 18 }, status: 'committed' };
const FORMED = { ...UNFORMED, text: 'You write in short sentences and rarely use exclamation marks.' };
const cards = () => byId('memory-list').querySelectorAll('.memory-item').map((el) => ({
  text: (el.querySelector('.memory-item-text') || { textContent: null }).textContent,
  meta: el.querySelector('.memory-item-meta') ? el.querySelector('.memory-item-meta').readable : '',
}));
const chips = () => byId('memory-category-filters').querySelectorAll('.memory-cat-chip')
  .map((c) => c.textContent);
const serve = (rows, style) => mockFetch((url) => (/\\/api\\/memory$/.test(url)
  ? res(200, { memory: rows, style }) : res(200, {})));
"""


@pytest.fixture(scope="module")
def brain(tmp_path_factory):
    shim = _SHIM.replace("__IDS__", json.dumps(_index_ids()))
    return _make_sandbox(tmp_path_factory.mktemp("stylecard"), MEMORY_JS, shim, _LOADING_STUBS)


def _brain(sandbox, script):
    return _run(sandbox, _PREAMBLE + _UNFORMED, script)


def test_before_a_profile_forms_the_record_is_not_a_card(brain):
    out = _brain(brain, """
        serve([UNFORMED, ...ROWS], { profile: null, observed: 18, needed: 20 });
        ready(); await tick();
        await openBrain();
        console.log(JSON.stringify({ cards: cards(), count: count(), tab: byId('memory-count').textContent,
                                     chips: chips() }));
    """)
    texts = [c["text"] for c in out["cards"]]
    assert all((t or "").strip() for t in texts), f"a blank card was drawn: {out['cards']}"
    assert sorted(texts) == sorted(["Rowan prefers tea to coffee", "The launch is on the 14th"])
    # Counted as what it is drawn as: two memories, not three.
    assert out["count"] == "2 memories"
    assert out["tab"] == "2"
    assert "style" not in out["chips"]


def test_a_store_holding_only_the_record_is_empty(brain):
    # A person who has chatted a little and saved nothing: the store holds one
    # record, and it is not a memory.
    out = _brain(brain, """
        serve([UNFORMED], { profile: null, observed: 3, needed: 20 });
        ready(); await tick();
        await openBrain();
        console.log(JSON.stringify({ cards: cards(), list: list(), count: count() }))
    """)
    assert out["cards"] == []
    assert "No memories yet" in out["list"]
    assert out["count"] == "0 memories"


def test_once_a_profile_forms_its_text_is_still_drawn(brain):
    # `Law 1`: the formed profile's card is how it is read, edited and deleted
    # today; this row takes away the blank one only.
    out = _brain(brain, """
        serve([FORMED, ...ROWS], { profile: { id: 'sty', sentences: [] }, observed: 20, needed: 20 });
        ready(); await tick();
        await openBrain();
        console.log(JSON.stringify({ cards: cards(), count: count() }));
    """)
    texts = [c["text"] for c in out["cards"]]
    assert "You write in short sentences and rarely use exclamation marks." in texts
    assert out["count"] == "3 memories"


def test_after_a_tidy_the_redrawn_list_has_no_blank_card(brain):
    # Tidy reads the list again on its own, after the audit; it draws the same
    # rows the window does.
    out = _brain(brain, """
        let after = false;
        mockFetch((url) => {
          if (/\\/api\\/memory\\/audit$/.test(url)) { after = true; return res(200, { removed: 1 }); }
          if (/\\/api\\/memory$/.test(url)) {
            return res(200, { memory: after ? [UNFORMED, ROWS[0]] : [UNFORMED, ...ROWS],
                              style: { profile: null, observed: 18, needed: 20 } });
          }
          return res(200, {});
        });
        ready(); await tick();
        await openBrain();
        await mem.tidyMemories();
        console.log(JSON.stringify({ cards: cards(), count: count() }));
    """)
    assert [c["text"] for c in out["cards"]] == ["Rowan prefers tea to coffee"]
    assert out["count"] == "1 memory"
