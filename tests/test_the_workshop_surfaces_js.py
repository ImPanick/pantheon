# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-02` / `P8-04` / `P8-05` / `P8-06` / `P8-07` / `P8-08` / `P8-12` — the Workshop's surface.

Driven under node against the real modules, in the sandbox pattern
`tests/test_chat_steer_js.py` established and `tests/test_tool_effect_surfaces_js.py`
owns. The shim, the sandbox builder and the runner are imported from that file
rather than copied — one harness, one place it can be fixed (`Law 14`).

The element ids come out of the shipped `static/index.html` rather than being
retyped here, so a rename in the markup fails these rather than passing against
a private copy of the page.

**What is driven and what is not, stated rather than glossed.** The shim stores
`innerHTML` as a string and does not parse it, which is deliberate — several
tests assert on the raw string, and `test_agent_drafts_js.py` goes further and
omits the property entirely so that assigning it throws. Three of the four
surfaces here are built with `createElement`, so they are exercised end to end
by clicking the real control. The fourth — the skill-test panel — is a template
string inside a card that `renderSkillsList` also builds as markup, so the click
path cannot be driven at all under this shim. `P8-08` is therefore asserted the
next way down `Law 20`'s list: **the scope is resolved first and the assertion
made inside it**, paired with a test that drives the *server's* half for real,
because the half that was missing all along was the request body.
"""

import json
import re
import shutil
import textwrap
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.datastructures import State

from services.memory.skills import SkillsManager

from test_a_draft_skill_is_uncatalogued_not_inactive import js_function  # noqa: E402
from test_tool_effect_surfaces_js import _DOM, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILLS_JS = ROOT / "static" / "js" / "skills.js"
MEMORY_JS = ROOT / "static" / "js" / "memory.js"
INDEX = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _index_ids() -> list:
    """Every id the shipped page declares. Cheap, and it means a control this
    surface reaches through a helper is present without anyone listing it."""
    ids = re.findall(r'\bid="([^"]+)"', INDEX.read_text(encoding="utf-8"))
    assert "skills-list" in ids and "add-skill-btn" in ids, "the Skills markup moved"
    return sorted(set(ids))


# ── stubs ───────────────────────────────────────────────────────────────────

_STUBS = {
    "ui.js": """
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');
export const calls = { toasts: [], errors: [] };
export default {
  esc,
  showToast: (m) => { calls.toasts.push(String(m)); },
  showError: (m) => { calls.errors.push(String(m)); },
  styledConfirm: async () => true,
  copyToClipboard: () => {},
  el: (id) => document.getElementById(id),
  debounce: (f) => f,
};
""",
    "spinner.js": """
export function createLoadingRow(){ return {}; }
export function createWhirlpool(){ return { element: { style: {} }, destroy(){} }; }
export default { createWhirlpool: () => ({ element: { style: {} }, destroy(){} }) };
""",
    "escMenuStack.js": "export function bindMenuDismiss(){ return () => {}; }\nexport function dismissOrRemove(){}\n",
    "toolWindowZOrder.js": "export function topPortalZ(){ return 1; }\n",
    "sessions.js": "export default { getCurrentModel: () => 'm', getCurrentEndpointUrl: () => 'u' };\n",
    "windowDrag.js": "export function makeWindowDraggable(){}\n",
    "tileManager.js": "export function snapModalToZone(){}\n",
}

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

const IDS = __IDS__;
for (const id of IDS) {
  const n = document.body.appendChild(new Node('div'));
  n.setAttribute('id', id);
}

/** The page ships these two panels hidden; the shim has to say so too or the
 *  preview's open/close toggle reads as already-open on the first click. */
for (const id of ['skills-prompt-panel', 'skills-audit-panel']) {
  const n = document.getElementById(id);
  if (n) n.className = 'skills-audit-panel hidden';
}

/** The confidence slider is an <input type=range>: the shim's generic node has
 *  no min/max/step, and `syncPrefSlider` reads all three off the element. Copy
 *  them from the shipped markup so the geometry under test is the geometry the
 *  page ships. */
export function configureSlider(attrs) {
  const s = document.getElementById('skill-confidence-slider');
  Object.assign(s, attrs);
  return s;
}

export const calls = { fetch: [] };

export function mockFetch(handler) {
  globalThis.fetch = async (url, opts) => {
    const entry = { url: String(url), method: (opts && opts.method) || 'GET' };
    if (opts && typeof opts.body === 'string') {
      try { entry.body = JSON.parse(opts.body); } catch { entry.body = opts.body; }
    }
    calls.fetch.push(entry);
    return handler(String(url), opts || {});
  };
}

export function res(status, payload) {
  return { ok: status >= 200 && status < 300, status, json: async () => (payload || {}) };
}

export function fire(node, type) {
  node.dispatchEvent({ type, stopPropagation() {}, preventDefault() {} });
}

export function ready() { fire(document, 'DOMContentLoaded'); }

export function byId(id) { return document.getElementById(id); }

export function setValue(id, value) {
  const n = document.getElementById(id);
  if (!n) throw new Error('no element ' + id);
  n.value = value;
  return n;
}

export function tick(n = 8) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}

/** A node's text with boundaries preserved, so adjacent spans never read as
 *  one word (the `readable` getter the effect-card harness introduced). */
export function readable(node) { return node ? node.readable : ''; }
"""


@pytest.fixture(scope="module")
def skills_sandbox(tmp_path_factory):
    shim = _SHIM.replace("__IDS__", json.dumps(_index_ids()))
    return _make_sandbox(tmp_path_factory.mktemp("workshopskills"), SKILLS_JS, shim, _STUBS)


