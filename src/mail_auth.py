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

logger = logging.getLogger(__name__)

# Providers that authenticate with a bearer token rather than a password. A
# frozenset rather than `== "google"` scattered about, so the second provider
# (`P18-05`) is an entry here and not another sweep.
OAUTH_PROVIDERS = frozenset({"google"})

# Refresh this far before the stated expiry. A token that expires mid-handshake
# fails as an authentication error, which reads like a wrong password and sends
# the operator to re-enter credentials that were never the problem.
TOKEN_SKEW_SECONDS = 60

GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

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


def refresh_google_token(account_id: str) -> Optional[str]:
    """Exchange the stored refresh token for a new access token and persist it."""
    import httpx

    from core.database import EmailAccount as _EA, SessionLocal as _SL
    from src.secret_storage import decrypt as _dec, encrypt as _enc

    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
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
        resp = httpx.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        access_token = data["access_token"]
        row.oauth_access_token = _enc(access_token)
        row.oauth_token_expiry = str(int(time.time()) + data.get("expires_in", 3600))
        db.commit()
        return access_token
    except Exception:
        # Deliberately not re-raised: every caller's next move is the same —
        # report that the account needs reconnecting — and the account id is
        # the only detail worth keeping. The token never enters the log.
        logger.warning("Google token refresh failed for account %s", account_id)
        return None
    finally:
        db.close()


# Provider -> the function that trades a refresh token for an access token.
# A table rather than a call to Google's refresher inside `access_token_for`,
# for two reasons. It makes `P18-05`'s second provider an entry instead of a
# branch; and the old shape would have run **Google's** refresh for any account
# whose provider was not Google — unreachable today only because every caller
# checks `is_oauth` first, which is a guarantee living in the callers rather
# than in the function that depends on it.
# The lambda is not decoration: a table holding the function *object* freezes
# the binding at import, so replacing `refresh_google_token` — in a test, or to
# intercept it — rebinds the module global and leaves the table pointing at the
# original. Resolving the name inside the call makes the table late-bound, which
# is what a lookup table of behaviour should be.
_REFRESHERS = {"google": lambda account_id: refresh_google_token(account_id)}


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
    refresher = _REFRESHERS.get(provider_of(cfg))
    if refresher is None:
        return None
    return refresher(str((cfg or {}).get("account_id") or ""))


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
