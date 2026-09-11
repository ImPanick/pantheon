# SPDX-License-Identifier: AGPL-3.0-or-later
"""Minting and checking the credential Pantheon presents to this agent.

`companion/pairing.py` mints a token, stores its **hash**, and hands the raw
value to a phone. This is that mechanism with the roles swapped: the agent is
the verifier, so the agent stores the hash and *Pantheon* holds the raw value.

**Why this is a SHA-256 and not bcrypt, which `companion/` uses.** A password
KDF exists to make guessing a *low-entropy* secret expensive. This token is
`secrets.token_urlsafe(32)` — 256 bits, machine-generated, never chosen by a
person and never reused anywhere. There is nothing to guess, so the work factor
buys nothing, and bcrypt is a compiled dependency this package would have to
install on the operator's host to buy it. Rule 1 of the package docstring says
standard library only, and this is the first place that rule costs something, so
it is the first place it is argued rather than asserted.

The comparison is still constant-time. The entropy makes brute force pointless;
it does not make a timing oracle acceptable.

**The token FORMAT is shared with the app on purpose** — same prefix, same
entropy — so an operator who has seen one Pantheon token recognises this one and
the length checks in the middleware would accept it. It is declared here rather
than imported, because importing `core.api_tokens` would pull `core/__init__`
and the whole application onto the host. A test pins the two declarations equal;
that is the seam, and it is watched.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Optional, Tuple

# Mirrors `core.api_tokens.TOKEN_PREFIX` / `TOKEN_ENTROPY_BYTES`.
# `tests/test_the_network_agent_is_its_own_process.py` fails if they drift.
TOKEN_PREFIX = "pan_"
TOKEN_ENTROPY_BYTES = 32
TOKEN_PREFIX_LEN = 8


def mint_raw_token() -> str:
    """A new token, prefix included. Shown to the operator exactly once."""
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def token_matches(raw: str, stored_hash: str) -> bool:
    """Constant-time. See the module docstring for why the KDF is absent."""
    if not raw or not stored_hash:
        return False
    return hmac.compare_digest(hash_token(raw), stored_hash)


def bearer_credential(auth_header: str) -> Optional[str]:
    """The token out of an `Authorization:` header, or None.

    Same shape as `core.api_tokens.bearer_credential`, including the
    case-insensitive scheme — `Authorization` values are not case-normalised by
    every client and a 401 on `bearer` versus `Bearer` is an afternoon lost.
    """
    if not auth_header or not isinstance(auth_header, str):
        return None
    parts = auth_header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    raw = parts[1].strip()
    if not raw.startswith(TOKEN_PREFIX):
        return None
    # The middleware's own sanity bounds. A 4KB "token" is not a token, and
    # hashing one on an unauthenticated path is free work for a stranger.
    if not (12 <= len(raw) <= 100):
        return None
    return raw


def load_or_create(state_dir: Path) -> Tuple[str, Optional[str]]:
    """Return `(stored_hash, raw_if_just_minted)`.

    First run mints and returns the raw value so the launcher can print it once.
    Every run after that returns the stored hash and `None`, because the raw
    value is not recoverable — which is the property that makes storing a hash
    worth doing at all.
    """
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "token.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            stored = str(data.get("hash") or "")
            if stored:
                return stored, None
        except (OSError, ValueError):
            # A corrupt token file is not a reason to run unauthenticated. Fall
            # through and mint a new one; the operator re-pastes it, which is a
            # visible inconvenience rather than an invisible open door.
            pass
    raw = mint_raw_token()
    payload = {"hash": hash_token(raw), "prefix": raw[:TOKEN_PREFIX_LEN]}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # Windows ignores POSIX modes. The file still sits under the operator's
        # own profile directory; tightening it further is the platform's job.
        pass
    return payload["hash"], raw
