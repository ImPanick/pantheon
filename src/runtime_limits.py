"""
Runtime guardrail gating (cybertooth custom fork).

Lifts guardrail caps when inference runs on LOCAL / self-hosted infrastructure
(the user's own GPU: LM Studio, Ollama, localhost, host.docker.internal, LAN IPs)
and keeps the platform's default caps when the active model is a CLOUD provider
(OpenAI, Anthropic, OpenRouter, etc.).

The agent loop sets per-request "local mode" from the active endpoint; truncation
and limit sites read `unlimited()` to decide whether to apply caps.

Imports nothing from the project (stdlib only), so it is safe to import anywhere,
including lazily from src.tool_utils (which forbids project imports to avoid cycles).

Env overrides:
  PANTHEON_UNLIMITED_LOCAL=0   -> keep caps even for local inference
  PANTHEON_FORCE_UNLIMITED=1   -> lift caps for ALL endpoints (use with care)
"""
import contextvars
import os

_local_mode = contextvars.ContextVar("pantheon_local_mode", default=False)


def _truthy(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off", "")


_LIFT_WHEN_LOCAL = _truthy("PANTHEON_UNLIMITED_LOCAL", "1")
_FORCE_UNLIMITED = _truthy("PANTHEON_FORCE_UNLIMITED", "0")


def set_local_mode(is_local: bool):
    """Record whether the active request targets local/self-hosted inference."""
    try:
        return _local_mode.set(bool(is_local))
    except Exception:
        return None


def unlimited() -> bool:
    """True when guardrail caps should be lifted for the current request."""
    if _FORCE_UNLIMITED:
        return True
    if not _LIFT_WHEN_LOCAL:
        return False
    try:
        return bool(_local_mode.get())
    except Exception:
        return False


def lift_cap(value: int, lifted: int, *, unlimited: bool, pinned: bool) -> int:
    """One cap's local-inference lift, as a rule rather than four inline ifs.

    `H08`. This was three copies of `if unlimited(): value = <bigger>` inside
    `stream_agent_loop`, and two of them raised a number the operator had
    entered in the settings UI — validated to 1..200 by the admin endpoint and
    re-clamped in `chat_routes` *with a comment about defending against
    hand-edits*, then overwritten here on the default deployment.

    `pinned` is the caller's answer to "did a person choose this value?" —
    `settings.setting_is_explicit` — and it is the whole fix: **lift a default
    nobody chose, honour a value somebody did**. The caller computes it because
    this module deliberately imports nothing from the project.

    A falsy `value` already means "no cap" and is returned untouched rather
    than being given one, and a value above `lifted` is never lowered: this
    only ever raises, which is what "lift" has to mean for the caller to be
    able to reason about it.
    """
    if not unlimited or pinned or not value:
        return value
    return max(value, lifted)
