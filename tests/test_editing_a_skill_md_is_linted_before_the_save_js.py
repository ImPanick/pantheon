# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B613` — the SKILL.md editor on a card is told what the Add form is told.

`P8-12` put the lint on the Add-Skill form, where a skill is created; the card's
raw SKILL.md editor (`_toggleSkillEdit` / `_saveSkillEdit`), where an existing
skill is changed, POSTed the whole file to `/{name}/markdown` with no check at
all. The blocker was shape: `lint_skill` takes a skill dict and the editor holds
markdown. `POST /api/skills/lint` now takes `markdown` and reads it with the
parser the save uses, under the stored name the save pins; the editor asks it
when it opens and as the person types, and draws the answer with the Add form's
own renderer. Advice only: the save is never gated on it.

The server half calls the real route; the browser half drives the real
`skills.js` on the real markup (the `test_one_skills_module_two_places_js.py`
harness).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.datastructures import State

sys.path.insert(0, str(Path(__file__).resolve().parent))

from routes.skills_routes import SkillLintRequest, setup_skills_routes  # noqa: E402
from services.memory.skill_lint import lint_skill  # noqa: E402
from services.memory.skills import SkillsManager  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_one_skills_module_two_places_js import SHIM, STUBS, _markup  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILLS_JS = ROOT / "static" / "js" / "skills.js"

EDITED = textwrap.dedent("""\
    ---
    name: Somebody Else Entirely
    description: Rotate logs
    category: general
    ---

    ## When to Use
    the disk is full
    """)


def _request(user=None):
    scope = {"type": "http", "app": type("App", (), {"state": State()})(),
             "state": {"current_user": user}, "headers": []}
    return Request(scope=scope)


def _lint_route(sm):
    router = setup_skills_routes(sm)
    return next(r.endpoint for r in router.routes
                if r.path == "/api/skills/lint" and "POST" in r.methods)


@pytest.fixture()
def store(tmp_path):
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(name="rotate-logs", description="Rotate and prune application logs",
                 category="ops", tags=["logs"], when_to_use="the disk is full of logs",
                 procedure=["stop the writer", "rotate"], pitfalls=["open files"],
                 verification=["df"], source="user", status="published")
    return sm


def test_the_lint_reads_a_whole_skill_md_as_the_save_would(store):
    from services.memory.skill_format import Skill

    lint = _lint_route(store)
    got = asyncio.run(lint(_request(), SkillLintRequest(name="rotate-logs", markdown=EDITED)))
    codes = {f["code"] for f in got["findings"]}
    assert "missing-procedure" in codes          # the edit removed the steps
    assert "default-category" in codes
    # Under the stored name, as the save pins it — not the text's own name,
    # and not compared with itself.
    assert "name-not-a-slug" not in codes and "missing-name" not in codes
    assert "same-base-name" not in codes and "duplicate-of" not in codes
    # The same answer the Add form gets for the same skill as fields.
    as_fields = dict(Skill.from_markdown(EDITED).to_dict(), name="rotate-logs")
    assert got == lint_skill(as_fields, [])


def test_the_lint_writes_nothing(store):
    before = store.read_skill_md("rotate-logs")
    asyncio.run(_lint_route(store)(_request(), SkillLintRequest(name="rotate-logs", markdown=EDITED)))
    assert store.read_skill_md("rotate-logs") == before


# ── the editor ───────────────────────────────────────────────────────────────

pytestmark_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

PREAMBLE = (
    "import { document, server, fire, tick, $, cards } from './shim.js';\n"
    "import { calls } from './ui.js';\n"
    "globalThis.addEventListener = globalThis.addEventListener || (() => {});\n"
    "globalThis.removeEventListener = globalThis.removeEventListener || (() => {});\n"
    "const base = globalThis.fetch;\n"
    "globalThis.fetch = async (url, init = {}) => {\n"
    "  const u = String(url).replace('http://test.local', '');\n"
    "  const method = init.method || 'GET';\n"
    "  const body = init.body ? JSON.parse(init.body) : null;\n"
    "  const reply = (b) => { server.calls.push({ url: u, method, body });\n"
    "    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(b)) }; };\n"
    "  if (u === '/api/skills/lint') return reply({ verdict: 'problems', counts: { problem: 1, advisory: 0 },\n"
    "    findings: [{ code: 'missing-procedure', severity: 'problem', field: 'procedure',\n"
    "      message: 'No Procedure. There is nothing for the model to follow.', fix: 'Add the numbered steps.' }] });\n"
    "  if (/\\/markdown$/.test(u) && method === 'GET') return reply({ name: 'beta-print',\n"
    "    markdown: '---\\nname: beta-print\\ndescription: clear the print queue\\n---\\n' });\n"
    "  if (/\\/markdown$/.test(u) && method === 'POST') return reply({ ok: true });\n"
    "  return base(url, init);\n"
    "};\n"
    "const skills = await import('./skills.js');\n"
    "fire(document, 'DOMContentLoaded');\n"
    "await tick();\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const card = cards('skills-list').find((c) => c.dataset.skillName === 'beta-print');\n"
    "fire(card.querySelector('.skill-kebab-btn'), 'click');\n"
    "const menu = document.body.querySelectorAll('.skill-kebab-menu').slice(-1)[0];\n"
    "fire(menu.querySelectorAll('.skill-kebab-item').find((b) => b.textContent.trim() === 'Edit'), 'click');\n"
    "await tick(20);\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    shim = SHIM.replace("__MARKUP__", json.dumps(_markup()))
    return _make_sandbox(tmp_path_factory.mktemp("cardlint"), SKILLS_JS, shim, STUBS)


@pytestmark_node
def test_opening_the_editor_says_what_is_wrong_before_any_save(box):
    o = _run(box, PREAMBLE, """
        const panel = card.querySelector('.skill-card-lint');
        out({ editing: !!card.querySelector('.skill-md-editor'),
              text: panel ? panel.textContent : null,
              hidden: panel ? panel.classList.contains('hidden') : null,
              asked: server.calls.filter((c) => c.url === '/api/skills/lint').map((c) => c.body),
              saved: server.calls.filter((c) => c.method === 'POST' && /\\/markdown$/.test(c.url)).length });
    """)
    assert o["editing"] is True
    assert o["hidden"] is False
    assert "No Procedure" in o["text"] and "None of this stops you saving." in o["text"]
    assert o["asked"] and o["asked"][0]["name"] == "beta-print"
    assert o["asked"][0]["markdown"].startswith("---\nname: beta-print")
    assert o["saved"] == 0, "the lint saved something"


@pytestmark_node
def test_typing_asks_again_and_the_save_is_never_held_back(box):
    o = _run(box, PREAMBLE, """
        const ta = card.querySelector('.skill-md-editor');
        ta.value = '---\\nname: beta-print\\ndescription: changed\\n---\\n';
        fire(ta, 'input');
        await new Promise((r) => setTimeout(r, 500));
        await tick(10);
        const asked = server.calls.filter((c) => c.url === '/api/skills/lint').map((c) => c.body.markdown);
        const save = card.querySelectorAll('.doclib-card-action-btn').find((b) => /Save/.test(b.textContent));
        fire(save, 'click');
        await tick(20);
        out({ asked, saved: server.calls.filter((c) => c.method === 'POST' && /\\/markdown$/.test(c.url))
                                         .map((c) => c.body.markdown) });
    """)
    assert o["asked"][-1].endswith("description: changed\n---\n")
    assert o["saved"] == ["---\nname: beta-print\ndescription: changed\n---\n"]
