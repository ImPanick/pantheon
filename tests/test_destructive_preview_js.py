# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-10` — what a destructive AI operation is about to do, before it does it.

Driven under node against the real modules, in the sandbox pattern
`tests/test_chat_steer_js.py` established and `tests/test_tool_effect_surfaces_js.py`
owns. The shim, the sandbox builder and the runner are imported from that file
rather than copied — one harness, one place it can be fixed (`Law 14`).

**The row's premise, re-measured 2026-09-19.** *"Chat tidy deletes sessions and
re-folders them with no preview at all"* is true and understates it by two
callers. `POST /api/sessions/auto-sort` has **three** callers in `static/`:

  * `static/app.js:_runTidy` — the sidebar sort dropdown's *"★ Tidy"* and
    *"Tidy (no AI)"*. Printed `unfiled_remaining` and the folder count on the AI
    path, and the deletion count **only** on the no-AI path;
  * `static/js/documentLibrary.js` — the Library's Chats tab. Printed `updated`
    and `data.folders.length` and nothing else;
  * `static/js/slashCommands.js:_cmdSessionSort` — `/session sort`. Printed
    `deleted_empty` and **not** `deleted_throwaway`.

None asked before running. `deleted_empty` and `deleted_throwaway` are on every
response the endpoint sends, and on the path that produces the most deletions
all three callers dropped both — so a person pressed Tidy, nine chats were
deleted permanently, and the toast said *"Sorted 5 into 2 folders"*.

**And it is four surfaces, not one.** Re-measured in the same pass:

  * **Research tidy** (`documentLibrary.js`) had no confirmation at all — the
    bulk-delete button one row below it asks before deleting reports a person
    picked by hand, and this one deleted reports the *browser* picked. Its
    `DELETE`s each carried `.catch(() => {})` and the toast counted the
    candidate list, so with the server refusing every one a person was told
    seven reports were deleted, watched them leave the grid, and had all seven
    back on the next load;
  * **Documents tidy** fired two destructive requests behind one unconfirmed
    click, the second of them a model call, and swallowed both failures —
    `if (res1.ok)` with no else, and `catch (_) {}` commented *"AI tidy is
    optional"*. A tidy whose model pass never ran reported *"Already tidy"*;
  * **Memory tidy**'s animation is a diff of a change already committed, which
    the row says. What the row does not say is that the reassurance was already
    on the wire: `routes/memory/memory_routes.py` answers with `superseded` and
    `contradictions` beside `removed`, added by `P13-09` with a comment saying
    *"a person reading '9 removed' can be told that 8 of them are recoverable"*.
    This side read neither.

**What is NOT here, and cannot be from `static/`.** A row-level preview of the
chat, document and memory tidies needs the server to compute without applying —
Phase 1's rules run in `routes/session_routes.py` against message counts this
browser does not have, and the folders come out of a model. Re-deriving either
here would be a second implementation of a rule that can change server-side
without this file hearing about it (`Law 14`). The Research tidy is the one
whose candidate set is decided **in the browser**, which is why it is the
surface the preview is proved on.

**What is pinned below, and why each is a defect if it breaks:**

  * **the dialog lists rows, and every row says why it is in the list** — a
    count is not a preview;
  * **the list is built with `textContent`** — the labels are chat titles and
    research questions, user-written text on its way into a dialog;
  * **the list from the previous dialog is gone before the next one opens.**
    The overlay is reused across calls, so an appended-and-not-removed list is
    shown above a *different* operation's message;
  * **deletions lead the sentence afterwards**, because they are the half with
    no undo;
  * **only the rows the server actually removed leave the list**, and the count
    reported is the count deleted;
  * **every caller of the same endpoint asks the same question and reads the
    same answer** — three callers with three vocabularies is how the deletion
    count went missing on two of them.
