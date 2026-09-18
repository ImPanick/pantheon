# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-07` / `P9-08` — the one empty state, and the three states it tells apart.

Driven under node against the real modules, in the sandbox pattern
`tests/test_chat_steer_js.py` established and `tests/test_tool_effect_surfaces_js.py`
owns. The shim, the sandbox builder and the runner are imported from that file
rather than copied — one harness, one place it can be fixed (`Law 14`).

**The row's premise, re-measured 2026-09-18.** `P9-07` was filed saying no empty
state existed anywhere, corrected in 2026-08-27 to *"wrong by about fifty-four —
~54 sites across 20 class names, a shared helper at `ui.js:833`"*. The
correction is closer than the original and still wrong in three ways:

  * **25 class names, not 20; 70 textual occurrences, not ~54**, across 17
    files. Scope, because a number without one is not a number (`Law 5`):
    `class="…"` attributes and `classList.add()` calls in `static/**/*.js`
    outside `static/lib/**`, plus `static/*.html`;
  * **there is no shared helper at `ui.js:833`.** That line is inside
    `styledPrompt`. The only empty-state export in the file is
    `emptyStateIcon(kind)` — now at `ui.js:957` — and it returns **an SVG icon
    string**. It has no title, no message and no action, and each of its five
    callers hand-writes its own wrapper span. It could not be "the one shape"
    because it is not a shape;
  * **`calendar.js:827-855` is now `calendar.js:834-857`**, and the row is right
    that `_renderEmpty` there is the good example — icon, title, message,
    actions, and a separate error variant. It is what `renderEmptyState` is
    modelled on.

So the defect is not coverage. It is that the states a list can be in were drawn
with one sentence, and a person could not tell which one they were looking at —
`Law 15`, exactly: *can someone who has never seen this surface tell what state
it is in and what to do next?*

**Why the Library modal is the surface under test.** Its four tabs answer the
same question four ways, side by side, so the inconsistency is visible without
being told about it:

  * **Documents** was the only tab that told *nothing yet* from *nothing
    matched*. It is the model, not the exception;
  * **Chats** said *"No chats"* whether you had none or had typed a query that
    matched none;
  * **Archive** said *"No archived items"* **when every one of its three fetches
    had failed**. Each carried its own `.catch(() => ({}))`, so none could
    reject, so the outer `.catch` was unreachable and its *"Failed to load"*
    branch was dead code. A person whose server was down was told their archive
    was empty;
  * **Research** drew both its empty state and its error in `.hwfit-loading` —
    the *loading* class — so a failure read as "still working".

**What is pinned below, and why each is a defect if it breaks:**

  * **the three states are distinguishable from the screen alone.** Not by class
    name — by the words, and by whether there is a way out;
  * **an unknown `kind` fails to `error`, never to `empty`.** Drawing "nothing
    here yet" over a failure is the lie the row exists to end, so the default
    must be the honest end of the range;
  * **the server's own words survive to the screen**, as text and never as
    markup;
  * **a filtered state offers to clear the filter, and clearing it works** — a
    state that explains itself and leaves you to find the box is half a fix;
  * **the archive's three sources are reported individually**, so one failing
    does not blank the other two and three failing is not drawn as "empty";
  * **no new `var(--accent…)` site.** `tests/test_accent_fallback_semantics_css.py`
    pins `static/style.css` at 814 uses so a new one has to be a decision.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from test_a_draft_skill_is_uncatalogued_not_inactive import js_function  # noqa: E402
from test_tool_effect_surfaces_js import _DOM, _make_sandbox, _run  # noqa: E402
from tests.helpers.source_text import blank_text  # B290

ROOT = Path(__file__).resolve().parents[1]
UI_JS = ROOT / "static" / "js" / "ui.js"
DOCLIB_JS = ROOT / "static" / "js" / "documentLibrary.js"
STYLE = ROOT / "static" / "style.css"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

KINDS = ("empty", "filtered", "error")


# ── sandbox ─────────────────────────────────────────────────────────────────