@pytest.fixture(scope="module")
def memory_sandbox(tmp_path_factory):
    shim = _SHIM.replace("__IDS__", json.dumps(_index_ids()))
    return _make_sandbox(tmp_path_factory.mktemp("workshopmem"), MEMORY_JS, shim, _STUBS)


_SKILLS_PREAMBLE = (
    "import { document, calls, mockFetch, res, fire, ready, byId, setValue, tick, readable }"
    " from './shim.js';\n"
    "import uiStub, { calls as uiCalls } from './ui.js';\n"
    "const skillsModule = (await import('./skills.js')).default;\n"
)
_MEMORY_PREAMBLE = (
    "import { document, calls, mockFetch, res, fire, ready, byId, setValue, tick,"
    " configureSlider, readable } from './shim.js';\n"
    "const mem = await import('./memory.js');\n"
)


def _skills(sandbox, script):
    return _run(sandbox, _SKILLS_PREAMBLE, script)


def _memory(sandbox, script):
    return _run(sandbox, _MEMORY_PREAMBLE, script)


_EMPTY_STORE = """
    mockFetch((url) => {
      if (url.includes('/api/skills/audit-status')) return res(200, { status: 'idle' });
      if (url.includes('/api/skills/index')) return res(200, { index: [], count: 0 });
      if (url.includes('/api/prefs')) return res(200, {});
      if (url.includes('/api/skills')) return res(200, { skills: [], count: 0 });
      return res(200, {});
    });
"""


# ── P8-02 · four fields that were only ever reachable by knowing the format ──

def test_the_form_posts_the_four_fields_the_api_has_always_taken(skills_sandbox):
    """`SkillAddRequest` has accepted all four since it was written and the
    form sent none of them. A mutation that adds the inputs to the markup and
    forgets the request body looks finished and dies here."""
    out = _skills(skills_sandbox, _EMPTY_STORE + """
        ready();
        await tick();
        setValue('new-skill-name', 'tidy-logs');
        setValue('new-skill-description', 'tidy the build logs');
        setValue('new-skill-procedure', '1. run it\\n2. read it');
        setValue('new-skill-pitfalls', '- it eats symlinks\\nit is slow on NFS');
        setValue('new-skill-verification', 'the log is smaller\\nnothing else changed');
        setValue('new-skill-platforms', 'linux, macos');
        setValue('new-skill-toolsets', 'shell , files');
        calls.fetch.length = 0;
        fire(byId('add-skill-btn'), 'click');
        await tick();
        // `P8-12` put a lint POST in front of this one, so "the first POST"
        // is no longer the save. Named rather than positional (`Law 20`).
        const post = calls.fetch.find(c => c.method === 'POST' && c.url.endsWith('/api/skills/add'));
        console.log(JSON.stringify({ post }));
    """)
    body = out["post"]["body"]
    assert out["post"]["url"].endswith("/api/skills/add")
    assert body["pitfalls"] == ["it eats symlinks", "it is slow on NFS"], (
        "pitfalls must arrive as a list with the bullet prefix stripped, the "
        "same shape the procedure field has always sent"
    )
    assert body["verification"] == ["the log is smaller", "nothing else changed"]
    assert body["platforms"] == ["linux", "macos"]
    assert body["requires_toolsets"] == ["shell", "files"]
    # The four that already worked must not have been disturbed on the way.
    assert body["name"] == "tidy-logs"
    assert body["procedure"] == ["run it", "read it"]


def test_the_four_new_fields_clear_when_the_skill_is_saved(skills_sandbox):
    """Everything else on this form clears on success. A field that keeps its
    text is the next skill silently inheriting the last one's pitfalls."""
    out = _skills(skills_sandbox, _EMPTY_STORE + """
        ready();
        await tick();
        setValue('new-skill-description', 'tidy the build logs');
        for (const id of ['new-skill-pitfalls', 'new-skill-verification',
                          'new-skill-platforms', 'new-skill-toolsets']) setValue(id, 'x');
        fire(byId('add-skill-btn'), 'click');
        await tick();
        console.log(JSON.stringify({
          left: ['new-skill-pitfalls', 'new-skill-verification',
                 'new-skill-platforms', 'new-skill-toolsets']
                .filter(id => byId(id).value !== ''),
        }));
    """)
    assert out["left"] == []


def test_an_empty_optional_field_does_not_become_an_empty_string_entry(skills_sandbox):
    """`[""]` is not "no pitfalls" — it is one blank pitfall, and it renders as
    a bullet with nothing after it in the model's prompt."""
    out = _skills(skills_sandbox, _EMPTY_STORE + """
        ready();
        await tick();
        setValue('new-skill-description', 'tidy the build logs');
        calls.fetch.length = 0;
        fire(byId('add-skill-btn'), 'click');
        await tick();
        console.log(JSON.stringify({ body: calls.fetch.find(c => c.method === 'POST' && c.url.endsWith('/api/skills/add')).body }));
    """)
    for field in ("pitfalls", "verification", "platforms", "requires_toolsets"):
        assert out["body"][field] == [], field


def test_the_four_inputs_are_on_the_page_and_carry_their_own_explanation():
    """`Law 15`, and the reason this row is a `Law 15` row rather than a
    `Law 13` one: all four were reachable, by someone who already knew the
    frontmatter format. A field with a name and no sentence reproduces that."""
    html = INDEX.read_text(encoding="utf-8")
    block = html[html.index('<details class="skill-more">'):html.index('id="add-skill-btn"')]
    for element_id in ("new-skill-pitfalls", "new-skill-verification",
                       "new-skill-platforms", "new-skill-toolsets"):
        assert f'id="{element_id}"' in block, element_id
    assert "aria-label=" in block
    # The one fact about these fields nobody can guess, and `P8-07`'s half of it.
    assert "never sent" in block
    assert "hidden unless all are on" in block or "hide the skill" in block


