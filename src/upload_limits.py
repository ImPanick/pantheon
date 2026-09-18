# SPDX-License-Identifier: AGPL-3.0-or-later
"""Route-local upload size caps, and the layers that answer for them.

`P12-01` / `P12-03`. Every cap here resolves
**role profile → instance setting → env → built-in default**, and resolves it
*per request* rather than once at import. Before this, eight of the ten byte
caps in the product were module constants fixed at import: an operator who
wanted a bigger upload for one team had no move except editing compose and
rebuilding.

The module-level constants below are kept and still read the environment at
import. They are `Law 1`: `from src.upload_limits import GALLERY_UPLOAD_MAX_BYTES`
keeps working, an invalid environment value still fails fast at boot instead of
mid-request, and three tests pin their defaults exactly (`FORBIDDEN.md` Part 2).
They are the *snapshot*, not the live answer — live call sites use
`resolve_byte_limit`.
"""

import logging
import os

from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

DEFAULT_CHAT_UPLOAD_MAX_BYTES = 10 * 1024 * 1024
CHAT_UPLOAD_MAX_BYTES_ENV = "PANTHEON_CHAT_UPLOAD_MAX_BYTES"


def format_byte_limit(limit: int) -> str:
    if limit % (1024 * 1024) == 0:
        return f"{limit // (1024 * 1024)} MB"
    if limit % 1024 == 0:
        return f"{limit // 1024} KB"
    return f"{limit} bytes"


def read_byte_limit_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer byte count") from exc
    if limit < 1:
        raise ValueError(f"{name} must be greater than 0")
    return limit


# ── The registry (`P12-01`) ────────────────────────────────────────────────
#
# Settings key → (environment variable, built-in default). Eight of the ten
# `PANTHEON_*BYTES` caps in the product live here; the other two are owned by
# the modules that enforce them — `PANTHEON_BACKUP_IMPORT_MAX_BYTES` in
# `routes/backup_routes.py` and `PANTHEON_TTS_CACHE_MAX_BYTES` in
# `services/tts/tts_service.py` — and resolve through the same
# `settings.resolve_limit`. Re-measured 2026-09-18: ten distinct
# `PANTHEON_*BYTES` environment names across non-test Python, in three files.
#
# The settings key is the variable minus `PANTHEON_`, lowercased, and that is
# load-bearing twice: an operator who knows the variable can find the setting
# (`Law 15`), and `.pantheon/check-env-declared.py` matches the two by exactly
# that stem when it checks whether an env layer is reachable.
BYTE_LIMITS: dict[str, tuple[str, int]] = {
    "gallery_upload_max_bytes": ("PANTHEON_GALLERY_UPLOAD_MAX_BYTES", 100 * 1024 * 1024),
    "gallery_transform_upload_max_bytes": ("PANTHEON_GALLERY_TRANSFORM_UPLOAD_MAX_BYTES", 25 * 1024 * 1024),
    "memory_import_max_bytes": ("PANTHEON_MEMORY_IMPORT_MAX_BYTES", 10 * 1024 * 1024),
    "personal_upload_max_bytes": ("PANTHEON_PERSONAL_UPLOAD_MAX_BYTES", 25 * 1024 * 1024),
    "email_compose_upload_max_bytes": ("PANTHEON_EMAIL_COMPOSE_UPLOAD_MAX_BYTES", 25 * 1024 * 1024),
    "stt_max_audio_bytes": ("PANTHEON_STT_MAX_AUDIO_BYTES", 25 * 1024 * 1024),
    "ics_max_bytes": ("PANTHEON_ICS_MAX_BYTES", 10 * 1024 * 1024),
    "chat_upload_max_bytes": (CHAT_UPLOAD_MAX_BYTES_ENV, DEFAULT_CHAT_UPLOAD_MAX_BYTES),
}

# A byte cap is not a rate: there is no sane upper bound to clamp to, because
# "how big a file may this install accept" is a property of the operator's disk
# and their patience. The floor is 1 — a cap of zero would reject every upload
# while reading as a configured limit rather than as a closed door.
_BYTE_LIMIT_MIN = 1


