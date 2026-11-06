# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenAI's Responses API, for the models that answer nowhere else.

`B1750`. Panick's first picture sent to OpenAI came back `404`. OpenAI answers
`/v1/chat/completions` with a 404 for a model that exists but is served only by
`/v1/responses` — the `-pro` models (`o1-pro`, `o3-pro`, `gpt-5-pro`,
`gpt-5.x-pro`), the deep-research models, `computer-use-preview` and the codex
line — with a body like *"This model is only supported in v1/responses and not
in v1/chat/completions."* Every OpenAI-hosted request went to chat completions,
so those models could not answer anything, text or picture; a picture is just
the first thing people reach for the strongest model with.

This module is the one place that knows the other API:

* :func:`uses_responses_api` — whether a request goes there: an api.openai.com
  endpoint and a model named as Responses-only, or one OpenAI has already
  answered so this run (:func:`learn_from_refusal`).
* :func:`build_payload` — Pantheon's chat-completions messages and tools in the
  Responses shape: system turns become ``instructions``, a picture becomes an
  ``input_image`` part, an assistant's tool calls become ``function_call``
  items and a tool's answer a ``function_call_output``.
* :func:`parse_response` / :class:`StreamTranslator` — the answer back in the
  events every other provider's path yields (``delta``, ``tool_calls``,
  ``usage``), so nothing above the transport knows which API answered.
"""
from __future__ import annotations

import json
import re
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

# Model ids OpenAI serves only through /v1/responses. Matched on the id with any
# `openai/` prefix removed. `-pro` is anchored on OpenAI's own families so a
# look-alike name on another host is never affected (this is only asked for
# api.openai.com anyway).
_RESPONSES_ONLY_RE = re.compile(
    r"^(?:"
    r"o1-pro|o3-pro|gpt-5(?:\.\d+)?-pro"            # the -pro reasoning models
    r"|o3-deep-research|o4-mini-deep-research"       # deep research
    r"|computer-use-preview"
    r"|codex-mini|gpt-5(?:\.\d+)?-codex"             # the codex line
    r")(?:$|[-_:.@].*)",
    re.I,
)

# Models OpenAI has told this process (by a 404 naming /v1/responses) that it
# serves only there — a new model needs no release of Pantheon to work.
_LEARNED: set = set()

_REFUSAL_RE = re.compile(r"v1/responses|responses api|only supported in", re.I)


def _bare(model: str) -> str:
    m = (model or "").strip()
    if m.lower().startswith("openai/"):
        m = m[len("openai/"):]
    return m


def is_openai_platform_url(url: str) -> bool:
    """True for OpenAI's own API host — not a proxy, not a look-alike."""
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except Exception:
        return False
    return host == "api.openai.com"


def is_responses_only_model(model: str) -> bool:
    bare = _bare(model)
    return bool(_RESPONSES_ONLY_RE.match(bare)) or bare.lower() in _LEARNED


def uses_responses_api(url: str, model: str) -> bool:
    """Whether a request for `model` at `url` must go to /v1/responses."""
    return is_openai_platform_url(url) and is_responses_only_model(model)


def learn_from_refusal(url: str, model: str, status: int, body) -> bool:
    """Record `model` as Responses-only when OpenAI's 404 says so; True if it did.

    Only a 404 from api.openai.com whose text names the Responses API counts, so
    an ordinary *model not found* is never mistaken for one."""
    if status != 404 or not is_openai_platform_url(url):
        return False
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if not _REFUSAL_RE.search(str(body or "")):
        return False
    bare = _bare(model).lower()
    if not bare or bare in _LEARNED:
        return False
    _LEARNED.add(bare)
    return True


