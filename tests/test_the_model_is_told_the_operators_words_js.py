# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-48`, re-cut (`D-2026-09-27-02`) — the browser half of the description
override: Settings → MCP → a connected server → a tool.

Before this, the tool row drew the server's `description` and nothing else
could be said about it. A third-party server's description is often one word,
or wrong about this install, and it is the only thing the model reads when
deciding whether to call the tool. The row now shows **whose words** the model
is reading, offers a box to rewrite them, shows the server's own words beside
a rewrite, and takes a rewrite back with one button.

Driven under node against the real `static/js/settings/mcpFields.js`, in the
harness `tests/test_the_mcp_form_names_the_field_js.py` already uses — no case
greps a file (`Law 20`). The two things `settings.js` adds (one save path for
both answers, and `Server's answer` taking back only its own key) are driven
too: the three bindings are cut out of `static/js/settings.js` by
`tests/helpers/js_source.js_binding` and run against a recording `fetch`.

The payloads handed to the row are **Python's own**: a case asks
`McpManager.get_all_tools` for the entry and feeds it to the module, so the two
halves are checked against each other rather than against a hand-written
imitation of one of them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_tool_effect_surfaces_js import _make_sandbox  # noqa: E402
from test_the_mcp_form_names_the_field_js import _SHIM, run  # noqa: E402
from tests.helpers.js_source import js_binding  # noqa: E402

MCP_FIELDS = ROOT / "static" / "js" / "settings" / "mcpFields.js"
SETTINGS = ROOT / "static" / "js" / "settings.js"

_SETTLE = "await new Promise((r) => setTimeout(r, 0));"
_OPEN = "row.querySelector('.mcp-tool-more').dispatchEvent({ type: 'click', preventDefault() {} });"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("mcpdesc"), MCP_FIELDS, _SHIM, {})


def _payload(override=None):
    """One tool entry exactly as `GET /api/mcp/servers/{id}/tools` builds it."""
    from src.mcp_manager import McpManager, normalize_tool_overrides

    mgr = McpManager.__new__(McpManager)
    mgr._tools = {"srv1": [{"name": "query", "description": "Run a query",
                            "input_schema": {"type": "object", "properties": {}},
                            "annotations": None}]}
    mgr._connections = {"srv1": {"name": "Ops"}}
    overrides = {"srv1": normalize_tool_overrides({"query": override})} if override else {}
    return mgr.get_all_tools(overrides=overrides)[0]


# A row plus everything a case wants to read off it.
_DESCRIBE = """
function look(row) {
  const box = row.querySelector('.mcp-tool-description');
  const input = row.querySelector('[data-mcp-description-input]');
  const save = row.querySelector('[data-mcp-description="save"]');
  const reset = row.querySelector('[data-mcp-description="reset"]');
  return {
    line: row.querySelector('.mcp-tool-description-text').textContent,
    mine: row.querySelector('.mcp-tool-description-mine').textContent,
    lineSource: row.querySelector('.mcp-tool-description-text').getAttribute('data-mcp-description-source'),
    editor: !!box,
    whose: box ? row.querySelector('.mcp-tool-description-whose').textContent : null,
    theirs: box ? row.querySelector('.mcp-tool-description-server').textContent : null,
    theirsShown: box ? row.querySelector('.mcp-tool-description-server').style.display !== 'none' : null,
    value: input ? input.value : null,
    saveDisabled: save ? save.disabled : null,
    resetShown: reset ? reset.style.display !== 'none' : null,
    count: box ? row.querySelector('.mcp-tool-description-count').textContent : null,
    status: box ? row.querySelector('.mcp-tool-description-status').textContent : null,
    statusRole: box ? row.querySelector('.mcp-tool-description-status').getAttribute('role') : null,
    readable: row.readable,
  };
}
"""


def _row(sandbox, entry, setter_js="null", then=""):
    return run(sandbox, _DESCRIBE + f"""
        const calls = [];
        const setter = {setter_js};
        const row = F.createMcpToolRow({json.dumps(entry)},
          setter ? {{ onDescription: (n, v) => {{ calls.push([n, v]); return setter(n, v); }} }} : {{}});
        document.body.appendChild(row);
        const closed = look(row);
        {_OPEN}
        const opened = look(row);
        {then}
        {_SETTLE}
        console.log(JSON.stringify({{ closed, opened, after: look(row), calls }}));
    """)


