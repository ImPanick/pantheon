# SPDX-License-Identifier: AGPL-3.0-or-later
# src/personal_docs.py
import os
import re
import json
import logging
from typing import List, Dict, Set, Any, Tuple
from dataclasses import dataclass

from src.index_walk import prune_index_dirs, is_indexable_file

from src.markitdown_runtime import MARKITDOWN_EXTS

logger = logging.getLogger(__name__)


def extract_pdf_text(file_path: str) -> str:
    """Extract text from a PDF file using pypdf (permissive, BSD)."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        text = "".join((page.extract_text() or "") for page in reader.pages)
        return text
    except ImportError:
        logger.warning("pypdf not installed, cannot extract PDF text")
        return ""
    except Exception as e:
        logger.error(f"Failed to extract PDF text from {file_path}: {e}")
        return ""


def extract_office_text(file_path: str) -> str:
    """Extract text from an Office/EPUB doc via the optional markitdown dep.

    Returns "" when markitdown is missing or extraction fails, mirroring
    extract_pdf_text — the indexer then simply skips the file's content.
    """
    from src.markitdown_runtime import convert_to_markdown
    return convert_to_markdown(file_path) or ""


# ── one register per extractor (`B75`) ──────────────────────────────────────
#
# Two indexes were built over the same directory by the same click from two
# hand-maintained lists. The vector indexer read `rag_vector.DEFAULT_FILE_
# EXTENSIONS` (11 entries), the keyword indexer read `config.DEFAULT_EXTENSIONS`
# (9); they agreed on four, so 12 of the 16 extensions named between them were
# indexed by exactly one of the two — a `.docx` was findable by keyword and
# invisible to semantic search, a `.py` was the reverse, and nothing on screen
# said which kind of search the user was getting.
#
# The asymmetry was not arbitrary in one direction: `index_personal_documents`
# opened everything but `.pdf` with a plain UTF-8 `open()`, so it *could not*
# read the Office formats. That is why the fix is a register keyed by EXTRACTOR
# rather than a merged list — each indexer now takes the union of what can
# actually be read, and reads it through the same function.
#
# `MARKITDOWN_EXTS` is the register that already existed for the Office
# extractor (`src/markitdown_runtime.py`); these two sit beside it rather than
# restating it (`Law 14`).
TEXT_EXTENSIONS: frozenset = frozenset({
    ".txt", ".md", ".json", ".yaml", ".yml", ".csv",
    ".html", ".css", ".js", ".py",
})
PDF_EXTENSIONS: frozenset = frozenset({".pdf"})
OFFICE_EXTENSIONS: frozenset = frozenset(MARKITDOWN_EXTS)

#: Every extension some extractor on this box can turn into text, sorted. Both
#: indexers derive their default from this; neither keeps a list of its own.
INDEXABLE_EXTENSIONS: Tuple[str, ...] = tuple(sorted(
    TEXT_EXTENSIONS | PDF_EXTENSIONS | OFFICE_EXTENSIONS
))

# Why a file under an indexed directory is not in the index. Three reasons, kept
# separate because they mean different things to the person who indexed it: a
# format nothing here reads, a file that read as nothing (an encrypted PDF, a
# scan with no text layer, an Office file with markitdown not installed), and a
# file that could not be opened at all.
SKIP_UNSUPPORTED = "unsupported extension"
SKIP_NO_TEXT = "no extractable text"
SKIP_UNREADABLE = "could not be read"


@dataclass
class PersonalDocsConfig:
    """Configuration for personal documents management."""
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    # `B75`. Derived, not restated. The name and the tuple type are unchanged —
    # callers and tests that read `config.DEFAULT_EXTENSIONS` keep working; what
    # changed is that it can no longer disagree with the vector indexer's list.
    DEFAULT_EXTENSIONS: Tuple[str, ...] = INDEXABLE_EXTENSIONS
    DEFAULT_K: int = 5
    STOP_WORDS: Set[str] = None
    
    def __post_init__(self):
        if self.STOP_WORDS is None:
            self.STOP_WORDS = set("""
            the a an is are was were be been being to of in for on at by with from 
            and or if then else when while as it this that those these i you he she 
            we they my your our their me him her us them
            """.split())

# Initialize configuration
config = PersonalDocsConfig()

def read_text_file(path: str) -> str:
    """Read a text file with error handling."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def extractor_for(name: str):
    """The function that turns this filename into text, or None (`B75`).

    Keyed by extractor so a caller cannot ask for a format and then read it the
    wrong way — which is exactly how the vector indexer came to claim `.docx`
    was unsupported while opening `.py` as UTF-8.
    """
    ext = os.path.splitext(str(name or ""))[1].lower()
    if ext in PDF_EXTENSIONS:
        return extract_pdf_text
    if ext in OFFICE_EXTENSIONS:
        return extract_office_text
    if ext in TEXT_EXTENSIONS:
        return read_text_file
    return None


