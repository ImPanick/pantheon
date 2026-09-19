# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-46` and the read half of `P8-48` — the MCP server form's two JSON boxes.

**The row's premise, re-measured 2026-09-19, is half stale and half worse than
it says.** *"A parse failure is caught and silently discarded, posting empty
args and env"* was true until `1dc03f5` (2026-09-13, `test_a_server_you_could_
not_start_is_not_added.py`), which put a `return` in both catches on the server
and in both browser forms. What the headline asks for was never done: **the
inputs were still single-line JSON**, at `static/js/settings.js:5624-5625`,

    <input id="uf-mcp-args" placeholder='["-y", "@modelcontextprotocol/server-filesystem"]'>
    <input id="uf-mcp-env"  placeholder='{"KEY": "value"}'>

so a person with two arguments had to produce a JSON array by hand, in a
single-line box, with the whole placeholder wider than the box, and was told
*"Args must be valid JSON, e.g. [\"-y\", \"pkg\"]"* in a shared 11px span at
the bottom of the card when they got it wrong — the format's name repeated
back at somebody who had just failed to produce it, 140px from the box it was
about, with no indication of **where**.

**And the live form threw away the one message written to be read.**
`add_server` answers 400 with a `detail` saying which field and what shape
would have worked. `settings.js:5686` read `r.status` and rendered
`Failed (${r.status})` — *"Failed (400)"*. The **dead** admin form four
hundred lines away prints `data.detail || \`Failed (${res.status})\``
(`static/js/admin.js:2460`), so the panel nobody can reach explained itself and
the one everybody uses did not. That is `Law 13`: the same thing in two places,
and they disagreed.

**What this file drives.** Every rule now lives in `static/js/settings/
mcpFields.js` and is exercised through the module, not read out of it
(`Law 20`). The editor is built and typed into; JSON is pasted into it and the
mode switched; the refusal shaping is handed real response bodies.

`settings.js` builds its card with `formEl.innerHTML = ...`, and the shared DOM
shim stores markup as a string rather than parsing it, so no control inside
that card is reachable from a test — which is why `collectMcpStdioFields` is a
module function taking the two editors rather than eleven lines inside the
click handler. What is left at the call site is `fd.append` and
`textContent =`.

**`P8-48` is NOT closed here** and this file says why in
`test_the_payload_carries_the_schema_and_not_the_annotations`: `input_schema`
is on the wire and now rendered, `annotations` is not on the wire at all, and
nothing anywhere can write either.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_tool_effect_surfaces_js import _make_sandbox  # noqa: E402

MCP_FIELDS = ROOT / "static" / "js" / "settings" / "mcpFields.js"

# The module touches `document` and nothing else in the browser, so the shim is
# the shared DOM plus the three things a form field reaches for that a bare
# `Node` does not have: a parent element, a focus target, and an event object.
_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

Object.defineProperty(Node.prototype, 'parentElement', {
  get() { return this.parentNode && this.parentNode.tagName !== '#DOCUMENT' ? this.parentNode : null; },
  configurable: true,
});

/** A click the module's handlers can read, with the two methods they call. */
export function click(node) {
  node.dispatchEvent({ type: 'click', preventDefault() {}, stopPropagation() {} });
}

export function type(node, value) {
  node.value = value;
  node.dispatchEvent({ type: 'input' });
}