# ---------------------------------------------------------------------------
# Whose words, on the closed row
# ---------------------------------------------------------------------------


def test_the_closed_row_says_when_the_words_are_the_operators(sandbox):
    """The badge's rule, one field over: a rewrite never reads as the server's."""
    ours = _row(sandbox, _payload({"description": "Sales SQL, read-only"}))["closed"]
    theirs = _row(sandbox, _payload())["closed"]

    assert ours["line"] == " — Sales SQL, read-only"
    assert ours["mine"] == " (your wording)"
    assert ours["lineSource"] == "override"

    assert theirs["line"] == " — Run a query"
    assert theirs["mine"] == ""
    assert theirs["lineSource"] == "server"


# ---------------------------------------------------------------------------
# The editor
# ---------------------------------------------------------------------------


_ANSWER = """(n, v) => Promise.resolve(v === null
  ? { name: n, description: 'Run a query', server_description: 'Run a query',
      description_source: 'server', description_max: 1024 }
  : { name: n, description: v.trim(), server_description: 'Run a query',
      description_source: 'override', description_max: 1024 })"""


def test_the_panel_shows_what_the_model_reads_and_whose_it_is(sandbox):
    out = _row(sandbox, _payload(), _ANSWER)["opened"]
    assert out["editor"] is True
    assert out["whose"] == "These are the server’s own words."
    assert out["value"] == "Run a query"
    assert out["theirsShown"] is False, "no rewrite, so nothing to compare against"
    assert out["resetShown"] is False, "nothing to take back"
    assert out["saveDisabled"] is True, "nothing typed yet is nothing to save"
    assert out["count"] == "11 of 1024 characters"
    assert "It does not change what the tool accepts." in out["readable"]


def test_a_person_rewrites_it_and_the_row_says_so_everywhere(sandbox):
    """`P8-00`: someone who has never read this tracker opens a tool, types a
    better sentence, presses Save wording, and the row — closed and open —
    says the model now reads their words and shows what the server said."""
    out = _row(sandbox, _payload(), _ANSWER, then="""
        const input = row.querySelector('[data-mcp-description-input]');
        input.value = '  Sales figures only. Read-only SQL on the replica.  ';
        input.dispatchEvent({ type: 'input' });
        const typed = look(row);
        row.querySelector('[data-mcp-description="save"]').dispatchEvent(
          { type: 'click', preventDefault() {} });
    """)
    assert out["calls"] == [["query", "Sales figures only. Read-only SQL on the replica."]]
    after = out["after"]
    assert after["line"] == " — Sales figures only. Read-only SQL on the replica."
    assert after["mine"] == " (your wording)"
    assert after["whose"] == "You rewrote this on this install. The server’s own words:"
    assert after["theirs"] == "Run a query" and after["theirsShown"] is True
    assert after["resetShown"] is True
    assert after["status"] == "Saved."
    assert after["statusRole"] == "status", "the answer is announced, not only drawn"
    assert after["saveDisabled"] is True, "what is saved is not a change"


def test_use_the_servers_takes_the_rewrite_back(sandbox):
    out = _row(sandbox, _payload({"description": "Sales SQL, read-only"}), _ANSWER, then="""
        row.querySelector('[data-mcp-description="reset"]').dispatchEvent(
          { type: 'click', preventDefault() {} });
    """)
    assert out["opened"]["resetShown"] is True
    assert out["calls"] == [["query", None]]
    after = out["after"]
    assert after["line"] == " — Run a query" and after["mine"] == ""
    assert after["value"] == "Run a query"
    assert after["resetShown"] is False
    assert after["status"] == "Back to the server’s words."


def test_the_servers_own_words_typed_back_are_not_a_rewrite(sandbox):
    """Stored as a rewrite they would pin today's wording and hide the
    server's next change, so they are sent as the erase."""
    out = _row(sandbox, _payload({"description": "Sales SQL"}), _ANSWER, then="""
        const input = row.querySelector('[data-mcp-description-input]');
        input.value = 'Run a query';
        input.dispatchEvent({ type: 'input' });
        row.querySelector('[data-mcp-description="save"]').dispatchEvent(
          { type: 'click', preventDefault() {} });
    """)
    assert out["calls"] == [["query", None]]
    assert out["after"]["mine"] == ""


