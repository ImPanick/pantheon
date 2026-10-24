# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P27-03` · Each person's private vault: logins the agent uses by reference.

The owner (2026-10-24): *"a per-user private vault for logins to be stored. So
the user can map a URL on a local domain even, and configure a local account on
that service (assign rbac etc) and then store the login details for the agent
to login and automate (using shell or even the browser)."*

**Whose.** One vault per account (`workstation_access.account_of`, the spelling
git and the workstation use). No function here takes a second account: every
read and write is the caller's own, and another person's item is *not found*,
never *forbidden* — its existence is not theirs to learn.

**How it is kept.** Each account has its own key (`VaultKey`), a Fernet key
wrapped by the server's (`secret_storage`). An item's label and addresses are
in the clear — they are how it is named and how a page's origin is checked —
and everything else (user name, password, one-time-code secret, notes, a key)
is one sealed JSON blob under the person's key.

**How it is used.** By reference. `public()` is what any screen is told: no
password, no secret, only that one is set. `for_use()` is the one reader of a
sealed blob for the agent, and its callers hand the values straight to the
daemon (`agent_browser login`) or a command's environment — never to the model,
a transcript, a log or an error message. `reveal()` is the person's own look,
after their password, and is logged.

**Locking.** A person may set an idle time; the vault then locks that long
after it was last unlocked or used by them, and a locked vault refuses the
agent with a sentence telling the person where to unlock it. `0` (the default)
keeps it unlocked: it is still encrypted at rest. The unlock is in memory, so a
restart locks every vault that has an idle time.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

KINDS = ("login", "key", "note")
USES = ("ask", "chat", "allowed")
ITEMS_MAX = 500
ADDRESSES_MAX = 8
LABEL_MAX = 80
USERNAME_MAX = 256
SECRET_MAX = 4096
NOTES_MAX = 8000
IDLE_MAX_MINUTES = 24 * 60

LOCKED_SENTENCE = ("Your vault is locked. Unlock it in Settings → Vault, then ask again. "
                   "Nothing was filled.")


class VaultRefused(ValueError):
    def __init__(self, sentence: str, status: int = 400):
        super().__init__(sentence)
        self.sentence = sentence
        self.status = status


def account(owner: Optional[str]) -> str:
    from src.workstation_access import account_of
    return account_of(owner)


# ── addresses ───────────────────────────────────────────────────────────────

_LOCAL_SUFFIXES = (".lan", ".local", ".home", ".internal", ".localdomain", ".home.arpa", ".test")


