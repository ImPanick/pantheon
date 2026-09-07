#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fork's old short name, in code, with every survivor named.

`P0-31`. `P0-04` renamed 113 browser storage keys and reported *"no `ody-` /
`ody.` keys remain in static/"*, which was true and was not the whole question.
The abbreviated prefix survived in four other shapes, and each one cost
something different:

* **`ody_` on every API token this product minted** — the one string a person
  copies out of Pantheon and pastes into another machine. The row scoped to
  find the residue could not see it: its own regex was `(?i:ody)[-.]`, and the
  separator here is `_`.
* **`ody-agent-` on the tmux session behind the agent's shell** — a name that
  is how running state is *found*, so a bare rename abandons a live shell and
  leaks the process.
* **`html.ody-sidebar-off` in sixteen CSS selectors** whose writers had already
  been renamed, which killed the pre-paint sidebar guard (`B26`).
* **`ody-math-pending` and `ody-session-cost` in test fixtures**, which is how
  five suite failures stood for a fortnight looking like flake.

None of that was a missing rule. It was that nothing ever looked. This is the
looking, and it runs in CI so the next rename cannot half-finish quietly.

**Code, not prose.** A comment or a docstring that explains what the old name
was is worth keeping — deleting the history is how the next person rediscovers
the question from scratch (`Law 1`). So Python is read through `ast` and only
non-docstring string literals and identifiers are considered; JS, CSS and HTML
have their comments stripped first.

**Shipped examples are checked elsewhere and on purpose.** `.env.example`,
`docs/setup.md` and the two integration READMEs print a token prefix to a
first-time reader, and `tests/test_token_prefix_migration.py` fails if any of
them shows the old one — or loses its example rather than updating it, which is
the other way to make a naive grep pass.

Every hit that remains is in `ALLOWED` with a reason. That list is the row's
`Verify:` line, in a form that cannot go stale silently.
"""
import ast
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The old short name, with every separator it was ever spelled with. `_` is the
# one the row's original regex was missing, and it is where the token prefix
# and the tmux session name both hid.
PATTERN = re.compile(r"(?<![A-Za-z0-9])(?i:ody)[-._]")

# Extensions this reads. Everything else is prose, data, or vendored.
CODE_SUFFIXES = {".py", ".js", ".mjs", ".css", ".html", ".sh"}

SKIP_PREFIXES = (
    ".pantheon/",      # this tracker's own text, and the design mockup
    "static/lib/",     # vendored third-party builds
    "licenses/",       # other people's licence text
    "library/",        # bundled skills — other people's words
)

# path -> why the old name is still there. A migration path that reads the old
# name, or a test that asserts its absence. Nothing else belongs here.
ALLOWED = {
    "core/api_tokens.py":
        "`ACCEPTED_TOKEN_PREFIXES` still honours `ody_`. Every token minted "
        "before 2026-09-07 carries it — in an .env, in a paired phone, in a "
        "scrape config — and dropping it revokes all of them at once.",
    "src/agent_tools/subprocess_tools.py":
        "`LEGACY_TMUX_SESSION_PREFIXES`. A tmux session still alive under the "
        "old name is adopted rather than orphaned; without it the shell keeps "
        "running and the user simply loses it.",
    "tests/test_token_prefix_migration.py":
        "The migration's own tests. `LEGACY_PREFIX` is the subject.",
    "tests/test_tmux_session_name_adoption.py":
        "Same, for the shell: the adoption tests name the old prefix because "
        "that is what they are about.",
    "tests/test_api_token_routes.py":
        "Stored `token_prefix` values kept at the old spelling on purpose — "
        "they are what a pre-migration row looks like, and sweeping them would "
        "stop exercising the case the migration exists for.",
    "tests/test_root_class_wiring.py":
        "Asserts the old spelling is *absent* from the stylesheets (`B26`).",
    "scripts/pantheon-init.sh":
        "The rename tool itself. Its progress line names both spellings "
        "because naming both is what it does.",
}


def _tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    for rel in out.splitlines():
        if rel.startswith(SKIP_PREFIXES):
            continue
        if pathlib.Path(rel).suffix in CODE_SUFFIXES:
            yield rel


def _python_code(text):
    """Identifiers and non-docstring string literals. Comments and docstrings
    never reach the caller, which is the point."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text  # unparseable: fall back to the whole file rather than pass
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    parts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                parts.append(node.value)
        elif isinstance(node, ast.Name):
            parts.append(node.id)
        elif isinstance(node, ast.Attribute):
            parts.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            parts.append(node.name)
        elif isinstance(node, ast.arg):
            parts.append(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            parts.append(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            parts.extend(a.name for a in node.names)
            parts.extend(a.asname for a in node.names if a.asname)
            if isinstance(node, ast.ImportFrom) and node.module:
                parts.append(node.module)
    return "\n".join(parts)


def _strip_c_comments(text):
    return re.sub(r"(?m)//.*$", " ", re.sub(r"/\*.*?\*/", " ", text, flags=re.S))


def _code_text(rel, text):
    suffix = pathlib.Path(rel).suffix
    if suffix == ".py":
        return _python_code(text)
    if suffix in {".js", ".mjs"}:
        return _strip_c_comments(text)
    if suffix == ".css":
        return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    if suffix == ".html":
        # HTML comments first, then the CSS and JS comments inside <style> and
        # <script>, which is where B26's dead selectors lived.
        return _strip_c_comments(re.sub(r"<!--.*?-->", " ", text, flags=re.S))
    if suffix == ".sh":
        return re.sub(r"(?m)#.*$", " ", text)
    return text


def main():
    offenders, allowed_hits = {}, {}
    for rel in _tracked():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits = PATTERN.findall(_code_text(rel, text))
        if not hits:
            continue
        (allowed_hits if rel in ALLOWED else offenders)[rel] = len(hits)

    stale = sorted(set(ALLOWED) - set(allowed_hits))
    if offenders:
        print("The fork's old short name survives in code:\n")
        for rel, n in sorted(offenders.items()):
            print(f"  {n:>3}  {rel}")
        print(
            "\nRename it, or — if it is a migration path that has to read the "
            "old name, or a test asserting its absence — add the file to "
            "ALLOWED in .pantheon/check-fork-names.py with the reason."
        )
        return 1
    if stale:
        print("ALLOWED names files that no longer carry the old name:\n")
        for rel in stale:
            print(f"  {rel}")
        print("\nRemove the entry; an excuse for something that is gone is noise.")
        return 1
    total = sum(allowed_hits.values())
    print(f"fork names OK — {total} deliberate hits across "
          f"{len(allowed_hits)} files, each named")
    for rel, n in sorted(allowed_hits.items()):
        print(f"  {n:>3}  {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
