# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1475`, `D-2026-10-25-04` §5 — each person's own networks, and an admin
who sees them all.

The owner, 2026-10-25: *"Network scope allowable by admin — configured per
user. Admin has omni-sight. Admin can enable or disable global network scope
setting. Users can then setup their workspaces with their own network endpoints
etc. Users can link their network endpoints with credentials stored in vault
for agent use. Admin can see the network endpoints the users implemented but
not the vault credentials, only that *something* is linked to a login. Never
the login directly."*

**What a person's network is.** The same object as the install-wide list in
Settings → Networks (`src/networks.py`): a name, hosts, ranges, a trust, on or
off — plus `login`, the id of an item in that person's **own** vault. It
directs that person's runs only: the agent's `network list` names it, a `reach`
or a page fetch in an untrusted one is refused, a task scoped to it is held to
it. Another person's runs never see it. It grants nothing: whether the agent
may reach the LAN at all is still the install's switch and the person's
workstation privilege (`outbound_fetch.lan_reach_for`, `D-2026-10-25-03`).

**Off unless an admin turns it on** (`networks_per_person`). Off, nothing here
is read, a person's saved list is kept, and every run sees the install-wide
list only — as before this existed.

**The admin's view** (`everyone`) is every person's networks — names, hosts,
ranges, trust, notes — and for a linked login, `login_linked: true`. Never the
item's id, its label, its user name or anything sealed: the id is dropped here,
before the route, so no screen can be one `JSON.stringify` away from it.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SETTING = "networks_per_person"
NETWORKS_MAX = 50
NOTES_MAX = 500
_FIELDS = ("name", "hosts", "cidrs", "trust", "enabled", "notes", "login")

OFF_SENTENCE = ("An admin hasn't turned on networks for each person (Settings → Networks → "
                "“Each person may declare their own networks”), so only the install's networks apply.")

# A run reads its person's list on every connection it opens, so it is kept in
# memory and dropped on a save; the TTL covers a save made by another process.
_CACHE_TTL = 30.0
_cache: Dict[str, tuple] = {}
_cache_lock = threading.Lock()


class NetworksRefused(ValueError):
    def __init__(self, sentence: str, status: int = 400):
        super().__init__(sentence)
        self.sentence = sentence
        self.status = status


def enabled() -> bool:
    """Whether an admin turned per-person networks on. Only a stored `true`."""
    try:
        from src.settings import get_setting
        return get_setting(SETTING, False) is True
    except Exception:
        return False


def account(owner: Optional[str]) -> str:
    from src.workstation_access import account_of
    return account_of(owner)


def _decode(text: Any) -> List[Dict[str, Any]]:
    try:
        value = json.loads(text or "[]")
    except (TypeError, ValueError):
        return []
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _stored(db, acct: str) -> List[Dict[str, Any]]:
    from core.database import PersonNetworks
    row = db.query(PersonNetworks).filter(PersonNetworks.account == acct).first()
    return _decode(row.networks) if row else []


def _vault_labels(db, acct: str) -> Dict[str, str]:
    """`{item id: label}` for the person's own vault — which links still point
    at something, and what the person (and their agent) call it."""
    from src import vault as V
    return {r.id: r.label for r in V._rows(db, acct)}


def for_run(owner: Optional[str]) -> List[Dict[str, Any]]:
    """The person's networks as `src/networks.py` reads them, or `[]` when
    per-person networks are off or nobody is named. Cached briefly."""
    if not owner or not enabled():
        return []
    acct = account(owner)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(acct)
        if hit and now - hit[0] < _CACHE_TTL:
            return [dict(n) for n in hit[1]]
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        nets = _stored(db, acct)
    except Exception as e:  # noqa: BLE001 — an unreadable list is no list, said once
        logger.warning("person networks for %s could not be read: %s", acct, e)
        nets = []
    finally:
        db.close()
    with _cache_lock:
        _cache[acct] = (now, [dict(n) for n in nets])
    return nets


def forget(owner: Optional[str] = None) -> None:
    with _cache_lock:
        if owner is None:
            _cache.clear()
        else:
            _cache.pop(account(owner), None)


def _install_names() -> List[str]:
    from src import networks as N
    return [n.name for n in N.declared_networks(include_disabled=True, person=False)]


