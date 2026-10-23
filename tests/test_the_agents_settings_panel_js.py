# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-15` — Settings → Agents, driven under node.

The real `static/js/agentsSettings.js` against the panel's own element ids read
from the shipped `static/index.html`, a recorded `fetch` that keeps settings as
`POST /api/auth/settings` keeps them (the switch a yes/no, the number clamped
to 1–16), and a stub `appConfig.js` that counts invalidations.

What is pinned: the panel draws what is stored; a change saves exactly that
key; it then draws what the server KEPT (so a clamped number shows clamped);
a refusal is the server's sentence and the panel goes back to the stored
value; and the shared settings snapshot is invalidated after a save.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

IDS = ["agents-pausedToggle", "agents-maxInput", "agents-settingsResult"]

_SHIM = r"""
class El {
  constructor(id) { this.id = id; this.checked = false; this.value = ''; this.hidden = true;
    this.textContent = ''; this._on = {}; this._cls = new Set();
    this.classList = { toggle: (c, on) => { on ? this._cls.add(c) : this._cls.delete(c); },
                       contains: (c) => this._cls.has(c) }; }
  addEventListener(type, fn) { (this._on[type] ||= []).push(fn); }
  fire(type) { (this._on[type] || []).forEach((fn) => fn({ target: this })); }
}
export const els = Object.fromEntries(%IDS%.map((id) => [id, new El(id)]));
globalThis.document = { getElementById: (id) => els[id] || null };
export const server = { stored: { agents_paused: false, agents_max_concurrent: 2 }, posts: [], invalidated: 0 };
globalThis.fetch = async (url, opts = {}) => {
  const reply = (status, payload) => ({ ok: status < 300, status, json: async () => payload });
  if ((opts.method || 'GET') === 'GET') return reply(200, { ...server.stored, other: 'x' });
  const body = JSON.parse(opts.body);
  server.posts.push({ ...body });
  if ('agents_paused' in body && typeof body.agents_paused !== 'boolean')
    return reply(400, { detail: 'agents_paused must be true or false' });
  if ('agents_max_concurrent' in body)
    body.agents_max_concurrent = Math.min(16, Math.max(1, body.agents_max_concurrent));
  Object.assign(server.stored, body);
  return reply(200, { ok: true });
};
export const settle = () => new Promise((r) => setTimeout(r, 20));
"""

_PREAMBLE = (
    "import { els, server, settle } from './shim.js';\n"
    "const mod = await import('./agentsSettings.js');\n"
    "const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };\n"
)


def test_the_panels_ids_are_the_pages():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    start = html.index('<div data-settings-panel="agents"')
    end = html.index('<div data-settings-panel="workstation"', start)
    assert set(IDS) <= set(re.findall(r'\bid="([^"]+)"', html[start:end]))


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("agents-settings")
    (d / "shim.js").write_text(_SHIM.replace("%IDS%", json.dumps(IDS)))
    (d / "appConfig.js").write_text(
        "import { server } from './shim.js';\nexport function invalidateSettings() { server.invalidated += 1; }\n")
    shutil.copy(ROOT / "static" / "js" / "agentsSettings.js", d / "agentsSettings.js")
    return d


def _run(sandbox, script):
    (sandbox / "case.mjs").write_text(_PREAMBLE + textwrap.dedent(script))
    proc = subprocess.run(["node", "case.mjs"], cwd=sandbox, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_it_draws_what_is_stored_and_a_switch_saves_its_one_key(sandbox):
    out = _run(sandbox, """
        server.stored.agents_max_concurrent = 4;
        await mod.open();
        const drawn = [els['agents-pausedToggle'].checked, els['agents-maxInput'].value];
        els['agents-pausedToggle'].checked = true; els['agents-pausedToggle'].fire('change'); await settle();
        out({ drawn, posts: server.posts, stored: server.stored.agents_paused,
              said: els['agents-settingsResult'].textContent, invalidated: server.invalidated });
    """)
    assert out == {"drawn": [False, "4"], "posts": [{"agents_paused": True}], "stored": True,
                   "said": "Every agent is paused.", "invalidated": 1}


def test_a_number_past_its_range_shows_what_was_kept(sandbox):
    out = _run(sandbox, """
        await mod.open();
        els['agents-maxInput'].value = '40'; els['agents-maxInput'].fire('change'); await settle();
        const kept = [els['agents-maxInput'].value, els['agents-settingsResult'].textContent];
        els['agents-maxInput'].value = 'many'; els['agents-maxInput'].fire('change'); await settle();
        out({ kept, posts: server.posts, said: els['agents-settingsResult'].textContent });
    """)
    assert out == {"kept": ["16", "Saved: at most 16 at once."], "posts": [{"agents_max_concurrent": 40}],
                   "said": "Type a whole number."}


def test_a_refusal_is_the_servers_sentence_and_the_panel_goes_back(sandbox):
    out = _run(sandbox, """
        await mod.open();
        await mod.save({ agents_paused: 'yes' });
        out({ said: els['agents-settingsResult'].textContent,
              error: els['agents-settingsResult'].classList.contains('agents-settings-error'),
              checked: els['agents-pausedToggle'].checked, invalidated: server.invalidated });
    """)
    assert out == {"said": "agents_paused must be true or false", "error": True, "checked": False,
                   "invalidated": 0}


def test_opening_twice_wires_once(sandbox):
    out = _run(sandbox, """
        await mod.open(); await mod.open();
        els['agents-pausedToggle'].checked = true; els['agents-pausedToggle'].fire('change'); await settle();
        out(server.posts.length);
    """)
    assert out == 1