_STUBS = {
    "theme.js": "export default { applyColors(){}, current(){ return 'dark'; } };\n",
    "modalManager.js": "export function register(){}\nexport function open(){}\nexport function close(){}\n",
    "spinner.js": (
        "export function createLoadingRow(text){ const n = document.createElement('div');"
        " n.className = 'lib-loading-row'; n.textContent = text || 'Loading'; return n; }\n"
        "export function createWhirlpool(){ return { element: document.createElement('div'),"
        " stop(){}, destroy(){} }; }\n"
        "export default { createLoadingRow, createWhirlpool };\n"
    ),
    "escMenuStack.js": (
        "export function registerMenuDismiss(){ return () => {}; }\n"
        "export function dismissTopMenu(){}\nexport function dismissOrRemove(){}\n"
    ),
    "toolWindowZOrder.js": (
        "export function nextToolWindowZ(){ return 1; }\n"
        "export function topToolWindowZ(){ return 1; }\nexport function topPortalZ(){ return 1; }\n"
    ),
    "motion.js": "export function prefersReducedMotion(){ return false; }\n",
}

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

// `ui.js` wires page-level behaviour at module load — a `MutationObserver` over
// the toast host, a media query for the pointer type, and a rAF for the smooth
// scroll. The shared DOM shim does not carry those, and a module that throws on
// a missing browser global fails on the global rather than on the assertion,
// which is the wrong way round (`_copy_unstubbed_imports`' own argument).
globalThis.MutationObserver = class { observe(){} disconnect(){} takeRecords(){ return []; } };
globalThis.ResizeObserver = class { observe(){} unobserve(){} disconnect(){} };
globalThis.matchMedia = () => ({
  matches: false, media: '', addEventListener(){}, removeEventListener(){},
  addListener(){}, removeListener(){},
});
globalThis.requestAnimationFrame = (fn) => setTimeout(() => fn(0), 0);
globalThis.cancelAnimationFrame = (id) => clearTimeout(id);
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.innerWidth = 1280;
globalThis.innerHeight = 800;

// `ui.js`'s `_initScrollDismiss` binds to `#chat-history`, and when the element
// is absent it re-arms itself on a 500ms timer — its own comment says "retry
// once", and it is unbounded (filed as `B733`). Under node that is a refed
// handle that never settles and the case hangs rather than failing. The page
// always has this element, so the shim does too.
document.body.appendChild(new Node('div')).setAttribute('id', 'chat-history');

/** A fresh container to draw into, as a tab's grid would be. */
export function host(id) {
  const n = document.body.appendChild(new Node('div'));
  n.setAttribute('id', id || 'grid');
  return n;
}

export function fire(node, type) {
  node.dispatchEvent({ type, stopPropagation() {}, preventDefault() {} });
}

/**
 * What a person sees, read off the screen rather than out of the source.
 *
 * `kind` comes from the data attribute rather than the class list on purpose:
 * the caller's own class rides along on the same element, so a test that read
 * the class could not tell the shared shape from the caller's legacy name.
 */
export function readState(box) {
  if (!box) return null;
  const text = (sel) => { const n = box.querySelector(sel); return n ? n.textContent : null; };
  return {
    kind: box.dataset.emptyState || null,
    classes: String(box.className || '').split(/\s+/).filter(Boolean),
    role: box.getAttribute('role'),
    title: text('.empty-state-title'),
    message: text('.empty-state-message'),
    reason: text('.empty-state-reason'),
    // Raw `_html`: '' if and only if the renderer used `textContent`.
    reasonHtml: (() => { const n = box.querySelector('.empty-state-reason'); return n ? n._html : null; })(),
    icon: !!box.querySelector('.empty-state-icon'),
    actions: box.querySelectorAll('.empty-state-action').map(b => b.textContent),
    readable: box.readable,
  };
}

/** Click the action with this label. Returns false when there is none. */
export function clickAction(box, label) {
  const button = box.querySelectorAll('.empty-state-action').find(b => b.textContent === label);
  if (!button) return false;
  fire(button, 'click');
  return true;
}

