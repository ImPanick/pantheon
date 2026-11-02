# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vault-domain tool implementations.

Extracted from tool_implementations.py as part of slice 1 (#4082/#4071).
Holds the Bitwarden CLI wrappers (vault_search / vault_get / vault_unlock)
and their helpers (_load_vault_config, _run_bw).
``src.tool_implementations`` re-exports these for backward compatibility.
"""
import json
import logging
from typing import Dict, Optional

from src.constants import VAULT_FILE
from src.tools._common import _parse_tool_args

logger = logging.getLogger(__name__)


def _load_vault_config() -> Dict:
    """Load Vaultwarden config from data/vault.json."""
    from pathlib import Path
    p = Path(VAULT_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


async def _run_bw(args: list, session: Optional[str] = None, input_text: Optional[str] = None) -> tuple:
    """Run a bw CLI command with optional session + stdin. Returns (stdout, stderr, returncode)."""
    import asyncio
    env = {}
    import os as _os
    env.update(_os.environ)
    if session:
        env["BW_SESSION"] = session

    proc = await asyncio.create_subprocess_exec(
        "bw", *args,
        stdin=asyncio.subprocess.PIPE if input_text else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate(input=input_text.encode() if input_text else None)
    return stdout.decode(errors="replace").strip(), stderr.decode(errors="replace").strip(), proc.returncode


def bitwarden_set_up() -> bool:
    """Whether the server's Bitwarden vault was ever set up here: a session
    saved, or a server named. Without either there is nothing to unlock, and
    no tool says the person's vault is "locked" because of it."""
    cfg = _load_vault_config()
    return bool(cfg.get("session") or cfg.get("server_url") or cfg.get("email"))


def _own_matches(owner: Optional[str], query: str, agent: Optional[str]) -> tuple:
    """`(rows, sealed usernames)` in the person's own vault (`src/vault.py`)
    this agent may use and `query` names — by name, address or user name.
    `B-vault-search`: the vault a person means when they say "the vault"."""
    from core.database import SessionLocal
    from src import vault as V
    db = SessionLocal()
    try:
        rows = [r for r in V._rows(db, V.account(owner)) if V.may_use(r, agent)]
        locked = V.is_locked(db, owner)
        q = query.lower()
        words = [w for w in q.split() if w]
        out = []
        for r in rows:
            hay = f"{r.label} {r.kind} {' '.join(json.loads(r.addresses or '[]'))}".lower()
            if not words or q in hay or all(w in hay for w in words):
                out.append(r)
        return out, locked
    finally:
        db.close()


def _own_lines(rows) -> list:
    from src import vault as V
    from src.agent_tools.login_shell_tools import env_name
    lines = []
    for r in rows:
        addresses = json.loads(r.addresses or "[]")
        facts = [r.kind]
        if addresses:
            facts.append(", ".join(addresses[:3]))
        forge = V.git_host_of(r.kind, r.label, addresses)
        if forge:
            facts.append(f"a token git and gh use for {forge}")
        facts.append({"allowed": "may be used without asking", "chat": "asks once per chat"}.get(r.use, "asks the person first"))
        var = f"$LOGIN_{env_name(r.label)}_" + ("TOKEN" if r.kind == "key" else "PASSWORD")
        lines.append(f"- “{r.label}” ({'; '.join(facts)}) — in shell_with_login it is {var}")
    return lines


async def do_vault_search(content: str, owner: Optional[str] = None, agent: Optional[str] = None) -> Dict:
    """Search the person's own vault — and the server's Bitwarden vault, when
    one is set up — by keyword. Names and addresses only, never a secret."""
    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}
    query = str(args.get("query", "") or "").strip()

    try:
        own, locked = _own_matches(owner, query, agent)
    except Exception as exc:  # noqa: BLE001 — as `vault_get`'s
        logger.warning("vault_search: the person's vault could not be read (%s)", type(exc).__name__)
        own, locked = [], False
    lines = []
    if own:
        lines.append(f"In the person's vault ({len(own)} match{'es' if len(own) != 1 else ''}"
                     f"{'' if query else ', everything'}):")
        lines += _own_lines(own[:20])
        lines.append("Use one by its name — you never see the value: shell_with_login "
                     '{"logins": ["<name>"], "command": "…$LOGIN_…"} (for a git host token, plain git '
                     "and gh in that command are signed in too), or agent_browser login for a web login. "
                     "The git tool also uses a git host's token by itself when the item may be used without asking.")
        if locked:
            lines.append("The person's vault is locked right now: they unlock it in Settings → Vault.")

    if query and bitwarden_set_up():
        cfg = _load_vault_config()
        session = cfg.get("session")
        if not session:
            lines.append("The server's Bitwarden vault is set up but locked; an admin unlocks it in Settings.")
        else:
            stdout, stderr, rc = await _run_bw(["list", "items", "--search", query], session=session)
            items = []
            if rc == 0:
                try:
                    items = json.loads(stdout)
                except json.JSONDecodeError:
                    items = []
            if items:
                lines.append(f"In the server's Bitwarden vault ({len(items)}):")
                for it in items[:20]:
                    item_id = it.get("id", "?")
                    login = it.get("login") or {}
                    uris = login.get("uris") or []
                    parts = [f"[bw:{item_id}] {it.get('name', '?')}"]
                    if login.get("username"):
                        parts.append(f"user: {login['username']}")
                    if uris:
                        parts.append(f"url: {uris[0].get('uri', '')}")
                    lines.append("- " + " · ".join(parts))
                lines.append('Sign in with one by "bw:<its id>" in agent_browser login or shell_with_login.')

    if not lines:
        what = f"matches “{query}”" if query else "is there"
        return {"output": f"Nothing in the person's vault {what}. They add logins, keys and tokens in "
                          "Settings → Vault.", "exit_code": 0}
    return {"output": "\n".join(lines), "exit_code": 0}