# ── P8-06 / P8-07 · the endpoint written to answer this, finally called ─────

def test_the_preview_calls_the_endpoint_no_frontend_file_had_ever_called(skills_sandbox):
    out = _skills(skills_sandbox, _EMPTY_STORE + """
        ready();
        await tick();
        calls.fetch.length = 0;
        fire(byId('skills-preview-btn'), 'click');
        await tick();
        console.log(JSON.stringify({ urls: calls.fetch.map(c => c.url) }));
    """)
    assert any(u.endswith("/api/skills/index") for u in out["urls"]), out["urls"]


def test_the_preview_shows_what_the_endpoint_returned_and_not_a_recomputation(skills_sandbox):
    """The names, descriptions and categories come back verbatim. A preview
    that filters or re-sorts on its own has become a second renderer, and the
    first time the server's rules move it is a confident lie (`Law 14`)."""
    index = [
        {"name": "tidy-logs", "description": "tidy the build logs",
         "category": "ops", "status": "published"},
        {"name": "retry-with-backoff", "description": "retry politely",
         "category": "general", "status": "draft"},
    ]
    out = _skills(skills_sandbox, """
        mockFetch((url) => {
          if (url.includes('/api/skills/audit-status')) return res(200, { status: 'idle' });
          if (url.includes('/api/skills/index')) return res(200, { index: %s, count: 2 });
          if (url.includes('/api/prefs')) return res(200, {});
          if (url.includes('/api/skills')) return res(200, { skills: [], count: 0 });
          return res(200, {});
        });
        ready();
        await tick();
        fire(byId('skills-preview-btn'), 'click');
        await tick();
        const panel = byId('skills-prompt-panel');
        console.log(JSON.stringify({
          hidden: panel.className.includes('hidden'),
          text: readable(panel),
          names: panel.querySelectorAll('.skill-prompt-name').map(n => n.textContent),
          cats: panel.querySelectorAll('.skill-prompt-cat').map(n => n.textContent),
        }));
    """ % json.dumps(index))
    assert out["hidden"] is False
    assert sorted(out["names"]) == ["retry-with-backoff", "tidy-logs"]
    assert sorted(out["cats"]) == ["general", "ops"]
    assert "tidy the build logs" in out["text"]
    assert "retry politely" in out["text"]


def test_an_empty_catalogue_says_so_rather_than_drawing_nothing(skills_sandbox):
    """A blank panel reads as broken. It also happens to be the state a person
    is most likely to be in the first time they open this."""
    out = _skills(skills_sandbox, _EMPTY_STORE + """
        ready();
        await tick();
        fire(byId('skills-preview-btn'), 'click');
        await tick();
        console.log(JSON.stringify({ text: readable(byId('skills-prompt-panel')) }));
    """)
    assert "no skills" in out["text"].lower()
    assert "publish one" in out["text"].lower()


def test_the_preview_names_what_is_never_sent(skills_sandbox):
    """`P8-07`. The catalogue carries a name and a description; a match adds
    the procedure and the pitfalls; the verification steps and the body of
    SKILL.md are sent nowhere at all. The last of those is the one people are
    surprised by, and it was written down nowhere."""
    out = _skills(skills_sandbox, _EMPTY_STORE + """
        ready();
        await tick();
        fire(byId('skills-preview-btn'), 'click');
        await tick();
        console.log(JSON.stringify({ text: readable(byId('skills-prompt-panel')) }));
    """)
    text = out["text"].lower()
    assert "never sent" in text
    assert "verification" in text
    assert "skill.md" in text
    assert "pitfalls" in text and "procedure" in text


def test_the_preview_says_a_skill_arms_the_approval_gate(skills_sandbox):
    """`P8-18` on the surface that shows the injected text. Correct behaviour,
    completely invisible, and the reason a run stops halfway."""
    out = _skills(skills_sandbox, _EMPTY_STORE + """
        ready();
        await tick();
        fire(byId('skills-preview-btn'), 'click');
        await tick();
        console.log(JSON.stringify({ text: readable(byId('skills-prompt-panel')) }));
    """)
    text = out["text"].lower()
    assert "untrusted" in text
    assert "asks you" in text


def test_skill_text_reaches_the_preview_as_text_and_never_as_markup(skills_sandbox):
    """`H01`'s lesson on the one panel whose whole job is to show user-written
    text verbatim. A description is a perfectly good XSS payload, and this
    surface exists to print descriptions."""
    hostile = {"name": "x", "category": "general", "status": "published",
               "description": "<img src=x onerror=alert(1)>"}
    out = _skills(skills_sandbox, """
        mockFetch((url) => {
          if (url.includes('/api/skills/index')) return res(200, { index: [%s] });
          if (url.includes('/api/skills/audit-status')) return res(200, { status: 'idle' });
          if (url.includes('/api/prefs')) return res(200, {});
          if (url.includes('/api/skills')) return res(200, { skills: [] });
          return res(200, {});
        });
        ready();
        await tick();
        fire(byId('skills-preview-btn'), 'click');
        await tick();
        const panel = byId('skills-prompt-panel');
        const desc = panel.querySelector('.skill-prompt-desc');
        console.log(JSON.stringify({ text: desc.textContent, html: desc.innerHTML }));
    """ % json.dumps(hostile))
    assert out["text"] == "<img src=x onerror=alert(1)>"
    assert out["html"] == "", "the description was assigned as markup"


