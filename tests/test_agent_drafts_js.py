"""The approval surface for mail the agent is holding (`H01`).

THE ROW'S PATHOLOGY IS WHAT THESE TESTS GUARD.

`agent_email_confirm` ships ON, so `_send_email` stages every agent-composed
message into `scheduled_emails` with a far-future `send_at` the poller never
reaches. Three endpoints to complete the loop have existed since before the
fork. Nothing called them — `grep -rn "email/pending" static/` returned nothing
across 183 frontend files — while THREE separate places asserted the surface
existed, including the model's own tool description, which tells the user their
mail is waiting for them in a chat UI that had never been built.

So the tests below are mostly not about rendering. They are about the specific
ways this can silently go back to being a lie:

  * the panel appearing only when somebody goes looking for it,
  * a failed poll emptying it,
  * the recipients — especially `bcc` — not being shown before Send,
  * and the model's promise drifting out of sync with the surface again.

Driven under node against the real file, in the sandbox pattern
`tests/test_chat_steer_js.py` established. The element ids come from the real
`static/index.html`, extracted here rather than retyped, so a rename in the
markup fails these rather than passing against a private copy of it.
"""
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not shutil.which("node"),
                                reason="node binary not on PATH")

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "static" / "js" / "agentDrafts.js"
INDEX = ROOT / "static" / "index.html"
STYLE = ROOT / "static" / "style.css"


def _panel_markup() -> str:
    html = INDEX.read_text(encoding="utf-8")
    start = html.index('<section id="agent-drafts-panel"')
    end = html.index("</section>", start) + len("</section>")
    return html[start:end]


def _panel_ids():
    return re.findall(r'id="([a-z0-9-]+)"', _panel_markup())


_SHIM = r"""
class Node {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.className = ''; this.id = ''; this.textContent = ''; this.type = '';
    this.hidden = false; this.disabled = false; this.title = '';
    this.childNodes = []; this.parentNode = null;
    this.dataset = {}; this.attrs = {}; this.listeners = {}; this.style = {};
    this.classList = {
      _n: this,
      add: (c) => { if (!(' ' + this.className + ' ').includes(' ' + c + ' ')) this.className = (this.className + ' ' + c).trim(); },
      remove: (c) => { this.className = this.className.split(/\s+/).filter(x => x && x !== c).join(' '); },
      contains: (c) => (' ' + this.className + ' ').includes(' ' + c + ' '),
      toggle: (c) => { if (this.classList.contains(c)) { this.classList.remove(c); return false; } this.classList.add(c); return true; },
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') this.id = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  appendChild(n) { n.parentNode = this; this.childNodes.push(n); return n; }
  replaceChildren(...kids) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = [];
    for (const k of kids) this.appendChild(k);
  }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  dispatchEvent(ev) { (this.listeners[ev.type] || []).slice().forEach(fn => fn(ev)); return true; }
  click() { this.dispatchEvent({ type: 'click' }); }
  _walk(out) { for (const c of this.childNodes) { out.push(c); c._walk(out); } return out; }
  get innerText() {
    return this.childNodes.length
      ? this.childNodes.map(c => c.innerText).join('\n')
      : (this.textContent || '');
  }
  // Deliberately absent: `innerHTML`. Assigning it in the module under test
  // would throw here rather than quietly work, which is the point — every
  // field on these cards is model-written text derived from arriving email.
}

const document = new Node('#document');
document.body = document.appendChild(new Node('body'));
document.createElement = (t) => new Node(t);
document.getElementById = (id) => document._walk([]).find(n => n.id === id) || null;

const PANEL_IDS = __PANEL_IDS__;
const _byId = {};
for (const id of PANEL_IDS) {
  const n = document.body.appendChild(new Node('div'));
  n.id = id;
  _byId[id] = n;
}
_byId['agent-drafts-panel'].hidden = true;

function _defineGlobal(name, value) {
  Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
globalThis.document = document;
_defineGlobal('window', globalThis);

export const calls = { fetch: [], confirms: [] };
export let confirmAnswer = true;
export function setConfirm(v) { confirmAnswer = v; }
globalThis.confirm = (msg) => { calls.confirms.push(String(msg)); return confirmAnswer; };

export function mockFetch(handler) {
  globalThis.fetch = async (url, opts) => {
    calls.fetch.push({ url: String(url), method: (opts && opts.method) || 'GET' });
    return handler(String(url), opts || {});
  };
}
export function res(status, payload) {
  return { ok: status >= 200 && status < 300, status, json: async () => (payload || {}) };
}
export function boom() {
  globalThis.fetch = async () => { throw new Error('offline'); };
}

export function panel() { return _byId['agent-drafts-panel']; }
export function list() { return _byId['agent-drafts-list']; }
export function byId(id) { return _byId[id]; }
export function rows() {
  return list().childNodes.map(r => ({
    id: r.dataset.draftId,
    text: r.innerText,
    classes: r._walk([]).map(n => n.className),
    buttons: r._walk([]).filter(n => n.tagName === 'BUTTON')
      .map(b => ({ label: b.textContent, cls: b.className, disabled: b.disabled })),
  }));
}
export function clickButton(rowIndex, label) {
  const r = list().childNodes[rowIndex];
  const b = r._walk([]).find(n => n.tagName === 'BUTTON' && n.textContent === label);
  if (!b) throw new Error('no button ' + label);
  b.click();
}
export function tick(n = 6) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise(r => setTimeout(r, 0)));
  return p;
}
export { document };
"""