export function tick(n = 8) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
"""

_PREAMBLE = (
    "import { document, Node, host, fire, readState, clickAction, tick } from './shim.js';\n"
    "import uiModule, { renderEmptyState, EMPTY_STATE_KINDS } from './ui.js';\n"
)


@pytest.fixture(scope="module")
def ui_sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("emptystates"), UI_JS, _SHIM, _STUBS)


def _ui(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


# ── P9-07 · the three states, told apart from the screen alone ──────────────

def test_the_helper_is_exported_and_offers_exactly_three_states(ui_sandbox):
    """Three, because a list can be in three situations with three different
    answers. A fourth would be a state nobody wrote copy for; a missing one is
    the state that gets drawn as one of the others, which is the defect."""
    out = _ui(ui_sandbox, """
        console.log(JSON.stringify({
          kinds: EMPTY_STATE_KINDS,
          onDefault: typeof uiModule.renderEmptyState,
          named: typeof renderEmptyState,
        }));
    """)
    assert out["kinds"] == list(KINDS)
    assert out["onDefault"] == "function", (
        "82 sites import ui.js as a default object; a named-only export is "
        "reachable by none of them"
    )
    assert out["named"] == "function"


def test_each_state_says_which_one_it_is_without_naming_a_class(ui_sandbox):
    """`Law 15`. The screen has to carry the distinction; a class name is not on
    screen. A mutation that draws all three identically dies here."""
    out = _ui(ui_sandbox, """
        const seen = {};
        for (const kind of EMPTY_STATE_KINDS) {
          seen[kind] = readState(renderEmptyState(host('h-' + kind), { kind }));
        }
        console.log(JSON.stringify(seen));
    """)
    titles = {k: out[k]["title"] for k in KINDS}
    assert len(set(titles.values())) == 3, f"the three states read the same: {titles}"
    for kind in KINDS:
        assert out[kind]["kind"] == kind
        assert out[kind]["title"], f"{kind} drew no title"
        assert f"empty-state-{kind}" in out[kind]["classes"]
        assert "empty-state" in out[kind]["classes"]
    # The error is the only one that is news; the other two describe a list the
    # reader is already looking at.
    assert out["error"]["role"] == "alert"
    assert out["empty"]["role"] == "status"
    assert out["filtered"]["role"] == "status"


def test_an_unknown_state_fails_to_error_and_never_to_empty(ui_sandbox):
    """The whole row in one assertion. A caller bug must not put "nothing here
    yet" over a failure — that is the lie, and it is the failure mode that
    cannot be seen from a screenshot."""
    out = _ui(ui_sandbox, """
        const got = {};
        for (const bad of ['', 'loading', 'EMPTY ', null, undefined, 'unknown']) {
          got[String(bad)] = readState(renderEmptyState(host('h'), { kind: bad })).kind;
        }
        // A correctly-spelled kind in the wrong case is still that kind.
        got['UPPER'] = readState(renderEmptyState(host('h2'), { kind: 'FILTERED' })).kind;
        console.log(JSON.stringify(got));
    """)
    for spelling in ("", "loading", "null", "undefined", "unknown"):
        assert out[spelling] == "error", f"{spelling!r} fell back to {out[spelling]!r}"
    assert out["EMPTY "] == "empty", "a recognised kind with stray whitespace must still land"
    assert out["UPPER"] == "filtered"


def test_the_callers_own_class_rides_along_so_no_class_name_has_to_move(ui_sandbox):
    """`Law 14` and `Law 2` together: 25 class names already carry CSS, and the
    consolidation is a shared *shape*, not a rename. A helper that replaced the
    caller's class would silently restyle 70 sites."""
    out = _ui(ui_sandbox, """
        console.log(JSON.stringify(readState(renderEmptyState(host('h'), {
          kind: 'empty', className: 'doclib-empty',
        }))));
    """)
    assert "doclib-empty" in out["classes"]
    assert "empty-state" in out["classes"]


def test_a_state_with_no_copy_still_says_which_state_it_is(ui_sandbox):
    """A caller that forgets the words ships a screen that is honest but terse,
    never a blank one. This is the floor, not the target."""
    out = _ui(ui_sandbox, """
        const got = {};
        for (const kind of EMPTY_STATE_KINDS) got[kind] = readState(renderEmptyState(host('h'), { kind })).title;
        console.log(JSON.stringify(got));
    """)
    assert all(out[k] and out[k].strip() for k in KINDS)
    assert len(set(out.values())) == 3


# ── P9-08 · the server's own words, and the way out ─────────────────────────

def test_the_servers_reason_reaches_the_screen_as_text_and_not_as_markup(ui_sandbox):
    """`P9-08`. "Failed to load" is two words a person can neither act on nor
    report. The reason is rendered verbatim — and through `textContent`, so a
    server that echoes a filename with a `<` in it cannot write markup."""
    out = _ui(ui_sandbox, """
        console.log(JSON.stringify(readState(renderEmptyState(host('h'), {
          kind: 'error',
          title: 'Could not load your chats',
          reason: '500 Internal Server Error — <img src=x onerror=1> disk full',
        }))));
    """)
    assert "disk full" in out["reason"]
    assert "500 Internal Server Error" in out["reason"]
    assert out["reasonHtml"] == "", "the reason was assigned as HTML, not as text"


