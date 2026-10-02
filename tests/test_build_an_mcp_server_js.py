# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-22` — *Build an MCP server*, driven in the browser module that draws it.

The real `static/js/settings/mcpBuild.js`, with the real `argsForm.js` it builds
*Try*'s form from and the real `mcpFields.js` it reads refusals with, over the
DOM shim with a fake `fetch` scripted per case — whose answers are C-M's own
shapes as `routes/mcp/mcp_routes.py` sends them (the Python file drives the
real routes; this one drives what the browser does with their answers).

What a person can see is what is asserted: the door greyed with the
workstation's own sentence; Build → "It started and offers: get_forecast";
*Try* with `text: "Oslo"` posting exactly that and showing the answer as text;
a broken server's traceback shown as text; *Register* handing an admin the
registration and a non-admin the fields to send. Hostile names, descriptions
and answers stay text — no element is ever made from them.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _run
from tests.helpers.mcp_build_sandbox import build

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

OFF = "The workstation is switched off. An admin turns it on in Settings → Workstation."
# The registration the scaffold's read answers, from the real function
# (`integrate-e`: it was a literal, and kept saying "Settings → Integrations"
# and no fingerprint after both changed).
PIN = "0123456789abcdef" * 4
REG = __import__("src.workstation_mcp", fromlist=["ws_registration"]).ws_registration("ann", "weather", PIN)
# As `workstation_mcp._tool_offer` sends it: the server's own read/write verdict included.
OFFER = {"name": "get_forecast", "description": "Forecast for a place.",
         "input_schema": {"type": "object", "properties": {"text": {"type": "string",
                          "description": "Where."}}, "required": ["text"]},
         "annotations": None, "is_readonly": True, "readonly_source": "heuristic"}

