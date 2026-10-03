# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-23` — the skill actions only a terminal could reach, pressed in the browser.

Draft from a description, *Fix these with the model*, *History* with *View* and
*Put this back*, and *Download*: each was a `manage_skills` action and nothing
else. Driven here with the real `skills.js` on the real Skills window and
Workbench markup (the harness of `test_one_skills_module_two_places_js.py`:
`installHtmlParsing`, the window and the room both mounted), with the fake
server answering the five new routes in the shapes `routes/skills_routes.py`
returns — `tests/test_the_skill_actions_have_buttons.py` drives those routes for
real.

Proven:
  * a sentence goes to `POST /api/skills/draft`, the reply fills the Add form
    — in the place it was typed, not the other — and nothing is saved; a draft
    carrying markup lands as text in the fields;
  * *Fix these with the model* appears once a skill with findings is saved
    (never before), posts `/improve`, and says the counts before and after;
  * *History* lists the earlier copies, *View* shows one as text, *Put this
    back* says what it replaces before it posts `/restore`, and nothing is
    posted when the person says no;
  * *Download* fetches `/export` and saves `<name>.json` through a link.
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
from tests.helpers.esc_stub import ui_default_stub  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILLS_JS = ROOT / "static" / "js" / "skills.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_STUBS = dict(STUBS)
_STUBS["ui.js"] = ui_default_stub(
    "showToast: (m) => calls.toasts.push(String(m)), showError: (m) => calls.errors.push(String(m)),"
    " styledConfirm: async (m) => { calls.confirms.push(String(m)); return calls.answer; },"
    " copyToClipboard: () => {},",
    before="export const calls = { toasts: [], errors: [], confirms: [], answer: true };",
)

HOSTILE = "<img src=x onerror=alert(1)>"