def extract_document_text(path: str) -> str:
    """Text for one indexable file, through its registered extractor (`B75`).

    Returns "" for a format nothing here reads — the caller decides whether that
    is a skip to report or a file to drop.
    """
    fn = extractor_for(path)
    if fn is None:
        return ""
    return fn(path) or ""


def walk_index_candidates(directory: str, extensions=None):
    """Yield ``(path, ext, text, reason)`` for every file the shared walk policy
    admits under ``directory`` (`B75`).

    ``reason`` is "" when the file was read and has text, and one of the
    ``SKIP_*`` constants otherwise. Both indexers consume this, so they cannot
    disagree about which files they saw, how those files were read, or why one
    was left out — which is the whole defect this row is about. Names are sorted
    so two runs over one directory produce the same order.

    ``extensions`` narrows the walk for a caller that deliberately wants a
    subset of the register; the default is everything the register can read.
    The narrowing is applied only to files some extractor COULD have read — a
    format nothing here reads is reported whatever the caller asked for, because
    "you narrowed to .md" is not why a ``.psd`` is missing from the index.
    """
    allowed = None
    if extensions is not None:
        allowed = {str(e).lower() for e in extensions}
    for root, dirs, names in os.walk(directory):
        # Hidden/junk pruning is single-sourced in src.index_walk (#5559); the
        # passed-in root is exempt, as it is for both indexers today.
        prune_index_dirs(dirs)
        for name in sorted(names):
            if not is_indexable_file(name):
                continue
            path = os.path.join(root, name)
            ext = os.path.splitext(name)[1].lower()
            fn = extractor_for(name)
            if fn is None:
                yield path, ext, "", SKIP_UNSUPPORTED
                continue
            if allowed is not None and ext not in allowed:
                continue
            if not os.path.isfile(path):
                yield path, ext, "", SKIP_UNREADABLE
                continue
            try:
                text = fn(path) or ""
            except Exception as e:                      # noqa: BLE001 - reported, not swallowed
                logger.error(f"extract {path}: {e}")
                yield path, ext, "", SKIP_UNREADABLE
                continue
            if not text.strip():
                yield path, ext, "", SKIP_NO_TEXT
                continue
            yield path, ext, text, ""


