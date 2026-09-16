# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B04` — `P2-17`'s 413 cap on `/api/import`, its boundary, and its ORDERING.

`P2-17` put a byte ceiling on the backup-import body because
``Request.json()`` goes through ``Request.body()``, which concatenates the
whole stream into memory with no bound, and this app installs no
request-body-size middleware. It shipped with zero tests. Two things about it
can be wrong independently, and only one of them is about size:

* **the meter** — a declared Content-Length is a client-supplied hint and is
  absent on chunked bodies, so the streamed byte count has to be the real
  control, and the boundary has to sit where the code says it sits;
* **the order** — ``require_admin`` is a `FORBIDDEN.md` Part 2 control. "the
  cap runs before the auth check" and "the cap runs after it" both refuse an
  oversized body with *a* status code, and they are not the same program: the
  first reads an unauthenticated stranger's body before deciding whether to
  talk to them at all, and answers 413 where the honest answer is 403.

The ordering tests below therefore assert on **which** refusal comes back and
on whether the body was read at all, not merely that something was refused.
``require_admin`` and ``get_current_user`` are the real functions here — the
whole point is the sequence the route executes, so stubbing either one would
test the stub.

The existing backup-import tests (`tests/test_backup_import_cross_user_dedup.py`,
`tests/test_backup_import_skills*.py`) pass a request double with **no**
``stream``, which takes ``_load_import_body``'s in-process branch and never
reaches the meter. That branch is pinned here too, so it stays a deliberate
escape hatch for in-process callers rather than a hole.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import routes.backup_routes as br
from src.upload_limits import format_byte_limit, read_byte_limit_env


# Distinguishes "the test did not say" from "the test said None" for the
# auth manager, since `auth_manager=None` is itself a state require_admin reads.
_UNSET = object()


class _AuthManager:
    """The shape ``require_admin`` reads: ``is_configured`` + ``is_admin``."""

    is_configured = True

    def __init__(self, admins=()):
        self._admins = set(admins)

    def is_admin(self, user):
        return user in self._admins


class _StreamedRequest:
    """A Request double whose body arrives as an ASGI stream.

    ``started`` records whether anything ever pulled on that stream, which is
    how the ordering tests tell "refused before the body was read" from
    "refused after reading it".
    """

    def __init__(self, chunks, *, user=None, admins=(), content_length=None,
                 headers=None, auth_manager=_UNSET):
        self._chunks = list(chunks)
        self.started = False
        self.state = SimpleNamespace(current_user=user)
        mgr = _AuthManager(admins) if auth_manager is _UNSET else auth_manager
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=mgr))
        self.client = SimpleNamespace(host="127.0.0.1")
        hdrs = dict(headers or {})
        if content_length is not None:
            hdrs["content-length"] = str(content_length)
        self.headers = hdrs

    def stream(self):
        async def _gen():
            self.started = True
            for chunk in self._chunks:
                yield chunk

        return _gen()

    async def json(self):  # pragma: no cover - the streamed branch is used
        raise AssertionError("the streamed branch must not fall back to .json()")


class _InProcessRequest:
    """A Request-like double with no ASGI stream, as in-process callers pass."""

    def __init__(self, body, *, user=None, admins=()):
        self._body = body
        self.state = SimpleNamespace(current_user=user)
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=_AuthManager(admins)))
        self.client = SimpleNamespace(host="127.0.0.1")
        self.headers = {}

    async def json(self):
        return self._body


def _backup_router():
    mem = MagicMock()
    mem.load_all.return_value = []
    mem.load_all_for_update.return_value = []
    mem.load.return_value = []
    presets = MagicMock()
    presets.get_all.return_value = []
    skills = MagicMock()
    skills.load_all.return_value = []
    skills.load.return_value = []
    return br.setup_backup_routes(mem, presets, skills)


def _route(path, method):
    for route in _backup_router().routes:
        if route.path == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"{method} {path} is not registered")


def _import_endpoint():
    """The real `POST /api/import` handler off the real router."""
    return _route("/api/import", "POST")


# ── The meter ───────────────────────────────────────────────────────────────

async def test_a_body_of_exactly_the_limit_is_accepted():
    """The ceiling is inclusive: `limit` bytes parse, and that is the boundary
    a `>=` would move by one byte in the wrong direction."""
    body = b'{"a":"' + b"x" * 8 + b'"}'
    req = _StreamedRequest([body])
    assert await br._load_import_body(req, len(body)) == {"a": "x" * 8}


async def test_one_byte_over_the_limit_is_413():
    body = b'{"a":"' + b"x" * 8 + b'"}'
    req = _StreamedRequest([body])
    with pytest.raises(HTTPException) as exc:
        await br._load_import_body(req, len(body) - 1)
    assert exc.value.status_code == 413
    assert exc.value.detail == f"Import body exceeds {format_byte_limit(len(body) - 1)} limit"


async def test_the_stream_is_metered_across_chunks_not_per_chunk():
    """Sixteen one-byte chunks are sixteen bytes. A per-chunk check would let
    an unbounded body through one byte at a time."""
    req = _StreamedRequest([b"x"] * 16)
    with pytest.raises(HTTPException) as exc:
        await br._load_import_body(req, 8)
    assert exc.value.status_code == 413