def resolve_byte_cap(key: str, env_name: str, default: int,
                     owner: str | None = None) -> tuple[int, str]:
    """`(bytes, source)` for one byte cap, resolved now.

    `source` is `"role profile"`, `"instance setting"`, the environment
    variable's name, or `"built-in default"` — the vocabulary
    `settings.resolve_limit` and `task_scheduler.resolve_task_concurrency_cap`
    already use.

    Takes `env_name` and `default` rather than looking them up, so the two caps
    that do not live in `BYTE_LIMITS` — the backup import cap in
    `routes/backup_routes.py` and the TTS cache cap in
    `services/tts/tts_service.py` — resolve through this same function instead
    of growing a second copy of the rule beside their own number (`Law 13`).

    The environment leg is deliberately read through `read_byte_limit_env`
    rather than the generic coercion: a non-integer or non-positive value
    **raises**, which is the contract every one of these caps has had since
    #3364 and which `tests/test_chat_upload_limit_config.py` pins. In practice
    a bad value never reaches a request — the constants below evaluate the same
    variables at import, so the process dies at boot — and keeping the two legs
    identical is what stops that from quietly ceasing to be true.
    """
    from src.settings import resolve_limit
    value, source = resolve_limit(
        key, default, env_name=None, owner=owner, minimum=_BYTE_LIMIT_MIN,
        label=env_name,
    )
    if source != "built-in default":
        return value, source
    raw = os.getenv(env_name)
    if raw is not None and raw.strip():
        return read_byte_limit_env(env_name, default), env_name
    return default, "built-in default"


def resolve_byte_limit_with_source(key: str, owner: str | None = None) -> tuple[int, str]:
    """`resolve_byte_cap` for a key in this module's own registry."""
    env_name, default = BYTE_LIMITS[key]
    return resolve_byte_cap(key, env_name, default, owner)


def resolve_byte_limit(key: str, owner: str | None = None) -> int:
    """The effective cap in bytes. See `resolve_byte_cap`."""
    return resolve_byte_limit_with_source(key, owner)[0]


def get_chat_upload_max_bytes(owner: str | None = None) -> int:
    """The chat composer's per-file cap.

    One of the two caps that already re-read on every call before `P12-03`;
    it keeps doing so and now has the settings and role layers above it.
    """
    return resolve_byte_limit("chat_upload_max_bytes", owner)


# Per-route upload byte-limits, single-sourced here (issue #3364). Each is
# validated + env-overridable via read_byte_limit_env: set the matching
# PANTHEON_*_MAX_BYTES env var to an integer byte count to tune it; an invalid
# value fails fast at import rather than crashing mid-request. Defaults match
# the prior per-route values, so behavior is unchanged unless an env var is set.
#
# `P12-03`: these are the import-time SNAPSHOT and no longer the live answer.
# Route code calls `resolve_byte_limit("<key>")`, which adds the instance
# setting and role-profile layers above the environment and re-reads per
# request. These stay because `Law 1` says a working import keeps working, and
# because evaluating them here is what makes a malformed environment value stop
# the process at boot rather than at somebody's upload.
GALLERY_UPLOAD_MAX_BYTES = read_byte_limit_env(*BYTE_LIMITS["gallery_upload_max_bytes"])
GALLERY_TRANSFORM_UPLOAD_MAX_BYTES = read_byte_limit_env(*BYTE_LIMITS["gallery_transform_upload_max_bytes"])
MEMORY_IMPORT_MAX_BYTES = read_byte_limit_env(*BYTE_LIMITS["memory_import_max_bytes"])
PERSONAL_UPLOAD_MAX_BYTES = read_byte_limit_env(*BYTE_LIMITS["personal_upload_max_bytes"])
EMAIL_COMPOSE_UPLOAD_MAX_BYTES = read_byte_limit_env(*BYTE_LIMITS["email_compose_upload_max_bytes"])
STT_MAX_AUDIO_BYTES = read_byte_limit_env(*BYTE_LIMITS["stt_max_audio_bytes"])
ICS_MAX_BYTES = read_byte_limit_env(*BYTE_LIMITS["ics_max_bytes"])


async def read_upload_limited(upload: UploadFile, limit: int, label: str = "Upload") -> bytes:
    """Read an UploadFile with a hard byte cap."""
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"{label} exceeds {format_byte_limit(limit)} limit",
        )
    return data


# ── `P12-06` · the upload burst gate ─────────────────────────────────────────
#
# `routes/upload_routes.py` refuses a request when an IP has completed too many
# uploads recently. Until this row the number was `3`, written into
# `UploadHandler.__init__` and reachable only by rebuilding, and the window was
# `10.0` as a default argument on `count_recent_uploads` that nothing passed.
#
# **It is a burst limit and it was called concurrency.** Nothing in the gate
# knows how many uploads are in flight: `upload_rate_log` is appended to by
# `save_upload` when a file is accepted and no entry is ever removed when one
# finishes. The number it reads is "uploads completed in the last N seconds".
# The 429 said "Maximum concurrent uploads (3) exceeded", which sends an
# operator looking for three simultaneous uploads that do not exist (`Law 10`).
#
# The row allowed either fix. Renaming it is the one that ships, because
# turning a 3-per-10s burst limit into a 3-in-flight concurrency limit would
# quietly **relax** a live control — a browser uploading three files serially
# inside a second trips the first and not the second — on the exact path that
# produced issue #1346. `P12-05b` owns the throttle values; this is one of
# them, and it now resolves the same way every other limit in `P12` will.
DEFAULT_UPLOAD_BURST_LIMIT = 3
DEFAULT_UPLOAD_BURST_WINDOW_SECONDS = 10

