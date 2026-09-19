# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-11` — work that keeps running after you close the window it belongs to.

THE ROW SAYS FIVE JOBS REPORT INTO CLOSED WINDOWS. RE-MEASURED 2026-09-19: TWO
OF THE FIVE ALREADY REPORTED, AND EACH HAD WRITTEN ITS OWN.

  * the **Forge** puts live text on its own sidebar button —
    `static/index.html:1123` is `#cookbook-bg-status`, a `<span>` inside
    `#tool-cookbook-btn` and therefore outside `#cookbook-modal`, and
    `cookbookRunning.js` writes `"downloading 62%"` / `"cooking"` / `"error"` /
    `"done"` into it from the background poll, beside a notification dot and a
    rail highlight;
  * **research** does the same on `#tool-research-btn` —
    `research/panel.js:_syncResearchRail` adds a pulsing `R2` and lights the
    rail, under a comment that says *"panel-independent so it works with the
    modal closed"*.

Three reported nothing: the **skills audit** (drawn into `#skills-audit-panel`
inside the Brain while `_auditPoll` keeps polling every 1.5 seconds whether or
not the Brain is on screen), the **memory tidy** (a spinner on a button in the
same modal), and the **mailbox poll** — which is the one where the silence is
not merely unhelpful. `emailInbox.js` polls every 60s; the server answers
`sync.source: "unavailable"` with a `retry_in` when it has stopped calling the
mailbox at all; the unread count that comes with it is `0`; and
`_refreshUnreadCount` then hides `#email-unread-dot`. A mailbox Pantheon can no
longer read looks **exactly** like a mailbox with no new mail.

So the row's own prescription — *extend the minimized-dock chips* — is also the
`Law 14` answer to what the measurement found: not *nothing reports*, but *two
separate implementations of reporting and three tools with none*. This file
pins the shared one.

WHAT IS PINNED HERE, AND WHY EACH ONE IS A DEFECT AND NOT A PREFERENCE.

  1. **Two jobs, one window.** `#skills-audit-panel` and `#memory-tidy-btn` are
     both inside `#memory-modal` (`static/index.html:622` and `:452`). A store
     keyed by modal id alone lets the second job overwrite the first and lets
     the first's completion clear the second — a progress indicator that lies
     about what is running, which is worse than the blank it replaced.
  2. **The dock is built lazily, by `minimize()` and by nothing else.** On a
     session where nobody has minimized a window there is no `#minimized-dock`
     in the document, so a chip drawn into it is drawn nowhere. That is the
     shape `Law 13` names: built, passing, and unreachable by the people it is
     for.
  3. **A work chip has no `×`.** Dismissing the indicator while the job runs on
     is the original defect wearing the fix's clothes.
  4. **A work chip has a door.** `email-lib-modal` is deliberately
     `{ rail: null, sidebar: null }` in `_AUTO_WIRE` — it has its own unread dot
     and a second badge was rejected — and `openEmailLibrary` removes the
     element and rebuilds it, so there is nothing to un-hide either. A chip for
     it without an opener is a button that does nothing.
  5. **The label is text.** It carries research questions and skill names.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_a_draft_skill_is_uncatalogued_not_inactive import js_function  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
MODALS_JS = JS / "modalManager.js"
SKILLS_JS = JS / "skills.js"
MEMORY_JS = JS / "memory.js"
EMAIL_JS = JS / "emailLibrary.js"
RESEARCH_JOBS_JS = JS / "research" / "jobs.js"
INDEX_HTML = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


_STUBS = {
    "tileManager.js": (
        "export function previewZoneAt(){ return null; }\nexport function clearPreview(){}\n"
        "export function snapModalToZone(){}\n"
    ),
    "modalSnap.js": (
        "export function suspendDock(){}\nexport function resumeDock(){}\n"
        "export function clearRightDock(){}\nexport function applyEdgeDock(){}\n"
    ),
    "escMenuStack.js": "export function dismissOrRemove(){}\n",
    "toolWindowZOrder.js": "export function nextToolWindowZ(){ return 1; }\n",
}

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

// `modalManager.js` binds `window.addEventListener('modal-dismissed', ...)` at
// module load. `installDom` aliases `window` to `globalThis`, which in node has
// no such method, so without this the module throws on the global instead of
// failing an assertion.
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};

