# SPDX-License-Identifier: AGPL-3.0-or-later
"""
model_context.py

Query and cache model context window sizes from OpenAI-compatible APIs.
Provides token estimation for context usage tracking.
"""

import contextvars
import ipaddress
import logging
import sys
import time
from typing import Dict, List, Optional, Tuple

from urllib.parse import urlparse

# `B1022`: the context-window lookups go through `paced_http` — routed (a
# `NO_PROXY` range is honoured, `B982`) and paced (a cloud catalog cooling down
# is refused before the call; a local server costs nothing). `httpx.get` builds
# a client inside and takes no `mounts=`, so `B1014`'s rule could not reach it.
from src import paced_http

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"}
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)

# Tailscale uses the CGNAT range 100.64.0.0/10, NOT all of 100.0.0.0/8.
# A bare "100." prefix would classify public addresses (e.g. AWS ranges
# under 100.x outside the CGNAT block) as local; routes/model_routes.py
# already narrows this the same way for endpoint classification.
_TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _in_tailscale_range(host: str) -> bool:
    try:
        return ipaddress.ip_address(host) in _TAILSCALE_CGNAT
    except ValueError:
        return False


def _is_private_ip_literal(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in network for network in _PRIVATE_NETWORKS)


def _normalize_base_for_compare(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/models", "/completions", "/v1/messages"):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
    return url


# `P23-04` (PERF-M-14). One context-length lookup asked the endpoint table
# six times — `_configured_endpoint_kind` four times (directly and through
# `is_local_endpoint`) and `_endpoint_auth_headers` twice — measured in-process
# on the showcase: 11 statements per `GET /api/session/{id}/context`, six of
# them `SELECT … FROM model_endpoints`, and that route runs on every chat open.
# Inside `_rows_read_once()` the enabled rows are read once and shared; outside
# one, every call reads as it always did, so nothing else changes.
_ROWS_SCOPE: contextvars.ContextVar = contextvars.ContextVar("model_context_rows", default=None)


class _rows_read_once:
    """Within this block, the enabled endpoint rows are read at most once."""

    def __enter__(self):
        self._token = _ROWS_SCOPE.set({})
        return self

    def __exit__(self, *exc):
        _ROWS_SCOPE.reset(self._token)
        return False


def _enabled_endpoint_rows():
    """The enabled `ModelEndpoint` rows — shared within `_rows_read_once()`.

    Raises when the database layer is unavailable; callers keep their own
    fallbacks for that, exactly as before."""
    scope = _ROWS_SCOPE.get()
    if scope is not None and "rows" in scope:
        return scope["rows"]
    from core.database import SessionLocal, ModelEndpoint
    db = SessionLocal()
    try:
        rows = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()  # noqa: E712
    finally:
        db.close()
    if scope is not None:
        scope["rows"] = rows
    return rows


def _endpoint_auth_headers(url: str) -> Dict[str, str]:
    """Authorization header for a configured endpoint matching ``url``.

    Mirrors the chat-completions path: match an enabled ModelEndpoint by its
    normalized base_url, resolve its runtime credentials the same way, and send
    ``Authorization: Bearer <key>`` only when a key is configured. Returns {}
    when nothing matches, no key is set, or the DB layer isn't loaded — so
    keyless local servers (LM Studio/llama.cpp without a token) are still probed
    unauthenticated and behavior is unchanged for them."""
    target = _normalize_base_for_compare(url)
    if not target or "core.database" not in sys.modules:
        return {}
    try:
        from src.endpoint_resolver import resolve_endpoint_runtime
        for ep in _enabled_endpoint_rows():
            base = _normalize_base_for_compare(getattr(ep, "base_url", "") or "")
            if not base:
                continue
            if target != base and not target.startswith(base + "/"):
                continue
            try:
                _b, api_key = resolve_endpoint_runtime(ep, owner=getattr(ep, "owner", None))
            except Exception:
                api_key = getattr(ep, "api_key", None)
            return {"Authorization": f"Bearer {api_key}"} if api_key else {}
    except Exception:
        return {}
    return {}


def _configured_endpoint_kind(url: str) -> Optional[str]:
    """Return configured endpoint kind for a chat/base URL when available."""
    target = _normalize_base_for_compare(url)
    if not target:
        return None
    if "core.database" not in sys.modules:
        return None
    try:
        for ep in _enabled_endpoint_rows():
            base = _normalize_base_for_compare(getattr(ep, "base_url", "") or "")
            if not base:
                continue
            if target != base and not target.startswith(base + "/"):
                continue
            kind = (getattr(ep, "endpoint_kind", None) or "auto").strip().lower()
            if kind in ("local", "api", "proxy"):
                return kind
            if getattr(ep, "api_key", None):
                parsed = urlparse(base)
                host = (parsed.hostname or "").lower()
                path = (parsed.path or "").rstrip("/")
                if parsed.port != 11434 and "ollama" not in host and (path.endswith("/v1") or "/openai" in path):
                    return "proxy"
            return "auto"
    except Exception:
        return None


def is_local_endpoint(url: str) -> bool:
    """Check if URL points to a local/private/tailscale address."""
    kind = _configured_endpoint_kind(url)
    if kind in ("api", "proxy"):
        return False
    if kind == "local":
        return True
    try:
        host = urlparse(url).hostname or ""
        return host in _LOCAL_HOSTS or _is_private_ip_literal(host) or _in_tailscale_range(host)
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_CONTEXT = 128000
REQUEST_TIMEOUT = 5

# `B1369`. **Where the number came from**, which `known` could not say.
#
# `known` was True for two different things: a window an endpoint actually
# reported, and a *substring match on the model's name* in
# `KNOWN_CONTEXT_WINDOWS`. Measured on 2026-10-14:
# `budget_context_for_model("http://127.0.0.1:9/v1", "gemma-4-26b")` answered
# **262,144** with nothing listening on that port, because `"gemma"` is a key in
# the table. Every caller that scales a budget off the window — the agent's trim
# budget, the context wheel, the tool suite's room — was therefore unable to
# tell a measurement from a guess about a name, which is at least adjacent to
# `D-2026-10-07-02` §1's rule that a capability is never read off a model's name.
#
# Three values, not a second boolean (`Law 10`): a flag would have to be read
# together with `known` to mean anything, and the pair has four states of which
# one is impossible.
#
#   `reported`    — an endpoint said so: llama.cpp `/slots` `n_ctx`, a
#                   `/v1/models` entry, or a proxy catalogue.
#   `known_table` — a substring of the model's name matched
#                   `KNOWN_CONTEXT_WINDOWS`. True of the name, not of the server.
#   `fallback`    — neither, so the value is the bare `DEFAULT_CONTEXT`.
#
# **This changes no behaviour.** `budget_context_for_model` still treats
# `known_table` as proven, because whether it should is the owner's call and the
# row says so; what changes is that a caller can now ask, and the run receipt
# records the answer. `known` remains exactly `basis != BASIS_FALLBACK`, and
# `test_the_window_says_where_it_came_from` asserts that rather than leaving two
# fields free to disagree (`Law 7`).
BASIS_REPORTED = "reported"
BASIS_KNOWN_TABLE = "known_table"
BASIS_FALLBACK = "fallback"

#: Every value a basis may take, in descending order of how much it proves.
CONTEXT_BASES = (BASIS_REPORTED, BASIS_KNOWN_TABLE, BASIS_FALLBACK)

# Known context windows for major API models (used as fallback when /models
# endpoint doesn't report context_length).
# Substring matching — use the shortest unique prefix so variants get caught.
KNOWN_CONTEXT_WINDOWS = {
    # --- Anthropic ---
    'claude-sonnet-4-5': 200000,
    'claude-sonnet-4-6': 200000,
    'claude-sonnet-4': 200000,
    'claude-opus-4': 200000,
    'claude-haiku-4': 200000,
    'claude-haiku-3-5': 200000,
    'claude-3-5-sonnet': 200000,
    'claude-3-5-haiku': 200000,
    'claude-3-opus': 200000,
    'claude-3-sonnet': 200000,
    'claude-3-haiku': 200000,

    # --- OpenAI ---
    'gpt-5': 400000,
    'gpt-4.1': 1047576,
    'gpt-4.1-mini': 1047576,
    'gpt-4.1-nano': 1047576,
    'gpt-4o': 128000,
    'gpt-4o-mini': 128000,
    'gpt-4-turbo': 128000,
    'gpt-4': 8192,
    'gpt-3.5-turbo': 16385,
    'o1': 200000,
    'o1-mini': 128000,
    'o1-pro': 200000,
    'o3': 200000,
    'o3-mini': 200000,
    'o4-mini': 200000,

    # --- DeepSeek ---
    'deepseek-chat': 64000,
    'deepseek-coder': 64000,
    'deepseek-reasoner': 64000,
    'deepseek-r1': 64000,
    'deepseek-v3': 64000,
    'deepseek-v2': 64000,

    # --- Google ---
    'gemini-2.5-pro': 1048576,
    'gemini-2.5-flash': 1048576,
    'gemini-2.0-flash': 1048576,
    'gemini-1.5-pro': 1048576,
    'gemini-1.5-flash': 1048576,
    'gemma-4': 262144,
    'gemma-3': 128000,
    'gemma-2': 8192,

    # --- Mistral ---
    'mistral-large': 128000,
    'mistral-medium': 32000,
    'mistral-small': 32000,
    'mistral-nemo': 128000,
    'mistral-7b': 32000,
    'mixtral': 32000,
    'codestral': 32000,
    'pixtral': 128000,

    # --- xAI ---
    'grok-4': 131072,
    'grok-3': 131072,
    'grok-2': 131072,

    # --- Meta / Llama ---
    'llama-4': 1048576,
    'llama-3.3': 131072,
    'llama-3.2': 131072,
    'llama-3.1': 131072,
    'llama-3': 131072,

    # --- Qwen ---
    'qwen3': 131072,
    'qwen2.5': 131072,
    'qwen2': 32768,
    'qwq': 32768,

    # --- Cohere ---
    'command-r-plus': 128000,
    'command-r': 128000,
    'command-a': 256000,

    # --- Perplexity ---
    'sonar-pro': 200000,
    'sonar': 128000,

    # --- MiniMax ---
    'minimax': 1000000,

    # --- Moonshot / Kimi ---
    'moonshot': 128000,
    'kimi': 128000,

    # --- Microsoft ---
    'phi-4': 16000,
    'phi-3': 128000,

    # --- Nvidia ---
    'nemotron': 131072,

    # --- Yi ---
    'yi-large': 32768,
    'yi-1.5': 16384,

    # --- 01.ai ---
    'yi-lightning': 16384,

    # --- Nous ---
    'hermes': 131072,
    'nous-hermes': 131072,

    # --- Xiaomi ---
    'mimo-v2.5-pro': 1048576,
    'mimo-v2.5': 1048576,

    # --- Open community ---
    'dolphin': 32768,
    'mythomax': 4096,
    'wizard': 32768,
    'openchat': 8192,
    'solar': 32768,
}

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_context_cache: Dict[Tuple[str, str], Tuple[int, bool, str]] = {}


def _get_context_length_cached(endpoint_url: str, model: str) -> Tuple[int, bool, str]:
    """Return ``(context_length, known, basis)``.

    ``known`` is False only when the value is a bare DEFAULT_CONTEXT fallback (no
    endpoint report and not in the known table); ``basis`` says which of the two
    things ``known`` means (`B1369`, see `CONTEXT_BASES`)."""
    with _rows_read_once():   # `P23-04` (PERF-M-14)
        return _get_context_length_once(endpoint_url, model)


def _get_context_length_once(endpoint_url: str, model: str) -> Tuple[int, bool, str]:
    configured_kind = _configured_endpoint_kind(endpoint_url)
    is_local = is_local_endpoint(endpoint_url)
    # Key on (endpoint_url, model): the same model id can be served by two
    # different remote endpoints with different real context windows (e.g. a
    # capped proxy vs. the full provider), so caching by model id alone would
    # serve one endpoint's window for the other (issue #2603).
    cache_key = (endpoint_url, model)
    if not is_local and cache_key in _context_cache:
        return _context_cache[cache_key]

    ctx, known, basis = _query_context_length(endpoint_url, model)
    # Only cache non-default values to allow retry on next request.
    # Local endpoints can restart with a different --max-model-len while keeping
    # the same model id, so always re-query them instead of serving stale cache.
    if not is_local and (ctx != DEFAULT_CONTEXT or configured_kind in ("api", "proxy")):
        _context_cache[cache_key] = (ctx, known, basis)
    logger.info(f"Context length for {model}: {ctx} ({basis})")
    return ctx, known, basis


def get_context_length(endpoint_url: str, model: str) -> int:
    """Get the context window size for a model.

    Queries /v1/models on the endpoint and looks for context_length
    or context_window fields. Caches result per (endpoint, model).
    Falls back to DEFAULT_CONTEXT if unavailable.
    """
    return _get_context_length_cached(endpoint_url, model)[0]


def get_context_length_known(endpoint_url: str, model: str) -> Tuple[int, bool]:
    """Like ``get_context_length`` but also returns whether the window was actually
    discovered (endpoint-reported or in the known-models table) rather than the bare
    DEFAULT_CONTEXT fallback. Callers that *scale* a budget off the window must not
    trust an unknown value — a fallback 128K isn't proof the model holds 128K
    (review on #4122).

    Kept at two values on purpose: this is the contract a dozen callers already
    hold, and `B1369` is about making the provenance *askable*, not about making
    every caller handle it. `get_context_length_basis` is the three-value form."""
    ctx, known, _basis = _get_context_length_cached(endpoint_url, model)
    return ctx, known


def get_context_length_basis(endpoint_url: str, model: str) -> Tuple[int, bool, str]:
    """``(context_length, known, basis)`` — the window and where it came from.

    `B1369`. For callers that scale something off the window and want to record
    what they scaled off: a window an endpoint reported is evidence about the
    server, and a window matched from the model's *name* is not. The run receipt
    stores it (`ToolSuite.window_basis` → `run_config.suite.basis`) so a
    narrowed turn can be read back and the question answered after the fact."""
    return _get_context_length_cached(endpoint_url, model)


def budget_context_for_model(endpoint_url: str, model: str, *, fallback: int = 0) -> int:
    """Context window to scale the agent input budget against.

    Returns the *freshly discovered* window when it was actually proven
    (endpoint-reported / known table), else 0 so auto-scaling stays conservative.
    Crucially this binds the ``known`` flag to the value it proves — callers must
    not pair this flag with a context length from a *different* lookup (a stale
    local re-query, or a caller that didn't pass one), which would budget off an
    unproven number (review on #4122). On probe error, returns ``fallback`` (the
    caller's best-known value) to preserve prior behaviour."""
    try:
        ctx, known = get_context_length_known(endpoint_url, model)
        return ctx if known else 0
    except Exception:
        return fallback


def budget_context_basis(endpoint_url: str, model: str, *, fallback: int = 0) -> Tuple[int, str]:
    """``budget_context_for_model`` plus the basis of the number it returned.

    `B1369`. The same branch, so the two can never disagree (`Law 7`) — when
    the window is not proven this returns `(0, BASIS_FALLBACK)`, because 0 is
    not a window that came from anywhere. On probe error it returns the
    caller's ``fallback`` with `BASIS_FALLBACK`, matching
    ``budget_context_for_model``'s own behaviour rather than inventing one."""
    try:
        ctx, known, basis = get_context_length_basis(endpoint_url, model)
        return (ctx, basis) if known else (0, BASIS_FALLBACK)
    except Exception:
        return fallback, BASIS_FALLBACK


def _lookup_known(model: str) -> Optional[int]:
    """Check known context windows by substring match.

    Picks the LONGEST matching key so a short key never shadows a more specific
    one. Without this, 'o1' (200k) precedes 'o1-mini' (128k) in the table and a
    first-match return would report o1-mini's window as 200k.
    """
    name = model.lower()
    basename = name.split("/")[-1] if "/" in name else name
    basename = basename.split(":")[0]  # strip :free, :extended etc.
    best_key: Optional[str] = None
    best_ctx: Optional[int] = None
    for key, ctx in KNOWN_CONTEXT_WINDOWS.items():
        if key in basename or key in name:
            if best_key is None or len(key) > len(best_key):
                best_key, best_ctx = key, ctx
    return best_ctx


def _model_ctx_from_entry(m: dict) -> Optional[int]:
    """Extract a positive context window from one /models catalog entry.

    Checks the common top-level fields first, then a nested meta/model_extra
    object. Returns None when no positive window is reported.
    """
    if not isinstance(m, dict):
        return None
    for field in (
        "context_length",
        "context_window",
        "max_model_len",
        "max_context_length",
        "max_seq_len",
    ):
        val = m.get(field)
        if val and isinstance(val, (int, float)) and val > 0:
            return int(val)
    meta = m.get("meta") or m.get("model_extra") or {}
    if isinstance(meta, dict):
        # n_ctx is the actual serving context (set via -c flag in llama.cpp)
        for field in ("n_ctx", "context_length", "context_window", "max_model_len"):
            val = meta.get(field)
            if val and isinstance(val, (int, float)) and val > 0:
                return int(val)
    return None


# Per-endpoint cache of the {model_id: context_length} map parsed from a
# proxy/api catalog. api/proxy endpoints skip the /models download on every
# lookup because a large catalog is expensive; caching the whole map lets us
# pay that download at most once per endpoint instead of once per model.
_catalog_ctx_cache: Dict[str, Dict[str, int]] = {}


def _proxy_catalog_context(endpoint_url: str, model: str) -> Optional[int]:
    """Context window for a model read from the endpoint's /models catalog.

    Fetches the catalog once per endpoint and caches the full id->context map,
    so an api/proxy endpoint serving a model that isn't in KNOWN_CONTEXT_WINDOWS
    (e.g. a new OpenRouter model) still reports its real window instead of the
    bare default. Returns None when the catalog can't be read or doesn't list a
    positive window for the model.
    """
    cat = _catalog_ctx_cache.get(endpoint_url)
    if cat is None:
        from src.endpoint_resolver import build_models_url
        try:
            r = paced_http.get_sync(build_models_url(endpoint_url), timeout=REQUEST_TIMEOUT, headers=_endpoint_auth_headers(endpoint_url) or None, follow_redirects=False, reuse=True)
        except Exception as e:
            logger.debug(f"Failed to fetch proxy catalog for context length: {e}")
            return None
        if not r.is_success:
            return None
        cat = {}
        try:
            for m in (r.json().get("data") or []):
                mid = m.get("id") if isinstance(m, dict) else None
                ctx = _model_ctx_from_entry(m) if mid else None
                if mid and ctx:
                    cat[mid] = ctx
        except Exception as e:
            logger.debug(f"Failed to parse proxy catalog for context length: {e}")
            return None
        _catalog_ctx_cache[endpoint_url] = cat

    if model in cat:
        return cat[model]
    # Catalog ids may carry a provider prefix (e.g. "openai/gpt-4o") while the
    # session stores the bare id; match on the trailing segment as a fallback.
    base = model.split("/")[-1]
    for mid, ctx in cat.items():
        if mid.split("/")[-1] == base:
            return ctx
    return None


def _query_context_length(endpoint_url: str, model: str) -> Tuple[int, bool, str]:
    """Query the model API for context length.

    Returns ``(context_length, known, basis)``. ``known`` is False only for the
    bare ``DEFAULT_CONTEXT`` fallback; ``basis`` is one of `CONTEXT_BASES` and
    says **which** of the two things `known` used to mean (`B1369`).

    The arity is deliberately strict rather than tolerant. A caller — or a test
    monkeypatching this — that still returns a 2-tuple raises here, loudly. The
    alternative, defaulting the basis when it is missing, would answer *we do
    not know where this came from* in exactly the shape this row exists to
    remove: a number whose provenance cannot be told.
    """
    known = _lookup_known(model)
    api_ctx = None
    configured_kind = _configured_endpoint_kind(endpoint_url)

    # Large OpenAI-compatible proxies can make /models expensive. If the
    # endpoint is explicitly configured as API/proxy, prefer known context
    # metadata (or the default) over downloading the full catalog.
    if configured_kind in ("api", "proxy"):
        if known:
            logger.info(f"Using known context window for {model}: {known}")
            return known, True, BASIS_KNOWN_TABLE
        # Not in the known table: read the real window from the catalog (cached
        # once per endpoint) instead of capping every unknown model at the
        # default — that under-reported large windows on aggregators like
        # OpenRouter (issue #4886).
        api_ctx = _proxy_catalog_context(endpoint_url, model)
        if api_ctx:
            logger.info(f"Proxy catalog reports context window for {model}: {api_ctx}")
            return api_ctx, True, BASIS_REPORTED
        return DEFAULT_CONTEXT, False, BASIS_FALLBACK

    # Try llama.cpp /slots endpoint first — reports actual serving context.
    # `B1608`: these lookups run every round and a local answer is never
    # cached, so they keep one client (`paced_http` `reuse`) rather than
    # building one — and its TLS contexts — per request.
    if is_local_endpoint(endpoint_url):
        try:
            base = endpoint_url.split("/v1")[0] if "/v1" in endpoint_url else endpoint_url.rsplit("/", 1)[0]
            r = paced_http.get_sync(f"{base}/slots", timeout=REQUEST_TIMEOUT, headers=_endpoint_auth_headers(endpoint_url) or None, follow_redirects=False, reuse=True)
            if r.is_success:
                slots = r.json()
                if isinstance(slots, list) and slots:
                    n_ctx = slots[0].get("n_ctx")
                    if n_ctx and isinstance(n_ctx, int) and n_ctx > 0:
                        logger.info(f"llama.cpp /slots reports n_ctx={n_ctx} for {model}")
                        return n_ctx, True, BASIS_REPORTED
        except Exception:
            pass

    # `B1732`. LM Studio and Ollama's OpenAI-compatible door report no window
    # on `/v1/models`, so a model they serve — gpt-oss-20b on LM Studio, measured
    # in the owner's context wheel — read as "unknown" and the agent was held to
    # 6,000 tokens. Both say what the model was LOADED with on their own API.
    # Asked first only of a server known to be LM Studio or Ollama (their
    # ports); any other local server is asked below, when its own
    # `/v1/models` named no window.
    if is_local_endpoint(endpoint_url):
        served = _local_server_window(endpoint_url, model)
        if served is not None:
            served_ctx, server = served
            if served_ctx:
                logger.info(f"{server} reports {model} loaded with a {served_ctx}-token window")
                return served_ctx, True, BASIS_REPORTED
            # The server is LM Studio and has not loaded the model: it loads it
            # on the next request with whatever its own default is (often 4,096),
            # so the model's trained window from the table is not what will be
            # served. Unknown it stays until the server has loaded it.
            logger.info(f"{server} has not loaded {model}; its window is unknown until it does")
            return DEFAULT_CONTEXT, False, BASIS_FALLBACK

    # GitHub Copilot's /models requires auth + X-GitHub-Api-Version headers that
    # aren't available here; an unauthenticated probe just 400s. All Copilot
    # picker models are major API models covered by the known-context table, so
    # rely on that instead of a doomed network call.
    from src.copilot import is_copilot_base
    if is_copilot_base(endpoint_url):
        if known:
            logger.info(f"Using known context window for {model}: {known}")
            return known, True, BASIS_KNOWN_TABLE
        return DEFAULT_CONTEXT, False, BASIS_FALLBACK

    from src.endpoint_resolver import build_models_url

    models_url = build_models_url(endpoint_url)
    try:
        r = paced_http.get_sync(models_url, timeout=REQUEST_TIMEOUT, headers=_endpoint_auth_headers(endpoint_url) or None, follow_redirects=False, reuse=True)
        if r.is_success:
            data = r.json()
            models_list = data.get("data") or []

            for m in models_list:
                mid = m.get("id", "")
                if mid == model or mid.split("/")[-1] == model.split("/")[-1]:
                    api_ctx = _model_ctx_from_entry(m)
                    break
    except Exception as e:
        logger.debug(f"Failed to query context length for {model}: {e}")

    # For local/self-hosted endpoints, trust the API value (user set --max-model-len)
    # For cloud APIs, use the larger value (API can report low defaults)
    if api_ctx and known:
        _is_local = is_local_endpoint(endpoint_url)
        if _is_local and api_ctx < known:
            logger.info(f"Local endpoint reports {api_ctx} for {model} (known max: {known}) — using API value")
            return api_ctx, True, BASIS_REPORTED
        result = max(api_ctx, known)
        if api_ctx < known:
            logger.info(f"API reported {api_ctx} for {model}, using known {known} instead")
        # The basis follows the number that WON, not the fact that both were
        # found. When the table out-bids the endpoint, the window being
        # returned is the one derived from the model's name — which is the
        # whole distinction this row is about, and the one place it would have
        # been easy to label as `reported` because an endpoint did answer.
        return result, True, (BASIS_REPORTED if result == api_ctx else BASIS_KNOWN_TABLE)
    if api_ctx:
        return api_ctx, True, BASIS_REPORTED
    # `B1732`. LM Studio on a port of its own choosing: asked once its OpenAI
    # list has said nothing.
    if is_local_endpoint(endpoint_url):
        served = _local_server_window(endpoint_url, model, any_local_server=True)
        if served is not None and served[0]:
            logger.info(f"{served[1]} reports {model} loaded with a {served[0]}-token window")
            return served[0], True, BASIS_REPORTED
        if served is not None:
            return DEFAULT_CONTEXT, False, BASIS_FALLBACK
    if known:
        logger.info(f"Using known context window for {model}: {known}")
        return known, True, BASIS_KNOWN_TABLE

    return DEFAULT_CONTEXT, False, BASIS_FALLBACK


# ── `B1732` · what a local server LOADED the model with ─────────────────────
#
# LM Studio: its native list (`/api/v1/models`, LM Studio 0.4+) carries each
# model's `loaded_instances[].config.context_length`; the older `/api/v0/models`
# carries `loaded_context_length` and `state`. Ollama: `/api/ps` lists the
# running models with the `context_length` they were loaded with — asked only
# on Ollama's OpenAI-compatible door, because on its native door Pantheon sends
# `num_ctx` itself (`_build_ollama_payload`) and the loaded number is our own.
#
# Answers are kept `_SERVED_WINDOW_TTL` seconds per (host, port): this lookup
# runs several times a turn and local answers are otherwise never cached.

_SERVED_WINDOW_TTL = 10.0
_served_window_cache: Dict[Tuple[str, Optional[int], str], Tuple[Optional[Tuple[Optional[int], str]], float]] = {}


def _same_model(a: str, b: str) -> bool:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    return a.split("/")[-1] == b.split("/")[-1]


def _lmstudio_loaded_window(models: list, model: str) -> Optional[Tuple[Optional[int], str]]:
    """From LM Studio's native model list: (loaded window, "LM Studio"),
    (None, "LM Studio") when it lists the model unloaded, None when it does not
    list the model at all."""
    from src.model_capability_readers.lmstudio import loaded_context_tokens
    for m in models:
        if not isinstance(m, dict):
            continue
        names = [str(m.get("key") or ""), str(m.get("id") or ""), str(m.get("display_name") or "")]
        for inst in m.get("loaded_instances") or []:
            if isinstance(inst, dict):
                names.append(str(inst.get("id") or ""))
        if any(_same_model(n, model) for n in names):
            return loaded_context_tokens(m), "LM Studio"
    return None


def _local_server_window(endpoint_url: str, model: str, *,
                         any_local_server: bool = False) -> Optional[Tuple[Optional[int], str]]:
    """`(window, server)` when a local LM Studio or Ollama answers for `model`:
    `window` is what it loaded the model with, or None when LM Studio lists the
    model but has not loaded it. None when no such server answered.

    Without `any_local_server` only an endpoint on LM Studio's or Ollama's own
    port is asked; with it, any generic OpenAI-compatible local server is asked
    LM Studio's question too."""
    if not model:
        return None
    try:
        from src.model_capability_readers import (VENDOR_GENERIC_OPENAI, VENDOR_LMSTUDIO,
                                                  VENDOR_OLLAMA, detect_vendor)
        vendor = detect_vendor(endpoint_url)
    except Exception:
        return None
    parsed = urlparse(endpoint_url)
    lmstudio_vendors = ((VENDOR_LMSTUDIO, VENDOR_GENERIC_OPENAI) if any_local_server
                        else (VENDOR_LMSTUDIO,))
    if vendor not in lmstudio_vendors and vendor != VENDOR_OLLAMA:
        return None
    key = (parsed.hostname or "", parsed.port, model)
    now = time.monotonic()
    hit = _served_window_cache.get(key)
    if hit is not None and hit[1] > now:
        return hit[0]

    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    authority = host if parsed.port is None else f"{host}:{parsed.port}"
    root = f"{parsed.scheme or 'http'}://{authority}"
    auth = _endpoint_auth_headers(endpoint_url) or None
    answer: Optional[Tuple[Optional[int], str]] = None

    if vendor in lmstudio_vendors:
        for path, field in (("/api/v1/models", "models"), ("/api/v0/models", "data")):
            try:
                r = paced_http.get_sync(f"{root}{path}", timeout=1.0, headers=auth,
                                        follow_redirects=False, reuse=True)
                payload = r.json() if r.is_success else None
            except Exception:
                payload = None
            models = payload.get(field) if isinstance(payload, dict) else None
            if not isinstance(models, list) or not models:
                continue
            # An LM Studio list, not some other server's `/api/...`: native
            # entries carry `key`, v0 entries carry `state` / `max_context_length`.
            first = models[0] if isinstance(models[0], dict) else {}
            if not ({"key", "loaded_instances"} & set(first) or
                    {"state", "max_context_length"} & set(first)):
                continue
            answer = _lmstudio_loaded_window(models, model)
            if answer is not None:
                break
    elif vendor == VENDOR_OLLAMA and "/v1" in (parsed.path or ""):
        try:
            r = paced_http.get_sync(f"{root}/api/ps", timeout=1.0, headers=auth,
                                    follow_redirects=False, reuse=True)
            payload = r.json() if r.is_success else None
        except Exception:
            payload = None
        running = payload.get("models") if isinstance(payload, dict) else None
        for m in running if isinstance(running, list) else []:
            if not isinstance(m, dict):
                continue
            names = {str(m.get("name") or ""), str(m.get("model") or "")}
            names |= {n[:-len(":latest")] for n in names if n.endswith(":latest")}
            if any(_same_model(n, model) for n in names):
                ctx = m.get("context_length")
                if isinstance(ctx, int) and ctx > 0:
                    answer = (ctx, "Ollama")
                break

    _served_window_cache[key] = (answer, now + _SERVED_WINDOW_TTL)
    return answer


def estimate_tokens(messages: List[Dict]) -> int:
    """Rough token estimate for a list of messages.

    Uses chars * 0.3 which is closer to real BPE tokenizer output
    than the commonly-cited chars/4 (which underestimates by ~20-30%).
    Also adds ~4 tokens per message for role/formatting overhead, and counts
    assistant tool_calls (name + arguments) — a tool-only turn carries
    content=None with the real payload in tool_calls, so ignoring them made the
    estimate (and the compaction/trim gates that rely on it) blind to large
    tool arguments.
    """
    total = 0
    for msg in messages:
        total += 4  # per-message overhead (role, separators)
        content = msg.get("content", "")
        if isinstance(content, str):
            total += int(len(content) * 0.3)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    total += int(len(item.get("text", "")) * 0.3)
        # Tool calls carry real payload too: a tool-only assistant turn is stored
        # with content=None and the actual args (e.g. a create_document body) in
        # tool_calls[].function.arguments. Ignoring them made large tool arguments
        # read as ~0 tokens, so the compaction/trim gates missed genuine overflow.
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
                name = fn.get("name", "") or ""
                args = fn.get("arguments", "") or ""
                if not isinstance(args, str):
                    args = str(args)  # some shapes store arguments as a dict
                total += 4  # per tool-call overhead (id, type, wrapper)
                total += int((len(str(name)) + len(args)) * 0.3)
    return total
