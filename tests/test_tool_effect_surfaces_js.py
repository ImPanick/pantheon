# SPDX-License-Identifier: AGPL-3.0-or-later
"""P7-06 / P6-11 — what a tool can do, on the two surfaces that show it.

`describe_effects()` (`src/tool_capabilities.py`) ranks a tool's effects and
resolves the English once. Two frontend surfaces consume it and neither may
own a second copy of the ordering or of the words:

  * the approval card (`static/js/chatRenderer.js`), which used to print
    `Effects: destructive, external_side_effect` in exactly the grey text, at
    exactly the size, that `Effects: ui_side_effect` got — the defect `P7-06`
    names;
  * the docked plan window (`static/js/planWindow.js`), whose fifth per-step
    field never shipped.

Driven under node against the real files, in the sandbox pattern
`tests/test_chat_steer_js.py` established: stub modules plus a DOM shim beside
a copy of the unmodified source, which is then imported and exercised. The CSS
cannot be driven that way, so the rules that carry the non-colour half of the
distinction are read out of `static/style.css` — as a supplement to the
behavioural assertions, never as a substitute for one.

What is pinned, and why each is a defect if it breaks:

  * a destructive action and a UI side effect no longer produce the same card,
    and what separates them is wording and type size before it is hue — colour
    alone fails a colour-blind reader, which is a `Law 15` failure and not a
    decoration bug;
  * the ranked lead is what the card leads with, even when the sealed record's
    own (alphabetical) order disagrees;
  * every one of these fields is optional on the wire, so a payload carrying
    none of them must render a working card and must never print "undefined";
  * a raw-valued payload is shown undressed rather than given invented English;
  * the phrase reaches the DOM as text and never as markup — on the one card
    in the app whose whole job is to describe an action truthfully;
  * a card rebuilt from a saved session reads the same as the live one, and
    knows which of the two places a persisted event can hold the presentation
    outranks the other;
  * `update_plan` / `ask_user` are bookkeeping and cannot overwrite a real
    step's effect — the trap `BOOKKEEPING_TOOLS` exists for;
  * a genuinely new plan drops the previous plan's per-step effect, or step 3
    inherits step 3 of a plan that never ran;
  * the band ladder in the stylesheet differs in *values* a reader can see, at
    both narrow breakpoints as well as on a desktop, and the most serious
    phrase is never rendered less legible than the most harmless one in any of
    the sixteen shipped themes.

Sections marked CORRECTED or REWRITTEN carry, in place, what the previous
version claimed and why refutation showed it was not enough. The programme
keeps its corrections rather than quietly replacing them.
"""

import functools
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from tests.helpers.source_text import blank, blank_text  # B290

ROOT = Path(__file__).resolve().parents[1]
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"
PLAN_WINDOW = ROOT / "static" / "js" / "planWindow.js"
STYLE = ROOT / "static" / "style.css"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── DOM shim ────────────────────────────────────────────────────────────────
# Only what these two modules touch. Shared by both sandboxes so a node built
# for one surface behaves identically on the other.

_DOM = r"""
export class Node {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.className = ''; this.id = ''; this.value = ''; this.title = '';
    this.type = ''; this.disabled = false; this.hidden = false;
    this.tabIndex = 0; this.focused = false; this.scrollTop = 0;
    this.scrolledIntoView = false; this.placeholder = '';
    this.childNodes = []; this.parentNode = null;
    this.dataset = {}; this.attrs = {}; this.listeners = {};
    // `setProperty` because the history renderer paints a per-model role colour
    // through it; plain assignment (`style.display = ...`) is used elsewhere and
    // still works, so both spellings have to exist on the same object.
    this.style = {
      setProperty(k, v) { this[k] = v; },
      removeProperty(k) { delete this[k]; },
      getPropertyValue(k) { return this[k] === undefined ? '' : this[k]; },
    };
    this._text = ''; this._html = '';
    const self = this;
    this.classList = {
      add(...cs) {
        cs.forEach((c) => { if (!self._classes().includes(c)) self.className = (self.className + ' ' + c).trim(); });
      },
      remove(...cs) { self.className = self._classes().filter((c) => !cs.includes(c)).join(' '); },
      contains(c) { return self._classes().includes(c); },
      toggle(c, on) {
        const want = on === undefined ? !self._classes().includes(c) : !!on;
        if (want) this.add(c); else this.remove(c);
      },
    };
  }
  _classes() { return String(this.className || '').split(/\s+/).filter(Boolean); }
  get children() { return this.childNodes.filter((n) => n.tagName !== '#TEXT'); }
  set textContent(v) { this.childNodes = []; this._html = ''; this._text = String(v == null ? '' : v); }
  get textContent() {
    return this.childNodes.length
      ? this.childNodes.map((c) => c.textContent).join('')
      : (this._text || this._html.replace(/<[^>]*>/g, ''));
  }
  set innerHTML(v) { this.childNodes = []; this._text = ''; this._html = String(v == null ? '' : v); }
  get innerHTML() { return this._html; }
  /** Text with node boundaries preserved, so adjacent chips never read as one word. */
  get readable() {
    return (this.childNodes.length
      ? this.childNodes.map((c) => c.readable).join(' ')
      : this.textContent).replace(/\s+/g, ' ').trim();
  }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') this.id = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  appendChild(n) {
    if (n.tagName === '#FRAGMENT') { n.childNodes.slice().forEach((c) => this.appendChild(c)); n.childNodes = []; return n; }
    if (this.childNodes.length === 0 && (this._text || this._html)) { this._text = ''; this._html = ''; }
    n.parentNode = this; this.childNodes.push(n); return n;
  }
  removeChild(n) {
    const i = this.childNodes.indexOf(n);
    if (i >= 0) this.childNodes.splice(i, 1);
    n.parentNode = null; return n;
  }
  // Added 2026-09-18 by `P8-06`. A panel built with `createElement` swaps its
  // whole contents in one call rather than clearing with `innerHTML = ''`,
  // which is the discipline `H01` set for any surface printing user-written
  // text. Without it the real module throws on a method the browser has.
  replaceChildren(...kids) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = []; this._text = ''; this._html = '';
    for (const k of kids) this.appendChild(k);
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  removeEventListener(t, fn) {
    const a = this.listeners[t] || []; const i = a.indexOf(fn); if (i >= 0) a.splice(i, 1);
  }
  dispatchEvent(ev) { (this.listeners[ev.type] || []).slice().forEach((fn) => fn(ev)); return true; }
  focus() { this.focused = true; }
  scrollIntoView() { this.scrolledIntoView = true; }
  closest() { return null; }
  _walk(out) { for (const c of this.childNodes) { out.push(c); c._walk(out); } return out; }
  _matches(sel) {
    let p = String(sel).trim();
    let attr = null;
    const am = p.match(/\[([a-zA-Z-]+)(?:="([^"]*)")?\]/);
    if (am) { attr = am; p = p.replace(am[0], ''); }
    const idm = p.match(/#([A-Za-z0-9_-]+)/);
    if (idm) { if (this.id !== idm[1]) return false; p = p.replace(idm[0], ''); }
    const classes = (p.match(/\.[A-Za-z0-9_-]+/g) || []).map((c) => c.slice(1));
    const tag = p.replace(/\.[A-Za-z0-9_-]+/g, '').trim();
    if (tag && this.tagName !== tag.toUpperCase()) return false;
    for (const c of classes) if (!this._classes().includes(c)) return false;
    if (attr) {
      let actual = this.getAttribute(attr[1]);
      if (actual == null && attr[1].startsWith('data-')) {
        const key = attr[1].slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase());
        actual = this.dataset[key];
      }
      if (actual == null) return false;
      if (attr[2] !== undefined && actual !== attr[2]) return false;
    }
    return true;
  }
  querySelectorAll(sel) {
    const parts = String(sel).split(',').map((s) => s.trim()).filter(Boolean);
    return this._walk([]).filter((n) => parts.some((p) => n._matches(p)));
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

function defineGlobal(name, value) {
  Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}

export function installDom() {
  const document = new Node('#document');
  document.head = document.appendChild(new Node('head'));
  document.body = document.appendChild(new Node('body'));
  document.createElement = (tag) => new Node(tag);
  document.createElementNS = (ns, tag) => new Node(tag);
  document.createTextNode = (text) => { const n = new Node('#text'); n.textContent = text; return n; };
  document.createDocumentFragment = () => new Node('#fragment');
  document.getElementById = (id) => document._walk([]).find((n) => n.id === id) || null;
  document.hidden = false;
  document.activeElement = null;
  globalThis.document = document;
  globalThis.Node = Node;
  defineGlobal('window', globalThis);
  defineGlobal('location', { origin: 'http://test.local' });
  defineGlobal('navigator', { platform: 'Linux x86_64' });
  globalThis.CustomEvent = class { constructor(t, i) { this.type = t; this.detail = (i || {}).detail; } };
  globalThis.Event = class { constructor(t) { this.type = t; } };
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ tools: [] }) });

  const store = new Map();
  defineGlobal('localStorage', {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)); },
    removeItem: (k) => { store.delete(k); },
  });
  defineGlobal('sessionStorage', { getItem: () => null, removeItem: () => {}, setItem: () => {} });

  // The plan window starts a 1s ticker while a plan is executing; an un-unref'd
  // handle would keep node alive past the end of the case.
  const realInterval = globalThis.setInterval;
  globalThis.setInterval = (fn, ms) => { const t = realInterval(fn, ms); if (t && t.unref) t.unref(); return t; };
  return document;
}
"""

