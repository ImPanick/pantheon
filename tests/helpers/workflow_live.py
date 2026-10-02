# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-19`, `P22-20`, `P22-24` — the Workbench's Slice E browser half, driven
against the REAL server (`integrate-e`).

Until the wave E merge, `tests/helpers/workflow_ca_fake.py` stood in for
contract C-A while wb-assist's routes were on another branch: a fake server in
JavaScript answering C-A's routes from one in-memory workflow (a check cleared
marks by itself, a fix applied its config by itself, a refusal was a literal),
C-A's five calls laid beside `workflowApi.js` until it had them, and C-A's
literal shapes wherever wb-assist's code was absent. On the merged tree every
one of those stand-ins still answered in place of the code it stood for — a
test of the fake (`Law 20`), so it is deleted.

What replaces it: wb-assist's world (`assist_harness.build_world` — the real
scheduler, the real task and workflow routers, a real SQLite FILE, the real
rule, slots and dispatcher; what would reach outside is the only stand-in: the
model's seam, the chat server's far end, the Integration store) served on a
loopback port by uvicorn in a thread, and the room's `fetch` in node pointed at
it. Every request the browser half makes reaches the real route; every reply it
draws is the real route's, recorded beside the request it answered (`wire`).

`LIVE_PREAMBLE(base)` is the JavaScript each case starts with: the shim, the
real room and source, `net` (the room's fetch: the real server, with the test
app's caller header, every request and its reply recorded in `wire`, each
reply read whole before it is handed on), `quiet()` (waits until no request is
in flight, three times running — the replies come from another thread now, so
a fixed number of timer ticks is no longer a wait for anything), `room()`, and
the small readers the cases share. C-R's door (`openWorkbench({ room })`,
wb-rooms') is the shim's `loadWorkbench` recorder: the room hands it the room
it asked for, and the real door is driven in Chromium and in
`test_skills_and_integrations_are_rooms_js.py`.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path