def test_the_preview_closes_again(skills_sandbox):
    """It is a toggle on a toolbar beside two other toggles. One that only
    opens is the panel that eats the list."""
    out = _skills(skills_sandbox, _EMPTY_STORE + """
        ready();
        await tick();
        fire(byId('skills-preview-btn'), 'click');
        await tick();
        const opened = !byId('skills-prompt-panel').className.includes('hidden');
        fire(byId('skills-preview-btn'), 'click');
        await tick();
        console.log(JSON.stringify({
          opened,
          closed: byId('skills-prompt-panel').className.includes('hidden'),
        }));
    """)
    assert out["opened"] is True and out["closed"] is True


# ── P8-04 · the loose end of the slider ────────────────────────────────────

SLIDER = "configureSlider({ min: '45', max: '100', step: '5', value: '85' });"


def test_the_loose_end_of_the_slider_is_the_left_one_now(memory_sandbox):
    """Dragging a control labelled "Minimum confidence" to its far right used
    to store 0 — the one value that turns the gate off. Both ends are checked
    in one case so a fix that moves the label without moving the mapping fails
    on the value rather than on the word."""
    out = _memory(memory_sandbox, """
        %s
        mockFetch(() => res(200, { value: 0.85 }));
        await mem.syncPrefSlider('skill-confidence-slider', 'skill_min_confidence',
                                 'skill-confidence-label', 0.85);
        const slider = byId('skill-confidence-slider');
        const label = byId('skill-confidence-label');
        const saved = [];
        for (const pos of ['45', '50', '85', '100']) {
          slider.value = pos;
          calls.fetch.length = 0;
          fire(slider, 'input');
          const shown = label.textContent;
          fire(slider, 'change');
          await tick();
          saved.push([pos, calls.fetch.filter(c => c.method === 'PUT').map(c => c.body.value)[0], shown]);
        }
        console.log(JSON.stringify({ saved }));
    """ % SLIDER)
    saved = {row[0]: (row[1], row[2]) for row in out["saved"]}
    assert saved["45"][0] == 0, "the sentinel stop must still mean no minimum"
    assert saved["45"][1] == "All"
    assert saved["50"][0] == 0.5
    assert saved["85"][0] == 0.85
    assert saved["100"][0] == 1.0, (
        "the far right stored 0 before this row — the strictest-looking "
        "position was the loosest setting on the control"
    )
    assert saved["100"][1] == "≥ 100%"


def test_a_stored_zero_still_lands_on_the_stop_that_means_it(memory_sandbox):
    """Nothing about the stored preference changes, which is the whole reason
    this fix is safe: someone who had "All" set keeps it."""
    out = _memory(memory_sandbox, """
        %s
        mockFetch(() => res(200, { value: 0 }));
        await mem.syncPrefSlider('skill-confidence-slider', 'skill_min_confidence',
                                 'skill-confidence-label', 0.85);
        console.log(JSON.stringify({
          pos: byId('skill-confidence-slider').value,
          label: byId('skill-confidence-label').textContent,
        }));
    """ % SLIDER)
    assert out["pos"] == "45"
    assert out["label"] == "All"


def test_a_stored_value_below_the_lowest_stop_is_not_read_as_no_minimum(memory_sandbox):
    """0.45 and "no minimum at all" are not the same instruction, and the
    sentinel is now sitting at 45. Anything real clamps to the lowest
    percentage the control can express instead."""
    out = _memory(memory_sandbox, """
        %s
        mockFetch(() => res(200, { value: 0.3 }));
        await mem.syncPrefSlider('skill-confidence-slider', 'skill_min_confidence',
                                 'skill-confidence-label', 0.85);
        console.log(JSON.stringify({
          pos: byId('skill-confidence-slider').value,
          label: byId('skill-confidence-label').textContent,
        }));
    """ % SLIDER)
    assert out["pos"] == "50"
    assert out["label"] == "≥ 50%"


# ── P8-05 · the coupling the toggle never mentioned ────────────────────────

def test_the_hint_says_the_loose_end_lets_everything_in(memory_sandbox):
    out = _memory(memory_sandbox, """
        console.log(JSON.stringify({
          all: mem.skillGateHints({ autoApprove: true, minConfidence: 0 }),
          strict: mem.skillGateHints({ autoApprove: true, minConfidence: 0.95 }),
        }));
    """)
    assert "loosest" in out["all"]["confidence"]
    assert "No minimum" in out["all"]["confidence"]
    assert "95%" in out["strict"]["confidence"]


def test_turning_auto_approve_off_says_what_it_did_to_injection(memory_sandbox):
    """The defect: a toggle whose label only mentions the audit silently makes
    injection published-only, by setting the floor to a number no confidence
    can reach."""
    out = _memory(memory_sandbox, """
        console.log(JSON.stringify({
          off: mem.skillGateHints({ autoApprove: false, minConfidence: 0.85 }),
          on: mem.skillGateHints({ autoApprove: true, minConfidence: 0.85 }),
        }));
    """)
    assert "only published skills are injected" in out["off"]["coupling"]
    assert "Audit all" in out["off"]["confidence"]
    assert out["on"]["coupling"] != out["off"]["coupling"]


def test_the_two_sentences_redraw_when_either_control_moves(memory_sandbox):
    """Half a coupling is worse than none: a sentence that was true when the
    panel opened and is not true now is read as the product being wrong about
    something else."""
    out = _memory(memory_sandbox, """
        %s
        const toggle = byId('auto-approve-skills-toggle');
        toggle.checked = true;
        mem.refreshSkillGateHints();
        const on = byId('skill-approve-coupling').textContent;
        toggle.checked = false;
        mem.refreshSkillGateHints();
        const off = byId('skill-approve-coupling').textContent;
        byId('skill-confidence-slider').value = '45';
        toggle.checked = true;
        mem.refreshSkillGateHints();
        console.log(JSON.stringify({
          on, off, loose: byId('skill-confidence-hint').textContent,
        }));
    """ % SLIDER)
    assert out["on"] != out["off"]
    assert "only published skills are injected" in out["off"]
    assert "loosest" in out["loose"]


