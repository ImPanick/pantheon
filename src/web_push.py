# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web Push to a person's own phone and desktop, even with Pantheon closed.

`B1830`. The browser hands Pantheon a *subscription* — an address at the push
service its maker runs (Google's for Chrome and Android, Mozilla's for Firefox,
Apple's for Safari, Microsoft's for Edge on Windows) plus two keys. Pantheon
encrypts each message to those keys (RFC 8291, `aes128gcm`) and signs a short
token with its own key (VAPID, RFC 8292), so the push service carries bytes it
cannot read and can tell only that the same server sent them.

`Law 16`, asked the way the law asks it — *who owns the address at the other
end?* Nothing is sent until a person turns push on for a device, and the
address is the one that person's own browser chose. A fresh install talks to
no push service at all.

`Law 17`, the adversary: somebody with an account on a shared install who
registers a "subscription" whose endpoint is a box on the operator's network,
so that the server POSTs to it. That is why an endpoint must be `https` on a
push service's host (`PUSH_SERVICE_HOSTS`, widened by `PANTHEON_PUSH_HOSTS`
for an operator who runs their own) — never a free-form URL.

What is stored, in the data volume and nowhere else:

  push_vapid.json          the server's signing key, made on first use, 0600.
                           Losing it unsubscribes every device, so the write
                           is guarded (`check-config-writes.py`).
  push_subscriptions.json  each person's devices: endpoint, keys, a label.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import struct
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from core.atomic_io import atomic_write_json
from src.constants import DATA_DIR

logger = logging.getLogger(__name__)

VAPID_FILE = os.path.join(DATA_DIR, "push_vapid.json")
SUBSCRIPTIONS_FILE = os.path.join(DATA_DIR, "push_subscriptions.json")

# The push services the four browser makers run. A subscription's endpoint must
# be on one of these (or a host the operator adds), over https.
PUSH_SERVICE_HOSTS = (
    "fcm.googleapis.com",            # Chrome, Android, Brave, Opera, Samsung Internet
    "push.services.mozilla.com",     # Firefox (updates.push.services.mozilla.com)
    "notify.windows.com",            # Edge on Windows (*.notify.windows.com)
    "push.apple.com",                # Safari, iOS home-screen apps (web.push.apple.com)
)
PUSH_HOSTS_ENV = "PANTHEON_PUSH_HOSTS"
PUSH_CONTACT_ENV = "PANTHEON_PUSH_CONTACT"

MAX_DEVICES_PER_PERSON = 20
# RFC 8291 allows a 4096-byte record; 103 of it is the header and tag. The
# rest is generous for a title, a line and a few ids.
MAX_PAYLOAD_BYTES = 3000
RECORD_SIZE = 4096
DEFAULT_TTL_SECONDS = 60 * 60
# The notification's picture. Sent with each message so `static/sw.js` names
# no static file of its own (its precache lists are derived, `B86`).
PUSH_ICON = "/static/icons/icon-192.png"
TOKEN_LIFETIME_SECONDS = 12 * 60 * 60

_lock = threading.RLock()


class PushError(ValueError):
    """A subscription or message Pantheon refuses, in words a person can act on."""


