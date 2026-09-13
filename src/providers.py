# SPDX-License-Identifier: AGPL-3.0-or-later
"""One record type for *a thing you sign in to* — a mailbox or a service.

`P18-05`. The row was filed about mail providers and the owner's answer
(`D-2026-09-12-01`) widened it: *"Google, GitHub, Slack, etc… Possibly even
Anthropic/Claude with OpenAI/Codex/ChatGPT"*, which is mostly not mailboxes.
That is the row being too narrow, not the answer being off. **The difference
between a mailbox and a service is which fields a provider populates, not which
flow it runs**, so there is one record type and `mail` is an optional field on
it.

**WHAT WAS HERE BEFORE.** Google was the only provider and it was spelled as a
literal in nineteen places: `oauth_provider == "google"` eight times in
`routes/email_routes.py` alone, plus `_GOOGLE_OAUTH_IMAP_HOST`,
`_google_oauth_imap_transport_allowed`, `_google_oauth_smtp_transport_allowed`,
`_google_redirect_uri`, `_google_oauth_configured`, a hand-built authorize URL,
a hand-built token exchange, a hand-built userinfo fetch, and a
`_REFRESHERS = {"google": ...}` table. Adding Microsoft to that meant writing a
second one of each, and GitHub after it a third. `Law 13` names that defect
class by the count: a rule that lives in N places is wrong in N-1 of them the
first time somebody edits one.

**THE PROOF THAT THIS IS DATA AND NOT A FLOW** is not a grep (`Law 20`). It is
`tests/test_a_provider_is_a_record.py`, which invents a provider that does not
exist, inserts the record at runtime, and drives the *whole* path — the
`/oauth/providers` list, the authorize redirect, the transport guards, the
refresh table — with no edit to any module. If a branch anywhere still asks
*which provider is this* by name, that test fails.

**THREE THINGS THE SECOND PROVIDER TAUGHT THE RECORD**, each of which would
have become a second flow under the old shape:

1. **Microsoft has two SMTP hosts.** `smtp.office365.com` for Microsoft 365 and
   `smtp-mail.outlook.com` for personal Outlook.com, against the same IMAP host.
   A record with one `smtp_host` string cannot express the pair, so the guard
   holds tuples.
2. **Microsoft's verified identity does not come from a userinfo endpoint.**
   `https://graph.microsoft.com/v1.0/me` needs the Graph scope `User.Read`, and
   Entra will not issue one token for Graph *and* `https://outlook.office.com/…`
   resource scopes — they are different resources. So the address is read from
   the `id_token` that `openid email profile` returns alongside them. Google
   reads it from a userinfo call. `identity_source` is that difference, and the
   ownership check in the callback — which is a security control, not a
   convenience — reads whichever one the record names.
3. **The same vendor is sometimes two records.** OpenAI ships an API key for
   `api.openai.com` and a PKCE OAuth for a ChatGPT subscription, and this repo
   already speaks both (`src/chatgpt_subscription.py`). They are two entries
   because what you sign in to is the *service*, not the company.

**AND ONE THING WORTH SAYING PLAINLY RATHER THAN PAPERING OVER.** Anthropic and
OpenAI have no consumer OAuth for *API* access; they are API-key services. A
registry that gave them an `authorize_url` so every row looked alike would be a
lie told for symmetry. `auth` is `api_key` for those two and `is_configured`
asks a different question of them, which is the record doing its job.

Stdlib only, deliberately: `mcp_servers/` and `routes/` both import from here
through `src/mail_auth.py`, and a registry that dragged in `httpx` or the ORM
could not live below both.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import secrets
from typing import Any, Dict, NamedTuple, Optional, Tuple

# ── How a provider proves who you are ──────────────────────────────────────

AUTH_OAUTH2 = "oauth2"
AUTH_API_KEY = "api_key"
AUTH_KINDS = (AUTH_OAUTH2, AUTH_API_KEY)

# Where the verified account address comes from. Not cosmetic: the email the
# callback compares against the row's configured logins is the ownership check,
# and reading it from the wrong place means reading nothing and failing closed.
IDENTITY_USERINFO = "userinfo"
IDENTITY_ID_TOKEN = "id_token"
IDENTITY_NONE = ""


class MailTransport(NamedTuple):
    """The mailbox half of a provider record.

    Every tuple is *allowed values, default first*. The default is what gets
    written to a freshly linked account; the rest of the tuple is what the
    validator accepts from a form. One field per protocol rather than a single
    "settings" blob because the validator has to be able to refuse a shape —
    `P18-07` is the row where a default of SSL-on-587 was written by code and
    then rejected by this app's own guard.
    """

    imap_hosts: Tuple[str, ...]
    smtp_hosts: Tuple[str, ...]
    # ((port, starttls), …)
    imap_transports: Tuple[Tuple[int, bool], ...] = ((993, False),)
    # ((port, security), …) where security is "ssl" or "starttls"
    smtp_transports: Tuple[Tuple[int, str], ...] = ((587, "starttls"),)

    @property
    def imap_host(self) -> str:
        return self.imap_hosts[0]

    @property
    def smtp_host(self) -> str:
        return self.smtp_hosts[0]

    @property
    def imap_port(self) -> int:
        return self.imap_transports[0][0]

    @property
    def imap_starttls(self) -> bool:
        return self.imap_transports[0][1]

    @property
    def smtp_port(self) -> int:
        return self.smtp_transports[0][0]

    @property
    def smtp_security(self) -> str:
        return self.smtp_transports[0][1]


class Provider(NamedTuple):
    """A thing you sign in to.

    The environment variable names follow Google's existing ones —
    `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
    `GOOGLE_OAUTH_REDIRECT_URI` — so the convention generalises what already
    shipped instead of replacing it, and no deployment's `.env` has to change
    (`Law 1`).
    """

    id: str
    label: str
    auth: str = AUTH_OAUTH2

    # The variables, written out rather than composed from a prefix. A prefix
    # was the first shape and `check-env-declared.py` refused it inside the
    # hour: it reports any name declared in `.env.example` that appears nowhere
    # in the source, and a name built as `f"{prefix}_OAUTH_REDIRECT_URI"`
    # appears nowhere — so an operator could set it, believe something changed,
    # and have no way to find out otherwise. The convention is still a
    # convention; it is just spelled out, which is what makes it greppable by a
    # person and checkable by a checker.
    client_id_env: str = ""
    client_secret_env: str = ""
    redirect_uri_env: str = ""

    # OAuth 2.0
    authorize_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    scopes: Tuple[str, ...] = ()
    authorize_params: Tuple[Tuple[str, str], ...] = ()
    needs_client_secret: bool = True
    # **Load-bearing since `D-2026-09-13-01`.** This was a fact about the
    # provider with nothing reading it, recorded so that `P18-06` would be a
    # change in one place instead of a survey. It now is that one place: a
    # provider with this set gets `code_challenge` on the authorize request and
    # `code_verifier` on the exchange, and one without gets neither.
    #
    # Per-provider rather than always-on, because RFC 7636 only says a server
    # that does not understand `code_challenge` SHOULD ignore it, and *should*
    # is not a guarantee to hand an operator whose mailbox stops linking. Both
    # values below were taken from the authorization servers' own discovery
    # documents rather than from prose — see the records.
    supports_pkce: bool = False
    identity_source: str = IDENTITY_NONE
    identity_email_fields: Tuple[str, ...] = ()
    identity_name_fields: Tuple[str, ...] = ()
    # Placeholders in the URLs above, resolved from the environment:
    # ((placeholder, env var, default), …). Microsoft's `{tenant}` is the one
    # that needed it — `common`, `organizations`, `consumers` or a tenant id,
    # and an operator with a single-tenant registration must be able to say so
    # without a fork.
    url_vars: Tuple[Tuple[str, str, str], ...] = ()

    # API-key services
    key_env: str = ""

    # Optional halves
    mail: Optional[MailTransport] = None
    api_base: str = ""
    # How a call to `api_base` carries the credential, in the vocabulary
    # `src/integrations.py` already speaks — "bearer" or "header" plus a header
    # name. Present so a service record can *become* an integration preset
    # rather than being described twice (`Law 14`).
    api_auth_type: str = ""
    api_auth_header: str = ""
    # The endpoint crib the agent is given when this integration is called,
    # same shape as every other preset's `description`.
    api_hint: str = ""

    # `Law 15`. Where a person goes to create the credentials. Before `P18-04`
    # the redirect URI was discoverable only by failing the flow; the console
    # URL is the same class of missing signpost one step earlier.
    setup_url: str = ""
    setup_hint: str = ""
    note: str = ""


# ── The registry ───────────────────────────────────────────────────────────

_GOOGLE = Provider(
    id="google",
    label="Google",
    client_id_env="GOOGLE_OAUTH_CLIENT_ID",
    client_secret_env="GOOGLE_OAUTH_CLIENT_SECRET",
    redirect_uri_env="GOOGLE_OAUTH_REDIRECT_URI",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    userinfo_url="https://www.googleapis.com/oauth2/v1/userinfo",
    scopes=("https://mail.google.com/", "email"),
    # `access_type=offline` is what makes Google return a refresh token at all,
    # and `prompt=consent` is what makes it return one on a *re-*link — without
    # it a second authorisation of an already-granted app omits the refresh
    # token and the account silently stops working an hour later.
    authorize_params=(("access_type", "offline"), ("prompt", "consent")),
    needs_client_secret=True,
    # `https://accounts.google.com/.well-known/openid-configuration` advertises
    # `"code_challenge_methods_supported": ["plain", "S256"]`, against exactly
    # the two endpoints above. Google's prose documents PKCE under *native
    # apps* and never mentions it on the web-server page — which is why this
    # was checked against the discovery document instead, that being a
    # statement about the authorization server rather than about a client type.
    supports_pkce=True,
    identity_source=IDENTITY_USERINFO,
    identity_email_fields=("email",),
    identity_name_fields=("name",),
    mail=MailTransport(
        imap_hosts=("imap.gmail.com",),
        smtp_hosts=("smtp.gmail.com",),
        imap_transports=((993, False), (143, True)),
        smtp_transports=((587, "starttls"), (465, "ssl")),
    ),
    setup_url="https://console.cloud.google.com/apis/credentials",
    setup_hint=(
        "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env "
        "and restart, then this button will work."
    ),
)