# ── Approval card sandbox ───────────────────────────────────────────────────

_CARD_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

const history = document.body.appendChild(new Node('div'));
history.setAttribute('id', 'chat-history');
export { history };

/** A fresh root per card, so rendering the second does not retire the first. */
export function root() {
  const box = document.body.appendChild(new Node('div'));
  box.className = 'card-root';
  return box;
}

export function approvalPayload(overrides) {
  return Object.assign({
    kind: 'tool_approval',
    approval_id: 'ap-1',
    question: 'Allow this task to continue?',
    options: [
      { label: 'Allow for this task', value: 'approve_task', description: 'Execute the sealed action.' },
      { label: 'Deny', value: 'deny', description: 'Do not execute the proposed action.' },
    ],
  }, overrides || {});
}

export function describeCard(card) {
  if (!card) return null;
  const box = card.querySelector('.approval-effects');
  const rows = card.querySelectorAll('.approval-effect');
  const lead = card.querySelector('.approval-effect-lead');
  const phraseNode = (row) => row.querySelector('.approval-effect-text');
  return {
    hasBox: !!box,
    band: box ? (box.dataset.effectBand || null) : null,
    title: box ? (card.querySelector('.approval-effects-title').textContent) : '',
    lead: lead ? phraseNode(lead).textContent : '',
    leadIsFirst: !!(lead && rows.length && rows[0] === lead),
    phrases: rows.map((r) => phraseNode(r).textContent),
    // The RAW `_html` behind each phrase, deliberately not read through the
    // `textContent` getter above it. That getter falls back to stripping tags
    // out of `_html`, so a phrase assigned through `innerHTML` reads back
    // identically and a switch away from `textContent` is invisible to every
    // assertion that goes through text — refutation shipped exactly that
    // mutation past a full green run. `_html` is '' if and only if the
    // renderer used `textContent`, which is the property actually under test.
    html: rows.map((r) => phraseNode(r)._html),
    raw: rows.map((r) => r._classes().includes('approval-effect-raw')),
    text: card.readable,
  };
}

/**
 * The approval card a session reload rebuilds out of one persisted tool event.
 *
 * `addMessage` is passed in rather than imported so this module stays free of
 * the file under test; the sandbox copies that file in beside it.
 */
export function reloadHistory(addMessage, event) {
  history.childNodes = [];
  addMessage('assistant', 'Working on it.', 'test-model', {
    round_texts: ['Working on it.'],
    tool_events: [Object.assign({
      round: 1,
      tool: 'write_file',
      command: '/etc/hosts',
      output: 'Waiting for an exact user approval.',
      exit_code: null,
    }, event)],
  });
  return history.querySelector('.ask-user-card');
}
"""

_CARD_STUBS = {
    "ui.js": """
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
export default {
  esc, showToast: () => {}, showError: () => {}, copyToClipboard: () => {},
  el: (id) => document.getElementById(id), debounce: (f) => f,
  autoResize: () => {}, scrollHistory: () => {}, formatBytes: (n) => String(n),
};
""",
    "markdown.js": """
export function svgifyEmoji(s) { return String(s == null ? '' : s); }
export default {
  renderContent: (c) => String(c), mdToHtml: (s) => String(s),
  processWithThinking: (s) => String(s), squashOutsideCode: (s) => String(s),
};
""",
    "tts-ai.js": "export function addAITTSButton(){}\n",
    "providers.js": "export function providerLogo(){return '';}\nexport function providerLabel(){return '';}\n",
    "settings.js": "export default { get: () => ({}) };\n",
    "spinner.js": """
export function createLoadingRow(){return {};}
export function createWhirlpool(){return { element: { style: {} }, destroy(){} };}
export default { createWhirlpool: () => ({ element: { style: {} }, destroy(){} }) };
""",
    "escMenuStack.js": "export function bindMenuDismiss(){return () => {};}\nexport function dismissOrRemove(){}\n",
    "panels.js": "export function loadPanel(){}\n",
    "appConfig.js": "export function getTools(){return Promise.resolve({ tools: [] });}\nexport function getSettings(){return Promise.resolve({});}\n",
    "model/matchKey.js": "export function matchModelKey(){return null;}\n",
    # ADDED 2026-08-29 by P7-03/P7-04. `chatRenderer.js` now imports the
    # approval card's allow-rule scope chooser from `static/js/trustLadder.js`;
    # without this entry every case in this file dies on an unresolved import.
    # Stubbed to "no chooser", which is also what the real module returns
    # whenever the rule store is absent or the trust rung is not `allow_listed`
    # — so the cards these tests build are exactly the ones a default install
    # renders. The chooser itself is covered against the real module in
    # `tests/test_trust_ladder_js.py`.
    "trustLadder.js": "export function buildAllowRuleChooser(){ return null; }\n",
}

# ── Plan window sandbox ─────────────────────────────────────────────────────

_PLAN_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();

// Derived from static/index.html, not transcribed. `collectEls()` refuses to
// draw a window that is missing ANY of its elements, so a hand-kept list here
// turns "index.html gained a span" into nine failures in a file about tool
// effects. It already had: this list went stale the moment `B11` added the
// title and blurb ids, and the test that noticed was this one.
const IDS = __PLAN_WINDOW_IDS__;
const root = document.body.appendChild(new Node('div'));
for (const id of IDS) {
  const n = root.appendChild(new Node(id === 'plan-window-steps' ? 'ul' : 'div'));
  n.setAttribute('id', id);
}
export { root };

export function stepRows() {
  return document.getElementById('plan-window-steps').children;
}

/** What the window says about one step, as a person would read it off the row. */
export function readStep(i) {
  const row = stepRows()[i];
  if (!row) return null;
  const effect = row.querySelector('.plan-step-effect');
  return {
    text: row.querySelector('.task-text').textContent,
    effect: effect ? effect.textContent : null,
    band: effect ? (effect.dataset.effectBand || null) : null,
    tool: row.querySelector('.plan-step-tool') ? row.querySelector('.plan-step-tool').textContent : null,
    /** Position of the effect chip among the row's chips — 0 means it leads. */
    chipIndex: effect ? row.querySelectorAll('.plan-step-chip').indexOf(effect) : -1,
    row: row.readable,
  };
}
"""

