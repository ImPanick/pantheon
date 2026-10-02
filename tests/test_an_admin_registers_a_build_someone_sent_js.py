# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1130` — the browser half: a person sends a build; an admin reads its code
and *Register* fills the existing Add MCP Server form, pin included.

Driven, not read (`Law 20`): the real `static/js/settings/mcpBuild.js` (with
the real `argsForm.js`, `mcpFields.js`, `mcpPresets.js`) and `settings.js`'s own
`showMcpForm`, cut out by `js_function` and run in its closure
(`tests/helpers/mcp_build_sandbox.py`), over the DOM shim with markup parsing.
The fake `fetch` answers in the shapes `routes/mcp/mcp_routes.py` sends; the
server half is `test_an_admin_registers_a_build_someone_sent.py`, against the
real routes and a real workstation.

What a person can see is what is asserted, and what the module sends:

  * a non-admin's *Register* → *Send it to an admin* posts the server's name and
    nothing else, says where an admin finds it, and *Withdraw* takes it back;
    a send whose code changed since says so;
  * an admin sees what waits — who, when, what it offers, and the command line
    Register fills in, fingerprint included — reads every file as text (a
    compiled file or a link named as unreadable), and *Register this code*
    fills the form with the registration exactly as served, `--sha256`
    included, which saves through `POST /api/mcp/servers`;
  * a build that changed since it was sent offers no Register;
  * nothing a sender wrote ever becomes an element.
"""
from __future__ import annotations

import json
import shutil

import pytest

from test_tool_effect_surfaces_js import _run
from tests.helpers.mcp_build_sandbox import build, write_form_module

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

PIN = "0123456789abcdef" * 4
REG = __import__("src.workstation_mcp", fromlist=["ws_registration"]).ws_registration("ann", "weather", PIN)
WHERE = __import__("src.workbench_rooms", fromlist=["ADD_MCP_SERVER_PATH"]).ADD_MCP_SERVER_PATH
HOSTILE = '<img src=x onerror="alert(1)">'
SOURCE = f"# {HOSTILE}\nprint('</pre><script>alert(2)</script>')\n"
ENTRY = {"id": "s1", "owner": "ann", "server": "weather", "sent_at": 1790000000.0,
         "registered_before": True, "pin": PIN, "registration": REG,
         "tools": [{"name": "get_forecast", "description": HOSTILE}],
         "files": [{"path": "server.py", "kind": "source", "bytes": len(SOURCE)},
                   {"path": "__pycache__/x.pyc", "kind": "compiled", "bytes": 30},
                   {"path": "lib.py", "kind": "link", "target": "/etc/hostname"}]}
DETAIL = dict(ENTRY, files=[{"path": "server.py", "kind": "source", "bytes": len(SOURCE),
                             "sha256": "f" * 64, "text": SOURCE},
                            {"path": "__pycache__/x.pyc", "kind": "compiled", "bytes": 30,
                             "sha256": "e" * 64},
                            {"path": "lib.py", "kind": "link", "target": "/etc/hostname"}],
              registration=REG, now="as_sent", now_why=None)

_PREAMBLE = (
    "import { document, server, settle, click, type, tags, text } from './shim.js';\n"
    "const B = await import('./settings/mcpBuild.js');\n"
    "const { showMcpForm, formEl, el } = await import('./form.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    f"const REG = {json.dumps(REG)};\n"
    f"const ENTRY = {json.dumps(ENTRY)};\n"
    f"const DETAIL = {json.dumps(DETAIL)};\n"
    f"const WHERE = {json.dumps(WHERE)};\n"
    "const writes = () => server.calls.filter((c) => c.method !== 'GET').map((c) => [c.method, c.url, c.body]);\n"
    "const rowsOf = (field) => field.querySelectorAll('.mcp-field-row').map((r) =>\n"
    "  r.querySelectorAll('input').map((i) => i.value));\n"
    "const host = document.createElement('div'); document.body.appendChild(host);\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = build(tmp_path_factory.mktemp("mcpsent"))
    write_form_module(root)
    return root


def _case(box, script):
    return _run(box, _PREAMBLE, script + "\nprocess.exit(0);\n")


_PERSON = """
    window._isAdmin = false;
    let sent = SENT;
    server.answer = (url, method) => {
      if (url === '/api/mcp/scaffold') return [200, { servers: [{ name: 'weather', tools: ['get_forecast'],
        modified: 1, checked: 'works', sent: sent && { id: sent.id, at: sent.at } }],
        workstation: { available: true, why: null } }];
      if (url === '/api/mcp/scaffold/weather') return [200, { name: 'weather', source: 'x', registration: REG,
        agent_refusal: '', registered: 'no', sent }];
      if (url === '/api/mcp/scaffold/weather/send' && method === 'POST') {
        sent = { id: 's2', at: 1790000100, as_sent: true };
        return [200, { sent: { id: 's2', owner: 'ann', server: 'weather', sent_at: 1790000100,
                               tools: [], files: [], pin: REG.args[6], registration: REG, where: WHERE } }];
      }
      if (url === '/api/mcp/builds-sent/s2' && method === 'DELETE') { sent = null;
        return [200, { removed: true, server: 'weather' }]; }
      return [404, { detail: 'Not Found' }];
    };
    await B.mountMcpBuild(host, { isAdmin: false, onRegister: () => { throw new Error('not an admin'); } });
    click(host.querySelector('.mcp-build-register'));
    await settle();
    const reg = host.querySelector('.mcp-build-registration');