_MICROSOFT = Provider(
    id="microsoft",
    label="Microsoft",
    client_id_env="MICROSOFT_OAUTH_CLIENT_ID",
    client_secret_env="MICROSOFT_OAUTH_CLIENT_SECRET",
    redirect_uri_env="MICROSOFT_OAUTH_REDIRECT_URI",
    authorize_url="https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
    token_url="https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
    # Deliberately empty: see `identity_source`. Graph and the Outlook resource
    # cannot be requested in one token, so there is no userinfo call to make.
    userinfo_url="",
    scopes=(
        "offline_access",
        "openid",
        "email",
        "profile",
        "https://outlook.office.com/IMAP.AccessAsUser.All",
        "https://outlook.office.com/SMTP.Send",
    ),
    authorize_params=(("prompt", "consent"), ("response_mode", "query")),
    needs_client_secret=True,
    # **Microsoft's discovery document does not advertise
    # `code_challenge_methods_supported` at all**, and its prose does: the
    # v2.0 authorization-code page lists `code_challenge` and
    # `code_challenge_method` as *recommended for all application types* and
    # required for single-page apps. The two sources disagree in shape rather
    # than in substance, and it is worth knowing which one this was taken from.
    supports_pkce=True,
    identity_source=IDENTITY_ID_TOKEN,
    # `email` is present when the account has one; personal Microsoft accounts
    # and some work accounts carry the address in `preferred_username`, and
    # older tenants in `upn`. Ordered, first non-empty wins.
    identity_email_fields=("email", "preferred_username", "upn"),
    identity_name_fields=("name",),
    url_vars=(("tenant", "MICROSOFT_OAUTH_TENANT", "common"),),
    mail=MailTransport(
        # One IMAP host, two SMTP hosts: `smtp.office365.com` for Microsoft 365
        # and `smtp-mail.outlook.com` for personal Outlook.com.
        imap_hosts=("outlook.office365.com",),
        smtp_hosts=("smtp.office365.com", "smtp-mail.outlook.com"),
        imap_transports=((993, False),),
        smtp_transports=((587, "starttls"),),
    ),
    setup_url="https://learn.microsoft.com/entra/identity-platform/quickstart-register-app",
    setup_hint=(
        "Register an app in Microsoft Entra ID, then set "
        "MICROSOFT_OAUTH_CLIENT_ID and MICROSOFT_OAUTH_CLIENT_SECRET in .env "
        "and restart. Grant the delegated permissions IMAP.AccessAsUser.All "
        "and SMTP.Send."
    ),
    note=(
        "Basic authentication is disabled in every Exchange Online tenant, so "
        "a mailbox password will not work here — OAuth is the only way in."
    ),
)