_PLAN_STUBS = {
    "storage.js": """
const mem = { blob: null, toggles: {} };
export function setToggles(t) { mem.toggles = t || {}; }
export default {
  getJSON: (k, fallback) => (mem.blob === null ? fallback : JSON.parse(JSON.stringify(mem.blob))),
  setJSON: (k, v) => { mem.blob = JSON.parse(JSON.stringify(v)); },
  remove: () => { mem.blob = null; },
  loadToggleState: () => mem.toggles,
  KEYS: { TOGGLES: 'toggles' },
};
""",
}


# `import … from './x.js'` AND `export { … } from './x.js'`. The re-export form
# was invisible here until `B83` used one: `checklist.js` re-exports the play
# triangle from the shared icon table, and a sandbox that copied the first file
# and not the second failed at module resolution rather than at an assertion.
_RELATIVE_IMPORT = re.compile(
    r"""^\s*(?:import|export)\s[^'"]*['"]\.\/([^'"?]+)""", re.M)


def _copy_unstubbed_imports(directory: Path, source: Path, stubs: dict) -> None:
    """Copy any local module the source imports that has no stub.

    Every sandbox here hand-writes a stub per import, which means **adding one
    import to a sandboxed module breaks every sandbox that copies it**, with a
    node resolution error that names a path in a temp directory and nothing
    about the cause. `P1-12` added a four-line `./motion.js` to `theme.js` and
    took 54 assertions down across two files.

    So: a stub still wins where one exists — that is how these sandboxes keep
    `storage.js` in memory and `ui.js` silent — and anything else is copied
    from `static/js/` for real, transitively. A dependency-free helper then
    costs nothing, and a heavy new import fails loudly on its own missing
    globals rather than on a path, which is the right way round.
    """
    js_root = source.parent
    seen, queue = set(), [source]
    while queue:
        current = queue.pop()
        try:
            text = current.read_text(encoding="utf-8")
        except OSError:
            continue
        for rel in _RELATIVE_IMPORT.findall(text):
            if rel in stubs or rel in seen:
                continue
            seen.add(rel)
            real = js_root / rel
            if not real.is_file():
                continue
            target = directory / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(real, target)
            queue.append(real)


def _make_sandbox(directory: Path, source: Path, shim: str, stubs: dict) -> Path:
    (directory / "dom.js").write_text(_DOM)
    (directory / "shim.js").write_text(shim)
    for name, src in stubs.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(src)
    shutil.copy(source, directory / source.name)
    _copy_unstubbed_imports(directory, source, stubs)
    return directory


@pytest.fixture(scope="module")
def card_sandbox(tmp_path_factory):
    return _make_sandbox(
        tmp_path_factory.mktemp("effectcard"), CHAT_RENDERER, _CARD_SHIM, _CARD_STUBS
    )


