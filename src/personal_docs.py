# SPDX-License-Identifier: AGPL-3.0-or-later
# src/personal_docs.py
import os
import re
import json
import logging
from typing import List, Dict, Set, Any, Tuple
from dataclasses import dataclass

from src.index_walk import (IndexBudget, IndexPacer, file_is_too_large,
                            is_indexable_file, max_file_bytes, prune_index_dirs)

# `B162`/`B180`. The registers are imported, never restated. ``MARKITDOWN_EXTS``
# is kept as a re-export because this module has exported it since `B75` and
# taking a name away is not this row's business (`Law 1`); nothing here reads it
# any more — ``OFFICE_EXTS`` is the register that answers "can anything extract
# this", which is the question an indexer has.
from src.markitdown_runtime import MARKITDOWN_EXTS, OFFICE_EXTS  # noqa: F401
from src.pdf_runtime import PDF_EXTS
from src.document_processor import (
    ENCODING_UNIDENTIFIED,
    INGESTIBLE_EXTS,
    TEXT_EXTS,
    TEXT_SNIFF_BYTES,
    decode_text_file,
    describe_text_encoding,
    sniff_text_encoding,  # noqa: F401 - exported since `B162`; `Law 1`
)

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


# ── one register per extractor (`B75`, joined to chat ingest by `B162`) ─────
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
# `B75` wrote three new names here — a ten-entry `TEXT_EXTENSIONS`, a one-entry
# `PDF_EXTENSIONS` and `OFFICE_EXTENSIONS = MARKITDOWN_EXTS` — which collapsed
# the two indexing lists into one but made the index a **fourth** answer to "can
# we read this extension", beside `document_processor.TEXT_EXTS` (28),
# `markitdown_runtime.OFFICE_EXTS` (7) and `pdf_runtime.PDF_EXTS` (1). Measured
# on the tree before `B162`: chat ingest read **36** extensions and the index
# **16**, so the 20 in between — `.bash .c .cpp .doc .go .h .htm .java .jsx .log
# .nix .odt .php .rb .rs .sh .sql .ts .tsx .xml` — were files a chat could read
# and a search could not find. `.doc` and `.odt` are the sharp ones: `B102`
# wrote two bundled extractors for them and the index called them unsupported.
#
# So the three names stay (`Law 1` — `rag_vector` and the tests import them) and
# every one of them is now the register that already existed (`Law 14`). There
# is one register per extractor and the index takes the union, which is the same
# union chat ingest takes, because it is the same object.
#
# A register is still only half the answer, and the same half it was in `B76`:
# it says WHICH extractor, never WHETHER to read. `extract_index_text` asks the
# bytes for the files no register claims, so a `.conf` or a `.toml` is indexed
# for the same reason it reaches the model — it decodes.
TEXT_EXTENSIONS: frozenset = frozenset(TEXT_EXTS)
PDF_EXTENSIONS: frozenset = frozenset(PDF_EXTS)
OFFICE_EXTENSIONS: frozenset = frozenset(OFFICE_EXTS)

#: Every extension some extractor on this box can turn into text, sorted. Both
#: indexers derive their default from this; neither keeps a list of its own, and
#: since `B162` it is ``document_processor.INGESTIBLE_EXTS`` — the set
#: `upload_handler.is_document_file` already answers with — rather than a
#: parallel union that happened to be built from two of the same three parts.
INDEXABLE_EXTENSIONS: Tuple[str, ...] = tuple(sorted(INGESTIBLE_EXTS))

