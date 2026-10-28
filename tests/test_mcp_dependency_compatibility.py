# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression coverage for the built-in MCP servers' SDK compatibility line.

A major version of the MCP SDK is a breaking rewrite, so the pin stays on one
major line and moves to the next only with the built-in servers and the client.
`B621` was that move, 1.x -> 2.x: the servers register through
`src/mcp_tool_server.py` on 2.x's constructor handlers, and the ceiling here
moved with the pin, from `<2` to `<3`.

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
import re
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version

_REPO = Path(__file__).resolve().parents[1]
REQUIREMENTS = _REPO / "requirements.txt"
DEPENDABOT = _REPO / ".github" / "dependabot.yml"


def _mcp_specifier() -> str:
    spec = importlib.util.spec_from_file_location(
        "mcp_compat_pins", _REPO / ".pantheon" / "check-pins.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    found = [s for _, _, name, s in checker.parse_requirements(REQUIREMENTS)
             if name.lower() == "mcp"]
    assert len(found) == 1, f"expected one `mcp` requirement, found {found}"
    return found[0]


def test_mcp_requirement_excludes_breaking_v3_sdk():
    specifier = SpecifierSet(_mcp_specifier())
    # The 2.x line is what the built-in servers are written against (`B621`).
    assert any(
        Version(s.version).major == 2 for s in specifier if s.operator in ("==", "===")
    ), f"`mcp{specifier}` does not select the 2.x SDK line"
    # Not back to 1.x, whose decorators the servers no longer use — and no 3.x,
    # whether by a pin or by a range that leaves the door open.
    for rejected in ("1.30.0", "3.0.0", "3.1.0", "4.0.0"):
        assert not specifier.contains(Version(rejected)), (
            f"`mcp{specifier}` admits {rejected} — the built-in servers are written "
            f"against the 2.x low-level Server, and a major is a migration")


def test_the_reason_for_the_ceiling_is_still_written_down():
    """`Law 1`. The pin is enforceable; the paragraph above it is why anyone
    would keep it. A Dependabot pull request moving `mcp` to a new major is a migration,
    not a bump, and that sentence is the only thing that says so."""
    text = REQUIREMENTS.read_text(encoding="utf-8")
    # `B621`: the sentence moved with the pin — it is about any major now.
    assert "A major version of it is a migration, not a bump" in text
    assert "moved together" in text


def test_dependabot_does_not_group_an_mcp_major_with_safe_bumps():
    """The exact pin protects installs; the bot also needs to respect it."""
    text = DEPENDABOT.read_text(encoding="utf-8")
    pip_block = re.search(
        r"(?ms)^  - package-ecosystem: pip\n(.*?)(?=^  - package-ecosystem:|\Z)", text)
    assert pip_block, "Dependabot no longer has a pip entry"
    assert re.search(
        r"(?m)^    ignore:\n      - dependency-name: [\"']?mcp[\"']?\n"
        r"        update-types: \[[\"']version-update:semver-major[\"']\]$",
        pip_block.group(1)), "an MCP major must wait for a coordinated server/client migration"
