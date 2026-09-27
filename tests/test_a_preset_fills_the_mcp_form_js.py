# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-45` — the preset catalogue, reachable at last, inside the MCP form.

**Re-measured before a line was written (`Law 3`).** Fifteen presets, fourteen
with a setup walkthrough, sat in `static/js/admin.js` at 1854-1920 (the row
said 1793-1859; the file had grown), counted by a balanced-bracket parse of the
array, not a regex. They fed `initMcpForm`, which returns on `adm-mcpCommand`,
and the admin tool list, `loadMcpServers`, which returns on `adm-mcpList` — no
template in this tree renders either id (`.pantheon/check-wiring.py` declares
all fourteen `adm-mcp*` ids absent by design). With `_GOOGLE_OAUTH_HELP`, the
list and the form, that is 426 lines no person could reach; the row's "420"
was within rounding. The live form — `settings.js`'s, rebuilt by `P8-46` —
asked for a Command and Arguments a person must already know.

**What is driven here.** The catalogue's one home
(`static/js/settings/mcpPresets.js`, which `admin.js` now imports rather than
copies — `Law 7`), and the picker filling the form's OWN controls: the real
`createMcpFieldEditor` editors from `static/js/settings/mcpFields.js`, not
imitations. The last cases run `settings.js`'s own `presetPicker` binding, cut
out by `tests/helpers/js_source.js_binding`, against a recording `fetch` —
which is the wiring, driven rather than grepped (`Law 20`).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_tool_effect_surfaces_js import _make_sandbox  # noqa: E402
from test_the_mcp_form_names_the_field_js import _SHIM  # noqa: E402
from tests.helpers.js_source import js_binding, js_code, js_function  # noqa: E402

PRESETS = ROOT / "static" / "js" / "settings" / "mcpPresets.js"
FIELDS = ROOT / "static" / "js" / "settings" / "mcpFields.js"
SETTINGS = ROOT / "static" / "js" / "settings.js"
ADMIN = ROOT / "static" / "js" / "admin.js"

_PREAMBLE = (
    "import { document, Node, click, type, describe } from './shim.js';\n"
    "const P = await import('./mcpPresets.js');\n"
    "const F = await import('./mcpFields.js');\n"
    # The form's own controls, the way `settings.js` hands them over.
    "function form(checkLaunch) {\n"
    "  const name = document.createElement('input');\n"
    "  const transport = document.createElement('select'); transport.value = 'stdio';\n"
    "  const command = document.createElement('input');\n"
    "  const events = [];\n"
    "  transport.addEventListener('change', () => events.push('transport:change'));\n"
    "  command.addEventListener('input', () => events.push('command:input'));\n"
    "  const args = F.createMcpFieldEditor({ kind: 'args' });\n"
    "  const env = F.createMcpFieldEditor({ kind: 'env' });\n"
    "  document.body.appendChild(args.element); document.body.appendChild(env.element);\n"
    "  const picker = P.createMcpPresetPicker({ fields: { name, transport, command, args, env },\n"
    "    ...(checkLaunch ? { checkLaunch } : {}) });\n"
    "  document.body.appendChild(picker.element);\n"
    "  return { name, transport, command, args, env, picker, events };\n"
    "}\n"
    "const index = (label) => P.MCP_PRESETS.findIndex((p) => p.name === label);\n"
    "const settle = () => new Promise((r) => setTimeout(r, 0));\n"
    # A refusal carries the DOM cell to focus; print everything else.
    "const plain = (o) => JSON.parse(JSON.stringify(o,\n"
    "  (k, v) => (v && typeof v === 'object' && v.tagName ? undefined : v)));\n"
    "const info = (f) => f.picker.element.querySelector('[data-mcp-preset-info]');\n"
    "const checks = (f) => Array.from(f.picker.element.querySelectorAll('[data-mcp-check]'))\n"
    "  .map((n) => [n.getAttribute('data-mcp-check'), n.getAttribute('data-mcp-check-tone'), n.textContent]);\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("mcppresets"), PRESETS, _SHIM,
                         {"mcpFields.js": FIELDS.read_text(encoding="utf-8")})


def run(sandbox: Path, script: str) -> dict:
    from test_tool_effect_surfaces_js import _run

    return _run(sandbox, _PREAMBLE, script + "\nprocess.exit(0);\n")