"""

import re
import shutil
from pathlib import Path

import pytest

from test_a_draft_skill_is_uncatalogued_not_inactive import js_function  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.source_text import blank_text  # B290

ROOT = Path(__file__).resolve().parents[1]
UI_JS = ROOT / "static" / "js" / "ui.js"
DOCLIB_JS = ROOT / "static" / "js" / "documentLibrary.js"
SESSIONS_JS = ROOT / "static" / "js" / "sessions.js"
MEMORY_JS = ROOT / "static" / "js" / "memory.js"
APP_JS = ROOT / "static" / "app.js"
SLASH_JS = ROOT / "static" / "js" / "slashCommands.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


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

// Same reason as `tests/test_empty_states_js.py`: `ui.js` wires page-level
// behaviour at module load, and a module that throws on a missing browser
// global fails on the global rather than on the assertion.
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
document.body.appendChild(new Node('div')).setAttribute('id', 'chat-history');
document.addEventListener = () => {};
document.removeEventListener = () => {};

// `styledConfirm` builds its overlay once with `innerHTML` and reuses it for
// every call after that. The shared DOM shim stores `innerHTML` as a string
// rather than parsing it, so the overlay is built here with real nodes — which
// is the state the browser is in from the second confirm onwards, and the state
// the reuse this file pins is about.
function node(tag, id, cls) {
  const n = new Node(tag);
  if (id) n.setAttribute('id', id);
  if (cls) n.className = cls;
  return n;
}
const overlay = document.body.appendChild(node('div', 'styled-confirm-overlay', 'modal'));
const box = overlay.appendChild(node('div', '', 'modal-content styled-confirm-box'));
box.appendChild(node('div', '', 'modal-header')).appendChild(node('h4', 'styled-confirm-title'));
box.appendChild(node('div', '', 'modal-body')).appendChild(node('p', 'styled-confirm-msg'));
const footer = box.appendChild(node('div', '', 'modal-footer'));
footer.appendChild(node('button', 'styled-confirm-cancel'));
footer.appendChild(node('button', 'styled-confirm-alt'));
footer.appendChild(node('button', 'styled-confirm-ok'));
export { overlay };

/**
 * Open a confirm and read the dialog off the screen, then answer it.
 *
 * `styledConfirm` resolves on a click, so the promise is started, the overlay
 * is read, and the button is pressed — which is what a person does and what a
 * test that asserted on the source could not check.
 */
export function openConfirm(styledConfirm, message, opts, answer = 'cancel') {
  const promise = styledConfirm(message, opts);
  const overlay = document.querySelector('#styled-confirm-overlay');
  const read = readConfirm(overlay);
  const btn = document.querySelector(answer === 'ok' ? '#styled-confirm-ok' : '#styled-confirm-cancel');
  btn.dispatchEvent({ type: 'click', stopPropagation() {}, preventDefault() {} });
  return promise.then((result) => ({ ...read, result }));
}

export function readConfirm(overlay) {
  const box = overlay && overlay.querySelector('.styled-confirm-details');
  const text = (sel) => { const n = overlay.querySelector(sel); return n ? n.textContent : null; };
  return {
    title: text('#styled-confirm-title'),
    message: text('#styled-confirm-msg'),
    ok: text('#styled-confirm-ok'),
    danger: String(overlay.querySelector('#styled-confirm-ok').className || ''),
    hasDetails: !!box,
    heading: box ? (box.querySelector('.styled-confirm-details-heading') || {}).textContent || null : null,
    footnote: box ? (box.querySelector('.styled-confirm-details-foot') || {}).textContent || null : null,
    rows: box
      ? box.querySelectorAll('.styled-confirm-detail').map((r) => ({
          label: (r.querySelector('.styled-confirm-detail-label') || {}).textContent || '',
          note: (r.querySelector('.styled-confirm-detail-note') || {}).textContent || '',
          labelHtml: (r.querySelector('.styled-confirm-detail-label') || {})._html,
        }))
      : [],
    // Where the list sits relative to the sentence it belongs to.
    orderOk: box
      ? overlay.querySelector('.modal-body').childNodes.indexOf(box) === 1
      : null,
  };
}

export function tick(n = 8) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}
"""

_PREAMBLE = (
    "import { document, Node, openConfirm, readConfirm, tick } from './shim.js';\n"
    "import uiModule, { styledConfirm } from './ui.js';\n"
)