/** Everything a case wants to assert about one field, in one object. */
export function describe(field) {
  const box = field.element;
  const problem = box.querySelector('[data-mcp-problem]');
  const json = box.querySelector('[data-mcp-json]');
  const rows = Array.from(box.querySelectorAll('.mcp-field-row'));
  return {
    mode: field.mode(),
    rowCount: rows.length,
    rowValues: rows.map((r) => Array.from(r.querySelectorAll('input')).map((i) => i.value)),
    jsonText: json ? json.value : null,
    jsonVisible: json ? json.style.display !== 'none' : false,
    problemShown: problem ? problem.style.display === 'block' : false,
    problemText: problem ? problem.readable : '',
    problemInsideField: !!problem,
    toggleLabel: box.querySelector('[data-mcp-mode-toggle]').textContent,
    hint: box.readable,
  };
}
"""

_PREAMBLE = (
    "import { document, Node, click, type, describe } from './shim.js';\n"
    "const F = await import('./mcpFields.js');\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("mcpfields"), MCP_FIELDS, _SHIM, {})


def run(sandbox: Path, script: str) -> dict:
    entry = sandbox / "case.mjs"
    entry.write_text(_PREAMBLE + textwrap.dedent(script) + "\nprocess.exit(0);\n")
    proc = subprocess.run(
        ["node", str(entry)], cwd=sandbox, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])


def parse(sandbox: Path, raw: str, kind: str) -> dict:
    return run(sandbox, f"""
        const out = F.parseJsonField({json.dumps(raw)}, {json.dumps(kind)});
        console.log(JSON.stringify(out));
    """)


# ---------------------------------------------------------------------------
# What is wrong with it, not that something is
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,raw,expect_in_title,expect_in_detail",
    [
        # The two typos a person actually makes, from the endpoint test's own
        # parametrize list — which asserts only that the server says 400.
        ("args", "[-y, pkg]", "unquoted word", "-y"),
        ("args", "['-y']", "Single quotes", '"text"'),
        ("env", '{"API_KEY": "x"', "missing", "{"),
        ("args", '["-y",]', "comma", "closing bracket"),
        ("args", '[“-y”]', "Curly quotes", "word processor"),
        ("env", "API_KEY=sk-1", "Shell syntax", "colon"),
        ("args", '["-y', "never closed", "closing"),
        ("args", "-y, pkg", "start with [", "[…]"),
        # Valid JSON of a shape the route cannot use, caught before the post.
        ("args", '"-y"', "must be a list", "list of arguments"),
    ],
)
def test_the_field_says_what_is_wrong_with_the_text(
    sandbox, kind, raw, expect_in_title, expect_in_detail
):
    """Each of these was *"Args must be valid JSON, e.g. [\"-y\", \"pkg\"]"*.

    The reading is the module's own, not `JSON.parse`'s: V8 says
    `Unexpected token '-', "[-y, pkg]" is not valid JSON`, SpiderMonkey says
    `expected property name or '}' at line 1 column 2`, JavaScriptCore says
    neither. A message that changes with the browser cannot be shown to a
    person and cannot be asserted on.
    """
    out = parse(sandbox, raw, kind)
    assert out["ok"] is False
    problem = out["problem"]
    assert expect_in_title.lower() in problem["title"].lower(), problem
    assert expect_in_detail in problem["detail"], problem


def test_the_caret_points_at_the_character_that_stopped_it(sandbox):
    """*Which field* was the old ceiling. This is where in the field."""
    out = parse(sandbox, '["-y", \'pkg\']', "args")
    problem = out["problem"]
    caret = problem["caret"]
    excerpt = problem["excerpt"]
    assert caret.count("^") == 1
    assert excerpt[caret.index("^")] == "'", (excerpt, caret)
    assert problem["position"]["line"] == 1
    assert problem["position"]["column"] == 8


def test_a_long_paste_is_windowed_around_the_fault_and_still_lines_up(sandbox):
    """A 400-character config pasted into the box must not print 400 columns."""
    raw = '["' + "a" * 300 + "\", 'x']"
    out = parse(sandbox, raw, "args")
    problem = out["problem"]
    assert len(problem["excerpt"]) <= 50
    assert problem["excerpt"].startswith("…")
    assert problem["excerpt"][problem["caret"].index("^")] == "'"


def test_blank_is_not_a_failure(sandbox):
    """`Law 1`. Most servers take no args and no env; blank must stay legal."""
    for kind, empty in (("args", []), ("env", {})):
        for raw in ("", "   "):
            out = parse(sandbox, raw, kind)
            assert out == {"ok": True, "value": empty}, (kind, raw)


def test_a_valid_value_still_parses(sandbox):
    out = parse(sandbox, '["-y", "@modelcontextprotocol/server-filesystem"]', "args")
    assert out == {"ok": True, "value": ["-y", "@modelcontextprotocol/server-filesystem"]}
    out = parse(sandbox, '{"API_KEY": "sk-test"}', "env")
    assert out == {"ok": True, "value": {"API_KEY": "sk-test"}}


def test_an_apostrophe_inside_a_string_is_not_a_single_quoted_string(sandbox):
    """The typo rules scan outside the quotes, which is the only way this works.

    `["don't"]` is legal JSON. A rule that greps for `'` calls it a
    single-quoted string and refuses a value the server would have accepted —
    a validator that invents a failure is worse than one that misses one.
    """
    out = parse(sandbox, '["don\'t", "a, ]"]', "args")
    assert out == {"ok": True, "value": ["don't", "a, ]"]}


# ---------------------------------------------------------------------------
# Valid JSON of the wrong shape — including the part the server does not check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,raw,expect",
    [
        ("args", "5", "must be a list"),
        ("args", '{"a": 1}', "must be a list"),
        ("env", "5", "name/value pairs"),
        ("env", '["API_KEY"]', "name/value pairs"),
    ],
)
def test_the_container_shape_is_refused_before_the_round_trip(sandbox, kind, raw, expect):
    """`routes/mcp/mcp_routes.py:221-222` refuses these and stays the authority.

    This side exists to name the field without a round trip, and because the
    row editor makes the shape unreachable in the first place.
    """
    out = parse(sandbox, raw, kind)
    assert out["ok"] is False
    assert expect in out["problem"]["title"] or expect in out["problem"]["detail"]


@pytest.mark.parametrize(
    "kind,raw,expect",
    [
        ("args", '["-y", 5]', "Argument 2 is not text"),
        ("env", '{"PORT": 3000}', "PORT is not text"),
        ("env", '{"DEBUG": true}', "DEBUG is not text"),
    ],
)
def test_an_entry_of_the_wrong_type_is_refused_too(sandbox, kind, raw, expect):
    """**The server does not check this and it reaches a subprocess.**

    `_parsed_json_field` asserts the container (`list`, `dict`) and nothing
    inside it, so `{"PORT": 3000}` is stored, handed to
    `StdioServerParameters(env=...)` and on into the process environment as an
    int. Measured 2026-09-19 against `routes/mcp/mcp_routes.py:206-216`.
    """
    out = parse(sandbox, raw, kind)
    assert out["ok"] is False
    assert expect in out["problem"]["title"], out["problem"]


# ---------------------------------------------------------------------------
# The field itself — the half a validator does not deliver
# ---------------------------------------------------------------------------


def test_the_field_opens_as_boxes_and_not_as_json(sandbox):
    """The row's headline. A person with two arguments types two arguments."""
    out = run(sandbox, """
        const args = F.createMcpFieldEditor({ kind: 'args' });
        const env = F.createMcpFieldEditor({ kind: 'env' });
        console.log(JSON.stringify({
          args: describe(args), env: describe(env),
          argsRead: args.read(), envRead: env.read(),
        }));
    """)
    assert out["args"]["mode"] == "fields"
    assert out["args"]["jsonVisible"] is False
    assert out["args"]["rowCount"] == 1
    assert out["args"]["rowValues"] == [[""]]
    assert out["env"]["rowValues"] == [["", ""]]
    assert out["argsRead"] == {"ok": True, "value": []}
    assert out["envRead"] == {"ok": True, "value": {}}