# Why a file under an indexed directory is not in the index. Three reasons, kept
# separate because they mean different things to the person who indexed it: a
# format nothing here reads *and* whose bytes do not decode as text, a file that
# read as nothing (an encrypted PDF, a scan with no text layer, an Office file
# with markitdown not installed), and a file that could not be opened at all.
SKIP_UNSUPPORTED = "unsupported extension"
SKIP_NO_TEXT = "no extractable text"
SKIP_UNREADABLE = "could not be read"
# `B201`: a fourth reason, because the third was being used for a file that is
# none of the above. A file whose suffix no register names and whose bytes are
# text in an encoding too short a sample cannot identify was reported as
# "unsupported extension" — a lie about the format, which is fine, pointing the
# operator at the wrong fix. It is grouped with ``SKIP_UNSUPPORTED`` everywhere
# a decision is made (see ``NOT_LISTED``); only the sentence differs.
SKIP_UNKNOWN_ENCODING = "text in an unidentifiable encoding"
# `P14-07`: a fifth, and it is the only one that is about US rather than about
# the file. The other four say "we cannot read this"; these two say "we can, and
# we chose not to, and here is the number that decided it" — so the sentence
# carries the ceiling and the setting, because a skip whose remedy is a setting
# is useless without the setting's name.
SKIP_TOO_LARGE = "larger than the {mb} MB index ceiling (index_max_file_mb)"
SKIP_INDEX_FULL = ("listed but not held in memory: the index reached its "
                   "{mb} MB ceiling (index_budget_mb)")

# The reasons that mean "this file is not in the index at all", as opposed to
# "it is listed and holds nothing". One tuple so a new reason cannot be added
# without deciding which side of that line it falls on.
#
# `SKIP_TOO_LARGE` and `SKIP_INDEX_FULL` are deliberately NOT here. A file we
# declined to read is one the user put in their documents folder and can see in
# their file manager; dropping it from the listing as well would answer "where
# is my 400 MB export" with silence, which is the failure mode `B75` filed.
NOT_LISTED = (SKIP_UNSUPPORTED, SKIP_UNREADABLE, SKIP_UNKNOWN_ENCODING)


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
    """Read a text file in the encoding its own bytes declare (`B162`).

    This was ``open(..., encoding="utf-8", errors="ignore")`` — the exact call
    `B101` removed from the chat path, left in place here because
    `src/personal_docs.py` was another row's surface that wave. ``errors=
    "ignore"`` does not mangle a legacy-encoded file, it **empties** it, and it
    cannot raise, so nothing downstream ever knew. Measured on the tree before
    this row, over files the index accepted and indexed:

      * a cp1251 Russian ``.txt`` indexed as ``'  '`` — two spaces, **zero
        tokens**, so it matched no query and reported no error;
      * a cp1250 Polish ``.txt`` reading ``Zażółć gęślą jaźń`` indexed as
        ``'Za gl ja'``, so a search for the word the user typed missed a file
        the index believed it held;
      * a BOM'd UTF-16 ``.txt`` indexed as ``'a\\x00t\\x00t\\x00...'``, because
        NUL is valid UTF-8 and ``ignore`` had nothing to drop.

    ``document_processor.decode_text_file`` is this read with the encoding
    sniffed from the first 8 KiB (BOM, then NUL-means-binary, then clean UTF-8,
    then ``charset_normalizer`` when it decodes strictly cleaner) — one reader
    for chat and index, so a file cannot be legible in a message and empty in
    the search (`Law 13`).

    The "never raises" contract is unchanged: every caller here treats ``""`` as
    "nothing to index", and ``walk_index_candidates`` reports that as
    ``SKIP_NO_TEXT``.
    """
    try:
        return decode_text_file(path)
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


