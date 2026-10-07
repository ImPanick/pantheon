# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B-NEW-9` (P23 round 2, `fx2-doors`) — an offline reload says it is offline.

`P23-07`'s service worker draws the shell offline — sidebar, composer, the
address kept — and every `/api/` read then rejects. Measured on `a936b5c`
(the acceptance drive's `o-offline-reload-dark.png`) and again on this branch
before the change: the first thing a person read was a red *Failed to load
presets* toast over an empty chat area, and under it, overwritten a moment
later in the one `#toast`, *Could not load chats: Failed to fetch*. Nothing
said *offline*.

Now the boot's first read (`presets.js` `loadPresets`, `app.js`'s "Load
initial data") says it once, in the chat area, with the one empty-state
builder: *You're offline.* when the browser knows it is, *Pantheon isn't
answering.* when it is online and the server is not, beside **Reload**; the
line says *Back online.* when the connection returns. The presets' and the
chat list's toasts stay quiet for a request that never reached the server, and
both still speak when the server answered badly.

Driven under node (`Law 20`): the real `presets.js` imported, with
`window.uiModule.renderEmptyState` recording what it is asked to draw; the
real `loadSessions` cut out of `sessions.js`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]
PRESETS_JS = ROOT / "static" / "js" / "presets.js"
SESSIONS_JS = ROOT / "static" / "js" / "sessions.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _node(tmp_path: Path, script: str) -> dict:
    entry = tmp_path / "case.mjs"
    entry.write_text(script, encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# A chat area, a window that keeps its listeners, and a `uiModule` whose
# `renderEmptyState` records the spec it is handed and draws a title node.
_PAGE = """
const out = { drawn: [], errors: [], warned: 0, reloaded: 0 };
const chatHistory = { msgs: 0, querySelector: (sel) => (sel === '.msg' && chatHistory.msgs ? {} : null) };
globalThis.document = { getElementById: (id) => (id === 'chat-history' ? chatHistory : null), querySelectorAll: () => [] };
const listeners = {};
globalThis.window = {
  addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
  location: { reload: () => { out.reloaded += 1; } },
  uiModule: {
    renderEmptyState: (host, spec) => {
      const title = { textContent: spec.title };
      out.drawn.push({ host: host === chatHistory, kind: spec.kind, title: spec.title, retry: spec.retryLabel, icon: spec.icon });
      out.box = { querySelector: (sel) => (sel === '.empty-state-title' ? title : null), title, spec };
      return out.box;
    },
  },
};
const fire = (type) => (listeners[type] || []).forEach((fn) => fn({ type }));
console.warn = () => { out.warned += 1; };
console.error = () => {};
const setOnline = (on) => Object.defineProperty(globalThis, 'navigator', { value: { onLine: on }, configurable: true });
const presets = await import(%s);
const showError = (m) => out.errors.push(String(m));
""" % json.dumps(PRESETS_JS.as_uri())


def test_offline_the_chat_area_says_so_once_and_the_presets_toast_is_quiet(tmp_path):
    out = _node(tmp_path, _PAGE + """
        setOnline(false);
        globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
        await presets.loadPresets(showError);
        const offline = out.drawn.slice();
        fire('online');
        out.back = out.box.title.textContent;
        out.box.spec.onRetry();
        delete out.box;
        console.log(JSON.stringify({ ...out, offline }));
    """)
    assert out["errors"] == [], "the presets loader still toasted over an offline page"
    assert out["offline"] == [{"host": True, "kind": "error", "title": "You’re offline.",
                               "retry": "Reload", "icon": None}]
    assert out["back"] == "Back online."
    assert out["reloaded"] == 1, "Reload reloads the page"


def test_online_with_pantheon_not_answering_says_that_instead(tmp_path):
    out = _node(tmp_path, _PAGE + """
        setOnline(true);
        globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
        await presets.loadPresets(showError);
        delete out.box;
        console.log(JSON.stringify(out));
    """)
    assert [d["title"] for d in out["drawn"]] == ["Pantheon isn’t answering."]
    assert out["errors"] == []


def test_a_server_that_answered_badly_is_still_the_presets_own_error(tmp_path):
    out = _node(tmp_path, _PAGE + """
        setOnline(true);
        globalThis.fetch = async () => ({ ok: false, status: 500, json: async () => { throw new SyntaxError('not JSON'); } });
        await presets.loadPresets(showError);
        delete out.box;
        console.log(JSON.stringify(out));
    """)
    assert out["drawn"] == [], "a reached server is not 'offline'"
    assert out["errors"] == ["Failed to load presets"]


def test_a_chat_already_on_screen_is_left_alone(tmp_path):
    out = _node(tmp_path, _PAGE + """
        setOnline(false);
        chatHistory.msgs = 3;
        globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
        await presets.loadPresets(showError);
        delete out.box;
        console.log(JSON.stringify(out));
    """)
    assert out["drawn"] == [] and out["errors"] == []


def test_the_chat_list_does_not_toast_a_request_that_never_reached_the_server(tmp_path):
    """The second toast under the first: `loadSessions` said *Could not load
    chats: Failed to fetch*. A request that never arrived is the chat area's
    line; an HTTP refusal is still the list's own toast."""
    body = js_function(SESSIONS_JS.read_text(encoding="utf-8"), "export async function loadSessions(")
    out = _node(tmp_path, """
        const shown = [];
        const uiModule = { showError: (m) => shown.push(String(m)) };
        let _sessionsWanted = 0, currentSessionId = null;
        const API_BASE = 'http://x';
        const _cleanupIncognitoSessions = async () => {};
        const _isIncognitoSession = () => false;
        globalThis.sessionStorage = { getItem: () => null, removeItem() {} };
        console.warn = () => {}; console.error = () => {};
        let early = null;
        const _earlyFetch = () => early;
        let fetch = async () => { throw new TypeError('Failed to fetch'); };
        async function loadSessions() %s
        const unreached = await loadSessions();
        early = Promise.reject(new TypeError('Failed to fetch'));
        const earlyUnreached = await loadSessions();
        const quiet = shown.slice();
        early = null;
        fetch = async () => ({ ok: false, status: 500, json: async () => ({ detail: 'The chat list is unreadable.' }) });
        const refused = await loadSessions();
        console.log(JSON.stringify({ unreached, earlyUnreached, quiet, refused, shown }));
    """ % body)
    assert out["unreached"] is False and out["earlyUnreached"] is False
    assert out["quiet"] == [], "the chat list toasted a request that never reached the server"
    assert out["refused"] is False
    assert out["shown"] == ["Could not load chats: The chat list is unreadable."]