def test_a_reason_is_shown_only_on_the_error_state(ui_sandbox):
    """An empty shelf has no reason to give. Printing one there would invent a
    failure that did not happen."""
    out = _ui(ui_sandbox, """
        const got = {};
        for (const kind of EMPTY_STATE_KINDS) {
          got[kind] = readState(renderEmptyState(host('h'), { kind, reason: 'boom' })).reason;
        }
        console.log(JSON.stringify(got));
    """)
    assert out["error"] == "boom"
    assert out["empty"] is None and out["filtered"] is None


def test_an_error_offers_a_retry_and_the_retry_runs_the_loader_again(ui_sandbox):
    """The other half of `P9-08`. Four of `documentLibrary.js`'s five load paths
    had no way back at all: the only recovery was switching tabs."""
    out = _ui(ui_sandbox, """
        let ran = 0;
        const box = renderEmptyState(host('h'), {
          kind: 'error', title: 'Could not load', onRetry: () => { ran++; },
        });
        const clicked = clickAction(box, 'Try again');
        console.log(JSON.stringify({ clicked, ran, state: readState(box) }));
    """)
    assert out["clicked"] is True
    assert out["ran"] == 1
    assert "Try again" in out["state"]["actions"]


def test_a_retry_is_never_offered_on_a_state_that_is_not_a_failure(ui_sandbox):
    """"Try again" over an empty shelf tells a person something went wrong when
    nothing did — the same class of lie, pointing the other way."""
    out = _ui(ui_sandbox, """
        const got = {};
        for (const kind of EMPTY_STATE_KINDS) {
          got[kind] = readState(renderEmptyState(host('h'), { kind, onRetry: () => {} })).actions;
        }
        console.log(JSON.stringify(got));
    """)
    assert out["error"] == ["Try again"]
    assert out["empty"] == [] and out["filtered"] == []


def test_a_failing_action_does_not_take_the_page_with_it(ui_sandbox):
    """A handler that throws must not leave the click unhandled — the state is
    already the recovery screen, and a thrown error there is a dead end."""
    out = _ui(ui_sandbox, """
        const box = renderEmptyState(host('h'), {
          kind: 'filtered', action: { label: 'Clear filters', onClick: () => { throw new Error('nope'); } },
        });
        let threw = false;
        try { clickAction(box, 'Clear filters'); } catch { threw = true; }
        console.log(JSON.stringify({ threw }));
    """)
    assert out["threw"] is False


# ── P9-07 / P9-08 · the Library's four tabs, driven for real ────────────────
#
# `Law 20` option 1: the function's own body is resolved out of the shipped file
# by brace balance, its free variables are supplied, and it is then CALLED
# against the real `renderEmptyState`. A grep for the string 'filtered' would
# pass on a module that never reaches the branch; this does not.

_CHATS_GRID = """
    let _chatsSessions = __SESSIONS__;
    let _chatsSearch = __SEARCH__;
    let _chatsModelFilter = __FOLDER__;
    let _chatsSort = 'recent';
    let _chatsSelectMode = false;
    let _chatsVisibleLimit = 20;
    const _chatsSelected = new Set();
    let cleared = 0;
    function _chatsClearFilters() { cleared++; }
    function _appendInlineLoadMore() {}
    function _maybeCascadeGrid() {}
    function closeLibrary() {}
    function _toggleChatPreview() {}
    function chevronIcon() { return ''; }
    const _esc = (s) => String(s == null ? '' : s);
    __BODY__
"""


def _chats_case(sandbox, sessions, search="''", folder="''", tail=""):
    body = js_function(DOCLIB_JS.read_text(encoding="utf-8"), "function _renderChatsGrid(")
    script = (
        _CHATS_GRID
        .replace("__SESSIONS__", sessions)
        .replace("__SEARCH__", search)
        .replace("__FOLDER__", folder)
        .replace("__BODY__", "function _renderChatsGrid() " + body)
    )
    return _ui(sandbox, script + """
        const grid = host('doclib-chats-grid');
        _renderChatsGrid();
        const box = grid.querySelector('.empty-state');
    """ + tail + """
        console.log(JSON.stringify({ state: readState(box), cleared }));
    """)


