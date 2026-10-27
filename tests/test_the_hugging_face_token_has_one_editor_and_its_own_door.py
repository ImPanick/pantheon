# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1258` — one home for "how the LLM is served": the Hugging Face token.

The owner's ruling asked for the Hugging Face switch "along with how the LLM is
served" in admin settings. **Measured on `a16e7d75`:** the token's only editor
was inside the Forge (`cookbook.js`, `#hwfit-hftoken`), and it was written by
the Forge's whole-state save — `POST /api/cookbook/state` carrying the browser's
`_envState.hfToken` — so Settings → Forge could only offer a door to it, and a
Forge open in another tab re-posted whatever its own copy of the state said.
`allow_model_download`, the other Hugging Face switch (the embedding and
Whisper models Pantheon itself fetches), lived in Settings → System with
nothing in Settings → Forge pointing at it.

Now:

* the token has its own route, `GET`/`PUT /api/cookbook/hf-token`, the
  operator's (`require_operator`) — the whole-state save no longer writes it,
  and no answer ever carries it back;
* one editor, `static/js/servingSettings.js` `mountHfToken`, mounted by
  Settings → Forge (its home) and by the Forge's Settings tab;
* Settings → Forge's Hugging Face card says what `allow_model_download` is set
  to and has a door to its one control.

Driven: the real routes on a real temp state file through the real router, and
the real module under node against the page's own markup.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "hf_abcdefghijklmnopqrstuvwxyz0123"


@pytest.fixture()
def forge(monkeypatch, tmp_path):
    """The real cookbook router over a temp state file, as the operator
    (`ADMIN`) or a member who is not (`MEMBER`)."""
    from tests.helpers.signed_in import ADMIN, MEMBER, as_person, signed_in
    import routes.cookbook_routes as cr

    manager = signed_in(monkeypatch, tmp_path / "auth")
    state = tmp_path / "cookbook_state.json"
    state.write_text(json.dumps({"env": {"servers": [{"name": "lab", "host": "me@lab"}]},
                                 "tasks": [], "presets": []}), encoding="utf-8")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    monkeypatch.setattr(cr, "COOKBOOK_STATE_FILE", str(state))

    def client(person):
        app = FastAPI()
        app.include_router(cr.setup_cookbook_routes())
        return TestClient(as_person(app, person, auth_manager=manager))

    return client, state, ADMIN, MEMBER


def _on_disk(state: Path) -> dict:
    return json.loads(state.read_text(encoding="utf-8"))


def test_the_operator_stores_it_encrypted_and_no_answer_carries_it(forge):
    client, state, admin, _ = forge
    op = client(admin)
    assert op.get("/api/cookbook/hf-token").json() == {
        "configured": False, "masked": "", "from_environment": False}
    r = op.put("/api/cookbook/hf-token", json={"token": TOKEN})
    assert r.status_code == 200, r.text
    assert r.json()["configured"] is True and TOKEN not in r.text
    stored = _on_disk(state)["env"]["hfToken"]
    assert stored and TOKEN not in json.dumps(_on_disk(state)), "kept encrypted"
    from routes.cookbook_helpers import load_stored_hf_token
    assert load_stored_hf_token(state_path=state) == TOKEN, "what downloads and serves read"
    assert _on_disk(state)["env"]["servers"] == [{"name": "lab", "host": "me@lab"}], \
        "nothing else in the state was touched"
    assert TOKEN not in op.get("/api/cookbook/hf-token").text
    assert TOKEN not in op.get("/api/cookbook/state").text


def test_empty_removes_it_and_a_bad_one_is_refused_with_a_sentence(forge):
    client, state, admin, _ = forge
    op = client(admin)
    op.put("/api/cookbook/hf-token", json={"token": TOKEN})
    r = op.put("/api/cookbook/hf-token", json={"token": "hf bad token"})
    assert r.status_code == 400
    assert "Hugging Face token" in r.json()["detail"]
    assert op.get("/api/cookbook/hf-token").json()["configured"] is True, "a refusal changes nothing"
    assert op.put("/api/cookbook/hf-token", json={"token": ""}).json()["configured"] is False
    assert "hfToken" not in _on_disk(state)["env"]


def test_the_environment_variable_is_said_when_nothing_is_stored(forge, monkeypatch):
    client, _, admin, _ = forge
    monkeypatch.setenv("HF_TOKEN", "hf_from_the_environment")
    got = client(admin).get("/api/cookbook/hf-token").json()
    assert got == {"configured": False, "masked": "", "from_environment": True}


def test_a_member_who_does_not_run_the_instance_cannot_read_or_write_it(forge):
    client, state, _, member = forge
    m = client(member)
    assert m.get("/api/cookbook/hf-token").status_code == 403
    assert m.put("/api/cookbook/hf-token", json={"token": TOKEN}).status_code == 403
    assert "hfToken" not in _on_disk(state)["env"]


def test_the_whole_state_save_no_longer_writes_it(forge):
    """A Forge open in another tab re-posts its own copy of the state; the
    token is not part of that copy any more, in either direction."""
    client, state, admin, _ = forge
    op = client(admin)
    op.put("/api/cookbook/hf-token", json={"token": TOKEN})
    kept = _on_disk(state)["env"]["hfToken"]
    body = {"env": {"servers": [{"name": "lab", "host": "me@lab"}], "hfToken": "hf_from_a_stale_tab"},
            "tasks": [], "presets": []}
    assert op.post("/api/cookbook/state", json=body).status_code == 200
    assert _on_disk(state)["env"]["hfToken"] == kept, "a stale tab cannot replace it"
    body["env"].pop("hfToken")
    assert op.post("/api/cookbook/state", json=body).status_code == 200
    assert _on_disk(state)["env"]["hfToken"] == kept, "nor clear it by leaving it out"


