"""The shape of an API token, and the one hook that revokes one.

Four places mint or invalidate API tokens and, before this module existed, all
four kept their own copy of both facts:

* `routes/api_token_routes.py` — the admin UI's POST /api/tokens
* `companion/pairing.py` — the phone-pairing mint
* `src/agent_tools/admin_tools.py` — the agent's `manage_tokens` tool
* `routes/auth_routes.py` — deleting a user takes their tokens with them

Three of them agreed. The fourth (`admin_tools`) minted a token with **no
prefix**, dropped the `owner` its caller handed it, and never told the auth
middleware anything had changed — so it returned a credential that could not
authenticate, and deleted ones that went on authenticating. That is `B43`, and
the reason the literals live here now: the prefix is protocol surface, and a
fourth copy of a protocol constant is a fourth chance to disagree.

**Minting and accepting are deliberately two different names.** `TOKEN_PREFIX`
is what new tokens get. `ACCEPTED_TOKEN_PREFIXES` is what the middleware will
try. They are equal today and they must be allowed to differ: renaming the
prefix is a migration, not a rename — every token already in a user's
`.env`, in a paired phone, or in someone's Prometheus scrape config was minted
under the old one, and a bare rename invalidates all of them at once.
"""
from __future__ import annotations

import logging
import secrets
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

# What new tokens are minted with. `P0-31` renames this; see the module
# docstring for why that is a two-value change and not a one-value one.
TOKEN_PREFIX = "ody_"

# What the auth middleware will accept. Keep the currently-minted prefix first;
# every other entry is a prefix this build still honours from tokens minted by
# an older one. Nothing is ever removed from here without a release note.
ACCEPTED_TOKEN_PREFIXES: Tuple[str, ...] = ("ody_",)

# 43 characters of base64url. `secrets.token_urlsafe(32)` is 32 bytes, which is
# what the two mint sites that worked already used; the third used the same
# call and only the prefix was missing.
TOKEN_ENTROPY_BYTES = 32

# The first 8 characters, stored on the row for display and used as the cache
# bucket key. With a 4-character prefix that leaves 4 characters of the secret
# in the bucket key, which is what makes the bucket useful and still shows the
# user something they can recognise in a list.
TOKEN_PREFIX_LEN = 8


def mint_raw_token() -> str:
    """A new token, prefix included. Returned to the caller exactly once."""
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def bearer_credential(auth_header: str) -> Optional[str]:
    """The token out of an `Authorization:` header, or None.

    Returns None for anything that is not a Bearer credential carrying a prefix
    this build accepts, so a caller can fall through to cookie auth rather than
    failing the request. Case is significant in the prefix and not in the
    scheme, which is what RFC 7235 says.
    """
    if not auth_header:
        return None
    scheme, _, credential = auth_header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    credential = credential.strip()
    if not credential.startswith(ACCEPTED_TOKEN_PREFIXES):
        return None
    return credential


# --- Revocation ------------------------------------------------------------
#
# The auth middleware serves bearer auth from an in-memory prefix→tokens map
# that only rebuilds when something flags it dirty. Routes reach that flag
# through `request.app.state.invalidate_token_cache`. The agent's tool layer has
# no `Request` — it is called from the model loop, not from an HTTP handler —
# so before this hook existed it simply could not invalidate anything, and its
# `delete` action left the revoked token authenticating until the next restart.

_invalidators: list[Callable[[], None]] = []


def register_cache_invalidator(fn: Callable[[], None]) -> None:
    """Called once by `app.py` at startup with its own dirty-flag setter."""
    if fn not in _invalidators:
        _invalidators.append(fn)


def invalidate_token_cache() -> None:
    """Tell every registered auth middleware its token map is stale.

    Never raises: a token was just created or destroyed and the caller has
    already committed. Failing here would turn a stale cache into a 500 and
    lose the far more useful log line.
    """
    for fn in list(_invalidators):
        try:
            fn()
        except Exception:  # pragma: no cover — defensive
            logger.warning("API token cache invalidator failed", exc_info=True)
