# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1989` — a server that refuses native tool calls is asked again with written ones.

An endpoint nobody declared (`supports_tools` unset: the Settings form's
default, and what the Forge records for a vLLM launched with its Auto Tool
Choice box left off) is offered the tools (`B1301`: `tool_schema_offer` is
`both`). vLLM started without `--enable-auto-tool-choice` answers every request
that carries a `tools` array with HTTP 400, *'"auto" tool choice requires
--enable-auto-tool-choice and --tool-call-parser to be set'*, and the turn
ended on it before its first step. For a model whose name is on
`resolve_tool_transport`'s list (Qwen3, Gemma, Llama 3.x and more) the request
also carried the compact prompt, which tells the model not to write tool
syntax, so dropping the array alone would have left it no way to call a tool.

Now that refusal, before a word of the step, on a `both` route, asks the same
step again fenced: no `tools` key, the full prompt with the fenced syntax and
the fenced parser. The route stays fenced for the rest of the turn and the
chat says so once. A route declared native keeps the refusal as its error, as
does any other refusal. The shape is `B1281`'s for a refused picture. Upstream
Odysseus recovers the same refusal inside its fallback wrapper (`84aa9a91`);
its markers are the ones read here.

Driven through the real loop, the real fallback wrapper and the real request
factory; only the socket (`llm_core.stream_llm`) is replaced, by a server that
refuses any body with `tools` the way vLLM does, and the tool runner.
"""
import asyncio
import json

import pytest

import src.agent_tools  # noqa: F401  (break the agent_tools <-> tool_parsing import cycle)
import src.agent_loop as agent_loop
import src.llm_core as llm_core

URL = "http://127.0.0.1:8000/v1"   # vLLM's own default port
MODEL = "qwen3-8b"                 # on `resolve_tool_transport`'s list: the compact prompt
VLLM_REFUSAL = json.dumps({
    "object": "error", "type": "BadRequestError", "param": None, "code": 400,
    "message": '"auto" tool choice requires --enable-auto-tool-choice and '
               '--tool-call-parser to be set'})
CONTEXT_REFUSAL = json.dumps({
    "object": "error", "type": "BadRequestError", "param": None, "code": 400,
    "message": "This model's maximum context length is 8192 tokens."})
COMPACT = "Only the tool schemas provided by the API are available for this turn."
FENCED = "write a fenced code block with the tool name as the language tag"


def _error_chunk(status, body):
    """The chunk `_stream_llm_inner` yields for an answer that is not 200."""
    text = llm_core._format_upstream_error(status, body, URL + "/chat/completions", model=MODEL)
    return ("event: error\ndata: "
            + json.dumps({"status": status, "text": text, "raw": body[:500]}) + "\n\n")


def _drive(monkeypatch, *, declared=None, refusal=VLLM_REFUSAL):
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    # The endpoint row's `supports_tools`: None is the Settings form's default.
    monkeypatch.setattr(agent_loop, "_endpoint_declared_supports",
                        lambda url, model, owner=None, headers=None: declared)

    sent = []   # what each request that reached the socket carried

    async def socket(url, model, messages, *a, **k):
        prompt = "\n".join(m["content"] for m in messages
                           if m.get("role") == "system" and isinstance(m.get("content"), str))
        sent.append({"tools": bool(k.get("tools")), "prompt": prompt})
        if k.get("tools"):
            yield _error_chunk(400, refusal)
            return
        written = sum(1 for s in sent if not s["tools"])
        reply = "```bash\nnvidia-smi\n```" if written == 1 else "The GPU is idle."
        yield f"data: {json.dumps({'delta': reply})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(llm_core, "stream_llm", socket)

    ran = []

    async def run_tool(block, *a, **k):
        ran.append((block.tool_type, block.content.strip()))
        return block.tool_type, {"output": "GPU 0: idle", "exit_code": 0}

    monkeypatch.setattr(agent_loop, "execute_tool_block", run_tool)

    async def collect():
        return [c async for c in agent_loop.stream_agent_loop(
            URL, MODEL, [{"role": "user", "content": "Is the GPU busy?"}],
            max_rounds=3, relevant_tools={"bash"}, owner="alice", session_id="b1989")]

    events = []
    for chunk in asyncio.run(collect()):
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                events.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
        elif chunk.startswith("event: error"):
            events.append({"type": "error", "raw": chunk})
    return events, sent, ran


def _said(events):
    return "".join(e.get("delta", "") for e in events if isinstance(e.get("delta"), str))


def _errors(events):
    return [e for e in events if e.get("type") == "error"]


def test_the_refusal_is_told_apart_from_any_other_error():
    assert llm_core.tools_transport_refused(_error_chunk(400, VLLM_REFUSAL))
    # The same refusal in the error-object shape, and as a stream's own text.
    assert llm_core.tools_transport_refused(_error_chunk(400, json.dumps(
        {"error": json.loads(VLLM_REFUSAL)})))
    assert llm_core.tools_transport_refused("Tools are not supported for this model")
    assert llm_core.tools_transport_refused("function calling is not supported")
    assert not llm_core.tools_transport_refused(_error_chunk(400, CONTEXT_REFUSAL))
    assert not llm_core.tools_transport_refused(
        'event: error\ndata: {"status": 400, "text": "image input is not supported"}\n\n')
    assert not llm_core.tools_transport_refused("")
    assert not llm_core.tools_transport_refused(None)


def test_a_refused_step_is_asked_again_with_written_tool_calls(monkeypatch):
    events, sent, ran = _drive(monkeypatch)

    # Offered both channels, under the compact prompt; refused for the array.
    assert sent[0]["tools"] and COMPACT in sent[0]["prompt"]
    assert len(sent) >= 2, "the turn ended on the server's refusal"
    # The same step again: no array, the full prompt with the fenced syntax.
    assert not sent[1]["tools"]
    assert COMPACT not in sent[1]["prompt"] and FENCED in sent[1]["prompt"]
    # The written call ran, and every later request of the turn stayed fenced.
    assert ran == [("bash", "nvidia-smi")]
    assert [s["tools"] for s in sent] == [True, False, False]
    said = _said(events)
    assert said.count(agent_loop.TOOLS_REFUSED_NOTE) == 1
    assert "The GPU is idle." in said
    assert not _errors(events), "the refusal reached the chat as an error"
    assert not [e for e in events if e.get("type") == "agent_terminal"]
    # The asked-again step is the same step, not a step of its own.
    assert [e["round"] for e in events if e.get("type") == "tool_start"] == [1]


def test_only_a_route_nobody_declared_is_asked_again_and_only_for_that_refusal(monkeypatch):
    # Declared native: the refusal is the turn's error, as before.
    events, sent, ran = _drive(monkeypatch, declared=True)
    assert [s["tools"] for s in sent] == [True] and ran == []
    assert _errors(events)
    # Nobody declared, but the server refused something else: as before.
    events, sent, ran = _drive(monkeypatch, refusal=CONTEXT_REFUSAL)
    assert [s["tools"] for s in sent] == [True] and ran == []
    assert _errors(events)
    # Nobody declared and the server refused the array: asked again, fenced.
    events, sent, ran = _drive(monkeypatch)
    assert [s["tools"] for s in sent] == [True, False, False]
    assert ran == [("bash", "nvidia-smi")] and not _errors(events)
