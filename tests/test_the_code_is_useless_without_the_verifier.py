# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P18-06` / `D-2026-09-13-01` — PKCE on the mailbox OAuth flow.

The owner's call, and the reason they gave is sharper than the textbook one:

    PKCE is needed. This is the exact defense against a MITM/DNS Poisoning
    attack and the like. If we release to the public and we aren't including
    PKCE — we open the users to an attack surface.

**THE TEXTBOOK WOULD SAY TLS IS THE ANSWER TO MITM, AND FOR MOST PRODUCTS IT
WOULD BE RIGHT. IT IS NOT RIGHT HERE**, and the reason is a property this fork
deliberately has: `P18-04` made direct-access deployments first class. Somebody
reaching Pantheon at `http://192.168.1.71:7000` is a supported configuration
and the redirect leg of their OAuth flow is **plaintext on a LAN**. An attacker
who poisons DNS or sits in the path sees `?code=…` in the clear. TLS is not
protecting that leg because there is no TLS on it.

What stops them redeeming the code today is the client secret. That is one
credential, in one `.env`, on a self-hosted box — and a design that concentrates
the entire defence into a single secret is one bad day from having none.

So this is defence in depth, and the honest scope is worth writing down: **PKCE
does not make plaintext HTTP safe.** An attacker on that path can still take the
session cookie and read the tokens on the way back. What PKCE removes is the
specific ability to take an intercepted authorization code and turn it into a
mailbox.

**THE DESIGN PROBLEM WAS KEEPING THE FLOW STATELESS.** The verifier must outlive
the redirect, and `make_oauth_state` is a signed envelope with no server-side
record — no store, no TTL, no cleanup. Putting the verifier in that envelope as
it stood would have defeated PKCE completely: whoever catches the code catches
the state beside it, and a *signed* payload is readable by anyone.

Encrypting it is what makes the stateless version work. The interceptor holds
ciphertext, cannot open it without the app key, cannot produce the verifier, and
cannot redeem the code. The signature still covers the ciphertext, because
encryption alone would leave the account id and owner forgeable — which is what
the HMAC was there for. Both, not either. That is the property this file exists
to pin, and it is the one that would be silently lost by a refactor that decided
signing was enough.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes.email_helpers import make_oauth_state, verify_oauth_state  # noqa: E402
from src import providers  # noqa: E402


# --------------------------------------------------------------------------
# The primitives, against the RFC's own numbers
# --------------------------------------------------------------------------


