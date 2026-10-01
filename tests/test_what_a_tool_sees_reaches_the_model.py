# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-04` — what a tool sees reaches the model that asked.

Before this row nothing reached a model as an image: a tool result's picture
(`images`, the envelope key `FORBIDDEN.md` protects) went to the page and the
model was handed text — and the text was the picture's base64, cut off at
8,000 characters by `format_tool_result`.

Everything here runs the shipped code. The real agent loop drives the real
`computer` tool against the real workstation daemon
(`tests/helpers/workstation_daemon.py`); a scripted model asks for one action
per round, and each round's request is read off the loop's own per-candidate
request builder — the thing `stream_llm_with_fallback` sends. That request then
goes through the real `llm_core.stream_llm` for each provider format the
codebase speaks, over a socket that records the body instead of sending it:

  * a model that can see gets the screenshot as an image part, after the tool
    result, in the OpenAI-compatible body, as an Anthropic `image` block, as
    native Ollama's `images`, as a Responses `input_image`, and with Copilot's
    vision header — a step Copilot still counts as agent-initiated;
  * a model that cannot see — or any model while an admin has vision switched
    off — gets a sentence saying it cannot see the screen and naming the text
    tools, and no image part anywhere;
  * over a twenty-step run the request never carries more than the newest
    three pictures, and the older ones are a line saying so;
  * the trim gate reserves room for each picture it is about to send;
  * a browser screenshot takes the same path, and its base64 no longer reaches
    the model as text.
"""
from __future__ import annotations

import asyncio
import base64
import json

import pytest

import src.agent_loop as agent_loop
import src.context_compactor as context_compactor
import src.llm_core as llm_core
import src.settings as settings_module
import src.tool_result_images as images
from src.tool_execution import format_tool_result
from src.model_context import estimate_tokens
from src.workstation_client import account_for
from test_the_agent_works_the_workstation_screen import PERMITTED, configure
from tests.helpers.workstation_daemon import running_workstation

SCREEN_URL_PREFIX = "data:image/png;base64,"


def _patch_loop(monkeypatch, *, vision_enabled=True):
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default,
                        raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    real = settings_module.get_setting
    monkeypatch.setattr(settings_module, "get_setting",
                        lambda key, default=None: vision_enabled if key == "vision_enabled"
                        else real(key, default))


def _native_call(round_num, args, name="computer"):
    return {"type": "tool_calls", "calls": [{"id": f"call_{round_num}", "name": name,
                                             "arguments": json.dumps(args)}]}


def run_loop(monkeypatch, model, actions, *, fenced=False, url="http://local.test/v1",
             vision_enabled=True, execute=None):
    """Drive the real loop: round N asks for `actions[N-1]`, the round after
    the last says "Done.". Returns every round's request messages, as built for
    the model that answers it, and the loop's events."""
    _patch_loop(monkeypatch, vision_enabled=vision_enabled)
    if execute is not None:
        monkeypatch.setattr(agent_loop, "execute_tool_block", execute, raising=False)
    requests = []

    async def fake_stream(candidates, messages, **kwargs):
        request = await kwargs["candidate_request_factory"](0, *candidates[0])
        requests.append(request["messages"])
        n = len(requests)
        if n <= len(actions):
            if fenced:
                text = "```computer\n" + json.dumps(actions[n - 1]) + "\n```"
                yield f"data: {json.dumps({'delta': text})}\n\n"
            else:
                name = actions[n - 1].pop("_tool", "computer")
                yield f"data: {json.dumps(_native_call(n, actions[n - 1], name))}\n\n"
        else:
            yield f"data: {json.dumps({'delta': 'Done.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            url, model, [{"role": "user", "content": "use the workstation"}],
            max_rounds=len(actions) + 1, owner=PERMITTED,
            relevant_tools={"computer"})]

    events = []
    for chunk in asyncio.run(drain()):
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                events.append(json.loads(chunk[6:]))
            except ValueError:
                pass
    return requests, events


