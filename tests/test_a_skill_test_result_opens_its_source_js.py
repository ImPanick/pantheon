# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1975`. After a skill test, its comparison or its History, Edit had no source to open.

Test (the footer's, the ⋯ menu's, or the needs-your-yes pill), *Compare with
previous* and History each draw into the card's preview by replacing what was
there: the SKILL.md `<pre>` and the footer (Publish, Test, Edit, Delete) were
destroyed, not hidden. The test verdict's own Edit then asked to put the editor
before the footer, found the verdict's footer instead, a node inside the result
rather than beside it, and the browser refused, so nothing opened. The ⋯ Edit
of the folded card opened an editor under the ask panel, the comparison or
History, with no Save: none of their buttons says Edit, so none became Save,
and the card ignores clicks while an editor is open. Folding and opening the
card did not bring the source back; only a fresh draw of the list did.

Now the three views keep the source view's nodes, with their handlers, and
Edit puts them back before it opens the editor, so it opens where it always
does, above the footer, with Save. The editor also has a Cancel, which puts
the card back as it was without saving, and Test is hidden while editing,
since starting one would replace the editor. The footer Test is reset when its
run has started, since that button now comes back.

Ported from upstream Odysseus 3efbecd5 (#6931), which kept the nodes only in
the test view; Pantheon's comparison (`P8-09`) and History (`P22-23`) replace
the preview the same way. Driven under node through the real `skills.js` on
the shipped markup, in the harness `test_one_skills_module_two_places_js.py`
owns; the shim's nodes are given a browser's `nextSibling` and `parentElement`,
so where Cancel lands is asserted too.
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
DRAFT = SOURCE + "2. tell whoever printed\n"

# A browser's nodes have both of these and the shim's have neither. Cancel goes
# in before Edit's next sibling, and a verdict's "checked" chip goes in before
# the status pill through its parent element.
SIBLINGS = r"""
Object.defineProperty(Node.prototype, 'nextSibling', {
  configurable: true,
  get() {
    const kids = this.parentNode ? this.parentNode.childNodes : [];
    return kids[kids.indexOf(this) + 1] || null;
  },
});
Object.defineProperty(Node.prototype, 'parentElement', {
  configurable: true,
  get() { return this.parentNode && this.parentNode.tagName !== '#DOCUMENT' ? this.parentNode : null; },
});
"""

# A running test puts a spinner in the card's name; the shared stub's is not a
# node, and the shim cannot walk past it.
STUBS_HERE = dict(STUBS, **{"spinner.js": (
    "export function createWhirlpool(){ return { element: document.createElement('span'), destroy(){} }; }\n"
    "export default { createWhirlpool };\n")})

# `look(card)` is the preview as a person sees it: its direct children in order,
# the footer's buttons that are not hidden, and what the editor holds.
PREAMBLE = (
    "import { document, server, fire, tick, cards } from './shim.js';\n"
    "globalThis.addEventListener = globalThis.addEventListener || (() => {});\n"
    "globalThis.removeEventListener = globalThis.removeEventListener || (() => {});\n"
    "const reply = (b) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(b)) });\n"
    "const SOURCE = " + json.dumps(SOURCE) + ";\n"
    "const DRAFT = " + json.dumps(DRAFT) + ";\n"
    "const DONE = { status: 'done', task: 'clear it', log: [{ type: 'say', text: 'Cleared.' }],\n"
    "  verdict: { verdict: 'pass', confidence: 0.9, summary: 'It cleared the queue.', issues: [] } };\n"
    "const RUNNING = { status: 'running', log: [{ type: 'skill_test_start', task: 'clear it', model: 'm' }] };\n"
    "const statuses = [];   // answers for /test-status, in order; the last one repeats\n"
    "const routes = {\n"
    "  'GET /api/skills/beta-print/markdown': () => reply({ markdown: SOURCE }),\n"
    "  'GET /api/skills/beta-print/test-status': () => reply(statuses.length > 1 ? statuses.shift() : statuses[0]),\n"
    "  'GET /api/skills/beta-print/versions': () => reply({ versions: [\n"
    "    { id: 'v-1', version: '1.0.0', saved_at: 1760000000 }] }),\n"
    "};\n"
    "const base = globalThis.fetch;\n"
    "globalThis.fetch = async (url, init = {}) => {\n"
    "  const u = String(url).replace('http://test.local', '');\n"
    "  const method = init.method || 'GET';\n"
    "  const route = routes[method + ' ' + u];\n"
    "  if (!route) return base(url, init);\n"
    "  server.calls.push({ url: u, method, body: null });\n"
    "  return route();\n"
    "};\n"
    "await import('./skills.js');\n"
    "fire(document, 'DOMContentLoaded');\n"
    "await tick();\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const card = cards('skills-list').find((c) => c.dataset.skillName === 'beta-print');\n"
    "const preview = () => card.querySelector('.skill-card-preview');\n"
    "const footer = () => preview().children.find((k) => k.classList.contains('doclib-card-expanded-actions'));\n"
    "const press = async (label) => {\n"
    "  const b = card.querySelectorAll('.doclib-card-action-btn').find((x) => x.textContent.trim() === label);\n"
    "  if (b) fire(b, 'click');\n"
    "  await tick(20);\n"
    "  return !!b;\n"
    "};\n"
    "function menu(label) {\n"
    "  fire(card.querySelector('.skill-kebab-btn'), 'click');\n"
    "  const m = document.body.querySelectorAll('.skill-kebab-menu').slice(-1)[0];\n"
    "  fire(m.querySelectorAll('.skill-kebab-item').find((b) => b.textContent.trim() === label), 'click');\n"
    "}\n"
    "const KIND = [['skill-md-pre', 'source'], ['skill-md-editor', 'editor'], ['skill-card-lint', 'lint'],\n"
    "  ['doclib-card-expanded-actions', 'footer'], ['skill-test', 'test view']];\n"
    "function look() {\n"
    "  const kids = preview().children;\n"
    "  const ta = kids.find((k) => k.classList.contains('skill-md-editor'));\n"
    "  const pre = kids.find((k) => k.classList.contains('skill-md-pre'));\n"
    "  const foot = footer();\n"
    "  return {\n"
    "    order: kids.map((k) => (KIND.find(([c]) => k.classList.contains(c)) || [0, k.className])[1]),\n"
    "    buttons: foot ? foot.querySelectorAll('button').filter((b) => b.style.display !== 'none')\n"
    "      .map((b) => b.textContent.trim()) : [],\n"
    "    editor: ta ? ta.value : null,\n"
    "    sourceShown: pre ? pre.style.display !== 'none' : null,\n"
    "  };\n"
    "}\n"
    "const saved = () => server.calls.filter((c) => c.method === 'POST' && /\\/markdown$/.test(c.url))\n"
    "  .map((c) => c.body);\n"
)

EDITING = {"order": ["source", "editor", "lint", "footer"],
           "buttons": ["Publish", "Save", "Cancel", "Delete"],
           "editor": SOURCE, "sourceShown": False}
SOURCE_VIEW = {"order": ["source", "footer"], "buttons": ["Publish", "Test", "Edit", "Delete"],
               "editor": None, "sourceShown": True}


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    shim = SHIM.replace("__MARKUP__", json.dumps(_markup())) + SIBLINGS
    return _make_sandbox(tmp_path_factory.mktemp("testedit"), SKILLS_JS, shim, STUBS_HERE)


def test_the_verdicts_edit_opens_the_skill_md_above_the_footer_and_saves_it_once(box):
    o = _run(box, PREAMBLE, """
        statuses.push(DONE);
        fire(card, 'click');                    // open the card
        await tick();
        await press('Test');                    // the footer's Test: a finished run, with its verdict
        const verdict = preview().querySelector('.skill-test-verdict');
        const asked = !!(verdict && verdict.querySelector('.skill-eval-badge'));
        fire(verdict.querySelector('[data-act="edit"]'), 'click');
        await tick();
        const editing = look();
        preview().querySelector('.skill-md-editor').value = DRAFT;
        await press('Save');
        out({ asked, editing, saved: saved() });
    """)
    assert o["asked"] is True, "the test did not draw its verdict, so this asserts nothing"
    assert o["editing"] == EDITING, o["editing"]
    assert o["saved"] == [{"markdown": DRAFT}]


@pytest.mark.parametrize("view", ["the test's ask panel", "the comparison", "History"])
def test_the_menus_edit_puts_the_skill_md_back_after_the_view_and_offers_save(box, view):
    o = _run(box, PREAMBLE, """
        statuses.push({ status: 'none' });
        const VIEW = __VIEW__;
        if (VIEW === "the test's ask panel") {
          fire(card, 'click');
          await tick();
          await press('Test');
        } else {
          menu(VIEW === 'History' ? 'History' : 'Compare with previous');   // from the folded card
          await tick(20);
        }
        const drawn = look().order;
        fire(card, 'click');                    // fold it: the ⋯ menu is the folded card's
        await tick();
        menu('Edit');
        await tick(20);
        out({ drawn, editing: look() });
    """.replace("__VIEW__", json.dumps(view)))
    assert o["drawn"] == ["test view"], f"{view} was not drawn: {o['drawn']}"
    assert o["editing"] == EDITING, o["editing"]


def test_cancel_puts_the_card_back_without_saving_and_test_comes_back_ready(box):
    o = _run(box, PREAMBLE, """
        statuses.push(DONE);
        fire(card, 'click');
        await tick();
        await press('Edit');                    // straight from the source view
        preview().querySelector('.skill-md-editor').value = DRAFT;
        const cancelled = await press('Cancel');
        const plain = look();
        plain.lint = !!card.querySelector('.skill-card-lint');
        await press('Test');                    // and from a verdict
        fire(preview().querySelector('.skill-test-verdict').querySelector('[data-act="edit"]'), 'click');
        await tick();
        await press('Cancel');
        const afterTest = look();
        const foot = footer();
        const test = foot && foot.querySelectorAll('button').find((b) => b.textContent.trim() === 'Test');
        afterTest.test = test ? { disabled: test.disabled, busy: test.dataset.busy || '' } : null;
        out({ cancelled, plain, afterTest, saved: saved() });
    """)
    assert o["cancelled"] is True, "the editor has no Cancel"
    assert o["plain"] == dict(SOURCE_VIEW, lint=False), o["plain"]
    assert o["afterTest"] == dict(SOURCE_VIEW, test={"disabled": False, "busy": ""}), (
        f"the footer came back, but not as it was: {o['afterTest']}")
    assert o["saved"] == [], "Cancel saved"


def test_a_test_still_running_leaves_the_draft_alone(box):
    o = _run(box, PREAMBLE, """
        statuses.push(RUNNING, DONE);
        fire(card, 'click');
        await tick();
        await press('Test');                    // a run that has not finished: the card polls it
        const running = !!card._testPoll;
        fire(card, 'click');
        await tick();
        menu('Edit');
        await tick(20);
        const editing = look();
        preview().querySelector('.skill-md-editor').value = DRAFT;
        await new Promise((r) => setTimeout(r, 1600));   // past a poll tick (1300 ms)
        await tick(20);
        const later = look();
        out({ running, editing, later, polling: !!card._testPoll });
    """)
    assert o["running"] is True, "the run was not being polled, so this asserts nothing"
    assert o["editing"] == EDITING, o["editing"]
    assert o["later"] == dict(EDITING, editor=DRAFT), f"the poll touched the editor: {o['later']}"
    assert o["polling"] is False, "the poll did not stop when the run finished"


def test_edit_gives_back_a_skill_md_that_did_not_load_and_opening_the_card_again_asks_again(box):
    # The ⋯ Test of a folded card opens it first, and here its SKILL.md does not
    # come. The verdict's Edit cannot edit it (`B1974`), but it gives the card
    # back, saying so, and opening the card again asks for the text again.
    o = _run(box, PREAMBLE, """
        statuses.push(DONE);
        let asked = 0;
        routes['GET /api/skills/beta-print/markdown'] = () => {
          asked += 1;
          return asked > 1 ? reply({ markdown: SOURCE })
            : { ok: false, status: 500, json: async () => ({ detail: 'read failed' }) };
        };
        menu('Test');                           // from the folded card
        await tick(20);
        const verdict = preview().querySelector('.skill-test-verdict');
        const drawn = !!(verdict && verdict.querySelector('.skill-eval-badge'));
        fire(verdict.querySelector('[data-act="edit"]'), 'click');
        await tick();
        const back = look();
        const pre = preview().querySelector('.skill-md-pre');
        const edit = footer() && footer().querySelectorAll('button').find((b) => b.textContent.trim() === 'Edit');
        back.says = pre ? pre.textContent : null;
        back.editDisabled = edit ? edit.disabled : null;
        fire(card, 'click');                    // fold it
        fire(card, 'click');                    // and open it again
        await tick(20);
        await press('Edit');
        out({ drawn, back, asked, editing: look() });
    """)
    assert o["drawn"] is True, "the test did not draw its verdict, so this asserts nothing"
    assert o["back"] == dict(SOURCE_VIEW, says="Failed to load SKILL.md", editDisabled=True), o["back"]
    assert o["asked"] == 2, "opening the card again did not ask for the SKILL.md again"
    assert o["editing"] == EDITING, o["editing"]