// `_renderDock` preserves any `data-*` a foreign module stamped onto a chip
// (emailLibrary's slot number and unread label) by reading `element.attributes`
// before it rebuilds. The shared shim keeps attributes in `attrs` and `dataset`
// as two plain objects and exposes neither as an `attributes` list, so the real
// module throws on the property rather than failing an assertion. Projecting
// both is what a browser shows: `dataset.modalId` IS `data-modal-id`.
Object.defineProperty(Node.prototype, 'attributes', {
  configurable: true,
  get() {
    const out = Object.entries(this.attrs || {}).map(([name, value]) => ({ name, value: String(value) }));
    for (const [k, v] of Object.entries(this.dataset || {})) {
      out.push({ name: 'data-' + k.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase()), value: String(v) });
    }
    return out;
  },
});
// …and the round trip back: `setAttribute('data-tab-num', 2)` has to land where
// `dataset.tabNum` reads it, or the preservation above restores into a slot
// nothing looks at.
const _setAttribute = Node.prototype.setAttribute;
Node.prototype.setAttribute = function (k, v) {
  _setAttribute.call(this, k, v);
  if (String(k).startsWith('data-')) {
    this.dataset[String(k).slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase())] = String(v);
  }
};
globalThis.matchMedia = () => ({
  matches: false, media: '', addEventListener(){}, removeEventListener(){},
  addListener(){}, removeListener(){},
});
globalThis.requestAnimationFrame = (fn) => setTimeout(() => fn(0), 0);
globalThis.cancelAnimationFrame = (id) => clearTimeout(id);
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.innerWidth = 1280;
globalThis.innerHeight = 800;

// `HTMLElement.click()` — `openClosedWindow` presses the rail/sidebar button
// the person would have pressed, and the shared shim has no such method.
Node.prototype.click = function () { click(this); };

// The chip's `×` is written with `innerHTML` and the work label is then
// `appendChild`ed — and the shared shim's `appendChild` CLEARS `_html` when it
// puts the first real child on a node that was holding a string. So a working
// chip's `innerHTML` reads empty whatever the module wrote into it, and an
// assertion on it would be vacuous on every run: a mutation restoring the `×`
// survived exactly that. Keep what was written, unwiped.
const _htmlDesc = Object.getOwnPropertyDescriptor(Node.prototype, 'innerHTML');
Object.defineProperty(Node.prototype, 'innerHTML', {
  configurable: true,
  get: _htmlDesc.get,
  set(v) { this._writtenHtml = String(v == null ? '' : v); _htmlDesc.set.call(this, v); },
});

export function click(node) {
  node.dispatchEvent({
    type: 'click', target: node, currentTarget: node,
    stopPropagation() {}, preventDefault() {},
  });
}

/** The dock as a person would read it: one entry per chip, in order. */
export function readDock() {
  const dock = document.getElementById('minimized-dock');
  if (!dock) return null;
  return dock.querySelectorAll('.minimized-dock-chip').map((chip) => ({
    id: chip.dataset.modalId,
    title: chip.title,
    working: chip.classList.contains('chip-working'),
    state: (chip.querySelector('.minimized-dock-work') || {}).textContent || null,
    stateHtml: (chip.querySelector('.minimized-dock-work') || {})._html || '',
    hasClose: String(chip._writtenHtml || '').includes('minimized-dock-x'),
  }));
}
"""

_PREAMBLE = (
    "import { document, Node, click, readDock } from './shim.js';\n"
    "import * as Modals from './modalManager.js';\n"
)


@pytest.fixture(scope="module")
def dock(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("dock"), MODALS_JS, _SHIM, _STUBS)


def _dock(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


# ── the store: two jobs in one window ───────────────────────────────────────

def test_two_jobs_in_one_window_do_not_erase_each_other(dock):
    """The Brain hosts the skills audit AND the memory tidy. Keyed by modal id
    alone, the second job silently replaces the first on the dock and the
    first's completion clears the survivor."""
    out = _dock(dock, """
        Modals.setBackgroundWork('memory-modal', { key: 'skills-audit', label: 'Auditing 4/19',
                                                   detail: 'Skills audit: 4 of 19 done' });
        const afterAudit = Modals.getBackgroundWork('memory-modal');
        Modals.setBackgroundWork('memory-modal', { key: 'memory-tidy', label: 'Tidying memories',
                                                   detail: 'Brain: tidying memories' });
        const both = Modals.getBackgroundWork('memory-modal');
        const listed = Modals.listBackgroundWork().map(w => w.key).sort();
        // The audit finishes. The tidy is still running.
        Modals.setBackgroundWork('memory-modal', { key: 'skills-audit' });
        const afterOneEnds = Modals.getBackgroundWork('memory-modal');
        Modals.setBackgroundWork('memory-modal', { key: 'memory-tidy' });
        console.log(JSON.stringify({
          afterAudit, both, listed, afterOneEnds,
          empty: Modals.getBackgroundWork('memory-modal'),
        }));
    """)
    assert out["afterAudit"]["label"] == "Auditing 4/19"
    assert out["listed"] == ["memory-tidy", "skills-audit"]
    # Two jobs: the chip counts rather than truncating either sentence, and the
    # tooltip keeps both.
    assert out["both"]["label"] == "2 jobs"
    assert "Skills audit: 4 of 19 done" in out["both"]["detail"]
    assert "Brain: tidying memories" in out["both"]["detail"]
    # The one that ended is gone; the one still running is not.
    assert out["afterOneEnds"]["label"] == "Tidying memories"
    assert out["empty"] is None


