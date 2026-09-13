# SPDX-License-Identifier: AGPL-3.0-or-later
"""One answer to *how does this mailbox prove who it is*.

`P18-02` and `P18-03`, which turned out to be the same row twice.

**THE DEFECT THAT OPENED THIS HAS A MEASURABLE CONSEQUENCE.** *Can this account
send mail* was written by hand in three places:

    routes/email_routes.py:1334   host and user and (password or oauth_provider)
    routes/note/note_routes.py    host and user and (password or oauth_provider)
    mcp_servers/email_server.py   host and user and  password

Two agree. The third omits OAuth, and it is the one the agent's own email tools
run. So a mailbox linked with the Connect button worked in the web app, worked
from notes, and told the agent *"has no SMTP configured"* — the feature working
everywhere except the place a person would most reasonably try it. Nothing
failed loudly; the account was simply invisible to one of three callers.

`P18-03` names the same disease in the other direction: the SASL XOAUTH2
exchange is spelled four times, and adding the MCP server's IMAP and SMTP paths
would have made six. Six copies of an authentication step is six places for the
next protocol detail to be applied five times.

**SO THIS MODULE IS WHERE BOTH QUESTIONS ARE ANSWERED, AND IT LIVES IN `src/`
DELIBERATELY.** `routes/` and `mcp_servers/` both import from `src/` and neither
imports from the other; putting it in `routes/email_helpers.py` — where most of
this code was — would have meant the MCP server importing a request handler's
module to log in to IMAP. The old names in `email_helpers` still work and now
delegate here, because ten test files and three modules import them and `Law 1`
says we add rather than subtract.

**WHAT IS DELIBERATELY NOT HERE.** Transport — ports, STARTTLS, SSL contexts —
stays with each caller. The two are genuinely different decisions: the
test-connection route builds a connection from unsaved form values and has to
refuse a Google account on the wrong port *before* connecting, while the MCP
server opens a connection from a stored row. Folding transport in would have
forced one shape on both and made the refusals harder to read, not easier.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from src import providers

logger = logging.getLogger(__name__)

class _MailProviderIds:
    """The set of providers a mailbox can be linked to, read from the registry.

    `P18-05`. This was `frozenset({"google"})` — a literal, which is what the
    row exists to remove. It is a live view rather than a snapshot taken at
    import because the registry is a plain dict that tests insert into: a
    frozenset built once would answer for the registry as it was, not as it is,
    and the whole claim of this row is that **adding a provider is data**. Kept
    under its original name and behaving like a set, because `Law 1` says a
    working name does not get taken away to make a refactor tidier.
    """

    __slots__ = ()

    def __contains__(self, value) -> bool:
        return value in providers.mail_provider_ids()

    def __iter__(self):
        return iter(providers.mail_provider_ids())

    def __len__(self) -> int:
        return len(providers.mail_provider_ids())

    def __eq__(self, other) -> bool:
        return set(providers.mail_provider_ids()) == set(other)

    def __hash__(self):
        return hash(providers.mail_provider_ids())

    def __repr__(self) -> str:
        return f"OAUTH_PROVIDERS({set(providers.mail_provider_ids())!r})"


OAUTH_PROVIDERS = _MailProviderIds()

# Refresh this far before the stated expiry. A token that expires mid-handshake
# fails as an authentication error, which reads like a wrong password and sends
# the operator to re-enter credentials that were never the problem.
TOKEN_SKEW_SECONDS = 60

# Kept as a name because it is one; the value now comes from the record so
# there is one place the endpoint is written down (`Law 13`).
GOOGLE_TOKEN_ENDPOINT = providers.token_url(providers.get("google"))

RECONNECT_HINT = (
    "Google OAuth token unavailable — reconnect the account in "
    "Settings → Integrations"
)


class MailAuthUnavailable(RuntimeError):
    """The account says it is linked and no usable token can be produced.

    Its own type because the caller's recovery differs from every other
    authentication failure: a wrong password is fixed by typing a new one, and
    this is fixed by pressing Connect again. A bare `RuntimeError` made those
    indistinguishable at the call site.
    """


def provider_of(cfg: dict) -> str:
    """The OAuth provider for this account, or `""` for password auth."""
    provider = str((cfg or {}).get("oauth_provider") or "").strip().lower()
    return provider if provider in OAUTH_PROVIDERS else ""


def is_oauth(cfg: dict) -> bool:
    return bool(provider_of(cfg))


# ── The SASL exchange, spelled once ────────────────────────────────────────


def xoauth2_raw(user: str, access_token: str) -> str:
    """The SASL XOAUTH2 initial response, **unencoded**.

    Both `smtplib.SMTP.auth()` and `imaplib.IMAP4.authenticate()` base64-encode
    whatever their callback returns, so callers hand back this raw form. Passing
    something already encoded double-encodes it, and the server's rejection says
    only *invalid credentials*.
    """
    return f"user={user}\x01auth=Bearer {access_token}\x01\x01"


def xoauth2_bytes(user: str, access_token: str) -> bytes:
    """Raw XOAUTH2 bytes, for `imaplib`'s callback, which wants bytes."""
    return xoauth2_raw(user, access_token).encode()


