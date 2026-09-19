# SPDX-License-Identifier: AGPL-3.0-or-later
# routes/memory_routes.py
from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, File
from typing import Dict, Any, Optional, List
import json
import os
import re
import tempfile
import time
from datetime import datetime
import logging
# H11: the diagnostic reports how the retriever read the question.
from src import memory_edges, memory_retrieval, memory_style

# Leading list-marker like "1.", "12)", or "3:" plus surrounding whitespace.
# Strips one prefix per call so import-from-LLM-output doesn't leave the
# numbering inside the saved memory text. Bullet markers (-, *, •) are
# also peeled here for the same reason.
_LIST_PREFIX_RE = re.compile(r"^\s*(?:\d{1,3}[.):]\s+|[-*•]\s+)")


def _strip_list_prefix(text: str) -> str:
    if not text:
        return text
    return _LIST_PREFIX_RE.sub("", text, count=1).strip()

from services.memory import MemoryManager, MemoryStoreUnreadable
from src.memory import archive_forecast, new_provenance
from core.session_manager import SessionManager
from src.request_models import MemoryAddRequest
from core.database import SessionLocal
from src.llm_core import llm_call_async
from services.memory import provider_import
from services.memory.memory_extractor import (
    COMMIT_COMMITTED,
    audit_memories,
    commit_memory,
    store_imported,
)
from src.auth_helpers import get_current_user, require_user
from src.endpoint_resolver import resolve_endpoint
from src.task_endpoint import resolve_task_endpoint
from src.upload_limits import read_upload_limited, resolve_byte_limit

logger = logging.getLogger(__name__)


def _record_style_edit(memory_id: str, action: str, owner: str = None) -> None:
    """The person corrected or removed what we wrote about them. `P13-17`.

    In the table `P14-01` already built, beside `P13-05`'s commitments and for
    the same reason that row gives: *"a commitment is the same kind of thing as
    the tool calls, retrievals and approvals already in it"*, and so is somebody
    telling us our description of them is wrong.

    **This is the feature's only instrument.** `D-2026-09-09-01` is explicit
    that there is no golden set for *did we describe you correctly* and there
    cannot be one — so *"did the person change what we wrote about them"* is
    the whole measurement, and a measurement nobody records is a measurement
    that does not exist. `outcome` is an enum and not a boolean (`Law 10`):
    `edited` and `deleted` are different verdicts on the same description and
    a flag could only carry one of them.
    """
    try:
        from src.events import record_event
        record_event("memory", name="style_profile", owner=owner,
                     outcome=action, detail={"memory_id": memory_id})
    except Exception:
        logging.getLogger(__name__).debug(
            "style profile event not recorded", exc_info=True)


def _style_block(memory_manager, owner: str = None) -> Dict[str, Any]:
    """How this person writes, as the Brain reads it. `P13-17`, `P13-20`.

    **A field on the payload that already reaches the Brain, and not a route of
    its own.** It started as `GET /api/memory/style` and
    `.pantheon/check-unreachable.py` was right to object: the count went 90 → 91
    against a ceiling of 90, because `static/**` belongs to another agent this
    wave and nothing would have called it. Raising a ratchet to admit an
    endpoint with no caller is the exact drift `Law 13` names, and the fix was
    not to raise it — the list payload is already fetched every time the Brain
    opens, and this is one more key on it. That is `P13-01`'s call on the
    confidence pill, applied one layer out: *the field and its one consumer,
    together.*

    `profile` is `None` until there is enough history, and `observed` /
    `needed` are why that branch carries two numbers rather than a null:
    **"18 of 20 messages seen"** is a sentence a cold reader understands
    (`Law 15`), and a page that can only say nothing is one they file as broken.

    **`humour.means` reads `null` for a long time and that is `P13-20` working.**
    Detecting that somebody jokes is trivial; knowing what their humour means is
    the whole problem, and until the evidence separates the three readings the
    honest answer is that we do not know.
    """
    profile = None
    try:
        profile = memory_manager.style_profile(owner=owner)
    except AttributeError:
        # A manager that predates this row. The Brain still lists memories.
        return {"profile": None, "observed": 0,
                "needed": memory_style.PROFILE_MIN_MESSAGES}
    totals = (profile or {}).get("style") or {}
    observed = int(totals.get("messages", 0) or 0)
    block = {"profile": None, "observed": observed,
             "needed": memory_style.PROFILE_MIN_MESSAGES}
    if not profile or observed < memory_style.PROFILE_MIN_MESSAGES:
        return block
    trait_values = memory_style.traits(totals)
    block["profile"] = {
        "id": profile.get("id"),
        "text": profile.get("text") or "",
        "sentences": memory_style.sentences(trait_values),
        "traits": trait_values,
        "edited": profile.get("style_edited"),
        "humour": {
            "means": memory_style.humour_means(
                (profile.get("humour") or {}).get("observations")),
            "observations": (profile.get("humour") or {}).get("observations") or {},
        },
    }
    return block