async def bw_item(item_id: str) -> Dict:
    """One item from the server's Bitwarden vault, or `{"error"}`. The one
    reader of a Bitwarden secret; its callers are `vault_get` (which says
    only that one is set) and `src.vault.resolve` (which hands it to the
    daemon or a command's environment, by reference — `P27`)."""
    cfg = _load_vault_config()
    session = cfg.get("session")
    if not session:
        return {"error": "The server's Bitwarden vault is locked. An admin unlocks it in Settings."}
    stdout, stderr, rc = await _run_bw(["get", "item", item_id], session=session)
    if rc != 0:
        return {"error": f"bw failed: {stderr[:300]}"}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": "Failed to parse bw output"}


def _describe_own(owner: Optional[str], ref: str, agent: Optional[str]) -> Optional[Dict]:
    """`vault_get` for an item in the person's own vault, by name or id — what
    is set, never a value — or None when there is no such item."""
    from core.database import SessionLocal
    from src import vault as V
    db = SessionLocal()
    try:
        row = V._find(db, V.account(owner), ref)
        if row is None or not V.may_use(row, agent):
            return None
        sealed = {} if V.is_locked(db, owner) else V._open(V._fernet(db, V.account(owner), create=True), row.sealed)
        item = V.public(row, sealed)
        locked = V.is_locked(db, owner)
    finally:
        db.close()
    lines = [f"Vault item: {item['label']} ({item['kind']})"]
    if item["username"]:
        lines.append(f"User name: {item['username']}")
    lines.append(f"{'Token' if item['kind'] == 'key' else 'Password'}: "
                 f"{'set' if item['has_secret'] else ('(locked)' if locked else '(none)')}")
    if item["addresses"]:
        lines.append("Addresses: " + ", ".join(item["addresses"]))
    lines += _own_lines([row])
    if locked:
        lines.append("The person's vault is locked: they unlock it in Settings → Vault.")
    lines.append("Use it by name in shell_with_login (or agent_browser login); you never see the value, "
                 "and you never need to.")
    return {"output": "\n".join(lines), "exit_code": 0}