_GITHUB = Provider(
    id="github",
    label="GitHub",
    client_id_env="GITHUB_OAUTH_CLIENT_ID",
    client_secret_env="GITHUB_OAUTH_CLIENT_SECRET",
    redirect_uri_env="GITHUB_OAUTH_REDIRECT_URI",
    authorize_url="https://github.com/login/oauth/authorize",
    token_url="https://github.com/login/oauth/access_token",
    userinfo_url="https://api.github.com/user",
    scopes=("repo", "read:org"),
    needs_client_secret=True,
    supports_pkce=True,
    identity_source=IDENTITY_USERINFO,
    identity_email_fields=("email",),
    identity_name_fields=("name", "login"),
    api_base="https://api.github.com",
    api_auth_type="bearer",
    api_hint=(
        "GitHub REST API v3. Paste a personal access token as the key, or the "
        "token from an OAuth app. Key endpoints:\n"
        "  GET /user — the authenticated user\n"
        "  GET /user/repos — your repositories (params: sort, per_page, page)\n"
        "  GET /repos/{owner}/{repo} — repository details\n"
        "  GET /repos/{owner}/{repo}/issues — list issues (params: state, labels)\n"
        "  POST /repos/{owner}/{repo}/issues — create issue {\"title\": \"...\"}\n"
        "  GET /repos/{owner}/{repo}/pulls — list pull requests\n"
        "  GET /repos/{owner}/{repo}/commits — list commits\n"
        "  GET /search/issues?q=... — search issues and pull requests\n"
        "  GET /repos/{owner}/{repo}/contents/{path} — read a file"
    ),
    setup_url="https://github.com/settings/developers",
    setup_hint=(
        "Register an OAuth App on GitHub, then set GITHUB_OAUTH_CLIENT_ID and "
        "GITHUB_OAUTH_CLIENT_SECRET in .env and restart."
    ),
    note="No mailbox: GitHub is a service record, and the same flow drives it.",
)

