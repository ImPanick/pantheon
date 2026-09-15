# SPDX-License-Identifier: AGPL-3.0-or-later
"""P6-18 — the steer control in `static/js/chatStream.js`, driven under node.

`chatStream.js` imports six browser-coupled modules and touches the DOM, so it
is exercised in a sandbox: stub modules plus a small DOM shim are written beside
a copy of the REAL file, which is then imported unmodified. No jsdom (this repo
adds zero external dependencies), and no source-text greps standing in for
behaviour — every assertion below drives the module and reads what it did.

What is pinned, and why each one is a defect if it breaks:

  * With no `/api/chat/steer` route the control never appears and Cmd/Ctrl+Enter
    is NOT taken. Shipping a visible control that cannot work is the `Law 13`
    failure this feature is most exposed to, and stealing a key binding to do
    nothing is worse than not having the feature.
  * With the route present, a live run draws the bar, and the bar names both
    verbs and both keys — the `Law 15` requirement, checked as rendered text
    rather than as a promise in a comment.
  * A refusal falls back to `chat.js`'s existing queue rather than dropping the
    user's words or growing a second queue (`Law 14`).
  * The steer is addressed to the session that was current when the key was
    pressed — the `P6-01` defect class.
  * Nothing in the user-facing copy claims the redirect is immediate; the
    backend cannot interrupt a round in progress.
  * `B14`: the RUN's own verdict outranks the composer's guess, in both
    directions, and does not survive into the next run. The guess below —
    `test_no_steer_bar_is_drawn_for_a_plain_chat_turn` — passed from `P6-18`
    until this row while the bar was still being offered on research turns,
    image sessions and compare panes, because it only ever asked about the one
    case `P6-18` knew about.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHAT_STREAM = ROOT / "static" / "js" / "chatStream.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


_SHIM = r"""
// Minimal DOM/window shim — only what chatStream.js's steer control touches.
class Node {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.className = ''; this.id = ''; this.textContent = ''; this.value = '';
    this.title = ''; this.disabled = false; this.focused = false;
    this.childNodes = []; this.parentNode = null;
    this.dataset = {}; this.attrs = {}; this.listeners = {}; this.style = {};
  }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') this.id = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  appendChild(n) { n.parentNode = this; this.childNodes.push(n); return n; }
  insertBefore(n, ref) {
    const i = this.childNodes.indexOf(ref);
    n.parentNode = this;
    if (i < 0) this.childNodes.push(n); else this.childNodes.splice(i, 0, n);
    return n;
  }
  removeChild(n) {
    const i = this.childNodes.indexOf(n);
    if (i >= 0) this.childNodes.splice(i, 1);
    n.parentNode = null; return n;
  }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  removeEventListener(t, fn) {
    const a = this.listeners[t] || []; const i = a.indexOf(fn); if (i >= 0) a.splice(i, 1);
  }
  dispatchEvent(ev) { (this.listeners[ev.type] || []).slice().forEach(fn => fn(ev)); return true; }
  focus() { this.focused = true; }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === document; }
  get innerText() {
    return this.childNodes.length
      ? this.childNodes.map(c => c.innerText).join('')
      : (this.textContent || '');
  }
  _walk(out) { for (const c of this.childNodes) { out.push(c); c._walk(out); } return out; }
  _matchesCompound(sel) {
    let p = sel.trim();
    let attr = null;
    const am = p.match(/\[([a-zA-Z-]+)="([^"]*)"\]/);
    if (am) { attr = am; p = p.replace(am[0], ''); }
    const idm = p.match(/#([A-Za-z0-9_-]+)/);
    if (idm) { if (this.id !== idm[1]) return false; p = p.replace(idm[0], ''); }
    const classes = (p.match(/\.[A-Za-z0-9_-]+/g) || []).map(c => c.slice(1));
    const tag = p.replace(/\.[A-Za-z0-9_-]+/g, '').trim();
    if (tag && this.tagName !== tag.toUpperCase()) return false;
    for (const c of classes) if (!(' ' + this.className + ' ').includes(' ' + c + ' ')) return false;
    if (attr) {
      let actual = this.getAttribute(attr[1]);
      if (actual == null && attr[1].startsWith('data-')) {
        const key = attr[1].slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase());
        actual = this.dataset[key];
      }
      if (actual !== attr[2]) return false;
    }
    return true;
  }
  querySelectorAll(sel) {
    const parts = String(sel).split(',').map(s => s.trim()).filter(Boolean);
    return this._walk([]).filter(n => parts.some(p => n._matchesCompound(p)));
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

const document = new Node('#document');
document.head = document.appendChild(new Node('head'));
document.body = document.appendChild(new Node('body'));
document.createElement = (tag) => new Node(tag);
document.getElementById = (id) => document._walk([]).find(n => n.id === id) || null;
document.hidden = false;

// Node 22 defines `navigator`/`location` as getter-only globals, so they are
// replaced by descriptor rather than by assignment.
function _defineGlobal(name, value) {
  Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
globalThis.document = document;
globalThis.Node = Node;
_defineGlobal('navigator', { platform: 'Linux x86_64' });
_defineGlobal('window', globalThis);
_defineGlobal('location', { origin: 'http://test.local' });
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } };
globalThis.Event = class { constructor(type) { this.type = type; } };
const _winListeners = {};
globalThis.addEventListener = (t, fn) => { (_winListeners[t] = _winListeners[t] || []).push(fn); };
globalThis.dispatchEvent = (ev) => { (_winListeners[ev.type] || []).slice().forEach(fn => fn(ev)); return true; };