def test_the_brain_really_does_hold_both_of_those_jobs():
    """The premise under the test above, read out of the shipped markup rather
    than asserted. If either moves to its own window the collision stops being
    real and the keying stops being load-bearing."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    start = html.index('<div id="memory-modal"')
    end = re.compile(r'\n  <div id="[^"]+" class="modal').search(html, start).start()
    brain = html[start:end]
    assert 'id="skills-audit-panel"' in brain
    assert 'id="memory-tidy-btn"' in brain


def test_a_poll_that_says_the_same_thing_twice_does_not_redraw(dock):
    """`skills.js` polls every 1.5s and research notifies on every job event.
    A store that redrew on every repeat would rebuild the whole dock — and
    every chip's drag wiring — three times a second."""
    out = _dock(dock, """
        const first = Modals.setBackgroundWork('research-overlay', { label: 'Researching', detail: 'q' });
        const same = Modals.setBackgroundWork('research-overlay', { label: 'Researching', detail: 'q' });
        const moved = Modals.setBackgroundWork('research-overlay', { label: '2 running', detail: 'q' });
        const cleared = Modals.setBackgroundWork('research-overlay', null);
        const again = Modals.setBackgroundWork('research-overlay', null);
        console.log(JSON.stringify({ first, same, moved, cleared, again }));
    """)
    assert [out["first"], out["same"], out["moved"], out["cleared"], out["again"]] == \
        [True, False, True, True, False]


# ── the dock: a chip for a window that is not open ──────────────────────────

def test_work_builds_the_dock_on_a_session_that_never_minimized_anything(dock):
    """`#minimized-dock` is created by `minimize()` and by nothing else. A
    chip drawn before anything has ever been minimized is drawn into a document
    that has no dock in it — built, green, and invisible (`Law 13`)."""
    out = _dock(dock, """
        const before = !!document.getElementById('minimized-dock');
        Modals.setBackgroundWork('memory-modal', { key: 'skills-audit', label: 'Auditing 2/9',
                                                   detail: 'Skills audit: 2 of 9 done' });
        const chips = readDock();
        Modals.setBackgroundWork('memory-modal', { key: 'skills-audit' });
        console.log(JSON.stringify({ before, chips, after: readDock() }));
    """)
    assert out["before"] is False, "the dock should not exist before any work or minimize"
    assert out["chips"] == [{
        "id": "memory-modal", "title": "Skills audit: 2 of 9 done", "working": True,
        "state": "Auditing 2/9", "stateHtml": "", "hasClose": False,
    }]
    assert out["after"] == [], "the chip leaves when the job does"


def test_a_work_chip_carries_no_close_control(dock):
    """A minimized window's chip has a `×`. A chip that exists only because a
    job is running must not — dismissing the indicator while the job runs on is
    the defect, not the fix."""
    out = _dock(dock, """
        Modals.setBackgroundWork('research-overlay', { label: 'Researching', detail: 'q' });
        const workChip = readDock()[0];
        console.log(JSON.stringify({ workChip }));
    """)
    assert out["workChip"]["hasClose"] is False
    assert out["workChip"]["working"] is True