_SLACK = Provider(
    id="slack",
    label="Slack",
    client_id_env="SLACK_OAUTH_CLIENT_ID",
    client_secret_env="SLACK_OAUTH_CLIENT_SECRET",
    redirect_uri_env="SLACK_OAUTH_REDIRECT_URI",
    authorize_url="https://slack.com/oauth/v2/authorize",
    token_url="https://slack.com/api/oauth.v2.access",
    userinfo_url="",
    scopes=("channels:read", "chat:write", "users:read"),
    needs_client_secret=True,
    identity_source=IDENTITY_NONE,
    api_base="https://slack.com/api",
    api_auth_type="bearer",
    api_hint=(
        "Slack Web API. Paste a bot token (`xoxb-…`) as the key. Every method "
        "is a POST or GET under this base and answers JSON with an `ok` field; "
        "`ok: false` carries an `error` string rather than an HTTP status.\n"
        "  GET /auth.test — who this token is\n"
        "  GET /conversations.list — channels (params: types, limit)\n"
        "  GET /conversations.history?channel=C… — messages in a channel\n"
        "  POST /chat.postMessage {\"channel\": \"C…\", \"text\": \"...\"}\n"
        "  GET /users.list — workspace members\n"
        "  GET /search.messages?query=… — search (user tokens only)"
    ),
    setup_url="https://api.slack.com/apps",
    setup_hint=(
        "Create a Slack app, then set SLACK_OAUTH_CLIENT_ID and "
        "SLACK_OAUTH_CLIENT_SECRET in .env and restart."
    ),
)

