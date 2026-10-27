# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P27-04` · Pantheon's side of a person's mapped names and pinned
certificates. `D-2026-10-24-03`.

The vault keeps them on each login (`VaultItem.mapped`, `VaultItem.pins`);
this module gathers the person's whole set, sends it to their workstation
(`ROUTES["names"]`, `workstation/names.py`) when it changed, and says what a
command run there should be given — the person's own proxy and the trusted
file (`env_for`). The browser picks the set up from its profile when it next
starts; the daemon restarts it on a change.

**Testing a login** (`test`) asks, from the workstation, the questions a person
needs answered before mapping or pinning anything: does the name resolve on
their network already (then nothing is mapped); does the address answer (through
the proxy when mapped); and for HTTPS, which certificate the server shows — its
SHA-256 fingerprint, subject, whether it signed itself, and whether the
workstation already trusts it. **Pinning** (`pin`) fetches it again and keeps
it only when its fingerprint is the one the person confirmed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()
_sent: Dict[str, Dict[str, Any]] = {}    # account -> {"digest", "answer"}


def wanted(db, owner: Optional[str]) -> Dict[str, Any]:
    """The person's whole set: every login's mapped names, every pin."""
    from src import vault as V
    names: Dict[str, str] = {}
    pins = []
    for row in V._rows(db, V.account(owner)):
        names.update(V.mapped(row))
        for origin, p in sorted(V.pinned(row).items()):
            if p.get("pem"):
                pins.append({"origin": origin, "pem": p["pem"]})
    return {"map": dict(sorted(names.items())), "pins": pins}


async def with_db(db, fn):
    """`fn(session)`: in the caller's session when one is given, otherwise in
    a session of its own, off the event loop (`B1223`) — so a route never
    holds one open across a probe of the person's network."""
    if db is not None:
        return fn(db)

    def work():
        from core.database import SessionLocal
        own = SessionLocal()
        try:
            return fn(own)
        except Exception:
            own.rollback()
            raise
        finally:
            own.close()
    return await asyncio.to_thread(work)


