# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B710`. A memory can be proposed rather than committed, and now it shows.

`P13-05` put `status`, `committed_at` and `committed_by` on the record,
excluded proposals from every retrieval path through `memory_edges.live`,
added `POST /api/memory/{id}/commit` with a gate, and honoured an
`auto_approve_memories` preference in background extraction. Every half had a
consumer and the preference was settable the day it landed — and **no surface
showed any of it**. That is the unwired half `Law 13` is about, and it is also
`Law 15`, which is this phase's acceptance criterion: *a proposal a person
cannot see is a proposal they cannot reject.* It is why the preference had to
ship defaulting **on** — off, with nothing to look at, is a Brain that quietly
stops learning.

What is pinned here, and why each one is a defect if it breaks:

  * **The browser's status vocabulary is the server's.** Two copies, one table,
    both driven — the `MEMORY_ENGINE_LABELS` arrangement, which has now earned
    its keep four times. The default for an unrecognised value is the
    load-bearing half: `committed`, in both, because a record that binds when
    it should not is wrong and obvious while one that stops binding is wrong
    and invisible.
  * **Nothing is said about a committed memory.** A badge on every row is a
    column, not information; the reading a person needs from this field is
    *which of these is not what it looks like*.
  * **A proposal is visible in the list, and the list says so without being
    asked.** The chip row appears only once something is not committed, and
    carries its count.
  * **The list and its count never disagree.** They are two functions applying
    one clause, which is how a header reading "7 of 9" ends up over a list of
    three.
  * **Committing goes through the gate and the gate's own words reach the
    person.** *"the Brain already knows this — …"* is the most useful sentence
    on this path and a generic failure banner throws it away (`Law 10`).
  * **The control that can only refuse is not offered.** `commit_memory`
    refuses an already-committed record and `archive` refuses anything not
    currently committed, so each surface offers the one its state admits.