def extract_index_text(path: str, name: str = None) -> Tuple[str, str]:
    """``(text, reason)`` for one file, by the same dispatch chat ingest uses.

    `B162`/`B180`. One place answers "can we read this file", and it answers it
    in two steps, which is the shape `B76` measured and `build_user_content`
    already runs:

      1. **The registers say which extractor.** `.pdf` -> pypdf, an Office
         format -> ``markitdown_runtime`` (markitdown, or the bundled
         `.docx`/`.odt`/`.doc` readers), a registered text suffix -> the encoding
         sniffer.
      2. **When no register claims the file, the bytes decide whether to read
         it.** ``sniff_text_encoding`` is the same verdict
         ``document_processor.looks_like_text`` returns for an attachment, so a
         `.conf`, a `.toml` or a `.rst` that a person can paste into a chat is
         indexed rather than called "unsupported extension" — which is `B162`'s
         `Verify` clause, and the reason a register alone could not have met it.

    Refusing to guess from the suffix alone is the whole point: the registers
    keep their real job (*which* extractor) and never regain the one they were
    wrong at (*whether* to bother).

    Reasons, not silence: a caller gets ``SKIP_UNSUPPORTED`` when nothing reads
    the format and the bytes are not text, ``SKIP_UNKNOWN_ENCODING`` when the
    bytes *are* text but too few of them to name the encoding (`B201`),
    ``SKIP_NO_TEXT`` when an extractor ran and produced nothing, and
    ``SKIP_UNREADABLE`` when it raised or the file could not be opened at all.
    """
    label = name or path
    fn = extractor_for(label)
    if fn is None:
        # `B76`'s rule, now the index's too. This is one bounded ``read(8192)``
        # and it is paid only by files no register claims — i.e. only by files
        # whose current cost is "not in the index at all". ``sniff_text_encoding``
        # is the function ``looks_like_text`` is a two-line wrapper around; it is
        # called directly here so that a file which cannot be OPENED is reported
        # as unreadable instead of being filed under "unsupported extension",
        # which would be a lie about a format that may be perfectly supported.
        try:
            with open(path, "rb") as fh:
                head = fh.read(TEXT_SNIFF_BYTES)
        except OSError as e:
            logger.warning(f"probe {path}: {e}")
            return "", SKIP_UNREADABLE
        encoding, why = describe_text_encoding(head)
        if encoding is None:
            # `B201`. Two different things to tell the operator: a container
            # nothing here reads, and a text file whose encoding a short sample
            # could not name. Both stay out of the index; only one of them is
            # answered by "install an extractor".
            return "", (SKIP_UNKNOWN_ENCODING if why == ENCODING_UNIDENTIFIED
                        else SKIP_UNSUPPORTED)
        fn = read_text_file
    try:
        text = fn(path) or ""
    except Exception as e:                      # noqa: BLE001 - reported, not swallowed
        logger.error(f"extract {path}: {e}")
        return "", SKIP_UNREADABLE
    if not text.strip():
        return "", SKIP_NO_TEXT
    return text, ""


def extract_document_text(path: str) -> str:
    """Text for one indexable file, through its registered extractor (`B75`).

    Returns "" for a file nothing here can read — the caller decides whether that
    is a skip to report or a file to drop. `B162` widened "can read" from the
    registers alone to the registers plus the decode probe, so this answers for
    a `.conf` the way chat ingest does; ``extract_index_text`` is the same call
    with the reason attached.
    """
    return extract_index_text(path)[0]


