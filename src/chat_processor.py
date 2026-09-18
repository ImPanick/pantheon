# SPDX-License-Identifier: AGPL-3.0-or-later
# src/chat_processor.py
import logging

from src.feature_gate import feature_enabled   # H05
import math
import re
import time
from collections import Counter
from typing import List, Dict, Any, Optional, Tuple
from src import memory_retrieval, retrieval_engine
from src.chat_helpers import extract_urls
from src.youtube_handler import is_youtube_url
from src.search import comprehensive_web_search, fetch_webpage_content
from src.prompt_security import UNTRUSTED_CONTEXT_POLICY, untrusted_context_message

logger = logging.getLogger(__name__)


def _clean_search_query(query: str, max_len: int = 200) -> str:
    """Strip fenced code blocks from a search query while preserving inline
    code text.

    This is a focused, defensive cleanup for the *final* web-search query
    selected in ``build_context_preface`` (issue #4547): regardless of whether
    the query came from the LLM-generated path (#4557) or the first-line
    fallback, residual fenced / inline markdown should not leak into the search
    call. Rather than using regex (which is brittle and strips inline code
    text like ``git reset`` from the query), we render the query to HTML via
    ``markdown`` and parse it with ``BeautifulSoup`` so that:

    * ``<pre>`` blocks (fenced / indented code) are removed entirely.
    * ``<code>`` elements (inline code) are preserved as plain text.

    Both libraries are already project dependencies. The result is whitespace
    collapsed and truncated to ``max_len``; an all-code input collapses to an
    empty string, which the caller treats as "no query".
    """
    import markdown as _md
    from bs4 import BeautifulSoup as _BS

    html = _md.markdown(query, extensions=["fenced_code"])
    soup = _BS(html, "html.parser")

    # Remove fenced / indented code blocks.
    for pre in soup.find_all("pre"):
        pre.decompose()

    # Preserve inline code by unwrapping <code> to text.
    for code in soup.find_all("code"):
        code.replace_with(code.get_text())

    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text[:max_len]


# ── Stopwords & tokenizer ──

_STOPWORDS = memory_retrieval.STOPWORDS

# `P13-14`. Re-exported, not reimplemented. The tokenizer and its stopword list
# moved to `src/memory_retrieval.py` with the scorer that is their only reason
# to exist; these two names stay because tests and callers import them from here
# and a second copy is the defect `Law 14` names.
_content_tokens = memory_retrieval.content_tokens