def responses_url(url: str) -> str:
    """The /v1/responses URL beside a chat-completions (or base) URL."""
    base = (url or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/responses"):
        if base.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
            break
    parsed = urlparse(base)
    if not (parsed.path or "").strip("/"):
        base = base + "/v1"
    return base + "/responses"


# ── request ─────────────────────────────────────────────────────────────────

def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    out.append(part["text"])
                elif isinstance(part.get("content"), str):
                    out.append(part["content"])
            elif part:
                out.append(str(part))
        return "\n".join(out)
    return "" if content is None else str(content)


def _image_url_of(part: Dict) -> Optional[str]:
    if part.get("type") == "image_url":
        raw = part.get("image_url")
        url = raw.get("url") if isinstance(raw, dict) else raw
    elif part.get("type") == "input_image":
        url = part.get("image_url")
    else:
        return None
    return url if isinstance(url, str) and url else None


def _input_parts(content) -> List[Dict]:
    """A user turn's content as Responses input parts, pictures kept."""
    if not isinstance(content, list):
        text = _text_of(content)
        return [{"type": "input_text", "text": text}]
    parts: List[Dict] = []
    for part in content:
        if not isinstance(part, dict):
            if part:
                parts.append({"type": "input_text", "text": str(part)})
            continue
        url = _image_url_of(part)
        if url:
            image = {"type": "input_image", "image_url": url}
            detail = part.get("image_url", {}).get("detail") if isinstance(part.get("image_url"), dict) else None
            if detail:
                image["detail"] = detail
            parts.append(image)
        elif part.get("type") in ("text", "input_text") or isinstance(part.get("text"), str):
            parts.append({"type": "input_text", "text": part.get("text") or ""})
        elif part.get("type") == "input_audio":
            # The Responses API takes no recording part; the transcript, when
            # there is one, is already in the text beside it.
            continue
    return parts or [{"type": "input_text", "text": ""}]


def build_input(messages: Iterable[Dict]) -> Tuple[str, List[Dict]]:
    """`(instructions, input items)` for chat-completions `messages`."""
    instructions: List[str] = []
    items: List[Dict] = []
    for msg in messages or []:
        role = msg.get("role") or "user"
        content = msg.get("content")
        if role in ("system", "developer"):
            text = _text_of(content).strip()
            if text:
                instructions.append(text)
            continue
        if role == "tool":
            items.append({
                "type": "function_call_output",
                "call_id": msg.get("tool_call_id") or "",
                "output": _text_of(content),
            })
            continue
        if role == "assistant":
            text = _text_of(content)
            if text:
                items.append({"role": "assistant",
                              "content": [{"type": "output_text", "text": text}]})
            for tc in msg.get("tool_calls") or []:
                fn = (tc or {}).get("function") or {}
                args = fn.get("arguments")
                if not isinstance(args, str):
                    args = json.dumps(args or {})
                items.append({
                    "type": "function_call",
                    "call_id": tc.get("id") or "",
                    "name": fn.get("name") or "",
                    "arguments": args or "{}",
                })
            continue
        items.append({"role": "user", "content": _input_parts(content)})
    return "\n\n".join(instructions), items


def _tools(tools: Optional[List[Dict]]) -> List[Dict]:
    out = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") if t.get("type") == "function" else None
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        out.append({
            "type": "function",
            "name": fn["name"],
            "description": fn.get("description") or "",
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def build_payload(model: str, messages: List[Dict], max_tokens: Optional[int] = None, *,
                  stream: bool = False, tools: Optional[List[Dict]] = None,
                  tool_choice_none: bool = False) -> Dict:
    """A /v1/responses request body. No `temperature`: every model sent here
    is a reasoning model, and those refuse it."""
    instructions, items = build_input(messages)
    payload: Dict = {"model": model, "input": items, "store": False}
    if instructions:
        payload["instructions"] = instructions
    if stream:
        payload["stream"] = True
    if max_tokens and max_tokens > 0:
        payload["max_output_tokens"] = int(max_tokens)
    converted = _tools(tools)
    if converted:
        payload["tools"] = converted
    elif tool_choice_none and tools is not None:
        payload["tool_choice"] = "none"
    return payload


def finish_payload(payload: Dict, model: str) -> Dict:
    """Move a chat-completions reasoning field into the Responses shape.

    `src/reasoning_effort.py` writes `reasoning_effort` for api.openai.com; the
    Responses API names it `reasoning.effort`. The gpt-5 `-pro` models take
    only `high`, so any other level is left to the model's default."""
    effort = payload.pop("reasoning_effort", None)
    if effort:
        bare = _bare(model).lower()
        if re.match(r"^gpt-5(?:\.\d+)?-pro", bare) and effort != "high":
            return payload
        if effort == "none":
            return payload
        reasoning = dict(payload.get("reasoning") or {})
        reasoning["effort"] = effort
        payload["reasoning"] = reasoning
    return payload


# ── response ────────────────────────────────────────────────────────────────

def _usage(usage) -> Optional[Dict]:
    if not isinstance(usage, dict):
        return None
    return {
        "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0,
        "output_tokens": usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0,
    }


def parse_response(data: Dict) -> Tuple[str, List[Dict]]:
    """`(text, tool calls)` of a non-streamed Responses answer."""
    if not isinstance(data, dict):
        return "", []
    texts: List[str] = []
    calls: List[Dict] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") in ("output_text", "text"):
                    texts.append(part.get("text") or "")
        elif item.get("type") == "function_call":
            calls.append({"id": item.get("call_id") or item.get("id") or "",
                          "name": item.get("name") or "",
                          "arguments": item.get("arguments") or ""})
    text = "".join(texts)
    if not text and isinstance(data.get("output_text"), str):
        text = data["output_text"]
    return text, calls


def error_text(data) -> str:
    err = (data or {}).get("error") if isinstance(data, dict) else None
    if not err and isinstance(data, dict):
        err = (data.get("response") or {}).get("error")
    if isinstance(err, dict):
        return err.get("message") or err.get("code") or "OpenAI request failed"
    return str(err or "OpenAI request failed")


def _sse(payload: Dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


class StreamTranslator:
    """Responses SSE events in, Pantheon's stream events out.

    Feed it each decoded `data:` object with :meth:`feed`; it returns the events
    to yield and sets :attr:`done` once the response has finished (completed,
    incomplete or failed)."""

    def __init__(self) -> None:
        self.done = False
        self.model = ""
        self._calls: Dict[int, Dict] = {}

    def _call_events(self) -> List[str]:
        if not self._calls:
            return []
        calls = [self._calls[i] for i in sorted(self._calls)]
        return [_sse({"type": "tool_calls", "calls": calls})]

    def feed(self, data: Dict, event_name: str = "") -> List[str]:
        if not isinstance(data, dict):
            return []
        evt = data.get("type") or event_name
        response = data.get("response") if isinstance(data.get("response"), dict) else {}
        if response.get("model"):
            self.model = str(response["model"])
        out: List[str] = []
        if evt == "response.output_text.delta":
            delta = data.get("delta") or ""
            if delta:
                out.append(_sse({"delta": delta}))
        elif evt in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            delta = data.get("delta") or ""
            if delta:
                out.append(_sse({"delta": delta, "thinking": True}))
        elif evt == "response.output_item.added":
            item = data.get("item") or {}
            if item.get("type") == "function_call":
                idx = int(data.get("output_index", len(self._calls)))
                self._calls[idx] = {"id": item.get("call_id") or item.get("id") or "",
                                    "name": item.get("name") or "",
                                    "arguments": item.get("arguments") or ""}
        elif evt == "response.function_call_arguments.delta":
            idx = int(data.get("output_index", max(self._calls, default=0)))
            slot = self._calls.setdefault(idx, {"id": data.get("item_id") or "", "name": "", "arguments": ""})
            delta = data.get("delta") or ""
            slot["arguments"] += delta
            if delta and slot.get("name") in ("create_document", "update_document", "edit_document"):
                out.append(_sse({"type": "tool_call_delta", "index": idx,
                                 "name": slot["name"], "arg_delta": delta}))
        elif evt == "response.output_item.done":
            item = data.get("item") or {}
            if item.get("type") == "function_call":
                idx = int(data.get("output_index", len(self._calls)))
                slot = self._calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                slot["id"] = item.get("call_id") or slot["id"] or item.get("id") or ""
                slot["name"] = item.get("name") or slot["name"]
                if isinstance(item.get("arguments"), str):
                    slot["arguments"] = item["arguments"]
        elif evt in ("response.completed", "response.incomplete"):
            out.extend(self._call_events())
            usage = _usage(response.get("usage") or data.get("usage"))
            if usage:
                out.append(_sse({"type": "usage", "data": usage}))
            out.append("data: [DONE]\n\n")
            self.done = True
        elif evt in ("response.failed", "error"):
            status = 400
            err = data.get("error") or response.get("error") or {}
            if isinstance(err, dict):
                code = str(err.get("code") or "")
                if code in ("rate_limit_exceeded",):
                    status = 429
                elif code in ("server_error",):
                    status = 502
            out.append(f'event: error\ndata: {json.dumps({"status": status, "text": error_text(data) if data.get("error") else error_text({"error": err})})}\n\n')
            self.done = True
        return out