# ── Tokens ─────────────────────────────────────────────────────────────────


def refresh_oauth_token(provider_id: str, account_id: str) -> Optional[str]:
    """Exchange the stored refresh token for a new access token and persist it.

    `P18-05`. One function for every provider, because the exchange is RFC 6749
    section 6 and the only things that differ are the endpoint and the client
    credentials — both of which are fields on the record.

    **Microsoft rotates its refresh token and Google does not.** The response
    is checked for a new one and it is persisted when present. The old
    Google-only code did not look, which was correct for Google and would have
    been a mailbox that stops working after the old refresh token expires for
    anybody who copied it.
    """
    import httpx

    from core.database import EmailAccount as _EA, SessionLocal as _SL
    from src.secret_storage import decrypt as _dec, encrypt as _enc

    provider = providers.get(provider_id)
    if provider is None or provider.auth != providers.AUTH_OAUTH2:
        return None
    if not providers.is_configured(provider):
        return None
    if not account_id:
        # No row to refresh against. Distinguished from a failed refresh
        # because the fix is different: this account was never linked.
        return None
    db = _SL()
    try:
        row = db.get(_EA, account_id)
        if not row or not row.oauth_refresh_token:
            return None
        refresh_token = _dec(row.oauth_refresh_token or "")
        if not refresh_token:
            return None
        form = {
            "client_id": providers.client_id(provider),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        secret = providers.client_secret(provider)
        if secret:
            form["client_secret"] = secret
        resp = httpx.post(providers.token_url(provider), data=form, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        access_token = data["access_token"]
        row.oauth_access_token = _enc(access_token)
        row.oauth_token_expiry = str(int(time.time()) + data.get("expires_in", 3600))
        rotated = data.get("refresh_token") or ""
        if rotated and rotated != refresh_token:
            row.oauth_refresh_token = _enc(rotated)
        db.commit()
        return access_token
    except Exception:
        # Deliberately not re-raised: every caller's next move is the same —
        # report that the account needs reconnecting — and the account id is
        # the only detail worth keeping. The token never enters the log.
        logger.warning(
            "%s token refresh failed for account %s", provider.label, account_id
        )
        return None
    finally:
        db.close()


def refresh_google_token(account_id: str) -> Optional[str]:
    """Google's refresh, kept as a name rather than as an implementation.

    `routes/email_helpers._refresh_google_token` re-exports this and three
    tests patch `src.mail_auth.refresh_google_token` directly, so the name is
    load-bearing and `Law 1` says it stays. The behaviour underneath is the
    generic one — which is the point of the row.
    """
    return refresh_oauth_token("google", account_id)


# Provider -> a refresher that is *not* the generic one. Empty but for Google,
# and Google's entry exists only to keep the patchable name above in the path;
# every other provider, including one inserted into the registry at runtime,
# goes straight to `refresh_oauth_token`. An override table rather than a
# branch on the id, so the generic path is the default rather than the
# fallback.
# The lambda is not decoration: a table holding the function *object* freezes
# the binding at import, so replacing `refresh_google_token` — in a test, or to
# intercept it — rebinds the module global and leaves the table pointing at the
# original. Resolving the name inside the call makes the table late-bound,
# which is what a lookup table of behaviour should be.
_REFRESH_OVERRIDES = {"google": lambda account_id: refresh_google_token(account_id)}

# The old name, unchanged in meaning for the one entry it ever had.
_REFRESHERS = _REFRESH_OVERRIDES


def access_token_for(cfg: dict) -> Optional[str]:
    """A usable access token for this account, refreshing when it has to."""
    from src.secret_storage import decrypt as _dec

    access_token = _dec((cfg or {}).get("oauth_access_token") or "")
    expiry = str((cfg or {}).get("oauth_token_expiry") or "")
    if access_token and expiry:
        try:
            if int(expiry) - TOKEN_SKEW_SECONDS > time.time():
                return access_token
        except (ValueError, TypeError):
            # A malformed expiry is treated as expired rather than as absent:
            # a stored token whose expiry cannot be read might be valid, and
            # refreshing costs one request while using a dead one costs a
            # failed send the person has to interpret.
            pass
    provider_id = provider_of(cfg)
    if not provider_id:
        return None
    account_id = str((cfg or {}).get("account_id") or "")
    override = _REFRESH_OVERRIDES.get(provider_id)
    if override is not None:
        return override(account_id)
    return refresh_oauth_token(provider_id, account_id)


def require_token(cfg: dict) -> str:
    token = access_token_for(cfg)
    if not token:
        raise MailAuthUnavailable(RECONNECT_HINT)
    return token


# ── The question three modules were answering differently ──────────────────


def can_send(cfg: dict) -> bool:
    """Whether this account has enough to authenticate an SMTP send.

    **The OAuth clause is the whole point of this function existing.** Without
    it a linked Google mailbox reports as having no SMTP configured, which is
    what `mcp_servers/email_server.py` did while the web app said otherwise.
    """
    cfg = cfg or {}
    if not cfg.get("smtp_host") or not cfg.get("smtp_user"):
        return False
    return bool(cfg.get("smtp_password") or is_oauth(cfg))


def missing_send_fields(cfg: dict) -> list:
    """The same rule as `can_send`, itemised for a message to a person.

    `routes/note/note_routes.py` needs to say *which* part is missing, and
    before this it did that by re-deriving the rule inline — the third copy.
    Same predicate, two presentations, one place.
    """
    cfg = cfg or {}
    missing = []
    if not cfg.get("smtp_host"):
        missing.append("SMTP host")
    if not cfg.get("smtp_user"):
        missing.append("SMTP user")
    if not (cfg.get("smtp_password") or is_oauth(cfg)):
        missing.append("SMTP credentials")
    return missing


# ── Authenticating a connection somebody else opened ───────────────────────


def authenticate_imap(conn, cfg: dict) -> None:
    """Log in to an already-connected `imaplib` connection.

    The connection is the caller's because transport is the caller's decision;
    only the credential exchange is shared. The caller is also responsible for
    closing the socket when this raises — a failed `AUTHENTICATE` otherwise
    orphans a connected descriptor, which is `#3174` and is why every call site
    has a `try/except` that shuts the socket down.
    """
    cfg = cfg or {}
    user = cfg.get("imap_user") or ""
    if is_oauth(cfg):
        token = require_token(cfg)
        conn.authenticate("XOAUTH2", lambda _challenge: xoauth2_bytes(user, token))
        return
    conn.login(user, cfg.get("imap_password") or "")


def authenticate_smtp(smtp, cfg: dict) -> None:
    """Authenticate an already-connected, already-secured `smtplib` connection.

    **A password-less non-OAuth account is left unauthenticated on purpose**,
    matching what every call site did before this existed: a local relay or a
    Proton Mail Bridge genuinely takes no credentials, and refusing here would
    break a working setup (`Law 1`).
    """
    cfg = cfg or {}
    user = cfg.get("smtp_user") or ""
    password = cfg.get("smtp_password") or ""
    if is_oauth(cfg):
        token = require_token(cfg)
        # EHLO first: the server advertises XOAUTH2 in its capabilities, and
        # `smtplib.auth` consults that list. Skipping it fails with
        # "SMTP AUTH extension not supported" on a server that supports it.
        smtp.ehlo()
        smtp.auth(
            "XOAUTH2",
            lambda challenge=None: xoauth2_raw(user, token),
            initial_response_ok=True,
        )
        return
    if user and password:
        smtp.login(user, password)
