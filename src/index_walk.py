# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared walk policy for personal-document indexing (#5559, `P14-07`).

Single source of the hidden-dir / junk-dir / hidden-file skip so the vector
index (``rag_vector.index_personal_documents``) and the keyword index
(``personal_docs.load_personal_index``) apply the exact same policy and cannot
drift — the drift is what left the keyword path sweeping in `.obsidian/`,
`.git/`, and `node_modules/` after the vector path was fixed.

`P14-07` — PACED AND BOUNDED, AND HERE FOR THE SAME REASON THE PRUNING IS.

The row cites PandaOS: an out-of-memory crash that closed the app with no
warning while it built a search index, fixed with one lazy bounded index and
paced background work. Pantheon indexes ChromaDB, the tool index and RAG **on
the machine somebody is using**, and the same two holes were open here.
Measured on this tree, before this row:

  * a 105 MB notes vault -> 131,200 chunks retained in memory, RSS 48 -> 185 MB,
    and `PersonalDocsManager.index` holds them for the life of the process —
    which `__init__` builds at startup, before anyone asks for anything;
  * **one 419 MB file in that folder -> RSS 185 -> 1,384 MB.** A 3.3x
    multiplier: the decoded string, then the chunk list, which overlaps and so
    is larger than the file. On a 2 GB container that is the crash, with no
    warning, exactly as the row describes. Nothing capped the size of a file the
    walk would read, and a `.md` is a `.md` whether it is a note or a database
    dump somebody exported into their documents folder;
  * nothing yielded. The walk runs flat out for as long as it takes, holding a
    core (and the GIL) while a person is mid-conversation with the thing.

So: a per-file ceiling, a ceiling on what the keyword index retains, and a duty
cycle. All three are settings with a `0` that means *no ceiling*, because an
operator who wants their 400 MB file indexed is entitled to it — what they are
not entitled to is inheriting that as a default that kills the app (`Law 1`:
the capability stays, the default becomes finite).

