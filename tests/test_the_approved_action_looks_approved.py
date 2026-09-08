# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-12` — the action you personally authorised stops looking like every other one.

`approved: true` has been on four events since exact approvals shipped, and no
line of the frontend ever read it. So the one card in a thread that a person
stopped and allowed by hand carried the same icon, the same label and the same
everything as a routine call — the row's words: *"indistinguishable"*.

Rendering the flag as it stood would have shipped a second, worse defect. Two
gates can refuse an approved action **after** the card is already on screen:
this replay's own `approval_matches` pre-check, and the dispatcher's `claim()`,
which additionally refuses an unarmed run, an approval granted before untrusted
content arrived, a document action with no sealed target, and a workspace that
is no longer safe. All four of those used to emit a result card still saying
`approved: true`. A badge that asserts **authority** over an action that was
blocked is worse than no badge, so `approved` on the result card and its
persisted twin now means what it says: *this ran under your approval*.

That is also why `approved` is deliberately **not** carried across the rewrite
the way `round` is. The round is a fact about the card that later events may
omit; approval is a claim the result is entitled to withdraw.
"""

import asyncio
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

import src.agent_loop as agent_loop
from src.tool_approvals import ToolApprovalStore
from src.tool_capabilities import capabilities_for_action

_REPO = Path(__file__).resolve().parent.parent
_MODULE = _REPO / "static" / "js" / "agentThread.js"

_UI_STUB = """
const MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export default { esc: (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => MAP[c]) };
"""


# ── the badge ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = tmp_path_factory.mktemp("approvedbadge")
    (d / "ui.js").write_text(_UI_STUB, encoding="utf-8")
    shutil.copy(_MODULE, d / "agentThread.js")
    return d


def _node(sandbox: Path, script: str):
    entry = sandbox / "case.mjs"
    entry.write_text(
        "const m = await import('./agentThread.js');\n" + textwrap.dedent(script),
        encoding="utf-8",
    )
    proc = subprocess.run(["node", str(entry)], cwd=sandbox, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"node produced no stdout\n{proc.stderr}"
    return json.loads(lines[-1])


def _card(sandbox: Path, opts: dict) -> str:
    return _node(sandbox, f"console.log(JSON.stringify(m.agentThreadNodeHtml({json.dumps(opts)})));")


def test_an_authorised_action_says_so_on_the_card(sandbox):
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True, "approved": True})
    assert 'class="agent-thread-approved"' in html
    assert "approved" in html


def test_the_badge_says_out_loud_what_it_means(sandbox):
    # Law 15. "approved" alone leaves open *who* approved it and *when*; the
    # tooltip is the only place that answers, so it has to be there.
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True, "approved": True})
    assert 'title="You approved this action"' in html


def test_a_routine_call_is_not_badged(sandbox):
    # The overwhelming majority of cards. A badge on all of them says nothing.
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True})
    assert "agent-thread-approved" not in html


@pytest.mark.parametrize("value", [False, 0, None, "", "true", 1, [], {}])
def test_only_the_literal_truth_earns_the_badge(sandbox, value):
    # `"true"` and `1` are the ones that matter: this badge asserts authority,
    # so a truthy-looking value from a hand-built replay event may not buy it.
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True, "approved": value})
    assert "agent-thread-approved" not in html, f"{value!r} earned the badge"


def test_a_running_card_may_be_badged_before_it_finishes(sandbox):
    # `tool_start` fires before either gate has spoken and says what was
    # believed then. That is honest and it is what the user needs while they
    # watch: this is the thing you just allowed.
    html = _card(sandbox, {"tool": "bash", "state": "running", "approved": True})
    assert "agent-thread-approved" in html


def test_a_refused_action_loses_the_badge_when_the_result_lands(sandbox):
    # The asymmetry with `round`, executed. A round the rewrite omits is
    # remembered; an approval the rewrite withdraws is *withdrawn*, because the
    # result card is the event entitled to correct it.
    out = _node(sandbox, """
        const node = { className: '', innerHTML: '',
                       classList: { contains: (c) => node.className.split(' ').includes(c) } };
        m.applyAgentThreadNode(node, { tool: 'bash', state: 'running', approved: true, round: 2 });
        const running = node.innerHTML;
        m.applyAgentThreadNode(node, { tool: 'bash', state: 'done', ok: false, approved: false });
        console.log(JSON.stringify({ running, done: node.innerHTML }));
    """)
    assert "agent-thread-approved" in out["running"]
    assert "agent-thread-approved" not in out["done"], (
        "a blocked action kept a badge claiming the user authorised it"
    )
    assert ">2<" in out["done"], "the round was withdrawn along with the approval"


def test_an_event_that_says_nothing_about_approval_is_not_a_claim(sandbox):
    # The decision, pinned so the next reader does not "fix" the asymmetry with
    # `round`. A rewrite that omits the round leaves a fact intact; a rewrite
    # that omits the approval must not leave an authority claim standing on the
    # strength of an earlier event. Silence is not consent, on a wire either.
    out = _node(sandbox, """
        const node = { className: '', innerHTML: '',
                       classList: { contains: (c) => node.className.split(' ').includes(c) } };
        m.applyAgentThreadNode(node, { tool: 'bash', state: 'running', approved: true, round: 2 });
        m.applyAgentThreadNode(node, { tool: 'bash', state: 'done', ok: true });
        console.log(JSON.stringify({ html: node.innerHTML }));
    """)
    assert "agent-thread-approved" not in out["html"], (
        "an approval survived an event that made no claim about one"
    )
    assert ">2<" in out["html"], "the round is a fact and is kept"


def test_the_badge_cannot_be_written_by_the_event(sandbox):
    html = _card(sandbox, {"tool": "bash", "state": "done", "ok": True,
                           "approved": '"><img src=x onerror=alert(1)>'})
    assert "<img" not in html and "onerror" not in html


# ── the wire ──────────────────────────────────────────────────────────────────


def _events(generator):
    async def _drain():
        return [chunk async for chunk in generator]

    events = []
    for chunk in asyncio.run(_drain()):
        if not chunk.startswith("data: ") or chunk.startswith("data: [DONE]"):
            continue
        try:
            events.append(json.loads(chunk[6:]))
        except json.JSONDecodeError:
            pass
    return events


def _patch(monkeypatch, model_replies, *, result=None, progress=()):
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    replies = iter(model_replies)

    async def fake_stream(*a, **k):
        yield f"data: {json.dumps({'delta': next(replies, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *a, **k):
        cb = k.get("progress_cb")
        if cb is not None:
            for payload in progress:
                await cb(dict(payload))
        return (block.tool_type, dict(result or {"output": "ok", "exit_code": 0}))

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute, raising=False)


def _of_type(events, event_type):
    return [e for e in events if e.get("type") == event_type]


def _persisted(events):
    return next(e for e in events if e.get("type") == "metrics")["data"].get("tool_events") or []


# The dispatcher's own refusal shape, copied off `src/tool_execution.py`. Every
# one of its exact-approval refusals returns this pair, and every one of them
# reaches `approved_result` after the card is already on screen.
BLOCKED = {
    "error": "The exact-action approval did not match this tool request.",
    "exit_code": 1,
    "blocked": True,
    "policy": "exact_tool_approval",
}


def _approved_run(monkeypatch, *, workspace=None, result=None, progress=()):
    store = ToolApprovalStore()
    pending = store.create(
        owner="alice", session_id="approved-badge", origin_run_id="run-1",
        tool_name="bash", content="printf hi", workspace=None,
        external_untrusted_context_seen=True, requested_round=2,
        capabilities=capabilities_for_action("bash", "printf hi"),
    )
    grant = store.consume(pending.approval_id, decision="approve",
                          owner="alice", session_id="approved-badge")
    assert grant is not None
    _patch(monkeypatch, ["Ran it."], result=result, progress=progress)
    return _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "yes, go ahead"}],
            max_rounds=1, owner="alice", session_id="approved-badge",
            workspace=workspace,
            relevant_tools=set(grant.pending.selected_tools),
            exact_approval=grant,
        )
    )


def test_an_action_that_ran_under_the_approval_is_badged_on_every_event(monkeypatch):
    events = _approved_run(monkeypatch)
    assert _of_type(events, "tool_start")[0]["approved"] is True
    assert _of_type(events, "tool_output")[0]["approved"] is True
    assert _persisted(events)[0]["approved"] is True


def test_a_dispatcher_refusal_withdraws_the_claim(monkeypatch):
    # `approval_matches` passed, the card went up saying approved, and the
    # dispatcher then refused. Before this row the result card still said
    # `approved: true` — a badge asserting the user authorised something that
    # never ran.
    events = _approved_run(monkeypatch, result=BLOCKED)
    assert _of_type(events, "tool_start")[0]["approved"] is True, (
        "the start event reports what was believed then, and that is honest"
    )
    assert _of_type(events, "tool_output")[0]["approved"] is False
    assert _persisted(events)[0]["approved"] is False


def test_a_binding_that_does_not_match_this_run_is_never_badged(monkeypatch):
    # The grant was sealed against no workspace and this run has one, so the
    # replay's own pre-check refuses before the dispatcher is reached: no start
    # event at all, and a result card that claims nothing.
    events = _approved_run(monkeypatch, workspace="/a/different/workspace",
                           result=BLOCKED)
    assert _of_type(events, "tool_start") == []
    output = _of_type(events, "tool_output")[0]
    assert output["approved"] is False
    assert output["command"] == ""
    assert _persisted(events)[0]["approved"] is False


def test_a_mismatched_binding_is_not_badged_even_when_the_tool_reports_success(monkeypatch):
    # The two gates are independent and the emit side must not lean on the
    # dispatcher to say no for it. In production a mismatched grant is blocked,
    # so a result that is *not* blocked can only mean the dispatcher was
    # bypassed, replaced, or changed — precisely when a card must not start
    # claiming the user authorised something the replay itself refused to show.
    events = _approved_run(monkeypatch, workspace="/a/different/workspace")
    output = _of_type(events, "tool_output")[0]
    assert output["approved"] is False
    assert output["command"] == "", (
        "the replay showed an action whose binding it had already refused"
    )
    assert _persisted(events)[0]["approved"] is False


def test_progress_on_a_refused_action_claims_nothing(monkeypatch):
    # The progress relay sits *outside* the `approval_matches` guard that stops
    # the start event, so it is the one event on this path that can contradict
    # the branch above it.
    events = _approved_run(monkeypatch, workspace="/a/different/workspace",
                           result=BLOCKED, progress=[{"message": "working"}])
    progress = _of_type(events, "tool_progress")
    assert progress, "the progress relay produced nothing to check"
    assert all(e["approved"] is False for e in progress)


def test_progress_on_an_authorised_action_says_so(monkeypatch):
    events = _approved_run(monkeypatch, progress=[{"message": "working"}])
    progress = _of_type(events, "tool_progress")
    assert progress and all(e["approved"] is True for e in progress)


def test_a_routine_call_carries_no_approval_claim_at_all(monkeypatch):
    # Absence is what "routine" means on this wire. A `false` on every ordinary
    # card would be a second way of saying nothing, and the badge reads `true`.
    _patch(monkeypatch, ["```bash\nprintf hi\n```"])
    events = _events(
        agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "do the thing"}],
            max_rounds=2, relevant_tools={"bash"},
        )
    )
    assert "approved" not in _of_type(events, "tool_start")[0]
    assert "approved" not in _of_type(events, "tool_output")[0]
    assert "approved" not in _persisted(events)[0]


# ── the callers ───────────────────────────────────────────────────────────────


def _calls(text: str) -> list[str]:
    calls, rest = [], text
    while "applyAgentThreadNode(" in rest:
        i = rest.index("applyAgentThreadNode(")
        depth, j = 0, i + len("applyAgentThreadNode")
        while j < len(rest):
            if rest[j] == "(":
                depth += 1
            elif rest[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        calls.append(rest[i:j + 1])
        rest = rest[j + 1:]
    return calls


@pytest.mark.parametrize("rel", [
    "static/js/chat.js", "static/js/chatRenderer.js", "static/js/compare/stream.js",
])
def test_every_card_built_from_an_event_is_handed_its_approval(rel):
    for call in _calls((_REPO / rel).read_text(encoding="utf-8")):
        if re.search(r"\b\w+CardOptions\(", call):
            # Options from a named builder: the builder is a pure function with
            # its own tests, and nobody approves a verdict or a refusal anyway.
            continue
        if "tool: ''" in call or 'tool: ""' in call:
            continue  # the document writer's card, which nobody approves
        assert "approved:" in call, (
            f"{rel} builds a card from an event without passing its approval: {call}"
        )
        value = call.split("approved:", 1)[1].split(",")[0].strip(" \t\r\n});")
        assert value not in {"true", "false"}, (
            f"{rel} hardcodes approved={value!r}; it must come from the event"
        )
