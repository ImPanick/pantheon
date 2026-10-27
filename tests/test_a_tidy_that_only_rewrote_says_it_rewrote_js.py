# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1569` — a memory tidy that only rewrote memories says so, and shows the edit.

`tidyMemories` (`static/js/memory.js`) returned *Already clean* whenever the
audit's `removed` was 0 — before the diff below it that finds edited text.
`removed` is `before - after` (`routes/memory/memory_routes.py`), so a pass
that merged nothing and rewrote one memory's text answered 0 and was called
clean while the rewritten text sat in the list unannounced.

The same early return caught a pass that stopped: the model's reply was not a
usable list, it would have removed most of the store, or the store could not be
read back. Each answers 200 with `ok: false` and `before == after`, so each
said *Already clean* about a tidy that did nothing. The route now carries the
sentence (`reason`) and the Brain says it.

Driven on the real `memory.js` under node, in the Brain's sandbox
(`tests/test_the_brain_says_it_is_loading.py`), with `ui.js`'s toasts and
errors recorded; and the real audit handler with its pass answered by a
stand-in (`tests/test_tidy_names_its_model.py`'s `_audit_route`).
"""

import json
import shutil

import pytest

from test_the_brain_says_it_is_loading import _LOADING_STUBS, _PREAMBLE  # noqa: E402
from test_the_workshop_surfaces_js import _SHIM, _index_ids, MEMORY_JS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.esc_stub import empty_state_source, ui_default_stub
from test_tidy_names_its_model import _audit_route  # noqa: E402

_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_STUBS = dict(_LOADING_STUBS)
_STUBS["ui.js"] = ui_default_stub(
    "showToast: (m) => { globalThis.__said.push(['toast', String(m)]); },"
    " showError: (m) => { globalThis.__said.push(['error', String(m)]); },"
    " styledConfirm: async () => true,"
    " copyToClipboard: () => {}, el: (id) => document.getElementById(id),"
    " debounce: (f) => f, emptyStateIcon, renderEmptyState,",
    before="globalThis.__said = globalThis.__said || [];\n" + empty_state_source())

_CASE = """
const tidyWith = async (audit, after) => {
  let done = false;
  mockFetch((url) => {
    if (/\\/api\\/memory\\/audit$/.test(url)) { done = true; return res(200, audit); }
    if (/\\/api\\/memory$/.test(url)) return res(200, { memory: done ? after : ROWS, style: STYLE });
    return res(200, {});
  });
  ready(); await tick();
  await openBrain();
  // What the animation does to each card, recorded as it happens.
  const seen = [];
  for (const el of byId('memory-list').querySelectorAll('.memory-item')) {
    const add = el.classList.add.bind(el.classList);
    el.classList.add = (...c) => { seen.push(c.join(' ')); return add(...c); };
  }
  globalThis.__said.length = 0;
  await mem.tidyMemories();
  const texts = byId('memory-list').querySelectorAll('.memory-item')
    .map((el) => (el.querySelector('.memory-item-text') || {}).textContent);
  return { said: [...globalThis.__said], seen, texts };
};
"""

REWRITTEN = "Rowan prefers green tea to coffee"


@pytest.fixture(scope="module")
def brain(tmp_path_factory):
    shim = _SHIM.replace("__IDS__", json.dumps(_index_ids()))
    return _make_sandbox(tmp_path_factory.mktemp("tidyrewrite"), MEMORY_JS, shim, _STUBS)


def _tidy(sandbox, audit: dict, after_js: str) -> dict:
    return _run(sandbox, _PREAMBLE + _CASE,
                f"console.log(JSON.stringify(await tidyWith({json.dumps(audit)}, {after_js})));")


@_node
def test_a_tidy_that_rewrote_one_and_merged_none_says_it_rewrote_one(brain):
    """The row's `Verify:` — it says it rewrote one, and animates the edit."""
    out = _tidy(brain, {"ok": True, "before": 2, "after": 2, "removed": 0, "superseded": 0,
                        "contradictions": 0, "model": "qwen3-utility-8b"},
                f"[{{ ...ROWS[0], text: {json.dumps(REWRITTEN)} }}, ROWS[1]]")
    assert out["said"] == [["toast", "Tidied by qwen3-utility-8b: 1 rewritten, 0 removed (2 → 2)"]], out
    assert "memory-tidy-editing" in out["seen"], f"the edit was not animated: {out['seen']}"
    assert REWRITTEN in out["texts"], out["texts"]


@_node
def test_a_tidy_that_changed_nothing_is_still_already_clean(brain):
    out = _tidy(brain, {"ok": True, "before": 2, "after": 2, "removed": 0, "model": "m"}, "ROWS")
    assert out["said"] == [["toast", "Already clean"]], out
    out = _tidy(brain, {"ok": True, "before": 2, "after": 2, "removed": 0, "already_tidy": True,
                        "model": None}, "ROWS")
    assert out["said"] == [["toast", "Already clean"]], out


@_node
def test_a_tidy_that_stopped_says_why_and_not_that_it_is_clean(brain):
    reason = "Tidy changed nothing: your model's answer would have removed more than half"
    out = _tidy(brain, {"ok": False, "reason": reason, "before": 2, "after": 2, "removed": 0},
                "ROWS")
    assert out["said"] == [["error", reason]], out


@_node
def test_a_tidy_that_merged_still_says_what_it_removed(brain):
    out = _tidy(brain, {"ok": True, "before": 2, "after": 1, "removed": 1, "superseded": 1,
                        "model": "m"}, "[ROWS[1]]")
    assert out["said"] == [["toast", "Tidied by m: 1 removed (2 → 1) — 1 superseded, "
                                      "still on the record"]], out


@pytest.mark.parametrize("code, words", [
    ("bad_json", "not a list of memories it could use"),
    ("unsafe_removal", "more than half of your memories"),
    ("store_unreadable", "could not be read back"),
])
def test_the_route_says_why_a_stopped_tidy_changed_nothing(monkeypatch, code, words):
    out = _audit_route(monkeypatch, {"before": 4, "after": 4, "archived": 0, "error": code})
    assert out["ok"] is False and out["removed"] == 0
    assert out["reason"].startswith("Tidy changed nothing") and words in out["reason"], out


def test_a_tidy_that_ran_carries_no_reason(monkeypatch):
    out = _audit_route(monkeypatch, {"before": 4, "after": 3, "superseded": 1})
    assert out["ok"] is True and out["reason"] == ""