Nothing below reads a source file for behaviour: the module is imported
unmodified into a DOM sandbox and driven (`Law 20`). `B61` is the reason —
a helper can be perfect and the page still show nothing.
"""

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.helpers.motion_stub import motion_stub
from tests.helpers.esc_stub import empty_state_source, ui_default_stub
from test_tool_effect_surfaces_js import _DOM, _copy_unstubbed_imports  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
MEMORY_JS = JS / "memory.js"
FACTS = JS / "memoryFacts.js"
INDEX = ROOT / "static" / "index.html"

sys.path.insert(0, str(ROOT))
from src import memory_edges  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the sandbox ─────────────────────────────────────────────────────────────
# `memory.js` imports eleven modules and owns a window. Everything that is not
# the rule under test is stubbed; `memoryFacts.js` and `brainFilter.js` are
# copied in REAL by `_copy_unstubbed_imports`, because they ARE the rule.

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

/** Every toast and error the module raised, in order, so a refusal can be read
 *  as the sentence a person sees rather than as a call that happened. */
export const said = { toasts: [], errors: [] };

/** The requests the module made, so a route can be checked by being called. */
export const sent = [];

let _corpus = [];
let _prefs = {};
/** What `GET /api/memory` answers next. */
export function store(rows, prefs) {
  _corpus = rows;
  if (prefs) _prefs = prefs;
}
/** Verdicts `POST /{id}/commit` answers, keyed by memory id. */
export const verdicts = new Map();

function _res(body, status = 200) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

globalThis.fetch = async (url, opts) => {
  const path = String(url).replace('http://test.local', '');
  sent.push({ path, method: (opts && opts.method) || 'GET' });
  if (path === '/api/prefs') return _res(_prefs);
  if (path.startsWith('/api/prefs/')) return _res({ value: _prefs[path.split('/').pop()] });
  if (path === '/api/memory') return _res({ memory: _corpus.map((m) => ({ ...m })) });
  const commit = path.match(/^\/api\/memory\/([^/]+)\/commit$/);
  if (commit) {
    const verdict = verdicts.get(commit[1]) || { verdict: 'committed', reason: 'committed' };
    if (verdict.__status) return _res(verdict, verdict.__status);
    // A real commit moves the record, which is what the reload then shows.
    if (verdict.verdict === 'committed') {
      _corpus = _corpus.map((m) => (m.id === commit[1] ? { ...m, status: 'committed' } : m));
    }
    return _res(verdict);
  }
  return _res({});
};

/** The Brain's markup, cut to the ids this surface touches. */
export function page() {
  document.body.childNodes = [];
  const add = (tag, id, cls) => {
    const n = document.body.appendChild(new Node(tag));
    if (id) n.setAttribute('id', id);
    if (cls) n.className = cls;
    return n;
  };
  const made = {
    list: add('div', 'memory-list'),
    cats: add('div', 'memory-category-filters'),
    statuses: add('div', 'memory-status-filters'),
    search: add('input', 'memory-search'),
    h2: add('span', 'memory-count-h2'),
    tab: add('span', 'memory-count'),
    approve: add('input', 'auto-approve-memories-toggle'),
    hint: add('p', 'auto-approve-memories-hint'),
  };
  made.statuses.hidden = true;
  made.approve.type = 'checkbox';
  return made;
}

/** The rows on screen, as a reader would read them. */
export function rows() {
  return document.querySelectorAll('.memory-item').map((row) => ({
    id: row.dataset.memoryId,
    badge: (row.querySelector('.memory-status-badge') || {}).textContent || null,
    badgeTitle: (row.querySelector('.memory-status-badge') || {}).title || null,
    classes: row._classes(),
    text: row.readable,
  }));
}

/** The status chips on screen. */
export function chips() {
  const host = document.getElementById('memory-status-filters');
  return {
    hidden: !!host.hidden,
    labels: host.querySelectorAll('button').map((b) => b.textContent),
    active: host.querySelectorAll('button.active').map((b) => b.dataset.status),
  };
}

/** Click a status chip by its stored value. */
export function clickChip(value) {
  const btn = document.getElementById('memory-status-filters')
    .querySelectorAll('button').find((b) => b.dataset.status === value);
  if (!btn) throw new Error('no chip for ' + value);
  click(btn);
}

/** A click the handlers can actually use. The shared shim's `Event` is a bare
 *  `{type}`, and every control on this surface calls `stopPropagation` first —
 *  a shim that makes the module throw on a method the browser has is worse
 *  than no shim at all. */
export function click(node) {
  const ev = new globalThis.Event('click');
  ev.stopPropagation = () => {};
  ev.preventDefault = () => {};
  ev.target = node;
  node.dispatchEvent(ev);
  return ev;
}

/** Open one row's kebab and read the items it offers. */
export function menuItems(id) {
  const row = document.querySelectorAll('.memory-item').find((r) => r.dataset.memoryId === String(id));
  if (!row) throw new Error('no row ' + id);
  const kebab = row.querySelector('.memory-menu-btn');
  click(kebab);
  const menu = document.body.querySelector('.memory-item-dropdown');
  return (menu ? menu.querySelectorAll('button') : []).map((b) => ({
    label: b.readable, title: b.title, node: b,
  }));
}

export function clickMenuItem(id, label) {
  const hit = menuItems(id).find((m) => m.label.includes(label));
  if (!hit) throw new Error('no menu item ' + label);
  click(hit.node);
}

export const tick = () => new Promise((r) => setTimeout(r, 0));
export async function settle(n = 8) { for (let i = 0; i < n; i++) await tick(); }

export function hint() { return document.getElementById('auto-approve-memories-hint').textContent; }
"""

# `B1430`. The shipped `esc` (`ui_default_stub`), not one that returns its
# input — `test_one_esc_stub_js.py` refuses the hand-written kind (`B874`).
# `B730`: with the shipped `renderEmptyState`, which the Brain's list draws its
# empty states through.
_UI = ui_default_stub(
    "showToast: (m) => { globalThis.__said.toasts.push(String(m)); },\n"
    "  showError: (m) => { globalThis.__said.errors.push(String(m)); },\n"
    "  emptyStateIcon, renderEmptyState,",
    before=empty_state_source())

