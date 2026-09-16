# Cybertooth — the five changes this fork started as

Before Pantheon had a name it was a branch called `custom` on one machine, under the
working name **Cybertooth**, carrying five changes to
[Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) (AGPL-3.0). Those five are
the reason this repository exists, so they are written down here in the detail they were
written in at the time, and summarised for a reader in
[`CHANGELOG.md`](CHANGELOG.md) under *Before the fork was named*.

**Read this as dated history, not as documentation.** Every change below is still in the
product. Every *address* in it is not: the names and paths were written before the fork's
rename sweep, and five environment variables named here do not exist under those spellings
any more. Each one is corrected inline, dated, rather than quietly rewritten — a lineage
file that is silently kept current has stopped being lineage. For what this product does
today, read [`README.md`](README.md), [`docs/setup.md`](docs/setup.md) and
[`.env.example`](.env.example), which is the only complete list of the environment this
fork reads.

`scripts/pantheon-init.sh` excludes this file from the rename sweep on purpose, alongside
`LICENSE`, `NOTICE`, `CREDITS.md` and `CHANGELOG.md`: sweeping it would rewrite what this
was forked *from* into a claim about what it is now.

Every claim below was re-checked against the tree on **2026-09-16**. The corrections carry
that date.

## Changes

### 1. Disable false-positive repetition guard (src/llm_core.py)
Odysseus' `_DegenerateStreamGuard` 4-gram phrase-loop detector false-flagged legitimately
templated output (repeated HTML/CSS blocks, chart bars) and aborted valid generations with a 502.
Gated the phrase-loop sub-check behind `ODYSSEUS_PHRASE_LOOP_MIN` (default 0 = off). The
single-token-collapse guard ("Var Var Var...") is retained.

> **2026-09-16.** Still in the product, under a different name. The variable is
> `PANTHEON_PHRASE_LOOP_MIN` (`src/llm_core.py:442`), still defaulting to `0` = off;
> `ODYSSEUS_PHRASE_LOOP_MIN` is read by nothing and setting it does nothing.
> `_DegenerateStreamGuard` is at `src/llm_core.py:391`.

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

> **2026-09-16.** The mechanism and all three numbers are intact — `100_000` rounds and
> `86_400s` are at `src/agent_loop.py:4135` and `:5779`, and `_is_local_openai_compat_url`
> is at `src/agent_loop.py:1348`. Both overrides are renamed:
> `PANTHEON_UNLIMITED_LOCAL` and `PANTHEON_FORCE_UNLIMITED`, both in
> `src/runtime_limits.py`. The `ODYSSEUS_` spellings are read by nothing. The three
> follow-ups listed as *not lifted* stopped being follow-ups in change 3, below.

### 3. Phase 1 - finish local-unlimited surface
web_tools.py / outbound_fetch.py / filesystem_tools.py: web_search+web_fetch char truncation,
web-fetch byte caps (soft/hard + declared-length guard), and read_file char cap are lifted when
runtime_limits.unlimited() is true (local self-hosted). max_tokens (4096) also lifted to 1,000,000
for local, inside the Phase-0 block in agent_loop.py. Cloud endpoints keep every default.

> **2026-09-16.** Two of the three paths moved a directory down: the agent's tools live in
> `src/agent_tools/` now, so this is `src/agent_tools/web_tools.py` and
> `src/agent_tools/filesystem_tools.py`. `src/outbound_fetch.py` is where it was. The
> `max_tokens` lift to `1_000_000` is at `src/agent_loop.py:4138`.

### 4. Phase 2 - agent working memory (RAG add_text/search + guidance)
mcp_servers/rag_server.py: manage_rag gains two agent-callable actions - add_text (ingest arbitrary
text into the ChromaDB vector store) and search (semantic query). Owner resolved from injected arg or
ODYSSEUS_MCP_RAG_OWNER/ODYSSEUS_DOCUMENT_OWNER env (single-user box => ownerless/global, fine).
agent_loop.py: a "Working memory (long/large tasks)" rule added to BOTH _AGENT_RULES and
_API_AGENT_RULES (native function-calling path) - journal to manage_notes, offload big results to
manage_rag add_text/search instead of holding them in context; manage_memory only for durable USER
facts (no double-storage with auto-memory).

> **2026-09-16.** Both owner variables are renamed: `PANTHEON_MCP_RAG_OWNER` and
> `PANTHEON_DOCUMENT_OWNER`, both read in `mcp_servers/rag_server.py`. The `ODYSSEUS_`
> spellings are read by nothing. *"Single-user box => ownerless/global, fine"* is no longer
> the whole story — single-user mode is a switch an operator sets, and what it does when
> turned **off** was corrected in `B96`; see the upgrade notes in
> [`CHANGELOG.md`](CHANGELOG.md).

### 5. Phase 3 - local-inference probe auth
chat_helpers.py (_probe_auth_headers) + model_context.py (_endpoint_auth_headers): the /slots,
/v1/models and llama.cpp models probes now attach Authorization: Bearer <key> for a matching enabled
ModelEndpoint (empty dict when keyless => unchanged for keyless servers). routes/model_routes.py:
_ping_endpoint passes its in-scope headers to the Ollama reachability probe. Fixes the 401 spam from
LM Studio's API-token server. (Known follow-ups: two Ollama /api/tags fallbacks still keyless - benign.)

> **2026-09-16.** Intact. The two modules are `src/chat_helpers.py` and
> `src/model_context.py`; `routes/model_routes.py` is where it was.
