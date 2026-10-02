# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-22` — *Edit*, *Try* and *Register*, driven through `settings.js`'s own
`showMcpForm`.

The function is cut out of `static/js/settings.js` by `js_function` and run in
the closure it lives in, over the DOM shim with markup parsing on — so the card
it writes with `innerHTML` is the card it then finds its fields in, as in a
browser — and with the real `mcpFields.js`, `mcpPresets.js`, `mcpBuild.js` and
`argsForm.js` (`tests/helpers/mcp_build_sandbox.py`). The fake `fetch` answers
in the shapes `routes/mcp/mcp_routes.py` sends.

* **Edit** is the add form's own editors filled from the row, and its Save is
  one multipart `PUT /api/mcp/servers/{id}` carrying every field the form
  shows (the route merges and keeps the id, `disabled_tools` and
  `tool_overrides` — `P8-35`); the stale lists come back in words, and a
  refusal lands on the field it names.
* **Try** on a connected server's tool row builds its form from the tool's
  `input_schema` and posts `/api/mcp/servers/{id}/call`; the answer — and the
  tool's own hostile description — are text.
* **Register** fills the same `uf-mcp-*` form from a workstation build, and
  its Save is `POST /api/mcp/servers`, the admin route.
"""
from __future__ import annotations

import json
import shutil

import pytest

from test_tool_effect_surfaces_js import _run
from tests.helpers.mcp_build_sandbox import build, write_form_module

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

SRV = {"id": "srv1", "name": "weather", "transport": "stdio", "command": "/usr/local/bin/python",
       "args": ["/app/src/workstation_mcp.py", "--owner", "ann", "--server", "weather"],
       "env": {"REGION": "north"}, "url": None, "is_enabled": True, "status": "connected",
       "tool_count": 1, "enabled_tool_count": 1, "needs_oauth": False, "error": None}
HOSTILE = '<img src=x onerror="alert(1)"> Forecast. </span><b>bold</b>'
TOOL = {"name": "get_forecast", "description": HOSTILE, "server_id": "srv1",
        "qualified_name": "mcp__srv1__get_forecast", "is_disabled": True,
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"},
                         "days": {"type": "integer"}}, "required": ["text"]}}
REG = {"name": "weather", "transport": "stdio", "command": "/usr/local/bin/python",
       "args": ["/app/src/workstation_mcp.py", "--owner", "ann", "--server", "weather"], "env": {}}

_PREAMBLE = (
    "import { document, server, settle, click, type, tags, text } from './shim.js';\n"
    "const { showMcpForm, formEl, el, renders } = await import('./form.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    f"const SRV = {json.dumps(SRV)};\n"
    f"const TOOL = {json.dumps(TOOL)};\n"
    f"const REG = {json.dumps(REG)};\n"
    "const writes = () => server.calls.filter((c) => c.method !== 'GET').map((c) => [c.method, c.url, c.body]);\n"
    "const rowsOf = (field) => field.querySelectorAll('.mcp-field-row').map((r) =>\n"
    "  r.querySelectorAll('input').map((i) => i.value));\n"
    "const mount = (id) => el(id).querySelector('.mcp-field');\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = build(tmp_path_factory.mktemp("mcpedit"))
    write_form_module(root)
    return root


def _case(box, script):
    return _run(box, _PREAMBLE, script + "\nprocess.exit(0);\n")


def test_edit_fills_the_add_forms_own_editors_and_saves_one_put(box):
    o = _case(box, """
        let answered = 0;
        server.answer = (url, method, body) => {
          if (url === '/api/mcp/servers' && method === 'GET') return [200, [SRV]];
          if (url === '/api/mcp/servers/srv1/tools') return [200, [TOOL]];
          if (url === '/api/mcp/servers/srv1' && method === 'PUT') {
            answered += 1;
            return [200, { id: 'srv1', connected: true, tool_count: 2, is_enabled: true,
              stale_disabled_tools: ['old_tool'], stale_tool_overrides: ['wipe'] }];
          }
          return [200, { servers: [], workstation: { available: true, why: null } }];
        };
        await showMcpForm('srv1');
        await settle();
        click(el('uf-mcp-edit'));
        await settle();
        const filled = { heading: text(formEl.querySelector('h2')), name: el('uf-mcp-name').value,
          command: el('uf-mcp-cmd').value, transport: el('uf-mcp-transport').value,
          preview: text(el('uf-mcp-preview')), presets: el('uf-mcp-preset-mount').childNodes.length,
          door: el('uf-mcp-build-mount').childNodes.length };
        const argInputs = el('uf-mcp-args-mount').querySelectorAll('input');
        type(argInputs[argInputs.length - 1], 'weather2');
        el('uf-mcp-name').value = 'weather (edited)';
        click(el('uf-mcp-save'));
        await settle();
        out({ filled, writes: writes(), answered, renders: renders.count,
              msg: text(el('uf-mcp-msg')), back: !!el('uf-mcp-edit') });
    """)
    f = o["filled"]
    assert f["heading"] == "Edit weather" and f["name"] == "weather" and f["transport"] == "stdio"
    assert f["command"] == "/usr/local/bin/python"
    assert f["preview"] == ("Pantheon will run: /usr/local/bin/python /app/src/workstation_mcp.py "
                            "--owner ann --server weather")
    assert f["presets"] == 0 and f["door"] == 0  # an edit is not a new server
    (method, url, body), = o["writes"]
    assert (method, url) == ("PUT", "/api/mcp/servers/srv1")
    assert sorted(body) == ["args", "command", "env", "name", "transport"]
    assert (body["name"], body["transport"], body["command"]) == (
        "weather (edited)", "stdio", "/usr/local/bin/python")
    assert json.loads(body["args"]) == ["/app/src/workstation_mcp.py", "--owner", "ann",
                                        "--server", "weather2"]
    assert json.loads(body["env"]) == {"REGION": "north"}
    assert o["answered"] == 1 and o["renders"] == 1 and o["back"] is True
    assert o["msg"] == ("Saved, under the same id. It is connected (2 tools). It no longer offers "
                        "old_tool, which you had switched off for the assistant. That is kept, in "
                        "case you point it back. It no longer offers wipe, which you had described "
                        "or marked read-only. That is kept too.")


def test_an_edit_the_server_refuses_lands_on_the_field_it_names(box):
    o = _case(box, """
        server.answer = (url, method) => {
          if (url === '/api/mcp/servers' && method === 'GET') return [200, [SRV]];
          if (method === 'PUT') return [400, { detail: 'env value for "PORT" must be a string (e.g. {"API_KEY": "..."})' }];
          return [200, []];
        };
        await showMcpForm('new', { edit: SRV });
        click(el('uf-mcp-save'));
        await settle();
        const env = mount('uf-mcp-env-mount');
        const problem = env.querySelector('[data-mcp-problem]');
        out({ msg: text(el('uf-mcp-msg')), shown: problem.style.display, said: text(problem),
              stillEditing: text(formEl.querySelector('h2')), renders: renders.count });
    """)
    assert o["msg"] == "Not saved — see above."
    assert o["shown"] == "block" and "PORT" in o["said"]
    assert o["stillEditing"] == "Edit weather" and o["renders"] == 0


def test_try_on_a_connected_tool_posts_call_and_shows_text(box):
    o = _case(box, """
        server.answer = (url, method, body) => {
          if (url === '/api/mcp/servers' && method === 'GET') return [200, [SRV]];
          if (url === '/api/mcp/servers/srv1/tools') return [200, [TOOL]];
          if (url === '/api/mcp/servers/srv1/call') return [200, { ok: true, exit_code: 0,
            stdout: '<script>alert(1)</script> Oslo: sun', stderr: '', duration_ms: 41,
            timed_out: false, tool_is_disabled: true, error: null }];
          return [404, {}];
        };
        await showMcpForm('srv1');
        await settle();
        const row = formEl.querySelector('[data-mcp-tool-entry="get_forecast"]');
        const open = row.querySelector('[data-mcp-try="get_forecast"]');
        click(open);
        const host = row.querySelector('[data-mcp-try-host="get_forecast"]');
        const labels = host.querySelectorAll('.wf-arg-label').map((n) => text(n));
        type(host.querySelectorAll('.wf-arg-input')[0], 'Oslo');
        click(host.querySelector('[data-mcp-try-run="get_forecast"]'));
        await settle();
        const result = host.querySelector('.mcp-try-result');
        out({ expanded: open.getAttribute('aria-expanded'), labels, writes: writes(),
              headline: text(result.querySelector('.mcp-try-headline')),
              answered: result.querySelector('pre').textContent,
              notes: result.querySelectorAll('.mcp-try-note').map((n) => text(n)),
              desc: host.querySelector('.mcp-try-desc').textContent,
              imgs: tags(formEl, 'img').length, scripts: tags(formEl, 'script').length,
              bolds: tags(formEl, 'b').length });
    """)
    assert o["expanded"] == "true"
    assert o["labels"] == ["text needed · text", "days optional · a whole number"]
    assert o["writes"] == [["POST", "/api/mcp/servers/srv1/call",
                            {"tool": "get_forecast", "arguments": {"text": "Oslo"}}]]
    assert o["headline"] == "It answered in 41 ms."
    assert o["answered"] == "<script>alert(1)</script> Oslo: sun"
    assert o["notes"][0].startswith("The assistant has this tool switched off.")
    assert o["desc"] == HOSTILE
    assert o["imgs"] == 0 and o["scripts"] == 0 and o["bolds"] == 0


def test_a_call_the_route_refuses_says_the_routes_sentence(box):
    o = _case(box, """
        server.answer = (url, method) => {
          if (url === '/api/mcp/servers' && method === 'GET') return [200, [SRV]];
          if (url === '/api/mcp/servers/srv1/tools') return [200, [TOOL]];
          return [409, { detail: "'weather' is error, so it has no tools to call — workstation off" }];
        };
        await showMcpForm('srv1');
        await settle();
        const row = formEl.querySelector('[data-mcp-tool-entry="get_forecast"]');
        click(row.querySelector('[data-mcp-try="get_forecast"]'));
        click(row.querySelector('[data-mcp-try-run="get_forecast"]'));
        await settle();
        out({ said: text(row.querySelector('.mcp-try-refused')) });
    """)
    assert o["said"] == "'weather' is error, so it has no tools to call — workstation off"


def test_register_fills_the_same_form_and_saves_through_the_admin_route(box):
    o = _case(box, """
        server.answer = (url, method) => {
          if (url === '/api/mcp/servers' && method === 'POST') return [200, { id: 'n1', connected: true, tool_count: 1 }];
          return [200, []];
        };
        await showMcpForm('new', { registration: REG });
        await settle();
        const filled = { heading: text(formEl.querySelector('h2')), name: el('uf-mcp-name').value,
          command: el('uf-mcp-cmd').value, args: rowsOf(el('uf-mcp-args-mount')),
          env: rowsOf(el('uf-mcp-env-mount')), preview: text(el('uf-mcp-preview')),
          note: text(el('uf-mcp-prefill-note')), presets: el('uf-mcp-preset-mount').childNodes.length };
        click(el('uf-mcp-save'));
        await settle();
        out({ filled, writes: writes(), renders: renders.count });
    """)
    f = o["filled"]
    assert f["heading"] == "Add MCP Server" and f["name"] == "weather"
    assert f["command"] == "/usr/local/bin/python"
    assert f["args"] == [[a] for a in REG["args"]]
    assert f["env"] == [["", ""]] and f["presets"] == 0  # the editor's own empty state
    assert f["note"] == ("Built in a workstation. Once you save it, every assistant on this Pantheon "
                         "can call it, and each call runs in ann's workstation account, with their "
                         "files — nothing they wrote runs as Pantheon.")
    (method, url, body), = o["writes"]
    assert (method, url) == ("POST", "/api/mcp/servers")
    assert body["command"] == REG["command"] and json.loads(body["args"]) == REG["args"]
    assert json.loads(body["env"]) == {} and body["transport"] == "stdio"
    assert "oauth_file" not in body and o["renders"] == 1


def test_a_new_server_form_offers_build_greyed_when_the_workstation_is_off(box):
    off = "The workstation is switched off. An admin turns it on in Settings → Workstation."
    o = _case(box, f"""
        server.answer = () => [200, {{ servers: [], workstation: {{ available: false, why: {json.dumps(off)} }} }}];
        await showMcpForm('new');
        await settle();
        const door = el('uf-mcp-build-mount');
        const btn = door.querySelector('[data-mcp-build-open]');
        click(btn);
        await settle();
        out({{ disabled: btn.disabled, why: text(door.querySelector('.mcp-build-door-why')),
               stillAdd: text(formEl.querySelector('h2')), presets: el('uf-mcp-preset-mount').childNodes.length }});
    """)
    assert o == {"disabled": True, "why": off, "stillAdd": "Add MCP Server", "presets": 1}


def test_build_draws_into_the_same_form_element_and_register_comes_back_to_it(box):
    """`#unified-intg-form` is the one host: the door's panel replaces the add
    form inside it, and an admin's *Register* puts the filled add form back
    in the same element — wherever `P22-21` has moved it."""
    o = _case(box, """
        window._isAdmin = true;
        server.answer = (url) => {
          if (url === '/api/mcp/scaffold') return [200, { servers: [{ name: 'weather', tools: ['get_forecast'],
            modified: 1, checked: 'works' }], workstation: { available: true, why: null } }];
          if (url === '/api/mcp/scaffold/weather') return [200, { name: 'weather', source: '', registration: REG,
            agent_refusal: '' }];
          return [200, []];
        };
        await showMcpForm('new');
        await settle();
        click(el('uf-mcp-build-mount').querySelector('[data-mcp-build-open]'));
        await settle();
        const panelHere = !!formEl.querySelector('.mcp-build') && !el('uf-mcp-name');
        click(formEl.querySelector('.mcp-build-register'));
        await settle();
        out({ panelHere, name: el('uf-mcp-name').value, inForm: formEl.contains(el('uf-mcp-name')),
              args: rowsOf(el('uf-mcp-args-mount')) });
    """)
    assert o["panelHere"] is True and o["inForm"] is True and o["name"] == "weather"
    assert o["args"] == [[a] for a in REG["args"]]