@pytest.fixture
def station(tmp_path, monkeypatch):
    with running_workstation(tmp_path) as ws:
        configure(monkeypatch, ws)
        yield ws


def image_parts(messages):
    return [part for m in messages if isinstance(m.get("content"), list)
            for part in m["content"] if isinstance(part, dict) and part.get("type") == "image_url"]


def texts(messages):
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            out += [p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"]
    return "\n".join(out)


# ── a model that can see ─────────────────────────────────────────────────────

CLICK = {"action": "click", "x": 640, "y": 400}


def _click_request(monkeypatch, model="gpt-4o", **kwargs):
    requests, events = run_loop(monkeypatch, model, [dict(CLICK)], **kwargs)
    assert len(requests) == 2, "one round to click, one to answer"
    return requests[1], events


def test_a_vision_model_is_sent_the_screen_after_its_click(station, monkeypatch):
    request, _events = _click_request(monkeypatch)
    [part] = image_parts(request)
    url = part["image_url"]["url"]
    assert url.startswith(SCREEN_URL_PREFIX)
    raw = base64.b64decode(url[len(SCREEN_URL_PREFIX):])
    assert raw.startswith(b"\x89PNG")
    # It is the picture the daemon took after the click, not before it.
    screen = station.screen(account_for(PERMITTED))
    assert screen.actions == [{"action": "click", "x": 640, "y": 400}]
    # After the tool's own answer, where a person's attachment would be.
    roles = [m["role"] for m in request]
    tool_at = roles.index("tool")
    image_at = next(i for i, m in enumerate(request) if isinstance(m.get("content"), list)
                    and image_parts([m]))
    assert image_at == tool_at + 1 and request[image_at]["role"] == "user"
    assert "Screen after click at (640, 400)" in texts([request[image_at]])
    assert "iVBOR" not in request[tool_at]["content"], "the picture is not text any more"


def test_a_fenced_model_that_can_see_is_sent_it_too(station, monkeypatch):
    request, _events = _click_request(monkeypatch, model="llava:13b", fenced=True)
    assert len(image_parts(request)) == 1
    assert "iVBOR" not in texts(request)


class _Resp:
    status_code = 200

    async def aiter_lines(self):
        yield "data: [DONE]"

    async def aread(self):
        return b""


class _Ctx:
    async def __aenter__(self):
        return _Resp()

    async def __aexit__(self, *a):
        return False


class _Recorder:
    """`httpx.AsyncClient` for `stream_llm`: records the body and the headers."""

    def __init__(self):
        self.payload, self.headers = None, None

    def stream(self, method, url, **kw):
        self.payload, self.headers = kw.get("json") or {}, kw.get("headers") or {}
        return _Ctx()


def sent_body(monkeypatch, url, model, messages):
    recorder = _Recorder()
    monkeypatch.setattr(llm_core, "_get_http_client", lambda: recorder)
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda u: False)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *a, **k: None)
    monkeypatch.setattr(llm_core, "_clear_host_dead", lambda *a, **k: None)
    monkeypatch.setattr(llm_core, "get_context_length", lambda u, m: 32768)

    async def go():
        return [c async for c in llm_core.stream_llm(url, model, messages)]

    asyncio.run(go())
    assert recorder.payload is not None, "nothing was sent"
    return recorder


def _the_screen(request):
    [part] = image_parts(request)
    return part["image_url"]["url"][len(SCREEN_URL_PREFIX):]


def test_openai_compatible_body_carries_the_image_part_after_the_tool_result(station, monkeypatch):
    request, _events = _click_request(monkeypatch)
    body = sent_body(monkeypatch, "http://local.test/v1", "gpt-4o", request).payload
    msgs = body["messages"]
    tool_at = next(i for i, m in enumerate(msgs) if m.get("role") == "tool")
    follow = msgs[tool_at + 1]
    assert follow["role"] == "user"
    assert [p for p in follow["content"] if p.get("type") == "image_url"][0]["image_url"]["url"] \
        == SCREEN_URL_PREFIX + _the_screen(request)
    assert "metadata" not in follow, "Pantheon's own label never reaches a provider"


