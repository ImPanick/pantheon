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
  ODYSSEUS_UNLIMITED_LOCAL=0   -> keep caps even for local inference
  ODYSSEUS_FORCE_UNLIMITED=1   -> lift caps for ALL endpoints (use with care)
"""
import contextvars
import os

_local_mode = contextvars.ContextVar("odysseus_local_mode", default=False)


def _truthy(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off", "")


_LIFT_WHEN_LOCAL = _truthy("ODYSSEUS_UNLIMITED_LOCAL", "1")
_FORCE_UNLIMITED = _truthy("ODYSSEUS_FORCE_UNLIMITED", "0")


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
