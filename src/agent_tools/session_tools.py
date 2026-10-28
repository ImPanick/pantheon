# SPDX-License-Identifier: AGPL-3.0-or-later
"""session_tools.py - agent tools for AI-to-AI session management.

Owns create_session, list_sessions, send_to_session and manage_session, moved
out of src.ai_interaction as part of the tool -> registry migration (#3629), and
their handler classes registered in TOOL_HANDLERS — and `read_chat` (`B1621`),
one of the person's own chats read through.

The session manager is a runtime-set singleton in src.ai_interaction, so each
function fetches it via get_session_manager() (imported here); _resolve_model and
AI_CHAT_TIMEOUT are reused from there too.
"""
import asyncio
import json
import logging
import uuid
from typing import Dict, Optional

from src.ai_interaction import get_session_manager, _resolve_model, AI_CHAT_TIMEOUT

logger = logging.getLogger(__name__)


async def create_session(content: str, session_id: Optional[str] = None, owner: Optional[str] = None) -> Dict:
    """Create a new chat session.

    Content format:
      Line 1: session name
      Line 2: model_name (or model_name@endpoint_name)
    """
    _session_manager = get_session_manager()
    if not _session_manager:
        return {"error": "Session manager not available"}

    lines = content.strip().split("\n")
    if len(lines) < 2:
        return {"error": "Need 2 lines: session name, then model spec"}

    name = lines[0].strip()
    model_spec = lines[1].strip()

    if not name:
        return {"error": "Session name cannot be empty"}

    try:
        url, model, headers = await asyncio.to_thread(_resolve_model, model_spec, owner=owner)
    except ValueError as e:
        return {"error": str(e)}

    sid = str(uuid.uuid4())[:8]
    try:
        _session_manager.create_session(
            session_id=sid,
            name=name,
            endpoint_url=url,
            model=model,
            rag=False,
            owner=owner,
        )
        # Store headers on session for future calls
        sess = _session_manager.get_session(sid)
        if sess and headers:
            sess.headers = headers
        try:
            from src.event_bus import fire_event
            # `P8-23`. Which chat.
            fire_event("session_created", owner,
                       {"session_id": sid, "name": name})
        except Exception:
            logger.debug("session_created event dispatch failed", exc_info=True)

        return {"session_id": sid, "name": name, "model": model, "endpoint_url": url}
    except Exception as e:
        logger.error(f"create_session failed: {e}")
        return {"error": f"Failed to create session: {e}"}

