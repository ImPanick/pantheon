# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P27-03` · Each person's private vault, over HTTP.

    GET    /api/vault/mine                     my items (never a password), locked?, idle time
    POST   /api/vault/mine/items               add one {kind, label, addresses, username,
                                               secret, totp?, notes?, use?, agent_account?}
    PUT    /api/vault/mine/items/{id}          change it (a field left out is kept; "" clears)
    DELETE /api/vault/mine/items/{id}          remove it
    POST   /api/vault/mine/items/{id}/reveal   {password} → its values, for the person's own eyes
    PUT    /api/vault/mine/lock                {idle_minutes?} | {locked: true} | {locked: false, password}
    POST   /api/vault/mine/items/{id}/agent-account
                                               {template, role, username, label?} — `P27-05`: from
                                               this admin login, make an account for the agent on
                                               the service and keep it here (`src/agent_accounts.py`)
    POST   /api/vault/mine/items/{id}/test     `P27-04`: from the workstation — does each address's
                                               name resolve, does it answer, which certificate it shows
    POST   /api/vault/mine/items/{id}/pin      {origin, sha256} trust the certificate the person
                                               confirmed, or {origin, remove: true}
    POST   /api/vault/mine/import              `P27-10`: {text, passphrase?} a Bitwarden/Vaultwarden
                                               JSON or CSV export, or a Pantheon export and its
                                               passphrase; or {source: "server-bitwarden"}, an
                                               admin's — into the caller's own vault, nobody else's
    POST   /api/vault/mine/export              `P27-10`: {passphrase, password} → the caller's own
                                               items, sealed with the passphrase (`src/vault_transfer.py`)

`/api/vault/…` without `mine` is the server's Bitwarden link (`routes/vault/`),
an admin's; this is everyone's own and no route here reaches another person's.
**Only a person** writes, reveals or unlocks (`request_is_a_person`): an API
token or the assistant's loopback choosing which logins exist would be a
credential choosing its own reach. Reveal and unlock ask for the person's
password again — a session left open on a shared screen is not enough to read
a password out of it.

Every refusal is `{detail: "<sentence>"}` (`Law 15`). The route ceiling
(`check-unreachable.py`): each path is spelled in `static/js/vaultSettings.js`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.database import SessionLocal
from src.auth_helpers import get_current_user, request_is_a_person

BODY_MAX_BYTES = 64 * 1024
# `P27-10`: an export file is read whole, so its door takes more.
IMPORT_MAX_BYTES = 17 * 1024 * 1024
ONLY_A_PERSON = ("Only a person signed in to Pantheon can change, reveal or unlock their vault — "
                 "not an API token or the assistant.")
WRONG_PASSWORD = "That is not your Pantheon password. Nothing was shown."