class LiveServer:
    """`app` served on 127.0.0.1 by uvicorn in a daemon thread."""

    def __init__(self, app):
        import uvicorn

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off",
                                                    access_log=False))
        self.thread = threading.Thread(
            target=lambda: asyncio.run(self.server.serve(sockets=[self.sock])), daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError("the live server did not start")
            time.sleep(0.02)

    def close(self):
        self.server.should_exit = True
        self.thread.join(timeout=15)
        try:
            self.sock.close()
        except OSError:
            pass


# What every Slice E case adds to the canvas shim: a click a download can make,
# the object URLs it makes and takes back, and the room's door to another room
# recorded (C-R's `openWorkbench({ room })`).
SHIM_EXTRA = r"""
export const downloads = { made: [], revoked: [], clicked: [] };
Node.prototype.click = function click() {
  downloads.clicked.push({ tag: this.tagName, download: this.download, href: this.href });
  if (typeof this.onclick === 'function') this.onclick();
};
const realCreate = URL.createObjectURL.bind(URL);
URL.createObjectURL = (blob) => { const u = realCreate(blob); downloads.made.push({ url: u, blob }); return u; };
URL.revokeObjectURL = (u) => { downloads.revoked.push(u); };
export const doors = { opened: [] };
export const loadWorkbench = async () => ({ openWorkbench: (o) => { doors.opened.push(o); return true; } });
"""

_NO_BODY = (101, 204, 205, 304)


def build_sandbox(root: Path, shim: str) -> Path:
    """Every real Workbench module and the `../` modules they reach, with the
    shim (`shim.js` / `dom.js`) and `windowDrag.js`'s two numbers — the C-W
    sandbox, whose fake server is never imported here."""
    from helpers.workflow_cw_fake import build_sandbox as _cw_sandbox

    return _cw_sandbox(root, shim + SHIM_EXTRA)


def as_js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def LIVE_PREAMBLE(base: str, user: str = "alice") -> str:  # noqa: N802 — reads as a constant at call sites
    return (
        "// The DOM shim installs a `fetch` that answers nothing; the real one is\n"
        "// kept first (a dynamic import, so this line runs before the shim does).\n"
        "const realFetch = globalThis.fetch;\n"
        "const { document, Node, fire, settle, host, markup, downloads, doors, loadWorkbench } = await import('./shim.js');\n"
        "const { mountAutomations } = await import('./workflowRoom.js');\n"
        "const { createWorkflowSource } = await import('./workflowSource.js');\n"
        f"const BASE = {as_js(base)}, WHO = {as_js(user)};\n"
        "const out = (o) => console.log(JSON.stringify(o));\n"
        "// Every request, with the real route's reply: { method, url, body, status, reply }.\n"
        "const wire = [];\n"
        "let inflight = 0;\n"
        "const net = async (url, init = {}) => {\n"
        "  url = String(url);\n"
        "  const method = init.method || 'GET';\n"
        "  let body; try { body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined; } catch (_) { body = init.body; }\n"
        "  const seen = { method, url, body, status: 0, reply: null };\n"
        "  wire.push(seen);\n"
        "  inflight += 1;\n"
        "  try {\n"
        "    const res = await realFetch(BASE + url, { ...init, headers: { ...(init.headers || {}), 'x-test-user': WHO } });\n"
        "    const bytes = await res.arrayBuffer();\n"
        "    seen.status = res.status;\n"
        "    try { seen.reply = JSON.parse(new TextDecoder().decode(bytes)); } catch (_) { seen.reply = null; }\n"
        f"    return new Response({as_js(list(_NO_BODY))}.includes(res.status) ? null : bytes,\n"
        "      { status: res.status, statusText: res.statusText, headers: res.headers });\n"
        "  } finally { inflight -= 1; }\n"
        "};\n"
        "const quiet = async () => { for (let calm = 0; calm < 3;) { await settle(15); calm = inflight ? 0 : calm + 1; } };\n"
        "const by = (root, cls) => root.querySelector('.' + cls);\n"
        "const all = (root, cls) => root.querySelectorAll('.' + cls);\n"
        "const shown = (n) => { for (let x = n; x; x = x.parentNode) if (x.hidden) return false; return true; };\n"
        "const sayOf = (root) => { const s = root.querySelectorAll('.wb-say-text').filter(shown);\n"
        "  return s.length ? s[s.length - 1].textContent : root.querySelector('.wf-say-text').textContent; };\n"
        "const sayButton = (root) => { const b = root.querySelectorAll('.wb-say-action').filter((x) => !x.hidden && shown(x));\n"
        "  return b.length ? b[b.length - 1] : null; };\n"
        "const nodeEl = (root, id) => root.querySelectorAll('.wb-node').find((n) => n.dataset.itemId === id) || null;\n"
        "const steps = (root) => root.querySelector('.wf-edit').querySelectorAll('.wb-node')\n"
        "  .filter((n) => n.dataset.itemId && n.dataset.itemId !== '__start__');\n"
        "const typed = (el, value) => { el.value = value;\n"
        "  el.dispatchEvent({ type: 'input', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
        "const mountTaskFields = () => ({ destroy() {} });\n"
        "const room = async (o = {}) => {\n"
        "  const r = host();\n"
        "  const handle = mountAutomations(r, { fetch: net, mountTaskFields, describeTrigger: () => 'On a webhook',\n"
        "    loadWorkbench, ...o });\n"
        "  await handle.ready; await quiet();\n"
        "  return { r, handle };\n"
        "};\n"
        "// What the browser sent: [url, body] per request of `method` whose url passes `pred`.\n"
        "const calls = (method, pred = () => true) => wire.filter((c) => c.method === method && pred(c.url))\n"
        "  .map((c) => [c.url, c.body === undefined ? null : c.body]);\n"
        "// The real route's reply to the last such request.\n"
        "const replyTo = (method, pred) => { const c = wire.filter((x) => x.method === method && pred(x.url)); return c.length ? c[c.length - 1] : null; };\n"
        "// Read something from the server directly, as the browser would (recorded too).\n"
        "const ask = async (url) => (await net(url)).json();\n"
    )