def test_the_rfc_7636_test_vector():
    """Appendix B. The one assertion here that cannot be wrong in the same
    direction as the implementation, because the answer was written by somebody
    else before this code existed."""
    assert providers.code_challenge_for(
        "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    ) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_the_challenge_is_the_hash_and_not_the_verifier():
    """`plain` is legal in RFC 7636 and is worth nothing: a `plain` challenge
    *is* the verifier, so an interceptor who sees the authorize request has it.
    """
    verifier = providers.new_code_verifier()
    challenge = providers.code_challenge_for(verifier)
    assert challenge != verifier
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    assert challenge == expected
    assert providers.PKCE_METHOD == "S256"


def test_the_challenge_carries_no_padding():
    """`=` is not URL-safe, and a padded challenge is a different string from
    the one the server computes — so the exchange fails with `invalid_grant`,
    an error that names nothing."""
    for _ in range(20):
        assert "=" not in providers.code_challenge_for(providers.new_code_verifier())


def test_the_verifier_is_the_length_and_alphabet_the_rfc_requires():
    seen = set()
    for _ in range(50):
        verifier = providers.new_code_verifier()
        assert 43 <= len(verifier) <= 128
        assert all(c.isalnum() or c in "-._~" for c in verifier), verifier
        seen.add(verifier)
    assert len(seen) == 50, "a verifier that repeats is not a verifier"


# --------------------------------------------------------------------------
# The part that makes a stateless flow safe
# --------------------------------------------------------------------------


def test_the_verifier_cannot_be_read_out_of_the_state():
    """**The assertion this whole design turns on.**

    An interceptor holds exactly the redirect: a code and a state. If the
    verifier is recoverable from the state, PKCE here is theatre — they have
    both halves and the protection is zero. Base64 is not encryption, so this
    checks the decoded bytes too.
    """
    verifier = providers.new_code_verifier()
    state = make_oauth_state("acct-1", "alice", verifier)
    assert verifier not in state
    decoded = base64.urlsafe_b64decode(state.encode()).decode()
    assert verifier not in decoded, (
        "the verifier is readable in the state — this is signing, not encrypting, "
        "and it gives an interceptor both halves"
    )
    payload = json.loads(decoded.rsplit("|", 1)[0])
    assert payload["v"] != verifier


def test_the_verifier_survives_the_round_trip():
    verifier = providers.new_code_verifier()
    restored = verify_oauth_state(make_oauth_state("acct-1", "alice", verifier))
    assert restored["v"] == verifier
    assert restored["a"] == "acct-1"
    assert restored["o"] == "alice"


def test_the_signature_still_covers_the_encrypted_verifier():
    """Encryption alone would leave the account id and owner forgeable, which is
    what the HMAC was there for. Both, not either."""
    state = make_oauth_state("acct-1", "alice", providers.new_code_verifier())
    decoded = base64.urlsafe_b64decode(state.encode()).decode()
    payload, sig = decoded.rsplit("|", 1)
    tampered = json.loads(payload)
    tampered["a"] = "acct-victim"
    forged = base64.urlsafe_b64encode(
        f"{json.dumps(tampered, separators=(',', ':'))}|{sig}".encode()
    ).decode()
    assert verify_oauth_state(forged) is None


def test_a_state_with_no_verifier_still_verifies():
    """`Law 1`. A provider that declares no PKCE support, and any state minted
    before this shipped, must go through unchanged."""
    restored = verify_oauth_state(make_oauth_state("acct-1", "alice"))
    assert restored["a"] == "acct-1"
    assert not restored.get("v")


def test_an_unreadable_verifier_comes_back_empty_rather_than_raising(monkeypatch):
    """This route is reached by a person coming back from Google. An exception
    escaping state verification turns an unreadable envelope into a 500 there.
    """
    import src.secret_storage as ss

    state = make_oauth_state("acct-1", "alice", providers.new_code_verifier())
    monkeypatch.setattr(ss, "decrypt", lambda _v: (_ for _ in ()).throw(ValueError("key rotated")))
    restored = verify_oauth_state(state)
    assert restored is not None
    assert restored["v"] == ""
    assert restored["a"] == "acct-1"


def test_the_state_stays_small_enough_for_a_url():
    """It travels as a query parameter through two redirects."""
    state = make_oauth_state("a" * 36, "owner@example.com",
                             providers.new_code_verifier())
    assert len(state) < 1024, f"state is {len(state)} characters"


# --------------------------------------------------------------------------
# Per provider, because the record decides
# --------------------------------------------------------------------------


def test_both_mailbox_providers_declare_pkce():
    for pid in providers.mail_provider_ids():
        assert providers.get(pid).supports_pkce is True, pid


def test_a_provider_that_declares_no_support_gets_no_parameters():
    """RFC 7636 says a server that does not understand `code_challenge` SHOULD
    ignore it, and *should* is not a guarantee to hand an operator whose
    mailbox stops linking."""
    verifier = providers.new_code_verifier()
    off = providers.Provider(id="x", label="X", supports_pkce=False)
    assert providers.pkce_authorize_params(off, verifier) == {}
    assert providers.pkce_authorize_params(None, verifier) == {}
    assert providers.pkce_authorize_params(providers.get("google"), "") == {}


# --------------------------------------------------------------------------
# The flow, end to end
# --------------------------------------------------------------------------


def _endpoint(leaf):
    from routes.email_routes import setup_email_routes

    router = setup_email_routes()
    return next(r.endpoint for r in router.routes
                if r.path == f"/api/email/oauth/{{provider_id}}/{leaf}")


@pytest.fixture()
def configured(monkeypatch):
    for prefix in ("GOOGLE", "MICROSOFT"):
        monkeypatch.setenv(f"{prefix}_OAUTH_CLIENT_ID", "cid")
        monkeypatch.setenv(f"{prefix}_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setattr("routes.email_routes._assert_owns_account", lambda *a, **k: None)


@pytest.mark.parametrize("provider_id", ["google", "microsoft"])
def test_the_authorize_request_presents_a_challenge(configured, provider_id):
    import asyncio
    import urllib.parse

    resp = asyncio.run(_endpoint("authorize")(
        provider_id=provider_id, account_id="acct-1", request=None, owner="alice"))
    query = urllib.parse.parse_qs(urllib.parse.urlparse(resp.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    challenge = query["code_challenge"][0]
    assert "=" not in challenge

    # And the challenge is the hash of the verifier the state is carrying —
    # the link between the two halves, which is the only thing that makes the
    # exchange work and is invisible from either end alone.
    verifier = verify_oauth_state(query["state"][0])["v"]
    assert verifier
    assert providers.code_challenge_for(verifier) == challenge


@pytest.mark.parametrize("provider_id", ["google", "microsoft"])
def test_the_exchange_sends_the_verifier(configured, provider_id, monkeypatch):
    """The other half. A challenge with no verifier is a flow that cannot
    complete, which is a louder failure than no PKCE but still a failure."""
    import asyncio
    import unittest.mock as mock
    import urllib.parse

    resp = asyncio.run(_endpoint("authorize")(
        provider_id=provider_id, account_id="acct-1", request=None, owner="alice"))
    query = urllib.parse.parse_qs(urllib.parse.urlparse(resp.headers["location"]).query)
    state = query["state"][0]
    verifier = verify_oauth_state(state)["v"]

    token_resp = mock.MagicMock()
    token_resp.raise_for_status = mock.MagicMock()
    token_resp.json.return_value = {}
    with mock.patch("httpx.post", return_value=token_resp) as posted:
        asyncio.run(_endpoint("callback")(
            provider_id=provider_id, code="4/code", state=state,
            error=None, request=None))
    sent = posted.call_args.kwargs["data"]
    assert sent["code_verifier"] == verifier
    assert providers.code_challenge_for(sent["code_verifier"]) == query["code_challenge"][0]


def test_a_state_without_a_verifier_sends_no_empty_parameter(configured):
    """`Law 1`, and the sharp edge of it. An empty `code_verifier` is worse
    than none: the provider treats the parameter as present and refuses a flow
    that never presented a challenge."""
    import asyncio
    import unittest.mock as mock

    state = make_oauth_state("acct-1", "alice")
    token_resp = mock.MagicMock()
    token_resp.raise_for_status = mock.MagicMock()
    token_resp.json.return_value = {}
    with mock.patch("httpx.post", return_value=token_resp) as posted:
        asyncio.run(_endpoint("callback")(
            provider_id="google", code="4/code", state=state,
            error=None, request=None))
    assert "code_verifier" not in posted.call_args.kwargs["data"]


def test_two_flows_do_not_share_a_verifier(configured):
    """A verifier reused across flows is a verifier an attacker can learn once."""
    import asyncio
    import urllib.parse

    seen = set()
    for _ in range(5):
        resp = asyncio.run(_endpoint("authorize")(
            provider_id="google", account_id="acct-1", request=None, owner="alice"))
        query = urllib.parse.parse_qs(urllib.parse.urlparse(resp.headers["location"]).query)
        seen.add(query["code_challenge"][0])
    assert len(seen) == 5


def test_the_client_secret_is_still_sent(configured):
    """PKCE is defence in depth, not a replacement. Dropping the secret would
    turn a confidential client into a public one, which is a different
    decision and is `P18-06`'s open half."""
    import asyncio
    import unittest.mock as mock

    state = make_oauth_state("acct-1", "alice", providers.new_code_verifier())
    token_resp = mock.MagicMock()
    token_resp.raise_for_status = mock.MagicMock()
    token_resp.json.return_value = {}
    with mock.patch("httpx.post", return_value=token_resp) as posted:
        asyncio.run(_endpoint("callback")(
            provider_id="google", code="4/code", state=state,
            error=None, request=None))
    assert posted.call_args.kwargs["data"]["client_secret"] == "secret"