def test_anthropic_body_carries_an_image_block_after_the_tool_result(station, monkeypatch):
    request, _events = _click_request(monkeypatch, model="claude-sonnet-4-5")
    body = sent_body(monkeypatch, "https://api.anthropic.com/v1", "claude-sonnet-4-5",
                     request).payload
    blocks = [(i, b) for i, m in enumerate(body["messages"]) if isinstance(m["content"], list)
              for b in m["content"]]
    result_at = next(i for i, b in blocks if b.get("type") == "tool_result")
    image_at, image = next((i, b) for i, b in blocks if b.get("type") == "image")
    assert image_at > result_at
    assert image["source"] == {"type": "base64", "media_type": "image/png",
                               "data": _the_screen(request)}


def test_native_ollama_body_carries_the_images_array(station, monkeypatch):
    request, _events = _click_request(monkeypatch)
    body = sent_body(monkeypatch, "http://localhost:11434", "llava:13b", request).payload
    [with_image] = [m for m in body["messages"] if m.get("images")]
    assert with_image["images"] == [_the_screen(request)]
    assert "Screen after click at (640, 400)" in with_image["content"]


def test_chatgpt_subscription_body_carries_an_input_image(station, monkeypatch):
    request, _events = _click_request(monkeypatch)
    body = sent_body(monkeypatch, "https://chatgpt.com/backend-api/codex", "gpt-5",
                     request).payload
    parts = [p for item in body["input"] for p in item["content"]]
    [image] = [p for p in parts if p.get("type") == "input_image"]
    assert image["image_url"] == SCREEN_URL_PREFIX + _the_screen(request)


def test_copilot_is_told_the_request_carries_a_picture(station, monkeypatch):
    request, _events = _click_request(monkeypatch)
    sent = sent_body(monkeypatch, "https://api.githubcopilot.com", "gpt-4o", request)
    assert len(image_parts(sent.payload["messages"])) == 1
    assert sent.headers.get("Copilot-Vision-Request") == "true"
    # The picture is the tool's answer, not the person speaking: the step
    # stays agent-initiated for Copilot's request accounting, as it is with no
    # picture at all.
    assert sent.headers.get("x-initiator") == "agent"
    words = sent_body(monkeypatch, "https://api.githubcopilot.com", "gpt-4o",
                      [m for m in request if not images.is_images_message(m)])
    assert words.headers.get("x-initiator") == "agent"
    # Only the tool's picture: a person steering mid-run is still the person.
    steered = sent_body(monkeypatch, "https://api.githubcopilot.com", "gpt-4o",
                        [m for m in request if not images.is_images_message(m)]
                        + [{"role": "user", "content": [{"type": "text", "text": "stop"}]}])
    assert steered.headers.get("x-initiator") == "user"


# ── a model that cannot see ──────────────────────────────────────────────────

@pytest.mark.parametrize("model, vision_enabled, fenced", [
    ("deepseek-chat", True, False),        # native tools, no vision
    ("small-local-model", True, True),     # fenced, no vision
    ("gpt-4o", False, False),              # can see, and an admin switched vision off
], ids=["native-text-model", "fenced-text-model", "vision-switched-off"])
def test_a_model_that_cannot_see_is_told_so_in_words(station, monkeypatch, model,
                                                     vision_enabled, fenced):
    request, _events = _click_request(monkeypatch, model=model, fenced=fenced,
                                      vision_enabled=vision_enabled)
    assert image_parts(request) == []
    [said] = [m for m in request if images.NO_VISION_SENTENCE in str(m.get("content"))]
    assert isinstance(said["content"], str), "plain text for a text-only server"
    assert "Screen after click at (640, 400)" in said["content"]
    assert "`bash`" in said["content"] and "`read_file`" in said["content"]
    body = sent_body(monkeypatch, "http://local.test/v1", model, request).payload
    assert "image_url" not in json.dumps(body)
    assert images.NO_VISION_SENTENCE in json.dumps(body, ensure_ascii=False)


