# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reasoning effort: how hard a thinking model is asked to think.

The composer offers one ladder for every model — Low, Medium, High, Extra,
Max — plus Auto (the model's own default, nothing sent). This module says
whether the selected model has any way to take a level (`effort_support`),
and turns a level into what that model's server actually reads
(`apply_to_payload`, `apply_to_messages`).

Each model family has its own switch, so each level is mapped per family:

* Claude (Anthropic API): ``output_config.effort`` — low / medium / high /
  xhigh / max, where the model takes them (Opus 4.5+, Sonnet 4.6+, Haiku 5.5+,
  Fable / Mythos). Levels a model lacks fall to the nearest it has.
* OpenAI reasoning models (o-series, gpt-5) on api.openai.com, OpenRouter, the
  ChatGPT subscription and Gemini's OpenAI-compatible door:
  ``reasoning_effort`` / ``reasoning.effort`` — low / medium / high.
* gpt-oss on any server (LM Studio, Ollama, vLLM, llama.cpp, Groq):
  ``reasoning_effort`` low / medium / high, or Ollama's ``think`` level.
* Mistral's thinking models: ``reasoning_effort``.
* Qwen3 hybrid models (the ones with a thinking switch): thinking turned on
  (``enable_thinking``, Ollama ``think``, and the ``/think`` soft switch) plus a
  written effort instruction, since the switch has no depth setting.
* Every other thinking model (QwQ, DeepSeek R1, MiniMax, Gemma, Magistral off
  Mistral's API, ...): a written effort instruction in the system prompt.

Where a model's own switch tops out below the chosen level (gpt-oss at Max,
say) the highest native value is sent *and* the written instruction is added,
so Extra and Max still ask for more than High. That instruction is the same
idea as Claude Code's "ultrathink" keyword: words that ask the model to think
longer. Typing ``ultrathink`` in a message runs that one turn at Max
(`turn_level`).

A level reaches the request through a context variable set for one chat turn
(`turn_scope`), so the many layers between the route and `stream_llm` do not
each carry a new argument; `stream_llm` reads it for foreground calls only.
"""

from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional

AUTO = "auto"
LEVELS = ("low", "medium", "high", "extra", "max")
LEVEL_LABELS = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "extra": "Extra",
    "max": "Max",
}
_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}

_turn_level: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pantheon_reasoning_effort", default=AUTO
)


def normalize_level(raw: object) -> str:
    """A level from a request, or `AUTO` for anything unknown or empty."""
    value = str(raw or "").strip().lower()
    aliases = {"med": "medium", "xhigh": "extra", "extra-high": "extra",
               "extra_high": "extra", "maximum": "max", "default": AUTO}
    value = aliases.get(value, value)
    return value if value in LEVELS else AUTO


_ULTRATHINK = re.compile(r"(?<![\w-])ultrathink(?![\w-])", re.IGNORECASE)


def turn_level(chosen: object, message: object) -> str:
    """The level a turn runs at: Max when the message says ``ultrathink``,
    else the composer's choice."""
    if isinstance(message, str) and _ULTRATHINK.search(message):
        return "max"
    return normalize_level(chosen)


def current_level() -> str:
    return _turn_level.get()


@contextmanager
def turn_scope(level: object) -> Iterator[None]:
    token = _turn_level.set(normalize_level(level))
    try:
        yield
    finally:
        try:
            _turn_level.reset(token)
        except ValueError:
            # Reset from another context (a generator closed elsewhere): the
            # context the value was set in is going away with its task.
            pass


# ── which family a model is ────────────────────────────────────────────────

_CLAUDE_RE = re.compile(
    r"(?<![a-z])(opus|sonnet|haiku)[-_]?(\d{1,2})(?!\d)(?:[-_.](\d{1,2})(?!\d))?"
)
_ALL_FIVE = ("low", "medium", "high", "xhigh", "max")


def _claude_native(model: str) -> Optional[Dict[str, str]]:
    m = (model or "").lower()
    if "fable" in m or "mythos" in m:
        values = _ALL_FIVE
    else:
        match = _CLAUDE_RE.search(m)
        if not match:
            return None
        tier = match.group(1)
        version = (int(match.group(2)), int(match.group(3) or 0))
        if tier == "opus" and version >= (4, 7) or tier == "sonnet" and version >= (5, 0) \
                or tier == "haiku" and version >= (5, 5):
            values = _ALL_FIVE
        elif tier in ("opus", "sonnet") and version == (4, 6):
            values = ("low", "medium", "high", "max")
        elif tier == "opus" and version == (4, 5):
            values = ("low", "medium", "high")
        else:
            return None
    native = {"low": "low", "medium": "medium", "high": "high"}
    native["extra"] = "xhigh" if "xhigh" in values else "high"
    native["max"] = "max" if "max" in values else "high"
    return native


_OPENAI_REASONING_RE = re.compile(r"^(?:openai/)?(?:o\d(?:[-_].*)?|gpt-5(?:[.\-_:].*)?)$")
_THREE = {"low": "low", "medium": "medium", "high": "high", "extra": "high", "max": "high"}


def _is_gpt_oss(model: str) -> bool:
    return "gpt-oss" in (model or "").lower()


def _is_qwen3_hybrid(model: str) -> bool:
    """Qwen3 models with a thinking on/off switch. Coder and the 2507
    Instruct / Thinking releases have none (one never thinks, one always)."""
    m = (model or "").lower()
    if "qwen3" not in m:
        return False
    return not any(tag in m for tag in ("coder", "instruct", "thinking", "-vl", "embed", "rerank"))


_ALWAYS_THINKING_HINTS = (
    "qwq", "deepseek-r1", "deepseek-reasoner", "r1-distill", "minimax", "m2-reap",
    "gemma", "stepfun", "step-3", "step3", "magistral", "-thinking", "_thinking",
    "thinking-", "reasoner", "reasoning", "phi-4-reasoning", "nemotron",
    "exaone-deep", "hunyuan-a13b", "glm-4.5", "glm-4.6", "glm-z1", "seed-oss",
    "kimi-k2-thinking", "deepseek-v3.1", "deepseek-v3.2", "deepseek-v4",
    "qwen3", "mistral-small", "mistral-medium",
)


def _thinks_without_a_switch(model: str) -> bool:
    m = (model or "").lower()
    if "coder" in m and "qwen3" in m:
        return False          # Qwen3-Coder never thinks
    if "qwen3" in m and "instruct" in m:
        return False          # Qwen3 2507 Instruct never thinks
    return any(h in m for h in _ALWAYS_THINKING_HINTS)


def _provider(url: str) -> str:
    from src.llm_core import _detect_provider
    return _detect_provider(url or "")


def _host(url: str, *domains: str) -> bool:
    from src.llm_core import _host_match
    return _host_match(url or "", *domains)


def mechanism(url: str, model: str) -> Optional[str]:
    """Which switch this model on this server reads, or None for none."""
    if not model:
        return None
    provider = _provider(url)
    m = model.lower()
    if provider == "anthropic":
        return "anthropic" if _claude_native(model) else None
    if _is_gpt_oss(model):
        return "ollama_think_level" if provider == "ollama" else "openai_reasoning_effort"
    if provider in ("openai", "chatgpt-subscription", "openrouter") and \
            _OPENAI_REASONING_RE.match(m.split("/", 1)[-1] if provider == "openrouter" else m):
        if provider == "chatgpt-subscription":
            return "responses_reasoning"
        if provider == "openrouter":
            return "openrouter_reasoning"
        # api.openai.com, or a proxy (Azure, LiteLLM) answering under an
        # OpenAI model name: the same field is the one it forwards.
        return "openai_reasoning_effort"
    if _host(url, "googleapis.com") and ("gemini-2.5" in m or "gemini-3" in m):
        return "openai_reasoning_effort"
    if provider == "openrouter" and _thinks_without_a_switch(model):
        return "openrouter_reasoning"
    if provider == "mistral" and ("magistral" in m or "mistral-small" in m or "mistral-medium" in m):
        return "mistral_reasoning_effort"
    if _is_qwen3_hybrid(model):
        return "qwen3_switch"
    if _thinks_without_a_switch(model):
        return "instruction"
    return None


def _native_values(mech: str, model: str) -> Dict[str, Optional[str]]:
    """What each level sends natively; None means instruction only."""
    if mech == "anthropic":
        return dict(_claude_native(model) or {})
    if mech in ("openai_reasoning_effort", "ollama_think_level", "responses_reasoning",
                "openrouter_reasoning", "mistral_reasoning_effort"):
        return dict(_THREE)
    return {lvl: None for lvl in LEVELS}


def _needs_instruction(mech: str, level: str, native: Optional[str]) -> bool:
    """Words are added where the model's switch can't say the level itself."""
    if mech == "anthropic":
        return False
    if native is None:
        return level != "medium"
    # A three-step switch carries Low–High; Extra and Max also get the words.
    return _RANK[level] > _RANK["high"]


def effort_support(url: str, model: str) -> Dict[str, object]:
    """What the composer shows for this model: whether to show the selector
    and, per level, how it reaches the model (said to the person on hover)."""
    mech = mechanism(url, model)
    if not mech:
        return {"supported": False, "levels": [], "mechanism": None}
    native = _native_values(mech, model)
    levels = []
    for lvl in LEVELS:
        value = native.get(lvl)
        words = _needs_instruction(mech, lvl, value)
        if mech == "qwen3_switch":
            how = ("Thinking switched on." if lvl == "medium"
                   else "Thinking switched on, plus a note on how hard to think.")
        elif value and words:
            how = f"Model set to {value} (its highest), plus a note to think harder."
        elif value:
            how = f"Model set to {value}."
        elif lvl == "medium":
            how = "The model's usual depth."
        else:
            how = "A note in the prompt; this model has no setting of its own."
        levels.append({"id": lvl, "label": LEVEL_LABELS[lvl], "native": value,
                       "instruction": words, "how": how})
    return {"supported": True, "mechanism": mech, "levels": levels}


# ── what is sent ──────────────────────────────────────────────────────────

_INSTRUCTIONS = {
    "low": ("Reasoning effort: low. Think only as much as the task needs and "
            "prefer a quick, direct answer."),
    "medium": "",
    "high": ("Reasoning effort: high. Think the problem through carefully and "
             "check your work before you answer."),
    "extra": ("Reasoning effort: extra high. Reason step by step in depth before "
              "answering: consider more than one approach, look for edge cases "
              "and mistakes, and verify your conclusion."),
    "max": ("Reasoning effort: maximum. Take as long as you need. Reason "
            "exhaustively before answering: break the problem down, consider "
            "every plausible approach, test your reasoning against edge cases, "
            "and double-check each step before giving your final answer."),
}


def instruction_for(level: str) -> str:
    return _INSTRUCTIONS.get(level, "")


def apply_to_messages(messages: List[Dict], url: str, model: str, level: str) -> List[Dict]:
    """The messages with this level's written instruction (and Qwen3's
    ``/think`` switch) added to the system prompt. Returns a new list."""
    if level not in LEVELS:
        return messages
    mech = mechanism(url, model)
    if not mech:
        return messages
    native = _native_values(mech, model).get(level)
    parts = []
    if mech == "qwen3_switch":
        parts.append("/think")
    if _needs_instruction(mech, level, native):
        text = instruction_for(level)
        if text:
            parts.append(text)
    if not parts:
        return messages
    addition = "\n\n".join(parts)
    out = list(messages or [])
    if out and out[0].get("role") == "system" and isinstance(out[0].get("content"), str):
        first = dict(out[0])
        first["content"] = (first["content"].rstrip() + "\n\n" + addition).lstrip()
        out[0] = first
    else:
        out.insert(0, {"role": "system", "content": addition})
    return out


def apply_to_payload(payload: Dict, url: str, model: str, level: str) -> Dict:
    """Write the level's native field into an already-built request body."""
    if level not in LEVELS:
        return payload
    mech = mechanism(url, model)
    if not mech:
        return payload
    value = _native_values(mech, model).get(level)
    if mech == "anthropic" and value:
        cfg = dict(payload.get("output_config") or {})
        cfg["effort"] = value
        payload["output_config"] = cfg
    elif mech in ("openai_reasoning_effort", "mistral_reasoning_effort") and value:
        payload["reasoning_effort"] = value
    elif mech == "ollama_think_level" and value:
        payload["think"] = value
    elif mech == "responses_reasoning" and value:
        reasoning = dict(payload.get("reasoning") or {})
        reasoning["effort"] = value
        payload["reasoning"] = reasoning
    elif mech == "openrouter_reasoning" and value:
        reasoning = dict(payload.get("reasoning") or {})
        reasoning["effort"] = value
        payload["reasoning"] = reasoning
    elif mech == "qwen3_switch":
        _turn_thinking_on(payload, url)
    elif mech == "instruction":
        from src.llm_core import _is_ollama_native_url, _is_ollama_openai_compat_url
        # Ollama is told not to think on these by default (tool calls hid in
        # <think>); a person who picked a level asked for thinking.
        if _is_ollama_native_url(url) or _is_ollama_openai_compat_url(url):
            payload["think"] = True
    return payload


def _turn_thinking_on(payload: Dict, url: str) -> None:
    from src.llm_core import (
        _is_ollama_native_url,
        _is_ollama_openai_compat_url,
        _is_self_hosted_openai_compatible,
    )
    if _is_ollama_native_url(url) or _is_ollama_openai_compat_url(url):
        # Ollama's field; the detector is generous, and LM Studio or vLLM on
        # localhost ignore it, so the template switch below is sent too.
        payload["think"] = True
    if _is_self_hosted_openai_compatible(url) and not _is_ollama_native_url(url):
        kwargs = dict(payload.get("chat_template_kwargs") or {})
        kwargs["enable_thinking"] = True
        payload["chat_template_kwargs"] = kwargs