def split_chunks(text: str, size: int = config.CHUNK_SIZE, overlap: int = config.CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks."""
    if not isinstance(text, str):
        return []
    text = text.strip()
    if not text:
        return []
    chunks = []
    i = 0
    n = len(text)
    while i < n:
        j = min(i + size, n)
        chunks.append(text[i:j])
        if j >= n:
            # Reached the end. Without this, the next start (j - overlap) is
            # still > i, so the loop appended one extra chunk duplicating the
            # last `overlap` chars of the text.
            break
        i = j - overlap if j - overlap > i else j
    return chunks

def tokenize(s: str) -> Set[str]:
    """Tokenize string into words, excluding stop words."""
    text = s if isinstance(s, str) else ""
    tokens = re.findall(r"[A-Za-z0-9_\-]+", text.lower())
    return set(t for t in tokens if t not in config.STOP_WORDS and len(t) > 1)

def load_personal_index(
    personal_dir: str,
    extensions: Tuple[str, ...] = config.DEFAULT_EXTENSIONS,
    skipped: List[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Load and index personal documents.

    Skips hidden and junk directories and hidden files via the shared
    ``index_walk`` policy, so the keyword index matches the vector index and a
    real vault/repo does not sweep in ``.obsidian/`` / ``.git/`` /
    ``node_modules/`` content (#5559).

    `B75`: the walk, the extension set and the extractor routing now come from
    ``walk_index_candidates`` — the same generator the vector indexer consumes —
    so the two indexes over one directory cover the same files. Pass a list as
    ``skipped`` to be told about every file that was NOT indexed and why; the
    parameter is optional so existing callers are unaffected.

    A file whose extractor produced nothing is still listed (with no chunks), as
    it always has been — the docs listing shows the user the file it found — and
    is additionally reported in ``skipped`` with a reason, because "listed but
    unsearchable" is the state this row exists to stop being silent.
    """
    files = []
    for path, _ext, text, reason in walk_index_candidates(personal_dir, extensions):
        if reason == SKIP_UNSUPPORTED or reason == SKIP_UNREADABLE:
            if skipped is not None:
                skipped.append({"path": path, "reason": reason})
            continue
        if reason and skipped is not None:
            skipped.append({"path": path, "reason": reason})
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        chunks = split_chunks(text)
        display = os.path.relpath(path, personal_dir)
        files.append({"name": display, "path": path, "size": size, "chunks": chunks})
    return files

def retrieve_personal_keyword(personal_index: List[Dict], query: str, k: int = 5) -> List[str]:
    """
    Retrieve relevant documents using keyword search.

    Args:
        personal_index: The loaded document index
        query: Search query
        k: Number of results to return

    Returns:
        List of formatted search results
    """
    q = tokenize(query)
    if not q:
        return []

    scored = []
    for f in personal_index:
        if not isinstance(f, dict):
            continue
        for idx, ch in enumerate(f.get("chunks") or []):
            score = len(q & tokenize(ch))
            if score > 0:
                scored.append((score, f.get("name", ""), idx, ch))
    scored.sort(key=lambda x: x[0], reverse=True)

    out = []
    for s, fname, idx, ch in scored[:k]:
        out.append(f"[{fname} :: chunk {idx+1}]\n{ch}")
    return out

def retrieve_personal(personal_index: List[Dict], query: str, k: int = 5,
                     rag_manager=None) -> List[str]:
    """
    Retrieve relevant personal documents using vector search first, falling back to keyword search.

    Args:
        personal_index: The loaded document index
        query: The search query
        k: Number of results to return
        rag_manager: Optional RAGManager instance for vector search

    Returns:
        List of formatted search results
    """
    if not query:
        return []

    # First try vector search if RAGManager is available
    if rag_manager:
        try:
            vector_results = rag_manager.search(query, k)
            if vector_results:
                # Format vector results
                out = []
                for result in vector_results:
                    # Extract filename from path
                    source = result["metadata"].get("source", "")
                    filename = os.path.basename(source)

                    # Format the result
                    formatted = f"[{filename} :: vector search]\n{result['document']}"
                    out.append(formatted)
                return out
        except Exception as e:
            logger.warning(f"Vector search failed, falling back to keyword search: {e}")

    # Fall back to keyword search
    return retrieve_personal_keyword(personal_index, query, k)


def _string_list(values) -> list[str]:
    return [value for value in values or [] if isinstance(value, str)]


class PersonalDocsManager:
    """Manager class for personal document indexing and retrieval."""

    def __init__(self, personal_dir: str, rag_manager=None):
        self.personal_dir = personal_dir
        self.rag_manager = rag_manager
        self.index = []
        # Files walked past and not indexed, with a reason each (`B75`).
        # Populated by refresh_index; declared here so it exists before the
        # first refresh and a reader never meets a missing attribute.
        self.skipped: List[Dict[str, str]] = []
        self.indexed_directories = []  # Track additional directories
        self.excluded_files: Set[str] = set()  # Files removed from RAG listing
        self.directories_file = os.path.join(personal_dir, "indexed_directories.json")
        self._excluded_file = os.path.join(personal_dir, "excluded_files.json")
        self.load_directories()
        self._load_excluded()
        self.refresh_index()

    def load_directories(self):
        """Load the list of indexed directories from persistent storage."""
        try:
            if os.path.exists(self.directories_file):
                with open(self.directories_file, 'r', encoding="utf-8") as f:
                    directories = json.load(f)
                if not isinstance(directories, list):
                    raise ValueError("indexed directories must be a list")
                self.indexed_directories = _string_list(directories)
                logger.info(f"Loaded {len(self.indexed_directories)} indexed directories")
            else:
                self.indexed_directories = []
        except Exception as e:
            logger.error(f"Error loading directories: {e}")
            self.indexed_directories = []

    def save_directories(self):
        """Save the list of indexed directories to persistent storage."""
        try:
            with open(self.directories_file, 'w', encoding="utf-8") as f:
                json.dump(_string_list(self.indexed_directories), f, indent=2)
            logger.info(f"Saved {len(self.indexed_directories)} indexed directories")
        except Exception as e:
            logger.error(f"Error saving directories: {e}")

    def _load_excluded(self):
        """Load the set of excluded file paths from persistent storage."""
        try:
            if os.path.exists(self._excluded_file):
                with open(self._excluded_file, 'r', encoding="utf-8") as f:
                    excluded = json.load(f)
                if not isinstance(excluded, list):
                    raise ValueError("excluded files must be a list")
                self.excluded_files = set(_string_list(excluded))
            else:
                self.excluded_files = set()
        except Exception as e:
            logger.error(f"Error loading excluded files: {e}")
            self.excluded_files = set()

    def _save_excluded(self):
        try:
            with open(self._excluded_file, 'w', encoding="utf-8") as f:
                json.dump(_string_list(self.excluded_files), f)
        except Exception as e:
            logger.error(f"Error saving excluded files: {e}")

    def exclude_file(self, filepath: str):
        """Exclude a file from the listing. Persists across restarts."""
        self.excluded_files.add(os.path.abspath(filepath))
        self._save_excluded()
        self.index = [f for f in self.index if os.path.abspath(f.get("path", "")) != os.path.abspath(filepath)]

    def add_directory(self, directory: str, *, index: bool = True, owner: str = None):
        """Add a directory to the tracking list and optionally index it."""
        # Normalize the path
        directory = os.path.abspath(directory)

        # Clear any exclusions for files in this directory. Match on a path
        # boundary (the directory itself or paths under it) rather than a raw
        # string prefix: a bare ``startswith(directory)`` also matches sibling
        # directories that merely share a name prefix (e.g. adding ``/docs``
        # would wrongly un-exclude files under ``/docs2``).
        self.excluded_files = {
            p for p in self.excluded_files
            if not (p == directory or p.startswith(directory + os.sep))
        }
        self._save_excluded()

        if directory not in self.indexed_directories:
            self.indexed_directories.append(directory)
            self.save_directories()
            logger.info(f"Added directory to tracking: {directory}")
            
            # If RAG manager is available, index the directory immediately.
            # Callers that already indexed with owner metadata can pass
            # index=False so we do not create a second ownerless copy.
            if index and self.rag_manager:
                try:
                    result = self.rag_manager.index_personal_documents(directory, owner=owner)
                    logger.info(f"Indexed {result.get('indexed_count', 0)} chunks from {directory}")
                except Exception as e:
                    logger.error(f"Failed to index directory {directory}: {e}")
            
            # Refresh the local index to include the new directory
            self.refresh_index()
        else:
            logger.info(f"Directory already indexed: {directory}")

    def remove_directory(self, directory: str):
        """Remove a directory from the tracking list."""
        # Normalize the path
        directory = os.path.abspath(directory)
        
        if directory in self.indexed_directories:
            self.indexed_directories.remove(directory)
            self.save_directories()
            logger.info(f"Removed directory from tracking: {directory}")
            
            # Refresh the index to exclude the removed directory
            self.refresh_index()
            
            # Targeted delete of just this directory's chunks. This previously
            # called rag_manager.rebuild_index(), which delete+recreates the
            # entire shared collection (every owner + the base index) and then
            # re-indexed only the remaining tracked dirs — ownerless and never
            # personal_dir — a catastrophic wipe (#1660). remove_directory now
            # removes exactly this directory's chunks and leaves the rest intact.
            if self.rag_manager:
                try:
                    self.rag_manager.remove_directory(directory)
                except Exception as e:
                    logger.error(f"Failed to remove directory from RAG index: {e}")
        else:
            logger.info(f"Directory not in index: {directory}")

    def rename_directory(self, old_directory: str, new_directory: str, *, path_map: Dict[str, str] = None):
        """Rewrite tracked directory and excluded-file paths after an owner rename."""
        old_directory = os.path.abspath(old_directory)
        new_directory = os.path.abspath(new_directory)
        path_map = {os.path.abspath(k): os.path.abspath(v) for k, v in (path_map or {}).items()}

        def rewrite(path: str) -> str:
            abs_path = os.path.abspath(path)
            mapped = path_map.get(abs_path)
            if mapped:
                return mapped
            if abs_path == old_directory:
                return new_directory
            if abs_path.startswith(old_directory + os.sep):
                return new_directory + abs_path[len(old_directory):]
            return abs_path

        changed_dirs = False
        rewritten_dirs = []
        for directory in self.indexed_directories:
            rewritten = rewrite(directory)
            changed_dirs = changed_dirs or rewritten != os.path.abspath(directory)
            if rewritten not in rewritten_dirs:
                rewritten_dirs.append(rewritten)
        if changed_dirs:
            self.indexed_directories = rewritten_dirs
            self.save_directories()

        changed_excluded = False
        rewritten_excluded = set()
        for path in self.excluded_files:
            rewritten = rewrite(path)
            changed_excluded = changed_excluded or rewritten != os.path.abspath(path)
            rewritten_excluded.add(rewritten)
        if changed_excluded:
            self.excluded_files = rewritten_excluded
            self._save_excluded()

        if changed_dirs or changed_excluded:
            self.refresh_index()

    def get_indexed_directories(self):
        """Get the list of all indexed directories."""
        return self.indexed_directories.copy()

    def refresh_index(self):
        """Refresh the document index including all tracked directories.

        `B75`: records every file it walked past and why on ``self.skipped``, so
        a caller can say which files are in neither index instead of leaving the
        user to discover it by searching and finding nothing.
        """
        self.index = []
        self.skipped: List[Dict[str, str]] = []

        # Index the base personal directory
        base_files = load_personal_index(self.personal_dir, skipped=self.skipped)
        for f in base_files:
            if os.path.abspath(f.get("path", "")) in self.excluded_files:
                continue
            f['source_dir'] = self.personal_dir
            self.index.append(f)

        # Index additional directories
        for directory in self.indexed_directories:
            if not os.path.exists(directory):
                logger.warning(f"Directory no longer exists: {directory}")
                continue

            if not os.path.isdir(directory):
                logger.warning(f"Path is not a directory: {directory}")
                continue

            # Load files from this directory
            dir_files = load_personal_index(directory, skipped=self.skipped)
            for f in dir_files:
                if os.path.abspath(f.get("path", "")) in self.excluded_files:
                    continue
                # Update the name to include the directory for clarity
                f['source_dir'] = directory
                f['name'] = f"{os.path.basename(directory)}/{f['name']}"
                self.index.append(f)

        logger.info(f"Refreshed index: {len(self.index)} documents from {len(self.indexed_directories) + 1} directories")

    def retrieve(self, query: str, k: int = 5) -> List[str]:
        """Retrieve relevant documents for a query."""
        return retrieve_personal(self.index, query, k, self.rag_manager)

    def get_file_list(self) -> List[Dict[str, Any]]:
        """Get list of indexed files with metadata."""
        return [{"name": f["name"], "size": f["size"]} for f in self.index]

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about indexed documents."""
        total_docs = len(self.index)
        total_chunks = sum(len(doc.get('chunks', [])) for doc in self.index)
        total_size = sum(doc.get('size', 0) for doc in self.index)
        
        extensions = {}
        for doc in self.index:
            ext = os.path.splitext(doc['path'])[1]
            extensions[ext] = extensions.get(ext, 0) + 1
        
        return {
            'total_documents': total_docs,
            'total_chunks': total_chunks,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'file_types': extensions,
            'directories_count': len(self.indexed_directories) + 1,
            'base_directory': self.personal_dir,
            'additional_directories': self.indexed_directories
        }
        
    def index_all_directories(self):
        """Re-index all tracked directories in the RAG system."""
        if not self.rag_manager:
            logger.warning("No RAG manager available for indexing")
            return
        
        success_count = 0
        failure_count = 0
        
        # Index the base personal directory
        try:
            result = self.rag_manager.index_personal_documents(self.personal_dir)
            if result.get('success'):
                success_count += 1
                logger.info(f"Indexed base directory: {self.personal_dir}")
        except Exception as e:
            failure_count += 1
            logger.error(f"Failed to index base directory {self.personal_dir}: {e}")
        
        # Index additional directories
        for directory in self.indexed_directories:
            if not os.path.exists(directory):
                logger.warning(f"Skipping non-existent directory: {directory}")
                failure_count += 1
                continue
            
            try:
                result = self.rag_manager.index_personal_documents(directory)
                if result.get('success'):
                    success_count += 1
                    logger.info(f"Indexed directory: {directory}")
                else:
                    failure_count += 1
                    logger.error(f"Failed to index directory {directory}: {result.get('message')}")
            except Exception as e:
                failure_count += 1
                logger.error(f"Failed to index directory {directory}: {e}")
        
        logger.info(f"Indexing complete: {success_count} succeeded, {failure_count} failed")
        return {"success": success_count, "failed": failure_count}