async def do_vault_get(content: str, owner: Optional[str] = None, agent: Optional[str] = None) -> Dict:
    """Describe a vault entry by item ID — never its password, one-time-code
    secret or notes (`B-P27-vault-get`): the agent signs in with it by
    reference, `bw:<id>` in `agent_browser login` or `shell_with_login`.
    Logs access to assistant chat."""
    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}
    item_id = args.get("item_id", "").strip()
    reason = args.get("reason", "").strip()
    if not item_id:
        return {"error": "item_id is required", "exit_code": 1}
    if not reason:
        return {"error": "reason is required — explain WHY you need this password", "exit_code": 1}

    try:
        own = _describe_own(owner, item_id, agent)
    except Exception as exc:  # noqa: BLE001 — the person's vault unreadable is not every vault unreadable
        logger.warning("vault_get: the person's vault could not be read (%s)", type(exc).__name__)
        own = None
    if own is not None:
        return own
    if item_id.lower().startswith("bw:"):
        item_id = item_id[3:].strip()
    elif not bitwarden_set_up():
        from core.database import SessionLocal
        from src import vault as V
        db = SessionLocal()
        try:
            names = V.labels(db, owner, agent)
        except Exception:  # noqa: BLE001
            names = []
        finally:
            db.close()
        have = ("It has: " + ", ".join(f"“{n}”" for n in names[:30]) + ".") if names else \
            "It is empty; the person adds items in Settings → Vault."
        return {"error": f"There is no item “{item_id[:80]}” in the person's vault. {have}", "exit_code": 1}

    item = await bw_item(item_id)
    if item.get("error"):
        return {"error": item["error"], "exit_code": 1}

    login = item.get("login") or {}
    name = item.get("name", "?")

    # Audit log to assistant chat
    try:
        from src.assistant_log import log_to_assistant
        if owner:
            log_to_assistant(
                owner,
                f"Looked up **{name}** (not its password) — reason: {reason}",
                category="Vault",
            )
    except Exception:
        pass

    # `P27`. A password in a tool result is in the transcript, in every later
    # turn's context, and in whatever the model is persuaded to send on. The
    # item is used by reference instead; this says only what is set.
    output = [
        f"Vault item: {name}",
        f"Username: {login.get('username', '(none)')}",
        f"Password: {'set' if login.get('password') else '(none)'}",
    ]
    if login.get("totp"):
        output.append("One-time codes: set (made at the moment of sign-in)")
    uris = login.get("uris") or []
    if uris:
        output.append("URLs: " + ", ".join(u.get("uri", "") for u in uris))
    if item.get("notes"):
        output.append("Notes: set (not shown)")
    output.append(f"To sign in with it: agent_browser login with item \"bw:{item.get('id', item_id)}\", "
                  f"or shell_with_login with logins [\"bw:{item.get('id', item_id)}\"]. "
                  "You never see the password, and you never need to.")

    return {"output": "\n".join(output), "exit_code": 0}


async def do_vault_unlock(content: str, owner: Optional[str] = None) -> Dict:
    """Unlock the vault using a master password. Stores the resulting session key."""
    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}
    master_password = args.get("master_password", "")
    if not master_password:
        return {"error": "master_password is required", "exit_code": 1}

    # Do not pass the master password as an argv element. Local process lists
    # can expose argv to other users; stdin keeps the secret out of `ps`.
    stdout, stderr, rc = await _run_bw(["unlock", "--raw"], input_text=master_password + "\n")
    if rc != 0:
        return {"error": f"Unlock failed: {stderr[:300]}", "exit_code": 1}

    session = stdout.strip()
    if not session:
        return {"error": "bw returned empty session", "exit_code": 1}

    # Save session to vault.json
    from pathlib import Path
    p = Path(VAULT_FILE)
    cfg = {}
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    cfg["session"] = session
    from datetime import datetime as _dt
    cfg["unlocked_at"] = _dt.utcnow().isoformat()
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        import os as _os
        _os.chmod(str(p), 0o600)
    except Exception:
        pass

    return {"output": "Vault unlocked. Session saved.", "exit_code": 0}