# ── P8-08 · the task the endpoint has always accepted ──────────────────────
#
# Not driven by clicking, and the docstring at the top of this file says why.
# `Law 20` option 2 instead: resolve the scope, then assert inside it.

def test_the_test_request_carries_a_task():
    body = js_function(SKILLS_JS.read_text(encoding="utf-8"),
                        "async function _startSkillTest")
    assert "JSON.stringify({ task, model, endpoint_url })" in body, (
        "the POST body is the whole row: the endpoint has read `body.task` "
        "since it was written and the UI sent `{model, endpoint_url}`"
    )
    assert "/test`" in body


def test_the_task_comes_from_a_box_the_user_can_type_in():
    body = js_function(SKILLS_JS.read_text(encoding="utf-8"),
                        "async function _testSkill")
    assert "skill-test-task-input" in body
    assert "_startSkillTest(card, name, (taskEl && taskEl.value.trim()) || ''" in body
    # Blank is a real choice and the box has to say what it costs, or the
    # server's invented scenario looks like the product ignoring the field.
    assert "Leave blank" in body
    # `P8-18` where a person will actually meet it.
    assert "stop halfway" in body


def test_retry_starts_from_the_task_the_last_run_used():
    """`/test-status` has always echoed `task`. Re-running the same task is
    one click and changing it is one edit — which is also what `P8-09`'s
    before/after diff will need when its own blocker clears."""
    body = js_function(SKILLS_JS.read_text(encoding="utf-8"),
                        "async function _testSkill")
    assert "previous.task" in body


def test_the_server_uses_the_task_it_is_given_and_invents_one_only_when_blank():
    """The other half, driven for real. `_skill_test_messages` is what the run
    is built from, and `_skill_test_task` is the fallback the UI has been
    silently getting for the product's whole history."""
    from routes.skills_routes import _skill_test_messages, _skill_test_task

    mine = _skill_test_messages("# SKILL", "tidy yesterday's build log")
    assert mine[-1] == {"role": "user", "content": "tidy yesterday's build log"}

    invented = _skill_test_task({"when_to_use": "the build log is enormous"})
    assert "the build log is enormous" in invented
    assert "invent a plausible" in invented
    assert invented != "tidy yesterday's build log"


def test_the_skill_under_test_is_still_untrusted_context():
    """`P8-18`'s claim about the test panel, checked rather than asserted in
    prose: this is why a test run can pause on an approval, and the panel now
    says so before the run starts."""
    from routes.skills_routes import _skill_test_messages

    messages = _skill_test_messages("# SKILL", "do it")
    wrapper = next(m for m in messages if isinstance(m.get("metadata"), dict))
    assert wrapper["metadata"]["trusted"] is False
    assert wrapper["metadata"]["tool_gate_untrusted"] is True


# ── the harness reads the page it claims to ────────────────────────────────

def test_the_shim_is_built_from_the_shipped_markup():
    ids = _index_ids()
    for required in ("skills-preview-btn", "skills-prompt-panel",
                     "skill-confidence-slider", "skill-confidence-hint",
                     "skill-approve-coupling", "new-skill-pitfalls"):
        assert required in ids, required
    assert "replaceChildren" in _DOM, (
        "the shared DOM shim lost `replaceChildren`, which every panel built "
        "with createElement in this file uses to swap its contents"
    )


# ── P8-06 (closing half) · the TEXT, not a list rendered to look like it ────
#
# The preview shipped rendering the `index` rows because when it was written the
# endpoint had no `prompt` to render. It has one:
# `services/memory/skill_injection.render_skill_index_block`, the same call
# `agent_loop._build_base_prompt` makes. Every case below chooses a payload whose
# `prompt` and whose `index` DISAGREE — different order, different wording,
# characters no row carries — because that is the only way to tell a panel
# showing the served text from a panel reassembling one that looks like it.

_PROMPT_BLOCK = (
    "\n\n## Available skills\n"
    "Procedures the assistant should consult before doing domain work.\n"
    "\n**ops**\n"
    "- `tidy-logs` — tidy the build logs\n"
    "\n**general**\n"
    "- `retry-with-backoff` — retry politely *(draft)*"
)


def _index_payload(**over) -> str:
    payload = {
        "index": [
            {"name": "tidy-logs", "description": "tidy the build logs",
             "category": "ops", "status": "published"},
            {"name": "retry-with-backoff", "description": "retry politely",
             "category": "general", "status": "draft"},
        ],
        "count": 2,
        "prompt": _PROMPT_BLOCK,
        "prompt_chars": len(_PROMPT_BLOCK),
        "injected_fields": ["name", "description", "category", "status"],
        "withheld_fields": ["procedure", "pitfalls", "verification", "body_extra"],
    }
    payload.update(over)
    return json.dumps(payload)


def _preview(sandbox, payload: str, extra: str = "") -> dict:
    return _skills(sandbox, """
        mockFetch((url) => {
          if (url.includes('/api/skills/audit-status')) return res(200, { status: 'idle' });
          if (url.includes('/api/skills/index')) return res(200, %s);
          if (url.includes('/api/prefs')) return res(200, {});
          if (url.includes('/api/skills')) return res(200, { skills: [], count: 0 });
          return res(200, {});
        });
        ready();
        await tick();
        fire(byId('skills-preview-btn'), 'click');
        await tick();
        const panel = byId('skills-prompt-panel');
        const pre = panel.querySelector('.skill-prompt-text');
        %s
        console.log(JSON.stringify({
          text: readable(panel),
          exact: pre ? pre.textContent : null,
          exactHtml: pre ? pre.innerHTML : null,
          label: panel.querySelector('.skill-prompt-exact-label')
                 ? panel.querySelector('.skill-prompt-exact-label').textContent : '',
          withheld: panel.querySelector('.skill-prompt-withheld')
                 ? panel.querySelector('.skill-prompt-withheld').textContent : null,
        }));
    """ % (payload, extra))