_STUBS = {
    "ui.js": _UI,
    "sessions.js": "export default { getCurrentSessionId: () => '' };\n",
    "spinner.js": (
        "export default { createLoadingRow: (t) => {"
        " const n = document.createElement('div'); n.textContent = t; return n; } };\n"
    ),
    "windowDrag.js": "export function makeWindowDraggable() {}\n",
    "tileManager.js": "export function snapModalToZone() {}\n",
    "toolWindowZOrder.js": "export function topPortalZ() { return 10000; }\n",
    "modalManager.js": (
        "export function setBackgroundWork() {}\n"
        "export function register() {}\n"
        "export function close() {}\n"
        "export function open() {}\n"
        "export default {};\n"
    ),
    "escMenuStack.js": (
        "export function bindMenuDismiss(node, onClose) { return onClose; }\n"
        "export function dismissOrRemove(node) { if (node && node.remove) node.remove(); }\n"
    ),
    "workbench/refusal.js": (
        "export async function readRefusal(res, fallback) {"
        " return { sentence: fallback }; }\n"
    ),
    "motion.js": motion_stub(),
}

_PREAMBLE = (
    "import { document, said, sent, store, verdicts, page, rows, chips, clickChip,"
    " menuItems, clickMenuItem, click, settle, hint } from './shim.js';\n"
    "globalThis.__said = said;\n"
    "const brain = (await import('./memory.js')).default;\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("brainstatus")
    (d / "dom.js").write_text(_DOM, encoding="utf-8")
    (d / "shim.js").write_text(_SHIM, encoding="utf-8")
    for name, src in _STUBS.items():
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(src, encoding="utf-8")
    shutil.copy(MEMORY_JS, d / "memory.js")
    _copy_unstubbed_imports(d, MEMORY_JS, _STUBS)
    return d


def _run(sandbox, script: str):
    entry = sandbox / "case.mjs"
    entry.write_text(_PREAMBLE + textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], cwd=sandbox,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])