async def list_sessions(content: str, session_id: Optional[str] = None, owner: Optional[str] = None) -> Dict:
    """List sessions sorted by most-recently-active first.

    Output includes a relative "last active" timestamp per row so the
    agent can answer "open my last chat" without guessing from titles.
    The most-recent session is always first in the list.

    Content = optional filter keyword (matches session name).
    """
    _session_manager = get_session_manager()
    if not _session_manager:
        return {"error": "Session manager not available"}

    keyword = content.strip().lower() if content.strip() else None

    try:
        from core.database import SessionLocal, Session as DbSession
        from datetime import datetime, timezone

        # SECURITY: scope to the caller's sessions. Passing None returned
        # every user's sessions, which the agent tool then exposed via the
        # "list my chats" reply.
        # `B1224` (fx-ops): the caller's own newest chats from the database,
        # as the sidebar's first page (`list_page`). It filtered the boot
        # cache — the 100 most recently used chats of every owner — so a
        # person whose chats were older than someone else's last 100 was told
        # they had none.
        page, has_more = _session_manager.list_page(owner, limit=100)
        sessions = {sess.id: sess for sess in page}

        # The rows' last_accessed, to sort by recency — this page's only (it
        # read every owner's row, every call).
        db = SessionLocal()
        try:
            db_rows = {r.id: r for r in db.query(DbSession).filter(
                DbSession.id.in_(list(sessions))).all()} if sessions else {}
        finally:
            db.close()

        rows = []
        for sid, sess in sessions.items():
            if (sess.name or "").startswith("SFT trace batch"):
                continue
            if keyword and keyword not in (sess.name or "").lower():
                continue
            db_row = db_rows.get(sid)
            # Prefer last_accessed; fall back to updated_at, then created_at.
            ts = None
            if db_row:
                ts = getattr(db_row, 'last_accessed', None) or getattr(db_row, 'updated_at', None) or getattr(db_row, 'created_at', None)
            rows.append((ts, sid, sess))

        # Sort by timestamp DESC; rows without a timestamp sink to the bottom.
        rows.sort(key=lambda r: r[0] or datetime.min, reverse=True)

        def _rel(ts):
            if not ts:
                return 'never'
            now = datetime.utcnow()
            try:
                if ts.tzinfo is not None:
                    now = datetime.now(timezone.utc)
                diff = (now - ts).total_seconds()
            except Exception:
                return 'unknown'
            if diff < 60: return 'just now'
            if diff < 3600: return f'{int(diff / 60)}m ago'
            if diff < 86400: return f'{int(diff / 3600)}h ago'
            if diff < 86400 * 7: return f'{int(diff / 86400)}d ago'
            return ts.strftime('%Y-%m-%d')

        lines = []
        for i, (ts, sid, sess) in enumerate(rows):
            if i >= 50:
                lines.append(f"... and {len(rows) - 50} more (showing first 50)")
                break
            safe_name = (sess.name or "Untitled").replace("[", "\\[").replace("]", "\\]")
            msg_count = getattr(sess, "message_count", 0) or 0
            model = getattr(sess, "model", "unknown")
            marker = " ← most recent" if i == 0 else ""
            lines.append(f"- **[{safe_name}](#session-{sid})** (id: `{sid}`, model: {model}, {msg_count} msgs, last active {_rel(ts)}){marker}")

        if not lines:
            return {"results": "No sessions found" + (f" matching '{keyword}'" if keyword else "") + "."}
        if has_more:
            lines.append("(Older chats exist; these are the 100 most recently active.)")

        return {
            "results": (
                f"Found {len(rows)} session(s), sorted most-recent first:\n"
                + "\n".join(lines)
                + "\n\nAssistant: when replying to the user, preserve the chat-title markdown links exactly as shown, e.g. `[Chat](#session-id)`. Do not rewrite this as a plain, non-clickable table."
            )
        }
    except Exception as e:
        logger.error(f"list_sessions failed: {e}")
        return {"error": str(e)}

async def send_to_session(content: str, session_id: Optional[str] = None, owner: Optional[str] = None) -> Dict:
    """Send a message to an existing session and get a response.

    Content format:
      Line 1: session_id
      Line 2+: message
    """
    _session_manager = get_session_manager()
    from src.llm_core import llm_call_async
    from core.models import ChatMessage

    if not _session_manager:
        return {"error": "Session manager not available"}

    lines = content.strip().split("\n", 1)
    if len(lines) < 2:
        return {"error": "Need 2 lines: session_id, then message"}

    target_sid = lines[0].strip()
    message = lines[1].strip()

    sess = _session_manager.get_session(target_sid)
    if not sess:
        return {"error": f"Session '{target_sid}' not found"}

    # Owner-scope: reject access to another user's session. When the caller is
    # authenticated, a null-owner (legacy / auth-was-off) session is not theirs
    # either — list_sessions (`list_page`, owner-exact) and manage_session already
    # exclude those, so treating it as reachable here let an authenticated agent
    # read/write a session the other tools hide. Require an exact owner match.
    if owner and getattr(sess, "owner", None) != owner:
        return {"error": f"Session '{target_sid}' not found"}

    # `B994`. Never into the chat this call runs in. A message sent there is
    # persisted as that chat's newest *user* message — the place a plan reads
    # the person's answer from (`document_folders.plan_answer`) — so the agent
    # could write "Apply the plan" for the person and then apply its own plan;
    # measured, it deleted a document no one approved. Talking to the chat you
    # are already in is never what this tool is for: answer in the reply.
    if session_id and target_sid == session_id:
        return {"error": "send_to_session talks to another chat, and this is the chat "
                         "you are in. Answer here, in your reply.", "exit_code": 1}

    if not message:
        return {"error": "No message provided"}

    try:
        # Build context from session history
        context = sess.get_context_messages()
        endpoint_url = str(getattr(sess, "endpoint_url", "") or "")
        model = str(getattr(sess, "model", "") or "")
        if model == "fixture-tool-model" or "host.docker.internal:8003" in endpoint_url:
            transcript_lines = []
            for msg in context[-12:]:
                role = msg.get("role", "unknown")
                text = (msg.get("content") or "").strip()
                if text:
                    transcript_lines.append(f"{role}: {text}")
            transcript = "\n".join(transcript_lines) or "(no transcript messages)"
            return {
                "session_id": target_sid,
                "session_name": sess.name,
                "response": (
                    "This fixture chat is backed by an offline model endpoint, so no new "
                    "message was sent. Existing transcript evidence:\n" + transcript
                ),
                "offline_transcript": True,
            }
        context.append({"role": "user", "content": message})

        response = await llm_call_async(
            sess.endpoint_url, sess.model, context,
            headers=sess.headers,
            timeout=AI_CHAT_TIMEOUT,
        )

        # Save both messages to session
        sess.add_message(ChatMessage("user", message))
        sess.add_message(ChatMessage("assistant", response))

        # Truncate for tool output
        if len(response) > 10000:
            response = response[:10000] + "\n... (truncated)"

        return {
            "session_id": target_sid,
            "session_name": sess.name,
            "response": response,
        }
    except Exception as e:
        logger.error(f"send_to_session failed: {e}")
        return {
            "error": f"Failed to send to session: {e}",
            "untrusted_content": True,
        }