class ChatProcessor:
    def __init__(self, memory_manager, personal_docs_manager, memory_vector=None, skills_manager=None):
        self.memory_manager = memory_manager
        self.personal_docs_manager = personal_docs_manager
        self.memory_vector = memory_vector
        self.skills_manager = skills_manager

    # Minimum similarity score for RAG results to be injected
    RAG_SIMILARITY_THRESHOLD = 0.35
    MEMORY_CONTEXT_LIMIT = 5
    PINNED_MEMORY_LIMIT = MEMORY_CONTEXT_LIMIT

    def _is_core_memory(self, memory: Dict[str, Any]) -> bool:
        """Return whether a pinned memory is safe to keep globally available."""
        category = (memory.get("category") or "").lower()
        if category in {"identity", "contact"}:
            return True
        text = (memory.get("text") or "").lower()
        return any(marker in text for marker in (
            "my name is",
            "name is",
            "call me",
            "i am ",
            "i'm ",
            "email",
            "phone",
            "address",
        ))

    # `P13-10`. What a core pinned memory says when the trace asks why it is
    # there. Nothing ranked it, so there is no match to describe and inventing
    # one would be `B61`'s defect wearing a reason — the honest answer is the
    # rule that put it in the prompt.
    PINNED_REASON = "pinned, so it is always available — nothing ranked it"

    def _select_pinned_memories(self, message: str, pinned: list,
                                report: dict | None = None) -> list:
        """Keep pinned memories high-priority without injecting all of them.

        Pinned used to mean "always send every pinned memory to the model".
        That bloats every request and leaks unrelated personal context into
        tasks that do not need it. Now only a small set of core identity/contact
        memories is always available; other pinned memories must match the
        current request, but are retrieved before ordinary memories.
        """
        if not pinned:
            return []

        def _recent_first(memory: Dict[str, Any]) -> int:
            try:
                return int(memory.get("timestamp") or 0)
            except Exception:
                return 0

        core = sorted(
            [m for m in pinned if self._is_core_memory(m)],
            key=_recent_first,
            reverse=True,
        )[:self.PINNED_MEMORY_LIMIT]

        core_ids = {m.get("id") for m in core if m.get("id")}
        contextual_candidates = [
            m for m in pinned
            if not (m.get("id") and m.get("id") in core_ids)
        ]
        remaining_slots = max(self.PINNED_MEMORY_LIMIT - len(core), 0)
        # `P13-10`. The report is threaded through so a pinned memory that had
        # to MATCH can say how it matched. Only these rows get a scorer reason:
        # `core` below was never ranked, and giving it one would be `B61`'s lie
        # in the shape of an explanation.
        contextual = self._hybrid_retrieve(
            message,
            contextual_candidates,
            k=remaining_slots,
            report=report,
        ) if remaining_slots else []

        selected = []
        seen = set()
        for memory in [*core, *contextual]:
            key = memory.get("id") or memory.get("text")
            if key in seen:
                continue
            seen.add(key)
            selected.append(memory)
        return selected[:self.PINNED_MEMORY_LIMIT]

    def _hybrid_retrieve(self, message: str, mem_entries: list, k: int = 5,
                         report: dict | None = None) -> list:
        """Retrieve memories relevant to the message.

        `P13-14`. The scoring moved to `src/memory_retrieval.py`, which is now
        the only memory scorer in the tree — this method is the chat preface's
        binding to it, not a second implementation. It kept its name and
        signature because five call sites and their test doubles use both, and
        renaming a working seam to advertise a refactor is churn.
        """
        return memory_retrieval.retrieve(
            message, mem_entries, k, vector=self.memory_vector, report=report)

    def build_context_preface(
        self,
        message: str,
        session: Any,
        use_web: bool = False,
        use_rag: bool = True,
        use_memory: bool = True,
        time_filter: Optional[str] = None,
        preset_system_prompt: Optional[str] = None,
        owner: Optional[str] = None,
        character_name: Optional[str] = None,
        agent_mode: bool = False,
        incognito: bool = False,
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]], List[Dict[str, str]]]:
        """Build the context preface for LLM calls.

        Returns:
            Tuple of (preface messages, rag_sources list)

        Note on KV-cache friendliness: the ``system``-role messages assembled
        here are later concatenated into a single system message and sent as
        the very first thing in the payload (see ``llm_core``'s "consolidate
        system messages" step). Local OpenAI-compatible backends (llama.cpp /
        LM Studio) key their KV cache off the byte-identical token prefix, so
        *anything* that changes turn-to-turn — timestamps, retrieved snippets,
        per-turn counts — must NOT be folded into a system message here. Such
        content belongs in a separate ``user``/context message appended near
        the end of the array (see ``current_datetime_context_message`` and
        ``untrusted_context_message`` callers in ``build_chat_context``),
        which keeps the static system prefix byte-identical across turns of
        the same session and lets the backend reuse its cached prefix.
        """
        preface = []
        rag_sources = []

        # Add preset system prompt if specified
        if preset_system_prompt:
            preface.append({
                "role": "system",
                "content": preset_system_prompt
            })
        preface.append({
            "role": "system",
            "content": UNTRUSTED_CONTEXT_POLICY,
        })

        # Memory: core pinned facts + relevant pinned/extended recall.
        self._last_used_memories = []  # track what was injected
        if use_memory:
            mem_entries = self.memory_manager.load(owner=owner)

            pinned = [m for m in mem_entries if m.get("pinned")]
            extended = [m for m in mem_entries if not m.get("pinned")]

            _used_ids: list = []
            _pinned_report: dict = {}
            selected_pinned = self._select_pinned_memories(
                message, pinned, report=_pinned_report)
            _pinned_reasons = {row["id"]: row["reason"]
                               for row in (_pinned_report.get("selected") or ())
                               if row.get("id")}
            if selected_pinned:
                pinned_text = "\n- ".join([m["text"] for m in selected_pinned])
                preface.append(untrusted_context_message(
                    "saved memory: pinned context",
                    (
                        "Pinned memory context. Some pinned memories are only "
                        f"included when relevant:\n- {pinned_text}"
                    ),
                ))
                for m in selected_pinned:
                    # `B61`. Pinned is its own engine: nothing ranked these, so
                    # reporting them as a keyword or vector hit is the same lie
                    # pointed the other way.
                    self._last_used_memories.append({
                        "text": m["text"], "category": m.get("category", "fact"),
                        "type": "pinned", "engine": retrieval_engine.PINNED,
                        # `P13-01`/`P13-10`. The trace already says WHICH
                        # memories changed the answer and by which engine; the
                        # one field it never had is how sure anything was that
                        # they are true. `None` where nobody recorded one,
                        # never a default — a pill reading "80%" over a memory
                        # that was never assessed is the exact failure the
                        # phase preamble cites from PandAtlas.
                        "confidence": m.get("confidence"),
                        # `P13-10`. The id, so the panel can open the memory
                        # the pill names rather than matching on text; and the
                        # reason, which the scorer already wrote. A pinned
                        # memory that had to match reports how it matched; a
                        # core one reports the rule that included it.
                        "id": m.get("id"),
                        "reason": _pinned_reasons.get(m.get("id"),
                                                      self.PINNED_REASON)})
                    if m.get("id"):
                        _used_ids.append(m["id"])

            remaining_memory_slots = max(self.MEMORY_CONTEXT_LIMIT - len(self._last_used_memories), 0)
            if extended and remaining_memory_slots:
                recall_report: dict = {}
                relevant = self._hybrid_retrieve(
                    message, extended, k=remaining_memory_slots, report=recall_report)
                if relevant:
                    ext_text = "\n".join([f"- {m['text']}" for m in relevant])
                    preface.append(untrusted_context_message(
                        "saved memory: retrieved context",
                        (
                            "Memory context. Do not reference unless the user asks "
                            f"about these topics.\n{ext_text}"
                        ),
                    ))
                    # Indexed, not `.get`. `_hybrid_retrieve` writes `engine` before
                    # every early return, so a missing key means that guarantee broke
                    # — and a default here would paper over it with whichever answer
                    # the default happened to be, which is this row's whole subject.
                    _run_engine = recall_report["engine"]
                    _vector_ids = set(recall_report.get("vector_ids") or ())
                    # `P13-10`. Indexed for the same reason `engine` is: the
                    # scorer writes this key before every early return, so a
                    # missing one means that guarantee broke and a default here
                    # would hide it behind whatever the default happened to be.
                    _reasons = {row["id"]: row["reason"]
                                for row in recall_report["selected"]
                                if row.get("id")}
                    for m in relevant:
                        # Per memory, not per run. On a hybrid run some of these
                        # were found by the index and some only by BM25, and a
                        # single run-level label would claim the index found
                        # both. `HYBRID` collapses to what actually applied.
                        _engine = _run_engine
                        if _run_engine == retrieval_engine.HYBRID:
                            _engine = (retrieval_engine.VECTOR if m.get("id") in _vector_ids
                                       else retrieval_engine.KEYWORD)
                        self._last_used_memories.append({
                            "text": m["text"], "category": m.get("category", "fact"),
                            "type": "recalled", "engine": _engine,
                            "confidence": m.get("confidence"),
                            "id": m.get("id"),
                            "reason": _reasons.get(m.get("id"), "")})
                        if m.get("id"):
                            _used_ids.append(m["id"])

            # Bump usage counters for the memories that were actually injected.
            if _used_ids and hasattr(self.memory_manager, "increment_uses"):
                try:
                    self.memory_manager.increment_uses(_used_ids)
                except Exception as _e:
                    logger.warning("Failed to increment memory uses: %s", _e)

            # (skills index injection moved out — see below; only fires in
            # agent mode so chat mode and incognito stay clean.)

        # RAG: search if enabled and rag_manager available, inject only above threshold
        #
        # `H05` — the `rag` flag is honoured HERE and nowhere else, because
        # retrieval is not a tool the model calls: it is context assembled
        # before the turn. There is no name to put in a denylist and no router
        # that is only retrieval, so a flag mapped to either of those would have
        # been decoration. `rag` was one of the three flags the audit found with
        # no consumer in any layer at all; this is its consumer.
        if use_rag and not feature_enabled("rag"):
            logger.info("RAG retrieval skipped: the `rag` feature is switched off")
            use_rag = False
        if use_rag:
            try:
                rag_manager = getattr(self.personal_docs_manager, 'rag_manager', None)
                if rag_manager:
                    results = rag_manager.search(message, k=5, owner=owner)
                    # Filter by similarity threshold
                    relevant = [r for r in results if r.get("similarity", 0) >= self.RAG_SIMILARITY_THRESHOLD]
                    if relevant:
                        logger.info(f"RAG: {len(relevant)}/{len(results)} results above threshold {self.RAG_SIMILARITY_THRESHOLD}")
                        rag_sources = [
                            {
                                "filename": r["metadata"].get("filename", r["metadata"].get("source", "unknown")),
                                "snippet": r["document"][:200],
                                "similarity": round(r.get("similarity", 0), 3)
                            }
                            for r in relevant
                        ]
                        rag_content = "Relevant documents:\n\n" + "\n\n---\n\n".join(
                            f"[{s['filename']}]\n{r['document']}" for s, r in zip(rag_sources, relevant)
                        )
                        if len(rag_content) > 10000:
                            rag_content = rag_content[:10000] + "\n[Truncated]"
                        preface.append(untrusted_context_message(
                            "retrieved documents",
                            rag_content,
                        ))
            except Exception as e:
                logger.warning(f"RAG retrieval failed: {e}")

        # Add web search if enabled
        web_sources = []
        if use_web:
            try:
                from src.llm_core import llm_call

                t_url, t_model, t_headers = session.endpoint_url, session.model, session.headers

                # Default fallback is the first non-empty line of the original user message
                fallback_query = next((line.strip() for line in message.split("\n") if line.strip()), "")
                search_query = fallback_query

                try:
                    generated_query = llm_call(
                        t_url,
                        t_model,
                        [
                            {
                                "role": "system",
                                "content": (
                                    "Extract a concise search query from the user's message. "
                                    "Reply ONLY with the query."
                                ),
                            },
                            {"role": "user", "content": message},
                        ],
                        headers=t_headers,
                        temperature=0.1,
                        max_tokens=50,
                        timeout=15,
                    ).strip()

                    if generated_query:
                        # LLM successfully generated a non-empty query -> use the generated query
                        search_query = generated_query
                    else:
                        # LLM returned an empty or whitespace-only query -> fall back to original query
                        logger.warning("LLM generated an empty search query, using fallback.")
                except Exception as e:
                    # LLM failed (exception/error) -> fall back to original user query
                    logger.warning(f"Failed to generate search query via LLM, using fallback: {e}")

                search_query = " ".join(search_query.split())
                if len(search_query) > 150:
                    search_query = search_query[:150].strip()

                # Defensive cleanup of the final selected query (interim fix
                # for #4547): strip any residual fenced/inline markdown so that
                # neither the generated query nor the first-line fallback leaks
                # fences or backticks into the search call. No-op on clean
                # generated queries; collapses to "" when the query is all code.
                search_query = _clean_search_query(search_query, max_len=150)

                if search_query:
                    # Execute web search using the final selected query
                    web_context, web_sources = comprehensive_web_search(
                        search_query, time_filter=time_filter, return_sources=True
                    )
                    preface.append(untrusted_context_message("web search results", web_context))
            except Exception as e:
                logger.error(f"Web search failed: {e}")
                preface.append({"role": "system", "content": "Web search encountered an error and could not retrieve results."})

        # Process non-YouTube URLs in message (YouTube handled by preprocess_message)
        # Skip auto-fetch for long pastes (the user already pasted the content —
        # fetching every embedded link buries the actual question under
        # hundreds of KB of duplicate page HTML and confuses the model) or for
        # link-heavy pastes (>3 URLs typically means it's a boilerplate-laden
        # blog post, not a "summarize this URL" request).
        urls = extract_urls(message)
        non_yt_urls = [u for u in urls if not is_youtube_url(u)]
        skip_url_fetch = len(message) > 2000 or len(non_yt_urls) > 3
        if not skip_url_fetch:
            for url in non_yt_urls:
                try:
                    result = fetch_webpage_content(url)
                except Exception:
                    # The URL and exception can both contain signed-query
                    # credentials or response-controlled text. Keep the log
                    # diagnostic stable as well as the model-facing context.
                    logger.warning("Automatic URL fetch failed while building context")
                    result = {"success": False, "error": ""}
                if result.get('success'):
                    content = result.get('content', '')[:10000]
                    preface.append(untrusted_context_message(
                        f"web page: {url}",
                        f"Content from {url}:\n\n{content}",
                        provenance_origin="external",
                    ))
                else:
                    # A failed automatic URL fetch is context too. Never pass
                    # exception text or response-controlled diagnostics back to
                    # the model: reduce the result to a small transport-owned
                    # status and explicitly state that the page was not read.
                    error = str(result.get("error") or "")
                    status = "the page was unavailable"
                    status_match = re.match(r"^HTTP\s+(\d{3})\b", error)
                    if status_match:
                        status = f"the server returned HTTP {status_match.group(1)}"
                    elif error.startswith("TooLarge:"):
                        status = "the response exceeded the fetch size limit"
                    elif error.startswith("Rate limit"):
                        status = "the request was rate limited"
                    preface.append(untrusted_context_message(
                        "web page fetch failure",
                        f"A linked page was not read: {status}.",
                    ))

        # `B60`. The skills index used to be assembled here as well as in
        # `agent_loop._build_base_prompt`, and both landed in the same message
        # array: `agent_mode` is true only on the route whose `else` branch
        # calls `stream_agent_loop`, so the two always shipped together. A
        # duplicated catalogue was the small half. The large half was that the
        # two were gated differently and *between them every gate was defeated*
        # — this copy passed `active_toolsets=None`, so it advertised
        # procedures whose required tools were switched off, while the loop's
        # copy ignored the `skills_enabled` preference entirely. Turning skills
        # off did not turn the index off.
        #
        # One injection now, at the site that already gates on toolsets. The
        # gates this one uniquely honoured — the preference, `incognito`,
        # `allow_tool_preprocessing`, this module's own low-signal predicate —
        # reach it through the `suppress_skills` the route computes and hands
        # to `stream_agent_loop`. Nothing was lost; the suppressions started
        # working.

        return preface, rag_sources, web_sources
