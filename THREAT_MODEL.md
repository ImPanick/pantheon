# Threat Model

Pantheon is a **self-hosted AI workspace with privileged local access**. This document states the trust boundary so contributors can reason about security decisions without reading through the full auth and middleware stack.

## Trust Boundary

Pantheon is designed for **trusted users on a private network**, not public exposure. The README describes it as "treat it like an admin console" — that framing is accurate. A logged-in admin can execute shell commands, read and write files, send email, and control model serving. This is intentional. The threat model does not try to prevent admins from doing these things. It does try to prevent:

- Unauthenticated access
- Non-admins reaching admin-only capabilities
- The AI agent acting on instructions injected through untrusted content (web results, emails, fetched pages, memories)
- Internal services (ChromaDB, Ollama, SearXNG, etc.) being reachable from outside the host

## Roles and Capabilities

| Capability | Admin | Non-admin (default) |
|---|---|---|
| Chat with agent | ✓ | ✓ |
| Browser tool | ✓ | ✓ |
| Documents | ✓ | ✓ |
| Research mode | ✓ | ✓ |
| Image generation | ✓ | ✓ |
| Memory management | ✓ | ✓ |
| Shell / Python execution | ✓ | ✗ |
| File read / write | ✓ | ✗ |
| Email send / read | ✓ | ✗ |
| MCP tools | ✓ | ✗ |
| Calendar management | ✓ | ✗ |
| Token / webhook management | ✓ | ✗ |
| Model serving | ✓ | ✗ |
| Vault | ✓ | ✗ |
| Settings | ✓ | ✗ |

Non-admin defaults are in `core/auth.py:DEFAULT_PRIVILEGES`.

**Tool enforcement is two gates, and the order matters.** `src/tool_execution.py:_ADMIN_ONLY_TOOLS` (11 names) is checked **first**, with its own refusal message; `src/tool_security.py:NON_ADMIN_BLOCKED_TOOLS` is checked after it. All 11 names in the first gate are currently also in the second, so a name removed from one of them is still refused by the other — which means **a prune of either list looks harmless in a manual test and may not be** (`P2-25` found exactly that). Treat the two as a pair: change one, re-read the other. Any tool whose name starts with `mcp__` is also blocked for non-admins.

Admins get full access to every **declared** privilege regardless of stored values. An undeclared key — a typo, or a name from a newer build — resolves to denied for everybody, admins included, because a privilege the registry has never heard of cannot be granted on the strength of a name (`P11-01`).

## Authentication

- **Sessions:** bcrypt passwords, 7-day session tokens stored atomically in `data/sessions.json` via `core/atomic_io.py`.
- **2FA:** TOTP with 8 single-use backup codes. Verified after password check, before session issuance.
- **Reserved usernames:** request sentinels and the Default/Local storage owner cannot be registered or renamed into. `core/auth.py:66` exposes them as `RESERVED_USERNAMES`, but the list itself lives in `src/owner_identity.py:RESERVED_AUTH_USERNAMES` — add a reserved name there, not in `core/auth.py`, or only one of the two will know about it.
  - `internal-tool` is security-critical: `core/middleware.py:require_admin` treats any request where `request.state.current_user == "internal-tool"` as the in-process tool loopback and grants admin unconditionally. A real account with that name would silently pass every `require_admin` check.
- **Orphan sessions:** `validate_token` re-checks that the user record still exists on every call. A deleted user's cookie is dropped on next request rather than continuing to authenticate.
- **`AUTH_ENABLED=0` disables auth**, and it did not always. Every environment boolean in the tree now parses through `src/env_flags.py:env_flag` — `1 / true / yes / on` is on, `0 / false / no / off` is off, case-folded and stripped, blank and unrecognised both mean unset. Before that (`B91`, 2026-09-15) only the literal string `false` turned auth off, so an operator who wrote `AUTH_ENABLED=0` got a running instance that still demanded a login and a security switch that silently did the opposite of what they set. Three call sites agree on the answer: `app.py:280`, `core/middleware.py`, and `src/auth_helpers.py:_auth_disabled`. **Turning auth off is an operator decision this project honours, not a bug it works around** — which is exactly why the parse has to be right.

## Internal Tool Loopback

Agent tool calls reach admin-gated HTTP routes over an in-process HTTP loopback. The mechanism:

