# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-17` — the verifier's findings, and the outcome that was not an outcome.

A second model with no shared history reads the request and a record of what the
agent actually did, and judges whether "done" is true. It is the one step in the
loop whose entire job is to not be taken on trust — and its findings went into
the **prompt** and nowhere else. The reader got one sentence, *"Double-checked
the work and found something to fix"*, and never saw what.

Reporting it needed the verdict to be honest first. `_run_verifier_subagent`
returned a bare list of issues, and **three different things returned the empty
one**: the verifier passed the work, the verifier raised (network, timeout, a
model that will not answer), and the verifier answered without ever emitting a
`VERIFICATION:` line. Not blocking a valid completion on an error is right and
it stays. Saying *an independent model checked this and agreed* when no second
model spoke is a different claim, and it is the one this row is about.

A fourth case was hiding in the parser: `VERIFICATION: FAIL` with no colon has
no reasons to split, fell through the `"VERIFICATION: FAIL:" not in line` test,
and was reported as a pass. A refusal to sign off is not a pass.
"""

import asyncio
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _copy_unstubbed_imports  # noqa: E402

import src.agent_loop as agent_loop
from src.agent_loop import VerifierVerdict, _run_verifier_subagent

from tests.helpers.esc_stub import ui_default_stub  # B874

_REPO = Path(__file__).resolve().parent.parent
_MODULE = _REPO / "static" / "js" / "agentThread.js"

# `B874`. The shipped escaper, read out of `static/js/util/escapeHtml.js`
# at test time rather than restated here. Seven files held this same
# five-character copy and three more held one that escaped nothing.
_UI_STUB = ui_default_stub()


# ── the verdict ───────────────────────────────────────────────────────────────


def _verify(monkeypatch, reply=None, *, raises=None):
    async def fake_call(**kwargs):
        if raises is not None:
            raise raises
        return reply

    import src.llm_core as llm_core
    monkeypatch.setattr(llm_core, "llm_call_async", fake_call, raising=False)
    return asyncio.run(_run_verifier_subagent(
        "do the thing", "did the thing",
        endpoint_url="http://local.test/v1", model="m", headers={},
    ))


def test_a_clean_verdict_is_a_pass(monkeypatch):
    v = _verify(monkeypatch, "Looks right.\nVERIFICATION: SUCCESS")
    assert v.outcome == "pass"
    assert not v


def test_a_listed_failure_carries_its_reasons(monkeypatch):
    v = _verify(monkeypatch,
                "VERIFICATION: FAIL: the file was never written; the tests were not run")
    assert v.outcome == "fail"
    assert list(v.issues) == ["the file was never written", "the tests were not run"]
    assert v, "the loop's fix-it branch reads this as truthy"


def test_a_verifier_that_could_not_run_is_not_a_pass(monkeypatch):
    # The defect. Three paths returned the same empty list, so an error read as
    # agreement — on screen and in the code.
    v = _verify(monkeypatch, raises=RuntimeError("connection refused"))
    assert v.outcome == "unavailable"
    assert "connection refused" in v.detail


def test_an_answer_with_no_verdict_line_is_not_a_pass(monkeypatch):
    v = _verify(monkeypatch, "I am not sure I can judge this from what I was given.")
    assert v.outcome == "unavailable"
    assert v.detail


def test_a_refusal_to_sign_off_is_not_a_pass(monkeypatch):
    # `VERIFICATION: FAIL` with no colon: nothing to split, so it fell past the
    # FAIL test and was reported as agreement.
    v = _verify(monkeypatch, "VERIFICATION: FAIL")
    assert v.outcome == "fail"
    assert v.issues


def test_a_failure_that_lists_nothing_still_fails(monkeypatch):
    v = _verify(monkeypatch, "VERIFICATION: FAIL:   ;  ; ")
    assert v.outcome == "fail"
    assert v.issues


@pytest.mark.parametrize("verdict, blocks", [
    (VerifierVerdict("pass"), False),
    (VerifierVerdict("unavailable", detail="it fell over"), False),
    (VerifierVerdict("fail", issues=("nope",)), True),
])
def test_only_real_issues_stop_the_agent_finishing(verdict, blocks):
    # The behaviour the docstring promised and this row had to keep: an error
    # must not block a valid completion. `__bool__` is what the loop reads.
    assert bool(verdict) is blocks


def test_the_last_verdict_line_is_the_one_that_counts(monkeypatch):
    # The model reasons before answering and can name the format mid-thought.
    v = _verify(monkeypatch,
                "I might say VERIFICATION: FAIL: nothing here\n"
                "…on reflection it is fine.\nVERIFICATION: SUCCESS")
    assert v.outcome == "pass"


# ── the report ────────────────────────────────────────────────────────────────


def _events(chunks):
    out = []
    for chunk in chunks:
        if not chunk.startswith("data: ") or chunk.startswith("data: [DONE]"):
            continue
        try:
            out.append(json.loads(chunk[6:]))
        except json.JSONDecodeError:
            pass
    return out


def _run(monkeypatch, verdict):
    settings = {"agent_verifier_subagent": True}
    monkeypatch.setattr(agent_loop, "get_setting",
                        lambda k, d=None: settings.get(k, d), raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(),
                        raising=False)
    replies = iter(["```bash\nprintf hi\n```", "Done."])

    async def fake_stream(*a, **k):
        yield f"data: {json.dumps({'delta': next(replies, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *a, **k):
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    async def fake_verifier(*a, **k):
        return verdict

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)
    monkeypatch.setattr(agent_loop, "_run_verifier_subagent", fake_verifier, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "write the file and run the tests"}],
            max_rounds=3, relevant_tools={"bash"},
        )]

    return _events(asyncio.run(drain()))


def _verifier_events(events):
    return [e for e in events if e.get("type") == "verifier"]


def test_a_failed_check_says_what_it_found(monkeypatch):
    # The row, in one assertion: the issues reached the model and never reached
    # the person the work was for.
    events = _run(monkeypatch, VerifierVerdict(
        "fail", issues=("the file was never written",)))
    reported = _verifier_events(events)
    assert reported, "the findings still go to the model and nowhere else"
    assert reported[0]["outcome"] == "fail"
    assert reported[0]["issues"] == ["the file was never written"]


def test_a_passed_check_is_reported_too(monkeypatch):
    # "A second model read this cold and agreed" is worth saying. Before this
    # it was said only by silence, which is also what a broken verifier said.
    events = _run(monkeypatch, VerifierVerdict("pass"))
    reported = _verifier_events(events)
    assert reported and reported[0]["outcome"] == "pass"
    assert reported[0]["issues"] == []


def test_a_check_that_did_not_run_says_so(monkeypatch):
    events = _run(monkeypatch, VerifierVerdict("unavailable", detail="it fell over"))
    reported = _verifier_events(events)
    assert reported and reported[0]["outcome"] == "unavailable"
    assert reported[0]["detail"] == "it fell over"


def test_the_verdict_names_the_round_it_judged(monkeypatch):
    events = _run(monkeypatch, VerifierVerdict("pass"))
    assert _verifier_events(events)[0]["round"] >= 1


def test_the_verdict_survives_a_reload(monkeypatch):
    # Same invariant as every other row in this phase: one action, two
    # surfaces, one answer.
    events = _run(monkeypatch, VerifierVerdict("fail", issues=("nope",)))
    live = _verifier_events(events)
    metrics = next(e for e in events if e.get("type") == "metrics")["data"]
    assert metrics.get("verifier_findings") == live


def test_a_turn_with_no_check_reports_none(monkeypatch):
    # The toggle is off by default; a card claiming a check nobody ran is the
    # defect this row exists to remove, not one to add.
    settings = {"agent_verifier_subagent": False}
    monkeypatch.setattr(agent_loop, "get_setting",
                        lambda k, d=None: settings.get(k, d), raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(),
                        raising=False)
    replies = iter(["```bash\nprintf hi\n```", "Done."])

    async def fake_stream(*a, **k):
        yield f"data: {json.dumps({'delta': next(replies, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *a, **k):
        return (block.tool_type, {"output": "ok", "exit_code": 0})

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "write the file and run the tests"}],
            max_rounds=3, relevant_tools={"bash"},
        )]

    events = _events(asyncio.run(drain()))
    assert _verifier_events(events) == []
    metrics = next(e for e in events if e.get("type") == "metrics")["data"]
    assert "verifier_findings" not in metrics


def test_the_issues_still_reach_the_model(monkeypatch):
    # Reporting them must not stop them being fixed. The system message that
    # tells the agent to go and fix the findings is the point of the verifier.
    events = _run(monkeypatch, VerifierVerdict("fail", issues=("the file was never written",)))
    text = "".join(e.get("delta", "") for e in events)
    assert "Double-checked" in text, "the reply no longer mentions the re-check"


# ── the card ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = tmp_path_factory.mktemp("verifiercard")
    (d / "ui.js").write_text(_UI_STUB, encoding="utf-8")
    shutil.copy(_MODULE, d / "agentThread.js")
    # `P5-04` added an import to `agentThread.js`, and a sandbox that copies one
    # file cannot see one. `_copy_unstubbed_imports` was written for exactly this
    # ("adding one import to a sandboxed module breaks every sandbox that copies
    # it") and is borrowed rather than re-implemented here (`Law 14`): `ui.js` keeps
    # its stub, everything else comes in for real, transitively.
    _copy_unstubbed_imports(d, _MODULE, {"ui.js"})
    return d


def _card(sandbox: Path, event: dict) -> str:
    entry = sandbox / "case.mjs"
    entry.write_text(
        "const m = await import('./agentThread.js');\n"
        + textwrap.dedent(f"""
        const opts = m.verifierCardOptions({json.dumps(event)});
        console.log(JSON.stringify({{ html: m.agentThreadNodeHtml(opts), opts }}));
        """),
        encoding="utf-8",
    )
    proc = subprocess.run(["node", str(entry)], cwd=sandbox, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_a_failed_check_shows_every_issue(sandbox):
    out = _card(sandbox, {"outcome": "fail", "round": 2,
                          "issues": ["the file was never written",
                                     "the tests were not run"]})
    assert "the file was never written" in out["html"]
    assert "the tests were not run" in out["html"]
    assert out["opts"]["ok"] is False


def test_a_passed_check_reads_as_a_pass(sandbox):
    out = _card(sandbox, {"outcome": "pass", "round": 1, "issues": []})
    assert out["opts"]["ok"] is True
    assert "Verified" in out["html"]
    assert "✓" in out["html"]


def test_a_check_that_could_not_run_does_not_read_as_agreement(sandbox):
    # The whole point. A tick here says a second model agreed, and none did.
    out = _card(sandbox, {"outcome": "unavailable", "round": 1, "issues": [],
                          "detail": "the check did not run: timeout"})
    assert out["opts"]["ok"] is False
    assert "✓" not in out["html"]
    assert "Not verified" in out["html"]
    assert "timeout" in out["html"]


def test_an_unknown_outcome_is_treated_as_unavailable(sandbox):
    # A value from a future emit site, or junk. "It could not say" is the only
    # safe reading of an outcome nobody recognises.
    for outcome in ("", "SUCCESS", None, "maybe", 1):
        out = _card(sandbox, {"outcome": outcome, "round": 1, "issues": []})
        assert out["opts"]["ok"] is False, outcome


def test_the_card_carries_the_round_like_every_other_one(sandbox):
    out = _card(sandbox, {"outcome": "pass", "round": 4, "issues": []})
    assert 'title="Agent round 4"' in out["html"]


def test_the_findings_cannot_be_written_by_the_verifier(sandbox):
    # The issues are a second model's free text and go straight into the page.
    out = _card(sandbox, {"outcome": "fail", "round": 1,
                          "issues": ["<img src=x onerror=alert(1)>"]})
    assert "<img" not in out["html"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in out["html"]


def test_the_reason_a_check_failed_to_run_cannot_be_written_either(sandbox):
    out = _card(sandbox, {"outcome": "unavailable", "round": 1, "issues": [],
                          "detail": "<script>alert(1)</script>"})
    assert "<script>" not in out["html"]