_ANTHROPIC = Provider(
    id="anthropic",
    label="Anthropic",
    auth=AUTH_API_KEY,
    key_env="ANTHROPIC_API_KEY",
    api_base="https://api.anthropic.com",
    # Not a bearer token: Anthropic reads the raw key from `x-api-key`, and
    # sending it as `Authorization: Bearer` fails authentication.
    api_auth_type="header",
    api_auth_header="x-api-key",
    api_hint=(
        "Anthropic Messages API. Paste an API key as the key; it is sent as "
        "`x-api-key`, not as a bearer token. Every request also needs the "
        "header `anthropic-version: 2023-06-01`.\n"
        "  POST /v1/messages {\"model\": \"...\", \"max_tokens\": N, "
        "\"messages\": [{\"role\": \"user\", \"content\": \"...\"}]}\n"
        "  GET /v1/models — models this key can use"
    ),
    setup_url="https://console.anthropic.com/settings/keys",
    setup_hint="Create an API key in the Anthropic console and paste it here.",
    note=(
        "API access is a key, not a sign-in. There is no consumer OAuth to "
        "offer, and a Connect button here would be a button that cannot work."
    ),
)

_OPENAI = Provider(
    id="openai",
    label="OpenAI",
    auth=AUTH_API_KEY,
    key_env="OPENAI_API_KEY",
    api_base="https://api.openai.com/v1",
    api_auth_type="bearer",
    api_hint=(
        "OpenAI platform API. Paste an API key as the key.\n"
        "  POST /responses {\"model\": \"...\", \"input\": \"...\"}\n"
        "  POST /chat/completions {\"model\": \"...\", \"messages\": [...]}\n"
        "  POST /embeddings {\"model\": \"...\", \"input\": \"...\"}\n"
        "  GET /models — models this key can use"
    ),
    setup_url="https://platform.openai.com/api-keys",
    setup_hint="Create an API key in the OpenAI platform console and paste it here.",
    note=(
        "The platform API is a key. A ChatGPT subscription is a different "
        "thing you sign in to, and it is the separate `openai-chatgpt` record."
    ),
)

_OPENAI_CHATGPT = Provider(
    id="openai-chatgpt",
    label="ChatGPT subscription",
    auth=AUTH_OAUTH2,
    token_url="https://auth.openai.com/oauth/token",
    needs_client_secret=False,
    supports_pkce=True,
    api_base="https://chatgpt.com/backend-api/codex",
    setup_url="https://chatgpt.com/codex",
    note=(
        "Listed so the registry is the honest inventory rather than a partial "
        "one. Its flow is a device-code grant against a fixed public client "
        "and lives in `src/chatgpt_subscription.py`; it is not driven from "
        "here and does not appear in the mailbox link list, which is what "
        "`mail is None` and the absent `authorize_url` say."
    ),
)

PROVIDERS: Dict[str, Provider] = {
    p.id: p
    for p in (
        _GOOGLE,
        _MICROSOFT,
        _GITHUB,
        _SLACK,
        _ANTHROPIC,
        _OPENAI,
        _OPENAI_CHATGPT,
    )
}


# ── Lookups ────────────────────────────────────────────────────────────────


def get(provider_id) -> Optional[Provider]:
    """The record, or `None`. Never raises: callers pass user input."""
    return PROVIDERS.get(str(provider_id or "").strip().lower())


def provider_ids() -> Tuple[str, ...]:
    return tuple(PROVIDERS)


def mail_provider_ids() -> Tuple[str, ...]:
    """Providers a mailbox can be linked to with a button.

    Both conditions matter. `mail` alone would include a hypothetical
    password-only mailbox preset; `authorize_url` alone would include GitHub,
    which has no IMAP host to point at.
    """
    return tuple(
        pid
        for pid, p in PROVIDERS.items()
        if p.mail is not None and p.auth == AUTH_OAUTH2 and p.authorize_url
    )