def _draft(**kw):
    base = {
        "id": "d1", "to_addr": "someone@example.test", "cc": None, "bcc": None,
        "subject": "Re: the thing", "body": "Hi,\n\nAs discussed.\n\nThanks,",
        "created_at": "2025-09-06T10:00:00", "account_id": "gmail",
        "age_seconds": 120.0,
    }
    base.update(kw)
    return base


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("draftsjs")
    (d / "shim.js").write_text(_SHIM.replace("__PANEL_IDS__", json.dumps(_panel_ids())))
    shutil.copy(MODULE, d / "agentDrafts.js")
    return d


def _run(sandbox, script: str) -> dict:
    entry = sandbox / "case.mjs"
    entry.write_text(
        "import { calls, mockFetch, res, boom, panel, list, byId, rows, "
        "clickButton, tick, setConfirm, document } from './shim.js';\n"
        "import drafts from './agentDrafts.js';\n"
        + textwrap.dedent(script)
    )
    proc = subprocess.run(["node", str(entry)], cwd=sandbox,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])


# ── it shows itself ─────────────────────────────────────────────────────────

def test_the_panel_stays_hidden_when_nothing_is_staged(sandbox):
    out = _run(sandbox, """
        mockFetch(() => res(200, { pending: [], count: 0, oldest_age_seconds: null }));
        await drafts.refresh();
        await tick();
        console.log(JSON.stringify({ hidden: panel().hidden, rows: rows().length }));
    """)
    assert out["hidden"] is True and out["rows"] == 0


def test_one_staged_draft_opens_the_panel_with_nobody_clicking_anything(sandbox):
    """The whole failure being fixed is that mail was held where nobody looked.
    A surface that has to be found is the same bug with a shorter path."""
    out = _run(sandbox, f"""
        mockFetch(() => res(200, {{ pending: [{json.dumps(_draft())}], count: 1,
                                    oldest_age_seconds: 120 }}));
        await drafts.refresh();
        await tick();
        console.log(JSON.stringify({{
          hidden: panel().hidden,
          rows: rows().length,
          state: byId('agent-drafts-state').textContent,
          count: byId('agent-drafts-count').textContent,
        }}));
    """)
    assert out["hidden"] is False
    assert out["rows"] == 1
    assert out["count"] == "1"
    assert "holding" in out["state"].lower()
    assert "nothing has been sent" in out["state"].lower()


def test_a_failed_poll_does_not_empty_the_panel(sandbox):
    """Hiding held mail because one request failed is the original bug in
    miniature: the drafts are still staged, and the user now has no way to see
    that they are."""
    out = _run(sandbox, f"""
        mockFetch(() => res(200, {{ pending: [{json.dumps(_draft())}], count: 1 }}));
        await drafts.refresh();
        await tick();
        const before = {{ hidden: panel().hidden, rows: rows().length }};
        boom();
        await drafts.refresh();
        await tick();
        console.log(JSON.stringify({{ before, after: {{ hidden: panel().hidden, rows: rows().length }} }}));
    """)
    assert out["before"] == {"hidden": False, "rows": 1}
    assert out["after"] == {"hidden": False, "rows": 1}


# ── what a card has to show before you can act on it ────────────────────────