async def test_a_lying_content_length_does_not_buy_an_unbounded_read():
    """Content-Length is client-supplied. A body that declares 4 bytes and
    sends 4096 is refused on the streamed count, which is the real control."""
    req = _StreamedRequest([b"x" * 4096], content_length=4)
    with pytest.raises(HTTPException) as exc:
        await br._load_import_body(req, 64)
    assert exc.value.status_code == 413


async def test_an_oversized_declaration_is_refused_before_the_body_is_read():
    """The cheap early reject: a declared length over the ceiling is answered
    without pulling a single chunk off the stream."""
    req = _StreamedRequest([b"{}"], content_length=10_000)
    with pytest.raises(HTTPException) as exc:
        await br._load_import_body(req, 64)
    assert exc.value.status_code == 413
    assert req.started is False, "the oversized declaration still read the body"


async def test_a_declaration_of_exactly_the_limit_is_not_refused():
    """The early reject is `>`, not `>=` — a body that declares exactly the
    ceiling is legal and must still be parsed."""
    body = b'{"ok":1}'
    req = _StreamedRequest([body], content_length=len(body))
    assert await br._load_import_body(req, len(body)) == {"ok": 1}


async def test_a_junk_content_length_falls_through_to_the_streamed_count():
    """`Transfer-Encoding: chunked` sends no Content-Length at all, and a
    header can be junk. Neither may disable the meter."""
    for header in ({"content-length": "not-a-number"}, {"content-length": ""}, {}):
        req = _StreamedRequest([b"x" * 200], headers=header)
        with pytest.raises(HTTPException) as exc:
            await br._load_import_body(req, 64)
        assert exc.value.status_code == 413, header


async def test_an_in_process_caller_with_no_stream_still_parses():
    """In-process callers hand the handler a double with no ASGI stream.
    There is nothing to meter, so it defers to whatever parser it offers —
    pinned so the escape hatch stays narrow and deliberate."""
    assert await br._load_import_body(_InProcessRequest({"memories": []}), 1) == {"memories": []}


# ── The order ───────────────────────────────────────────────────────────────

async def test_an_oversized_body_from_a_non_admin_gets_the_admin_refusal():
    """The ordering test. `require_admin` is a Part 2 control and runs FIRST:
    a stranger with a 10 MB body is told 403 Admin only, and their body is
    never read. Move the cap above the gate and this comes back 413 — a
    refusal that reveals the ceiling and that was computed by reading an
    unauthenticated body."""
    endpoint = _import_endpoint()
    req = _StreamedRequest([b"x" * 4096], user="mallory", admins=("root",),
                           content_length=10 * 1024 * 1024)
    with pytest.raises(HTTPException) as exc:
        await endpoint(req)
    assert exc.value.status_code == 403
    assert exc.value.detail == "Admin only"
    assert req.started is False, "an unauthenticated body was read before the gate"


async def test_an_anonymous_caller_with_an_oversized_body_gets_403_too():
    endpoint = _import_endpoint()
    req = _StreamedRequest([b"x" * 4096], user=None, admins=("root",),
                           content_length=10 * 1024 * 1024)
    with pytest.raises(HTTPException) as exc:
        await endpoint(req)
    assert exc.value.status_code == 403
    assert req.started is False


async def test_the_same_oversized_body_from_an_admin_gets_the_cap(monkeypatch):
    """Same request, admin caller: past the gate, the cap is what refuses it.
    Paired with the test above, this is the ordering — one request, two
    callers, two different refusals, in that order."""
    monkeypatch.setattr(br, "BACKUP_IMPORT_MAX_BYTES", 64)
    endpoint = _import_endpoint()
    req = _StreamedRequest([b"x" * 4096], user="root", admins=("root",))
    with pytest.raises(HTTPException) as exc:
        await endpoint(req)
    assert exc.value.status_code == 413
    assert exc.value.detail == f"Import body exceeds {format_byte_limit(64)} limit"
    assert req.started is True


async def test_the_cap_still_applies_when_the_admin_gate_short_circuits(monkeypatch):
    """`AUTH_ENABLED=0` makes `require_admin` return for everyone. That is
    exactly where the ceiling is the only thing between /api/import and an
    unbounded read, so it must not be conditional on the gate having bitten."""
    monkeypatch.setenv("AUTH_ENABLED", "0")
    monkeypatch.setattr(br, "BACKUP_IMPORT_MAX_BYTES", 64)
    endpoint = _import_endpoint()
    req = _StreamedRequest([b"x" * 4096], user=None, auth_manager=None)
    with pytest.raises(HTTPException) as exc:
        await endpoint(req)
    assert exc.value.status_code == 413
    assert req.started is True