PREAMBLE = (
    "import { document, server, fire, tick, $, cards, names } from './shim.js';\n"
    "import { calls } from './ui.js';\n"
    "globalThis.addEventListener = globalThis.addEventListener || (() => {});\n"
    "globalThis.removeEventListener = globalThis.removeEventListener || (() => {});\n"
    "const base = globalThis.fetch;\n"
    "server.lint = { findings: [], counts: { problem: 0, advisory: 0 } };\n"
    "server.draftReply = { status: 200, body: { ok: true, model: 'scripted', draft: {\n"
    "  name: 'clear-print-queue', description: 'Clear a jammed queue " + HOSTILE + "', category: 'ops',\n"
    "  when_to_use: 'When the print queue jams', procedure: ['Stop the spooler', 'Delete the jobs'],\n"
    "  pitfalls: ['Jobs in flight are lost'], verification: ['A test page prints'], tags: ['printing'] } } };\n"
    "globalThis.fetch = async (url, init = {}) => {\n"
    "  const u = String(url).replace('http://test.local', '');\n"
    "  const method = init.method || 'GET';\n"
    "  const reply = (status, b) => { server.calls.push({ url: u, method, body: init.body ? JSON.parse(init.body) : null });\n"
    "    return { ok: status < 400, status, json: async () => JSON.parse(JSON.stringify(b)),\n"
    "             blob: async () => ({ bytes: JSON.stringify(b) }) }; };\n"
    "  if (u === '/api/skills/draft') return reply(server.draftReply.status, server.draftReply.body);\n"
    "  if (u === '/api/skills/lint') return reply(200, server.lint);\n"
    "  if (/\\/improve$/.test(u)) return reply(200, { ok: true, outcome: 'rewrote', findings: 3,\n"
    "    before: { problem: 2, advisory: 1 }, after: { problem: 0, advisory: 1 } });\n"
    "  if (/\\/versions$/.test(u)) return reply(200, { ok: true, versions: [\n"
    "    { id: '0002-1.0.1', version: '1.0.1', saved_at: 1759300000, bytes: 300 },\n"
    "    { id: '0001-1.0.0', version: '1.0.0', saved_at: 1759200000, bytes: 280 }] });\n"
    "  if (/\\/versions\\/[^/]+$/.test(u)) return reply(200, { ok: true, markdown: '---\\nname: beta-print\\n---\\n<script>alert(1)</script>' });\n"
    "  if (/\\/restore$/.test(u)) return reply(200, { ok: true, restored: '0001-1.0.0' });\n"
    "  if (/\\/export$/.test(u)) return reply(200, { skill: 'beta-print', files: { 'SKILL.md': 'x' } });\n"
    "  if (/\\/markdown$/.test(u)) return reply(200, { name: 'beta-print', markdown: '---\\nname: beta-print\\n---\\n' });\n"
    "  return base(url, init);\n"
    "};\n"
    "const skills = await import('./skills.js');\n"
    "fire(document, 'DOMContentLoaded');\n"
    "await tick();\n"
    "skills.mountSkills($('skills-room'));\n"
    "await tick();\n"
    "const posts = (re) => server.calls.filter((c) => c.method === 'POST' && re.test(c.url));\n"
    "const kebab = (listId, name) => { const card = cards(listId).find((c) => c.dataset.skillName === name);\n"
    "  fire(card.querySelector('.skill-kebab-btn'), 'click');\n"
    "  const menu = document.body.querySelectorAll('.skill-kebab-menu').slice(-1)[0];\n"
    "  return { card, menu, items: menu.querySelectorAll('.skill-kebab-item') }; };\n"
    "const pick = (m, label) => fire(m.items.find((b) => b.textContent.trim() === label), 'click');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    shim = SHIM.replace("__MARKUP__", json.dumps(_markup()))
    return _make_sandbox(tmp_path_factory.mktemp("skillactions"), SKILLS_JS, shim, _STUBS)


def test_a_sentence_fills_the_form_where_it_was_typed_and_saves_nothing(box):
    o = _run(box, PREAMBLE, """
        $('wb-skill-draft-text').value = 'when the print queue jams I clear it and restart the spooler';
        fire($('wb-skill-draft-btn'), 'click');
        await tick(20);
        const v = (id) => $(id).value;
        out({ sent: posts(/\\/api\\/skills\\/draft$/).map((c) => c.body),
              room: { name: v('wb-new-skill-name'), description: v('wb-new-skill-description'),
                      when: v('wb-new-skill-when'), procedure: v('wb-new-skill-procedure'),
                      category: v('wb-new-skill-category'), tags: v('wb-new-skill-tags'),
                      pitfalls: v('wb-new-skill-pitfalls'), verification: v('wb-new-skill-verification') },
              window: v('new-skill-name'),
              more: $('skills-room').querySelector('details.skill-more').open,
              note: $('wb-skill-draft-status').textContent, noteHidden: $('wb-skill-draft-status').hidden,
              added: posts(/\\/api\\/skills\\/add$/).length,
              markup: $('wb-new-skill-description').childNodes.length });
    """)
    assert o["sent"] == [{"description": "when the print queue jams I clear it and restart the spooler"}]
    assert o["room"] == {
        "name": "clear-print-queue", "description": "Clear a jammed queue " + HOSTILE,
        "when": "When the print queue jams", "procedure": "Stop the spooler\nDelete the jobs",
        "category": "ops", "tags": "printing", "pitfalls": "Jobs in flight are lost",
        "verification": "A test page prints",
    }
    assert o["window"] == "", "the draft filled the other place's form"
    assert o["more"] is True
    assert o["noteHidden"] is False and "nothing is saved until you press Add Skill" in o["note"]
    assert "scripted" in o["note"]
    assert o["added"] == 0, "drafting saved a skill"
    assert o["markup"] == 0


def test_a_draft_that_cannot_be_made_says_why_beside_the_box(box):
    o = _run(box, PREAMBLE, """
        fire($('skill-draft-btn'), 'click');
        await tick();
        const empty = { note: $('skill-draft-status').textContent, posts: posts(/draft$/).length };
        server.draftReply = { status: 503, body: { detail: 'No model is set up to draft a skill. Write it by hand below.' } };
        $('skill-draft-text').value = 'clear the print queue';
        fire($('skill-draft-btn'), 'click');
        await tick(20);
        out({ empty, refused: $('skill-draft-status').textContent, name: $('new-skill-name').value,
              enabled: !$('skill-draft-btn').disabled });
    """)
    assert o["empty"] == {"note": "Say what the skill is for first — one sentence is enough.", "posts": 0}
    assert o["refused"] == "No model is set up to draft a skill. Write it by hand below."
    assert o["name"] == "" and o["enabled"] is True


def test_fix_these_with_the_model_appears_once_saved_and_says_the_counts(box):
    o = _run(box, PREAMBLE, """
        server.lint = { findings: [
            { field: 'verification', severity: 'problem', message: 'No way to tell it worked.', fix: 'Add a check.' },
            { field: 'pitfalls', severity: 'problem', message: 'No pitfalls.', fix: 'Add one.' },
            { field: 'tags', severity: 'advisory', message: 'No tags.', fix: 'Add two.' }],
          counts: { problem: 2, advisory: 1 } };
        $('new-skill-name').value = 'gamma-spooler';
        $('new-skill-description').value = 'restart the spooler';
        fire($('new-skill-description'), 'blur');
        await tick(10);
        const beforeSave = $('skill-lint-panel').querySelectorAll('.skill-lint-fix-btn').length;
        fire($('add-skill-btn'), 'click');
        await tick(30);
        const btn = $('skill-lint-panel').querySelectorAll('.skill-lint-fix-btn')[0];
        const label = btn && btn.textContent;
        const head = $('skill-lint-panel').querySelectorAll('.skill-lint-head')[0].textContent;
        fire(btn, 'click');
        await tick(30);
        out({ beforeSave, label, head, improve: posts(/\\/improve$/).map((c) => c.url),
              said: $('skill-lint-panel').textContent });
    """)
    assert o["beforeSave"] == 0, "the button was offered before there was a skill to rewrite"
    assert o["label"] == "Fix these with the model"
    assert "fix them with the model below" in o["head"], "the line sent the person to the card instead"
    assert o["improve"] == ["/api/skills/gamma-spooler/improve"]
    # `P23-02` (`D-31`): the counts before → after, in one line.
    assert "Fixed gamma-spooler: problems 2 → 0, suggestions 1 → 1." in o["said"]
    assert "History" in o["said"]


def test_history_lists_views_as_text_and_puts_back_only_after_saying_what_it_replaces(box):
    o = _run(box, PREAMBLE, """
        const m = kebab('skills-list', 'beta-print');
        const labels = m.items.map((b) => b.textContent.trim());
        pick(m, 'History');
        await tick(20);
        const card = cards('skills-list').find((c) => c.dataset.skillName === 'beta-print');
        const rows = card.querySelectorAll('.skill-history-row');
        const rowText = rows.map((r) => r.querySelector('.skill-history-when').textContent);
        fire(rows[1].querySelectorAll('button')[0], 'click');            // View
        await tick(10);
        const pre = card.querySelector('.skill-history-text');
        const viewed = { text: pre.textContent, nodes: pre.childNodes.length, hidden: pre.hidden };
        calls.answer = false;
        fire(rows[1].querySelectorAll('button')[1], 'click');            // Put this back — No
        await tick(10);
        const declined = posts(/\\/restore$/).length;
        calls.answer = true;
        fire(rows[1].querySelectorAll('button')[1], 'click');            // Put this back — Yes
        await tick(20);
        out({ labels, rowText, viewed, declined, confirm: calls.confirms[0],
              restored: posts(/\\/restore$/).map((c) => c.url),
              versions: server.calls.filter((c) => /\\/versions\\/[^/]+$/.test(c.url)).map((c) => c.url),
              toast: calls.toasts.slice(-1)[0] });
    """)
    assert "History" in o["labels"] and "Download" in o["labels"]
    assert len(o["rowText"]) == 2 and o["rowText"][1].endswith("— was version 1.0.0")
    assert o["versions"] == ["/api/skills/beta-print/versions/0001-1.0.0"]
    assert o["viewed"]["text"].endswith("<script>alert(1)</script>") and o["viewed"]["nodes"] == 0
    assert o["viewed"]["hidden"] is False
    assert o["declined"] == 0, "No still put the copy back"
    # `P23-02` (`D-30`): which copy, which it replaces, and that it is kept — in one line.
    assert o["confirm"].startswith("Put back 1.0.0 (") and "The current copy (1.0.0) stays in History." in o["confirm"]
    assert o["restored"] == ["/api/skills/beta-print/versions/0001-1.0.0/restore"]
    assert o["toast"] == "Restored 1.0.0. The old copy is in History."


def test_download_saves_the_skill_as_a_file(box):
    o = _run(box, PREAMBLE, """
        const made = [];
        globalThis.URL = { createObjectURL: (b) => { made.push(b); return 'blob:skill'; }, revokeObjectURL: () => {} };
        const before = document.body.querySelectorAll('a').length;
        const m = kebab('wb-skills-list', 'alpha-logs');
        let clicked = null;
        const realCreate = document.createElement;
        document.createElement = (tag) => { const n = realCreate(tag);
          if (String(tag).toLowerCase() === 'a') n.click = () => { clicked = { href: n.href, download: n.download }; };
          return n; };
        pick(m, 'Download');
        await tick(20);
        out({ fetched: server.calls.filter((c) => /\\/export$/.test(c.url)).map((c) => c.url), clicked,
              blobs: made.length, left: document.body.querySelectorAll('a').length - before });
    """)
    assert o["fetched"] == ["/api/skills/alpha-logs/export"]
    assert o["clicked"] == {"href": "blob:skill", "download": "alpha-logs.json"}
    assert o["blobs"] == 1 and o["left"] == 0