// A composer and a chat input bar, exactly the two anchors the control needs.
const inputBar = document.body.appendChild(new Node('div'));
inputBar.className = 'chat-input-bar';
const composer = inputBar.appendChild(new Node('textarea'));
composer.id = 'message';
const sendBtn = inputBar.appendChild(new Node('button'));
sendBtn.className = 'send-btn';

export { document, composer, inputBar, sendBtn };

export function tick(n = 4) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise(r => setTimeout(r, 0)));
  return p;
}

export function setBusy(active) {
  globalThis.__pantheonChatBusy = !!active;
  globalThis.__pantheonChatBusyUntil = active ? Date.now() + 120000 : 0;
  globalThis.dispatchEvent(new CustomEvent('pantheon:chat-busy-change', { detail: { active: !!active } }));
}

export const calls = { fetch: [], toasts: [], errors: [], queued: 0 };

export function mockFetch(handler) {
  globalThis.fetch = async (url, opts) => {
    let body = null;
    try { body = JSON.parse((opts && opts.body) || 'null'); } catch (_) {}
    calls.fetch.push({ url: String(url), body });
    return handler(String(url), body);
  };
}

export function res(status, payload) {
  return { ok: status >= 200 && status < 300, status, json: async () => (payload || {}) };
}

export function pressSteerKey(target) {
  const ev = {
    key: 'Enter', metaKey: false, ctrlKey: true, shiftKey: false, altKey: false,
    isComposing: false, repeat: false, target: target || composer,
    prevented: false, stopped: false,
    preventDefault() { this.prevented = true; },
    stopImmediatePropagation() { this.stopped = true; },
  };
  document.dispatchEvent(Object.assign(ev, { type: 'keydown' }));
  return ev;
}
"""

_STUBS = {
    "ui.js": """
import { calls } from './shim.js';
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
export default {
  esc,
  showToast: (m) => calls.toasts.push(String(m)),
  showError: (m) => calls.errors.push(String(m)),
  autoResize: () => {},
  el: (id) => document.getElementById(id),
  scrollHistory: () => {},
};
""",
    "storage.js": """
export default { getJSON: () => ({}), setJSON: () => {}, remove: () => {}, KEYS: { TOGGLES: 'toggles' } };
""",
    "theme.js": "export default {};\n",
    "markdown.js": "export default {};\n",
    "sessions.js": """