def test_typing_two_arguments_produces_the_array_the_route_wants(sandbox):
    out = run(sandbox, """
        const f = F.createMcpFieldEditor({ kind: 'args' });
        const add = f.element.querySelector('[data-mcp-add]');
        type(f.element.querySelectorAll('input')[0], '-y');
        click(add);
        const rows = Array.from(f.element.querySelectorAll('input'));
        type(rows[1], '@modelcontextprotocol/server-filesystem');
        click(add);  // a blank row left behind must not become an empty argument
        console.log(JSON.stringify({ read: f.read(), rows: describe(f).rowCount }));
    """)
    assert out["rows"] == 3
    assert out["read"] == {
        "ok": True, "value": ["-y", "@modelcontextprotocol/server-filesystem"],
    }


def test_removing_a_row_leaves_the_field_usable(sandbox):
    """`×` on the last row must not leave a field with nothing to type in."""
    out = run(sandbox, """
        const f = F.createMcpFieldEditor({ kind: 'args' });
        type(f.element.querySelectorAll('input')[0], '-y');
        click(f.element.querySelector('[data-mcp-drop]'));
        console.log(JSON.stringify({ d: describe(f), read: f.read() }));
    """)
    assert out["d"]["rowCount"] == 1
    assert out["d"]["rowValues"] == [[""]]
    assert out["read"] == {"ok": True, "value": []}