@pytest.mark.parametrize("typed,expect_disabled,count", [
    ("", True, "0 of 1024 characters"),
    ("   ", True, "0 of 1024 characters"),
    ("Run a query", True, "11 of 1024 characters"),
    ("x" * 1024, False, "1024 of 1024 characters"),
    ("x" * 1030, True, "6 characters over the limit of 1024"),
])
def test_save_is_only_offered_for_something_that_can_be_saved(sandbox, typed, expect_disabled, count):
    out = _row(sandbox, _payload(), _ANSWER, then=f"""
        const input = row.querySelector('[data-mcp-description-input]');
        input.value = {json.dumps(typed)};
        input.dispatchEvent({{ type: 'input' }});
    """)
    assert out["after"]["saveDisabled"] is expect_disabled
    assert out["after"]["count"] == count


def test_an_over_long_or_empty_save_never_reaches_the_server(sandbox):
    """A disabled button is not the only guard: the click is refused too."""
    for typed, says in (("x" * 1030, "1030 characters; the limit is 1024."),
                        ("   ", "Empty.")):
        out = _row(sandbox, _payload(), _ANSWER, then=f"""
            const input = row.querySelector('[data-mcp-description-input]');
            input.value = {json.dumps(typed)};
            const save = row.querySelector('[data-mcp-description="save"]');
            save.disabled = false;
            save.dispatchEvent({{ type: 'click', preventDefault() {{}} }});
        """)
        assert out["calls"] == []
        assert out["after"]["status"].startswith(says)


def test_a_refusal_keeps_what_was_typed_and_changes_nothing_else(sandbox):
    out = _row(sandbox, _payload(),
               "() => Promise.reject(new Error('you are not signed in as an administrator'))",
               then="""
        const input = row.querySelector('[data-mcp-description-input]');
        input.value = 'A sentence somebody took care over';
        input.dispatchEvent({ type: 'input' });
        row.querySelector('[data-mcp-description="save"]').dispatchEvent(
          { type: 'click', preventDefault() {} });
    """)
    after = out["after"]
    assert after["status"] == "Not saved — you are not signed in as an administrator"
    assert after["value"] == "A sentence somebody took care over", "the typing was thrown away"
    assert after["line"] == " — Run a query" and after["mine"] == ""
    assert after["saveDisabled"] is False, "a refusal must not leave the box unusable"


def test_a_throw_is_a_refusal_and_not_an_unhandled_rejection(sandbox):
    out = _row(sandbox, _payload(), "() => { throw new Error('offline'); }", then="""
        const input = row.querySelector('[data-mcp-description-input]');
        input.value = 'Better';
        row.querySelector('[data-mcp-description="save"]').dispatchEvent(
          { type: 'click', preventDefault() {} });
    """)
    assert out["after"]["status"] == "Not saved — offline"
    assert out["after"]["mine"] == ""


def test_markup_in_either_description_is_text_and_never_markup(sandbox):
    """`H01`. The server's words come from a third party, and the operator's
    are shown back to every admin who opens the panel."""
    nasty = 'Say "hi" <img src=x onerror=alert(1)> & run'
    entry = _payload({"description": nasty})
    entry["server_description"] = nasty
    out = run(sandbox, f"""
        const row = F.createMcpToolRow({json.dumps(entry)}, {{ onDescription: () => null }});
        {_OPEN}
        const html = ['.mcp-tool-description-text', '.mcp-tool-description-mine',
                      '.mcp-tool-description-whose', '.mcp-tool-description-server']
          .map((s) => row.querySelector(s)._html);
        console.log(JSON.stringify({{
          html, imgs: row.querySelectorAll('img').length,
          value: row.querySelector('[data-mcp-description-input]').value,
          theirs: row.querySelector('.mcp-tool-description-server').textContent,
        }}));
    """)
    assert out["html"] == ["", "", "", ""], "something was assigned as markup"
    assert out["imgs"] == 0
    assert out["value"] == nasty and out["theirs"] == nasty


