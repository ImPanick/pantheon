#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Give one account everything an install without sign-in made.

    python scripts/claim_ownerless.py <username> [--dry-run]

Until 0.2.0 an install could run without sign-in, and what it made belongs to
nobody: rows with no owner, rows filed under the reserved `__pantheon_local__`,
and the no-sign-in account's workstation files. Since there is always a sign-in
(`D-2026-10-07-02` §2), none of that reaches anyone. This hands it to one
account — an explicit act by the operator, run where the data lives
(`B1270`, `D-2026-10-26-01` §4):

  * every table with an `owner` column — chats, documents, folders, gallery
    images and albums, comparisons, drafts, scheduled tasks, workflows, notes,
    calendars, tool allow-rules, memories, crew, hires — except the few where
    no owner means *the install's, for everyone* (endpoints, the mailbox from
    `.env` and its signatures) or where it is a record of the past (the
    activity log) or a credential (API tokens, sign-ins in progress);
  * the no-sign-in account's vault, git identity and tokens, design systems
    and networks — when the account claiming them has none of its own (a vault
    is sealed with its account's key, so two cannot be merged);
  * memories in `memory.json`, skills in `data/skills` with no owner, and the
    no-sign-in preferences;
  * the no-sign-in projects folder's contents, into the account's own.

The no-sign-in workstation *home* is in the workstation's own volume, which
this cannot reach; the command that copies it is printed at the end.

**Stop Pantheon first, and start it again after** — it reads accounts and
preferences when it starts. `--dry-run` says what would move and moves nothing.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LOCAL = "__pantheon_local__"

#: Tables where no owner is not an orphan. Each with why.
NOT_CLAIMED = {
    "model_endpoints": "an endpoint with no owner is the admin's, offered to everyone",
    "email_accounts": "a mailbox with no owner is the install's, from .env",
    "signatures": "they belong to the install's mailbox",
    "events": "the activity log records who did what when it happened",
    "api_tokens": "a token is a credential; one with no owner is refused, never handed on",
    "provider_auth_sessions": "a sign-in in progress",
}

#: Tables keyed by workstation account rather than by name, moved together or
#: not at all: a vault's items are sealed with its key.
ACCOUNT_GROUPS = (("vault_keys", "vault_items"), ("git_identities", "git_credentials"),
                  ("design_systems",), ("person_networks",))


def claim_json_entries(entries, owner):
    """Give `owner` the entries with no owner (or the no-sign-in one)."""
    count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not entry.get("owner") or str(entry.get("owner")).strip().lower() == LOCAL:
            entry["owner"] = owner
            count += 1
    return count


def owner_arg(argv):
    if len(argv) < 2 or not argv[1].strip():
        return None
    return argv[1].strip()


def _orphan_clause(column):
    from sqlalchemy import func, or_
    return or_(column.is_(None), column == "", func.lower(column) == LOCAL)


def claim_owned_tables(db, owner, *, dry_run=False):
    """`{table: (claimed, kept)}` — `kept` are rows the account already has
    the same of (a unique constraint), left where they were."""
    from sqlalchemy.exc import IntegrityError
    from core.database import Base
    out = {}
    for mapper in sorted(Base.registry.mappers, key=lambda m: m.class_.__tablename__):
        model = mapper.class_
        table = model.__tablename__
        if table in NOT_CLAIMED or "owner" not in model.__table__.columns:
            continue
        q = db.query(model).filter(_orphan_clause(model.owner))
        try:
            n = q.count()
        except Exception:   # a table this install never made
            db.rollback()
            continue
        if not n:
            continue
        if dry_run:
            out[table] = (n, 0)
            continue
        nested = db.begin_nested()
        try:
            q.update({"owner": owner}, synchronize_session=False)
            nested.commit()
            out[table] = (n, 0)
        except IntegrityError:
            nested.rollback()
            claimed = kept = 0
            for row in q.all():
                one = db.begin_nested()
                try:
                    row.owner = owner
                    db.flush()
                    one.commit()
                    claimed += 1
                except IntegrityError:
                    one.rollback()
                    kept += 1
            out[table] = (claimed, kept)
    return out


def claim_account_tables(db, old_account, new_account, *, dry_run=False):
    """`{group: moved | reason}` for the account-keyed stores."""
    from sqlalchemy import text
    out = {}
    for group in ACCOUNT_GROUPS:
        name = "+".join(group)
        try:
            have_old = sum(db.execute(text(f"SELECT COUNT(*) FROM {t} WHERE account = :a"),
                                      {"a": old_account}).scalar() or 0 for t in group)
            have_new = sum(db.execute(text(f"SELECT COUNT(*) FROM {t} WHERE account = :a"),
                                      {"a": new_account}).scalar() or 0 for t in group)
        except Exception:   # a table this install never made
            db.rollback()
            continue
        if not have_old:
            continue
        if have_new:
            out[name] = "kept: the account already has its own"
            continue
        if not dry_run:
            for t in group:
                db.execute(text(f"UPDATE {t} SET account = :new WHERE account = :old"),
                           {"new": new_account, "old": old_account})
        out[name] = have_old
    return out


_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)
_OWNER_LINE = re.compile(r"(?m)^owner:[ \t]*(.*?)[ \t]*$")


def claim_skill_text(text, owner):
    """A SKILL.md's text with `owner:` set when it had none, or the no-sign-in
    one; None when it already belongs to someone (or has no frontmatter)."""
    m = _FRONTMATTER.match(text)
    if not m:
        return None
    head = m.group(1)
    line = _OWNER_LINE.search(head)
    if line:
        current = line.group(1).strip().strip("'\"")
        if current and current.lower() != LOCAL:
            return None
        new_head = head[:line.start()] + f"owner: {owner}" + head[line.end():]
    else:
        new_head = f"owner: {owner}\n" + head
    return text[:m.start(1)] + new_head + text[m.end(1):]


