# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1974`. Edit opened on "Loading…", and Save wrote it over the skill.

A skill card fetches its SKILL.md when it is first opened, and shows
"Loading…" in its place until the answer comes, or "Failed to load SKILL.md"
if it does not. Edit never waited. The footer Edit was never disabled, the ⋯
menu's Edit opened the card and then the editor even when the fetch had
failed, and the editor took whatever the card was showing as its text. Save is
the only way out of that editor, and `POST /{name}/markdown` refuses only a
blank text, so "Loading…" was saved as the skill: its description and steps
gone, unpublished, moved to `general/`. `P8-10` kept the old copy in History,
but nothing said that had happened. The built-in capability editor did the
same with its own "Loading…" and "Failed to load.", for an operator.

Now Edit is disabled while the text is on its way and stays disabled if it
never comes, and both editors refuse to open on a card whose text has not
loaded, whichever button asked. Opening the card again asks for the text
again. An empty SKILL.md has loaded, and opens.

Ported from upstream Odysseus eea39ce1 (#6934), which guarded the skill editor
only. Driven under node through the real `skills.js` on the shipped markup, in
the harness `test_one_skills_module_two_places_js.py` owns, with a server whose
answer the case holds back.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_one_skills_module_two_places_js import SHIM, STUBS, _markup  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILLS_JS = ROOT / "static" / "js" / "skills.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

SOURCE = "---\nname: beta-print\ndescription: clear the print queue\n---\n\n## Procedure\n1. cancel every job\n"

# `routes['GET /path']` answers a request the shim's own server does not, and
# may hold its answer back: `held()` is a promise the case opens. `press` and
# `disabled` find a card's footer button by its label, and say `null` when no
# button has that label any more (an Edit already turned into Save).
PREAMBLE = (
    "import { document, server, fire, tick, cards } from './shim.js';\n"
    "globalThis.addEventListener = globalThis.addEventListener || (() => {});\n"
    "globalThis.removeEventListener = globalThis.removeEventListener || (() => {});\n"
    "const routes = {};\n"
    "const reply = (b) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(b)) });\n"
    "const refuse = () => ({ ok: false, status: 500, json: async () => ({ detail: 'read failed' }) });\n"
    "const held = () => { let open; const p = new Promise((r) => { open = r; }); return { p, open }; };\n"
    "const base = globalThis.fetch;\n"
    "globalThis.fetch = async (url, init = {}) => {\n"
    "  const u = String(url).replace('http://test.local', '');\n"
    "  const method = init.method || 'GET';\n"
    "  const route = routes[method + ' ' + u];\n"
    "  if (!route) return base(url, init);\n"
    "  server.calls.push({ url: u, method, body: init.body ? JSON.parse(init.body) : null });\n"
    "  return route();\n"
    "};\n"
    "routes['GET /api/skills/builtin'] = async () => reply({ count: 2, builtin: [\n"
    "  { name: 'read_file', description: 'Read a file', is_overridden: false },\n"
    "  { name: 'web_search', description: 'Search the web', is_overridden: false }] });\n"
    "await import('./skills.js');\n"
    "fire(document, 'DOMContentLoaded');\n"
    "await tick();\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const card = cards('skills-list').find((c) => c.dataset.skillName === 'beta-print');\n"
    "const button = (c, label) => c.querySelectorAll('.doclib-card-action-btn')\n"
    "  .find((b) => b.textContent.trim() === label);\n"
    "const disabled = (c, label) => { const b = button(c, label); return b ? b.disabled : null; };\n"
    "const press = async (c, label) => { const b = button(c, label); if (b) fire(b, 'click'); await tick(); };\n"
    "function menuEdit(c) {\n"
    "  fire(c.querySelector('.skill-kebab-btn'), 'click');\n"
    "  const menu = document.body.querySelectorAll('.skill-kebab-menu').slice(-1)[0];\n"
    "  fire(menu.querySelectorAll('.skill-kebab-item').find((b) => b.textContent.trim() === 'Edit'), 'click');\n"
    "}\n"
    "const shown = (c) => c.querySelector('.skill-md-pre').textContent;\n"
    "const editor = (c) => { const ta = c.querySelector('.skill-md-editor'); return ta ? ta.value : null; };\n"
    "const sent = (method, pattern) => server.calls.filter((c) => c.method === method && pattern.test(c.url))\n"
    "  .map((c) => c.body);\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    shim = SHIM.replace("__MARKUP__", json.dumps(_markup()))
    return _make_sandbox(tmp_path_factory.mktemp("editorwaits"), SKILLS_JS, shim, STUBS)


@pytest.mark.parametrize("source", [SOURCE, ""], ids=["a-skill", "an-empty-skill-md"])
def test_while_the_skill_md_is_on_its_way_no_edit_opens_and_nothing_is_saved(box, source):
    o = _run(box, PREAMBLE, """
        const SOURCE = __SOURCE__;
        const gate = held();
        routes['GET /api/skills/beta-print/markdown'] = async () => { await gate.p; return reply({ markdown: SOURCE }); };
        fire(card, 'click');                  // open the card: the fetch starts, and is held
        await tick();
        const loading = { shown: shown(card), disabled: disabled(card, 'Edit') };
        await press(card, 'Edit');            // the footer's Edit, pressed anyway
        menuEdit(card);                       // and the menu's
        await tick();
        await press(card, 'Save');            // and Save, if either made one
        const meanwhile = { editor: editor(card), saved: sent('POST', /\\/markdown$/) };
        gate.open();
        await tick();
        const loaded = { disabled: disabled(card, 'Edit') };
        await press(card, 'Edit');
        loaded.editor = editor(card);
        await press(card, 'Save');
        await tick(20);
        out({ loading, meanwhile, loaded, saved: sent('POST', /\\/markdown$/) });
    """.replace("__SOURCE__", json.dumps(source)))
    assert o["loading"] == {"shown": "Loading…", "disabled": True}, (
        f"Edit was offered before the text came: {o['loading']}")
    assert o["meanwhile"] == {"editor": None, "saved": []}, (
        f"an editor opened on the placeholder, or it was saved: {o['meanwhile']}")
    assert o["loaded"] == {"disabled": False, "editor": source}, o["loaded"]
    assert o["saved"] == [{"markdown": source}], "the save after loading sent something else"


def test_a_skill_md_that_did_not_load_is_not_edited_and_opening_the_card_again_asks_again(box):
    o = _run(box, PREAMBLE, """
        let asked = 0;
        routes['GET /api/skills/beta-print/markdown'] = async () => {
          asked += 1;
          return asked === 1 ? refuse() : reply({ markdown: __SOURCE__ });
        };
        menuEdit(card);                       // a folded card: open it, then edit
        await tick(20);
        const failed = { shown: shown(card), disabled: disabled(card, 'Edit'), editor: editor(card) };
        await press(card, 'Edit');
        await press(card, 'Save');
        failed.afterEdit = editor(card);
        failed.saved = sent('POST', /\\/markdown$/);
        fire(card, 'click');                  // fold it
        fire(card, 'click');                  // and open it again
        await tick(20);
        const again = { asked, disabled: disabled(card, 'Edit') };
        await press(card, 'Edit');
        again.editor = editor(card);
        out({ failed, again });
    """.replace("__SOURCE__", json.dumps(SOURCE)))
    assert o["failed"] == {"shown": "Failed to load SKILL.md", "disabled": True, "editor": None,
                           "afterEdit": None, "saved": []}, o["failed"]
    assert o["again"] == {"asked": 2, "disabled": False, "editor": SOURCE}, o["again"]


def test_a_built_in_capability_waits_for_its_text_and_is_not_edited_without_it(box):
    # Before the fix this editor opened while loading and Save sent a PUT. In a
    # browser it sent "Loading…"; here it sends "", because the shim keeps a
    # node's own text in `_text`, the name the card stores the capability under.
    o = _run(box, PREAMBLE, """
        const gate = held();
        routes['GET /api/skills/builtin/read_file'] = async () => {
          await gate.p;
          return reply({ name: 'read_file', text: 'Read files with care.', default: 'Read files with care.' });
        };
        routes['GET /api/skills/builtin/web_search'] = async () => refuse();
        const [slow, broken] = ['read_file', 'web_search'].map((n) =>
          document.body.querySelectorAll('.skill-builtin-card').find((c) => c.dataset.builtinName === n));
        fire(slow, 'click');
        await tick();
        const loading = { shown: shown(slow), disabled: disabled(slow, 'Edit') };
        await press(slow, 'Edit');
        await press(slow, 'Save');
        loading.editor = editor(slow);
        loading.put = sent('PUT', /\\/builtin\\//);
        gate.open();
        await tick();
        const loaded = { disabled: disabled(slow, 'Edit') };
        await press(slow, 'Edit');
        loaded.editor = editor(slow);
        fire(broken, 'click');
        await tick(20);
        const failed = { shown: shown(broken), disabled: disabled(broken, 'Edit') };
        await press(broken, 'Edit');
        await press(broken, 'Save');
        failed.editor = editor(broken);
        failed.put = sent('PUT', /\\/builtin\\//);
        out({ loading, loaded, failed });
    """)
    assert o["loading"] == {"shown": "Loading…", "disabled": True, "editor": None, "put": []}, o["loading"]
    assert o["loaded"] == {"disabled": False, "editor": "Read files with care."}, o["loaded"]
    assert o["failed"] == {"shown": "Failed to load.", "disabled": True, "editor": None, "put": []}, o["failed"]
