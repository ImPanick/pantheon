# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P18-05` — the proof that adding a provider is data and not a flow.

The row's `Verify:` is *"a provider is a record — endpoints, scopes, whether it
needs a client secret — and adding one is data rather than a flow"*. A grep for
`== "google"` would test the file rather than the code (`Law 20`), and it would
pass the moment somebody wrote `in ("google", "microsoft")`.

**SO THE TEST INVENTS A PROVIDER THAT DOES NOT EXIST AND DRIVES THE WHOLE PATH
WITH IT.** `acme` is inserted into the registry at runtime and nothing else is
touched: no module edited, no route added, no branch widened. If any step still
asks *which provider is this* by name, `acme` falls out of that step and the
assertion below it fails.

Microsoft is the row's stated proof and it is asserted separately, because a
fictional provider proves the mechanism and a real one proves the mechanism was
pointed at something true — the endpoints, the scopes and the two SMTP hosts
are facts about Microsoft that a made-up record cannot check.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import mail_auth, providers  # noqa: E402

ACME = providers.Provider(
    id="acme",
    label="Acme Mail",
    client_id_env="ACME_OAUTH_CLIENT_ID",
    client_secret_env="ACME_OAUTH_CLIENT_SECRET",
    redirect_uri_env="ACME_OAUTH_REDIRECT_URI",
    authorize_url="https://auth.acme.test/{realm}/authorize",
    token_url="https://auth.acme.test/{realm}/token",
    userinfo_url="https://api.acme.test/me",
    scopes=("mail.read", "mail.send"),
    authorize_params=(("acme_param", "yes"),),
    identity_source=providers.IDENTITY_USERINFO,
    identity_email_fields=("address",),
    identity_name_fields=("full_name",),
    url_vars=(("realm", "ACME_OAUTH_REALM", "default"),),
    mail=providers.MailTransport(
        imap_hosts=("imap.acme.test",),
        smtp_hosts=("smtp.acme.test", "mail.acme.test"),
        imap_transports=((993, False),),
        smtp_transports=((587, "starttls"), (465, "ssl")),
    ),
    setup_url="https://acme.test/console",
    setup_hint="Set ACME_OAUTH_CLIENT_ID and ACME_OAUTH_CLIENT_SECRET.",
)


@pytest.fixture()
def acme(monkeypatch):
    """`acme` exists for the duration of one test, and nothing else changes."""
    monkeypatch.setitem(providers.PROVIDERS, "acme", ACME)
    monkeypatch.setenv("ACME_OAUTH_CLIENT_ID", "acme-id")
    monkeypatch.setenv("ACME_OAUTH_CLIENT_SECRET", "acme-secret")
    monkeypatch.delenv("ACME_OAUTH_REDIRECT_URI", raising=False)
    monkeypatch.delenv("ACME_OAUTH_REALM", raising=False)
    return ACME


# --------------------------------------------------------------------------
# The registry itself
# --------------------------------------------------------------------------


def test_a_new_record_joins_the_linkable_set_with_no_code_change(acme):
    assert "acme" in providers.mail_provider_ids()
    assert providers.is_mail_provider("acme") is True


def test_the_module_that_held_the_literal_now_reads_the_registry(acme):
    """`src/mail_auth.py` had `frozenset({"google"})` written into it.

    That frozenset is the reason this is asserted rather than assumed: a
    snapshot taken at import would answer for the registry as it was, and this
    fixture inserts `acme` after import.
    """
    assert "acme" in mail_auth.OAUTH_PROVIDERS
    assert mail_auth.provider_of({"oauth_provider": "AcMe"}) == "acme"
    assert mail_auth.is_oauth({"oauth_provider": "acme"}) is True


def test_a_service_record_is_not_a_mailbox(acme):
    """`github` has an authorize URL and no mailbox, and must stay out.

    The mailbox flow writes IMAP and SMTP hosts onto an account row. A record
    with no `mail` block has nothing to write, so reaching that flow through
    one would produce an account configured against nothing.
    """
    assert "github" not in providers.mail_provider_ids()
    assert providers.is_mail_provider("github") is False
    assert mail_auth.provider_of({"oauth_provider": "github"}) == ""


