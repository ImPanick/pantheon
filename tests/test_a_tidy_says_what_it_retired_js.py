# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1578` — a memory tidy says what its decay sweep retired, and how to bring it back.

`POST /api/memory/audit` has answered `archived` since `P13-04`: the fade runs
first in every audit, before the model and before `before` is counted, and
retires what nothing has used in `ARCHIVE_AFTER_DAYS`. `tidyMemories`
(`static/js/memory.js`) never read it, so a tidy whose sweep retired two
memories said *Already clean* (the `already_tidy` short-circuit, the store the
sweep fires on most), or *Tidied: 0 removed*, or only why the model pass
stopped — and two memories left every chat with no word about where they went.

Driven on the real `memory.js` under node in the Brain's sandbox, the way
`B1569`'s test drives it (`tests/test_a_tidy_that_only_rewrote_says_it_rewrote_js.py`),
and the real audit handler with its pass answered by a stand-in.
"""

import json
import shutil

import pytest

from test_a_tidy_that_only_rewrote_says_it_rewrote_js import _CASE, _STUBS  # noqa: E402
from test_the_brain_says_it_is_loading import _PREAMBLE  # noqa: E402
from test_the_workshop_surfaces_js import _SHIM, _index_ids, MEMORY_JS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_tidy_names_its_model import _audit_route  # noqa: E402

_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The list as the server holds it after the sweep: both rows kept, both retired.
_RETIRED_AFTER = "ROWS.map((r) => ({ ...r, status: 'archived' }))"
# What `_CASE` returns, plus the status row the sentence points at.
_CHIPS = """
const chips = () => byId('memory-status-filters').querySelectorAll('button')
  .map((b) => b.textContent);
"""

SAYS_TWO = ("2 memories nothing had used in 180 days were retired: the “retired” "
            "filter lists them, and Bring back in a memory’s menu restores one.")


@pytest.fixture(scope="module")
def brain(tmp_path_factory):
    shim = _SHIM.replace("__IDS__", json.dumps(_index_ids()))
    return _make_sandbox(tmp_path_factory.mktemp("tidyretired"), MEMORY_JS, shim, _STUBS)


def _tidy(sandbox, audit: dict, after_js: str) -> dict:
    return _run(sandbox, _PREAMBLE + _CASE + _CHIPS,
                f"const out = await tidyWith({json.dumps(audit)}, {after_js});\n"
                "out.chips = chips();\n"
                "console.log(JSON.stringify(out));")


@_node
def test_an_already_tidy_store_that_retired_two_says_so_and_how_to_bring_them_back(brain):
    """The row's `Verify:` on the path the sweep fires on most — `already_tidy`."""
    out = _tidy(brain, {"ok": True, "before": 0, "after": 0, "removed": 0, "already_tidy": True,
                        "archived": 2, "archive_after_days": 180, "model": None}, _RETIRED_AFTER)
    assert out["said"] == [["toast", f"Already clean. {SAYS_TWO}"]], out
    # The filter the sentence names is on screen, because the list was drawn again.
    assert "retired 2" in out["chips"], out["chips"]


@_node
def test_a_tidy_that_merged_nothing_but_retired_two_is_not_just_clean(brain):
    out = _tidy(brain, {"ok": True, "before": 2, "after": 2, "removed": 0, "archived": 2,
                        "archive_after_days": 180, "model": "m"}, _RETIRED_AFTER)
    assert out["said"] == [["toast", f"Already clean. {SAYS_TWO}"]], out
    assert "retired 2" in out["chips"], out["chips"]


@_node
def test_a_tidy_that_merged_and_retired_says_both(brain):
    out = _tidy(brain, {"ok": True, "before": 2, "after": 1, "removed": 1, "superseded": 1,
                        "archived": 1, "archive_after_days": 180, "model": "m"}, "[ROWS[1]]")
    assert out["said"] == [["toast",
                            "Tidied by m: 1 removed (2 → 1) — 1 superseded, still on the "
                            "record. 1 memory nothing had used in 180 days was retired: the "
                            "“retired” filter lists it, and Bring back in its menu "
                            "restores it."]], out


@_node
def test_a_stopped_tidy_still_says_what_its_sweep_retired(brain):
    reason = "Tidy changed nothing: your model's answer was not a list of memories it could use."
    out = _tidy(brain, {"ok": False, "reason": reason, "before": 2, "after": 2, "removed": 0,
                        "archived": 2, "archive_after_days": 180}, _RETIRED_AFTER)
    assert out["said"] == [["error", f"{reason} Separately, {SAYS_TWO}"]], out
    assert "retired 2" in out["chips"], out["chips"]


@_node
def test_a_tidy_that_retired_nothing_says_nothing_about_it(brain):
    out = _tidy(brain, {"ok": True, "before": 2, "after": 2, "removed": 0, "already_tidy": True,
                        "archived": 0, "archive_after_days": 180, "model": None}, "ROWS")
    assert out["said"] == [["toast", "Already clean"]], out


def test_the_route_carries_the_window_that_retired_them(monkeypatch):
    from src.memory import ARCHIVE_AFTER_DAYS

    out = _audit_route(monkeypatch, {"before": 3, "after": 3, "already_tidy": True, "archived": 2})
    assert out["archived"] == 2
    assert out["archive_after_days"] == ARCHIVE_AFTER_DAYS