# ── base64url ─────────────────────────────────────────────────────────────────

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    text = str(text or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ── the server's key (VAPID) ──────────────────────────────────────────────────

def _read_json(path: str) -> Optional[dict]:
    """`None` when the file does not exist; raises when it exists and is unreadable,
    so a corrupt key file is never silently replaced by a new key."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    if not isinstance(data, dict):
        raise PushError(f"{os.path.basename(path)} is not a JSON object")
    return data


def _private_key_from_pem(pem: str):
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(pem.encode("ascii"), password=None)


def _public_bytes(private_key) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def vapid_keys() -> Dict[str, Any]:
    """`{"private": key, "public": b64url}` — made and saved on first use."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    with _lock:
        data = _read_json(VAPID_FILE)
        if data and data.get("private_pem"):
            private_key = _private_key_from_pem(str(data["private_pem"]))
            return {"private": private_key, "public": b64url(_public_bytes(private_key))}
        private_key = ec.generate_private_key(ec.SECP256R1())
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")
        public = b64url(_public_bytes(private_key))
        atomic_write_json(VAPID_FILE, {
            "private_pem": pem,
            "public_key": public,
            "created_at": int(time.time()),
        }, indent=2, preserve_unreadable=True)
        try:
            os.chmod(VAPID_FILE, 0o600)
        except OSError:
            pass  # a filesystem without modes (a Windows bind mount) keeps the key all the same
        logger.info("Web Push: made this server's signing key (%s)", VAPID_FILE)
        return {"private": private_key, "public": public}


def public_key() -> str:
    return vapid_keys()["public"]


def _contact() -> str:
    """The `sub` claim: who a push service can write to about this sender.
    Apple refuses a token without a real `mailto:` or `https:` one."""
    configured = str(os.getenv(PUSH_CONTACT_ENV) or "").strip()
    if configured.startswith(("mailto:", "https://")):
        return configured
    try:
        from src.public_origin import public_origin
        origin = str(public_origin() or "").strip()
        if origin.startswith("https://"):
            return origin
    except Exception:
        pass  # no public origin to name: the project's page below is the contact
    return "https://github.com/ImPanick/pantheon"


def vapid_header(endpoint: str, *, now: Optional[float] = None) -> str:
    """`Authorization: vapid t=<ES256 JWT>, k=<public key>` for this endpoint."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    keys = vapid_keys()
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int((now if now is not None else time.time()) + TOKEN_LIFETIME_SECONDS),
        "sub": _contact(),
    }
    header = {"typ": "JWT", "alg": "ES256"}
    signing_input = (
        b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    der = keys["private"].sign(signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"vapid t={signing_input}.{b64url(signature)}, k={keys['public']}"


# ── the message (RFC 8291) ────────────────────────────────────────────────────

def encrypt(payload: bytes, p256dh: str, auth: str, *,
            salt: Optional[bytes] = None, sender_private=None) -> bytes:
    """One `aes128gcm` record for the subscription's keys.

    `salt` and `sender_private` are for the RFC's own test vector; a real send
    makes both fresh every time."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    ua_public = b64url_decode(p256dh)
    auth_secret = b64url_decode(auth)
    if len(ua_public) != 65 or ua_public[0] != 4:
        raise PushError("The device's key is not a P-256 public key.")
    if len(auth_secret) != 16:
        raise PushError("The device's auth secret is not 16 bytes.")
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise PushError("The message is too long for a push.")

    sender_private = sender_private or ec.generate_private_key(ec.SECP256R1())
    as_public = _public_bytes(sender_private)
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    ecdh_secret = sender_private.exchange(ec.ECDH(), receiver)

    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth_secret,
               info=b"WebPush: info\x00" + ua_public + as_public).derive(ecdh_secret)
    salt = salt if salt is not None else secrets.token_bytes(16)
    cek = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt,
               info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt,
                 info=b"Content-Encoding: nonce\x00").derive(ikm)
    # One record, so it is the last: the delimiter is 0x02 and no padding.
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public + ciphertext


# ── subscriptions ─────────────────────────────────────────────────────────────

def _normalized_owner(owner: Any) -> str:
    # The approval store's spelling (`tool_approvals._normalized_owner`), so a
    # card's owner finds the devices its person turned on.
    return str(owner or "").strip().casefold()


def allowed_hosts() -> tuple:
    extra = tuple(
        h.strip().lower().lstrip(".")
        for h in str(os.getenv(PUSH_HOSTS_ENV) or "").split(",")
        if h.strip()
    )
    return PUSH_SERVICE_HOSTS + extra


def check_endpoint(endpoint: Any) -> str:
    endpoint = str(endpoint or "").strip()
    if len(endpoint) > 2048:
        raise PushError("That push address is too long.")
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise PushError("A push address must be an https address at a push service.")
    if parts.port not in (None, 443):
        raise PushError("A push address must be on the standard https port.")
    if not any(host == h or host.endswith("." + h) for h in allowed_hosts()):
        raise PushError(
            f"{host} is not a push service Pantheon knows. An operator who runs "
            f"their own can add it to {PUSH_HOSTS_ENV}."
        )
    return endpoint


