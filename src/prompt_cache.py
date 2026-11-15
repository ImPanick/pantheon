# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2132`. Provider prompt-cache hints, in one place.

The owner, 2026-11-15, on the cloud caching hints: *"we need to rework the
cloud hints entirely that can get VERY expensive, VERY fast... massive waste
of tokens."* Measured on `fix/agent-lean-turn` before this module:

  * **Anthropic** got two breakpoints, the last tool and the system prompt.
    Nothing marked the conversation, so every agent round paid full price for
    the whole history again, tool results included, though all of it but the
    newest step had been sent seconds before.
  * **OpenAI** got no `prompt_cache_key`, so a conversation's requests were
    routed without a hint that they share a prefix.
  * **OpenRouter** got nothing, so a Claude or Gemini model reached through it
    cached nothing at all (OpenRouter passes `cache_control` through only when
    the request carries it; its OpenAI, DeepSeek and Grok models cache by
    themselves).

What this does, per provider. A breakpoint marks the end of a prefix the
provider stores for a few minutes; the next request that starts with the same
bytes reads it at the cache rate instead of the input rate.

  * Anthropic and OpenRouter's Claude models: the tools, the system prompt,
    the person's latest message and the end of the request. Each round writes
    the cache through its own end, and the next round reads all of it back and
    pays full price only for the new step. Four is Anthropic's limit.
  * OpenRouter's Gemini models: the end of the request (Gemini reads one).
  * OpenAI (`api.openai.com`, Chat Completions and Responses): a
    `prompt_cache_key` derived from the conversation, never the conversation id
    itself.

A request that is not reused (one message and no tools: a title, a one-word
check) gets no conversation breakpoint, because writing a cache costs more
than reading the input once. Nothing here changes a message's text, so a
request is byte-for-byte the request it was, plus the markers.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

ANTHROPIC_MAX_BREAKPOINTS = 4
_EPHEMERAL = {"type": "ephemeral"}


def _host(url: str) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def _host_is(url: str, domain: str) -> bool:
    h = _host(url)
    return h == domain or h.endswith("." + domain)


def _is_reused(messages: List[Dict[str, Any]], tools) -> bool:
    """A request whose prefix the next one will start with: an agent step
    (tools) or a conversation (anything past a single message)."""
    convo = [m for m in messages or [] if isinstance(m, dict) and m.get("role") != "system"]
    return bool(tools) or len(convo) >= 2


def _as_blocks(content: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else None
    if isinstance(content, list) and content and all(isinstance(b, dict) for b in content):
        return [dict(b) for b in content]
    return None


def _mark_last_block(message: Dict[str, Any]) -> bool:
    """Put a breakpoint on a message's last content block. False when the
    message has nothing to mark (no content)."""
    blocks = _as_blocks(message.get("content"))
    if not blocks:
        return False
    blocks[-1]["cache_control"] = dict(_EPHEMERAL)
    message["content"] = blocks
    return True


def _count_breakpoints(payload: Dict[str, Any]) -> int:
    n = 0
    for t in payload.get("tools") or []:
        if isinstance(t, dict) and "cache_control" in t:
            n += 1
    system = payload.get("system")
    if isinstance(system, list):
        n += sum(1 for b in system if isinstance(b, dict) and "cache_control" in b)
    for m in payload.get("messages") or []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list):
            n += sum(1 for b in content if isinstance(b, dict) and "cache_control" in b)
    return n


def _is_persons_message(message: Dict[str, Any]) -> bool:
    """A user turn that carries words, not a tool result (Anthropic carries
    tool results as user messages of `tool_result` blocks)."""
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    content = message.get("content")
    if isinstance(content, list):
        return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return bool(content)


def apply_anthropic(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Conversation breakpoints on an Anthropic Messages payload, in place.

    The tools and system breakpoints are `_build_anthropic_payload`'s; this
    adds the person's latest message and the end of the request when the
    request will be reused, never more than `ANTHROPIC_MAX_BREAKPOINTS`.
    """
    messages = payload.get("messages") or []
    if not messages or not _is_reused(messages, payload.get("tools")):
        return payload
    room = ANTHROPIC_MAX_BREAKPOINTS - _count_breakpoints(payload)
    if room <= 0:
        return payload
    # One shape for every message, string or not, so a message reads the same
    # bytes in the round that marked it and in every round after.
    for m in messages:
        if isinstance(m, dict) and isinstance(m.get("content"), str):
            blocks = _as_blocks(m["content"])
            if blocks:
                m["content"] = blocks
    last = len(messages) - 1
    if _mark_last_block(messages[last]):
        room -= 1
    if room <= 0 or _is_persons_message(messages[last]):
        return payload
    for i in range(last - 1, -1, -1):
        if _is_persons_message(messages[i]):
            _mark_last_block(messages[i])
            break
    return payload


def _openrouter_family(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("anthropic/") or "/claude" in m or m.startswith("claude"):
        return "anthropic"
    if m.startswith("google/gemini") or m.startswith("gemini"):
        return "gemini"
    return ""


def apply_openrouter(payload: Dict[str, Any], model: str) -> Dict[str, Any]:
    """`cache_control` in the content parts of an OpenAI-shaped payload sent
    to OpenRouter, for the model families that need it marked, in place."""
    family = _openrouter_family(model)
    messages = payload.get("messages") or []
    if not family or not messages or not _is_reused(messages, payload.get("tools")):
        return payload
    for m in messages:
        if (isinstance(m, dict) and m.get("role") in ("system", "user", "assistant")
                and isinstance(m.get("content"), str)):
            blocks = _as_blocks(m["content"])
            if blocks:
                m["content"] = blocks
    if family == "gemini":
        for m in reversed(messages):
            if m.get("role") in ("user", "assistant") and _as_blocks(m.get("content")):
                _mark_last_block(m)
                break
        return payload
    # Claude through OpenRouter: the system prompt, then the latest message
    # that carries words. A `tool` message is left unmarked: OpenRouter's
    # documented parts are on user, assistant and system messages, and a hint
    # must never be the reason a request is refused.
    marks = 0
    if messages[0].get("role") == "system" and _mark_last_block(messages[0]):
        marks += 1
    for i in range(len(messages) - 1, 0, -1):
        m = messages[i]
        if m.get("role") in ("user", "assistant") and _as_blocks(m.get("content")):
            if marks < ANTHROPIC_MAX_BREAKPOINTS:
                _mark_last_block(m)
            break
    return payload


def openai_cache_key(session_id: Optional[str]) -> Optional[str]:
    """A stable, opaque key for one conversation. The conversation id itself
    never leaves the machine."""
    if not session_id:
        return None
    digest = hashlib.sha256(f"pantheon:{session_id}".encode("utf-8")).hexdigest()
    return f"pantheon-{digest[:32]}"


def apply_openai(payload: Dict[str, Any], session_id: Optional[str]) -> Dict[str, Any]:
    key = openai_cache_key(session_id)
    if key:
        payload.setdefault("prompt_cache_key", key)
    return payload


def apply(payload: Dict[str, Any], *, provider: str, url: str, model: str,
          session_id: Optional[str] = None) -> Dict[str, Any]:
    """The one entry point every request path calls after building its payload."""
    try:
        if provider == "anthropic":
            return apply_anthropic(payload)
        if provider == "openrouter" or _host_is(url, "openrouter.ai"):
            return apply_openrouter(payload, model)
        if provider == "openai" and _host_is(url, "api.openai.com"):
            return apply_openai(payload, session_id)
    except Exception:  # a hint must never cost the request
        return payload
    return payload