def test_the_preview_shows_the_characters_the_model_is_given(skills_sandbox):
    """The row's whole distinction. `prompt` here carries a heading, a preamble,
    blank lines, backticks and a `*(draft)*` badge — **none** of which any
    `index` row contains. A preview rebuilt from the rows cannot produce this
    string, so a byte-for-byte comparison is the only assertion that separates
    the two implementations."""
    out = _preview(skills_sandbox, _index_payload())
    assert out["exact"] == _PROMPT_BLOCK, (
        "the panel must print the served `prompt` unaltered — no trim, no "
        "re-wrap, no re-sort; the moment it formats it, it stops being evidence"
    )


def test_the_prompt_reaches_the_preview_as_text_and_never_as_markup(skills_sandbox):
    """A skill description is a perfectly good XSS payload and it arrives inside
    this string. `H01` on the one node in the app whose contents are a prompt
    assembled out of what users typed."""
    hostile = "\n\n## Available skills\n- `x` — <img src=x onerror=alert(1)>"
    out = _preview(skills_sandbox, _index_payload(prompt=hostile,
                                                  prompt_chars=len(hostile)))
    assert out["exact"] == hostile
    assert out["exactHtml"] == "", "the prompt was assigned as markup"


def test_the_preview_says_how_much_of_the_prompt_this_is(skills_sandbox):
    """A person reading a skills catalogue has no way to judge what it costs
    them. The endpoint counts the characters; printing the number is what makes
    "my prompt is full of skills" a thing anybody can notice."""
    out = _preview(skills_sandbox, _index_payload())
    assert str(len(_PROMPT_BLOCK)) in out["label"].replace(",", ""), out["label"]
    assert "character" in out["label"].lower()


def test_an_empty_library_says_no_line_reaches_the_prompt(skills_sandbox):
    """`render_skill_index_block` returns `""` for an empty index, and "" is a
    real answer — *nothing about skills is injected at all* — which a blank
    panel cannot distinguish from a failed fetch."""
    out = _preview(skills_sandbox,
                   _index_payload(index=[], count=0, prompt="", prompt_chars=0))
    assert out["exact"] is None, "there is no text to print, so there is no block"
    assert "nothing is injected" in out["label"].lower()


def test_the_withheld_list_is_the_servers_and_not_a_sentence_about_it(skills_sandbox):
    """`WITHHELD_FIELDS` is derived from `Skill.to_dict()`, so a field added to
    the schema appears there without anyone remembering to. The panel's English
    beside it is hand-written and cannot follow. Printing the served list is
    what keeps the two honest (`Law 7`)."""
    out = _preview(skills_sandbox, _index_payload(
        withheld_fields=["verification", "body_extra", "a_field_added_tomorrow"]))
    assert out["withheld"] is not None, "the served list is not drawn"
    for field in ("verification", "body_extra", "a_field_added_tomorrow"):
        assert field in out["withheld"], field


def test_the_panel_no_longer_titles_itself_after_the_list(skills_sandbox):
    """It called itself "The catalogue the AI browses" — accurate when the list
    was all it had, and a promise the prompt block in front of it does not keep."""
    out = _preview(skills_sandbox, _index_payload())
    assert "what the ai is given" in out["text"].lower()


# ── P8-12 · the lint, on the surface where a person is typing ───────────────

_LINT_TWO = {
    "verdict": "problems",
    "counts": {"problem": 1, "advisory": 1},
    "findings": [
        {"code": "missing-procedure", "severity": "problem", "field": "procedure",
         "message": "No Procedure. There is nothing for the model to follow.",
         "fix": "Add the numbered steps, in the order they are performed."},
        {"code": "no-tags", "severity": "advisory", "field": "tags",
         "message": "No tags. A whole-token tag match is the strongest signal.",
         "fix": "Add three to five keywords a user would actually type."},
    ],
}


def _lint_store(lint_payload: str, lint_status: int = 200) -> str:
    return """
        mockFetch((url) => {
          if (url.includes('/api/skills/audit-status')) return res(200, { status: 'idle' });
          if (url.includes('/api/skills/index')) return res(200, { index: [], count: 0 });
          if (url.includes('/api/skills/lint')) return res(%d, %s);
          if (url.includes('/api/prefs')) return res(200, {});
          if (url.includes('/api/skills')) return res(200, { skills: [], count: 0 });
          return res(200, {});
        });
    """ % (lint_status, lint_payload)


def test_leaving_a_field_asks_the_lint_what_is_wrong(skills_sandbox):
    """`manage_skills action=lint` has answered this since the lint landed and
    the form could not ask, because a browser has no way into a tool handler.
    On blur, because that is the moment a person has finished saying one thing
    and has not yet committed to the whole."""
    out = _skills(skills_sandbox, _lint_store(json.dumps(_LINT_TWO)) + """
        ready();
        await tick();
        setValue('new-skill-name', 'tidy-logs');
        setValue('new-skill-description', 'tidy the build logs');
        calls.fetch.length = 0;
        fire(byId('new-skill-description'), 'blur');
        await tick();
        const post = calls.fetch.find(c => c.method === 'POST');
        console.log(JSON.stringify({ post, text: readable(byId('skill-lint-panel')) }));
    """)
    assert out["post"]["url"].endswith("/api/skills/lint")
    assert out["post"]["body"]["name"] == "tidy-logs"
    assert out["post"]["body"]["description"] == "tidy the build logs"
    assert "No Procedure" in out["text"]


