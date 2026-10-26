# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Skills window, driven, for four rows whose server half changed.

The real `static/js/skills.js` on the real Skills window and Workbench markup
(the harness of `test_one_skills_module_two_places_js.py`), with a fake server
answering in the shapes `routes/skills_routes.py` now returns:

  * `B886` — a skill the audit could not judge without a person's yes carries
    `audit_needs_approval`, and its card says so in a pill that IS the Test
    button; an ordinary `inconclusive` has no such pill.
  * `B581` — a skill saved from the Add form is a draft, and the model is shown
    no draft a person wrote (`B1361`); the toast says so and its **Publish**
    action publishes it, and the draft pill no longer promises a match.
  * `B1376` — the prompt preview says which turn its block assumed.
  * `B1421` — a shipped skill is a card, and when the person's copy replaces it
    the off-pill says how to get it back.
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
    "showToast: (m, o) => calls.toasts.push({ m: String(m), action: o && o.action, run: o && o.onAction }),"
    " showError: (m) => calls.errors.push(String(m)),"
    " styledConfirm: async () => true, styledPrompt: async () => 'Ops', copyToClipboard: () => {},",
    before="export const calls = { toasts: [], errors: [] };",
)

ASSUMES = "Shown as a turn that can open a skill gets it."

PREAMBLE = (
    "import { document, server, fire, tick, $, cards, names } from './shim.js';\n"
    "import { calls } from './ui.js';\n"
    "globalThis.addEventListener = globalThis.addEventListener || (() => {});\n"
    "globalThis.removeEventListener = globalThis.removeEventListener || (() => {});\n"
    "server.skills = [\n"
    "  { name: 'weekly-report', description: 'send the weekly report', status: 'published',\n"
    "    confidence: 0.9, version: '1.0.0', audit_verdict: 'inconclusive', audit_needs_approval: true },\n"
    "  { name: 'tidy-logs', description: 'tidy the build logs', status: 'published',\n"
    "    confidence: 0.9, version: '1.0.0', audit_verdict: 'inconclusive', audit_needs_approval: false },\n"
    "  { name: 'my-draft', description: 'half done', status: 'draft', source: 'user',\n"
    "    confidence: 0.8, version: '1.0.0' },\n"
    "  { name: 'teacher-fix', description: 'from the teacher', status: 'draft',\n"
    "    source: 'teacher-escalation', confidence: 0.9, version: '1.0.0' },\n"
    "  { name: 'workstation-shell', description: 'the shipped shell procedure', status: 'published',\n"
    "    confidence: 0.9, version: '1.0.0', bundled: true, editable: false, source: 'bundled',\n"
    "    library: 'pantheon', owner: null },\n"
    "];\n"
    "server.collections.off = { 'workstation-shell': ['replaced by your copy workstation-shell-fork'] };\n"
    "const base = globalThis.fetch;\n"
    "globalThis.fetch = async (url, init = {}) => {\n"
    "  const u = String(url).replace('http://test.local', '');\n"
    "  const method = init.method || 'GET';\n"
    "  const reply = (b) => { server.calls.push({ url: u, method, body: init.body ? JSON.parse(init.body) : null });\n"
    "    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(b)) }; };\n"
    "  if (/\\/test-status$/.test(u)) return reply({ status: 'none' });\n"
    "  if (/\\/markdown$/.test(u) && method === 'GET') return reply({ name: 'x', markdown: '---\\nname: x\\n---\\n' });\n"
    "  if (u === '/api/skills/index') return reply({ index: [{ name: 'tidy-logs', description: 'tidy',\n"
    "    category: 'ops', status: 'published' }], prompt: '\\n## Available skills\\n- `tidy-logs` — tidy',\n"
    "    prompt_chars: 40, withheld_fields: ['procedure'], can_fetch: true, assumes: '" + ASSUMES + "' });\n"
    "  return base(url, init);\n"
    "};\n"
    "const skills = await import('./skills.js');\n"
    "fire(document, 'DOMContentLoaded');\n"
    "await tick();\n"
    "const card = (name) => cards('skills-list').find((c) => c.dataset.skillName === name);\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    shim = SHIM.replace("__MARKUP__", json.dumps(_markup()))
    return _make_sandbox(tmp_path_factory.mktemp("skillstruth"), SKILLS_JS, shim, _STUBS)


# ── B886 ─────────────────────────────────────────────────────────────────────

def test_a_skill_that_stopped_for_a_yes_is_told_apart_and_the_pill_runs_its_test(box):
    o = _run(box, PREAMBLE, """
        const asked = card('weekly-report').querySelector('.skill-needs-approval-pill');
        const plain = card('tidy-logs').querySelector('.skill-needs-approval-pill');
        const label = asked ? asked.textContent : null;
        const title = asked ? asked.title : null;
        server.calls.length = 0;
        fire(asked, 'click');
        await tick(20);
        out({ label, title, plain: !!plain,
              statusAsked: server.calls.some((c) => c.url === '/api/skills/weekly-report/test-status'),
              runOffered: !!card('weekly-report').querySelector('.skill-test-run') });
    """)
    assert o["label"] == "needs your yes"
    assert "Press" in o["title"] and "allow or deny" in o["title"]
    assert o["plain"] is False, "an ordinary inconclusive grew the pill"
    assert o["statusAsked"] and o["runOffered"], "the pill did not open the skill's Test"


# ── B581 ─────────────────────────────────────────────────────────────────────

def test_a_skill_written_in_the_form_says_it_is_a_draft_and_publishes_from_the_toast(box):
    o = _run(box, PREAMBLE, """
        $('new-skill-name').value = 'clear-print-queue';
        $('new-skill-description').value = 'clear a jammed print queue';
        fire($('add-skill-btn'), 'click');
        await tick(20);
        const toast = calls.toasts.slice(-1)[0] || {};
        server.calls.length = 0;
        if (toast.run) await toast.run();
        await tick(10);
        out({ toast: toast.m, action: toast.action,
              put: server.calls.filter((c) => c.method === 'PUT').map((c) => [c.url, c.body]),
              mine: card('my-draft').querySelector('.skill-status-pill').title,
              teacher: card('teacher-fix').querySelector('.skill-status-pill').title });
    """)
    assert "draft" in o["toast"] and "not shown it until you publish it" in o["toast"]
    assert o["action"] == "Publish"
    assert o["put"] == [["/api/skills/clear-print-queue", {"status": "published"}]]
    assert "not shown" in o["mine"] and "when a message matches" not in o["mine"]
    assert "when a message matches" in o["teacher"]


# ── B1376 ────────────────────────────────────────────────────────────────────

def test_the_preview_says_which_turn_it_assumed(box):
    o = _run(box, PREAMBLE, """
        fire($('skills-preview-btn'), 'click');
        await tick(20);
        const note = $('skills-prompt-panel').querySelector('.skill-prompt-assumes');
        out({ note: note ? note.textContent : null });
    """)
    assert o["note"] == ASSUMES


# ── B1421 ────────────────────────────────────────────────────────────────────

def test_a_shipped_skill_has_a_card_and_says_its_copy_replaced_it(box):
    o = _run(box, PREAMBLE, """
        const c = card('workstation-shell');
        const off = c && c.querySelector('.skill-off-pill');
        out({ card: !!c, off: off ? off.title : null });
    """)
    assert o["card"] is True
    assert "workstation-shell-fork" in o["off"] and "Delete the copy" in o["off"]