def _load_subscriptions() -> List[dict]:
    data = _read_json(SUBSCRIPTIONS_FILE) or {}
    rows = data.get("subscriptions")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _save_subscriptions(rows: List[dict]) -> None:
    atomic_write_json(SUBSCRIPTIONS_FILE, {"subscriptions": rows},
                      indent=2, preserve_unreadable=True)
    try:
        os.chmod(SUBSCRIPTIONS_FILE, 0o600)
    except OSError:
        pass  # as for the key: the list is saved either way


def _public_row(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "label": row.get("label") or "This device",
        "endpoint": row.get("endpoint"),
        "created_at": row.get("created_at"),
        "last_sent_at": row.get("last_sent_at"),
        "last_status": row.get("last_status"),
    }


def list_devices(owner: Any) -> List[dict]:
    who = _normalized_owner(owner)
    with _lock:
        return [_public_row(r) for r in _load_subscriptions() if r.get("owner") == who]


def subscribe(owner: Any, subscription: Any, *, label: Any = "") -> dict:
    """Save (or refresh) one device for one person. The endpoint is the key: a
    browser that re-subscribes replaces its row, and a browser somebody else
    signs in on and turns push on in becomes theirs — the endpoint is a secret
    only that browser holds, so whoever sends it is at that browser."""
    who = _normalized_owner(owner)
    if not who:
        raise PushError("Sign in to turn on push.")
    if not isinstance(subscription, dict):
        raise PushError("That is not a push subscription.")
    endpoint = check_endpoint(subscription.get("endpoint"))
    keys = subscription.get("keys") if isinstance(subscription.get("keys"), dict) else {}
    p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
    try:
        if len(b64url_decode(p256dh)) != 65 or len(b64url_decode(auth)) != 16:
            raise ValueError
    except (ValueError, TypeError):
        raise PushError("That subscription's keys are not a browser's push keys.")
    label = str(label or "").strip()[:60] or "This device"
    with _lock:
        rows = _load_subscriptions()
        rows = [r for r in rows if r.get("endpoint") != endpoint]
        mine = [r for r in rows if r.get("owner") == who]
        if len(mine) >= MAX_DEVICES_PER_PERSON:
            raise PushError(
                f"Push is on for {MAX_DEVICES_PER_PERSON} devices already. "
                "Remove one in Settings first."
            )
        row = {
            "id": secrets.token_urlsafe(9),
            "owner": who,
            "endpoint": endpoint,
            "p256dh": p256dh,
            "auth": auth,
            "label": label,
            "created_at": int(time.time()),
            "last_sent_at": None,
            "last_status": None,
        }
        rows.append(row)
        _save_subscriptions(rows)
    return _public_row(row)


def unsubscribe(owner: Any, *, device_id: Any = None, endpoint: Any = None) -> bool:
    who = _normalized_owner(owner)
    with _lock:
        rows = _load_subscriptions()
        kept = [
            r for r in rows
            if not (r.get("owner") == who and (
                (device_id and r.get("id") == device_id)
                or (endpoint and r.get("endpoint") == endpoint)
            ))
        ]
        if len(kept) == len(rows):
            return False
        _save_subscriptions(kept)
        return True


def _note_result(endpoint: str, status: int, *, drop: bool) -> None:
    with _lock:
        rows = _load_subscriptions()
        if drop:
            kept = [r for r in rows if r.get("endpoint") != endpoint]
        else:
            kept = rows
            for r in rows:
                if r.get("endpoint") == endpoint:
                    r["last_sent_at"] = int(time.time())
                    r["last_status"] = status
        _save_subscriptions(kept)


# ── sending ───────────────────────────────────────────────────────────────────

async def _send_one(row: dict, body: bytes, *, ttl: int, urgency: str) -> dict:
    from src import paced_http

    endpoint = row["endpoint"]
    try:
        check_endpoint(endpoint)
        record = encrypt(body, row["p256dh"], row["auth"])
        response = await paced_http.post(
            endpoint,
            content=record,
            timeout=15.0,
            headers={
                "Authorization": vapid_header(endpoint),
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(max(0, int(ttl))),
                "Urgency": urgency,
            },
        )
        status = int(getattr(response, "status_code", 0) or 0)
    except Exception as exc:  # a device that cannot be reached is not the others' problem
        logger.warning("Web Push to %s failed: %s", urlsplit(endpoint).hostname, exc)
        return {"id": row.get("id"), "label": row.get("label"), "ok": False,
                "status": 0, "error": str(exc)[:200]}
    # 404 and 410 are the push service saying the browser unsubscribed (or the
    # site's permission was taken away): the row is dead, so it goes.
    gone = status in (404, 410)
    try:
        _note_result(endpoint, status, drop=gone)
    except Exception:
        logger.exception("Web Push: could not record the result for a device")
    ok = 200 <= status < 300
    result = {"id": row.get("id"), "label": row.get("label"), "ok": ok, "status": status}
    if gone:
        result["error"] = "This device turned push off; it has been removed."
    elif not ok:
        result["error"] = f"The push service answered {status}."
    return result