def test_an_api_key_service_is_not_asked_for_a_client_secret(monkeypatch):
    """`Law 9`, applied to a record. Anthropic has no consumer OAuth for API
    access, and a registry that gave it an `authorize_url` so every row looked
    alike would be a lie told for symmetry."""
    anthropic = providers.get("anthropic")
    assert anthropic.auth == providers.AUTH_API_KEY
    assert anthropic.authorize_url == ""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert providers.is_configured(anthropic) is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert providers.is_configured(anthropic) is True


# --------------------------------------------------------------------------
# The flow, driven by a provider nobody wrote code for
# --------------------------------------------------------------------------


def test_the_served_provider_list_grows_by_itself(acme):
    import routes.email_routes as er

    served = {p["id"]: p for p in er._oauth_providers()}
    assert "acme" in served, "the list is still written out by hand somewhere"
    entry = served["acme"]
    assert entry["label"] == "Acme Mail"
    assert entry["imap_hosts"] == ["imap.acme.test"]
    assert entry["smtp_hosts"] == ["smtp.acme.test", "mail.acme.test"]
    assert entry["authorize"] == "/api/email/oauth/acme/authorize"
    assert entry["configured"] is True
    assert entry["redirect_uri"].endswith("/api/email/oauth/acme/callback")
    assert entry["setup_url"] == "https://acme.test/console"


def test_the_defaults_written_on_link_come_from_the_record(acme):
    """`P18-07`'s lesson as a rule: the first transport pair is the default.

    The pair written to a freshly linked account has to be one the validator
    accepts, and before `P18-07` it was not — port and security mode were set
    from two places and produced SSL on 587, which this app's own guard refuses
    and `smtplib` answers by hanging until the socket timeout.
    """
    import routes.email_routes as er

    entry = next(p for p in er._oauth_providers() if p["id"] == "acme")
    assert (entry["smtp_port"], entry["smtp_security"]) == (587, "starttls")
    assert providers.smtp_transport_allowed(
        ACME, entry["smtp_port"], entry["smtp_security"]
    ), "the default written on link must be a pair the validator accepts"
    assert providers.imap_transport_allowed(
        ACME, entry["imap_port"], entry["imap_starttls"]
    )


def test_every_shipped_provider_defaults_to_a_transport_it_allows():
    """The same check against every real record, not just the invented one."""
    for pid in providers.mail_provider_ids():
        record = providers.get(pid)
        assert providers.imap_transport_allowed(
            record, record.mail.imap_port, record.mail.imap_starttls
        ), pid
        assert providers.smtp_transport_allowed(
            record, record.mail.smtp_port, record.mail.smtp_security
        ), pid
        assert providers.imap_host_allowed(record, record.mail.imap_host), pid
        assert providers.smtp_host_allowed(record, record.mail.smtp_host), pid


@pytest.mark.asyncio
async def test_the_authorize_redirect_is_built_from_the_record(acme, monkeypatch):
    """The consent URL: endpoint, scopes and per-provider parameters."""
    import urllib.parse

    from routes.email_routes import setup_email_routes

    router = setup_email_routes()
    authorize = next(
        r.endpoint for r in router.routes
        if r.path == "/api/email/oauth/{provider_id}/authorize"
    )
    monkeypatch.setattr(
        "routes.email_routes._assert_owns_account", lambda *a, **k: None
    )
    resp = await authorize(
        provider_id="acme", account_id="acct-1", request=None, owner="alice"
    )
    location = resp.headers["location"]
    assert location.startswith("https://auth.acme.test/default/authorize?")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    assert query["client_id"] == ["acme-id"]
    assert query["scope"] == ["mail.read mail.send"]
    assert query["acme_param"] == ["yes"], "per-provider authorize params are dropped"
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"][0].endswith("/api/email/oauth/acme/callback")


@pytest.mark.asyncio
async def test_a_url_placeholder_is_resolved_from_the_environment(acme, monkeypatch):
    """Microsoft's `{tenant}` is the real case; `{realm}` is its stand-in.

    A single-tenant Entra registration cannot use `common`, and before this the
    endpoint was a literal in the route — so restricting it meant editing code.
    """
    monkeypatch.setenv("ACME_OAUTH_REALM", "tenant-42")
    assert providers.authorize_url(ACME) == "https://auth.acme.test/tenant-42/authorize"
    assert providers.token_url(ACME) == "https://auth.acme.test/tenant-42/token"


