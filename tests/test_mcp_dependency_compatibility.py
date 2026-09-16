# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression coverage for the built-in MCP servers' SDK compatibility line.

The built-in servers use the v1 low-level `Server` decorator API. MCP SDK v2 is
a breaking rewrite, so a fresh install must land on the maintained v1 line until
the servers are migrated together.

This used to assert the literal string `mcp<2` appeared in `requirements.txt`.
`B320` pinned every dependency to an exact version, which is a strictly tighter
constraint — `mcp==1.30.0` cannot resolve to a v2 — but it deleted the string,
and a test that reads a string rather than the rule it stands for fails on a
change that makes its own subject safer.

So the rule is now read the way pip reads it: find the `mcp` requirement, and
check the version it resolves to. A pin to any 2.x, and a range that would
*admit* a 2.x, both fail. The parser is `.pantheon/check-pins.py`'s, rather than
a second one written here (`Law 14`).
"""

import importlib.util
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version

_REPO = Path(__file__).resolve().parents[1]
REQUIREMENTS = _REPO / "requirements.txt"


def _mcp_specifier() -> str:
    spec = importlib.util.spec_from_file_location(
        "mcp_compat_pins", _REPO / ".pantheon" / "check-pins.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    found = [s for _, _, name, s in checker.parse_requirements(REQUIREMENTS)
             if name.lower() == "mcp"]
    assert len(found) == 1, f"expected one `mcp` requirement, found {found}"
    return found[0]


def test_mcp_requirement_excludes_breaking_v2_sdk():
    specifier = SpecifierSet(_mcp_specifier())
    # The v1 line is what the built-in servers are written against.
    assert specifier.contains(Version("1.30.0")) or any(
        Version(s.version).major == 1 for s in specifier if s.operator in ("==", "===")
    ), f"`mcp{specifier}` does not select the v1 SDK line"
    # And no v2, whether by a pin or by a range that leaves the door open.
    for rejected in ("2.0.0", "2.1.0", "3.0.0"):
        assert not specifier.contains(Version(rejected)), (
            f"`mcp{specifier}` admits {rejected} — the built-in servers use the v1 "
            f"low-level Server decorator API and have not been migrated")


def test_the_reason_for_the_ceiling_is_still_written_down():
    """`Law 1`. The pin is enforceable; the paragraph above it is why anyone
    would keep it. A Dependabot pull request moving `mcp` to 2.x is a migration,
    not a bump, and that sentence is the only thing that says so."""
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert "MCP SDK v2 is a" in text
    assert "servers are migrated together" in text
