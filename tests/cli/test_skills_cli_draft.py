# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-14` — the door: `pantheon-skills draft "what I did"`.

`P8-00` binds every row in this phase to a person reaching the capability
unaided, and the Workshop's own button needs `static/js/skills.js`. This is the
half that works today, and it is driven here rather than described: the
subcommand is parsed off the real parser, `cmd_draft` is called with real
`args`, and the only things stubbed are the model call and the store.

The property that matters most is the last one. `draft` prints; `--save`
writes. A command that quietly added a skill to the library because you asked
it what a skill would look like is the failure `Law 15` is about.
"""
import sys
import types
from unittest.mock import MagicMock

import pytest

from tests.helpers.cli_loader import load_script

DRAFT = {
    "name": "restart-the-print-spooler",
    "description": "Clear a stuck print queue by restarting the spooler",
    "category": "system",
    "when_to_use": "When jobs pile up and nothing prints",
    "procedure": ["Stop the service", "Clear the queue", "Start it"],
    "pitfalls": [], "verification": [], "tags": ["printer"],
}


def _load_cli(monkeypatch):
    svc = types.ModuleType("services.memory.skills")
    svc.SkillsManager = MagicMock()
    monkeypatch.setitem(sys.modules, "services.memory.skills", svc)
    return load_script("pantheon-skills")


def _wire(monkeypatch, cli, *, draft=DRAFT, model=("http://e", "m", {})):
    """Stub the three things `cmd_draft` reaches outside itself."""
    async def fake_draft(*a, **k):
        return draft

    ex = types.ModuleType("services.memory.skill_extractor")
    ex.draft_skill_from_description = fake_draft
    monkeypatch.setitem(sys.modules, "services.memory.skill_extractor", ex)

    lint = types.ModuleType("services.memory.skill_lint")
    lint.lint_skill = lambda d, siblings: {"verdict": "clean", "findings": []}
    monkeypatch.setitem(sys.modules, "services.memory.skill_lint", lint)

    er = types.ModuleType("src.endpoint_resolver")
    er.resolve_endpoint = lambda *a, **k: model
    monkeypatch.setitem(sys.modules, "src.endpoint_resolver", er)

    mgr = MagicMock()
    mgr.load.return_value = []
    mgr.add_skill.return_value = {"name": "restart-the-print-spooler",
                                  "status": "draft"}
    monkeypatch.setattr(cli, "_manager", lambda: mgr)
    return mgr


def _args(cli, argv):
    return cli._build_parser().parse_args(argv)


def _out(capsys):
    import json
    return json.loads(capsys.readouterr().out)


def test_draft_is_a_subcommand_of_the_cli_a_person_already_has(monkeypatch):
    cli = _load_cli(monkeypatch)
    args = _args(cli, ["draft", "I cleared the stuck print queue"])
    assert args.func is cli.cmd_draft
    assert args.description == "I cleared the stuck print queue"
    assert args.save is False


def test_it_prints_the_draft_and_writes_nothing(monkeypatch, capsys):
    cli = _load_cli(monkeypatch)
    mgr = _wire(monkeypatch, cli)
    cli.cmd_draft(_args(cli, ["draft", "I cleared the stuck print queue"]))
    payload = _out(capsys)
    assert payload["saved"] is False
    assert payload["skill"]["name"] == "restart-the-print-spooler"
    assert payload["skill"]["when_to_use"] == "When jobs pile up and nothing prints"
    mgr.add_skill.assert_not_called()


def test_save_is_what_writes_it(monkeypatch, capsys):
    cli = _load_cli(monkeypatch)
    mgr = _wire(monkeypatch, cli)
    cli.cmd_draft(_args(cli, ["draft", "I cleared the queue", "--save"]))
    payload = _out(capsys)
    assert payload["saved"] is True
    mgr.add_skill.assert_called_once()
    kwargs = mgr.add_skill.call_args.kwargs
    # Every field the drafter filled in reaches the store — the whole point of
    # `P8-17`'s nine-field schema is lost if the writer passes four of them.
    assert kwargs["name"] == "restart-the-print-spooler"
    assert kwargs["category"] == "system"
    assert kwargs["when_to_use"] == "When jobs pile up and nothing prints"
    assert kwargs["procedure"] == ["Stop the service", "Clear the queue", "Start it"]
    assert kwargs["tags"] == ["printer"]
    # `source="user"`: a person asked for this one, so it is exempt from
    # dedup-at-creation exactly as `POST /api/skills/add` is.
    assert kwargs["source"] == "user"


def test_it_shows_the_same_lint_the_workshop_form_shows(monkeypatch, capsys):
    cli = _load_cli(monkeypatch)
    _wire(monkeypatch, cli)
    cli.cmd_draft(_args(cli, ["draft", "I cleared the queue"]))
    assert _out(capsys)["lint"]["verdict"] == "clean"


def test_with_no_model_configured_it_says_what_to_do(monkeypatch, capsys):
    """`Law 15`. The failure a fresh install actually hits, and the message has
    to name the setting rather than the exception."""
    cli = _load_cli(monkeypatch)
    _wire(monkeypatch, cli, model=(None, None, None))
    with pytest.raises(SystemExit) as e:
        cli.cmd_draft(_args(cli, ["draft", "I cleared the queue"]))
    assert e.value.code == 2
    err = capsys.readouterr().err.lower()
    assert "model" in err and "settings" in err


def test_when_the_model_declines_it_says_what_is_missing(monkeypatch, capsys):
    cli = _load_cli(monkeypatch)
    _wire(monkeypatch, cli, draft=None)
    with pytest.raises(SystemExit):
        cli.cmd_draft(_args(cli, ["draft", "printers are annoying"]))
    err = capsys.readouterr().err.lower()
    assert "procedure" in err


def test_an_empty_description_is_refused_before_any_model_is_asked(monkeypatch):
    cli = _load_cli(monkeypatch)
    _wire(monkeypatch, cli)
    with pytest.raises(SystemExit):
        cli.cmd_draft(_args(cli, ["draft", "   "]))


def test_the_help_text_tells_a_first_timer_what_this_is_for(monkeypatch):
    """`P8-00`. `--help` is the only documentation a CLI has, so the thing a
    person needs to know — say it in your own words — has to be in it."""
    cli = _load_cli(monkeypatch)
    text = cli._build_parser().format_help()
    assert "draft" in text
    sub = [a for a in cli._build_parser()._actions
           if getattr(a, "choices", None) and "draft" in a.choices][0]
    assert "own words" in sub.choices["draft"].format_help()
    assert "own words" in cli.__doc__
