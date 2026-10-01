#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P3-16` — every config write is classified, and the classification is checked.

PandaOS permanently lost user API keys to one shape: a **read with a silent
fallback** feeding a **write**. `except: return {}` is correct for a loader
that must not crash the app at startup, and catastrophic when the caller then
hands that `{}` back to be saved. The two halves are usually in different
functions, often in different files, and neither is wrong on its own.

There is no static analysis that decides this. What there is, is a small closed
set of files the app rewrites in place, and a decision to make about each one:

  guarded      irreplaceable. Somebody typed it, or it is the only copy.
               The write must pass `preserve_unreadable=True`, so a target
               that exists and cannot be read is never replaced.

  strict-read  the writer's own read raises instead of defaulting, so a failed
               read aborts the write before this module is reached. Passing
               `preserve_unreadable` too would be redundant, and for the
               uploads index actively wrong: it keeps a `.bak` and recovers
               from the sibling, which the guard would pre-empt.

  rebuildable  the app regenerates it. Refusing to overwrite a corrupt one
               would wedge a file whose repair *is* overwriting it.

The checker fails on a `guarded` site missing the keyword, on a
`rebuildable`/`strict-read` site that has it (a guard on a rebuildable store is
not harmless — it wedges the recovery), on a write to a target nobody has
classified, and on a classification that no longer matches any site.