async def send_to_owner(owner: Any, message: Dict[str, Any], *,
                        ttl: int = DEFAULT_TTL_SECONDS, urgency: str = "normal",
                        device_id: Any = None) -> List[dict]:
    """Push `message` (a JSON object the service worker reads) to every device
    this person turned on, or to one of them. Returns one result per device."""
    import asyncio

    who = _normalized_owner(owner)
    if not who:
        return []
    message = {"icon": PUSH_ICON, **message}
    body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_PAYLOAD_BYTES:
        raise PushError("The message is too long for a push.")
    with _lock:
        rows = [r for r in _load_subscriptions() if r.get("owner") == who
                and (not device_id or r.get("id") == device_id)]
    if not rows:
        return []
    return list(await asyncio.gather(*(
        _send_one(r, body, ttl=ttl, urgency=urgency) for r in rows
    )))


def has_devices(owner: Any) -> bool:
    who = _normalized_owner(owner)
    if not who:
        return False
    try:
        with _lock:
            return any(r.get("owner") == who for r in _load_subscriptions())
    except Exception:
        return False


# ── a tool approval, on the lock screen ───────────────────────────────────────

def _tool_words(tool_name: str) -> str:
    try:
        from src.tool_map import brief
        line = brief(tool_name).split(" · ")[0].strip()
    except Exception:
        line = ""
    return line or tool_name.replace("_", " ")


def approval_message(pending: Any) -> Dict[str, Any]:
    """What the service worker draws for a card: the tool in a few words, the
    first line of what it would do, and whether the notification may answer.

    A workflow run's question (`held_by_run`, `B1103`) is answered from the
    run's own surfaces, not the chat route, so its notification only opens
    Pantheon."""
    tool = str(getattr(pending, "tool_name", "") or "tool")
    content = str(getattr(pending, "content", "") or "")
    first = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
    if len(first) > 140:
        first = first[:139] + "…"
    words = _tool_words(tool)
    approval_id = str(getattr(pending, "approval_id", "") or "")
    return {
        "type": "tool_approval",
        "title": "Pantheon is asking before it acts",
        "body": f"{words}: {first}" if first else words,
        "tool": tool,
        "approval_id": approval_id,
        "session_id": str(getattr(pending, "session_id", "") or ""),
        "can_answer": not bool(getattr(pending, "held_by_run", False)),
        "expires_at": int(getattr(pending, "expires_at", 0) or 0),
        "tag": f"approval-{approval_id[:16]}",
    }


def _run_soon(coro) -> None:
    """Fire and forget, from the agent's loop when there is one."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        task = loop.create_task(coro)
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)
        return
    threading.Thread(target=asyncio.run, args=(coro,), daemon=True,
                     name="web-push").start()


_pending_tasks: set = set()


async def _push_approval(pending: Any) -> None:
    try:
        ttl = max(30, int(float(getattr(pending, "expires_at", 0) or 0) - time.time()))
        await send_to_owner(getattr(pending, "owner", ""), approval_message(pending),
                            ttl=ttl, urgency="high")
    except Exception:
        logger.exception("Web Push: could not send a tool approval")


def on_approval_created(pending: Any) -> None:
    """`tool_approvals` listener: a card that waits on a person reaches their
    devices. Cards with no chat (the skill tester's) have nowhere to answer."""
    if not getattr(pending, "session_id", "") or not has_devices(getattr(pending, "owner", "")):
        return
    _run_soon(_push_approval(pending))


def install() -> None:
    from src.tool_approvals import register_approval_created_listener
    register_approval_created_listener(on_approval_created)