1. At app startup, `core/middleware.py:21` sets `INTERNAL_TOOL_TOKEN` to `os.environ.get("PANTHEON_INTERNAL_TOKEN") or secrets.token_hex(32)`. Left unset — which is the default and the intended state — it is a fresh random value per process, never persisted and never sent to clients. **`PANTHEON_INTERNAL_TOKEN` is an override, and setting it makes the token as durable and as secret as wherever you put it.** Anything holding that value can call every `require_admin` route on this instance without a session.
2. Loopback requests carry `X-Pantheon-Internal-Token: <token>` or have `request.state.current_user` already set to `"internal-tool"` by the auth middleware.
3. `require_admin` recognises either signal and grants access without checking the session user.

The agent may be running in a non-admin user's session, but tool dispatch first calls `src/tool_security.py:owner_is_admin_or_single_user` to verify the session owner is an admin before issuing any loopback call. Non-admin users cannot invoke admin tools even via the agent.

## Prompt-Injection Hardening

External content that reaches the LLM is treated as untrusted via `src/prompt_security.py`:

- `untrusted_context_message(label, content)` wraps the content in a `user`-role message with a header block instructing the model not to follow instructions inside it. Content goes in as data, not as a system instruction.
- `UNTRUSTED_CONTEXT_POLICY` is a system-prompt preamble that states the same policy at the top of every session where untrusted data may appear.

**Untrusted surfaces that must go through this wrapper:** web search results, fetched URLs, emails (read), saved memories, skill text, notes, and any tool output sourced from outside the server. Injecting untrusted content directly into the system role is a security bug.

## Security Headers

`core/middleware.py:SecurityHeadersMiddleware` sets headers on every response:

- `X-Frame-Options: DENY` + `frame-ancestors 'none'` on all routes except tool-render iframes (which are sandboxed at the HTML level).
- `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer` everywhere.
- **CSP:** `default-src 'self'`, and `script-src 'self' 'wasm-unsafe-eval'` plus one `'sha256-…'` source per inline `<script>` in whatever HTML page this response served. `src/app_helpers.py:serve_html_with_nonce` computes those hashes from the bytes it just served and stamps them on `request.state`; `core/middleware.py` reads them back. A response that served no such page — an API reply, a static asset, FastAPI's own `/docs` — names no inline source at all, and a `script-src` naming *any* hash or nonce already refused every inline block it did not name, so nothing loses a script by it. The `'nonce-…'` path is still live for any template that still carries `{{CSP_NONCE}}`; it is simply no longer paid for on every response.
  - There is **no external origin left in this policy**. `https://cdn.jsdelivr.net` was in `script-src`, `style-src` and `connect-src` until 2026-09-01 (`P16-07`); Pyodide was its only consumer and is vendored under `static/lib/`. `'wasm-unsafe-eval'` is what makes that vendoring work — a page with any `script-src` cannot compile WebAssembly without it — and permits compiling wasm bytes and nothing else: not `eval`, not inline script, not a byte from another origin. `img-src` lost `https:` in the same wave (`P16-08`); remote images go through `/api/img`, same-origin, and only when the `remote_images` setting allows it.
  - `style-src 'unsafe-inline'` is intentionally kept — `static/index.html` and `static/login.html` ship inline `<style>` blocks and JS modules set `style=""` attributes at runtime. Inline styles do not execute script so the risk is visual-only. Removing this requires templating the HTML files and auditing all JS-set style attributes.

  *Corrected 2026-09-16. This bullet described a nonce-based policy that allowed `cdn.jsdelivr.net`, and both halves had stopped being true — the CDN allowance was removed on 2026-09-01 (`P16-07`) and inline scripts moved from nonces to per-file hashes on 2026-09-16 (`B141`). A threat model is read instead of the middleware, which is the reason it is worth correcting rather than deleting.*

## Uploaded And Rendered Content

Bytes somebody else chose, replayed from this app's own origin, are the other half of the boundary. Two controls carry it, and both are in `FORBIDDEN.md` Part 2 — they do not lift:

- **Uploads are inert.** `GET /api/upload/{id}` answers with `Content-Disposition: attachment`, `nosniff`, and its own CSP — `default-src 'none'; sandbox allow-downloads; frame-ancestors 'none'` — set in the `is_upload` branch of `SecurityHeadersMiddleware` rather than at the route, because Starlette's `MutableHeaders.__setitem__` replaces rather than appends and a CSP set by the handler would be overwritten by the middleware and never reach the wire. `sandbox` with no other token means an opaque origin with scripting, forms, popups and top-level navigation all off; `allow-downloads` is granted deliberately so the chat attachment UI's `window.open` still works.