Usage:  python3 .pantheon/check-config-writes.py [--list]
"""
from __future__ import annotations

import ast
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WRITERS = {"atomic_write_json", "atomic_write_text", "_atomic_write_json", "_atomic_write_text"}

GUARDED, STRICT_READ, REBUILDABLE = "guarded", "strict-read", "rebuildable"

# (file, first-argument source text) -> (classification, why)
STORES: dict[tuple[str, str], tuple[str, str]] = {
    # ── guarded: irreplaceable ────────────────────────────────────────────────
    ("core/auth.py", "self.auth_path"): (
        GUARDED, "the user database; an unreadable one read as empty opens first-run setup"),
    ("src/settings.py", "SETTINGS_FILE"): (
        GUARDED, "credentials and every operator choice, written by ~20 read-modify-write callers"),
    ("src/settings.py", "FEATURES_FILE"): (
        GUARDED, "admin feature flags; H05 is the record of one coming back on by itself"),
    # `B988`: `contacts_routes.py` and `email_helpers.py` wrote settings.json
    # through doors of their own (two entries here until 2026-10-01). Both now
    # call `src.settings.save_settings`, so the file has one write site.
    ("routes/contacts/contacts_routes.py", "str(LOCAL_CONTACTS_FILE)"): (
        GUARDED, "an address book; the loader answers a bad read with []"),
    ("routes/prefs_routes.py", "PREFS_FILE"): (
        GUARDED, "one file holds every user's preferences"),
    ("src/api_key_manager.py", "self.api_keys_file"): (
        GUARDED, "the store this row is named after: `_load_raw` returns {} and `save` wrote it back"),
    ("src/device_inventory.py", "_store_path()"): (
        GUARDED, "`P17-04`. The observations rebuild themselves — an ARP table "
                 "repopulates — but the NAMES do not: 'the printer' is something a "
                 "person typed while looking at a sticker, and nothing else in the "
                 "system knows it. A store that is half rebuildable is guarded, "
                 "because the half that is not is the half somebody would miss"),
    ("src/integrations.py", "DATA_FILE"): (
        GUARDED, "integration API keys, encrypted at rest"),
    ("src/preset_manager.py", "self.presets_file"): (
        GUARDED, "user-authored personas; `load` falls back to DEFAULT_PRESETS"),
    ("services/memory/skill_collections.py", "self.path"): (
        GUARDED, "`P8-50`. The groups a person made and the packages and groups they "
                 "switched off; `_load` answers a damaged file with an empty store "
                 "so injection keeps working, and that empty store must never be "
                 "saved over it"),

    # ── strict-read: the read raises, so the write never happens ─────────────
    ("src/upload_handler.py", "uploads_db_path"): (
        STRICT_READ, "`_load_upload_index(fail_on_error=True)`, plus a .bak sibling to recover from"),
    ("routes/auth_routes.py", "str(p)"): (
        STRICT_READ, "rename migration: `json.loads`/`read_text` raise and the except skips the write"),
    ("routes/auth_routes.py", "MEMORY_FILE"): (
        STRICT_READ, "rename migration: the read is unguarded, so a bad file skips the write"),
    ("routes/auth_routes.py", "str(usage_path)"): (
        STRICT_READ, "rename migration: same shape"),
    ("services/memory/skills.py", "path"): (
        STRICT_READ, "`_read_skill` returns None on a parse failure, never an empty Skill"),
    ("services/memory/skills.py", "dest"): (
        STRICT_READ, "import writes files supplied by the caller, not read from the target"),
    ("services/memory/skills.py", "self._skill_file(cat, nm)"): (
        STRICT_READ, "same: the Skill is built from the request, not from the file"),
    ("services/memory/skills.py", "os.path.join(vdir, vid + '.md')"): (
        STRICT_READ, "`P8-10`. A version snapshot, at a path that did not exist a "
                     "moment ago — `vid` is one past the highest sequence number in "
                     "the directory, so there is no target to read and none to lose. "
                     "Its content is the SKILL.md text the caller has just read, and "
                     "that read is the strict one two entries up: `_read_skill` "
                     "returns None on a parse failure rather than an empty Skill, so "
                     "a corrupt file is never what gets copied"),

    # ── rebuildable: overwriting a corrupt one is the repair ─────────────────
    ("core/auth.py", "self._sessions_path"): (
        REBUILDABLE, "session tokens; the worst case is everyone logs in again"),
    ("services/memory/skills.py", "self.usage_file"): (
        REBUILDABLE, "usage counters"),
    ("src/bg_jobs.py", "str(_STORE)"): (
        REBUILDABLE, "in-flight background job state"),
    ("src/rate_limiter.py", "path"): (
        REBUILDABLE, "per-host rate-limit counters"),
    ("src/builtin_actions.py", "state_path"): (
        REBUILDABLE, "cookbook serve state, rebuilt from the running processes"),
    ("src/cookbook_serve_lifecycle.py", "state_path"): (
        REBUILDABLE, "cookbook serve state"),
    ("routes/codex_routes.py", "cookbook_state_path"): (
        REBUILDABLE, "cookbook serve state"),
    ("routes/cookbook_routes.py", "str(_cookbook_state_path)"): (
        REBUILDABLE, "cookbook serve state"),
    ("routes/cookbook_routes.py", "_cookbook_state_path"): (
        REBUILDABLE, "cookbook serve state"),
}

# ── `B1008` · a guarded store written with no writer at all ─────────────────
#
# Everything above classifies `atomic_write_*` calls, so a store written with a
# plain `open(…, "w")` was outside the measurement: `src/integrations.py`'s
# `migrate_from_settings` rewrote settings.json that way on every boot that
# found two legacy keys — not atomic, no `preserve_unreadable`, around
# `src.settings`' cache — and this checker passed. So a plain write is looked
# for too: `open(<target>, <a mode that writes>)` and `<target>.write_text` /
# `.write_bytes`, where the target, followed through the simple assignments in
# its function and its module (`settings_path = SETTINGS_FILE`), names one of
# the guarded stores below — by the constant every module imports it as, or by
# its file name. Such a write is a problem: a guarded store has one writer, and
# it is the classified site above.
#
# The constants that name a guarded store wherever they are imported, and the
# STORES entry each one is.
GUARDED_NAMES: dict[str, tuple[str, str]] = {
    "SETTINGS_FILE": ("src/settings.py", "SETTINGS_FILE"),
    "FEATURES_FILE": ("src/settings.py", "FEATURES_FILE"),
    "USER_PREFS_FILE": ("routes/prefs_routes.py", "PREFS_FILE"),
    "PREFS_FILE": ("routes/prefs_routes.py", "PREFS_FILE"),
    "INTEGRATIONS_FILE": ("src/integrations.py", "DATA_FILE"),
    "AUTH_FILE": ("core/auth.py", "self.auth_path"),
}
GUARDED_BASENAMES: dict[str, tuple[str, str]] = {
    "settings.json": ("src/settings.py", "SETTINGS_FILE"),
    "features.json": ("src/settings.py", "FEATURES_FILE"),
    "user_prefs.json": ("routes/prefs_routes.py", "PREFS_FILE"),
    "integrations.json": ("src/integrations.py", "DATA_FILE"),
    "auth.json": ("core/auth.py", "self.auth_path"),
}

# Plain writes onto a guarded store that are known and filed rather than fixed,
# keyed (file, the store's constant) — so a NEW one fails, and an entry whose
# write is gone fails as a STORES entry does.
KNOWN_PLAIN_WRITES: dict[tuple[str, str], str] = {
    ("core/database.py", "USER_PREFS_FILE"): (
        "found by `B1008`'s widening and filed, not fixed (`w5-docs` B-NEW-1): the boot "
        "migration of a flat user_prefs.json to the per-user form writes it with "
        "`open(prefs_path, 'w')`; its read raises on a bad file, so it is not the "
        "`P3-16` shape, but it is not atomic"),
    ("setup.py", "AUTH_FILE"): (
        "found by `B1008`'s widening and filed with the one above: the installer writes "
        "the first admin with `open(auth_path, 'w')`, only when no auth.json exists — "
        "nothing to lose, but a crash mid-write leaves a file it then skips forever"),
}

_WRITE_MODES = set("wax+")

SKIP_PREFIXES = ("tests/", ".pantheon/")
SKIP_FILES = {"core/atomic_io.py"}


def _tracked_python() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [
        f for f in out.split()
        if not f.startswith(SKIP_PREFIXES) and f not in SKIP_FILES
    ]


def _sites() -> list[tuple[str, int, str, bool]]:
    """(file, line, first-arg source, passes preserve_unreadable)."""
    found = []
    for rel in _tracked_python():
        path = ROOT / rel
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name not in WRITERS or not node.args:
                continue
            guarded = any(kw.arg == "preserve_unreadable" for kw in node.keywords)
            found.append((rel, node.lineno, ast.unparse(node.args[0]), guarded))
    return found


def _aliases(body) -> dict[str, str]:
    """`name -> source` for each plain `name = <expr>` in *body* (not nested
    functions' — those are their own scope)."""
    out: dict[str, str] = {}
    for node in body:
        for sub in ast.walk(node):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and sub is not node:
                continue
            if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                    and isinstance(sub.targets[0], ast.Name)):
                out[sub.targets[0].id] = ast.unparse(sub.value)
    return out