# ---------------------------------------------------------------------------
# The catalogue: what the row counted, and what it no longer ships
# ---------------------------------------------------------------------------


def test_the_catalogue_is_the_fifteen_the_row_counted(sandbox):
    out = run(sandbox, """
        console.log(JSON.stringify({
          names: P.MCP_PRESETS.map((p) => p.name),
          withHelp: P.MCP_PRESETS.filter((p) => p.help).length,
          commands: Array.from(new Set(P.MCP_PRESETS.map((p) => p.command))),
        }));
    """)
    assert len(out["names"]) == 15
    assert out["withHelp"] == 14, "fourteen walkthroughs; Memory has none"
    assert out["names"][0] == "Gmail" and out["names"][-1] == "Todoist"
    assert out["commands"] == ["npx"], "every preset starts npx — the check below depends on it"


def test_no_preset_ships_a_secret_that_looks_filled_in(sandbox):
    """The owner's rule: a value only the person has is left empty and marked.

    `postgresql://user:pass@localhost/db` shipped as a Postgres argument —
    credentials in a URL that read as a working value. No argument may carry
    credentials, every secret-named variable must ship empty, and whatever
    ships empty is marked as needed."""
    out = run(sandbox, """
        console.log(JSON.stringify(P.MCP_PRESETS.map((p) => ({
          name: p.name, args: p.args, env: p.env, needs: P.presetNeeds(p) }))));
    """)
    secretish = re.compile(r"TOKEN|SECRET|PASSWORD|API_KEY|CLIENT_ID|HEADERS|CREDENTIALS|USERNAME|ADDRESS")
    for preset in out:
        for arg in preset["args"]:
            assert not re.search(r"://[^/\s]*:[^@\s]*@", arg), (preset["name"], arg)
        for key, value in preset["env"].items():
            if secretish.search(key):
                assert value == "", f"{preset['name']}: {key} ships {value!r}"
            if value == "":
                assert key in preset["needs"]["env"], f"{preset['name']}: {key} is empty and unmarked"
    postgres = next(p for p in out if p["name"] == "Postgres")
    assert postgres["args"][2] == "" and postgres["needs"]["args"] == {
        "2": "postgresql://USER:PASSWORD@HOST:5432/DATABASE"}


def test_the_walkthroughs_name_this_forms_button_and_boxes(sandbox):
    """`Law 15`: a walkthrough that says "click Add Server" on a form whose
    button says Save is a walkthrough nobody can follow."""
    out = run(sandbox, "console.log(JSON.stringify(P.MCP_PRESETS.map((p) => [p.name, p.help || ''])));")
    for name, help_text in out:
        assert "Add Server" not in help_text, name
        assert "Args field" not in help_text, name
    github = dict(out)["GitHub"]
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in github


# ---------------------------------------------------------------------------
# Choosing one fills the form's own fields
# ---------------------------------------------------------------------------


def test_choosing_a_preset_fills_the_forms_own_fields(sandbox):
    out = run(sandbox, """
        const f = form();
        const select = f.picker.element.querySelector('[data-mcp-preset-select]');
        select.value = String(index('GitHub'));
        select.dispatchEvent({ type: 'change' });
        const envRow = f.env.element.querySelector('.mcp-field-row');
        const valueCell = envRow.querySelectorAll('input')[1];
        console.log(JSON.stringify({
          name: f.name.value, transport: f.transport.value, command: f.command.value,
          events: f.events, args: describe(f.args).rowValues, env: describe(f.env).rowValues,
          needs: envRow.getAttribute('data-mcp-needs'),
          required: valueCell.getAttribute('aria-required'), placeholder: valueCell.placeholder,
          active: f.picker.active() && f.picker.active().name,
          options: Array.from(select.querySelectorAll('option')).map((o) => o.textContent),
        }));
    """)
    assert out["name"] == "GitHub"
    assert out["transport"] == "stdio" and out["command"] == "npx"
    # The form's own listeners heard it: the transport toggle and the live
    # "Pantheon will run:" line both run off these two events.
    assert "transport:change" in out["events"] and "command:input" in out["events"]
    assert out["args"] == [["-y"], ["@modelcontextprotocol/server-github"]]
    assert out["env"] == [["GITHUB_PERSONAL_ACCESS_TOKEN", ""]]
    assert out["needs"] and out["required"] == "true"
    assert out["placeholder"] == "Yours to fill in — see Setup above"
    assert out["active"] == "GitHub"
    assert out["options"][0] == "Nothing — fill in the fields yourself"
    assert len(out["options"]) == 16