def test_an_environment_value_with_no_name_is_named_rather_than_dropped(sandbox):
    """Silently dropping it is the defect class this row is filed under."""
    out = run(sandbox, """
        const f = F.createMcpFieldEditor({ kind: 'env' });
        const cells = f.element.querySelectorAll('input');
        type(cells[1], 'sk-secret');
        const read = f.read();
        f.showProblem(read.problem);
        console.log(JSON.stringify({
          ok: read.ok, title: read.problem.title, detail: read.problem.detail,
          d: describe(f),
        }));
    """)
    assert out["ok"] is False
    assert "no name" in out["title"]
    assert "×" in out["detail"]
    assert out["d"]["problemShown"] is True
    assert "sk-secret" in str(out["d"]["rowValues"]), "the value must survive the refusal"


def test_the_json_mode_is_the_same_field_and_carries_the_value_across(sandbox):
    """`Law 1` — the raw route is kept. `Law 14` — as a mode, not a second box."""
    out = run(sandbox, """
        const f = F.createMcpFieldEditor({ kind: 'args' });
        type(f.element.querySelectorAll('input')[0], '-y');
        click(f.element.querySelector('[data-mcp-mode-toggle]'));
        const inJson = describe(f);
        click(f.element.querySelector('[data-mcp-mode-toggle]'));
        console.log(JSON.stringify({ inJson, back: describe(f), read: f.read() }));
    """)
    assert out["inJson"]["mode"] == "json"
    assert out["inJson"]["jsonText"] == '["-y"]'
    assert out["inJson"]["jsonVisible"] is True
    assert "Back to argument boxes" in out["inJson"]["toggleLabel"]
    assert out["back"]["mode"] == "fields"
    assert out["back"]["rowValues"] == [["-y"]]
    assert out["read"] == {"ok": True, "value": ["-y"]}


def test_a_paste_that_will_not_parse_is_kept_on_screen_with_the_reason(sandbox):
    """**The half of this row a validator alone does not deliver.**

    A refusal that also clears the box makes the person retype something they
    cannot see any more, and the old form's single line had no way to show
    them where in it the fault was.
    """
    bad = "['-y', 'pkg']"
    out = run(sandbox, f"""
        const f = F.createMcpFieldEditor({{ kind: 'args' }});
        click(f.element.querySelector('[data-mcp-mode-toggle]'));
        type(f.element.querySelector('[data-mcp-json]'), {json.dumps(bad)});
        const switched = f.setMode('fields');
        console.log(JSON.stringify({{ switched, d: describe(f) }}));
    """)
    assert out["switched"] is False, "it must not silently drop back to empty boxes"
    assert out["d"]["mode"] == "json"
    assert out["d"]["jsonText"] == bad, "what they typed is still there"
    assert out["d"]["problemShown"] is True
    assert "Single quotes" in out["d"]["problemText"]
    assert "^" in out["d"]["problemText"], "the caret is drawn"


