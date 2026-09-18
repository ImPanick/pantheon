# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chat routes — /api/chat, /api/chat_stream, /api/inject_context, /api/search."""

import asyncio
import json
import os
import re
import time
import logging
from datetime import datetime
from typing import Callable, Dict, Any, AsyncGenerator, List, Optional, Union

from fastapi import APIRouter, Request, HTTPException, Form, Query, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from core.models import ChatMessage, get_session_manager_instance
from src.request_models import ChatRequest
from src.llm_core import (
    _normalize_http_status,
    llm_call_async,
    llm_call_async_with_route_fallback,
    stream_llm,
    stream_llm_with_fallback,
)
from src.agent_loop import pending_steers, stream_agent_loop, submit_steer
from src import agent_runs
from src.model_context import estimate_tokens
from src.context_compactor import (
    apply_compaction_state,
    maybe_compact,
    trim_for_context,
)
from src.chat_helpers import coerce_message_and_session
from src.endpoint_resolver import normalize_base as _normalize_base, build_chat_url
from src.foreground_model_routing import (
    build_foreground_model_candidates,
    build_foreground_route_descriptors,
    resolve_foreground_model_policy,
)
from src.session_search import search_session_messages
from src.prompt_security import untrusted_context_message
from core.exceptions import SessionNotFoundError
from src.auth_helpers import (
    effective_user,
    get_current_user,
    is_delegated_credential,
    require_api_token_scope,
    require_chat_api_token_scope,
    require_user,
    storage_owner_for_request,
)
from routes.session_routes import _verify_session_owner
from routes.document_helpers import _owner_session_filter
from core.database import SessionLocal, get_session_mode, set_session_mode
from core.database import Session as DBSession, ChatMessage as DBChatMessage
from core.database import Document as DBDocument, ModelEndpoint
from core.log_safety import redact_url
from routes.research_routes import _resolve_research_endpoint
from routes.model_routes import _visible_models
from src.env_flags import request_flag
def _mark_turn_start() -> None:
    """Start the turn clock (`P14-02`). Guarded: instrumentation must never be
    the reason a chat request fails to start."""
    try:
        from src.events import mark_turn_start
        mark_turn_start()
    except Exception:
        pass


from routes.chat_helpers import (
    approval_consume_message,
    escalation_withholds,
    note_escalation,
    resolve_session_auth,
    build_chat_context,
    save_assistant_response,
    run_post_response_tasks,
    accumulate_token_usage,
    clean_thinking_for_save,
    _allowed_models_for_request,
    _enforce_chat_privileges,
)
from src.action_intents import ToolIntent, classify_tool_intent as _classify_tool_intent
from src.image_model_ids import looks_like_image_generation_model
from src.tool_policy import (
    WEB_TOOL_NAMES,
    build_effective_tool_policy,
    is_web_search_explicitly_denied,
    web_search_enabled_for_turn,
)
from src.tool_approvals import (
    register_approval_expiry_listener,
    tool_approval_store,
)
from src.tool_approval_scopes import stamp_chat_session_grant
from src.tool_security import delegated_credential_blocked_tools
from src import tool_allow_rules

logger = logging.getLogger(__name__)

# Track active streams for partial-save safety net
_active_streams: Dict[str, dict] = {}


class ToolAllowRuleCreate(BaseModel):
    """Body of `POST /api/tool-allow-rules` (P7-04)."""

    tool_name: str
    match_kind: str
    pattern: Optional[str] = ""
    # Declared only so that a client which sends one is refused, rather than
    # having it silently rewritten to the caller. The stored owner always comes
    # from `_allow_rule_owner`.
    owner: Optional[str] = None


def _allow_rule_owner(request: Request) -> str:
    """The owner an allow-rule request may read and write, or a refusal.

    `require_user` first: it 403s a bearer API token — no token scope grants the
    right to lower an owner's confirmation gate — and 401s an unauthenticated
    caller. `storage_owner_for_request` then resolves the explicit no-login mode
    to the reserved local owner instead of the legacy NULL bucket, because a
    rule with no owner is a rule that matches for everybody.
    """
    require_user(request)
    owner = storage_owner_for_request(request)
    if not owner:
        raise HTTPException(403, "Allow rules need a signed-in owner")
    return owner

# How a refused steer answers on the wire. None of these may be 404, 405 or
# 501: `chatStream.js` reads exactly those three as "this build has no steer
# transport", hides the control and stops asking for the rest of the page's
# life — so a refusal that borrowed one would retire a working feature. The
# same rule binds the ownership refusal, which is why `chat_steer` re-stamps
# `_verify_session_owner`'s 404 as 403 instead of letting it through.
_STEER_REFUSAL_STATUS = {
    "no_active_run": 409,   # the session is the caller's; the run is over
    "too_many": 429,        # STEER_MAX_PENDING, counted in agent_loop
    "too_long": 400,        # STEER_MAX_CHARS, likewise
    "empty": 400,
}


def _stream_is_steerable(
    *,
    chat_mode: str,
    is_image_session: Union[bool, Callable[[], bool]],
    do_research: bool,
    compare_mode: bool = False,
) -> bool:
    """Whether a steer sent during this stream can actually reach the model.

    `stream_with_save` picks one of three destinations, and only the last of
    them drains the steer inbox (`consume_steers_for_round` and `clear_steers`
    exist nowhere else): an image-generation session generates and returns;
    ``chat_mode == "chat"`` goes to `stream_llm_with_fallback`; everything else
    runs the agent loop. Research is refused here even though it can end up on
    the agent branch: a research turn that actually researches returns from its
    own block before the three-way choice is made, and the one case that falls
    through (the clarifying-questions round) is not worth mirroring an inner
    `_skip_research` decision to catch. The cost of this conservatism is a
    steer that is queued instead of applied; the cost of the opposite error is
    the user's words accepted into an inbox nothing reads.

    ``compare_mode`` is a fourth refusal and a different KIND of one: a compare
    pane's stream is fine in itself, but it is returned raw and never reaches
    `agent_runs.start`, so `is_steerable` — which reads the registry — answers
    False for it no matter what this returns. It was previously outside the
    predicate because the only caller ran after compare mode had returned.
    `B14` gave the predicate a second reader, the `stream_steerable` event,
    which IS emitted on a compare pane; leaving the clause at one call site
    would have made the announcement the one inaccurate thing this produces.

    ``is_image_session`` accepts a thunk because it is the only expensive term:
    `_is_image_generation_session` opens a DB session and queries the endpoint
    table, while the other three are locals. The route cannot hand over the
    answer it already has — `image_generation_session` at `:1457` is computed
    BEFORE `build_chat_context` normalises the session's model, and this
    predicate's question is about the normalised one — so the choice is a second
    query or a deferred one. Deferred: a chat turn, a research turn and a compare
    pane are all settled by terms that are already in registers. Bools still
    work, and the table test passes them.

    Kept as one named predicate rather than an expression at the call sites so
    the four conditions are stated once, next to the reason for each.
    """
    if chat_mode == "chat" or do_research or compare_mode:
        return False
    return not (is_image_session() if callable(is_image_session) else is_image_session)


def _stream_failure_status(chunk: str) -> Optional[int]:
    """Extract a provider status without retaining provider-supplied detail."""

    try:
        for line in str(chunk or "").splitlines():
            if not line.startswith("data: "):
                continue
            status = json.loads(line[6:]).get("status")
            return _normalize_http_status(status)
    except json.JSONDecodeError:
        return None
    return None


def _reject_delegated_tool_approval(request: Request) -> None:
    """Refuse an approval answered by a bearer API token.

    `B70`. A tool approval records that a **human** authorized one dangerous
    action. A token is a delegated credential handed to an integration, so when
    it answers the prompt it triggered, nobody is asked and the gate collapses
    into an extra round trip. Owner and session already match here — the token
    is answering on behalf of the account that minted it — which is exactly why
    nothing else would have caught this.
    """
    if is_delegated_credential(request):
        raise HTTPException(
            403,
            "Tool approvals require an interactive session. "
            "API tokens cannot authorize a gated action.",
        )


def _mark_tool_approval_resolved(sess, approval_id: Any, decision: Any) -> bool:
    """Persist a consumed approval decision on its existing tool event."""

    approval_key = str(approval_id or "")
    normalized_decision = str(decision or "").strip().lower()
    if not approval_key or normalized_decision not in {"approve", "approve_task", "deny"}:
        return False

    message_id = None
    resolved_metadata = None
    for item in reversed(getattr(sess, "history", []) or []):
        metadata = getattr(item, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        tool_events = metadata.get("tool_events")
        if not isinstance(tool_events, list):
            continue
        for event in reversed(tool_events):
            ask_user = event.get("ask_user") if isinstance(event, dict) else None
            if not isinstance(ask_user, dict):
                continue
            if str(ask_user.get("approval_id") or "") != approval_key:
                continue
            ask_user["resolved"] = normalized_decision
            # B70. The signature is written only here, on the server's own
            # resolve path, so a card edited into a transcript never carries
            # one. `stamp_chat_session_grant` also *removes* a stale signature
            # when the decision is not a chat-session grant, so downgrading a
            # `deny` to an `approve` in the transcript does not resurrect one.
            stamp_chat_session_grant(
                ask_user,
                getattr(sess, "id", ""),
                normalized_decision,
            )
            message_id = metadata.get("_db_id")
            resolved_metadata = {
                key: value for key, value in metadata.items() if key != "_db_id"
            }
            break
        if resolved_metadata is not None:
            break

    if resolved_metadata is None or not message_id:
        return False

    db = SessionLocal()
    try:
        db_message = db.query(DBChatMessage).filter(
            DBChatMessage.id == message_id,
            DBChatMessage.session_id == str(getattr(sess, "id", "")),
        ).first()
        if db_message is None:
            return False
        db_message.meta_data = json.dumps(resolved_metadata)
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.exception("Failed to persist tool approval resolution")
        return False
    finally:
        db.close()


def deny_expired_tool_approval(pending) -> bool:
    """`P12-10`. Mark a lapsed card denied in the transcript that asked for it.

    The run that asked has already returned — it emitted the card and ended —
    so the only thing left holding the question is the persisted tool event
    the browser rebuilds the card from. Before this row nothing ever wrote
    `resolved` on it for a lapse, so a reloaded chat drew the card as live
    (`chatRenderer.renderAskUserCard` returns `null` only when `resolved` is
    set) and its buttons answered 409 on the click.

    This is the same field and the same writer an answered card uses, so there
    is one way a card becomes resolved and not two (`Law 14`). Returns whether
    the denial was written; `False` covers the ordinary cases — no session
    manager in this process (a CLI, a test), a session nobody has loaded, a
    card from a surface with no transcript.
    """
    manager = get_session_manager_instance()
    if manager is None:
        return False
    session_id = str(getattr(pending, "session_id", "") or "")
    approval_id = str(getattr(pending, "approval_id", "") or "")
    if not session_id or not approval_id:
        return False
    sess = (getattr(manager, "sessions", None) or {}).get(session_id)
    if sess is None:
        try:
            sess = manager.get_session(session_id)
        except Exception:
            return False
    if sess is None:
        return False
    try:
        return _mark_tool_approval_resolved(sess, approval_id, "deny")
    except Exception:
        logger.warning(
            "Could not mark lapsed tool approval %s denied", approval_id,
            exc_info=True,
        )
        return False


async def _tool_approval_resolution_stream(decision: str) -> AsyncGenerator[str, None]:
    yield f"data: {json.dumps({'type': 'tool_approval_resolved', 'decision': decision})}\n\n"
    yield "data: [DONE]\n\n"


def _chat_candidate_request_factory(
    messages,
    fallback_context_length: int = 0,
    *,
    session=None,
    owner: Optional[str] = None,
):
    """Shape one route-neutral Chat prompt for each candidate window."""

    state = {
        "requests": {},
        "context_lengths": {},
        "trim_stats": {},
        "compactions": {},
        "was_compacted": {},
    }

    async def factory(index, candidate_url, candidate_model, candidate_headers):
        compaction_state = {}
        candidate_messages, context_length, was_compacted = await maybe_compact(
            session,
            candidate_url,
            candidate_model,
            list(messages),
            candidate_headers,
            owner=owner,
            persist=False,
            compaction_state=compaction_state,
        )
        if not context_length:
            context_length = fallback_context_length
        request_messages = trim_for_context(candidate_messages, context_length)
        state["requests"][index] = request_messages
        state["context_lengths"][index] = context_length
        state["compactions"][index] = compaction_state
        state["was_compacted"][index] = was_compacted
        state["trim_stats"][index] = {
            "messages_before": len(messages),
            "messages_after": len(request_messages),
            "tokens_before": estimate_tokens(messages),
            "tokens_after": estimate_tokens(request_messages),
        }
        return {"messages": request_messages}

    return factory, state


def _candidate_index(candidates, actual_candidate) -> int:
    for index, candidate in enumerate(candidates):
        if candidate == actual_candidate:
            return index
    return 0


def _stream_set(session_id: str, **fields) -> None:
    """Update fields on the active-stream entry for `session_id`, or
    no-op if the entry has already been popped. Using .get() avoids a
    KeyError race between `if x in d` and `d[x]["k"] = v` if a sibling
    finally pops the key in between (which becomes possible the moment
    a coroutine cancellation reaches an inner cleanup before the
    outermost cleanup runs)."""
    rec = _active_streams.get(session_id)
    if rec is None:
        return
    rec.update(fields)


def _message_plain_text(content: Any) -> str:
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return str(content or "")


def _last_user_plain_text(messages: List[Dict[str, Any]]) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            return _message_plain_text(msg.get("content"))
    return ""


def _ensure_current_request_is_latest_user(messages: List[Dict[str, Any]], current_message: str) -> List[Dict[str, Any]]:
    """Defensively keep detached streams grounded on the request that created them."""
    current = str(current_message or "").strip()
    if not current:
        return messages
    latest = _last_user_plain_text(messages).strip()
    if latest == current or current in latest or latest in current:
        return messages
    logger.warning(
        "[chat_stream] latest user context mismatch; appending current request for model call. latest=%r current=%r",
        latest[:120],
        current[:120],
    )
    repaired = list(messages or [])
    repaired.append({"role": "user", "content": current})
    return repaired


_WEB_FOLLOWUP_RE = re.compile(
    r"^\s*(?:(?:can|could|would|will)\s+you\s+)?"
    r"(?:check|try\s+again|look(?:\s+now|\s+it\s+up)?|search(?:\s+now|\s+online|\s+it)?|"
    r"do\s+it|again|approved|approve(?:d)?|yes|ok(?:ay)?|proceed|go\s+ahead|"
    r"send(?:\s+it)?|submit(?:\s+it)?|email(?:\s+them|\s+it)?)\??\s*$",
    re.I,
)
_RECENT_WEB_CONTEXT_RE = re.compile(
    r"\b(?:weather|forecast|rain|raining|hourly|news|headlines|rate|exchange|currency|"
    r"price|current|latest|search|look\s+up|online)\b",
    re.I,
)
_RECENT_BROWSER_CONTEXT_RE = re.compile(
    r"\b(?:browser|browse|open\s+(?:the\s+)?(?:site|page|url|link)|click|"
    r"fill(?:\s+out)?|submit|send\s+(?:the\s+)?form|contact\s+form|web\s*form|"
    r"form\s+submission|playwright|automation)\b",
    re.I,
)
_BROWSER_MCP_TOOLS = {
    "mcp__builtin_browser__browser_navigate",
    "mcp__builtin_browser__browser_snapshot",
    "mcp__builtin_browser__browser_click",
    "mcp__builtin_browser__browser_type",
    "mcp__builtin_browser__browser_fill_form",
    "mcp__builtin_browser__browser_select_option",
    "mcp__builtin_browser__browser_press_key",
    "mcp__builtin_browser__browser_wait_for",
    "mcp__builtin_browser__browser_take_screenshot",
    "mcp__builtin_browser__browser_drag",
    "mcp__builtin_browser__browser_navigate_back",
    "mcp__builtin_browser__browser_close",
}


def _recent_session_text(sess, limit: int = 8, max_chars: int = 2000) -> str:
    history = getattr(sess, "history", None) or getattr(sess, "_history", None) or []
    chunks: List[str] = []
    for msg in history[-limit:]:
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        text = _message_plain_text(content).strip()
        if text:
            chunks.append(text)
    return " ".join(chunks)[-max_chars:]


def _is_contextual_web_followup(message: str, sess) -> bool:
    """Treat short retry/check replies as web lookups when recent context was web."""
    if not message or not _WEB_FOLLOWUP_RE.search(message):
        return False
    return bool(_RECENT_WEB_CONTEXT_RE.search(_recent_session_text(sess)))


def _is_contextual_browser_followup(message: str, sess) -> bool:
    """Treat short retry replies as browser tasks when recent context was forms/browser automation."""
    if not message or not _WEB_FOLLOWUP_RE.search(message):
        return False
    return bool(_RECENT_BROWSER_CONTEXT_RE.search(_recent_session_text(sess, limit=12, max_chars=4000)))


def _resolve_request_workspace(request, raw_value) -> tuple:
    """Resolve the posted workspace for this request: (workspace, rejected).

    Privilege is checked BEFORE the path ever touches the filesystem. Only
    admin/single-user callers can use the workspace-backed file/shell tools,
    so only they get vet_workspace() and the workspace_rejected signal. For
    any other caller the submitted value is dropped uniformly, with no vetting
    and no event: otherwise the presence/absence of workspace_rejected would
    let a non-admin chat caller probe which host paths exist.

    vet_workspace rejects non-directories, sensitive roots (.ssh, .gnupg,
    ...), and filesystem roots; on rejection there is no confinement and the
    default tool-path allowlist applies. The rejected value is surfaced so the
    stream can tell an admin client (which believes a workspace is active)
    that it was dropped.
    """
    requested = (raw_value or "").strip()
    if not requested:
        return "", ""
    from src.tool_security import owner_is_admin_or_single_user
    if not owner_is_admin_or_single_user(get_current_user(request)):
        return "", ""
    from src.tool_execution import vet_workspace
    workspace = vet_workspace(requested) or ""
    return workspace, (requested if not workspace else "")


_ABS_PATH_RE = re.compile(r"(?<!\S)(~?/[^\"'\s`<>]+)")
_LOCAL_FILE_TASK_RE = re.compile(
    r"\b(?:file|folder|directory|path|workspace|repo|project|movie|video|"
    r"subtitle|subtitles|srt|vtt|ass|download|save|rename|move|copy|extract|"
    r"convert|ffmpeg|run|execute|open|read|inspect|fix|debug|test|build)\b",
    re.IGNORECASE,
)


def _resolve_workspace_from_message_path(request, message: str) -> tuple[str, str]:
    """Auto-bind a workspace only when the user names an explicit safe path.

    This is intentionally deterministic rather than LLM/RAG-driven: RAG can
    choose the tool family, but filesystem binding must not let a prompt infer
    or probe arbitrary host paths. For a file path, bind its parent directory.
    For a directory path, bind that directory.
    """
    text = str(message or "")
    if not text or not _LOCAL_FILE_TASK_RE.search(text):
        return "", ""

    from src.tool_security import owner_is_admin_or_single_user
    if not owner_is_admin_or_single_user(get_current_user(request)):
        return "", ""

    from src.tool_execution import vet_workspace

    for match in _ABS_PATH_RE.finditer(text):
        raw = match.group(1).rstrip(".,;:)]}")
        expanded = os.path.realpath(os.path.expanduser(raw))
        candidates = [expanded]
        if os.path.isfile(expanded):
            candidates.insert(0, os.path.dirname(expanded))
        for candidate in candidates:
            workspace = vet_workspace(candidate) or ""
            if workspace:
                return workspace, ""
    return "", ""


def _session_url_matches_endpoint(session_url: str, endpoint_base: str) -> bool:
    if not session_url or not endpoint_base:
        return False
    sess = session_url.rstrip("/")
    base = _normalize_base(endpoint_base).rstrip("/")
    variants = {
        base,
        base + "/chat/completions",
        build_chat_url(base).rstrip("/"),
    }
    return sess in variants or sess.startswith(base + "/")


def _clear_orphaned_session_endpoint(sess, owner: str | None = None) -> bool:
    """Clear a session model if its endpoint was deleted from ModelEndpoint."""
    if not getattr(sess, "endpoint_url", ""):
        return False
    db = SessionLocal()
    try:
        q = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)
        if owner:
            from src.auth_helpers import owner_filter
            q = owner_filter(q, ModelEndpoint, owner)
        endpoints = q.all()
        for ep in endpoints:
            if _session_url_matches_endpoint(sess.endpoint_url or "", ep.base_url or ""):
                return False
        db_session = db.query(DBSession).filter(DBSession.id == sess.id).first()
        if db_session:
            db_session.endpoint_url = ""
            db_session.model = ""
            db_session.updated_at = datetime.utcnow()
            db.commit()
        sess.endpoint_url = ""
        sess.model = ""
        sess.headers = {}
        return True
    except Exception as e:
        logger.warning("Failed to clear orphaned session endpoint", exc_info=e)
        db.rollback()
        return False
    finally:
        db.close()


