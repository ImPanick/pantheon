# SPDX-License-Identifier: AGPL-3.0-or-later
"""`pantheon` with no arguments prints one name per row — `B881`.

`scripts/pantheon:66` used to strip the leading `pantheon-<name> — ` noise
with `re.sub(r"^pantheon-\w+\s*—\s*", ...)`. `\w` excludes `-`, so the first
hyphenated subcommand this repository shipped — `mcp-new` — printed as
`mcp-new    pantheon-mcp-new — make a working MCP server…`, its name twice,
while every other row read `mcp        shell wrapper for MCP…`.

`scripts/pantheon-mcp-new` was also tracked at mode 100644, so
`_list_subcommands` dropped it and `pantheon mcp-new` answered
`unknown subcommand 'mcp-new'`.

These drive the dispatcher (`Law 20`); nothing here reads the regex.
"""
import os
import re
from pathlib import Path

from tests.helpers.cli_loader import load_script

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _listing(capsys):
    """Drive the real entrypoint and return its rows as (name, desc)."""
    cli = load_script("pantheon")
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    rows = []
    started = False
    for line in out.splitlines():
        if line.startswith("Available subcommands:"):
            started = True
            continue
        if not started:
            continue
        if not line.startswith("  ") or not line.strip():
            continue
        name, _, desc = line.strip().partition(" ")
        rows.append((name, desc.strip()))
    assert rows, out
    return rows


def test_no_row_repeats_its_own_subcommand_name(capsys):
    """Every description is prose, not `pantheon-<name> — prose`."""
    offenders = [(n, d) for n, d in _listing(capsys) if d.startswith("pantheon-")]
    assert offenders == [], f"rows still printing their own name: {offenders}"


def test_the_hyphenated_subcommand_is_listed_and_dispatchable(capsys):
    """`mcp-new` is in the table and `pantheon mcp-new` resolves to a file."""
    rows = dict(_listing(capsys))
    assert "mcp-new" in rows, f"mcp-new missing from listing: {sorted(rows)}"
    assert rows["mcp-new"] == "make a working MCP server and say how to register it."

    cli = load_script("pantheon")
    assert cli._is_runnable_subcommand(SCRIPTS / "pantheon-mcp-new") is True


def test_every_shipped_subcommand_is_executable():
    """A `pantheon-*` that is not `chmod +x` is invisible to the dispatcher."""
    cli = load_script("pantheon")
    listed = {p.name for p in cli._list_subcommands()}
    on_disk = {
        p.name
        for p in SCRIPTS.iterdir()
        if p.is_file()
        and p.name.startswith("pantheon-")
        and p.suffix not in (".sh", ".bak", ".pyc")
    }
    assert on_disk - listed == set(), (
        f"present but not executable, so unreachable: {sorted(on_disk - listed)}"
    )


def test_strip_handles_any_hyphen_depth(tmp_path):
    """Synthetic: the strip is not tied to the names that happen to ship."""
    cli = load_script("pantheon")
    for name in ("pantheon-a", "pantheon-a-b", "pantheon-a-b-c"):
        p = tmp_path / name
        p.write_text(f'#!/usr/bin/env python3\n"""{name} — does a thing.\n\nmore\n"""\n')
        assert cli._short_help(p) == "does a thing."


def test_strip_leaves_a_lookalike_name_alone(tmp_path):
    """The strip is anchored on the file's own name, so a different one stays."""
    cli = load_script("pantheon")
    p = tmp_path / "pantheon-mcp"
    p.write_text('#!/usr/bin/env python3\n"""pantheon-mcp-new — wrong name here.\n"""\n')
    assert cli._short_help(p) == "pantheon-mcp-new — wrong name here."


def test_dispatch_rejects_an_unknown_hyphenated_name(capsys):
    """The unknown-subcommand path still answers, hyphen or not."""
    cli = load_script("pantheon")
    assert cli.main(["mcp-nope"]) == 1
    assert "unknown subcommand 'mcp-nope'" in capsys.readouterr().err