async def test_the_413_is_not_laundered_into_invalid_json(monkeypatch):
    """The handler wraps the load in `except Exception -> 400 Invalid JSON`.
    Without the `except HTTPException: raise` above it, every 413 would come
    back as a 400 about syntax and the cap would be invisible to the caller.
    The body here is oversized AND unparseable, so only the order of the two
    handlers decides the answer."""
    monkeypatch.setattr(br, "BACKUP_IMPORT_MAX_BYTES", 64)
    endpoint = _import_endpoint()
    req = _StreamedRequest([b"not json at all " * 32], user="root", admins=("root",))
    with pytest.raises(HTTPException) as exc:
        await endpoint(req)
    assert exc.value.status_code == 413


async def test_malformed_json_under_the_cap_is_still_a_400(monkeypatch):
    """The other side of the same branch: the cap must not swallow the parse
    error it sits in front of."""
    monkeypatch.setattr(br, "BACKUP_IMPORT_MAX_BYTES", 64)
    endpoint = _import_endpoint()
    req = _StreamedRequest([b"{nope"], user="root", admins=("root",))
    with pytest.raises(HTTPException) as exc:
        await endpoint(req)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid JSON"


async def test_a_json_scalar_under_the_cap_is_rejected_as_not_an_object(monkeypatch):
    monkeypatch.setattr(br, "BACKUP_IMPORT_MAX_BYTES", 64)
    endpoint = _import_endpoint()
    req = _StreamedRequest([b"[1,2,3]"], user="root", admins=("root",))
    with pytest.raises(HTTPException) as exc:
        await endpoint(req)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Expected a JSON object"


async def test_an_admin_import_within_the_cap_goes_through(monkeypatch):
    """`Law 1`: the ceiling must not have subtracted the route. A legal
    admin import still runs and still reports what it imported."""
    monkeypatch.setattr(br, "BACKUP_IMPORT_MAX_BYTES", 4096)
    endpoint = _import_endpoint()
    req = _StreamedRequest([b'{"memories":[{"text":"buy milk"}]}'],
                           user="root", admins=("root",))
    result = await endpoint(req)
    assert result["ok"] is True
    assert result["imported"] == ["1 memories"], result


# ── The ceiling itself ──────────────────────────────────────────────────────

def test_the_ceiling_is_env_overridable_through_the_house_helper(monkeypatch):
    """Not a raw `int(os.getenv(...))`: an unparseable or sub-1 value fails
    fast rather than producing a ceiling of 0 (refuse everything) or a
    ValueError mid-request."""
    monkeypatch.setenv("PANTHEON_BACKUP_IMPORT_MAX_BYTES", "1048576")
    assert read_byte_limit_env("PANTHEON_BACKUP_IMPORT_MAX_BYTES", 25 * 1024 * 1024) == 1048576

    monkeypatch.setenv("PANTHEON_BACKUP_IMPORT_MAX_BYTES", "twenty")
    with pytest.raises(ValueError):
        read_byte_limit_env("PANTHEON_BACKUP_IMPORT_MAX_BYTES", 25 * 1024 * 1024)

    monkeypatch.setenv("PANTHEON_BACKUP_IMPORT_MAX_BYTES", "0")
    with pytest.raises(ValueError):
        read_byte_limit_env("PANTHEON_BACKUP_IMPORT_MAX_BYTES", 25 * 1024 * 1024)

    monkeypatch.delenv("PANTHEON_BACKUP_IMPORT_MAX_BYTES", raising=False)
    assert read_byte_limit_env("PANTHEON_BACKUP_IMPORT_MAX_BYTES", 77) == 77


def test_the_shipped_default_is_above_the_memory_import_ceiling():
    """A backup is a strict superset of a memory import — it carries presets,
    skills, settings and preferences too — so a ceiling at or below the memory
    one would refuse backups the product itself produces."""
    from src.upload_limits import MEMORY_IMPORT_MAX_BYTES

    assert br.BACKUP_IMPORT_MAX_BYTES == 25 * 1024 * 1024
    assert br.BACKUP_IMPORT_MAX_BYTES > MEMORY_IMPORT_MAX_BYTES


# ── The gate's other route ──────────────────────────────────────────────────

async def test_export_is_behind_the_same_admin_gate():
    """`GET /api/export` hands back every memory, preset, skill and setting in
    one file. It is the same `require_admin` call, one route above the one
    `P2-17` touched, and it had no test either — a mutation that deleted its
    gate survived the first pass of this file's mutation run, which is how it
    came to be written down."""
    endpoint = _route("/api/export", "GET")
    req = _StreamedRequest([], user="mallory", admins=("root",))
    with pytest.raises(HTTPException) as exc:
        await endpoint(req)
    assert exc.value.status_code == 403
    assert exc.value.detail == "Admin only"


async def test_an_admin_gets_past_the_export_gate(monkeypatch):
    """The refusal above is not vacuous: the same call from an admin returns
    the export rather than a 403."""
    monkeypatch.setattr(br, "load_settings", lambda: {})
    monkeypatch.setattr(br, "load_features", lambda: {})
    monkeypatch.setattr("routes.prefs_routes._load_for_user", lambda user: {})
    endpoint = _route("/api/export", "GET")
    response = await endpoint(_StreamedRequest([], user="root", admins=("root",)))
    assert response.status_code == 200
    assert b'"exported_by": "root"' in response.body
