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
import shutil
import subprocess
import textwrap
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


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_handler_renders_the_name_it_is_sent(tmp_path):
    # `B915`. This read the handler's source for `esc(json.name` (`Law 20`: a
    # test of the file). The note is drawn now by `renderAgentNote`
    # (`static/js/agentStops.js`), the builder a reload and a resumed stream
    # use too, and it is text by construction — so the live arm is cut out of
    # `handleChatSubmit` and run against the real builder, with a name and a
    # category that would be markup if they were ever assigned as such.
    from tests.helpers.js_source import js_definition, js_function
    from tests.helpers.source_text import blank_text
    from test_tool_effect_surfaces_js import _DOM

    chat = _CHAT.read_text(encoding="utf-8")
    handler = js_definition(chat, blank_text(chat, "js").index("export async function handleChatSubmit("))
    arm = js_function(handler, "} else if (json.type === 'skill_saved') {")
    (tmp_path / "dom.js").write_text(_DOM, encoding="utf-8")
    shutil.copy(_REPO / "static" / "js" / "agentStops.js", tmp_path / "agentStops.js")
    (tmp_path / "case.mjs").write_text(textwrap.dedent("""
        import { installDom, Node } from './dom.js';
        import { renderAgentNote } from './agentStops.js';
        const document = installDom();
        const box = document.body.appendChild(new Node('div'));
        box.setAttribute('id', 'chat-history');
        const uiModule = { scrollHistory() {} };
        const json = { type: 'skill_saved', name: '<img src=x onerror=alert(1)>tidy-logs',
                       category: '<b>ops</b>', status: 'draft' };
        for (const _isBg of [false]) %s
        const note = box.children[0];
        console.log(JSON.stringify({
          cls: note.className,
          text: note.textContent,
          markup: note._walk([]).filter((n) => n._html).map((n) => n._html),
          elements: note._walk([]).filter((n) => n.tagName !== '#TEXT').map((n) => n.tagName),
        }));
    """) % arm, encoding="utf-8")
    proc = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["cls"] == "skill-saved-note"
    assert out["text"] == "Skill learned: <img src=x onerror=alert(1)>tidy-logs [<b>ops</b>]"
    assert out["markup"] == [], "a part of the note was assigned as markup"
    assert out["elements"] == ["STRONG", "CODE", "SPAN"], out["elements"]