def test_a_problem_and_a_suggestion_do_not_look_the_same(skills_sandbox):
    """The row asks for `problem` in the accent colour and `advisory` muted.
    Colour cannot be driven here, so what is pinned is the thing colour is
    applied through — a class per severity, taken from the served `severity`
    rather than guessed from the wording."""
    out = _skills(skills_sandbox, _lint_store(json.dumps(_LINT_TWO)) + """
        ready();
        await tick();
        setValue('new-skill-description', 'tidy the build logs');
        fire(byId('new-skill-description'), 'blur');
        await tick();
        const panel = byId('skill-lint-panel');
        console.log(JSON.stringify({
          problems: panel.querySelectorAll('.skill-lint-problem').map(n => readable(n)),
          advisories: panel.querySelectorAll('.skill-lint-advisory').map(n => readable(n)),
        }));
    """)
    assert len(out["problems"]) == 1 and len(out["advisories"]) == 1
    assert "No Procedure" in out["problems"][0]
    assert "No tags" in out["advisories"][0]


def test_every_finding_says_what_is_wrong_and_then_what_to_type(skills_sandbox):
    """`message` then `fix`. A finding with only the first is a complaint, and
    the reason this row exists is that nobody could tell what to do about a
    skill the nightly audit was about to demote."""
    out = _skills(skills_sandbox, _lint_store(json.dumps(_LINT_TWO)) + """
        ready();
        await tick();
        setValue('new-skill-description', 'x');
        fire(byId('new-skill-description'), 'blur');
        await tick();
        const rows = byId('skill-lint-panel').querySelectorAll('.skill-lint-finding');
        console.log(JSON.stringify({
          rows: rows.map(r => ({
            message: r.querySelector('.skill-lint-message').textContent,
            fix: r.querySelector('.skill-lint-fix') ? r.querySelector('.skill-lint-fix').textContent : null,
          })),
        }));
    """)
    for row, expected in zip(out["rows"], _LINT_TWO["findings"]):
        assert row["message"] == expected["message"]
        assert row["fix"] == expected["fix"], "the fix is the sentence acted on"


def test_the_lint_advises_and_never_gates_the_save(skills_sandbox):
    """The row's sharpest clause. A draft with a `problems` verdict still
    reaches `/api/skills/add` — a lint that blocks is a validator, and this
    product's whole authoring story is that a draft is allowed to be bad."""
    out = _skills(skills_sandbox, _lint_store(json.dumps(_LINT_TWO)) + """
        ready();
        await tick();
        setValue('new-skill-name', 'tidy-logs');
        setValue('new-skill-description', 'tidy the build logs');
        calls.fetch.length = 0;
        fire(byId('add-skill-btn'), 'click');
        await tick();
        console.log(JSON.stringify({
          posts: calls.fetch.filter(c => c.method === 'POST').map(c => c.url),
          text: readable(byId('skill-lint-panel')),
        }));
    """)
    assert any(u.endswith("/api/skills/add") for u in out["posts"]), out["posts"]
    # And the lint ran first, or "before they save" is not what happened.
    assert out["posts"][0].endswith("/api/skills/lint"), out["posts"]
    assert "Saved as a draft" in out["text"]


def test_a_lint_that_cannot_answer_does_not_take_the_save_with_it(skills_sandbox):
    """The check is advice. A 500, a dropped connection or an install with the
    route disabled must cost the person nothing — least of all the skill they
    just typed."""
    out = _skills(skills_sandbox, _lint_store("{}", lint_status=500) + """
        ready();
        await tick();
        setValue('new-skill-name', 'tidy-logs');
        setValue('new-skill-description', 'tidy the build logs');
        calls.fetch.length = 0;
        fire(byId('add-skill-btn'), 'click');
        await tick();
        console.log(JSON.stringify({
          posts: calls.fetch.filter(c => c.method === 'POST').map(c => c.url),
          errors: uiCalls.errors,
        }));
    """)
    assert out["posts"][0].endswith("/api/skills/lint"), (
        "the lint has to have been asked, or this case proves nothing about "
        "what happens when it cannot answer"
    )
    assert any(u.endswith("/api/skills/add") for u in out["posts"]), out["posts"]
    assert out["errors"] == [], "a failed lint must not be reported as a failed save"


def test_an_untouched_form_is_not_linted(skills_sandbox):
    """Tabbing through an empty form is not a request for a verdict, and eight
    findings about a blank form is the surface shouting at somebody who has not
    started."""
    out = _skills(skills_sandbox, _lint_store(json.dumps(_LINT_TWO)) + """
        ready();
        await tick();
        calls.fetch.length = 0;
        fire(byId('new-skill-name'), 'blur');
        await tick();
        console.log(JSON.stringify({
          posts: calls.fetch.filter(c => c.method === 'POST').map(c => c.url),
          hidden: byId('skill-lint-panel').className.includes('hidden'),
        }));
    """)
    assert out["posts"] == []
    assert out["hidden"] is True


def test_a_clean_draft_is_told_it_is_clean(skills_sandbox):
    """Silence reads as "the check did not run", which is the state this panel
    is most often in and the one that makes people stop trusting it."""
    clean = {"verdict": "clean", "counts": {"problem": 0, "advisory": 0}, "findings": []}
    out = _skills(skills_sandbox, _lint_store(json.dumps(clean)) + """
        ready();
        await tick();
        setValue('new-skill-description', 'tidy the build logs');
        fire(byId('new-skill-description'), 'blur');
        await tick();
        console.log(JSON.stringify({ text: readable(byId('skill-lint-panel')) }));
    """)
    assert "nothing to fix" in out["text"].lower()