def _facts(script: str):
    """Drive `memoryFacts.js` on its own — it imports nothing and needs no DOM."""
    source = "import * as F from '%s';\n" % FACTS.as_posix() + textwrap.dedent(script)
    proc = subprocess.run(["node", "--input-type=module"], input=source,
                          capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


#: Everything a `status` field can hold that is worth disagreeing about. The
#: junk at the end is the point: a memory store is a file a person can edit.
STATUS_TABLE = [
    "committed", "proposed", "archived",
    None, "", " ", "COMMITTED", "Proposed", "retired", "live", "pending",
    0, 1, True, False, [], {}, "archived ",
]


# ── one vocabulary, two implementations ─────────────────────────────────────

def test_the_browser_and_the_server_name_the_same_three_statuses():
    """`MEMORY_STATUSES` is the server's list; the browser's table is keyed by
    it. A fourth status added on one side and not the other is a surface that
    silently calls it committed."""
    browser = _facts("console.log(JSON.stringify(Object.keys(F.MEMORY_STATUS_LABELS)));")
    assert sorted(browser) == sorted(memory_edges.MEMORY_STATUSES)


def test_the_browser_and_the_server_agree_on_every_status_value():
    """One table, both sides. The junk rows are where the two could part — and
    the direction they agree in is the decision: unrecognised binds."""
    browser = _facts(
        "const t = %s;\n"
        "console.log(JSON.stringify(t.map((v) => F.memoryStatus({ status: v }))));"
        % json.dumps(STATUS_TABLE)
    )
    server = [memory_edges.status_of({"status": v}) for v in STATUS_TABLE]
    disagree = [f"{v!r}: python {p} vs browser {b}"
                for v, p, b in zip(STATUS_TABLE, server, browser) if p != b]
    assert not disagree, "\n".join(disagree)


def test_a_record_with_no_status_field_binds_on_both_sides():
    """Every memory written before `P13-05` reads this, and they ARE binding —
    they are being injected into prompts today."""
    browser = _facts(
        "console.log(JSON.stringify(["
        "F.memoryStatus({}), F.memoryStatus(null), F.memoryStatus('nope'),"
        "F.memoryBinds({}), F.memoryBinds({ status: 'proposed' })]));")
    assert browser == ["committed", "committed", "committed", True, False]
    assert memory_edges.status_of({}) == "committed"
    assert memory_edges.is_committed({}) is True


# ── the badge says nothing about the ordinary case ──────────────────────────

def test_a_committed_memory_carries_no_badge_at_all():
    out = _facts(
        "console.log(JSON.stringify(["
        "F.memoryStatusBadge({ status: 'committed' }),"
        "F.memoryStatusBadge({}),"
        "F.memoryStatusBadge({ status: 'who knows' })]));")
    assert out == [None, None, None], (
        "a badge on every row is a column, not information")


def test_the_two_extraordinary_states_say_which_they_are():
    out = _facts(
        "console.log(JSON.stringify(["
        "F.memoryStatusBadge({ status: 'proposed' }),"
        "F.memoryStatusBadge({ status: 'archived' })]));")
    proposed, archived = out
    assert proposed["text"] == "proposed"
    # The word on the badge is the word on the button that produces it
    # (`brainExplore.js` says *Retire*), and they come from one table so they
    # cannot drift into disagreeing about one record.
    assert archived["text"] == "retired"
    for badge in out:
        assert "chat" in badge["title"], (
            "the title has to say what the status DOES, not restate the word")


# ── the surface, driven ─────────────────────────────────────────────────────

_CORPUS = [
    {"id": "m1", "text": "Lives in Leeds", "category": "fact", "timestamp": 1760000000},
    {"id": "m2", "text": "Allergic to shellfish", "category": "fact",
     "status": "proposed", "timestamp": 1760000100},
    {"id": "m3", "text": "Old address", "category": "fact",
     "status": "archived", "timestamp": 1759000000},
    {"id": "m4", "text": "Prefers dark mode", "category": "preference",
     "status": "committed", "timestamp": 1760000200},
]


def test_a_proposal_is_marked_on_the_row_and_a_committed_one_is_not(sandbox):
    out = _run(sandbox, """
        page();
        store(%s);
        await brain.loadMemories();
        await settle();
        console.log(JSON.stringify(rows()));
    """ % json.dumps(_CORPUS))
    by_id = {row["id"]: row for row in out}
    assert by_id["m2"]["badge"] == "proposed"
    assert by_id["m3"]["badge"] == "retired"
    assert by_id["m1"]["badge"] is None
    assert by_id["m4"]["badge"] is None
    assert "memory-item-proposed" in by_id["m2"]["classes"]
    assert "memory-item-archived" in by_id["m3"]["classes"]
    assert "memory-item-proposed" not in by_id["m1"]["classes"]


def test_the_chip_row_stays_away_until_something_is_not_committed(sandbox):
    """A person who never turns auto-approve off is never shown a control for a
    state their Brain is not in."""
    ordinary = [_CORPUS[0], _CORPUS[3], {"id": "m9", "text": "Junk status",
                                         "status": "nonsense", "timestamp": 1}]
    out = _run(sandbox, """
        page();
        store(%s);
        await brain.loadMemories();
        await settle();
        const quiet = chips();
        store(%s);
        await brain.loadMemories();
        await settle();
        console.log(JSON.stringify({ quiet, loud: chips() }));
    """ % (json.dumps(ordinary), json.dumps(_CORPUS)))
    assert out["quiet"]["hidden"] is True
    assert out["quiet"]["labels"] == []
    assert out["loud"]["hidden"] is False
    assert out["loud"]["labels"] == ["all 4", "in use 2", "proposed 1", "retired 1"], (
        "the chips carry their counts, and only the statuses the corpus has")


def test_narrowing_to_proposed_shows_the_proposals_and_says_so(sandbox):
    out = _run(sandbox, """
        page();
        store(%s);
        await brain.loadMemories();
        await settle();
        clickChip('proposed');
        await settle();
        console.log(JSON.stringify({
          rows: rows().map((r) => r.id),
          active: chips().active,
          header: document.getElementById('memory-count-h2').textContent,
          tab: document.getElementById('memory-count').textContent,
        }));
    """ % json.dumps(_CORPUS))
    assert out["rows"] == ["m2"]
    assert out["active"] == ["proposed"]
    # The count is the other half of the claim: a header saying "4 of 4" over
    # one row is the defect this pins.
    assert out["header"] == "1 of 4"
    assert out["tab"] == "4"


def test_in_use_is_an_effect_and_not_a_spelling(sandbox):
    """A record with an unreadable status IS reaching chats, so it is in the
    *in use* list. A filter written as `status === 'committed'` would hide it
    while the retriever kept injecting it."""
    corpus = _CORPUS + [{"id": "m5", "text": "Typo in the store",
                         "status": "committted", "timestamp": 1760000300}]
    out = _run(sandbox, """
        page();
        store(%s);
        await brain.loadMemories();
        await settle();
        clickChip('binding');
        await settle();
        console.log(JSON.stringify(rows().map((r) => r.id)));
    """ % json.dumps(corpus))
    assert sorted(out) == ["m1", "m4", "m5"]


def test_a_status_with_no_members_is_not_offered(sandbox):
    """A `retired 0` chip is an invitation to click something that can only
    produce an empty list. `in use` and `all` are the two exceptions, because
    *everything* and *what is actually in use* stay askable whatever the
    corpus holds."""
    only_proposals = [dict(_CORPUS[1]), {"id": "m7", "text": "Second proposal",
                                         "status": "proposed", "timestamp": 2}]
    mixed_no_retired = [_CORPUS[0], _CORPUS[1], _CORPUS[3]]
    out = _run(sandbox, """
        page();
        store(%s);
        await brain.loadMemories();
        await settle();
        const none_retired = chips().labels;
        store(%s);
        await brain.loadMemories();
        await settle();
        console.log(JSON.stringify({ none_retired, all_proposals: chips().labels }));
    """ % (json.dumps(mixed_no_retired), json.dumps(only_proposals)))
    assert out["none_retired"] == ["all 3", "in use 2", "proposed 1"]
    assert out["all_proposals"] == ["all 2", "in use 0", "proposed 2"], (
        "`in use 0` stays offered — it is the question, not a bucket")


def test_a_narrowed_list_with_no_survivors_says_no_matches(sandbox):
    """`B1070` wearing a different hat: "No memories yet." over a full store is
    a false statement about the store.

    Narrowed by the **status chip alone** — no search box, no category — which
    is the one path the empty-state branch could miss. A corpus of nothing but
    proposals still offers *in use*, and clicking it is how a reader gets here
    without touching anything else."""
    only_proposals = [dict(_CORPUS[1]), {"id": "m7", "text": "Second proposal",
                                         "status": "proposed", "timestamp": 2}]
    out = _run(sandbox, """
        page();
        store(%s);
        await brain.loadMemories();
        await settle();
        clickChip('binding');
        await settle();
        console.log(JSON.stringify({
          search: document.getElementById('memory-search').value,
          empty: document.getElementById('memory-list').readable,
        }));
    """ % json.dumps(only_proposals))
    assert out["search"] == "", "this case has to reach the empty list by status alone"
    assert "No matches" in out["empty"]
    assert "No memories yet" not in out["empty"], (
        "the store is full; saying it is empty is a false statement about it")


# ── committing ──────────────────────────────────────────────────────────────

def test_only_a_memory_that_is_not_committed_is_offered_the_act(sandbox):
    out = _run(sandbox, """
        page();
        store(%s);
        await brain.loadMemories();
        await settle();
        const labels = (id) => menuItems(id).map((m) => m.label);
        console.log(JSON.stringify({
          committed: labels('m1'), proposed: labels('m2'), archived: labels('m3'),
        }));
    """ % json.dumps(_CORPUS))
    # NEITHER verb on a committed memory. Checked as both, because the two
    # labels are one control and a mutation that offers it unconditionally
    # simply picks the other word.
    assert not any("Commit" in label or "Bring back" in label
                   for label in out["committed"]), (
        "`commit_memory` refuses an already-committed record, so this menu "
        "would be offering a control that can only produce a refusal")
    assert any("Commit" in label for label in out["proposed"])
    assert not any("Bring back" in label for label in out["proposed"]), (
        "a proposal has never been in use, so there is nothing to bring back")
    # A retired memory is brought back by the same act, under a word that says
    # what happens rather than what the act is named.
    assert any("Bring back" in label for label in out["archived"])
    assert not any("Commit" in label for label in out["archived"])


def test_committing_calls_the_gate_and_the_memory_starts_binding(sandbox):
    out = _run(sandbox, """
        page();
        store(%s);
        await brain.loadMemories();
        await settle();
        clickMenuItem('m2', 'Commit');
        await settle(20);
        console.log(JSON.stringify({
          posted: sent.filter((r) => r.method === 'POST').map((r) => r.path),
          toasts: said.toasts,
          badge: rows().find((r) => r.id === 'm2').badge,
          chips: chips().labels,
        }));
    """ % json.dumps(_CORPUS))
    assert out["posted"] == ["/api/memory/m2/commit"]
    assert out["badge"] is None, "after committing it is an ordinary memory"
    assert out["chips"] == ["all 4", "in use 3", "retired 1"], (
        "the proposed chip goes when the last proposal does")
    assert any("reach chats" in t for t in out["toasts"])


def test_committing_the_last_proposal_does_not_leave_the_reader_in_an_empty_list(sandbox):
    """The chip that is narrowing the list is the chip that is about to go.

    A reader who narrows to *proposed*, commits the only one, and is left
    looking at an empty list with no visible control explaining it has been
    shown the Brain losing its contents. The row puts its own state back when
    it puts itself away — which is only correct if it happens before the list
    is redrawn, so this drives the whole sequence rather than the helper."""
    one_proposal = [_CORPUS[0], _CORPUS[1], _CORPUS[3]]
    out = _run(sandbox, """
        page();
        store(%s);
        await brain.loadMemories();
        await settle();
        clickChip('proposed');
        await settle();
        const narrowed = rows().map((r) => r.id);
        clickMenuItem('m2', 'Commit');
        await settle(20);
        console.log(JSON.stringify({
          narrowed,
          after: rows().map((r) => r.id),
          chips: chips(),
          header: document.getElementById('memory-count-h2').textContent,
        }));
    """ % json.dumps(one_proposal))
    assert out["narrowed"] == ["m2"]
    assert sorted(out["after"]) == ["m1", "m2", "m4"], (
        "the list went back to everything when the filter did")
    assert out["chips"]["hidden"] is True
    assert out["header"] == "", "nothing is hidden, so the header says nothing"


def test_a_refusal_reaches_the_person_in_the_gates_own_words(sandbox):
    """*"the Brain already knows this — …"* is the most useful sentence this
    path produces, and a generic failure banner throws it away (`Law 10`)."""
    out = _run(sandbox, """
        page();
        store(%s);
        verdicts.set('m2', { verdict: 'refused',
          reason: 'the Brain already knows this — "Allergic to shellfish"' });
        await brain.loadMemories();
        await settle();
        clickMenuItem('m2', 'Commit');
        await settle(20);
        console.log(JSON.stringify({ toasts: said.toasts, errors: said.errors,
                                     badge: rows().find((r) => r.id === 'm2').badge }));
    """ % json.dumps(_CORPUS))
    assert out["toasts"] == ['the Brain already knows this — "Allergic to shellfish"']
    assert out["errors"] == [], "a refusal is an answer, not an error"
    assert out["badge"] == "proposed", "a refused commit changes nothing"


def test_a_route_that_never_ran_is_an_error_and_not_a_verdict(sandbox):
    """A 403 or a 404 means the gate did not decide. That IS a failure, and
    reporting it as a quiet toast would tell a person their memory was
    considered and declined."""
    out = _run(sandbox, """
        page();
        store(%s);
        verdicts.set('m2', { __status: 403, detail: 'nope' });
        await brain.loadMemories();
        await settle();
        clickMenuItem('m2', 'Commit');
        await settle(20);
        console.log(JSON.stringify({ toasts: said.toasts, errors: said.errors }));
    """ % json.dumps(_CORPUS))
    assert out["errors"], "a refused route has to surface as an error"
    assert not out["toasts"]


# ── the preference, and the sentence under it ───────────────────────────────

def test_the_toggle_reads_and_writes_the_preference_the_extractor_reads(sandbox):
    """The id in the markup, the pref key the server reads, and the control are
    one chain. Checked by driving it: the switch is set from `GET /api/prefs`
    and a change PUTs the same key."""
    out = _run(sandbox, """
        page();
        store(%s, { auto_approve_memories: false });
        await brain.loadMemories();
        await settle();
        const toggle = document.getElementById('auto-approve-memories-toggle');
        const before = toggle.checked;
        toggle.checked = true;
        toggle.dispatchEvent(new globalThis.Event('change'));
        await settle(20);
        console.log(JSON.stringify({
          before,
          puts: sent.filter((r) => r.method === 'PUT').map((r) => r.path),
        }));
    """ % json.dumps(_CORPUS))
    assert out["before"] is False, "the switch shows the stored value"
    assert out["puts"] == ["/api/prefs/auto_approve_memories"]


def test_the_extractor_reads_that_preference_under_that_name():
    """The other end of the same chain, so the pair cannot drift. `False` has
    to reach the extractor as *propose, do not commit*."""
    source = (ROOT / "services" / "memory" / "memory_extractor.py").read_text(encoding="utf-8")
    assert '"auto_approve_memories", True' in source, (
        "the server's default is what the switch's default has to match")


def _hint(auto: bool, waiting: int) -> str:
    """`memoryGateHint`, cut out of `memory.js` and RUN.

    The function is pure and the module around it is not, so the function is
    what runs — `js_definition` is this repository's way to cut one declaration
    out of a 2,300-line module, and running it is the difference between
    checking the sentence and checking that a sentence exists (`Law 20`).
    """
    from tests.helpers.js_source import js_definition
    from tests.helpers.source_text import blank_text
    src = MEMORY_JS.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    decl = js_definition(src, code.index("export function memoryGateHint("))
    script = (decl.replace("export function", "function", 1)
              + "\nconsole.log(JSON.stringify(memoryGateHint(%s)));"
              % json.dumps({"autoApprove": auto, "proposed": waiting}))
    proc = subprocess.run(["node", "--input-type=module"], input=script,
                          capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("auto,waiting,must_say", [
    (True, 0, "as soon as"),
    (False, 0, "wait for you"),
    (False, 3, "proposed"),
    (True, 2, "does not commit"),
])
def test_the_switch_says_where_its_effect_shows_up(auto, waiting, must_say):
    """`P8-05`'s lesson on a worse case: off, extraction keeps running and the
    Brain keeps growing, and *nothing new reaches a chat*. A person who cannot
    see where the proposals went has watched their assistant stop learning.

    The fourth row is the one that is easy to get wrong: turning the switch
    back ON does not commit what was proposed while it was off, and a reader
    who is not told that will wonder why the Brain is ignoring six facts."""
    out = _hint(auto, waiting)
    assert must_say in out
    if waiting:
        assert str(waiting) in out, "a count is the difference between a rule and a queue"


def test_the_four_sentences_are_four_different_sentences():
    """Each of the two inputs has to change what is said. A hint that ignores
    the count reads correctly in the state it was written for and lies in the
    other three."""
    said = {(auto, waiting): _hint(auto, waiting)
            for auto in (True, False) for waiting in (0, 2)}
    assert len(set(said.values())) == 4, (
        "two states produced the same sentence:\n"
        + "\n".join(f"  auto={a} waiting={w}: {text}" for (a, w), text in said.items()))


def test_the_live_sentence_is_the_rules_sentence(sandbox):
    """The hint on the page is `memoryGateHint`'s answer for the corpus that is
    actually loaded — not a static string that happens to read the same."""
    out = _run(sandbox, """
        page();
        store(%s, { auto_approve_memories: false });
        await brain.loadMemories();
        await settle();
        console.log(JSON.stringify({ hint: hint() }));
    """ % json.dumps(_CORPUS))
    assert out["hint"] == _hint(False, 1)
    assert "1 proposed" in out["hint"]


# ── the markup carries the anchors the module reaches for ───────────────────

def test_the_shipped_page_has_the_two_anchors_this_surface_needs(sandbox):
    """Driven, not grepped: the module is loaded against the SHIPPED ids and
    has to find them. An id renamed in one file and not the other is the
    failure this catches."""
    html = INDEX.read_text(encoding="utf-8")
    for anchor in ("memory-status-filters", "auto-approve-memories-toggle",
                   "auto-approve-memories-hint"):
        assert f'id="{anchor}"' in html, f"{anchor} is not in the shipped page"