export default {
  getCurrentSessionId: () => globalThis.__sid || '',
  getSessions: () => [],
  selectSession: () => {},
};
""",
    "document.js": "export default {};\n",
}


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("steerjs")
    (d / "shim.js").write_text(_SHIM)
    for name, src in _STUBS.items():
        (d / name).write_text(src)
    shutil.copy(CHAT_STREAM, d / "chatStream.js")
    return d


def _run(sandbox, script: str) -> dict:
    entry = sandbox / "case.mjs"
    entry.write_text(
        "import { document, composer, inputBar, sendBtn, tick, setBusy, calls, "
        "mockFetch, res, pressSteerKey } from './shim.js';\n"
        + textwrap.dedent(script)
    )
    proc = subprocess.run(
        ["node", str(entry)], cwd=sandbox, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])


# ── no transport: nothing ships dead ────────────────────────────────────────

def test_without_the_route_no_control_is_drawn_and_no_key_is_taken(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(404, {}));
        await import('./chatStream.js');
        setBusy(true);
        await tick();
        composer.value = 'use the staging db';
        const ev = pressSteerKey();
        console.log(JSON.stringify({
          bar: !!document.querySelector('.steer-bar'),
          prevented: ev.prevented,
          composerStillHasText: composer.value,
          probes: calls.fetch.length,
        }));
    """)
    assert out["bar"] is False, "a control that cannot work must not be drawn"
    assert out["prevented"] is False, "Cmd/Ctrl+Enter must keep its existing behaviour"
    assert out["composerStillHasText"] == "use the staging db"
    assert out["probes"] == 1, "the capability probe should fire once, not per keystroke"


# ── with the route: the Law 15 surface ──────────────────────────────────────

def test_a_live_run_draws_a_bar_that_names_both_verbs_and_both_keys(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { supported: true }));
        await import('./chatStream.js');
        setBusy(true);
        await tick();
        const bar = document.querySelector('.steer-bar');
        console.log(JSON.stringify({
          drawn: !!bar,
          text: bar ? bar.innerText : '',
          hasButton: !!(bar && bar.querySelector('.steer-bar-btn')),
          buttonLabel: bar ? bar.querySelector('.steer-bar-btn').innerText : '',
          role: bar ? bar.getAttribute('role') : '',
        }));
    """)
    assert out["drawn"] is True
    assert out["hasButton"] is True, "Law 15: a key binding alone is not discoverable"
    assert out["buttonLabel"] == "Steer now"
    assert out["role"] == "status"
    text = out["text"]
    assert "Ctrl+⏎" in text, "the steer key is named on screen"
    assert "⏎" in text and "queues it for after" in text, "the queue verb is named too"
    assert "next step" in text, "the honest round-boundary promise"


def test_the_bar_never_claims_an_instant_redirect(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, {}));
        await import('./chatStream.js');
        setBusy(true);
        await tick();
        composer.value = 'stop and switch to the other file';
        document.querySelector('.steer-bar-btn').dispatchEvent({ type: 'click', preventDefault(){} });
        await tick();
        const bar = document.querySelector('.steer-bar');
        console.log(JSON.stringify({ text: bar.innerText, toasts: calls.toasts }));
    """)
    blob = (out["text"] + " " + " ".join(out["toasts"])).lower()
    for lie in ("immediately", "instantly", "right now", "interrupt"):
        assert lie not in blob, f"the backend cannot deliver {lie!r} — see agent_loop round structure"
    assert "next step" in blob


def test_the_bar_disappears_when_the_run_ends(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, {}));
        await import('./chatStream.js');
        setBusy(true); await tick();
        const during = !!document.querySelector('.steer-bar');
        setBusy(false); await tick();
        console.log(JSON.stringify({ during, after: !!document.querySelector('.steer-bar') }));
    """)
    assert out == {"during": True, "after": False}


# ── sending ─────────────────────────────────────────────────────────────────

def test_the_key_posts_the_steer_to_the_session_that_was_current(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { accepted: true, pending: 1, applies_at: 'next_round' }));
        await import('./chatStream.js');
        setBusy(true); await tick();
        calls.fetch.length = 0;
        composer.value = '  use the staging db  ';
        const ev = pressSteerKey();
        await tick();
        console.log(JSON.stringify({
          prevented: ev.prevented, stopped: ev.stopped,
          url: calls.fetch[0].url, body: calls.fetch[0].body,
          composer: composer.value,
          echo: document.querySelector('.steer-sent').innerText,
        }));
    """)
    assert out["prevented"] is True and out["stopped"] is True
    assert out["url"] == "http://test.local/api/chat/steer/sess-a"
    assert out["body"] == {"text": "use the staging db"}, "trimmed, and no probe flag"
    assert out["composer"] == "", "the composer is cleared once the steer is accepted"
    assert "use the staging db" in out["echo"] and "lands at the next step" in out["echo"]