def test_the_lint_and_the_save_read_the_same_form(skills_sandbox):
    """Two readers of eight inputs are two chances to disagree about whether the
    procedure box was empty — and a lint judging different text from the one the
    save sends is worse than no lint (`Law 14`)."""
    out = _skills(skills_sandbox, _lint_store(json.dumps(_LINT_TWO)) + """
        ready();
        await tick();
        setValue('new-skill-name', 'tidy-logs');
        setValue('new-skill-description', 'tidy the build logs');
        setValue('new-skill-procedure', '1. run it\\n2. read it');
        setValue('new-skill-tags', 'logs, build');
        setValue('new-skill-when', 'the build log is enormous');
        setValue('new-skill-pitfalls', '- it eats symlinks');
        setValue('new-skill-verification', 'the log is smaller');
        calls.fetch.length = 0;
        fire(byId('add-skill-btn'), 'click');
        await tick();
        const posts = calls.fetch.filter(c => c.method === 'POST');
        console.log(JSON.stringify({
          lint: posts.find(c => c.url.endsWith('/api/skills/lint')).body,
          add: posts.find(c => c.url.endsWith('/api/skills/add')).body,
        }));
    """)
    for field in ("name", "description", "category", "when_to_use",
                  "procedure", "tags", "pitfalls", "verification"):
        assert out["lint"][field] == out["add"][field], field


def _lint_request(user: str, body: dict) -> Request:
    """The minimum `_owner(request)` reads. Lifted from
    `tests/test_skills_routes_owner_update.py`, which drives these routes the
    same way — one pattern for reaching a handler, not two (`Law 14`)."""
    class DummyApp:
        state = State()

    return Request(scope={
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", b"application/json")],
        "app": DummyApp(),
        "state": {"current_user": user},
    }, receive=lambda: None)


async def test_the_lint_route_answers_a_draft_and_writes_nothing(tmp_path):
    """The other half, driven for real — the handler, not the function under
    it. The route is the door the browser needed: `manage_skills action=lint`
    has answered this since the lint landed and a browser has no way into a tool
    handler. Both call `lint_skill`, so the chat channel and the form cannot
    disagree about whether a skill is a duplicate (`Law 14`).

    Nothing may reach disk. The draft is a question.
    """
    from routes.skills_routes import SkillLintRequest, setup_skills_routes

    sm = SkillsManager(str(tmp_path))
    router = setup_skills_routes(sm)
    handler = next(r.endpoint for r in router.routes
                   if r.path == "/api/skills/lint" and "POST" in r.methods)

    before = sorted(p.name for p in tmp_path.rglob("SKILL.md"))
    result = await handler(_lint_request("alice", {}), SkillLintRequest(
        name="Tidy Logs", description="", procedure=[], when_to_use="",
        tags=[], pitfalls=[], verification=[], category="general"))

    assert result["verdict"] == "problems"
    codes = {f["code"] for f in result["findings"]}
    assert "missing-description" in codes and "missing-procedure" in codes
    # `name-not-a-slug` is the one nobody guesses: the save silently re-slugs.
    assert "name-not-a-slug" in codes
    for finding in result["findings"]:
        assert finding["fix"], finding["code"]
        assert finding["severity"] in ("problem", "advisory")
    assert sorted(p.name for p in tmp_path.rglob("SKILL.md")) == before, (
        "the lint wrote a skill"
    )


async def test_the_lint_route_compares_the_draft_against_the_callers_library(tmp_path):
    """`siblings` is what makes `duplicate-of` possible, and it is the finding
    nobody can reach any other way — the nightly audit demotes the loser of a
    pair to draft, days later, with no trace on the form that made it."""
    from routes.skills_routes import SkillLintRequest, setup_skills_routes

    skills_root = tmp_path / "skills"
    _write_lint_sibling(skills_root, "rotate-nginx-logs", "alice")

    sm = SkillsManager(str(tmp_path))
    router = setup_skills_routes(sm)
    handler = next(r.endpoint for r in router.routes
                   if r.path == "/api/skills/lint" and "POST" in r.methods)

    result = await handler(_lint_request("alice", {}), SkillLintRequest(
        name="rotate-nginx-logs-2", description="rotate the nginx logs nightly",
        when_to_use="the nginx logs are enormous",
        procedure=["rotate them"], tags=["nginx", "logs"]))

    assert "duplicate-of" in {f["code"] for f in result["findings"]}


def test_the_lint_request_model_describes_an_over_long_description_rather_than_refusing():
    """`SkillAddRequest` caps `description` at 200 characters, and "your
    description is past the point the API truncates it" is one of the findings
    this endpoint exists to return. A validator that 422s on the input cannot
    report it."""
    from routes.skills_routes import SkillLintRequest
    from services.memory.skill_lint import MAX_DESCRIPTION, lint_skill

    body = SkillLintRequest(name="x", description="d" * (MAX_DESCRIPTION + 40))
    result = lint_skill(body.model_dump(), [])
    assert "description-too-long" in {f["code"] for f in result["findings"]}


def _write_lint_sibling(skills_root: Path, name: str, owner: str) -> Path:
    """One published skill on disk, for the duplicate check to find."""
    skill_dir = skills_root / "general" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    md = textwrap.dedent(f"""\
        ---
        name: {name}
        description: rotate the nginx logs nightly
        version: 1.0.0
        category: general
        tags: [nginx, logs]
        status: published
        confidence: 0.9
        source: user
        owner: {owner}
        created: 2026-01-01T00:00:00Z
        ---

        # When to use
        the nginx logs are enormous

        # Procedure
        - rotate them
        """)
    path = skill_dir / "SKILL.md"
    path.write_text(md, encoding="utf-8")
    return path