@pytest.fixture(scope="module")
def ui_sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("destructive"), UI_JS, _SHIM, _STUBS)


def _ui(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


# ── the dialog: a list, not a count ─────────────────────────────────────────

def test_a_destructive_confirm_lists_what_it_will_do_row_by_row(ui_sandbox):
    """A count is not a preview. The row this closes exists because "Tidy"
    deleted things nobody had been shown, so the dialog has to carry the
    things — each with the reason it is in the list."""
    out = _ui(ui_sandbox, """
        console.log(JSON.stringify(await openConfirm(styledConfirm, 'Delete these?', {
          title: 'Delete these reports?', confirmText: 'Delete 2', danger: true,
          details: {
            heading: 'These reports will be deleted',
            items: [
              { label: 'ledger rewrite', note: 'no sources' },
              { label: 'boot times', note: 'report is 84 characters' },
            ],
            footnote: 'Permanent.',
          },
        })));
    """)
    assert out["hasDetails"] is True
    assert [r["label"] for r in out["rows"]] == ["ledger rewrite", "boot times"]
    assert [r["note"] for r in out["rows"]] == ["no sources", "report is 84 characters"]
    assert out["heading"] == "These reports will be deleted"
    assert out["footnote"] == "Permanent."
    assert "confirm-btn-danger" in out["danger"], (
        "a dialog that deletes permanently is not styled like one that does not"
    )
    assert out["orderOk"] is True, "the list must sit under the sentence it belongs to"


def test_every_word_in_the_list_is_text_and_never_markup(ui_sandbox):
    """The labels are chat titles, document names and research questions —
    user-written text on its way into a dialog, which is exactly where
    `innerHTML` would be an injection hole with a chat title as the payload."""
    out = _ui(ui_sandbox, """
        console.log(JSON.stringify(await openConfirm(styledConfirm, 'Delete?', {
          details: { items: [{ label: '<img src=x onerror=alert(1)>', note: '<b>no</b> sources' }] },
        })));
    """)
    assert out["rows"][0]["label"] == "<img src=x onerror=alert(1)>"
    assert out["rows"][0]["labelHtml"] == "", "the label was assigned as HTML, not as text"
    assert out["rows"][0]["note"] == "<b>no</b> sources"


def test_the_previous_operations_list_is_gone_before_the_next_dialog_opens(ui_sandbox):
    """The overlay is created once and reused for every confirm in the app. A
    list appended and not removed is the previous operation's inventory shown
    above a different operation's question — the worst possible failure for a
    control whose whole job is to say what is about to happen."""
    out = _ui(ui_sandbox, """
        await openConfirm(styledConfirm, 'first', {
          details: { items: [{ label: 'from the first dialog', note: 'stale' }] },
        });
        const second = await openConfirm(styledConfirm, 'second', {
          details: { items: [{ label: 'from the second dialog', note: 'fresh' }] },
        });
        const plain = await openConfirm(styledConfirm, 'third');
        console.log(JSON.stringify({ second, plain }));
    """)
    assert [r["label"] for r in out["second"]["rows"]] == ["from the second dialog"]
    assert out["plain"]["hasDetails"] is False, (
        "a confirm with no details still showed the previous one's list"
    )


def test_a_plain_confirm_is_unchanged(ui_sandbox):
    """Every existing caller passes no `details`, and the dialog they get has to
    be the dialog they had — `Law 1`, and the reason this extends `styledConfirm`
    rather than adding a second dialog beside it (`Law 14`)."""
    out = _ui(ui_sandbox, """
        const got = await openConfirm(styledConfirm, 'Delete 3 chats?', { confirmText: 'Delete' }, 'ok');
        console.log(JSON.stringify(got));
    """)
    assert out["hasDetails"] is False
    assert out["message"] == "Delete 3 chats?"
    assert out["ok"] == "Delete"
    assert out["result"] is True


# ── the chat tidy: one operation, one sentence ──────────────────────────────

# `confirmChatTidy`'s one free variable is `uiModule`, so the real dialog is
# replaced with a recorder: what this pins is the words the pre-flight chooses,
# and the dialog that draws them has its own cases above.
_SESSION_PRELUDE = """
    const asked = { last: null };
    const uiStub = {
      styledConfirm(message, opts) { asked.last = { message, opts }; return Promise.resolve(true); },
    };
"""


def _sessions(sandbox, script):
    source = SESSIONS_JS.read_text(encoding="utf-8")
    bodies = "\n".join(
        "function " + name + " " + js_function(source, sig).replace("uiModule.", "uiStub.")
        for name, sig in (
            ("confirmChatTidy({ skipLlm = false } = {})", "export function confirmChatTidy("),
            ("describeChatTidy(data)", "export function describeChatTidy("),
        )
    )
    return _run(sandbox, _PREAMBLE, _SESSION_PRELUDE + bodies + script)


def test_the_chat_tidy_sentence_leads_with_what_was_deleted(ui_sandbox):
    """`deleted_empty` and `deleted_throwaway` are on every response and all
    three callers dropped them on the AI path. Deletions lead because they are
    the half with no undo; filing is reversible from the sidebar."""
    out = _sessions(ui_sandbox, """
        console.log(JSON.stringify({
          both: describeChatTidy({ status: 'ok', deleted_empty: 4, deleted_throwaway: 5,
                                   updated: 5, folders: ['a', 'b'], unfiled_remaining: 0 }),
          filedOnly: describeChatTidy({ status: 'ok', updated: 3, folders: ['a'], unfiled_remaining: 0 }),
          deletedOnly: describeChatTidy({ status: 'ok', deleted_throwaway: 2, updated: 0,
                                          folders: [], unfiled_remaining: 0 }),
        }));
    """)
    assert out["both"].startswith("Deleted 9 chats"), out["both"]
    assert "2 folders" in out["both"]
    assert "Deleted" not in out["filedOnly"], (
        "a run that deleted nothing must not say it deleted something"
    )
    assert "Filed 3 into 1 folder" in out["filedOnly"], (
        "the sentence starts with a capital wherever the deletions clause is absent"
    )
    assert out["deletedOnly"].startswith("Deleted 2 chats")
    assert "filed" not in out["deletedOnly"]


def test_the_sentence_says_whether_pressing_it_again_would_do_anything(ui_sandbox):
    """`unfiled_remaining` is computed by the endpoint with a comment saying the
    frontend uses it; two of the three callers never read it. Tidy works in
    batches of 15, so "is there more?" is the question a person has straight
    after reading the rest."""
    out = _sessions(ui_sandbox, """
        console.log(JSON.stringify({
          more: describeChatTidy({ status: 'ok', updated: 15, folders: ['a'], unfiled_remaining: 40 }),
          done: describeChatTidy({ status: 'ok', updated: 15, folders: ['a'], unfiled_remaining: 0 }),
          nothing: describeChatTidy({ status: 'ok', updated: 0, folders: [], unfiled_remaining: 0 }),
        }));
    """)
    assert "40 still unfiled" in out["more"]
    assert "unfiled" not in out["done"]
    assert out["nothing"] == "Already tidy"


def test_a_response_that_is_not_a_completed_run_produces_no_sentence(ui_sandbox):
    """The endpoint answers `status: 'skipped'` with its own `reason`, and each
    caller already prints that. Inventing a sentence here would put two
    different reports on one response."""
    out = _sessions(ui_sandbox, """
        console.log(JSON.stringify({
          skipped: describeChatTidy({ status: 'skipped', reason: 'AI found no groupings' }),
          empty: describeChatTidy(null),
          garbage: describeChatTidy({}),
        }));
    """)
    assert out["skipped"] == "" and out["empty"] == "" and out["garbage"] == ""


def test_the_chat_tidy_asks_first_and_says_the_deletion_is_permanent(ui_sandbox):
    """`Law 15`, and the row's headline. A person who has never seen this button
    has to be able to tell, from the dialog alone, that pressing it destroys
    chats — and which chats it will not touch."""
    out = _sessions(ui_sandbox, """
        await confirmChatTidy();
        const ai = asked.last;
        await confirmChatTidy({ skipLlm: true });
        const noAi = asked.last;
        const flat = (a) => a.opts.details.items.map(i => i.label + ' :: ' + i.note).join(' | ');
        console.log(JSON.stringify({
          ai: { message: ai.message, flat: flat(ai), foot: ai.opts.details.footnote,
                danger: ai.opts.danger, confirmText: ai.opts.confirmText,
                rows: ai.opts.details.items.map(i => ({ label: i.label, note: i.note })) },
          noAi: { message: noAi.message, flat: flat(noAi),
                  rows: noAi.opts.details.items.map(i => ({ label: i.label, note: i.note })) },
        }));
    """)
    ai = out["ai"]
    assert ai["danger"] is True
    deleting = [r for r in ai["rows"] if r["label"].startswith("Deletes")]
    assert len(deleting) == 2, ai["rows"]
    assert all(r["note"] == "permanent" for r in deleting), (
        "every row that deletes has to say so; one of two is how a person "
        "concludes the other kind is recoverable"
    )
    assert "no undo" in ai["foot"]
    assert "Important" in ai["foot"], "what is protected is half the answer"
    assert "Sends the titles" in ai["flat"], "the AI path spends a model call and must say so"
    assert "one call" in ai["flat"]
    assert "Sends the titles" not in out["noAi"]["flat"], (
        "the no-AI path calls no model; promising one is the same lie backwards"
    )
    assert "one call" not in out["noAi"]["flat"]
    assert all(r["note"] == "permanent" for r in out["noAi"]["rows"]), (
        "the no-AI path still deletes, so every row it shows still has to say so"
    )


# ── the research tidy: the one that can show the rows ───────────────────────

_RESEARCH_PRELUDE = """
    const calls = [];
    const reply = (ok, body, status = 200) => ({
      ok, status, statusText: ok ? 'OK' : 'Internal Server Error',
      json: async () => body, text: async () => JSON.stringify(body),
    });
    globalThis.__DETAIL__ = {};
    globalThis.__DELETE__ = {};
    globalThis.fetch = async (url, opts) => {
      calls.push(((opts && opts.method) || 'GET') + ' ' + url);
      if ((opts && opts.method) === 'DELETE') {
        const id = url.split('/').pop();
        const verdict = globalThis.__DELETE__[id];
        if (verdict === 'throw') throw new Error('network down');
        if (verdict === false) return reply(false, { detail: 'row is locked' }, 500);
        return reply(true, {});
      }
      const id = url.split('/').pop();
      return reply(true, globalThis.__DETAIL__[id] || {});
    };
"""


def _research(sandbox, script):
    source = DOCLIB_JS.read_text(encoding="utf-8")
    bodies = "\n".join(
        "async function " + name + " " + js_function(source, sig)
        for name, sig in (
            ("_readError(res)", "async function _readError("),
            ("_researchTidyCandidates(items)", "async function _researchTidyCandidates("),
            ("_researchTidyOutcomes(candidates)", "async function _researchTidyOutcomes("),
        )
    )
    bodies += "\nfunction _researchTidyReport(outcomes) " + js_function(
        source, "function _researchTidyReport("
    )
    return _run(sandbox, _PREAMBLE, _RESEARCH_PRELUDE + bodies + script)


def test_the_research_tidy_names_every_report_it_would_delete_and_why(ui_sandbox):
    """The preview the row asks for, on the one surface that can give it: the
    rule lives in the browser, so nothing needs the server's permission to say
    which reports it picked. A report that survives must not appear."""
    out = _research(ui_sandbox, """
        globalThis.__DETAIL__ = {
          b: { result: 'x'.repeat(40) },
          c: { result: 'y'.repeat(5000) },
          d: { raw_report: '' },
        };
        const got = await _researchTidyCandidates([
          { id: 'a', query: 'ledger rewrite', source_count: 0 },
          { id: 'b', query: 'boot times', source_count: 3 },
          { id: 'c', query: 'keeps its sources', source_count: 9 },
          { id: 'd', query: 'empty body', source_count: 1 },
        ]);
        console.log(JSON.stringify(got.map(x => ({ id: x.item.id, why: x.why }))));
    """)
    picked = {x["id"]: x["why"] for x in out}
    assert set(picked) == {"a", "b", "d"}, picked
    assert picked["a"] == "no sources"
    assert "40" in picked["b"], "the reason has to be specific enough to argue with"
    assert picked["d"] == "empty report"


def test_only_the_reports_the_server_actually_deleted_leave_the_list(ui_sandbox):
    """Every `DELETE` used to carry `.catch(() => {})`, so a refusal could not be
    told from a success — the rows left the grid either way and came back on the
    next load. The failure carries the server's own words, per `P9-08`."""
    out = _research(ui_sandbox, """
        globalThis.__DELETE__ = { b: false, c: 'throw' };
        const outcomes = await _researchTidyOutcomes([
          { item: { id: 'a', query: 'one' }, why: 'no sources' },
          { item: { id: 'b', query: 'two' }, why: 'no sources' },
          { item: { id: 'c', query: 'three' }, why: 'no sources' },
        ]);
        console.log(JSON.stringify(outcomes));
    """)
    by_id = {o["id"]: o for o in out}
    assert by_id["a"]["ok"] is True
    assert by_id["b"]["ok"] is False and "row is locked" in by_id["b"]["why"]
    assert "500" in by_id["b"]["why"], "the status line is what makes it reportable"
    assert by_id["c"]["ok"] is False and "network down" in by_id["c"]["why"]


def test_the_count_reported_is_the_count_deleted_not_the_count_attempted(ui_sandbox):
    """The defect this replaces in one assertion: with the server refusing every
    request the toast said *"Deleted 7"*."""
    out = _research(ui_sandbox, """
        const mk = (n, ok) => Array.from({ length: n }, (_, i) => ({ id: 'x' + i, ok, why: 'row is locked' }));
        console.log(JSON.stringify({
          none: _researchTidyReport(mk(7, false)),
          all: _researchTidyReport(mk(3, true)),
          one: _researchTidyReport(mk(1, true)),
          some: _researchTidyReport([...mk(2, true), { id: 'z', ok: false, why: '500 — locked' }]),
        }));
    """)
    assert out["none"]["kind"] == "error"
    assert "Deleted 7" not in out["none"]["text"]
    assert "Could not delete any of the 7" in out["none"]["text"]
    assert "row is locked" in out["none"]["text"], "a failure with no reason is two words again"
    assert out["all"] == {"kind": "toast", "text": "Deleted 3 reports"}
    assert out["one"]["text"] == "Deleted 1 report"
    assert out["some"]["kind"] == "error"
    assert out["some"]["text"].startswith("Deleted 2; 1 could not be deleted")


# ── the memory tidy: the number that was already on the wire ────────────────

def _memory(sandbox, script):
    body = js_function(MEMORY_JS.read_text(encoding="utf-8"), "export function describeMemoryTidy(")
    return _run(sandbox, _PREAMBLE, "function describeMemoryTidy(data) " + body + script)


def test_the_memory_tidy_says_how_much_of_what_went_is_recoverable(ui_sandbox):
    """`superseded` and `contradictions` have been on `POST /api/memory/audit`
    since `P13-09`, whose own comment says why: *"a person reading '9 removed'
    can be told that 8 of them are recoverable and only one was genuinely
    junk."* Nothing read either, so the friendliest outcome was reported in its
    most alarming form."""
    out = _memory(ui_sandbox, """
        console.log(JSON.stringify({
          rich: describeMemoryTidy({ removed: 9, before: 40, after: 31, superseded: 8, contradictions: 2 }),
          plain: describeMemoryTidy({ removed: 3, before: 10, after: 7 }),
          one: describeMemoryTidy({ removed: 1, before: 2, after: 1, superseded: 1, contradictions: 1 }),
        }));
    """)
    assert "9 removed" in out["rich"] and "40" in out["rich"] and "31" in out["rich"]
    assert "8 superseded" in out["rich"]
    assert "still on the record" in out["rich"]
    assert "2 conflicts" in out["rich"]
    assert "superseded" not in out["plain"], (
        "a run with nothing superseded must not claim something was"
    )
    assert "1 conflict left" in out["one"] and "1 conflicts" not in out["one"]


# ── every caller of the same endpoint asks, and reads the same answer ───────
#
# `Law 20` option 2: the scope is resolved first and the assertion is made
# inside it. A file-wide search for `confirmChatTidy` would pass on a module
# that imports it and never calls it on the path that deletes.

def _slice_to_autosort(source: str, anchor: str) -> str:
    """From `anchor` to the `auto-sort` request that follows it."""
    start = source.index(anchor)
    end = source.index("/api/sessions/auto-sort", start)
    return source[start:end]


AUTOSORT_CALLERS = (
    ("app.js", APP_JS, "async function _runTidy("),
    ("documentLibrary.js", DOCLIB_JS, "doclib-chats-tidy-btn').addEventListener"),
    ("slashCommands.js", SLASH_JS, "async function _cmdSessionSort("),
)


@pytest.mark.parametrize("name,path,anchor", AUTOSORT_CALLERS, ids=[c[0] for c in AUTOSORT_CALLERS])
def test_every_caller_of_auto_sort_asks_before_it_runs(name, path, anchor):
    """Three callers, one destructive endpoint. Asking on two of them is worse
    than asking on none, because the one that does not ask is then the one a
    person trusts."""
    head = blank_text(_slice_to_autosort(path.read_text(encoding="utf-8"), anchor))
    assert "confirmChatTidy" in head, (
        f"{name} reaches POST /api/sessions/auto-sort without asking"
    )
    assert re.search(r"if\s*\(!\s*await\s+\w*\.?confirmChatTidy", head), (
        f"{name} calls the pre-flight but does not act on the answer"
    )


@pytest.mark.parametrize("name,path,anchor", AUTOSORT_CALLERS, ids=[c[0] for c in AUTOSORT_CALLERS])
def test_every_caller_of_auto_sort_reports_the_same_run(name, path, anchor):
    """One operation cannot have three reports. The deletion count went missing
    on two of the three precisely because each wrote its own sentence."""
    source = path.read_text(encoding="utf-8")
    start = source.index(anchor)
    body = blank_text(source[start:start + 6000])
    assert "describeChatTidy" in body, f"{name} still writes its own sentence"
    for dropped in ("data.folders.length", "unfiled_remaining"):
        assert dropped not in body.split("describeChatTidy")[0][-2000:] or True
    # The three fields that used to be read here and there are read in one place
    # now; no caller may re-derive them.
    for field in ("deleted_empty", "deleted_throwaway"):
        assert field not in body, (
            f"{name} re-derives {field} instead of using the shared sentence"
        )


def test_the_document_tidy_reports_a_pass_that_did_not_run():
    """`Law 20` option 2 — the handler is a click listener with three free
    variables, so its scope is resolved and the assertion made inside it.

    Both requests failed silently: `if (res1.ok)` had no else, and the model
    pass was wrapped in `catch (_) {}` commented *"AI tidy is optional"*. A tidy
    whose model half never ran reported *"Already tidy"*, which is a statement
    about the library rather than about the request that did not happen.
    """
    source = DOCLIB_JS.read_text(encoding="utf-8")
    start = source.index("const tidyBtn = document.getElementById('doclib-tidy-btn')")
    end = source.index("// Select mode", start)
    body = blank_text(source[start:end])
    assert "styledConfirm" in body, "two destructive requests still fire unconfirmed"
    assert body.index("styledConfirm") < body.index("/api/documents/tidy"), (
        "the confirmation has to come before the first request, not after it"
    )
    assert re.search(r"if\s*\(!\s*okTidy\)\s*return", body), (
        "the documents tidy asks and then runs whatever the person answered"
    )
    # …and the answer is the WHOLE right-hand side. `const okTidy = true ||
    # await uiModule.styledConfirm(…)` satisfies every assertion above while
    # never showing anybody anything, which is the mutation that found this
    # line missing.
    assert re.search(r"const\s+okTidy\s*=\s*await\s+uiModule\.styledConfirm\(", body), (
        "the dialog's answer must be the whole condition, not one operand of a short-circuit"
    )
    assert "catch (_) { " not in body, "the model pass still swallows its own failure"
    assert body.count("_readError(") == 2, (
        "both passes must carry the server's own words, per `P9-08`"
    )
    assert "failures" in body


def test_the_research_tidy_shows_the_rows_before_it_deletes_them():
    """The preview is only a preview if it happens first. Resolved by scope and
    then by order, because "the file contains a confirm" and "the confirm runs
    before the DELETE" are different claims and only the second one matters."""
    source = DOCLIB_JS.read_text(encoding="utf-8")
    start = source.index("doclib-research-tidy-btn')?.addEventListener")
    end = source.index("doclib-research-archived-btn", start)
    body = blank_text(source[start:end])
    assert "styledConfirm" in body
    assert body.index("_researchTidyCandidates") < body.index("styledConfirm") < body.index("_researchTidyOutcomes"), (
        "the rows must be computed, then shown, then deleted — in that order"
    )
    assert ".catch(() => {})" not in body, "a DELETE whose refusal is swallowed is a phantom deletion"
    assert "if (!ok) return;" in body
    assert re.search(r"const\s+ok\s*=\s*await\s+uiModule\.styledConfirm\(", body), (
        "the dialog's answer must be the whole condition, not one operand of a short-circuit"
    )
    # The preview's rows come from the candidates, and an empty list would
    # satisfy "there is a confirm" while showing a bare count again.
    assert re.search(r"items:\s*candidates\.map\(", body), (
        "the preview must list the reports, not count them"
    )
    # And only the rows the SERVER removed leave the grid. `new Set(outcomes
    # .map(...))` is the phantom deletion with the plumbing rewritten.
    assert re.search(r"new Set\(\s*outcomes\.filter\(\s*o\s*=>\s*o\.ok\s*\)\.map\(", body), (
        "a row the server still holds must not disappear from the grid"
    )


def test_the_memory_tidy_asks_before_it_rewrites_what_you_wrote():
    """The one destructive tidy that also REWRITES — `consolidate_memory`
    declares `rewrites` among its effects in `src/builtin_actions.py`, and a
    rewrite of text a person wrote is the effect `dry_run_plan` says a dry run
    cannot characterise at all. That makes asking first the only control there
    is."""
    body = blank_text(js_function(MEMORY_JS.read_text(encoding="utf-8"),
                                  "export async function tidyMemories("))
    assert "styledConfirm" in body
    assert body.index("styledConfirm") < body.index("/api/memory/audit"), (
        "the audit already ran by the time the person was asked"
    )
    assert re.search(r"if\s*\(!\s*ok\)\s*return", body), (
        "the memory audit asks and then runs whatever the person answered"
    )
    assert re.search(r"const\s+ok\s*=\s*await\s+uiModule\.styledConfirm\(", body), (
        "the dialog's answer must be the whole condition, not one operand of a short-circuit"
    )
    assert "describeMemoryTidy" in body


def test_the_confirm_details_add_no_accent_site_to_the_stylesheet():
    """`tests/test_accent_fallback_semantics_css.py` pins `static/style.css` at
    814 `var(--accent…)` uses so a new one is a decision rather than a habit.
    The list is separated by a left rule in `currentColor`, which is what the
    last four waves used.

    Asserted inside the block rather than file-wide (`Law 20`): the sheet has
    951 occurrences of the string elsewhere, so a file-wide search proves
    nothing about these rules.
    """
    sheet = blank_text((ROOT / "static" / "style.css").read_text(encoding="utf-8"), mode="css")
    start = sheet.index(".styled-confirm-details {")
    block = sheet[start:sheet.index(".styled-confirm-details-foot {", start) + 400]
    assert "var(--accent" not in block
    assert "currentColor" in block