- **SVG preview is a gate, not a sanitiser.** `src/svg_runtime.py` refuses SVGs it cannot vouch for instead of rewriting them, because a rewriter that misses one node fails open and a gate that refuses fails closed — and the alternative needed an XML parser this project does not have (`xml.etree` expands entities; `defusedxml` is not a dependency). As of `B160` the reference check is an **allowlist**: `_reference_verdict` accepts a same-document `#fragment` or a `data:image/<raster>` and refuses everything else. The rule it replaced asked whether a value *started with* one of four bad schemes, so any scheme nobody had thought of, and any value that reached its scheme by another route, was accepted by default. The known cost of the allowlist is recorded as a roadmap row, not hidden: an `https://` hyperlink inside a diagram is refused along with the beacons, because the gate sees attribute values and not the elements they hang on.

## Known Gaps

These are open, acknowledged, and contributor help is welcome. Each one was re-checked against the tree on 2026-09-16; three former entries had been fixed and are recorded under *Closed gaps* below rather than deleted, because a reader who saw the old list deserves to know what happened to it.

1. **No OS-level sandbox for `bash`.** The agent's `bash` tool runs subprocesses as the app process user, in `agent_cwd()`, with no namespace, seccomp profile, or network egress filter. A prompt injection that reaches a shell-enabled **admin** session can read anything that user can read and can reach any host the machine can reach, including the internal services `SECURITY.md` tells you to keep internal. Note the scope carefully: `read_file`/`write_file` are *not* in this gap — they go through `src/tool_execution.py:_resolve_tool_path`, which resolves symlinks, rejects a sensitive-path deny list (`.ssh`, `.gnupg`, `id_rsa`, …), requires containment in an allowlisted root, and narrows to the active workspace when one is bound. `bash` is subject to none of that, because a shell is.

2. **Token scopes do not narrow the agent.** `routes/api_token_routes.py:ALLOWED_SCOPES` is genuinely granular for *routes* — 16 named scopes with read/write splits, plus `TOKEN_PROFILES` for the common combinations — but the `chat` scope is a single grant, and a session reached through it runs the agent with the privileges of the token's owner. There is no way to issue a token that can chat but cannot use a subset of the tools that owner has. The privilege split that exists is admin versus non-admin (`src/tool_security.py:NON_ADMIN_BLOCKED_TOOLS`), not per-token.

3. **Prompt-injection hardening is a convention, not an enforced boundary.** `untrusted_context_message` has to be *called*. Nothing in the type system or the test suite proves that every path carrying external content into the LLM goes through it — a new tool that returns fetched text and injects it directly is a security bug that compiles, imports and passes review. The list of surfaces above is maintained by hand.

### Closed gaps

- ~~**SSRF via `/api/v1/chat` `base_url`.**~~ Fixed. `routes/webhook/webhook_routes.py:298` passes a token-supplied `base_url` through `src/url_security.py:validate_public_http_url` and returns `400` on rejection. Auto-resolved known-provider URLs and admin-configured LAN endpoints are deliberately still allowed, which is the `Law 17` position — a self-hoster pointing at their own Ollama is the intended case.
- ~~**`src/search/` partial consolidation.**~~ Fixed. All seven modules under `src/search/` are now shims over `services.search`: `analytics`, `cache`, `content`, `core`, `providers` and `query` alias by `sys.modules` replacement, and `ranking` re-exports. None holds a parallel implementation, so there is nothing left to drift.
- ~~**Coarse token scopes.**~~ Partly fixed, and what remains is gap 2 above. The claim that tokens carried "either `chat` or `admin` scope" is no longer true; there is no `admin` scope in `ALLOWED_SCOPES` at all.

*The three entries above cited `#1058` and `#1039`, and `#1058` was cited for two unrelated gaps. Those numbers appear nowhere else in this tree, and every issue this repository refers to elsewhere is three digits (`#485`, `#593`, `#622`), so they are upstream Odysseus's and were carried over by the fork. A bare `#NNNN` in a GitHub markdown file links to **this** repository's issue of that number whatever it happens to be, so they are removed rather than left to point somewhere plausible and wrong.*
