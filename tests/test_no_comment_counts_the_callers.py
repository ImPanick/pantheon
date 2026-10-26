# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1516` — no comment states how many callers something has.

`B891` found a caller count written into a comment that was wrong the day after
it was written, `B1503` cleared `markdown.js`'s; the rest of the tree still
carried them — *"seven call sites"* in `src/mcp_manager.py`, *"five call sites"*
in `src/memory.py`, *"six callers"* in `static/js/backStack.js` — numbers that
nothing re-measures and every new caller makes false (`Law 6`: count it, do not
carry it). Each now names its callers or drops the count.

A count in the past tense stays: *"`load_features()` had three callers"* is a
record of what was measured when a row was fixed, and a later caller does not
make it untrue. So the rule is: a count of two or more callers or call sites in
`src/`, `routes/`, `services/`, `core/`, `mcp_servers/` or `static/` reads as
history on its own line, or it is not there.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOTS = ("src", "routes", "services", "core", "mcp_servers", "integrations", "companion",
         "netagent", "workstation", "static", "app.py")
SUFFIXES = (".py", ".js", ".mjs")

COUNT = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[2-9]|[1-9][0-9]+)"
    r"\s+(?:other\s+)?(?:callers?|call[- ]sites?)\b", re.I)
# A line that says when: what was measured then is not a claim about now.
HISTORY = re.compile(r"\b(had|were|was|used to|asked|until|before)\b", re.I)


def _files():
    out = subprocess.run(["git", "ls-files", *ROOTS], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split()
    return [f for f in out if f.endswith(SUFFIXES) and not f.startswith("static/lib/")]


def _present_counts(text: str):
    for n, line in enumerate(text.splitlines(), 1):
        if COUNT.search(line) and not HISTORY.search(line):
            yield n, line.strip()


def test_no_comment_states_a_caller_count_in_the_present():
    found = []
    for rel in _files():
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        found += [f"{rel}:{n}  {line[:110]}" for n, line in _present_counts(text)]
    assert not found, (
        "a comment counts the callers of something, and nothing re-measures it:\n  "
        + "\n  ".join(found)
        + "\n\nName the callers, or drop the number (B1516).")


def test_the_rule_reads_a_count_and_lets_history_stand():
    """Not a tautology: the shapes this row removed are found, and the record
    of a measurement is not."""
    assert list(_present_counts("    because seven call sites want only the boolean."))
    assert list(_present_counts("  // Six callers rewrite the URL with `replaceState`"))
    assert list(_present_counts("    One predicate, 4 callers."))
    assert not list(_present_counts("nothing**: `load_features()` had three callers and"))
    assert not list(_present_counts("Until `fx7-search2` its only two call sites were"))
    assert not list(_present_counts("The one call site for the dependency"))
    assert len(_files()) > 500, "the scan looked at almost nothing"