@pytest.mark.asyncio
async def test_an_unknown_provider_is_refused_rather_than_guessed(monkeypatch):
    from fastapi import HTTPException

    from routes.email_routes import setup_email_routes

    router = setup_email_routes()
    authorize = next(
        r.endpoint for r in router.routes
        if r.path == "/api/email/oauth/{provider_id}/authorize"
    )
    monkeypatch.setattr(
        "routes.email_routes._assert_owns_account", lambda *a, **k: None
    )
    for bad in ("acme", "github", "../google", ""):
        with pytest.raises(HTTPException) as caught:
            await authorize(
                provider_id=bad, account_id="acct-1", request=None, owner="alice"
            )
        assert caught.value.status_code == 404, bad


@pytest.mark.asyncio
async def test_the_callback_refuses_an_unknown_provider_without_touching_the_database(monkeypatch):
    from routes.email_routes import setup_email_routes

    router = setup_email_routes()
    callback = next(
        r.endpoint for r in router.routes
        if r.path == "/api/email/oauth/{provider_id}/callback"
    )

    def _explode():
        raise AssertionError("the database must not be opened for an unknown provider")

    monkeypatch.setattr("core.database.SessionLocal", _explode)
    resp = await callback(
        provider_id="github", code="c", state="s", error=None, request=None
    )
    assert "email_oauth_error=unknown_provider" in resp.headers["location"]


def test_the_transport_guards_refuse_the_wrong_host_for_the_right_provider(acme):
    assert providers.imap_host_allowed(ACME, "IMAP.ACME.TEST.") is True
    assert providers.imap_host_allowed(ACME, "imap.gmail.com") is False
    assert providers.smtp_host_allowed(ACME, "mail.acme.test") is True
    assert providers.smtp_transport_allowed(ACME, 465, "ssl") is True
    assert providers.smtp_transport_allowed(ACME, 587, "ssl") is False
    assert providers.imap_transport_allowed(ACME, 143, True) is False, (
        "Google allows 143/STARTTLS and Acme does not — the rule is per record"
    )


def test_the_refresh_table_needs_no_entry_for_a_new_provider(acme, monkeypatch):
    """The old shape was `{"google": ...}` and a missing key meant `None`.

    Worse than `None`, in the version before that: a table keyed on nothing ran
    **Google's** refresh for any provider, which is only unreachable while every
    caller checks first — a guarantee living in the callers rather than in the
    function that depends on it.
    """
    seen = {}

    def _fake(provider_id, account_id):
        seen["args"] = (provider_id, account_id)
        return "acme-token"

    monkeypatch.setattr(mail_auth, "refresh_oauth_token", _fake)
    token = mail_auth.access_token_for(
        {"oauth_provider": "acme", "account_id": "acct-9"}
    )
    assert token == "acme-token"
    assert seen["args"] == ("acme", "acct-9")


def test_a_rotated_refresh_token_is_persisted(monkeypatch, tmp_path):
    """Microsoft rotates its refresh token on every use; Google does not.

    The old Google-only refresher never looked for a new one, which is correct
    for Google and a mailbox that dies the day the original expires for anybody
    who copied it. **A mutation run found this unproven**: discarding the
    rotated token broke nothing, because no test had ever exercised a refresh
    that returned one.
    """
    import time
    import unittest.mock as mock

    from core.database import Base, EmailAccount
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.secret_storage import decrypt as _dec, encrypt as _enc

    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "mid")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "msecret")

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine)
    db = Factory()
    db.add(EmailAccount(
        id="acct-ms", owner="alice", name="ms",
        oauth_provider="microsoft",
        oauth_refresh_token=_enc("old-refresh"),
        oauth_token_expiry=str(int(time.time()) - 10),
    ))
    db.commit()
    db.close()

    resp = mock.MagicMock()
    resp.raise_for_status = mock.MagicMock()
    resp.json.return_value = {
        "access_token": "new-access",
        "refresh_token": "rotated-refresh",
        "expires_in": 3600,
    }
    with mock.patch("httpx.post", return_value=resp) as posted, \
         mock.patch("core.database.SessionLocal", Factory):
        token = mail_auth.refresh_oauth_token("microsoft", "acct-ms")

    assert token == "new-access"
    assert posted.call_args[0][0].startswith("https://login.microsoftonline.com/")

    verify = Factory()
    row = verify.query(EmailAccount).filter(EmailAccount.id == "acct-ms").first()
    stored_refresh = _dec(row.oauth_refresh_token)
    stored_access = row.oauth_access_token
    verify.close()
    assert stored_refresh == "rotated-refresh", (
        "the rotated refresh token was discarded; this mailbox dies when the "
        "original expires"
    )
    assert stored_access != "new-access", "the access token must be stored encrypted"
    assert _dec(stored_access) == "new-access"


