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

### 3. Phase 1 - finish local-unlimited surface
web_tools.py / outbound_fetch.py / filesystem_tools.py: web_search+web_fetch char truncation,
web-fetch byte caps (soft/hard + declared-length guard), and read_file char cap are lifted when
runtime_limits.unlimited() is true (local self-hosted). max_tokens (4096) also lifted to 1,000,000
for local, inside the Phase-0 block in agent_loop.py. Cloud endpoints keep every default.

### 4. Phase 2 - agent working memory (RAG add_text/search + guidance)
mcp_servers/rag_server.py: manage_rag gains two agent-callable actions - add_text (ingest arbitrary
text into the ChromaDB vector store) and search (semantic query). Owner resolved from injected arg or
ODYSSEUS_MCP_RAG_OWNER/ODYSSEUS_DOCUMENT_OWNER env (single-user box => ownerless/global, fine).
agent_loop.py: a "Working memory (long/large tasks)" rule added to BOTH _AGENT_RULES and
_API_AGENT_RULES (native function-calling path) - journal to manage_notes, offload big results to
manage_rag add_text/search instead of holding them in context; manage_memory only for durable USER
facts (no double-storage with auto-memory).

### 5. Phase 3 - local-inference probe auth
chat_helpers.py (_probe_auth_headers) + model_context.py (_endpoint_auth_headers): the /slots,
/v1/models and llama.cpp models probes now attach Authorization: Bearer <key> for a matching enabled
ModelEndpoint (empty dict when keyless => unchanged for keyless servers). routes/model_routes.py:
_ping_endpoint passes its in-scope headers to the Ollama reachability probe. Fixes the 401 spam from
LM Studio's API-token server. (Known follow-ups: two Ollama /api/tags fallbacks still keyless - benign.)