def test_the_setup_steps_are_shown_in_place_as_text(sandbox):
    out = run(sandbox, """
        const f = form();
        f.picker.choose(index('Notion'));
        const panel = info(f);
        const steps = panel.querySelector('.mcp-preset-steps');
        console.log(JSON.stringify({ shown: panel.style.display, text: panel.readable,
          steps: steps.textContent, html: steps._html }));
    """)
    assert out["shown"] == "block"
    assert "Filled in below. Nothing is added until you press Save." in out["text"]
    assert "You fill in: OPENAPI_MCP_HEADERS." in out["text"]
    assert out["steps"].startswith("1. Go to notion.so/my-integrations")
    assert '{"Authorization": "Bearer YOUR_SECRET"' in out["steps"]
    assert out["html"] == "", "a walkthrough holding braces and quotes was assigned as markup"
    assert "npx downloads this package from the npm registry" in out["text"], (
        "Law 16: what reaches out when it runs is said before it is saved")


def test_a_needed_value_left_empty_stops_the_post_on_its_own_field(sandbox):
    out = run(sandbox, """
        const f = form();
        f.picker.choose(index('GitHub'));
        const refused = F.collectMcpStdioFields(f.args, f.env);
        f.env.element.querySelectorAll('.mcp-field-row')[0].querySelectorAll('input')[1].value = 'github_pat_x';
        const accepted = F.collectMcpStdioFields(f.args, f.env);
        console.log(JSON.stringify(plain({ refused, accepted })));
    """)
    refused = out["refused"]
    assert refused["ok"] is False and refused["field"] == "env"
    assert refused["problem"]["title"] == "GITHUB_PERSONAL_ACCESS_TOKEN needs your value"
    assert out["accepted"]["ok"] is True
    assert json.loads(out["accepted"]["env"]) == {"GITHUB_PERSONAL_ACCESS_TOKEN": "github_pat_x"}


def test_the_postgres_url_is_an_empty_marked_argument_until_it_is_given(sandbox):
    out = run(sandbox, """
        const f = form();
        f.picker.choose(index('Postgres'));
        const rows = Array.from(f.args.element.querySelectorAll('.mcp-field-row'));
        const marked = rows.map((r) => r.getAttribute('data-mcp-needs'));
        const refused = F.collectMcpStdioFields(f.args, f.env);
        rows[2].querySelectorAll('input')[0].value = 'postgresql://me:pw@db.lan/app';
        const accepted = F.collectMcpStdioFields(f.args, f.env);
        console.log(JSON.stringify(plain({ marked, refused, accepted,
          placeholder: rows[2].querySelectorAll('input')[0].placeholder,
          preview: F.formatCommandLine(f.command.value, f.args.peek()) })));
    """)
    assert out["marked"] == [None, None, "postgresql://USER:PASSWORD@HOST:5432/DATABASE"]
    assert out["placeholder"] == "postgresql://USER:PASSWORD@HOST:5432/DATABASE"
    assert out["refused"]["ok"] is False and out["refused"]["field"] == "args"
    assert out["refused"]["problem"]["title"] == "Argument 3 needs your value"
    assert json.loads(out["accepted"]["args"]) == [
        "-y", "@modelcontextprotocol/server-postgres", "postgresql://me:pw@db.lan/app"]


def test_a_needed_row_the_person_removed_is_not_demanded(sandbox):
    """× is deliberate. The form refuses an empty box, not an absent one."""
    out = run(sandbox, """
        const f = form();
        f.picker.choose(index('Slack'));
        const rows = f.env.element.querySelectorAll('.mcp-field-row');
        rows[0].querySelectorAll('input')[1].value = 'xoxb-1';
        click(rows[1].querySelector('[data-mcp-drop]'));
        console.log(JSON.stringify(plain(F.collectMcpStdioFields(f.args, f.env))));
    """)
    assert out["ok"] is True
    assert json.loads(out["env"]) == {"SLACK_BOT_TOKEN": "xoxb-1"}