def is_mail_provider(provider_id) -> bool:
    return str(provider_id or "").strip().lower() in mail_provider_ids()


# ── Environment ────────────────────────────────────────────────────────────


def client_id_env(provider: Provider) -> str:
    return provider.client_id_env


def client_secret_env(provider: Provider) -> str:
    return provider.client_secret_env


def redirect_uri_env(provider: Provider) -> str:
    return provider.redirect_uri_env


def _env(name: str) -> str:
    return (os.environ.get(name, "") or "").strip() if name else ""


def client_id(provider: Provider) -> str:
    return _env(client_id_env(provider))


def client_secret(provider: Provider) -> str:
    return _env(client_secret_env(provider))


def api_key(provider: Provider) -> str:
    return _env(provider.key_env)


def is_configured(provider: Provider) -> bool:
    """Whether this deployment can actually complete the flow.

    **Both halves for a confidential client**, which is `P18-01`'s lesson kept
    rather than re-learned: reporting *configured* on the client id alone sends
    a person to the provider, has them grant access to their mailbox, and fails
    on the way back — after the one step they cannot undo by pressing back.
    """
    if provider is None:
        return False
    if provider.auth == AUTH_API_KEY:
        return bool(api_key(provider))
    if not client_id(provider):
        return False
    return bool(client_secret(provider)) or not provider.needs_client_secret


def resolve_url(provider: Provider, template: str) -> str:
    """Fill `{placeholder}` from `url_vars`, each with an environment override."""
    url = template or ""
    for name, env_name, default in provider.url_vars or ():
        url = url.replace("{" + name + "}", _env(env_name) or default)
    return url


def authorize_url(provider: Provider) -> str:
    return resolve_url(provider, provider.authorize_url)


def token_url(provider: Provider) -> str:
    return resolve_url(provider, provider.token_url)


def scope_string(provider: Provider) -> str:
    """Space-separated, which is what every provider here wants.

    GitHub documents commas and accepts spaces; Google, Microsoft and Slack
    require spaces. One separator rather than a per-provider field, because a
    field nothing varies is a field that will be set wrong eventually.
    """
    return " ".join(provider.scopes or ())


# ── Mail transport guards ──────────────────────────────────────────────────


def normalize_host(value) -> str:
    """Normalize a mail hostname for exact provider-bound comparisons."""
    return str(value or "").strip().lower().rstrip(".")


def imap_host_allowed(provider: Provider, host) -> bool:
    if provider is None or provider.mail is None:
        return False
    return normalize_host(host) in provider.mail.imap_hosts


def smtp_host_allowed(provider: Provider, host) -> bool:
    if provider is None or provider.mail is None:
        return False
    return normalize_host(host) in provider.mail.smtp_hosts


def imap_transport_allowed(provider: Provider, port, starttls) -> bool:
    if provider is None or provider.mail is None:
        return False
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    return (port, bool(starttls)) in provider.mail.imap_transports


def smtp_transport_allowed(provider: Provider, port, security) -> bool:
    if provider is None or provider.mail is None:
        return False
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    return (port, str(security or "")) in provider.mail.smtp_transports


def _host_phrase(hosts: Tuple[str, ...]) -> str:
    return hosts[0] if len(hosts) == 1 else " or ".join(hosts)


def imap_host_error(provider: Provider) -> str:
    return (
        f"{provider.label} OAuth IMAP requires "
        f"{_host_phrase(provider.mail.imap_hosts)}"
    )


def smtp_host_error(provider: Provider) -> str:
    return (
        f"{provider.label} OAuth SMTP requires "
        f"{_host_phrase(provider.mail.smtp_hosts)}"
    )


def _transport_phrase(pairs, ssl_word: str) -> str:
    parts = []
    for port, mode in pairs:
        starttls = mode is True or mode == "starttls"
        parts.append(f"{'STARTTLS' if starttls else ssl_word} on port {port}")
    return " or ".join(parts)