def _is_local_host(host: str) -> bool:
    h = host.strip("[]").lower()
    if h == "localhost" or "." not in h or h.endswith(_LOCAL_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def origin_of(raw: Any) -> str:
    """`https://grafana.lan:3000/login` → `https://grafana.lan:3000`. A bare
    name is https unless it is a name or address only a local network knows,
    which is http (`browserWindow.addressOf`'s rule). Default ports dropped."""
    text = str(raw or "").strip()
    if not text:
        raise VaultRefused("An address is empty.")
    if len(text) > 2048 or any(c.isspace() for c in text):
        raise VaultRefused(f"“{text[:60]}” is not an address.")
    if "://" not in text:
        host_part = text.split("/")[0]
        bare = host_part.rsplit(":", 1)[0] if host_part.count(":") == 1 else host_part
        text = ("http://" if _is_local_host(bare) else "https://") + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise VaultRefused(f"“{str(raw)[:60]}” is not an address.") from None
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise VaultRefused(f"“{str(raw)[:60]}”: a login is for an http or https address.")
    host = (parts.hostname or "").lower()
    if not host or not re.fullmatch(r"[a-z0-9._\-:\[\]]+", host):
        raise VaultRefused(f"“{str(raw)[:60]}” has no host name.")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if port is None or (scheme, port) in (("http", 80), ("https", 443)):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _clean_addresses(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [a for a in re.split(r"[\s,]+", raw) if a]
    if not isinstance(raw, list):
        raise VaultRefused("“addresses” is a list of addresses.")
    out: List[str] = []
    for a in raw:
        o = origin_of(a)
        if o not in out:
            out.append(o)
    if len(out) > ADDRESSES_MAX:
        raise VaultRefused(f"At most {ADDRESSES_MAX} addresses on one login.")
    return out


# ── keys ────────────────────────────────────────────────────────────────────

def _fernet(db, acct: str, *, create: bool):
    from cryptography.fernet import Fernet
    from core.database import VaultKey
    from src.secret_storage import decrypt, encrypt
    row = db.query(VaultKey).filter(VaultKey.account == acct).first()
    if row is None:
        if not create:
            return None
        key = Fernet.generate_key().decode()
        row = VaultKey(account=acct, wrapped=encrypt(key), idle_minutes=0)
        db.add(row)
        db.flush()
        return Fernet(key.encode())
    return Fernet(decrypt(row.wrapped).encode())


def _seal(f, data: Dict[str, Any]) -> str:
    return f.encrypt(json.dumps(data, separators=(",", ":")).encode()).decode()


def _open(f, sealed: str) -> Dict[str, Any]:
    try:
        return json.loads(f.decrypt(sealed.encode()).decode())
    except Exception:  # noqa: BLE001 — a blob this key cannot open is no item at all
        raise VaultRefused("That item could not be opened with your vault's key.", 500) from None


# ── lock ────────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_unlocked_until: Dict[str, float] = {}


def _idle_minutes(db, acct: str) -> int:
    from core.database import VaultKey
    row = db.query(VaultKey).filter(VaultKey.account == acct).first()
    return int(row.idle_minutes or 0) if row else 0


def is_locked(db, owner: Optional[str]) -> bool:
    acct = account(owner)
    idle = _idle_minutes(db, acct)
    if idle <= 0:
        return False
    with _lock:
        return time.time() >= _unlocked_until.get(acct, 0.0)


def touch(db, owner: Optional[str]) -> None:
    """The person did something with their vault: an unlocked one stays so."""
    acct = account(owner)
    idle = _idle_minutes(db, acct)
    with _lock:
        if idle > 0 and time.time() < _unlocked_until.get(acct, 0.0):
            _unlocked_until[acct] = time.time() + idle * 60


def unlock(db, owner: Optional[str]) -> None:
    """After the caller checked the person's password."""
    acct = account(owner)
    idle = _idle_minutes(db, acct)
    with _lock:
        _unlocked_until[acct] = time.time() + max(idle, 1) * 60


def lock_now(owner: Optional[str]) -> None:
    with _lock:
        _unlocked_until.pop(account(owner), None)


def set_idle(db, owner: Optional[str], minutes: Any) -> None:
    from core.database import VaultKey
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 <= minutes <= IDLE_MAX_MINUTES:
        raise VaultRefused(f"“idle_minutes” is a whole number from 0 (never lock) to {IDLE_MAX_MINUTES}.")
    acct = account(owner)
    _fernet(db, acct, create=True)
    row = db.query(VaultKey).filter(VaultKey.account == acct).first()
    row.idle_minutes = minutes
    db.commit()
    if minutes > 0:
        unlock(db, owner)   # setting a lock does not lock you out mid-sentence


# ── reading ─────────────────────────────────────────────────────────────────

def _iso(dt) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None


def public(row, sealed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What a screen is told about an item: never a password, a key or a
    one-time-code secret — only that one is set."""
    s = sealed or {}
    return {"id": row.id, "kind": row.kind, "label": row.label,
            "addresses": json.loads(row.addresses or "[]"),
            "username": s.get("username") or "",
            "has_secret": bool(s.get("secret")), "has_totp": bool(s.get("totp")),
            "has_notes": bool(s.get("notes")), "agent_account": bool(row.agent_account),
            "use": row.use if row.use in USES else "ask",
            "last_used_at": _iso(row.last_used_at), "last_used_by": row.last_used_by or None,
            "updated_at": _iso(row.updated_at)}


def _rows(db, acct: str):
    from core.database import VaultItem
    return (db.query(VaultItem).filter(VaultItem.account == acct)
            .order_by(VaultItem.label).all())


def listing(db, owner: Optional[str]) -> Dict[str, Any]:
    acct = account(owner)
    locked = is_locked(db, owner)
    f = None if locked else _fernet(db, acct, create=False)
    items = []
    for r in _rows(db, acct):
        items.append(public(r, _open(f, r.sealed) if f else None))
    return {"items": items, "locked": locked, "idle_minutes": _idle_minutes(db, acct),
            "kinds": list(KINDS), "uses": list(USES)}


def labels(db, owner: Optional[str]) -> List[str]:
    """The names the agent may ask for. Names only."""
    return [r.label for r in _rows(db, account(owner))]


def _find(db, acct: str, ref: Any):
    from core.database import VaultItem
    ref = str(ref or "").strip()
    if not ref:
        return None
    q = db.query(VaultItem).filter(VaultItem.account == acct)
    row = q.filter(VaultItem.id == ref).first()
    if row is None:
        low = ref.lower()
        row = next((r for r in q.all() if r.label.lower() == low), None)
    return row


# ── writing ─────────────────────────────────────────────────────────────────

def _clean_label(raw: Any) -> str:
    label = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not label:
        raise VaultRefused("Give the item a name, such as “Grafana (agent)”.")
    if len(label) > LABEL_MAX:
        raise VaultRefused(f"A name is at most {LABEL_MAX} characters.")
    return label


def _clean_totp(raw: Any) -> str:
    text = re.sub(r"\s+", "", str(raw or "")).upper()
    if text.startswith("OTPAUTH://"):
        import pyotp
        try:
            text = pyotp.parse_uri(str(raw).strip()).secret
        except Exception:  # noqa: BLE001 — any unreadable URI is the same sentence
            raise VaultRefused("That one-time-code link could not be read.") from None
    if not re.fullmatch(r"[A-Z2-7]{16,128}=*", text):
        raise VaultRefused("A one-time-code secret is the base32 text (or otpauth:// link) the service showed.")
    return text


def _apply(sealed: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(sealed)
    for key, limit in (("username", USERNAME_MAX), ("secret", SECRET_MAX), ("notes", NOTES_MAX)):
        if key not in body:
            continue
        v = body.get(key)
        if v is None or v == "":
            out.pop(key, None)
            continue
        if not isinstance(v, str):
            raise VaultRefused(f"“{key}” is text.")
        if len(v) > limit:
            raise VaultRefused(f"“{key}” is at most {limit} characters.")
        if key == "username":
            v = v.strip()
        out[key] = v
    if "totp" in body:
        v = body.get("totp")
        if v in (None, ""):
            out.pop("totp", None)
        else:
            out["totp"] = _clean_totp(v)
    return out


def create(db, owner: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
    from core.database import VaultItem
    acct = account(owner)
    if is_locked(db, owner):
        raise VaultRefused(LOCKED_SENTENCE.replace(" Nothing was filled.", ""), 423)
    kind = body.get("kind") or "login"
    if kind not in KINDS:
        raise VaultRefused(f"“kind” is one of {', '.join(KINDS)}.")
    label = _clean_label(body.get("label"))
    addresses = _clean_addresses(body.get("addresses"))
    if kind == "login" and not addresses:
        raise VaultRefused("A login needs the address it is for, such as grafana.lan or https://example.org.")
    use = body.get("use") or "ask"
    if use not in USES:
        raise VaultRefused(f"“use” is one of {', '.join(USES)}.")
    rows = _rows(db, acct)
    if len(rows) >= ITEMS_MAX:
        raise VaultRefused(f"A vault holds at most {ITEMS_MAX} items.")
    if any(r.label.lower() == label.lower() for r in rows):
        raise VaultRefused(f"You already have an item named “{label}”.", 409)
    sealed = _apply({}, body)
    if kind == "login" and not sealed.get("secret"):
        raise VaultRefused("A login needs its password.")
    f = _fernet(db, acct, create=True)
    row = VaultItem(id=uuid.uuid4().hex, account=acct, kind=kind, label=label,
                    addresses=json.dumps(addresses), sealed=_seal(f, sealed),
                    agent_account=bool(body.get("agent_account")), use=use)
    db.add(row)
    db.commit()
    touch(db, owner)
    return public(row, sealed)


def update(db, owner: Optional[str], item_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    acct = account(owner)
    if is_locked(db, owner):
        raise VaultRefused(LOCKED_SENTENCE.replace(" Nothing was filled.", ""), 423)
    row = _find(db, acct, item_id)
    if row is None or row.id != item_id:
        raise VaultRefused("There is no such item in your vault.", 404)
    f = _fernet(db, acct, create=True)
    sealed = _apply(_open(f, row.sealed), body)
    if "label" in body:
        label = _clean_label(body.get("label"))
        if any(r.id != row.id and r.label.lower() == label.lower() for r in _rows(db, acct)):
            raise VaultRefused(f"You already have an item named “{label}”.", 409)
        row.label = label
    if "addresses" in body:
        addresses = _clean_addresses(body.get("addresses"))
        if row.kind == "login" and not addresses:
            raise VaultRefused("A login needs the address it is for.")
        row.addresses = json.dumps(addresses)
    if "use" in body:
        if body.get("use") not in USES:
            raise VaultRefused(f"“use” is one of {', '.join(USES)}.")
        row.use = body["use"]
    if "agent_account" in body:
        row.agent_account = bool(body.get("agent_account"))
    if row.kind == "login" and not sealed.get("secret"):
        raise VaultRefused("A login needs its password.")
    row.sealed = _seal(f, sealed)
    db.commit()
    touch(db, owner)
    return public(row, sealed)


def remove(db, owner: Optional[str], item_id: str) -> None:
    row = _find(db, account(owner), item_id)
    if row is None or row.id != item_id:
        raise VaultRefused("There is no such item in your vault.", 404)
    db.delete(row)
    db.commit()
    touch(db, owner)


def reveal(db, owner: Optional[str], item_id: str) -> Dict[str, Any]:
    """The person's own look at an item, after the caller checked their
    password. Logged (who and which, never what)."""
    acct = account(owner)
    row = _find(db, acct, item_id)
    if row is None or row.id != item_id:
        raise VaultRefused("There is no such item in your vault.", 404)
    sealed = _open(_fernet(db, acct, create=True), row.sealed)
    logger.info("vault: %s revealed item %s", acct, row.id)
    touch(db, owner)
    return {"username": sealed.get("username") or "", "secret": sealed.get("secret") or "",
            "totp": sealed.get("totp") or "", "notes": sealed.get("notes") or ""}


# ── using ───────────────────────────────────────────────────────────────────

def for_use(db, owner: Optional[str], ref: Any, *, by: str = "agent") -> Dict[str, Any]:
    """The values, for the daemon or a command's environment — the one place
    the agent's side opens a sealed blob. Raises a sentence that names
    nothing secret: the item it could not find, the labels it could."""
    acct = account(owner)
    row = _find(db, acct, ref)
    if row is None:
        names = labels(db, owner)
        have = ("Your vault has: " + ", ".join(f"“{n}”" for n in names[:30]) + ".") if names \
            else "Your vault is empty; the person adds logins in Settings → Vault."
        raise VaultRefused(f"There is no item “{str(ref)[:80]}” in the vault. {have}", 404)
    if is_locked(db, owner):
        raise VaultRefused(LOCKED_SENTENCE, 423)
    sealed = _open(_fernet(db, acct, create=True), row.sealed)
    otp = ""
    if sealed.get("totp"):
        import pyotp
        otp = pyotp.TOTP(sealed["totp"]).now()
    row.last_used_at = datetime.utcnow()
    row.last_used_by = str(by or "agent")[:80]
    db.commit()
    logger.info("vault: %s item %s used by %s", acct, row.id, row.last_used_by)
    return {"id": row.id, "label": row.label, "kind": row.kind,
            "origins": json.loads(row.addresses or "[]"),
            "username": sealed.get("username") or "", "secret": sealed.get("secret") or "",
            "otp": otp, "use": row.use if row.use in USES else "ask"}


def scrub(text: str, values: List[str]) -> str:
    """`text` with every value of an item replaced — for a command's output
    (`P27-07`) and any error a page or a tool echoes back."""
    out = str(text or "")
    for v in sorted({v for v in values if v and len(v) >= 3}, key=len, reverse=True):
        out = out.replace(v, "••••")
    return out