def test_no_chats_and_no_chats_matching_are_no_longer_the_same_sentence(ui_sandbox):
    """The row's `Law 15` case, stated as one comparison. Before this change
    both branches reached `'<div class="doclib-empty">No chats' + sadIcon`, and
    the person with 40 chats and a typo in the search box was told they had
    none."""
    none_yet = _chats_case(ui_sandbox, "[]")
    hidden = _chats_case(
        ui_sandbox,
        "[{id:'a',name:'Ledger rewrite'},{id:'b',name:'Boot times'}]",
        search="'zzzz'",
    )
    assert none_yet["state"]["kind"] == "empty"
    assert hidden["state"]["kind"] == "filtered"
    assert none_yet["state"]["title"] != hidden["state"]["title"]
    # The filtered state has to say the list is not actually empty, and the
    # count is the thing that makes that credible.
    assert "2" in (hidden["state"]["message"] or ""), hidden["state"]["message"]
    assert hidden["state"]["actions"], "a filtered state with no way out is half a fix"


def test_a_folder_chip_alone_counts_as_narrowed(ui_sandbox):
    """The search box is not the only filter on this tab. A version that only
    checked `_chatsSearch` reports "No chats yet" to someone who clicked a
    folder chip, which is the original defect with one extra step."""
    out = _chats_case(
        ui_sandbox,
        "[{id:'a',name:'one',folder:'work'}]",
        folder="'personal'",
    )
    assert out["state"]["kind"] == "filtered"


def test_clearing_the_filter_from_the_empty_state_actually_clears_it(ui_sandbox):
    """The button has to do what its label says. A label with no wiring behind
    it is the shape of defect `Law 13` is named for."""
    out = _chats_case(
        ui_sandbox,
        "[{id:'a',name:'one'}]",
        search="'zzzz'",
        tail="clickAction(box, 'Clear filters');",
    )
    assert out["cleared"] == 1


_ARC_GRID = """
    let _arcSessions = __SESSIONS__;
    let _arcDocs = [];
    let _arcResearch = [];
    let _arcSearch = __SEARCH__;
    let _arcSort = 'recent';
    let _arcSelectMode = false;
    let _arcModelFilter = '';
    let _arcTypeFilter = '';
    let _arcVisibleLimit = 20;
    let _arcLoadFailures = __FAILURES__;
    const _arcSelected = new Set();
    function _arcClearFilters() {}
    function _renderLibArchive() {}
    function _appendInlineLoadMore() {}
    function _maybeCascadeGrid() {}
    function chevronIcon() { return ''; }
    const _esc = (s) => String(s == null ? '' : s);
    __BODY__
"""


def _arc_case(sandbox, sessions="[]", search="''", failures="[]"):
    body = js_function(DOCLIB_JS.read_text(encoding="utf-8"), "function _renderArcGrid(")
    script = (
        _ARC_GRID
        .replace("__SESSIONS__", sessions)
        .replace("__SEARCH__", search)
        .replace("__FAILURES__", failures)
        .replace("__BODY__", "function _renderArcGrid() " + body)
    )
    return _ui(sandbox, script + """
        const grid = host('doclib-arc-grid');
        _renderArcGrid();
        console.log(JSON.stringify({ state: readState(grid.querySelector('.empty-state')) }));
    """)


def test_an_archive_that_failed_to_load_is_not_drawn_as_an_empty_archive(ui_sandbox):
    """The sharpest instance of `P9-08` in the file. Three fetches, three
    private `.catch(() => ({}))`, and therefore an outer `.catch` that could
    never run — so a total server failure rendered as *"No archived items"* and
    told a person their archive was gone."""
    broken = _arc_case(ui_sandbox, failures="['Chats: 500 Internal Server Error']")
    truly_empty = _arc_case(ui_sandbox)
    assert broken["state"]["kind"] == "error"
    assert truly_empty["state"]["kind"] == "empty"
    assert broken["state"]["title"] != truly_empty["state"]["title"]
    assert "500" in (broken["state"]["reason"] or ""), (
        "which source failed, and what it said, is the whole point of the row"
    )


def test_the_archives_three_sources_are_reported_one_by_one(ui_sandbox):
    """One source failing must not blank the other two, and must not pass
    silently either. The loader records a line per source; the grid prints
    them."""
    source = DOCLIB_JS.read_text(encoding="utf-8")
    loader = js_function(source, "function _renderLibArchive(")
    assert "_arcSource('Chats'" in loader
    assert "_arcSource('Documents'" in loader
    assert "_arcSource('Research'" in loader
    # The dead branch is gone: nothing in the loader may swallow a rejection
    # into a bare object without recording it.
    assert ".catch(() => ({}))" not in blank_text(loader), (
        "a per-source catch that records nothing is the unreachable outer "
        "`.catch` all over again"
    )
    out = _arc_case(
        ui_sandbox,
        failures="['Chats: 503 Service Unavailable','Research: 500 Internal Server Error']",
    )
    assert "Chats" in out["state"]["reason"] and "Research" in out["state"]["reason"]