def _plan_window_ids() -> list:
    """Every `id` inside `<section id="plan-window">` in the shipped markup."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    start = html.index('<section id="plan-window"')
    end = html.index("</section>", start)
    ids = re.findall(r'\bid="([^"]+)"', html[start:end])
    assert "plan-window-steps" in ids, "the plan window markup moved"
    return ids


@pytest.fixture(scope="module")
def plan_sandbox(tmp_path_factory):
    shim = _PLAN_SHIM.replace("__PLAN_WINDOW_IDS__", json.dumps(_plan_window_ids()))
    return _make_sandbox(
        tmp_path_factory.mktemp("effectplan"), PLAN_WINDOW, shim, _PLAN_STUBS
    )


def _run(sandbox: Path, preamble: str, script: str) -> dict:
    entry = sandbox / "case.mjs"
    entry.write_text(preamble + textwrap.dedent(script))
    proc = subprocess.run(
        ["node", str(entry)], cwd=sandbox, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])


_CARD_PREAMBLE = (
    "import { document, root, approvalPayload, describeCard, reloadHistory }"
    " from './shim.js';\n"
    "const { renderAskUserCard, addMessage } = await import('./chatRenderer.js');\n"
)
_PLAN_PREAMBLE = (
    "import { document, readStep, stepRows } from './shim.js';\n"
    "import { setToggles } from './storage.js';\n"
    "const planWindow = (await import('./planWindow.js')).default;\n"
)


def _card(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _CARD_PREAMBLE, script)


def _plan(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _PLAN_PREAMBLE, script)


# The shape `describe_effects()` puts on the wire. Written out here rather than
# imported so this file pins the contract the browser is built against, not
# whatever Python happens to return today.
_DESTRUCTIVE = """{
  action: {
    tool: 'write_file', content: '/etc/hosts', digest: 'ab12cd34',
    // The seal sorts for a stable digest, so its order is alphabetical.
    effects: ['admin_change', 'destructive'],
  },
  effect: 'destructive',
  effects: ['destructive', 'admin_change'],
  effect_label: 'Can permanently delete or overwrite',
  effect_labels: ['Can permanently delete or overwrite', 'Changes settings for everyone'],
  effect_severity: 130,
  effect_band: 'serious',
}"""

_UI = """{
  action: { tool: 'ui_control', content: '{"panel":"tasks"}', digest: 'ff00ff00', effects: ['ui_side_effect'] },
  effect: 'ui_side_effect',
  effects: ['ui_side_effect'],
  effect_label: 'Changes what is on screen',
  effect_labels: ['Changes what is on screen'],
  effect_severity: 10,
  effect_band: 'routine',
}"""


# ── Job 1: the approval card ────────────────────────────────────────────────

def test_a_destructive_card_and_a_ui_side_effect_card_do_not_read_alike(card_sandbox):
    out = _card("""
        const bad = renderAskUserCard(approvalPayload(%s), { root: root(), focus: false, scroll: false });
        const mild = renderAskUserCard(approvalPayload(%s), { root: root(), focus: false, scroll: false });
        console.log(JSON.stringify({ bad: describeCard(bad), mild: describeCard(mild) }));
    """ % (_DESTRUCTIVE, _UI), card_sandbox)

    bad, mild = out["bad"], out["mild"]
    assert bad["hasBox"] and mild["hasBox"]
    assert bad["lead"] == "Can permanently delete or overwrite"
    assert mild["lead"] == "Changes what is on screen"
    assert bad["lead"] != mild["lead"], "P7-06: the two cards must not say the same thing"
    assert bad["band"] == "serious" and mild["band"] == "routine"
    # The wording alone already separates them, before a single colour is read.
    assert "permanently delete" in bad["text"]
    assert "permanently delete" not in mild["text"]


def test_the_card_never_prints_the_enum_identifier_when_it_was_given_words(card_sandbox):
    out = _card("""
        const bad = renderAskUserCard(approvalPayload(%s), { root: root(), focus: false, scroll: false });
        const mild = renderAskUserCard(approvalPayload(%s), { root: root(), focus: false, scroll: false });
        console.log(JSON.stringify({ bad: describeCard(bad).text, mild: describeCard(mild).text }));
    """ % (_DESTRUCTIVE, _UI), card_sandbox)

    for blob in out.values():
        for identifier in ("destructive", "admin_change", "ui_side_effect", "Effects:"):
            assert identifier not in blob, f"{identifier!r} is a name for the code, not for a person"


def test_the_ranked_effect_leads_even_when_the_seal_disagrees(card_sandbox):
    # `admin_change` sorts before `destructive`, so a card that read the sealed
    # list would lead with the settings change and bury the deletion.
    out = _card("""
        const card = renderAskUserCard(approvalPayload(%s), { root: root(), focus: false, scroll: false });
        console.log(JSON.stringify(describeCard(card)));
    """ % _DESTRUCTIVE, card_sandbox)

    assert out["phrases"] == [
        "Can permanently delete or overwrite",
        "Changes settings for everyone",
    ]
    assert out["lead"] == "Can permanently delete or overwrite"
    assert out["leadIsFirst"] is True


def test_a_payload_with_no_effect_fields_at_all_still_renders(card_sandbox):
    out = _card("""
        const card = renderAskUserCard(approvalPayload({
          action: { tool: 'read_file', content: 'README.md', digest: '0011' },
        }), { root: root(), focus: false, scroll: false });
        console.log(JSON.stringify({
          drawn: !!card,
          detail: describeCard(card),
          options: card.querySelectorAll('.ask-user-option').length,
        }));
    """, card_sandbox)

    assert out["drawn"] is True, "an unclassified action must still be approvable"
    assert out["options"] == 2, "the card's controls survive a missing description"
    assert out["detail"]["hasBox"] is False, "nothing known means nothing claimed"
    assert "undefined" not in out["detail"]["text"]
    assert "null" not in out["detail"]["text"]
    assert "README.md" in out["detail"]["text"], "the sealed action is still shown verbatim"


def test_raw_sealed_values_are_shown_undressed_rather_than_invented(card_sandbox):
    # This is the payload the seal can produce on its own: values, no words.
    out = _card("""
        const card = renderAskUserCard(approvalPayload({
          action: { tool: 'write_file', content: '/etc/hosts', digest: 'ab12',
                    effects: ['admin_change', 'destructive'] },
        }), { root: root(), focus: false, scroll: false });
        console.log(JSON.stringify(describeCard(card)));
    """, card_sandbox)

    assert out["hasBox"] is True, "a listed effect is never silently dropped"
    assert out["band"] is None, "no band was sent, so none is claimed"
    assert out["raw"] == [True, True], "identifiers are marked as identifiers"
    assert out["phrases"] == ["admin_change", "destructive"]
    assert "undefined" not in out["text"]


_HOSTILE = "<img src=x onerror=alert(1)>&<b>bold</b>‮"


def test_a_phrase_is_written_as_text_and_never_as_markup(card_sandbox):
    """The dressed and the undressed row both go through `textContent`.

    Escaping was already correct when this was written; what was missing was
    anything holding it there. The assertion is on the phrase node's raw
    `_html`, not on its text: the DOM shim's `textContent` getter strips tags
    out of `_html` as a fallback, so a renderer that switched to `innerHTML`
    read back identically and the mutation survived all sixteen tests here.

    Both rows matter. The dressed phrase is prose from a fixed table in Python
    and is the less likely of the two to carry markup; the undressed one is an
    effect *value* off a persisted approval record. Neither is a place to
    render HTML — this card is where a user is asked to consent to an action,
    so markup in the sentence describing it forges the description of the very
    thing being approved.
    """
    out = _card("""
        const dressed = renderAskUserCard(approvalPayload({
          action: { tool: 'write_file', content: '/etc/hosts', digest: 'ab12',
                    effects: ['destructive'] },
          effect_label: %(hostile)s,
          effect_labels: [%(hostile)s, 'Changes settings for everyone'],
          effect_band: 'serious',
        }), { root: root(), focus: false, scroll: false });
        const undressed = renderAskUserCard(approvalPayload({
          action: { tool: 'write_file', content: '/etc/hosts', digest: 'ab12',
                    effects: [%(hostile)s] },
        }), { root: root(), focus: false, scroll: false });
        console.log(JSON.stringify({
          dressed: describeCard(dressed), undressed: describeCard(undressed),
        }));
    """ % {"hostile": json.dumps(_HOSTILE)}, card_sandbox)

    for name, detail in out.items():
        assert detail["html"] == [""] * len(detail["phrases"]), (
            f"{name}: the phrase was assigned as markup, not as text"
        )
        assert detail["phrases"][0] == _HOSTILE, (
            f"{name}: the hostile string must survive verbatim, not half-escaped"
        )
    assert out["undressed"]["raw"] == [True]


def test_a_four_hundred_character_phrase_does_not_break_the_card(card_sandbox):
    # An unbroken run with no space is what an overflow rule has to survive;
    # `overflow-wrap: anywhere` on `.approval-effect` is what handles it, and
    # the card must still be answerable either way.
    out = _card("""
        const long = 'x'.repeat(400);
        const card = renderAskUserCard(approvalPayload({
          action: { tool: 'write_file', content: '/etc/hosts', digest: 'ab12',
                    effects: ['destructive'] },
          effect_label: long, effect_labels: [long], effect_band: 'serious',
        }), { root: root(), focus: false, scroll: false });
        console.log(JSON.stringify({
          detail: describeCard(card),
          options: card.querySelectorAll('.ask-user-option').length,
        }));
    """, card_sandbox)

    assert out["detail"]["lead"] == "x" * 400
    assert out["detail"]["html"] == [""]
    assert out["options"] == 2, "the controls survive a phrase that outgrows the box"


def test_the_effects_are_read_before_the_technical_block(card_sandbox):
    out = _card("""
        const card = renderAskUserCard(approvalPayload(%s), { root: root(), focus: false, scroll: false });
        const kids = card.children.map((c) => c.className);
        console.log(JSON.stringify({
          effectsAt: kids.indexOf('approval-effects'),
          detailAt: kids.indexOf('ask-user-option-desc'),
          optionsAt: kids.indexOf('ask-user-options'),
        }));
    """ % _DESTRUCTIVE, card_sandbox)

    assert out["effectsAt"] >= 0
    assert out["effectsAt"] < out["detailAt"] < out["optionsAt"], (
        "the consequence decides the answer, so it comes before the machine detail"
    )


# ── Job 1b: the same card, rebuilt from a saved session ─────────────────────
#
# `addMessage` reconstructs an unanswered approval out of `metadata.tool_events`
# when a session is reloaded. It is a separate block of code from the live
# render, it is the path a user hits after closing the tab on a question, and
# until this section existed it had no test at all — refutation deleted the
# merge that feeds it and all sixteen tests here still passed.
#
# There are two places a persisted event can hold the presentation and the
# precedence between them is the thing worth pinning:
#
#   * inside `ask_user`, which is `PendingToolApproval.public_payload()` and is
#     shared by every producer of an approval card — this is where it lives now
#     and it wins;
#   * on the event itself, from the `**block_effects` spread in `agent_loop` —
#     the only copy a session saved before the payload carried it will have.

_RELOADED_KEYS = """{
  effect: 'destructive',
  effects: ['destructive', 'admin_change'],
  effect_label: 'Can permanently delete or overwrite',
  effect_labels: ['Can permanently delete or overwrite', 'Changes settings for everyone'],
  effect_severity: 130,
  effect_band: 'serious',
}"""

_SEALED_ACTION = """{
  tool: 'write_file', content: '/etc/hosts', digest: 'ab12cd34',
  effects: ['admin_change', 'destructive'],
}"""


def test_a_reloaded_card_reads_the_presentation_off_the_payload(card_sandbox):
    out = _card("""
        const card = reloadHistory(addMessage, {
          ask_user: approvalPayload(Object.assign(
            { action: %s }, %s,
          )),
        });
        console.log(JSON.stringify({ drawn: !!card, detail: describeCard(card) }));
    """ % (_SEALED_ACTION, _RELOADED_KEYS), card_sandbox)

    assert out["drawn"] is True, "an unanswered approval survives the reload"
    assert out["detail"]["band"] == "serious"
    assert out["detail"]["lead"] == "Can permanently delete or overwrite"
    assert out["detail"]["raw"] == [False, False], "the words arrived; nothing is undressed"
    assert out["detail"]["phrases"] == [
        "Can permanently delete or overwrite",
        "Changes settings for everyone",
    ]


def test_a_reloaded_card_falls_back_to_the_events_own_keys(card_sandbox):
    # A session saved before the presentation moved into `public_payload()`.
    out = _card("""
        const card = reloadHistory(addMessage, Object.assign({
          ask_user: approvalPayload({ action: %s }),
        }, %s));
        console.log(JSON.stringify({ drawn: !!card, detail: describeCard(card) }));
    """ % (_SEALED_ACTION, _RELOADED_KEYS), card_sandbox)

    assert out["drawn"] is True
    assert out["detail"]["band"] == "serious", (
        "the event's own keys are the only copy this session has; dropping them "
        "sends the reader back to raw identifiers"
    )
    assert out["detail"]["lead"] == "Can permanently delete or overwrite"
    assert out["detail"]["raw"] == [False, False]


def test_the_payloads_own_presentation_outranks_the_events_copy(card_sandbox):
    # They agree in production. When they do not, the shared one is the one
    # every other producer of this card is drawing, so it has to win.
    out = _card("""
        const card = reloadHistory(addMessage, Object.assign({
          ask_user: approvalPayload(Object.assign({ action: %s }, %s)),
        }, {
          effect: 'ui_side_effect',
          effects: ['ui_side_effect'],
          effect_label: 'Changes what is on screen',
          effect_labels: ['Changes what is on screen'],
          effect_severity: 10,
          effect_band: 'routine',
        }));
        console.log(JSON.stringify(describeCard(card)));
    """ % (_SEALED_ACTION, _RELOADED_KEYS), card_sandbox)

    assert out["band"] == "serious"
    assert out["lead"] == "Can permanently delete or overwrite"
    assert "Changes what is on screen" not in out["phrases"]


def test_a_session_saved_before_the_ranking_reloads_undressed(card_sandbox):
    # The pre-P7-06 shape: the sealed list and nothing else. It is no longer
    # the common path — `public_payload()` carries the words for everything
    # saved since — but it is still a real one, and inventing English for a
    # value nobody ranked would be worse than showing the value.
    out = _card("""
        const card = reloadHistory(addMessage, {
          ask_user: approvalPayload({
            action: { tool: 'write_file', content: '/etc/hosts', digest: 'ab12cd34',
                      effects: ['admin_change'] },
          }),
        });
        console.log(JSON.stringify({ drawn: !!card, detail: describeCard(card) }));
    """, card_sandbox)

    assert out["drawn"] is True
    assert out["detail"]["band"] is None, "no band was ever saved, so none is claimed"
    assert out["detail"]["lead"] == "admin_change"
    assert out["detail"]["raw"] == [True], "an identifier is marked as an identifier"
    assert "undefined" not in out["detail"]["text"]


# ── Job 2: the plan window's fifth per-step field ───────────────────────────

_TWO_STEP_PLAN = "- [ ] Rewrite the host file\\n- [ ] Report back"

_START_DESTRUCTIVE = """{
  tool: 'write_file', command: '/etc/hosts',
  effect: 'destructive',
  effect_label: 'Can permanently delete or overwrite',
  effect_band: 'serious',
}"""


def test_the_step_shows_one_phrase_for_what_its_tool_can_do(plan_sandbox):
    out = _plan("""
        setToggles({ plan_mode: false });
        planWindow.onSessionId(() => 'sess-a');
        planWindow.init();
        planWindow.setPlan('%s');
        planWindow.markApproved();
        planWindow.noteToolStart(%s);
        planWindow.noteToolEnd({ tool: 'write_file', exit_code: 0, output: 'Written: /etc/hosts',
                                 effect_label: 'Can permanently delete or overwrite',
                                 effect_band: 'serious' });
        console.log(JSON.stringify({ first: readStep(0), second: readStep(1) }));
    """ % (_TWO_STEP_PLAN, _START_DESTRUCTIVE), plan_sandbox)

    assert out["first"]["effect"] == "Can permanently delete or overwrite"
    assert out["first"]["band"] == "serious"
    assert out["first"]["chipIndex"] == 0, "the consequence leads the row, not the tool name"
    assert out["first"]["tool"] == "write_file", "the other four fields are untouched"
    assert out["second"]["effect"] is None, "only the step the agent was on is described"


def test_a_bookkeeping_event_cannot_overwrite_a_real_steps_effect(plan_sandbox):
    out = _plan("""
        setToggles({ plan_mode: false });
        planWindow.onSessionId(() => 'sess-a');
        planWindow.init();
        planWindow.setPlan('%s');
        planWindow.markApproved();
        planWindow.noteToolStart(%s);
        const before = readStep(0);
        // agent_loop orders update_plan after every step, wrapped in the same
        // tool_start/tool_output pair as real work.
        planWindow.noteToolStart({ tool: 'update_plan', command: '{"plan":"..."}',
                                   effect_label: 'Changes what is on screen', effect_band: 'routine' });
        planWindow.noteToolEnd({ tool: 'ask_user', exit_code: 0, output: 'Awaiting their selection.',
                                 effect_label: 'Asks you a question', effect_band: 'routine' });
        console.log(JSON.stringify({ before, after: readStep(0) }));
    """ % (_TWO_STEP_PLAN, _START_DESTRUCTIVE), plan_sandbox)

    assert out["before"]["effect"] == "Can permanently delete or overwrite"
    assert out["after"] == out["before"], (
        "bookkeeping is the agent talking to this window, not doing the step's work"
    )


def test_a_new_plan_does_not_inherit_the_previous_plans_effect(plan_sandbox):
    out = _plan("""
        setToggles({ plan_mode: false });
        planWindow.onSessionId(() => 'sess-a');
        planWindow.init();
        planWindow.setPlan('%s');
        planWindow.markApproved();
        planWindow.noteToolStart(%s);
        const before = readStep(0);
        planWindow.setPlan('- [ ] Summarise the quarterly figures\\n- [ ] Draft the email');
        console.log(JSON.stringify({ before, after: readStep(0), rows: stepRows().length }));
    """ % (_TWO_STEP_PLAN, _START_DESTRUCTIVE), plan_sandbox)

    assert out["before"]["effect"] == "Can permanently delete or overwrite"
    assert out["rows"] == 2
    assert out["after"]["text"] == "Summarise the quarterly figures"
    assert out["after"]["effect"] is None, (
        "step 1 of a plan that never ran must not inherit step 1 of the plan that did"
    )
    assert "permanently delete" not in out["after"]["row"]


def test_a_revision_of_the_same_plan_keeps_the_effect_it_earned(plan_sandbox):
    # The other half of the reset rule: ticking a box is not a new plan.
    out = _plan("""
        setToggles({ plan_mode: false });
        planWindow.onSessionId(() => 'sess-a');
        planWindow.init();
        planWindow.setPlan('%s');
        planWindow.markApproved();
        planWindow.noteToolStart(%s);
        planWindow.setPlan('- [x] Rewrite the host file\\n- [ ] Report back');
        console.log(JSON.stringify({ first: readStep(0) }));
    """ % (_TWO_STEP_PLAN, _START_DESTRUCTIVE), plan_sandbox)

    assert out["first"]["effect"] == "Can permanently delete or overwrite"


def test_an_event_with_no_phrase_leaves_the_row_blank(plan_sandbox):
    out = _plan("""
        setToggles({ plan_mode: false });
        planWindow.onSessionId(() => 'sess-a');
        planWindow.init();
        planWindow.setPlan('%s');
        planWindow.markApproved();
        // An unclassified tool contributes no keys at all.
        planWindow.noteToolStart({ tool: 'read_file', command: 'README.md' });
        planWindow.noteToolEnd({ tool: 'read_file', exit_code: 0, output: '# Pantheon' });
        console.log(JSON.stringify({ first: readStep(0) }));
    """ % _TWO_STEP_PLAN, plan_sandbox)

    assert out["first"]["effect"] is None, "no phrase means no guess"
    assert out["first"]["tool"] == "read_file"
    assert "undefined" not in out["first"]["row"]


def test_a_phraseless_tool_output_does_not_wipe_the_starts_phrase(plan_sandbox):
    """The back half of a pair is allowed to say nothing.

    `tool_output` normally repeats its `tool_start`'s description, so every
    other case in this file sends the keys on both. That made a mutation which
    cleared the record on *every* phraseless output invisible: the step would
    lose its consequence the instant its own tool finished, which is precisely
    when a reader looks at the row.

    The other direction — a different tool's output landing on the same step —
    is a hand-over and must still replace the record; that is the case below.
    """
    out = _plan("""
        setToggles({ plan_mode: false });
        planWindow.onSessionId(() => 'sess-a');
        planWindow.init();
        planWindow.setPlan('%s');
        planWindow.markApproved();
        planWindow.noteToolStart(%s);
        const before = readStep(0);
        // Same tool, no effect keys at all — an older server, or an emit site
        // whose resolver raised and dropped the fields rather than the stream.
        planWindow.noteToolEnd({ tool: 'write_file', exit_code: 0, output: 'Written: /etc/hosts' });
        console.log(JSON.stringify({ before, after: readStep(0) }));
    """ % (_TWO_STEP_PLAN, _START_DESTRUCTIVE), plan_sandbox)

    assert out["before"]["effect"] == "Can permanently delete or overwrite"
    assert out["after"]["effect"] == "Can permanently delete or overwrite", (
        "the pair describes one action; the half that says nothing erases nothing"
    )
    assert out["after"]["band"] == "serious"


def test_a_different_tools_output_on_the_same_step_does_replace_it(plan_sandbox):
    # The hand-over case the rule above must not swallow: an approval gate and
    # a policy block both emit `tool_output` with no `tool_start` in front of
    # it, so an unrelated tool can finish on a step another tool has claimed.
    out = _plan("""
        setToggles({ plan_mode: false });
        planWindow.onSessionId(() => 'sess-a');
        planWindow.init();
        planWindow.setPlan('%s');
        planWindow.markApproved();
        planWindow.noteToolStart(%s);
        planWindow.noteToolEnd({ tool: 'read_file', exit_code: 0, output: 'blocked' });
        console.log(JSON.stringify({ first: readStep(0) }));
    """ % (_TWO_STEP_PLAN, _START_DESTRUCTIVE), plan_sandbox)

    assert out["first"]["tool"] == "read_file"
    assert out["first"]["effect"] is None, (
        "a phrase describing the tool that did not finish here would misattribute it"
    )
    assert "permanently delete" not in out["first"]["row"]


def test_a_later_tool_on_the_same_step_replaces_the_earlier_phrase(plan_sandbox):
    out = _plan("""
        setToggles({ plan_mode: false });
        planWindow.onSessionId(() => 'sess-a');
        planWindow.init();
        planWindow.setPlan('%s');
        planWindow.markApproved();
        planWindow.noteToolStart(%s);
        planWindow.noteToolStart({ tool: 'read_file', command: 'README.md' });
        console.log(JSON.stringify({ first: readStep(0) }));
    """ % (_TWO_STEP_PLAN, _START_DESTRUCTIVE), plan_sandbox)

    assert out["first"]["tool"] == "read_file"
    assert out["first"]["effect"] is None, (
        "the record now describes a different tool; a stale phrase would misattribute it"
    )


def test_the_effect_survives_a_reload_with_the_rest_of_the_step_record(plan_sandbox):
    out = _plan("""
        setToggles({ plan_mode: false });
        planWindow.onSessionId(() => 'sess-a');
        planWindow.init();
        planWindow.setPlan('%s');
        planWindow.markApproved();
        planWindow.noteToolStart(%s);
        // A reload re-reads both stores; nothing else changes.
        planWindow.init();
        console.log(JSON.stringify({ first: readStep(0) }));
    """ % (_TWO_STEP_PLAN, _START_DESTRUCTIVE), plan_sandbox)

    assert out["first"]["effect"] == "Can permanently delete or overwrite"
    assert out["first"]["band"] == "serious"


# ── Job 3: the stylesheet carries the non-colour half ───────────────────────
#
# REWRITTEN 2026-08-29 after refutation. The two tests in this section used to
# compare property *names*: `test_each_band_changes_more_than_a_colour` asserted
# that the serious lead set something outside a set of colour properties, and
# `test_the_narrow_breakpoints_keep_both_surfaces_legible` grepped three
# selector substrings out of each media block. Both remain true of a stylesheet
# that has been hollowed out, as long as the declarations are still spelled —
# collapsing the serious lead to the routine size, collapsing the phone lead to
# body size, and replacing the narrow-dock rule's whole body with
# `color: inherit` each survived a full green run. A property name says a
# channel was touched; only its value says it was touched in a direction a
# reader can see. Everything below reads values.

_COLOUR_PROPS = {"color", "background", "background-color", "border-color", "border-left-color"}

_MEDIA_SPANS = {
    # (opening marker, the exact closer that ends the block)
    "phone": ("@media (max-width: 640px) {\n  .ask-user-card", "\n}\n"),
    "dock": ("@media (max-width: 768px) {\n      .plan-window-steps", "\n    }\n"),
}


@functools.lru_cache(maxsize=1)
def _css() -> str:
    return STYLE.read_text(encoding="utf-8")


def _span(css: str, where: str) -> tuple:
    marker, closer = _MEDIA_SPANS[where]
    start = css.index(marker)
    return start, start + css[start:].index(closer) + len(closer)


def _decls(selector: str, where: str = "desktop", required: bool = True) -> dict:
    """Every declaration this exact selector makes, in cascade order.

    `where` picks the region: "desktop" is everything outside the two narrow
    breakpoints, "phone" and "dock" are those blocks. Splitting them matters —
    a union across all three reports the phone's 12px lead as the desktop's,
    which is how a desktop-only distinction hides.

    Later declarations win, which is the cascade for rules of equal
    specificity; the banded selectors are read on top of their base explicitly
    by `_cascade` below rather than being folded in here.
    """
    css = _css()
    spans = {name: _span(css, name) for name in _MEDIA_SPANS}
    out = {}
    found = False
    for match in re.finditer(
        r"(?:^|[},/])\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css, re.M,
    ):
        inside = next(
            (name for name, (a, b) in spans.items() if a <= match.start() < b), "desktop"
        )
        if inside != where:
            continue
        found = True
        # Split on `;` rather than reading one declaration per line. An earlier
        # version of this anchored each declaration to a line start, so a rule
        # written on one line — `.approval-effects { padding: 7px; border-left-
        # width: 2px; }`, which is the house style for short overrides at a
        # breakpoint — reported only its first declaration and a mutation
        # hiding behind the second was invisible.
        body = blank_text(match.group(1), "css")
        for chunk in body.split(";"):
            declaration = re.match(r"\s*([a-z-]+)\s*:\s*(\S.*?)\s*$", chunk, re.S)
            if not declaration:
                continue
            prop = declaration.group(1)
            # Re-inserted rather than reassigned so the dict's order is the
            # order the declarations actually resolved in — `_rule_px` needs to
            # know whether a longhand landed after its shorthand or before it.
            out.pop(prop, None)
            out[prop] = re.sub(r"\s+", " ", declaration.group(2))
    assert found or not required, f"no rule found for {selector!r} in the {where} region"
    return out


def _props(selector: str) -> set:
    """Every property this exact selector sets, anywhere in the sheet.

    Kept from the original version of this file — it is still the right shape
    for "was this channel touched at all". It is no longer enough on its own;
    see the section header.
    """
    names = set()
    for where in ("desktop", *_MEDIA_SPANS):
        try:
            names |= set(_decls(selector, where))
        except AssertionError:
            continue
    assert names, f"no rule found for {selector!r}"
    return names


def _cascade(where: str, *selectors: str) -> dict:
    """Resolve a chain of equal-or-increasing specificity selectors, in order.

    Every selector has to exist somewhere in the sheet — a typo, or a rule that
    was deleted outright, still fails — but a region is allowed not to restate
    one. That is the normal case at a breakpoint: the phone block resizes the
    lead and says nothing about the rule ladder, which is exactly how the
    ladder reaches the phone unchanged.
    """
    out = {}
    for selector in selectors:
        _props(selector)
        out.update(_decls(selector, where, required=False))
    return out


def _px(value: str) -> float:
    match = re.match(r"^([\d.]+)px$", str(value).strip())
    assert match, f"expected a px length, got {value!r}"
    return float(match.group(1))


_BOX = {
    "routine": ".approval-effects",
    "notable": '.approval-effects[data-effect-band="notable"]',
    "serious": '.approval-effects[data-effect-band="serious"]',
}
_LEAD = {
    "routine": ".approval-effect-lead",
    "notable": '.approval-effects[data-effect-band="notable"] .approval-effect-lead',
    "serious": '.approval-effects[data-effect-band="serious"] .approval-effect-lead',
}
_MARK = {
    band: (selector + " .approval-effect-mark" if band != "routine" else ".approval-effect-mark")
    for band, selector in _LEAD.items()
}


def _lead(band: str, where: str = "desktop") -> dict:
    chain = [".approval-effect", ".approval-effect-lead"]
    if band != "routine":
        chain.append(_LEAD[band])
    return _cascade(where, *chain)


def _box(band: str, where: str = "desktop") -> dict:
    chain = [".approval-effects"]
    if band != "routine":
        chain.append(_BOX[band])
    return _cascade(where, *chain)


_RULE_PROPS = ("border-left", "border-left-width")


def _rule_px(band: str, where: str = "desktop") -> float:
    """The box's left-rule width, whichever spelling last set it.

    The base rule writes the shorthand and the bands override the longhand, so
    a reader of one spelling alone sees either the same 2px for all three bands
    or nothing at all.
    """
    resolved = _box(band, where)
    last = [prop for prop in resolved if prop in _RULE_PROPS]
    assert last, f"the {band} box declares no left rule"
    value = resolved[last[-1]]
    return _px(value.split()[0])


def _mark(band: str) -> dict:
    """The mark's shape, as the channels a greyscale reader actually resolves."""
    chain = [".approval-effect-mark"]
    if band != "routine":
        chain.append(_MARK[band])
    d = _cascade("desktop", *chain)
    return {
        "size": (d.get("width"), d.get("height")),
        "corners": d.get("border-radius"),
        "turned": d.get("transform"),
        "filled": d.get("background") not in (None, "none"),
        "edges": (
            d.get("border"), d.get("border-left"),
            d.get("border-right"), d.get("border-bottom"),
        ),
    }