def test_every_recipient_is_shown_including_bcc(sandbox):
    """A blind carbon copy you cannot see before pressing Send is a worse
    failure than the black hole this replaces — and the endpoint did not return
    `cc`/`bcc` at all until this row, so the card would have hidden the one
    field you most need."""
    d = _draft(cc="cc@example.test", bcc="secret@example.test")
    out = _run(sandbox, f"""
        mockFetch(() => res(200, {{ pending: [{json.dumps(d)}], count: 1 }}));
        await drafts.refresh();
        await tick();
        console.log(JSON.stringify(rows()[0]));
    """)
    assert "someone@example.test" in out["text"]
    assert "cc@example.test" in out["text"]
    assert "secret@example.test" in out["text"]
    assert any("agent-draft-has-bcc" in c for c in out["classes"]), \
        "a bcc is present and the row does not mark it"


def test_the_body_is_on_the_card_before_approval_is_possible(sandbox):
    """Approving sends real mail, composed by a model, possibly a year ago. A
    card showing only a subject would be asking for a signature on an unread
    document."""
    d = _draft(body="Please wire the deposit to the account below.")
    out = _run(sandbox, f"""
        mockFetch(() => res(200, {{ pending: [{json.dumps(d)}], count: 1 }}));
        await drafts.refresh();
        await tick();
        console.log(JSON.stringify(rows()[0]));
    """)
    assert "wire the deposit" in out["text"]


def test_a_long_body_is_truncated_but_can_be_opened_in_full(sandbox):
    long_body = "x" * 900 + "END-OF-MESSAGE"
    d = _draft(body=long_body)
    out = _run(sandbox, f"""
        mockFetch(() => res(200, {{ pending: [{json.dumps(d)}], count: 1 }}));
        await drafts.refresh();
        await tick();
        const truncated = rows()[0].text.includes('END-OF-MESSAGE');
        clickButton(0, 'Show full message');
        await tick();
        console.log(JSON.stringify({{ truncated, full: rows()[0].text.includes('END-OF-MESSAGE') }}));
    """)
    assert out["truncated"] is False, "the whole body was rendered without asking"
    assert out["full"] is True, "there is no way to read the rest of it"


def test_the_age_is_on_every_card_and_is_coarse(sandbox):
    """The row's gating question was *is this backlog a week or a year*, because
    the answer changes what the user should do. Nobody needs '11 months, 3 days'
    — they need to know it is months."""
    out = _run(sandbox, f"""
        const mk = (id, age) => Object.assign({json.dumps(_draft())}, {{ id, age_seconds: age }});
        mockFetch(() => res(200, {{ pending: [mk('a', 30), mk('b', 3600 * 5),
                                              mk('c', 86400 * 400), mk('d', 86400 * 800)],
                                    count: 4, oldest_age_seconds: 86400 * 800 }}));
        await drafts.refresh();
        await tick();
        console.log(JSON.stringify({{ rows: rows().map(r => r.text), state: byId('agent-drafts-state').textContent }}));
    """)
    joined = "\n".join(out["rows"])
    assert "just now" in joined
    assert "5 hrs ago" in joined
    assert "13 months ago" in joined, "400 days should read as months, not days or years"
    assert "2 years ago" in joined
    assert "2 years ago" in out["state"], "the oldest age is not on the panel headline"


@pytest.mark.parametrize("seconds,expected", [
    (0, "just now"), (89, "just now"),
    # The singulars, and every one of these is reachable: the bands hand over at
    # 90s, 90min, 36hr and 24 months, so "1 min", "1 hr", "1 day" and "1 year"
    # all occur. ("1 month" does not — months begin at 60 days.) Without them
    # the plural rule can be deleted entirely and every assertion still passes,
    # which is how "1 years ago" survived the first mutation run.
    (90, "1 min ago"),
    (60 * 90, "1 hr ago"),
    (3600 * 36, "1 day ago"),
    (86400 * 730, "2 years ago"),
    (86400 * 366, "12 months ago"),
    (60 * 60, "60 mins ago"),
    (60 * 60 * 2, "2 hrs ago"),
    (86400 * 2, "2 days ago"),
    (86400 * 90, "3 months ago"),
    (86400 * 365 * 3, "3 years ago"),
])
def test_the_age_reads_as_english(sandbox, seconds, expected):
    """It said "1 years ago". A panel whose whole job is to make an age
    legible should not be the thing that reads as a machine."""
    out = _run(sandbox, f"""
        const d = Object.assign({json.dumps(_draft())}, {{ age_seconds: {seconds} }});
        mockFetch(() => res(200, {{ pending: [d], count: 1 }}));
        await drafts.refresh();
        await tick();
        console.log(JSON.stringify({{ text: rows()[0].text }}));
    """)
    assert expected in out["text"]