def test_without_somewhere_to_save_there_is_no_editor_and_nothing_is_lost(sandbox):
    """`Law 1`: a caller with nowhere to write keeps the old panel, which
    printed a long description in full."""
    entry = _payload({"description": "An operator's sentence " * 6})
    out = _row(sandbox, entry)
    assert out["opened"]["editor"] is False
    assert "An operator's sentence An operator's sentence" in out["opened"]["readable"]
    assert out["closed"]["mine"] == " (your wording)"


def test_every_source_python_can_emit_reads_differently(sandbox):
    """The `Law 13` pin across the boundary: ask `description_verdict` for
    every source it can produce, by driving it, and require the row to tell
    them apart."""
    from src.mcp_manager import description_verdict

    emitted = sorted({
        description_verdict({"description": "x"})[1],
        description_verdict({"description": "x"}, {"description": "y"})[1],
    })
    assert emitted == ["override", "server"], "a source was added or renamed in Python"
    marks = [
        _row(sandbox, dict(_payload(), description_source=s))["closed"]["mine"]
        for s in emitted
    ]
    assert len(set(marks)) == 2, marks
    # An unknown source is the claim that needs no evidence: the server's.
    unknown = _row(sandbox, dict(_payload(), description_source="something_new"))["closed"]
    assert unknown["mine"] == "" and unknown["lineSource"] == "server"


# ---------------------------------------------------------------------------
# What `settings.js` sends — its own three bindings, driven
# ---------------------------------------------------------------------------


def _settings_bindings() -> str:
    source = SETTINGS.read_text(encoding="utf-8")
    return ";\n".join(js_binding(source, name) for name in
                      ("saveToolOverride", "onOverride", "onDescription")) + ";\n"


def _drive_settings(sandbox, calls_js: str) -> dict:
    return run(sandbox, f"""
        const {{ describeServerRefusal }} = F;
        const srv = {{ id: 'srv1' }};
        const sent = [];
        globalThis.fetch = async (url, init) => {{
          if (init && init.method === 'PATCH') {{
            sent.push([url, JSON.parse(init.body)]);
            return {{ ok: true, status: 200, json: async () => ({{}}) }};
          }}
          return {{ ok: true, status: 200, json: async () => ([{{ name: 'wipe', description: 'fresh' }}]) }};
        }};
        {_settings_bindings()}
        const answers = [];
        {calls_js}
        console.log(JSON.stringify({{ sent, answers }}));
    """)


def test_servers_answer_takes_back_the_read_only_key_and_nothing_else(sandbox):
    """`settings.js` sent `null` for the WHOLE entry, which was right while an
    entry held one answer. It holds two now, and a whole-entry `null` from the
    read-only buttons would have taken the operator's wording with it."""
    out = _drive_settings(sandbox, """
        answers.push(await onOverride('wipe', null));
        answers.push(await onOverride('wipe', true));
    """)
    assert out["sent"] == [
        ["/api/mcp/servers/srv1/tools", {"overrides": {"wipe": {"read_only": None}}}],
        ["/api/mcp/servers/srv1/tools", {"overrides": {"wipe": {"read_only": True}}}],
    ]
    assert out["answers"][0] == {"name": "wipe", "description": "fresh"}, "the verdict is read back"


def test_the_wording_goes_out_on_the_same_route_under_its_own_key(sandbox):
    out = _drive_settings(sandbox, """
        answers.push(await onDescription('wipe', 'Deletes every row. Never call it in a plan.'));
        answers.push(await onDescription('wipe', null));
    """)
    assert out["sent"] == [
        ["/api/mcp/servers/srv1/tools",
         {"overrides": {"wipe": {"description": "Deletes every row. Never call it in a plan."}}}],
        ["/api/mcp/servers/srv1/tools", {"overrides": {"wipe": {"description": None}}}],
    ]


def test_the_servers_refusal_reaches_the_row_as_its_own_sentence(sandbox):
    out = run(sandbox, f"""
        const {{ describeServerRefusal }} = F;
        const srv = {{ id: 'srv1' }};
        globalThis.fetch = async () => ({{ ok: false, status: 400,
          json: async () => ({{ detail: "description for 'wipe' is 1030 characters; the limit is 1024." }}) }});
        {_settings_bindings()}
        let message = null;
        try {{ await onDescription('wipe', 'x'); }} catch (e) {{ message = e.message; }}
        console.log(JSON.stringify({{ message }}));
    """)
    assert out["message"] == "description for 'wipe' is 1030 characters; the limit is 1024."