_BANDS = ("routine", "notable", "serious")
_ADJACENT = (("routine", "notable"), ("notable", "serious"))


def test_each_band_is_separated_by_values_and_not_only_by_names():
    lead = {b: _lead(b) for b in _BANDS}
    rule = {b: _rule_px(b) for b in _BANDS}
    mark = {b: _mark(b) for b in _BANDS}

    size = {b: _px(lead[b]["font-size"]) for b in _BANDS}
    weight = {b: int(lead[b]["font-weight"]) for b in _BANDS}

    assert size["serious"] > size["notable"], (
        "the serious lead collapsing to the routine size is the mutation this "
        "row exists to catch; a name-only comparison did not"
    )
    assert size["notable"] == size["routine"]
    assert weight["notable"] > weight["routine"], (
        "routine and notable must differ by more than the mark and a border alpha"
    )
    assert weight["serious"] >= weight["notable"]
    assert rule["routine"] < rule["notable"] < rule["serious"], (
        f"the rule ladder is not monotonic: {rule}"
    )
    assert rule["serious"] - rule["routine"] >= 3, (
        "a rule that widens by less than 3px is not a distinction on a phone"
    )

    for lower, upper in _ADJACENT:
        differing = sum(
            1 for key in mark[lower] if mark[lower][key] != mark[upper][key]
        )
        assert differing >= 2, (
            f"the {lower} and {upper} marks differ in {differing} channel(s); "
            "at 7px, shape alone is not enough"
        )
    assert len({tuple(sorted(m.items(), key=str)) for m in mark.values()}) == 3
    # Hollow-to-solid, named on its own rather than left to the channel count:
    # it is the half of the routine/notable difference that survives greyscale,
    # and the count above still cleared its threshold without it.
    assert mark["routine"]["filled"] is False
    assert mark["notable"]["filled"] is True, (
        "a 7px outline turned 45 degrees is not enough on its own; the fill is "
        "what a reader resolves before the shape"
    )

    # The lead's size is what makes it the lead, in every band.
    body = _px(_decls(".approval-effect")["font-size"])
    for band in _BANDS:
        assert size[band] > body, f"the {band} lead does not out-size the rows under it"