"""


def test_a_person_sends_it_to_an_admin_and_can_take_it_back(box):
    o = _case(box, "const SENT = null;\n" + _PERSON + """
        const before = { lead: text(reg.querySelector('.mcp-build-admin-only')),
          send: text(reg.querySelector('.mcp-build-send')),
          withdrawShown: reg.querySelector('.mcp-build-withdraw').style.display !== 'none',
          fold: text(reg.querySelector('.mcp-build-fields-fold').childNodes[0]),
          fields: reg.querySelector('.mcp-build-fields').textContent.includes(REG.args[6]) };
        click(reg.querySelector('.mcp-build-send'));
        await settle();
        const after = { said: text(reg.querySelector('.mcp-build-sent')), send: text(reg.querySelector('.mcp-build-send')),
          card: text(host.querySelector('.mcp-build-sent-at')) };
        click(reg.querySelector('.mcp-build-withdraw'));
        await settle();
        out({ before, after, withdrawn: text(reg.querySelector('.mcp-build-sent')),
              cardAfter: host.querySelector('.mcp-build-sent-at').style.display, writes: writes() });
    """)
    b = o["before"]
    assert b["lead"] == ("Only an admin registers a server. Send it to them: they read its code, "
                         "and register exactly that code.")
    assert (b["send"], b["withdrawShown"], b["fold"]) == ("Send it to an admin", False,
                                                         "Or copy the fields yourself")
    assert b["fields"] is True, "the fields as text are still there (Law 1), folded"
    assert o["after"]["said"] == f"Sent. An admin sees its code in {WHERE}, and registers it from there."
    assert o["after"]["send"] == "Send it again"
    assert o["after"]["card"].startswith("Sent to an admin on ")
    assert o["withdrawn"] == "Withdrawn. No admin sees it now."
    assert o["cardAfter"] == "none"
    # The send is the server's name in the path and nothing else.
    assert o["writes"] == [["POST", "/api/mcp/scaffold/weather/send", {}],
                           ["DELETE", "/api/mcp/builds-sent/s2", None]]


def test_a_send_whose_code_changed_since_says_send_it_again(box):
    o = _case(box, "const SENT = { id: 's1', at: 1790000000, as_sent: false };\n" + _PERSON + """
        out({ said: text(reg.querySelector('.mcp-build-sent')), send: text(reg.querySelector('.mcp-build-send')),
              withdraw: reg.querySelector('.mcp-build-withdraw').style.display });
    """)
    assert "it has changed since — they would see the code you sent, not this. Send it again." in o["said"]
    assert o["send"] == "Send it again" and o["withdraw"] == ""


def test_an_admin_reads_every_file_as_text_and_registers_exactly_that(box):
    o = _case(box, """
        server.answer = (url, method) => {
          if (url === '/api/mcp/builds-sent') return [200, { sent: [ENTRY] }];
          if (url === '/api/mcp/builds-sent/s1') return [200, DETAIL];
          return [404, {}];
        };
        const handed = [];
        const drawn = await B.mountBuildsSent(host, { onRegister: (r) => handed.push(r) });
        const card = host.querySelector('.mcp-sent');
        const listed = { count: drawn.count, title: text(host.querySelector('h3')),
          meta: text(card.querySelector('.mcp-sent-meta')), runs: text(card.querySelector('.mcp-sent-runs')),
          all: text(card) };
        click(card.querySelector('.mcp-sent-read'));
        await settle();
        const review = card.querySelector('.mcp-sent-review');
        out({ listed, now: text(review.querySelector('.mcp-sent-now')),
              pins: text(review.querySelector('.mcp-sent-pins')),
              code: review.querySelector('.mcp-sent-code').textContent,
              unreadable: review.querySelectorAll('.mcp-sent-unreadable').map(text),
              handedBefore: handed.length, made: [...tags(host, 'img'), ...tags(host, 'script'), ...tags(host, 'b')].length,
              registered: (click(review.querySelector('.mcp-sent-register')), handed), writes: writes() });
    """)
    listed = o["listed"]
    assert listed["count"] == 1 and listed["title"] == "Sent for registration (1)"
    assert listed["meta"].startswith("from ann · ")
    assert "registered before, with other code" in listed["meta"]
    # Listed with the fields Register fills in, fingerprint and all, as the
    # Add MCP Server form previews them.
    assert listed["runs"] == f"Pantheon will run: {REG['command']} {' '.join(REG['args'])}"
    assert listed["runs"].endswith(f"--sha256 {PIN}")
    assert "Offers: get_forecast" in listed["all"]
    assert "3 files: server.py, __pycache__/x.pyc, lib.py" in listed["all"]
    assert o["now"] == "Still as sent: this is the code in their workstation now."
    assert o["pins"].startswith(f"Register pins exactly the code below (fingerprint {PIN[:12]}…)")
    assert o["code"] == SOURCE, "the code is shown whole, as text"
    assert o["unreadable"] == [
        "__pycache__/x.pyc is compiled code (30 bytes) and cannot be read here. It is pinned with the rest "
        "and can run as part of this server — ask ann why it is there.",
        "lib.py is a link to /etc/hostname. Where it leads cannot be read here, and can run as part of "
        "this server."]
    assert o["made"] == 0, "nothing a sender wrote became an element"
    assert o["handedBefore"] == 0, "reading registers nothing"
    assert o["registered"] == [REG], "Register hands on the registration exactly as served"
    assert o["writes"] == []


def test_a_build_changed_since_it_was_sent_offers_no_register(box):
    o = _case(box, """
        const changed = Object.assign({}, DETAIL, { now: 'changed' });
        server.answer = (url) => url === '/api/mcp/builds-sent' ? [200, { sent: [ENTRY] }]
          : url === '/api/mcp/builds-sent/s1' ? [200, changed] : [404, {}];
        await B.mountBuildsSent(host, { onRegister: () => {} });
        click(host.querySelector('.mcp-sent-read'));
        await settle();
        out({ now: text(host.querySelector('.mcp-sent-now')), register: !!host.querySelector('.mcp-sent-register') });
    """)
    assert o["now"].startswith("Changed since it was sent: the code shown here is no longer what is in their "
                               "workstation, so registering it would run nothing.")
    assert o["register"] is False


def test_dismiss_takes_it_off_and_nothing_waiting_draws_nothing(box):
    o = _case(box, """
        let waiting = [ENTRY];
        server.answer = (url, method) => {
          if (url === '/api/mcp/builds-sent') return [200, { sent: waiting }];
          if (url === '/api/mcp/builds-sent/s1' && method === 'DELETE') { waiting = []; return [200, { removed: true }]; }
          return [404, {}];
        };
        await B.mountBuildsSent(host, { onRegister: () => {} });
        click(host.querySelector('.mcp-sent-dismiss'));
        await settle();
        let reviewed = 0;
        const note = B.sentNotice([ENTRY, Object.assign({}, ENTRY, { id: 's2', server: 'tides', owner: 'bob' })],
                                  () => { reviewed += 1; });
        click(note.querySelector('.intg-sent-review'));
        out({ empty: host.childNodes.length, writes: writes(), none: B.sentNotice([], () => {}),
              note: text(note.querySelector('span')), reviewed });
    """)
    assert o["empty"] == 0 and o["writes"] == [["DELETE", "/api/mcp/builds-sent/s1", None]]
    assert o["none"] is None
    assert o["note"] == "2 MCP servers were sent for registration: weather (from ann), tides (from bob)."
    assert o["reviewed"] == 1


def test_register_fills_the_admins_add_form_pin_included_and_saves_through_the_admin_route(box):
    """`settings.js`'s own `showMcpForm`, as an admin: the list is in the Add
    MCP Server form; *Register this code* is `registerBuilt` — the same fill as
    an admin's own build — and Save is `POST /api/mcp/servers`."""
    o = _case(box, """
        window._isAdmin = true;
        server.answer = (url, method) => {
          if (url === '/api/mcp/builds-sent') return [200, { sent: [ENTRY] }];
          if (url === '/api/mcp/builds-sent/s1') return [200, DETAIL];
          if (url === '/api/mcp/servers' && method === 'GET') return [200, []];
          if (url === '/api/mcp/servers' && method === 'POST') return [200, { id: 'new1', connected: true,
            tool_count: 1 }];
          if (url === '/api/mcp/scaffold') return [200, { servers: [], workstation: { available: false,
            why: 'The workstation is switched off.' } }];
          return [404, {}];
        };
        await showMcpForm('new');
        await settle();
        const mount = el('uf-mcp-sent-mount');
        const listed = text(mount.querySelector('h3'));
        click(mount.querySelector('.mcp-sent-read'));
        await settle();
        click(mount.querySelector('.mcp-sent-register'));
        await settle();
        const filled = { name: el('uf-mcp-name').value, cmd: el('uf-mcp-cmd').value,
          args: rowsOf(el('uf-mcp-args-mount')), preview: text(el('uf-mcp-preview')),
          note: text(el('uf-mcp-prefill-note')) };
        click(el('uf-mcp-save'));
        await settle();
        out({ listed, filled, writes: writes() });
    """)
    assert o["listed"] == "Sent for registration (1)"
    f = o["filled"]
    assert (f["name"], f["cmd"]) == ("weather", REG["command"])
    assert f["args"] == [[a] for a in REG["args"]] and REG["args"][-2:] == ["--sha256", PIN]
    assert f["preview"].endswith(f"--sha256 {PIN}")
    assert "each call runs in ann's workstation account" in f["note"]
    (method, url, body), = o["writes"]
    assert (method, url) == ("POST", "/api/mcp/servers")
    assert json.loads(body["args"]) == REG["args"] and body["command"] == REG["command"]