# ── a long session keeps only the newest few ────────────────────────────────

def test_twenty_steps_keep_only_the_newest_three_screens(station, monkeypatch):
    steps = [{"action": "wait", "ms": n} for n in range(1, 21)]
    requests, _events = run_loop(monkeypatch, "gpt-4o", steps)
    assert len(requests) == 21
    for n, request in enumerate(requests, start=1):
        assert len(image_parts(request)) == min(n - 1, images.KEEP_NEWEST_IMAGES), n
    last = requests[-1]
    # The three kept are the three newest, each beside its own caption.
    kept_captions = []
    for m in last:
        if not images.is_images_message(m) and not (isinstance(m.get("content"), list)
                                                     and image_parts([m])):
            continue
        content = m["content"]
        for i, part in enumerate(content):
            if isinstance(part, dict) and part.get("type") == "image_url":
                kept_captions.append(content[i - 1]["text"])
    assert [c.split(".")[0] for c in kept_captions] == [
        "Screen after wait 18 ms", "Screen after wait 19 ms", "Screen after wait 20 ms"]
    placeholder = images.OLDER_IMAGE_PLACEHOLDER.format(keep=images.KEEP_NEWEST_IMAGES)
    assert texts(last).count(placeholder) == 17
    # Every caption stays, so the model still reads what each older screen was.
    assert all(f"Screen after wait {n} ms" in texts(last) for n in range(1, 21))


def test_the_trim_gate_reserves_room_for_each_picture_it_sends(station, monkeypatch):
    reserves = []
    real = context_compactor.trim_for_context

    def recording(messages, budget, reserve_tokens=512):
        reserves.append((images.count_image_parts(messages), reserve_tokens))
        return real(messages, budget, reserve_tokens=reserve_tokens)

    monkeypatch.setattr(context_compactor, "trim_for_context", recording)
    steps = [{"action": "wait", "ms": n} for n in range(1, 6)]
    run_loop(monkeypatch, "gpt-4o", steps)
    base = [r for count, r in reserves if count == 0]
    assert base, "a round with no picture was trimmed too"
    for count, reserve in reserves:
        assert reserve == base[0] + count * images.IMAGE_TOKEN_RESERVE
    assert max(count for count, _ in reserves) == images.KEEP_NEWEST_IMAGES


def test_a_picture_is_not_counted_as_its_base64(station, monkeypatch):
    request, _events = _click_request(monkeypatch)
    b64 = _the_screen(request)
    assert len(b64) > 4_000
    as_text = [dict(m, content=texts([m])) if isinstance(m.get("content"), list) else m
               for m in request]
    # The image adds nothing to the estimate; its base64 would have added ~0.3/char.
    assert estimate_tokens(request) - estimate_tokens(as_text) < 50


# ── the browser's screenshot takes the same path ─────────────────────────────

BROWSER = "mcp__builtin_browser__browser_take_screenshot"


def test_a_browser_screenshot_reaches_the_model_as_a_picture_not_as_base64(station, monkeypatch):
    shot = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"browser-screenshot" * 400).decode()
    mcp_result = {"stdout": "[Screenshot captured (image/png)]", "stderr": "", "exit_code": 0,
                  "images": [{"data": shot, "mimeType": "image/png"}]}

    async def browser_execute(block, *args, **kwargs):
        assert block.tool_type == BROWSER
        return f"mcp: {BROWSER}", dict(mcp_result)

    requests, _events = run_loop(monkeypatch, "gpt-4o", [{"_tool": BROWSER}],
                                 execute=browser_execute)
    request = requests[1]
    [part] = image_parts(request)
    assert part["image_url"]["url"] == SCREEN_URL_PREFIX + shot
    [tool_text] = [m["content"] for m in request if m.get("role") == "tool"]
    assert shot[:200] not in tool_text and "iVBOR" not in tool_text
    assert "[Screenshot captured (image/png)]" in tool_text
    assert f"Picture from `{BROWSER}`" in texts(request)


