# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B813` — one function says a job is running; the dock chip, the rail dot and
the sidebar text are three drawings of that answer.

`P9-11` gave the product `modalManager.setBackgroundWork` and put the skills
audit, the memory tidy, research and the mailbox on the dock with it. The two
tools that had built their own indicator first kept computing *is something
running* for themselves beside it: the Forge's `_showCookbookNotif` and its poll
wrote `#cookbook-bg-status` and the rail, and Research's `_syncResearchRail`
counted the jobs again and set `window._researchJobsActive`, a flag
`sessions.js` ORed with so one re-render did not erase the other's dot.

Decided under the owner's blanket authority, option (b): running work is the
store's, and the store gains a change subscription (`onBackgroundWork`) that
the Forge's and Research's doors draw from; a job that *finished* or *failed*
stays with each tool, so `P9-11`'s rule — a work chip has no `×` and leaves
when its job ends — holds; `window._researchJobsActive` goes; a chat
researching in place lights the rail and gets no dock chip, because it has no
window to own one.

Driven in node on the real `modalManager.js` (the `P9-11` sandbox), with the
real bodies of the functions involved lifted out of the shipped modules —
`jobs.js:_syncResearchChip`, `panel.js:init` and `_syncResearchRail`, the
`sessions.js` research door, and the Forge's door in `cookbookRunning.js`.
"""
import re
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition, js_function
from tests.helpers.source_text import blank_text
from test_background_work_dock_js import _SHIM, _STUBS, MODALS_JS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

import shutil

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
PANEL = (JS / "research" / "panel.js").read_text(encoding="utf-8")
JOBS = (JS / "research" / "jobs.js").read_text(encoding="utf-8")
SESSIONS = (JS / "sessions.js").read_text(encoding="utf-8")
FORGE = (JS / "cookbookRunning.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _whole(source: str, signature: str) -> str:
    """One declaration as it ships, `export` dropped so it can sit in a case."""
    return js_definition(source, source.index(signature))


def _top_level_statement(source: str, opening: str) -> str:
    """A statement the module runs at its top level, starting `opening`."""
    m = re.search(rf"^{re.escape(opening)}.*?;$", source, re.M)
    assert m, f"no top-level `{opening}` statement"
    return m.group(0)


_PREAMBLE = (
    "import { document, Node, click, readDock } from './shim.js';\n"
    "import { installHtmlParsing } from './dom.js';\n"
    "import * as Modals from './modalManager.js';\n"
    "installHtmlParsing();\n"
    "const { setBackgroundWork, getBackgroundWork, onBackgroundWork } = Modals;\n"
    "function el(tag, id) { const n = document.createElement(tag); n.setAttribute('id', id);"
    " document.body.appendChild(n); return n; }\n"
    "const chipsOf = (id) => (readDock() || []).filter(c => c.id === id).map(c => c.state);\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("b813"), MODALS_JS, _SHIM, _STUBS)


def _classes_js():
    # The shim's classList keeps its set privately; read it through `contains`
    # over the names the doors write, so the case does not depend on that.
    return """
    const NAMES = ['rail-notify', 'rail-notify-success', 'rail-notify-error',
                   'research-notif-active', 'cookbook-notif-active'];
    const lit = (id) => NAMES.filter(n => document.getElementById(id).classList.contains(n)).sort();
    """


# ── the store says when it changed ──────────────────────────────────────────

def test_the_store_tells_its_doors_once_per_change(sandbox):
    out = _run(sandbox, _PREAMBLE, """
        const heard = [];
        const off = onBackgroundWork((id) => heard.push([id, getBackgroundWork(id) && getBackgroundWork(id).label]));
        setBackgroundWork('research-overlay', { label: 'Researching', detail: 'q' });
        setBackgroundWork('research-overlay', { label: 'Researching', detail: 'q' });   // a repeat
        setBackgroundWork('research-overlay', null);
        off();
        setBackgroundWork('research-overlay', { label: 'Researching', detail: 'q' });  // nobody listening
        setBackgroundWork('research-overlay', null);
        console.log(JSON.stringify({ heard }));
    """)
    assert out["heard"] == [["research-overlay", "Researching"], ["research-overlay", None]]


def test_a_door_that_throws_does_not_stop_the_others(sandbox):
    out = _run(sandbox, _PREAMBLE, """
        const heard = [];
        const realWarn = console.warn; console.warn = () => {};
        onBackgroundWork(() => { throw new Error('boom'); });
        onBackgroundWork((id) => heard.push(id));
        setBackgroundWork('cookbook-modal', { key: 'forge-tasks', label: 'cooking' });
        console.warn = realWarn;
        console.log(JSON.stringify({ heard, chip: readDock().map(c => c.state) }));
    """)
    assert out == {"heard": ["cookbook-modal"], "chip": ["cooking"]}


# ── Research ────────────────────────────────────────────────────────────────

def _research_case(body: str) -> str:
    """The research door as the app wires it: the panel's real `init`,
    `_syncResearchRail` and the jobs module's `_syncResearchChip`, and the
    sessions module's real research door."""
    parts = [
        _classes_js(),
        "el('button', 'rail-research'); el('button', 'tool-research-btn');",
        "let _jobs = [];",
        # jobs.js, as its `_notify` reaches it on every job-state change.
        _whole(JOBS, "function _syncResearchChip("),
        # sessions.js: the in-chat set, its door and its rail hub.
        "const _researchingSessions = new Set(); const _completedSessions = new Set();",
        _whole(SESSIONS, "let _researchDoor = null;").split("\n")[0],
        _whole(SESSIONS, "function setResearchDoor("),
        _whole(SESSIONS, "function researchingInChat("),
        _whole(SESSIONS, "function _updateRailNotifs("),
        "const sessionModule = { researchingInChat, setResearchDoor };",
        # panel.js: its state, the door, and `init` exactly as it ships.
        "let _apiBase, _markdownModule, _sessionModule, _open = false;",
        "let _orbitSpeedDegPerSec = 22; function _ensureOrbit() {}",
        "function _showBadge() {}",
        "const jobs = { init() {}, setRenderCallback() {}, onComplete() {}, getJobs: () => _jobs };",
        _whole(PANEL, "function _syncResearchRail("),
        "function _renderJobs() { _syncResearchRail(); }",
        _whole(PANEL, "function init(").replace("export ", "", 1),
        "init('', null, sessionModule);",
        "const sidebar = () => { const w = document.getElementById('tool-research-btn').querySelector('.research-sb-running');"
        " return w ? w.querySelector('.research-sb-status').textContent : null; };",
        "const look = () => ({ chip: chipsOf('research-overlay'),"
        " rail: lit('rail-research'), sidebar: sidebar() });",
        body,
    ]
    return "\n".join(parts)