def test_the_problem_is_drawn_against_the_field_and_not_in_a_shared_footer(sandbox):
    """*Which field* is answered by where the sentence is, not by naming it."""
    out = run(sandbox, """
        const args = F.createMcpFieldEditor({ kind: 'args' });
        const env = F.createMcpFieldEditor({ kind: 'env' });
        click(env.element.querySelector('[data-mcp-mode-toggle]'));
        type(env.element.querySelector('[data-mcp-json]'), '{BROKEN}');
        const read = env.read();
        env.showProblem(read.problem);
        console.log(JSON.stringify({
          onEnv: describe(env).problemShown,
          onArgs: describe(args).problemShown,
          envSaysEnv: env.element.getAttribute('data-mcp-field'),
          marked: env.element.querySelector('[data-mcp-json]').getAttribute('aria-invalid'),
        }));
    """)
    assert out["onEnv"] is True
    assert out["onArgs"] is False, "the other field must not light up"
    assert out["envSaysEnv"] == "env"
    assert out["marked"] == "true"


def test_clearing_the_problem_leaves_the_value_alone(sandbox):
    out = run(sandbox, """
        const f = F.createMcpFieldEditor({ kind: 'args' });
        type(f.element.querySelectorAll('input')[0], '-y');
        f.showProblem({ title: 'x', detail: 'y' });
        f.clearProblem();
        console.log(JSON.stringify({ d: describe(f), read: f.read() }));
    """)
    assert out["d"]["problemShown"] is False
    assert out["read"] == {"ok": True, "value": ["-y"]}


def test_the_field_says_in_words_what_it_is_for(sandbox):
    """`Law 15`/`P8-00`. "Args" is a word from the config file, not from a person."""
    out = run(sandbox, """
        const f = F.createMcpFieldEditor({
          kind: 'args',
          hint: 'One box per argument — exactly what you would type after the command.',
        });
        console.log(JSON.stringify({ hint: describe(f).hint }));
    """)
    assert "One box per argument" in out["hint"]


# ---------------------------------------------------------------------------
# The decision the Save button makes
# ---------------------------------------------------------------------------


def test_the_form_posts_json_encoded_values_when_both_fields_read(sandbox):
    """What goes on the wire is what `Form(args=..., env=...)` expects."""
    out = run(sandbox, """
        const args = F.createMcpFieldEditor({ kind: 'args' });
        const env = F.createMcpFieldEditor({ kind: 'env' });
        type(args.element.querySelectorAll('input')[0], '-y');
        const cells = env.element.querySelectorAll('input');
        type(cells[0], 'API_KEY'); type(cells[1], 'sk-test');
        console.log(JSON.stringify(F.collectMcpStdioFields(args, env)));
    """)
    assert out == {"ok": True, "args": '["-y"]', "env": '{"API_KEY":"sk-test"}'}


def test_a_bad_field_stops_the_post_and_names_which_one(sandbox):
    out = run(sandbox, """
        const args = F.createMcpFieldEditor({ kind: 'args' });
        const env = F.createMcpFieldEditor({ kind: 'env' });
        click(env.element.querySelector('[data-mcp-mode-toggle]'));
        type(env.element.querySelector('[data-mcp-json]'), "{'A': 'b'}");
        console.log(JSON.stringify(F.collectMcpStdioFields(args, env)));
    """)
    assert out["ok"] is False
    assert out["field"] == "env"
    assert "Single quotes" in out["problem"]["title"]