def walk_index_candidates(directory: str, extensions=None, pacer=None):
    """Yield ``(path, ext, text, reason)`` for every file the shared walk policy
    admits under ``directory`` (`B75`).

    ``reason`` is "" when the file was read and has text, and one of the
    ``SKIP_*`` constants otherwise. Both indexers consume this, so they cannot
    disagree about which files they saw, how those files were read, or why one
    was left out — which is the whole defect this row is about. Names are sorted
    so two runs over one directory produce the same order.

    ``extensions`` narrows the walk for a caller that deliberately wants a
    subset of the register; the default is everything this box can read. The
    narrowing is applied only to files that COULD have been read — a file
    nothing here reads is reported whatever the caller asked for, because "you
    narrowed to .md" is not why a ``.psd`` is missing from the index.

    `B162`: naming the whole register is not a narrowing. Both indexers pass it
    explicitly (``config.DEFAULT_EXTENSIONS`` / ``rag_vector.DEFAULT_FILE_
    EXTENSIONS``) and they mean "everything", so a set that covers the register
    is treated as no filter at all — otherwise the byte-decoded formats, which
    by definition have no registered suffix, would be filtered out by the
    default argument of the only two callers there are.

    `P14-07`: a file over ``index_max_file_mb`` is reported as ``SKIP_TOO_LARGE``
    **without being read**, and the walk rests periodically so a long index does
    not own the machine somebody is using. ``pacer`` is an ``IndexPacer``; the
    default builds one per walk, and a caller indexing several directories in a
    row can pass one so the duty cycle spans the whole job rather than resetting
    at each directory boundary.
    """
    allowed = None
    if extensions is not None:
        allowed = {str(e).lower() for e in extensions}
        if allowed.issuperset(INDEXABLE_EXTENSIONS):
            allowed = None
    # `P14-07`. The ceiling and the duty cycle sit here, at the one generator
    # both indexers consume, rather than at each of them — a bound applied in
    # one of two places is the defect class `Law 13` names, and these two have
    # drifted from each other before (#5559, `B75`).
    ceiling = max_file_bytes()
    pacer = pacer or IndexPacer()
    for root, dirs, names in os.walk(directory):
        # Hidden/junk pruning is single-sourced in src.index_walk (#5559); the
        # passed-in root is exempt, as it is for both indexers today.
        prune_index_dirs(dirs)
        for name in sorted(names):
            if not is_indexable_file(name):
                continue
            path = os.path.join(root, name)
            ext = os.path.splitext(name)[1].lower()
            registered = extractor_for(name) is not None
            # A registered format the caller narrowed away costs nothing: the
            # extractor never runs. An unregistered one has to be probed before
            # this can tell "you asked not to see it" from "nothing reads it",
            # and the probe is the bounded 8 KiB read, not the extraction.
            if registered and allowed is not None and ext not in allowed:
                continue
            if not os.path.isfile(path):
                yield path, ext, "", SKIP_UNREADABLE
                continue
            # Before the extractor, because the extractor is where the memory
            # goes: one 419 MB file measured at 1,384 MB of RSS, and by the time
            # it is a `str` the decision has already been made.
            if file_is_too_large(path, ceiling):
                yield path, ext, "", SKIP_TOO_LARGE.format(
                    mb=ceiling // (1024 * 1024))
                continue
            # Once per file, and it sleeps only after a run of solid work — a
            # short index never reaches the first rest.
            pacer.tick()
            text, reason = extract_index_text(path, name)
            if not reason and allowed is not None and ext not in allowed:
                continue
            yield path, ext, text, reason


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
    """Tokenize string into words, excluding stop words.

    `B200`: the pattern was ``[A-Za-z0-9_\\-]+``, so the keyword index scored
    every document on its ASCII fragments alone. Measured: ``сервер порт
    настройка`` tokenises to **nothing at all**, and so does Greek; Polish
    ``Zażółć gęślą jaźń pchnąć`` tokenises to ``{za, ja, pchn}`` — the pieces
    between the accents, none of which is a word anyone would search for. A
    correctly decoded, correctly indexed Russian document therefore matched no
    query, including a query copied out of the document.

    ``\\w`` is Unicode-aware for ``str`` patterns in Python 3 and is a strict
    superset of the old class (letters, digits and ``_``), so every token the
    index held before it still holds. **What this does not fix**: a script that
    does not put spaces between words — Chinese, Japanese, Thai — still yields
    one token per run of characters. That needs segmentation, not a character
    class, and it is not something a regex will ever answer.
    """
    text = s if isinstance(s, str) else ""
    tokens = re.findall(r"[\w\-]+", text.lower())
    return set(t for t in tokens if t not in config.STOP_WORDS and len(t) > 1)

def load_personal_index(
    personal_dir: str,
    extensions: Tuple[str, ...] = config.DEFAULT_EXTENSIONS,
    skipped: List[Dict[str, str]] = None,
    budget: "IndexBudget" = None,
    pacer: "IndexPacer" = None,
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

    `P14-07`: ``budget`` caps what is held in memory across the whole call, and
    ``pacer`` is the duty cycle. Both default to a fresh one per call; a caller
    indexing several directories — ``PersonalDocsManager.refresh_index`` does —
    passes one of each so the ceiling covers the *index*, not each directory
    separately, which would be a ceiling multiplied by however many folders
    somebody happened to add.
    """
    files = []
    budget = budget if budget is not None else IndexBudget()
    for path, _ext, text, reason in walk_index_candidates(
            personal_dir, extensions, pacer=pacer):
        if reason in NOT_LISTED:
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
        # `P14-07`. The chunks are what this index IS — they are held for the
        # life of the process, and `PersonalDocsManager.__init__` builds them at
        # startup before anybody has asked for anything. Measured: 105 MB of
        # notes retained 131,200 chunks and 137 MB of RSS, with no ceiling of
        # any kind above it.
        #
        # Past the ceiling the file is still LISTED — the user can see it, with
        # the reason and the setting that raises it — and simply holds nothing.
        # That is the same state as a file whose extractor produced no text,
        # which this index has always had and `B75` made visible rather than
        # silent. Dropping the file from the listing instead would answer "where
        # is my document" with nothing at all.
        if chunks and not budget.take(sum(len(c) for c in chunks)):
            chunks = []
            if skipped is not None:
                skipped.append({"path": path, "reason": SKIP_INDEX_FULL.format(
                    mb=budget.limit // (1024 * 1024))})
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

        # `P14-07`. ONE budget and ONE pacer for the whole refresh, not one per
        # directory. Thirteen folders each politely stopping at their own
        # ceiling is thirteen ceilings, which is not a ceiling — the same
        # mistake `P15-05` found in the HuggingFace refresh, where per-source
        # caps summed to a burst.
        budget = IndexBudget()
        pacer = IndexPacer()

        # Index the base personal directory
        base_files = load_personal_index(self.personal_dir, skipped=self.skipped,
                                         budget=budget, pacer=pacer)
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
            dir_files = load_personal_index(directory, skipped=self.skipped,
                                            budget=budget, pacer=pacer)
            for f in dir_files:
                if os.path.abspath(f.get("path", "")) in self.excluded_files:
                    continue
                # Update the name to include the directory for clarity
                f['source_dir'] = directory
                f['name'] = f"{os.path.basename(directory)}/{f['name']}"
                self.index.append(f)

        # Kept so `get_stats` can report what was held and what was not. A
        # ceiling nobody can see is a ceiling that gets diagnosed as "search is
        # broken" (`Law 15`).
        self.index_budget = budget
        self.index_pacer = pacer
        logger.info(
            f"Refreshed index: {len(self.index)} documents from "
            f"{len(self.indexed_directories) + 1} directories "
            f"({budget.used / (1024 * 1024):.0f} MB held"
            + (f", {budget.dropped} file(s) over the ceiling" if budget.dropped else "")
            + (f", rested {pacer.slept:.1f}s" if pacer.rests else "") + ")")

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
        
        # `P14-07`. What the in-memory index is holding, against what it is
        # allowed to hold. Zero-cost to report and the difference between
        # "search does not find my file" and "search is broken".
        budget = getattr(self, 'index_budget', None)
        return {
            'total_documents': total_docs,
            'total_chunks': total_chunks,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'file_types': extensions,
            'directories_count': len(self.indexed_directories) + 1,
            'base_directory': self.personal_dir,
            'additional_directories': self.indexed_directories,
            'held_bytes': getattr(budget, 'used', 0),
            'held_limit_bytes': getattr(budget, 'limit', 0),
            'files_over_budget': getattr(budget, 'dropped', 0),
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