def _digest(body: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


async def sync(client, account: str, owner: Optional[str], *, force: bool = False) -> Dict[str, Any]:
    """Send the set when it changed since it was last sent. Answers what
    commands are given; `{}` when nothing is mapped or pinned."""
    body = await with_db(None, lambda db: wanted(db, owner))   # `B1223`: off the event loop
    digest = _digest(body)
    with _cache_lock:
        last = _sent.get(account)
    if last and last["digest"] == digest and not force:
        return last["answer"]
    if not body["map"] and not body["pins"] and not last:
        return {}
    answer = await client.names(account, body["map"], body["pins"])
    with _cache_lock:
        _sent[account] = {"digest": digest, "answer": answer}
    return answer


def forget(account: str) -> None:
    with _cache_lock:
        _sent.pop(account, None)


def env_for(answer: Dict[str, Any]) -> Dict[str, str]:
    """What a command is given: the person's proxy (it forwards every host,
    mapped ones to their address, as the person) and the trusted file."""
    env: Dict[str, str] = {}
    proxy = (answer or {}).get("proxy")
    if proxy:
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            env[k] = proxy
        env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1,::1"
    ca = (answer or {}).get("ca_file")
    if ca:
        for k in ("SSL_CERT_FILE", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "GIT_SSL_CAINFO", "NODE_EXTRA_CA_CERTS"):
            env[k] = ca
    return env


# ── testing a login, and pinning what it shows ──────────────────────────────

# Run in the workstation with the standard library only. Arguments: host,
# port, scheme, mapped address or "", proxy url or "", trusted file or "".
_PROBE = r'''
import hashlib, json, socket, ssl, sys, urllib.request
host, port, scheme, mapped, proxy, cafile = sys.argv[1:7]
port = int(port)
out = {"host": host, "port": port}
try:
    out["dns"] = sorted({a[4][0] for a in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)})[:4]
except OSError as e:
    out["dns"] = []
    out["dns_error"] = str(e)[:160]
target = mapped or (out["dns"][0] if out["dns"] else "")
if scheme == "https" and target:
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((target, port), timeout=8) as s:
            with ctx.wrap_socket(s, server_hostname=host) as t:
                der = t.getpeercert(binary_form=True)
        pem = ssl.DER_cert_to_PEM_cert(der)
        out["cert"] = {"sha256": ":".join(f"{b:02X}" for b in hashlib.sha256(der).digest()), "pem": pem}
        try:
            import subprocess
            info = subprocess.run(["openssl", "x509", "-noout", "-subject", "-issuer"], input=pem,
                                  capture_output=True, text=True, timeout=5).stdout
            lines = dict(l.split("=", 1) for l in info.strip().splitlines() if "=" in l)
            out["cert"]["subject"] = lines.get("subject", "").strip()[:200]
            out["cert"]["self_signed"] = lines.get("subject", "").strip() == lines.get("issuer", "").strip()
        except Exception:
            out["cert"]["subject"] = ""
        try:
            v = ssl.create_default_context(cafile=cafile or None)
            with socket.create_connection((target, port), timeout=8) as s:
                with v.wrap_socket(s, server_hostname=host):
                    out["cert"]["trusted"] = True
        except (ssl.SSLError, OSError) as e:
            out["cert"]["trusted"] = False
            out["cert"]["why"] = str(e)[:200]
    except OSError as e:
        out["tls_error"] = str(e)[:200]
try:
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})]
    if scheme == "https":
        c = ssl.create_default_context(cafile=cafile or None)
        if not out.get("cert", {}).get("trusted"):
            c.check_hostname = False
            c.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=c))
    opener = urllib.request.build_opener(*handlers)
    url = f"{scheme}://{host}:{port}/"
    try:
        r = opener.open(urllib.request.Request(url, method="GET"), timeout=10)
        out["http"] = r.status
    except urllib.error.HTTPError as e:
        out["http"] = e.code
except Exception as e:
    out["http_error"] = str(e)[:200]
print(json.dumps(out))
'''


async def _probe(owner: Optional[str], origin: str, mapped_to: str) -> Dict[str, Any]:
    from src.agent_tools.git_tools import _Place
    from src.vault import VaultRefused
    parts = urlsplit(origin)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    place = _Place(owner, None)
    refused = await place.open()
    if refused is not None:
        raise VaultRefused(refused.get("error") or "Your workstation did not answer.", 503)
    if not place.in_workstation:
        from src.tool_security import blocked_tools_for_owner
        if "bash" in blocked_tools_for_owner(owner):
            raise VaultRefused("Testing a login runs from your workstation, and this account has none turned "
                               "on. Ask an admin for one.", 409)
    proxy = place.names_env.get("HTTP_PROXY", "") if mapped_to else ""
    cafile = place.names_env.get("SSL_CERT_FILE", "")
    import shlex
    command = "python3 -c " + shlex.quote(_PROBE) + " " + " ".join(
        shlex.quote(a) for a in (host, str(port), parts.scheme, mapped_to, proxy, cafile))
    r = await place.run(command, place.base(), {}, 40.0)
    try:
        return json.loads((r.get("stdout") or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise VaultRefused(f"The test did not run: {(r.get('stderr') or 'no answer').strip()[-200:]}", 502) \
            from None


async def test(db, owner: Optional[str], item_id: str) -> Dict[str, Any]:
    """What a person reads before mapping or pinning: per address, whether
    the name resolves on their network, whether it answers, and which
    certificate it shows. `db` None: the item is read in a session of its own,
    off the event loop (`with_db`)."""
    from src import vault as V

    def read(session):
        row = V._find(session, V.account(owner), item_id)
        if row is None or row.id != item_id:
            raise V.VaultRefused("There is no such item in your vault.", 404)
        return row.id, row.label, V.mapped(row), V.pinned(row), json.loads(row.addresses or "[]")
    row_id, label, names, pins, addresses = await with_db(db, read)
    out = []
    for origin in addresses[:4]:
        host = urlsplit(origin).hostname or ""
        got = await _probe(owner, origin, names.get(host, ""))
        cert = got.get("cert")
        if cert:
            pin = pins.get(origin)
            cert["pinned"] = bool(pin and pin.get("sha256") == cert["sha256"])
            cert["changed"] = bool(pin and pin.get("sha256") != cert["sha256"])
            cert.pop("pem", None)
        out.append({"origin": origin, "mapped_to": names.get(host) or None, **got})
    return {"id": row_id, "label": label, "results": out}


async def pin(db, owner: Optional[str], item_id: str, origin: str, sha256: str) -> Dict[str, Any]:
    """Keep the certificate `origin` shows now, if it is the one the person
    confirmed by its fingerprint (`D-2026-10-24-03` §3). `db` None: the item
    is read and written in sessions of its own, off the event loop."""
    from src import vault as V

    def find(session):
        row = V._find(session, V.account(owner), item_id)
        if row is None or row.id != item_id:
            raise V.VaultRefused("There is no such item in your vault.", 404)
        return row

    def read(session):
        row = find(session)
        if origin not in json.loads(row.addresses or "[]") or not origin.startswith("https://"):
            raise V.VaultRefused("Pin a certificate for one of this login's https addresses.")
        return V.mapped(row).get(urlsplit(origin).hostname or "", "")
    mapped_to = await with_db(db, read)
    got = await _probe(owner, origin, mapped_to)
    cert = got.get("cert") or {}
    if not cert.get("pem"):
        raise V.VaultRefused(f"{origin} showed no certificate: {got.get('tls_error') or 'no answer'}.", 502)
    if cert["sha256"] != str(sha256 or "").strip().upper():
        raise V.VaultRefused(f"{origin} now shows a different certificate ({cert['sha256'][:23]}…) from the one "
                             "you confirmed. Test it again and look before trusting it.", 409)

    def write(session):
        row = find(session)
        pins = V.pinned(row)
        pins[origin] = {"sha256": cert["sha256"], "pem": cert["pem"], "subject": cert.get("subject", "")}
        row.pins = json.dumps(pins)
        session.commit()
        return V.public(row)
    kept = await with_db(db, write)
    logger.info("vault: %s pinned a certificate for %s", V.account(owner), origin)
    return kept


def unpin(db, owner: Optional[str], item_id: str, origin: str) -> Dict[str, Any]:
    from src import vault as V
    row = V._find(db, V.account(owner), item_id)
    if row is None or row.id != item_id:
        raise V.VaultRefused("There is no such item in your vault.", 404)
    pins = V.pinned(row)
    pins.pop(origin, None)
    row.pins = json.dumps(pins)
    db.commit()
    return V.public(row)
