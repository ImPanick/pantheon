# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-19` — stderr, separated, and the exit code that was only ever a colour.

The two streams were joined into one string with a `STDERR:` marker and then
truncated **as one**, so a failing command with chatty output lost its error
message entirely — from the card and from the model's context alike. Measured
against the real cap: 12,000 characters of stdout, and the `ValueError` on the
end is gone.

The row's summary is *"the model sees stdout and stderr labelled separately; the
user only sees stderr when stdout is empty"*, and the mechanism turned out to be
a branch order in the loop. `elif "stdout" in result:` came **before**
`elif "output" in result:` and read `stdout or stderr or error` — so on a
timed-out command, which is where the two streams were returned separately, a
non-empty stdout meant stderr was never reached at all.

So: stderr gets a reserved share of the budget instead of the leftovers, the
merged view wins the branch, the card shows the error in its own pane, and the
numeric exit code is on screen. `127` and `124` are the difference between "not
installed" and "killed after the timeout", and both used to read as a red card
and nothing else.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _copy_unstubbed_imports  # noqa: E402

from src.agent_tools.subprocess_tools import split_streams
from src.constants import MAX_OUTPUT_CHARS

from tests.helpers.esc_stub import ui_default_stub  # B874

_REPO = Path(__file__).resolve().parent.parent
_MODULE = _REPO / "static" / "js" / "agentThread.js"

# `B874`. The shipped escaper, read out of `static/js/util/escapeHtml.js`
# at test time rather than restated here. Seven files held this same
# five-character copy and three more held one that escaped nothing.
_UI_STUB = ui_default_stub()

ERROR = "ValueError: the real problem"


# ── the budget ────────────────────────────────────────────────────────────────


def test_a_chatty_command_can_no_longer_bury_its_own_error():
    # The measurement the row is really about, run against the real cap.
    result = split_streams("x" * (MAX_OUTPUT_CHARS + 2000), ERROR)
    assert ERROR in result["output"], "the error was truncated away again"
    assert result["stderr"] == ERROR


def test_the_error_is_reachable_without_reading_the_output():
    result = split_streams("x" * 5000, ERROR)
    assert result["stderr"] == ERROR
    assert result["stdout"] == "x" * 5000


def test_stdout_keeps_the_whole_budget_when_nothing_went_wrong():
    # The reserve is only spent when there is an error to spend it on, so an
    # ordinary command loses nothing to this.
    quiet = split_streams("x" * (MAX_OUTPUT_CHARS + 2000), "")
    noisy = split_streams("x" * (MAX_OUTPUT_CHARS + 2000), ERROR)
    assert len(quiet["stdout"]) > len(noisy["stdout"])
    assert quiet["stderr"] == ""


def test_an_enormous_error_is_capped_too():
    # A reserve is a floor, not a licence: a process that prints megabytes to
    # stderr must not push the context past the cap either.
    result = split_streams("", "e" * (MAX_OUTPUT_CHARS * 2))
    assert len(result["stderr"]) < MAX_OUTPUT_CHARS
    assert "truncated" in result["stderr"]


def test_the_merged_view_keeps_the_shape_every_reader_expects():
    # The model has been reading `STDERR:` in this prompt since before the row.
    result = split_streams("hello", ERROR)
    assert result["output"] == f"hello\nSTDERR: {ERROR}"


def test_a_silent_command_says_so_rather_than_nothing():
    assert split_streams("", "")["output"] == "(no output)"


def test_an_error_with_no_output_is_still_an_error():
    assert split_streams("", "boom")["output"] == "STDERR: boom"


@pytest.mark.parametrize("stdout, stderr", [(None, None), ("", None), (None, "x")])
def test_a_stream_that_never_arrived_does_not_crash_the_result(stdout, stderr):
    assert isinstance(split_streams(stdout, stderr)["output"], str)


# ── the branch that hid it ────────────────────────────────────────────────────


_LOOP = (_REPO / "src" / "agent_loop.py").read_text(encoding="utf-8")


def test_the_merged_view_wins_the_branch():
    # The ordering *was* the defect: `stdout or stderr or error` never reached
    # its second term when the first was non-empty.
    #
    # Scoped to the chain that builds `output_text`. A `elif "stdout" in result`
    # also appears in the web-sources stripper a hundred lines earlier, and
    # comparing raw file offsets found that one instead — a whole-file `.index`
    # is a fine way to assert about the wrong code.
    chain = _LOOP[_LOOP.index("            output_text = \"\""):]
    chain = chain[:chain.index('elif "response" in result:')]
    output_at = chain.index('elif "output" in result:')
    stdout_at = chain.index('elif "stdout" in result:')
    assert output_at < stdout_at, (
        "the stdout-first branch is back, and with it a timed-out command that "
        "printed anything shows no error"
    )


def test_the_streams_reach_the_card_only_when_there_is_an_error():
    import src.agent_loop as agent_loop
    assert agent_loop._stream_fields({"stdout": "a", "stderr": "boom"}) == {
        "stdout": "a", "stderr": "boom"}
    # An empty stderr means `output` already is stdout, so sending a second copy
    # of it would double the payload of every successful command.
    assert agent_loop._stream_fields({"stdout": "a", "stderr": ""}) == {}
    assert agent_loop._stream_fields({"stdout": "a"}) == {}
    assert agent_loop._stream_fields({"stderr": "   "}) == {}
    assert agent_loop._stream_fields(None) == {}