def claim_skills(skills_root, owner, *, dry_run=False):
    from core.atomic_io import atomic_write_text
    count = 0
    if not os.path.isdir(skills_root):
        return 0
    for base, _, files in os.walk(skills_root):
        for f in files:
            if f != "SKILL.md":
                continue
            path = os.path.join(base, f)
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            new = claim_skill_text(text, owner)
            if new is None:
                continue
            count += 1
            if not dry_run:
                atomic_write_text(path, new)
    return count


def claim_prefs(owner, *, dry_run=False):
    """The no-sign-in preferences become the account's, when it has none."""
    from routes.prefs_routes import _load, _save
    prefs = _load()
    if not isinstance(prefs, dict) or not prefs:
        return "none"
    users = prefs.get("_users")
    if isinstance(users, dict):
        if users.get(owner):
            return "kept: the account has its own"
        local = users.get(LOCAL)
        if not isinstance(local, dict) or not local:
            return "none"
        if not dry_run:
            users[owner] = users.pop(LOCAL)
            _save(prefs)
        return "moved"
    flat = {k: v for k, v in prefs.items() if k != "_users"}
    if not flat:
        return "none"
    if not dry_run:
        _save({**flat, "_users": {owner: dict(flat)}})
    return "moved"


def claim_projects(projects_root, old_folder, new_folder, *, dry_run=False):
    """Move what is in the no-sign-in projects folder into the account's; a
    name the account already has stays where it was."""
    src = os.path.join(projects_root, old_folder)
    dst = os.path.join(projects_root, new_folder)
    if not os.path.isdir(src) or os.path.realpath(src) == os.path.realpath(dst):
        return 0, []
    moved, kept = 0, []
    if not dry_run:
        os.makedirs(dst, exist_ok=True)
    for name in sorted(os.listdir(src)):
        if os.path.exists(os.path.join(dst, name)):
            kept.append(name)
            continue
        moved += 1
        if not dry_run:
            shutil.move(os.path.join(src, name), os.path.join(dst, name))
    return moved, kept


def main(argv=None):
    ap = argparse.ArgumentParser(prog="claim_ownerless.py",
                                 description="Give one account everything an install without sign-in made.")
    ap.add_argument("username")
    ap.add_argument("--dry-run", action="store_true", help="say what would move; move nothing")
    args = ap.parse_args(argv)
    owner = args.username.strip().lower()

    from core.auth import DEFAULT_AUTH_PATH, AuthManager
    mgr = AuthManager(DEFAULT_AUTH_PATH)
    if owner not in mgr.users:
        known = ", ".join(sorted(mgr.users)) or "none yet — sign in once to make the admin"
        print(f"There is no account “{args.username}”. The accounts are: {known}.", file=sys.stderr)
        return 1

    from src.constants import DATA_DIR, SKILLS_DIR
    from src.workstation_access import account_of
    from workstation import protocol as P
    old_account, new_account = account_of(None), account_of(owner)
    verb = "would claim" if args.dry_run else "claimed"
    print(f"{'Dry run: ' if args.dry_run else ''}giving {owner} what the install without sign-in made\n")

    from core.database import SessionLocal
    db = SessionLocal()
    try:
        tables = claim_owned_tables(db, owner, dry_run=args.dry_run)
        accounts = claim_account_tables(db, old_account, new_account, dry_run=args.dry_run)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"  The database could not be updated ({e}); nothing in it was changed.", file=sys.stderr)
        return 2
    finally:
        db.close()
    for table, (n, kept) in tables.items():
        print(f"  {table}: {verb} {n}" + (f", {kept} kept (the account has the same)" if kept else ""))
    for group, result in accounts.items():
        print(f"  {group}: " + (f"{verb} {result}" if isinstance(result, int) else result))
    for table, why in NOT_CLAIMED.items():
        print(f"  {table}: left as it is — {why}")

    from src.memory import MemoryManager
    memories = MemoryManager(DATA_DIR)
    try:
        entries = memories.load_all_for_update()
    except Exception as e:  # MemoryStoreUnreadable: leave it, say so
        print(f"  memory.json: unreadable ({e}); left as it is")
    else:
        n = claim_json_entries(entries, owner)
        if n and not args.dry_run:
            memories.save(entries)
        print(f"  memory.json: {verb} {n}")

    print(f"  skills: {verb} {claim_skills(SKILLS_DIR, owner, dry_run=args.dry_run)}")
    print(f"  preferences: {claim_prefs(owner, dry_run=args.dry_run)}")

    from src.tool_execution import projects_base
    moved, kept = claim_projects(projects_base(create=False), P.project_folder(None),
                                 P.project_folder(owner), dry_run=args.dry_run)
    print(f"  projects: {verb} {moved}" + (f"; kept where they were (the account has the same name): "
                                          f"{', '.join(kept)}" if kept else ""))

    print(f"\nThe workstation home of the install without sign-in is /home/{old_account}, in the "
          "workstation's own volume. To give its files to this account too, with the workstation running:\n"
          f"  docker compose exec workstation sh -c 'cp -a /home/{old_account}/. /home/{new_account}/ && "
          f"chown -R {new_account}: /home/{new_account}'\n"
          f"(the account's home exists once {owner} has used the workstation).")
    if not args.dry_run:
        print("\nDone. Start Pantheon again — it reads accounts and preferences when it starts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