def test_a_needed_variable_is_still_needed_in_the_json_mode(sandbox):
    out = run(sandbox, """
        const f = form();
        f.picker.choose(index('Linear'));
        f.env.setMode('json');
        const refused = f.env.read();
        f.env.element.querySelector('[data-mcp-json]').value = '{"LINEAR_API_KEY": "lin_api_1"}';
        console.log(JSON.stringify(plain({ refused, accepted: f.env.read() })));
    """)
    assert out["refused"]["ok"] is False
    assert out["refused"]["problem"]["title"] == "LINEAR_API_KEY needs your value"
    assert out["accepted"] == {"ok": True, "value": {"LINEAR_API_KEY": "lin_api_1"}}


def test_a_plain_set_value_carries_no_marks(sandbox):
    """`Law 1` for the editor `P8-46` built: a value from anywhere but a
    preset is not suddenly demanded."""
    out = run(sandbox, """
        const f = form();
        f.picker.choose(index('GitHub'));
        f.env.setValue({ GITHUB_PERSONAL_ACCESS_TOKEN: '' });
        console.log(JSON.stringify(f.env.read()));
    """)
    assert out == {"ok": True, "value": {"GITHUB_PERSONAL_ACCESS_TOKEN": ""}}


# ---------------------------------------------------------------------------
# Nothing typed is taken away
# ---------------------------------------------------------------------------


def test_choosing_nothing_keeps_every_field_as_it_is(sandbox):
    out = run(sandbox, """
        const f = form();
        f.picker.choose(index('Gmail'));
        f.env.element.querySelectorAll('.mcp-field-row')[0].querySelectorAll('input')[1].value = 'id-1';
        f.picker.choose('');
        console.log(JSON.stringify({ env: describe(f.env).rowValues, command: f.command.value,
          name: f.name.value, shown: info(f).style.display, active: f.picker.active(),
          extras: f.picker.saveExtras({ GOOGLE_CLIENT_ID: 'id-1' }) }));
    """)
    assert out["env"] == [["GOOGLE_CLIENT_ID", "id-1"], ["GOOGLE_CLIENT_SECRET", ""]]
    assert out["command"] == "npx" and out["name"] == "Gmail"
    assert out["shown"] == "none" and out["active"] is None
    assert out["extras"] == {}, "a preset the person stepped away from still rode along on Save"


def test_switching_to_a_url_transport_stops_the_preset(sandbox):
    """Every preset is stdio. On SSE or HTTP the form sends a URL and nothing
    the preset filled, so its steps and its Google extras must not stay on."""
    out = run(sandbox, """
        const f = form();
        f.picker.choose(index('Gmail'));
        f.transport.value = 'sse';
        f.transport.dispatchEvent({ type: 'change' });
        console.log(JSON.stringify({ active: f.picker.active(), shown: info(f).style.display,
          select: f.picker.element.querySelector('[data-mcp-preset-select]').value,
          extras: f.picker.saveExtras({ GOOGLE_CLIENT_ID: 'x' }) }));
    """)
    assert out == {"active": None, "shown": "none", "select": "", "extras": {}}


def test_a_name_the_person_typed_is_kept(sandbox):
    out = run(sandbox, """
        const typed = form();
        typed.name.value = 'work-github';
        typed.picker.choose(index('GitHub'));
        typed.picker.choose(index('Slack'));
        const blank = form();
        blank.picker.choose(index('GitHub'));
        const first = blank.name.value;
        blank.picker.choose(index('Slack'));
        console.log(JSON.stringify({ typed: typed.name.value, first, second: blank.name.value }));
    """)
    assert out["typed"] == "work-github"
    assert out["first"] == "GitHub" and out["second"] == "Slack", (
        "a name the picker wrote follows the preset; one the person typed does not")


