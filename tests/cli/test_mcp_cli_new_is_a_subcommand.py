# SPDX-License-Identifier: AGPL-3.0-or-later
"""`pantheon-mcp new` — `P8-47`'s scaffold, folded into the MCP CLI.

`P8-47` shipped the generator as `scripts/pantheon-mcp-new`, a sibling of the
MCP CLI rather than a subcommand of it, and its row recorded the fold as
something the merge still needed (`Law 14`: one MCP CLI, one door per act). It
was never filed as a `B` row; `P8-45`'s handoff names it.

The subcommand takes the scaffold's own parser as its parent, so the flags are
the scaffold's by construction, and it runs the same body
(`mcp_scaffold.run_parsed`) that `pantheon-mcp-new` runs. The old script stays
(`Law 1`; `tests/cli/test_pantheon_dispatcher_listing.py` pins it).

Driven through the CLI's real `run` (`Law 20`). Nothing here starts a server:
`--no-self-test` writes the files without spawning them.
"""
from __future__ import annotations

import json

import pytest

from tests.helpers.cli_loader import load_script


def _cli():
    return load_script("pantheon-mcp")


def _json(capsys):
    return json.loads(capsys.readouterr().out)


def test_new_lists_what_is_on_the_volume_exactly_as_the_old_door_does(tmp_path, capsys):
    from src.mcp_scaffold import main as scaffold_main

    cli = _cli()
    assert cli.run(cli._build_parser(), ["new", "--list", "--data-dir", str(tmp_path)]) == 0
    through_new = _json(capsys)
    assert scaffold_main(["--list", "--data-dir", str(tmp_path)]) == 0
    through_old = _json(capsys)
    assert through_new == through_old
    assert through_new["count"] == 0


def test_new_writes_a_server_the_old_door_then_finds(tmp_path, capsys):
    from src.mcp_scaffold import main as scaffold_main

    cli = _cli()
    code = cli.run(cli._build_parser(), [
        "new", "weather", "--tool", "get_forecast", "--no-self-test",
        "--data-dir", str(tmp_path)])
    assert code == 0
    made = _json(capsys)
    assert made["name"] == "weather"
    assert (tmp_path / "mcp_servers" / "weather" / "server.py").is_file()

    assert scaffold_main(["--list", "--data-dir", str(tmp_path)]) == 0
    assert [s["name"] for s in _json(capsys)["servers"]] == ["weather"]


def test_a_refusal_is_the_scaffolds_own_and_exits_non_zero(tmp_path, capsys):
    """The scaffold never overwrites, so a second `new` with the same name is
    refused — through this door with the same exit code and the same words."""
    cli = _cli()
    argv = ["new", "weather", "--no-self-test", "--data-dir", str(tmp_path)]
    assert cli.run(cli._build_parser(), argv) == 0
    capsys.readouterr()
    written = (tmp_path / "mcp_servers" / "weather" / "server.py").read_bytes()
    with pytest.raises(SystemExit) as caught:
        cli.run(cli._build_parser(), argv)
    assert caught.value.code == 1
    assert "error:" in capsys.readouterr().err
    assert (tmp_path / "mcp_servers" / "weather" / "server.py").read_bytes() == written


def test_no_name_prints_the_subcommands_own_usage(capsys):
    cli = _cli()
    with pytest.raises(SystemExit) as caught:
        cli.run(cli._build_parser(), ["new"])
    assert caught.value.code == 2
    assert "usage: pantheon-mcp new" in capsys.readouterr().out


def test_help_names_the_new_door(capsys):
    cli = _cli()
    with pytest.raises(SystemExit) as caught:
        cli.run(cli._build_parser(), ["new", "--help"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "usage: pantheon-mcp new" in out
    assert "pantheon-mcp new weather --tool get_forecast" in out
    assert "pantheon-mcp-new" not in out


def test_the_flags_are_the_scaffolds_by_construction():
    """A flag added to the scaffold reaches `pantheon-mcp new` with no edit
    here, because the subcommand's parent IS the scaffold's parser."""
    from src.mcp_scaffold import _build_parser as scaffold_parser

    cli = _cli()
    parser = cli._build_parser()
    new = next(a for a in parser._subparsers._group_actions if a.dest == "cmd").choices["new"]
    assert set(new._option_string_actions) == set(scaffold_parser()._option_string_actions)