def _load_for_update(memory_manager) -> List[Dict[str, Any]]:
    """Load the whole store for a read-modify-write cycle.

    A transient read failure must not look like an empty store: the caller
    would append to ``[]`` and save that back, atomically destroying every
    existing memory (issue #5673). Surface it as a 503 and change nothing.
    """
    try:
        return memory_manager.load_all_for_update()
    except MemoryStoreUnreadable as e:
        logger.error("Refusing to rewrite the memory store: %s", e)
        raise HTTPException(
            503, "Memory store is temporarily unreadable — no changes were made."
        )


def _import_result(suggestions, filename, export, memory_manager, owner):
    """The import's answer, and on the provider path the memories themselves.

    `P13-06`. A generic upload keeps the shape it has always had — suggestions
    to review, persisted nowhere — because changing that would change a flow
    this row is not about (`Law 1`).

    A **provider export** is written to the store as proposals before the
    answer is returned, because the row's word is *every*: an origin and a
    confidence that ride back through the browser to `POST /add` are an origin
    and a confidence a client can drop, and `P13-05` already recorded that a
    suggestion nobody clicked in that browser session is gone. The review step
    is unchanged from the person's side — the same list, the same save button —
    and saving one now **commits the proposal** rather than writing a second
    copy, which is the one branch `POST /add` had that could never be reached.
    """
    if export is None:
        return {"suggestions": suggestions, "filename": filename}
    written = store_imported(memory_manager, suggestions, export["provider"],
                             owner=owner, filename=filename)
    return {
        # The ids are on the wire so a reviewer can commit the record rather
        # than re-send its text. Nothing else about the shape changes, so the
        # panel that reads `text` and `category` keeps working untouched.
        "suggestions": [{"id": e["id"], "text": e["text"],
                         "category": e.get("category", "fact"),
                         "confidence": e.get("confidence"),
                         "status": e.get("status")}
                        for e in written["stored"]],
        "filename": filename,
        # Counts of what happened, never of what was in the file. An importer
        # that reports the size of the upload tells somebody 4,000 messages
        # were imported when 60 were read.
        "provider": export["provider"],
        "conversations": export["conversations"],
        "messages": export["messages"],
        "dropped_assistant": export["dropped_assistant"],
        "truncated": export["truncated"],
        "already_known": written["duplicates"],
        "below_floor": written["below_floor"],
    }