# ── the one editor, under node ─────────────────────────────────────────────

_SHIM = r"""
class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this.hidden = false;
    this.textContent = ''; this.value = ''; this.disabled = false; this.style = {}; this.className = '';
    this.placeholder = ''; this._on = {}; this.id = ''; this.type = ''; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') this.id = String(v);
    if (k === 'type') this.type = String(v); if (k === 'placeholder') this.placeholder = String(v); }
  append(...n) { this.children.push(...n); }
  appendChild(n) { this.children.push(n); return n; }
  removeChild(n) { this.children = this.children.filter((c) => c !== n); }
  get firstChild() { return this.children[0] || null; }
  addEventListener(t, f) { (this._on[t] ||= []).push(f); }
  click() { (this._on.click || []).forEach((f) => f({ target: this })); }
}
const docListeners = {};
globalThis.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = o && o.detail; } };
globalThis.document = {
  createElement: (t) => new El(t),
  addEventListener: (t, f) => { (docListeners[t] ||= []).push(f); },
  dispatchEvent: (e) => { (docListeners[e.type] || []).forEach((f) => f(e)); return true; },
};
export const server = { stored: '', puts: [] };
globalThis.fetch = async (url, opts = {}) => {
  const reply = (status, payload) => ({ ok: status < 300, status, json: async () => payload });
  const answer = () => ({ configured: !!server.stored, masked: server.stored ? 'hf_…123' : '',
                          from_environment: false });
  if ((opts.method || 'GET') === 'GET') return reply(200, answer());
  const body = JSON.parse(opts.body);
  server.puts.push(body.token);
  if (/\s/.test(body.token)) return reply(400, { detail: 'That is not a Hugging Face token.' });
  server.stored = body.token;
  return reply(200, answer());
};
export const El_ = El;
export const settle = () => new Promise((r) => setTimeout(r, 20));
"""


def _node(script: str, tmp_path: Path) -> dict:
    shutil.copy(ROOT / "static" / "js" / "servingSettings.js", tmp_path / "servingSettings.js")
    (tmp_path / "shim.js").write_text(_SHIM)
    (tmp_path / "case.mjs").write_text(
        "import { server, El_, settle } from './shim.js';\n"
        "const mod = await import('./servingSettings.js');\n"
        "const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };\n"
        "const find = (host, tag, text) => host.children.flatMap((c) => c.children.length ? c.children : [c])"
        ".find((n) => n.tagName === tag && (!text || n.textContent === text));\n"
        + textwrap.dedent(script))
    proc = subprocess.run(["node", "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_editor_saves_through_its_route_and_both_mounts_agree(tmp_path):
    out = _node("""
        const a = new El_('div'), b = new El_('div');
        mod.mountHfToken(a, { inputId: 'set-a' }); mod.mountHfToken(b, { inputId: 'set-b' });
        await settle();
        const status = (h) => h.children[1].textContent;
        const before = status(a);
        const input = find(a, 'input'); input.value = '  hf_good_token_123  ';
        find(a, 'button', 'Save').click(); await settle();
        const saved = [status(a), status(b), input.value, find(b, 'button', 'Remove').hidden];
        input.value = 'hf bad'; find(a, 'button', 'Save').click(); await settle();
        const refused = status(a);
        input.value = ''; find(a, 'button', 'Save').click(); await settle();
        const empty = status(a);
        find(a, 'button', 'Remove').click(); await settle();
        out({ before, saved, refused, empty, removed: status(b), puts: server.puts,
              label: find(a, 'label').attrs.for, id: input.id });
    """, tmp_path)
    assert out["before"].startswith("None stored.")
    assert out["saved"] == ["Saved. Stored (hf_…123). Downloads of gated and private models use it.",
                            "Stored (hf_…123). Downloads of gated and private models use it.",
                            "", False]
    assert out["refused"] == "That is not a Hugging Face token."
    assert out["empty"] == "Type a token to save it, or Remove to clear the stored one."
    assert out["removed"].startswith("None stored."), "the other window's copy follows"
    assert out["puts"] == ["hf_good_token_123", "hf bad", ""]
    assert out["label"] == out["id"] == "set-a"


def test_both_windows_mount_the_one_editor_and_the_forge_writes_no_token_of_its_own():
    settings_js = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    cookbook_js = (ROOT / "static" / "js" / "cookbook.js").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for source in (settings_js, cookbook_js):
        assert re.search(r"import \{[^}]*\bmountHfToken\b[^}]*\} from '\./servingSettings\.js'", source)
        assert re.search(r"\bmountHfToken\(", source)
    assert 'id="hwfit-hftoken"' not in cookbook_js, "the Forge's own token field is gone"
    forge_panel = html[html.index('<div data-settings-panel="forge"'):html.index("<!-- ═══ TOOLS TAB ═══ -->")]
    assert 'id="set-forgeHfToken"' in forge_panel
    assert 'data-forge-door="settings:system"' in forge_panel, "allow_model_download's door"