def imap_transport_error(provider: Provider) -> str:
    return (
        f"{provider.label} OAuth IMAP requires "
        f"{_transport_phrase(provider.mail.imap_transports, 'TLS')}"
    )


def smtp_transport_error(provider: Provider) -> str:
    return (
        f"{provider.label} OAuth SMTP requires "
        f"{_transport_phrase(provider.mail.smtp_transports, 'TLS')}"
    )


# ── The verified address ───────────────────────────────────────────────────


def _decode_jwt_claims(token: str) -> Dict[str, Any]:
    """The payload of a JWT, **without checking the signature**.

    Stated rather than hidden. This is only ever called on an `id_token` that
    arrived in the body of our own TLS request to the provider's token
    endpoint, in response to a code exchange we authenticated — the case OIDC
    Core 3.1.3.7 explicitly exempts from signature validation, because the
    channel already establishes the issuer. It must never be called on a token
    that arrived from a browser, and there is no path here that does.

    Returns `{}` for anything malformed. A caller that gets `{}` reads it as
    *no verified address*, which fails the ownership check closed.
    """
    try:
        payload = str(token or "").split(".")[1]
    except IndexError:
        return {}
    payload += "=" * (-len(payload) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload.encode()))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def identity_claims(provider: Provider, token_response: Dict[str, Any],
                    userinfo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The dict the address and display name are read out of, per the record."""
    if provider is None:
        return {}
    if provider.identity_source == IDENTITY_ID_TOKEN:
        return _decode_jwt_claims((token_response or {}).get("id_token", ""))
    if provider.identity_source == IDENTITY_USERINFO:
        return userinfo if isinstance(userinfo, dict) else {}
    return {}


def _first_field(claims: Dict[str, Any], fields: Tuple[str, ...]) -> str:
    for field in fields or ():
        value = (claims or {}).get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def identity_email(provider: Provider, claims: Dict[str, Any]) -> str:
    return _first_field(claims, (provider.identity_email_fields if provider else ()))


def identity_name(provider: Provider, claims: Dict[str, Any]) -> str:
    return _first_field(claims, (provider.identity_name_fields if provider else ()))


# ── PKCE ───────────────────────────────────────────────────────────────────
#
# `D-2026-09-13-01`. Here rather than beside the email flow because PKCE is
# OAuth mechanics, not mail: this module already owns the endpoints, the
# scopes, the client credentials and the id_token decode, and a second copy of
# these six lines is how the next flow gets a subtly different one (`Law 14`).

PKCE_METHOD = "S256"

# 32 bytes -> 43 characters, which is RFC 7636's stated minimum and the length
# every reference implementation uses. Longer is allowed to 128 and buys
# nothing: the challenge is a SHA-256 either way, and this value travels inside
# a URL parameter that already carries an encrypted envelope.
_VERIFIER_BYTES = 32


def new_code_verifier() -> str:
    """A fresh PKCE verifier: 43 unreserved characters from a CSPRNG.

    `secrets.token_urlsafe` emits `[A-Za-z0-9_-]`, a subset of RFC 7636's
    permitted `[A-Za-z0-9-._~]`, so no escaping is needed anywhere it travels.
    """
    return secrets.token_urlsafe(_VERIFIER_BYTES)


def code_challenge_for(verifier: str) -> str:
    """`BASE64URL(SHA256(verifier))`, unpadded — RFC 7636 section 4.2.

    Unpadded matters. The `=` of standard base64 is not URL-safe, and a padded
    challenge is a different string from the one the server computes, so the
    exchange fails with `invalid_grant` — an error that names nothing.
    """
    digest = hashlib.sha256(str(verifier or "").encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def pkce_authorize_params(provider: Provider, verifier: str) -> Dict[str, str]:
    """The two authorize-request parameters, or nothing at all.

    Returns `{}` for a provider that does not declare PKCE support, so a caller
    can merge unconditionally and the per-provider decision stays in the record.
    """
    if provider is None or not provider.supports_pkce or not verifier:
        return {}
    return {
        "code_challenge": code_challenge_for(verifier),
        "code_challenge_method": PKCE_METHOD,
    }
