# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P25-02` · Git, per account: who a person's commits say they are, and the
tokens their pushes and pulls are made with.

The owner (2026-10-24): *"We need per-account git tooling and stuff too - and a
way to call on it."* Pantheon is many people's: each one's git identity and
credentials are their own — one row per account (`account_of`, the one
spelling of a person whatever route built the owner) — and nothing here is
shared, defaulted from someone else, or read by another person.

**A token is written once and never read back out of the server.** It is
encrypted with the install's key (`secret_storage`, the same key the mail
passwords use) and `public()` says only that one is set: the host, the user
name, and when. The one reader of the plain token is `credential_for`, which the
git tool calls for the host a command is about to reach, and hands to that one
process in its environment (`src/agent_tools/git_tools.py`) — never to a file,
a remote URL or the person's home.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*(?::\d{1,5})?$")
NAME_MAX = 100
EMAIL_RE = re.compile(r"^[^\s@<>]{1,64}@[^\s@<>]{1,190}$")
TOKEN_MAX = 512
HOSTS_MAX = 20

# The forges a person picks from by name; any other https host is typed.
KNOWN_HOSTS = (
    ("github.com", "GitHub"),
    ("gitlab.com", "GitLab"),
    ("codeberg.org", "Codeberg"),
    ("bitbucket.org", "Bitbucket"),
)


class GitRefused(ValueError):
    def __init__(self, sentence: str, status: int = 400):
        super().__init__(sentence)
        self.sentence = sentence
        self.status = status


def account(owner: Optional[str]) -> str:
    from src.workstation_access import account_of
    return account_of(owner)


def clean_host(raw: Any) -> str:
    """A host as a person types it — `https://GitHub.com/`, `gitlab.example.org:8443`
    — or a sentence why it is not one."""
    text = str(raw or "").strip().lower()
    text = re.sub(r"^[a-z]+://", "", text).split("/", 1)[0]
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    if not HOST_RE.match(text):
        raise GitRefused(f"“{str(raw or '').strip()[:80]}” is not a host name, like github.com "
                         "or git.example.org:8443.")
    return text


def _clean_identity(name: Any, email: Any) -> Tuple[str, str]:
    n = " ".join(str(name or "").split())
    e = str(email or "").strip()
    if not n:
        raise GitRefused("Say the name your commits should carry.")
    if len(n) > NAME_MAX or any(c in n for c in "<>\n"):
        raise GitRefused(f"A commit name is at most {NAME_MAX} characters, without < or >.")
    if not EMAIL_RE.match(e):
        raise GitRefused("That is not an email address a commit can carry.")
    return n, e


def _clean_token(raw: Any) -> str:
    t = str(raw or "").strip()
    if not t:
        raise GitRefused("Paste the token for this host — a personal access token with the "
                         "repository scopes you want the agent to have.")
    if len(t) > TOKEN_MAX or any(c.isspace() for c in t):
        raise GitRefused(f"A token is one word of at most {TOKEN_MAX} characters.")
    return t


def _clean_user(raw: Any) -> str:
    u = str(raw or "").strip()
    if not u:
        # Every forge above accepts any non-empty user name beside a token.
        return "git"
    if len(u) > 100 or any(c.isspace() or c in ":@/" for c in u):
        raise GitRefused("A user name is one word, without : @ or /.")
    return u


# ── reading ─────────────────────────────────────────────────────────────────

def identity(db, owner: Optional[str]) -> Optional[Dict[str, str]]:
    from core.database import GitIdentity
    row = db.query(GitIdentity).filter(GitIdentity.account == account(owner)).first()
    return {"name": row.name, "email": row.email} if row else None


def hosts(db, owner: Optional[str]) -> List[Dict[str, Any]]:
    from core.database import GitCredential
    rows = (db.query(GitCredential).filter(GitCredential.account == account(owner))
            .order_by(GitCredential.host).all())
    return [{"host": r.host, "username": r.username, "set": True,
             "since": r.updated_at.isoformat() + "Z" if r.updated_at else None} for r in rows]


def public(db, owner: Optional[str]) -> Dict[str, Any]:
    """What the Settings panel and the + menu are told — never a token."""
    return {"identity": identity(db, owner), "hosts": hosts(db, owner),
            "known_hosts": [{"host": h, "label": label} for h, label in KNOWN_HOSTS]}


def credential_for(db, owner: Optional[str], host: str) -> Optional[Tuple[str, str]]:
    """`(username, token)` for this person on `host`, or None. The one reader
    of a plain token; its caller is the git tool, for one command."""
    from core.database import GitCredential
    from src.secret_storage import decrypt
    try:
        h = clean_host(host)
    except GitRefused:
        return None
    row = (db.query(GitCredential)
           .filter(GitCredential.account == account(owner), GitCredential.host == h).first())
    if row is None:
        return None
    return row.username, decrypt(row.token)


# ── writing ─────────────────────────────────────────────────────────────────

def change(db, owner: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
    """One body for every change: `{identity: {name, email} | null,
    hosts: {host: {username?, token} | null}}`. All of it is checked before
    any of it is written."""
    from core.database import GitCredential, GitIdentity
    from src.secret_storage import encrypt
    acct = account(owner)
    plan_identity = None
    if "identity" in body:
        ident = body.get("identity")
        if ident is None:
            plan_identity = ()
        elif isinstance(ident, dict):
            plan_identity = _clean_identity(ident.get("name"), ident.get("email"))
        else:
            raise GitRefused("“identity” is {name, email}, or null to clear it.")
    raw_hosts = body.get("hosts") or {}
    if not isinstance(raw_hosts, dict):
        raise GitRefused("“hosts” is {host: {username, token}}, or {host: null} to forget one.")
    plan_hosts: Dict[str, Optional[Tuple[str, str]]] = {}
    for raw, value in raw_hosts.items():
        h = clean_host(raw)
        if value is None:
            plan_hosts[h] = None
        elif isinstance(value, dict):
            plan_hosts[h] = (_clean_user(value.get("username")), _clean_token(value.get("token")))
        else:
            raise GitRefused(f"{h}: give {{username, token}}, or null to forget it.")
    existing = {r.host: r for r in db.query(GitCredential).filter(GitCredential.account == acct).all()}
    after = ((set(existing) | {h for h, v in plan_hosts.items() if v})
             - {h for h, v in plan_hosts.items() if v is None})
    if len(after) > HOSTS_MAX:
        raise GitRefused(f"At most {HOSTS_MAX} hosts.")

    if plan_identity is not None:
        row = db.query(GitIdentity).filter(GitIdentity.account == acct).first()
        if plan_identity == ():
            if row is not None:
                db.delete(row)
        elif row is None:
            db.add(GitIdentity(account=acct, name=plan_identity[0], email=plan_identity[1]))
        else:
            row.name, row.email = plan_identity
    for h, value in plan_hosts.items():
        row = existing.get(h)
        if value is None:
            if row is not None:
                db.delete(row)
        elif row is None:
            db.add(GitCredential(id=uuid.uuid4().hex, account=acct, host=h, username=value[0],
                                 token=encrypt(value[1])))
        else:
            row.username, row.token = value[0], encrypt(value[1])
    db.commit()
    return public(db, owner)