UPLOAD_BURST_LIMIT_SETTING = "upload_burst_limit"
UPLOAD_BURST_WINDOW_SETTING = "upload_burst_window_seconds"
UPLOAD_BURST_LIMIT_ENV = "PANTHEON_UPLOAD_BURST_LIMIT"
UPLOAD_BURST_WINDOW_ENV = "PANTHEON_UPLOAD_BURST_WINDOW_SECONDS"

# Bounds, held here so `POST /api/auth/settings` clamps to the same numbers the
# resolver does — the stored value and the effective value are then the same
# number, which is the rule `otlp_interval_seconds` and `skill_audit_hour`
# already state in that route.
MIN_UPLOAD_BURST_LIMIT = 1
MAX_UPLOAD_BURST_LIMIT = 10_000
MIN_UPLOAD_BURST_WINDOW_SECONDS = 1
MAX_UPLOAD_BURST_WINDOW_SECONDS = 3600


# ── Files per request (`P12-02`) ───────────────────────────────────────────
#
# The "files per request" the row names. It was `MAX_FILES_PER_REQUEST = 25` in
# `src/upload_handler.py` — a constant the route closed over, so an operator who
# wanted one team to attach forty files had the same non-move every other limit
# in this phase had. The name there survives and is this number (`Law 1`,
# `Law 7`): an alias, not a second copy.
#
# The window `tests/test_upload_multifile.py` pins is unchanged and still binds
# the BUILT-IN DEFAULT — at or above the browser's `MAX_FILES`, at or below
# `upload_rate_limit`, or a legitimate full batch 400s at one end and 429s
# part-written at the other. An operator raising the setting past
# `upload_rate_limit` gets the second failure, which is why the two are shown
# together on the admin surface `P12-07` owes.
#
# SETTINGS-ONLY, the reasoning `P12-05b` gives for the throttles: no
# `PANTHEON_*` variable existed, so `Law 1` requires none and a new one would be
# a new place the same number can be set (`Law 13`).
DEFAULT_MAX_FILES_PER_REQUEST = 25
MAX_FILES_PER_REQUEST_SETTING = "upload_max_files_per_request"
MIN_MAX_FILES_PER_REQUEST = 1
# starlette's own form parser stops at 1000 files; above that this number is
# describing a request the server will never finish parsing.
MAX_MAX_FILES_PER_REQUEST = 1000


def resolve_max_files_per_request(owner=None, *, fallback: int | None = None):
    """How many files one `POST /api/upload` may carry, resolved now.

    `fallback` is the caller's own constant, honoured so a route holding a
    number chosen in code keeps it — the same shape `resolve_upload_burst_limit`
    uses, and what keeps `MAX_FILES_PER_REQUEST` the bottom layer rather than a
    number this function replaced.
    """
    from src.limit_policy import resolve_int_limit

    return resolve_int_limit(
        MAX_FILES_PER_REQUEST_SETTING,
        default=(DEFAULT_MAX_FILES_PER_REQUEST if fallback is None else fallback),
        env_name=None,
        owner=owner,
        minimum=MIN_MAX_FILES_PER_REQUEST,
        maximum=MAX_MAX_FILES_PER_REQUEST,
    )


def resolve_upload_burst_limit(owner=None, *, fallback: int | None = None):
    """How many recent uploads one client may have before the gate refuses.

    `fallback` is the handler's own attribute, which is the built-in default on
    every real install and is honoured so a caller holding a handler configured
    in code keeps that number. Resolved per request, so a settings change takes
    effect without a restart (`P12-03`).
    """
    from src.limit_policy import resolve_int_limit

    return resolve_int_limit(
        UPLOAD_BURST_LIMIT_SETTING,
        default=DEFAULT_UPLOAD_BURST_LIMIT if fallback is None else fallback,
        env_name=UPLOAD_BURST_LIMIT_ENV,
        owner=owner,
        minimum=MIN_UPLOAD_BURST_LIMIT,
        maximum=MAX_UPLOAD_BURST_LIMIT,
    )


def resolve_upload_burst_window_seconds(owner=None, *, fallback: int | None = None):
    """How far back the gate looks. The number that was never "concurrent"."""
    from src.limit_policy import resolve_int_limit

    return resolve_int_limit(
        UPLOAD_BURST_WINDOW_SETTING,
        default=(
            DEFAULT_UPLOAD_BURST_WINDOW_SECONDS if fallback is None else fallback
        ),
        env_name=UPLOAD_BURST_WINDOW_ENV,
        owner=owner,
        minimum=MIN_UPLOAD_BURST_WINDOW_SECONDS,
        maximum=MAX_UPLOAD_BURST_WINDOW_SECONDS,
    )