# ---------------------------------------------------------------------------
# The server's own reason, which the live form was throwing away
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,body,field,contains",
    [
        (400, {"detail": 'args must be a JSON array, e.g. ["-y", "pkg"]'}, "args", "JSON array"),
        (400, {"detail": 'env must be valid JSON, e.g. {"API_KEY": "..."}'}, "env", "valid JSON"),
        (400, {"detail": "url is required for SSE transport"}, None, "url is required"),
        (409, {"detail": "A server named filesystem already exists"}, None, "already exists"),
    ],
)
def test_the_servers_reason_reaches_the_person(sandbox, status, body, field, contains):
    """`settings.js:5686` rendered every one of these as *"Failed (400)"*."""
    out = run(sandbox, f"""
        console.log(JSON.stringify(F.describeServerRefusal({status}, {json.dumps(body)})));
    """)
    assert out["field"] == field
    assert contains in out["text"]


def test_a_refusal_with_no_reason_still_says_something_a_person_can_act_on(sandbox):
    out = run(sandbox, """
        console.log(JSON.stringify({
          bare: F.describeServerRefusal(500, {}),
          forbidden: F.describeServerRefusal(403, {}),
          fastapi: F.describeServerRefusal(422, { detail: [{ msg: 'field required' }] }),
        }));
    """)
    assert "500" in out["bare"]["text"]
    assert "administrator" in out["forbidden"]["text"]
    assert "field required" in out["fastapi"]["text"]


def test_the_command_line_preview_is_the_command_that_will_run(sandbox):
    """`P8-00`. Nobody can tell what "Command" plus "Arguments" adds up to."""
    out = run(sandbox, """
        console.log(JSON.stringify({
          plain: F.formatCommandLine('npx', ['-y', '@modelcontextprotocol/server-filesystem']),
          spaced: F.formatCommandLine('python3', ['-m', 'my server']),
          bare: F.formatCommandLine('uvx', []),
          empty: F.formatCommandLine('', []),
        }));
    """)
    assert out["plain"] == "npx -y @modelcontextprotocol/server-filesystem"
    assert out["spaced"] == 'python3 -m "my server"'
    assert out["bare"] == "uvx"
    assert out["empty"] == ""


# ---------------------------------------------------------------------------
# `P8-48`, read half — the schema that was already on the wire
# ---------------------------------------------------------------------------


def test_the_payload_carries_the_schema_and_not_the_annotations():
    """The row says *"the schema is already carried end-to-end"*. Half of it is.

    `get_all_tools` copies `input_schema` into every entry and **does not copy
    `annotations`**, which is captured at both stdio and SSE connect sites and
    read by `mcp_tool_is_readonly`. So the schema can be shown today and the
    readOnlyHint/destructiveHint UI cannot be built at all — not the editor,
    not even the display — without a payload change in a file this agent does
    not own. Driven rather than grepped: the manager is constructed, given a
    tool, and asked.
    """
    from src.mcp_manager import McpManager

    manager = McpManager.__new__(McpManager)
    manager._tools = {"srv": [{
        "name": "read_file",
        "description": "Read a file",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        "annotations": {"readOnlyHint": True},
    }]}
    manager._connections = {"srv": {"name": "Filesystem"}}
    payload = manager.get_all_tools()
    assert len(payload) == 1
    entry = payload[0]
    assert entry["input_schema"]["properties"]["path"]["type"] == "string"
    assert "annotations" not in entry, (
        "if this passes, the annotation half of P8-48 is unblocked on the read side"
    )


def test_the_schema_becomes_a_parameter_list_a_person_can_read(sandbox):
    out = run(sandbox, """
        const schema = {
          type: 'object',
          properties: {
            path: { type: 'string', description: 'Absolute path to read' },
            encoding: { type: ['string', 'null'] },
            mode: { enum: ['text', 'binary'] },
            depth: { anyOf: [{ type: 'integer' }, { type: 'null' }] },
          },
          required: ['path'],
        };
        const summary = F.summariseSchema(schema);
        console.log(JSON.stringify({
          summary, line: F.describeParameters(summary),
          none: F.describeParameters(F.summariseSchema({})),
          allReq: F.describeParameters(F.summariseSchema(
            { properties: { a: {} }, required: ['a'] })),
        }));
    """)
    params = out["summary"]["params"]
    assert params[0]["name"] == "path", "required parameters come first"
    assert params[0]["required"] is True
    assert params[0]["description"] == "Absolute path to read"
    by_name = {p["name"]: p for p in params}
    assert by_name["encoding"]["type"] == "string", "a nullable union reads as its type"
    assert by_name["mode"]["choices"] == ["text", "binary"]
    assert by_name["depth"]["type"] == "integer"
    assert out["line"] == "4 parameters, 1 required"
    assert out["none"] == "Takes no parameters"
    assert out["allReq"] == "1 required parameter"


