# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P27-10` · Bring logins into a person's own vault, and take them out.

**In.** A Bitwarden or Vaultwarden export — its JSON (not encrypted) or its
CSV, the two shapes both write — or a file this module exported, with the
passphrase it was sealed with; or, for an admin, the items of the server's
Bitwarden link (`routes/vault/`, `bw list items`). Every item lands in the
caller's own vault and nowhere else: the account is the caller's
(`vault.account`), never a field of the file, and nothing here takes a second
account (`Law 17`: the adversary is a file — or a person — trying to put items
in somebody else's vault, or to read theirs).

What becomes what:

* a login with a web address → a *login* at those addresses;
* a login with no web address (a Wi-Fi password, an app's) → a *key*: a
  command may use it by name, the browser cannot sign in with it, and the
  report says so;
* a secure note → a *note*; an SSH key → a *key* holding the private key;
* a card or an identity → left out, said by name: not something an agent signs
  in with.

Custom fields go into the item's sealed notes, so nothing the file held is
dropped silently. A name already in the vault for the same addresses and user
name is the same login, and is not brought in twice; a name taken by a
different one is brought in as *Name (2)*. Everything is checked before
anything is written, and written in one transaction.

**Out.** The caller's own items, as Bitwarden's unencrypted JSON shape (so the
file, opened, is a Bitwarden import), sealed whole — names and addresses
included — with AES-256-GCM under a key scrypt derives from a passphrase the
person types. The server keeps neither the passphrase nor the key; without
the passphrase the file is the count of items and the day it was made. The
envelope's parameters are bound into the seal, so a file whose parameters were
changed does not open either. The cryptography is the `cryptography` package
the vault already uses (`Fernet`); no new dependency.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src import vault as V

logger = logging.getLogger(__name__)

FORMAT = "pantheon_vault_export"
FORMAT_VERSION = 1
PASSPHRASE_MIN = 12
PASSPHRASE_MAX = 1024
# scrypt at OWASP's floor for it (N=2^17, r=8, p=1: 128 MiB, about a second).
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 17, 8, 1
# What an export's own header may ask of this server when it is opened: at
# least the floor above's quarter, at most 1 GiB — a file cannot make an
# import spend more than that.
SCRYPT_N_RANGE = (2 ** 15, 2 ** 20)
TEXT_MAX = 16 * 1024 * 1024

BITWARDEN_TYPES = {1: "login", 2: "note", 3: "card", 4: "identity", 5: "ssh"}
LEFT_OUT = {"card": "a card is not something an agent signs in with",
            "identity": "an identity is not something an agent signs in with"}


class TransferRefused(V.VaultRefused):
    pass


# ── reading a file into one shape ───────────────────────────────────────────
#
# Every source becomes a list of Bitwarden-shaped items (`bw list items` and
# the JSON export already are), so there is one mapping into the vault.

def _sniff(text: str) -> str:
    head = text.lstrip("﻿ \t\r\n")[:1]
    return "json" if head in ("{", "[") else "csv"


def _from_json(text: str) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """`(items, envelope)` — `envelope` is this module's own sealed export,
    to be opened with a passphrase first."""
    try:
        doc = json.loads(text.lstrip("﻿"))
    except ValueError:
        raise TransferRefused("That file is not JSON Pantheon can read. Export it from Bitwarden or "
                              "Vaultwarden as “.json” or “.csv”.") from None
    if isinstance(doc, dict) and doc.get(FORMAT):
        return [], doc
    if isinstance(doc, list):
        return [i for i in doc if isinstance(i, dict)], None
    if not isinstance(doc, dict):
        raise TransferRefused("That JSON is not an export of logins.")
    if doc.get("encrypted"):
        if doc.get("passwordProtected"):
            raise TransferRefused("This is Bitwarden's password-protected export, which Pantheon cannot open. "
                                  "Export again as “.json” (not encrypted) or “.csv”, bring that in, then "
                                  "delete the file.")
        raise TransferRefused("This export is encrypted to the Bitwarden account that made it, so nothing "
                              "else can read it. Export again as “.json” (not encrypted) or “.csv”.")
    items = doc.get("items")
    if not isinstance(items, list):
        raise TransferRefused("That JSON has no “items”: it is not a Bitwarden or Vaultwarden export.")
    return [i for i in items if isinstance(i, dict)], None


def _split_uris(raw: str) -> List[str]:
    return [u.strip() for u in re.split(r"[,\n]", raw or "") if u.strip()]


def _from_csv(text: str) -> List[Dict[str, Any]]:
    """Bitwarden's CSV (`folder,favorite,type,name,notes,fields,reprompt,
    login_uri,login_username,login_password,login_totp`; an organisation's has
    `collections` instead of the first two)."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    cols = {c.strip().lower() for c in (reader.fieldnames or [])}
    if not {"name", "login_password"} <= cols:
        raise TransferRefused("That CSV is not a Bitwarden or Vaultwarden export: it needs the columns "
                              "“name” and “login_password” (and “login_uri”, “login_username”).")
    out = []
    for row in reader:
        r = {str(k or "").strip().lower(): (v or "") for k, v in row.items()}
        kind = (r.get("type") or "login").strip().lower()
        fields = []
        for line in (r.get("fields") or "").splitlines():
            name, _, value = line.partition(": ")
            if name.strip():
                fields.append({"name": name.strip(), "value": value})
        item: Dict[str, Any] = {"name": r.get("name") or "", "notes": r.get("notes") or "", "fields": fields}
        if kind == "note":
            item["type"] = 2
        else:
            item["type"] = 1
            item["login"] = {"uris": [{"uri": u} for u in _split_uris(r.get("login_uri") or "")],
                             "username": r.get("login_username") or "",
                             "password": r.get("login_password") or "",
                             "totp": r.get("login_totp") or ""}
        out.append(item)
    return out


# ── one item, into the vault's shape ────────────────────────────────────────

def _notes_with_fields(item: Dict[str, Any], extra: str = "") -> str:
    notes = str(item.get("notes") or "")
    lines = []
    for f in item.get("fields") or []:
        if isinstance(f, dict) and str(f.get("name") or "").strip():
            lines.append(f"{str(f.get('name')).strip()}: {f.get('value') if f.get('value') is not None else ''}")
    if lines:
        notes = (notes + "\n\n" if notes else "") + "Fields:\n" + "\n".join(lines)
    if extra:
        notes = (notes + "\n\n" if notes else "") + extra
    return notes


def _shape(item: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """`(body for the vault, sentences)` — body None when the item is left
    out, the first sentence then saying why."""
    t = item.get("type")
    kind_bw = BITWARDEN_TYPES.get(t if isinstance(t, int) else -1) or (
        str(t).strip().lower() if isinstance(t, str) else "login")
    said: List[str] = []
    if kind_bw in LEFT_OUT:
        return None, [LEFT_OUT[kind_bw]]
    ours = item.get("pantheon") if isinstance(item.get("pantheon"), dict) else {}
    body: Dict[str, Any] = {"label": re.sub(r"\s+", " ", str(item.get("name") or "")).strip()[:V.LABEL_MAX]
                            or "Untitled"}
    if ours.get("use") in V.USES:
        body["use"] = ours["use"]
    if ours.get("agent_account") is True:
        body["agent_account"] = True
    if kind_bw == "note":
        body["kind"] = "note"
        body["notes"] = _notes_with_fields(item)
    elif kind_bw == "ssh":
        key = item.get("sshKey") or {}
        if not str(key.get("privateKey") or "").strip():
            return None, ["an SSH key with no private key in the file"]
        body["kind"] = "key"
        body["secret"] = str(key.get("privateKey"))
        pub = str(key.get("publicKey") or "").strip()
        body["notes"] = _notes_with_fields(item, f"Public key: {pub}" if pub else "")
    elif kind_bw == "login":
        login = item.get("login") or {}
        addresses: List[str] = []
        odd = []
        for u in login.get("uris") or []:
            raw = u.get("uri") if isinstance(u, dict) else u
            if not str(raw or "").strip():
                continue
            try:
                o = V.origin_of(raw)
            except V.VaultRefused:
                odd.append(str(raw)[:60])
                continue
            if o not in addresses:
                addresses.append(o)
        if odd:
            said.append(f"not a web address, left off: {', '.join(odd[:3])}")
        if len(addresses) > V.ADDRESSES_MAX:
            said.append(f"only its first {V.ADDRESSES_MAX} addresses were kept")
            addresses = addresses[:V.ADDRESSES_MAX]
        password = str(login.get("password") or "")
        if not password:
            return None, ["it has no password to keep"]
        body["kind"] = "login" if addresses and ours.get("kind") != "key" else "key"
        if body["kind"] == "key" and ours.get("kind") != "key":
            said.append("kept as a key: it has no web address, so a command can use it and the browser cannot")
        body["addresses"] = addresses
        body["username"] = str(login.get("username") or "").strip()
        body["secret"] = password
        totp = str(login.get("totp") or "").strip()
        if totp:
            try:
                body["totp"] = V._clean_totp(totp)
            except V.VaultRefused:
                said.append("its one-time-code secret is in a form Pantheon does not read, so it was left out")
        body["notes"] = _notes_with_fields(item)
    else:
        return None, [f"“{kind_bw}” is not a kind of item Pantheon keeps"]
    if len(body.get("username") or "") > V.USERNAME_MAX:
        return None, [f"its user name is longer than {V.USERNAME_MAX} characters"]
    if len(body.get("secret") or "") > V.SECRET_MAX:
        return None, [f"its secret is longer than {V.SECRET_MAX} characters"]
    if len(body.get("notes") or "") > V.NOTES_MAX:
        body["notes"] = body["notes"][:V.NOTES_MAX - 40] + "\n… (cut at the vault's limit)"
        said.append(f"its notes were cut to {V.NOTES_MAX} characters")
    if not body.get("notes"):
        body.pop("notes", None)
    return body, said


# ── bringing in ─────────────────────────────────────────────────────────────

def bring_in(db, owner: Optional[str], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every item into `owner`'s own vault, in one transaction. Answers what
    came in, what was the same as something already there, and what was left
    out and why — by name, never by value."""
    from core.database import VaultItem
    acct = V.account(owner)
    if V.is_locked(db, owner):
        raise TransferRefused("Your vault is locked. Unlock it, then bring the file in again. "
                              "Nothing was brought in.", 423)
    f = V._fernet(db, acct, create=True)
    existing = V._rows(db, acct)
    # The same login is known by what it is, under its name or the *Name (2)*
    # an earlier import gave it — so bringing one file in twice adds nothing.
    def base(label: str) -> str:
        return re.sub(r" \(\d+\)$", "", label).lower()

    same_key: Dict[str, List[tuple]] = {}
    for r in existing:
        sealed = V._open(f, r.sealed)
        same_key.setdefault(base(r.label), []).append(
            (json.loads(r.addresses or "[]"), sealed.get("username") or "", sealed.get("secret") or "",
             sealed.get("notes") or ""))
    taken = {r.label.lower() for r in existing}
    room = V.ITEMS_MAX - len(existing)
    planned: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    report: Dict[str, Any] = {"imported": [], "already": [], "left_out": [], "said": []}
    for item in items:
        body, said = _shape(item)
        name = str(item.get("name") or "Untitled")[:V.LABEL_MAX]
        if body is None:
            report["left_out"].append({"name": name, "why": said[0]})
            continue
        label = body["label"]
        fingerprint = (body.get("addresses") or [], body.get("username") or "", body.get("secret") or "",
                       body.get("notes") or "")
        if fingerprint in same_key.get(base(label), []):
            report["already"].append(label)
            continue
        if label.lower() in taken:
            n = 2
            while f"{label[:V.LABEL_MAX - 6]} ({n})".lower() in taken:
                n += 1
            label = f"{label[:V.LABEL_MAX - 6]} ({n})"
            said.append(f"named “{label}”: you already have one called “{body['label']}”")
            body["label"] = label
        if len(planned) >= room:
            raise TransferRefused(f"A vault holds at most {V.ITEMS_MAX} items; you have {len(existing)}, and this "
                                  f"brings {len(planned) + 1} or more. Nothing was brought in.")
        taken.add(label.lower())
        same_key.setdefault(base(label), []).append(fingerprint)
        sealed = V._apply({}, {k: body[k] for k in ("username", "secret", "notes") if body.get(k)})
        if body.get("totp"):
            sealed["totp"] = body["totp"]
        planned.append((body, sealed))
        report["imported"].append(label)
        for s in said:
            report["said"].append({"name": label, "said": s})
    for body, sealed in planned:
        db.add(VaultItem(id=uuid.uuid4().hex, account=acct, kind=body["kind"], label=body["label"],
                         addresses=json.dumps(body.get("addresses") or []), sealed=V._seal(f, sealed),
                         agent_account=bool(body.get("agent_account")), use=body.get("use") or "ask",
                         agents="[]", mapped="{}", pins="{}"))
    db.commit()
    V.touch(db, owner)
    logger.info("vault: %s brought in %d item(s), %d already there, %d left out",
                acct, len(report["imported"]), len(report["already"]), len(report["left_out"]))
    return report


def read_file(text: Any, passphrase: Any = None) -> List[Dict[str, Any]]:
    """The items in an uploaded file: Bitwarden/Vaultwarden JSON or CSV, or
    this module's own export opened with `passphrase`."""
    if not isinstance(text, str) or not text.strip():
        raise TransferRefused("Pick a file to bring in: a Bitwarden or Vaultwarden export (.json or .csv), "
                              "or a Pantheon vault export.")
    if len(text) > TEXT_MAX:
        raise TransferRefused("That file is larger than 16 MB, so it was not read.", 413)
    if _sniff(text) == "csv":
        return _from_csv(text)
    items, envelope = _from_json(text)
    if envelope is not None:
        return open_export(envelope, passphrase)
    return items


async def server_bitwarden_items(owner: Optional[str]) -> List[Dict[str, Any]]:
    """The items of the server's Bitwarden link, for an admin — the same
    question `vault_get` is asked (`vault._bw_for_use`'s)."""
    from src.tool_security import blocked_tools_for_owner
    if "vault_get" in blocked_tools_for_owner(owner):
        raise TransferRefused("The server's Bitwarden link is an admin's. Export from your own Bitwarden "
                              "or Vaultwarden and bring the file in instead.", 403)
    from src.tools.vault import _load_vault_config, _run_bw
    session = _load_vault_config().get("session")
    if not session:
        raise TransferRefused("The server's Bitwarden link is not set up or is locked. An admin sets and "
                              "unlocks it in Workbench → MCP & Integrations.", 409)
    stdout, stderr, rc = await _run_bw(["list", "items"], session=session)
    if rc != 0:
        raise TransferRefused(f"Bitwarden said: {stderr.strip()[:200] or 'it could not list the items'}. "
                              "Nothing was brought in.", 502)
    try:
        items = json.loads(stdout)
    except ValueError:
        raise TransferRefused("Bitwarden's answer was not a list of items. Nothing was brought in.", 502) from None
    if not isinstance(items, list):
        raise TransferRefused("Bitwarden's answer was not a list of items. Nothing was brought in.", 502)
    return [i for i in items if isinstance(i, dict)]


# ── taking out ──────────────────────────────────────────────────────────────

def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: Any) -> bytes:
    try:
        return base64.b64decode(str(s), validate=True)
    except (ValueError, TypeError):
        raise TransferRefused("This export is damaged: a part of it is not what was written.") from None


def _check_passphrase(passphrase: Any) -> bytes:
    if not isinstance(passphrase, str) or len(passphrase) < PASSPHRASE_MIN:
        raise TransferRefused(f"Type a passphrase of at least {PASSPHRASE_MIN} characters. It is the only way "
                              "back into the file: Pantheon does not keep it.")
    if len(passphrase) > PASSPHRASE_MAX:
        raise TransferRefused(f"A passphrase is at most {PASSPHRASE_MAX} characters.")
    return passphrase.encode("utf-8")


def _key(passphrase: bytes, salt: bytes, n: int, r: int, p: int) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase)