Both indexers take their files from ``walk_index_candidates``, which is why the
ceiling and the pacing live behind one call rather than at two sites that would
drift apart the first time one of them was edited (`Law 13`).
"""
import time
from typing import List, Optional, Set

# Well-known non-hidden junk directories to skip. Matched case-insensitively so
# a `Node_Modules` on a case-insensitive filesystem (macOS default) is still
# pruned. Hidden directories (dot-prefixed) are pruned separately. Kept
# deliberately small: over-pruning would silently drop a user's real content
# (e.g. a notes directory legitimately named "build").
EXCLUDED_DIR_NAMES: Set[str] = {'node_modules', '__pycache__', 'venv'}


def prune_index_dirs(dirs: List[str]) -> None:
    """In-place ``os.walk`` (topdown) directory prune: drop hidden and known
    junk directories so the walk never descends into them.

    The explicitly-targeted walk root is never a member of ``dirs`` (it is the
    ``dirpath`` argument), so it stays exempt — a user who deliberately points
    indexing at a hidden directory gets its contents, minus nested junk.
    """
    dirs[:] = [
        d for d in dirs
        if not d.startswith('.') and d.lower() not in EXCLUDED_DIR_NAMES
    ]


def is_indexable_file(name: str) -> bool:
    """A file is indexable only if it is not hidden (dot-prefixed)."""
    return not name.startswith('.')


# ---------------------------------------------------------------------------
# P14-07 — the ceilings, and the duty cycle
# ---------------------------------------------------------------------------

# One file this walk will read, in MiB. 32 MiB of text is roughly a 30-volume
# encyclopedia and about four times the largest file in any real document set
# measured here; at the 3.3x peak multiplier above it costs ~105 MB while it is
# being chunked, which a small container survives and 419 MB was not.
DEFAULT_MAX_FILE_MB = 32

# What the keyword index will hold in memory, in MiB. The measurement: 105 MB of
# text retained 137 MB of RSS, so 256 MiB is a ~190 MB document set held whole —
# comfortably more than the folder anybody has pointed this at, and a ceiling
# rather than an ambition. Past it, files are still LISTED with a reason; they
# are simply not held (see `personal_docs.load_personal_index`).
DEFAULT_BUDGET_MB = 256

# The duty cycle. Work for this long, then let go for this long.
#
# 10% is enough to keep a machine responsive during a long index and small
# enough that nobody watching a progress count thinks it has stalled. It costs
# nothing on a short walk: a 0.2s index never reaches the first rest.
PACE_WORK_SECONDS = 0.2
PACE_REST_SECONDS = 0.02


def _setting_mb(name: str, default_mb: int) -> int:
    """A MiB setting in bytes. `0` means no ceiling and is a real answer.

    Settings-only, with no environment variable, for the reason written out at
    `events_retention_days` in `src/settings.py`: `get_setting` merges
    `DEFAULT_SETTINGS` on every read, so an env fallback beneath a truthy
    default is unreachable code. That shape has been found dead four times in
    this repository and is not being added a fifth.
    """
    try:
        from src.settings import get_setting
        mb = int(get_setting(name, default_mb))
    except Exception:
        mb = default_mb
    if mb < 0:
        mb = default_mb
    return mb * 1024 * 1024


def max_file_bytes() -> int:
    """The per-file ceiling for an index read. 0 = no ceiling."""
    return _setting_mb("index_max_file_mb", DEFAULT_MAX_FILE_MB)


def retained_budget_bytes() -> int:
    """What the in-memory keyword index may hold. 0 = no ceiling."""
    return _setting_mb("index_budget_mb", DEFAULT_BUDGET_MB)


def file_is_too_large(path: str, ceiling: Optional[int] = None) -> bool:
    """Whether reading this file would be the crash rather than the index.

    Asked before the extractor runs, because the extractor is where the memory
    goes: by the time a 419 MB file is a `str` the decision has been made.
    A file that cannot be stat'd is NOT called too large — that is a different
    failure with its own reason (`SKIP_UNREADABLE`), and answering it here
    would file an unreadable file under the wrong cause.
    """
    import os

    ceiling = max_file_bytes() if ceiling is None else ceiling
    if ceiling <= 0:
        return False
    try:
        return os.path.getsize(path) > ceiling
    except OSError:
        return False


class IndexBudget:
    """A byte budget for what an index keeps in memory.

    `take(n)` is the whole interface: True while there is room, False once
    there is not, and it never partially admits — half a document in a keyword
    index is a document that matches queries it cannot answer.

    A budget of `0` admits everything, which is what an operator who set the
    setting to `0` asked for.
    """

    def __init__(self, limit_bytes: Optional[int] = None):
        self.limit = retained_budget_bytes() if limit_bytes is None else int(limit_bytes)
        self.used = 0
        self.dropped = 0

    @property
    def exhausted(self) -> bool:
        return bool(self.limit) and self.used >= self.limit

    def take(self, n: int) -> bool:
        n = max(0, int(n))
        if self.limit and self.used + n > self.limit:
            self.dropped += 1
            return False
        self.used += n
        return True


class IndexPacer:
    """Let go of the CPU periodically, so an index does not own the machine.

    Deliberately NOT `src/jitter.py`. That module spreads the moment a recurring
    job *starts*, across installs, so a shared provider sees a rate rather than a
    spike; this shares one machine between a background walk and the person
    using it. Same discipline, different question, and folding them together
    would give one of them the other's docstring.

    `tick()` is called once per file. It sleeps only when the work since the last
    rest has run past `work_seconds`, so a short index never sleeps at all and a
    long one gives back ~10%.
    """

    def __init__(self, work_seconds: float = PACE_WORK_SECONDS,
                 rest_seconds: float = PACE_REST_SECONDS,
                 sleep=time.sleep, clock=time.monotonic):
        self.work_seconds = float(work_seconds)
        self.rest_seconds = float(rest_seconds)
        self._sleep = sleep
        self._clock = clock
        self._worked_since = clock()
        self.rests = 0
        self.slept = 0.0

    def tick(self) -> float:
        """Rest if it is time to. Returns the seconds slept (0 when it is not)."""
        if self.work_seconds <= 0 or self.rest_seconds <= 0:
            return 0.0
        now = self._clock()
        if now - self._worked_since < self.work_seconds:
            return 0.0
        self._sleep(self.rest_seconds)
        self.rests += 1
        self.slept += self.rest_seconds
        self._worked_since = self._clock()
        return self.rest_seconds