def test_no_band_recolours_the_phrase_itself():
    """`Law 15`, and the finding that produced this row.

    The `serious` lead used to be recoloured `var(--accent, var(--red))` over a
    red-tinted panel. Measured across all sixteen themes in `static/js/theme.js`
    that put the one line the card exists to make unmissable at 2.11:1 on
    `paper` and 2.81:1 on `light`, while the harmless line beside it sat above
    6:1 — the alarm was the least legible text in the box on six of sixteen
    themes, and on `terminal` and `retrowave` `--fg` and `--red` are the same
    hex so the recolour changed nothing at all.

    The invariant is deliberately blunt and theme-independent: body text takes
    its colour from one place, so no band can ever be less legible than
    another. Hue is carried on the rule and the mark, which are geometry.
    """
    for band in ("notable", "serious"):
        assert "color" not in _decls(_LEAD[band]), (
            f"the {band} lead sets its own text colour"
        )
        assert "color" not in _decls(
            f'.plan-step-effect[data-effect-band="{band}"]'
        ), f"the {band} plan chip sets its own text colour"
    assert _decls(".approval-effect")["color"] == "var(--fg)"
    assert _decls(".approval-effect-lead")["opacity"] == "1", (
        "a lead faded below full opacity is a recolour by another name"
    )