async def manage_session(content: str, session_id: Optional[str] = None, owner: Optional[str] = None) -> Dict:
    """Manage sessions: rename, archive, delete, important, truncate, fork.

    Content format:
      Line 1: action (rename|archive|unarchive|delete|important|unimportant|truncate|fork)
      Line 2: target session_id (or "current" to use the active session)
      Line 3+: action-specific params (e.g. new name for rename, keep_count for truncate)
    """
    _session_manager = get_session_manager()
    if not _session_manager:
        return {"error": "Session manager not available"}

    from src.database import SessionLocal, Session as DbSession

    # Accept BOTH the structured JSON args the tool schema advertises
    # ({action, session_id, value}) AND the legacy line-based format
    # (line1=action, line2=session_id, line3=value). Native function-calling
    # models send JSON; fenced-block callers send lines. Previously only the
    # line format was parsed, so a model that followed the schema (JSON) got
    # "Need at least 2 lines" / "Rename needs line 3" and couldn't drive it.
    _raw = (content or "").strip()
    action = ""
    target_sid = ""
    value = None      # the action param: new name (rename) / keep_count (truncate, fork)
    _list_filter = ""
    _parsed = None
    if _raw.startswith("{"):
        try:
            _parsed = json.loads(_raw)
        except Exception:
            _parsed = None
    if isinstance(_parsed, dict):
        action = str(_parsed.get("action") or "").strip().lower()
        target_sid = str(_parsed.get("session_id") or _parsed.get("session") or _parsed.get("id") or "").strip()
        _v = _parsed.get("value")
        if _v is None:
            _v = (_parsed.get("name") or _parsed.get("new_name")
                  or _parsed.get("title") or _parsed.get("keep_count"))
        value = None if _v is None else str(_v).strip()
        _list_filter = str(_parsed.get("filter") or "").strip()
    else:
        lines = _raw.split("\n")
        if not lines or not lines[0].strip():
            return {"error": "Missing action (rename|archive|delete|important|truncate|fork|list|switch)"}
        action = lines[0].strip().lower()
        target_sid = lines[1].strip() if len(lines) >= 2 else ""
        value = lines[2].strip() if len(lines) >= 3 else None
        _list_filter = "\n".join(lines[1:]).strip()

    if not action:
        return {"error": "Missing action (rename|archive|delete|important|truncate|fork|list|switch)"}

    # `list` alias - dispatch to list_sessions so the agent's natural
    # first guess (every other manage_* tool has a `list` action) works.
    if action == "list":
        return await list_sessions(_list_filter, session_id, owner=owner)

    if not target_sid:
        return {"error": "Need a session_id (or 'current' for the active chat)"}

    # Allow "current" to refer to the active session
    if target_sid.lower() == "current" and session_id:
        target_sid = session_id

    # `switch` / `open` / `select` / `view` - the agent reaches for
    # these when the user asks to "open" or "switch to" a session.
    # There's no server-side way to make the browser navigate, so we
    # just return a clickable anchor link the user can click. The
    # frontend's chat-history click delegate routes `#session-<id>`
    # to selectSession(). The agent's reply naturally embeds this
    # result so the user sees a single clickable line.
    def _session_query(db):
        query = db.query(DbSession).filter(DbSession.id == target_sid)
        if owner is not None:
            query = query.filter(DbSession.owner == owner)
        return query

    if action in ("switch", "open", "select", "view"):
        db = SessionLocal()
        try:
            db_sess = _session_query(db).first()
            if not db_sess:
                return {"error": f"Session '{target_sid}' not found. Use list_sessions and pass the exact id it returned."}
            name = db_sess.name or target_sid
        finally:
            db.close()
        return {
            "action": action,
            "session_id": target_sid,
            "name": name,
            "results": f"[{name}](#session-{target_sid}) - click to open.",
        }

    db = SessionLocal()
    try:
        if action == "rename":
            if not value:
                return {"error": "rename needs a new name (the `value` arg, or line 3 in the legacy format)"}
            new_name = value
            db_sess = _session_query(db).first()
            if not db_sess:
                return {"error": f"Session '{target_sid}' not found. Use list_sessions and pass the exact id it returned."}
            db_sess.name = new_name
            db.commit()
            _session_manager.update_session_name(target_sid, new_name)
            return {"action": "rename", "session_id": target_sid, "name": new_name,
                    "results": f"Session renamed to '{new_name}'"}

        elif action == "archive":
            db_sess = _session_query(db).first()
            if not db_sess:
                return {"error": f"Session '{target_sid}' not found. Use list_sessions and pass the exact id it returned."}
            db_sess.archived = True
            db.commit()
            return {"action": "archive", "session_id": target_sid,
                    "results": f"Session '{db_sess.name}' archived"}

        elif action == "unarchive":
            db_sess = _session_query(db).first()
            if not db_sess:
                return {"error": f"Session '{target_sid}' not found. Use list_sessions and pass the exact id it returned."}
            db_sess.archived = False
            db.commit()
            return {"action": "unarchive", "session_id": target_sid,
                    "results": f"Session '{db_sess.name}' unarchived"}

        elif action == "delete":
            if target_sid == session_id:
                return {"error": "Cannot delete the current session while chatting in it. Delete other sessions first."}
            db_sess = _session_query(db).first()
            if not db_sess:
                return {"error": f"Session '{target_sid}' not found. Refusing to delete an unknown chat id; use the exact id from list_sessions."}
            if db_sess and db_sess.is_important:
                return {"error": f"Session '{db_sess.name}' is starred/favorited. Unstar it first before deleting."}
            try:
                ok = _session_manager.delete_session(target_sid)
                if not ok:
                    return {"error": f"Session '{target_sid}' was not deleted because it no longer exists."}
                return {"action": "delete", "session_id": target_sid,
                        "results": f"Session '{db_sess.name or target_sid}' deleted"}
            except Exception as e:
                return {"error": f"Failed to delete session: {e}"}

        elif action in ("important", "unimportant"):
            is_important = action == "important"
            db_sess = _session_query(db).first()
            if not db_sess:
                return {"error": f"Session '{target_sid}' not found. Use list_sessions and pass the exact id it returned."}
            # Prevent AI from unstarring sessions - only the user can do that manually
            if not is_important and db_sess.is_important:
                return {"error": f"Session '{db_sess.name}' is starred by the user. Only the user can unstar sessions manually."}
            db_sess.is_important = is_important
            db.commit()
            status = "marked as important" if is_important else "unmarked as important"
            return {"action": action, "session_id": target_sid,
                    "results": f"Session '{db_sess.name}' {status}"}

        elif action == "truncate":
            db_sess = _session_query(db).first()
            if not db_sess:
                return {"error": f"Session '{target_sid}' not found. Use list_sessions and pass the exact id it returned."}
            keep_count = 10
            if value:
                try:
                    keep_count = int(value)
                except ValueError:
                    pass
            success = _session_manager.truncate_messages(target_sid, keep_count)
            if success:
                return {"action": "truncate", "session_id": target_sid,
                        "results": f"Session truncated to last {keep_count} messages"}
            return {"error": f"Failed to truncate session '{target_sid}'"}

        elif action == "fork":
            db_sess = _session_query(db).first()
            if not db_sess:
                return {"error": f"Session '{target_sid}' not found. Use list_sessions and pass the exact id it returned."}
            keep_count = 0  # 0 = all messages
            if value:
                try:
                    keep_count = int(value)
                except ValueError:
                    pass

            source = _session_manager.get_session(target_sid)
            if not source:
                return {"error": f"Session '{target_sid}' not found"}

            new_sid = str(uuid.uuid4())[:8]
            _session_manager.create_session(
                session_id=new_sid,
                name=f"Fork: {source.name}",
                endpoint_url=source.endpoint_url,
                model=source.model,
                rag=False,
                owner=owner,
            )
            # Copy messages
            history = source.get_context_messages()
            if keep_count > 0:
                history = history[:keep_count]
            from core.models import ChatMessage as InMemoryMsg
            new_sess = _session_manager.get_session(new_sid)
            for msg in history:
                new_sess.add_message(InMemoryMsg(msg["role"], msg["content"]))
            try:
                from src.event_bus import fire_event
                fire_event("session_created", owner,
                           {"session_id": new_sid,
                            "name": getattr(new_sess, "name", None)})
            except Exception:
                logger.debug("session_created event dispatch failed", exc_info=True)

            return {"action": "fork", "session_id": new_sid,
                    "source_session": target_sid, "messages_copied": len(history),
                    "results": f"Forked session '{source.name}' -> new session {new_sid} ({len(history)} messages)"}

        else:
            return {"error": f"Unknown action '{action}'. Use: list, switch, rename, archive, unarchive, delete, important, unimportant, truncate, fork"}
    except Exception as e:
        logger.error(f"manage_session failed: {e}")
        return {"error": str(e)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# `B1621` · read_chat — one of the person's own chats, in full, a page at a time
# ---------------------------------------------------------------------------
#
# `search_chats` hands back a match and 180 characters either side of it, and
# `list_sessions` the titles; nothing read a chat through. So Decision Log,
# Weekly Review, FAQ Builder, Dataset Curator and Eval Builder — whose jobs are
# to summarise what was said — summarised snippets. `read_chat` reads one chat,
# its messages in order, bounded: a page of at most `READ_CHAT_MAX_CHARS`, each
# message cut at `READ_CHAT_MESSAGE_MAX_CHARS` with how much was left out
# said, and where the next page starts.
#
# **Owner-scoped, and only that** (the adversary, `Law 17`, is a chat that is
# not the caller's: another person's, asked for by id — a model guessing, or
# an id a page planted). The chat is read only when its row's owner **is** the
# caller: not `owner IS NULL` too, as `search_chats` reads the pre-auth rows
# (which is why that one is an admin's), and not when the call names no owner
# — a call that cannot say whose chats it may read reads none. A chat that is
# someone else's is answered exactly as one that does not exist, so the answer
# does not tell anyone it is there.

#: How much of a chat one call hands the model: a long conversation in two or
#: three calls, never a year of one in a single context.
READ_CHAT_MAX_CHARS = 24_000
#: A message longer than this is cut, and the cut is said.
READ_CHAT_MESSAGE_MAX_CHARS = 6_000
#: What a chat's reader reads: what the person and the assistant said.
READ_CHAT_ROLES = ("user", "assistant")

NOT_YOUR_CHAT = ("There is no chat with that id among yours. Call list_sessions or search_chats "
                 "and pass the id they give.")
NO_OWNER = ("Reading a chat needs to know whose chats it may read, and this call does not say, "
            "so nothing was read.")


def _read_chat_args(content) -> tuple:
    """`(chat id, first message number)` from `{"session_id", "from"}` or the
    fenced form (line 1 the id, line 2 where to start). A link the other chat
    tools print (`[title](#session-<id>)`) is read as its id."""
    raw = content if isinstance(content, dict) else None
    text = "" if raw is not None else str(content or "").strip()
    if raw is None and text.startswith("{"):
        try:
            raw = json.loads(text)
        except ValueError:
            raw = None
    if isinstance(raw, dict):
        sid = raw.get("session_id") or raw.get("chat_id") or raw.get("id") or ""
        start = raw.get("from") or raw.get("start") or 1
    else:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        sid = lines[0] if lines else ""
        start = lines[1] if len(lines) > 1 else 1
    sid = str(sid).strip()
    if "#session-" in sid:
        sid = sid.split("#session-", 1)[1].split(")", 1)[0]
    sid = sid.strip("`'\" ")
    try:
        start = max(1, int(start))
    except (TypeError, ValueError):
        start = 1
    return sid, start


def _read_chat_page(owner: str, target: str, start: int) -> Dict:
    from core.database import ChatMessage as DbChatMessage, Session as DbSession, SessionLocal

    db = SessionLocal()
    try:
        row = (db.query(DbSession)
               .filter(DbSession.id == target, DbSession.owner == owner).first())
        if row is None:
            return {"error": NOT_YOUR_CHAT, "exit_code": 1}
        query = (db.query(DbChatMessage)
                 .filter(DbChatMessage.session_id == target, DbChatMessage.role.in_(READ_CHAT_ROLES))
                 .order_by(DbChatMessage.timestamp.asc(), DbChatMessage.id.asc()))
        total = query.count()
        name = row.name or "Untitled"
        if total == 0:
            return {"results": f"The chat “{name}” (id: `{target}`) has no messages yet.",
                    "session_id": target, "messages": 0}
        if start > total:
            return {"results": f"The chat “{name}” (id: `{target}`) has {total} messages; there is "
                               f"no message {start}. Start from 1.",
                    "session_id": target, "messages": total}
        lines, used, shown = [], 0, 0
        for n, msg in enumerate(query.offset(start - 1).all(), start=start):
            body = msg.content or ""
            if len(body) > READ_CHAT_MESSAGE_MAX_CHARS:
                body = (body[:READ_CHAT_MESSAGE_MAX_CHARS]
                        + f" … [{len(msg.content) - READ_CHAT_MESSAGE_MAX_CHARS:,} more characters of "
                          f"this message are not shown]")
            when = msg.timestamp.strftime("%Y-%m-%d %H:%M") if msg.timestamp else "undated"
            entry = f"[{n}] {msg.role} ({when}):\n{body}"
            if shown and used + len(entry) > READ_CHAT_MAX_CHARS:
                break
            lines.append(entry)
            used += len(entry)
            shown += 1
        last = start + shown - 1
        head = (f"The chat “{name}” (id: `{target}`) — messages {start} to {last} of {total}, "
                f"oldest first:")
        tail = ("That is the end of the chat." if last >= total else
                f"Messages {last + 1} to {total} are not shown: call read_chat with "
                f'{{"session_id": "{target}", "from": {last + 1}}} for them.')
        return {"results": "\n\n".join([head, *lines, tail]), "session_id": target,
                "messages": total, "shown": [start, last]}
    finally:
        db.close()


async def read_chat(content, session_id: Optional[str] = None, owner: Optional[str] = None) -> Dict:
    """`B1621`. One of the caller's own chats, read through, a page at a time."""
    if not owner:
        return {"error": NO_OWNER, "exit_code": 1}
    target, start = _read_chat_args(content)
    if not target:
        return {"error": "Which chat? Pass its id — list_sessions and search_chats give it.",
                "exit_code": 1}
    if target.lower() == "current" and session_id:
        target = session_id
    try:
        return await asyncio.to_thread(_read_chat_page, owner, target, start)
    except Exception as e:  # noqa: BLE001 — a read that fails says so, in a sentence
        logger.error("read_chat failed: %s", e)
        return {"error": f"The chat could not be read: {e}", "exit_code": 1}


# ---------------------------------------------------------------------------
# Handler classes registered in TOOL_HANDLERS
# ---------------------------------------------------------------------------

class CreateSessionTool:
    async def execute(self, content: str, ctx: dict) -> Dict:
        return await create_session(content, ctx.get("session_id"), owner=ctx.get("owner"))


class ListSessionsTool:
    async def execute(self, content: str, ctx: dict) -> Dict:
        return await list_sessions(content, ctx.get("session_id"), owner=ctx.get("owner"))


class SendToSessionTool:
    async def execute(self, content: str, ctx: dict) -> Dict:
        return await send_to_session(content, ctx.get("session_id"), owner=ctx.get("owner"))


class ManageSessionTool:
    async def execute(self, content: str, ctx: dict) -> Dict:
        return await manage_session(content, ctx.get("session_id"), owner=ctx.get("owner"))


class ReadChatTool:
    async def execute(self, content: str, ctx: dict) -> Dict:
        return await read_chat(content, ctx.get("session_id"), owner=ctx.get("owner"))