def test_the_key_is_ignored_when_no_run_is_live(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, {}));
        await import('./chatStream.js');
        setBusy(true); await tick();       // probe + draw
        setBusy(false); await tick();
        calls.fetch.length = 0;
        composer.value = 'too late';
        const ev = pressSteerKey();
        await tick();
        console.log(JSON.stringify({ prevented: ev.prevented, posts: calls.fetch.length }));
    """)
    assert out == {"prevented": False, "posts": 0}


def test_an_empty_composer_never_posts(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, {}));
        await import('./chatStream.js');
        setBusy(true); await tick();
        calls.fetch.length = 0;
        composer.value = '   ';
        const ev = pressSteerKey();
        document.querySelector('.steer-bar-btn').dispatchEvent({ type: 'click', preventDefault(){} });
        await tick();
        console.log(JSON.stringify({
          prevented: ev.prevented, posts: calls.fetch.length,
          toasts: calls.toasts, focused: composer.focused,
        }));
    """)
    assert out["posts"] == 0
    assert out["prevented"] is False
    assert any("Type the change first" in t for t in out["toasts"])
    assert out["focused"] is True, "the button should send you back to the composer"


# ── refusals fall back to the ONE queue ─────────────────────────────────────

def test_a_refused_steer_falls_back_to_the_existing_queue(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        globalThis.chatModule = { queueStreamingComposerRequest: () => { calls.queued++; return true; } };
        let n = 0;
        mockFetch(async () => (++n === 1
          ? res(200, {})                                              // probe
          : res(409, { accepted: false, reason: 'no_active_run' })));  // the steer
        await import('./chatStream.js');
        setBusy(true); await tick();
        composer.value = 'change of plan';
        pressSteerKey();
        await tick();
        console.log(JSON.stringify({ queued: calls.queued, toasts: calls.toasts, errors: calls.errors }));
    """)
    assert out["queued"] == 1, "the words go to chat.js's queue, never on the floor"
    assert any("queued for after this response" in t for t in out["toasts"])
    # Was "already finished" until 2026-08-29. The server folds two causes into
    # `no_active_run` — the run ended, and the run cannot take a steer at all (a
    # plain chat or image turn, which has no rounds) — and "already finished"
    # was false for the second. The sentence has to hold whichever one it was.
    assert any("no agent run to steer" in t for t in out["toasts"])
    assert out["errors"] == []


def test_no_steer_bar_is_drawn_for_a_plain_chat_turn(sandbox):
    """A control that can only decline is worse than no control (`Law 15`).

    Chat mode has no rounds, so there is no step boundary to deliver a steer at
    and the server refuses. Drawing the bar anyway would advertise a course
    correction that never lands. The composer's own mode getter answers this —
    the capability probe fires once per page load and cannot, because
    steerability is a property of the run, not of the build.
    """
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { supported: true }));
        let mode = 'chat';
        globalThis.window.__pantheonGetChatMode = () => mode;
        await import('./chatStream.js');
        setBusy(true); await tick();
        const chatMode = !!document.querySelector('.steer-bar');
        setBusy(false); await tick();
        mode = 'agent';
        setBusy(true); await tick();
        const agentMode = !!document.querySelector('.steer-bar');
        console.log(JSON.stringify({ chatMode, agentMode }));
    """)
    assert out["chatMode"] is False, "chat mode must not advertise steering"
    assert out["agentMode"] is True, "agent mode still gets the bar"


# ── the run's own verdict (B14) ─────────────────────────────────────────────
#
# The composer's mode getter above closed the chat-mode case and left three
# open: a research turn, an image-generation session and a compare pane all draw
# a bar the server refuses with `no_active_run`. None of them is visible from the
# composer — research in particular is decided server-side, from
# `research_pending`, on a message whose research toggle `chat.js` has already
# cleared. So the run says what it is, on the same SSE dispatch chain that
# carries `steer_applied`, and that answer outranks the guess.


