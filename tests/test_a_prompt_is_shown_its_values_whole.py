# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1883` (`prompt-values-clipped`) — an AI step is shown the values it reads whole, up to a setting, and says when it was not.

An AI (Prompt or Skill) step's references travel to the model in their own
untrusted block (`P22-09`). Each value was cut to 2,000 characters and the
block to 6,000 — the numbers a trigger payload is shown at — so the most
common automation, *fetch a page, then summarise
`{{ steps.fetch.data.body }}`*, quietly summarised the first 2,000
characters, and nothing on the step said so.

Now the values together are held to `workflow_prompt_values_max_chars`
(20,000 characters as shipped, from 2,000 to 1,000,000; settings-only, one
number for the install). Within it every value is shown whole. Past it the
longest values are cut first, each to the same length, so a short title
beside a long body is never cut (`workflow_refs.fit_values`); each cut value
ends saying how much of it is shown, and the step's log says which values
were cut and names the setting.

Who is the adversary (`Law 17`): nobody new — the values still travel only
in the untrusted block with the gate armed; this changes how much of them,
and the cap is mistake prevention (a model's context is finite), not a
control.
"""

from __future__ import annotations

import pytest

from src import workflow_refs as refs  # noqa: E402
from tests.helpers.walker_harness import (  # noqa: E402
    arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow,
)

pytestmark = pytest.mark.asyncio


# ── Fitting values to a budget (pure) ────────────────────────────────────────

async def test_values_within_the_budget_are_shown_whole():
    texts = ["Weekly report", "x" * 9_000, "y" * 9_000]
    shown, cut = refs.fit_values(texts, 20_000)
    assert shown == texts and cut == ()


async def test_past_the_budget_the_longest_are_cut_first_and_a_short_one_never():
    texts = ["Weekly report", "x" * 30_000, "y" * 12_000, "z" * 3_000]
    shown, cut = refs.fit_values(texts, 20_000)
    assert shown[0] == "Weekly report" and shown[3] == "z" * 3_000
    assert [i for i, _kept, _total in cut] == [1, 2]
    assert sum(len(s) for s in shown) <= 20_000
    # Cut to the same length: what is left is shared between the long ones.
    assert abs(len(shown[1]) - len(shown[2])) <= 1
    assert len(shown[1]) > 8_000
    for i, kept, total in cut:
        assert shown[i].startswith(texts[i][:kept])
        assert shown[i].endswith(f"(cut here: the first {kept:,} of its {total:,} characters are shown)")
        assert total == len(texts[i]) and kept < total


async def test_one_value_is_cut_to_the_budget_and_says_so():
    shown, cut = refs.fit_values(["a" * 50_000], 2_000)
    assert len(shown[0]) <= 2_000 and shown[0].startswith("a" * 1_900)
    assert cut == ((0, len(shown[0].split("\n")[0]), 50_000),)


@pytest.mark.parametrize("budget", [2_000, 5_000, 20_000, 100_000])
async def test_whatever_the_budget_the_values_fit_it(budget):
    import random
    rng = random.Random(budget)
    for _ in range(40):
        texts = ["q" * rng.choice((0, 5, 80, 1_500, 9_000, 60_000)) for _ in range(rng.randint(1, 7))]
        shown, cut = refs.fit_values(texts, budget)
        assert sum(len(s) for s in shown) <= budget
        assert bool(cut) == (sum(len(t) for t in texts) > budget)
        whole = [i for i in range(len(texts)) if i not in {c[0] for c in cut}]
        assert all(shown[i] == texts[i] for i in whole)
        # Nothing kept whole is longer than anything that was cut.
        assert all(len(texts[i]) <= len(texts[c[0]]) for i in whole for c in cut)


# ── The setting ──────────────────────────────────────────────────────────────

async def test_the_budget_is_a_setting_held_to_its_range():
    import src.settings as S
    from src import workflow_runs as wr
    assert (wr.PROMPT_VALUES_MAX_CHARS_SETTING, wr.PROMPT_VALUES_MAX_CHARS_DEFAULT,
            wr.PROMPT_VALUES_MAX_CHARS_RANGE) == ("workflow_prompt_values_max_chars", 20_000,
                                                  (2_000, 1_000_000))
    assert S.DEFAULT_SETTINGS["workflow_prompt_values_max_chars"] == 20_000
    assert S.int_setting_ranges()["workflow_prompt_values_max_chars"] == (2_000, 1_000_000)
    assert S.clamp_int_setting("workflow_prompt_values_max_chars", 10) == 2_000
    assert S.clamp_int_setting("workflow_prompt_values_max_chars", 10**9) == 1_000_000
    assert wr.prompt_values_max_chars() == 20_000


# ── A run ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def world(monkeypatch, tmp_path):
    import src.settings as S
    factory = make_db(monkeypatch, tmp_path / "values.db")
    values = {}
    real, real_explicit = S.get_setting, S.setting_is_explicit
    monkeypatch.setattr(S, "get_setting",
                        lambda key, default=None: values[key] if key in values else real(key, default))
    monkeypatch.setattr(S, "setting_is_explicit", lambda key: key in values or real_explicit(key))

    class World:
        pass
    w = World()
    w.factory, w.values, w.s = factory, values, recording_scheduler()
    return w


BODY = "The page says: " + "lorem ipsum " * 1_000          # 12,015 characters


def _seed(w):
    seed_workflow(w.factory, [
        node("fetch", "Fetch the page", "set", fields=[
            {"name": "title", "value": "Release notes"}, {"name": "body", "value": BODY}]),
        node("sum", "Summarise", "llm",
             prompt="Summarise {{ steps.fetch.data.body }}, titled {{ steps.fetch.data.title }}."),
    ], [arrow("fetch", "sum")])


def _block(w):
    [call] = [c for c in w.s.calls if c["kind"] == "llm"]
    [msg] = [m for m in call["slot_state"]["context_messages"]
             if "values this step was handed" in str(m.get("content"))]
    return str(msg["content"])


async def test_a_page_of_twelve_thousand_characters_is_summarised_whole(world):
    """It was cut at 2,000 with nothing said."""
    w = world
    _seed(w)
    await w.s._execute_task("wf")
    [run] = runs_of(w.factory, "wf")
    assert run["status"] == "success", run
    block = _block(w)
    assert BODY.strip() in block and "[title] = Release notes" in block
    assert "cut here" not in block and "(truncated)" not in block
    rec = {r["node_id"]: r for r in records_of(w.factory, run["id"])}["sum"]
    assert not any("workflow_prompt_values_max_chars" in str(st.get("detail")) for st in rec["steps"])


async def test_past_the_setting_the_body_is_cut_the_title_is_not_and_the_step_says_so(world):
    w = world
    w.values["workflow_prompt_values_max_chars"] = 5_000
    _seed(w)
    await w.s._execute_task("wf")
    [run] = runs_of(w.factory, "wf")
    assert run["status"] == "success", run
    block = _block(w)
    assert "[title] = Release notes" in block
    assert BODY.strip()[:4_000] in block and BODY.strip() not in block
    assert f"of its {len(BODY.strip()):,} characters are shown)" in block
    rec = {r["node_id"]: r for r in records_of(w.factory, run["id"])}["sum"]
    said = [str(st.get("detail")) for st in rec["steps"]
            if "workflow_prompt_values_max_chars" in str(st.get("detail"))]
    assert len(said) == 1, rec["steps"]
    line = said[0]
    assert line.startswith("The model was shown only the start of {{ steps.fetch.data.body }} (")
    assert f"of {len(BODY.strip()):,} characters" in line
    assert "steps.fetch.data.title" not in line
    assert "5,000 characters" in line