_PREAMBLE = (
    "import { document, server, settle, click, type, tags, text } from './shim.js';\n"
    "const B = await import('./settings/mcpBuild.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const host = document.createElement('div'); document.body.appendChild(host);\n"
    f"const REG = {__import__('json').dumps(REG)};\n"
    f"const OFFER = {__import__('json').dumps(OFFER)};\n"
    f"const OFF = {__import__('json').dumps(OFF)};\n"
    "const posts = () => server.calls.filter((c) => c.method !== 'GET').map((c) => [c.method, c.url, c.body]);\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build(tmp_path_factory.mktemp("mcpbuild"))


def _case(box, script):
    return _run(box, _PREAMBLE, script + "\nprocess.exit(0);\n")


def test_the_door_is_greyed_with_the_workstations_own_sentence(box):
    o = _case(box, """
        server.answer = () => [200, { servers: [], workstation: { available: false, why: OFF } }];
        let opened = 0;
        const state = await B.mountMcpBuildDoor(host, { onOpen: () => { opened += 1; } });
        const btn = host.querySelector('[data-mcp-build-open]');
        click(btn);
        const why = host.querySelector('.mcp-build-door-why');
        out({ state, disabled: btn.disabled, aria: btn.getAttribute('aria-disabled'),
              describedBy: btn.getAttribute('aria-describedby') === why.id, why: text(why),
              shown: why.style.display, opened, title: btn.title, look: [btn.style.opacity, btn.style.cursor] });
    """)
    assert o["state"] == {"available": False, "why": OFF}
    assert o["disabled"] is True and o["aria"] == "true" and o["describedBy"] is True
    assert o["why"] == OFF and o["shown"] == "block" and o["title"] == OFF
    assert o["opened"] == 0
    assert o["look"] == ["0.45", "not-allowed"]  # greyed where it can be seen, not only announced


def test_the_door_opens_the_panel_when_the_workstation_is_yours(box):
    o = _case(box, """
        server.answer = () => [200, { servers: [], workstation: { available: true, why: null } }];
        let opened = 0;
        await B.mountMcpBuildDoor(host, { onOpen: () => { opened += 1; } });
        const btn = host.querySelector('[data-mcp-build-open]');
        click(btn);
        out({ disabled: btn.disabled, opened, why: host.querySelector('.mcp-build-door-why').style.display,
              asked: server.calls.map((c) => [c.method, c.url]) });
    """)
    assert o == {"disabled": False, "opened": 1, "why": "none",
                 "asked": [["GET", "/api/mcp/scaffold"]]}


def test_build_check_and_try_without_a_terminal(box):
    """The row's Verify, in the module: weather / get_forecast, "It started
    and offers: get_forecast", Try with text "Oslo", the placeholder answer."""
    o = _case(box, """
        const made = { servers: [] };
        server.answer = (url, method, body) => {
          if (url === '/api/mcp/scaffold' && method === 'GET') {
            return [200, { servers: made.servers, workstation: { available: true, why: null } }];
          }
          if (url === '/api/mcp/scaffold' && method === 'POST') {
            made.servers = [{ name: 'weather', tools: ['get_forecast'], modified: 1, checked: 'works' }];
            return [200, { name: 'weather', tools: ['get_forecast'], description: '',
              check: { started: true, tools: ['get_forecast'], error: null, offers: [OFFER], stderr: '' },
              registration: REG, agent_refusal: 'manage_mcp: refused' }];
          }
          if (url === '/api/mcp/scaffold/weather/try') {
            return [200, { ok: true, stdout: "get_forecast has not been written yet. It was called with text='Oslo'",
              stderr: '', exit_code: 0, duration_ms: 168, timed_out: false, error: null, printed: '' }];
          }
          return [404, { detail: 'Not Found' }];
        };
        const panel = await B.mountMcpBuild(host, { isAdmin: false });
        type(host.querySelector('.mcp-build-name'), 'weather');
        type(host.querySelector('.mcp-build-tool'), 'get_forecast');
        click(host.querySelector('.mcp-build-make'));
        await settle();
        const said = text(host.querySelector('.mcp-build-new-msg'));
        const card = host.querySelector('[data-mcp-build-server="weather"]');
        click(card.querySelector('.mcp-build-try'));
        const input = card.querySelector('.wf-arg-input');
        type(input, 'Oslo');
        click(card.querySelector('[data-mcp-try-run="get_forecast"]'));
        await settle();
        const result = card.querySelector('.mcp-try-result');
        out({ said, check: text(card.querySelector('.mcp-build-check')), posts: posts(),
              headline: text(result.querySelector('.mcp-try-headline')),
              meta: text(result.querySelector('.mcp-try-meta')),
              sections: result.querySelectorAll('.mcp-try-section').map((s) => [
                s.getAttribute('data-mcp-try-section'), s.querySelector('pre').textContent]),
              argLabel: text(card.querySelector('.wf-arg-label')),
              badge: text(card.querySelector('.wf-args-writes')) });
    """)
    assert o["said"] == "It started and offers: get_forecast"
    assert o["check"] == "It started and offers: get_forecast"
    assert o["posts"] == [
        ["POST", "/api/mcp/scaffold", {"name": "weather", "tools": ["get_forecast"], "description": ""}],
        ["POST", "/api/mcp/scaffold/weather/try", {"tool": "get_forecast", "arguments": {"text": "Oslo"}}],
    ]
    assert o["argLabel"] == "text needed · text"
    assert o["badge"] == "Read-only (guessed from the name)"  # the verdict the row will show
    assert o["headline"] == "It answered in 168 ms."
    assert o["meta"] == "exit code 0 · 168 ms · finished in time"
    assert o["sections"] == [["What it answered",
                              "get_forecast has not been written yet. It was called with text='Oslo'"]]


def test_nothing_is_refused_before_the_server_sees_it(box):
    """`D-2026-09-27-02`: no client-side schema refusal. A required box left
    empty and a number that is not one go to the server as they are; what it
    says back is the answer."""
    o = _case(box, """
        server.answer = () => [200, { ok: false, stdout: '', stderr: 'text is required',
          exit_code: 1, duration_ms: 3, timed_out: false, error: null }];
        const tool = { name: 'get_forecast', input_schema: { type: 'object', required: ['text', 'days'],
          properties: { text: { type: 'string' }, days: { type: 'integer' } } } };
        const t = B.mountToolTry(host, { tool, call: async (args) => {
          server.calls.push({ args }); return server.answer()[1]; } });
        type(host.querySelectorAll('.wf-arg-input')[1], 'three');
        await t.run();
        const result = host.querySelector('.mcp-try-result');
        out({ sent: server.calls.map((c) => c.args), headline: text(result.querySelector('.mcp-try-headline')),
              tone: result.querySelector('.mcp-try-headline').getAttribute('data-tone'),
              wrong: result.querySelector('[data-mcp-try-section="What it said went wrong"]').querySelector('pre').textContent });
    """)
    assert o["sent"] == [{"days": "three"}]
    assert o["headline"] == "It answered that it failed." and o["tone"] == "bad"
    assert o["wrong"] == "text is required"


def test_a_broken_server_shows_what_it_printed_as_text(box):
    o = _case(box, """
        server.answer = (url, method) => {
          if (method === 'GET') return [200, { servers: [{ name: 'weather', tools: [], modified: 1, checked: 'changed' }],
            workstation: { available: true, why: null } }];
          return [200, { started: false, tools: [], error: 'It stopped before it answered.', offers: [],
            stderr: 'Traceback (most recent call last):\\n  File "server.py", line 3\\nSyntaxError: <b>bad</b> <img src=x onerror=alert(1)>' }];
        };
        await B.mountMcpBuild(host, { isAdmin: true });
        const card = host.querySelector('[data-mcp-build-server="weather"]');
        const before = text(card.querySelector('.mcp-build-checked'));
        click(card.querySelector('.mcp-build-check-run'));
        await settle();
        const printed = card.querySelector('.mcp-build-printed');
        out({ before, check: text(card.querySelector('.mcp-build-check')),
              tone: card.querySelector('.mcp-build-check').getAttribute('data-tone'),
              printed: printed.textContent, shown: printed.style.display,
              after: text(card.querySelector('.mcp-build-checked')),
              imgs: tags(host, 'img').length, bolds: tags(host, 'b').length, tries: card.querySelectorAll('.mcp-build-try').length });
    """)
    assert o["before"] == "Edited since it was last checked."
    assert o["check"] == "It did not start: It stopped before it answered."
    assert o["tone"] == "bad" and o["shown"] == "block"
    assert o["printed"].endswith("SyntaxError: <b>bad</b> <img src=x onerror=alert(1)>")
    assert o["after"] == "It did not start when it was last checked."
    assert o["imgs"] == 0 and o["bolds"] == 0 and o["tries"] == 0


def test_register_hands_an_admin_the_registration_and_a_non_admin_the_fields(box):
    o = _case(box, """
        server.answer = (url, method) => {
          if (url === '/api/mcp/scaffold') return [200, { servers: [{ name: 'weather', tools: ['get_forecast'],
            modified: 1, checked: 'works' }], workstation: { available: true, why: null } }];
          if (url === '/api/mcp/scaffold/weather') return [200, { name: 'weather', source: 'x', registration: REG,
            agent_refusal: 'manage_mcp: refused unsafe server registration: no' }];
          return [404, {}];
        };
        const handed = [];
        await B.mountMcpBuild(host, { isAdmin: true, onRegister: (reg) => handed.push(reg) });
        click(host.querySelector('.mcp-build-register'));
        await settle();
        const adminSaw = text(host.querySelector('.mcp-build-registration'));
        const other = document.createElement('div');
        await B.mountMcpBuild(other, { isAdmin: false, onRegister: (reg) => handed.push(['wrong', reg]) });
        click(other.querySelector('.mcp-build-register'));
        await settle();
        out({ handed, adminSaw, lead: text(other.querySelector('.mcp-build-admin-only')),
              fields: other.querySelector('.mcp-build-fields').textContent,
              note: text(other.querySelector('.mcp-build-runs-as')),
              writes: server.calls.filter((c) => c.method !== 'GET').length });
    """)
    assert o["handed"] == [REG]
    assert o["adminSaw"].startswith("Once it is registered, every assistant")
    # `B1130` moved this: a non-admin sends the build to the admins
    # (`test_an_admin_registers_a_build_someone_sent_js.py`); the fields stay,
    # folded under "Or copy the fields yourself".
    assert o["lead"] == ("Only an admin registers a server. Send it to them: they read its code, "
                         "and register exactly that code.")
    assert o["fields"] == (f"Name: weather\nTransport: stdio\nCommand: {REG['command']}\n"
                           f"Arguments (one box each):\n  {REG['args'][0]}\n  --owner\n"
                           f"  ann\n  --server\n  weather\n  --sha256\n  {PIN}\n"
                           "Environment: leave empty")
    assert "runs in your workstation account" in o["note"]
    assert o["writes"] == 0  # nothing here registers anything


def test_the_code_is_edited_saved_and_checked_again(box):
    o = _case(box, """
        server.answer = (url, method, body) => {
          if (url === '/api/mcp/scaffold') return [200, { servers: [{ name: 'weather', tools: [], modified: 1,
            checked: 'never' }], workstation: { available: true, why: null } }];
          if (url === '/api/mcp/scaffold/weather' && method === 'GET') return [200, { name: 'weather',
            source: '# server.py\\n</textarea><img src=x>', registration: REG, agent_refusal: '' }];
          if (url === '/api/mcp/scaffold/weather' && method === 'PUT') return [200, { saved: true }];
          if (url.endsWith('/check')) return [200, { started: true, tools: ['get_forecast'], error: null,
            offers: [OFFER], stderr: '' }];
          return [404, {}];
        };
        await B.mountMcpBuild(host, {});
        const card = host.querySelector('[data-mcp-build-server="weather"]');
        click(card.querySelector('.mcp-build-edit'));
        await settle();
        const area = card.querySelector('.mcp-build-code');
        const opened = area.value;
        area.value = opened + '\\n# mine';
        click(card.querySelector('.mcp-build-save'));
        await settle();
        out({ opened, posts: posts(), check: text(card.querySelector('.mcp-build-check')),
              msg: text(card.querySelector('.mcp-build-save-msg')), imgs: tags(host, 'img').length });
    """)
    assert o["opened"] == "# server.py\n</textarea><img src=x>"
    assert o["posts"] == [
        ["PUT", "/api/mcp/scaffold/weather", {"source": "# server.py\n</textarea><img src=x>\n# mine"}],
        ["POST", "/api/mcp/scaffold/weather/check", {}],
    ]
    assert o["check"] == "It started and offers: get_forecast" and o["msg"] == "Saved."
    assert o["imgs"] == 0


def test_a_refusal_is_the_servers_own_sentence(box):
    o = _case(box, """
        server.answer = (url, method) => method === 'GET'
          ? [200, { servers: [], workstation: { available: true, why: null } }]
          : [400, { detail: "'x\\"; import os#' does not work as a tool name. Use a lowercase word, digits and single underscores, starting with a letter — `get_forecast`, `send_alert`, `search2`." }];
        await B.mountMcpBuild(host, {});
        type(host.querySelector('.mcp-build-name'), 'weather');
        type(host.querySelector('.mcp-build-tool'), 'x"; import os#');
        click(host.querySelector('.mcp-build-make'));
        await settle();
        out({ said: text(host.querySelector('.mcp-build-new-msg')), list: text(host.querySelector('.mcp-build-list')) });
    """)
    assert o["said"].startswith("'x\"; import os#' does not work as a tool name.")
    assert o["list"] == "None yet."


def test_a_workstation_that_is_not_yours_disables_building_and_says_why(box):
    o = _case(box, """
        server.answer = () => [200, { servers: [], workstation: { available: false, why: OFF } }];
        await B.mountMcpBuild(host, {});
        out({ why: text(host.querySelector('.mcp-build-why')),
              disabled: ['.mcp-build-name', '.mcp-build-tool', '.mcp-build-make'].map((s) => host.querySelector(s).disabled) });
    """)
    assert o == {"why": OFF, "disabled": [True, True, True]}


def test_the_words_for_an_answer(box):
    o = _case(box, """
        out([
          B.describeTryResult({ ok: false, timed_out: true, exit_code: 1, duration_ms: 30000 }),
          B.describeTryResult({ ok: false, error: "'weather' is disconnected, so it has no tools to call" }),
          B.describeTryResult({ ok: true, stdout: '', duration_ms: 4, tool_is_disabled: true }),
          B.describeCheck({ started: true, tools: [] }),
        ]);
    """)
    timed, refused, quiet, empty = o
    assert timed["headline"] == "It did not answer in time, and was stopped."
    assert timed["meta"] == "exit code 1 · 30000 ms · ran out of time"
    assert refused["headline"] == "'weather' is disconnected, so it has no tools to call"
    assert quiet["sections"] == [["What it answered", "(nothing)"]]
    assert quiet["notes"][0].startswith("The assistant has this tool switched off.")
    assert empty == "It started, and offers no tools yet."


def test_saving_a_registered_servers_code_says_an_admin_registers_it_again(box):
    """`integrate-e`: a registration pins the code, so a person's save of a
    registered server's code is saved — and said to take its tools off the air
    until an admin registers it again (the route's `registered`)."""
    o = _case(box, """
        server.answer = (url, method) => {
          if (url === '/api/mcp/scaffold') return [200, { servers: [{ name: 'weather', tools: [], modified: 1,
            checked: 'works' }], workstation: { available: true, why: null } }];
          if (url === '/api/mcp/scaffold/weather' && method === 'GET') return [200, { name: 'weather',
            source: '# server.py', registration: REG, agent_refusal: '', registered: 'current' }];
          if (url === '/api/mcp/scaffold/weather' && method === 'PUT') return [200, { saved: true, registered: true }];
          if (url.endsWith('/check')) return [200, { started: true, tools: ['get_forecast'], error: null,
            offers: [OFFER], stderr: '' }];
          return [404, {}];
        };
        await B.mountMcpBuild(host, {});
        const card = host.querySelector('[data-mcp-build-server="weather"]');
        click(card.querySelector('.mcp-build-edit'));
        await settle();
        card.querySelector('.mcp-build-code').value = '# server.py\\n# changed';
        click(card.querySelector('.mcp-build-save'));
        await settle();
        out({ msg: text(card.querySelector('.mcp-build-save-msg')) });
    """)
    assert o["msg"] == ("Saved. It is registered, so its tools do not run this code until an admin registers it "
                        "again (Register).")