def test_a_refresh_that_returns_no_new_token_keeps_the_old_one(monkeypatch):
    """Google's shape. The rotation must not blank what is already there."""
    import time
    import unittest.mock as mock

    from core.database import Base, EmailAccount
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.secret_storage import decrypt as _dec, encrypt as _enc

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "gid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "gsecret")

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine)
    db = Factory()
    db.add(EmailAccount(
        id="acct-g", owner="alice", name="g",
        oauth_provider="google",
        oauth_refresh_token=_enc("keep-me"),
        oauth_token_expiry=str(int(time.time()) - 10),
    ))
    db.commit()
    db.close()

    resp = mock.MagicMock()
    resp.raise_for_status = mock.MagicMock()
    resp.json.return_value = {"access_token": "a", "expires_in": 3600}
    with mock.patch("httpx.post", return_value=resp), \
         mock.patch("core.database.SessionLocal", Factory):
        assert mail_auth.refresh_oauth_token("google", "acct-g") == "a"

    verify = Factory()
    row = verify.query(EmailAccount).filter(EmailAccount.id == "acct-g").first()
    kept = _dec(row.oauth_refresh_token)
    verify.close()
    assert kept == "keep-me"


def test_googles_patchable_refresher_still_intercepts(monkeypatch):
    """`Law 1`. Three tests and `routes/email_helpers` hold that name."""
    calls = []
    monkeypatch.setattr(
        mail_auth, "refresh_google_token", lambda account_id: calls.append(account_id) or "g"
    )
    assert mail_auth.access_token_for(
        {"oauth_provider": "google", "account_id": "acct-g"}
    ) == "g"
    assert calls == ["acct-g"]


# --------------------------------------------------------------------------
# The verified address, which is a security control and not a convenience
# --------------------------------------------------------------------------


def test_the_identity_source_decides_where_the_address_is_read_from():
    """Google answers a userinfo call; Microsoft cannot.

    Entra will not issue one token covering Graph *and* the
    `https://outlook.office.com/…` resource scopes IMAP and SMTP need, so
    Microsoft's address comes from the `id_token` returned alongside them.
    Reading it from the wrong place returns nothing, and nothing fails the
    reconnect ownership check closed — which is the safe direction, and still a
    mailbox that can never be linked.
    """
    import base64
    import json

    google = providers.get("google")
    claims = providers.identity_claims(
        google, {"id_token": "ignored"}, {"email": "a@gmail.com", "name": "A"}
    )
    assert providers.identity_email(google, claims) == "a@gmail.com"
    assert providers.identity_name(google, claims) == "A"

    payload = base64.urlsafe_b64encode(
        json.dumps({"preferred_username": "b@contoso.com", "name": "B"}).encode()
    ).decode().rstrip("=")
    microsoft = providers.get("microsoft")
    claims = providers.identity_claims(
        microsoft, {"id_token": f"h.{payload}.sig"}, {"email": "wrong@example.com"}
    )
    assert providers.identity_email(microsoft, claims) == "b@contoso.com", (
        "a userinfo body must not be read for a provider that does not use one"
    )
    assert providers.identity_name(microsoft, claims) == "B"


@pytest.mark.parametrize(
    "token",
    ["", "not-a-jwt", "a.b", "h..s", "h.!!!!.s", "h." + "e30", None],
)
def test_a_malformed_id_token_reads_as_no_address(token):
    """`{}` rather than a raise. The callback treats it as *unverified*."""
    microsoft = providers.get("microsoft")
    claims = providers.identity_claims(microsoft, {"id_token": token})
    assert providers.identity_email(microsoft, claims) == ""


