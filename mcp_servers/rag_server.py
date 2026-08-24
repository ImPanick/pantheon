"""
rag_server.py

MCP server exposing RAG document management (list, add_directory, remove_directory).
"""

import asyncio
import os
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

server = Server("rag")

_rag_manager = None
_personal_docs_manager = None
_initialized = False

# Owner-scoping arg (injected by the tool dispatcher, mirroring the email MCP)
# plus env fallbacks, so add_text/search can scope like chat_processor's
# rag_manager.search(..., owner=owner). Ownerless callers get owner=None,
# which matches the existing directory-indexing behavior.
_MCP_OWNER_ARG = "_odysseus_owner"


def _owner_from_args(arguments: dict) -> str | None:
    """Resolve the owner for owner-scoped RAG calls (injected arg or env)."""
    val = arguments.get(_MCP_OWNER_ARG)
    if isinstance(val, str) and val.strip():
        return val.strip()
    for env_key in ("ODYSSEUS_MCP_RAG_OWNER", "ODYSSEUS_DOCUMENT_OWNER"):
        env_val = os.environ.get(env_key, "").strip()
        if env_val:
            return env_val
    return None


def _ensure_init():
    """Lazy-init RAG managers on first use."""
    global _rag_manager, _personal_docs_manager, _initialized
    if _initialized:
        return
    _initialized = True

    try:
        from src.rag_singleton import get_rag_manager
        _rag_manager = get_rag_manager()
    except Exception:
        pass

    try:
        from src.constants import PERSONAL_DIR
        from src.personal_docs import PersonalDocsManager
        _personal_docs_manager = PersonalDocsManager(PERSONAL_DIR, _rag_manager)
    except Exception:
        pass


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="manage_rag",
            description="Manage RAG indexed documents. List indexed files, add or remove directories, store arbitrary text (add_text), or search the vector store (search).",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add_directory", "remove_directory", "add_text", "search"],
                        "description": "The action to perform",
                    },
                    "directory": {"type": "string", "description": "Directory path (for add/remove)"},
                    "text": {"type": "string", "description": "Text to store in the RAG vector store (for add_text)"},
                    "title": {"type": "string", "description": "Optional title/source label for stored text (for add_text)"},
                    "source": {"type": "string", "description": "Optional source label for stored text (for add_text)"},
                    "query": {"type": "string", "description": "Search query (for search)"},
                    "k": {"type": "integer", "description": "Number of matches to return (for search, default 5)"},
                },
                "required": ["action"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "manage_rag":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    _ensure_init()
    action = arguments.get("action", "")

    if action == "list":
        if not _personal_docs_manager:
            return [TextContent(type="text", text="Personal docs manager not available. RAG may not be configured.")]
        try:
            files = getattr(_personal_docs_manager, 'index', None) or []
            dirs = []
            if hasattr(_personal_docs_manager, 'get_indexed_directories'):
                dirs = _personal_docs_manager.get_indexed_directories()

            lines = []
            if dirs:
                lines.append(f"**Indexed directories ({len(dirs)}):**")
                for d in dirs:
                    lines.append(f"  - `{d}`")
            if files:
                lines.append(f"\n**Indexed files ({len(files)}):**")
                for f in files[:50]:
                    fname = f.get("name", str(f)) if isinstance(f, dict) else str(f)
                    lines.append(f"  - {fname}")
                if len(files) > 50:
                    lines.append(f"  ... and {len(files) - 50} more")
            if not lines:
                return [TextContent(type="text", text="No files or directories indexed in RAG.")]
            return [TextContent(type="text", text="\n".join(lines))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif action == "add_directory":
        _dir = arguments.get("directory")
        directory = _dir.strip() if isinstance(_dir, str) else ""
        if not directory:
            return [TextContent(type="text", text="Error: add_directory needs a directory path")]
        # Store an absolute path so indexed `source` metadata is absolute and
        # remove_directory (which abspath-normalizes) can match it later (#1660).
        directory = os.path.abspath(os.path.expanduser(directory))
        if not os.path.isdir(directory):
            return [TextContent(type="text", text=f"Error: Directory not found: {directory}")]
        if not _rag_manager:
            return [TextContent(type="text", text="Error: RAG manager not available")]
        try:
            result = _rag_manager.index_personal_documents(directory)
            indexed = result.get("indexed_count", 0) if isinstance(result, dict) else 0
            # Record the directory so `list` and `remove_directory` can see it.
            # Indexing was just done above, so pass index=False to avoid a second
            # (ownerless) pass. Without this the directory was indexed but never
            # tracked in indexed_directories, so it was invisible/unremovable.
            if _personal_docs_manager and hasattr(_personal_docs_manager, "add_directory"):
                try:
                    _personal_docs_manager.add_directory(directory, index=False)
                except Exception:
                    pass
            return [TextContent(type="text", text=f"Directory '{directory}' added to RAG index ({indexed} chunks indexed)")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: Failed to index directory: {e}")]

    elif action == "remove_directory":
        _dir = arguments.get("directory")
        directory = _dir.strip() if isinstance(_dir, str) else ""
        if not directory:
            return [TextContent(type="text", text="Error: remove_directory needs a directory path")]
        # Expand ~ to match add_directory, which indexes the expanded path.
        # Without this, removing "~/docs" never matches the stored absolute path.
        directory = os.path.expanduser(directory)
        if not _personal_docs_manager:
            return [TextContent(type="text", text="Error: Personal docs manager not available")]
        try:
            if hasattr(_personal_docs_manager, 'remove_directory'):
                _personal_docs_manager.remove_directory(directory)
            if _rag_manager and hasattr(_rag_manager, 'remove_directory'):
                _rag_manager.remove_directory(directory)
            return [TextContent(type="text", text=f"Directory '{directory}' removed from RAG index")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: Failed to remove directory: {e}")]

    elif action == "add_text":
        _text = arguments.get("text")
        text = _text.strip() if isinstance(_text, str) else ""
        if not text:
            return [TextContent(type="text", text="Error: add_text needs text")]
        if not _rag_manager:
            return [TextContent(type="text", text="Error: RAG manager not available")]
        owner = _owner_from_args(arguments)
        _title = arguments.get("title")
        _source = arguments.get("source")
        title = _title.strip() if isinstance(_title, str) and _title.strip() else ""
        source = _source.strip() if isinstance(_source, str) and _source.strip() else ""
        metadata = {"source": source or title or "agent_text"}
        if title:
            metadata["title"] = title
            metadata["filename"] = title
        if owner:
            metadata["owner"] = owner
        try:
            ok = _rag_manager.add_document(text, metadata)
            if ok:
                return [TextContent(type="text", text=f"Stored text into RAG (1 chunk, source '{metadata['source']}')")]
            return [TextContent(type="text", text="Error: Failed to store text into RAG")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: Failed to store text: {e}")]

    elif action == "search":
        _query = arguments.get("query")
        query = _query.strip() if isinstance(_query, str) else ""
        if not query:
            return [TextContent(type="text", text="Error: search needs a query")]
        if not _rag_manager:
            return [TextContent(type="text", text="Error: RAG manager not available")]
        try:
            k = int(arguments.get("k", 5))
        except (TypeError, ValueError):
            k = 5
        if k <= 0:
            k = 5
        owner = _owner_from_args(arguments)
        try:
            results = _rag_manager.search(query, k=k, owner=owner)
        except Exception as e:
            return [TextContent(type="text", text=f"Error: Search failed: {e}")]
        if not results:
            return [TextContent(type="text", text=f"No matches found for '{query}'.")]
        lines = [f"**Top {len(results)} matches for '{query}':**"]
        for i, r in enumerate(results, 1):
            meta = r.get("metadata") if isinstance(r, dict) else None
            meta = meta if isinstance(meta, dict) else {}
            src = meta.get("filename") or meta.get("title") or meta.get("source") or "unknown"
            snippet = (r.get("document") or "").strip().replace("\n", " ")
            if len(snippet) > 300:
                snippet = snippet[:300] + "…"
            sim = r.get("similarity")
            sim_txt = f" (similarity {sim})" if sim is not None else ""
            lines.append(f"{i}. [{src}]{sim_txt}\n   {snippet}")
        return [TextContent(type="text", text="\n".join(lines))]

    else:
        return [TextContent(type="text", text=f"Error: Unknown action '{action}'. Use: list, add_directory, remove_directory, add_text, search")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