def test_only_an_admin_is_shown_the_list(box):
    o = _case(box, """
        window._isAdmin = false;
        server.answer = (url) => url === '/api/mcp/scaffold' ? [200, { servers: [],
          workstation: { available: true, why: null } }] : [403, { detail: 'Admin only' }];
        await showMcpForm('new');
        await settle();
        out({ asked: server.calls.some((c) => c.url.startsWith('/api/mcp/builds-sent')),
              drawn: el('uf-mcp-sent-mount').childNodes.length });
    """)
    assert o == {"asked": False, "drawn": 0}


def test_register_on_one_registered_before_is_that_rows_edit(box):
    """Registered before with other code: *Register this code* re-registers
    that row (its Edit, the admin route's `PUT`), not a second row."""
    row = {"id": "srv1", "name": "weather", "transport": "stdio", "command": REG["command"],
           "args": REG["args"][:6] + ["a" * 64], "env": {}, "url": None, "is_enabled": True,
           "status": "connected", "tool_count": 1, "enabled_tool_count": 1, "needs_oauth": False,
           "error": None}
    o = _case(box, f"""
        window._isAdmin = true;
        const ROW = {json.dumps(row)};
        server.answer = (url, method) => {{
          if (url === '/api/mcp/builds-sent') return [200, {{ sent: [ENTRY] }}];
          if (url === '/api/mcp/builds-sent/s1') return [200, DETAIL];
          if (url === '/api/mcp/servers' && method === 'GET') return [200, [ROW]];
          if (url === '/api/mcp/servers/srv1' && method === 'PUT') return [200, {{ id: 'srv1', connected: true,
            tool_count: 1, is_enabled: true }}];
          if (url === '/api/mcp/scaffold') return [200, {{ servers: [], workstation: {{ available: false, why: 'off' }} }}];
          return [200, []];
        }};
        await showMcpForm('new');
        await settle();
        click(el('uf-mcp-sent-mount').querySelector('.mcp-sent-read'));
        await settle();
        click(el('uf-mcp-sent-mount').querySelector('.mcp-sent-register'));
        await settle();
        const heading = text(formEl.querySelector('h2'));
        click(el('uf-mcp-save'));
        await settle();
        out({{ heading, writes: writes() }});
    """)
    assert o["heading"] == "Edit weather"
    (method, url, body), = o["writes"]
    assert (method, url) == ("PUT", "/api/mcp/servers/srv1")
    assert json.loads(body["args"]) == REG["args"]