def test_starting_and_ending_a_research_job_is_one_call_drawn_three_times(sandbox):
    """The row's `Verify:`. Nothing calls the rail: the jobs module says what
    is running, once, and the chip, the rail and the sidebar follow."""
    out = _run(sandbox, _PREAMBLE, _research_case("""
        const idle = look();
        _jobs = [{ status: 'running', query: 'who owns the seabed', progress: { round: 2 } }];
        _syncResearchChip();
        const running = look();
        _jobs = [{ status: 'done', query: 'who owns the seabed' }];
        _syncResearchChip();
        const ended = look();
        console.log(JSON.stringify({ idle, running, ended }));
    """))
    assert out["idle"] == {"chip": [], "rail": [], "sidebar": None}
    assert out["running"] == {
        "chip": ["Researching"],
        "rail": ["rail-notify", "rail-notify-success", "research-notif-active"],
        "sidebar": "R2",
    }
    assert out["ended"] == {"chip": [], "rail": [], "sidebar": None}


def test_a_chat_researching_in_place_lights_the_rail_and_gets_no_chip(sandbox):
    """And the two do not erase each other — the case the global flag was for:
    a chat re-rendering its rail while the panel's job runs, and the panel's
    job ending while a chat is still researching."""
    out = _run(sandbox, _PREAMBLE, _research_case("""
        _researchingSessions.add('s1'); _updateRailNotifs();
        const inChat = look();
        _jobs = [{ status: 'running', query: 'q' }]; _syncResearchChip();
        _researchingSessions.delete('s1'); _updateRailNotifs();
        const panelOnly = look();
        _researchingSessions.add('s1'); _updateRailNotifs();
        _jobs = []; _syncResearchChip();
        const chatOutlivesPanel = look();
        console.log(JSON.stringify({ inChat, panelOnly, chatOutlivesPanel,
                                     flag: Object.prototype.hasOwnProperty.call(globalThis, '_researchJobsActive') }));
    """))
    assert out["inChat"] == {"chip": [], "rail": ["rail-notify"], "sidebar": None}
    assert out["panelOnly"]["chip"] == ["Researching"]
    assert "rail-notify-success" in out["panelOnly"]["rail"]
    assert out["chatOutlivesPanel"] == {"chip": [], "rail": ["rail-notify"], "sidebar": None}
    assert out["flag"] is False


def test_a_failed_research_job_stays_with_research_and_off_the_dock(sandbox):
    """Option (b): failed is not running work. It reds the rail and puts no
    chip on the dock, where a chip with no `×` would sit until dismissed."""
    out = _run(sandbox, _PREAMBLE, _research_case("""
        _jobs = [{ status: 'error', query: 'q' }];
        _syncResearchChip(); _renderJobs();
        console.log(JSON.stringify(look()));
    """))
    assert out == {"chip": [], "rail": ["rail-notify", "rail-notify-error", "research-notif-active"],
                   "sidebar": None}