def test_the_email_provider_fills_both_hosts_and_nothing_else(sandbox):
    """No provider is chosen for the person — a host filled in before they
    said which is the placeholder-that-looks-filled-in — and choosing one
    keeps the address and password they already typed."""
    out = run(sandbox, """
        const f = form();
        f.picker.choose(index('Email (IMAP/SMTP)'));
        const before = describe(f.env).rowValues;
        const rows = f.env.element.querySelectorAll('.mcp-field-row');
        rows[0].querySelectorAll('input')[1].value = 'me@example.org';
        rows[1].querySelectorAll('input')[1].value = 'app-password';
        const provider = f.picker.element.querySelector('[data-mcp-preset-provider]');
        const firstOption = provider.querySelectorAll('option')[0].textContent;
        provider.value = '1';
        provider.dispatchEvent({ type: 'change' });
        const fastmail = describe(f.env).rowValues;
        provider.value = '7';
        provider.dispatchEvent({ type: 'change' });
        const custom = F.collectMcpStdioFields(f.args, f.env);
        console.log(JSON.stringify(plain({ before, firstOption, fastmail, custom })));
    """)
    assert out["before"] == [["MCP_EMAIL_ADDRESS", ""], ["MCP_EMAIL_PASSWORD", ""],
                             ["MCP_EMAIL_IMAP_HOST", ""], ["MCP_EMAIL_SMTP_HOST", ""]]
    assert out["firstOption"] == "Choose yours…"
    assert out["fastmail"] == [["MCP_EMAIL_ADDRESS", "me@example.org"], ["MCP_EMAIL_PASSWORD", "app-password"],
                               ["MCP_EMAIL_IMAP_HOST", "imap.fastmail.com"],
                               ["MCP_EMAIL_SMTP_HOST", "smtp.fastmail.com"]]
    assert out["custom"]["ok"] is False
    assert out["custom"]["problem"]["title"] == "MCP_EMAIL_IMAP_HOST needs your value"


def test_gmail_sends_what_add_server_writes_the_credentials_file_from(sandbox):
    """Ported from the unreachable admin form's save, the only one that ever
    sent these; without them the Gmail preset could not be authorized."""
    out = run(sandbox, """
        const f = form();
        f.picker.choose(index('Gmail'));
        const gmail = f.picker.saveExtras({ GOOGLE_CLIENT_ID: 'cid', GOOGLE_CLIENT_SECRET: 'csec' });
        f.picker.choose(index('GitHub'));
        const github = f.picker.saveExtras({ GITHUB_PERSONAL_ACCESS_TOKEN: 't' });
        console.log(JSON.stringify({ gmail, github, oauth: P.MCP_PRESETS[index('Gmail')].oauth }));
    """)
    assert json.loads(out["gmail"]["oauth_file"]) == {
        "dir": "gmail", "filename": "gcp-oauth.keys.json", "client_id": "cid", "client_secret": "csec"}
    assert json.loads(out["gmail"]["oauth_config"]) == out["oauth"]
    assert out["github"] == {}


# ---------------------------------------------------------------------------
# What this install makes of it — asked, before anything is typed
# ---------------------------------------------------------------------------


_REFUSED = ("command 'npx' is not allowed on the agent MCP path: interpreters, runtimes, "
            "package runners, and shells can execute arbitrary code. Register such a server "
            "via the admin route instead.")