def test_a_run_that_says_it_cannot_be_steered_takes_the_bar_down(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { supported: true }));
        const mod = await import('./chatStream.js');
        setBusy(true); await tick();
        const beforeAnswer = !!document.querySelector('.steer-bar');
        mod.handleStreamSteerable({ type: 'stream_steerable', steerable: false });
        const afterAnswer = !!document.querySelector('.steer-bar');
        console.log(JSON.stringify({ beforeAnswer, afterAnswer }));
    """)
    assert out["beforeAnswer"] is True, "the bar is drawn on the busy edge, before the POST answers"
    assert out["afterAnswer"] is False, (
        "a research turn, an image session and a compare pane can only decline; "
        "leaving the bar up is the Law 15 half of the defect P6-18 fixed elsewhere"
    )


def test_a_run_that_cannot_be_steered_hands_the_key_binding_back(sandbox):
    """No round trip spent being refused, and no `Steering…` toast in front of
    the queue. `app.js`'s plain-Enter binding does not exclude the modifier, so
    the text lands in the same queue the refusal would have put it in."""
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { supported: true }));
        const mod = await import('./chatStream.js');
        setBusy(true); await tick();
        mod.handleStreamSteerable({ steerable: false });
        calls.fetch.length = 0;
        composer.value = 'change of plan';
        const ev = pressSteerKey();
        await tick();
        console.log(JSON.stringify({
          prevented: ev.prevented, posts: calls.fetch.length,
          composer: composer.value, toasts: calls.toasts,
        }));
    """)
    assert out["prevented"] is False, "the key falls through to the queue, as it does with no route"
    assert out["posts"] == 0
    assert out["composer"] == "change of plan", "the words are still where the user left them"
    assert out["toasts"] == []


def test_a_run_that_says_it_CAN_be_steered_overrides_the_composers_guess(sandbox):
    """`Law 1`, and the direction the row does not mention. A chat-mode turn
    auto-escalated to agent IS steerable — the server runs the agent loop — and
    the composer still says 'chat', so the guess was withholding a bar from a run
    that would have taken the steer. The key already worked there; only the
    discoverable half was missing."""
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { supported: true }));
        globalThis.window.__pantheonGetChatMode = () => 'chat';
        const mod = await import('./chatStream.js');
        setBusy(true); await tick();
        const guessed = !!document.querySelector('.steer-bar');
        mod.handleStreamSteerable({ steerable: true });
        const answered = !!document.querySelector('.steer-bar');
        composer.value = 'use the staging db';
        const ev = pressSteerKey();
        await tick();
        console.log(JSON.stringify({ guessed, answered, prevented: ev.prevented }));
    """)
    assert out["guessed"] is False, "the composer's mode getter hid it"
    assert out["answered"] is True, "the run said otherwise, and the run is the authority"
    assert out["prevented"] is True


@pytest.mark.parametrize("answer, drawn", [(True, True), (False, False)])
def test_a_verdict_that_beats_the_capability_probe_still_wins(sandbox, answer, drawn):
    """The first run of a page load is the one case where the two answers race:
    the probe is a round trip and the stream's first event is on its way while it
    is in flight. The busy-change listener resumes after the `await` and has to
    re-read the verdict rather than fall back to the guess it was about to use —
    in both directions, since the guess can be wrong either way.

    Driven by holding the probe's response open until the verdict has landed."""
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        let releaseProbe;
        const held = new Promise((r) => { releaseProbe = r; });
        mockFetch(async () => { await held; return res(200, { supported: true }); });
        globalThis.window.__pantheonGetChatMode = () => 'chat';
        const mod = await import('./chatStream.js');
        setBusy(true);                                  // listener parks on the probe
        await tick();
        const beforeProbe = !!document.querySelector('.steer-bar');
        mod.handleStreamSteerable({ steerable: ANSWER });
        releaseProbe();
        await tick();
        console.log(JSON.stringify({
          beforeProbe, bar: !!document.querySelector('.steer-bar'),
        }));
    """.replace("ANSWER", "true" if answer else "false"))
    assert out["beforeProbe"] is False, "nothing is drawn until the build is known to support it"
    assert out["bar"] is drawn


def test_the_verdict_does_not_carry_from_one_run_to_the_next(sandbox):
    """Steerability is a property of the run, which is the whole reason the
    capability probe could not answer it.

    Both edges are driven, because `chat.js` produces both: the ordinary
    finish-then-start pair, and two `active: true` edges in a row —
    `_setForegroundChatBusy(true)` fires at send-path entry and
    `_syncForegroundStreamGlobals()` fires again once the stream is up, with no
    `false` in between. A reset on the end edge alone would look correct on the
    first sequence and leave the second run of the second sequence permanently
    unsteerable."""
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { supported: true }));
        const mod = await import('./chatStream.js');
        setBusy(true); await tick();
        mod.handleStreamSteerable({ steerable: false });
        const duringResearch = !!document.querySelector('.steer-bar');
        setBusy(false); await tick();
        setBusy(true); await tick();          // an ordinary agent turn follows
        const nextRun = !!document.querySelector('.steer-bar');
        composer.value = 'and now steer';
        const ev = pressSteerKey();
        await tick();

        // Now the back-to-back case: refused, then a new run starts with no
        // end edge between them.
        mod.handleStreamSteerable({ steerable: false });
        const refusedAgain = !!document.querySelector('.steer-bar');
        setBusy(true); await tick();
        const backToBack = !!document.querySelector('.steer-bar');
        console.log(JSON.stringify({
          duringResearch, nextRun, prevented: ev.prevented, refusedAgain, backToBack,
        }));
    """)
    assert out["duringResearch"] is False
    assert out["nextRun"] is True, "the next run is steerable until it says otherwise"
    assert out["prevented"] is True, "and the key comes back with it"
    assert out["refusedAgain"] is False
    assert out["backToBack"] is True, (
        "a second `active` edge with no `inactive` between them is still a new run"
    )


