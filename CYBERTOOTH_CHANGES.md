# Cybertooth fork - modifications

Private customization of Odysseus (https://github.com/pewdiepie-archdaemon/odysseus),
licensed under AGPL-3.0. Upstream LICENSE and attribution retained; this file tracks local changes.

## Changes

### 1. Disable false-positive repetition guard (src/llm_core.py)
Odysseus' `_DegenerateStreamGuard` 4-gram phrase-loop detector false-flagged legitimately
templated output (repeated HTML/CSS blocks, chart bars) and aborted valid generations with a 502.
Gated the phrase-loop sub-check behind `ODYSSEUS_PHRASE_LOOP_MIN` (default 0 = off). The
single-token-collapse guard ("Var Var Var...") is retained.

### 2. Guardrail caps conditional on local vs cloud inference
New: src/runtime_limits.py | Modified: src/agent_loop.py, src/tool_utils.py

When the active model endpoint is LOCAL / self-hosted (LM Studio, Ollama, localhost,
host.docker.internal, LAN IPs) guardrail caps are lifted so long autonomous runs are not
artificially stopped. When the endpoint is a CLOUD provider (OpenAI, Anthropic, OpenRouter, ...)
the platform's default caps apply. Detection reuses the existing `_is_local_openai_compat_url()`;
per-request state via a contextvar.

Lifted for local:
- Max agent rounds:            50    -> 100,000
- Per-round stream timeout:    300s  -> 86,400s (also fixes the derived wall-clock deadline)
- Tool-output truncation (bash/python/grep/native results via _truncate): disabled

Env overrides:
- ODYSSEUS_UNLIMITED_LOCAL=0   keep caps even for local inference
- ODYSSEUS_FORCE_UNLIMITED=1   lift caps for ALL endpoints (use with care)

Deliberately NOT lifted (follow-ups): web_fetch byte caps, read_file MAX_READ_CHARS,
per-response max_tokens, and the input-token context budget (kept - it prevents the
context-overflow that caused earlier HTTP 500s on local models).