def test_the_narrow_breakpoints_keep_both_surfaces_legible():
    phone_body = _px(_decls(".approval-effect", "phone")["font-size"])
    phone_lead = {b: _px(_lead(b, "phone").get("font-size")) for b in _BANDS}

    assert phone_lead["routine"] > phone_body, (
        "Law 15: the form factor with the least room needs the distinction most"
    )
    assert phone_lead["serious"] > phone_lead["routine"], (
        "a phone lead that collapses to the routine size loses the band entirely"
    )
    assert phone_lead["serious"] - phone_body >= 3, (
        "the ranked phrase has to out-size the rows under it by a readable margin"
    )
    # The rule ladder is never restated at the breakpoint, so it must survive
    # the cascade intact — this is what stops a phone-only override flattening it.
    desktop_rule = {b: _rule_px(b) for b in _BANDS}
    for band in _BANDS:
        restated = set(_RULE_PROPS) & set(_box(band, "phone"))
        assert not restated, (
            f"the phone block restates the {band} rule via {sorted(restated)}; "
            f"the ladder is {desktop_rule} on desktop and must reach the phone "
            "unchanged"
        )

    dock = _decls(".plan-step-effect", "dock")
    assert dock.get("white-space") == "normal", (
        "on a narrow dock the effect chip must wrap rather than be the one "
        "ellipsised away — it is the field a reader with the least room can "
        "least afford to lose"
    )
    assert dock.get("flex-basis") == "100%" and dock.get("max-width") == "100%", (
        f"the chip needs its own full-width line on a narrow dock; got {dock}"
    )