def setup_memory_routes(memory_manager: MemoryManager, session_manager: SessionManager, memory_vector=None):
    """Set up memory-related routes."""
    # `H05`. `memory` was one of the three flags with NO consumer anywhere —
    # not in the UI, not on the server, not in the agent. It has all three now.
    from fastapi import Depends
    from src.feature_gate import require_feature
    router = APIRouter(prefix="/api/memory", tags=["memory"],
                       dependencies=[Depends(require_feature("memory", label="Memory"))])

    def _owner(request: Request) -> Optional[str]:
        return get_current_user(request)

    def _assert_session_owner(session_obj, user):
        """SECURITY: 404 if the caller does not own this session.

        SessionManager.get_session is NOT owner-scoped — it returns any
        session by id. These routes accept a caller-supplied session id, so
        without this gate a user could target another tenant's session and
        leak their chat history, their session-scoped LLM credentials, or the
        session title. Mirrors session_routes / webhook_routes ownership.
        """
        if user is not None and getattr(session_obj, "owner", None) != user:
            raise HTTPException(404, "Session not found")

    def _verify_memory_owner(memory: dict, user: Optional[str]):
        """Raise 404 if user doesn't own this memory.

        SECURITY: strict ownership — previously `mem_owner and mem_owner != user`
        allowed any user to read/edit/delete memories with an empty/null owner
        field, which leaked legacy data across the multi-user deploy.
        """
        if user is None:
            return  # Auth disabled
        if memory.get("owner") != user:
            raise HTTPException(404, "Memory not found")

    @router.post("/debug")
    def debug_memory_relevance(request: Request, query: str = Form(...)):
        """Debug which memories would be triggered for a query"""
        user = _owner(request)
        memories = memory_manager.load(owner=user)
        # `H11`. `explanations` and `query_type` are ADDITIVE — `memories` and
        # `total` keep the exact shape and order they had, so anything already
        # reading this endpoint is unaffected. The route's docstring has always
        # promised to say which memories would be triggered; it can now say why,
        # which is the half the scorer used to compute and throw away.
        explained = memory_manager.explain_relevant_memories(query, memories, threshold=0.05)
        relevant = [row["memory"] for row in explained]

        return {
            "query": query,
            "total_memories": len(memories),
            "relevant_count": len(relevant),
            "relevant_memories": [{"text": m["text"], "category": m.get("category", "unknown")}
                                 for m in relevant],
            # `H11`, all three keys additive. `relevant_memories` above keeps
            # its exact shape — text and category, no id — which is why
            # `memories` is a separate key rather than an edit to it: the
            # diagnostic has to line each explanation up with a row, and it
            # cannot do that without ids.
            "memories": relevant,
            # How the retriever read the question. Reported once rather than
            # per row, because it is a property of the query and it is the
            # single most surprising thing a person learns here.
            #
            # `P13-14`. This was `classify_query`, and after the scorer moved it
            # would have been a classifier reporting on a ranking it no longer
            # drives — a diagnostic that agrees with the truth by coincidence is
            # worse than none, because it is believed. `query_intent` is the
            # function the boost actually consults. `classify_query` still
            # exists and still answers; it is simply no longer wired to
            # ranking, and its own docstring now says so.
            "query_type": memory_retrieval.query_intent(query),
            "explanations": [
                {"id": row["memory"].get("id"), "score": row["score"],
                 "reason": row["reason"],
                 # `P13-01`. Beside the score and never folded into it. The
                 # score says how well this matched the question; the
                 # confidence says how sure whatever wrote it was that it is
                 # true, and `None` says nobody recorded one. A diagnostic that
                 # showed one number for both would be the `CONFIDENCE 66% ·
                 # 1 mentions` reading the phase preamble is about.
                 "confidence": row["memory"].get("confidence"),
                 # `P13-03`. Which producer and which message, so "why do you
                 # think that" has an answer that is not "an LLM said so".
                 "provenance": row["memory"].get("provenance")}
                for row in explained
            ],
        }

    @router.post("/add", response_model=Dict[str, Any])
    async def api_add_memory(
        request: Request,
        memory_data: Optional[MemoryAddRequest] = None
    ):
        """Add a new memory entry with optional category, source, and session reference."""
        from src.auth_helpers import require_privilege
        require_privilege(request, "can_manage_memory")
        if memory_data is None:
            form = await request.form()
            memory_data = MemoryAddRequest(
                text=form.get("text"),
                category=form.get("category", "fact"),
                source=form.get("source", "user"),
                session_id=form.get("session_id")
            )

        user = _owner(request)
        text = (memory_data.text or "").strip()
        if not text:
            raise HTTPException(400, "empty memory")
        user_mem = memory_manager.load(owner=user)
        existing = memory_manager.find_duplicates(text, user_mem)
        if existing:
            # `P13-06`. A save on a text the Brain already holds **as a
            # proposal** is the explicit act, not a no-op. This branch was
            # unreachable before anything wrote proposals through a surface a
            # person reviews, and it is the whole seam between an import and
            # the memories it produces: the review list sends the same text the
            # proposal carries, so without this a person clicking *save* on an
            # imported fact would get "Memory already exists" and the proposal
            # would sit unbound forever — the least visible failure this
            # product can have (`P0-05`).
            #
            # `commit_memory` and not a status write here: that gate already
            # refuses an empty text, an unknown id, something already committed
            # and a restatement of something live, and records the verdict in
            # `P14-01`'s table. A second promotion path would be a second set
            # of those checks (`Law 14`).
            proposal = next((m for m in existing
                             if not memory_edges.is_committed(m)), None)
            if proposal is not None:
                verdict = commit_memory(memory_manager, proposal["id"], by=user,
                                        owner=user, memory_vector=memory_vector)
                return {"ok": verdict["verdict"] == COMMIT_COMMITTED,
                        "count": len(user_mem),
                        "memory_id": proposal["id"],
                        "verdict": verdict["verdict"],
                        "message": verdict["reason"]}
            return {"ok": True, "count": len(user_mem), "message": "Memory already exists"}

        if memory_data.session_id:
            try:
                session_obj = session_manager.get_session(memory_data.session_id)
            except KeyError:
                raise HTTPException(404, "Session not found")
            _assert_session_owner(session_obj, user)

        new_entry = memory_manager.add_entry(
            text, memory_data.source, memory_data.category, owner=user,
            # `P13-01`. Left unrecorded on purpose, and this is the case that
            # makes the field honest: a person typing a memory into the Brain
            # is not a 1.0, they are a producer nobody asked. Writing a number
            # here would make hand-entered memories outrank extracted ones on a
            # confidence sort for no reason anybody could defend.
            confidence=None,
            # `P13-03`. The producer, which `source` cannot give: `source` is
            # whatever the caller passed ("user" by default, but this endpoint
            # accepts any string), and it is the same word whether the request
            # came from the Brain, a script or a token.
            provenance=new_provenance("memory_routes.add"),
        )
        if memory_data.session_id:
            new_entry["session_id"] = memory_data.session_id
        all_mem = _load_for_update(memory_manager)
        all_mem.append(new_entry)
        memory_manager.save(all_mem)
        # Sync vector index
        if memory_vector and memory_vector.healthy:
            memory_vector.add(new_entry["id"], text)
        try:
            from src.event_bus import fire_event
            fire_event("memory_added", user,
                       {"memory_id": new_entry.get("id"), "text": text})
        except Exception:
            logger.debug("memory_added event dispatch failed", exc_info=True)
        return {"ok": True, "count": len([m for m in all_mem if m.get("owner") == user])}

    @router.get("")
    def api_get_memory(request: Request):
        """Return all memory entries with their metadata.

        `P13-04` adds `archive` to each row: `{"verdict": "fades"|"held",
        "reason": str, "days": int|None}`. **Computed here and never stored**
        — it is derived from four dates that are already on the record, and a
        copy of a derived value is a copy that is wrong by tomorrow (`Law 7`,
        `Law 8`). The whole point of surfacing it is that fading is visible
        before it happens rather than reported after: *"fades in 12 days"* is a
        sentence a person can act on, and an archive that arrives unannounced
        is the silent drop this row exists to prevent.
        """
        user = _owner(request)
        rows = memory_manager.load(owner=user)
        stale = memory_edges.superseded_ids(rows)
        for row in rows:
            row["archive"] = archive_forecast(
                row, superseded=row.get("id") in stale)
        return {"memory": rows, "style": _style_block(memory_manager, user)}

    @router.post("/search")
    def search_memories(request: Request, query: str = Form(...), session_id: str = Form(None), category: str = Form(None)):
        """Search across all memories with optional filters."""
        user = _owner(request)
        memories = memory_manager.load(owner=user)

        if session_id:
            memories = [m for m in memories if m.get("session_id") == session_id]

        if category:
            memories = [m for m in memories if category in m.get("categories", [m.get("category", "")])]

        relevant = memory_manager.get_relevant_memories(query, memories, threshold=0.05, max_items=20)

        return {"memories": relevant, "total": len(relevant), "query": query}

    @router.get("/timeline")
    def memory_timeline(request: Request):
        """Get memories in chronological order with source session information.

        **`P13-17` records are excluded, and leaving them in would have broken
        this surface rather than decorated it.** The style profile's
        `timestamp` moves on *every* user message, so a timeline that included
        it would show the same single row at the top of every view, for ever,
        pushing the thing the timeline is for off the screen. It is not a
        memory, it does not belong in a chronology of what was learned, and
        `GET /api/memory/style` is where it is read.
        """
        user = _owner(request)
        memories = [m for m in memory_manager.load(owner=user)
                    if memory_style.kind_of(m) == memory_style.KIND_MEMORY]
        sorted_memories = sorted(memories, key=lambda x: x.get("timestamp", 0), reverse=True)

        results = []
        for memory in sorted_memories:
            if "timestamp" in memory:
                try:
                    dt = datetime.fromtimestamp(memory["timestamp"])
                    memory["timestamp_str"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, OSError, OverflowError):
                    memory["timestamp_str"] = "Unknown"
            else:
                memory["timestamp_str"] = "Unknown"

            session_id = memory.get("session_id")
            if session_id and session_id in session_manager.sessions:
                try:
                    session = session_manager.get_session(session_id)
                    if session:
                        _assert_session_owner(session, user)
                    memory["session_name"] = session.name if session else f"Session {session_id[:6]}"
                except KeyError:
                    memory["session_name"] = "Unknown"
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
                    memory["session_name"] = "Unknown"
            else:
                memory["session_name"] = "Unknown"

            results.append(memory)

        return {"timeline": results, "total": len(results)}

    @router.get("/by-session/{session_id}")
    def get_memory_by_session(request: Request, session_id: str):
        """Get all memories associated with a specific session."""
        user = _owner(request)
        try:
            _session_obj = session_manager.get_session(session_id)
        except KeyError:
            raise HTTPException(404, f"Session {session_id} not found")
        _assert_session_owner(_session_obj, user)
        memories = memory_manager.load(owner=user)
        session_memories = [m for m in memories if m.get("session_id") == session_id]

        session_memories.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        try:
            session = session_manager.get_session(session_id)
            session_name = session.name if session else f"Session {session_id[:6]}"
        except KeyError:
            session_name = f"Session {session_id[:6]}"

        for memory in session_memories:
            memory["session_name"] = session_name

        return {
            "session_id": session_id,
            "session_name": session_name,
            "memory_count": len(session_memories),
            "memories": session_memories
        }

    @router.post("/extract")
    async def extract_memory(request: Request, session: str = Form(...)) -> Dict[str, List[str]]:
        """Analyze a session's chat history and return memory suggestions."""
        require_user(request)
        try:
            sess = session_manager.get_session(session)
        except KeyError:
            raise HTTPException(404, "Session not found")
        _assert_session_owner(sess, _owner(request))

        system_msg = {
            "role": "system",
            "content": (
                "You are a helpful assistant. Analyze the entire conversation history provided and extract any "
                "useful factual statements, contacts, addresses, phone numbers, or other information that the user "
                "might want to remember for future interactions. Return each piece of information as a JSON object "
                "with a 'text' field. For example: [{'text': 'Alice lives at 123 Main St'}, {'text': 'Bob works at Acme Corp'}]. "
                "Only include information that is specific and likely to be useful later."
            ),
        }
        messages = [system_msg] + sess.get_context_messages()

        t_url, t_model, t_headers = resolve_task_endpoint(
            sess.endpoint_url, sess.model, sess.headers, owner=_owner(request)
        )

        try:
            suggestion_text = await llm_call_async(
                t_url,
                t_model,
                messages,
                temperature=0.2,
                max_tokens=500,
                headers=t_headers,
            )
            try:
                suggestions = json.loads(suggestion_text)
                if isinstance(suggestions, list):
                    suggestions = [s if isinstance(s, str) else s.get("text", "") for s in suggestions]
                else:
                    suggestions = []
            except json.JSONDecodeError:
                suggestions = [line.strip() for line in suggestion_text.splitlines() if line.strip()]

            return {"suggestions": [s for s in suggestions if s]}
        except Exception as e:
            logger.error(f"LLM memory extraction failed (session {session}): {e}")
            fallback = memory_manager.extract_memory_from_chat(sess.history, session)
            return {"suggestions": [item["text"] for item in fallback]}

    @router.post("/audit")
    async def api_audit_memories(request: Request, session: str = Form(None)):
        """Deduplicate and consolidate memories via LLM.

        Uses task/utility/default settings through the shared resolver, with
        the active session as fallback when no task or utility model is set.
        Returns before and after memory counts.
        """
        user = _owner(request)
        fallback_url = fallback_model = None
        fallback_headers = None
        if session:
            try:
                sess = session_manager.get_session(session)
                _assert_session_owner(sess, user)
                fallback_url = sess.endpoint_url
                fallback_model = sess.model
                fallback_headers = sess.headers
            except KeyError:
                pass

        endpoint_url, model, headers = resolve_task_endpoint(
            fallback_url, fallback_model, fallback_headers, owner=user
        )

        if not endpoint_url or not model:
            raise HTTPException(400, "No default model configured — set one in Settings")

        result = await audit_memories(
            memory_manager,
            memory_vector,
            endpoint_url,
            model,
            headers,
            owner=user,
        )

        if "error" in result and "before" not in result:
            raise HTTPException(502, f"Audit failed: {result['error']}")

        return {
            "ok": "error" not in result,
            "before": result.get("before", 0),
            "after": result.get("after", 0),
            "removed": result.get("before", 0) - result.get("after", 0),
            # `P13-09`, both additive — `removed` keeps its exact meaning
            # ("stopped surfacing") and its exact arithmetic. `superseded` is
            # how many of those are still on the record with a `supersedes`
            # edge naming the entry that replaced them, so a person reading
            # "9 removed" can be told that 8 of them are recoverable and only
            # one was genuinely junk. `contradictions` is the conflicts the
            # pass recorded instead of resolving.
            "superseded": result.get("superseded", 0),
            "contradictions": result.get("contradictions", 0),
            # `P13-04`. Its own number, outside `removed`'s arithmetic. The
            # fade runs before `before` is counted, so these are not part of
            # `before - after` — and they should not be: "stopped surfacing
            # because nothing has reached for it in six months" is a different
            # event from "merged into another entry", and both are recoverable
            # in a click while `removed` historically was not.
            "archived": result.get("archived", 0),
            # True when the audit skipped the LLM because nothing changed
            # since the last tidy. Frontend already says "Already clean"
            # for removed==0, so this is here for future use / debugging.
            "already_tidy": bool(result.get("already_tidy")),
        }

    @router.post("/import")
    async def import_memories_from_file(
        request: Request,
        session: str | None = Form(None),
        file: UploadFile = File(...)
    ):
        """Extract memory suggestions from an uploaded file (PDF, TXT, MD, etc.)."""
        from src.auth_helpers import require_privilege
        require_privilege(request, "can_manage_memory")

        endpoint_url = None
        model = None
        headers = {}

        user = _owner(request)

        if session:
            try:
                sess = session_manager.get_session(session)
                _assert_session_owner(sess, user)
            except KeyError:
                sess = None
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                sess = None

            if sess is None:
                logger.warning("Session %s not found or inaccessible, falling back to utility endpoint", session)
                endpoint_url, model, headers = resolve_endpoint("utility", owner=user)
            else:
                endpoint_url, model, headers = resolve_task_endpoint(
                    sess.endpoint_url, sess.model, sess.headers, owner=user
                )
        else:
            endpoint_url, model, headers = resolve_task_endpoint(owner=user)
    
        if not endpoint_url or not model:
            raise HTTPException(400, "No LLM model configured. Set a default model in Settings.")

        content = await read_upload_limited(
            file, resolve_byte_limit("memory_import_max_bytes"), "Memory import")
        filename = file.filename or "upload"
        _, ext = os.path.splitext(filename.lower())

        allowed = {".txt", ".md", ".pdf", ".csv", ".log", ".json", ".py", ".js", ".html"}
        if ext not in allowed:
            raise HTTPException(400, f"Unsupported file type: {ext}")

        # Extract text based on file type
        if ext == ".pdf":
            from src.document_processor import _process_pdf
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                text = _process_pdf(tmp_path, owner=_owner(request))
            finally:
                os.unlink(tmp_path)
        else:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                from charset_normalizer import detect
                encoding = (detect(content) or {}).get("encoding") or "utf-8"
                text = content.decode(encoding, errors="replace")

        if not text.strip():
            return {"suggestions": [], "message": "No readable content found"}

        # `P13-06`. A conversation export from ChatGPT, Claude or Gemini,
        # recognised by its own structure rather than by its filename — all
        # three are called some variant of `conversations.json` and the person
        # may have renamed it.
        #
        # **Measured before it was written:** every one of those files already
        # reached this endpoint and was handled by the generic path below, so
        # the first 15,000 characters of raw export JSON — braces, node ids,
        # `create_time` floats — went to the model as "a document", and the
        # memories-export fast path underneath found no `text` key and passed
        # it through. The pipe was right and nothing read the file.
        #
        # This sits ABOVE that fast path, and the two are one `if`/`elif` over
        # **one** parse rather than two conditions over two. A file can satisfy
        # both shapes — a conversation export beside a row that happens to
        # carry a `text` key — and the fast path returns early, so a person
        # would get one stray suggestion and none of their conversations. An
        # exclusion written as a second condition over a re-parse of a string
        # this branch has already replaced is one a mutation deletes for free:
        # it reads like a control and cannot change an answer.
        export = None
        if ext == ".json":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list) and parsed:
                export = provider_import.read_export(parsed)
            if export is not None:
                if not export["text"].strip():
                    # A recognised export we could read nothing out of. Said
                    # plainly rather than handed to the model as an empty
                    # document: "no facts found" and "nothing of yours was in
                    # the file" are different answers.
                    return {"suggestions": [], "provider": export["provider"],
                            "conversations": export["conversations"],
                            "messages": 0, "filename": filename,
                            "message": f"No messages of yours found in this "
                                       f"{export['provider']} export"}
                text = export["text"]
            # Fast path: a .json upload that already looks like a memories
            # export (list of {text, category, ...} dicts, or list of strings)
            # round-trips directly without spending an LLM call to re-extract
            # its own output. Without this, re-importing a memories.json from
            # another account ran the file through the extractor, which often
            # re-emitted the entries as a numbered list (and the numbering
            # leaked into the `text` field).
            #
            # `else` on the sniff, over the SAME parse (`P13-06`): a recognised
            # export is read as an export and this never gets first refusal on
            # one.
            elif isinstance(parsed, list) and parsed:
                direct = []
                for item in parsed:
                    if isinstance(item, dict) and item.get("text"):
                        direct.append({
                            "text": _strip_list_prefix(str(item["text"])),
                            "category": item.get("category") or "fact",
                        })
                    elif isinstance(item, str) and item.strip():
                        direct.append({
                            "text": _strip_list_prefix(item.strip()),
                            "category": "fact",
                        })
                if direct:
                    return {"suggestions": direct, "filename": filename}

        # Truncate very long documents
        if len(text) > 15000:
            text = text[:15000] + "\n[Truncated]"

        # Send to LLM for memory extraction
        import_prompt = (
            "You are a memory extraction assistant. The user uploaded a document. "
            "Analyze the text below and extract specific, useful facts — things like "
            "names, preferences, jobs, locations, relationships, opinions, projects, "
            "goals, contacts, or any other personal details worth remembering.\n\n"
            "Rules:\n"
            "- Each fact should be a short, self-contained statement\n"
            "- Do NOT extract generic knowledge\n"
            "- Focus on personal, memorable information\n"
            "- If there are no useful facts, return an empty array\n\n"
            "Return a JSON array of objects with 'text' and 'category' fields.\n"
            "Categories: 'identity', 'preference', 'fact', 'contact', 'project', 'goal'\n\n"
            "Return ONLY valid JSON, no markdown fences."
        )

        try:
            raw = await llm_call_async(
                endpoint_url,
                model,
                [
                    {"role": "system", "content": import_prompt},
                    {"role": "user", "content": f"Document: {filename}\n\n{text}"},
                ],
                temperature=0.2,
                max_tokens=2000,
                headers=headers,
            )

            # Parse JSON
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            suggestions = json.loads(raw)
            if isinstance(suggestions, list):
                normalized = []
                for s in suggestions:
                    if not s:
                        continue
                    if isinstance(s, dict):
                        s = dict(s)
                        if s.get("text"):
                            s["text"] = _strip_list_prefix(str(s["text"]))
                        normalized.append(s)
                    else:
                        normalized.append({"text": _strip_list_prefix(str(s)), "category": "fact"})
                suggestions = normalized
            else:
                suggestions = []

            return _import_result(suggestions, filename, export,
                                  memory_manager, user)

        except json.JSONDecodeError:
            # Fallback: split by lines, stripping any "1.", "2)" markdown-list
            # numbering the model added so saved memories don't keep the prefix.
            lines = [_strip_list_prefix(l.strip()) for l in raw.splitlines() if l.strip() and len(l.strip()) > 5]
            return _import_result([{"text": l, "category": "fact"} for l in lines[:20]],
                                  filename, export, memory_manager, user)
        except Exception as e:
            logger.error(f"Memory import extraction failed: {e}")
            raise HTTPException(502, f"LLM extraction failed: {str(e)}")

    @router.post("/{memory_id}/pin")
    def pin_memory(request: Request, memory_id: str, pinned: bool = Form(True)):
        """Pin or unpin a memory. Pinned memories are always included in context."""
        user = _owner(request)
        all_mem = _load_for_update(memory_manager)
        for i, memory in enumerate(all_mem):
            if memory["id"] == memory_id:
                _verify_memory_owner(memory, user)
                all_mem[i]["pinned"] = pinned
                memory_manager.save(all_mem)
                return {"ok": True, "pinned": pinned}
        raise HTTPException(404, f"Memory item {memory_id} not found")

    @router.post("/{memory_id}/commit")
    def commit_memory_item(request: Request, memory_id: str):
        """Bind a proposed memory. `P13-05` — the explicit act.

        Beside `/pin` rather than folded into `PUT /{memory_id}`, because it is
        a different kind of change: an edit alters what a memory says, and this
        alters whether it is allowed to say anything at all. Modelled on the
        route that already exists for the same shape of decision.

        `can_manage_memory`, the same privilege `/add` requires, because the
        effect is the same: after this call a sentence starts reaching models.

        The verdict is an enum in the body and the status code is always 200 for
        a decision the gate actually made — a refusal is an answer, not an
        error, and a 4xx would make the panel show a failure banner for
        *"the Brain already knows this"*, which is the most useful thing it can
        say. A genuinely unknown id is the one case that is a 404.
        """
        from src.auth_helpers import require_privilege
        require_privilege(request, "can_manage_memory")

        user = _owner(request)
        # Unscoped read plus `_verify_memory_owner`, which is the shape every
        # other mutating route in this file uses (`/pin`, `PUT`, `DELETE`) and
        # not the belt-and-braces union of that and a scoped load. Mutation
        # testing is what settled it: with `load(owner=user)` in front, the
        # ownership check can never fire — a scoped load returns nothing for
        # another tenant and returns everything when auth is off, which is the
        # branch `_verify_memory_owner` returns early on — so deleting the
        # check changed no test, and a control nothing can distinguish from its
        # own absence is not a control (`P13-09`, `P13-14`, `B62`). One
        # reachable gate, exercised by a test that fails when it goes.
        #
        # `_load_for_update` and not `load`: a store that cannot be read is a
        # 503, not a 404. "There is no such memory" and "I could not look" are
        # different answers and only one of them tells the person to try again.
        entry = next((m for m in _load_for_update(memory_manager)
                      if m.get("id") == memory_id), None)
        if entry is None:
            raise HTTPException(404, f"Memory item {memory_id} not found")
        _verify_memory_owner(entry, user)

        result = commit_memory(memory_manager, memory_id, by=user, owner=user,
                               memory_vector=memory_vector)
        if result["verdict"] == COMMIT_COMMITTED:
            try:
                from src.event_bus import fire_event
                fire_event("memory_added", user,
                           {"memory_id": memory_id, "text": entry.get("text")})
            except Exception:
                logger.debug("memory_added event dispatch failed", exc_info=True)
        return result

    # Wildcard routes MUST come last — otherwise they swallow /import, /search, etc.
    @router.get("/{memory_id}")
    def get_memory_item(request: Request, memory_id: str):
        """Get a specific memory item by ID."""
        user = _owner(request)
        memories = memory_manager.load(owner=user)
        for memory in memories:
            if memory["id"] == memory_id:
                return {"memory": memory}

        raise HTTPException(404, "Memory not found")

    @router.put("/{memory_id}")
    def update_memory(request: Request, memory_id: str, text: str = Form(...), category: str = Form(None)):
        """Update an existing memory item with new text and optional category."""
        user = _owner(request)
        all_mem = _load_for_update(memory_manager)
        for i, memory in enumerate(all_mem):
            if memory["id"] == memory_id:
                _verify_memory_owner(memory, user)
                all_mem[i]["text"] = text.strip()
                if category:
                    all_mem[i]["category"] = category
                all_mem[i]["timestamp"] = int(time.time())
                # `P13-17`. **Editing the style profile is the only error signal
                # this feature can have**, and it is recorded in the route that
                # already edits records rather than in a second one (`Law 14`):
                # *"there is no golden set for did-we-describe-you-correctly and
                # there cannot be; did you change what we wrote is real and it
                # is the one to keep."* The flag also stops the observer
                # overwriting the correction on the next bucket change, which
                # is how a system teaches people that correcting it is pointless.
                if memory_style.kind_of(all_mem[i]) == memory_style.KIND_STYLE:
                    all_mem[i]["style_edited"] = int(time.time())
                    _record_style_edit(memory_id, "edited", user)

                memory_manager.save(all_mem)
                # Sync vector index (remove old, add updated)
                if memory_vector and memory_vector.healthy:
                    memory_vector.remove(memory_id)
                    memory_vector.add(memory_id, text.strip())
                return {"ok": True, "message": "Memory updated successfully"}

        raise HTTPException(404, f"Memory item {memory_id} not found")

    @router.delete("/{memory_id}")
    def delete_memory(request: Request, memory_id: str):
        """Delete a memory item by its ID."""
        user = _owner(request)
        all_mem = _load_for_update(memory_manager)

        # Find and verify ownership before deleting
        target = next((m for m in all_mem if m["id"] == memory_id), None)
        if not target:
            raise HTTPException(404, f"Memory item {memory_id} not found")
        _verify_memory_owner(target, user)

        if memory_style.kind_of(target) == memory_style.KIND_STYLE:
            # `P13-17`'s `Verify:` asks for *"deletable in one action"*, and
            # this route already is that action — no second endpoint, and no
            # tombstone either. Deleting the profile deletes the counters with
            # it, so the next observation starts a new one from nothing rather
            # than re-deriving the same sentences from history the person just
            # asked us to forget. That is what makes the delete meaningful.
            _record_style_edit(memory_id, "deleted", user)
        all_mem = [m for m in all_mem if m["id"] != memory_id]
        memory_manager.save(all_mem)
        # Sync vector index
        if memory_vector and memory_vector.healthy:
            memory_vector.remove(memory_id)
        return {"ok": True, "message": "Memory deleted successfully"}

    return router