def test_a_schema_written_by_somebody_else_does_not_break_the_panel(sandbox):
    """An MCP server writes this. It may be absent, null, or not a schema."""
    out = run(sandbox, """
        const bad = [undefined, null, 5, 'nope', [], { properties: null },
                     { properties: { a: 'not an object' } }];
        console.log(JSON.stringify(bad.map((s) => F.summariseSchema(s).count)));
    """)
    assert out == [0, 0, 0, 0, 0, 0, 1]


def test_the_tool_row_shows_what_the_model_calls_it_and_what_it_takes(sandbox):
    out = run(sandbox, """
        const row = F.createMcpToolRow({
          name: 'write_file',
          qualified_name: 'mcp__abc123__write_file',
          description: 'Write text to a file on disk',
          is_disabled: false,
          input_schema: { type: 'object',
            properties: { path: { type: 'string' }, contents: { type: 'string' } },
            required: ['path', 'contents'] },
        });
        document.body.appendChild(row);
        const toggle = row.querySelector('.mcp-tool-more');
        const closed = { label: toggle.textContent, expanded: toggle.getAttribute('aria-expanded'),
                         detail: row.querySelector('.mcp-tool-schema').style.display };
        click(toggle);
        console.log(JSON.stringify({
          closed,
          openText: row.querySelector('.mcp-tool-schema').readable,
          openExpanded: toggle.getAttribute('aria-expanded'),
          checkbox: row.querySelector('input').checked,
          toolName: row.querySelector('input').getAttribute('data-mcp-tool-name'),
        }));
    """)
    assert out["closed"]["label"].startswith("2 required parameters")
    assert out["closed"]["expanded"] == "false"
    assert out["closed"]["detail"] == "none"
    assert out["openExpanded"] == "true"
    assert "mcp__abc123__write_file" in out["openText"]
    assert "path" in out["openText"] and "contents" in out["openText"]
    # The save path reads exactly these two, and this row is not the place to
    # reorganise it.
    assert out["checkbox"] is True
    assert out["toolName"] == "write_file"


def test_a_disabled_tool_still_renders_unchecked(sandbox):
    out = run(sandbox, """
        const row = F.createMcpToolRow({ name: 't', is_disabled: true, input_schema: {} });
        console.log(JSON.stringify({ checked: row.querySelector('input').checked }));
    """)
    assert out["checked"] is False


def test_a_description_with_a_quote_in_it_is_text_and_never_markup(sandbox):
    """`H01`, and a live hole in the markup this replaces.

    The panel wrote `title="${esc(t.description)}"` with an `esc` that escapes
    `&` and `<` and not `"` (`static/js/settings.js:5552`), so a description
    containing a double quote closed the attribute early. Node-by-node
    construction removes the attribute and the question with it.
    """
    out = run(sandbox, """
        const nasty = 'Say "hi" <img src=x onerror=alert(1)> & run';
        const row = F.createMcpToolRow({ name: 'x', description: nasty, input_schema: {} });
        const span = row.querySelector('span');
        console.log(JSON.stringify({
          text: row.readable,
          html: span.innerHTML,
          childTags: Array.from(row.querySelectorAll('img')).length,
        }));
    """)
    assert '"hi"' in out["text"]
    assert out["childTags"] == 0
    assert out["html"] == "", "nothing was ever assigned as markup"
