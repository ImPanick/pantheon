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
    ("routes/contacts/contacts_routes.py", "str(SETTINGS_FILE)"): (
        GUARDED, "second door onto settings.json"),
    ("routes/email_helpers.py", "str(SETTINGS_FILE)"): (
        GUARDED, "third door onto settings.json, and it carries mail credentials"),
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

    print(f"write sites {len(sites)}  ·  "
          f"guarded {counts[GUARDED]}  ·  strict-read {counts[STRICT_READ]}  ·  "
          f"rebuildable {counts[REBUILDABLE]}  ·  PROBLEMS {len(problems)}")
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