def test_a_minimized_window_keeps_its_close_control(dock):
    """The other half of the test above, and the reason it is not vacuous: an
    ordinary minimized chip still has the `\u00d7` it always had (`Law 1`)."""
    out = _dock(dock, """
        Modals.minimize('gallery-modal');
        const plain = readDock().find(c => c.id === 'gallery-modal');
        Modals.setBackgroundWork('gallery-modal', { label: 'Generating', detail: 'one image' });
        const alsoWorking = readDock().find(c => c.id === 'gallery-modal');
        Modals.setBackgroundWork('gallery-modal', null);
        Modals.close('gallery-modal');
        console.log(JSON.stringify({ plain, alsoWorking }));
    """)
    assert out["plain"]["hasClose"] is True
    assert out["plain"]["working"] is False
    # A minimized window that ALSO has work keeps its close control — closing it
    # is still a thing the person may do, and the chip was already theirs.
    assert out["alsoWorking"]["hasClose"] is True
    assert out["alsoWorking"]["working"] is True


def test_a_chip_does_not_jump_to_the_end_of_the_dock_when_another_window_docks(dock):
    """`_dockOrder` is what keeps a chip in its slot across re-renders. A work
    chip belongs to a window that is not in `_state`, so an order list pruned by
    `_state` alone drops it every render and re-adds it at the back — and a
    skills audit re-stating itself every 1.5 seconds would walk across the dock
    while somebody tried to read it."""
    out = _dock(dock, """
        Modals.setBackgroundWork('memory-modal', { key: 'skills-audit', label: 'Auditing 1/9' });
        const first = readDock().map(c => c.id);
        Modals.minimize('gallery-modal');
        const second = readDock().map(c => c.id);
        Modals.setBackgroundWork('memory-modal', { key: 'skills-audit', label: 'Auditing 2/9' });
        const third = readDock().map(c => c.id);
        Modals.setBackgroundWork('memory-modal', { key: 'skills-audit' });
        Modals.close('gallery-modal');
        console.log(JSON.stringify({ first, second, third }));
    """)
    assert out["first"] == ["memory-modal"]
    assert out["second"] == ["memory-modal", "gallery-modal"], "the work chip held its slot"
    assert out["third"] == ["memory-modal", "gallery-modal"]


def test_the_label_is_text_and_never_markup(dock):
    """Labels carry research questions and skill names. A question is text a
    person typed, on its way onto a chip."""
    out = _dock(dock, """
        Modals.setBackgroundWork('research-overlay', {
          label: '<img src=x onerror=alert(1)>',
          detail: '<b>boom</b>',
        });
        const chip = readDock()[0];
        console.log(JSON.stringify({ chip }));
    """)
    assert out["chip"]["state"] == "<img src=x onerror=alert(1)>"
    assert out["chip"]["stateHtml"] == "", "the label must not be parsed as markup"
    assert out["chip"]["title"] == "<b>boom</b>"


def test_clicking_a_chip_for_a_closed_window_opens_it_the_way_a_person_would(dock):
    """`restore` needs `_state`, and `close()` deletes the entry — so a chip for
    a closed window has to press the control the person would have pressed."""
    out = _dock(dock, """
        const btn = document.createElement('button');
        btn.setAttribute('id', 'tool-memory-btn');
        let opened = 0;
        btn.addEventListener('click', () => { opened += 1; });
        document.body.appendChild(btn);
        Modals.setBackgroundWork('memory-modal', { key: 'memory-tidy', label: 'Tidying memories' });
        const chip = document.querySelector('.minimized-dock-chip');
        click(chip);
        console.log(JSON.stringify({ opened, wired: Modals.openClosedWindow('memory-modal') }));
    """)
    assert out["opened"] == 1
    assert out["wired"] is True


def test_a_job_can_supply_its_own_door_when_the_wire_map_has_none(dock):
    """`email-lib-modal` is `{ rail: null, sidebar: null }` on purpose, and
    `openEmailLibrary` rebuilds the element rather than un-hiding it. Without an
    opener from the job, its chip is a button that does nothing."""
    out = _dock(dock, """
        let opened = 0;
        Modals.setBackgroundWork('email-lib-modal', {
          key: 'mailbox-sync', label: 'Mail paused in 4 min',
          detail: 'This mailbox is paused — retrying in 4 min',
          open: () => { opened += 1; },
        });
        // A later poll repeats the state and passes no opener. The door must
        // survive the repeat or the chip dies after 60 seconds.
        Modals.setBackgroundWork('email-lib-modal', {
          key: 'mailbox-sync', label: 'Mail paused in 3 min',
          detail: 'This mailbox is paused — retrying in 3 min',
        });
        click(document.querySelector('.minimized-dock-chip'));
        console.log(JSON.stringify({ opened, chip: readDock()[0] }));
    """)
    assert out["opened"] == 1, "the chip must open the window its job belongs to"
    assert out["chip"]["state"] == "Mail paused in 3 min"