def test_an_id_token_whose_payload_is_not_an_object_is_rejected():
    import base64

    payload = base64.urlsafe_b64encode(b'"just-a-string"').decode().rstrip("=")
    microsoft = providers.get("microsoft")
    claims = providers.identity_claims(microsoft, {"id_token": f"h.{payload}.s"})
    assert claims == {}


def test_the_email_field_order_is_the_fallback_order():
    """Personal Microsoft accounts carry the address in `preferred_username`."""
    microsoft = providers.get("microsoft")
    assert microsoft.identity_email_fields == ("email", "preferred_username", "upn")
    assert providers.identity_email(
        microsoft, {"email": "  ", "preferred_username": "c@outlook.com"}
    ) == "c@outlook.com"


# --------------------------------------------------------------------------
# Microsoft, which is the row's stated proof
# --------------------------------------------------------------------------


def test_microsoft_is_linkable_and_carries_the_scopes_it_needs():
    microsoft = providers.get("microsoft")
    assert "microsoft" in providers.mail_provider_ids()
    scopes = set(microsoft.scopes)
    assert "https://outlook.office.com/IMAP.AccessAsUser.All" in scopes
    assert "https://outlook.office.com/SMTP.Send" in scopes
    assert "offline_access" in scopes, (
        "without it Microsoft issues no refresh token and the mailbox stops "
        "working about an hour after it is linked"
    )
    assert {"openid", "email", "profile"} <= scopes, (
        "the address comes from the id_token, which these three scopes produce"
    )
    assert "https://graph.microsoft.com/User.Read" not in scopes, (
        "a Graph scope cannot share a token with the Outlook resource scopes"
    )


def test_microsoft_accepts_both_of_its_smtp_hosts():
    """One IMAP host, two SMTP hosts — the shape a single string cannot hold.

    `smtp.office365.com` is Microsoft 365; `smtp-mail.outlook.com` is personal
    Outlook.com. Google has one of each, which is why the field looked scalar
    until there was a second provider to check it against.
    """
    microsoft = providers.get("microsoft")
    assert providers.smtp_host_allowed(microsoft, "smtp.office365.com")
    assert providers.smtp_host_allowed(microsoft, "smtp-mail.outlook.com")
    assert providers.smtp_host_allowed(microsoft, "smtp.gmail.com") is False
    assert providers.imap_host_allowed(microsoft, "outlook.office365.com")


def test_the_tenant_is_configurable_and_defaults_to_common(monkeypatch):
    microsoft = providers.get("microsoft")
    monkeypatch.delenv("MICROSOFT_OAUTH_TENANT", raising=False)
    assert providers.authorize_url(microsoft).startswith(
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    )
    monkeypatch.setenv("MICROSOFT_OAUTH_TENANT", "contoso.onmicrosoft.com")
    assert "contoso.onmicrosoft.com" in providers.token_url(microsoft)


def test_the_panel_no_longer_says_microsoft_is_unsupported():
    """It said *"Pantheon does not support Microsoft OAuth/Graph mail yet"*.

    A panel that tells a person a working feature does not exist is worse than
    one that says nothing, because they believe it and stop looking.
    """
    js = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    region = js[js.index("      outlook: {"):]
    region = region[: region.index("linkLabel")]
    # The *strings*, not the region. Written first as a substring check over
    # the whole block, which failed on a code comment quoting the sentence it
    # had just removed — a test of the file rather than of what the panel says
    # (`Law 20`), and it would equally have passed on a block that shipped the
    # old text in a variable.
    shown = " ".join(
        line.split(":", 1)[1].strip().strip("',")
        for line in region.splitlines()
        if line.strip().startswith(("title:", "body:"))
    )
    assert shown, "the outlook note lost its title and body"
    assert "does not support" not in shown
    assert "placeholder for future support" not in shown
    assert "Sign in with Microsoft" in shown

    from routes.email_helpers import _friendly_email_auth_error

    # The real function, on the real error Microsoft returns.
    message = _friendly_email_auth_error(
        "SMTP",
        "smtp.office365.com",
        Exception("535 5.7.139 Authentication unsuccessful, basic authentication is disabled"),
    )
    assert "cannot be added" not in message
    assert "Sign in with Microsoft" in message