def test_the_formatter_no_longer_writes_a_picture_into_the_text():
    shot = base64.b64encode(b"x" * 30_000).decode()
    text = format_tool_result("mcp: browser", {"stdout": "[Screenshot captured (image/png)]",
                                               "stderr": "", "exit_code": 0,
                                               "images": [{"data": shot, "mimeType": "image/png"}],
                                               "screenshot_caption": "Screen"})
    assert shot[:100] not in text and '"images"' not in text and "screenshot_caption" not in text
    assert "[Screenshot captured (image/png)]" in text


def test_what_the_screen_shows_is_marked_as_a_strangers_content():
    """A picture of an instruction is still content, not the person: the
    message carrying it is labelled untrusted and arms the gate exactly when
    the tool's own result does."""
    from src.tool_capabilities import external_untrusted_context_sources

    record = {"tool_name": "computer", "content": json.dumps({"action": "screenshot"}),
              "result": {"output": "Took a screenshot.", "exit_code": 0,
                         "images": [{"data": "aGVsbG8=", "mimeType": "image/png"}],
                         "screenshot_caption": "Screen"}}
    message = images.images_message([record])
    assert message["role"] == "user"
    assert external_untrusted_context_sources([message]) == ["tool result: computer"]
    blocked = dict(record, result=dict(record["result"], blocked=True))
    quiet = images.images_message([blocked])
    assert external_untrusted_context_sources([quiet]) == [], "a refused call armed nothing"
    assert images.images_message([dict(record, result={"output": "no picture"})]) is None


def test_an_approved_click_reaches_the_model_and_the_card_like_any_other(station, monkeypatch):
    """The approval card resumes into its own block of the loop (`P7-06`'s
    "replay pair"). A click a person allowed after the screen had been read
    runs there — and its picture must reach the model and the card the way an
    unasked one does, or approving an action would be the way to lose it."""
    from src.tool_approvals import ToolApprovalStore
    from src.tool_capabilities import capabilities_for_action

    content = json.dumps(CLICK)
    store = ToolApprovalStore()
    pending = store.create(
        owner=PERMITTED, session_id="session-1", origin_run_id="run-1", tool_name="computer",
        content=content, workspace=None, external_untrusted_context_seen=True,
        capabilities=capabilities_for_action("computer", content))
    grant = store.consume(pending.approval_id, decision="approve", owner=PERMITTED,
                          session_id="session-1")
    assert grant is not None
    _patch_loop(monkeypatch)
    requests = []

    async def fake_stream(candidates, messages, **kwargs):
        request = await kwargs["candidate_request_factory"](0, *candidates[0])
        requests.append(request["messages"])
        yield f"data: {json.dumps({'delta': 'Clicked it.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "gpt-4o", [{"role": "user", "content": "yes, go ahead"}],
            max_rounds=1, owner=PERMITTED, session_id="session-1", workspace=None,
            relevant_tools=set(pending.selected_tools), exact_approval=grant)]

    events = [json.loads(c[6:]) for c in asyncio.run(drain())
              if c.startswith("data: {")]
    assert station.screen(account_for(PERMITTED)).actions == [
        {"action": "click", "x": 640, "y": 400}]
    [live] = [e for e in events if e.get("type") == "tool_output" and e.get("approved")]
    assert live["screenshot"].startswith("data:image/jpeg;base64,")
    assert live["screenshot_caption"] == "Screen after click at (640, 400)"
    [saved] = [e for e in next(e for e in events if e.get("type") == "metrics")["data"]
               ["tool_events"] if e.get("approved")]
    assert saved["screenshot"] == live["screenshot"]
    assert saved["screenshot_caption"] == live["screenshot_caption"]
    assert len(image_parts(requests[0])) == 1, "the model that answers sees what it did"