def validate(db, owner: Optional[str], value: Any) -> List[str]:
    """Every problem with a proposed list, as sentences: `validate_networks`'
    (the one rule for what a network is, `Law 7`), and what is a person's
    own — a name the install already uses, a login not in their vault."""
    from src.networks import validate_networks
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return ["networks must be a list of objects."]
    problems = validate_networks(value)
    if not isinstance(value, list):
        return problems
    if len(value) > NETWORKS_MAX:
        problems.append(f"That is {len(value)} networks; a person may declare {NETWORKS_MAX}.")
    install = {n.lower() for n in _install_names()}
    labels = _vault_labels(db, account(owner))
    for i, raw in enumerate(value):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        where = f"“{name}”" if name else f"entry {i + 1}"
        if name and name.lower() in install:
            problems.append(f"{where} is the name of a network your admin declared for everyone. "
                            "Name yours something else, so a run scoped to it means one thing.")
        login = raw.get("login")
        if login not in (None, "") and str(login) not in labels:
            problems.append(f"{where}: the login it links is not in your vault. Pick one from "
                            "Settings → Vault, or none.")
        if len(str(raw.get("notes") or "")) > NOTES_MAX:
            problems.append(f"{where}: notes are at most {NOTES_MAX} characters.")
    return problems


def _clean(raw: Dict[str, Any]) -> Dict[str, Any]:
    split = lambda v: [str(x).strip() for x in (v or []) if str(x).strip()]   # noqa: E731
    out = {"name": str(raw.get("name") or "").strip(),
           "hosts": [h.lower() for h in split(raw.get("hosts"))],
           "cidrs": split(raw.get("cidrs")),
           "trust": raw.get("trust") if raw.get("trust") in ("trusted", "untrusted") else "trusted",
           "enabled": raw.get("enabled", True) is not False,
           "notes": str(raw.get("notes") or "").strip()}
    login = str(raw.get("login") or "").strip()
    if login:
        out["login"] = login
    return out


def save(db, owner: Optional[str], value: Any) -> Dict[str, Any]:
    """Replace the person's list. Refused whole, with every problem, when
    anything in it is wrong; refused when an admin has the feature off."""
    from core.database import PersonNetworks
    if not enabled():
        raise NetworksRefused(OFF_SENTENCE, 403)
    problems = validate(db, owner, value)
    if problems:
        raise NetworksRefused(" ".join(problems))
    if isinstance(value, str):
        value = json.loads(value)
    nets = [_clean(r) for r in value]
    acct = account(owner)
    row = db.query(PersonNetworks).filter(PersonNetworks.account == acct).first()
    if row is None:
        row = PersonNetworks(account=acct, networks="[]")
        db.add(row)
    row.networks = json.dumps(nets)
    db.commit()
    forget(owner)
    logger.info("networks: %s saved %d network(s) of their own", acct, len(nets))
    return mine(db, owner)


def mine(db, owner: Optional[str]) -> Dict[str, Any]:
    """The person's own view: their networks with each link's label (theirs to
    read), the install's network names (taken), and whether it is on."""
    acct = account(owner)
    labels = _vault_labels(db, acct)
    nets = []
    for n in _stored(db, acct):
        item = {k: n.get(k) for k in _FIELDS if k != "login"}
        login = str(n.get("login") or "")
        item["login"] = login if login in labels else ""
        item["login_label"] = labels.get(login, "")
        item["login_missing"] = bool(login) and login not in labels
        nets.append(item)
    return {"enabled": enabled(), "networks": nets, "install": _install_names(),
            "off": "" if enabled() else OFF_SENTENCE}


def everyone(db, people: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """`D-2026-10-25-04` §5's omni-sight: every person's networks, and of a
    linked login only that one is linked — never which, nor anything in it.
    `people` (the install's user names) puts a name to each account; the
    store is keyed by account, the one spelling of a person."""
    from core.database import PersonNetworks
    names = {account(u): u for u in (people or [])}
    out = []
    for row in db.query(PersonNetworks).order_by(PersonNetworks.account).all():
        nets = _decode(row.networks)
        if not nets:
            continue
        linked = set(_vault_labels(db, row.account))
        shown = []
        for n in nets:
            item = {k: n.get(k) for k in _FIELDS if k != "login"}
            item["login_linked"] = str(n.get("login") or "") in linked
            shown.append(item)
        out.append({"account": row.account, "person": names.get(row.account, ""), "networks": shown,
                    "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None})
    return out


def agent_logins(owner: Optional[str], agent: Optional[str] = None) -> Dict[str, str]:
    """`{network name: login label}` for the person's networks whose linked
    login this agent may use (`vault.may_use`) — what `network list` tells the
    agent to sign in with. An item not granted to the agent is not named."""
    if not owner or not enabled():
        return {}
    from core.database import SessionLocal
    from src import vault as V
    db = SessionLocal()
    try:
        rows = {r.id: r for r in V._rows(db, account(owner))}
        out = {}
        for n in _stored(db, account(owner)):
            row = rows.get(str(n.get("login") or ""))
            if row is not None and V.may_use(row, agent):
                out[str(n.get("name") or "")] = row.label
        return out
    finally:
        db.close()


__all__ = ["NetworksRefused", "OFF_SENTENCE", "SETTING", "agent_logins", "enabled", "everyone",
           "for_run", "forget", "mine", "save", "validate"]