def test_the_browser_asks_the_account_which_provider_it_is_linked_to():
    """`=== 'google'` against a provider resolved from the host.

    A Microsoft-linked account matched the host, failed that comparison, and
    would have rendered as *Connect* with the password fields back — the same
    rule answered two ways, one step apart (`Law 13`).
    """
    js = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "existing.oauth_provider === 'google'" not in js
    assert "existing.oauth_provider === provider.id" in js


# --------------------------------------------------------------------------
# The other half of the row: one record type, two consumers
# --------------------------------------------------------------------------


def test_a_service_record_becomes_an_integration_preset():
    """`D-2026-09-12-01`: one record shape for mailboxes *and* integrations.

    Unproven if nothing but the mail path ever reads a record, which is what
    this asserts against. The four service presets are projections of records
    rather than a second description of the same services (`Law 14`).
    """
    from src.integrations import INTEGRATION_PRESETS

    for pid in ("github", "slack", "anthropic", "openai"):
        record = providers.get(pid)
        preset = INTEGRATION_PRESETS[pid]
        assert preset["name"] == record.label
        assert preset["base_url"] == record.api_base
        assert preset["auth_type"] == record.api_auth_type
        assert preset["description"] == record.api_hint
        assert preset["description"], f"{pid} ships an empty endpoint crib"


def test_anthropic_is_not_given_a_bearer_token():
    """It reads `x-api-key`, and `Authorization: Bearer` fails authentication.

    The kind of per-service detail that a generated preset gets right once and
    a hand-written one gets wrong on the third copy.
    """
    from src.integrations import INTEGRATION_PRESETS

    assert INTEGRATION_PRESETS["anthropic"]["auth_header"] == "x-api-key"
    assert INTEGRATION_PRESETS["openai"]["auth_type"] == "bearer"


def test_an_existing_preset_is_never_overwritten_by_a_record():
    """`Law 1`. A hand-written preset under one of these ids stays theirs.

    **Written first as an assertion about `gitea`**, which is hand-written and
    is not one of the four ids — so it proved nothing about the rule. A
    mutation run turned the `setdefault` into an assignment and every test
    still passed. The collision is now made rather than hoped for.
    """
    from src.integrations import INTEGRATION_PRESETS, install_provider_presets

    mine = {"name": "My GitHub Enterprise", "auth_type": "header",
            "auth_header": "X-Mine", "description": "hand written"}
    target = {"github": dict(mine)}
    install_provider_presets(target)
    assert target["github"] == mine, "a hand-written preset was replaced"
    assert "slack" in target, "the others are still installed alongside it"

    # And the module's own table is untouched by that call.
    assert INTEGRATION_PRESETS["github"]["base_url"] == "https://api.github.com"
    assert INTEGRATION_PRESETS["gitea"]["auth_header"] == "Authorization"


# --------------------------------------------------------------------------
# Shapes the registry must refuse to be wrong about
# --------------------------------------------------------------------------


def test_every_record_declares_a_known_auth_kind():
    for pid, record in providers.PROVIDERS.items():
        assert record.auth in providers.AUTH_KINDS, pid
        assert record.id == pid


def test_every_oauth_record_that_can_be_started_has_both_endpoints():
    for pid, record in providers.PROVIDERS.items():
        if record.auth != providers.AUTH_OAUTH2 or not record.authorize_url:
            continue
        assert record.token_url, f"{pid} can start a flow it cannot finish"
        assert record.client_id_env, pid
        if record.needs_client_secret:
            assert record.client_secret_env, pid


def test_every_url_placeholder_has_a_default():
    """An unresolved `{tenant}` produces a request to a literal brace."""
    for pid, record in providers.PROVIDERS.items():
        for url in (providers.authorize_url(record), providers.token_url(record)):
            assert "{" not in url, f"{pid}: {url}"


def test_a_lookup_never_raises_on_junk():
    for junk in (None, "", "  ", 0, [], "GOOGLE ", "../../etc/passwd"):
        assert providers.get(junk) in (None, providers.get("google"))
    assert providers.get("GOOGLE ") is providers.get("google")