def test_the_error_reader_carries_the_status_and_the_servers_detail(ui_sandbox):
    """`_readError` is what turns "Failed to load" into something reportable.
    Driven against real `Response`-shaped objects rather than asserted on."""
    body = js_function(DOCLIB_JS.read_text(encoding="utf-8"), "async function _readError(")
    out = _ui(ui_sandbox, "async function _readError(res) " + body + """
        const mk = (status, statusText, text) => ({ status, statusText, text: async () => text });
        console.log(JSON.stringify({
          detail: await _readError(mk(500, 'Internal Server Error', '{"detail":"disk full"}')),
          plain: await _readError(mk(502, 'Bad Gateway', 'upstream refused')),
          silent: await _readError(mk(404, 'Not Found', '')),
          unreadable: await _readError({ status: 500, statusText: 'Boom', text: async () => { throw new Error('consumed'); } }),
          long: (await _readError(mk(500, 'x', 'y'.repeat(9000)))).length,
        }));
    """)
    assert "500" in out["detail"] and "disk full" in out["detail"]
    assert "502" in out["plain"] and "upstream refused" in out["plain"]
    assert out["silent"] == "404 Not Found", "the status alone still beats two words"
    assert "500" in out["unreadable"], "an unreadable body must not lose the status"
    assert out["long"] < 500, "a stack trace must not take over the panel"


# ── the theme constraint ────────────────────────────────────────────────────

def test_the_empty_state_adds_no_accent_site_to_the_stylesheet():
    """`tests/test_accent_fallback_semantics_css.py` pins `static/style.css` at
    814 `var(--accent…)` uses so that a new one is a decision rather than a
    habit, and full-strength accent text misses 4.5:1 against `--panel` on seven
    of the sixteen palettes. The three states are separated by a left rule and
    by `currentColor` — the alternative the last three waves used.

    Asserted inside the block rather than file-wide (`Law 20`): the sheet has
    949 occurrences of the string elsewhere, so a file-wide search proves
    nothing about these rules.
    """
    sheet = blank_text(STYLE.read_text(encoding="utf-8"), mode="css")
    start = sheet.index("\n.empty-state {")
    block = sheet[start:]
    assert ".empty-state-error" in block, "the empty-state block moved or was split"
    assert "var(--accent" not in block, (
        "a new accent site here is a new instance of a known defect"
    )
    # And the caller-side conversions removed four of the existing ones.
    for rule in (".empty-state-action", ".empty-state-reason", ".empty-state-title"):
        assert rule in block


def test_a_failed_document_load_is_not_silent():
    """The quietest shape of the same defect, and the fourth in one file.
    `libraryFetch`'s only failure handling was `console.error`, so the Documents
    tab never finished: the loading row (or the previous page of results) stayed
    on screen with no error, no reason and no way to try again.

    A failing *"Load more"* is a different case and is asserted separately —
    blanking rows a person is already reading, to tell them the next page did
    not arrive, replaces information with an apology.
    """
    body = blank_text(js_function(DOCLIB_JS.read_text(encoding="utf-8"),
                                  "async function libraryFetch("))
    catch = body[body.rindex("} catch"):]
    assert "renderEmptyState" in catch, "a failed document load is still silent"
    assert "_readError" in body, "the failure carries no reason from the server"
    assert "onRetry" in catch, "there is no way back"
    assert "if (append)" in catch, (
        "a failed 'Load more' must not blank the rows already on screen"
    )
    assert "showError" in catch


def test_the_library_no_longer_paints_a_finished_state_with_the_loading_class():
    """The Research tab drew both its empty state and its failure in
    `.hwfit-loading`. A loading class over a finished failure is a surface
    telling a person to wait for something that already stopped.

    The class is not banned — the same function's spinner fallback is a genuine
    loading row and keeps it. What is banned is reaching for it in a statement
    that is not about waiting, which is the distinction the defect blurred.
    """
    source = DOCLIB_JS.read_text(encoding="utf-8")
    offenders = []
    for name in ("function _renderResearchGrid(", "async function _renderLibResearch("):
        body = blank_text(js_function(source, name))
        for statement in re.split(r";\n", body):
            if "hwfit-loading" in statement and "Loading" not in statement:
                offenders.append((name, statement.strip()[:160]))
    assert not offenders, (
        "a finished state is still drawn in the loading class: " + repr(offenders)
    )