def test_the_auto_wire_entry_for_email_is_still_deliberately_empty():
    """The premise under the test above. If email ever gains a rail or sidebar
    entry the opener stops being load-bearing and this file should say so."""
    src = MODALS_JS.read_text(encoding="utf-8")
    wire = js_function(src, "function _autoRegister")
    assert "_AUTO_WIRE" in wire
    table = src[src.index("const _AUTO_WIRE = {"):]
    row = re.search(r"'email-lib-modal':\s*\{[^}]*\}", table).group(0)
    assert "rail: null" in row and "sidebar: null" in row


# ── the producers: called, not grepped ──────────────────────────────────────

def _call_js(tmp_path, harness: str) -> dict:
    """Run one extracted function with its collaborators replaced.

    `Law 20` option 1. Each of the three below is a small named function whose
    only free variables are `setBackgroundWork` and one collaborator, so the
    real body runs against a recorder and a mutation to it dies here.
    """
    case = tmp_path / "case.mjs"
    case.write_text(textwrap.dedent(harness))
    proc = subprocess.run(
        ["node", str(case)], cwd=tmp_path, capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_the_skills_audit_names_its_job_so_the_tidy_cannot_erase_it(tmp_path):
    """The audit's chip body, run for real. It shares `memory-modal` with the
    memory tidy, so an unkeyed write from here is the collision."""
    body = js_function(SKILLS_JS.read_text(encoding="utf-8"), "function _syncAuditChip")
    out = _call_js(tmp_path, f"""
        const calls = [];
        const toasts = [];
        function setBackgroundWork(id, work) {{ calls.push({{ id, work }}); return true; }}
        const uiModule = {{ showToast: (t) => toasts.push(t) }};
        let _auditSaid = null;
        function _syncAuditChip(st) {body}
        _syncAuditChip({{ status: 'running', done: 4, total: 19, current: 'summarise-pdf' }});
        _syncAuditChip({{ status: 'running', done: 5, total: 19 }});
        _syncAuditChip({{ status: 'done', done: 19, total: 19, results: [{{ result: 'fail' }}] }});
        console.log(JSON.stringify({{ calls, toasts }}));
    """)
    assert [c["id"] for c in out["calls"]] == ["memory-modal"] * 3
    assert {c["work"]["key"] for c in out["calls"]} == {"skills-audit"}
    assert out["calls"][0]["work"]["label"] == "Auditing 4/19"
    assert "summarise-pdf" in out["calls"][0]["work"]["detail"]
    # The finished audit clears its chip rather than leaving furniture, and
    # says the outcome once.
    assert out["calls"][2]["work"].get("label") in (None, "")
    assert out["toasts"] == ["Skills audit finished — 1 of 19 need work"]


def test_the_mailbox_chip_appears_only_when_the_server_says_it_stopped_calling(tmp_path):
    """`_syncMailboxWorkChip`, run for real against the shipped throttle
    vocabulary. A healthy mailbox must get no chip — a chip that is always
    there is furniture — and a paused one must say so and say when."""
    shutil.copy(JS / "runStatus.js", tmp_path / "runStatus.js")
    body = js_function(EMAIL_JS.read_text(encoding="utf-8"), "function _syncMailboxWorkChip")
    out = _call_js(tmp_path, f"""
        import {{ isThrottledSource, throttleNotice, clearsInLabel }} from './runStatus.js';
        const calls = [];
        let opened = 0;
        const Modals = {{ setBackgroundWork: (id, w) => {{ calls.push({{ id, w }}); return true; }} }};
        const openEmailLibrary = () => {{ opened += 1; }};
        function _syncMailboxWorkChip(sync) {body}
        _syncMailboxWorkChip({{ source: 'imap', unread_count: 0 }});
        _syncMailboxWorkChip({{ source: 'unavailable', retry_in: 240, detail: 'password rejected' }});
        _syncMailboxWorkChip({{ source: 'throttled' }});
        const doors = calls.filter(c => c.w && typeof c.w.open === 'function');
        doors.forEach(c => c.w.open());
        console.log(JSON.stringify({{
          calls: calls.map(c => ({{ id: c.id, key: c.w.key, label: c.w.label || null, detail: c.w.detail || null }})),
          opened,
        }}));
    """)
    healthy, paused, no_countdown = out["calls"]
    assert healthy == {"id": "email-lib-modal", "key": "mailbox-sync", "label": None, "detail": None}
    assert paused["label"] == "Mail paused in 4 min"
    assert "paused" in paused["detail"] and "password rejected" in paused["detail"]
    # No `Retry-After` is the common case and it must not fabricate a countdown.
    assert no_countdown["label"] == "Mail paused"
    assert out["opened"] == 2, "every paused chip carries a door"


def test_the_sixty_second_poll_puts_the_quiet_mailbox_on_the_dock():
    """End to end through the door `emailInbox.js` calls, on the shared
    `P15-11` harness rather than a second one (`Law 14`): the real
    `noteMailboxSync`, the real `_setEmailSyncStatus`, and the real
    `runStatus.js` vocabulary, driven by the payload the server sends.

    This is the assertion the extracted-function test above cannot make — that
    the poll's own entry point reaches the chip at all."""
    harness = ROOT / "tests" / "harness" / "email_sync_throttle.js"
    proc = subprocess.run(
        ["node", str(harness), "poll", json.dumps({
            "updated_at": "2026-09-18T11:00:00Z",
            "polls": [{"source": "unavailable", "retry_in": 240, "detail": "password rejected"}],
        })],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["chip"]["id"] == "email-lib-modal"
    assert out["chip"]["work"]["label"] == "Mail paused in 4 min"
    # And the line inside the window still says what `P15-11` made it say.
    assert "paused" in out["line"]


def test_research_counts_the_jobs_and_names_the_one_question(tmp_path):
    """Research is the only one of the five that can have several running, so
    its chip is the case where a single label cannot be one job's words."""
    body = js_function(RESEARCH_JOBS_JS.read_text(encoding="utf-8"), "function _syncResearchChip")
    out = _call_js(tmp_path, f"""
        const calls = [];
        function setBackgroundWork(id, work) {{ calls.push({{ id, work }}); return true; }}
        let _jobs = [];
        function _syncResearchChip() {body}
        _jobs = [{{ status: 'running', query: 'who owns the seabed' }}];
        _syncResearchChip();
        _jobs = [{{ status: 'running', query: 'who owns the seabed' }},
                 {{ status: 'running', query: 'b' }}, {{ status: 'queued', query: 'c' }}];
        _syncResearchChip();
        _jobs = [{{ status: 'done', query: 'a' }}];
        _syncResearchChip();
        console.log(JSON.stringify({{ calls }}));
    """)
    one, many, none = out["calls"]
    assert one["work"]["label"] == "Researching"
    assert "who owns the seabed" in one["work"]["detail"]
    assert many["work"]["label"] == "2 running · 1 queued"
    assert none["work"] is None


def test_the_memory_tidy_puts_itself_on_the_dock_and_takes_itself_off():
    """`tidyMemories` is 70 lines with four exits, one of which is an early
    `return` for "Already clean". `Law 20` option 2: the scope is resolved
    first, so this cannot be satisfied by the string appearing in some other
    function in a 1,800-line module."""
    body = js_function(MEMORY_JS.read_text(encoding="utf-8"), "export async function tidyMemories")
    assert "setBackgroundWork('memory-modal'" in body
    # Keyed, because the Brain also hosts the skills audit.
    assert "key: 'memory-tidy'" in body
    # And cleared in `finally`, which is the only exit every path shares.
    tail = body[body.index("} finally {"):]
    assert "setBackgroundWork('memory-modal', { key: 'memory-tidy' })" in tail


# ── the two that already reported, measured rather than assumed ─────────────

def test_the_forge_already_reports_from_outside_its_own_window():
    """The row says all five are invisible. This one is not, and the fix for it
    is therefore not to add a second indicator."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    btn = html[html.index('id="tool-cookbook-btn"'):]
    btn = btn[:btn.index("</button>")]
    assert 'id="cookbook-bg-status"' in btn, "the Forge's live status is on its sidebar button"
    src = (JS / "cookbookRunning.js").read_text(encoding="utf-8")
    poll = js_function(src, "async function _pollBackgroundStatus")
    assert "cookbook-bg-status" in poll
    assert "downloading" in poll


def test_research_already_lights_its_rail_from_outside_its_own_window():
    src = (JS / "research" / "panel.js").read_text(encoding="utf-8")
    rail = js_function(src, "function _syncResearchRail")
    assert "rail-research" in rail and "research-sb-running" in rail