def test_the_install_is_asked_the_moment_a_preset_is_chosen(sandbox):
    out = run(sandbox, f"""
        const asked = [];
        let answer;
        const f = form((registration) => {{ asked.push(registration);
          return new Promise((resolve) => {{ answer = resolve; }}); }});
        f.picker.choose(index('GitHub'));
        const pending = checks(f);
        answer({{ command: 'npx', launcher: {{ verdict: 'found' }},
                  assistant: {{ verdict: 'refused', reason: {json.dumps(_REFUSED)} }} }});
        await settle();
        console.log(JSON.stringify({{ asked, pending, done: checks(f) }}));
    """)
    assert out["asked"] == [{"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                             "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": ""}}]
    assert out["pending"] == [["pending", "note", "Checking this install…"]]
    assert out["done"] == [
        ["launcher", "ok", "npx is installed on this machine."],
        ["assistant", "note", "Only an administrator can add this, from this form. "
                              f"Asked to, the assistant refuses: “{_REFUSED}”"],
    ]


def test_a_missing_launcher_is_said_plainly(sandbox):
    out = run(sandbox, """
        const f = form(() => Promise.resolve({ launcher: { verdict: 'missing' },
          assistant: { verdict: 'accepted', reason: null } }));
        f.picker.choose(index('Memory'));
        await settle();
        console.log(JSON.stringify(checks(f)));
    """)
    assert out[0] == ["launcher", "bad",
                      "Pantheon can’t find npx on this machine, so this server won’t start here. Install it first."]
    assert out[1] == ["assistant", "ok", "The assistant could add this one for you too."]


def test_a_check_that_fails_says_so_instead_of_leaving_a_gap(sandbox):
    out = run(sandbox, """
        const f = form(() => Promise.reject(new Error('HTTP 404')));
        f.picker.choose(index('Memory'));
        await settle();
        const rejected = checks(f);
        const g = form(() => { throw new Error('offline'); });
        g.picker.choose(index('Memory'));
        await settle();
        console.log(JSON.stringify({ rejected, thrown: checks(g) }));
    """)
    assert out["rejected"] == [["error", "bad", "Couldn’t check this install (HTTP 404). You can still save."]]
    assert out["thrown"] == [["error", "bad", "Couldn’t check this install (offline). You can still save."]]


def test_a_verdict_never_outlives_the_command_it_was_about(sandbox):
    out = run(sandbox, """
        const f = form(() => Promise.resolve({ launcher: { verdict: 'found' },
          assistant: { verdict: 'refused', reason: 'x' } }));
        f.picker.choose(index('GitHub'));
        await settle();
        const before = checks(f).length;
        type(f.command, 'npx');
        const same = checks(f).length;
        type(f.command, 'uvx');
        console.log(JSON.stringify({ before, same, after: checks(f) }));
    """)
    assert out["before"] == 2 and out["same"] == 2
    assert out["after"] == [], "a verdict about npx stayed on screen under another command"


def test_a_slow_answer_for_an_earlier_choice_is_dropped(sandbox):
    out = run(sandbox, """
        const resolvers = [];
        const f = form(() => new Promise((resolve) => resolvers.push(resolve)));
        f.picker.choose(index('GitHub'));
        f.picker.choose(index('Slack'));
        resolvers[1]({ launcher: { verdict: 'found' }, assistant: { verdict: 'accepted' } });
        await settle();
        resolvers[0]({ launcher: { verdict: 'missing' }, assistant: { verdict: 'refused', reason: 'old' } });
        await settle();
        console.log(JSON.stringify(checks(f)));
    """)
    assert [c[1] for c in out] == ["ok", "ok"], out


def test_nothing_is_fetched_to_show_the_catalogue(sandbox):
    """`Law 16`: a preset must not reach out to be shown. The module never
    calls `fetch`; the only request is the install check the caller passes."""
    out = run(sandbox, """
        const calls = [];
        globalThis.fetch = async (...a) => { calls.push(a); return { ok: true, json: async () => ({}) }; };
        const f = form();
        for (let i = 0; i < P.MCP_PRESETS.length; i += 1) f.picker.choose(i);
        await settle();
        console.log(JSON.stringify({ calls: calls.length }));
    """)
    assert out["calls"] == 0


@pytest.mark.parametrize("payload,expect", [
    ({}, []),
    ({"launcher": {"verdict": "maybe"}, "assistant": {"verdict": "perhaps"}}, []),
    ({"command": "npx", "assistant": {"verdict": "refused"}},
     [["assistant", "note", "Only an administrator can add this, from this form. Asked to, the assistant refuses."]]),
])
def test_the_sentences_come_from_the_verdicts_and_nothing_else(sandbox, payload, expect):
    out = run(sandbox, f"""
        console.log(JSON.stringify(P.describeLaunchCheck({json.dumps(payload)})
          .map((l) => [l.key, l.tone, l.text])));
    """)
    assert out == expect


def test_the_route_python_serves_is_the_one_the_picker_reads(sandbox, monkeypatch):
    """Across the boundary: the check route's real answer, handed to the
    module, comes out quoting the rule's own sentence."""
    import asyncio

    from test_mcp_preset_launch_check import _endpoint, _FakeRequest

    monkeypatch.delenv("PANTHEON_MCP_ALLOWED_COMMANDS", raising=False)
    answer = asyncio.run(_endpoint("/api/mcp/check", "POST")(
        request=_FakeRequest({"command": "npx", "args": ["-y", "pkg"], "env": {}})))
    out = run(sandbox, f"""
        console.log(JSON.stringify(P.describeLaunchCheck({json.dumps(answer)})));
    """)
    said = {line["key"]: line["text"] for line in out}
    assert answer["assistant"]["reason"] in said["assistant"]
    assert said["launcher"] in ("npx is installed on this machine.",
                                "Pantheon can’t find npx on this machine, so this server won’t start here. Install it first.")


# ---------------------------------------------------------------------------
# One home, and the live form's own wiring
# ---------------------------------------------------------------------------


def test_admin_js_reads_the_catalogue_from_its_one_home():
    """`Law 7`. Absence anywhere in the file is the claim, so a file-wide
    check is the right one (`Law 20`'s one exception); the import is read
    from code with comments and strings blanked."""
    admin = ADMIN.read_text(encoding="utf-8")
    with pytest.raises(AssertionError):
        js_binding(admin, "MCP_PRESETS")
    # `js_code` blanks string bodies with offsets kept, so the statement is
    # found in code and its specifier read from the source at the same place.
    code = js_code(admin)
    found = re.search(r"\bimport\s*\{[^}]*\bMCP_PRESETS\b[^}]*\}\s*from\b", code)
    assert found, "admin.js does not import MCP_PRESETS"
    spec = admin[found.end():].split(";", 1)[0].strip()
    assert spec == "'./settings/mcpPresets.js'"


def _settings_picker_binding() -> str:
    source = SETTINGS.read_text(encoding="utf-8")
    body = js_function(source, "async function showMcpForm")
    return js_binding(body, "presetPicker")


def test_the_live_form_builds_the_picker_on_its_own_controls(sandbox):
    """`settings.js`'s own `presetPicker` binding, cut out and run: it hands
    the picker the form's name, transport and command inputs and its two field
    editors, and its install check posts to `/api/mcp/check`."""
    binding = _settings_picker_binding()
    out = run(sandbox, f"""
        const {{ createMcpPresetPicker }} = P;
        const {{ describeServerRefusal }} = F;
        const nodes = {{}};
        for (const id of ['uf-mcp-name', 'uf-mcp-transport', 'uf-mcp-cmd']) {{
          nodes[id] = document.createElement(id === 'uf-mcp-transport' ? 'select' : 'input');
        }}
        const el = (id) => nodes[id] || null;
        const argsField = F.createMcpFieldEditor({{ kind: 'args' }});
        const envField = F.createMcpFieldEditor({{ kind: 'env' }});
        const posted = [];
        globalThis.fetch = async (url, init) => {{
          posted.push([url, init.method, JSON.parse(init.body)]);
          return {{ ok: true, status: 200, json: async () => ({{
            launcher: {{ verdict: 'found' }}, assistant: {{ verdict: 'refused', reason: 'no' }} }}) }};
        }};
        {binding};
        presetPicker.choose(P.MCP_PRESETS.findIndex((p) => p.name === 'Brave Search'));
        await settle();
        console.log(JSON.stringify({{
          posted, name: nodes['uf-mcp-name'].value, cmd: nodes['uf-mcp-cmd'].value,
          transport: nodes['uf-mcp-transport'].value, env: describe(envField).rowValues,
          checks: Array.from(presetPicker.element.querySelectorAll('[data-mcp-check]')).map((n) => n.textContent),
        }}));
    """)
    assert out["posted"] == [["/api/mcp/check", "POST", {
        "command": "npx", "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env": {"BRAVE_API_KEY": ""}}]]
    assert out["name"] == "Brave Search" and out["cmd"] == "npx" and out["transport"] == "stdio"
    assert out["env"] == [["BRAVE_API_KEY", ""]]
    assert out["checks"][0] == "npx is installed on this machine."


def test_the_live_form_mounts_it_and_sends_its_extras_before_the_post():
    """What cannot be run in a shim that does not parse `innerHTML` — the
    mount in the card's markup and two lines of the save handler — asserted
    inside `showMcpForm` and nowhere else (`Law 20`, option 2)."""
    source = SETTINGS.read_text(encoding="utf-8")
    body = js_function(source, "async function showMcpForm")
    assert body.index('id="uf-mcp-preset-mount"') < body.index('id="uf-mcp-name"')
    assert "el('uf-mcp-preset-mount').replaceChildren(presetPicker.element)" in body
    save = body[body.index("el('uf-mcp-save').addEventListener('click'"):]
    append_env = save.index("fd.append('env', collected.env);")
    extras = save.index("presetPicker.saveExtras(JSON.parse(collected.env))")
    post = save.index("await fetch('/api/mcp/servers', { method: 'POST'")
    assert append_env < extras < post
    # A save the server accepted but could not start lands on the server's own
    # page, which says which of the two it is — never on a bare "Saved".
    accepted_branch = save[save.index("} else if (r.ok) {"):save.index("describeServerRefusal(r.status, data)")]
    assert "await showMcpForm(data.id);" in accepted_branch
    assert "'Saved'" not in accepted_branch