def _endpoint_cache_contains_model(endpoint, model: str) -> bool:
    """Return True when a populated endpoint model cache includes ``model``.

    Empty/malformed caches are treated as unknown rather than a negative match
    so older image endpoints without cached models still work.
    """
    raw = getattr(endpoint, "cached_models", None)
    if not raw:
        return True
    try:
        models = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as e:
        logger.warning("Failed to parse cached models list, treating as containing model", exc_info=e)
        return True
    if not isinstance(models, list) or not models:
        return True
    wanted = (model or "").strip()
    return wanted in {str(item).strip() for item in models}


def _is_image_generation_session(sess, owner: str | None = None) -> bool:
    """Whether this chat session should bypass text chat and generate images.

    Model-name prefixes are explicit image models. Endpoint type is only used
    when the current session endpoint actually matches that image endpoint, and
    when a populated endpoint model cache includes the selected model. This
    prevents an image endpoint on the same host from misrouting ordinary text
    models into the image-generation path.
    """
    model = (getattr(sess, "model", "") or "").strip()
    if looks_like_image_generation_model(model):
        return True

    endpoint_url = (getattr(sess, "endpoint_url", "") or "").strip()
    if not endpoint_url:
        return False

    db = SessionLocal()
    try:
        q = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)
        if owner:
            from src.auth_helpers import owner_filter
            q = owner_filter(q, ModelEndpoint, owner)
        endpoints = q.all()
        for endpoint in endpoints:
            if (getattr(endpoint, "model_type", None) or "llm") != "image":
                continue
            if not _session_url_matches_endpoint(endpoint_url, getattr(endpoint, "base_url", "") or ""):
                continue
            if _endpoint_cache_contains_model(endpoint, model):
                return True
    except Exception:
        return False
    finally:
        db.close()
    return False


def _first_image_attachment(chat_handler, att_ids: List[str], owner: str | None = None) -> Optional[Dict[str, Any]]:
    """Return the first attached image file that this owner can read."""
    upload_handler = getattr(chat_handler, "upload_handler", None)
    if not upload_handler:
        return None
    for att_id in att_ids or []:
        try:
            info = upload_handler.resolve_upload(att_id, owner=owner)
        except Exception as e:
            logger.warning("Failed to resolve image edit upload %s", att_id, exc_info=e)
            continue
        if not info:
            continue
        name = info.get("name") or info.get("original_name") or info.get("id") or ""
        mime = info.get("mime", "")
        try:
            if upload_handler.is_image_file(name, mime):
                return info
        except Exception:
            continue
    return None


def _recover_empty_session_model(sess, session_id: str, owner: str | None = None) -> bool:
    """Re-populate sess.model from the matching endpoint's cached models.

    Covers the window between endpoint setup and the first chat send: the
    picker showed a model in the dropdown but the session record never got
    written (Issue #587 — UI uses the cached endpoint list, not s.model).
    For ChatGPT Subscription, also repairs stale OpenAI API model names such as
    ``gpt-5`` that are not accepted by the Codex-backed ChatGPT account route.
    """
    current_model = (getattr(sess, "model", "") or "").strip()
    endpoint_url = (getattr(sess, "endpoint_url", "") or "").strip()
    is_chatgpt_subscription = False
    if current_model:
        try:
            from src.chatgpt_subscription import is_chatgpt_subscription_base
            is_chatgpt_subscription = is_chatgpt_subscription_base(endpoint_url)
            if not is_chatgpt_subscription:
                return False
        except Exception:
            return False
    db = SessionLocal()
    try:
        # Prefer the endpoint whose base URL matches the session — we know the
        # user already pointed this session at that endpoint, so its first
        # cached model is the most defensible default.
        ep = None
        if getattr(sess, "endpoint_url", ""):
            q = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)
            if owner:
                from src.auth_helpers import owner_filter
                q = owner_filter(q, ModelEndpoint, owner)
            endpoints = q.all()
            for cand in endpoints:
                if _session_url_matches_endpoint(sess.endpoint_url or "", cand.base_url or ""):
                    ep = cand
                    break
        if not ep:
            return False
        if not is_chatgpt_subscription:
            try:
                from src.chatgpt_subscription import is_chatgpt_subscription_base
                is_chatgpt_subscription = is_chatgpt_subscription_base(getattr(ep, "base_url", "") or endpoint_url)
            except Exception:
                is_chatgpt_subscription = False
        try:
            cached = json.loads(ep.cached_models) if isinstance(ep.cached_models, str) else (ep.cached_models or [])
        except Exception as e:
            logger.warning("Failed to parse cached_models for endpoint %r", getattr(ep, "id", "?"), exc_info=e)
            cached = []
        if not cached:
            visible = []
        else:
            try:
                visible = _visible_models(cached, getattr(ep, "hidden_models", None))
            except Exception:
                visible = cached
        if current_model and current_model in {str(item).strip() for item in visible}:
            return False
        if is_chatgpt_subscription:
            live_models = []
            if getattr(ep, "provider_auth_id", None):
                try:
                    from src.chatgpt_subscription import fetch_available_models
                    from src.endpoint_resolver import resolve_endpoint_runtime
                    _base, api_key = resolve_endpoint_runtime(ep, owner=owner)
                    if api_key:
                        live_models = fetch_available_models(api_key)
                        if live_models:
                            ep.cached_models = json.dumps(live_models)
                            db.commit()
                except Exception:
                    live_models = []
            # ChatGPT Subscription recovery must use the live Codex catalog.
            # Cached rows are only trusted above to avoid revalidating a model
            # that is already present in the visible picker list.
            cached = live_models
            if not cached:
                return False
            try:
                visible = _visible_models(cached, getattr(ep, "hidden_models", None))
            except Exception:
                visible = cached
            if current_model and current_model in {str(item).strip() for item in visible}:
                return False
        if not visible:
            return False
        model = visible[0]
        if not isinstance(model, str) or not model.strip():
            return False
        model = model.strip()
        # Persist so the next request, websocket reconnect, or page reload
        # picks up the same model (we'd otherwise re-pick on every send
        # and silently switch on the user if the cached order shifts).
        db_session_q = db.query(DBSession).filter(DBSession.id == session_id)
        if owner:
            db_session_q = db_session_q.filter(DBSession.owner == owner)
        db_session = db_session_q.first()
        if db_session:
            db_session.model = model
            db_session.updated_at = datetime.utcnow()
            db.commit()
        sess.model = model
        logger.info(
            "Recovered session model for %s — picked %r from endpoint %s",
            session_id, model, ep.id,
        )
        return True
    except Exception as e:
        db.rollback()
        logger.warning("Failed to recover empty session model for %s: %s", session_id, e)
    return False


def _reconcile_selected_route_from_request(
    request: Request,
    sess,
    session_id: str,
    form_data,
    owner: str | None = None,
) -> bool:
    """Apply the model route the browser selected before streaming.

    The frontend creates a pending chat first and only materializes it on first
    send. Startup/default-model refreshes can race with that UI state, so the
    stream request includes the route that was selected at click/send time.
    Trust only registered endpoint ids, or the session's existing endpoint URL.
    """
    selected_model = str(form_data.get("selected_model") or "").strip()
    selected_endpoint_id = str(form_data.get("selected_endpoint_id") or "").strip()
    selected_endpoint_url = str(form_data.get("selected_endpoint_url") or "").strip()
    if not selected_model:
        return False

    endpoint_url = ""
    headers = None
    if selected_endpoint_id or selected_endpoint_url:
        try:
            from src.auth_helpers import owner_filter
            from src.endpoint_resolver import build_headers, normalize_base
            db = SessionLocal()
            try:
                q = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)
                if selected_endpoint_id:
                    q = q.filter(ModelEndpoint.id == selected_endpoint_id)
                if owner:
                    q = owner_filter(q, ModelEndpoint, owner)
                candidates = q.all() if selected_endpoint_url and not selected_endpoint_id else [q.first()]
                ep = None
                for cand in candidates:
                    if not cand:
                        continue
                    if selected_endpoint_id or _session_url_matches_endpoint(selected_endpoint_url, cand.base_url or ""):
                        ep = cand
                        break
                if not ep:
                    return False
                endpoint_url = build_chat_url(normalize_base(ep.base_url or ""))
                headers = build_headers(ep.api_key or "", ep.base_url or "") if ep.api_key else {}
            finally:
                db.close()
        except Exception as e:
            logger.warning("Failed to resolve selected endpoint %s/%s for %s: %s", selected_endpoint_id, selected_endpoint_url, session_id, e)
            return False

    if not endpoint_url:
        return False

    if (
        selected_model == (getattr(sess, "model", "") or "")
        and endpoint_url == (getattr(sess, "endpoint_url", "") or "")
    ):
        return False

    sess.model = selected_model
    sess.endpoint_url = endpoint_url
    sess.headers = headers or {}
    db = SessionLocal()
    try:
        db_session = db.query(DBSession).filter(DBSession.id == session_id).first()
        if db_session:
            db_session.model = selected_model
            db_session.endpoint_url = endpoint_url
            db_session.headers = sess.headers or {}
            db_session.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
    logger.info("Reconciled selected route for %s: model=%r endpoint=%s", session_id, selected_model, redact_url(endpoint_url))
    return True


def _set_user_time_from_request(request: Request) -> None:
    """Copy browser timezone headers into the per-request context.

    This is intentionally ephemeral: it is used only while building prompts
    and running tools for this request. It is not persisted or logged.
    """
    try:
        tz_offset = request.headers.get("x-tz-offset")
        tz_name = request.headers.get("x-tz-name")
        from src.user_time import clear_user_time_context, set_user_tz_name, set_user_tz_offset

        clear_user_time_context()
        if tz_offset is not None:
            set_user_tz_offset(tz_offset)
        if tz_name:
            set_user_tz_name(tz_name)
    except Exception:
        pass


