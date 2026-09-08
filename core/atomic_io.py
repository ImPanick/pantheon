# SPDX-License-Identifier: AGPL-3.0-or-later
"""Atomic JSON file writes.

Use this everywhere a JSON config file is persisted. A plain `open("w") +
json.dump` truncates the file on first write and only fills it with new
content afterwards — a kill -9 / power loss / OOM in between produces a
truncated or empty file. For password DBs (`auth.json`) and live state
(`sessions.json`, `settings.json`, `integrations.json`, `cookbook_state.json`),
that's a data-loss event.

`atomic_write_json` writes to a sibling tmp file, fsyncs, then `os.replace`s
into place. On POSIX `os.replace` is atomic on the same filesystem.

Atomicity is not the only way a config file dies. `P3-16`: PandaOS permanently
lost user API keys when a locked keychain made a read return empty and the
empty was written straight back. The shape is a **read-then-write** where the
read has a silent fallback — `except: return {}`, `except: merged =
dict(DEFAULTS)` — and the caller cannot tell "this file is not there" from
"this file is there and I could not read it". The first is an empty state a
write should create. The second is a full file a write will destroy.

`preserve_unreadable=True` refuses that second case: if the target exists but
cannot be parsed, the write raises `UnreadableTargetError` rather than
replacing it. Pass it for stores whose contents cannot be regenerated —
`auth.json`, `settings.json`, credentials, anything a person typed — and leave
it off for state the app rebuilds by itself, where refusing would wedge a
rebuildable file forever. `.pantheon/check-config-writes.py` holds that
classification so it is a decision per store rather than per call site.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Optional


class UnreadableTargetError(OSError):
    """A write was refused because the file it would replace could not be read.

    An `OSError` because that is what the callers around this already expect
    from a filesystem refusal, and because a store that cannot be read is a
    storage problem — not a validation error about the data being written.
    """


def _refuse_if_unreadable(path: str) -> None:
    """Guard for `preserve_unreadable`. Absent is fine; unreadable is not.

    An absent file is an empty state and creating it is the write's job. A file
    that exists and does not parse is a file whose contents are unknown, and
    every caller of this module reached its data through a loader that answers
    an unreadable file with defaults. Writing then persists the defaults over
    whatever was really there.

    The check runs at write time rather than being remembered from the read: a
    sticky flag set by one failed load would wedge every later save even after
    the operator fixed the file, and would miss a file that went bad between
    the read and the write.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            json.load(f)
    except FileNotFoundError:
        return
    except (OSError, ValueError) as exc:
        # ValueError covers json.JSONDecodeError, which subclasses it.
        raise UnreadableTargetError(
            f"refusing to overwrite {path}: it exists but could not be read "
            f"({exc.__class__.__name__}: {exc}). Whatever is in it now would be "
            "replaced by data derived from a read that failed."
        ) from exc


def atomic_write_json(
    path: str,
    data: Any,
    *,
    indent: Optional[int] = None,
    preserve_unreadable: bool = False,
) -> None:
    """Atomically persist `data` as JSON at `path`.

    The temp file uses a random suffix so two concurrent writers saving the
    same file don't collide on the rename target. A PID suffix does not do
    this: the PID is constant for the life of a process, so two writers on
    the same path within one process (or one single-process container, where
    the PID never changes at all) still race for the same temp file.
    """
    if preserve_unreadable:
        _refuse_if_unreadable(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{uuid.uuid4().hex}"

    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        # Directly unlink to avoid a check-then-act race condition.
        # Swallows FileNotFoundError (on success path) and other cleanup OSErrors.
        try:
            os.unlink(tmp)
        except OSError:
            pass


def atomic_write_text(path: str, text: str, *, preserve_unreadable: bool = False) -> None:
    """Text has no parse step, so "unreadable" here means the bytes cannot be
    read at all — a permission or IO error. A file that reads fine is readable
    whatever it says, because this module has no idea what a valid one looks
    like.
    """
    if not isinstance(text, str):
        raise TypeError("atomic_write_text expects a string")
    if preserve_unreadable:
        try:
            with open(path, "r", encoding="utf-8") as f:
                f.read()
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            raise UnreadableTargetError(
                f"refusing to overwrite {path}: it exists but could not be read "
                f"({exc.__class__.__name__}: {exc})."
            ) from exc
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{uuid.uuid4().hex}"

    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        # Directly unlink to avoid a check-then-act race condition.
        # Swallows FileNotFoundError (on success path) and other cleanup OSErrors.
        try:
            os.unlink(tmp)
        except OSError:
            pass