# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-03` — the handler was not dead; the emit was missing.

The row asks the question before the fix: *"Establish first whether the
**handler** is dead or the **emit** is missing — a save that never notifies the
UI is a `Law 13` gap, not dead code, and deleting the listener would close it
the wrong way. Decide on the row and record which it was."*

**It was the emit.** `chat.js` has three listeners in this family and
`src/teacher_escalation.py` emits two of them:

    skill_save_failed    3 emit sites   "teacher said NO_SKILL"
                                        "teacher did not emit valid skill JSON"
                                        "requires an interactive exact approval"
    escalation_failed    2 emit sites
    skill_saved          0

So every way of *failing* to save a skill reported, and succeeding was the one
outcome nobody was told about. Deleting the listener would have made the
silence permanent and looked like tidying up.

The save itself happens in two places, because a teacher-written skill goes
through an approval card and an agent-written one does not, so both completion
paths emit. `manage_skills` reports what it saved in a `skill_saved` key on its
result — additive, and the deduped branch returns before it, because nothing
was saved there.
"""

import asyncio
import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CHAT = _REPO / "static" / "js" / "chat.js"
_LOOP = _REPO / "src" / "agent_loop.py"
_ESCALATION = _REPO / "src" / "teacher_escalation.py"


# ── the finding ───────────────────────────────────────────────────────────────


def test_the_failure_events_this_pairs_with_are_still_emitted():
    # The evidence that decided the row: the handler is one of three, and the
    # other two have emitters. A listener with two working siblings is not
    # dead code.
    text = _ESCALATION.read_text(encoding="utf-8")
    assert text.count('"type": "skill_save_failed"') >= 3
    assert text.count('"type": "escalation_failed"') >= 2


def test_the_frontend_still_listens_for_all_three():
    text = _CHAT.read_text(encoding="utf-8")
    for event in ("skill_saved", "skill_save_failed", "escalation_failed"):
        assert f"'{event}'" in text, f"{event} lost its handler"


def test_something_finally_emits_the_success():
    loop = _LOOP.read_text(encoding="utf-8")
    assert loop.count('{"type": "skill_saved"') == 2, (
        "both completion paths must emit — a teacher skill goes through the "
        "approval card and an agent-written one does not"
    )


# ── what the tool reports ─────────────────────────────────────────────────────


def _add_result(monkeypatch, entry: dict, args: dict | None = None) -> dict:
    """Run the real `add` branch against a manager that returns `entry`.

    `do_manage_skills` imports `SkillsManager` **inside** the function and
    constructs it there, so the name has to be replaced on the module it comes
    from — `services.memory.skills` — not on `src.tools.system`, which never
    holds it. Patching an accessor that does not exist left the real manager in
    place and the first version of this test ran against a live skill
    directory, deduping against a real skill and passing for the wrong reason.
    """
    import services.memory.skills as skills_mod
    import src.tools.system as system

    class _FakeManager:
        def __init__(self, *_a, **_k):
            pass

        def add_skill(self, **_kwargs):
            return entry

    monkeypatch.setattr(skills_mod, "SkillsManager", _FakeManager)
    payload = {"action": "add", "name": entry.get("name", "x"),
               "procedure": ["do the thing"], **(args or {})}
    return asyncio.run(system.do_manage_skills(json.dumps(payload), owner="alice"))


@pytest.fixture(autouse=True)
def _no_writes_to_the_real_skill_library():
    """Fail loudly if the manager patch stops taking.

    The first version of this file patched an accessor that does not exist, so
    the **real** `SkillsManager` ran and wrote `data/skills/general/tidy-logs`
    into the working tree. That skill then changed tool selection for
    `test_fenced_example_not_executed_for_native_models.py`, which began failing
    two files away for reasons that had nothing to do with it — and the failure
    survived a `git stash`, because the damage was to a gitignored directory
    rather than to the code. Half an hour went into bisecting a phantom
    regression.

    `data/` is not the suite's to write to. This notices on the way out rather
    than three files later.
    """
    library = Path(_REPO / "data" / "skills")
    before = {p for p in library.rglob("*")} if library.exists() else set()
    yield
    after = {p for p in library.rglob("*")} if library.exists() else set()
    assert after == before, (
        "this test wrote to the real skill library: "
        f"{sorted(str(p.relative_to(_REPO)) for p in after - before)}"
    )


def test_a_saved_skill_reports_its_name_and_category(monkeypatch):
    out = _add_result(monkeypatch, {"name": "tidy-logs", "category": "ops",
                                    "status": "draft", "description": "d"})
    assert out["skill_saved"] == {"name": "tidy-logs", "category": "ops", "status": "draft"}


def test_a_deduped_skill_reports_nothing(monkeypatch):
    # Nothing was saved, so nothing may say "Skill learned".
    out = _add_result(monkeypatch, {"name": "tidy-logs", "_deduped": True})
    assert "skill_saved" not in out


def test_the_human_readable_result_is_unchanged(monkeypatch):
    # The model reads `results`. Adding a key beside it must not change what it
    # is told, or this becomes a prompt change wearing a UI fix's clothes.
    out = _add_result(monkeypatch, {"name": "tidy-logs", "category": "ops",
                                    "status": "published", "description": "d"})
    assert out["results"].startswith("Created skill `tidy-logs` — d")


# ── the shape on the wire ─────────────────────────────────────────────────────


def _emit_block(marker: str) -> str:
    text = _LOOP.read_text(encoding="utf-8")
    i = text.index(marker)
    return text[i:i + 400]


@pytest.mark.parametrize("marker", [
    'if isinstance(approved_result.get("skill_saved"), dict):',
    'if isinstance(result.get("skill_saved"), dict):',
])
def test_the_event_is_flat_because_that_is_what_the_handler_reads(marker):
    # `chat.js` reads `json.name` and `json.category`, not `json.data.name`.
    # Nesting it would emit an event the listener renders as an empty name.
    block = _emit_block(marker)
    assert '{"type": "skill_saved", **' in block


@pytest.mark.parametrize("marker", [
    'if isinstance(approved_result.get("skill_saved"), dict):',
    'if isinstance(result.get("skill_saved"), dict):',
])
def test_a_result_without_the_key_emits_nothing(marker):
    # Every other tool's result goes through this branch. `isinstance(..., dict)`
    # rather than a truthiness check, so a tool that happens to return a string
    # under that name cannot produce a malformed event.
    block = _emit_block(marker)
    assert "isinstance(" in block


def test_the_handler_renders_the_name_it_is_sent():
    text = _CHAT.read_text(encoding="utf-8")
    handler = text[text.index("json.type === 'skill_saved'"):]
    handler = handler[:handler.index("} else if")]
    assert "esc(json.name" in handler, "the name is interpolated unescaped"
    assert "esc(json.category" in handler
    assert "Skill learned" in handler
