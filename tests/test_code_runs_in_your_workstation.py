# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-18` — a Code step runs in the person's own workstation account.

`workflow_effects.run_code_step` goes `workstation_for` → `sync_config` →
`client.exec(source, shell=language, stdin=json)` (§ 0.5 of the design: not
`run_in_workstation`, whose `python` handler takes its content as the script
and has no stdin). The author's source is the command, byte for byte; what the
step is handed arrives as JSON on stdin and is never spliced into the source;
stdout that parses as JSON is the step's `data`; a non-zero exit leaves by the
error port with the tail of stderr. With the workstation off, unconfigured or
not the person's to use, the step says the sentence the palette greys it with.

Against the real daemon (`tests/helpers/workstation_daemon.py` runs
`workstation/agentd.py` on a free port), with the real `WorkstationClient`
spied on — the spy calls through — so "the command is the source" is read off
the wire call, not assumed (`Law 20`).
"""
import asyncio
import json
from typing import Any, Dict

import pytest

from src.workflow_effects import run_code_step
from src.workstation_access import (NOT_PERMITTED_SENTENCE, OFF_SENTENCE, UNCONFIGURED_SENTENCE,
                                   account_of)
from src.workstation_client import WorkstationClient
from tests.helpers.workstation_daemon import running_workstation

_USERS = {
    "ann": {"admin": False, "privs": {"can_use_workstation": True}},
    "bob": {"admin": False, "privs": {"can_use_workstation": False}},
}

TOTAL = """import json, sys
prices = json.load(sys.stdin)["prices"]
print(json.dumps({"total": round(sum(prices), 2)}))
"""


class _Auth:
    is_configured = True

    def is_admin(self, username):
        return bool(_USERS.get(username, {}).get("admin"))

    def get_privileges(self, username):
        return dict(_USERS.get(username, {}).get("privs", {}))


@pytest.fixture
def station(tmp_path, monkeypatch):
    import core.auth
    import src.auth_helpers
    import src.settings as S
    from workstation import protocol as P

    monkeypatch.setattr(src.auth_helpers, "_auth_disabled", lambda: False)
    monkeypatch.setattr(core.auth, "AuthManager", _Auth)
    monkeypatch.delenv(P.URL_ENV, raising=False)
    monkeypatch.delenv(P.TOKEN_ENV, raising=False)
    values: Dict[str, Any] = {}
    real = S.get_setting
    monkeypatch.setattr(S, "get_setting",
                        lambda key, default=None: values[key] if key in values else real(key, default))

    calls = []
    real_exec, real_config = WorkstationClient.exec, WorkstationClient.config

    async def exec_spy(self, account, command, **kw):
        calls.append(("exec", account, command, kw))
        return await real_exec(self, account, command, **kw)

    async def config_spy(self, **settings):
        calls.append(("config", settings))
        return await real_config(self, **settings)

    monkeypatch.setattr(WorkstationClient, "exec", exec_spy)
    monkeypatch.setattr(WorkstationClient, "config", config_spy)
    with running_workstation(tmp_path, sudo=True) as ws:
        values.update({"workstation_enabled": True, "workstation_url": ws.url,
                       "workstation_token": ws.token, "workstation_sudo": False})
        yield type("Station", (), {"ws": ws, "settings": values, "calls": calls})


def _node(source, language="python", **config):
    return {"id": "total", "kind": "code", "label": "Total the prices",
            "config": {"language": language, "source": source, **config}}


def _run(node, input_obj, owner="ann", timeout=None):
    return asyncio.run(run_code_step(node, input_obj, owner=owner, timeout=timeout))


def _execs(station):
    return [c for c in station.calls if c[0] == "exec"]


def test_four_lines_total_a_list_of_prices(station):
    out = _run(_node(TOTAL), {"prices": [4.5, 3.25, 2.25, 2.5]})
    assert out.status == "success", out
    assert out.data == {"total": 12.5}
    assert out.text.strip() == '{"total": 12.5}'


def test_the_source_is_the_command_and_the_input_only_rides_stdin(station):
    hostile = {"note": '"; rm -rf ~; echo "', "ref": "{{ steps.secret.data.x }}", "n": [1, 2]}
    source = "cat"
    out = _run(_node(source, language="bash"), hostile)
    assert out.status == "success", out
    assert out.data == hostile                      # it came back exactly as it went in
    (_kind, account, command, kw), = _execs(station)
    assert command == source                        # byte for byte, nothing spliced in
    assert kw["shell"] == "bash"
    assert json.loads(kw["stdin"]) == hostile
    assert account == account_of("ann")             # the person's own account


def test_the_admins_settings_reach_the_daemon_before_the_command(station):
    _run(_node(TOTAL), {"prices": [1]})
    kinds = [c[0] for c in station.calls]
    assert kinds.index("config") < kinds.index("exec")
    assert ("config", {"sudo": False}) in station.calls


def test_output_that_is_not_json_is_text(station):
    out = _run(_node("print('hello')"), {})
    assert out.status == "success" and out.data is None and out.text == "hello\n"


def test_a_failing_script_leaves_by_the_error_port_with_what_it_said(station):
    out = _run(_node("import sys\nprint('half way')\nraise ValueError('price 3 is not a number')"),
               {"prices": [1, 2, "x"]})
    assert out.status == "error"
    assert out.text.startswith("It stopped with exit code 1: ")
    assert "ValueError: price 3 is not a number" in out.text


def test_a_script_that_runs_too_long_is_stopped(station):
    out = _run(_node("import time\ntime.sleep(10)"), {}, timeout=1)
    assert out.status == "error"
    assert out.text == "It ran longer than 1 seconds and was stopped."


def test_the_workstation_off_unconfigured_or_not_theirs_is_said(station):
    station.settings["workstation_enabled"] = False
    assert _run(_node(TOTAL), {"prices": [1]}).text == OFF_SENTENCE
    station.settings.update({"workstation_enabled": True, "workstation_url": ""})
    assert _run(_node(TOTAL), {"prices": [1]}).text == UNCONFIGURED_SENTENCE
    station.settings["workstation_url"] = station.ws.url
    out = _run(_node(TOTAL), {"prices": [1]}, owner="bob")
    assert out.status == "error" and out.text == NOT_PERMITTED_SENTENCE
    assert _execs(station) == []


@pytest.mark.parametrize("node,why", [
    (_node(TOTAL, language="ruby"), "Code runs as bash or python; this step says 'ruby'."),
    (_node("   "), "This step has no code to run."),
])
def test_a_step_that_cannot_run_says_why_and_runs_nothing(station, node, why):
    out = _run(node, {})
    assert out.status == "error" and out.text == why
    assert _execs(station) == []


def test_an_input_that_is_not_json_is_refused(station):
    out = _run(_node(TOTAL), {"prices": {1, 2}})
    assert out.status == "error" and out.text.startswith("What this step was handed could not")
    assert _execs(station) == []