def test_no_module_keeps_the_research_flag():
    """`window._researchJobsActive` is gone from the code (comments that name
    what it was are prose, and are blanked first)."""
    found = [p.relative_to(ROOT).as_posix() for p in sorted(JS.rglob("*.js"))
             if "_researchJobsActive" in blank_text(p.read_text(encoding="utf-8"))]
    assert found == []


# ── the Forge ───────────────────────────────────────────────────────────────

def _forge_case(body: str) -> str:
    parts = [
        _classes_js(),
        "el('button', 'rail-cookbook');",
        "const btn = el('button', 'tool-cookbook-btn');",
        "const statusEl = document.createElement('span'); statusEl.setAttribute('id', 'cookbook-bg-status');"
        " btn.appendChild(statusEl);",
        "const dot = document.createElement('span'); dot.setAttribute('id', 'cookbook-notif-dot');"
        " btn.appendChild(dot);",
        _whole(FORGE, "function _downloadBadgeText("),
        _whole(FORGE, "const FORGE_WINDOW ="),
        _whole(FORGE, "const FORGE_JOB ="),
        "let _forgeOutcome = null; let _forgeOutcomeWord = null;",
        _whole(FORGE, "function _renderForgeDoor("),
        _whole(FORGE, "function _forgeTaskWords("),
        _whole(FORGE, "function _publishForgeWork("),
        _whole(FORGE, "function _showCookbookNotif("),
        _whole(FORGE, "function _clearCookbookNotif(").replace("export ", "", 1),
        # The module's own top-level subscription, as it ships.
        _top_level_statement(FORGE, "onBackgroundWork("),
        "const look = () => ({ chip: chipsOf('cookbook-modal'),"
        " rail: lit('rail-cookbook'), text: statusEl.style.display === 'none' ? null : statusEl.textContent,"
        " dot: dot.style.display !== 'none' });",
        body,
    ]
    return "\n".join(parts)


def test_a_forge_download_is_one_call_drawn_three_times(sandbox):
    out = _run(sandbox, _PREAMBLE, _forge_case("""
        statusEl.style.display = 'none'; dot.style.display = 'none';
        _publishForgeWork([{ type: 'download', progress: '62%', model: 'Qwen3-8B', session_id: 's1', status: 'running' }]);
        const running = look();
        const title = readDock()[0].title;
        _publishForgeWork([]);
        const ended = look();
        console.log(JSON.stringify({ running, title, ended }));
    """))
    assert out["running"] == {"chip": ["downloading 62%"],
                              "rail": ["cookbook-notif-active", "rail-notify", "rail-notify-success"],
                              "text": "downloading 62%", "dot": True}
    assert out["title"] == "Qwen3-8B: downloading 62%"
    assert out["ended"] == {"chip": [], "rail": [], "text": None, "dot": False}


def test_a_failed_forge_task_stays_with_the_forge_and_off_the_dock(sandbox):
    out = _run(sandbox, _PREAMBLE, _forge_case("""
        _forgeOutcomeWord = 'error';
        _showCookbookNotif(true);
        const failed = look();
        _forgeOutcomeWord = null; _clearCookbookNotif();
        console.log(JSON.stringify({ failed, cleared: look() }));
    """))
    assert out["failed"] == {"chip": [], "rail": ["cookbook-notif-active", "rail-notify", "rail-notify-error"],
                             "text": "error", "dot": True}
    assert out["cleared"] == {"chip": [], "rail": [], "text": None, "dot": False}


def test_the_forge_poll_says_running_work_to_the_store_and_draws_nothing_itself():
    """`_pollBackgroundStatus` is 300 lines of server reconciliation; the part
    `B813` changed is that it hands running work to `_publishForgeWork` and no
    longer writes the sidebar text it used to compute beside the chip."""
    poll = js_function(FORGE, "async function _pollBackgroundStatus")
    code = blank_text(poll)
    assert "_publishForgeWork(activeTasks)" in code
    assert "cookbook-bg-status" not in code and "rail-cookbook" not in code


def test_the_research_panel_subscribes_and_hands_sessions_its_door():
    """Scoped to `init` (`Law 20` option 2) — the two lines that make the
    cases above the app's wiring rather than this file's."""
    init = blank_text(js_function(PANEL, "export function init"))
    assert "onBackgroundWork(" in init and "setResearchDoor(_syncResearchRail)" in init
    module = re.search(r"const sessionModule = \{(.*?)\};", SESSIONS, re.S).group(1)
    assert "researchingInChat" in module and "setResearchDoor" in module