def _header_aad(env: Dict[str, Any]) -> bytes:
    """The envelope's parameters, bound into the seal: change one and the
    file does not open."""
    head = {FORMAT: env.get(FORMAT), "made": env.get("made"), "items": env.get("items"),
            "kdf": env.get("kdf"), "cipher": env.get("cipher")}
    return json.dumps(head, sort_keys=True, separators=(",", ":")).encode()


def _as_bitwarden(row, sealed: Dict[str, Any]) -> Dict[str, Any]:
    """One item in Bitwarden's unencrypted JSON shape, with how Pantheon used
    it beside (`pantheon`), which a Bitwarden import ignores."""
    base = {"id": row.id, "name": row.label, "notes": sealed.get("notes") or None, "favorite": False,
            "pantheon": {"kind": row.kind, "use": row.use if row.use in V.USES else "ask",
                         "agent_account": bool(row.agent_account)}}
    if row.kind == "note":
        return {**base, "type": 2, "secureNote": {"type": 0}}
    return {**base, "type": 1, "login": {
        "uris": [{"match": None, "uri": o} for o in json.loads(row.addresses or "[]")],
        "username": sealed.get("username") or None, "password": sealed.get("secret") or None,
        "totp": sealed.get("totp") or None}}


def export(db, owner: Optional[str], passphrase: Any) -> Dict[str, Any]:
    """The caller's own items, sealed with `passphrase`. Logged: who and how
    many, never what."""
    pw = _check_passphrase(passphrase)
    acct = V.account(owner)
    if V.is_locked(db, owner):
        raise TransferRefused("Your vault is locked. Unlock it, then export again.", 423)
    rows = V._rows(db, acct)
    f = V._fernet(db, acct, create=False)
    items = [_as_bitwarden(r, V._open(f, r.sealed)) for r in rows] if f else []
    plain = json.dumps({"encrypted": False, "folders": [], "items": items}, separators=(",", ":")).encode()
    salt, nonce = os.urandom(16), os.urandom(12)
    env: Dict[str, Any] = {FORMAT: FORMAT_VERSION, "made": datetime.utcnow().strftime("%Y-%m-%d"),
                           "items": len(items),
                           "kdf": {"name": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P, "salt": _b64(salt)},
                           "cipher": "AES-256-GCM"}
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    sealed = AESGCM(_key(pw, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)).encrypt(nonce, plain, _header_aad(env))
    env["nonce"] = _b64(nonce)
    env["data"] = _b64(sealed)
    env["about"] = ("A Pantheon vault export, sealed with a passphrase (scrypt, AES-256-GCM). Bring it in from "
                    "Settings → Vault with that passphrase.")
    logger.info("vault: %s exported %d item(s)", acct, len(items))
    V.touch(db, owner)
    return env