def setup_chat_routes(
    session_manager,
    chat_handler,
    chat_processor,
    memory_manager,
    research_handler,
    upload_handler,
    memory_vector=None,
    webhook_manager=None,
    skills_manager=None,
) -> APIRouter:
    # B70. Every chat surface requires the `chat` scope when the caller is a
    # bearer token; a browser session is unaffected.
    router = APIRouter(
        tags=["chat"],
        dependencies=[Depends(require_chat_api_token_scope)],
    )

    # `P12-10`. The store decides a lapsed approval is denied; this is the half
    # that makes the denial visible to whatever asked. Registered here because
    # this function runs once at boot and owns `_mark_tool_approval_resolved` —
    # a listener nothing registers is `Law 13`'s backend with no caller.
    # Registration is idempotent, so the test suite building the router several
    # times does not write a denial several times.
    register_approval_expiry_listener(deny_expired_tool_approval)

    # ------------------------------------------------------------------ #
    # POST /api/chat (non-streaming)
    # ------------------------------------------------------------------ #
    @router.post("/api/chat", response_model=Dict[str, Any])
    async def chat_endpoint(request: Request, chat_request: ChatRequest) -> Dict[str, Any]:
        require_api_token_scope(request, "chat")
        _set_user_time_from_request(request)
        _mark_turn_start()   # P14-02 — the clock read at accumulate_token_usage

        message = chat_request.message
        session = chat_request.session
        att_ids = chat_request.attachments or []
        use_web = chat_request.use_web
        use_research = chat_request.use_research
        time_filter = chat_request.time_filter
        preset_id = chat_request.preset_id

        # Verify the caller owns this session before loading it.
        # Without this, any authenticated user can post into another user's chat.
        _verify_session_owner(request, session)

        try:
            sess = session_manager.get_session(session)
        except KeyError:
            raise HTTPException(404, f"Session '{session}' not found")
        owner = effective_user(request)
        if _clear_orphaned_session_endpoint(sess, owner=owner):
            raise HTTPException(400, "Selected model endpoint was removed. Pick another model in Settings.")

        # Empty model + live endpoint = setup race (Issue #587). Repair from
        # the endpoint's cached model list before privilege checks, which
        # otherwise see "" and behave inconsistently with the allowlist.
        _recover_empty_session_model(sess, session, owner=owner)
        if not getattr(sess, "model", "").strip():
            raise HTTPException(
                400,
                "No model selected for this chat. Open the model picker and choose one before sending.",
            )
        if not (getattr(sess, "endpoint_url", "") or "").strip():
            raise HTTPException(400, "Selected model endpoint is not configured")

        # Same allowed_models + daily-cap gate as chat_stream (mirror so the
        # non-streaming path can't be used to bypass).
        _enforce_chat_privileges(request, sess)

        tool_policy = build_effective_tool_policy(last_user_message=message)
        allow_tool_preprocessing = not tool_policy.block_all_tool_calls

        # Inline memory command
        memory_response = None
        if not tool_policy.blocks("manage_memory"):
            memory_response = await chat_handler.handle_memory_command(sess, message)
        if memory_response:
            return {"response": memory_response}

        foreground_policy = resolve_foreground_model_policy(
            owner=owner,
            allowed_models=_allowed_models_for_request(request),
        )

        # Build shared context (preset, preprocess, preface, compact)
        ctx = await build_chat_context(
            sess, request, chat_handler, chat_processor,
            message=message,
            session_id=session,
            preset_id=preset_id,
            att_ids=att_ids,
            use_web=use_web,
            time_filter=time_filter,
            webhook_manager=webhook_manager,
            allow_tool_preprocessing=allow_tool_preprocessing,
            defer_context_shaping=foreground_policy.enabled,
        )

        # Research injection
        research_blocked_by_policy = (
            tool_policy.blocks("trigger_research")
            or tool_policy.blocks("manage_research")
        )
        if use_research and not research_blocked_by_policy:
            try:
                _r_ep, _r_model, _r_headers = _resolve_research_endpoint(sess)
                research_ctx = await research_handler.call_research_service(
                    message, _r_ep, _r_model, llm_headers=_r_headers
                )
                research_message = untrusted_context_message("research context", research_ctx)
                ctx.messages.insert(len(ctx.preface), research_message)
                if foreground_policy.enabled:
                    getattr(ctx, "route_messages", ctx.messages).insert(
                        len(ctx.preface),
                        research_message,
                    )
            except Exception as e:
                logger.error(f"Research failed: {e}")

        foreground_candidates = build_foreground_model_candidates(
            sess.endpoint_url,
            sess.model,
            sess.headers,
            owner=owner,
            policy=foreground_policy,
        )
        route_descriptors = build_foreground_route_descriptors(
            sess.endpoint_url,
            sess.model,
            sess.headers,
            owner=owner,
            policy=foreground_policy,
            selected_endpoint_id=chat_request.selected_endpoint_id,
        )
        candidate_request_factory = None
        selected_context_length = getattr(ctx, "context_length", 0)
        candidate_request_state = {
            "context_lengths": {0: selected_context_length},
            "requests": {0: ctx.messages},
            "trim_stats": {},
        }
        request_messages = ctx.messages
        if foreground_policy.enabled:
            request_messages = getattr(ctx, "route_messages", ctx.messages)
            candidate_request_factory, candidate_request_state = _chat_candidate_request_factory(
                request_messages,
                selected_context_length,
                session=sess,
                owner=owner,
            )
        requested_model = sess.model
        reply, actual_candidate, actual_model = await llm_call_async_with_route_fallback(
            foreground_candidates,
            request_messages,
            fallback_statuses=foreground_policy.eligible_statuses,
            candidate_request_factory=candidate_request_factory,
            temperature=ctx.preset.temperature,
            max_tokens=ctx.preset.max_tokens,
            prompt_type=preset_id,
            session_id=session,
        )
        actual_index = _candidate_index(foreground_candidates, actual_candidate)
        apply_compaction_state(
            sess,
            candidate_request_state.get("compactions", {}).get(actual_index),
        )
        requested_route = route_descriptors[0]
        actual_route = route_descriptors[actual_index]
        actual_trim = candidate_request_state.get("trim_stats", {}).get(actual_index, {})
        _clean_reply, _clean_md = clean_thinking_for_save(
            reply,
            {
                "model": actual_model,
                "requested_model": requested_model,
                "endpoint_id": actual_route.get("endpoint_id"),
                "endpoint_label": actual_route.get("endpoint_label"),
                "requested_endpoint_id": requested_route.get("endpoint_id"),
                "requested_endpoint_label": requested_route.get("endpoint_label"),
                "context_length": candidate_request_state["context_lengths"].get(
                    actual_index,
                    selected_context_length,
                ),
                "context_trimmed": bool(
                    actual_trim
                    and (
                        actual_trim.get("messages_after") < actual_trim.get("messages_before")
                        or actual_trim.get("tokens_after") < actual_trim.get("tokens_before")
                    )
                ),
            },
        )
        sess.add_message(ChatMessage("assistant", _clean_reply, metadata=_clean_md))

        from core.database import update_session_last_accessed
        update_session_last_accessed(session)
        session_manager.save_sessions()

        # Background tasks (memory, webhook, auto-name)
        run_post_response_tasks(
            sess, session_manager, session, message, reply, None,
            ctx.uprefs, memory_manager, memory_vector, webhook_manager,
            character_name=ctx.preset.character_name,
            owner=ctx.user,
            allow_background_extraction=not tool_policy.block_all_tool_calls,
        )

        return {
            "response": reply,
            "requested_model": requested_model,
            "model": actual_model,
            "requested_endpoint_id": requested_route.get("endpoint_id"),
            "requested_endpoint_label": requested_route.get("endpoint_label"),
            "endpoint_id": actual_route.get("endpoint_id"),
            "endpoint_label": actual_route.get("endpoint_label"),
        }

    # ------------------------------------------------------------------ #
    # POST /api/chat_stream
    # ------------------------------------------------------------------ #
    @router.post("/api/chat_stream")
    async def chat_stream(request: Request) -> StreamingResponse:
        require_api_token_scope(request, "chat")
        _mark_turn_start()   # P14-02 — the clock read at accumulate_token_usage
        body = None
        try:
            if request.headers.get("content-type", "").startswith("application/json"):
                try:
                    body = await request.json()
                except json.JSONDecodeError as e:
                    raise HTTPException(400, f"Invalid JSON: {e}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"Request parsing error: {e}")

        _set_user_time_from_request(request)

        form_data = await request.form()
        message = form_data.get("message")
        session = form_data.get("session")
        attachments = form_data.get("attachments")
        use_web = form_data.get("use_web")
        use_research = form_data.get("use_research")
        time_filter = form_data.get("time_filter")
        preset_id = form_data.get("preset_id")
        selected_endpoint_id = str(
            form_data.get("selected_endpoint_id")
            or (body or {}).get("selected_endpoint_id")
            or ""
        ).strip()
        # Issue #3229: API callers send JSON, not FormData.  Read from the
        # JSON body as fallback so callers who send {"allow_bash": true}
        # actually get bash enabled.
        allow_bash = form_data.get("allow_bash") or (body or {}).get("allow_bash")
        allow_web_search = form_data.get("allow_web_search") or (body or {}).get("allow_web_search")
        use_rag = form_data.get("use_rag")
        search_context = form_data.get("search_context")  # pre-fetched web search results (compare mode)
        # `B97`. Five fields, one rule. These read `.lower() == "true"` until
        # 2026-09-15 — the same spelling thirteen HTTP sites used and the same
        # one `routes/model_routes._truthy` had already stopped using, with
        # neither reachable from the other's callers. `request_truthy` widens
        # each of them to the eight words `.env.example` documents and narrows
        # none: our own composer sends the literal `'true'`/`'false'`, so what
        # changes is only the answer given to a hand-written `plan_mode=1`,
        # which used to mean *no* on a safety mode.
        compare_mode = request_flag(form_data.get("compare_mode"))
        incognito = request_flag(form_data.get("incognito"))
        plan_mode = request_flag(form_data.get("plan_mode") or (body or {}).get("plan_mode"))
        chat_mode = str(form_data.get("mode", "")).lower()  # 'chat' or 'agent'
        tool_approval_id = (
            form_data.get("tool_approval_id")
            or (body or {}).get("tool_approval_id")
        )
        tool_approval_decision = (
            form_data.get("tool_approval_decision")
            or (body or {}).get("tool_approval_decision")
        )
        exact_tool_approval = None
        pending_tool_approval = None
        retired_tool_approval_taint = False
        external_untrusted_context_seen = False
        tool_approval_continuation = False
        # Workspace: confine the agent's file/shell tools to this folder.
        workspace, workspace_rejected = _resolve_request_workspace(
            request, form_data.get("workspace")
        )
        # Plan mode is a modifier on agent mode — it only makes sense with tools.
        if plan_mode:
            chat_mode = "agent"
        # An approved plan being EXECUTED: the frontend sends the checklist back
        # on each turn so we can pin it in context. This way a long plan on a
        # weak model survives history truncation — the agent can always re-read
        # the plan. Ignored while still proposing (plan_mode on). Capped so a
        # huge plan can't blow the prompt.
        approved_plan = ""
        if not plan_mode:
            approved_plan = (form_data.get("approved_plan") or "").strip()[:8192]
        # Did the USER explicitly pick agent mode? (vs. us auto-escalating
        # below). Skill extraction should only learn from real agent sessions,
        # not chats we quietly promoted for a notes/calendar intent.
        user_requested_agent = (chat_mode == "agent")
        _search_enabled = web_search_enabled_for_turn(allow_web_search, use_web)
        _explicit_web_intent = False
        _explicit_browser_intent = False
        if isinstance(message, str):
            _msg_l = message.lower()
            _explicit_web_intent = bool(re.search(
                r"\b(search|look\s*up|lookup|google|browse|web|online|latest|current|today|news|weather|forecast|rate|exchange\s+rate)\b",
                _msg_l,
            ))
            _explicit_browser_intent = bool(re.search(
                r"\b(browser|browse|open\s+(?:the\s+)?(?:site|page|url|link)|"
                r"click|fill(?:\s+out)?|submit|send\s+(?:the\s+)?form|"
                r"contact\s+form|web\s*form|form\s+submission)\b",
                _msg_l,
            ))
        _allow_browser_for_web_turn = bool(
            _explicit_browser_intent
            or _explicit_web_intent
            or _search_enabled
        )
        # Intent auto-escalation: if the user is clearly asking the assistant
        # to create a todo, reminder, or calendar event, promote chat → agent
        # for this turn so the LLM has access to manage_notes / manage_calendar.
        # This is a LIGHT promotion — see the disabled_tools block below, which
        # withholds shell/code/file tools so the model doesn't try to `bash`
        # its way through a plain chat request (and fail, especially with the
        # shell disabled).
        _escalations: list[str] = []

        def _escalate(why: str) -> bool:
            return note_escalation(_escalations, why)

        auto_escalated = False
        _tool_intent = _classify_tool_intent(message) if isinstance(message, str) else None
        _workspace_agent_intent = False
        if chat_mode == "chat" and _tool_intent and _tool_intent.needs_tools:
            chat_mode = "agent"
            auto_escalated = _escalate(
                f"{_tool_intent.category}: {_tool_intent.reason}")
            _workspace_agent_intent = _tool_intent.category in {"shell", "workspace"}
            if _workspace_agent_intent:
                allow_bash = "true"
        elif chat_mode == "chat" and _search_enabled:
            chat_mode = "agent"
            auto_escalated = _escalate("web search is switched on for this chat")
        elif chat_mode == "chat" and _explicit_web_intent:
            chat_mode = "agent"
            auto_escalated = _escalate("the message asks for something on the web")
        active_doc_id = form_data.get("active_doc_id", "").strip()
        logger.info(f"[doc-inject] chat_mode={chat_mode}, active_doc_id={active_doc_id!r}")

        # Active email reader — when the user has an email open in the UI, the
        # frontend passes its uid/folder/account so "reply", "summarize this",
        # etc. resolve to the real email instead of the agent inventing a
        # fake markdown draft.
        active_email_uid = form_data.get("active_email_uid", "").strip()
        active_email_folder = form_data.get("active_email_folder", "INBOX").strip() or "INBOX"
        active_email_account = form_data.get("active_email_account", "").strip()
        active_email_ctx: Optional[Dict[str, str]] = None
        # Always reset between requests so a stale active-email pointer from
        # a previous turn (different reader closed, different account, etc.)
        # can't leak in when the user has no email open this turn.
        try:
            from src.tool_implementations import clear_active_email
            clear_active_email()
        except Exception:
            pass
        if active_email_uid:
            active_email_ctx = {
                "uid": active_email_uid,
                "folder": active_email_folder,
                "account": active_email_account,
            }
            # Try to enrich with subject + from so the agent's system prompt
            # block can quote them. Best-effort: a stale cache is fine, a
            # missing email just means we pass uid/folder/account only.
            try:
                from routes.email_routes import _read_cache_get, _read_cache_key
                _ck = _read_cache_key(active_email_account or None, active_email_folder, active_email_uid, owner=get_current_user(request))
                _cached_email = _read_cache_get(_ck)
                if _cached_email and isinstance(_cached_email, dict):
                    active_email_ctx["subject"] = str(_cached_email.get("subject") or "")
                    active_email_ctx["from"] = str(
                        _cached_email.get("from_address")
                        or _cached_email.get("from")
                        or _cached_email.get("from_name")
                        or ""
                    )
                    _body_preview = (_cached_email.get("body") or "")[:2000]
                    if _body_preview:
                        active_email_ctx["body_preview"] = _body_preview
            except Exception as _e:
                logger.debug(f"[email-inject] cache enrich skipped: {_e}")
            # Stash so email tools can resolve "this email" without UID guessing.
            try:
                from src.tool_implementations import set_active_email
                set_active_email(
                    uid=active_email_uid,
                    folder=active_email_folder,
                    account=active_email_account or None,
                    subject=active_email_ctx.get("subject"),
                    sender=active_email_ctx.get("from"),
                )
            except Exception as _e:
                logger.debug(f"[email-inject] set_active_email failed: {_e}")
            logger.info(
                "[email-inject] active_email uid=%s folder=%s account=%s subject=%r",
                active_email_uid, active_email_folder, active_email_account or "(default)",
                active_email_ctx.get("subject", ""),
            )

        try:
            # Attachment-only sends and approval controls may omit message text.
            _has_atts = (
                bool(body and isinstance(body.get("attachments"), list) and body["attachments"])
                or bool(form_data.get("attachments"))
            )
            message, session = coerce_message_and_session(
                body, message, session, session_manager,
                allow_empty=(_has_atts or bool(tool_approval_id)),
            )
            # Verify ownership AFTER coerce (which may resolve a default session)
            # but BEFORE loading. Prevents cross-user session hijack.
            _verify_session_owner(request, session)
            sess = session_manager.get_session(session)
            owner = effective_user(request)
            if tool_approval_id:
                _reject_delegated_tool_approval(request)
                pending_tool_approval = tool_approval_store.peek(tool_approval_id)
                normalized_owner = str(owner or "").strip().casefold()
                if (
                    pending_tool_approval is None
                    or pending_tool_approval.owner != normalized_owner
                    or pending_tool_approval.session_id != str(session)
                ):
                    raise HTTPException(
                        409,
                        "This tool approval is invalid, expired, or belongs to another thread.",
                    )
                pending_taint = bool(
                    pending_tool_approval.external_untrusted_context_seen
                )
                external_untrusted_context_seen = (
                    external_untrusted_context_seen or pending_taint
                )
                decision = str(tool_approval_decision or "").strip().lower()
                if decision not in {"approve", "approve_task", "deny"}:
                    raise HTTPException(400, "Invalid tool approval decision.")
                if plan_mode:
                    raise HTTPException(
                        409,
                        "Tool approvals cannot be consumed while plan mode is active.",
                    )
                # `P4-21`. Four different things produce `None` here and only
                # one of them is fixable by asking again. "Could not be
                # consumed" was the same sentence for a card that lapsed after
                # ten minutes, a card belonging to somebody else, an id that
                # never existed, and a decision value nothing recognises.
                _approval_outcome: dict = {}
                exact_tool_approval = tool_approval_store.consume(
                    tool_approval_id,
                    decision=decision,
                    owner=owner,
                    session_id=session,
                    outcome=_approval_outcome,
                )
                tool_approval_continuation = True
                if (
                    decision in {"approve", "approve_task"}
                    and exact_tool_approval is None
                ):
                    raise HTTPException(
                        409,
                        approval_consume_message(_approval_outcome.get("reason")),
                    )
                if not _mark_tool_approval_resolved(
                    sess,
                    tool_approval_id,
                    decision,
                ):
                    logger.warning(
                        "Tool approval %s was consumed but its persisted card could not be marked resolved",
                        tool_approval_id,
                    )
                if decision == "deny":
                    return StreamingResponse(
                        _tool_approval_resolution_stream(decision),
                        media_type="text/event-stream",
                    )
                # Approval is a control-plane continuation, not a new user turn.
                # Reuse the sealed interrupted request only for internal context,
                # retrieval, and policy reconstruction; never persist or display it.
                message = pending_tool_approval.continuation_query
                # The sealed server record, not mutable composer state,
                # restores the original action workspace.
                workspace = pending_tool_approval.workspace or None
                workspace_rejected = None
                if pending_tool_approval.document_id:
                    active_doc_id = pending_tool_approval.document_id
                # Restore only the coarse request toggle needed by the exact
                # sealed action. Current privilege, global-disable, incognito,
                # compare, and tool-policy gates still run.
                if pending_tool_approval.tool_name == "bash":
                    allow_bash = "true"
                if pending_tool_approval.tool_name in WEB_TOOL_NAMES:
                    allow_web_search = "true"
                    _search_enabled = True
                chat_mode = "agent"
            else:
                # A normal user message supersedes the card that was waiting
                # in this thread. Retire its opaque grant, but preserve the
                # originating provenance for this turn so dismissing a card
                # cannot make the same model-requested action authoritative.
                retired_tool_approval_taint = tool_approval_store.retire_for_session(
                    owner=owner,
                    session_id=session,
                )
                external_untrusted_context_seen = (
                    external_untrusted_context_seen or retired_tool_approval_taint
                )
            _reconcile_selected_route_from_request(request, sess, session, form_data, owner=owner)
            if _clear_orphaned_session_endpoint(sess, owner=owner):
                raise HTTPException(400, "Selected model endpoint was removed. Pick another model in Settings.")
            # Issue #587: picker shows a model from the endpoint cache but
            # s.model never made it onto the DB row (first-send race after
            # endpoint setup, or a previous endpoint delete/recreate). Pull
            # the first cached model off the matching endpoint so the
            # upstream isn't called with model="" (which surfaces as a
            # generic 401/503).
            _recover_empty_session_model(sess, session, owner=owner)
            if not getattr(sess, "model", "").strip():
                raise HTTPException(
                    400,
                    "No model selected for this chat. Open the model picker and choose one before sending.",
                )
            if not (getattr(sess, "endpoint_url", "") or "").strip():
                raise HTTPException(400, "Selected model endpoint is not configured")
            if (
                chat_mode == "chat"
                and isinstance(message, str)
                and (not _tool_intent or not _tool_intent.needs_tools)
                and _is_contextual_web_followup(message, sess)
            ):
                _tool_intent = ToolIntent(True, "web", "contextual web lookup follow-up")
                chat_mode = "agent"
                auto_escalated = _escalate(
                    f"{_tool_intent.category}: {_tool_intent.reason}")
                _workspace_agent_intent = False
            if isinstance(message, str) and _is_contextual_browser_followup(message, sess):
                _explicit_browser_intent = True
                if chat_mode == "chat":
                    chat_mode = "agent"
                    auto_escalated = _escalate(
                        "a follow-up to something already open in the browser")
                    _workspace_agent_intent = False
            if not workspace and isinstance(message, str):
                _auto_workspace, _ = _resolve_workspace_from_message_path(request, message)
                if _auto_workspace:
                    workspace = _auto_workspace
                    chat_mode = "agent"
                    auto_escalated = _escalate(
                        f"the message names a path in {workspace}")
                    _workspace_agent_intent = True
                    allow_bash = "true"
        except SessionNotFoundError as e:
            raise HTTPException(404, str(e))
        except (ValueError, ValidationError):
            raise HTTPException(400, "Invalid request parameters")

        # ------------------------------------------------------------------ #
        # Privilege gates that must fire BEFORE any LLM work / token spend.
        #   1. allowed_models — reject if session.model isn't in the user's
        #      configured allowlist (empty list = "no restriction").
        #   2. max_messages_per_day — count user-role ChatMessage rows owned
        #      by this user in the last UTC day; 429 if at/over the cap.
        # Admins always have full privileges via get_privileges (returns
        # ADMIN_PRIVILEGES wholesale) so this is a no-op for them.
        _enforce_chat_privileges(request, sess)

        # Ensure session has auth headers
        resolve_session_auth(sess, session, owner=effective_user(request))

        # Check for research_pending BEFORE mode persist overwrites it
        # An approval response resumes the sealed agent action.  Do not let
        # mutable form fields, or a stale research_pending session marker,
        # consume the one-use grant on the unrelated research path.
        do_research = (
            not tool_approval_continuation
            and request_flag(use_research)  # `B97`
        )
        if not do_research and not tool_approval_continuation:
            if get_session_mode(session) == 'research_pending':
                do_research = True
                logger.info(f"Session {session} in research_pending — auto-triggering research")

        att_ids = []
        if tool_approval_continuation:
            # Browser composer state is unrelated to the action that was
            # reviewed.  The original turn remains in session history.
            att_ids = []
        elif body and isinstance(body.get("attachments"), list):
            att_ids = [str(x) for x in body["attachments"]]
        elif attachments:
            try:
                att_ids = [str(x) for x in json.loads(attachments)]
            except Exception as e:
                logger.warning("Failed to parse attachments JSON, ignoring attachments", exc_info=e)

        image_generation_session = _is_image_generation_session(sess, owner=effective_user(request))
        no_memory = request_flag(form_data.get("no_memory"))  # `B97`
        if image_generation_session:
            no_memory = True
            use_rag = "false"
            search_context = None
        pre_context_tool_policy = build_effective_tool_policy(
            last_user_message=message,
        )
        allow_tool_preprocessing = not pre_context_tool_policy.block_all_tool_calls
        foreground_policy = resolve_foreground_model_policy(
            owner=owner,
            allowed_models=_allowed_models_for_request(request),
        )

        # Build shared context (stream path uses enhanced_message for context preface)
        ctx = await build_chat_context(
            sess, request, chat_handler, chat_processor,
            message=message,
            session_id=session,
            preset_id=preset_id,
            att_ids=att_ids,
            use_web=use_web,
            use_rag=use_rag,
            time_filter=time_filter,
            incognito=incognito,
            no_memory=no_memory,
            search_context=search_context,
            compare_mode=compare_mode,
            webhook_manager=webhook_manager,
            use_enhanced_message=True,
            # Skills index only ships when the model can actually call
            # manage_skills (agent mode). In plain chat or incognito the
            # index would be useless / unwanted noise.
            agent_mode=(chat_mode == "agent"),
            allow_tool_preprocessing=allow_tool_preprocessing,
            defer_context_shaping=foreground_policy.enabled,
            continuation_context_message=(
                pending_tool_approval.continuation_query
                if exact_tool_approval
                and pending_tool_approval
                and pending_tool_approval.continuation_query
                else None
            ),
            persist_user_message=not tool_approval_continuation,
        )

        _research_flags = {"do": do_research}  # Mutable container for generator scope

        # Query active document — prefer explicit ID from frontend, fall back to session lookup
        active_doc = None
        _doc_db = SessionLocal()
        try:
            if active_doc_id:
                logger.info(f"[doc-inject] active_doc_id from frontend: {active_doc_id}")
                # Scope to the caller's documents. The session and in-memory
                # fallbacks below are already owner/session-bound; this
                # explicit-id path looked up by id alone, so a user could
                # inject another user's document by passing its id.
                _doc_q = _doc_db.query(DBDocument).filter(DBDocument.id == active_doc_id)
                active_doc = _owner_session_filter(_doc_q, ctx.user).first()
                if active_doc:
                    doc_session = active_doc.session_id
                    doc_owner = getattr(active_doc, "owner", None)
                    if doc_owner and ctx.user and doc_owner != ctx.user:
                        logger.warning(
                            "[doc-inject] ignoring active_doc_id %s owned by another user",
                            active_doc_id,
                        )
                        active_doc = None
                    else:
                        # NOTE: previously dropped the doc when doc.session_id
                        # != current chat session — but that broke the common
                        # case of "open an email draft from one chat, ask a
                        # different chat to write into it". The frontend only
                        # sends active_doc_id for docs currently visible in
                        # the UI, and we already owner-checked above, so trust
                        # the explicit signal. We just log the mismatch and
                        # re-bind the doc to the current session so future
                        # turns find it via the session-fallback path too.
                        if doc_session and doc_session != session:
                            logger.info(
                                "[doc-inject] cross-session active_doc_id %s (was session %s, now %s) — accepting and rebinding",
                                active_doc_id, doc_session, session,
                            )
                            try:
                                active_doc.session_id = session
                                _doc_db.commit()
                            except Exception as _e:
                                _doc_db.rollback()
                                logger.warning(f"[doc-inject] session rebind failed: {_e}")
                        logger.info(f"[doc-inject] found by ID: title={active_doc.title!r}, lang={active_doc.language!r}, is_active={active_doc.is_active}, content_len={len(active_doc.current_content or '')}")
                else:
                    logger.warning(f"[doc-inject] NOT FOUND by ID {active_doc_id}")
            if not active_doc:
                _email_doc_q = _doc_db.query(DBDocument).filter(
                    DBDocument.session_id == session,
                    DBDocument.is_active == True,
                    DBDocument.language == "email",
                )
                active_doc = _owner_session_filter(_email_doc_q, ctx.user).order_by(DBDocument.updated_at.desc()).first()
                if active_doc:
                    logger.info(f"[doc-inject] found email draft by session fallback: title={active_doc.title!r}")
            if not active_doc:
                _session_doc_q = _doc_db.query(DBDocument).filter(
                    DBDocument.session_id == session,
                    DBDocument.is_active == True
                )
                active_doc = _owner_session_filter(_session_doc_q, ctx.user).order_by(DBDocument.updated_at.desc()).first()
                if active_doc:
                    logger.info(f"[doc-inject] found by session fallback: title={active_doc.title!r}")
            # Last resort: the document the agent itself just created/edited
            # (tracked in-memory by the tool layer). This rescues docs that
            # got orphaned from their session (session_id NULL) — otherwise
            # neither lookup above can associate them with this conversation,
            # so the agent never sees what it just wrote. Guarded so we never
            # leak a doc that belongs to a DIFFERENT session.
            if not active_doc:
                try:
                    from src.agent_tools.document_tools import get_active_document
                    _mem_id = get_active_document()
                    if _mem_id:
                        _mem_q = _doc_db.query(DBDocument).filter(DBDocument.id == _mem_id)
                        cand = _owner_session_filter(_mem_q, ctx.user).first()
                        if cand and (not cand.session_id or cand.session_id == session):
                            active_doc = cand
                            logger.info(f"[doc-inject] found by in-memory active id: title={active_doc.title!r} (session_id={cand.session_id!r})")
                except Exception as _e:
                    logger.debug(f"[doc-inject] in-memory fallback failed: {_e}")
            if not active_doc:
                logger.info(f"[doc-inject] no active doc for session {session}")
            if active_doc:
                _doc_db.expunge(active_doc)
        except Exception as e:
            logger.warning(f"Failed to query active document: {e}")
        finally:
            _doc_db.close()

        # Build disabled-tools set from frontend toggles + user privileges
        disabled_tools = set()
        # B70. Minting is admin-only, so every owner-keyed check below answers
        # "admin" for a token. Cap it at the non-admin policy instead;
        # `stream_agent_loop` repeats this from `delegated_credential` so the
        # cap holds even for a caller that does not come through this route.
        _delegated_credential = is_delegated_credential(request)
        if _delegated_credential:
            disabled_tools.update(delegated_credential_blocked_tools())
        # Only disable bash when the caller *explicitly* set it to a falsy
        # value. When unset (None), defer to per-user privilege checks below.
        # Web search is per-turn opt-in: either the chat pre-search setting
        # (`use_web=true`) or agent web toggle (`allow_web_search=true`) must
        # explicitly enable it.
        # flag-spelling: `B97` holds this one. Every other HTTP field in this
        # route moved to `request_truthy`, which reads `1`/`yes`/`on` as yes;
        # here that would turn `allow_bash=1` from *shell denied* into *shell
        # granted* for any caller already sending it. Widening a gate is not the
        # same act as honouring an intent, and this gate governs the container
        # shell and the host shell together (`P17-11`). Same hold, and the same
        # reason, as the nine environment switches `B91` could not move: each
        # of those carries its reason at its own line too.
        if allow_bash is not None and str(allow_bash).lower() != "true":
            # `P17-11`. One switch, two places. The chat's "enable shell" toggle
            # governs the container shell and the host shell together, because a
            # second control for "may the agent run commands" is a second thing
            # to forget to turn off (`Law 14`). The host one is the more
            # consequential of the two, so it must never be the one still on.
            disabled_tools.update({"bash", "host_shell"})
        _explicit_web_intent = _explicit_web_intent or bool(_tool_intent and _tool_intent.category == "web")
        if is_web_search_explicitly_denied(allow_web_search) or not _search_enabled:
            disabled_tools.update(WEB_TOOL_NAMES)
        if _explicit_web_intent:
            # A direct lookup/search request should not drift into personal
            # tools or shell fallbacks. It can only use web_search/web_fetch
            # when the request's explicit web setting enabled them.
            disabled_tools.update({
                "bash", "host_shell", "python",
                "search_chats", "manage_skills", "manage_memory",
                "read_file", "write_file", "edit_file",
                "create_document", "edit_document", "update_document",
                "send_email", "reply_to_email",
                "manage_notes", "manage_calendar", "manage_tasks",
                "api_call",
            })
            if _search_enabled:
                disabled_tools.difference_update(WEB_TOOL_NAMES)
            else:
                disabled_tools.update(WEB_TOOL_NAMES)
        elif _search_enabled:
            disabled_tools.difference_update(WEB_TOOL_NAMES)

        # Nobody/incognito mode: deny tools that would expose the user's
        # persistent memory, past chats, or other identity-linked data.
        if incognito:
            disabled_tools.update({
                "manage_memory",      # persistent memory store
                "search_chats",       # past chat history
                "manage_skills",      # skill presets tied to user
                "create_session",
                "list_sessions",
                "manage_session",
                "send_to_session",
                "chat_with_model",
            })

        # Active email reader open → strip the tools that let the agent drift
        # away from the visible email or skip review. The only allowed compose
        # path is ui_control open_email_reply, which opens the same draft editor
        # as the Reply button with the generated body pre-filled. This prevents
        # the model from falling back to direct SMTP when it botches a draft
        # call, and prevents fake email-shaped documents.
        if active_email_ctx and active_email_ctx.get("uid"):
            disabled_tools.update({
                "create_document",
                "send_email",
                "reply_to_email",
                "mcp__email__send_email",
                "mcp__email__reply_to_email",
            })

        # Enforce per-user privileges
        _privs = {}
        _user = ctx.user
        if _user and hasattr(request.app.state, 'auth_manager') and request.app.state.auth_manager:
            _privs = request.app.state.auth_manager.get_privileges(_user)
        if _privs:
            if not _privs.get("can_use_bash", True):
                disabled_tools.update({"bash", "python", "read_file", "write_file"})
            if not _privs.get("can_use_browser", True):
                disabled_tools.update(_BROWSER_MCP_TOOLS)
            if not _privs.get("can_use_documents", True):
                disabled_tools.update({"create_document", "edit_document", "update_document", "suggest_document"})
            if not _privs.get("can_generate_images", True):
                disabled_tools.add("generate_image")
            if not _privs.get("can_manage_memory", True):
                disabled_tools.update({"manage_memory", "manage_skills"})
            if not _privs.get("can_use_research", True):
                _research_flags["do"] = False
            if not _privs.get("can_use_agent", True):
                _effective_mode = 'chat'
                chat_mode = 'chat'
        # Global admin disabled tools
        from src.settings import get_setting
        _global_disabled = get_setting("disabled_tools", [])
        if _global_disabled and isinstance(_global_disabled, list):
            disabled_tools.update(_global_disabled)

        # Light auto-escalation: the user is in chat mode and just expressed a
        # notes/calendar/email intent. Grant the relevant managers but withhold
        # the heavy "do things on the computer" tools — otherwise the model
        # tries to shell out for a request that never needed it, then fails
        # (and looks broken when the shell is disabled).
        # `P4-18`. One answer to "what did the promotion take away", named
        # rather than counted, and computed where a test can ask it.
        _escalation_withheld = escalation_withholds(
            promoted=auto_escalated,
            workspace_intent=_workspace_agent_intent,
            allow_browser=_allow_browser_for_web_turn,
            browser_tools=_BROWSER_MCP_TOOLS,
        )
        disabled_tools.update(_escalation_withheld)
        # `P4-18`. Built once, here, where both halves are known: the reasons
        # the six promotion sites recorded and the tools the promotion took
        # away. Streamed below and saved with the message, so a reloaded thread
        # can still say why it is an agent thread.
        _auto_escalation_payload = {
            "type": "auto_escalated",
            "reasons": list(_escalations),
            "withheld": list(_escalation_withheld),
        }

        # Disable document tools in compare sessions — they break the pane UI
        if sess.name and sess.name.startswith("[CMP]"):
            disabled_tools.update({"create_document", "edit_document", "update_document"})

        # Compare mode: disable tools based on compare type
        if compare_mode:
            _compare_strip = {
                "create_document", "edit_document", "update_document",
                "chat_with_model", "create_session", "list_sessions",
                "send_to_session",
                "pipeline", "manage_session", "manage_memory", "list_models",
                "generate_image", "ui_control",
            }
            disabled_tools.update(_compare_strip)
            # In chat mode compare, disable ALL agent tools (no bash, python, file ops)
            if chat_mode == 'chat':
                disabled_tools.update({"bash", "python", "read_file", "write_file", "web_search", "web_fetch", "search_chats", "manage_tasks"})

        # Plan mode: investigate read-only, propose a plan, don't mutate. Block
        # every tool not on the read-only allowlist. (stream_agent_loop enforces
        # this again + drops MCP, so this is belt-and-suspenders.)
        if plan_mode:
            from src.tool_security import plan_mode_disabled_tools
            disabled_tools.update(plan_mode_disabled_tools())

        tool_policy = build_effective_tool_policy(
            disabled_tools=disabled_tools,
            last_user_message=message,
        )
        disabled_tools = tool_policy.all_disabled_names()
        research_blocked_by_policy = bool(
            tool_policy.blocks("trigger_research")
            or tool_policy.blocks("manage_research")
        )
        effective_do_research = bool(
            do_research and _research_flags["do"] and not research_blocked_by_policy
        )

        # Persist session mode after policy/privilege gates so blocked research
        # turns remain ordinary chat/agent streams and saved messages.
        _effective_mode = 'research' if effective_do_research else (chat_mode or 'chat')
        if _effective_mode in ('agent', 'research', 'chat'):
            set_session_mode(session, _effective_mode)

        # `B14`. Decided here, once, and read twice: `agent_runs.start` gates the
        # steer route on it, and the stream announces it so the composer can stop
        # guessing. Everything it depends on is settled by this line — `chat_mode`
        # took its last value above, `effective_do_research` two lines up, and the
        # image check reads the model `build_chat_context` already normalised.
        _turn_is_steerable = _stream_is_steerable(
            chat_mode=chat_mode,
            is_image_session=lambda: _is_image_generation_session(sess, owner=_user),
            do_research=bool(effective_do_research),
            compare_mode=compare_mode,
        )

        async def stream_with_save() -> AsyncGenerator[str, None]:
            # _effective_mode is read-only here; closure captures it from
            # the outer scope. (Was `nonlocal` but never reassigned.)
            research_sources = None
            web_sources = ctx.web_sources

            # Register active stream for partial-save safety net
            _active_streams[session] = {"status": "streaming", "partial": "", "query": message, "is_research": effective_do_research, "mode": _effective_mode}

            # `B14`. First event on every stream, before any conditional yield,
            # because the composer has already drawn the steer bar by the time
            # this POST goes out and the sooner it is corrected the shorter the
            # wrong state lasts. `agent_runs.subscribe` replays a run's buffer
            # from the start, so a reconnect through `/api/chat/resume` re-learns
            # this too rather than inheriting the last turn's answer.
            #
            # The client could not work this out for itself, and its existing
            # guess is wrong in both directions. Research: `research_pending`
            # auto-triggers research on the NEXT message (above, ~:1424) while
            # `chat.js` clears the research toggle at send (~:2947), so the
            # composer says "not research" for a turn that is. Auto-escalation:
            # a chat-mode turn promoted to agent IS steerable, and the composer
            # still says "chat", so the bar is withheld from a run that would
            # have taken the steer. Image sessions and compare panes it never
            # knew about at all.
            yield f"data: {json.dumps({'type': 'stream_steerable', 'steerable': bool(_turn_is_steerable)})}\n\n"

            # The client sent a workspace the server refused to bind (deleted
            # folder, file path, sensitive dir, filesystem root). Tell it up
            # front so the UI can clear the pill instead of displaying a
            # confinement that is not actually in effect.
            if workspace_rejected:
                yield f"data: {json.dumps({'type': 'workspace_rejected', 'data': {'path': workspace_rejected}})}\n\n"

            if ctx.preprocessed.attachment_meta:
                yield f"data: {json.dumps({'type': 'attachments', 'data': ctx.preprocessed.attachment_meta})}\n\n"

            # Announce any docs auto-created during preprocess (e.g. fillable
            # PDF → editable markdown) so the editor pane switches to them
            # before the model starts streaming.
            for _opened in ctx.auto_opened_docs:
                yield (
                    f'data: {json.dumps({"type": "doc_update", **_opened})}\n\n'
                )

            if ctx.rag_sources:
                yield f"data: {json.dumps({'type': 'rag_sources', 'data': ctx.rag_sources})}\n\n"

            if web_sources:
                yield f"data: {json.dumps({'type': 'web_sources', 'data': web_sources})}\n\n"

            # Emit which memories were injected into context (captured before stream)
            if ctx.used_memories:
                yield f"data: {json.dumps({'type': 'memories_used', 'data': ctx.used_memories})}\n\n"

            # `P4-18`. The turn was typed in chat mode and answered in agent
            # mode, and until now that happened in silence — in both directions.
            # The reader saw an agent thread they did not ask for, and when the
            # model could not do something because a tool had been withheld,
            # nothing said a tool had been withheld.
            if auto_escalated:
                yield f"data: {json.dumps(_auto_escalation_payload)}\n\n"

            # Run research as a background task (survives page refresh)
            if effective_do_research:
                _r_ep, _r_model, _r_headers = _resolve_research_endpoint(sess)
                _auth_keys = list(_r_headers.keys()) if _r_headers else []
                logger.info(f"Research endpoint resolved: model={_r_model}, endpoint={redact_url(_r_ep)}, auth_keys={_auth_keys}, sess_headers_keys={list(sess.headers.keys()) if isinstance(sess.headers, dict) else type(sess.headers)}")

                # Clarification round: only for very short/vague queries on first research message.
                # Skip in compare mode — each pane is a fresh session, so every one would
                # ask clarifying questions and the user would have to answer each pane
                # separately, breaking the parallel comparison.
                _prior_json = research_handler._get_session_json(session)
                _history_len = len(sess.history) if hasattr(sess, 'history') else 0
                _is_first_research = not _prior_json and _history_len <= 2 and not compare_mode

                if _is_first_research:
                    logger.info(f"First research message — asking clarifying questions for: {message[:60]}")
                    yield f'data: {json.dumps({"type": "model_info", "model": sess.model, "suffix": "Research"})}\n\n'
                    # Set DB mode to research_pending so the NEXT message auto-triggers research
                    set_session_mode(session, "research_pending")
                    ctx.messages.insert(0, {"role": "system", "content":
                        "The user wants to start deep web research. Before searching, ask 2-3 brief "
                        "clarifying questions to understand exactly what they want to know. For example: "
                        "what aspects matter most, are they comparing to something, what's their context "
                        "(moving, traveling, curiosity). Be conversational. Keep it short."
                    })
                    if foreground_policy.enabled:
                        getattr(ctx, "route_messages", ctx.messages).insert(0, dict(ctx.messages[0]))
                    _skip_research = True
                else:
                    _skip_research = False

                if not _skip_research:
                    # Phase 2: Start actual research
                    def _on_research_done(_sid, _result, _sources, _findings):
                        """Persist research to DB when background task finishes."""
                        if incognito:
                            return
                        try:
                            _s = session_manager.get_session(_sid)
                            if not _s:
                                logger.warning(f"Session {_sid} expired before research completed")
                                return
                            _md = {"research": True, "model": _s.model}
                            if _sources:
                                _md["research_sources"] = _sources
                            if _findings:
                                _md["research_findings"] = _findings
                            _clean_res, _md = clean_thinking_for_save(_result, _md)
                            _s.add_message(ChatMessage("assistant", _clean_res, metadata=_md))
                            session_manager.save_sessions()
                            logger.info(f"Research result persisted to DB for session {_sid}")
                        except Exception as _e:
                            logger.error(f"Failed to persist research to DB: {_e}")

                    # Check for prior research to continue from
                    _prior_report = ""
                    _prior_findings = None
                    _prior_urls = None
                    _prior_json = research_handler._get_session_json(session)
                    if _prior_json:
                        _prior_report = _prior_json.get("raw_report", "")
                        _prior_findings = _prior_json.get("raw_findings")
                        _src_urls = {s.get("url", "") for s in (_prior_json.get("sources") or []) if s.get("url")}
                        _prior_urls = _src_urls if _src_urls else None
                        if _prior_report:
                            logger.info(f"Continuing research for session {session} with {len(_src_urls)} prior URLs")

                    # Synthesize conversation into a focused research query
                    _research_query = await research_handler.synthesize_query(
                        sess, message, _r_ep, _r_model, _r_headers,
                    )
                    logger.info(f"Research query: {_research_query[:120]}")

                    research_handler.start_research(
                        session, _research_query, _r_ep, _r_model,
                        llm_headers=_r_headers,
                        prior_report=_prior_report,
                        prior_findings=_prior_findings,
                        prior_urls=_prior_urls,
                        on_complete=_on_research_done,
                        owner=_user,
                    )

                    _heartbeat_counter = 0
                    _last_progress = {}
                    _sent_avg = False
                    while True:
                        status = research_handler.get_status(session)
                        if not status or status["status"] != "running":
                            break
                        progress = status.get("progress", {})
                        if progress and progress != _last_progress:
                            _last_progress = progress
                            if not _sent_avg:
                                _sent_avg = True
                                progress = dict(progress)
                                progress["started_at"] = status.get("started_at")
                                avg = status.get("avg_duration")
                                if avg:
                                    progress["avg_duration"] = avg
                            yield f"data: {json.dumps({'type': 'research_progress', 'data': progress})}\n\n"
                            _heartbeat_counter = 0
                        else:
                            _heartbeat_counter += 1
                            yield f": heartbeat {_heartbeat_counter}\n\n"
                        await asyncio.sleep(1.0)

                    research_sources = research_handler.get_sources(session)
                    if research_sources:
                        yield f"data: {json.dumps({'type': 'research_sources', 'data': research_sources})}\n\n"

                    research_findings = research_handler.get_raw_findings(session)
                    if research_findings:
                        yield f"data: {json.dumps({'type': 'research_findings', 'data': research_findings})}\n\n"

                    # Signal frontend to fetch and render the research result
                    yield f"data: {json.dumps({'type': 'research_done', 'data': {'session_id': session}})}\n\n"
                    yield "data: [DONE]\n\n"
                    research_handler.clear_result(session)
                    _stream_set(session, status="done")
                    _active_streams.pop(session, None)
                    return

            context_source = (
                getattr(ctx, "route_messages", ctx.messages)
                if foreground_policy.enabled
                else ctx.messages
            )
            messages = (
                list(context_source)
                if tool_approval_continuation
                else _ensure_current_request_is_latest_user(context_source, message)
            )

            # Auto-compact notification
            if ctx.was_compacted:
                yield f"data: {json.dumps({'type': 'compacted', 'context_length': ctx.context_length})}\n\n"
            if ctx.context_trimmed and not ctx.was_compacted:
                yield f"data: {json.dumps({'type': 'context_trimmed', 'data': {'context_length': ctx.context_length, 'messages_before': ctx.context_messages_before_trim, 'messages_after': ctx.context_messages_after_trim, 'tokens_before': ctx.context_tokens_before_trim, 'tokens_after': ctx.context_tokens_after_trim}})}\n\n"

            full_response = ""
            thinking_response = ""
            last_metrics = None

            # Foreground Chat and Agent requests share one explicit owner-aware
            # policy. Strict mode is the default; legacy values are unrelated.
            _foreground_policy = foreground_policy
            _foreground_candidates = build_foreground_model_candidates(
                sess.endpoint_url,
                sess.model,
                sess.headers,
                owner=_user,
                policy=_foreground_policy,
            )
            _foreground_route_descriptors = build_foreground_route_descriptors(
                sess.endpoint_url,
                sess.model,
                sess.headers,
                owner=_user,
                policy=_foreground_policy,
                selected_endpoint_id=selected_endpoint_id,
            )
            _chat_request_factory = None
            _selected_context_length = getattr(ctx, "context_length", 0)
            _chat_request_state = {
                "context_lengths": {0: _selected_context_length},
                "requests": {0: messages},
                "trim_stats": {},
            }
            if _foreground_policy.enabled:
                _chat_request_factory, _chat_request_state = _chat_candidate_request_factory(
                    messages,
                    _selected_context_length,
                    session=sess,
                    owner=_user,
                )

            # Send model name early so the frontend can show it during streaming
            _model_suffix = "Research" if effective_do_research else None
            _selected_route = _foreground_route_descriptors[0]
            _model_info = {
                "type": "model_info",
                "model": sess.model,
                "endpoint_id": _selected_route.get("endpoint_id"),
                "endpoint_label": _selected_route.get("endpoint_label"),
            }
            if _model_suffix:
                _model_info["suffix"] = _model_suffix
            if ctx.preset.character_name:
                _model_info["character_name"] = ctx.preset.character_name
            yield f'data: {json.dumps(_model_info)}\n\n'

            _terminal_saved = False
            if _is_image_generation_session(sess, owner=_user):
                from src.settings import get_setting
                if tool_policy.blocks("generate_image"):
                    _blocked_msg = tool_policy.reason_for("generate_image")
                    yield f'data: {json.dumps({"delta": _blocked_msg})}\n\n'
                    yield "data: [DONE]\n\n"
                    _active_streams.pop(session, None)
                    return
                if not get_setting("image_gen_enabled", True):
                    yield f'data: {json.dumps({"delta": "Image generation is disabled by the administrator."})}\n\n'
                    yield "data: [DONE]\n\n"
                    _active_streams.pop(session, None)
                    return
                from src.ai_interaction import do_edit_image, do_generate_image
                _user_msg = message or ""
                _image_upload = _first_image_attachment(chat_handler, att_ids, owner=_user)
                _image_tool_name = "edit_image" if _image_upload else "generate_image"
                # `P4-11`. This path never enters the agent loop — the whole
                # interaction is one call — so its round is 1 and stays 1. It is
                # stated rather than omitted so the card carries the same badge
                # every other tool card in the thread does.
                yield f'data: {json.dumps({"type": "tool_start", "tool": _image_tool_name, "command": _user_msg[:100], "round": 1})}\n\n'
                yield ": heartbeat\n\n"
                _progress_queue: asyncio.Queue = asyncio.Queue()

                async def _image_progress_callback(progress: Dict[str, Any]):
                    try:
                        _progress_queue.put_nowait(progress)
                    except Exception:
                        # `P3-17`: a percentage on a progress bar. The image
                        # itself is not in this queue, and blocking the
                        # generation to deliver a tick nobody will see by the
                        # time it arrives is the worse trade.
                        pass

                if _image_upload:
                    _img_task = asyncio.create_task(do_edit_image(
                        _user_msg,
                        _image_upload.get("path", ""),
                        model_spec=sess.model,
                        session_id=session,
                        owner=_user,
                        size="1024x1024",
                        progress_callback=_image_progress_callback,
                    ))
                else:
                    _img_task = asyncio.create_task(do_generate_image(f"{_user_msg}\n{sess.model}\n512x512", session, owner=_user))
                _img_started = time.time()
                _img_tick = 0
                while not _img_task.done():
                    try:
                        _progress = await asyncio.wait_for(_progress_queue.get(), timeout=2.0)
                    except asyncio.TimeoutError:
                        _progress = None
                    _img_tick += 1
                    _elapsed = int(time.time() - _img_started)
                    _label = "Editing image" if _image_upload else "Generating image"
                    yield ": image generation still running\n\n"
                    _progress_data = {"type": "tool_progress", "tool": _image_tool_name, "round": 1, "message": f"{_label}… {_elapsed}s", "elapsed": _elapsed, "tick": _img_tick}
                    if isinstance(_progress, dict) and _progress.get("total"):
                        _step = int(_progress.get("step") or 0)
                        _total = int(_progress.get("total") or 0)
                        _percent = _progress.get("percent")
                        _progress_data.update({
                            "step": _step,
                            "total": _total,
                            "percent": _percent,
                            "message": f"{_label}… {_step}/{_total}",
                        })
                    yield f'data: {json.dumps(_progress_data)}\n\n'
                _img_result = await _img_task
                _img_output = _img_result.get("results", _img_result.get("error", ""))
                _img_tool_data = {"type": "tool_output", "tool": _image_tool_name, "command": _user_msg[:100], "round": 1, "output": _img_output, "exit_code": 0 if "error" not in _img_result else 1}
                for _k in ("image_url", "image_id", "image_prompt", "image_model", "image_size", "image_quality"):
                    if _k in _img_result:
                        _img_tool_data[_k] = _img_result[_k]
                if _image_upload:
                    _img_tool_data["source_image"] = {
                        "id": _image_upload.get("id"),
                        "name": _image_upload.get("name") or _image_upload.get("original_name"),
                    }
                yield f'data: {json.dumps(_img_tool_data)}\n\n'
                if _img_result.get("image_url"):
                    _img_event = {"type": "generated_image", "url": _img_result.get("image_url")}
                    for _k in ("image_url", "image_id", "image_prompt", "image_model", "image_size", "image_quality"):
                        if _img_result.get(_k):
                            _img_event[_k] = _img_result[_k]
                    yield f'data: {json.dumps(_img_event)}\n\n'
                _desc = _img_result.get("results", _img_result.get("error", "Image generation complete"))
                full_response = _desc
                yield f'data: {json.dumps({"delta": _desc})}\n\n'
                # Save to session history
                if not incognito:
                    _ev = {"round": 1, "tool": _image_tool_name, "command": _user_msg[:100], "output": _img_output, "exit_code": 0 if "error" not in _img_result else 1}
                    for _ek in ("image_url", "image_id", "image_prompt", "image_model", "image_size", "image_quality"):
                        if _img_result.get(_ek):
                            _ev[_ek] = _img_result[_ek]
                    if _image_upload:
                        _ev["source_image_id"] = _image_upload.get("id")
                        _ev["source_image_name"] = _image_upload.get("name") or _image_upload.get("original_name")
                    sess.add_message(ChatMessage("assistant", full_response, metadata={"tool_events": [_ev], "model": sess.model}))
                    session_manager.save_sessions()
                yield f'data: {json.dumps({"type": "metrics", "data": {"total_time": 0}})}\n\n'
                yield "data: [DONE]\n\n"
                _active_streams.pop(session, None)
                return
            elif chat_mode == "chat":
                _chat_start = time.time()
                _answered_by = None  # set if the selected model failed and a fallback answered
                _fallback_chain = None  # `P4-05`: every candidate tried, with its status
                _requested_model = sess.model
                _actual_model = None
                _requested_route = _foreground_route_descriptors[0]
                _actual_route = _requested_route
                _actual_candidate_index = 0
                _chat_terminal_saved = False
                def _commit_chat_compaction(candidate_index: int) -> bool:
                    return apply_compaction_state(
                        sess,
                        _chat_request_state.get("compactions", {}).get(candidate_index),
                    )

                # ── Chat mode: call stream_llm directly, NO tools, NO document access ──
                try:
                    async for chunk in stream_llm_with_fallback(
                        _foreground_candidates,
                        messages,
                        temperature=ctx.preset.temperature,
                        # Respect the preset; 0/unset = let the server decide (no
                        # cap), matching agent mode. The old hard 4096 fallback
                        # truncated reasoning models mid-<think> — they'd burn the
                        # whole budget thinking and never emit the answer (seen in
                        # Compare on heavy generation prompts).
                        max_tokens=ctx.preset.max_tokens,
                        prompt_type=preset_id,
                        tools=None,
                        session_id=session,
                        fallback_statuses=_foreground_policy.eligible_statuses,
                        fallback_on_empty=_foreground_policy.fallback_on_empty,
                        candidate_request_factory=_chat_request_factory,
                        candidate_route_descriptors=_foreground_route_descriptors,
                    ):
                        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                            try:
                                data = json.loads(chunk[6:])
                                if "delta" in data:
                                    if _commit_chat_compaction(_actual_candidate_index):
                                        _compacted_length = _chat_request_state["context_lengths"].get(
                                            _actual_candidate_index,
                                            _selected_context_length,
                                        )
                                        yield f'data: {json.dumps({"type": "compacted", "context_length": _compacted_length})}\n\n'
                                    # Reasoning tokens arrive flagged thinking:true.
                                    # Forward them so the client can show a thinking
                                    # indicator, but don't fold them into the saved
                                    # reply (mirrors the rewrite path below).
                                    if data.get("thinking"):
                                        thinking_response += data["delta"]
                                    else:
                                        full_response += data["delta"]
                                        _stream_set(session, partial=full_response)
                                    yield chunk
                                elif data.get("type") == "fallback":
                                    # Selected model failed; a fallback answered.
                                    # Forward the notice and remember the real model.
                                    _answered_by = data.get("answered_by") or _answered_by
                                    _actual_model = _actual_model or _answered_by
                                    # `P4-05`. The chain of candidates and their
                                    # statuses. It was on the wire and read by
                                    # one line of a six-second toast; saving it
                                    # is what lets a reloaded reply still say
                                    # why it is answered by a model nobody
                                    # selected.
                                    _fallback_chain = {
                                        "selected_model": data.get("selected_model"),
                                        "answered_by": data.get("answered_by"),
                                        "failures": data.get("failures") or [],
                                    }
                                    _actual_candidate_index = data.get("candidate_index", 0)
                                    if not isinstance(_actual_candidate_index, int):
                                        _actual_candidate_index = 0
                                    if 0 <= _actual_candidate_index < len(_foreground_route_descriptors):
                                        _actual_route = _foreground_route_descriptors[_actual_candidate_index]
                                    if _commit_chat_compaction(_actual_candidate_index):
                                        _compacted_length = _chat_request_state["context_lengths"].get(
                                            _actual_candidate_index,
                                            _selected_context_length,
                                        )
                                        yield f'data: {json.dumps({"type": "compacted", "context_length": _compacted_length})}\n\n'
                                    data["selected_model"] = data.get("selected_model") or _requested_model
                                    yield f'data: {json.dumps(data)}\n\n'
                                elif data.get("type") == "model_actual":
                                    if _commit_chat_compaction(_actual_candidate_index):
                                        _compacted_length = _chat_request_state["context_lengths"].get(
                                            _actual_candidate_index,
                                            _selected_context_length,
                                        )
                                        yield f'data: {json.dumps({"type": "compacted", "context_length": _compacted_length})}\n\n'
                                    _actual_model = data.get("model") or _actual_model
                                    data["requested_model"] = _requested_model
                                    data["requested_endpoint_id"] = _requested_route.get("endpoint_id")
                                    data["requested_endpoint_label"] = _requested_route.get("endpoint_label")
                                    data["endpoint_id"] = _actual_route.get("endpoint_id")
                                    data["endpoint_label"] = _actual_route.get("endpoint_label")
                                    yield f'data: {json.dumps(data)}\n\n'
                                elif data.get("type") == "usage":
                                    if _commit_chat_compaction(_actual_candidate_index):
                                        _compacted_length = _chat_request_state["context_lengths"].get(
                                            _actual_candidate_index,
                                            _selected_context_length,
                                        )
                                        yield f'data: {json.dumps({"type": "compacted", "context_length": _compacted_length})}\n\n'
                                    last_metrics = data.get("data", {})
                                    _reported_model = last_metrics.get("model")
                                    last_metrics["requested_model"] = _requested_model
                                    last_metrics["model"] = _reported_model or _actual_model or _answered_by or _requested_model
                                    last_metrics["requested_endpoint_id"] = _requested_route.get("endpoint_id")
                                    last_metrics["requested_endpoint_label"] = _requested_route.get("endpoint_label")
                                    last_metrics["endpoint_id"] = _actual_route.get("endpoint_id")
                                    last_metrics["endpoint_label"] = _actual_route.get("endpoint_label")
                                    if isinstance(
                                        _actual_route.get("endpoint_cost_tracked"),
                                        bool,
                                    ):
                                        last_metrics["endpoint_cost_tracked"] = _actual_route.get(
                                            "endpoint_cost_tracked"
                                        )
                                    _actual_context_length = _chat_request_state["context_lengths"].get(
                                    _actual_candidate_index,
                                        _selected_context_length,
                                    )
                                    _route_trim = _chat_request_state.get("trim_stats", {}).get(
                                        _actual_candidate_index,
                                        {},
                                    )
                                    if _route_trim and (
                                        _route_trim.get("messages_after") < _route_trim.get("messages_before")
                                        or _route_trim.get("tokens_after") < _route_trim.get("tokens_before")
                                    ):
                                        last_metrics["context_trimmed"] = True
                                        last_metrics["context_messages_before_trim"] = _route_trim.get("messages_before")
                                        last_metrics["context_messages_after_trim"] = _route_trim.get("messages_after")
                                        last_metrics["context_tokens_before_trim"] = _route_trim.get("tokens_before")
                                        last_metrics["context_tokens_after_trim"] = _route_trim.get("tokens_after")
                                    elif ctx.context_trimmed:
                                        last_metrics["context_trimmed"] = True
                                        last_metrics["context_messages_before_trim"] = ctx.context_messages_before_trim
                                        last_metrics["context_messages_after_trim"] = ctx.context_messages_after_trim
                                        last_metrics["context_tokens_before_trim"] = ctx.context_tokens_before_trim
                                        last_metrics["context_tokens_after_trim"] = ctx.context_tokens_after_trim
                                    if _actual_context_length and last_metrics.get("input_tokens"):
                                        pct = min(round((last_metrics["input_tokens"] / _actual_context_length) * 100, 1), 100.0)
                                        last_metrics["context_percent"] = pct
                                        last_metrics["context_length"] = _actual_context_length
                                    # The frontend reads `tokens_per_second`; the raw usage event
                                    # carries the backend's true gen speed as `gen_tps` (llama.cpp
                                    # timings). Map it through so this direct-chat path shows real
                                    # t/s instead of "n/a" → falling back to a bare token count.
                                    if last_metrics.get("gen_tps") and not last_metrics.get("tokens_per_second"):
                                        last_metrics["tokens_per_second"] = last_metrics["gen_tps"]
                                        last_metrics["tps_source"] = "backend"
                                    # Wall-clock response time for the stats popup ("Time").
                                    last_metrics.setdefault("response_time", round(time.time() - _chat_start, 2))
                                    yield f'data: {json.dumps({"type": "metrics", "data": last_metrics})}\n\n'
                            except json.JSONDecodeError:
                                yield chunk
                        elif chunk.startswith("event: error"):
                            logger.warning(f"Stream error for {sess.model} on {sess.endpoint_url}: {chunk!r}")
                            if (
                                not _chat_terminal_saved
                                and (full_response.strip() or thinking_response.strip())
                            ):
                                _failure_status = _stream_failure_status(chunk)
                                _failure_message = (
                                    f"Model request failed (HTTP {_failure_status})"
                                    if _failure_status is not None
                                    else "Model request failed"
                                )
                                _terminal_content = full_response.strip()
                                _failure_note = f"[Response stopped: {_failure_message}]"
                                _terminal_content = (
                                    f"{_terminal_content}\n\n{_failure_note}"
                                    if _terminal_content
                                    else _failure_note
                                )
                                _had_terminal_usage = bool(last_metrics)
                                _terminal_metrics = dict(last_metrics or {})
                                if not _had_terminal_usage:
                                    _actual_request_messages = _chat_request_state["requests"].get(
                                        _actual_candidate_index,
                                        messages,
                                    )
                                    _actual_context_length = _chat_request_state["context_lengths"].get(
                                        _actual_candidate_index,
                                        _selected_context_length,
                                    )
                                    _estimated_input = estimate_tokens(_actual_request_messages)
                                    _estimated_output = max(
                                        len(full_response + thinking_response) // 4,
                                        0,
                                    )
                                    _terminal_metrics.update({
                                        "input_tokens": _estimated_input,
                                        "output_tokens": _estimated_output,
                                        "total_tokens": _estimated_input + _estimated_output,
                                        "usage_source": "estimated",
                                        "response_time": round(time.time() - _chat_start, 2),
                                        "context_length": _actual_context_length,
                                        "context_percent": (
                                            min(
                                                round(
                                                    (_estimated_input / _actual_context_length) * 100,
                                                    1,
                                                ),
                                                100.0,
                                            )
                                            if _actual_context_length
                                            else 0
                                        ),
                                    })
                                _terminal_metrics.update({
                                    "failed": True,
                                    "failure": {
                                        "status": _failure_status,
                                        "message": _failure_message,
                                    },
                                    "model": _actual_model or _answered_by or _requested_model,
                                    "requested_model": _requested_model,
                                    "endpoint_id": _actual_route.get("endpoint_id"),
                                    "endpoint_label": _actual_route.get("endpoint_label"),
                                    "requested_endpoint_id": _requested_route.get("endpoint_id"),
                                    "requested_endpoint_label": _requested_route.get("endpoint_label"),
                                })
                                if isinstance(
                                    _actual_route.get("endpoint_cost_tracked"),
                                    bool,
                                ):
                                    _terminal_metrics["endpoint_cost_tracked"] = _actual_route.get(
                                        "endpoint_cost_tracked"
                                    )
                                if thinking_response.strip():
                                    _terminal_metrics["thinking"] = thinking_response.strip()
                                _commit_chat_compaction(_actual_candidate_index)
                                _saved_id = save_assistant_response(
                                    sess,
                                    session_manager,
                                    session,
                                    _terminal_content,
                                    _terminal_metrics,
                                    character_name=ctx.preset.character_name,
                                    incognito=incognito,
                                )
                                accumulate_token_usage(session, _terminal_metrics, outcome="error")
                                _chat_terminal_saved = True
                                _stream_set(session, status="error")
                                if _saved_id:
                                    yield f'data: {json.dumps({"type": "message_saved", "id": _saved_id})}\n\n'
                                yield f'data: {json.dumps({"type": "chat_terminal", "data": _terminal_metrics})}\n\n'
                            yield chunk
                        elif chunk.startswith("event: "):
                            yield chunk
                        elif chunk == "data: [DONE]\n\n":
                            if _chat_terminal_saved:
                                # Some providers append DONE after a terminal
                                # error.  The failed partial is already saved;
                                # never re-save/post-process it as a success or
                                # advertise successful completion to the client.
                                continue
                            # Generate fallback metrics if LLM didn't send usage
                            if not last_metrics and full_response:
                                _elapsed = time.time() - _chat_start
                                _est_out = len(full_response) // 4
                                _tps = round(_est_out / _elapsed, 2) if _elapsed > 0 else 0
                                _actual_context_length = _chat_request_state["context_lengths"].get(
                                    _actual_candidate_index,
                                    _selected_context_length,
                                )
                                _actual_request_messages = _chat_request_state["requests"].get(
                                    _actual_candidate_index,
                                    messages,
                                )
                                _est_in = estimate_tokens(_actual_request_messages)
                                _ctx_pct = min(round((_est_in / _actual_context_length) * 100, 1), 100.0) if _actual_context_length else 0
                                last_metrics = {
                                    "response_time": round(_elapsed, 2),
                                    "input_tokens": _est_in,
                                    "output_tokens": _est_out,
                                    "tokens_per_second": _tps,
                                    "request_context_tokens": _est_in,
                                    "context_percent": _ctx_pct,
                                    "context_length": _actual_context_length,
                                    "model": _actual_model or _answered_by or _requested_model,
                                    "requested_model": _requested_model,
                                    "requested_endpoint_id": _requested_route.get("endpoint_id"),
                                    "requested_endpoint_label": _requested_route.get("endpoint_label"),
                                    "endpoint_id": _actual_route.get("endpoint_id"),
                                    "endpoint_label": _actual_route.get("endpoint_label"),
                                    "usage_source": "estimated",
                                }
                                if isinstance(
                                    _actual_route.get("endpoint_cost_tracked"),
                                    bool,
                                ):
                                    last_metrics["endpoint_cost_tracked"] = _actual_route.get(
                                        "endpoint_cost_tracked"
                                    )
                                yield f'data: {json.dumps({"type": "metrics", "data": last_metrics})}\n\n'
                            if full_response:
                                _commit_chat_compaction(_actual_candidate_index)
                                _metrics_to_save = dict(last_metrics or {})
                                if thinking_response.strip() and not _metrics_to_save.get("thinking"):
                                    _metrics_to_save["thinking"] = thinking_response.strip()
                                _saved_id = save_assistant_response(
                                    sess, session_manager, session, full_response, _metrics_to_save,
                                    character_name=ctx.preset.character_name,
                                    web_sources=web_sources,
                                    rag_sources=ctx.rag_sources,
                                    research_sources=research_sources,
                                    used_memories=ctx.used_memories,
                                    fallback_chain=_fallback_chain,
                                    auto_escalation=_auto_escalation_payload if auto_escalated else None,
                                    do_research=effective_do_research,
                                    incognito=incognito,
                                )
                                if _saved_id:
                                    yield f'data: {json.dumps({"type": "message_saved", "id": _saved_id})}\n\n'
                                run_post_response_tasks(
                                    sess, session_manager, session, message, full_response,
                                    _metrics_to_save, ctx.uprefs, memory_manager, memory_vector, webhook_manager,
                                    incognito=incognito, compare_mode=compare_mode,
                                    character_name=ctx.preset.character_name,
                                    owner=_user,
                                    allow_background_extraction=(
                                        not tool_policy.block_all_tool_calls
                                        and not tool_approval_continuation
                                    ),
                                )
                            _stream_set(session, status="done")
                            yield chunk
                except (asyncio.CancelledError, GeneratorExit):
                    if full_response and not incognito:
                        logger.info("Client disconnected mid-stream (chat mode) for session %s, saving partial (%d chars)", session, len(full_response))
                        _stopped_content, _stopped_md = clean_thinking_for_save(
                            full_response,
                            {
                                "stopped": True,
                                "model": _actual_model or _answered_by or _requested_model,
                                "requested_model": _requested_model,
                                "endpoint_id": _actual_route.get("endpoint_id"),
                                "endpoint_label": _actual_route.get("endpoint_label"),
                                "requested_endpoint_id": _requested_route.get("endpoint_id"),
                                "requested_endpoint_label": _requested_route.get("endpoint_label"),
                            },
                        )
                        sess.add_message(ChatMessage("assistant", _stopped_content, metadata=_stopped_md))
                        session_manager.save_sessions()
                    raise
                finally:
                    _active_streams.pop(session, None)
            else:
                # ── Agent mode: full agent loop with tools ──
                _agent_rounds = 0
                _agent_tool_calls = 0
                _answered_by = None  # set if the selected model failed and a fallback answered
                _fallback_chain = None  # `P4-05`: every candidate tried, with its status
                _requested_model = sess.model
                _actual_model = None
                _agent_requested_route = _foreground_route_descriptors[0]
                _agent_actual_endpoint_id = _agent_requested_route.get("endpoint_id")
                _agent_actual_endpoint_label = _agent_requested_route.get("endpoint_label")
                _agent_round_models = {1: _requested_model}
                _agent_round_endpoint_ids = {1: _agent_actual_endpoint_id}
                _agent_round_endpoint_labels = {1: _agent_actual_endpoint_label}
                try:
                    from src.settings import get_setting
                    from src.agent_tools import MAX_AGENT_ROUNDS as _DEFAULT_ROUNDS
                    # Per-message tool budget from settings; guard defensively in
                    # case settings.json was hand-edited to a non-numeric value
                    # (the HTTP admin endpoint validates, but direct edits bypass
                    # it). 0 = unlimited, matching auth_routes set_settings().
                    try:
                        _tool_budget = int(get_setting("agent_max_tool_calls", 0))
                    except (TypeError, ValueError):
                        _tool_budget = 0
                    # Per-message round cap from settings; clamp defensively in
                    # case settings.json was hand-edited to a bad value.
                    try:
                        _max_rounds = int(get_setting("agent_max_rounds", _DEFAULT_ROUNDS) or _DEFAULT_ROUNDS)
                    except (TypeError, ValueError):
                        _max_rounds = _DEFAULT_ROUNDS
                    _max_rounds = max(1, min(_max_rounds, 200))

                    _forced_tools = None
                    if _search_enabled:
                        _forced_tools = set(WEB_TOOL_NAMES)
                        if _explicit_browser_intent:
                            _forced_tools |= set(_BROWSER_MCP_TOOLS)
                    elif _explicit_browser_intent:
                        _forced_tools = set(_BROWSER_MCP_TOOLS)

                    async for chunk in stream_agent_loop(
                        sess.endpoint_url,
                        sess.model,
                        messages,
                        headers=sess.headers,
                        temperature=ctx.preset.temperature,
                        max_tokens=ctx.preset.max_tokens,
                        prompt_type=preset_id,
                        # `B60`. Four of the six conditions that decide whether
                        # the skills index may ship are known only here — the
                        # user's preference, `incognito`,
                        # `allow_tool_preprocessing` and the casual-low-signal
                        # test — and none of them reached the loop, which built
                        # its own copy regardless. They arrive as one flag now.
                        suppress_skills=not ctx.skills_enabled,
                        max_tool_calls=_tool_budget,
                        max_rounds=_max_rounds,
                        context_length=_selected_context_length,
                        active_document=active_doc,
                        active_email=active_email_ctx,
                        session_id=session,
                        history_session=sess,
                        disabled_tools=disabled_tools if disabled_tools else None,
                        tool_policy=tool_policy,
                        owner=_user,
                        fallbacks=_foreground_candidates[1:],
                        route_descriptors=_foreground_route_descriptors,
                        fallback_statuses=_foreground_policy.eligible_statuses,
                        fallback_on_empty=_foreground_policy.fallback_on_empty,
                        plan_mode=plan_mode,
                        approved_plan=approved_plan or None,
                        workspace=workspace or None,
                        relevant_tools=(
                            set(pending_tool_approval.selected_tools)
                            if exact_tool_approval
                            and pending_tool_approval
                            and pending_tool_approval.selected_tools
                            else None
                        ),
                        forced_tools=_forced_tools,
                        uploaded_files=ctx.uploaded_files,
                        defer_context_shaping=_foreground_policy.enabled,
                        external_untrusted_context_seen=external_untrusted_context_seen,
                        delegated_credential=_delegated_credential,
                        exact_approval=exact_tool_approval,
                    ):
                        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                            try:
                                data = json.loads(chunk[6:])
                                if "delta" in data:
                                    # Reasoning tokens arrive flagged thinking:true.
                                    # Forward them for the live indicator, but keep
                                    # them out of the saved reply (same as chat mode).
                                    if data.get("thinking"):
                                        thinking_response += data["delta"]
                                    else:
                                        full_response += data["delta"]
                                        _stream_set(session, partial=full_response)
                                    yield chunk
                                elif data.get("type") == "web_sources":
                                    web_sources = data.get("data", [])
                                    yield chunk
                                elif data.get("type") in (
                                    "tool_start", "tool_output", "agent_step",
                                    "doc_stream_open", "doc_stream_delta",
                                    "doc_update", "doc_suggestions", "ui_control",
                                    "rounds_exhausted", "budget_exceeded",
                                    "loop_breaker_triggered",
                                    "intent_nudge_exhausted",
                                    "ask_user",
                                    "plan_update",
                                ):
                                    if data.get("type") == "agent_step":
                                        _event_round = data.get("round", 1)
                                        _agent_rounds = max(_agent_rounds, _event_round)
                                        _agent_round_models.setdefault(
                                            _event_round,
                                            _actual_model or _answered_by or _requested_model,
                                        )
                                        _agent_round_endpoint_ids.setdefault(
                                            _event_round,
                                            _agent_actual_endpoint_id,
                                        )
                                        _agent_round_endpoint_labels.setdefault(
                                            _event_round,
                                            _agent_actual_endpoint_label,
                                        )
                                    elif data.get("type") == "tool_start":
                                        _agent_tool_calls += 1
                                    yield chunk
                                elif data.get("type") == "fallback":
                                    # Selected model failed; a fallback answered.
                                    # Forward the notice and remember the real
                                    # model so metrics reflect it, not the masked
                                    # selected model.
                                    _answered_by = data.get("answered_by") or _answered_by
                                    _actual_model = _answered_by or _actual_model
                                    # `P4-05`. The chain of candidates and their
                                    # statuses. It was on the wire and read by
                                    # one line of a six-second toast; saving it
                                    # is what lets a reloaded reply still say
                                    # why it is answered by a model nobody
                                    # selected.
                                    _fallback_chain = {
                                        "selected_model": data.get("selected_model"),
                                        "answered_by": data.get("answered_by"),
                                        "failures": data.get("failures") or [],
                                    }
                                    if "answered_by_endpoint_id" in data:
                                        _agent_actual_endpoint_id = data.get("answered_by_endpoint_id")
                                    if data.get("answered_by_endpoint_label"):
                                        _agent_actual_endpoint_label = data.get("answered_by_endpoint_label")
                                    _event_round = data.get("round") or max(_agent_rounds, 1)
                                    _agent_round_models[_event_round] = _answered_by or _requested_model
                                    _agent_round_endpoint_ids[_event_round] = _agent_actual_endpoint_id
                                    _agent_round_endpoint_labels[_event_round] = _agent_actual_endpoint_label
                                    data["selected_model"] = data.get("selected_model") or _requested_model
                                    yield chunk
                                elif data.get("type") == "model_actual":
                                    _actual_model = data.get("model") or _actual_model
                                    if "endpoint_id" in data:
                                        _agent_actual_endpoint_id = data.get("endpoint_id")
                                    if data.get("endpoint_label"):
                                        _agent_actual_endpoint_label = data.get("endpoint_label")
                                    _event_round = data.get("round") or max(_agent_rounds, 1)
                                    _agent_round_models[_event_round] = _actual_model or _requested_model
                                    _agent_round_endpoint_ids[_event_round] = _agent_actual_endpoint_id
                                    _agent_round_endpoint_labels[_event_round] = _agent_actual_endpoint_label
                                    data["requested_model"] = _requested_model
                                    yield f'data: {json.dumps(data)}\n\n'
                                elif data.get("type") == "agent_terminal":
                                    terminal_metadata = dict(data.get("data") or {})
                                    last_metrics = terminal_metadata
                                    failure = terminal_metadata.get("failure") or {}
                                    failure_status = _normalize_http_status(
                                        failure.get("status")
                                    )
                                    failure_message = (
                                        f"Model request failed (HTTP {failure_status})"
                                        if failure_status is not None
                                        else "Model request failed"
                                    )
                                    terminal_metadata["failure"] = {
                                        "status": failure_status,
                                        "message": failure_message,
                                    }
                                    terminal_content = full_response.strip()
                                    failure_note = f"[Agent stopped: {failure_message}]"
                                    if terminal_content:
                                        terminal_content = f"{terminal_content}\n\n{failure_note}"
                                    else:
                                        terminal_content = failure_note
                                    if not _terminal_saved:
                                        _saved_id = save_assistant_response(
                                            sess,
                                            session_manager,
                                            session,
                                            terminal_content,
                                            terminal_metadata,
                                            character_name=ctx.preset.character_name,
                                            web_sources=web_sources,
                                            rag_sources=ctx.rag_sources,
                                            used_memories=ctx.used_memories,
                                            fallback_chain=_fallback_chain,
                                            auto_escalation=_auto_escalation_payload if auto_escalated else None,
                                            incognito=incognito,
                                        )
                                        _terminal_saved = True
                                        accumulate_token_usage(session, terminal_metadata, outcome="error")
                                        _stream_set(session, status="error")
                                        if _saved_id:
                                            yield f'data: {json.dumps({"type": "message_saved", "id": _saved_id})}\n\n'
                                    yield chunk
                                elif data.get("type") == "metrics":
                                    last_metrics = data.get("data", {})
                                    _reported_model = last_metrics.get("model")
                                    last_metrics["requested_model"] = last_metrics.get("requested_model") or _requested_model
                                    last_metrics["model"] = _reported_model or _actual_model or _answered_by or _requested_model
                                    if ctx.context_trimmed:
                                        last_metrics["context_trimmed"] = True
                                        last_metrics["context_messages_before_trim"] = ctx.context_messages_before_trim
                                        last_metrics["context_messages_after_trim"] = ctx.context_messages_after_trim
                                        last_metrics["context_tokens_before_trim"] = ctx.context_tokens_before_trim
                                        last_metrics["context_tokens_after_trim"] = ctx.context_tokens_after_trim
                                    _metrics_event = {"type": "metrics", "data": last_metrics}
                                    # Inline teacher escalation marks its
                                    # recursively emitted events at the SSE
                                    # envelope. Preserve that non-secret marker
                                    # when normalizing metrics so the browser's
                                    # replay-stable ledger keeps primary and
                                    # teacher segments distinct.
                                    if data.get("teacher") is True:
                                        _metrics_event["teacher"] = True
                                    yield f'data: {json.dumps(_metrics_event)}\n\n'
                            except json.JSONDecodeError:
                                yield chunk
                        elif chunk.startswith("event: "):
                            yield chunk
                        elif chunk == "data: [DONE]\n\n":
                            _has_tool_events = bool((last_metrics or {}).get("tool_events"))
                            if full_response or _has_tool_events:
                                _response_to_save = full_response or "Done."
                                _metrics_to_save = dict(last_metrics or {})
                                if thinking_response.strip() and not _metrics_to_save.get("thinking"):
                                    _metrics_to_save["thinking"] = thinking_response.strip()
                                _saved_id = save_assistant_response(
                                    sess, session_manager, session, _response_to_save, _metrics_to_save,
                                    character_name=ctx.preset.character_name,
                                    web_sources=web_sources,
                                    rag_sources=ctx.rag_sources,
                                    used_memories=ctx.used_memories,
                                    fallback_chain=_fallback_chain,
                                    auto_escalation=_auto_escalation_payload if auto_escalated else None,
                                    incognito=incognito,
                                )
                                if _saved_id:
                                    yield f'data: {json.dumps({"type": "message_saved", "id": _saved_id})}\n\n'
                                run_post_response_tasks(
                                    sess, session_manager, session, message, _response_to_save,
                                    _metrics_to_save, ctx.uprefs, memory_manager, memory_vector, webhook_manager,
                                    incognito=incognito, compare_mode=compare_mode,
                                    character_name=ctx.preset.character_name,
                                                            agent_rounds=_agent_rounds,
                                    agent_tool_calls=_agent_tool_calls,
                                    skills_manager=skills_manager,
                                    owner=_user,
                                    extract_skills=(
                                        user_requested_agent
                                        and not tool_approval_continuation
                                    ),
                                    allow_background_extraction=(
                                        not tool_policy.block_all_tool_calls
                                        and not tool_approval_continuation
                                    ),
                                )
                            _stream_set(session, status="done")
                            yield chunk
                except (asyncio.CancelledError, GeneratorExit):
                    # Client disconnected — save partial response. Wrap
                    # the save in its own try so an exception inside
                    # add_message / save_sessions doesn't mask the
                    # original CancelledError (which prevented the
                    # outer finally from running and left _active_streams
                    # with a stale entry).
                    try:
                        if full_response and not incognito:
                            logger.info("Client disconnected mid-stream for session %s, saving partial response (%d chars)", session, len(full_response))
                            _stopped_content2, _stopped_md2 = clean_thinking_for_save(
                                full_response,
                                {
                                    "stopped": True,
                                    "model": _actual_model or _answered_by or _requested_model,
                                    "requested_model": _requested_model,
                                    "endpoint_id": _agent_actual_endpoint_id,
                                    "endpoint_label": _agent_actual_endpoint_label,
                                    "requested_endpoint_id": _agent_requested_route.get("endpoint_id"),
                                    "requested_endpoint_label": _agent_requested_route.get("endpoint_label"),
                                    "round_models": [
                                        _agent_round_models.get(i, _actual_model or _requested_model)
                                        for i in range(1, max(_agent_round_models, default=1) + 1)
                                    ],
                                    "round_endpoint_ids": [
                                        _agent_round_endpoint_ids.get(i)
                                        for i in range(1, max(_agent_round_models, default=1) + 1)
                                    ],
                                    "round_endpoint_labels": [
                                        _agent_round_endpoint_labels.get(i)
                                        for i in range(1, max(_agent_round_models, default=1) + 1)
                                    ],
                                },
                            )
                            sess.add_message(ChatMessage("assistant", _stopped_content2, metadata=_stopped_md2))
                            session_manager.save_sessions()
                    except Exception:
                        logger.exception("Failed to save partial response on disconnect (session %s)", session)
                    raise
                finally:
                    _active_streams.pop(session, None)

        async def _safe_stream() -> AsyncGenerator[str, None]:
            """Wrapper that guarantees _active_streams cleanup even if stream_with_save
            raises before reaching a mode-specific finally block."""
            try:
                async for chunk in stream_with_save():
                    yield chunk
            finally:
                _active_streams.pop(session, None)

        # Compare panes are short-lived, single-shot generations whose sessions
        # exist only to drive that one pane — there's nothing to "resume" and
        # the user expects the pane's Stop button (which aborts the fetch,
        # closing this SSE) to promptly cancel the upstream LLM call. Detaching
        # them would keep burning upstream tokens/compute after the pane is
        # stopped or the comparison is abandoned, and would surface a stale
        # "still streaming" /resume target for a session nobody will revisit.
        #
        # So: stream them directly (no agent_runs wrapping). Starlette cancels
        # the underlying async generator (raising CancelledError/GeneratorExit
        # inside it) as soon as it notices the client disconnected — which the
        # mode-specific except blocks above already handle by saving the
        # partial response exactly once. This stops the upstream call promptly
        # without waiting on the next streamed chunk.
        #
        # Normal chat/agent streams keep the DETACHED behavior below: they
        # survive the client closing the tab / navigating away. The SSE response just subscribes (replay
        # buffered output + live); dropping the SSE only removes a subscriber —
        # the run keeps going and saves the assistant message on completion
        # regardless. Reconnect via /api/chat/resume.
        if compare_mode:
            return StreamingResponse(_safe_stream(), media_type="text/event-stream")

        # Registering the run also decides whether it can be steered, and the
        # answer is the one the stream already announced — computed once beside
        # `_effective_mode` rather than a second time here, so the refusal and
        # the affordance cannot disagree (`B14`, `Law 13`). `compare_mode` has
        # returned above, so the clause folded into `_turn_is_steerable` for the
        # announcement's sake changes nothing on this path.
        _detached_run = agent_runs.start(
            session,
            _safe_stream(),
            steerable=_turn_is_steerable,
        )
        return StreamingResponse(
            agent_runs.subscribe(session, _detached_run),
            media_type="text/event-stream",
            headers={"X-Pantheon-Run-Id": _detached_run.run_id},
        )

    # ------------------------------------------------------------------ #
    # GET /api/chat/resume — reconnect to a detached run that's still going
    # (e.g. after reopening a session whose agent kept running in the background)
    # ------------------------------------------------------------------ #
    @router.get("/api/chat/resume/{session_id}")
    async def chat_resume(request: Request, session_id: str) -> StreamingResponse:
        _verify_session_owner(request, session_id)
        _active_run = agent_runs.get_active_run(session_id)
        if _active_run is None:
            raise HTTPException(404, "No active run for this session")
        return StreamingResponse(
            agent_runs.subscribe(session_id, _active_run),
            media_type="text/event-stream",
            headers={"X-Pantheon-Run-Id": _active_run.run_id},
        )

    # ------------------------------------------------------------------ #
    # POST /api/chat/stop — cancel a detached run (Stop button). Closing the SSE
    # no longer stops it (it's detached), so the Stop button must call this.
    # ------------------------------------------------------------------ #
    @router.post("/api/chat/stop/{session_id}")
    async def chat_stop(request: Request, session_id: str) -> Dict[str, Any]:
        _verify_session_owner(request, session_id)
        _expected_run_id = request.headers.get("X-Pantheon-Run-Id")
        stopped = agent_runs.stop(session_id, _expected_run_id)
        return {"stopped": stopped}

    # ------------------------------------------------------------------ #
    # POST /api/chat/steer — redirect the run that is already in flight
    # (P6-18). The queue holds the NEXT message; this carries a correction for
    # the one running, which `src/agent_loop.py` delivers at the next round
    # boundary. Verdicts ride in the body, not in an HTTPException: the client
    # renders `reason` and FastAPI's error shape carries only `detail`.
    #
    # Every status this route can answer with:
    #   200  probe answered, or the steer reached the inbox
    #   400  malformed body, empty steer, or one over STEER_MAX_CHARS
    #   401  no authenticated caller (auth on, nobody signed in)
    #   403  not the caller's session, or no such session — one refusal, so
    #        neither can be told from the other
    #   409  no run that can consume a steer is in flight
    #   429  STEER_MAX_PENDING already waiting
    # 404/405/501 are absent by construction; see `_STEER_REFUSAL_STATUS`.
    # ------------------------------------------------------------------ #
    @router.post("/api/chat/steer/{session_id}")
    async def chat_steer(request: Request, session_id: str) -> JSONResponse:
        # Decided before the body is read, so the probe below cannot become a
        # cheaper route to session state than the steer itself — it reports
        # whether a run is live, which is the owner's business alone.
        #
        # `_verify_session_owner` refuses "not yours" and "no such session"
        # identically, which is what keeps this off being an existence oracle;
        # its status is re-stamped 403 here, with its wording untouched, and
        # only for the codes it uses for that refusal. 404 cannot leave this
        # route: `chatStream.js` reads 404/405/501 as "this build has no steer
        # transport" and retires the control for the rest of the page's life,
        # so a steer aimed at a session another tab has just deleted used to
        # kill steering in this one and report it as unsupported by the server.
        # A caller with no session at all still gets 401 from the same call —
        # that is authentication, not ownership, and stays as it is.
        try:
            _verify_session_owner(request, session_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                raise HTTPException(403, exc.detail)
            raise

        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON")
        if not isinstance(body, dict):
            raise HTTPException(400, "Invalid JSON")

        # The capability probe fires when the first run of the page starts —
        # `chatStream.js` calls it from its `pantheon:chat-busy-change`
        # listener, on the active edge — and only asks whether this build has
        # the route, so it answers without touching the inbox. (It used to say
        # "once on page load, before the user has typed anything"; there has
        # never been a call site that early, and a reader who believed it would
        # look for a probe that never fires on an idle page.)
        #
        # `is True`, not truthiness: `{"probe": "no"}` is a string and would
        # have read as a probe, while `{"probe": 0}` fell through to the steer
        # path. The wire type for a flag is a bool.
        #
        # The reply used to also carry `"active"`. Nothing read it —
        # `probeSteerSupport` branches on `res.status` alone — so it was a
        # liveness answer with no reader (`Law 13`), and it reported
        # `is_active`, which is not the question a steer is gated on anyway.
        if body.get("probe") is True:
            return JSONResponse({"supported": True})

        # Liveness is agent_runs' question and is deliberately not re-decided
        # inside agent_loop (`Law 14`), so the gate belongs here — but the
        # predicate is `is_steerable`, not `is_active`. This comment used to
        # justify the gate with `is_active` behind it, and described an outcome
        # the gate did not prevent: `is_active` is true for a plain chat or
        # image-generation stream as well, neither of which ever calls
        # `consume_steers_for_round`, so a steer sent during one was accepted,
        # reported to the user as landing at the next step, and then dropped by
        # `clear_steers` — exactly the loss the sentence claimed was avoided.
        # With `is_steerable` the refusal happens instead, and the client falls
        # back to the queue on `no_active_run`, which is what makes the words
        # survive.
        if not agent_runs.is_steerable(session_id):
            return JSONResponse(
                # `pending` on every verdict, refusals included: `submit_steer`
                # reports the backlog even when it refuses, and a client that
                # has to special-case one reason for a missing field is a
                # client that will forget to.
                {"accepted": False, "reason": "no_active_run",
                 "pending": len(pending_steers(session_id))},
                status_code=_STEER_REFUSAL_STATUS["no_active_run"],
            )

        # `submit_steer` coerces with `str()` rather than typing its argument,
        # so a JSON object here would reach the model as its repr.
        text = body.get("text")
        verdict = submit_steer(session_id, text if isinstance(text, str) else "")
        if verdict.get("accepted"):
            return JSONResponse(verdict)
        return JSONResponse(
            verdict,
            status_code=_STEER_REFUSAL_STATUS.get(verdict.get("reason"), 400),
        )

    # ------------------------------------------------------------------ #
    # GET /api/chat/stream_status — check if a stream is active for a session
    # ------------------------------------------------------------------ #
    @router.get("/api/chat/stream_status/{session_id}")
    async def chat_stream_status(request: Request, session_id: str) -> Dict[str, Any]:
        _verify_session_owner(request, session_id)
        # A detached run can still be going even if _active_streams was popped;
        # report it as active so the client knows to reconnect via /resume.
        # Read once via .get() to avoid a KeyError race between the membership
        # check and the indexed read if a sibling stream's finally pops the
        # entry in between (same pattern _stream_set already uses).
        rec = _active_streams.get(session_id)
        if rec is None:
            if agent_runs.is_active(session_id):
                return {"status": "streaming", "detached": True}
            raise HTTPException(404, "No active stream for this session")
        return rec

    # ------------------------------------------------------------------ #
    # POST /api/inject_context
    # ------------------------------------------------------------------ #
    @router.post("/api/inject_context/{session_id}")
    async def inject_context(request: Request, session_id: str, context: str = Form(...)) -> Dict[str, str]:
        _verify_session_owner(request, session_id)
        try:
            sess = session_manager.get_session(session_id)
            msg = untrusted_context_message("injected research context", f"Research Context: {context}")
            sess.add_message(ChatMessage(msg["role"], msg["content"], metadata=msg.get("metadata")))
            session_manager.save_sessions()
            return {"status": "context_injected"}
        except KeyError:
            raise HTTPException(404, "Session not found")

    # ------------------------------------------------------------------ #
    # GET /api/search — search across chat messages
    # ------------------------------------------------------------------ #
    @router.get("/api/search")
    async def search_messages(
        request: Request,
        q: str = Query("", min_length=0),
        limit: int = Query(20, ge=1, le=100),
    ) -> List[Dict[str, Any]]:
        if not q or not q.strip():
            return []

        _user = effective_user(request)
        return [
            result.to_dict()
            for result in search_session_messages(
                q,
                limit=limit,
                owner=_user,
                restrict_owner=_user is not None,
                include_legacy_owner=False,
            )
        ]

    # ------------------------------------------------------------------ #
    # POST /api/rewrite — lightweight rewrite of last AI message (no tools)
    # ------------------------------------------------------------------ #
    @router.post("/api/rewrite")
    async def rewrite_message(request: Request) -> StreamingResponse:
        """Rewrite the last AI message with an instruction (shorter/simpler/etc).

        Unlike the full chat pipeline, this does NOT run the agent loop or tools.
        It just asks the LLM to rewrite the given text.
        """
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON")

        session_id = body.get("session_id")
        original_text = body.get("original_text", "")
        instruction = body.get("instruction", "")

        if not session_id or not original_text or not instruction:
            raise HTTPException(400, "session_id, original_text, and instruction are required")

        _verify_session_owner(request, session_id)

        try:
            sess = session_manager.get_session(session_id)
        except (KeyError, SessionNotFoundError):
            raise HTTPException(404, "Session not found")

        messages = [
            {"role": "system", "content": (
                "You are rewriting a previous response. Follow the instruction exactly. "
                "Output ONLY the rewritten text — no preamble, no explanation, no meta-commentary. "
                "Preserve any formatting (markdown, code blocks, lists) from the original."
            )},
            {"role": "user", "content": (
                f"Here is the original response:\n\n{original_text}\n\n"
                f"Instruction: {instruction}"
            )},
        ]

        async def stream_rewrite() -> AsyncGenerator[str, None]:
            full_response = ""
            try:
                async for chunk in stream_llm(
                    sess.endpoint_url,
                    sess.model,
                    messages,
                    headers=sess.headers,
                    temperature=0.7,
                    # 0 = let the server decide (no cap). A hardcoded 4096 made
                    # local reasoning models (Qwen3 / R1) burn the whole budget
                    # inside <think> and emit no rewrite — the bubble just hung
                    # on "Rewriting...". Same fix as the chat max_tokens cap.
                    max_tokens=0,
                    tools=None,
                ):
                    if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                        try:
                            data = json.loads(chunk[6:])
                            if "delta" in data:
                                # Forward the chunk (so the client can show a
                                # thinking indicator) but DON'T fold reasoning
                                # tokens into the saved rewrite — only real
                                # content. reasoning_content arrives flagged
                                # with thinking:true.
                                if not data.get("thinking"):
                                    full_response += data["delta"]
                                yield chunk
                        except json.JSONDecodeError:
                            yield chunk
                    elif chunk.startswith("event: "):
                        yield chunk
                    elif chunk == "data: [DONE]\n\n":
                        # Update the last assistant message in session history.
                        # Strip reasoning-model <think> blocks so the persisted
                        # rewrite is just the rewritten text, not its scratchpad.
                        from src.research_utils import strip_thinking
                        full_response = strip_thinking(full_response).strip() or full_response
                        if full_response:
                            for msg in reversed(sess.history):
                                if (isinstance(msg, ChatMessage) and msg.role == 'assistant') or \
                                   (isinstance(msg, dict) and msg.get('role') == 'assistant'):
                                    if isinstance(msg, ChatMessage):
                                        msg.content = full_response
                                    else:
                                        msg['content'] = full_response
                                    break
                            # Update in DB too
                            db = SessionLocal()
                            try:
                                db_msg = (
                                    db.query(DBChatMessage)
                                    .filter(DBChatMessage.session_id == session_id, DBChatMessage.role == 'assistant')
                                    .order_by(DBChatMessage.timestamp.desc())
                                    .first()
                                )
                                if db_msg:
                                    db_msg.content = full_response
                                    db.commit()
                            except Exception as e:
                                logger.warning("Failed to update rewritten message in DB: %s", e)
                                db.rollback()
                            finally:
                                db.close()
                            session_manager.save_sessions()
                        yield chunk
            except Exception as e:
                logger.error("Rewrite stream error: %s", e)
                yield f'event: error\ndata: {json.dumps({"error": str(e), "status": 500})}\n\n'

        return StreamingResponse(stream_rewrite(), media_type="text/event-stream")

    # ------------------------------------------------------------------ #
    # Standing allow rules for the `allow_listed` trust rung (P7-04)
    #
    # These live in this module because it is already where a tool approval is
    # answered — `tool_approval_id` / `tool_approval_decision` above resolve the
    # "allow this once" card. A rule is the durable form of the same answer, so
    # both now share one module and one vocabulary rather than sitting in two
    # surfaces that can drift.
    #
    # `require_user` before anything else: it 403s bearer API tokens (no token
    # scope grants the right to lower an owner's confirmation gate) and 401s an
    # unauthenticated caller. The owner is then resolved from the request and
    # never from the body — see `_allow_rule_owner`.
    # ------------------------------------------------------------------ #

    @router.get("/api/tool-allow-rules")
    async def list_tool_allow_rules(request: Request) -> Dict[str, Any]:
        """Every standing allow rule belonging to the caller.

        Listable is half of revocable: a grant nobody can see is one nobody
        thinks to take back.
        """
        owner = _allow_rule_owner(request)
        return {
            "rules": tool_allow_rules.list_rules(owner),
            # The vocabulary travels with the list so a chooser is built from
            # the store's own kinds. Hardcoding the three strings client-side
            # would be a second vocabulary, and a kind added to one and not the
            # other renders as a blank option or an unsubmittable form.
            "match_kinds": list(tool_allow_rules.MATCH_KINDS),
        }

    @router.post("/api/tool-allow-rules")
    async def create_tool_allow_rule(
        request: Request,
        body: ToolAllowRuleCreate,
    ) -> Dict[str, Any]:
        owner = _allow_rule_owner(request)
        if body.owner is not None and body.owner.strip() != owner:
            # Refused rather than quietly rewritten to the caller. A client that
            # believes it is writing a rule for someone else has to be told it
            # is not, or the mistake ships as a rule in the wrong list.
            raise HTTPException(403, "An allow rule can only be created for yourself")
        try:
            return tool_allow_rules.create_rule(
                owner,
                body.tool_name,
                body.match_kind,
                body.pattern,
            )
        except tool_allow_rules.AllowRuleError as exc:
            raise HTTPException(400, str(exc))
        except Exception:
            logger.warning("tool allow rule create failed", exc_info=True)
            raise HTTPException(500, "Could not save the allow rule")

    @router.delete("/api/tool-allow-rules/{rule_id}")
    async def delete_tool_allow_rule(request: Request, rule_id: str) -> Dict[str, str]:
        owner = _allow_rule_owner(request)
        try:
            revoked = tool_allow_rules.delete_rule(owner, rule_id)
        except Exception:
            logger.warning("tool allow rule revoke failed", exc_info=True)
            raise HTTPException(500, "Could not revoke the allow rule")
        if not revoked:
            # 404 for another owner's rule as much as for one that never
            # existed, so this route cannot be used to probe which rule ids are
            # real.
            raise HTTPException(404, "Allow rule not found")
        return {"status": "revoked", "id": rule_id}

    return router