def test_a_replayed_verdict_after_the_run_ended_does_not_resurrect_the_bar(sandbox):
    """`/api/chat/resume` replays a run's buffer from the start, so this event
    arrives again on every reconnect — including one that lands after the run
    has finished."""
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { supported: true }));
        const mod = await import('./chatStream.js');
        setBusy(true); await tick();
        setBusy(false); await tick();
        mod.handleStreamSteerable({ steerable: true });
        console.log(JSON.stringify({ bar: !!document.querySelector('.steer-bar') }));
    """)
    assert out == {"bar": False}


def test_a_server_that_never_announces_behaves_exactly_as_before(sandbox):
    """`Law 1`. An older server sends no `stream_steerable`, and the composer's
    guess has to keep standing alone or steering would vanish from every build
    that has the route but not the event."""
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { supported: true }));
        let mode = 'agent';
        globalThis.window.__pantheonGetChatMode = () => mode;
        await import('./chatStream.js');
        setBusy(true); await tick();
        const agentMode = !!document.querySelector('.steer-bar');
        composer.value = 'steer it';
        const ev = pressSteerKey();
        await tick();
        setBusy(false); await tick();
        mode = 'chat';
        setBusy(true); await tick();
        const chatMode = !!document.querySelector('.steer-bar');
        console.log(JSON.stringify({ agentMode, chatMode, prevented: ev.prevented }));
    """)
    assert out == {"agentMode": True, "chatMode": False, "prevented": True}


def test_a_route_that_vanishes_hides_the_control_and_queues_instead(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        globalThis.chatModule = { queueStreamingComposerRequest: () => { calls.queued++; return true; } };
        let n = 0;
        mockFetch(async () => (++n === 1 ? res(200, {}) : res(404, {})));
        await import('./chatStream.js');
        setBusy(true); await tick();
        composer.value = 'change of plan';
        pressSteerKey();
        await tick();
        const gone = !document.querySelector('.steer-bar');
        composer.value = 'again';
        const ev = pressSteerKey();
        console.log(JSON.stringify({ queued: calls.queued, gone, secondPrevented: ev.prevented }));
    """)
    assert out["gone"] is True
    assert out["queued"] == 1
    assert out["secondPrevented"] is False, "the key binding is handed straight back"


# ── session binding (the P6-01 defect class) ────────────────────────────────

def test_switching_chats_mid_run_does_not_inherit_the_other_chats_steer_list(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { accepted: true }));
        await import('./chatStream.js');
        setBusy(true); await tick();
        composer.value = 'first chat steer';
        pressSteerKey();
        await tick();
        const aEcho = document.querySelector('.steer-sent').innerText;
        globalThis.__sid = 'sess-b';
        setBusy(true); await tick();       // a run starts in the other chat
        const bEcho = document.querySelector('.steer-sent').innerText;
        console.log(JSON.stringify({ aEcho, bEcho }));
    """)
    assert "first chat steer" in out["aEcho"]
    assert out["bEcho"] == "", "session B must not show session A's accepted steers"