def _refused(sentence: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": sentence}, status_code=status)


async def _body(request: Request, limit: int = BODY_MAX_BYTES) -> Dict[str, Any]:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > limit:
            raise ValueError(f"The request is larger than {limit // 1024} KiB, so it was not read.")
    if not bytes(raw).strip():
        return {}
    try:
        body = json.loads(bytes(raw))
    except (TypeError, ValueError):
        raise ValueError("The request body must be JSON.") from None
    if not isinstance(body, dict):
        raise ValueError("The request body must be a JSON object.")
    return body


async def _password_ok(request: Request, user, password: Any) -> bool:
    """The person's own password, checked again. An install with no sign-in
    has no password to ask for: whoever reaches it is its one person."""
    mgr = getattr(request.app.state, "auth_manager", None)
    if mgr is None or not getattr(mgr, "is_configured", False) or not user:
        return True
    if not isinstance(password, str) or not password:
        return False
    return bool(await asyncio.to_thread(mgr.verify_password, user, password))


def _server_bitwarden_for(user) -> bool:
    """`P27-10`: whether *From the server's Bitwarden* is offered — the
    caller may use the server's vault tools and an admin set the link up."""
    from src.tool_security import blocked_tools_for_owner
    if "vault_get" in blocked_tools_for_owner(user):
        return False
    from src.tools.vault import _load_vault_config
    return bool(_load_vault_config().get("session"))


def setup_vault_mine_routes() -> APIRouter:
    router = APIRouter(prefix="/api/vault/mine", tags=["vault"])

    def _run(fn):
        from src import vault as V
        db = SessionLocal()
        try:
            return fn(V, db)
        except V.VaultRefused as r:
            db.rollback()
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    @router.get("")
    def my_vault(request: Request):
        user = get_current_user(request)

        def go(V, db):
            from src.agent_accounts import templates_public
            return {**V.listing(db, user), "services": templates_public(),
                    "server_bitwarden": _server_bitwarden_for(user)}
        return _run(go)

    @router.post("/import")
    async def import_items(request: Request):
        """`P27-10`. Into the caller's own vault: the account is the caller's,
        never a field of the file."""
        from src import vault_transfer as T
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request, IMPORT_MAX_BYTES)
        except ValueError as e:
            return _refused(str(e), 413 if "KiB" in str(e) else 400)
        user = get_current_user(request)
        try:
            if body.get("source") == "server-bitwarden":
                items = await T.server_bitwarden_items(user)
            else:
                # scrypt for a Pantheon export is a second of work: off the loop (`B1223`).
                items = await asyncio.to_thread(T.read_file, body.get("text"), body.get("passphrase"))
        except T.TransferRefused as r:
            return _refused(r.sentence, r.status)
        return await asyncio.to_thread(_run, lambda V, db: T.bring_in(db, user, items))

    @router.post("/export")
    async def export_items(request: Request):
        """`P27-10`. Every secret in the vault, so the person's password is
        asked again, as for *Reveal*; sealed with a passphrase they type."""
        from src import vault_transfer as T
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e))
        user = get_current_user(request)
        if not await _password_ok(request, user, body.get("password")):
            return _refused("That is not your Pantheon password. Nothing was exported.", 403)
        got = await asyncio.to_thread(_run, lambda V, db: T.export(db, user, body.get("passphrase")))
        if isinstance(got, JSONResponse):
            return got
        return JSONResponse(got, headers={
            "Content-Disposition": f'attachment; filename="pantheon-vault-{got["made"]}.json"',
            "Cache-Control": "no-store"})

    @router.post("/items/{item_id}/test")
    async def test_item(item_id: str, request: Request):
        """`P27-04`. What the person reads before mapping a name or pinning a
        certificate. Reaches the login's addresses, so a person's only."""
        from src import vault_names
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        user = get_current_user(request)
        from src import vault as V
        db = SessionLocal()
        try:
            return await vault_names.test(db, user, item_id)
        except V.VaultRefused as r:
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    @router.post("/items/{item_id}/pin")
    async def pin_item(item_id: str, request: Request):
        """`P27-04`. Trust exactly the certificate the person confirmed."""
        from src import vault_names
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e))
        user = get_current_user(request)
        from src import vault as V
        db = SessionLocal()
        try:
            if body.get("remove"):
                return vault_names.unpin(db, user, item_id, str(body.get("origin") or ""))
            return await vault_names.pin(db, user, item_id, str(body.get("origin") or ""),
                                         str(body.get("sha256") or ""))
        except V.VaultRefused as r:
            db.rollback()
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    @router.post("/items/{item_id}/agent-account")
    async def agent_account(item_id: str, request: Request):
        """`P27-05`. The person's press is the yes: nothing is made without it."""
        from src import agent_accounts as A
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e))
        user = get_current_user(request)
        from src import vault as V
        db = SessionLocal()
        try:
            return await A.set_up(db, user, item_id, body)
        except (A.AccountRefused, V.VaultRefused) as r:
            db.rollback()
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    @router.post("/items")
    async def add_item(request: Request):
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e), 413 if "64 KiB" in str(e) else 400)
        user = get_current_user(request)
        return _run(lambda V, db: V.create(db, user, body))

    @router.put("/items/{item_id}")
    async def change_item(item_id: str, request: Request):
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e), 413 if "64 KiB" in str(e) else 400)
        user = get_current_user(request)
        return _run(lambda V, db: V.update(db, user, item_id, body))

    @router.delete("/items/{item_id}")
    def remove_item(item_id: str, request: Request):
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        user = get_current_user(request)

        def go(V, db):
            V.remove(db, user, item_id)
            return {"ok": True}
        return _run(go)

    @router.post("/items/{item_id}/reveal")
    async def reveal_item(item_id: str, request: Request):
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e))
        user = get_current_user(request)
        if not await _password_ok(request, user, body.get("password")):
            return _refused(WRONG_PASSWORD, 403)
        return _run(lambda V, db: V.reveal(db, user, item_id))

    @router.put("/lock")
    async def change_lock(request: Request):
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e))
        user = get_current_user(request)
        if body.get("locked") is False and not await _password_ok(request, user, body.get("password")):
            return _refused("That is not your Pantheon password. The vault stays locked.", 403)

        def go(V, db):
            if "idle_minutes" in body:
                V.set_idle(db, user, body.get("idle_minutes"))
            if body.get("locked") is True:
                V.lock_now(user)
            elif body.get("locked") is False:
                V.unlock(db, user)
            return V.listing(db, user)
        return _run(go)

    return router


__all__ = ["setup_vault_mine_routes"]