# ── The measurement the refutation ran, kept as a test ──────────────────────
#
# `Law 15` is carried by the wording first. The numbers below are the floor
# under it: they say the *presentation* of the most serious phrase can never be
# harder to read than the presentation of the most harmless one, in any theme
# the app ships. That is the exact property that failed, and it failed silently
# because nothing measured it.

_TOKEN_FALLBACK_ONLY = {"accent"}


def _themes() -> dict:
    """The sixteen shipped palettes, read out of `static/js/theme.js`."""
    src = (ROOT / "static" / "js" / "theme.js").read_text(encoding="utf-8")
    body = src[src.index("export const THEMES = {"):]
    body = body[body.index("{"):]
    depth = 0
    for i, ch in enumerate(body):
        depth += (ch == "{") - (ch == "}")
        if depth == 0:
            body = body[: i + 1]
            break
    root_red = _decls(":root")["--red"]
    out = {}
    for match in re.finditer(r"(\w+)\s*:\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", body):
        fields = dict(re.findall(r"(\w+)\s*:\s*'(#[0-9a-fA-F]{3,8})'", match.group(2)))
        if {"bg", "fg", "panel"} <= set(fields):
            # theme.js only writes `--red` when the palette names one, so an
            # unnamed one keeps the value from `:root`.
            fields.setdefault("red", root_red)
            out[match.group(1)] = fields
    assert len(out) >= 16, f"expected every shipped theme, found {sorted(out)}"
    return out


def _rgb(value: str) -> tuple:
    digits = value.lstrip("#")
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))


def _resolve(expr: str, theme: dict) -> tuple:
    """Resolve the colour expressions this block actually uses, and no others.

    Deliberately narrow. An expression it cannot resolve fails the test rather
    than being skipped, because a silently unmeasured colour is how the
    original defect stayed invisible; teach this function the new form instead.
    """
    expr = expr.strip()
    mix = re.fullmatch(
        r"color-mix\(in srgb,\s*(.+?)\s+([\d.]+)%\s*,\s*(.+?)\s*\)", expr
    )
    if mix:
        first = _resolve(mix.group(1), theme)
        second = _resolve(mix.group(3), theme)
        share = float(mix.group(2)) / 100
        return tuple(first[i] * share + second[i] * (1 - share) for i in range(3))
    token = re.fullmatch(r"var\(--([a-z-]+)(?:,\s*(.+))?\)", expr)
    if token:
        name, fallback = token.group(1), token.group(2)
        if name in theme:
            return _rgb(theme[name])
        assert name in _TOKEN_FALLBACK_ONLY and fallback, (
            f"--{name} resolves to nothing and has no fallback; a bare "
            f"var(--{name}) voids the whole declaration"
        )
        return _resolve(fallback, theme)
    assert expr.startswith("#"), (
        f"the contrast check cannot resolve {expr!r} — teach `_resolve` its form"
    )
    return _rgb(expr)


def _contrast(fore: tuple, back: tuple) -> float:
    def channel(value):
        value /= 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    def relative(colour):
        r, g, b = (channel(c) for c in colour)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    high, low = sorted((relative(fore), relative(back)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_the_serious_lead_is_never_less_legible_than_the_routine_one():
    measured = {}
    for name, theme in _themes().items():
        ratios = {}
        for band in ("routine", "serious"):
            text = _resolve(_lead(band)["color"], theme)
            back = _resolve(_box(band)["background"], theme)
            ratios[band] = _contrast(text, back)
        measured[name] = ratios

    worse = {
        name: r for name, r in measured.items()
        if r["serious"] < r["routine"] * 0.9
    }
    assert not worse, (
        "the serious lead is materially harder to read than the routine one on "
        + ", ".join(f"{n} ({r['serious']:.2f} vs {r['routine']:.2f})"
                    for n, r in sorted(worse.items()))
    )
    # 15px at weight 700 is WCAG "large text", so 3:1 is the applicable floor.
    # Two shipped palettes (`cute`, `retrowave`) put *all* of their body text
    # under 4.5:1 against their own panel; that ceiling belongs to the palette,
    # not to this card, and the assertion says so rather than pretending
    # otherwise.
    assert _px(_lead("serious")["font-size"]) >= 14, "the 3:1 floor assumes large text"
    assert int(_lead("serious")["font-weight"]) >= 700
    dim = {n: r["serious"] for n, r in measured.items() if r["serious"] < 3.0}
    assert not dim, f"the serious lead falls under the large-text floor on {dim}"


def test_no_new_rule_reaches_for_a_bare_accent():
    css = STYLE.read_text(encoding="utf-8")
    bodies = [
        body
        for selector, body in re.findall(r"(?m)^\s*([^{}\n]*?)\s*\{([^}]*)\}", css)
        if "approval-effect" in selector or "plan-step-effect" in selector
    ]
    assert bodies, "the new rules should exist"
    for body in bodies:
        for line in body.splitlines():
            if "var(--accent" not in line:
                continue
            assert "var(--accent, var(--red))" in line, (
                f"--accent is undefined until P1-01; {line.strip()!r} would void its declaration"
            )


def test_a_stub_always_beats_the_real_module(tmp_path):
    """B47's guard. The copier exists so a new import does not break every
    sandbox — it must never quietly replace a stub with the real thing, or the
    in-memory `storage.js` and the silent `ui.js` these sandboxes depend on
    would become the real ones and the failure would look like anything but
    this."""
    js = tmp_path / "js"
    js.mkdir()
    (js / "subject.js").write_text(
        "import a from './stubbed.js';\nimport b from './fresh.js';\n"
    )
    (js / "stubbed.js").write_text("export default 'THE REAL ONE';\n")
    (js / "fresh.js").write_text("import c from './deeper.js';\nexport default c;\n")
    (js / "deeper.js").write_text("export default 'deep';\n")

    box = tmp_path / "box"
    box.mkdir()
    _make_sandbox(box, js / "subject.js", "// shim", {"stubbed.js": "export default 'STUB';\n"})

    assert (box / "stubbed.js").read_text() == "export default 'STUB';\n"
    assert "THE REAL ONE" not in (box / "stubbed.js").read_text()
    assert (box / "fresh.js").is_file(), "an unstubbed import was not copied"
    assert (box / "deeper.js").is_file(), "the copy is not transitive"


def test_the_copier_ignores_an_import_that_is_not_a_local_module(tmp_path):
    """`import x from 'somepkg'` is not ours to copy, and a versioned
    specifier (`./chat.js?v=…`) has to resolve to the file without the query —
    both spellings exist in this tree."""
    js = tmp_path / "js"
    js.mkdir()
    (js / "subject.js").write_text(
        "import pkg from 'somepkg';\nimport v from './versioned.js?v=20260829trustladder1';\n"
    )
    (js / "versioned.js").write_text("export default 1;\n")
    box = tmp_path / "box2"
    box.mkdir()
    _make_sandbox(box, js / "subject.js", "// shim", {})
    assert (box / "versioned.js").is_file()
    assert not (box / "somepkg").exists()