def test_no_session_means_no_steer_and_no_lost_text(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        globalThis.chatModule = { queueStreamingComposerRequest: () => { calls.queued++; return true; } };
        mockFetch(async () => res(200, { accepted: true }));
        const mod = await import('./chatStream.js');
        setBusy(true); await tick();
        globalThis.__sid = '';
        const ok = await mod.submitSteer('orphan');
        console.log(JSON.stringify({ ok, queued: calls.queued }));
    """)
    assert out["ok"] is False
    assert out["queued"] == 1


# ── the applied confirmation ────────────────────────────────────────────────

def test_steer_applied_upgrades_pending_to_applied(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { accepted: true }));
        const mod = await import('./chatStream.js');
        setBusy(true); await tick();
        composer.value = 'switch approach';
        pressSteerKey();
        await tick();
        const before = document.querySelector('.steer-sent').innerText;
        mod.handleSteerApplied({ type: 'steer_applied', round: 3, steers: ['switch approach'] });
        console.log(JSON.stringify({ before, after: document.querySelector('.steer-sent').innerText }));
    """)
    assert "lands at the next step" in out["before"]
    assert "applied at step 3" in out["after"]
    assert "switch approach" in out["after"], "the user's own words survive the upgrade"


def test_a_steer_that_missed_the_run_is_reported_once_the_channel_is_known_live(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { accepted: true }));
        const mod = await import('./chatStream.js');

        // Run 1: the confirmation channel proves itself.
        setBusy(true); await tick();
        composer.value = 'first'; pressSteerKey(); await tick();
        mod.handleSteerApplied({ round: 2 });
        setBusy(false); await tick();
        const afterConfirmedRun = calls.toasts.slice();

        // Run 2: accepted, never confirmed — the run ended first.
        setBusy(true); await tick();
        composer.value = 'second'; pressSteerKey(); await tick();
        setBusy(false); await tick();
        console.log(JSON.stringify({
          afterConfirmedRun,
          warned: calls.toasts.filter(t => t.includes('finished before your steer')).length,
        }));
    """)
    assert not any("finished before your steer" in t for t in out["afterConfirmedRun"]), (
        "a steer that WAS applied must not be reported as missed"
    )
    assert out["warned"] == 1


def test_no_missed_steer_warning_when_the_confirmation_channel_is_absent(sandbox):
    # When no `steer_applied` ever reaches this module, every steer looks
    # unconfirmed. Crying wolf on all of them is worse than silence.
    #
    # This used to read "on a build where chat.js does not route
    # `steer_applied` yet" — true when written, and no longer: chat.js routes
    # it from the same dispatch chain as `ui_control` (P6-18, pinned by
    # `tests/test_chat_steer_route.py`). The behaviour pinned here is unchanged
    # and still load-bearing, because the channel is still absent whenever the
    # stream is not the agent loop: a plain-chat turn emits no `steer_applied`
    # at all, and neither does an older server.
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(200, { accepted: true }));
        await import('./chatStream.js');
        setBusy(true); await tick();
        composer.value = 'change of plan'; pressSteerKey(); await tick();
        setBusy(false); await tick();
        console.log(JSON.stringify({ toasts: calls.toasts }));
    """)
    assert not any("finished before your steer" in t for t in out["toasts"])


def test_steer_applied_is_safe_before_anything_was_steered(sandbox):
    out = _run(sandbox, """
        globalThis.__sid = 'sess-a';
        mockFetch(async () => res(404, {}));
        const mod = await import('./chatStream.js');
        mod.handleSteerApplied({ round: 1 });
        console.log(JSON.stringify({ ok: true }));
    """)
    assert out == {"ok": True}