def open_export(env: Dict[str, Any], passphrase: Any) -> List[Dict[str, Any]]:
    """The items inside one of this module's exports, or a sentence."""
    if env.get(FORMAT) != FORMAT_VERSION:
        raise TransferRefused("This Pantheon export is from a version this one does not read.")
    if not isinstance(passphrase, str) or not passphrase:
        raise TransferRefused("This is a Pantheon vault export: type the passphrase it was sealed with.", 401)
    kdf = env.get("kdf") or {}
    n, r, p = kdf.get("n"), kdf.get("r"), kdf.get("p")
    if (kdf.get("name") != "scrypt" or env.get("cipher") != "AES-256-GCM"
            or not all(isinstance(x, int) and not isinstance(x, bool) for x in (n, r, p))
            or not SCRYPT_N_RANGE[0] <= n <= SCRYPT_N_RANGE[1] or n & (n - 1) or not 1 <= r <= 16 or not 1 <= p <= 4):
        raise TransferRefused("This export's seal is not one Pantheon makes, so it was not opened.")
    salt, nonce, data = _unb64(kdf.get("salt")), _unb64(env.get("nonce")), _unb64(env.get("data"))
    if len(salt) < 16 or len(nonce) != 12:
        raise TransferRefused("This export is damaged: a part of it is not what was written.")
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        plain = AESGCM(_key(passphrase.encode("utf-8"), salt, n, r, p)).decrypt(nonce, data, _header_aad(env))
    except InvalidTag:
        raise TransferRefused("That passphrase does not open this export (or the file was changed). "
                              "Nothing was brought in.", 403) from None
    items, inner = _from_json(plain.decode("utf-8"))
    if inner is not None:
        raise TransferRefused("This export holds another export inside it; nothing was brought in.")
    return items


__all__ = ["TransferRefused", "read_file", "bring_in", "export", "open_export", "server_bitwarden_items"]