# ── the two buttons ─────────────────────────────────────────────────────────

def test_approve_posts_to_the_approve_route(sandbox):
    out = _run(sandbox, f"""
        let listed = 0;
        mockFetch((url, opts) => {{
          if (url.includes('/approve')) return res(200, {{ success: true }});
          listed += 1;
          return res(200, {{ pending: listed > 1 ? [] : [{json.dumps(_draft())}], count: listed > 1 ? 0 : 1 }});
        }});
        await drafts.refresh();
        await tick();
        clickButton(0, 'Approve & send');
        await tick(12);
        console.log(JSON.stringify({{ calls: calls.fetch, hidden: panel().hidden }}));
    """)
    approve = [c for c in out["calls"] if "/approve" in c["url"]]
    assert len(approve) == 1
    assert approve[0]["method"] == "POST"
    assert approve[0]["url"].endswith("/api/email/pending/d1/approve")
    assert out["hidden"] is True, "the panel did not close after the last draft was handled"


def test_discard_deletes_the_draft(sandbox):
    out = _run(sandbox, f"""
        let listed = 0;
        mockFetch((url, opts) => {{
          if (opts.method === 'DELETE') return res(200, {{ success: true }});
          listed += 1;
          return res(200, {{ pending: listed > 1 ? [] : [{json.dumps(_draft())}], count: listed > 1 ? 0 : 1 }});
        }});
        await drafts.refresh();
        await tick();
        clickButton(0, 'Discard');
        await tick(12);
        console.log(JSON.stringify({{ calls: calls.fetch }}));
    """)
    dele = [c for c in out["calls"] if c["method"] == "DELETE"]
    assert len(dele) == 1
    assert dele[0]["url"].endswith("/api/email/pending/d1")


def test_a_refused_approval_leaves_the_draft_where_it_is_and_says_so(sandbox):
    out = _run(sandbox, f"""
        mockFetch((url) => {{
          if (url.includes('/approve')) return res(200, {{ success: false, error: 'Draft not found or already handled' }});
          return res(200, {{ pending: [{json.dumps(_draft())}], count: 1 }});
        }});
        await drafts.refresh();
        await tick();
        clickButton(0, 'Approve & send');
        await tick(12);
        console.log(JSON.stringify({{ state: byId('agent-drafts-state').textContent, rows: rows().length }}));
    """)
    assert out["rows"] == 1
    assert "already handled" in out["state"]


def test_there_is_no_approve_all(sandbox):
    """Discard is bulk and approve is not. A button that sends hundreds of
    year-old model-composed emails to real people in one press is the auto-send
    hole `agent_email_confirm` exists to close, rebuilt with a dialog in front
    of it."""
    labels = _run(sandbox, f"""
        const mk = (id) => Object.assign({json.dumps(_draft())}, {{ id }});
        mockFetch(() => res(200, {{ pending: [mk('a'), mk('b'), mk('c')], count: 3 }}));
        await drafts.refresh();
        await tick();
        const all = list()._walk([]).filter(n => n.tagName === 'BUTTON').map(b => b.textContent);
        console.log(JSON.stringify({{ labels: all }}));
    """)["labels"]
    joined = " ".join(labels).lower()
    assert "approve all" not in joined
    assert labels.count("Approve & send") == 3
    # The bulk control is static markup, so it is asserted where it lives —
    # reading it off the shim node would only prove the shim has no text.
    markup = _panel_markup().lower()
    assert "discard all" in markup
    assert "approve all" not in markup


def test_discard_all_asks_first_and_does_nothing_when_refused(sandbox):
    out = _run(sandbox, f"""
        const mk = (id) => Object.assign({json.dumps(_draft())}, {{ id }});
        mockFetch(() => res(200, {{ pending: [mk('a'), mk('b')], count: 2 }}));
        await drafts.refresh();
        await tick();
        setConfirm(false);
        byId('agent-drafts-discard-all').click();
        await tick(10);
        console.log(JSON.stringify({{
          confirms: calls.confirms,
          posts: calls.fetch.filter(c => c.url.includes('discard-all')).length,
          rows: rows().length,
        }}));
    """)
    assert len(out["confirms"]) == 1
    assert "2 drafts" in out["confirms"][0]
    assert out["posts"] == 0, "it discarded without a yes"
    assert out["rows"] == 2