def test_a_timed_out_command_still_has_something_to_show():
    # Both timeout branches returned the two streams and no merged view, so the
    # card for a killed command — where what it managed to print matters most —
    # had nothing in it.
    tools = (_REPO / "src" / "agent_tools" / "subprocess_tools.py").read_text(encoding="utf-8")
    for marker in ('"exit_code": 124, **split_streams(stdout, stderr)}',
                   '**split_streams(stdout, stderr),'):
        assert marker in tools
    assert '"stdout": _truncate(stdout, MAX_OUTPUT_CHARS)' not in tools, (
        "a timeout branch still builds the streams by hand"
    )


# ── the panes ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = tmp_path_factory.mktemp("panes")
    (d / "ui.js").write_text(_UI_STUB, encoding="utf-8")
    shutil.copy(_MODULE, d / "agentThread.js")
    # `P5-04` added an import to `agentThread.js`, and a sandbox that copies one
    # file cannot see one. `_copy_unstubbed_imports` was written for exactly this
    # ("adding one import to a sandboxed module breaks every sandbox that copies
    # it") and is borrowed rather than re-implemented here (`Law 14`): `ui.js` keeps
    # its stub, everything else comes in for real, transitively.
    _copy_unstubbed_imports(d, _MODULE, {"ui.js"})
    return d


def _panes(sandbox: Path, event: dict) -> str:
    entry = sandbox / "case.mjs"
    entry.write_text(
        "const m = await import('./agentThread.js');\n"
        + textwrap.dedent(f"""
        console.log(JSON.stringify(m.toolOutputPanesHtml({json.dumps(event)})));
        """),
        encoding="utf-8",
    )
    proc = subprocess.run(["node", str(entry)], cwd=sandbox, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_an_error_gets_its_own_pane(sandbox):
    html = _panes(sandbox, {"output": f"hello\nSTDERR: {ERROR}", "stdout": "hello",
                            "stderr": ERROR, "exit_code": 1})
    assert "agent-tool-stderr" in html
    assert "Error output (stderr)" in html
    assert html.count(ERROR) == 1, "the error is shown twice"
    assert ">hello<" in html


def test_the_error_pane_does_not_need_a_click(sandbox):
    # Law 15. It is short, it is why the card is red, and a click to reach the
    # reason is a click the reader should not have to make.
    html = _panes(sandbox, {"output": "x", "stdout": "x", "stderr": ERROR, "exit_code": 1})
    assert "agent-tool-stderr\" open" in html


def test_a_clean_command_gets_one_pane_as_before(sandbox):
    html = _panes(sandbox, {"output": "hello", "exit_code": 0})
    assert "agent-tool-stderr" not in html
    # Count the pane, not the word. `P5-08` put a copy button in the summary
    # whose class is `agent-tool-output-copy`, and a substring count read that
    # as a second pane — `Law 20`'s exact failure, caught by its own file.
    assert html.count('<details class="agent-tool-output') == 1
    assert ">hello<" in html


def test_a_command_with_no_output_gets_no_panes(sandbox):
    assert _panes(sandbox, {"output": "", "exit_code": 0}) == ""


def test_the_exit_code_is_a_number_and_not_just_a_colour(sandbox):
    html = _panes(sandbox, {"output": "x", "exit_code": 127})
    assert "Exited 127" in html


def test_a_timeout_says_it_timed_out(sandbox):
    # `124` is the difference between "not installed" and "killed", and both
    # used to read as a red card and nothing else.
    html = _panes(sandbox, {"output": "x", "exit_code": 124})
    assert "Exited 124" in html and "timed out" in html


@pytest.mark.parametrize("code", [0, None, "", "boom", float("nan")])
def test_nothing_that_is_not_a_failing_code_is_announced(sandbox, code):
    # "Exited 0" on every successful card is noise, and a code nobody can parse
    # is worse than none.
    html = _panes(sandbox, {"output": "x", "exit_code": code})
    assert "agent-thread-exit-code" not in html, code


def test_the_streams_cannot_be_written_by_the_command(sandbox):
    html = _panes(sandbox, {"output": "x", "stdout": "x",
                            "stderr": "<img src=x onerror=alert(1)>", "exit_code": 1})
    assert "<img" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_both_surfaces_use_the_one_builder():
    # `Law 14`. There were two copies of the merged-pane markup and both had
    # the same defect, which is what a second copy is for.
    for rel in ("static/js/chat.js", "static/js/chatRenderer.js"):
        text = (_REPO / rel).read_text(encoding="utf-8")
        assert "toolOutputPanesHtml(" in text, rel
        # The literal a hand-built copy would carry. It is not the builder's
        # own string any more (`P5-08` put a copy button between the label and
        # the `</summary>`), which is the point: a caller still emitting the
        # old markup is a caller that stopped tracking the builder.
        assert '<details class="agent-tool-output"><summary>Output</summary>' not in text, (
            f"{rel} still builds the output pane by hand"
        )