def _resolve(text: str, *scopes: dict[str, str]) -> str:
    """*text* with a bare name followed through *scopes*, a few steps deep."""
    seen = set()
    while text not in seen:
        seen.add(text)
        for scope in scopes:
            if text in scope:
                text = scope[text]
                break
        else:
            break
    return text


def _guarded_store(text: str):
    """`(store key, the name it was found by)` when *text* names a guarded store."""
    import re

    for name, store in GUARDED_NAMES.items():
        if re.search(rf"\b{name}\b", text):
            return store, name
    for base, store in GUARDED_BASENAMES.items():
        if f"'{base}'" in text or f'"{base}"' in text:
            return store, base
    return None


def _plain_writes() -> list[tuple[str, int, str, tuple[str, str], str]]:
    """(file, line, how, store, the name it was found by) for each plain write
    onto a guarded store."""
    found = []
    for rel in _tracked_python():
        try:
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        module_aliases = _aliases([n for n in tree.body
                                   if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                         ast.ClassDef))])
        functions = [n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for fn in [tree, *functions]:
            local = _aliases(fn.body) if fn is not tree else {}
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                target = how = None
                if isinstance(f, ast.Name) and f.id == "open" and node.args:
                    mode = node.args[1] if len(node.args) > 1 else next(
                        (kw.value for kw in node.keywords if kw.arg == "mode"), None)
                    if (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                            and _WRITE_MODES & set(mode.value)):
                        target, how = node.args[0], f"open(…, {mode.value!r})"
                elif isinstance(f, ast.Attribute) and f.attr in ("write_text", "write_bytes"):
                    target, how = f.value, f".{f.attr}()"
                if target is None:
                    continue
                text = _resolve(ast.unparse(target), local, module_aliases)
                if isinstance(target, ast.Call) and target.args:
                    # `Path(x).write_text(…)`, `str(x)`: follow the argument too.
                    text += " " + _resolve(ast.unparse(target.args[0]), local, module_aliases)
                hit = _guarded_store(text)
                if hit:
                    found.append((rel, node.lineno, how, hit[0], hit[1]))
    # A function body is walked as itself and again inside the module walk;
    # one site is one write.
    return sorted(set(found))


def main() -> int:
    sites = _sites()
    listing = "--list" in sys.argv
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    counts: defaultdict[str, int] = defaultdict(int)

    for rel, line, target, guarded in sorted(sites):
        key = (rel, target)
        seen.add(key)
        entry = STORES.get(key)
        if entry is None:
            problems.append(
                f"{rel}:{line}: writes `{target}`, which nothing has classified. "
                "Decide whether losing this file matters and add it to STORES."
            )
            continue
        kind, why = entry
        counts[kind] += 1
        if kind == GUARDED and not guarded:
            problems.append(
                f"{rel}:{line}: `{target}` is {GUARDED} ({why}) and this write does "
                "not pass preserve_unreadable=True."
            )
        if kind != GUARDED and guarded:
            problems.append(
                f"{rel}:{line}: `{target}` is {kind} ({why}) and this write passes "
                "preserve_unreadable=True, which would refuse the overwrite that repairs it."
            )
        if listing:
            print(f"{kind:<12} {rel}:{line}  {target}")

    for key in sorted(set(STORES) - seen):
        problems.append(
            f"STORES has `{key[1]}` in {key[0]} and there is no write there any more — "
            "remove the entry so the map stays a description of the tree."
        )

    plain = _plain_writes()
    known_seen: set[tuple[str, str]] = set()
    for rel, line, how, store, by in plain:
        kind, why = STORES[store]
        if (rel, by) in KNOWN_PLAIN_WRITES:
            known_seen.add((rel, by))
            if listing:
                print(f"{'known-plain':<12} {rel}:{line}  {by}  {how}")
            continue
        problems.append(
            f"{rel}:{line}: writes `{by}` — the {kind} store `{store[1]}` in {store[0]} "
            f"({why}) — with a plain {how}: not atomic, no preserve_unreadable, and "
            f"around the store's own writer. Write it through {store[0]}."
        )
    for key in sorted(set(KNOWN_PLAIN_WRITES) - known_seen):
        problems.append(
            f"KNOWN_PLAIN_WRITES has `{key[1]}` in {key[0]} and there is no plain write "
            "there any more — remove the entry."
        )

    print(f"write sites {len(sites)}  ·  "
          f"guarded {counts[GUARDED]}  ·  strict-read {counts[STRICT_READ]}  ·  "
          f"rebuildable {counts[REBUILDABLE]}  ·  plain onto guarded {len(plain)} "
          f"(known {len(known_seen)})  ·  PROBLEMS {len(problems)}")
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