def test_discard_all_is_absent_for_a_single_draft(sandbox):
    out = _run(sandbox, f"""
        mockFetch(() => res(200, {{ pending: [{json.dumps(_draft())}], count: 1 }}));
        await drafts.refresh();
        await tick();
        console.log(JSON.stringify({{ hidden: byId('agent-drafts-discard-all').hidden }}));
    """)
    assert out["hidden"] is True


# ── the claims that were false for a year ───────────────────────────────────

def test_the_frontend_actually_references_the_endpoints(sandbox):
    """The grep that opened this row:

        grep -rn "email/pending|agent_draft" static/    →    nothing

    across 183 files, while three places said a surface existed. This is that
    grep, inverted, so it can never come back clean.
    """
    hits = []
    for f in (ROOT / "static").rglob("*.js"):
        if "lib" in f.parts:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if "email/pending" in text:
            hits.append(f.relative_to(ROOT).as_posix())
    assert hits, "no frontend file references /api/email/pending"


def test_the_models_promise_is_true(sandbox):
    """The worst of the three false claims: `src/agent_loop.py` TELLS the model
    to tell the user their mail "stages for the user to approve in the chat
    UI". If that sentence survives, the surface must too — otherwise the agent
    is again promising a screen nobody built.
    """
    loop = (ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8")
    promises = loop.count("approve in the chat UI")
    if not promises:
        pytest.skip("the model is no longer told there is an approval UI")
    markup = INDEX.read_text(encoding="utf-8")
    assert 'id="agent-drafts-panel"' in markup
    assert MODULE.exists()
    js = MODULE.read_text(encoding="utf-8")
    assert "/api/email/pending" in js


def _chat_js_code() -> str:
    """`static/js/chat.js` with comments stripped.

    The comment beside the wiring explains what the panel is for, so a substring
    search finds the identifier whether or not the call survives — the trap that
    has caught this project four times now (`B32`, `B33`, and twice in
    `P16-12`).
    """
    src = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return "\n".join(ln for ln in src.splitlines()
                      if not ln.lstrip().startswith("//"))


def test_something_actually_starts_the_panel():
    """`Law 15`, which is the law this row exists because of. A surface nobody
    starts is the same defect as the three endpoints nobody called — and the
    mutation that deleted this call survived every test in this file, because
    they all import the module directly and never go through `chat.js`.
    """
    code = _chat_js_code()
    assert "from './agentDrafts.js'" in code, "chat.js does not import the panel"
    assert re.search(r"agentDrafts\s*\.\s*start\s*\(", code), \
        "chat.js imports the panel and never starts it"


def test_the_panel_is_started_without_a_setting_or_a_click_in_front_of_it():
    """It must not be behind a feature flag or a menu. The failure being fixed
    is that email was held where nobody looked; a surface that has to be
    switched on is the same bug with an extra step."""
    code = _chat_js_code()
    match = re.search(r"agentDrafts\s*\.\s*start\s*\(", code)
    assert match
    window = code[max(0, match.start() - 400):match.start()]
    for gate in ("get_setting", "featureEnabled", "if (settings", "localStorage.getItem"):
        assert gate not in window, f"the panel is gated on {gate!r}"


def test_no_innerHTML_anywhere_on_these_cards():
    """Every field on a draft card is model-written text derived from email that
    arrived from outside. The shim above has no `innerHTML` at all, so an
    assignment would throw under node — this asserts it at the source too, so a
    reviewer does not have to trust that the shim stayed incomplete."""
    js = MODULE.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    code = "\n".join(ln for ln in code.splitlines() if not ln.strip().startswith("//"))
    assert "innerHTML" not in code
    assert "insertAdjacentHTML" not in code


def test_the_panel_reuses_the_queue_panels_shell_rather_than_a_second_one():
    """`Law 14`. This is one more thing docked above the composer, not a second
    visual language for the same idea — so the shell classes are the queue
    panel's and only the row vocabulary is new."""
    markup = _panel_markup()
    for shared in ("queue-panel", "queue-panel-head", "queue-panel-body",
                   "queue-panel-list", "queue-panel-fold"):
        assert shared in markup, f"{shared} not reused"
    css = STYLE.read_text(encoding="utf-8")
    assert ".agent-draft-row" in css


def test_the_stylesheet_never_defines_accent_in_root():
    """Protected territory. The sixteen themes own `--accent`; a definition in
    `:root` would freeze every one of them to the same colour."""
    css = STYLE.read_text(encoding="utf-8")
    assert not re.search(r":root\s*\{[^}]*--accent\s*:", css)
